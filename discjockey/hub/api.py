"""HubApi: the methods the window may call (pywebview's js_api; spec "hub" 6.8 and the plan's bridge contract).

pywebview runs every call on a new thread of its own and passes the page's arguments positionally. Every method
returns JSON: {"ok": true, ...} or {"ok": false, "kind", "message"} (plain English, never a traceback). Everything
that is not a bridge method starts with "_", because pywebview exposes every public attribute to the page.
"""
from __future__ import annotations

import contextlib
import functools
import inspect
import json
import logging
import re
import shutil
import sqlite3
import subprocess
import threading
import tomllib
import traceback
import unicodedata
import webbrowser
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from pathlib import Path, PurePosixPath
import time
from typing import Callable
from urllib.parse import quote

from .. import __version__, align, browsers, candidates, config, db, library, ops, planner, playlists_file as pf, qobuz
from .. import quality
from .. import app_update as update_check, setup_cmd, tool_updates, tools
from .. import sources, tidy
from ..sources import spotify
from .. import report as rep, run, upgrades
from ..accounts import ACCOUNTS, BROWSERS, SERVICE_NAMES, SERVICES, check_message
from ..acquire import make_ready
from ..candidates import current_key
from ..fallback import FallbackSource
from ..library import NoLibrary, Paths, Resolved, StateError, SupportPaths
from ..events import CancelToken
from ..models import (SERVICE_NAMES as PLAYLIST_SERVICES, SOURCE_NAMES, BatchResult, BatchRow, Candidate, PlaylistLine,
                      SaveChoice, SourceTrack, token)
from ..names import fold
from ..ops import OpProblem, snapshot
from ..pacing import Budget
from ..qobuz import QobuzError, QobuzLoginRejected, QobuzNotSetUp, QobuzSource, config_file, login_problem
from ..settings import MAX_DAILY_LIMIT, MAX_EXTRA, Settings, SettingsError, load_settings, save_settings
from ..setup_cmd import TOOL_HINTS
from ..sources.spotify import REDIRECT_URI
from . import media as media_mod, spectrum as spec, views
from .jobs import (UNEXPECTED, AppUpdate, Busy, FileDropped, Jobs, PreviewStore, SignInPhase, preview_after_run,
                   problem_of, refresh_work, service_of, sync_work)

RUN_ID = re.compile(r"\d{4}-\d{2}-\d{2}_\d{6}")
WHICH = ("current", "upgrade")
UPGRADE_MODES = ("swap", "add_new", "discard")
SYNC_RUNNING = "Not while a sync runs: Discjockey keeps its requests to Qobuz and YouTube paced."
AUTO_READ_DONE = "Your playlists were read by themselves once this session already. Use ↻ Read playlists to read them again."
NO_DROP = "Drag the bought file onto the window while this track is selected in the to-do list."
NOT_SELECTED = "Select the track in the to-do list first, then drop the file on the window."
CLIENT_ID = re.compile(r"[0-9a-fA-F]{32}")
NOT_CONNECTED = "Connect {name} first."
NOT_CHOSEN = "Choose your music folder first: it is the first step of Setup."
MISSING = "Your music folder isn't there: {path}. Connect the drive it is on, or choose another folder."
# Bridge methods that need a bound music folder: unbound, they answer no_library before anything runs. Every other
# method works with the support folder alone (Setup and Settings before a folder is chosen). Pinned by
# tests/test_hub_api_music.py and, against contract.ts, by hub-ui's contract test (keep the one-name-per-string form).
LIBRARY_METHODS = frozenset((
    "dashboard", "sidebar", "sync_preview", "refresh", "library", "track", "todo", "playlists", "limits",
    "limits_what_if", "save_limits", "mark_warnings_seen", "runs", "run", "spectrum", "media_url",
    "search_candidates", "preview", "add_playlist", "preview_playlist_change", "start_sync", "save_playlists",
    "hide", "never_download", "add_bought_file", "use_candidate", "use_link", "reject_current",
    "rekordbox_checked", "upgrade", "rescan_library", "show_in_finder", "reveal", "open_report",
    "tidy_preview", "move_batches", "undo_preview", "tidy_up", "undo_moves",
))


@dataclass
class Services:
    """Everything outside the hub that it talks to. Tests replace them with fakes."""
    open_qobuz: Callable = QobuzSource.open
    fallback: Callable = FallbackSource  # (emit=..., check=...)
    open_url: Callable[[str], object] = webbrowser.open
    open_path: Callable[[Path], object] = lambda p: subprocess.run(["open", str(p)], check=False)
    reveal: Callable[[Path], object] = lambda p: subprocess.run(["open", "-R", str(p)], check=False)
    which: Callable[[str], str | None] = shutil.which
    run: Callable = subprocess.run
    # PyPI (looked up per call: tests stub it)
    fetch: Callable[[str], bytes] = lambda url: tool_updates.http_get(url)
    # GitHub's latest release (looked up per call: tests stub it)
    fetch_release: Callable[[str], bytes] = lambda url: update_check.fetch_latest(url)
    analyze: Callable = quality.inspect
    process: Callable = make_ready
    compare: Callable = align.compare_files
    decode: Callable = quality.decode_mono
    now: Callable[[], datetime] = datetime.now
    home: Path = Path.home()  # where the browsers keep their files (tests: a folder that doesn't exist)
    open_in: Callable[[str, str, str | None], object] = lambda browser, url, profile=None: _open_in(browser, url, profile)
    # the window's folder dialog (app.main sets it: (start folder) -> the chosen path or None); None: no window
    pick_folder: Callable[[str], str | None] | None = None


# Signing in through the browser (spec settings-setup §5, §7): the pages it opens, how often it looks for the login,
# and how long it waits. Module-level: pywebview exposes every public name of HubApi.
_SIGN_IN_URLS = {
    "youtube": "https://accounts.google.com/ServiceLogin?service=youtube&passive=true&continue="
               + quote("https://www.youtube.com/signin?action_handle_signin=true&next=https://music.youtube.com/",
                       safe=""),
    "soundcloud": "https://soundcloud.com/signin"}
_SIGN_IN_POLL = 3.0
_UPDATE_TICK = 3600.0  # s: the update check looks at its day-old cache this often
_SIGN_IN_TIMEOUT = 600.0
DOWNLOAD_TOOLS_UNREADABLE = "Couldn't read the download tools' versions. The other checks above are still correct."
log = logging.getLogger(__name__)
_PRIVACY_SETTINGS = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"


def _open_in(browser: str, url: str, profile: str | None = None) -> None:
    """Opens the page in that browser; a chosen Chrome/Brave/Edge profile opens in its own window."""
    app = browsers.APPS[browser].removesuffix(".app")
    if profile is not None and browser in browsers.CHROMIUM:
        cmd = ["open", "-na", app, "--args", f"--profile-directory={profile}", url]
    else:
        cmd = ["open", "-a", app, url]
    subprocess.run(cmd, check=False)


def bridge(fn):
    """{"ok": true, **result} or {"ok": false, "kind", "message"}; never raises into pywebview. A problem with a
    playlist service (a SourceError) also carries "service"."""
    @functools.wraps(fn)
    def call(self, *args, **kwargs):
        try:
            if fn.__name__ in LIBRARY_METHODS:
                self._need_library()  # NoLibrary -> no_library before anything starts
            return {"ok": True, **(fn(self, *args, **kwargs) or {})}
        except Busy as e:
            return {"ok": False, "kind": e.kind, "message": str(e)}
        except StateError as e:
            return {"ok": False, "kind": "config_invalid", "message": str(e)}
        except TypeError as e:  # the page called with wrong arguments
            traceback.print_exc()
            return {"ok": False, "kind": "crashed", "message": UNEXPECTED}
        except BaseException as e:  # noqa: BLE001 - nothing may reach the page as a traceback
            kind, message = problem_of(e)
            if kind == "crashed":  # for whoever looks at the terminal; the page gets the plain message
                traceback.print_exc()
            service = service_of(e)
            return {"ok": False, "kind": kind, "message": message, **({"service": service} if service else {})}

    call.__signature__ = inspect.signature(fn)  # pywebview reads the parameter names from it
    return call


def profile_name(browser: str, profile: str | None, home: Path | None) -> str | None:
    """The display name of a saved browser profile ("DJ" for Chrome's "Profile 2"); None for the default one, or
    without `home` (no browser files are read then)."""
    if profile is None or home is None:
        return None
    return {p["id"]: p["name"] for p in browsers.profiles(browser, home)}.get(profile, profile)


