import pytest

from discjockey import fallback as fb
from discjockey.fallback import FallbackSource, entry_to_candidate, free_download
from discjockey.models import SourceTrack

T = SourceTrack("t1", "Gimme Gimme", ("Vatoz Locoz",), "Album", None, 156000, "DECE72605755")


def test_entry_to_candidate():
    c = entry_to_candidate("youtube", {"id": "abc", "url": "https://www.youtube.com/watch?v=abc",
                                       "title": "Vatoz Locoz - Gimme Gimme", "duration": 156,
                                       "channel": "Vatoz Locoz", "uploader": "Vatoz Locoz"})
    assert (c.source, c.id, c.duration_s, c.url) == ("youtube", "abc", 156.0, "https://www.youtube.com/watch?v=abc")
    assert "Vatoz Locoz" in c.artist


def test_entry_without_id_is_ignored():
    assert entry_to_candidate("youtube", {"title": "x"}) is None


def test_queries_order_with_isrc():
    q = FallbackSource().queries(T)
    assert [s for s, _, _ in q] == ["youtube_music", "youtube_music", "soundcloud", "youtube"]
    assert q[0][1].endswith("DECE72605755#songs")
    assert q[2][1] == "scsearch5:Vatoz Locoz Gimme Gimme"
    assert q[3][1] == "ytsearch5:Vatoz Locoz - Gimme Gimme"


def test_queries_without_isrc():
    t = SourceTrack("t1", "Gimme Gimme", ("Vatoz Locoz",), "Album", None, 156000, None)
    assert [s for s, _, _ in FallbackSource().queries(t)] == ["youtube_music", "soundcloud", "youtube"]


class FakeSource(FallbackSource):
    def __init__(self, pages, full=None, fail=(), check=lambda: None):
        super().__init__(check=check)
        self.pages, self.full, self.fail, self.calls = pages, full or {}, fail, []

    def _extract(self, url, flat):
        self.calls.append((url, flat))
        if any(f in url for f in self.fail):
            raise RuntimeError("HTTP Error 403: Forbidden\nmore")
        if not flat:
            return self.full[url]
        key = url.split("?")[0] if url.startswith("http") else url.split(":")[0]
        return self.pages.get(key, {})


def test_search_dedupes_resolves_missing_duration_and_collects_errors():
    entry = {"id": "a", "url": "https://yt/a", "title": "Gimme Gimme", "duration": 156}
    sc = {"id": "s", "url": "https://sc/s", "title": "Gimme Gimme"}  # no duration in flat results
    src = FakeSource(
        pages={"https://music.youtube.com/search": {"entries": [entry]},
               "scsearch5": {"entries": [sc]},
               "ytsearch5": {"entries": [entry]}},
        full={"https://sc/s": {**sc, "duration": 157, "webpage_url": "https://sc/s"}},
    )
    cands, errors = src.search(T)
    assert [c.id for c in cands] == ["a", "s"]
    assert cands[1].duration_s == 157.0
    assert errors == []


def test_search_reports_errors_per_source():
    src = FakeSource(pages={}, fail=("scsearch5",))
    cands, errors = src.search(T)
    assert cands == []
    assert errors == ["SoundCloud search failed: HTTP Error 403: Forbidden"]


def test_yt_dlp_output_becomes_debug_events():
    events = []
    src = FallbackSource(emit=events.append)
    src.opts["logger"].error("ERROR: [youtube] abc: Video unavailable")
    assert events[-1].level == "debug" and "Video unavailable" in events[-1].text


def test_search_queries_are_reported_for_verbose_mode():
    events = []

    class Quiet(FallbackSource):
        def _extract(self, url, flat):
            return {}

    Quiet(emit=events.append).search(T)
    assert sum("search:" in e.text for e in events) == 4


SC_NO_DURATION = {"id": "s", "url": "https://sc/s", "title": "Gimme Gimme"}


def test_lookup_errors_are_reported_not_dropped():
    # a network drop while looking up a result's length must not make the track "not found" (7-day wait)
    src = FakeSource(pages={"scsearch5": {"entries": [SC_NO_DURATION]}}, fail=("https://sc/s",))
    cands, errors = src.search(T)
    assert [c.id for c in cands] == ["s"] and cands[0].duration_s is None
    assert errors == ["SoundCloud lookup of https://sc/s failed: HTTP Error 403: Forbidden"]


