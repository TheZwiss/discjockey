"""The YouTube Music playlist source: link forms, parsing of yt-dlp's flat entries (songs vs videos, the skipped
ones), the reader (one request for the facts, lazy entries, Stop, every error word) and the registry. Offline: the
playlists are recorded yt-dlp answers with made-up ids, served by a fake `yt_dlp.YoutubeDL`; one test runs the real
extractor on canned page data to pin that a read writes no class-level state."""
import copy
import json
import socket
from pathlib import Path

import pytest
import yt_dlp

from discjockey import pacing, sources
from discjockey.events import Cancelled, CancelToken
from discjockey.library import SupportPaths
from discjockey.models import FetchedPlaylist, PlaylistInfo, PlaylistLine, SourceTrack
from discjockey.sources import LoginState, SourceError
from discjockey.sources import youtube_music as source

FIXTURES = Path(__file__).parent / "fixtures" / "youtube_music"
ALBUM_ID = "OLAK5uy_exampleAlbum0000000000000"
VIDEO_ID = "PLexampleVideoList000000000000000001"
ALBUM_LINE = PlaylistLine("Album", ALBUM_ID, 3, "youtube_music")
VIDEO_LINE = PlaylistLine("Warmup", VIDEO_ID, 4, "youtube_music")
UNREADABLE_FETCH = ("playlists.txt line 3 (Album): YouTube Music doesn't show this playlist. It must be public or "
                    "unlisted. Check the link, or put # in front of the line.")
UNREADABLE_INFO = "YouTube Music doesn't show this playlist. It must be public or unlisted. Check the link."
SLOW_DOWN = "YouTube Music asked Discjockey to slow down. Try again in an hour."
W17 = ("Discjockey can't read your liked songs or Watch later. Add the songs to a playlist, set it to public or "
       "unlisted, and paste that link.")
W18 = "This is a YouTube mix, which changes every time it plays. Save its songs to a playlist and paste that link."


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


# --- 3.1 recognise -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("link, expected", [
    ("https://music.youtube.com/playlist?list=PLexampleList0001", "PLexampleList0001"),
    ("https://music.youtube.com/playlist?list=PLexampleList0001&si=AbCdEf123", "PLexampleList0001"),
    ("https://music.youtube.com/playlist?si=AbCdEf123&list=PLexampleList0001", "PLexampleList0001"),
    ("http://music.youtube.com/playlist?list=PLexampleList0001", "PLexampleList0001"),
    ("https://music.youtube.com/browse/VLPLexampleList0001", "PLexampleList0001"),
    ("https://music.youtube.com/browse/VLOLAK5uy_exampleAlbum", "OLAK5uy_exampleAlbum"),
    ("https://www.youtube.com/playlist?list=PLexampleList0001", "PLexampleList0001"),
    ("https://youtube.com/playlist?list=PLexampleList0001", "PLexampleList0001"),
    ("https://m.youtube.com/playlist?list=PLexampleList0001", "PLexampleList0001"),
    ("https://www.youtube.com/watch?v=EXAMPLEid01&list=PLexampleList0001", "PLexampleList0001"),
    ("https://www.youtube.com/watch?v=EXAMPLEid01&list=PLexampleList0001&index=3&si=x", "PLexampleList0001"),
    ("https://music.youtube.com/watch?v=EXAMPLEid01&list=PLexampleList0001", "PLexampleList0001"),
    ("https://WWW.YouTube.com/playlist?list=PLexampleList0001", "PLexampleList0001"),
    ("https://music.youtube.com/playlist?list=PLexample-List_0001", "PLexample-List_0001"),
    # recognised, refused when read (W17, W18)
    ("https://music.youtube.com/playlist?list=LM", "LM"),
    ("https://www.youtube.com/playlist?list=LL", "LL"),
    ("https://www.youtube.com/playlist?list=WL", "WL"),
    ("https://music.youtube.com/watch?v=EXAMPLEid01&list=RDAMVMEXAMPLEid01", "RDAMVMEXAMPLEid01"),
    ("https://music.youtube.com/playlist?list=RDCLAK5uy_exampleCurated", "RDCLAK5uy_exampleCurated"),
])
def test_recognise_each_form(link, expected):
    assert source.recognise(link) == expected


