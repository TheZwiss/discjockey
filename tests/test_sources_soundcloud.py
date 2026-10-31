"""The SoundCloud playlist source: link forms, parsing (D9's three policies), the reader (batched stubs, paged likes,
every error word), `expand` (short links, `you/likes`) and the registry. Offline: SoundCloud's answers are recorded
files with made-up ids, served by a fake yt-dlp SoundCloud extractor behind a fake `yt_dlp.YoutubeDL`."""
import json
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path

import pytest
import yt_dlp

from discjockey import pacing, sources
from discjockey.events import Cancelled, CancelToken
from discjockey.library import SupportPaths
from discjockey.models import FetchedPlaylist, PlaylistInfo, PlaylistLine, SourceTrack
from discjockey.settings import Settings, save_settings
from discjockey.sources import LoginState, SourceError
from discjockey.sources import soundcloud as source

FIXTURES = Path(__file__).parent / "fixtures" / "soundcloud"
API = "https://api-v2.soundcloud.com/"
SET_ID = "example-label/sets/example-set"
LINE = PlaylistLine("House", SET_ID, 3, "soundcloud")
LIKES_LINE = PlaylistLine("Likes", "example-dj/likes", 4, "soundcloud")
YOU_LINE = PlaylistLine("Mine", "you/likes", 5, "soundcloud")
UNREADABLE_FETCH = ("playlists.txt line 3 (House): SoundCloud doesn't show this playlist. It may be private or removed; "
                    "for a private set, use its private share link. Check the link, or put # in front of the line.")
UNREADABLE_INFO = ("SoundCloud doesn't show this playlist. It may be private or removed; for a private set, use its "
                   "private share link.")
SLOW_DOWN = "SoundCloud asked Discjockey to slow down. Try again in an hour."
W8 = ("To read your own likes, use your profile's likes link: on SoundCloud, open your profile, click Likes and copy "
      "the address (soundcloud.com/your-name/likes).")


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class HTTPFailure(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP Error {status}")
        self.status = status


class ExtractorFailure(Exception):
    """yt-dlp's ExtractorError as far as the source reads it: the HTTP failure is its `cause`."""

    def __init__(self, status):
        super().__init__(f"[soundcloud] https://example.invalid/x: Unable to download JSON metadata: HTTP Error {status}")
        self.cause = HTTPFailure(status)


class World:
    """Everything the fake yt-dlp serves and records."""

    def __init__(self):
        self.calls = []          # (url, query, headers, kwargs) of every API request
        self.created = []        # the options of every YoutubeDL
        self.failures = {}       # url substring -> exception to raise
        self.on_call = None      # called with the number of calls so far
        self.login_headers = {"Authorization": "OAuth example"}
        self.cookie_error = None
        self.initialize_error = None
        self.set_resolve = fixture("set_resolve.json")

    def serve(self, url, query):
        for part, error in self.failures.items():
            if part in url:
                raise error
        if url.startswith(API + "resolve?url="):
            target = url.split("resolve?url=")[1]
            if "/sets/" in target:
                return self.set_resolve
            return fixture("user_resolve.json")
        if url == API + "tracks":
            ids = query["ids"].split(",")
            return [t for t in fixture("tracks_batch1.json") + fixture("tracks_batch2.json") if str(t["id"]) in ids]
        if url == API + "me":
            return fixture("me.json")
        if "/track_likes" in url:
            return fixture("likes_page2.json" if "offset=" in url else "likes_page1.json")
        raise AssertionError(f"unexpected request {url}")


class FakeIE:
    _API_V2_BASE = API
    _browser_impersonate_target = True

    def __init__(self, world, headers):
        self.world, self._HEADERS = world, headers

    @staticmethod
    def _resolv_url(url):
        return API + "resolve?url=" + url

    def initialize(self):
        if self.world.initialize_error:
            raise self.world.initialize_error

    def _call_api(self, url, video_id, query=None, headers=None, **kwargs):
        world = self.world
        world.calls.append((url, dict(query or {}), headers, kwargs))
        if world.on_call:
            world.on_call(len(world.calls))
        return world.serve(url, dict(query or {}))


class FakeYDL:
    def __init__(self, world, opts):
        self.world, self.opts, self.closed = world, opts, False

    def get_info_extractor(self, key):
        assert key == "SoundcloudUser"
        logged_in = "cookiesfrombrowser" in self.opts
        return FakeIE(self.world, dict(self.world.login_headers) if logged_in else {})

    def close(self):
        self.closed = True


@pytest.fixture
def world(monkeypatch):
    w = World()
    ydls = []

    def factory(opts):
        if "cookiesfrombrowser" in opts and w.cookie_error:
            raise w.cookie_error
        w.created.append(opts)
        ydl = FakeYDL(w, opts)
        ydls.append(ydl)
        return ydl

    monkeypatch.setattr(yt_dlp, "YoutubeDL", factory)
    w.ydls = ydls
    return w


@pytest.fixture
def paths(tmp_path):
    return SupportPaths(support=tmp_path / ".support")


def with_account(paths, browser="chrome", profile=None):
    paths.support.mkdir(parents=True, exist_ok=True)
    save_settings(paths.settings_file, Settings().with_account("soundcloud", browser, profile))


def read(paths, line=LINE, want_info=False, token=None):
    with source.open(paths, token or CancelToken()) as reader:
        reader.want_info = want_info
        return reader.fetch(line)


# --- 2.1 recognise ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("link,expected", [
    ("https://soundcloud.com/Example-Label/sets/Example-Set", "example-label/sets/example-set"),
    ("https://www.soundcloud.com/example-label/sets/example-set/", "example-label/sets/example-set"),
    ("https://m.soundcloud.com/example-label/sets/example-set?si=abc&utm_source=clipboard",
     "example-label/sets/example-set"),
    ("http://soundcloud.com/example-label/sets/example-set#top", "example-label/sets/example-set"),
    ("https://soundcloud.com/example-label/sets/charts-top:hiphop", "example-label/sets/charts-top:hiphop"),
    ("https://soundcloud.com/Example-Label/sets/Example-Set/s-AbC123xyZ?si=1",
     "example-label/sets/example-set/s-AbC123xyZ"),
    ("https://soundcloud.com/Example-DJ/likes", "example-dj/likes"),
    ("https://www.soundcloud.com/example-dj/likes/?si=1", "example-dj/likes"),
    ("https://soundcloud.com/you/likes", "you/likes"),
    ("https://soundcloud.com/example_dj/likes", "example_dj/likes"),
])
def test_recognise_each_form(link, expected):
    assert source.recognise(link) == expected