class Stop(BaseException):
    """Stands in for events.Cancelled."""


def test_stop_before_the_fallback_searches_go_out():
    def check():
        raise Stop()

    src = FakeSource(pages={}, check=check)
    with pytest.raises(Stop):
        src.search(T)
    assert src.calls == []  # nothing was sent


def test_stop_before_a_lookup():
    src = FakeSource(pages={"scsearch5": {"entries": [SC_NO_DURATION]}},
                     full={"https://sc/s": {**SC_NO_DURATION, "duration": 157}})

    def check():
        if src.calls:  # the searches are out: the next check comes before the lookups
            raise Stop()

    src.check = check
    with pytest.raises(Stop):
        src.search(T)
    assert ("https://sc/s", False) not in src.calls


def test_searches_run_side_by_side_and_keep_their_order():
    import threading
    import time
    barrier = threading.Barrier(4, timeout=5)  # only passes if all four searches are running at once

    class Slow(FakeSource):
        def _extract(self, url, flat):
            if flat:
                barrier.wait()
                time.sleep(0.05 if "scsearch5" in url else 0)
            return super()._extract(url, flat)

    yt = {"id": "y", "url": "https://yt/y", "title": "Gimme Gimme", "duration": 156}
    sc = {"id": "s", "url": "https://sc/s", "title": "Gimme Gimme", "duration": 157}
    src = Slow(pages={"scsearch5": {"entries": [sc]}, "ytsearch5": {"entries": [yt]}})
    cands, errors = src.search(T)
    assert [c.id for c in cands] == ["s", "y"] and errors == []  # SoundCloud before YouTube, as in queries()


def test_a_drm_protected_upload_is_left_out_of_the_search():
    class Drm(FakeSource):
        def _extract(self, url, flat):
            if not flat:
                raise RuntimeError("ERROR: [soundcloud] 2389424355: This video is DRM protected")
            return super()._extract(url, flat)

    cands, errors = Drm(pages={"scsearch5": {"entries": [SC_NO_DURATION]}}).search(T)
    assert cands == [] and errors == []


def test_a_drm_protected_download_raises_protected(tmp_path, monkeypatch):
    from discjockey import fallback
    from discjockey.models import Candidate, Protected

    class Ydl:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def extract_info(self, url, download):
            raise fallback.yt_dlp.utils.DownloadError("ERROR: [soundcloud] 1: This video is DRM protected")

    monkeypatch.setattr(fallback.yt_dlp, "YoutubeDL", Ydl)
    with pytest.raises(Protected) as err:
        FallbackSource().download(Candidate("soundcloud", "1", "t", "a", 1.0, url="https://sc/1"), tmp_path)
    assert err.value.permanent  # the sync never tries this version again for the track


def test_lookup_reads_one_link():
    src = FakeSource(pages={}, full={"https://youtu.be/x": {"id": "x", "webpage_url": "https://www.youtube.com/watch?v=x",
                                                            "title": "Song", "duration": 100, "channel": "A"}})
    c = src.lookup("youtube", "https://youtu.be/x")
    assert (c.key, c.duration_s, c.url) == ("youtube:x", 100.0, "https://www.youtube.com/watch?v=x")
    assert src.calls == [("https://youtu.be/x", False)]


RAW = {"id": 5, "title": "Backbone", "permalink_url": "https://soundcloud.com/eskha/eskha-backbone",
       "user": {"username": "ESKHA"}, "downloadable": False, "has_downloads_left": False,
       "purchase_url": "https://droploud.com/gate/96e6", "purchase_title": "Free Download"}


def test_free_download_reads_gates_and_the_download_button():
    assert free_download(RAW) == {"url": "https://droploud.com/gate/96e6", "host": "droploud.com", "direct": False,
                                  "page": "https://soundcloud.com/eskha/eskha-backbone", "title": "Backbone",
                                  "uploader": "ESKHA"}
    # a known gate host counts whatever the button says; a shop link does not
    assert free_download({**RAW, "purchase_url": "https://www.hypeddit.com/x/y", "purchase_title": "Buy"})["host"] \
        == "hypeddit.com"
    assert free_download({**RAW, "purchase_url": "https://www.beatport.com/track/x/1", "purchase_title": "Buy"}) is None
    assert free_download({**RAW, "purchase_url": "https://x.bandcamp.com/track/y", "purchase_title": "FREE DL"})
    assert free_download({**RAW, "purchase_url": "javascript:alert(1)", "purchase_title": "Free"}) is None
    assert free_download({**RAW, "purchase_url": None}) is None
    direct = free_download({**RAW, "downloadable": True, "has_downloads_left": True})
    assert direct["direct"] and direct["url"] == RAW["permalink_url"]