@pytest.mark.parametrize("link", [
    "https://www.youtube.com/watch?v=EXAMPLEid01",                       # a plain video
    "https://music.youtube.com/watch?v=EXAMPLEid01",
    "https://www.youtube.com/watch?list=PLexampleList0001",              # no video id: not a watch link
    "https://youtu.be/EXAMPLEid01",
    "https://youtu.be/EXAMPLEid01?list=PLexampleList0001",
    "https://www.youtube.com/channel/UCexampleChannel00000001",
    "https://www.youtube.com/@example",
    "https://music.youtube.com/channel/UCexampleChannel00000001",
    "https://music.youtube.com/browse/MPREb_example",                    # an album page, not its playlist
    "https://music.youtube.com/browse/VL",
    "https://www.youtube.com/browse/VLPLexampleList0001",
    "https://music.youtube.com/playlist",
    "https://music.youtube.com/playlist?list=",
    "https://music.youtube.com/playlist?list=PL bad id",
    "https://music.youtube.com/playlist?list=PL/../x",
    "https://music.youtube.com/search?q=example",
    "https://example.com/playlist?list=PLexampleList0001",
    "https://youtube.com.example.com/playlist?list=PLexampleList0001",
    "ftp://music.youtube.com/playlist?list=PLexampleList0001",
    "https://open.spotify.com/playlist/0DiscjockeyExampleList",
    "music.youtube.com/playlist?list=PLexampleList0001",
    "not a link",
    "",
])
def test_recognise_refuses_everything_else(link):
    assert source.recognise(link) is None


def test_canonical_link_and_the_ids_case_is_kept():
    assert source.canonical_link("PLexampleList0001") == "https://music.youtube.com/playlist?list=PLexampleList0001"
    pid = source.recognise("https://www.youtube.com/playlist?list=PLexAMPLElist0001")
    assert pid == "PLexAMPLElist0001"
    assert source.recognise(source.canonical_link(pid)) == pid


def test_login_state_needs_no_login(tmp_path):
    state = source.login_state(SupportPaths(support=tmp_path / ".support"))
    assert state == LoginState("not_needed") and state.connected


# --- 3.3 parsing ---------------------------------------------------------------------------------------------------

def test_parse_a_song_takes_the_channel_as_artist():
    track = source.parse_entry(fixture("album_playlist")["entries"][0])
    assert track == SourceTrack(
        id="EXAMPLEalb01", title="Example Song One", artists=("Example Artist",), album="",
        image_url="https://i.ytimg.com/vi/EXAMPLEalb01/hqdefault.jpg", duration_ms=215000, isrc=None,
        service="youtube_music", link="https://music.youtube.com/watch?v=EXAMPLEalb01")
    assert track.streamable and not track.account_only and track.key == "youtube_music:EXAMPLEalb01"


def test_parse_a_topic_channel_and_a_remix_keep_the_remix():
    track = source.parse_entry(fixture("album_playlist")["entries"][1])
    assert (track.artists, track.title) == (("Example Artist",), "Example Song Two (Example Remix)")


def test_parse_a_video_is_split_at_its_dash():
    video = fixture("video_playlist")["entries"]
    first = source.parse_entry(video[0])
    assert (first.artists, first.title, first.duration_ms) == (("Example Artist",), "Example Title", 231000)
    piped = source.parse_entry(video[1])  # the pipe tail goes
    assert (piped.artists, piped.title) == (("Example Artist",), "Example Title")
    bare = source.parse_entry(video[4])  # no dash: the channel is the artist
    assert (bare.artists, bare.title) == (("Example DJ",), "Lonely Example Title")
    featured = source.parse_entry(video[6])
    assert (featured.artists, featured.title) == (("Example Artist", "Other Artist"), "Example Title")


@pytest.mark.parametrize("index, text", [
    (2, "[Deleted video] (removed from YouTube)"),
    (3, "[Private video] (removed from YouTube)"),
    (5, "Odd Example (removed from YouTube)"),          # no id
    (7, "Example Live Stream (removed from YouTube)"),  # no length
])
def test_parse_skips_what_cannot_be_played(index, text):
    assert source.parse_entry(fixture("video_playlist")["entries"][index]) == text