@pytest.mark.parametrize("link", [
    "https://soundcloud.com/example-label/example-track",               # a track
    "https://soundcloud.com/example-label/example-track?in=example-label/sets/example-set",
    "https://soundcloud.com/example-label",                             # a user page
    "https://soundcloud.com/example-label/albums",
    "https://soundcloud.com/example-label/reposts",
    "https://soundcloud.com/example-label/sets",                        # all of a user's sets
    "https://soundcloud.com/discover/sets/charts-top:hiphop",           # changes daily
    "https://on.soundcloud.com/AbCd123",                                # a short link is expand's
    "https://open.spotify.com/playlist/0DiscjockeyExampleList",
    "https://open.qobuz.com/playlist/900000001",
    "https://example.com/example-label/sets/example-set",
    "soundcloud.com/example-label/sets/example-set",
    "",
])
def test_recognise_refuses_everything_else(link):
    assert source.recognise(link) is None


def test_canonical_link_and_the_secret_token_keeps_its_case():
    assert source.canonical_link("example-label/sets/example-set/s-AbC") == (
        "https://soundcloud.com/example-label/sets/example-set/s-AbC")
    assert source.canonical_link("example-dj/likes") == "https://soundcloud.com/example-dj/likes"


def test_login_state_needs_no_login(paths):
    state = source.login_state(paths)
    assert state == LoginState("not_needed") and state.connected


# --- 2.4 parsing -----------------------------------------------------------------------------------------------

def test_parse_a_plain_upload_splits_the_title():
    t = source.parse_track(fixture("set_resolve.json")["tracks"][0])
    assert t == SourceTrack(
        id="900000101", title="Example Title", artists=("Example Artist",), album="",
        image_url="https://i1.sndcdn.com/artworks-example900000101-t500x500.jpg", duration_ms=200500, isrc=None,
        service="soundcloud", link="https://soundcloud.com/example-label/example-track-900000101",
        streamable=True, account_only=False)


