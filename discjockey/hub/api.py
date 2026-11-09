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
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import tomllib
import traceback
import unicodedata
import webbrowser
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from pathlib import Path, PurePosixPath
import time
from typing import Callable
from urllib.parse import quote

from .. import __version__, align, browsers, candidates, config, db, library, ops, planner, playlists_file as pf, qobuz
from .. import quality
from .. import app_update as update_check, setup_cmd, tool_updates, tools
from .. import folders as folders_mod, importer, scanner, sources, tidy
from ..sources import soundcloud, spotify, youtube_music
from ..sources.soundcloud import YOU as SOUNDCLOUD_YOU  # the module imports yt-dlp only inside functions
from .. import auto_upgrade, batches, rekordbox, report as rep, run, upgrades
from ..rekordbox import process as rb_process
from ..accounts import ACCOUNTS, BROWSERS, SERVICE_NAMES, SERVICES, check_message
from ..acquire import make_ready
from ..candidates import current_key
from ..fallback import FallbackSource
from ..library import NoLibrary, Paths, Resolved, StateError, SupportPaths
from ..events import BatchProgress, Cancelled, CancelToken, Result
from ..models import (SERVICE_NAMES as PLAYLIST_SERVICES, SOURCE_NAMES, BatchResult, BatchRow, Candidate, PlaylistLine,
                      PlaylistRecord, SaveChoice, SourceTrack, WatchedFolder, token)
from ..names import fold
from ..ops import OpProblem, snapshot
from .. import pending_signs
from ..pacing import Budget
from ..qobuz import QobuzError, QobuzLoginRejected, QobuzNotSetUp, QobuzSource, config_file, login_problem
from ..settings import MAX_DAILY_LIMIT, MAX_EXTRA, Settings, SettingsError, load_settings, save_settings
from ..setup_cmd import TOOL_HINTS
from ..sources.spotify import REDIRECT_URI
from . import media as media_mod, spectrum as spec, views
from .jobs import (NOT_CONNECTED, UNEXPECTED, AppUpdate, Busy, DrivesChanged, FileDropped, Jobs, PreviewStore, SignInPhase,
                   import_work, preview_after_run, problem_of, refresh_work, replanned_work, service_of, sync_work)

RUN_ID = re.compile(r"\d{4}-\d{2}-\d{2}_\d{6}")
WHICH = ("current", "upgrade")
UPGRADE_MODES = ("swap", "add_new", "discard")
NO_TRACKS = "No tracks were chosen."
NO_UPGRADES = "None of these can be upgraded right now."
NO_AIFF_BATCH = "Discjockey has no record of this batch."
NOT_STOPPED = "This batch is not stopped, so there is nothing to resume."
UNDO_NONE = batches.NOTHING_UNDONE
NOTHING_TO_CHECK = "There is nothing to check for these tracks any more."
SYNC_RUNNING = "Not while a sync runs: Discjockey keeps its requests to Qobuz and YouTube paced."
AUTO_READ_DONE = "Your playlists were read by themselves once this session already. Use ↻ Read playlists to read them again."
NO_DROP = "Drag the bought file onto the window while this track is selected in the to-do list."
NOT_SELECTED = "Select the track in the to-do list first, then drop the file on the window."
CLIENT_ID = re.compile(r"[0-9a-fA-F]{32}")
NO_FOLDER = "That folder isn't one of the watched folders."
FAVOURITE_KEYS = ("playlist:", "folder:")  # what a Favourite's key starts with (plan library stage 5, D3)
ONE_READ_SERVICES = ("soundcloud", "youtube_music")  # a pasted link: their fetch also gives the page facts (want_info)
BAD_FAVOURITES = "That list of favourites isn't one Discjockey can keep."
BAD_CRATE = "That isn't a folder Discjockey can show or hide."
BRIEF_WRITE_FAILED = "Discjockey couldn't save that just now. Try again in a moment."
NO_RECORDS = "Discjockey has no records of your library yet, so it can't save that. Quit and open Discjockey again."
# how long a Favourites or crate-switch save waits for a running job's write (D15): longer than the engine's usual
# short transactions, short enough that a click never seems to hang (the binding 5 s would)
BRIEF_WRITE_WAIT_MS = 1500
NOT_ANSWERABLE = "Each answer needs the song or group it is about."
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
    "rekordbox_checked", "upgrade", "upgrade_all", "undo_upgrade", "batch_resume", "batch_undo", "rescan_library", "show_in_finder", "reveal", "open_report",
    "tidy_preview", "move_batches", "undo_preview", "tidy_up", "undo_moves",
    "watched_folders", "set_favourites", "set_crate_shown", "set_crates_shown", "check_import_folder", "removal_preview", "add_watched_folder", "remove_watched_folder",
    "start_import", "answer_same_song", "keep_duplicates", "supersede_duplicate", "add_liked_music",
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
    timeline_offset: Callable = rekordbox.timeline_offset  # where rekordbox's timeline sits for a file (New track)
    # whether rekordbox runs and where its library is (late-bound: tests and the fake never touch a real one)
    rekordbox_running: Callable[[], bool] = lambda: rb_process.running()
    rekordbox_place: Callable[[], object] = lambda: rekordbox.locate()
    decode: Callable = quality.decode_mono
    now: Callable[[], datetime] = datetime.now
    mounted: Callable[[Path], bool] = os.path.ismount  # whether a /Volumes drive is connected (the scanner's rule)
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
_DRIVES_TICK = 2.0  # s: the drives watch looks at the watched folders this often (a drive plugged in or ejected)
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


LIKED_NEEDS_LOGIN = "Sign in to YouTube first: Discjockey reads your Liked music through that login."
LIKED_LISTED = "Liked music is in your playlists already."


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
            setting = getattr(e, "setting", None)  # setting_off: the choice in Settings that is off
            return {"ok": False, "kind": kind, "message": message, **({"service": service} if service else {}),
                    **({"setting": setting} if setting else {})}

    call.__signature__ = inspect.signature(fn)  # pywebview reads the parameter names from it
    return call


def _lock_error(e: sqlite3.Error) -> bool:
    """Whether SQLite refused because another connection holds the database (SQLITE_BUSY / SQLITE_LOCKED)."""
    return getattr(e, "sqlite_errorcode", None) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) or any(
        word in str(e).lower() for word in ("locked", "busy"))


def profile_name(browser: str, profile: str | None, home: Path | None) -> str | None:
    """The display name of a saved browser profile ("DJ" for Chrome's "Profile 2"); None for the default one, or
    without `home` (no browser files are read then)."""
    if profile is None or home is None:
        return None
    return {p["id"]: p["name"] for p in browsers.profiles(browser, home)}.get(profile, profile)


def _paths_list(value: object) -> bool:
    """Whether `value` is a list of path strings (the group's files as the card showed them)."""
    return isinstance(value, list) and all(isinstance(p, str) for p in value)