def setup_status(support: SupportPaths, paths: Paths | None, music: dict, which: Callable[[str], str | None],
                 home: Path | None = None) -> dict:
    """What is set up (spec 6.9; the music folder first, spec public-release §4). Never returns any secret, only
    whether it is there. `paths`: the bound library (None: no music folder yet, so no playlists); `music`:
    HubApi._music_status(). `home`: where the browsers keep their files, for the profile names (None: not read)."""
    tools = {tool: which(tool) is not None for tool in TOOL_HINTS}
    spotify_app = spotify_login = qobuz_ok = playlists_ok = False
    spotify_user = None
    try:
        app = json.loads(support.spotify_app.read_text(encoding="utf-8"))
        spotify_app = bool(app.get("client_id"))
        spotify_user = app.get("user") if isinstance(app.get("user"), str) else None
    except (OSError, ValueError, AttributeError):
        pass
    try:
        spotify_login = bool(json.loads(support.spotify_token.read_text(encoding="utf-8")).get("refresh_token"))
    except (OSError, ValueError, AttributeError):
        pass
    try:
        q = tomllib.loads(config_file(support).read_text(encoding="utf-8")).get("qobuz", {})
        qobuz_ok = bool(q.get("email_or_userid")) and bool(q.get("password_or_token"))
    except (OSError, ValueError):
        pass
    if paths is not None:
        try:
            playlists_ok = bool(config.load_playlists(paths.playlists_file))
        except config.ConfigError:
            pass
    try:
        settings = load_settings(support.settings_file)
    except SettingsError:
        settings = Settings()
    steps = [("music", music["state"] == "ok"), ("tools", all(tools.values())),
             ("spotify", spotify_app and spotify_login), ("downloads", qobuz_ok or settings.qobuz_skipped),
             ("playlists", playlists_ok)]
    return {"music": music, "tools": tools, "spotify_app": spotify_app, "spotify_login": spotify_login,
            "qobuz": qobuz_ok,
            "playlists": playlists_ok, "complete": all(ok for _, ok in steps),
            "next_step": next((name for name, ok in steps if not ok), None),
            "version": __version__, "qobuz_skipped": settings.qobuz_skipped,
            "qobuz_last_check": dict(settings.qobuz_last_check) if settings.qobuz_last_check else None,
            "spotify_user": spotify_user if spotify_login else None,
            "accounts": {s: ({"browser": a.browser, "browser_name": BROWSERS[a.browser], "daily_limit": a.daily_limit,
                              "profile": a.profile, "profile_name": profile_name(a.browser, a.profile, home),
                              "last_check": dict(a.last_check) if a.last_check else None}
                             if (a := settings.accounts.get(s)) else None) for s in ACCOUNTS}}