def test_parse_publisher_metadata_wins():
    t = source.parse_track(fixture("set_resolve.json")["tracks"][1])
    assert t.artists == ("Example Artist",) and t.title == "Example Title (Original Mix)"
    assert t.album == "Example Album" and t.isrc == "XX0001300001"
    # no artwork: the uploader's avatar, at 500 px
    assert t.image_url == "https://i1.sndcdn.com/avatars-example900000010-t500x500.jpg"
    assert t.streamable and not t.account_only  # MONETIZE plays


def test_parse_policy_block_is_not_streamable():
    t = source.parse_track(fixture("set_resolve.json")["tracks"][2])
    assert t.streamable is False and t.account_only is False and t.title == "Blocked Title"


def test_parse_policy_snip_is_account_only_and_uses_the_full_length():
    t = source.parse_track(fixture("tracks_batch1.json")[0])
    assert t.account_only is True and t.streamable is True
    assert t.duration_ms == 215000  # full_duration, not the 30 s preview


def test_parse_length_falls_back_to_duration():
    obj = {**fixture("set_resolve.json")["tracks"][0], "full_duration": None}
    assert source.parse_track(obj).duration_ms == 200000


def test_parse_without_permalink_the_player_link_stands_in():
    obj = {**fixture("set_resolve.json")["tracks"][0], "permalink_url": None}
    assert source.parse_track(obj).link == "https://w.soundcloud.com/player/?url=https%3A//api.soundcloud.com/tracks/900000101"


@pytest.mark.parametrize("obj,text", [
    ({"title": "No id"}, "A track SoundCloud no longer shows"),
    ({}, "A track SoundCloud no longer shows"),
    (None, "A track SoundCloud no longer shows"),
])
def test_parse_an_entry_without_an_id_is_skipped(obj, text):
    assert source.parse_track(obj) == text


# --- 2.3 the reader: sets --------------------------------------------------------------------------------------

def test_a_set_reads_in_batches_of_fifty_and_keeps_the_order(world, paths):
    fetched = read(paths)
    assert isinstance(fetched, FetchedPlaylist) and fetched.info is None
    ids = [t.id for t in fetched.tracks]
    assert ids[:3] == ["900000101", "900000102", "900000103"]
    assert ids[3:] == [str(900000200 + n) for n in range(1, 60)]  # the set's order, not the answers'
    assert fetched.skipped == ["A track SoundCloud no longer shows (ID 900000260)"]
    urls = [c[0] for c in world.calls]
    assert urls == [API + "resolve?url=https://soundcloud.com/" + SET_ID, API + "tracks", API + "tracks"]
    first, second = world.calls[1][1], world.calls[2][1]
    assert len(first["ids"].split(",")) == 50 and len(second["ids"].split(",")) == 10
    assert first["playlistId"] == second["playlistId"] == "900000001"
    assert "playlistSecretToken" not in first
    assert fetched.tracks[3].account_only  # the SNIP in the first batch


def test_the_reader_is_anonymous(world, paths):
    read(paths)
    assert len(world.created) == 1 and "cookiesfrombrowser" not in world.created[0]
    assert all(call[2] == {} for call in world.calls)  # no Authorization even if another extractor set one
    assert all(y.closed for y in world.ydls)


def test_a_private_set_passes_its_secret_token(world, paths):
    line = PlaylistLine("House", SET_ID + "/s-AbC123", 3, "soundcloud")
    read(paths, line)
    assert world.calls[0][0] == API + "resolve?url=https://soundcloud.com/" + SET_ID + "/s-AbC123"
    assert world.calls[1][1]["playlistSecretToken"] == "s-AbC123"


def test_a_small_set_needs_no_batch(world, paths):
    world.set_resolve = {**world.set_resolve, "tracks": world.set_resolve["tracks"][:3]}
    fetched = read(paths)
    assert len(fetched.tracks) == 3 and [c[0] for c in world.calls] == [world.calls[0][0]]


def test_want_info_fills_the_info_from_the_first_answer(world, paths):
    fetched = read(paths, want_info=True)
    assert fetched.info == PlaylistInfo(
        "soundcloud", SET_ID, "Example Set", "900000010", "Example Label", False,
        "https://i1.sndcdn.com/artworks-exampleset-t500x500.jpg", 63, False, True)
    assert len(world.calls) == 3  # no extra request


def test_info_is_one_request(world, paths):
    with source.open(paths, CancelToken()) as reader:
        info = reader.info(SET_ID)
    assert info.name == "Example Set" and info.owner_name == "Example Label" and info.track_count == 63
    assert len(world.calls) == 1


