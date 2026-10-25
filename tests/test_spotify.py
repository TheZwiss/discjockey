import base64
import hashlib
import json
import time

import pytest

from discjockey.models import PlaylistInfo
from discjockey.sources import spotify
from discjockey.models import PlaylistLine, SourceTrack


def item(id="t1", name="Song", isrc="DE1", local=False, type_="track", key="item"):
    t = {"id": id, "name": name, "type": type_, "duration_ms": 180000,
         "artists": [{"name": "Artist"}, {"name": "Other"}],
         "album": {"name": "Album", "images": [{"url": "small", "width": 64}, {"url": "big", "width": 640}]},
         "external_ids": {"isrc": isrc} if isrc else {}}
    return {key: t, "is_local": local}


def test_parse_item_track():
    t = spotify.parse_item(item())
    assert t == SourceTrack("t1", "Song", ("Artist", "Other"), "Album", "big", 180000, "DE1")


def test_parse_item_old_track_key_and_missing_isrc():
    t = spotify.parse_item(item(key="track", isrc=None))
    assert isinstance(t, SourceTrack) and t.isrc is None


@pytest.mark.parametrize("raw,reason", [
    (item(local=True), "local file"),
    ({"item": None, "is_local": False}, "unavailable"),
    (item(type_="episode"), "episode"),
    (item(id=None), "no Spotify ID"),
])
def test_parse_item_skips(raw, reason):
    r = spotify.parse_item(raw)
    assert isinstance(r, str) and reason in r


def test_pkce_pair():
    verifier, challenge = spotify.pkce_pair()
    assert 43 <= len(verifier) <= 128
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers=None, form=None):
        self.calls.append((method, url, form))
        status, body, headers_out = self.responses.pop(0)
        return status, headers_out or {}, body if isinstance(body, bytes) else json.dumps(body).encode()


def session(tmp_path, expires_in=3600):
    token = {"access_token": "A", "refresh_token": "R", "expires_at": time.time() + expires_in}
    sleeps = []
    s = spotify.Session("cid", tmp_path / "token.json", token, sleep=sleeps.append)
    return s, sleeps


LINE = PlaylistLine("Hard_Bounce", "0DiscjockeyExampleList", 3)


def test_fetch_follows_next_and_collects_skips(tmp_path, monkeypatch):
    fake = FakeHttp([
        (200, {"items": [item("t1"), item(local=True)], "next": "https://api/next"}, None),
        (200, {"items": [item("t2")], "next": None}, None),
    ])
    monkeypatch.setattr(spotify, "_http", fake)
    s, _ = session(tmp_path)
    fp = spotify.fetch_playlist(s, LINE)
    assert [t.id for t in fp.tracks] == ["t1", "t2"]
    assert len(fp.skipped) == 1
    assert "playlists/0DiscjockeyExampleList/items" in fake.calls[0][1]
    assert fake.calls[1][1] == "https://api/next"


@pytest.mark.parametrize("status", [403, 404])
def test_unreadable_playlist_names_the_line(tmp_path, monkeypatch, status):
    monkeypatch.setattr(spotify, "_http", FakeHttp([(status, {"error": {}}, None)]))
    s, _ = session(tmp_path)
    with pytest.raises(spotify.SpotifyError, match="line 3.*Hard_Bounce") as excinfo:
        spotify.fetch_playlist(s, LINE)
    assert excinfo.value.kind == "playlist_unreadable"


def test_rate_limit_waits_retry_after(tmp_path, monkeypatch):
    monkeypatch.setattr(spotify, "_http", FakeHttp([
        (429, {}, {"retry-after": "7"}),
        (200, {"items": [], "next": None}, None),
    ]))
    s, sleeps = session(tmp_path)
    spotify.fetch_playlist(s, LINE)
    assert sleeps == [7.0]


def test_long_rate_limit_stops_instead_of_waiting_silently(tmp_path, monkeypatch):
    monkeypatch.setattr(spotify, "_http", FakeHttp([(429, {}, {"retry-after": "7200"})]))
    s, sleeps = session(tmp_path)
    with pytest.raises(spotify.SpotifyError, match="120 minutes"):
        spotify.fetch_playlist(s, LINE)
    assert sleeps == []


def test_refresh_network_error_retries_then_says_try_later(tmp_path, monkeypatch):
    monkeypatch.setattr(spotify, "_http", FakeHttp([(None, {}, None)] * 4))
    s, sleeps = session(tmp_path, expires_in=-1)
    with pytest.raises(spotify.SpotifyError, match="internet") as excinfo:
        spotify.fetch_playlist(s, LINE)
    assert "setup" not in str(excinfo.value) and excinfo.value.kind == "offline"
    assert sleeps == [2, 4, 8]