@pytest.mark.parametrize("entry, text", [
    (None, "A track (removed from YouTube)"),
    ("EXAMPLEvid09", "A track (removed from YouTube)"),
    ({"id": "EXAMPLEvid09", "title": "  ", "duration": 100}, "A track (removed from YouTube)"),
    ({"id": "EXAMPLEvid09", "title": "Example", "duration": 0}, "Example (removed from YouTube)"),
    ({"id": "EXAMPLEvid09", "title": "Example", "duration": True}, "Example (removed from YouTube)"),
    ({"id": "EXAMPLEvid09", "title": "[DELETED VIDEO]", "duration": 100}, "[DELETED VIDEO] (removed from YouTube)"),
])
def test_parse_odd_entries(entry, text):
    assert source.parse_entry(entry) == text


def test_parse_takes_the_largest_thumbnail_else_the_standard_one():
    entry = {"id": "EXAMPLEthm01", "title": "Artist - Title", "duration": 100, "channel": "x", "thumbnails": [
        {"url": "https://example.com/big.jpg", "width": 640, "height": 360},
        {"url": "https://example.com/small.jpg", "width": 120, "height": 90},
        {"url": "", "width": 1920, "height": 1080}]}
    assert source.parse_entry(entry).image_url == "https://example.com/big.jpg"
    unsized = {**entry, "thumbnails": [{"url": "https://example.com/a.jpg"}, {"url": "https://example.com/b.jpg"}]}
    assert source.parse_entry(unsized).image_url == "https://example.com/b.jpg"
    for none in ({**entry, "thumbnails": None}, {**entry, "thumbnails": []}, {**entry, "thumbnails": ["x", {}]}):
        assert source.parse_entry(none).image_url == "https://i.ytimg.com/vi/EXAMPLEthm01/hqdefault.jpg"


def test_parse_uses_the_uploader_when_there_is_no_channel():
    entry = {"id": "EXAMPLEupl01", "title": "Title Only", "duration": 61, "uploader": "Example Uploader"}
    track = source.parse_entry(entry)
    assert track.artists == ("Example Uploader",) and track.duration_ms == 61000
    assert source.parse_entry({**entry, "uploader": None}).artists == ()


# --- the reader ----------------------------------------------------------------------------------------------------

class World:
    """Everything the fake yt-dlp serves and records."""

    def __init__(self):
        self.created = []       # the options of every YoutubeDL
        self.calls = []         # (url, download, process) of every extract_info
        self.answers = {}       # playlist id -> the dict (or an exception to raise)
        self.consumed = []      # ids of the entries the reader pulled, in order
        self.on_entry = None    # called with the entry's index just before it is handed out
        self.fail_at = None     # (index, exception): the generator raises before handing out that entry
        self.closed = 0

    def add(self, name, playlist_id):
        self.answers[playlist_id] = fixture(name)

    def lazy(self, entries):
        for i, entry in enumerate(entries):
            if self.fail_at and self.fail_at[0] == i:
                raise self.fail_at[1]
            if self.on_entry:
                self.on_entry(i)
            self.consumed.append(entry.get("id"))
            yield entry


class FakeYDL:
    def __init__(self, world, opts):
        self.world, self.opts = world, opts

    def extract_info(self, url, download=True, process=True, **kwargs):
        self.world.calls.append((url, download, process))
        playlist_id = url.split("list=")[1]
        answer = self.world.answers[playlist_id]
        if isinstance(answer, Exception):
            raise answer
        answer = dict(answer)
        if "entries" in answer:
            answer["entries"] = self.world.lazy(answer["entries"])  # a generator, like yt-dlp's
        return answer

    def close(self):
        self.world.closed += 1


@pytest.fixture
def world(monkeypatch):
    w = World()

    def factory(opts):
        w.created.append(opts)
        return FakeYDL(w, opts)

    monkeypatch.setattr(yt_dlp, "YoutubeDL", factory)
    w.add("album_playlist", ALBUM_ID)
    w.add("video_playlist", VIDEO_ID)
    return w