def test_free_downloads_asks_only_for_soundcloud_and_survives_a_failed_lookup():
    from discjockey.models import Candidate

    class Src(FallbackSource):
        asked = []

        def _soundcloud_track(self, url):
            self.asked.append(url)
            if url.endswith("bad"):
                raise RuntimeError("HTTP Error 404")
            return RAW

    events = []
    src = Src(emit=events.append)
    cands = [Candidate("soundcloud", "1", "t", "a", 1.0, url="https://sc/1"),
             Candidate("youtube", "2", "t", "a", 1.0, url="https://yt/2"),
             Candidate("soundcloud", "3", "t", "a", 1.0, url="https://sc/bad")]
    out = src.free_downloads(cands)
    assert [o["key"] for o in out] == ["soundcloud:1"] and src.asked == ["https://sc/1", "https://sc/bad"]
    assert any("404" in e.text for e in events)


def test_the_download_info_of_a_track_named_by_its_id_is_asked_for_by_id(monkeypatch):
    import yt_dlp

    asked = []

    class IE:
        _API_V2_BASE, _HEADERS = "https://api-v2.soundcloud.com/", {}

        def initialize(self):
            pass

        def _resolv_url(self, url):
            return self._API_V2_BASE + "resolve?url=" + url

        def _call_api(self, url, video_id, headers=None):
            asked.append((url, headers))
            return RAW

    class YDL:
        def __init__(self, opts):
            assert "cookiesfrombrowser" not in opts  # the lookup is anonymous

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_info_extractor(self, key):
            return IE()

    monkeypatch.setattr(yt_dlp, "YoutubeDL", YDL)
    src = FallbackSource(logins={"soundcloud": ("firefox", None)})
    assert src._soundcloud_track(fb.stream_url("soundcloud", "900000101")) == RAW
    src._soundcloud_track("https://soundcloud.com/example-artist/example-title")
    assert asked == [("https://api-v2.soundcloud.com/tracks/900000101", {}),
                     ("https://api-v2.soundcloud.com/resolve?url=https://soundcloud.com/example-artist/example-title",
                      {})]


def test_search_can_be_limited_to_some_sources():
    src = FakeSource(pages={"scsearch5": {"entries": [{"id": "s", "url": "https://sc/s", "title": "x",
                                                        "duration": 156}]}})
    cands, _ = src.search(T, ("soundcloud",))
    assert [c.key for c in cands] == ["soundcloud:s"] and [u for u, _ in src.calls] == ["scsearch5:Vatoz Locoz Gimme Gimme"]


def test_a_direct_candidate_asks_yt_dlp_for_the_original_only(tmp_path, monkeypatch):
    from discjockey import fallback
    from discjockey.models import Candidate
    seen = {}

    class Ydl:
        def __init__(self, opts): seen.update(opts)
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def extract_info(self, url, download):
            (tmp_path / "soundcloud_1.wav").write_bytes(b"x")
            return {"id": "1", "ext": "wav"}
        def prepare_filename(self, info): return str(tmp_path / "soundcloud_1.wav")

    monkeypatch.setattr(fallback.yt_dlp, "YoutubeDL", Ydl)
    FallbackSource().download(Candidate("soundcloud", "1", "t", "a", 1.0, url="https://sc/1", direct=True), tmp_path)
    assert seen["format"] == "download"
    FallbackSource().download(Candidate("soundcloud", "1", "t", "a", 1.0, url="https://sc/1"), tmp_path)
    assert seen["format"] == "bestaudio/best"