def _import_folders(paths: Paths | None) -> int:
    """How many import folders the library watches (0 without a library or library.db: nothing to read)."""
    if paths is None or not paths.db_file.exists():
        return 0
    try:
        with db.connect(paths.db_file) as conn:
            return sum(1 for f in db.watched_folders(conn) if f.kind == "import")
    except (sqlite3.Error, StateError, OSError):
        return 0


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
        settings = Settings(auto_upgrade=False)  # a settings file the sync can't read starts no sync, so no upgrades
    import_folders = _import_folders(paths)
    liked_listed = False
    if paths is not None:
        try:
            liked_listed = pf.lists_liked_music(pf.load(paths.playlists_file).rows)
        except OSError:
            pass
    steps = [("music", music["state"] == "ok"), ("tools", all(tools.values())),
             ("spotify", (spotify_app and spotify_login) or settings.spotify_skipped), ("downloads", qobuz_ok or settings.qobuz_skipped),
             ("playlists", playlists_ok)]
    return {"music": music, "tools": tools, "spotify_app": spotify_app, "spotify_login": spotify_login,
            "qobuz": qobuz_ok,
            "playlists": playlists_ok, "complete": all(ok for _, ok in steps),
            "next_step": next((name for name, ok in steps if not ok), None),
            "version": __version__, "qobuz_skipped": settings.qobuz_skipped,
            "spotify_skipped": settings.spotify_skipped,
            # YouTube Music's Liked music (sources-round D5, I3): the choice, whether it can be turned on (a YouTube
            # account is set up) and whether a Liked music line is in playlists.txt (on or off)
            "youtube_music": {"liked_music": settings.reads_liked_music, "can_turn_on": "youtube" in settings.accounts,
                              "listed": liked_listed},
            # Auto-upgrade (issue 33 stage C): "Upgrade automatically when I sync", on by default (Setup, Settings)
            "auto_upgrade": settings.auto_upgrade,
            # "Your existing music" (plan library stage 4 I11): done once a folder is watched or the step was skipped;
            # not among `steps`, so it never blocks Continue
            "existing": import_folders > 0 or settings.import_skipped, "import_folders": import_folders,
            "import_skipped": settings.import_skipped,
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
        self._jobs.on_locked = self._record_waiting_signs  # a write job starts: signs that waited for the lock go in
        self._settings_mutex = threading.Lock()  # settings.json: read, change, save — one at a time
        self._store = PreviewStore()
        self._infos: dict = {}  # playlist ref -> models.PlaylistInfo
        self._extra_tracks: dict = {}  # playlist ref -> tracks of playlists read outside a refresh
        self._shown: dict[str, dict] = {}  # track id -> how the page last showed it (ops.snapshot)
        self._rb_cache: tuple[tuple, rekordbox.Status] | None = None  # (_rekordbox_status's key, its answer)
        self._selected: str | None = None
        self._dropped: dict | None = None
        self._drives_seen: dict[str, str] | None = None  # the away set the drives watch saw last (None: not yet)
        self._lock = threading.Lock()
        self._auto_lock = threading.Lock()
        self._quit: Callable[[], None] | None = None  # set by app.main: closes the window
        # the Qobuz auto-stop for "Use this" and links: one failure streak for the whole hub session (reset when a
        # sync starts), not one per job, so that failed downloads in a row do pause Qobuz
        self._qobuz_streak = {"failures_in_a_row": 0, "download_failed_in_row": False, "stopped": False}
        self._account_streaks: dict[str, dict] = {}  # service -> the same, for "Use this" through an account
        # the user stopped an import this session: it starts by itself no more until Continue import (D14)
        self._import_stopped = False
        self._import_auto_done = False  # the window's automatic start has run (or had nothing to do) this session

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
                self._media.bind(paths, self._file_path)
            self._store.records_reopened()  # its records may count their generation from 0 again
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
            self._watch_drives()

    def _first_read(self) -> None:
        self.refresh(auto=True)

    def _start(self, resolved: Resolved) -> None:
        """At launch (app.main): bind the library when the music folder is there, else remember why not."""
        if resolved.paths is not None:
            self._bind(resolved.paths)
            try:  # signs the last session left waiting for the lock (a read made while a sync ran)
                self._record_signs([])
            except Exception:  # noqa: BLE001 - best-effort: the first job or read tries again
                log.warning("recording the waiting warning signs failed", exc_info=True)
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

    def _auto_upgrade_on(self) -> bool:
        """Settings' Auto-upgrade switch, read strictly like a sync reads it (`_settings` would take defaults for a
        file it can't read): a file the sync refuses is no switch on."""
        try:
            return load_settings(self._support.settings_file).auto_upgrade
        except SettingsError:
            return False

    def _auto_upgrade_ready(self, state: dict) -> dict | None:
        """`sync_preview().auto_upgrade`: `{on: true, ready: n}` with n the tracks the sync's last phase would upgrade
        now (`auto_upgrade.plan`, quick: the cached rekordbox state, no read open of its library; a refusal that can't
        be told to still hold without one counts as holding), counting those that would wait for rekordbox. None when
        the switch is off (or the file unreadable) or there is no preview (no plan, so no questions to hold songs)."""
        prep = self._store.prep
        if prep is None:
            return None
        try:
            settings = load_settings(self._support.settings_file)
        except SettingsError:
            return None
        planned = auto_upgrade.plan(self._paths, state, {q.song_key for q in prep.plan.questions}, settings,
                                    running=self._svc.rekordbox_running, place=self._svc.rekordbox_place(),
                                    status=self._rekordbox_status(), quick=True)
        return None if planned is None else {"on": True, "ready": len(planned.run) + len(planned.waiting)}

    def _batch_starters(self, state: dict) -> dict[int, str]:
        """Batch id -> who started it, for the AIFF batches the open rekordbox checks belong to (To-do names the
        checks of a sync's Auto-upgrade batch differently)."""
        ids = {c["batch"] for e in state["tracks"].values() if (c := e.get("rekordbox_check")) and c.get("batch")}
        if not ids:
            return {}
        with self._move_log() as conn:
            if conn is None:
                return {}
            rows = (db.aiff_batch(conn, i) for i in sorted(ids))
            return {r.id: r.started_by for r in rows if r is not None}

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
                logins.append((service, sources.SOURCES[service].login_state(self._support).connected))
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

    def _record_signs(self, signs: list[tuple[str, str, str]]) -> None:
        """Records the warning signs a Liked music read met outside a sync (a pasted link, the change preview), as a
        download's would be. They are kept in the library's pending_signs.json first (so they survive the app closing
        and already count for the pause), then written into library.db under the library lock when this can have it.
        When a sync, a scan or a terminal run holds the lock they wait in the file, and the next job, the next start,
        paste or preview writes them. Called with no signs, it only writes what waits."""
        pending_signs.add(self._paths, signs, datetime.now())
        if not self._paths.pending_signs.exists():
            return
        with self._jobs.scan_lock() as held:
            if held:
                run.record_pending(self._paths, self._state(), run.lock_held, False)

    def _shown_state(self) -> dict:
        """The state for pages that show the warning signs: `_state()` plus the signs waiting for the lock. Not for
        anything that saves."""
        return run.with_pending_signs(self._paths, self._state())

    def _record_waiting_signs(self) -> None:
        self._record_signs([])

    def _paused_accounts(self) -> frozenset[str]:
        """The account services paused today, counting the signs still waiting for the library lock."""
        return run.paused_now(self._paths, self._state(), self._today())

    def _images(self) -> dict[str, str]:
        prep = self._store.prep
        return {t.key: t.image_url for fp in (prep.fetched if prep else []) for t in fp.tracks if t.image_url}

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
        """The player address of a track's or file's audio: by its path in the music folder, else (a file of an import
        folder, outside it) by its file id, which `_file_path` vets."""
        if self._media is None:
            return None
        url = self._media.url(e["path"]) if e.get("path") else None
        if url is None and e.get("file_id") is not None:
            url = self._media.url(media_mod.file_address(e["file_id"]))
        return url

    def _file_path(self, file_id: int) -> Path | None:
        """The real path of the file row `file_id` for the media server: only a known row that is online in a watched
        folder, and only if the path, links resolved, stays inside that folder (a link leading out is refused)."""
        if not self._paths.db_file.exists():
            return None
        with db.connect(self._paths.db_file) as conn:
            where = db.online_file(conn, file_id)
        return media_mod.file_inside(*where) if where is not None else None

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

    def _imported(self, e: dict, which: str) -> tuple[int, Path] | None:
        """(file id, vetted real path) when the track's current file is one of an import folder (outside the music
        folder, so its entry path is absolute); None for a file in the music folder. Never trusts a path from the page:
        the file row is looked up and vetted by `_file_path` (online, links resolved inside its watched folder)."""
        path = e.get("path")
        if which != "current" or not path or not PurePosixPath(path).is_absolute():
            return None
        real = self._file_path(e["file_id"]) if e.get("file_id") is not None else None
        if real is None:
            raise OpProblem("That file is not there.", "refused")
        return e["file_id"], real

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

    def _todo(self, state: dict, filt: str, show_hidden: bool, count_only: bool = False) -> dict:
        """views.todo with the import's questions (the last plan's) and duplicates (the plan's same-song groups and the
        records' same-audio ones, each with its files). `count_only` (the sidebar's number): the records' groups are
        counted without loading their files (they are online and not held by how they are found), so only the plan's
        few same-song groups read theirs; the groups of the answer are then not listed. While an import folder is
        away right now every group's files are read, so a group with a file in it is left out of the count too."""
        prep = self._store.prep
        questions = list(prep.plan.questions) if prep else []
        groups = list(prep.plan.duplicates) if prep else []
        files: dict[str, list] = {}
        counted: set[str] = set()
        away = self._away_roots()
        with self._move_log() as conn:
            if conn is not None:
                found = db.duplicate_groups(conn)
                # with a folder away now, a group may have a file in it: its files are read to tell (views.todo)
                counted = {g.id for g in found} if count_only and not away else set()
                groups += found
                files = {g.id: db.group_files(conn, g.id) for g in groups if g.id not in counted}
        # the sidebar's number needs neither rekordbox's state nor a look at each file
        rb = None if count_only else self._rekordbox_status()
        present = None if count_only else {k: batches.present(self._paths, e) for k, e in state["tracks"].items()
                                           if e.get("upgrade")}
        return views.todo(state, filt, show_hidden, self._others(state), self._today(), self._cover(self._images()),
                          questions, groups, files, self._audio, counted, away, rb, present,
                          None if count_only else self._stopped_batch(), self._auto_upgrade_on(),
                          {} if count_only else self._batch_starters(state))

    def _rekordbox_status(self) -> rekordbox.Status:
        """rekordbox's state for the screens, cached on master.db's modified time and size plus whether rekordbox runs
        (plan rekordbox B §4): one read open per change, never while any write job of this hub runs (it answers the
        last value then, or "readable" when it has none): a sync, import or tidy-up runs `recover_pending` first, which
        can finish a rekordbox write, so no job is known to leave rekordbox alone."""
        running = bool(self._svc.rekordbox_running())
        with self._lock:
            last = self._rb_cache
        job = self._jobs.running()
        if job is not None:
            return last[1] if last else rekordbox.Status("ready", running, None, None, None, None, None)
        place = self._svc.rekordbox_place()
        stat = None
        try:
            if place is not None:
                st = place.db.stat()
                stat = (st.st_mtime_ns, st.st_size)
        except OSError:
            stat = None
        key = (running, str(place.db) if place is not None else None, stat)
        if last is not None and last[0] == key:
            return last[1]
        try:
            answer = rekordbox.status(place, lambda: running)
        except Exception:  # noqa: BLE001 - status() never raises for a library it can't read; this is for the rest
            answer = rekordbox.Status("unreadable", running, None, None, None, None, None)
        with self._lock:
            self._rb_cache = (key, answer)
        return answer

    def _stopped_batch(self) -> tuple[int, int] | None:
        """(id, items left) of the newest stopped Same track batch that still has items to do, else None: To-do's
        "Resume · k left"."""
        with self._move_log() as conn:
            if conn is None:
                return None
            rows, _ = db.aiff_batches(conn, 20)
        for row in rows:
            if row.state == "stopped" and row.counts["planned"]:
                return row.id, row.counts["planned"]
        return None

    # --- read, any time ---

    @bridge
    def dashboard(self) -> dict:
        return views.dashboard(self._shown_state(), self._settings(), self._store, self._reports(), self._folders(),
                               setup_status(self._support, self._paths, self._music_status(), self._svc.which),
                               self._today(), self._svc.now(),
                               self._reading(), self._logins())

    @bridge
    def sidebar(self) -> dict:
        return self._sidebar_view()

    @bridge
    def rekordbox_status(self) -> dict:
        """rekordbox on this Mac, now (issue 33 stage C): `{state: "ready" | "none" | "unreadable", running}`. The state
        is the cached answer of `_rekordbox_status` (one read open per change of master.db; while a write job of this
        hub runs it answers its last value), `running` is asked every time: the Sync page reads it when it opens and
        when the window gets focus again, to say that rekordbox must be quit before a start. Works without a music
        folder."""
        status = self._rekordbox_status()
        return {"state": status.state, "running": status.running}

    def _sidebar_view(self, also: Sequence[str] = ()) -> dict:
        """The sidebar's numbers; `also`: Favourites keys to resolve besides the stored ones (set_favourites asks
        which of the keys it is given exist right now)."""
        state = self._shown_state()
        count = self._todo(state, "all", False, count_only=True)["chips"]["all"]
        # the dot on "Download limits": a warning sign the user hasn't marked as seen, or a service paused today
        warnings = any(c["new_warnings"] or c["paused"] for c in views.limit_cards(state, self._settings(), self._today()))
        with self._move_log() as conn:  # no library.db yet: no records, no Favourites, no watched folders
            records, favs, overrides, folders = ((db.playlist_records(conn), db.favourites(conn),
                                                  db.crate_overrides(conn), db.watched_folders(conn))
                                                 if conn is not None else ({}, [], {}, []))
        return views.sidebar(state, pf.load(self._paths.playlists_file).rows, count, warnings, records=records,
                             favourites=[*favs, *also], overrides=overrides, watched=folders,
                             away=self._away_folders(folders))

    @bridge
    def sync_preview(self) -> dict:
        state = self._state()
        with self._move_log() as conn:
            folders, overrides = (db.watched_folders(conn), db.crate_overrides(conn)) if conn is not None else ([], {})
        lines = pf.load(self._paths.playlists_file).rows
        where = views.sites(state, lines, folders).place
        return views.sync_preview(self._store, state, self._settings(), self._today(), self._svc.now(),
                                  self._reading(), self._cover(self._images()), self._logins(), where,
                                  views.song_places(state, lines, folders, overrides),
                                  self._auto_upgrade_ready(state))

    @bridge
    def refresh(self, auto: bool = False) -> dict:
        """auto: the hub's own read (when it opens, or the Sync page when it opens first). Only one per session
        starts, whatever its outcome; later ones are refused, so a stopped or failed read is never redone by itself."""
        with self._auto_lock:
            if auto and self._store.auto_read:
                raise OpProblem(AUTO_READ_DONE, "refused")
            read = refresh_work(self._paths, self._store, self._svc.now, infos=self._infos,
                                lock=self._opening_scan if auto else self._jobs.scan_lock)

            def work(ctx) -> dict:
                try:
                    return read(ctx)
                finally:  # the read ended before it scanned (no playlists.txt, no login): the files that wait still start
                    if auto and not ctx.token.cancelled:
                        self._auto_import()

            job = self._jobs.start_refresh(work)
            if auto:
                self._store.auto_read = True
        return {"job_id": job.id}

    @contextlib.contextmanager
    def _opening_scan(self):
        """The window's own first read scans Library/ and the import folders under Jobs.scan_lock; the moment that
        scan lets go of the library, the files it found start importing (D14), without waiting for the playlists to be
        read (a slow or missing login must not hold the import back, and no page is involved)."""
        with self._jobs.scan_lock() as held:
            yield held
        if held:
            self._auto_import()

    def _auto_import(self) -> None:
        """D14: the window opened and files wait for an import: it starts by itself, once per session, unless the
        user stopped one this session or something else is writing (the import then waits for Continue import or the
        next window). Only the window's own first read gets here, never a Sync page's ↻ Read playlists."""
        if self._import_stopped or self._import_auto_done:
            return
        try:
            if importer.files_waiting(self._paths) > 0:
                self._start_import()
            self._import_auto_done = True
        except (Busy, NoLibrary, StateError):
            return
        except Exception:  # noqa: BLE001 - a failed start is never worth ending the read that called it
            log.warning("starting the import by itself failed", exc_info=True)

    def _start_import(self, folder: Path | str | None = None):
        """The import as a write job (Busy when another job or a terminal run holds the library)."""
        stopped, self._import_stopped = self._import_stopped, False  # before it starts: it may be stopped at once
        try:
            return self._jobs.start("import", import_work(self._paths, self._store, self._svc.now, folder=folder,
                                                          on_stopped=self._note_stopped))
        except BaseException:
            self._import_stopped = stopped
            raise

    def _note_stopped(self) -> None:
        self._import_stopped = True

    @bridge
    def stop_refresh(self) -> dict:
        return {"stopped": self._jobs.stop_refresh()}

    @bridge
    def job_status(self) -> dict:
        return {**self._jobs.status(), "read_status": views.read_status(self._store, self._svc.now(), self._reading(),
                                                                           self._logins())}

    @bridge
    def library(self, view: str = "all", key: str | None = None, query: str = "", filter: str = "all",
                sort: str | None = None) -> dict:
        """One view of the library (views.library): view "all" | "unlisted" | "playlist" | "folder"; key the playlist's
        folder name or the folder's path for the last two; sort None = the view's own order. An unknown playlist or
        folder is not an error: the answer says `empty: "gone"`."""
        if view not in views.LIBRARY_VIEWS:
            raise ValueError(f"view must be one of {', '.join(views.LIBRARY_VIEWS)}")
        if view in ("playlist", "folder") and not key:
            raise ValueError(f"a {view} view needs its key")
        if filter not in views.LIBRARY_FILTERS:
            raise ValueError(f"filter must be one of {', '.join(views.LIBRARY_FILTERS)}")
        state = self._state()
        records, folders = self._records_and_folders()
        prep = self._store.prep
        out = views.library(state, view, key, query, filter, sort, self._cover(self._images()),
                            self._away_by_root(folders), lines=pf.load(self._paths.playlists_file).rows,
                            records=records, watched=folders, fetched=prep.fetched if prep else [],
                            planned={k: t["aliases"] for k, t in (prep.state["tracks"] if prep else {}).items()
                                     if t.get("aliases")})
        # a row without a file (a playlist song that waits) is no track the page can act on
        self._remember(state, [r["track_id"] for r in (*out["rows"], *(out["also"] or ())) if r["file_state"] != "no_file"])
        return out

    @bridge
    def track(self, track_id: str) -> dict:
        state = self._state()
        e = self._entry(state, track_id)
        prep = self._store.prep
        if prep is not None:  # the aliases the last read's linking added (a Qobuz track linked to this song) count too
            planned = (prep.state["tracks"].get(track_id) or {}).get("aliases") or []
            e = {**e, "aliases": list(dict.fromkeys([*(e.get("aliases") or []), *planned]))}
        # whether the file is at its path: asked for this one track only, since the last scan may be old
        exists = not e.get("path") or (self._paths.root / e["path"]).exists()
        with self._move_log() as conn:
            folders = db.watched_folders(conn) if conn is not None else []
        lines = pf.load(self._paths.playlists_file).rows
        where = views.sites(state, lines, folders).place(e["path"]) if e.get("path") else None
        detail = views.track_detail(track_id, e, prep.fetched if prep else [], self._today(),
                                    self._cover(self._images()), self._audio, self._away_by_root(folders), exists, where,
                                    self._rekordbox_status(), self._auto_upgrade_on())
        self._remember(state, [track_id])
        return {"track": detail}

    @bridge
    def todo(self, filter: str = "all", show_hidden: bool = False) -> dict:
        state = self._state()
        out = self._todo(state, filter, bool(show_hidden))
        # a question or a duplicate group is not a track the page can act on (hide, upgrade, …): nothing to remember
        self._remember(state, [i["track_id"] for g in out["groups"] for i in g["items"] if "pair" not in i])
        return out

    def _away_folders(self, rows: Sequence[WatchedFolder]) -> dict[int, str]:
        """Folder id -> why it is not there right now ("unmounted" or "missing", scanner.away_reason) for the import
        folders among `rows` that are away. Checked live: the files' stored `online` only changes with a scan. The one
        definition of "away now"."""
        return {f.id: why for f in rows if f.kind == "import"
                and (why := scanner.away_reason(f.path, self._svc.mounted)) is not None}

    def _away_by_root(self, rows: Sequence[WatchedFolder]) -> dict[str, str]:
        """Root (as the files' snapshot paths start) -> why, for the import folders among `rows` that are not there
        now, for the views that decide a file's state or whether it is there."""
        away = self._away_folders(rows)
        return {str(f.path): away[f.id] for f in rows if f.id in away}

    def _records_and_folders(self) -> tuple[dict[str, PlaylistRecord], list[WatchedFolder]]:
        """The playlists' read records and the watched folders, from library.db ({} and [] before there is one)."""
        with self._move_log() as conn:
            return (db.playlist_records(conn), db.watched_folders(conn)) if conn is not None else ({}, [])

    def _away_roots(self) -> dict[str, str]:
        """`_away_by_root` for the watched folders as they are now; looked up once per request."""
        with self._move_log() as conn:
            rows = db.watched_folders(conn) if conn is not None else []
        return self._away_by_root(rows)

    @bridge
    def watched_folders(self) -> dict:
        """The watched folders (the Library first, then the import folders) with how far their import is, the files
        it couldn't read, how many wait, and whether the user stopped the import this session (plan library stage 4
        I11)."""
        paths = self._paths
        state = self._state()
        job = self._jobs.running()
        phase = None
        if job is not None and job.kind == "import":
            phase = (job.last.get("ImportProgress") or {}).get("phase", "scan")
        with self._move_log() as conn:
            if conn is None:  # no library.db yet: only the Library, nothing imported; its files as "All tracks" counts
                rows, counts, unreadable, waiting, overrides = [WatchedFolder(0, paths.library, "library")], {}, [], 0, {}
            else:
                overrides = db.crate_overrides(conn)
                rows, counts = db.watched_folders(conn), db.import_counts(conn)
                waiting = db.import_left(conn)
                unreadable = sorted(db.import_unreadable(conn) + db.import_unreadable(conn, "library"))
                for f in rows:
                    if f.kind == "library":  # Library/ is listed like an import folder: its own waiting and unreadable
                        counts[f.id] = db.library_counts(conn)
        files = [e["path"] for e in views.tracks_with_file(state)]
        crates = views.crates(files, [str(f.path) for f in rows if f.kind == "import"], overrides)
        return views.watched_folders(rows, counts, self._away_folders(rows), views.listed_counts(files, rows), unreadable,
                                     waiting, self._import_stopped, phase, crates)

    def _brief_write(self, write: Callable[[sqlite3.Connection], None]) -> None:
        """A write to the records the hub keeps beside the library (Favourites, crate switches; plan library stage 5
        D15): not a job and without the engine lock, since these tables are no library state and pinning a playlist
        must work during a sync. SQLite's busy timeout orders it against a running job's transactions; a write that
        still can't be made answers `busy` (nothing was changed) and the page puts its list back. A library.db that
        is damaged or of another version answers as every other call does (config_invalid)."""
        if not self._paths.db_file.exists():
            raise OpProblem(NO_RECORDS, "refused")
        try:
            with db.connect(self._paths.db_file, wait_ms=BRIEF_WRITE_WAIT_MS) as conn:
                db.check(conn)
                write(conn)
        except sqlite3.Error as e:
            if not _lock_error(e):  # a damaged file, a read-only drive: retrying can't help
                raise db.unreadable(e) from None
            raise OpProblem(BRIEF_WRITE_FAILED, "busy") from None

    @bridge
    def set_favourites(self, keys: list[str]) -> dict:
        """Replaces the Favourites with `keys` (`playlist:<ref>` / `folder:<path>`, D3) in their order: a brief save,
        not a job. A stored key that isn't in `keys` and whose playlist or folder isn't there right now stays, in its
        place (the UI never saw it, so it can't have meant to remove it). Answers the stored list."""
        if not isinstance(keys, list) or not all(isinstance(k, str) and k.startswith(FAVOURITE_KEYS) for k in keys):
            raise ValueError(BAD_FAVOURITES)
        if not self._paths.db_file.exists():
            raise OpProblem(NO_RECORDS, "refused")
        resolving, _ = self._sidebar_targets()
        stored: list[str] = []

        def save(conn):
            db.set_favourites(conn, keys, resolving)
            stored.extend(db.favourites(conn))

        self._brief_write(save)
        return {"favourites": stored}

    def _sidebar_targets(self) -> tuple[set[str], set[str]]:
        """(the Favourites keys that exist right now, the crates' paths): `views.sidebar_targets` for the library as it
        is, without the sidebar's counts. A library with no records yet has none."""
        if not self._paths.db_file.exists():
            return set(), set()
        with self._move_log() as conn:
            watched = db.watched_folders(conn)
        return views.sidebar_targets(self._state(), pf.load(self._paths.playlists_file).rows, watched)

    @bridge
    def set_crate_shown(self, path: str, shown: bool | None) -> dict:
        """Shows or hides the crate at snapshot path `path` in the sidebar (Settings' switch; None goes back to the
        default, D8): a brief save, not a job. `path` must be a crate of a watched folder right now."""
        if not isinstance(path, str) or not path or not (shown is None or isinstance(shown, bool)):
            raise ValueError(BAD_CRATE)
        if not self._paths.db_file.exists():
            raise OpProblem(NO_RECORDS, "refused")
        if path not in self._sidebar_targets()[1]:
            raise ValueError(BAD_CRATE)
        self._brief_write(lambda conn: db.set_crate_shown(conn, path, shown))
        return {"path": path, "shown": shown}

    @bridge
    def set_crates_shown(self, paths: list[str], shown: bool | None) -> dict:
        """`set_crate_shown` for several crates at once (Settings' All / None): one brief save, one transaction. Every
        path must be a crate of a watched folder right now, else nothing is saved. A path given twice counts once."""
        if (not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p for p in paths)
                or not (shown is None or isinstance(shown, bool))):
            raise ValueError(BAD_CRATE)
        if not self._paths.db_file.exists():
            raise OpProblem(NO_RECORDS, "refused")
        wanted = list(dict.fromkeys(paths))
        known = self._sidebar_targets()[1]
        if not all(p in known for p in wanted):
            raise ValueError(BAD_CRATE)

        self._brief_write(lambda conn: db.set_crates_shown(conn, wanted, shown))
        return {"paths": wanted, "shown": shown}

    @bridge
    def check_import_folder(self, path: str) -> dict:
        """Whether the folder can be watched, changing nothing (W5): the words of a refusal, and the watched folders
        inside it that it would take over (`merges`, with `merge_hints` in W5's words)."""
        c = folders_mod.check_import_folder(path or "", paths=self._paths, support=self._support.support,
                                            program=tools.program_dir(), home=self._svc.home)
        return {"path": str(c.path), "exists": c.exists, "usable": c.usable, "problem": c.problem, "kind": c.kind,
                "message": folders_mod.problem_words(c), "merges": [str(m) for m in c.merges],
                "merge_hints": folders_mod.merge_hints(c)}

    def _import_folder(self, folder_id: int) -> WatchedFolder:
        """The import folder `folder_id` names; ValueError for anything else (the Library, an unknown number)."""
        if isinstance(folder_id, bool) or not isinstance(folder_id, int):
            raise ValueError(NO_FOLDER)
        with self._move_log() as conn:
            found = next((f for f in db.watched_folders(conn) if f.id == folder_id), None) if conn is not None else None
        if found is None or found.kind != "import":
            raise ValueError(NO_FOLDER)
        return found

    @bridge
    def removal_preview(self, folder_id: int) -> dict:
        """What removing the folder takes away (W4): its files, and the playlist songs that download again."""
        folder = self._import_folder(folder_id)
        counts = folders_mod.removal(self._paths, folder.id)
        return {"name": folder.path.name or str(folder.path), "files": counts.files, "redownload": counts.redownload}

    def _service(self, service: str, set_up: bool = False) -> str:
        if service not in SERVICES:
            raise ValueError(f"service must be one of {', '.join(SERVICES)}")
        if set_up and service not in views.services_of(self._settings()):
            raise OpProblem(f"Set up {SERVICE_NAMES[service]} first.", "refused")
        return service

    @bridge
    def limits(self, service: str = "qobuz") -> dict:
        return views.limits(self._service(service), self._shown_state(), self._settings(), self._store.prep, self._today())

    @bridge
    def limits_what_if(self, service: str, limit: int, extra_today: int = 0) -> dict:
        service, limit, extra_today = self._service(service, set_up=True), int(limit), int(extra_today)
        if not 1 <= limit <= MAX_DAILY_LIMIT or not 0 <= extra_today <= MAX_EXTRA:
            raise ValueError(f"The daily limit goes from 1 to {MAX_DAILY_LIMIT}, the extra for today from 0 to "
                             f"{MAX_EXTRA}.")
        return views.limits_what_if(service, limit, extra_today, self._shown_state(), self._settings(), self._store.prep,
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
        e = self._entry(self._state(), track_id)
        imported = self._imported(e, which)
        if imported is not None:
            data = spec.spectrum_of_file(self._paths, *imported, decode=self._svc.decode)
        else:
            data = spec.spectrum(self._paths, self._file_of(track_id, which), decode=self._svc.decode)
        return {"spectrum": {**data, "which": which, "cutoff_hz": e.get("cutoff_hz") if which == "current" else None}}

    @bridge
    def media_url(self, track_id: str, which: str = "current") -> dict:
        imported = self._imported(self._entry(self._state(), track_id), which)
        rel = media_mod.file_address(imported[0]) if imported is not None else self._file_of(track_id, which)
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
        state = self._shown_state() if self._bound is not None else library.empty_state()
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
        """Shows a place in Finder: a path inside the music folder (relative), or an absolute path inside a watched
        import folder (the folder itself, a crate): only places the library knows, never any path the page names."""
        self._svc.reveal(self._watched_place(rel_path) if str(rel_path).startswith("/") else self._inside_root(rel_path))
        return {}

    def _watched_place(self, path: str) -> Path:
        """The absolute `path` when it is a watched import folder or inside one (its symlinks followed: a link leading
        out of the folder is refused); ValueError for any other place, OpProblem when it is not there (a drive that is
        not connected)."""
        with self._move_log() as conn:
            roots = [f.path for f in db.watched_folders(conn) if f.kind == "import"] if conn is not None else []
        wanted = Path(path)
        if ".." in wanted.parts or not any(wanted == r or wanted.is_relative_to(r) for r in roots):
            raise ValueError("Discjockey only opens places inside your music folder or a folder it watches.")
        if not wanted.exists():
            raise OpProblem("That file or folder is not there.", "refused")
        real = wanted.resolve()
        if not any(real == r.resolve() or real.is_relative_to(r.resolve()) for r in roots):
            raise ValueError("Discjockey only opens places inside your music folder or a folder it watches.")
        return wanted

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

    def _watch_drives(self, interval: float = _DRIVES_TICK) -> threading.Thread:
        """Notices a watched folder coming or going while the window is open (a drive plugged in or ejected, a folder
        renamed or put back): the views read the away set live, but only when a page asks, so without this a Library
        open on an ejected drive would keep looking as if it were there. Read only: the away set every `interval`."""
        def loop() -> None:
            self._check_drives()  # the first look is the baseline: the page reads its views itself when it loads
            while not self._jobs.closed.wait(interval):
                self._check_drives()

        thread = threading.Thread(target=loop, name="hub-drives-watch", daemon=True)
        thread.start()
        return thread

    def _check_drives(self) -> None:
        """One look of the drives watch: DrivesChanged once when the away set (which import folders are away, and why)
        differs from the last look's, nothing when it is the same or on the first look. Never raises: a records
        file that can't be read now keeps the last answer, and the next look tries again."""
        try:
            now = self._away_roots()
        except Exception:  # an unreadable library.db says so on the page's own calls; the watch only waits
            log.debug("drives watch: the watched folders could not be read", exc_info=True)
            return
        seen, self._drives_seen = self._drives_seen, now
        if seen is not None and now != seen:
            self._emit(DrivesChanged(len(now)))

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
                if t.key in ids:
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
                                              logins={s: (a.browser, a.profile) for s, a in self._settings().download_accounts.items()})
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
                               self._state(), self._cover(self._images()),
                               liked_music_on=self._settings().reads_liked_music)

    @bridge
    def add_playlist(self, url: str) -> dict:
        """A pasted link: the playlist's name, owner and cover, whether Discjockey can read it, and its tracks."""
        self._no_sync_running()
        self._record_signs([])  # signs an earlier read left waiting for the library lock
        # a short link or one that names no user yet is expanded first (stage 6); clean_link then refuses what no source reads
        link = pf.clean_link(sources.expand((url or "").strip(), self._support, CancelToken()))
        service, pid = sources.recognise(link)  # clean_link raised for anything no source recognises
        source, ref = sources.SOURCES[service], token(service, pid)
        if not source.login_state(self._support).connected:
            raise sources.SourceError(NOT_CONNECTED.format(name=PLAYLIST_SERVICES[service]), "not_set_up", service)
        liked = ref == pf.LIKED_MUSIC_REF
        if liked:  # signs in, so it is a choice in Settings (D9); the reader keeps off a paused account (D6)
            if not self._settings().reads_liked_music:
                raise sources.SourceError(youtube_music.SETTING_OFF, "setting_off", service, youtube_music.SETTING)
        reader = source.open(self._support, CancelToken())
        signs: list[tuple[str, str, str]] = []
        reader.on_signal = lambda *sign: signs.append(sign)
        reader.paused = self._paused_accounts()  # the reader refuses Liked music while paused (D6)
        try:
            tracks, fetched = None, None
            if service in ONE_READ_SERVICES:  # their info always comes with a fetch: one read answers both
                reader.want_info = True
                try:
                    fetched = reader.fetch(PlaylistLine("x", pid, 0, service))
                except sources.SourceError as e:
                    if e.kind == "playlist_unreadable":
                        reader.info(pid)  # the page's own words (fetch's are worded for playlists.txt); else this one
                    raise
            info = fetched.info if fetched is not None and fetched.info is not None else reader.info(pid)
            self._infos[ref] = info
            if fetched is None and info.readable:
                fetched = reader.fetch(PlaylistLine(suggest_folder(info.name), pid, 0, service))
            if fetched is not None:
                self._extra_tracks[ref] = fetched.tracks
                tracks = len(fetched.tracks)
        finally:
            self._close(reader)
            self._record_signs(signs)  # a bot check met by the Liked music read: the account's warning sign
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
        paused = self._paused_accounts()
        signs: list[tuple[str, str, str]] = []
        try:
            for service in dict.fromkeys(r.service for r in unread):  # one reader per service; a failing one is skipped
                source = sources.SOURCES[service]
                if not source.login_state(self._support).connected:
                    continue
                try:
                    reader = source.open(self._support, CancelToken())
                except sources.SourceError:
                    continue
                reader.on_signal = lambda *sign: signs.append(sign)  # a bot check met by the Liked music read
                reader.paused = paused  # the reader refuses Liked music while its account is paused or the choice is off
                try:
                    for r in (r for r in unread if r.service == service):
                        try:
                            found = sources.recognise(r.link)
                            if found is None or (service == "soundcloud" and found[1] == SOUNDCLOUD_YOU):
                                continue  # not a playlist; or your likes, whose read opens the browser login (Keychain)
                            self._extra_tracks[r.ref] = reader.fetch(PlaylistLine("x", found[1], 0, service)).tracks
                        except sources.SourceError:
                            continue
                finally:
                    self._close(reader)
        finally:
            self._record_signs(signs)
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
        return {"track_id": track_id, "track_duration_s": round(track.duration_ms / 1000, 1),
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
        job = self._jobs.start("sync", sync_work(self._paths, self._store, ticked, self._svc.now,
                                                 self._rekordbox_services()))
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
    def add_watched_folder(self, path: str) -> dict:
        """Watches a folder of the user's own music and imports it in the same job (kind "import"; D14). Checked
        first (W5 words when refused); busy with W7 while an import runs."""
        c = folders_mod.check_import_folder(path or "", paths=self._paths, support=self._support.support,
                                            program=tools.program_dir(), home=self._svc.home)
        if not c.usable:
            raise OpProblem(folders_mod.problem_words(c), "refused")
        return {"job_id": self._start_import(c.path).id}

    @bridge
    def start_import(self) -> dict:
        """"Continue import": the import again, where it stopped (also after a Stop, which held the automatic start
        for the session)."""
        return {"job_id": self._start_import().id}

    @bridge
    def remove_watched_folder(self, folder_id: int) -> dict:
        """Stops watching an import folder (D12; its files stay where they are): a write job (kind "folders"), its
        result `{files, redownload}`."""
        folder = self._import_folder(folder_id)

        def change(ctx) -> dict:
            counts = folders_mod.remove(self._paths, folder.id, self._today(), emit=ctx.emit)
            return {"files": counts.files, "redownload": counts.redownload}

        return {"job_id": self._jobs.start("folders", replanned_work(self._store, change, self._svc.now)).id}

    @bridge
    def answer_same_song(self, song_key: str, own_key: str, same: bool) -> dict:
        """"Is this the same song?" answered (a write job, kind "answer"): the plan is made again, so the file is
        linked to the playlist song (yes) or the song downloads at the next sync (no)."""
        if not (isinstance(song_key, str) and isinstance(own_key, str) and isinstance(same, bool)):
            raise ValueError(NOT_ANSWERABLE)

        def change(ctx) -> dict:
            folders_mod.answer_same_song(self._paths, song_key, own_key, same, self._svc.now())
            return {}

        return {"job_id": self._jobs.start("answer", replanned_work(self._store, change, self._svc.now)).id}

    @bridge
    def keep_duplicates(self, group_id: str, paths: list[str]) -> dict:
        """Duplicates' "Keep both" / "Keep all" (a write job, kind "answer"): the group isn't asked again. `paths`:
        the group's files' paths as the card showed them; `changed` when the group's files are not those any more."""
        if not isinstance(group_id, str) or not _paths_list(paths):
            raise ValueError(NOT_ANSWERABLE)
        db.group_ids(group_id)  # ValueError for something that is no group

        def change(ctx) -> dict:
            folders_mod.keep_both(self._paths, group_id, paths, self._svc.now())
            return {}

        return {"job_id": self._jobs.start("answer", replanned_work(self._store, change, self._svc.now)).id}

    @bridge
    def supersede_duplicate(self, group_id: str, file_id: int, paths: list[str]) -> dict:
        """Duplicates' "Move to Superseded" for one file of the group (a write job, kind "supersede"; nothing is
        deleted). `paths`: the group's files' paths as the card showed them (`changed` when they are not the group's
        any more, whatever its file ids say). The result is `{result, recovered}` as an operation's, without a
        track."""
        if (not isinstance(group_id, str) or isinstance(file_id, bool) or not isinstance(file_id, int)
                or not _paths_list(paths)):
            raise ValueError(NOT_ANSWERABLE)
        db.group_ids(group_id)

        def change(ctx) -> dict:
            key, e = next(((k, t) for k, t in self._state()["tracks"].items() if t.get("file_id") == file_id),
                          (None, None))
            dst = folders_mod.supersede(self._paths, group_id, file_id, paths, emit=ctx.emit, now=self._svc.now)
            result = Result("replaced", (e or {}).get("folder") or "", (e or {}).get("artist") or "",
                            (e or {}).get("title") or "", key, folders_mod.MOVED.format(dst=dst),
                            (e or {}).get("status"), (e or {}).get("source"), (e or {}).get("cutoff_hz"), dst)
            return {"result": asdict(result), "recovered": []}

        return {"job_id": self._jobs.start("supersede", replanned_work(self._store, change, self._svc.now)).id}

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

    # --- upgrades, batches and the rekordbox check (issue 33 stage B; every action takes a list) ---

    @staticmethod
    def _track_list(track_ids: object) -> list[str]:
        """The tracks an action is about: a non-empty list of song keys (a lone string is bad input), each once."""
        if not isinstance(track_ids, list) or not track_ids or not all(isinstance(t, str) and t for t in track_ids):
            raise ValueError(NO_TRACKS)
        return list(dict.fromkeys(track_ids))

    def _begin(self) -> tuple[dict, list]:
        """What every upgrade job starts with: the records, interrupted steps finished (before a batch is recorded, or
        the new batch would be marked crashed), the scratch folder cleared. Returns (state, [[message, ok]])."""
        state = library.open_state(self._paths)
        recovered = library.recover_pending(self._paths, state)
        library.clear_tmp(self._paths, state)
        return state, [[message, ok] for message, ok in recovered]

    def _rekordbox_services(self) -> dict:
        """The sync's Auto-upgrade phase talks to rekordbox through the hub's services (tests and the fake never touch
        a real one): whether it runs, where its library is, and how two files are compared."""
        return {"running": self._svc.rekordbox_running, "place": self._svc.rekordbox_place(),
                "compare": self._svc.compare, "now": self._svc.now}

    def _rekordbox_options(self, ctx, state: dict) -> dict:
        return {"emit": ctx.emit, "token": ctx.token, "now": self._svc.now, "state": state,
                "running": self._svc.rekordbox_running, "place": self._svc.rekordbox_place()}

    def _batch_work(self, make: Callable[[], int] | None, resume: int | None, *, alone: bool):
        """A Same track batch as a write job: `make()` records a new batch of the chosen tracks (after recovery), or
        `resume` names a stopped one. The result is a BatchResult dict (+ `recovered`); a Stop, rekordbox opened
        (`rekordbox_open`), another window changing rekordbox (`busy`) and a batch with nothing to do (`refused`) end
        the job as a problem that still carries the batch (`JobFinished.result`), so the page can show where it stopped
        and Resume. `alone`: a batch of one track that meets rekordbox open or busy before anything ran is closed
        instead of left stopped (the track simply stays in Upgrade ready; `batches.close_unrun`)."""
        def work(ctx) -> dict:
            state, recovered = self._begin()
            batch_id = resume if resume is not None else make()
            options = self._rekordbox_options(ctx, state)
            call = batches.resume if resume is not None else batches.run
            try:
                result = call(self._paths, batch_id, compare=self._svc.compare, **options)
            except (batches.Stopped, batches.RekordboxOpen, batches.Refused, batches.Busy) as e:
                result = e.result if hasattr(e, "result") else batches.result_of(self._paths, batch_id)
                if alone and not isinstance(e, (batches.Stopped, batches.Refused)) and result.total == 1 \
                        and not result.done:
                    result = batches.close_unrun(self._paths, batch_id, "busy" if isinstance(e, batches.Busy)
                                                 else "rekordbox_open", str(e), now=self._svc.now)
                ctx.failed_result = {**result.to_dict(), "recovered": recovered}
                raise
            return {**result.to_dict(), "recovered": recovered}
        return work

    def _each_work(self, ids: list[str], mode: str):
        """New track and Discard on a list: one job, one track after the other (Stop between them, per-track results,
        no batch record, no Resume: each is quick and has its own undo). One track keeps the old single-track
        behaviour: the entry as the page showed it is checked and a failure ends the job with its own words. The
        result is BatchResult-shaped (`batch` null)."""
        with self._lock:
            expect = self._shown.get(ids[0]) if len(ids) == 1 else None
        one = len(ids) == 1

        def work(ctx) -> dict:
            state, recovered = self._begin()
            if one and ((e := state["tracks"].get(ids[0])) is None or snapshot(e) != expect):
                raise OpProblem(ops.CHANGED, "changed")
            results: list[batches.ItemResult] = []
            stopped = False
            for n, key in enumerate(ids):
                try:
                    ctx.token.check()
                except Cancelled:
                    stopped = True
                    results += [batches.ItemResult(t, mode, "planned", None, None, None, None) for t in ids[n:]]
                    break
                e = state["tracks"].get(key)
                if not e or not e.get("upgrade"):
                    if one:
                        raise OpProblem("No better version is waiting for this track any more.", "changed")
                    results.append(batches.ItemResult(key, mode, "skipped", "no_upgrade", None, None, None))
                    continue
                ctx.emit(BatchProgress(0, n, len(ids), key, f"{e['artist']} - {e['title']}"))
                up = dict(e["upgrade"])
                try:
                    done = (upgrades.add_new(self._paths, state, key, up, self._svc.compare,
                                             offset=self._svc.timeline_offset, now=self._svc.now)
                            if mode == "add_new" else upgrades.discard(self._paths, state, key, up))
                except Exception as err:  # noqa: BLE001 - one track's surprise must not stop the others
                    ops.log_operation(self._paths, self._svc.now(), key, e, f"upgrade_{mode}", "failed",
                                      f"{type(err).__name__}: {err}")
                    if one:
                        raise
                    message = str(err) if isinstance(err, (upgrades.UpgradeProblem, OpProblem)) else \
                        f"Could not {'add' if mode == 'add_new' else 'discard'} {e['artist']} - {e['title']}."
                    results.append(batches.ItemResult(key, mode, "failed", None, message, None, None))
                else:
                    ops.log_operation(self._paths, self._svc.now(), key, e, f"upgrade_{mode}", "done", done.note)
                    results.append(batches.ItemResult(key, mode, "done", None, done.note, done.path, None))
            count = lambda st: sum(1 for r in results if r.state == st)  # noqa: E731
            if count("done"):
                rep.write_not_lossless(self._paths, state)
            body = {"batch": None, "state": "stopped" if stopped else "done", "stop_reason": "stop" if stopped else None,
                    "total": len(results), "done": count("done"), "skipped": count("skipped"), "failed": count("failed"),
                    "results": [r.to_dict() for r in results], "backup": None, "recovered": recovered}
            if stopped:
                ctx.failed_result = body
                raise batches.Stopped(batches.BatchResult(0, "stopped", "stop", body["total"], body["done"],
                                                          body["skipped"], body["failed"], results, None))
            ctx.emit(BatchProgress(0, len(ids), len(ids), None, None))
            return body
        return work

    def _undo_work(self, target: list[str] | int):
        """Undo of tracks (newest first) or of a whole batch, as one job. The result is an UndoResult dict (+
        `recovered`); rekordbox open and Stop end it as a problem that carries the result. When nothing at all could be
        undone the job fails `refused` (one track: with that track's own words), the results still in the result."""
        def work(ctx) -> dict:
            state, recovered = self._begin()
            try:
                result = batches.undo(self._paths, target, **self._rekordbox_options(ctx, state))
            except (batches.RekordboxOpen, batches.UndoStopped) as e:
                ctx.failed_result = {**e.result.to_dict(), "recovered": recovered}
                raise
            body = {**result.to_dict(), "recovered": recovered}
            if result.total and not result.undone:
                ctx.failed_result = body
                raise OpProblem(result.results[0].message if result.total == 1 else UNDO_NONE, "refused")
            return body
        return work

    @bridge
    def rekordbox_checked(self, track_ids: list[str]) -> dict:
        """"Done, checked in rekordbox" for tracks (a batch card sends its done tracks): the reminders and with them
        the undo end. A write job (kind "rekordbox_checked"); the result lists the `checked` tracks, those with
        nothing to check (`not_checked`) and the engine's `results`."""
        ids = self._track_list(track_ids)

        def work(ctx) -> dict:
            state, recovered = self._begin()
            before = {t: state["tracks"].get(t) for t in ids}
            done = batches.checked(self._paths, ids, state=state, now=self._svc.now)
            checked = [r.track_id for r in done]
            if not checked:
                raise OpProblem(NOTHING_TO_CHECK, "changed")
            for t in checked:
                ops.log_operation(self._paths, self._svc.now(), t, before[t], "rekordbox_checked", "done",
                                  "checked in rekordbox")
            return {"results": [asdict(r) for r in done], "checked": checked,
                    "not_checked": [t for t in ids if t not in checked], "recovered": recovered}
        return {"job_id": self._jobs.start("rekordbox_checked", work, track_id=ids[0] if len(ids) == 1 else None).id}

    @bridge
    def upgrade(self, track_ids: list[str], mode: str) -> dict:
        """Replaces tracks with their better versions. `swap` is Same track for any format and runs one AIFF batch (job
        kind "upgrade_batch", result a BatchResult); `add_new` and `discard` run the tracks one after the other (kinds
        "upgrade_add_new" / "upgrade_discard", a BatchResult-shaped result without a batch). One track is a list of
        one. Progress is a BatchProgress event for all three."""
        if mode not in UPGRADE_MODES:
            raise ValueError(f"mode must be one of {', '.join(UPGRADE_MODES)}")
        ids = self._track_list(track_ids)
        track = ids[0] if len(ids) == 1 else None
        if mode == "swap":
            work = self._batch_work(lambda: batches.start(
                self._paths, [(t, "same_track") for t in ids], started_by="user", now=self._svc.now), None,
                alone=len(ids) == 1)
            return {"job_id": self._jobs.start("upgrade_batch", work, track_id=track).id}
        return {"job_id": self._jobs.start(f"upgrade_{mode}", self._each_work(ids, mode), track_id=track).id}

    @bridge
    def upgrade_all(self) -> dict:
        """Upgrade all: Same track for every parked upgrade the To-do list shows as possible (the group's `all.n`), as
        one batch started by `upgrade_all` (job kind "upgrade_batch")."""
        groups = self._todo(self._state(), "upgrade_ready", False)["groups"]
        ids = [i["track_id"] for g in groups if g["key"] == "upgrade_ready" for i in g["items"]
               if i["same_track"] is None]
        if not ids:
            raise OpProblem(NO_UPGRADES, "refused")
        work = self._batch_work(lambda: batches.start(
            self._paths, [(t, "same_track") for t in ids], started_by="upgrade_all", now=self._svc.now), None,
            alone=False)
        return {"job_id": self._jobs.start("upgrade_batch", work).id}

    def _stopped_aiff(self, batch_id: object):
        if isinstance(batch_id, bool) or not isinstance(batch_id, int):
            raise ValueError(NO_AIFF_BATCH)
        with self._move_log() as conn:
            row = db.aiff_batch(conn, batch_id) if conn is not None else None
        if row is None:
            raise ValueError(NO_AIFF_BATCH)
        return row

    @bridge
    def batch_resume(self, batch_id: int) -> dict:
        """Carries on a stopped Same track batch (its planned tracks, their eligibility asked again): a write job (kind
        "batch_resume"); the result is a BatchResult."""
        if self._stopped_aiff(batch_id).state != "stopped":
            raise ValueError(NOT_STOPPED)
        return {"job_id": self._jobs.start("batch_resume", self._batch_work(None, batch_id, alone=False)).id}

    @bridge
    def batch_undo(self, batch_id: int) -> dict:
        """Undoes every track a batch did, newest first ("Undo all"): a write job (kind "batch_undo"); the result is
        an UndoResult."""
        self._stopped_aiff(batch_id)
        return {"job_id": self._jobs.start("batch_undo", self._undo_work(batch_id)).id}

    @bridge
    def undo_upgrade(self, track_ids: list[str]) -> dict:
        """"Undo" next to "Done, checked in rekordbox" on items with `can_undo`: puts a swap, an added file or a Same
        track back as it was (the upgrade waits again), newest first, as one job (kind "undo_upgrade"). The result is an
        UndoResult; a refusal per track (a file changed since, nothing to undo) is in its results, and when nothing
        could be undone the job ends `refused`. Needs rekordbox closed where a step wrote it (`rekordbox_open`)."""
        ids = self._track_list(track_ids)
        return {"job_id": self._jobs.start("undo_upgrade", self._undo_work(ids),
                                           track_id=ids[0] if len(ids) == 1 else None).id}


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
            self._update_settings(lambda s: replace(s, spotify_skipped=False))
            self._store.clear_service("spotify")  # a read problem about Spotify's login is out of date now
            return {"user": name}

        return {"job_id": self._jobs.start("setup_spotify_login", work).id}

    @bridge
    def setup_skip_spotify(self) -> dict:
        """"I don't use Spotify": the Spotify step counts as done and playlists come from the other services' links. Connecting
        Spotify later (setup or Settings) un-skips it."""
        def work(ctx) -> dict:
            self._update_settings(lambda s: replace(s, spotify_skipped=True))
            return {}

        return {"job_id": self._jobs.start("setup_skip_spotify", work).id}

    @bridge
    def set_read_liked_music(self, on: bool) -> dict:
        """Settings' "Read my Liked music" (sources-round D5): whether YouTube Music's Liked music line is read, through
        the YouTube login. Turning it on without a YouTube account is refused (`not_set_up`); turning it off never
        touches playlists.txt (a listed line then reads as off)."""
        if not isinstance(on, bool):
            raise OpProblem("on must be true or false.", "refused")

        def work(ctx) -> dict:
            if on and "youtube" not in self._settings().accounts:
                raise OpProblem(LIKED_NEEDS_LOGIN, "not_set_up")
            self._update_settings(lambda s: replace(s, read_liked_music=on))
            return {}

        return {"job_id": self._jobs.start("set_read_liked_music", work).id}

    @bridge
    def set_auto_upgrade(self, on: bool) -> dict:
        """"Upgrade automatically when I sync" (Settings, Setup; issue 33 stage C): whether a sync ends with Same track
        for every upgrade that needs no decision, while rekordbox is closed. On by default. Turning it off never touches
        the upgrades waiting (they wait in To-do); turning it on moves nothing until the next sync."""
        if not isinstance(on, bool):
            raise OpProblem("on must be true or false.", "refused")

        def work(ctx) -> dict:
            self._update_settings(lambda s: replace(s, auto_upgrade=on))
            return {}

        return {"job_id": self._jobs.start("set_auto_upgrade", work).id}

    @bridge
    def add_liked_music(self) -> dict:
        """"Add Liked music to Playlists" (sources-round D8): appends `Liked_music = <its link>` to the end of
        playlists.txt (YouTube Music shares no link for it). Refused with `setting_off` while the choice is off and
        `exists` when a Liked music line is listed already, on or off. Answers `{folder}`."""
        def work(ctx) -> dict:
            if not self._settings().reads_liked_music:
                raise sources.SourceError(youtube_music.SETTING_OFF, "setting_off", youtube_music.SERVICE,
                                          youtube_music.SETTING)
            loaded = pf.load(self._paths.playlists_file)
            if pf.lists_liked_music(loaded.rows):
                raise OpProblem(LIKED_LISTED, "exists")
            taken = {fold(r.folder) for r in loaded.rows}
            folder, n = youtube_music.LIKED_MUSIC_FOLDER, 1
            while fold(folder) in taken:  # a folder of that name is another playlist's: add a number
                n += 1
                folder = f"{youtube_music.LIKED_MUSIC_FOLDER}_{n}"
            link = youtube_music.canonical_link(youtube_music.LIKED_MUSIC)
            pf.save(self._paths.playlists_file, [*loaded.rows, pf.Row(folder, link)], loaded.version)
            self._store.mark_stale()  # the plan was made for the old lines
            return {"folder": folder}

        return {"job_id": self._jobs.start("add_liked_music", work).id}

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
            self._store.clear_service("qobuz")  # a read problem about Qobuz's login is out of date now
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
    def setup_skip_import(self) -> dict:
        """"Skip" on Setup's "Your existing music": the step counts as done. A brief save, not a job (one writer at a
        time: busy while a job writes, console while a terminal run does)."""
        self._update_settings(lambda s: replace(s, import_skipped=True))
        return {}

    @bridge
    def setup_account(self, service: str, browser: str, profile: str | None = None) -> dict:
        """Checks the login in that browser profile (only cookie names are read), then saves the browser and profile
        with the check. A login without Premium or Go+ is saved too: SoundCloud's is used for downloads (many tracks
        have no Go+ stream, see check_message), YouTube's only to read Liked music (`Settings.download_accounts`). A
        failed check of the saved login itself is recorded on it."""
        self._account(service, browser)

        def work(ctx) -> dict:
            check = self._svc.fallback(emit=ctx.emit, check=ctx.token.check).check_account(service, browser, profile)
            return self._account_result(service, browser, profile, check)

        return {"job_id": self._jobs.start("setup_account", work).id}

    def _account_result(self, service: str, browser: str, profile: str | None, check: dict) -> dict:
        saved = check["ok"] or check["problem"] == "no_premium"
        record = self._check_record(check)

        def change(s: Settings) -> Settings:
            if saved:
                return s.with_account(service, browser, profile).with_check(service, record)
            a = s.accounts.get(service)
            if a is not None and (a.browser, a.profile) == (browser, profile):
                return s.with_check(service, record)  # the saved login no longer works: Settings says so
            return s
        self._update_settings(change)
        if saved and service == "soundcloud":  # a read problem about SoundCloud's login (a you/likes line) is out of date now
            self._store.clear_service("soundcloud", frozenset({"login_expired"}))  # not offline
            # only the likes hint (W8) is about the login: a private set's "doesn't show this playlist" stays
            self._store.clear_service("soundcloud", frozenset({"playlist_unreadable"}), soundcloud.LIKES_HINT)
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
            if found:
                self._store.clear_service("qobuz")  # the saved login works: a stored Qobuz read problem is out of date
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
            raise ValueError(f"This is not a playlist link Discjockey can read ({sources.service_list()}): "
                             f"{line['link']}")
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