class HubApi:
    def __init__(self, support: Path, events=None, services: Services | None = None, media=None):
        """Built from the support folder alone; a library is bound later with _bind (app.main at start when the
        music folder is there, or set_music_folder / retry_music_folder when it is chosen or comes back)."""
        self._support = SupportPaths(support=support)
        self._bound: Paths | None = None
        self._missing: Path | None = None  # config.json names this folder, but it isn't there
        self._music_lock = threading.RLock()  # binding and choosing the folder: one at a time
        self._events = events  # HubEvents (or anything with .emit); None: events go nowhere
        self._svc = services or Services()
        self._update = update_check.Checker(self._support.cache / update_check.CACHE_NAME,
                                            fetch=lambda url: self._svc.fetch_release(url))
        self._media = media  # MediaServer, or None (no audio or covers)
        self._jobs = Jobs(None, self._emit, now=self._svc.now)
        self._settings_mutex = threading.Lock()  # settings.json: read, change, save — one at a time
        self._store = PreviewStore()
        self._infos: dict = {}  # playlist ref -> models.PlaylistInfo
        self._extra_tracks: dict = {}  # playlist ref -> tracks of playlists read outside a refresh
        self._shown: dict[str, dict] = {}  # track id -> how the page last showed it (ops.snapshot)
        self._selected: str | None = None
        self._dropped: dict | None = None
        self._lock = threading.Lock()
        self._auto_lock = threading.Lock()
        self._quit: Callable[[], None] | None = None  # set by app.main: closes the window
        # the Qobuz auto-stop for "Use this" and links: one failure streak for the whole hub session (reset when a
        # sync starts), not one per job, so that failed downloads in a row do pause Qobuz
        self._qobuz_streak = {"failures_in_a_row": 0, "download_failed_in_row": False, "stopped": False}
        self._account_streaks: dict[str, dict] = {}  # service -> the same, for "Use this" through an account

    # --- helpers (not reachable from the page) ---

    @property
    def _paths(self) -> Paths:
        """The bound library. NoLibrary while there is none: every library path goes through here."""
        paths = self._bound
        if paths is None:
            raise NoLibrary(MISSING.format(path=self._missing) if self._missing else NOT_CHOSEN)
        if not paths.root.is_dir():  # bound, then the folder went away (an unplugged drive): never an empty library
            raise NoLibrary(library.MUSIC_GONE)
        return paths

    def _need_library(self) -> None:
        self._paths  # noqa: B018 - raises NoLibrary while unbound

    def _music_status(self) -> dict:
        bound, missing = self._bound, self._missing
        gone = bound is not None and not bound.root.is_dir()  # bound at start, the folder left since
        state = ("missing" if gone else "ok") if bound is not None else "missing" if missing is not None else "not_chosen"
        path = bound.root if bound is not None else missing
        return {"state": state, "path": str(path) if path is not None else None,
                "suggested": str(self._svc.home / "Music" / "Discjockey")}

    def _attach(self, paths: Paths) -> None:
        """Points the hub at a library without starting anything (_bind uses it; so do tests and the recorder)."""
        if paths.support != self._support.support:
            raise ValueError("The library belongs to another support folder.")
        with self._music_lock:
            self._jobs.bind(paths.lock)
            if self._media is not None:
                self._media.bind(paths)
            self._bound, self._missing = paths, None  # last: the library gate opens once lock and media are ready

    def _bind(self, paths: Paths) -> None:
        """The one place that starts the library's services: the lock for write jobs, the media server's root, the
        terminal-run watch and the playlists.txt watch. Runs once per process: at start, or when the user first
        chooses (or gets back) the music folder. A later change of the folder restarts the app instead
        (set_music_folder). Called with the music lock held; the caller then starts the session's one automatic
        Spotify read with _first_read(), after it has released the lock (the read starts a job of its own)."""
        with self._music_lock:
            if self._bound is not None:
                raise RuntimeError("A library is bound already; changing it needs a restart.")
            self._attach(paths)
            self._jobs.watch_console()
            self._watch_playlists_file()

    def _first_read(self) -> None:
        self.refresh(auto=True)

    def _start(self, resolved: Resolved) -> None:
        """At launch (app.main): bind the library when the music folder is there, else remember why not."""
        if resolved.paths is not None:
            self._bind(resolved.paths)
            self._first_read()
        elif resolved.problem == "missing":
            with self._music_lock:
                self._missing = resolved.music_folder

    def _check_folder(self, path: str) -> library.FolderCheck:
        return library.check_music_folder(path or "", support=self._support.support, program=tools.program_dir(),
                                          home=self._svc.home)

    def _emit(self, event: object) -> None:
        if self._events is not None:
            self._events.emit(event)

    def _state(self) -> dict:
        return library.load_state(self._paths)

    def _settings(self) -> Settings:
        try:
            return load_settings(self._support.settings_file)
        except SettingsError:
            return Settings()

    def _folders(self) -> list[str]:
        try:
            return [line.folder for line in config.load_playlists(self._paths.playlists_file)]
        except config.ConfigError:
            return []

    def _reports(self) -> list[tuple[str, dict]]:
        out = []
        for f in sorted(self._paths.reports.glob("*.json")) if self._paths.reports.is_dir() else []:
            if RUN_ID.fullmatch(f.stem):
                try:
                    out.append((f.stem, json.loads(f.read_text(encoding="utf-8"))))
                except (OSError, ValueError):
                    continue
        return out

    def _today(self):
        return self._svc.now().date()

    def _reading(self) -> bool:
        return self._jobs.status()["refresh_running"]

    def _logins(self) -> list[tuple[str, bool]]:
        """(service, logged in) for each playlist service the switched-on playlists.txt lines use, in line order.
        A local check of each service's login files, never a network call."""
        try:
            used = list(dict.fromkeys(r.service for r in pf.load(self._paths.playlists_file).rows if r.enabled))
        except Exception:  # noqa: BLE001 - a file that can't be read or a library that is gone: no list, never a failed poll
            return []
        logins = []
        for service in used:
            try:
                logins.append((service, sources.SOURCES[service].login_state(self._support).state == "ok"))
            except Exception:  # noqa: BLE001 - a login file this check can't make sense of counts as not connected
                logins.append((service, False))
        return logins

    @staticmethod
    def _close(reader) -> None:
        """Ends a playlist read's session. A close that fails must not replace the read's own answer."""
        try:
            reader.close()
        except Exception:  # noqa: BLE001
            log.warning("closing a playlist reader failed", exc_info=True)

    def _images(self) -> dict[str, str]:
        prep = self._store.prep
        return {t.id: t.image_url for fp in (prep.fetched if prep else []) for t in fp.tracks if t.image_url}

    def _cover(self, images: dict[str, str]) -> Callable[[str, dict], str | None]:
        def cover(track_id: str, e: dict) -> str | None:
            if self._media is not None and e and e.get("path"):
                rel = media_mod.cover_file(self._paths, e["path"])
                if rel:
                    return self._media.url(rel)
            ids = [track_id, *((e or {}).get("aliases") or [])]
            return next((images[i] for i in ids if i in images), None)
        return cover

    def _audio(self, track_id: str, e: dict) -> str | None:
        return self._media.url(e["path"]) if self._media is not None and e.get("path") else None

    def _remember(self, state: dict, track_ids) -> None:
        with self._lock:
            for k in track_ids:
                self._shown[k] = snapshot(state["tracks"].get(k))

    def _entry(self, state: dict, track_id: str) -> dict:
        e = state["tracks"].get(track_id)
        if e is None:
            raise OpProblem("This track is not in your library any more.", "changed")
        return e

    def _file_of(self, track_id: str, which: str) -> str:
        if which not in WHICH:
            raise ValueError(f"which must be one of {', '.join(WHICH)}")
        e = self._entry(self._state(), track_id)
        rel = (e.get("upgrade") or {}).get("file") if which == "upgrade" else e.get("path")
        if not rel or not (self._paths.root / rel).is_file():
            raise OpProblem("That file is not there.", "refused")
        return rel

    def _inside_root(self, rel: str) -> Path:
        """Paths from the page are accepted only inside the music folder; "." is the music folder itself."""
        root = self._paths.root
        if rel == ".":
            return root
        parts = PurePosixPath(rel or "").parts
        if not parts or rel.startswith("/") or ".." in parts:
            raise ValueError("Discjockey only opens places inside your music folder.")
        path = root / rel
        if not path.exists():
            raise OpProblem("That file or folder is not there.", "refused")
        return path

    def _others(self, state: dict) -> dict[str, str]:
        reports = self._reports()
        return views.todo_others(self._store.prep, reports[-1][1] if reports else None)

    # --- read, any time ---

    @bridge
    def dashboard(self) -> dict:
        return views.dashboard(self._state(), self._settings(), self._store, self._reports(), self._folders(),
                               setup_status(self._support, self._paths, self._music_status(), self._svc.which),
                               self._today(), self._svc.now(),
                               self._reading(), self._logins())

    @bridge
    def sidebar(self) -> dict:
        state = self._state()
        count = views.todo(state, "all", False, self._others(state), self._today())["chips"]["all"]
        # the dot on "Download limits": a warning sign the user hasn't marked as seen, or a service paused today
        warnings = any(c["new_warnings"] or c["paused"] for c in views.limit_cards(state, self._settings(), self._today()))
        return views.sidebar(state, self._folders(), count, warnings)

    @bridge
    def sync_preview(self) -> dict:
        state = self._state()
        return views.sync_preview(self._store, state, self._settings(), self._today(), self._svc.now(),
                                  self._reading(), self._cover(self._images()), self._logins())

    @bridge
    def refresh(self, auto: bool = False) -> dict:
        """auto: the hub's own read (when it opens, or the Sync page when it opens first). Only one per session
        starts, whatever its outcome; later ones are refused, so a stopped or failed read is never redone by itself."""
        with self._auto_lock:
            if auto and self._store.auto_read:
                raise OpProblem(AUTO_READ_DONE, "refused")
            job = self._jobs.start_refresh(refresh_work(self._paths, self._store, self._svc.now, infos=self._infos,
                                                         lock=self._jobs.scan_lock))
            if auto:
                self._store.auto_read = True
        return {"job_id": job.id}

    @bridge
    def stop_refresh(self) -> dict:
        return {"stopped": self._jobs.stop_refresh()}

    @bridge
    def job_status(self) -> dict:
        return {**self._jobs.status(), "spotify": views.spotify_status(self._store, self._svc.now(), self._reading(),
                                                                         self._logins())}

    @bridge
    def library(self, folder: str | None = None, query: str = "", filter: str = "all", sort: str = "artist") -> dict:
        if filter not in views.LIBRARY_FILTERS:
            raise ValueError(f"filter must be one of {', '.join(views.LIBRARY_FILTERS)}")
        state = self._state()
        out = views.library(state, folder, query, filter, sort, self._cover(self._images()))
        self._remember(state, [r["track_id"] for r in out["rows"]])
        return out

    @bridge
    def track(self, track_id: str) -> dict:
        state = self._state()
        e = self._entry(state, track_id)
        prep = self._store.prep
        detail = views.track_detail(track_id, e, prep.fetched if prep else [], self._today(),
                                    self._cover(self._images()), self._audio)
        self._remember(state, [track_id])
        return {"track": detail}

    @bridge
    def todo(self, filter: str = "all", show_hidden: bool = False) -> dict:
        state = self._state()
        out = views.todo(state, filter, bool(show_hidden), self._others(state), self._today(),
                         self._cover(self._images()))
        self._remember(state, [i["track_id"] for g in out["groups"] for i in g["items"]])
        return out

    def _service(self, service: str, set_up: bool = False) -> str:
        if service not in SERVICES:
            raise ValueError(f"service must be one of {', '.join(SERVICES)}")
        if set_up and service not in views.services_of(self._settings()):
            raise OpProblem(f"Set up {SERVICE_NAMES[service]} first.", "refused")
        return service

    @bridge
    def limits(self, service: str = "qobuz") -> dict:
        return views.limits(self._service(service), self._state(), self._settings(), self._store.prep, self._today())

    @bridge
    def limits_what_if(self, service: str, limit: int, extra_today: int = 0) -> dict:
        service, limit, extra_today = self._service(service, set_up=True), int(limit), int(extra_today)
        if not 1 <= limit <= MAX_DAILY_LIMIT or not 0 <= extra_today <= MAX_EXTRA:
            raise ValueError(f"The daily limit goes from 1 to {MAX_DAILY_LIMIT}, the extra for today from 0 to "
                             f"{MAX_EXTRA}.")
        return views.limits_what_if(service, limit, extra_today, self._state(), self._settings(), self._store.prep,
                                    self._today())

    @bridge
    def runs(self) -> dict:
        return {"runs": views.runs(self._reports())}

    @bridge
    def run(self, run_id: str) -> dict:
        found = dict(self._reports()).get(run_id) if RUN_ID.fullmatch(run_id or "") else None
        if found is None:
            raise OpProblem("That run report is not there any more.", "refused")
        return {"run": views.run_detail(run_id, found, self._state(), cover=self._cover(self._images()),
                                        folder_order=self._folders())}

    @bridge
    def spectrum(self, track_id: str, which: str = "current") -> dict:
        rel = self._file_of(track_id, which)
        e = self._entry(self._state(), track_id)
        data = spec.spectrum(self._paths, rel, decode=self._svc.decode)
        return {"spectrum": {**data, "which": which, "cutoff_hz": e.get("cutoff_hz") if which == "current" else None}}

    @bridge
    def media_url(self, track_id: str, which: str = "current") -> dict:
        rel = self._file_of(track_id, which)
        url = self._media.url(rel) if self._media is not None else None
        if url is None:
            raise OpProblem("This file can't be played here.", "refused")
        return {"url": url}

    @bridge
    def setup_status(self) -> dict:
        return setup_status(self._support, self._bound, self._music_status(), self._svc.which, self._svc.home)

    @bridge
    def downloads_view(self) -> dict:
        """The source ladder and the account panels (Settings, Setup): each source's state and the library by rung.
        Without a music folder the library counts are zero."""
        settings = self._settings()
        names = {s: profile_name(a.browser, a.profile, self._svc.home) for s, a in settings.accounts.items()}
        qobuz_ok = setup_status(self._support, self._bound, self._music_status(), self._svc.which)["qobuz"]
        state = self._state() if self._bound is not None else library.empty_state()
        return {"downloads": views.downloads(state, settings, qobuz_ok, names, self._today())}

    @bridge
    def select(self, track_id: str | None) -> dict:
        """The to-do item the page shows, so a file dropped on the window goes to that track."""
        with self._lock:
            self._selected = track_id
        return {}

    # --- other ---

    @bridge
    def show_in_finder(self, track_id: str, which: str = "current") -> dict:
        self._svc.reveal(self._paths.root / self._file_of(track_id, which))
        return {}

    @bridge
    def reveal(self, rel_path: str) -> dict:
        self._svc.reveal(self._inside_root(rel_path))
        return {}

    @bridge
    def open_report(self, run_id: str) -> dict:
        if not RUN_ID.fullmatch(run_id or ""):
            raise ValueError("That is not a run report.")
        self._svc.open_path(self._inside_root(f"{library.DATA_DIR}/reports/{run_id}.md"))
        return {}

    @bridge
    def open_licenses(self) -> dict:
        """Settings -> About: the licences of everything Discjockey bundles, in Finder (spec public-release §6.5)."""
        folder = tools.licenses_dir()
        if not folder.is_dir():
            raise OpProblem("The licences folder is missing from this copy of Discjockey.", "refused")
        self._svc.open_path(folder)
        return {}

    @bridge
    def open_external(self, url: str) -> dict:
        """Websites open in the system browser, never inside the hub window."""
        if not re.fullmatch(r"https?://[^\s]+", url or ""):
            raise ValueError("Only web links (https://...) can be opened.")
        self._svc.open_url(url)
        return {}

    @bridge
    def app_update(self) -> dict:
        """Is a newer Discjockey out (spec public-release §8)? The last answer of the update check, never the
        network: {state: available | up_to_date | unknown, current, latest, url}. Works without a music folder."""
        return self._update.status()

    def _watch_app_update(self, interval: float = _UPDATE_TICK) -> threading.Thread:
        """The update check at start, then every `interval` while the window is open: the cached answer, or GitHub's
        once the cache is a day old (spec public-release §8). Sends AppUpdate when the answer changed; the page also
        reads app_update() when it loads, for the first answer and for reloads (events sent before the page is ready are
        buffered, not lost)."""
        def tick() -> None:
            try:
                if self._update.check():
                    self._emit(AppUpdate(**self._update.status()))
            except Exception:  # a bug here must never end the window's session; Checker itself never raises
                log.warning("update check failed", exc_info=True)

        def loop() -> None:
            while not self._jobs.closed.is_set():  # a hub closed before the thread ran asks nothing
                tick()
                self._jobs.closed.wait(interval)

        thread = threading.Thread(target=loop, name="hub-update-check", daemon=True)
        thread.start()
        return thread

    def _watch_playlists_file(self, interval: float = 2.0) -> threading.Thread:
        """Reads Spotify again by itself when playlists.txt changes (edited by hand or saved on the playlists page),
        as soon as no hub sync runs (that one reads the playlists itself)."""
        def stamp():
            try:
                st = self._paths.playlists_file.stat()
                return st.st_mtime_ns, st.st_size
            except OSError:
                return None

        def loop() -> None:
            last, due = stamp(), False
            while not self._jobs.closed.wait(interval):
                now = stamp()
                if now != last:
                    last, due = now, True
                if due and self.refresh().get("ok"):
                    due = False

        thread = threading.Thread(target=loop, name="hub-playlists-watch", daemon=True)
        thread.start()
        return thread

    # --- what the network reads and the write jobs share ---

    def _no_sync_running(self) -> None:
        """Searches and previews would send unpaced requests next to a paced sync (the hub's or the console's)."""
        job = self._jobs.running()
        if (job is not None and job.kind == "sync") or self._jobs.console_running():
            raise Busy(SYNC_RUNNING, "sync_running")

    def _spotify_track(self, track_id: str, e: dict) -> SourceTrack:
        prep = self._store.prep
        ids = {track_id, *(e.get("aliases") or [])}
        for fp in prep.fetched if prep else []:
            for t in fp.tracks:
                if t.id in ids:
                    return t
        return ops.track_of(track_id, e)

    def _open_qobuz(self):
        try:
            return self._svc.open_qobuz(self._support)
        except QobuzError as e:
            raise OpProblem(f"Could not log in to Qobuz: {login_problem(e)}", "failed") from None

    def _budget(self, state: dict) -> Budget:
        """Today's Qobuz budget, carrying this session's failure streak."""
        budget = Budget(state, lambda: library.save_state(self._paths, state), self._settings())
        with self._lock:
            for name, value in self._qobuz_streak.items():
                setattr(budget, name, value)
        return budget

    def _keep_streak(self, budget: Budget) -> None:
        with self._lock:
            self._qobuz_streak = {name: getattr(budget, name) for name in self._qobuz_streak}

    def _account_budgets(self, state: dict) -> dict[str, Budget]:
        """Today's budget of each account that is set up, carrying this session's failure streak (a paused account
        stays paused for "Use this" until the next sync)."""
        accounts = run.account_budgets(state, lambda: library.save_state(self._paths, state),
                                       self._settings())
        with self._lock:
            for service, budget in accounts.items():
                for name, value in self._account_streaks.get(service, {}).items():
                    setattr(budget, name, value)
        return accounts

    def _keep_account_streaks(self, accounts: dict[str, Budget]) -> None:
        with self._lock:
            for service, budget in accounts.items():
                self._account_streaks[service] = {name: getattr(budget, name) for name in self._qobuz_streak}

    def _single(self, kind: str, track_id: str, do) -> dict:
        """A single operation as a write job (spec 6.7): recovery first, precondition (the entry as the page last
        showed it), the change, not_lossless.md and the operations log."""
        with self._lock:
            expect = self._shown.get(track_id)

        def work(ctx) -> dict:
            done = ops.run_single(self._paths, kind, track_id, expect, lambda state: do(state, ctx),
                                  now=self._svc.now)
            return {"track_id": track_id, "result": asdict(done.result),
                    "recovered": [[message, ok] for message, ok in done.recovered]}

        return {"job_id": self._jobs.start(kind, work, track_id=track_id).id}

    def _replace_with(self, track_id: str, find: Callable) -> dict:
        """use_candidate / use_link: `find(qobuz, fallback)` gives the version, which is then downloaded and placed."""
        def do(state: dict, ctx):
            e = state["tracks"][track_id]
            budget = self._budget(state)
            accounts = self._account_budgets(state)
            problem = ops.refusal(self._paths, e, find.cand, budget, find.needs_qobuz)
            if problem:  # before any Qobuz request (login, link lookup)
                raise OpProblem(problem)
            qobuz = self._open_qobuz() if find.needs_qobuz else None
            try:
                fallback = self._svc.fallback(emit=ctx.emit, check=ctx.token.check,
                                              logins={s: (a.browser, a.profile) for s, a in self._settings().accounts.items()})
                cand = find(qobuz, fallback)
                return ops.use_candidate(self._paths, state, track_id, cand, qobuz=qobuz, fallback=fallback,
                                         budget=budget, track=self._spotify_track(track_id, e), emit=ctx.emit,
                                         token=ctx.token, process=self._svc.process, accounts=accounts,
                                         now=self._svc.now)
            finally:
                self._keep_streak(budget)
                self._keep_account_streaks(accounts)
                if qobuz is not None:
                    qobuz.close()
        return self._single(find.kind, track_id, do)

    def _on_drop(self, event: dict) -> None:
        """pywebview's drop handler on the page (app.py): remembers the file for the selected to-do item and tells the
        page. Runs on a thread of its own; never raises."""
        try:
            files = (event.get("dataTransfer") or {}).get("files") or []
            found = next((f for f in files if f.get("pywebviewFullPath")), None)
            with self._lock:
                track_id = self._selected
            if found is None:
                self._emit(FileDropped(track_id, "", False, "Discjockey could not see where this file is. Drag it "
                                                            "from a Finder window."))
                return
            path = Path(found["pywebviewFullPath"])
            try:
                with open(path, "rb"):
                    readable = path.is_file()
            except OSError:
                readable = False
            message = "" if readable else ops.NO_ACCESS
            if readable and track_id is None:
                readable, message = False, NOT_SELECTED
            with self._lock:
                self._dropped = {"track_id": track_id, "path": path} if readable else None
            self._emit(FileDropped(track_id, path.name, readable, message))
        except Exception:
            traceback.print_exc()

    # --- playlists (playlists.txt stays the source of truth) ---

    def _tracks_by_id(self) -> dict:
        prep = self._store.prep
        return {**self._extra_tracks, **{fp.line.ref: fp.tracks for fp in (prep.fetched if prep else [])}}

    @bridge
    def playlists(self) -> dict:
        return views.playlists(pf.load(self._paths.playlists_file), self._tracks_by_id(), dict(self._infos),
                               self._state(), self._cover(self._images()))

    @bridge
    def add_playlist(self, url: str) -> dict:
        """A pasted link: the playlist's name, owner and cover, whether Discjockey can read it, and its tracks."""
        self._no_sync_running()
        link = pf.clean_link(url or "")
        service, pid = sources.recognise(link)  # clean_link raised for anything no source recognises
        source, ref = sources.SOURCES[service], token(service, pid)
        if source.login_state(self._support).state != "ok":
            raise sources.SourceError(NOT_CONNECTED.format(name=PLAYLIST_SERVICES[service]), "not_set_up", service)
        reader = source.open(self._support, CancelToken())
        try:
            info = reader.info(pid)
            self._infos[ref] = info
            tracks = None
            if info.readable:
                fetched = reader.fetch(PlaylistLine(suggest_folder(info.name), pid, 0, service))
                self._extra_tracks[ref] = fetched.tracks
                tracks = len(fetched.tracks)
        finally:
            self._close(reader)
        return {"playlist_id": ref, "service": service, "service_name": PLAYLIST_SERVICES[service], "link": link,
                "info": views.info_dict(info), "tracks": tracks, "readable": info.readable,
                "suggested_folder": suggest_folder(info.name),
                "hint": None if info.readable else source.UNREADABLE_HINT}

    @bridge
    def preview_playlist_change(self, lines: list) -> dict:
        """"What this change does" for edited (unsaved) lines: the pure planner on the last playlists read, plus a
        one-time read of a playlist that was not read yet. No file changes."""
        self._no_sync_running()
        rows = rows_from(lines)
        tracks = self._tracks_by_id()
        unread = [r for r in rows if r.enabled and r.ref not in tracks]
        for service in dict.fromkeys(r.service for r in unread):  # one reader per service; a failing one is skipped
            source = sources.SOURCES[service]
            if source.login_state(self._support).state != "ok":
                continue
            try:
                reader = source.open(self._support, CancelToken())
            except sources.SourceError:
                continue
            try:
                for r in (r for r in unread if r.service == service):
                    try:
                        line = PlaylistLine("x", sources.recognise(r.link)[1], 0, service)
                        self._extra_tracks[r.ref] = reader.fetch(line).tracks
                    except sources.SourceError:
                        continue
            finally:
                self._close(reader)
        if unread:
            tracks = self._tracks_by_id()
        problem = None
        try:
            pf.validate(rows)
        except config.ConfigError as e:
            problem = str(e)
        state = self._state()
        money = views.gate(views.moneys(state, self._settings(), self._today()))
        old = pf.load(self._paths.playlists_file).rows
        change = views.playlist_change(old, rows, tracks, state, state["files"], self._today(), money,
                                       self._cover(self._images()), library_dirs=tidy.library_dirs(self._paths),
                                       rename_offer=tidy.rename_offer, placement=pf.placement(rows, tracks, state),
                                       retargeted=pf.retargeted(old, rows, tracks, state))
        return {**change, "problem": problem}

    @bridge
    def save_playlists(self, lines: list, loaded_version: str, files: dict | None = None) -> dict:
        """Writes playlists.txt. `files` is the answer to the save question when the change retargets files: `{choice:
        "leave"|"move", renames: [[old, new]], moves: [[file_id, from_path]]}`. "move" renames the chosen folders on
        disk and moves the chosen files (move batches, undoable); "leave" makes the files this save would have moved
        the user's own placement (P1). The result is `{version, batches: [BatchResultJSON]}`; a Stop after the save
        still delivers the batches so far."""
        rows = rows_from(lines)
        choice = save_choice(files)

        def work(ctx) -> dict:
            retargeted, all_renames = {}, []
            if choice is not None:  # the targets before the save are what the save changes
                before = pf.load(self._paths.playlists_file).rows
                retargeted = pf.retargeted(before, rows, self._tracks_by_id(), self._state())
                all_renames = pf.renames(before, rows)
            version = pf.save(self._paths.playlists_file, rows, loaded_version or "")
            self._store.mark_stale()  # the plan was made for the old lines
            if choice is None:
                return {"version": version, "batches": []}
            try:
                done = tidy.after_save(self._paths, retargeted, choice, emit=ctx.emit, token=ctx.token,
                                       now=self._svc.now, all_renames=all_renames)
            except tidy.Stopped as stopped:
                ctx.failed_result = {"version": version, "batches": self._batch_results(stopped.results)}
                raise
            except Exception:  # the file is saved: the page needs the new version, whatever else went wrong
                ctx.failed_result = {"version": version, "batches": []}
                raise
            return {"version": version, "batches": self._batch_results(done)}

        return {"job_id": self._jobs.start("save_playlists", work).id}

    # --- tidy-up and the move log (plan library stage 2, I5) ---

    @contextlib.contextmanager
    def _move_log(self):
        """The library's records for reading; None while there is no library.db yet (nothing was ever moved)."""
        if not self._paths.db_file.exists():
            yield None
            return
        try:
            with db.connect(self._paths.db_file) as conn:
                db.check(conn)
                yield conn
        except sqlite3.Error as e:
            raise db.unreadable(e) from None

    def _batch_title(self, conn, b: BatchRow) -> str:
        """"Tidy-up", "Saved playlists", "Renamed A to B", "Undo of: <title of the batch it undid>"."""
        if b.started_by != "undo":
            return views.batch_title(b)
        target = db.batch(conn, b.undoes) if b.undoes is not None else None
        return views.batch_title(b, self._batch_title(conn, target) if target else None)

    def _batch_results(self, results) -> list[dict]:
        """BatchResultJSON of each result that ran a batch (a call that had nothing to move leaves no batch)."""
        done = [r for r in results if r.batch_id is not None]
        with self._move_log() as conn:
            return [views.batch_result(r, self._result_title(conn, r)) for r in done]

    def _result_title(self, conn, r: BatchResult) -> str:
        row = db.batch(conn, r.batch_id) if conn is not None and r.batch_id is not None else None
        return self._batch_title(conn, row) if row else views.BATCH_TITLES.get(r.started_by, "Undo")

    @bridge
    def tidy_preview(self) -> dict:
        """The "Tidy up files" preview: every file the playlist order would put elsewhere (plan I5)."""
        state = self._state()
        return views.tidy_preview(planner.tidy_rows(state), state, self._cover(self._images()))

    @bridge
    def move_batches(self) -> dict:
        """The 20 newest move batches (tidy-ups, saves, folder renames, undos), newest first."""
        with self._move_log() as conn:
            if conn is None:
                return views.move_batches([], 0)
            rows, total = db.batches(conn)
            known = {b.id for b in rows}
            older = {b.undoes for b in rows if b.undoes is not None and b.undoes not in known}
            titles = {i: self._batch_title(conn, b) for i in older if (b := db.batch(conn, i)) is not None}
            return views.move_batches(rows, total, titles)

    @bridge
    def undo_preview(self, batch_id: int) -> dict:
        """What undoing a batch would do, move by move, before the page asks for it."""
        if isinstance(batch_id, bool) or not isinstance(batch_id, int):
            raise ValueError(NO_BATCH)
        state = self._state()
        with self._move_log() as conn:
            row = db.batch(conn, batch_id) if conn is not None else None
            if row is None:
                raise ValueError(NO_BATCH)
            title = self._batch_title(conn, row)
        moves = tidy.undo_preview(self._paths, state, batch_id)
        return views.undo_preview(row, moves, state["files"], title)

    @bridge
    def tidy_up(self, moves: list) -> dict:
        """Moves the files the page chose (`[[file_id, from_path]]`, the path as the preview showed it) to where the
        playlist order puts them: a write job (kind "tidy"); the result is a BatchResultJSON."""
        sent = file_moves(moves)
        if not sent:
            raise ValueError(NOTHING_CHOSEN)

        def work(ctx) -> dict:
            try:
                done = tidy.tidy_up(self._paths, sent, emit=ctx.emit, token=ctx.token, now=self._svc.now)
            except tidy.Stopped as stopped:
                ctx.failed_result = self._batch_result(stopped.result)
                raise
            return self._batch_result(done)

        return {"job_id": self._jobs.start("tidy", work).id}

    @bridge
    def undo_moves(self, batch_id: int) -> dict:
        """Undoes a batch (a batch of its own, in reverse order): a write job (kind "undo_moves"); the result is a
        BatchResultJSON."""
        if isinstance(batch_id, bool) or not isinstance(batch_id, int):
            raise ValueError(NO_BATCH)
        with self._move_log() as conn:
            if conn is None or db.batch(conn, batch_id) is None:
                raise ValueError(NO_BATCH)

        def work(ctx) -> dict:
            try:
                done = tidy.undo(self._paths, batch_id, emit=ctx.emit, token=ctx.token, now=self._svc.now)
            except tidy.Stopped as stopped:
                ctx.failed_result = self._batch_result(stopped.result)
                raise
            return self._batch_result(done)

        return {"job_id": self._jobs.start("undo_moves", work).id}

    def _batch_result(self, r: BatchResult) -> dict:
        """BatchResultJSON of one result, also when nothing was asked to move (no batch)."""
        with self._move_log() as conn:
            return views.batch_result(r, self._result_title(conn, r))

    # --- read with network, not while a sync runs ---

    @bridge
    def search_candidates(self, track_id: str) -> dict:
        self._no_sync_running()
        e = self._entry(self._state(), track_id)
        track = self._spotify_track(track_id, e)
        notes = []
        try:
            qobuz = self._svc.open_qobuz(self._support)
        except QobuzNotSetUp:
            qobuz = None  # candidates.search says so itself
        except QobuzError as err:
            qobuz = None
            notes.append(f"Qobuz was not searched: {login_problem(err)}")
        try:
            found, more = candidates.search(track, e, qobuz, self._svc.fallback(),
                                            skip=candidates.protected(self._paths))
        finally:
            if qobuz is not None:
                qobuz.close()
        if notes:
            more = [m for m in more if not m.startswith("Qobuz is not set up")]
        rows = [candidate_row(s.candidate, track, score=s.score, matches=s.matches, length_ok=s.length_ok,
                              current=s.current, rejected=s.rejected) for s in found]
        key = current_key(e)
        if key and not any(r["current"] for r in rows):  # the version in the library, as the dialog's first row
            source, sid = key.split(":", 1)
            rows.insert(0, candidate_row(Candidate(source, sid, e["title"], e["artist"], None), track, score=None,
                                         matches=False, length_ok=True, current=True,
                                         rejected=key in (e.get("rejected_sources") or [])))
        return {"track_id": track_id, "spotify_duration_s": round(track.duration_ms / 1000, 1),
                "current_quality_label": views.quality_label(e), "candidates": rows, "notes": notes + more}

    @bridge
    def preview(self, track_id: str, candidate: dict) -> dict:
        self._no_sync_running()
        self._entry(self._state(), track_id)
        cand = to_candidate(candidate)
        out = candidates.preview(self._paths, cand, self._svc.fallback())
        url = self._media.url(media_mod.cache_address(self._paths, out)) if self._media is not None else None
        if url is None:
            raise OpProblem("The preview can't be played here.", "failed")
        return {"url": url}

    # --- write jobs (one at a time; each returns {"job_id"} at once, the outcome comes as JobFinished) ---

    @bridge
    def start_sync(self, selected: list) -> dict:
        ticked = set()
        for key in selected or []:
            if not (isinstance(key, (list, tuple)) and len(key) == 3 and all(isinstance(k, str) for k in key)):
                raise ValueError("Each ticked action is [kind, track_id, to_dir].")
            ticked.add(tuple(key))
        job = self._jobs.start("sync", sync_work(self._paths, self._store, ticked, self._svc.now))
        with self._lock:  # the sync has its own auto-stop; "Use this" starts a new streak after it
            self._qobuz_streak = {"failures_in_a_row": 0, "download_failed_in_row": False, "stopped": False}
            self._account_streaks = {}
        return {"job_id": job.id}

    @bridge
    def stop(self) -> dict:
        """Stop safely: the running write job (a sync, a download, a Spotify login) ends after its current step."""
        return {"stopped": self._jobs.stop()}

    @bridge
    def save_limits(self, service: str, limit: int, extra_today: int = 0) -> dict:
        service, limit, extra_today = self._service(service, set_up=True), int(limit), int(extra_today)
        if not 1 <= limit <= MAX_DAILY_LIMIT or not 0 <= extra_today <= MAX_EXTRA:
            raise ValueError(f"The daily limit goes from 1 to {MAX_DAILY_LIMIT}, the extra for today from 0 to "
                             f"{MAX_EXTRA}.")

        def work(ctx) -> dict:
            today: date = self._today()
            self._update_settings(
                lambda s: s.with_limit(service, limit, today.isoformat() if extra_today else None, extra_today))
            return {"service": service, "limit": limit, "extra_today": extra_today}

        return {"job_id": self._jobs.start("save_limits", work).id}

    @bridge
    def mark_warnings_seen(self, service: str) -> dict:
        """"Got it" on the Download limits page: the service's warning signs up to now are no longer new (the card and
        the sidebar dot go quiet); they stay listed until they drop out of the 14 days."""
        service = self._service(service, set_up=True)

        def work(ctx) -> dict:
            until = self._svc.now().isoformat(timespec="seconds")
            self._update_settings(lambda s: s.with_seen(service, until))
            return {"service": service, "seen_until": until}

        return {"job_id": self._jobs.start("mark_warnings_seen", work).id}

    @bridge
    def hide(self, track_id: str, hidden: bool) -> dict:
        return self._single("hide" if hidden else "unhide", track_id,
                            lambda state, ctx: ops.set_hidden(self._paths, state, track_id, bool(hidden)))

    @bridge
    def never_download(self, track_id: str, never: bool) -> dict:
        """"Never download" on the Sync page (or undo it): kept in state.json → never; the planner leaves the track
        out of every sync until undone. Nothing is downloaded or deleted. The preview moves the track at once."""
        prep = self._store.prep
        a = next((a for a in [*(prep.plan.actions if prep else []), *(prep.plan.never if prep else [])]
                  if a.track_id == track_id), None)
        if never and a is None:
            raise OpProblem("This track is not in the sync plan any more.", "changed")
        info = None
        if a is not None:
            e = prep.state["tracks"].get(track_id)
            artist, title = (e["artist"], e["title"]) if e else (a.track.first_artist, a.track.title)
            info = {"artist": artist, "title": title, "folder": a.folder}

        def work(ctx) -> dict:
            state = library.open_state(self._paths)
            if never:
                state["never"][track_id] = {**info, "at": self._svc.now().date().isoformat()}
            else:
                state["never"].pop(track_id, None)
            library.save_state(self._paths, state)
            rep.write_not_lossless(self._paths, state)  # a "not found" track leaves (or rejoins) that list
            what = "never download" if never else "download again"
            ops.log_operation(self._paths, self._svc.now(), track_id, info, what, "done", what)
            return {"track_id": track_id, "never": bool(never)}

        return {"job_id": self._jobs.start("never_download", work, track_id=track_id).id}

    @bridge
    def rescan_library(self) -> dict:
        """The window opened, or came back to the front after a while (spec library §6.4): index Library/ against
        library.db, so files moved or replaced by hand are found. A write job (kind "scan"): busy/console as every
        write method; the page ignores those answers, a running sync scans by itself. A scan that changed something
        plans the stored preview again from its own Spotify read (run.replan, no new read), so Sync and To-do never
        show the plan from before the scan."""
        def work(ctx) -> dict:
            summary = library.scan_library(self._paths, ctx.emit)
            prep = self._store.prep
            if prep is not None and summary != library.ScanSummary():
                preview_after_run(self._store, prep, self._store.read_at)
            return {"moved": summary.moved, "new": summary.new, "gone": summary.gone, "changed": summary.replaced,
                    "copies": summary.copies}

        return {"job_id": self._jobs.start("scan", work).id}

    @bridge
    def add_bought_file(self, track_id: str) -> dict:
        with self._lock:
            dropped = self._dropped
            if not dropped or dropped["track_id"] != track_id:
                raise OpProblem(NO_DROP, "refused")
        answer = self._single("add_bought_file", track_id, lambda state, ctx: ops.add_bought_file(
            self._paths, state, track_id, dropped["path"], analyze=self._svc.analyze, now=self._svc.now))
        with self._lock:  # only once the job runs: a refused job (busy) keeps the file for the next "Add"
            if self._dropped is dropped:
                self._dropped = None
        return answer

    @bridge
    def use_candidate(self, track_id: str, candidate: dict) -> dict:
        cand = to_candidate(candidate)

        def find(qobuz, fallback):
            return cand

        find.kind, find.needs_qobuz, find.cand = "use_candidate", cand.source == "qobuz", cand
        return self._replace_with(track_id, find)

    @bridge
    def use_link(self, track_id: str, url: str) -> dict:
        source, _ = candidates.parse_link(url)  # a plain message at once for links Discjockey can't use

        def find(qobuz, fallback):
            try:
                return candidates.link_candidate(url, qobuz, fallback)
            except ValueError as e:
                raise OpProblem(str(e)) from None

        find.kind, find.needs_qobuz, find.cand = "use_link", source == "qobuz", None
        return self._replace_with(track_id, find)

    @bridge
    def reject_current(self, track_id: str) -> dict:
        return self._single("reject_current", track_id,
                            lambda state, ctx: ops.reject_current(self._paths, state, track_id, now=self._svc.now))

    @bridge
    def rekordbox_checked(self, track_id: str) -> dict:
        """"Done" on a "Check in rekordbox" item: the reminder goes away."""
        return self._single("rekordbox_checked", track_id,
                            lambda state, ctx: ops.rekordbox_checked(self._paths, state, track_id))

    @bridge
    def upgrade(self, track_id: str, mode: str) -> dict:
        if mode not in UPGRADE_MODES:
            raise ValueError(f"mode must be one of {', '.join(UPGRADE_MODES)}")

        def do(state: dict, ctx):
            up = state["tracks"][track_id].get("upgrade")
            if not up:
                raise OpProblem("No better version is waiting for this track any more.", "changed")
            if mode == "swap":
                return upgrades.swap(self._paths, state, track_id, up, self._svc.compare)
            if mode == "add_new":
                return upgrades.add_new(self._paths, state, track_id, up, now=self._svc.now)
            return upgrades.discard(self._paths, state, track_id, up)

        return self._single(f"upgrade_{mode}", track_id, do)


    # --- setup wizard (spec 5.7); the steps that write files are write jobs ---

    @bridge
    def setup_check_tools(self) -> dict:
        """ffmpeg/ffprobe/deno and the download tools' versions. An unexpected error reading the versions only
        empties `download_tools` (with `download_tools_problem`); the rest of the check still answers."""
        tools_ = {tool: self._svc.which(tool) is not None for tool in TOOL_HINTS}
        download_tools, problem = None, None
        try:
            download_tools = tool_updates.current_status(self._support.support)
        except Exception:  # noqa: BLE001 - one unreadable folder must not blank the whole tool check
            log.warning("download tools: could not read their status", exc_info=True)
            problem = DOWNLOAD_TOOLS_UNREADABLE
        return {"tools": tools_, "missing": [t for t, ok in tools_.items() if not ok],
                "hints": {t: TOOL_HINTS[t] for t, ok in tools_.items() if not ok}, "redirect_uri": REDIRECT_URI,
                "download_tools": download_tools, "download_tools_problem": problem}

    @bridge
    def setup_save_client_id(self, client_id: str) -> dict:
        value = (client_id or "").strip()
        if not CLIENT_ID.fullmatch(value):
            raise ValueError("That does not look like a Client ID (32 letters and digits).")

        def work(ctx) -> dict:
            self._save_spotify_app(value, None)
            return {}

        return {"job_id": self._jobs.start("setup_save_client_id", work).id}

    def _save_spotify_app(self, client_id: str, user: str | None) -> None:
        """.spotify_app.json: the Client ID and, after a login, the account's display name (Settings: "connected as")."""
        data = {"client_id": client_id, **({"user": user} if user else {})}
        library.write_json_atomic(self._support.spotify_app, data, parents=True)  # the support folder may be new

    @bridge
    def spotify_sign_out(self) -> dict:
        """Forgets the Spotify login (the Client ID stays, so Connect signs in again in one step)."""
        def work(ctx) -> dict:
            self._support.spotify_token.unlink(missing_ok=True)
            try:
                client_id = json.loads(self._support.spotify_app.read_text(encoding="utf-8"))["client_id"]
            except (OSError, ValueError, KeyError, TypeError):
                return {}
            self._save_spotify_app(client_id, None)
            return {}

        return {"job_id": self._jobs.start("spotify_sign_out", work).id}

    @bridge
    def setup_spotify_login(self) -> dict:
        """Opens the system browser for the Spotify login; the job ends by itself when the login comes back, after
        5 minutes, or with stop()."""
        def work(ctx) -> dict:
            try:
                client_id = json.loads(self._support.spotify_app.read_text(encoding="utf-8"))["client_id"]
            except (OSError, ValueError, KeyError):
                raise OpProblem("Paste the Client ID first.") from None
            spotify.login(client_id, self._support.spotify_token, open_browser=self._svc.open_url, token=ctx.token)
            _, name = spotify.current_user(spotify.load_session(self._support))
            self._save_spotify_app(client_id, name)
            return {"user": name}

        return {"job_id": self._jobs.start("setup_spotify_login", work).id}

    @bridge
    def setup_qobuz_login(self, email: str, password: str) -> dict:
        def work(ctx) -> dict:
            try:
                qobuz.password_login(self._support, email or "", password or "")
            except QobuzLoginRejected:  # Qobuz refused it; offline or a Qobuz hiccup records nothing
                self._update_settings(lambda s: s.with_check("qobuz", self._check_record(
                    {"ok": False, "problem": "login_failed", "kbps": None})))
                raise
            self._update_settings(lambda s: replace(s, qobuz_skipped=False).with_check(
                "qobuz", self._check_record({"ok": True, "problem": None, "kbps": None})))
            return {}

        return {"job_id": self._jobs.start("setup_qobuz_login", work).id}

    def _check_record(self, check: dict) -> dict:
        """A login check as settings.json keeps it (Settings shows "checked today" without checking again)."""
        return {"ok": check["ok"], "problem": check["problem"], "kbps": check["kbps"],
                "at": self._svc.now().isoformat(timespec="seconds")}

    def _account(self, service: str, browser: str | None = None) -> None:
        if service not in ACCOUNTS:
            raise ValueError(f"service must be one of {', '.join(ACCOUNTS)}")
        if browser is not None and browser not in BROWSERS:
            raise ValueError(f"browser must be one of {', '.join(BROWSERS)}")

    def _update_settings(self, change: Callable[[Settings], Settings]) -> None:
        """The file as it is now, changed, saved: every settings write in the hub goes through here. One writer at a
        time (spec settings-setup §13): a write job holds the engine lock already; a save from outside one (the
        sign-in slot, a check from the page) takes it for the moment of the save and raises Busy (busy / console)
        instead of waiting. The mutex keeps this process's saves in order."""
        with self._settings_mutex, self._jobs.lock_briefly():
            save_settings(self._support.settings_file, change(load_settings(self._support.settings_file)))

    @bridge
    def setup_skip_qobuz(self) -> dict:
        """"I don't have Qobuz": the sync starts at the SoundCloud originals and the account sources."""
        def work(ctx) -> dict:
            self._update_settings(lambda s: replace(s, qobuz_skipped=True))
            return {}

        return {"job_id": self._jobs.start("setup_skip_qobuz", work).id}

    @bridge
    def setup_account(self, service: str, browser: str, profile: str | None = None) -> dict:
        """Checks the login in that browser profile (only cookie names are read), then saves the browser and profile
        with the check. A YouTube login without Premium is not saved; a SoundCloud one is (many tracks have no Go+
        stream, see check_message). A failed check of the saved login itself is recorded on it."""
        self._account(service, browser)

        def work(ctx) -> dict:
            check = self._svc.fallback(emit=ctx.emit, check=ctx.token.check).check_account(service, browser, profile)
            return self._account_result(service, browser, profile, check)

        return {"job_id": self._jobs.start("setup_account", work).id}

    def _account_result(self, service: str, browser: str, profile: str | None, check: dict) -> dict:
        saved = check["ok"] or (service == "soundcloud" and check["problem"] == "no_premium")
        record = self._check_record(check)

        def change(s: Settings) -> Settings:
            if saved:
                return s.with_account(service, browser, profile).with_check(service, record)
            a = s.accounts.get(service)
            if a is not None and (a.browser, a.profile) == (browser, profile):
                return s.with_check(service, record)  # the saved login no longer works: Settings says so
            return s
        self._update_settings(change)
        return {"service": service, "browser": browser, "profile": profile, "saved": saved,
                "check": {**{k: check[k] for k in ("ok", "problem", "kbps")},
                          "message": check_message(service, browser, check)}}

    @bridge
    def find_logins(self, service: str) -> dict:
        """Which installed browsers (and which of their profiles) hold a YouTube or SoundCloud login (spec
        settings-setup §6.1). Reads only cookie names, from copies; never asks macOS for a password."""
        self._account(service)
        home, default = self._svc.home, browsers.default_browser(self._svc.home)
        out = []
        for b in browsers.installed(home):
            scan = browsers.logins(service, b, home)
            out.append({"id": b, "name": BROWSERS[b], "default": b == default, "readable": scan["readable"],
                        "problem": scan["problem"],
                        "profiles": [{**p, "signed_in": p["id"] in scan["profiles"]}
                                     for p in browsers.profiles(b, home)]})
        out.sort(key=lambda x: (not x["default"], x["name"]))
        return {"browsers": out}

    @bridge
    def account_sign_in(self, service: str, browser: str, profile: str | None = None) -> dict:
        """Opens the service's sign-in page in that browser and waits (up to 10 minutes, Cancel: stop_sign_in) until
        a login shows up in it; then checks it as setup_account does. A chosen Chrome/Brave/Edge profile opens in its
        own window and only its login counts; other browsers open their default profile, so a login in any of their
        profiles counts (the chosen one first). Runs beside the write jobs: waiting changes nothing, and a sync may
        start meanwhile; then no check runs and the job ends sync_running (spec settings-setup §13)."""
        self._account(service, browser)
        self._no_sync_running()
        if browser not in browsers.installed(self._svc.home):
            raise OpProblem(f"{BROWSERS[browser]} isn't installed on this Mac.", "refused")
        name = BROWSERS[browser]

        def work(ctx) -> dict:
            first = browsers.logins(service, browser, self._svc.home)
            if first["problem"] == "no_access":
                raise OpProblem(check_message(service, browser, {"ok": False, "problem": "cookies_unreadable"}),
                                "failed")
            self._svc.open_in(browser, _SIGN_IN_URLS[service], profile)
            ctx.emit(SignInPhase(service, "waiting", browser, name))
            start = time.monotonic()
            while True:
                scan = browsers.logins(service, browser, self._svc.home)
                if scan["problem"] == "no_access":
                    raise OpProblem(check_message(service, browser, {"ok": False, "problem": "cookies_unreadable"}),
                                    "failed")
                hits = [p for p in scan["profiles"] if profile is None or p == profile
                        or browser not in browsers.CHROMIUM]
                if hits:
                    break
                if time.monotonic() - start >= _SIGN_IN_TIMEOUT:
                    raise OpProblem("Didn't see a login in 10 minutes. Sign in again.", "failed")
                ctx.token.sleep(_SIGN_IN_POLL)
            found = profile if profile in hits else hits[0]
            try:  # a sync (the hub's or the console's) started while the user signed in: no unpaced check beside it
                self._no_sync_running()
            except Busy:
                raise OpProblem("A sync started while you signed in. Check again after the sync.",
                                "sync_running") from None
            ctx.emit(SignInPhase(service, "checking", browser, name))
            check = self._svc.fallback(emit=ctx.emit, check=ctx.token.check).check_account(service, browser, found)
            try:
                return self._account_result(service, browser, found, check)
            except Busy as e:  # a write job or the console holds the lock: the save would race it
                job = self._jobs.running()
                if e.kind == "busy" and (job is None or job.kind != "sync"):
                    raise OpProblem("Discjockey saw your login but couldn't save it while it saved another change. "
                                    "Check again in a moment.", "busy") from None
                raise OpProblem("Discjockey saw your login but couldn't save it while a sync runs. Check again after "
                                "the sync.", e.kind) from None

        return {"job_id": self._jobs.start_sign_in("account_sign_in", work).id}

    @bridge
    def stop_sign_in(self) -> dict:
        """Cancel on a sign-in that waits for the browser (a running sync is never touched)."""
        return {"stopped": self._jobs.stop_sign_in()}

    @bridge
    def open_privacy_settings(self) -> dict:
        """System Settings at Full Disk Access (Safari's logins need it)."""
        self._svc.open_url(_PRIVACY_SETTINGS)
        return {}

    @bridge
    def qobuz_check_login(self) -> dict:
        """Settings' "Check again" for Qobuz: logs in with the saved login and searches once; records the outcome
        (login_failed only when Qobuz refuses the login; being offline or a Qobuz hiccup records nothing)."""
        self._no_sync_running()

        def work(ctx) -> dict:
            source = None
            try:
                source = self._svc.open_qobuz(self._support)
                found = bool(source.search("Daft Punk One More Time", limit=1))
            except QobuzLoginRejected as e:  # Qobuz said no to the saved login: Settings shows it as signed out
                self._update_settings(lambda s: s.with_check("qobuz", self._check_record(
                    {"ok": False, "problem": "login_failed", "kbps": None})))
                raise OpProblem(login_problem(e), "failed") from None
            except Exception as e:  # noqa: BLE001 - offline, a Qobuz error, a failed search: says nothing about the
                # login, so no check is recorded (the last one stays). login_problem words streamrip's errors plainly
                raise OpProblem(login_problem(e) if isinstance(e, QobuzError) else
                                "Couldn't reach Qobuz to check the login. Check the internet connection and try "
                                "again.", "failed") from None
            finally:
                if source is not None and hasattr(source, "close"):
                    source.close()
            self._update_settings(lambda s: s.with_check("qobuz", self._check_record(
                {"ok": found, "problem": None if found else "search_failed", "kbps": None})))
            if not found:
                raise OpProblem("Logged in to Qobuz, but a test search found nothing.", "failed")
            return {}

        return {"job_id": self._jobs.start("qobuz_check_login", work).id}

    @bridge
    def setup_check_account(self, service: str) -> dict:
        """The saved login checked again (the Download limits page and the setup step show the answer)."""
        self._account(service)
        self._no_sync_running()
        account = self._settings().accounts.get(service)
        if account is None:
            raise OpProblem(f"{SERVICE_NAMES[service]} is not set up.", "refused")
        check = self._svc.fallback().check_account(service, account.browser, account.profile)
        record = self._check_record(check)
        self._update_settings(lambda s: s.with_check(service, record) if service in s.accounts else s)
        return {"service": service, "check": {**{k: check[k] for k in ("ok", "problem", "kbps")},
                                              "message": check_message(service, account.browser, check)}}

    @bridge
    def setup_forget_account(self, service: str) -> dict:
        self._account(service)

        def work(ctx) -> dict:
            self._update_settings(lambda s: s.with_account(service, None))
            return {"service": service}

        return {"job_id": self._jobs.start("setup_forget_account", work).id}

    @bridge
    def update_tools(self) -> dict:
        """The newest yt-dlp into the support folder (tool_updates). Afterwards (restart) the window asks to quit
        and open Discjockey again."""
        def work(ctx) -> dict:
            try:
                before, after, restart = tool_updates.update(self._support.support, fetch=self._svc.fetch,
                                                             run=self._svc.run, check=ctx.token.check)
            except tool_updates.ToolsError as e:
                raise OpProblem(str(e), e.kind) from None
            return {"before": before, "after": after, "restart": restart}

        return {"job_id": self._jobs.start("update_tools", work).id}

    @bridge
    def rollback_tools(self) -> dict:
        """Settings' "Go back to ...": yt-dlp as before the last update (tool_updates.rollback). `refused` when there
        is nothing to go back to. Afterwards (restart) the window asks to quit and open Discjockey again."""
        def work(ctx) -> dict:
            try:
                before, after, restart = tool_updates.rollback(self._support.support)
            except tool_updates.ToolsError as e:
                raise OpProblem(str(e), e.kind) from None
            return {"before": before, "after": after, "restart": restart}

        return {"job_id": self._jobs.start("rollback_tools", work).id}

    @bridge
    def quit(self) -> dict:
        """Closes the hub (after update_tools or rollback_tools with restart: the page then asks to open Discjockey
        again). Refused while a change runs."""
        if self._jobs.running() is not None:
            raise Busy("Discjockey is still busy with a change. Wait until it has finished, then quit.", "busy")
        if self._quit is not None:
            self._quit()
        return {}

    # --- the music folder (spec public-release §4) ---

    @bridge
    def pick_folder(self, start: str | None = None) -> dict:
        """The Mac's folder dialog (Setup's music folder, Settings' Change…, the missing-folder screen). {"path"}:
        the chosen folder, null when the user cancelled. Opens at `start`, else ~/Music (the nearest folder that
        exists)."""
        if self._svc.pick_folder is None:
            raise OpProblem("The folder dialog can't open here.", "refused")
        begin = Path(start).expanduser() if start else self._svc.home / "Music"
        while not begin.is_dir() and begin != begin.parent:
            begin = begin.parent
        return {"path": self._svc.pick_folder(str(begin))}

    @bridge
    def check_music_folder(self, path: str) -> dict:
        """What the folder would be as the music folder; changes nothing."""
        c = self._check_folder(path)
        return {"path": str(c.path), "exists": c.exists, "usable": c.usable, "problem": c.problem, "kind": c.kind,
                "message": library.FOLDER_PROBLEMS.get(c.problem) if c.problem else None}

    @bridge
    def set_music_folder(self, path: str) -> dict:
        """Uses the folder as the music folder (the page asked first when it holds other files). Without a bound
        library (none chosen, or the chosen one missing) it is bound at once. A bound library is never swapped while
        the window is open: the choice is saved and {"restart": true} asks the page to close Discjockey (quit()).
        Refused while a change runs (busy) or a terminal run holds the library (console); a new folder is made."""
        with self._music_lock:
            c = self._check_folder(path)
            if not c.usable:
                raise OpProblem(library.FOLDER_PROBLEMS[c.problem], "refused")
            bound = self._bound
            if bound is not None and c.path == bound.root == library.read_music_folder(self._support.support):
                return {"music": self._music_status(), "restart": False}
            # the library lock sits in the music folder: with the bound folder gone there is nothing to wait for
            gone = bound is not None and not bound.root.is_dir()
            with contextlib.nullcontext() if gone else self._jobs.lock_briefly():
                c.path.mkdir(parents=True, exist_ok=True)
                library.write_music_folder(self._support.support, c.path)
            if bound is not None:
                # another folder: restart on it; the open one again (config pointed elsewhere after an earlier
                # change): config is right now, nothing to restart
                return {"music": self._music_status(), "restart": c.path != bound.root}
            self._bind(Paths(c.path, support=self._support.support))
            music = self._music_status()
        self._first_read()  # after the lock is released: it starts a job of its own
        return {"music": music, "restart": False}

    @bridge
    def retry_music_folder(self) -> dict:
        """Try again on the missing-folder screen: binds the library when the folder is back. A library bound
        already has nothing to bind: the status says whether its folder is there again."""
        bound_now = False
        with self._music_lock:
            if self._bound is None:
                resolved = library.resolve_in(self._support.support)
                if resolved.paths is not None:
                    self._bind(resolved.paths)
                    bound_now = True
                else:  # still gone (missing), or config.json no longer names a folder (not chosen)
                    self._missing = resolved.music_folder if resolved.problem == "missing" else None
            music = self._music_status()
        if bound_now:
            self._first_read()
        return {"music": music}


