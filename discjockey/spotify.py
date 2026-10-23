"""Spotify Web API: PKCE login, token refresh, reading playlist items. Metadata only, never audio."""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable

from .library import SupportPaths
from .models import FetchedPlaylist, PlaylistLine, SpotifyTrack

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = "playlist-read-private playlist-read-collaborative"
BACKOFF = (2, 4, 8)
MAX_RATE_LIMIT_WAITS = 20
MAX_RETRY_AFTER_S = 120
LOGIN_TIMEOUT_S = 300
LOGIN_PORT = 8888  # must match REDIRECT_URI
LOGIN_POLL_S = 0.5  # how often the login waits look at the stop flag
DONE_PAGE = (b'<!doctype html><meta charset="utf-8"><title>Discjockey</title>'
             b'<p style="font: 16px -apple-system, sans-serif">Spotify login done. You can close this tab.</p>')


class SpotifyError(Exception):
    """A problem the user has to fix; the run stops with exit code 2.

    kind (for the hub's cards): not_set_up | login_expired | offline | playlist_unreadable | login_failed."""

    def __init__(self, message: str, kind: str = "offline"):
        super().__init__(message)
        self.kind = kind


class PlaylistUnavailable(Exception):
    def __init__(self, status: int):
        super().__init__(status)
        self.status = status


def _http(method: str, url: str, headers: dict | None = None, form: dict | None = None):
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        try:
            return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read()
        except (http.client.HTTPException, OSError):
            return e.code, {}, b""
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
        # HTTPException: e.g. IncompleteRead when the connection drops in the middle of an answer
        return None, {}, b""


@dataclass
class Session:
    client_id: str
    token_path: Path
    token: dict
    sleep: Callable[[float], None] = time.sleep
    check: Callable[[], None] = lambda: None  # raises events.Cancelled once Stop was pressed (set by run.prepare)


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _token_record(resp: dict, old_refresh: str | None = None) -> dict:
    return {
        "access_token": resp["access_token"],
        "refresh_token": resp.get("refresh_token") or old_refresh,
        "expires_at": time.time() + int(resp.get("expires_in", 3600)) - 60,
    }


