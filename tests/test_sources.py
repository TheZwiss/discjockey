"""The source registry: which service a link belongs to, and one read over the lines of several services."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from discjockey import sources
from discjockey.events import Cancelled, CancelToken, ReadingPlaylist
from discjockey.library import SupportPaths
from discjockey.models import FetchedPlaylist, PlaylistInfo, PlaylistLine
from discjockey.sources import LoginState, SourceError, spotify
from discjockey.sources import qobuz as qobuz_source

ID1, ID2 = "0DiscjockeyExampleList", "3DiscjockeyExampleList"


class FakeReader:
    def __init__(self, log, name, fail=()):
        self.log, self.name, self.fail = log, name, set(fail)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self.log.append(("close", self.name))

    def fetch(self, line):
        self.log.append(("fetch", self.name, line.playlist_id))
        return FetchedPlaylist(line, [], [])

    def info(self, playlist_id):
        if playlist_id in self.fail:
            raise SourceError("no", "playlist_unreadable", self.name)
        return PlaylistInfo(self.name, playlist_id, "Name", "o", "Owner", False, None, 1, True, True)


def fake_source(log, name="fake", login="ok", open_error=None, fail=()):
    def open_(paths, token):
        log.append(("open", name))
        if open_error:
            raise open_error
        return FakeReader(log, name, fail)

    return SimpleNamespace(SERVICE=name, recognise=lambda link: None,
                           login_state=lambda paths: LoginState(login, "" if login == "ok" else f"{name} not set up"),
                           open=open_)


@pytest.fixture
def support(tmp_path):
    return SupportPaths(support=tmp_path / ".support")


def test_the_registry_holds_spotify_and_qobuz():
    assert list(sources.SOURCES) == ["spotify", "qobuz"]
    assert sources.SOURCES["spotify"] is spotify and sources.SOURCES["qobuz"] is qobuz_source


def test_service_list_names_every_service_in_registry_order():
    assert sources.service_list() == "Spotify, Qobuz, SoundCloud or YouTube Music"


def test_service_list_with_fewer_names(monkeypatch):
    monkeypatch.setattr(sources, "SERVICE_NAMES", {"spotify": "Spotify"})
    assert sources.service_list() == "Spotify"
    monkeypatch.setattr(sources, "SERVICE_NAMES", {"spotify": "Spotify", "qobuz": "Qobuz"})
    assert sources.service_list() == "Spotify or Qobuz"


@pytest.mark.parametrize("code", ["import discjockey.sources", "import discjockey.config, discjockey.playlists_file",
                                  "import discjockey.sources as s; s.recognise('https://example.com/x')"])
def test_the_registry_imports_without_yt_dlp(code):
    """`sources` is imported by config and playlists_file, which must not pull yt-dlp in before tools.activate().
    A fresh interpreter, because conftest.py imports yt_dlp itself."""
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run([sys.executable, "-c", f"import sys; {code}; print('yt_dlp' in sys.modules)"],
                         capture_output=True, text=True, cwd=root, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


def test_a_login_state_is_connected_unless_missing():
    assert LoginState("ok").connected and LoginState("not_needed").connected
    assert not LoginState("missing", "x").connected


def test_a_service_that_needs_no_login_reads_without_one(support, monkeypatch):
    log = []
    monkeypatch.setitem(sources.SOURCES, "fake", fake_source(log, login="not_needed"))
    fetched = sources.read(support, [PlaylistLine("A", "1", 1, "fake")])
    assert [f.line.folder for f in fetched] == ["A"] and ("open", "fake") in log


def _expanding():
    return SimpleNamespace(SERVICE="fake", recognise=lambda link: "1" if link.startswith("fake:") else None,
                           expand=lambda link, paths, token: f"{link}/expanded")


def test_expand_asks_the_source_that_recognises_the_link(support, monkeypatch):
    monkeypatch.setitem(sources.SOURCES, "fake", _expanding())
    assert sources.expand("fake:1", support, CancelToken()) == "fake:1/expanded"


def test_expand_returns_other_links_as_they_are(support, monkeypatch):
    monkeypatch.setitem(sources.SOURCES, "fake", _expanding())
    assert sources.expand("https://example.com/x", support, CancelToken()) == "https://example.com/x"
    assert sources.expand(f"spotify:playlist:{ID1}", support, CancelToken()) == f"spotify:playlist:{ID1}"  # no expand


def test_expand_passes_a_source_error_on(support, monkeypatch):
    def refuse(link, paths, token):
        raise SourceError("nope", "playlist_unreadable", "fake")

    monkeypatch.setitem(sources.SOURCES, "fake", SimpleNamespace(SERVICE="fake", recognise=lambda link: "1",
                                                                 expand=refuse))
    with pytest.raises(SourceError) as e:
        sources.expand("fake:1", support, CancelToken())
    assert (e.value.kind, e.value.service) == ("playlist_unreadable", "fake")


def test_recognise_gives_service_and_id():
    assert sources.recognise(f"https://open.spotify.com/playlist/{ID1}?si=x") == ("spotify", ID1)
    assert sources.recognise(f"spotify:playlist:{ID2}") == ("spotify", ID2)
    assert sources.recognise("https://example.com/playlist/x") is None


def test_spotify_source_interface():
    assert spotify.SERVICE == "spotify"
    assert spotify.recognise(f"spotify:playlist:{ID1}") == ID1 and spotify.recognise("nope") is None
    assert spotify.canonical_link(ID1) == f"https://open.spotify.com/playlist/{ID1}"


def test_spotify_login_state_is_a_local_file_check(support):
    state = spotify.login_state(support)
    assert state.state == "missing" and state.message == "Spotify is not set up yet. Run: discjockey setup"
    support.support.mkdir(parents=True, exist_ok=True)
    support.spotify_app.write_text(json.dumps({"client_id": "cid"}))
    assert spotify.login_state(support).state == "missing"  # the token is still missing
    support.spotify_token.write_text("{}")
    assert spotify.login_state(support) == LoginState("ok")


def test_spotify_error_is_a_source_error_of_service_spotify():
    e = spotify.SpotifyError("x", "login_expired")
    assert isinstance(e, SourceError) and (e.kind, e.service) == ("login_expired", "spotify")


def test_read_uses_the_reader_of_each_line_and_keeps_line_order(support, monkeypatch):
    log = []
    monkeypatch.setitem(sources.SOURCES, "fake", fake_source(log))
    monkeypatch.setitem(sources.SOURCES, "spotify", fake_source(log, "spotify"))
    lines = [PlaylistLine("A", "1", 1, "fake"), PlaylistLine("B", ID1, 2), PlaylistLine("C", "2", 3, "fake")]
    events = []
    fetched = sources.read(support, lines, emit=events.append, token=CancelToken())
    assert [f.line.folder for f in fetched] == ["A", "B", "C"]
    assert events == [ReadingPlaylist(1, 3, "A"), ReadingPlaylist(2, 3, "B"), ReadingPlaylist(3, 3, "C")]
    assert [e for e in log if e[0] == "open"] == [("open", "fake"), ("open", "spotify")]  # first-line order, once each
    assert [e[:2] for e in log if e[0] == "fetch"] == [("fetch", "fake"), ("fetch", "spotify"), ("fetch", "fake")]
    assert sorted(e for e in log if e[0] == "close") == [("close", "fake"), ("close", "spotify")]


def test_a_missing_login_stops_before_any_reader_opens(support, monkeypatch):
    log = []
    monkeypatch.setitem(sources.SOURCES, "spotify", fake_source(log, "spotify"))
    monkeypatch.setitem(sources.SOURCES, "fake", fake_source(log, "fake", login="missing"))
    events = []
    with pytest.raises(SourceError) as excinfo:
        sources.read(support, [PlaylistLine("A", ID1, 1), PlaylistLine("B", "1", 2, "fake")], emit=events.append)
    assert (excinfo.value.kind, excinfo.value.service, str(excinfo.value)) == ("not_set_up", "fake", "fake not set up")
    assert log == [] and events == []


def test_stop_between_playlists_closes_the_readers(support, monkeypatch):
    log = []
    token = CancelToken()
    monkeypatch.setitem(sources.SOURCES, "spotify", fake_source(log, "spotify"))
    lines = [PlaylistLine("A", ID1, 1), PlaylistLine("B", ID2, 2)]
    events = []

    def emit(e):
        events.append(e)
        token.cancel()

    with pytest.raises(Cancelled):
        sources.read(support, lines, emit=emit, token=token)
    assert len(events) == 1 and ("close", "spotify") in log  # the first playlist was read, the second was not
    assert [e for e in log if e[0] == "fetch"] == [("fetch", "spotify", ID1)]


def test_read_infos_fills_by_ref_and_a_failing_playlist_loses_its_entry(support, monkeypatch):
    log = []
    monkeypatch.setitem(sources.SOURCES, "spotify", fake_source(log, "spotify", fail=[ID2]))
    monkeypatch.setitem(sources.SOURCES, "fake", fake_source(log, "fake"))
    infos = {ID2: "stale"}
    sources.read_infos(support, [ID1, ID2, "fake:7"], infos, CancelToken())
    assert set(infos) == {ID1, "fake:7"} and infos["fake:7"].service == "fake"


def test_read_infos_a_failing_login_leaves_the_other_services(support, monkeypatch):
    log = []
    monkeypatch.setitem(sources.SOURCES, "spotify",
                        fake_source(log, "spotify", open_error=SourceError("x", "not_set_up", "spotify")))
    monkeypatch.setitem(sources.SOURCES, "fake", fake_source(log, "fake"))
    infos = {}
    sources.read_infos(support, [ID1, "fake:7"], infos, CancelToken())
    assert set(infos) == {"fake:7"}


def test_read_infos_a_failing_reader_keeps_the_entries_already_there(support, monkeypatch):
    """The Spotify reader fails every info() when its current_user call fails: that is the service's trouble, not
    each playlist's, so the entries stay (and a failure of one service never touches another's)."""
    log = []
    broken = SourceError("Spotify is not responding (x). Try again later.", "offline", "spotify")

    class BrokenReader(FakeReader):
        def info(self, playlist_id):
            raise broken

    spotify_source = fake_source(log, "spotify")
    spotify_source.open = lambda paths, token: BrokenReader(log, "spotify")
    monkeypatch.setitem(sources.SOURCES, "spotify", spotify_source)
    monkeypatch.setitem(sources.SOURCES, "fake", fake_source(log, "fake", fail=["8"]))
    old = {ID1: "old spotify", ID2: "old spotify 2", "fake:7": "old fake", "fake:8": "old fake 8"}
    infos = dict(old)
    sources.read_infos(support, [ID1, ID2, "fake:7", "fake:8"], infos, CancelToken())
    assert infos[ID1] == "old spotify" and infos[ID2] == "old spotify 2"  # Spotify failed: nothing dropped
    assert infos["fake:7"].service == "fake" and "fake:8" not in infos  # the other service read as usual


def test_read_infos_a_failing_login_keeps_that_services_entries(support, monkeypatch):
    log = []
    monkeypatch.setitem(sources.SOURCES, "spotify",
                        fake_source(log, "spotify", open_error=SourceError("x", "login_expired", "spotify")))
    monkeypatch.setitem(sources.SOURCES, "fake", fake_source(log, "fake"))
    infos = {ID1: "old"}
    sources.read_infos(support, [ID1, "fake:7"], infos, CancelToken())
    assert infos[ID1] == "old" and infos["fake:7"].service == "fake"


def test_read_infos_ignores_a_service_it_does_not_know(support):
    infos = {}
    sources.read_infos(support, ["nowhere:1"], infos, CancelToken())
    assert infos == {}


def test_the_spotify_reader_reads_the_user_once_and_repeats_a_failure(support, monkeypatch):
    calls = []

    def current_user(session):
        calls.append(1)
        raise spotify.SpotifyError("Spotify is not responding (x). Try again later.")

    monkeypatch.setattr(spotify, "current_user", current_user)
    reader = spotify.SpotifyReader(spotify.Session("cid", support.spotify_token, {}))
    for _ in range(2):
        with pytest.raises(spotify.SpotifyError):
            reader.info(ID1)
    assert len(calls) == 1


def test_the_spotify_reader_gets_user_and_playlist(support, monkeypatch):
    monkeypatch.setattr(spotify, "current_user", lambda s: ("dj1", "DJ One"))
    seen = []

    def playlist_info(session, pid, me):
        seen.append((pid, me))
        return PlaylistInfo("spotify", pid, "N", "dj1", "DJ One", False, None, 1, True, True)

    monkeypatch.setattr(spotify, "playlist_info", playlist_info)
    with spotify.SpotifyReader(spotify.Session("cid", support.spotify_token, {})) as reader:
        reader.info(ID1)
        reader.info(ID2)
    assert seen == [(ID1, "dj1"), (ID2, "dj1")]
