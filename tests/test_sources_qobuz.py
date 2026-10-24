"""The Qobuz playlist source: link forms, the local login check, the reader (own 500-track paging, every error kind and
word, Stop), parsing and the registry. Offline: the responses are recorded files built from streamrip's parser and
Qobuz's documented fields (made-up ids), served by a fake client behind a real QobuzSource."""
import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest

from discjockey import qobuz, sources
from discjockey.events import Cancelled, CancelToken
from discjockey.library import SupportPaths
from discjockey.models import FetchedPlaylist, PlaylistInfo, PlaylistLine, SourceTrack
from discjockey.sources import LoginState, SourceError
from discjockey.sources import qobuz as source

FIXTURES = Path(__file__).parent / "fixtures" / "qobuz"
NOT_SET_UP = "Your playlists include a Qobuz playlist, but Qobuz isn't set up yet. Run: discjockey setup"
UNREADABLE = ("playlists.txt line 3 (House): Qobuz doesn't show this playlist. It must be public or one of yours. "
              "Check the link, or put # in front of the line.")
LINE = PlaylistLine("House", "900000001", 3, "qobuz")


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class FakeClient:
    """streamrip's QobuzClient as far as the reader uses it: `_api_request` and the config's app id. `answers` is a
    list of (status, body) taken in order; a body that is an Exception is raised, a coroutine function awaited."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []
        self.config = SimpleNamespace(session=SimpleNamespace(qobuz=SimpleNamespace(app_id=123456789)))

    async def _api_request(self, epoint, params):
        self.calls.append((epoint, dict(params)))
        status, body = self.answers.pop(0)
        if isinstance(body, BaseException):
            raise body
        if callable(body):
            await body()
        return status, body


async def hang():
    await asyncio.sleep(60)


@pytest.fixture
def make_reader():
    """A QobuzReader over a real QobuzSource (so `_call`'s timeout and Stop apply) and a fake client."""
    opened = []

    def make(*answers, check=lambda: None):
        client = FakeClient(*answers)
        src = qobuz.QobuzSource(client, asyncio.Runner(), check=check)
        opened.append(src)
        return source.QobuzReader(src), client

    yield make
    for src in opened:
        try:
            src.runner.close()
        except Exception:
            pass


@pytest.fixture
def support(tmp_path):
    return SupportPaths(support=tmp_path / ".support")


@pytest.fixture
def small_pages(monkeypatch):
    monkeypatch.setattr(source, "PAGE_SIZE", 4)  # the page fixtures hold 4 + 1 tracks


@pytest.fixture
def fast_clock(monkeypatch):
    monkeypatch.setattr(qobuz, "CALL_TIMEOUT_S", 0.3)
    monkeypatch.setattr(qobuz, "STOP_POLL_S", 0.02)


# --- 3.1 recognise ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("link", [
    "https://open.qobuz.com/playlist/900000001",
    "https://play.qobuz.com/playlist/900000001",
    "https://listen.qobuz.com/playlist/900000001",
    "http://open.qobuz.com/playlist/900000001/",
    "https://open.qobuz.com/playlist/900000001?utm_source=share",
    "https://open.qobuz.com/playlist/900000001#top",
    "https://open.qobuz.com/playlist/900000001/tracks",
    "https://www.qobuz.com/gb-en/playlists/example-playlist/900000001",
    "https://www.qobuz.com/fr-fr/playlists/example-playlist/900000001?x=1",
])
def test_recognise_every_playlist_link_form(link):
    assert source.recognise(link) == "900000001"


@pytest.mark.parametrize("link", [
    "https://open.qobuz.com/album/0000000000001",
    "https://open.qobuz.com/track/900000101",
    "https://www.qobuz.com/gb-en/album/example-album/0000000000001",
    "https://open.qobuz.com/playlist/",
    "https://open.qobuz.com/playlist/abc",
    "https://example.com/playlist/900000001",
    "https://open.spotify.com/playlist/0DiscjockeyExampleList",
    "spotify:playlist:0DiscjockeyExampleList",
    "",
])
def test_recognise_refuses_everything_else(link):
    assert source.recognise(link) is None