def test_401_refreshes_once_and_keeps_old_refresh_token(tmp_path, monkeypatch):
    fake = FakeHttp([
        (401, {}, None),
        (200, {"access_token": "B", "expires_in": 3600}, None),  # token refresh, no new refresh token
        (200, {"items": [], "next": None}, None),
    ])
    monkeypatch.setattr(spotify, "_http", fake)
    s, _ = session(tmp_path)
    spotify.fetch_playlist(s, LINE)
    saved = json.loads((tmp_path / "token.json").read_text())
    assert saved["access_token"] == "B" and saved["refresh_token"] == "R"
    assert fake.calls[1][2]["grant_type"] == "refresh_token"


def test_second_401_asks_for_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(spotify, "_http", FakeHttp([
        (401, {}, None),
        (200, {"access_token": "B", "expires_in": 3600, "refresh_token": "R2"}, None),
        (401, {}, None),
    ]))
    s, _ = session(tmp_path)
    with pytest.raises(spotify.SpotifyError, match="setup") as excinfo:
        spotify.fetch_playlist(s, LINE)
    assert excinfo.value.kind == "login_expired"


def test_server_errors_back_off_then_give_up(tmp_path, monkeypatch):
    monkeypatch.setattr(spotify, "_http", FakeHttp([(503, {}, None)] * 4))
    s, sleeps = session(tmp_path)
    with pytest.raises(spotify.SpotifyError) as excinfo:
        spotify.fetch_playlist(s, LINE)
    assert sleeps == [2, 4, 8] and excinfo.value.kind == "offline"


def test_expired_refresh_token_means_login_expired(tmp_path, monkeypatch):
    monkeypatch.setattr(spotify, "_http", FakeHttp([(400, {"error": "invalid_grant"}, None)]))
    s, _ = session(tmp_path, expires_in=-1)
    with pytest.raises(spotify.SpotifyError, match="expired") as excinfo:
        spotify.fetch_playlist(s, LINE)
    assert excinfo.value.kind == "login_expired"


def test_every_request_checks_for_stop(tmp_path, monkeypatch):
    from discjockey.events import Cancelled, CancelToken
    monkeypatch.setattr(spotify, "_http", lambda *a, **k: pytest.fail("no request after Stop"))
    s, _ = session(tmp_path)
    token = CancelToken()
    token.cancel()
    s.check = token.check
    with pytest.raises(Cancelled):
        spotify.fetch_playlist(s, LINE)


def test_expired_token_is_refreshed_before_request(tmp_path, monkeypatch):
    fake = FakeHttp([
        (200, {"access_token": "B", "expires_in": 3600, "refresh_token": "R2"}, None),
        (200, {"items": [], "next": None}, None),
    ])
    monkeypatch.setattr(spotify, "_http", fake)
    s, _ = session(tmp_path, expires_in=-1)
    spotify.fetch_playlist(s, LINE)
    assert fake.calls[0][0] == "POST"
    assert s.token["refresh_token"] == "R2"


def test_load_session_without_setup(tmp_path):
    from discjockey.library import Paths
    with pytest.raises(spotify.SpotifyError, match="setup") as excinfo:
        spotify.load_session(Paths(tmp_path, support=tmp_path / ".support"))
    assert excinfo.value.kind == "not_set_up"


# --- a cut-off or garbled answer is a network problem ("try again later"), never a traceback ---

def test_incomplete_read_counts_as_no_connection(monkeypatch):
    import http.client

    class Cut:
        status, headers = 200, {}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            raise http.client.IncompleteRead(b'{"items": [', 500)

    monkeypatch.setattr(spotify.urllib.request, "urlopen", lambda req, timeout: Cut())
    assert spotify._http("GET", "https://api.spotify.com/v1/x") == (None, {}, b"")


def test_unreadable_refresh_answer_retries_then_says_try_later(tmp_path, monkeypatch):
    monkeypatch.setattr(spotify, "_http", FakeHttp([(200, b"<html>gateway", None)] * 4))
    s, sleeps = session(tmp_path, expires_in=-1)
    with pytest.raises(spotify.SpotifyError, match="try again") as excinfo:
        spotify.fetch_playlist(s, LINE)
    assert "setup" not in str(excinfo.value)
    assert sleeps == [2, 4, 8]


def test_unreadable_refresh_answer_is_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(spotify, "_http", FakeHttp([
        (200, b'{"access_tok', None),
        (200, {"access_token": "B", "expires_in": 3600}, None),
        (200, {"items": [], "next": None}, None),
    ]))
    s, sleeps = session(tmp_path, expires_in=-1)
    spotify.fetch_playlist(s, LINE)
    assert s.token["access_token"] == "B" and sleeps == [2]