@pytest.fixture
def paths(tmp_path):
    return SupportPaths(support=tmp_path / ".support")


def read(paths, line=ALBUM_LINE, want_info=False, token=None):
    with source.open(paths, token or CancelToken()) as reader:
        reader.want_info = want_info
        return reader.fetch(line)


def test_a_playlist_reads_in_order_with_one_request(world, paths):
    fetched = read(paths)
    assert isinstance(fetched, FetchedPlaylist) and fetched.line == ALBUM_LINE
    assert [t.title for t in fetched.tracks] == ["Example Song One", "Example Song Two (Example Remix)",
                                                 "Example Song Three"]
    assert fetched.skipped == [] and fetched.info is None
    assert world.calls == [(f"https://music.youtube.com/playlist?list={ALBUM_ID}", False, False)]
    assert world.closed == 1


def test_a_video_playlist_splits_and_names_what_it_skipped(world, paths):
    fetched = read(paths, VIDEO_LINE)
    assert [(t.artists, t.title) for t in fetched.tracks] == [
        (("Example Artist",), "Example Title"), (("Example Artist",), "Example Title"),
        (("Example DJ",), "Lonely Example Title"), (("Example Artist", "Other Artist"), "Example Title")]
    assert fetched.skipped == ["[Deleted video] (removed from YouTube)", "[Private video] (removed from YouTube)",
                               "Odd Example (removed from YouTube)", "Example Live Stream (removed from YouTube)"]


def test_the_reader_is_anonymous_and_flat(world, paths):
    read(paths)
    (opts,) = world.created
    assert opts["extract_flat"] == "in_playlist" and opts["skip_download"] is True and opts["socket_timeout"] == 30
    assert opts["quiet"] is True and opts["noprogress"] is True and "logger" in opts
    for key in ("cookiefile", "cookiesfrombrowser", "extractor_args", "username", "password", "http_headers",
                "proxy", "cachedir"):
        assert key not in opts
    assert set(opts) == {"quiet", "no_warnings", "noprogress", "logger", "skip_download", "extract_flat",
                         "socket_timeout"}


def test_the_logger_keeps_yt_dlp_quiet(world, paths, capsys):
    read(paths)
    (opts,) = world.created
    for method in ("debug", "info", "warning", "error"):
        getattr(opts["logger"], method)("something")
    out = capsys.readouterr()
    assert (out.out, out.err) == ("", "")


def test_want_info_fills_the_info_from_the_first_answer(world, paths):
    info = read(paths, want_info=True).info
    assert info == PlaylistInfo(
        "youtube_music", ALBUM_ID, "Example Album", "UCexampleChannel00000001", "Example Artist", False,
        "https://i.ytimg.com/vi/EXAMPLEalb01/sddefault.jpg", 3, False, True)
    assert len(world.calls) == 1


def test_info_counts_the_entries_read_when_the_page_gives_no_count(world, paths):
    world.answers[ALBUM_ID]["playlist_count"] = None
    assert read(paths, want_info=True).info.track_count == 3
    world.answers[VIDEO_ID]["playlist_count"] = None
    assert read(paths, VIDEO_LINE, want_info=True).info.track_count == 8  # skipped entries count too


def test_info_is_one_request_and_never_reads_an_entry(world, paths):
    with source.open(paths, CancelToken()) as reader:
        info = reader.info(VIDEO_ID)
    assert info == PlaylistInfo("youtube_music", VIDEO_ID, "Example Warmup Set", "UCexampleChannel00000001",
                                "Example Channel", False, "https://i.ytimg.com/vi/EXAMPLEalb01/sddefault.jpg", 8,
                                False, True)
    assert len(world.calls) == 1 and world.consumed == []


def test_info_leaves_a_title_without_the_album_prefix_alone(world, paths):
    world.answers[ALBUM_ID]["title"] = "Albums - Example"
    with source.open(paths, CancelToken()) as reader:
        assert reader.info(ALBUM_ID).name == "Albums - Example"
    world.answers[ALBUM_ID].update(title="Mix", channel=None, uploader="Example Uploader", channel_id=None,
                                   thumbnails=None, playlist_count=None)
    with source.open(paths, CancelToken()) as reader:
        info = reader.info(ALBUM_ID)
    assert (info.owner_id, info.owner_name, info.image_url, info.track_count) == ("", "Example Uploader", None, None)