def test_canonical_link_round_trips():
    assert source.canonical_link("900000001") == "https://open.qobuz.com/playlist/900000001"
    assert source.recognise(source.canonical_link("900000001")) == "900000001"
    assert source.SERVICE == "qobuz"


# --- 3.2 login state -------------------------------------------------------------------------------------------

def write_config(support, text):
    path = qobuz.config_file(support)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_login_state_is_a_local_check_of_the_saved_login(support, monkeypatch):
    monkeypatch.setattr(qobuz, "QobuzSource", None)  # a login check never opens a session
    assert source.login_state(support) == LoginState("missing", NOT_SET_UP)  # no file
    write_config(support, '[qobuz]\nemail_or_userid = ""\npassword_or_token = ""\n')
    assert source.login_state(support).state == "missing"  # the file Setup starts with, before a login
    write_config(support, '[qobuz]\nemail_or_userid = "dj@example.com"\npassword_or_token = ""\n')
    assert source.login_state(support).state == "missing"
    write_config(support, "[downloads]\nfolder = 'x'\n")
    assert source.login_state(support).state == "missing"  # no qobuz section
    write_config(support, "this is = = not toml")
    assert source.login_state(support).state == "missing"
    write_config(support, '[qobuz]\nemail_or_userid = "dj@example.com"\npassword_or_token = "5f4dcc3b5aa765d61d8327deb882cf99"\n')
    assert source.login_state(support) == LoginState("ok")


def test_login_state_agrees_with_what_setup_writes(support):
    qobuz.write_config(support)  # Setup's first step: defaults, no login yet
    assert source.login_state(support).state == "missing"


# --- 3.4 parsing -----------------------------------------------------------------------------------------------

def test_parse_item_reads_every_field():
    t = source.parse_item(fixture("playlist_page1.json")["tracks"]["items"][0])
    assert t == SourceTrack(
        id="900000101", title="Example Title (Extended Mix)", artists=("Example Artist",), album="Example Album",
        image_url="https://static.example.com/covers/900000101_600.jpg", duration_ms=372000, isrc="XXEXA2600001",
        service="qobuz", link="https://open.qobuz.com/track/900000101", streamable=True)
    assert t.key == "qobuz:900000101"


def test_parse_item_falls_back_to_the_album_artist_and_tolerates_missing_fields():
    t = source.parse_item(fixture("playlist_page1.json")["tracks"]["items"][2])
    assert t.artists == ("Various Example Artists",) and t.isrc is None and t.image_url is None
    bare = source.parse_item({"id": 5, "title": "Bare"})
    assert (bare.artists, bare.album, bare.duration_ms, bare.isrc, bare.streamable) == ((), "", 0, None, True)


def test_a_preview_only_item_stays_in_the_list_marked():
    t = source.parse_item(fixture("playlist_page1.json")["tracks"]["items"][1])
    assert isinstance(t, SourceTrack) and t.streamable is False and t.id == "900000102"


def test_an_item_without_an_id_is_skipped_with_words():
    assert source.parse_item(fixture("playlist_page1.json")["tracks"]["items"][3]) == "Gone Track (no Qobuz ID)"
    assert source.parse_item({"duration": 5}) == "Unknown track (no Qobuz ID)"


# --- 3.3 the reader: fetch ---------------------------------------------------------------------------------------

def test_fetch_pages_through_a_playlist_and_keeps_order(make_reader, small_pages):
    reader, client = make_reader((200, fixture("playlist_page1.json")), (200, fixture("playlist_page2.json")))
    got = reader.fetch(LINE)
    assert isinstance(got, FetchedPlaylist) and got.line is LINE
    assert [t.id for t in got.tracks] == ["900000101", "900000102", "900000103", "900000104"]
    assert got.skipped == ["Gone Track (no Qobuz ID)"]
    assert [t.streamable for t in got.tracks] == [True, False, True, True]
    # the app id is passed explicitly: streamrip's _api_request adds only the X-App-Id header, not the parameter
    assert client.calls == [
        ("playlist/get", {"app_id": "123456789", "playlist_id": "900000001", "extra": "tracks", "limit": 4,
                          "offset": 0}),
        ("playlist/get", {"app_id": "123456789", "playlist_id": "900000001", "extra": "tracks", "limit": 4,
                          "offset": 4}),
    ]