def test_a_set_without_artwork_takes_its_first_tracks(world, paths):
    world.set_resolve = {**world.set_resolve, "artwork_url": None}
    with source.open(paths, CancelToken()) as reader:
        assert reader.info(SET_ID).image_url == "https://i1.sndcdn.com/artworks-example900000101-t500x500.jpg"


# --- 2.3 the reader: likes -------------------------------------------------------------------------------------

def test_likes_page_through_next_href(world, paths):
    fetched = read(paths, LIKES_LINE, want_info=True)
    assert [t.id for t in fetched.tracks] == ["900000301", "900000302", "900000303"]
    assert fetched.skipped == ["A track SoundCloud no longer shows"]  # a like whose track is gone
    urls = [c[0] for c in world.calls]
    assert urls[0] == API + "resolve?url=https://soundcloud.com/example-dj"
    assert urls[1] == API + "users/900000020/track_likes"
    assert world.calls[1][1] == {"limit": 200, "linked_partitioning": "1"}
    assert "offset=" in urls[2] and world.calls[2][1] == {}  # the cursor is in the address
    assert len(urls) == 3
    assert all(c[2] == {} for c in world.calls)
    assert all(c[3].get("impersonate") is True for c in world.calls[1:])  # yt-dlp's own impersonation target
    assert fetched.info.name == "Example DJ's likes" and fetched.info.owner_name == "Example DJ"
    assert fetched.info.track_count == 4 and fetched.info.yours is False and fetched.info.readable
    assert fetched.info.image_url == "https://i1.sndcdn.com/artworks-example900000301-t500x500.jpg"


def test_likes_info_needs_only_the_user(world, paths):
    with source.open(paths, CancelToken()) as reader:
        info = reader.info("example-dj/likes")
    assert info.name == "Example DJ's likes" and info.track_count is None and len(world.calls) == 1


def test_a_like_listed_by_id_only_is_fetched(world, paths, monkeypatch):
    page = fixture("likes_page2.json")
    page["collection"][1] = {"kind": "like", "track": {"id": 900000201, "kind": "track"}}
    monkeypatch.setattr(world, "serve", lambda url, query: page if "offset=" in url else (
        fixture("likes_page1.json") if "track_likes" in url else World.serve(world, url, query)))
    fetched = read(paths, LIKES_LINE)
    assert fetched.tracks[-1].id == "900000201" and fetched.skipped == []
    assert "playlistId" not in world.calls[-1][1]


# --- 2.3 errors ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("status", [401, 403, 404])
def test_an_unreadable_set_says_so(world, paths, status):
    world.failures["resolve"] = ExtractorFailure(status)
    with pytest.raises(SourceError) as e:
        read(paths)
    assert (str(e.value), e.value.kind, e.value.service) == (UNREADABLE_FETCH, "playlist_unreadable", "soundcloud")
    with source.open(paths, CancelToken()) as reader, pytest.raises(SourceError) as e:
        reader.info(SET_ID)
    assert (str(e.value), e.value.kind) == (UNREADABLE_INFO, "playlist_unreadable")


def test_an_answer_with_errors_or_another_kind_is_unreadable(world, paths):
    world.set_resolve = {"errors": [{"error_message": "404 - Not Found"}]}
    with pytest.raises(SourceError) as e:
        read(paths)
    assert e.value.kind == "playlist_unreadable"
    world.set_resolve = {"kind": "track", "id": 5}
    with pytest.raises(SourceError) as e:
        read(paths)
    assert e.value.kind == "playlist_unreadable"


def test_an_unknown_likes_user_is_unreadable(world, paths):
    world.failures["resolve"] = ExtractorFailure(404)
    with pytest.raises(SourceError) as e:
        read(paths, LIKES_LINE)
    assert e.value.kind == "playlist_unreadable" and "likes" not in str(e.value).split("(")[0]


def test_a_refused_batch_is_unreadable(world, paths):
    world.failures["/tracks"] = ExtractorFailure(403)
    with pytest.raises(SourceError) as e:
        read(paths)
    assert str(e.value) == UNREADABLE_FETCH


def test_too_many_requests_says_slow_down(world, paths):
    world.failures["resolve"] = ExtractorFailure(429)
    with pytest.raises(SourceError) as e:
        read(paths)
    assert (str(e.value), e.value.kind, e.value.service) == (SLOW_DOWN, "offline", "soundcloud")