def test_unreadable_playlist_page_retries_then_says_try_later(tmp_path, monkeypatch):
    monkeypatch.setattr(spotify, "_http", FakeHttp([(200, b'{"items": [', None)] * 3 +
                                                   [(200, {"items": [], "next": None}, None)]))
    s, sleeps = session(tmp_path)
    spotify.fetch_playlist(s, LINE)  # recovers after three garbled answers
    assert sleeps == [2, 4, 8]
    monkeypatch.setattr(spotify, "_http", FakeHttp([(200, b'{"items": [', None)] * 4))
    with pytest.raises(spotify.SpotifyError, match="Try again later"):
        spotify.fetch_playlist(s, LINE)


def test_token_file_is_replaced_atomically_and_private(tmp_path, monkeypatch):
    path = tmp_path / "token.json"
    spotify._save_token(path, {"access_token": "old"})
    assert path.stat().st_mode & 0o777 == 0o600

    def crash(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(spotify.os, "replace", crash)
    with pytest.raises(OSError):
        spotify._save_token(path, {"access_token": "new"})
    assert json.loads(path.read_text())["access_token"] == "old"  # never a half-written token file
    monkeypatch.undo()
    spotify._save_token(path, {"access_token": "new"})
    assert json.loads(path.read_text())["access_token"] == "new"
    assert path.stat().st_mode & 0o777 == 0o600
    assert sorted(p.name for p in tmp_path.iterdir()) == ["token.json"]


# --- the hub: token refresh from several threads, a login refreshed elsewhere, login without a terminal ---

def write_token(path, access="A", refresh="R", expires_in=-1):
    path.write_text(json.dumps({"access_token": access, "refresh_token": refresh,
                                "expires_at": time.time() + expires_in}))


def test_two_threads_with_an_expired_token_refresh_only_once(tmp_path, monkeypatch):
    import threading
    path = tmp_path / "token.json"
    write_token(path)
    posts = []

    def fake_http(method, url, headers=None, form=None):
        if method == "POST":
            posts.append(form["refresh_token"])
            time.sleep(0.2)  # the second thread arrives while the first one is still refreshing
            return 200, {}, json.dumps({"access_token": "B", "expires_in": 3600, "refresh_token": "R2"}).encode()
        assert headers["Authorization"] == "Bearer B"
        return 200, {}, json.dumps({"items": [], "next": None}).encode()

    monkeypatch.setattr(spotify, "_http", fake_http)
    sessions = [spotify.Session("cid", path, json.loads(path.read_text())) for _ in range(2)]
    errors = []

    def read(s):
        try:
            spotify.fetch_playlist(s, LINE)
        except Exception as e:  # pragma: no cover - shown in the assert
            errors.append(e)

    threads = [threading.Thread(target=read, args=(s,)) for s in sessions]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert errors == [] and posts == ["R"]
    assert [s.token["refresh_token"] for s in sessions] == ["R2", "R2"]
    assert json.loads(path.read_text())["refresh_token"] == "R2"


def test_a_token_refreshed_by_another_run_is_used_instead_of_refreshing(tmp_path, monkeypatch):
    path = tmp_path / "token.json"
    write_token(path)
    s = spotify.Session("cid", path, json.loads(path.read_text()))
    write_token(path, access="C", refresh="R3", expires_in=3600)  # the console refreshed meanwhile
    fake = FakeHttp([(200, {"items": [], "next": None}, None)])
    monkeypatch.setattr(spotify, "_http", fake)
    spotify.fetch_playlist(s, LINE)
    assert [c[0] for c in fake.calls] == ["GET"] and s.token["access_token"] == "C"


def test_login_expired_only_after_reading_the_token_file_again(tmp_path, monkeypatch):
    path = tmp_path / "token.json"
    write_token(path, refresh="R")
    s = spotify.Session("cid", path, json.loads(path.read_text()))
    write_token(path, access="C", refresh="R2", expires_in=-1)  # refreshed elsewhere long ago: R is used up
    fake = FakeHttp([
        (400, {"error": "invalid_grant"}, None),
        (200, {"access_token": "D", "expires_in": 3600, "refresh_token": "R4"}, None),
        (200, {"items": [], "next": None}, None),
    ])
    monkeypatch.setattr(spotify, "_http", fake)
    spotify.fetch_playlist(s, LINE)
    assert [c[2]["refresh_token"] for c in fake.calls if c[0] == "POST"] == ["R", "R2"]
    assert s.token["access_token"] == "D" and json.loads(path.read_text())["refresh_token"] == "R4"


def test_login_expired_when_the_token_file_has_nothing_newer(tmp_path, monkeypatch):
    path = tmp_path / "token.json"
    write_token(path)
    s = spotify.Session("cid", path, json.loads(path.read_text()))
    fake = FakeHttp([(400, {"error": "invalid_grant"}, None)])
    monkeypatch.setattr(spotify, "_http", fake)
    with pytest.raises(spotify.SpotifyError) as excinfo:
        spotify.fetch_playlist(s, LINE)
    assert excinfo.value.kind == "login_expired" and len(fake.calls) == 1


def free_port():
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def port_is_free(port):
    """As the next login would bind it (HTTPServer reuses an address whose last connection is still closing)."""
    import socket
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def test_login_without_a_terminal(tmp_path, monkeypatch, capsys):
    import threading
    import urllib.parse
    import urllib.request
    port = free_port()
    monkeypatch.setattr(spotify, "LOGIN_PORT", port)
    monkeypatch.setattr(spotify, "_http", FakeHttp([(200, {"access_token": "A", "expires_in": 3600,
                                                          "refresh_token": "R"}, None)]))
    shown, pages = [], []

    def browser(url):  # the user logs in; Spotify sends the browser back to Discjockey
        state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]

        def come_back():
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?code=c1&state={state}") as r:
                pages.append(r.read().decode())

        threading.Thread(target=come_back).start()

    spotify.login("cid", tmp_path / "token.json", open_browser=browser, on_url=shown.append)
    assert shown and shown[0].startswith(spotify.AUTH_URL)
    assert "You can close this tab" in pages[0] and "terminal" not in pages[0]
    assert json.loads((tmp_path / "token.json").read_text())["refresh_token"] == "R"
    assert capsys.readouterr().out == ""  # the core never prints
    assert port_is_free(port)