def test_a_curated_playlist_is_read_like_any_other(world, paths):
    world.answers["RDCLAK5uy_exampleCurated"] = fixture("album_playlist")
    line = PlaylistLine("Curated", "RDCLAK5uy_exampleCurated", 1, "youtube_music")
    assert len(read(paths, line).tracks) == 3


# --- W17, W18: refused before any request --------------------------------------------------------------------------

@pytest.mark.parametrize("playlist_id, words", [
    ("LM", W17), ("LL", W17), ("WL", W17),
    ("RDAMVMEXAMPLEid01", W18), ("RDMM", W18), ("RDEMexample", W18),
])
def test_personal_lists_and_mixes_are_refused_without_a_request(world, paths, playlist_id, words):
    with source.open(paths, CancelToken()) as reader:
        for call in (lambda: reader.fetch(PlaylistLine("X", playlist_id, 2, "youtube_music")),
                     lambda: reader.info(playlist_id)):
            with pytest.raises(SourceError) as e:
                call()
            assert str(e.value) == words
            assert (e.value.kind, e.value.service) == ("playlist_unreadable", "youtube_music")
    assert world.calls == []


# --- errors --------------------------------------------------------------------------------------------------------

class Failure(Exception):
    """yt-dlp's DownloadError as far as the source reads it: its text."""


def failing(world, key, playlist_id=ALBUM_ID):
    world.answers[playlist_id] = Failure(fixture("errors")[key])


@pytest.mark.parametrize("key", ["removed_or_private", "bad_id", "not_a_playlist"])
def test_a_playlist_youtube_does_not_show_is_unreadable(world, paths, key):
    failing(world, key)
    with pytest.raises(SourceError) as e:
        read(paths)
    assert str(e.value) == UNREADABLE_FETCH
    assert (e.value.kind, e.value.service) == ("playlist_unreadable", "youtube_music")
    failing(world, key)
    with source.open(paths, CancelToken()) as reader, pytest.raises(SourceError) as e:
        reader.info(ALBUM_ID)
    assert str(e.value) == UNREADABLE_INFO and e.value.kind == "playlist_unreadable"
    assert world.closed == 2


@pytest.mark.parametrize("key", ["bot_check", "too_many_requests"])
def test_the_bot_check_and_too_many_requests_say_slow_down(world, paths, key):
    failing(world, key)
    with pytest.raises(SourceError) as e:
        read(paths)
    assert (str(e.value), e.value.kind, e.value.service) == (SLOW_DOWN, "offline", "youtube_music")


@pytest.mark.parametrize("key", ["network", "server_down"])
def test_anything_else_says_youtube_is_not_answering_with_only_the_error_kind(world, paths, key):
    failing(world, key)
    with pytest.raises(SourceError) as e:
        read(paths)
    assert str(e.value) == "YouTube Music is not responding (Failure). Try again later."
    assert (e.value.kind, e.value.service) == ("offline", "youtube_music")
    assert "example" not in str(e.value).lower() and "http" not in str(e.value).lower()


def test_a_dict_that_is_no_playlist_is_unreadable(world, paths):
    for answer in ({"_type": "url", "url": "https://www.youtube.com/watch?v=EXAMPLEid01"}, {"_type": "playlist"}):
        world.answers[ALBUM_ID] = answer
        with pytest.raises(SourceError) as e:
            read(paths)
        assert str(e.value) == UNREADABLE_FETCH


def test_a_later_page_that_fails_is_a_read_error_not_a_private_playlist(world, paths):
    world.fail_at = (2, Failure(fixture("errors")["removed_or_private"]))
    with pytest.raises(SourceError) as e:
        read(paths)
    assert str(e.value) == "YouTube Music is not responding (Failure). Try again later."
    world.fail_at = (1, Failure(fixture("errors")["too_many_requests"]))
    with pytest.raises(SourceError) as e:
        read(paths)
    assert str(e.value) == SLOW_DOWN
    assert world.closed == 2