def item(i):
    return {"id": 900100000 + i, "title": f"Track {i}", "duration": 200, "streamable": True,
            "performer": {"name": "Example Artist"}, "album": {"title": "Example Album"}}


def test_a_501_track_playlist_takes_two_requests_of_500():
    # streamrip's get_metadata would stop at 500 tracks
    first = {"tracks": {"total": 501, "items": [item(i) for i in range(500)]}}
    second = {"tracks": {"total": 501, "items": [item(500)]}}
    src = qobuz.QobuzSource(FakeClient((200, first), (200, second)), asyncio.Runner())
    try:
        got = source.QobuzReader(src).fetch(LINE)
        assert len(got.tracks) == 501 and got.tracks[-1].id == "900100500"
        assert [(c[1]["limit"], c[1]["offset"]) for c in src.client.calls] == [(500, 0), (500, 500)]
    finally:
        src.runner.close()


def test_a_playlist_that_fits_one_page_takes_one_request(make_reader):
    reader, client = make_reader((200, {"tracks": {"total": 2, "items": [item(1), item(2)]}}))
    assert len(reader.fetch(LINE).tracks) == 2 and len(client.calls) == 1


def test_an_empty_playlist_and_a_page_that_stops_early_end_the_read(make_reader):
    reader, _ = make_reader((200, {"tracks": {"total": 0, "items": []}}))
    assert reader.fetch(LINE) == FetchedPlaylist(LINE, [], [])
    reader, client = make_reader((200, {"tracks": {"total": 900, "items": []}}))  # Qobuz promises more, sends none
    assert reader.fetch(LINE).tracks == [] and len(client.calls) == 1
    reader, _ = make_reader((200, {"name": "No tracks key"}))
    assert reader.fetch(LINE).tracks == []


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_fetch_of_a_playlist_qobuz_does_not_show(make_reader, status):
    reader, _ = make_reader((status, fixture("private.json")))
    with pytest.raises(SourceError) as e:
        reader.fetch(LINE)
    assert (e.value.kind, e.value.service, str(e.value)) == ("playlist_unreadable", "qobuz", UNREADABLE)


def test_fetch_when_qobuz_answers_with_another_status(make_reader):
    reader, _ = make_reader((500, {"message": "oops"}))
    with pytest.raises(SourceError) as e:
        reader.fetch(LINE)
    assert (e.value.kind, e.value.service) == ("offline", "qobuz")
    assert str(e.value) == "Qobuz is not responding (HTTP 500). Try again later."


def test_fetch_when_a_later_page_fails_nothing_partial_is_returned(make_reader, small_pages):
    reader, _ = make_reader((200, fixture("playlist_page1.json")), (503, {}))
    with pytest.raises(SourceError) as e:
        reader.fetch(LINE)
    assert e.value.kind == "offline"


def test_fetch_when_the_connection_fails_names_only_the_kind_of_error(make_reader):
    reader, _ = make_reader((0, aiohttp.ClientConnectionError("https://example.com/?user_auth_token=secret")))
    with pytest.raises(SourceError) as e:
        reader.fetch(LINE)
    assert (e.value.kind, str(e.value)) == (
        "offline", "Qobuz is not responding (ClientConnectionError). Try again later.")
    assert "secret" not in str(e.value)


def test_fetch_when_qobuz_sends_something_that_is_not_json(make_reader):
    reader, _ = make_reader((200, ValueError("Attempt to decode JSON with unexpected mimetype")))
    with pytest.raises(SourceError) as e:
        reader.fetch(LINE)
    assert str(e.value) == "Qobuz is not responding (ValueError). Try again later."


@pytest.mark.usefixtures("fast_clock")
def test_fetch_when_qobuz_does_not_answer_in_time(make_reader):
    reader, _ = make_reader((200, hang))
    with pytest.raises(SourceError) as e:
        reader.fetch(LINE)
    assert e.value.kind == "offline"
    assert str(e.value) == "Qobuz is not responding (Qobuz did not answer within 0.3 seconds). Try again later."


