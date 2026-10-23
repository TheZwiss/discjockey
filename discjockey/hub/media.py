"""Makes local audio playable in the window (spec "hub" 6.5): a token-protected server on 127.0.0.1, random port.

The one server of our own, limited to audio and covers: it serves only files in Library/, Superseded/,
Upgrades ready/ (addressed by their path in the music folder) and the cached previews and covers in the support
folder (addressed as `cache/previews/...`, `cache/covers/...`), and only with the random token in the URL. bottle's
static_file answers range requests (WebKit needs them to play and seek). Every URL carries the file's size and
mtime, so the window never plays a cached old version after a swap.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import urllib.parse
from pathlib import Path, PurePosixPath
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

import bottle
import mutagen

from ..library import Paths, SupportPaths
from ..names import fold

MUSIC_ROOTS = ("Library", "Superseded", "Upgrades ready")
CACHE_ROOTS = ("previews", "covers")  # under <support>/cache/
CACHE_PREFIX = "cache/"


def cache_address(paths: SupportPaths, file: Path) -> str:
    """The media address of a cached preview or cover: "cache/previews/<name>"."""
    return CACHE_PREFIX + file.relative_to(paths.cache).as_posix()


class _ThreadingServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, *args) -> None:
        pass


class MediaServer:
    host = "127.0.0.1"

    def __init__(self, paths: Paths | None = None, token: str | None = None):
        self.paths = paths  # None: nothing is served until the hub binds a library
        self.token = token or secrets.token_urlsafe(24)
        app = bottle.Bottle()
        app.route("/<token>/<rel:path>", "GET", self._serve)
        self._server = make_server(self.host, 0, app, server_class=_ThreadingServer, handler_class=_QuietHandler)
        self.port = self._server.server_port
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.1},
                                        name="hub-media", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def bind(self, paths: Paths) -> None:
        """The library whose files it serves (the hub binds it at start, or when the music folder is chosen)."""
        self.paths = paths

    def _locate(self, rel: str) -> tuple[Path, Path] | None:
        """(the served folder, the file) for a media address, or None outside the served folders."""
        paths = self.paths
        if paths is None:
            return None
        key = fold(rel)
        for r in MUSIC_ROOTS:
            if key.startswith(fold(r) + "/"):
                return paths.root / r, paths.root / rel
        for r in CACHE_ROOTS:
            if key.startswith(fold(CACHE_PREFIX + r) + "/"):
                return paths.cache / r, paths.cache / rel[len(CACHE_PREFIX):]
        return None

    def allowed(self, rel: str) -> Path | None:
        """The file for a media address, if it is a file inside one of the served folders (links resolved)."""
        parts = PurePosixPath(rel).parts
        if not parts or rel.startswith("/") or ".." in parts or "\\" in rel:
            return None
        found = self._locate(rel)
        if found is None:
            return None
        base, path = found
        try:
            real = path.resolve(strict=True)
            inside = real.is_relative_to(base.resolve())
        except OSError:
            return None
        return real if inside and real.is_file() else None

    def url(self, rel: str) -> str | None:
        """http://127.0.0.1:<port>/<token>/<quoted path>?v=<size>-<mtime>, or None if the file can't be served."""
        real = self.allowed(rel)
        if real is None:
            return None
        st = real.stat()
        return (f"http://{self.host}:{self.port}/{self.token}/{urllib.parse.quote(rel)}"
                f"?v={st.st_size}-{st.st_mtime_ns}")

    def _serve(self, token: str, rel: str):
        if not hmac.compare_digest(token.encode(), self.token.encode()):
            return bottle.HTTPError(403, "Forbidden")
        real = self.allowed(rel)
        if real is None:
            return bottle.HTTPError(403, "Forbidden")
        return bottle.static_file(real.name, root=str(real.parent))


# --- covers (spec 6.9): from the file's embedded cover, cached in .cache/covers/ by path, size and mtime ---

IMAGE_TYPES = ((b"\xff\xd8\xff", ".jpg"), (b"\x89PNG", ".png"))


def _embedded_cover(path: Path) -> bytes | None:
    try:
        tags = getattr(mutagen.File(str(path)), "tags", None)
    except Exception:  # not audio, or tags mutagen can't read: no cover
        return None
    frames = tags.getall("APIC") if tags is not None and hasattr(tags, "getall") else []
    front = sorted(frames, key=lambda f: f.type != 3)  # the front cover first
    return front[0].data if front else None


def cover_file(paths: Paths, rel: str) -> str | None:
    """Media address of the cached cover image of a library file, or None if it has none."""
    try:
        st = (paths.root / rel).stat()
    except OSError:
        return None
    folder = paths.cache / "covers"
    stem = f"{hashlib.sha1(fold(rel).encode()).hexdigest()}-{st.st_size}-{st.st_mtime_ns}"
    for _, ext in IMAGE_TYPES:
        if (folder / f"{stem}{ext}").exists():
            return cache_address(paths, folder / f"{stem}{ext}")
    if (folder / f"{stem}.none").exists():
        return None
    data = _embedded_cover(paths.root / rel)
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob(f"{stem.split('-')[0]}-*"):  # an older version of the file (e.g. before a swap)
        old.unlink(missing_ok=True)
    ext = next((e for magic, e in IMAGE_TYPES if data and data.startswith(magic)), None)
    if ext is None:
        (folder / f"{stem}.none").touch()
        return None
    tmp = folder / f"{stem}.tmp"
    tmp.write_bytes(data)
    os.replace(tmp, folder / f"{stem}{ext}")
    return cache_address(paths, folder / f"{stem}{ext}")