def test_trouble_in_a_later_request_names_the_kind_of_error_only(world, paths):
    world.failures["/tracks"] = TimeoutError("https://secret.example/x?token=abc timed out")
    with pytest.raises(SourceError) as e:
        read(paths)
    assert str(e.value) == "SoundCloud is not responding (TimeoutError). Try again later."
    assert e.value.kind == "offline" and "secret" not in str(e.value)


def test_a_failing_start_says_soundcloud_is_not_responding(world, paths):
    world.initialize_error = OSError("https://example.invalid/client-id failed")
    with pytest.raises(SourceError) as e:
        source.open(paths, CancelToken())
    assert str(e.value) == "SoundCloud is not responding (OSError). Try again later."
    assert e.value.kind == "offline" and world.ydls[0].closed


def test_stop_between_requests(world, paths):
    token = CancelToken()
    world.on_call = lambda n: token.cancel() if n == 2 else None
    with pytest.raises(Cancelled):
        read(paths, token=token)
    assert len(world.calls) == 2  # the second batch was never asked for
    assert all(y.closed for y in world.ydls)


def test_stop_before_the_first_request(world, paths):
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        source.open(paths, token)
    assert world.calls == []


def test_a_read_uses_no_pacer_and_no_budget(world, paths, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a read must not touch the download protection")

    monkeypatch.setattr(pacing, "Pacer", boom)
    monkeypatch.setattr(pacing, "Budget", boom)
    assert read(paths).tracks
    assert not hasattr(source, "pacing") and not hasattr(source, "Pacer") and not hasattr(source, "Budget")


# --- 2.2 / 2.3 your own likes ----------------------------------------------------------------------------------

def test_your_likes_read_through_the_login(world, paths):
    with_account(paths, "chrome", "Profile 2")
    fetched = read(paths, YOU_LINE, want_info=True)
    assert [t.id for t in fetched.tracks] == ["900000301", "900000302", "900000303"]
    login_opts = [o for o in world.created if "cookiesfrombrowser" in o]
    assert len(login_opts) == 1 and login_opts[0]["cookiesfrombrowser"] == ("chrome", "Profile 2", None, None)
    assert world.calls[0][0] == API + "me" and world.calls[0][2] == {"Authorization": "OAuth example"}
    assert world.calls[1][0] == API + "users/900000030/track_likes"  # me's id, no user lookup
    assert all(c[2].get("Authorization") for c in world.calls)
    assert fetched.info.name == "Example Me's likes" and all(y.closed for y in world.ydls)


def test_your_likes_without_the_account(world, paths):
    with pytest.raises(SourceError) as e:
        read(paths, YOU_LINE)
    assert (str(e.value), e.value.kind, e.value.service) == (W8, "playlist_unreadable", "soundcloud")
    assert not any("cookiesfrombrowser" in o for o in world.created)


def test_your_likes_with_a_login_that_is_not_accepted(world, paths):
    with_account(paths, "firefox")
    expected = ("SoundCloud didn't accept the login from Firefox. Log in to SoundCloud there, or use your profile's "
                "likes link (soundcloud.com/your-name/likes).")
    for setup in (lambda: setattr(world, "cookie_error", RuntimeError("could not find firefox cookies database")),
                  lambda: (setattr(world, "cookie_error", None), setattr(world, "login_headers", {})),
                  lambda: (setattr(world, "login_headers", {"Authorization": "OAuth example"}),
                           world.failures.update({"/me": ExtractorFailure(401)}))):
        setup()
        with pytest.raises(SourceError) as e:
            read(paths, YOU_LINE)
        assert (str(e.value), e.value.kind, e.value.service) == (expected, "login_expired", "soundcloud")
    assert all(y.closed for y in world.ydls)


# --- 2.2 expand ------------------------------------------------------------------------------------------------

def test_expand_follows_a_short_link_once(paths, monkeypatch):
    seen = []
    monkeypatch.setattr(source, "_redirect_target", lambda url: seen.append(url) or
                        "https://soundcloud.com/Example-Label/sets/Example-Set/s-AbC?si=1&utm_source=clipboard")
    out = source.expand("https://on.soundcloud.com/AbCd123", paths, CancelToken())
    assert out == "https://soundcloud.com/example-label/sets/example-set/s-AbC"
    assert seen == ["https://on.soundcloud.com/AbCd123"]


def test_expand_leaves_a_short_link_to_a_track_alone(paths, monkeypatch):
    monkeypatch.setattr(source, "_redirect_target", lambda url: "https://soundcloud.com/example-label/example-track")
    link = "https://on.soundcloud.com/AbCd123"
    assert source.expand(link, paths, CancelToken()) == link
    monkeypatch.setattr(source, "_redirect_target", lambda url: None)
    assert source.expand(link, paths, CancelToken()) == link


def test_expand_short_link_errors(paths, monkeypatch):
    def fail(error):
        def go(url):
            raise error
        return go

    monkeypatch.setattr(source, "_redirect_target", fail(urllib.error.URLError("https://example.invalid down")))
    with pytest.raises(SourceError) as e:
        source.expand("https://on.soundcloud.com/AbCd123", paths, CancelToken())
    assert str(e.value) == "SoundCloud is not responding (URLError). Try again later." and e.value.kind == "offline"
    monkeypatch.setattr(source, "_redirect_target",
                        fail(urllib.error.HTTPError("https://on.soundcloud.com/x", 429, "Too Many Requests", Message(), None)))
    with pytest.raises(SourceError) as e:
        source.expand("https://on.soundcloud.com/AbCd123", paths, CancelToken())
    assert str(e.value) == SLOW_DOWN and e.value.kind == "offline"


def test_the_redirect_request_stops_at_the_first_answer(monkeypatch):
    headers = Message()
    headers["Location"] = "https://soundcloud.com/example-label/sets/example-set"
    requests = []

    class Opener:
        def open(self, request, timeout):
            requests.append((request.full_url, request.get_header("User-agent"), timeout))
            raise urllib.error.HTTPError(request.full_url, 302, "Found", headers, None)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: Opener())
    assert source._redirect_target("https://on.soundcloud.com/AbCd123") == headers["Location"]
    assert requests == [("https://on.soundcloud.com/AbCd123", source.USER_AGENT, 10)]