def test_stop_during_a_page_ends_the_read_and_is_not_a_source_error(make_reader, monkeypatch):
    monkeypatch.setattr(qobuz, "STOP_POLL_S", 0.02)  # the 30 s timeout stays: Stop must not wait for it
    token = CancelToken()
    reader, _ = make_reader((200, hang), check=token.check)
    threading.Timer(0.1, token.cancel).start()
    with pytest.raises(Cancelled):
        reader.fetch(LINE)


def test_stop_before_a_page_sends_no_request(make_reader):
    token = CancelToken()
    token.cancel()
    reader, client = make_reader((200, {}), check=token.check)
    with pytest.raises(Cancelled):
        reader.fetch(LINE)
    assert client.calls == []


def test_a_read_touches_no_download_protection(make_reader, monkeypatch):
    """Reads are not downloads: no pacing, no budget, no usage, no auto-stop. The reader is built from the source
    alone, and a failed read is an error to show, never a failure to count."""
    import discjockey.sources.qobuz as module
    assert not any(hasattr(module, name) for name in ("Pacer", "Budget", "Acquirer", "budget", "pacer"))
    reader, _ = make_reader((200, fixture("playlist_page2.json")), (404, fixture("private.json")))
    reader.fetch(LINE)
    with pytest.raises(SourceError):
        reader.fetch(LINE)


# --- 3.3 / 3.4 the reader: info ----------------------------------------------------------------------------------

def test_info_reads_the_playlist_page(make_reader):
    reader, client = make_reader((200, fixture("playlist_info.json")))
    assert reader.info("900000001") == PlaylistInfo(
        service="qobuz", id="900000001", name="Example Playlist", owner_id="700000001", owner_name="Example Owner",
        collaborative=False, image_url="https://static.example.com/playlists/900000001_300.jpg", track_count=5,
        yours=False, readable=True)
    assert client.calls == [("playlist/get", {"app_id": "123456789", "playlist_id": "900000001"})]


def test_info_tolerates_a_bare_answer_and_picks_the_largest_cover_present(make_reader):
    reader, _ = make_reader((200, {"name": "Bare", "is_collaborative": True,
                                   "image_rectangle": ["https://static.example.com/r.jpg"],
                                   "images150": ["https://static.example.com/s.jpg"]}),
                            (200, {"images150": ["https://static.example.com/s.jpg"]}), (200, {}))
    bare = reader.info("900000009")
    assert (bare.id, bare.name, bare.owner_id, bare.owner_name, bare.track_count, bare.collaborative) == (
        "900000009", "Bare", "", "", None, True)
    assert bare.image_url == "https://static.example.com/r.jpg"
    assert reader.info("900000009").image_url == "https://static.example.com/s.jpg"
    assert reader.info("900000009").image_url is None


def test_info_of_a_playlist_qobuz_does_not_show(make_reader):
    reader, _ = make_reader((404, fixture("private.json")))
    with pytest.raises(SourceError) as e:
        reader.info("900000001")
    assert (e.value.kind, e.value.service, str(e.value)) == (
        "playlist_unreadable", "qobuz",
        "Qobuz doesn't show this playlist. It must be public or one of yours. Check the link.")


def test_info_when_qobuz_is_not_answering(make_reader):
    reader, _ = make_reader((502, {}))
    with pytest.raises(SourceError) as e:
        reader.info("900000001")
    assert (e.value.kind, str(e.value)) == ("offline", "Qobuz is not responding (HTTP 502). Try again later.")


# --- 3.3 open and close ------------------------------------------------------------------------------------------

def patch_open(monkeypatch, result):
    def fake_open(paths):
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(qobuz.QobuzSource, "open", fake_open)


def test_open_logs_in_hands_stop_to_the_source_and_close_releases_it(support, monkeypatch):
    src = qobuz.QobuzSource(FakeClient(), asyncio.Runner())
    closed = []
    monkeypatch.setattr(src, "close", lambda: closed.append(1))
    patch_open(monkeypatch, src)
    token = CancelToken()
    with source.open(support, token) as reader:
        assert reader.source is src and src.check == token.check
    assert closed == [1]


def test_open_without_a_login_says_qobuz_is_not_set_up(support, monkeypatch):
    patch_open(monkeypatch, qobuz.QobuzNotSetUp("Qobuz is not set up yet. Run: discjockey setup"))
    with pytest.raises(SourceError) as e:
        source.open(support, CancelToken())
    assert (e.value.kind, e.value.service, str(e.value)) == ("not_set_up", "qobuz", NOT_SET_UP)