def test_login_can_be_cancelled_and_frees_the_port(tmp_path, monkeypatch):
    import threading

    from discjockey.events import Cancelled, CancelToken
    port = free_port()
    monkeypatch.setattr(spotify, "LOGIN_PORT", port)
    token = CancelToken()
    started = time.monotonic()
    with pytest.raises(Cancelled):
        spotify.login("cid", tmp_path / "token.json", open_browser=lambda url: threading.Timer(0.2, token.cancel).start(),
                      token=token)
    assert time.monotonic() - started < 2
    assert port_is_free(port) and not (tmp_path / "token.json").exists()


# --- playlist metadata for the hub's playlist page ---

PLAYLIST = {"id": "0DiscjockeyExampleList", "name": "Hard Bounce 2026", "collaborative": False,
            "owner": {"id": "dj1", "display_name": "DJ One"},
            "images": [{"url": "small", "width": 60}, {"url": "big", "width": 640}],
            "tracks": {"total": 49}}


def test_playlist_info(tmp_path, monkeypatch):
    fake = FakeHttp([(200, PLAYLIST, None)])
    monkeypatch.setattr(spotify, "_http", fake)
    s, _ = session(tmp_path)
    info = spotify.playlist_info(s, "0DiscjockeyExampleList", "dj1")
    assert info == PlaylistInfo("spotify", "0DiscjockeyExampleList", "Hard Bounce 2026", "dj1", "DJ One", False,
                                "big", 49, True, True)
    assert info.readable and fake.calls[0][1] == f"{spotify.API}/playlists/0DiscjockeyExampleList"


@pytest.mark.parametrize("change,yours,readable", [
    ({"owner": {"id": "someone", "display_name": "Someone"}}, False, False),  # only followed
    ({"owner": {"id": "someone"}, "collaborative": True}, False, True),
])
def test_playlist_info_readability(tmp_path, monkeypatch, change, yours, readable):
    monkeypatch.setattr(spotify, "_http", FakeHttp([(200, {**PLAYLIST, **change}, None)]))
    s, _ = session(tmp_path)
    info = spotify.playlist_info(s, "0DiscjockeyExampleList", "dj1")
    assert (info.yours, info.readable) == (yours, readable)


def test_playlist_info_reads_the_new_items_total_too(tmp_path, monkeypatch):
    data = {k: v for k, v in PLAYLIST.items() if k != "tracks"} | {"items": {"total": 12}, "images": None}
    monkeypatch.setattr(spotify, "_http", FakeHttp([(200, data, None)]))
    s, _ = session(tmp_path)
    info = spotify.playlist_info(s, "0DiscjockeyExampleList", "dj1")
    assert (info.track_count, info.image_url) == (12, None)


def test_playlist_info_for_a_playlist_spotify_does_not_show(tmp_path, monkeypatch):
    monkeypatch.setattr(spotify, "_http", FakeHttp([(404, {}, None)]))
    s, _ = session(tmp_path)
    with pytest.raises(spotify.SpotifyError, match="doesn't show") as excinfo:
        spotify.playlist_info(s, "0DiscjockeyExampleList", "dj1")
    assert excinfo.value.kind == "playlist_unreadable"


def test_current_user(tmp_path, monkeypatch):
    monkeypatch.setattr(spotify, "_http", FakeHttp([(200, {"id": "dj1", "display_name": "DJ One"}, None)]))
    s, _ = session(tmp_path)
    assert spotify.current_user(s) == ("dj1", "DJ One")
