import pytest

from discjockey import candidates, fallback
from discjockey.candidates import parse_link, score
from discjockey.library import Paths
from discjockey.models import Candidate, SourceTrack

T = SourceTrack("t1", "Get Naughty", ("Armin Hermann",), "Album", None, 268000, "DEXX1")


def qc(id, title="Get Naughty", dur=268.0, isrc=None, artist="Armin Hermann Various"):
    return Candidate("qobuz", id, title, artist, dur, isrc=isrc)


def fc(id, source="youtube_music", title="Get Naughty", dur=268.0, artist="Armin Hermann - Topic"):
    return Candidate(source, id, title, artist, dur, url=f"https://x/{id}")


def test_scores():
    assert score(T, qc("1", isrc="DEXX1")) == 100  # same ISRC and length
    assert score(T, fc("a")) == 100
    official = fc("b", "youtube", "Armin Hermann - Get Naughty (Official Video)", 271.0, "Armin Hermann")
    assert 90 <= score(T, official) < 100
    extended = fc("c", "soundcloud", "Armin Hermann - Get Naughty (Extended)", 352.0, "hardbouncefm")
    live = fc("d", "youtube", "Get Naughty (Live at Ruhr in Love)", 370.0, "someone")
    assert score(T, extended) < 90 and score(T, live) < score(T, extended)
    assert score(T, fc("e", dur=None)) < score(T, fc("a"))


class FakeQobuz:
    def __init__(self, results, fail=False):
        self.results, self.fail, self.queries = results, fail, []

    def search(self, query, limit=10):
        self.queries.append(query)
        if self.fail:
            raise RuntimeError("Cannot connect to host www.qobuz.com:443")
        return self.results.get(query, [])


class FakeFallback:
    def __init__(self, cands, errors=()):
        self.cands, self.errors = cands, list(errors)

    def search(self, track):
        return list(self.cands), list(self.errors)


def entry(**kw):
    e = {"source": "youtube", "source_id": "b", "rejected_sources": ["soundcloud:c"], "status": "not_lossless"}
    e.update(kw)
    return e


def test_search_lists_qobuz_and_fallback_with_scores_and_flags():
    q = FakeQobuz({"DEXX1": [qc("1", isrc="DEXX1")], "Armin Hermann Get Naughty": [qc("1", isrc="DEXX1"), qc("2")]})
    official = fc("b", "youtube", "Armin Hermann - Get Naughty (Official Video)", 271.0, "Armin Hermann")
    extended = fc("c", "soundcloud", "Armin Hermann - Get Naughty (Extended)", 352.0, "hardbouncefm")
    found, notes = candidates.search(T, entry(), q, FakeFallback([fc("a"), official, extended]))
    assert q.queries == ["DEXX1", "Armin Hermann Get Naughty"]
    keys = [s.candidate.key for s in found]
    assert keys[0] == "youtube:b"  # the version in the library now comes first
    assert sorted(keys) == sorted(["qobuz:1", "qobuz:2", "youtube_music:a", "youtube:b", "soundcloud:c"])
    by = {s.candidate.key: s for s in found}
    assert by["youtube:b"].current and not by["qobuz:1"].current
    assert by["soundcloud:c"].rejected and not by["soundcloud:c"].length_ok
    assert by["qobuz:1"].matches and by["qobuz:1"].length_ok and by["qobuz:1"].score == 100
    rest = [s.score for s in found[1:]]
    assert rest == sorted(rest, reverse=True)
    assert notes == []


def test_search_without_qobuz_still_lists_the_rest():
    found, notes = candidates.search(T, entry(), None, FakeFallback([fc("a")]))
    assert [s.candidate.key for s in found] == ["youtube_music:a"]
    assert notes == ["Qobuz is not set up, so only YouTube Music, SoundCloud and YouTube were searched."]


def test_search_reports_failed_searches():
    found, notes = candidates.search(T, entry(), FakeQobuz({}, fail=True),
                                     FakeFallback([], ["SoundCloud search failed: HTTP Error 403"]))
    assert found == []
    assert notes[0].startswith("Qobuz search failed:") and notes[1] == "SoundCloud search failed: HTTP Error 403"


@pytest.mark.parametrize("url,expected", [
    ("https://open.qobuz.com/track/123456", ("qobuz", "123456")),
    ("https://play.qobuz.com/track/123456?foo=1", ("qobuz", "123456")),
    ("https://www.qobuz.com/de-de/track/123456", ("qobuz", "123456")),
    ("https://music.youtube.com/watch?v=abcdefghijk&list=RD", ("youtube_music", "https://music.youtube.com/watch?v=abcdefghijk")),
    ("https://www.youtube.com/watch?v=abcdefghijk&t=10s", ("youtube", "https://www.youtube.com/watch?v=abcdefghijk")),
    ("https://youtu.be/abcdefghijk?si=x", ("youtube", "https://www.youtube.com/watch?v=abcdefghijk")),
    ("  https://soundcloud.com/hardbouncefm/get-naughty?in=x  ", ("soundcloud", "https://soundcloud.com/hardbouncefm/get-naughty")),
])
def test_parse_link(url, expected):
    assert parse_link(url) == expected


@pytest.mark.parametrize("url", ["", "hello", "https://open.spotify.com/track/abc",
                                 "https://soundcloud.com/hardbouncefm/sets/mix", "https://www.qobuz.com/album/x/123"])