def _save_token(path: Path, token: dict) -> None:
    """Written next to the old file and swapped in, so a crash never leaves a half-written (lost) login."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(token, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)  # also if an old .tmp file had other permissions
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _wait_for_redirect(url: str, open_browser, on_url=None, token=None) -> dict:
    """Serves one redirect on 127.0.0.1:8888. The server is always closed afterwards, also after a Stop."""
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            result.update({k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DONE_PAGE)

        def log_message(self, *args):
            pass

    try:
        server = HTTPServer(("127.0.0.1", LOGIN_PORT), Handler)
    except OSError:
        raise SpotifyError("Port 8888 is busy. Close the program using it and run setup again.",
                           "login_failed") from None
    with server:
        server.timeout = LOGIN_POLL_S
        if on_url:
            on_url(url)  # the console prints it, in case no browser opens
        open_browser(url)
        deadline = time.monotonic() + LOGIN_TIMEOUT_S
        while not result and time.monotonic() < deadline:
            if token is not None:
                token.check()
            server.handle_request()
    if not result:
        raise SpotifyError("Timed out waiting for the Spotify login. Run setup again.", "login_failed")
    return result


def login(client_id: str, token_path: Path, open_browser=webbrowser.open, on_url=None, token=None) -> None:
    """PKCE login in the system browser. on_url(url): told the login link first. token: a CancelToken; Stop
    raises events.Cancelled (and the port is free again)."""
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": REDIRECT_URI,
        "code_challenge_method": "S256", "code_challenge": challenge, "scope": SCOPES, "state": state,
    })
    params = _wait_for_redirect(url, open_browser, on_url, token)
    if "error" in params:
        raise SpotifyError(f"Spotify login was not completed: {params['error']}", "login_failed")
    if params.get("state") != state or "code" not in params:
        raise SpotifyError("Spotify login failed (unexpected answer). Run setup again.", "login_failed")
    status, _, body = _http("POST", TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, {
        "grant_type": "authorization_code", "code": params["code"], "redirect_uri": REDIRECT_URI,
        "client_id": client_id, "code_verifier": verifier,
    })
    if status != 200:
        raise SpotifyError(f"Spotify login failed (HTTP {status}). Check the Client ID and the redirect URI.",
                           "login_failed")
    token = _read_token(body)
    if token is None:
        raise SpotifyError("Spotify login failed (the answer was cut off or unreadable). Run setup again.",
                           "login_failed")
    _save_token(token_path, token)


def load_session(paths: SupportPaths) -> Session:
    try:
        app = json.loads(paths.spotify_app.read_text(encoding="utf-8"))
        token = json.loads(paths.spotify_token.read_text(encoding="utf-8"))
        return Session(app["client_id"], paths.spotify_token, token)
    except (OSError, ValueError, KeyError):
        raise SpotifyError("Spotify is not set up yet. Run: discjockey setup", "not_set_up") from None


def _read_json(body: bytes) -> dict | None:
    """None for an answer that was cut off or garbled (e.g. a proxy's error page): treated like no connection."""
    try:
        data = json.loads(body)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _read_token(body: bytes, old_refresh: str | None = None) -> dict | None:
    data = _read_json(body)
    if not data or not data.get("access_token"):
        return None
    return _token_record(data, old_refresh)


class _Refused(Exception):
    """Spotify did not take this refresh token (400/401)."""


_REFRESH_LOCKS: dict[str, threading.Lock] = {}
_REFRESH_LOCKS_GUARD = threading.Lock()


def _refresh_lock(token_path: Path) -> threading.Lock:
    """One lock per token file in this process: two threads never refresh at the same time."""
    with _REFRESH_LOCKS_GUARD:
        return _REFRESH_LOCKS.setdefault(str(Path(token_path).absolute()), threading.Lock())


def _token_on_disk(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("access_token") and data.get("refresh_token") else None


def _refresh_with(session: Session, refresh_token: str) -> None:
    form = {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": session.client_id}
    for attempt in range(len(BACKOFF) + 1):
        session.check()
        status, _, body = _http("POST", TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, form)
        if status == 200:
            token = _read_token(body, refresh_token)
            if token is not None:
                break
            problem = "unreadable answer"
        elif status in (400, 401):
            raise _Refused()
        else:
            problem = f"HTTP {status or 'no connection'}"
        if attempt < len(BACKOFF):  # no connection or Spotify trouble: wait and try again
            session.sleep(BACKOFF[attempt])
    else:
        raise SpotifyError(f"Cannot reach Spotify ({problem}). Check the internet connection and try again.")
    session.token = token
    _save_token(session.token_path, session.token)


def _refresh(session: Session, stale_access: str | None = None) -> None:
    """New access token. `stale_access`: the one that expired or was refused. The token file is the shared truth:
    another thread (or a console run) may have refreshed meanwhile, and the refresh token changes every time."""
    stale_access = stale_access or session.token.get("access_token")
    with _refresh_lock(session.token_path):
        disk = _token_on_disk(session.token_path)
        if disk and disk["access_token"] != stale_access and time.time() < disk.get("expires_at", 0):
            session.token = disk  # refreshed by someone else a moment ago
            return
        try:
            _refresh_with(session, session.token["refresh_token"])
            return
        except _Refused:
            disk = _token_on_disk(session.token_path)  # read once more before saying "expired"
            if not disk or disk["refresh_token"] == session.token["refresh_token"]:
                raise SpotifyError("Your Spotify login has expired. Run: discjockey setup", "login_expired") from None
        try:
            _refresh_with(session, disk["refresh_token"])
        except _Refused:
            raise SpotifyError("Your Spotify login has expired. Run: discjockey setup", "login_expired") from None


def api_get(session: Session, url: str) -> dict:
    refreshed = False
    failures = 0
    rate_waits = 0
    while True:
        session.check()
        if time.time() >= session.token.get("expires_at", 0):
            _refresh(session)
        used = session.token["access_token"]
        status, headers, body = _http("GET", url, {"Authorization": f"Bearer {used}"})
        problem = f"HTTP {status or 'no connection'}"
        if status == 200:
            data = _read_json(body)
            if data is not None:
                return data
            problem = "unreadable answer"  # retried below like any other Spotify trouble
        elif status == 429 and rate_waits < MAX_RATE_LIMIT_WAITS:
            rate_waits += 1
            wait = float(headers.get("retry-after") or 5)
            if wait > MAX_RETRY_AFTER_S:
                raise SpotifyError(f"Spotify asks to wait {wait / 60:.0f} minutes. Try again later.")
            session.sleep(wait)
            continue
        if status == 401 and not refreshed:
            _refresh(session, used)
            refreshed = True
            continue
        if status == 401:
            raise SpotifyError("Spotify did not accept the login. Run: discjockey setup", "login_expired")
        if status in (403, 404):
            raise PlaylistUnavailable(status)
        if failures < len(BACKOFF):
            session.sleep(BACKOFF[failures])
            failures += 1
            continue
        raise SpotifyError(f"Spotify is not responding ({problem}). Try again later.")


def parse_item(raw: dict) -> SpotifyTrack | str:
    t = raw.get("item") if "item" in raw else raw.get("track")
    name = (t or {}).get("name") or "Unknown track"
    if raw.get("is_local"):
        return f"{name} (local file, not on Spotify)"
    if t is None:
        return "A track that is unavailable on Spotify"
    if t.get("type") == "episode":
        return f"{name} (podcast episode)"
    if not t.get("id"):
        return f"{name} (no Spotify ID)"
    album = t.get("album") or {}
    images = album.get("images") or []
    image = max(images, key=lambda i: i.get("width") or 0, default=None)
    return SpotifyTrack(
        id=t["id"],
        title=t.get("name") or "",
        artists=tuple(a["name"] for a in t.get("artists") or [] if a.get("name")),
        album=album.get("name") or "",
        image_url=image["url"] if image else None,
        duration_ms=int(t.get("duration_ms") or 0),
        isrc=(t.get("external_ids") or {}).get("isrc") or None,
    )


def fetch_playlist(session: Session, line: PlaylistLine) -> FetchedPlaylist:
    url = f"{API}/playlists/{line.playlist_id}/items?limit=50&additional_types=track"
    tracks: list[SpotifyTrack] = []
    skipped: list[str] = []
    while url:
        try:
            page = api_get(session, url)
        except PlaylistUnavailable as e:
            raise SpotifyError(
                f"playlists.txt line {line.line_no} ({line.folder}): Spotify answered HTTP {e.status}. "
                "The playlist must exist and be yours or collaborative with your account. "
                "Check the link, or put # in front of the line.", "playlist_unreadable"
            ) from None
        for raw in page.get("items") or []:
            r = parse_item(raw)
            (tracks if isinstance(r, SpotifyTrack) else skipped).append(r)
        url = page.get("next")
    return FetchedPlaylist(line, tracks, skipped)


@dataclass(frozen=True)
class PlaylistInfo:
    """What the playlist page shows for a pasted link. Development Mode only reads playlists that are yours or
    collaborative ("Follow ≠ own"). [The fields are to be verified in the first live session.]"""
    id: str
    name: str
    owner_id: str
    owner_name: str
    collaborative: bool
    image_url: str | None
    track_count: int | None
    yours: bool

    @property
    def readable(self) -> bool:
        return self.yours or self.collaborative


def current_user(session: Session) -> tuple[str, str]:
    """(Spotify user id, display name) of the logged-in account."""
    me = api_get(session, f"{API}/me")
    return me.get("id") or "", me.get("display_name") or me.get("id") or ""


def playlist_info(session: Session, playlist_id: str, my_id: str) -> PlaylistInfo:
    try:
        data = api_get(session, f"{API}/playlists/{playlist_id}")
    except PlaylistUnavailable:
        raise SpotifyError("Spotify doesn't show this playlist. Check the link (and that the playlist still exists).",
                           "playlist_unreadable") from None
    owner = data.get("owner") or {}
    images = data.get("images") or []
    image = max(images, key=lambda i: i.get("width") or 0, default=None)
    total = (data.get("tracks") or data.get("items") or {}).get("total")
    return PlaylistInfo(data.get("id") or playlist_id, data.get("name") or "", owner.get("id") or "",
                        owner.get("display_name") or owner.get("id") or "", bool(data.get("collaborative")),
                        image["url"] if image else None, total, bool(my_id) and owner.get("id") == my_id)