@pytest.mark.parametrize("error", [
    qobuz.QobuzLoginRejected("Qobuz did not accept your login. Run: discjockey setup"),
    qobuz.QobuzError("Could not log in to Qobuz (ClientConnectorError). Check the internet connection; "
                     "if it keeps happening, run: discjockey update, then discjockey setup"),
    RuntimeError("email=dj@example.com password=5f4dcc3b5aa765d61d8327deb882cf99"),
])
def test_a_login_that_fails_is_a_qobuz_login_problem_in_plain_words(support, monkeypatch, error):
    patch_open(monkeypatch, error)
    with pytest.raises(SourceError) as e:
        source.open(support, CancelToken())
    assert (e.value.kind, e.value.service) == ("qobuz_login_failed", "qobuz")
    assert str(e.value) == qobuz.login_problem(error)
    assert "5f4dcc3b" not in str(e.value) and "dj@example.com" not in str(e.value)


# --- 3.5 the registry --------------------------------------------------------------------------------------------

def test_the_registry_holds_both_services_in_order():
    assert list(sources.SOURCES) == ["spotify", "qobuz"] and sources.SOURCES["qobuz"] is source


def test_recognise_routes_a_qobuz_link_to_qobuz():
    assert sources.recognise("https://open.qobuz.com/playlist/900000001") == ("qobuz", "900000001")
    assert sources.recognise("https://open.spotify.com/playlist/0DiscjockeyExampleList") == (
        "spotify", "0DiscjockeyExampleList")


def test_a_mixed_playlists_file_reads_both_services_once_each_in_line_order(support, monkeypatch, small_pages):
    log = []

    class SpotifyReader:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            log.append(("close", "spotify"))

        def fetch(self, line):
            log.append(("fetch", "spotify", line.folder))
            return FetchedPlaylist(line, [], [])

    fake_spotify = SimpleNamespace(
        SERVICE="spotify", recognise=lambda link: None, login_state=lambda paths: LoginState("ok"),
        open=lambda paths, token: log.append(("open", "spotify")) or SpotifyReader())
    monkeypatch.setitem(sources.SOURCES, "spotify", fake_spotify)

    write_config(support, '[qobuz]\nemail_or_userid = "dj@example.com"\npassword_or_token = "5f4dcc3b5aa765d61d8327deb882cf99"\n')
    client = FakeClient((200, fixture("playlist_page1.json")), (200, fixture("playlist_page2.json")),
                        (200, {"tracks": {"total": 1, "items": [item(4)]}}))
    src = qobuz.QobuzSource(client, asyncio.Runner())
    real_close = src.close
    monkeypatch.setattr(src, "close", lambda: log.append(("close", "qobuz")) or real_close())
    monkeypatch.setattr(qobuz.QobuzSource, "open", lambda paths: log.append(("open", "qobuz")) or src)

    lines = [PlaylistLine("A", "0DiscjockeyExampleList", 1), PlaylistLine("B", "900000001", 2, "qobuz"),
             PlaylistLine("C", "900000002", 3, "qobuz")]
    fetched = sources.read(support, lines, token=CancelToken())

    assert [f.line.folder for f in fetched] == ["A", "B", "C"]
    assert [t.id for t in fetched[1].tracks] == ["900000101", "900000102", "900000103", "900000104"]
    assert [t.id for t in fetched[2].tracks] == ["900100004"]
    assert [e for e in log if e[0] == "open"] == [("open", "spotify"), ("open", "qobuz")]  # once each
    assert sorted(e for e in log if e[0] == "close") == [("close", "qobuz"), ("close", "spotify")]  # both closed


def test_a_qobuz_line_without_a_login_stops_before_any_request(support, monkeypatch):
    patch_open(monkeypatch, AssertionError("no login attempt without a saved login"))
    with pytest.raises(SourceError) as e:
        sources.read(support, [PlaylistLine("B", "900000001", 1, "qobuz")], token=CancelToken())
    assert (e.value.kind, e.value.service, str(e.value)) == ("not_set_up", "qobuz", NOT_SET_UP)