def test_parse_link_refuses_other_links(url):
    with pytest.raises(ValueError, match="Qobuz track"):
        parse_link(url)


def test_link_candidate_for_qobuz_asks_qobuz_for_the_track():
    class Q:
        def track(self, track_id):
            return qc(track_id, dur=268.0)

    c = candidates.link_candidate("https://open.qobuz.com/track/99", Q(), None)
    assert (c.key, c.duration_s) == ("qobuz:99", 268.0)


def test_link_candidate_for_youtube_looks_it_up():
    class F:
        def lookup(self, source, url):
            return Candidate(source, "abcdefghijk", "Get Naughty", "Armin Hermann", 268.0, url=url)

    c = candidates.link_candidate("https://youtu.be/abcdefghijk", None, F())
    assert c.key == "youtube:abcdefghijk" and c.url == "https://www.youtube.com/watch?v=abcdefghijk"


def test_link_candidate_needs_qobuz_for_a_qobuz_link():
    with pytest.raises(ValueError, match="Qobuz is not set up"):
        candidates.link_candidate("https://open.qobuz.com/track/99", None, None)


# --- previews (YouTube Music, SoundCloud, YouTube only) ---

class FakeYDL:
    opts = None

    def __init__(self, opts):
        FakeYDL.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download):
        assert download
        out = FakeYDL.opts["outtmpl"].replace("%(id)s", "abcdefghijk").replace("%(ext)s", "webm")
        open(out, "wb").write(b"section")
        return {"id": "abcdefghijk", "ext": "webm"}

    def prepare_filename(self, info):
        return FakeYDL.opts["outtmpl"].replace("%(id)s", "abcdefghijk").replace("%(ext)s", "webm")


def test_preview_downloads_a_30_second_section_and_caches_it(tmp_path, monkeypatch):
    monkeypatch.setattr(fallback.yt_dlp, "YoutubeDL", FakeYDL)
    converted = []

    def convert(src, dst, **kw):
        converted.append(src.read_bytes())
        dst.write_bytes(b"AIFF preview")

    monkeypatch.setattr(candidates.audio, "convert_to_aiff", convert)
    paths = Paths(tmp_path, support=tmp_path / ".support")
    cand = fc("abcdefghijk", "youtube", dur=268.0)
    out = candidates.preview(paths, cand, fallback.FallbackSource())
    assert out == paths.cache / "previews" / "youtube_abcdefghijk.aiff" and out.read_bytes() == b"AIFF preview"
    assert converted == [b"section"]
    ranges = FakeYDL.opts["download_ranges"]({}, None)
    assert [(r["start_time"], r["end_time"]) for r in ranges] == [(60, 90)]
    assert [p.name for p in (paths.cache / "previews").iterdir()] == ["youtube_abcdefghijk.aiff"]
    FakeYDL.opts = None
    assert candidates.preview(paths, cand, fallback.FallbackSource()) == out and FakeYDL.opts is None  # cached


def test_short_tracks_preview_from_the_start(tmp_path, monkeypatch):
    monkeypatch.setattr(fallback.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(candidates.audio, "convert_to_aiff", lambda src, dst, **kw: dst.write_bytes(b"x"))
    candidates.preview(Paths(tmp_path, support=tmp_path / ".support"), fc("abcdefghijk", "soundcloud", dur=80.0),
                       fallback.FallbackSource())
    assert [(r["start_time"], r["end_time"]) for r in FakeYDL.opts["download_ranges"]({}, None)] == [(0, 30)]


def test_no_preview_for_qobuz(tmp_path):
    with pytest.raises(ValueError, match="no preview"):
        candidates.preview(Paths(tmp_path, support=tmp_path / ".support"), qc("1"), fallback.FallbackSource())


def test_a_failed_preview_leaves_nothing_behind(tmp_path, monkeypatch):
    class Broken(FakeYDL):
        def extract_info(self, url, download):
            raise RuntimeError("HTTP Error 403")

    monkeypatch.setattr(fallback.yt_dlp, "YoutubeDL", Broken)
    paths = Paths(tmp_path, support=tmp_path / ".support")
    with pytest.raises(RuntimeError):
        candidates.preview(paths, fc("abcdefghijk", "youtube"), fallback.FallbackSource())
    assert list((paths.cache / "previews").iterdir()) == []


def test_search_leaves_out_versions_known_to_be_protected():
    found, _ = candidates.search(T, entry(), None, FakeFallback([fc("a"), fc("p", "soundcloud")]),
                                 skip={"soundcloud:p"})
    assert [s.candidate.key for s in found] == ["youtube_music:a"]


def test_a_protected_preview_is_remembered(tmp_path, monkeypatch):
    from discjockey.models import Protected

    class Drm(FakeYDL):
        def extract_info(self, url, download):
            raise RuntimeError("ERROR: [soundcloud] 7: This video is DRM protected")

    monkeypatch.setattr(fallback.yt_dlp, "YoutubeDL", Drm)
    paths = Paths(tmp_path, support=tmp_path / ".support")
    with pytest.raises(Protected):
        candidates.preview(paths, fc("abcdefghijk", "soundcloud"), fallback.FallbackSource())
    assert candidates.protected(paths) == {"soundcloud:abcdefghijk"}
    candidates.mark_protected(paths, "youtube:x")
    assert candidates.protected(paths) == {"soundcloud:abcdefghijk", "youtube:x"}