def test_a_preview_clip_prefers_formats_ffmpeg_can_cut_without_a_dash_demuxer(tmp_path, monkeypatch):
    """The app's ffmpeg has no dash demuxer (no libxml2) and yt-dlp hands ffmpeg the manifest for a DASH format, so a
    section download tries the other formats first; a full download keeps the plain choice."""
    from discjockey import fallback
    from discjockey.models import Candidate
    seen = {}

    class Ydl:
        def __init__(self, opts): seen.update(opts)
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def extract_info(self, url, download):
            (tmp_path / "youtube_1.webm").write_bytes(b"x")
            return {"id": "1", "ext": "webm"}
        def prepare_filename(self, info): return str(tmp_path / "youtube_1.webm")

    monkeypatch.setattr(fallback.yt_dlp, "YoutubeDL", Ydl)
    cand = Candidate("youtube", "1", "t", "a", 1.0, url="https://yt/1")
    FallbackSource().download(cand, tmp_path, section=(10.0, 40.0))
    assert seen["format"] == "bestaudio[protocol!=http_dash_segments]/bestaudio/best" and "download_ranges" in seen
    seen.clear()
    FallbackSource().download(cand, tmp_path)
    assert seen["format"] == "bestaudio/best" and "download_ranges" not in seen


def test_stream_kbps_reads_the_format_a_download_would_take(monkeypatch):
    from discjockey import fallback
    seen = {}

    class Ydl:
        def __init__(self, opts): seen.update(opts)
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def extract_info(self, url, download):
            seen.update(url=url, download=download)
            return {"format_id": "251", "abr": 130.546}

    monkeypatch.setattr(fallback.yt_dlp, "YoutubeDL", Ydl)
    assert FallbackSource().stream_kbps("youtube_music", "abc") == 131
    assert seen["url"] == "https://music.youtube.com/watch?v=abc" and seen["download"] is False
    assert seen["format"] == "bestaudio/best" and seen["skip_download"]
    FallbackSource().stream_kbps("soundcloud", "2009930799")
    assert seen["url"] == "https://api.soundcloud.com/tracks/2009930799"
    assert FallbackSource().stream_kbps("manual", "x") is None


# SoundCloud's track JSON as yt-dlp gets it: a free 128 kbps MP3, and the Go+ ("hq") AAC stream
SC_FREE = {"url": "https://api-v2.soundcloud.com/media/1/a/stream/progressive", "preset": "mp3_1_0", "quality": "sq",
           "format": {"protocol": "progressive", "mime_type": "audio/mpeg"}}


def sc_go_plus(protocol):
    return {"url": "https://api-v2.soundcloud.com/media/1/b/stream/hls", "preset": "aac_256k", "quality": "hq",
            "format": {"protocol": protocol, "mime_type": 'audio/mp4; codecs="mp4a.40.2"'}}


def sc_extract(transcodings):
    """The real yt-dlp SoundCloud extractor on that JSON; the stream-URL request is answered here, any other request
    fails, so nothing is ever sent."""
    from yt_dlp.YoutubeDL import YoutubeDL  # the real one only for its options (conftest stubs yt_dlp.YoutubeDL)
    from discjockey import fallback

    def offline(*a, **k):
        raise OSError("no network in tests")

    ie = fallback.SoundcloudDrmIE()
    ie.set_downloader(YoutubeDL({"quiet": True}))
    ie._request_webpage = ie._download_json = offline
    ie._CLIENT_ID = "test"  # set by the login step, which is left out
    ie._call_api = lambda url, *a, **k: {"url": "https://cf-media.sndcdn.com/x.128.mp3?p=1" if "progressive" in url
                                                else "https://cf-hls-media.sndcdn.com/playlist/x.m3u8"}
    info = ie._extract_info_dict({"id": 1, "title": "t", "media": {"transcodings": transcodings}})
    return ie, info


def test_the_soundcloud_extractor_notes_a_go_plus_stream_that_yt_dlp_leaves_out_as_drm_protected():
    ie, info = sc_extract([SC_FREE, sc_go_plus("ctr-encrypted-hls")])
    assert [f["abr"] for f in info["formats"]] == [128]  # yt-dlp drops the protected stream without a word
    assert ie.drm_premium


def test_the_soundcloud_extractor_notes_nothing_for_a_plain_go_plus_stream():
    ie, info = sc_extract([SC_FREE, sc_go_plus("hls")])
    assert sorted(f["abr"] for f in info["formats"]) == [128, 256]
    assert not ie.drm_premium