def test_expand_your_likes_with_the_login(world, paths):
    with_account(paths)
    out = source.expand("https://soundcloud.com/you/likes?si=1", paths, CancelToken())
    assert out == "https://soundcloud.com/example-me/likes"
    assert [c[0] for c in world.calls] == [API + "me"] and all(y.closed for y in world.ydls)


def test_expand_your_likes_without_the_account_or_with_a_bad_login(world, paths):
    with pytest.raises(SourceError) as e:
        source.expand("https://soundcloud.com/you/likes", paths, CancelToken())
    assert (str(e.value), e.value.kind) == (W8, "playlist_unreadable")
    with_account(paths, "safari")
    world.cookie_error = RuntimeError("could not read the cookies: keychain")
    with pytest.raises(SourceError) as e:
        source.expand("https://soundcloud.com/you/likes", paths, CancelToken())
    assert e.value.kind == "login_expired" and "Safari" in str(e.value)


@pytest.mark.parametrize("link", [
    "https://soundcloud.com/example-label/sets/example-set",
    "https://soundcloud.com/example-dj/likes",
    "https://open.spotify.com/playlist/0DiscjockeyExampleList",
    "https://example.com/anything",
    "not a link",
])
def test_expand_returns_every_other_link_as_it_is(paths, link):
    assert source.expand(link, paths, CancelToken()) == link


# --- 2.5 the registry ------------------------------------------------------------------------------------------

def test_the_registry_routes_soundcloud_links():
    assert sources.recognise("https://soundcloud.com/Example-Label/sets/Example-Set") == ("soundcloud", SET_ID)
    assert sources.SOURCES["soundcloud"] is source and source.SERVICE == "soundcloud"


def test_the_registry_expands_a_short_link_before_recognising_it(paths, monkeypatch):
    monkeypatch.setattr(source, "_redirect_target", lambda url: "https://soundcloud.com/example-label/sets/example-set")
    link = sources.expand("https://on.soundcloud.com/AbCd123", paths, CancelToken())
    assert link == "https://soundcloud.com/example-label/sets/example-set"
    assert sources.recognise(link) == ("soundcloud", SET_ID)


def test_a_registry_read_needs_no_login(world, paths):
    fetched = sources.read(paths, [LINE], want_info=True)
    assert len(fetched) == 1 and fetched[0].info.name == "Example Set"
    infos = {}
    sources.read_infos(paths, ["soundcloud:" + SET_ID], infos, CancelToken())
    assert infos["soundcloud:" + SET_ID].owner_name == "Example Label"