def suggest_folder(name: str) -> str:
    """A folder name from a Spotify playlist name: letters, digits, - and _ only (spaces become _)."""
    text = unicodedata.normalize("NFC", name or "")
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r"[^\w\-]", "", text).strip("_-.")[:100]
    return text if text and fold(text) != "not_lossless" else "New_playlist"


NO_BATCH = "Discjockey has no record of these moves."
NOTHING_CHOSEN = "No files were chosen to move."
MALFORMED_MOVES = "Each file to move needs its number and where it is now."


def file_moves(moves) -> list[tuple[int, str]]:
    """The page's `[[file_id, from_path]]` as the engine takes it; ValueError (refused) for anything else."""
    out = []
    if not isinstance(moves, list):
        raise ValueError(MALFORMED_MOVES)
    for m in moves:
        if (not isinstance(m, (list, tuple)) or len(m) != 2 or isinstance(m[0], bool) or not isinstance(m[0], int)
                or not isinstance(m[1], str) or not m[1]):
            raise ValueError(MALFORMED_MOVES)
        out.append((m[0], m[1]))
    return out


def save_choice(files) -> SaveChoice | None:
    """The save question's answer from the page (`{choice, renames, moves}`; None: nothing was retargeted) as
    tidy.after_save takes it; ValueError (refused) for anything else."""
    if files is None:
        return None
    if not isinstance(files, dict) or files.get("choice") not in ("leave", "move"):
        raise ValueError("Choose whether to move the files or leave them where they are.")
    renames = files.get("renames") or []
    if not isinstance(renames, list) or any(not isinstance(r, (list, tuple)) or len(r) != 2 for r in renames):
        raise ValueError("Each folder rename needs the old and the new name.")
    pairs = tuple((r[0], r[1]) for r in renames)
    for old, new in pairs:
        tidy.check_folder_names(old, new)
    moves = tuple(file_moves(files.get("moves") or []))
    return SaveChoice(files["choice"], pairs, moves)