def test_open_failing_says_youtube_is_not_answering(paths):  # conftest's stub YoutubeDL refuses to be built
    with pytest.raises(SourceError) as e:
        source.open(paths, CancelToken())
    assert str(e.value) == "YouTube Music is not responding (OSError). Try again later."
    assert (e.value.kind, e.value.service) == ("offline", "youtube_music")


# --- Stop ----------------------------------------------------------------------------------------------------------

def test_stop_before_the_request_makes_none(world, paths):
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        source.open(paths, token)
    token = CancelToken()
    with source.open(paths, token) as reader:
        token.cancel()
        with pytest.raises(Cancelled):
            reader.fetch(ALBUM_LINE)
    assert world.calls == []


def test_stop_reaches_the_read_between_entries(world, paths):
    token = CancelToken()
    world.on_entry = lambda i: token.cancel() if i == 1 else None
    with pytest.raises(Cancelled):
        read(paths, token=token)
    assert world.consumed == ["EXAMPLEalb01", "EXAMPLEalb02"]  # the third entry (a further page) was never asked for
    assert world.closed == 1


# --- no download protection, no cookies ----------------------------------------------------------------------------

def test_a_read_uses_no_pacer_and_no_budget(world, paths, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a read must not pace or count")

    monkeypatch.setattr(pacing, "Pacer", boom)
    monkeypatch.setattr(pacing, "Budget", boom)
    assert len(read(paths, VIDEO_LINE).tracks) == 4
    for name in ("pacing", "Pacer", "Budget", "usage", "Acquirer", "settings", "load_settings"):
        assert not hasattr(source, name)


def test_a_read_never_looks_at_the_settings_or_a_browser(world, paths):
    assert not paths.support.exists()  # no settings file was needed, none was made
    read(paths)
    assert not paths.support.exists()


# --- class-level state (group 2's lesson) ---------------------------------------------------------------------------

def _tab_page():
    """Canned `ytInitialData` of a two-song playlist page, as far as the tab extractor reads it."""
    def video(video_id, title, seconds):
        return {"playlistVideoRenderer": {
            "videoId": video_id, "title": {"runs": [{"text": title}]}, "lengthSeconds": str(seconds),
            "shortBylineText": {"runs": [{"text": "Example Artist"}]},
            "thumbnail": {"thumbnails": [{"url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                                          "width": 480, "height": 360}]}}}

    return {
        "metadata": {"playlistMetadataRenderer": {"title": "Album - Example Album"}},
        "header": {"playlistHeaderRenderer": {
            "byline": [{"playlistBylineRenderer": {"text": {"simpleText": "2 tracks"}}}],
            "ownerText": {"runs": [{"text": "Example Artist"}]}}},
        "contents": {"twoColumnBrowseResultsRenderer": {"tabs": [{"tabRenderer": {"selected": True, "content": {
            "sectionListRenderer": {"contents": [{"itemSectionRenderer": {"contents": [{"playlistVideoListRenderer": {
                "contents": [video("EXAMPLEtab01", "Example Song One", 200),
                             video("EXAMPLEtab02", "Example Song Two", 210)]}}]}}]}}}}]}},
    }


# yt-dlp memoises the compiled form of a class's constant `_VALID_URL` on the class (`InfoExtractor._match_valid_url`,
# a one-tuple holding a compiled pattern): the same value for everyone, not state of a read, so it is not compared.
_MEMOS = frozenset({"_VALID_URL_RE"})


def _class_state(*classes):
    """Every plain-data class attribute (containers, strings, numbers) of the classes, deep-copied, to compare later."""
    plain = (dict, list, set, tuple, str, int, float, bool, bytes, type(None))
    return {f"{cls.__module__}.{cls.__qualname__}": {k: copy.deepcopy(v) for k, v in vars(cls).items()
                                                      if isinstance(v, plain) and k not in _MEMOS} for cls in classes}


def test_the_class_state_snapshot_sees_a_write():
    class Shared:
        headers = {}

    before = _class_state(Shared)
    Shared.headers["Authorization"] = "OAuth example"
    assert _class_state(Shared) != before


def test_a_read_through_the_real_extractor_writes_no_class_attribute(paths, monkeypatch):
    """yt-dlp keeps some state at class level (SoundCloud's login header lives in a dict every extractor of the
    process shares). Runs yt-dlp's real `youtube:tab` extractor on canned page data, so a read that wrote a class
    attribute of it, of its bases or of YoutubeDL would show. No socket is opened."""
    from yt_dlp.extractor.youtube._tab import YoutubeTabIE
    from yt_dlp.YoutubeDL import YoutubeDL as RealYoutubeDL  # conftest stubs `yt_dlp.YoutubeDL`; this one does no I/O

    def refuse(*a, **k):
        raise AssertionError("a read in this test must not open a socket")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    pages = []
    monkeypatch.setattr(YoutubeTabIE, "_extract_data",
                        lambda self, url, item_id, *a, **k: (pages.append(url), (_tab_page(), {}))[1])
    monkeypatch.setattr(YoutubeTabIE, "_reload_with_unavailable_videos", lambda self, *a, **k: None)
    monkeypatch.setattr(yt_dlp, "YoutubeDL", RealYoutubeDL)

    classes = (*YoutubeTabIE.__mro__[:-1], RealYoutubeDL)
    before = _class_state(*classes)
    with source.open(paths, CancelToken()) as reader:
        reader.want_info = True
        fetched = reader.fetch(PlaylistLine("Album", "OLAK5uy_exampleAlbum0000000000000", 1, "youtube_music"))
        info = reader.info("OLAK5uy_exampleAlbum0000000000000")
    assert _class_state(*classes) == before

    # and what the real extractor gave, with process=False: the facts first, flat entries, no cookies on the page
    assert pages == ["https://www.youtube.com/playlist?list=OLAK5uy_exampleAlbum0000000000000"] * 2
    assert [(t.id, t.artists, t.title, t.duration_ms) for t in fetched.tracks] == [
        ("EXAMPLEtab01", ("Example Artist",), "Example Song One", 200000),
        ("EXAMPLEtab02", ("Example Artist",), "Example Song Two", 210000)]
    assert (info.name, info.owner_name, info.track_count) == ("Example Album", "Example Artist", 2)
    assert fetched.info.track_count == 2


# --- the registry --------------------------------------------------------------------------------------------------

def test_the_registry_holds_youtube_music_last():
    assert list(sources.SOURCES)[-1] == "youtube_music" and sources.SOURCES["youtube_music"] is source


def test_recognise_routes_each_link_to_its_service():
    assert sources.recognise("https://music.youtube.com/playlist?list=PLexampleList0001") == (
        "youtube_music", "PLexampleList0001")
    assert sources.recognise("https://www.youtube.com/watch?v=EXAMPLEid01&list=PLexampleList0001") == (
        "youtube_music", "PLexampleList0001")
    assert sources.recognise("https://open.spotify.com/playlist/0DiscjockeyExampleList") == (
        "spotify", "0DiscjockeyExampleList")
    assert sources.recognise("https://www.youtube.com/watch?v=EXAMPLEid01") is None


def test_the_registry_reads_a_youtube_music_line_without_a_login(world, paths):
    (fetched,) = sources.read(paths, [ALBUM_LINE])
    assert len(fetched.tracks) == 3 and not paths.support.exists()


def test_read_infos_drops_an_unreadable_playlist_and_keeps_the_rest(world, paths):
    failing(world, "removed_or_private", VIDEO_ID)
    infos = {f"youtube_music:{VIDEO_ID}": object()}
    sources.read_infos(paths, [f"youtube_music:{ALBUM_ID}", f"youtube_music:{VIDEO_ID}"], infos, CancelToken())
    assert list(infos) == [f"youtube_music:{ALBUM_ID}"] and infos[f"youtube_music:{ALBUM_ID}"].name == "Example Album"


def test_the_hint_is_the_unreadable_words():
    assert source.UNREADABLE_HINT == "Set it to public or unlisted in YouTube Music."