def rows_from(lines: list) -> list[pf.Row]:
    """The page's playlist rows ({folder, link, enabled}, top = highest priority) as playlists.txt rows."""
    if not isinstance(lines, list):
        raise ValueError("The playlists come as a list of rows.")
    rows = []
    for line in lines:
        if not isinstance(line, dict) or not isinstance(line.get("folder"), str) or not line.get("link"):
            raise ValueError("Each playlist row needs a folder name and a link.")
        if sources.recognise(line["link"].strip()) is None:
            raise ValueError(f"This is not a Spotify or Qobuz playlist link: {line['link']}")
        rows.append(pf.Row(unicodedata.normalize("NFC", line["folder"].strip()), line["link"].strip(),
                           bool(line.get("enabled", True))))
    return rows


CANDIDATE_FIELDS = ("source", "id", "title", "artist", "duration_s", "url", "isrc", "album", "label", "image_url")


def candidate_row(c: Candidate, track: SourceTrack, **scored) -> dict:
    """One row of the "Wrong song?" dialog. The page sends the row back as it is (use_candidate, preview)."""
    return {**{f: getattr(c, f) for f in CANDIDATE_FIELDS}, "key": c.key, "source_name": SOURCE_NAMES[c.source],
            "length_diff_s": round(c.duration_s - track.duration_ms / 1000, 1) if c.duration_s else None,
            "can_preview": c.source in candidates.FALLBACK, **scored}


def to_candidate(d: dict) -> Candidate:
    if not isinstance(d, dict) or d.get("source") not in candidates.SOURCE_RANK or not d.get("id"):
        raise ValueError("That is not a version from the list.")
    if d["source"] != "qobuz" and not re.fullmatch(r"https?://[^\s]+", d.get("url") or ""):
        raise ValueError("That version has no link to download it from.")
    duration = d.get("duration_s")
    return Candidate(d["source"], str(d["id"]), d.get("title") or "", d.get("artist") or "",
                     float(duration) if duration is not None else None, d.get("url"), d.get("isrc"), d.get("album"),
                     d.get("label"), d.get("image_url"))

