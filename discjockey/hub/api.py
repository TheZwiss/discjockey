"""HubApi: the methods the window may call (pywebview's js_api; spec "hub" 6.8 and the plan's bridge contract).

pywebview runs every call on a new thread of its own and passes the page's arguments positionally. Every method
returns JSON: {"ok": true, ...} or {"ok": false, "kind", "message"} (plain English, never a traceback). Everything
that is not a bridge method starts with "_", because pywebview exposes every public attribute to the page.
"""
from __future__ import annotations

import contextlib
import contextvars
import functools
import hashlib
import inspect
import json
import logging
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import threading
import tomllib
import traceback
import unicodedata
import webbrowser
from collections import OrderedDict, deque
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from stat import S_ISREG
import time
from typing import TYPE_CHECKING, Callable
from urllib.parse import quote

from .. import __version__, align, browsers, candidates, config, db, library, ops, planner, playlists_file as pf, qobuz
from .. import aiff_plan as plans, audio, cdj, missing, models, quality
from .. import app_update as update_check, setup_cmd, tool_updates, tools
from .. import folders as folders_mod, importer, scanner, sources, tidy
from ..sources import soundcloud, spotify, youtube_music
from ..sources.soundcloud import YOU as SOUNDCLOUD_YOU  # the module imports yt-dlp only inside functions
from .. import auto_upgrade, batches, convert, rekordbox, report as rep, run, upgrades
from ..rekordbox import backup as rb_backup, lock as rb_lock, match as rb_match, preview as rb_preview, process as rb_process
from ..accounts import ACCOUNTS, BROWSERS, SERVICE_NAMES, SERVICES, check_message
from ..acquire import make_ready
from ..candidates import current_key
from ..fallback import FallbackSource
from ..library import NoLibrary, Paths, Resolved, StateError, SupportPaths
from ..events import BatchProgress, Cancelled, CancelToken, Result, no_emit
from ..models import (SERVICE_NAMES as PLAYLIST_SERVICES, SOURCE_NAMES, AiffBatchRow, BatchResult, BatchRow, Candidate,
                      PlaylistLine,
                      PlaylistRecord, ReadHead, SaveChoice, SourceTrack, WatchedFolder, file_missing, token)
from ..names import fold, search_fold
from ..words import SCAN_OLDER, preview_words, rekordbox_words
from ..ops import OpProblem
from .. import pending_signs, playlist_words, words as engine_words
from ..pacing import Budget, SharedPacer, streak_stopped
from ..qobuz import QobuzError, QobuzLoginRejected, QobuzNotSetUp, QobuzSource, config_file, login_problem
from ..settings import (MAX_DAILY_LIMIT, MAX_EXTRA, SCOPE_KINDS, Settings, SettingsError, extra_json, is_scope_target,
                        load_settings, update_settings_held)
from ..setup_cmd import TOOL_HINTS
from ..words import MISSING, NOT_CHOSEN  # the gate's words (`doctor` says them too)
from ..sources.spotify import REDIRECT_URI

if TYPE_CHECKING:
    from .shapes.setup import PlaylistOp, SaveFiles
from . import catalog, doctor as doctor_mod, history as history_mod, media as media_mod, plan_store, registry, select, shapes, since as since_mod, spectrum as spec, views
from .ids import BATCH_KINDS, BadId, parse as parse_id
from . import outcomes
from .outcomes import REASONS as OUTCOME_REASONS, problem_fields
from .jobs import (NOT_CONNECTED, UNEXPECTED, AppUpdate, Busy, DrivesChanged, FileDropped, Job, Jobs, PreviewStore, SignInPhase,
                   event_dict, finished_of, import_work, problem_of, refresh_work, service_of, sync_work)

RUN_ID = re.compile(r"\d{4}-\d{2}-\d{2}_\d{6}")
WHICH = ("current", "upgrade")
UPGRADE_MODES = ("same_track", "new_track", "discard")
NEW_TRACK_ACTION = {"new_track": "add_new", "discard": "discard"}  # the bridge's mode -> the action each track runs
NO_TRACKS = "No tracks were chosen."
NO_UPGRADES = "None of these can be upgraded right now."
PLAN_NOT_DISCARD = "A plan goes with Same track or New track; Discard has none."
PLAN_NOTHING = OUTCOME_REASONS["changed"].text
PLAN_CHANGED_WORDS = OUTCOME_REASONS["changed"].text
RESUME_FIRST = "An upgrade was stopped halfway. Carry it on instead of starting Upgrade all again."
BAD_AIFF_SCOPE = "That isn't a set of files Discjockey can make AIFF."
BAD_AIFF_ONLY = "`only` is rename, or left out."
AIFF_ORIGINS = ("library", "todo")  # where a Convert was started: the batch's scope says so ("library:selection")
SYNC_PLAN = "sync"  # the kind of the plan a Sync preview stores (`plan_store`)
PLAN_RESAVE = timedelta(hours=1)  # a Sync plan this window saved is saved again after this long (it is good for 24 hours)
JOB_EVENTS_PAGE = 500  # the most lines one `job_events` answer carries
JOB_EVENTS_READERS = 4  # followed jobs whose reader is kept between answers (the least recent is dropped)
TAG_CACHE_MAX = 50000  # file tag reads kept in memory (plan stage D §0.7); a library past it starts the cache over
NO_AIFF_BATCH = "Discjockey has no record of this batch."
NOT_STOPPED = "This batch is not stopped, so there is nothing to resume."
UNDO_NONE = batches.NOTHING_UNDONE
NOTHING_TO_CHECK = "There is nothing to check for these tracks any more."
NO_MISSING_LEFT = {select.DOWNLOAD_AGAIN: "No song whose file is missing waits for Download again.",
                   select.REMOVE_MISSING: "No song whose file is missing waits for Remove from library."}
NOTHING_TO_CHECK_ONE = "This track has nothing to check in rekordbox."
NEWER_CHECK = "A later batch ({later}) changed this track again, so its check belongs to that batch: `check done --batch {later}`."
NEWER_CHECK_STEP = "This track was changed again after this batch, so its check is not this batch's: `check done {track}`."
CHECK_ENDS_UNDO = " Their undo has ended: `track undo` can't put them back any more."
BATCH_OR_TRACKS = "Name the tracks or a batch, not both."
NO_PLAN_COMMANDS = frozenset(("upgrade discard", "track undo", "batch undo", "rekordbox restore", "library facts", "folder add", "folder remove",
                         "missing download", "missing remove"))  # run on what is there when --yes comes: no plan to run
QOBUZ_PAUSED_NOTE = "Qobuz was not searched: it is paused after 3 failed requests in a row."
PLAYLIST_COPIES = 20  # how many earlier copies of playlists.txt are kept for the undo that puts one back
COPY_NAME = re.compile(r"(\d{4}-\d{2}-\d{2}_\d{6})(?:_(\d+))?\.txt")  # `HubApi._keep_copy`'s file names
SYNC_RUNNING = "Not while a sync runs: Discjockey keeps its requests to Qobuz and YouTube paced."
AUTO_READ_DONE = "Your playlists were read by themselves once this session already. Use ↻ Read playlists to read them again."
NO_FILE = "There is no file at {path}."
NEEDS_FULL_PATH = "Give the full path of the file: it starts with /. {path} is not one."
NO_PATH = "A bought file needs the path of the file."
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
# Bridge methods that need a bound music folder: unbound, they answer no_library before anything runs. Every other
# method works with the support folder alone (Setup and Settings before a folder is chosen). Pinned by
# tests/test_hub_api_music.py and, against contract.ts, by hub-ui's contract test (keep the one-name-per-string form).
LIBRARY_METHODS = frozenset((
    "dashboard", "sidebar", "sync_preview", "refresh", "library", "track", "todo", "playlists", "limits",
    "limits_what_if", "save_limits", "mark_warnings_seen", "runs", "run", "spectrum",
    "search_candidates", "preview", "add_playlist", "preview_playlist_change", "start_sync", "save_playlists",
    "hide", "never_download", "add_bought_file", "use_candidate", "use_link", "reject_current",
    "rekordbox_checked", "upgrade", "upgrade_all", "undo_upgrade", "batch_resume", "batch_undo", "aiff_plan", "convert",
    "rename", "make_aiff", "rescan_library", "show_in_finder", "reveal", "open_report",
    "tidy_preview", "move_batches", "undo_preview", "tidy_up", "undo_moves",
    "watched_folders", "set_favourites", "set_crate_shown", "set_crates_shown", "check_import_folder", "removal_preview", "add_watched_folder", "remove_watched_folder",
    "start_import", "answer_same_song", "keep_duplicates", "keep_file", "add_liked_music",
    "missing_files_preview", "missing_files",
))
# the command line's own methods (`cli_first`; the window's HubApi has none of them) that need a music folder too
CLI_LIBRARY_METHODS = frozenset(("auto_upgrade_preview", "auto_upgrade_run", "history", "rekordbox_match",
                                 "library_superseded", "status_view", "prejob_start_sync"))  # `settings_view` needs none
# What a person types for a flag whose value `CliApi.resolve` turns into the method's own (`help` prints it as the flag's value)
RESOLVE_WORDS = {"upgrade_way": "same-track|new-track", "since": "today|yesterday|Nd|Nh|DATE",
                 "place": "all|playlist:NAME|folder:PATH|PATH", "report_file": "report:STAMP|last|not-lossless"}


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
    probe: Callable = quality.probe  # ffprobe's answer for one file: the facts a fill or a dry run reads
    process: Callable = make_ready
    pacer: Callable = SharedPacer  # (support folder, emit, token) -> the pacer of a sync's or "Use this"'s requests
    compare: Callable = align.compare_files
    timeline_offset: Callable = rekordbox.timeline_offset  # where rekordbox's timeline sits for a file (New track)
    # whether rekordbox runs and where its library is (late-bound: tests and the fake never touch a real one)
    rekordbox_running: Callable[[], bool] = lambda: rb_process.running()
    rekordbox_place: Callable[[], object] = lambda: rekordbox.locate()
    decode: Callable = quality.decode_mono
    now: Callable[[], datetime] = datetime.now
    mounted: Callable[[Path], bool] = os.path.ismount  # whether a /Volumes drive is connected (the scanner's rule)
    home: Path = Path.home()  # where the browsers keep their files (tests: a folder that doesn't exist)
    applications: tuple[Path, ...] = (Path("/Applications"),)  # the folders the browsers' apps are looked for in (tests: none)
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


# The bridge call being answered, `(method name, its arguments without self)`, for as long as `_answering` runs it. A job
# started inside it writes both into its registry record (`HubApi._job_record`), so `job list` says what the window started.
CALL: contextvars.ContextVar[tuple[str, dict] | None] = contextvars.ContextVar("bridge_call", default=None)


def _answering(fn):
    """The answer wrapper of `bridge` and `cli_first`: {"ok": true, **result} or {"ok": false, "kind", "message",
    "outcome", "reason", "next", "person_steps", "data"}; never raises. The window reads `kind` and `message`; the
    command line reads the rest (`outcomes.problem_fields`: the outcome row of the kind, the reason, the commands that
    move on, the steps only a person can do). A problem with a playlist service (a SourceError) also carries
    "service", a setting_off one "setting". A `BadId` (a typed id the command line cannot use) answers `bad_args`:
    the command line's methods raise it, and `todo` for a filter that is no group (the window sends only group keys)."""
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def call(self, *args, **kwargs):
        try:
            bound = dict(signature.bind(self, *args, **kwargs).arguments)
            bound.pop(next(iter(signature.parameters)), None)  # self
        except TypeError:  # the page called with wrong arguments: the call below answers it
            bound = {}
        token = CALL.set((fn.__name__, bound))
        try:
            if fn.__name__ in LIBRARY_METHODS or fn.__name__ in CLI_LIBRARY_METHODS:
                self._need_library()  # NoLibrary -> no_library before anything starts
            answer = fn(self, *args, **kwargs) or {}
            shapes.note_answer(fn.__name__, answer)  # test mode only: the answer must fit its shape
            return {"ok": True, **answer}
        except Busy as e:
            out = {"ok": False, "kind": e.kind, "message": str(e), **problem_fields(e.kind, e)}
            shapes.note_fail(fn.__name__, out)  # test mode only: a failure must fit `Fail`
            return out
        except StateError as e:
            out = {"ok": False, "kind": "config_invalid", "message": str(e), **problem_fields("config_invalid", e)}
            shapes.note_fail(fn.__name__, out)  # test mode only: a failure must fit `Fail`
            return out
        except BadId as e:
            out = {"ok": False, "kind": "bad_args", "message": e.message, "outcome": "bad_args", "reason": e.reason,
                   "next": list(e.next), "person_steps": [], "data": None}
            shapes.note_fail(fn.__name__, out)  # test mode only: a failure must fit `Fail`
            return out
        except plan_store.UnknownPlan as e:  # `--plan` with an id no dry run made (or one pruned long ago)
            out = {"ok": False, "kind": "bad_args", "message": str(e), "outcome": "bad_args", "reason": "unknown_id",
                   "next": [], "person_steps": [], "data": None}
            shapes.note_fail(fn.__name__, out)  # test mode only: a failure must fit `Fail`
            return out
        except registry.NoSuchJob as e:  # a job id the registry has no folder for (`job_events`, `stop(job_id)`)
            out = {"ok": False, "kind": "bad_args", "message": str(e), "outcome": "bad_args", "reason": e.reason,
                   "next": [], "person_steps": [], "data": None}
            shapes.note_fail(fn.__name__, out)  # test mode only: a failure must fit `Fail`
            return out
        except plan_store.PlanExpired as e:  # older than 24 hours, or made for another music folder
            out = {"ok": False, "kind": "refused", "message": str(e), **problem_fields("refused", e)}
            shapes.note_fail(fn.__name__, out)  # test mode only: a failure must fit `Fail`
            return out
        except TypeError as e:  # the page called with wrong arguments
            traceback.print_exc()
            out = {"ok": False, "kind": "crashed", "message": UNEXPECTED, **problem_fields("crashed")}
            shapes.note_fail(fn.__name__, out)  # test mode only: a failure must fit `Fail`
            return out
        except BaseException as e:  # noqa: BLE001 - nothing may reach the page as a traceback
            kind, message = problem_of(e)
            if kind == "crashed":  # for whoever looks at the terminal; the page gets the plain message
                traceback.print_exc()
            service = service_of(e)
            setting = getattr(e, "setting", None)  # setting_off: the choice in Settings that is off
            out = {"ok": False, "kind": kind, "message": message, **({"service": service} if service else {}),
                   **({"setting": setting} if setting else {}), **problem_fields(kind, e)}
            shapes.note_fail(fn.__name__, out)  # test mode only: a failure must fit `Fail`
            return out
        finally:
            CALL.reset(token)

    call.__signature__ = signature  # pywebview reads the parameter names from it
    return call


def bridge(fn):
    """A method the window calls (pywebview reads its name and parameters). The catalogue and its test find the
    bridge methods by `is_bridge`; contract.ts, types.ts and the fake bridge list exactly these."""
    call = _answering(fn)
    call.is_bridge = True
    return call


def cli_first(fn):
    """A method the command line needs and the window does not have (the catalogue's `cli_first` entries): the same
    answers as a bridge method, but not part of the window's contract (no `is_bridge`, nothing in contract.ts)."""
    call = _answering(fn)
    call.is_cli_first = True
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


def _file_problem(path: str | Path) -> str | None:
    """Why `path` can't be added as a file, None when it is an absolute path of a regular file this process can open
    for reading: the words of a relative path (NEEDS_FULL_PATH), of a missing file or one that is no regular file
    (NO_FILE), or of one macOS doesn't let it read (`ops.NO_ACCESS`). It stats before it opens, so a pipe is never
    opened (that would wait for a writer)."""
    p = Path(path)
    if not p.is_absolute():
        return NEEDS_FULL_PATH.format(path=path)
    try:
        st = os.stat(p)
    except (FileNotFoundError, NotADirectoryError, ValueError):  # ValueError: a NUL byte in the path
        return NO_FILE.format(path=path)
    except OSError:
        return ops.NO_ACCESS
    if not S_ISREG(st.st_mode):
        return NO_FILE.format(path=path)
    try:
        with open(p, "rb"):
            pass
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        return NO_FILE.format(path=path)
    except OSError:
        return ops.NO_ACCESS
    return None


def _import_folders(paths: Paths | None) -> int:
    """How many import folders the library watches (0 without a library or library.db: nothing to read)."""
    if paths is None or not paths.db_file.exists():
        return 0
    try:
        with db.connect(paths.db_file, read_only=True) as conn:
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




class _FollowReader:
    """What `HubApi.job_events` keeps of one followed job between answers: the file reader (its byte offsets can't travel
    in a position), the lines it read but did not deliver yet (an answer holds at most `JOB_EVENTS_PAGE`), and `count`,
    the position of the next line to deliver. A reader made for an `after` drops that many lines first."""

    def __init__(self, reader: registry.EventReader, after: int):
        self.reader, self.count = reader, after
        self._skip = after  # lines of the files still to drop: they were delivered before this reader existed
        self._pending: deque[str] = deque()

    def take(self, most: int) -> list[str]:
        self._pending.extend(self.reader.read())
        while self._skip and self._pending:
            self._pending.popleft()
            self._skip -= 1
        if self._skip:  # the position is past what the files hold: nothing to deliver yet
            return []
        taken = [self._pending.popleft() for _ in range(min(most, len(self._pending)))]
        self.count += len(taken)
        return taken


class HubApi:
    _skipped_check_is_ok = False  # the window's job ends `changed` when no named track had a check; the command line's is ok, the rows skipped
    _resume_first = False  # the command line refuses Upgrade all while a stopped upgrade batch waits (the window hides it)
    _via = "window"  # where the batches this api starts say they started (`CliApi`: terminal)

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
        self._jobs = Jobs(None, self._emit, now=self._svc.now, registry=registry.Registry(self._support.support))
        self._jobs.on_locked = self._record_waiting_signs  # a write job starts: signs that waited for the lock go in
        self._jobs.record_of = self._job_record  # what a job the window starts writes into the registry
        self._jobs.on_finished = self._registered_envelope  # ... and its `result.json` at the end
        self._settings_mutex = threading.Lock()  # settings.json: read, change, save — one at a time
        self._store = PreviewStore()
        # the plan derived from the stored read (`_plan`): the newest key's plan, so each page asks library.db's head,
        # not the whole read, and a process that did not make the read still has the plan
        self._plan_lock = threading.Lock()
        self._plan_cache: tuple[tuple, run.Prepared] | None = None
        # the Sync plan this window last stored in `<support>/plans/` and when (`_store_sync_plan`), under `_lock`
        self._saved_plan: tuple[str, dict, datetime] | None = None
        self._rb_cache: tuple[tuple, rekordbox.Status] | None = None  # (_rekordbox_status's key, its answer)
        self._rb_at: str | None = None  # when `_rb_cache`'s answer was read (ISO time): the `as_of` of a `writing` answer
        # the CDJ group's plan (To-do's `all {n,k}` and its rows' waits): (state generation, rekordbox's key, drives
        # away) -> the plan, so each To-do read doesn't open rekordbox's library again (A7)
        self._cdj_cache: tuple[tuple, plans.AiffPlan] | None = None
        # what a file's tags said (plan stage D §0.7): (path, size, mtime_ns) -> audio.FileFacts, so reopening the panel
        # reads no file again; a changed file has a new key
        self._tag_cache: dict[tuple[str, int, int], audio.FileFacts] = {}
        self._drives_seen: dict[str, str] | None = None  # the away set the drives watch saw last (None: not yet)
        self._lock = threading.Lock()
        self._auto_lock = threading.Lock()
        # `job_events`: one reader per followed job (the least recent dropped), with how many lines it delivered and the
        # lines it read but did not deliver yet. Its own lock: file reads never hold `_lock` (the bridge's)
        self._events_lock = threading.Lock()
        self._event_readers: OrderedDict[str, _FollowReader] = OrderedDict()
        self._quit: Callable[[], None] | None = None  # set by app.main: closes the window
        # the user stopping an import is in library.db (`import_state`: every process reads it): the import starts by
        # itself no more until Continue import (D14). Only the window's automatic start once per session is kept here
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
            with self._plan_lock:
                self._plan_cache = None  # another library's records: its plan is derived afresh
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
            self._jobs.watch_registry()
            self._watch_playlists_file()
            self._watch_drives()

    def _first_read(self) -> None:
        self.refresh(auto=True)

    def _start(self, resolved: Resolved) -> None:
        """At launch (app.main): bind the library when the music folder is there, else remember why not."""
        try:  # the lock file a reader of rekordbox holds exists before the first writer
            rb_lock.ensure(self._support.support)
        except OSError:
            pass
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

    def _plan_root(self) -> str | None:
        return str(self._bound.root) if self._bound is not None else None

    def _bind_plan(self, plan_id: str, now: Mapping[str, object]) -> tuple[plan_store.Plan, plan_store.Binding]:
        """The plan `plan_id` loaded for this music folder and held against the items a run finds now (`now`: item key
        -> the answer the engine gives today): which still stand, which changed (the run answers them `skipped`,
        `changed`) and which are new since the plan (`data.new_since_plan`, left out). Raises `UnknownPlan` or
        `PlanExpired`, which `_answering` turns into `bad_args` / `refused` for whoever called. What every write method
        that takes a `plan_id` starts with: before the job starts (`upgrade`, `upgrade_all`: the job asks each item again under
        its lock)."""
        plan = plan_store.load(self._support.support, plan_id, self._plan_root())
        return plan, plan_store.bind(plan, now)

    @staticmethod
    def _planned_actions(plan: plan_store.Plan) -> dict[str, tuple[str, str, str]]:
        """A stored Sync plan's actions by their ids as `run.action_key`s. A plan of another kind, or one whose file
        holds no such items, is no plan to start a sync from: `UnknownPlan`."""
        try:
            if plan.kind != SYNC_PLAN:
                raise TypeError(plan.kind)
            return {act: (item["kind"], item["track_id"], item["to_dir"]) for act, item in plan.items.items()}
        except (KeyError, TypeError):
            raise plan_store.UnknownPlan(plan.id) from None

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

    def _auto_upgrade_ready(self, state: dict, prep: run.Prepared | None, running: bool) -> dict | None:
        """`sync_preview().auto_upgrade`: `{on, ready, places, place_notes}`. `on`: the Auto-upgrade switch; `ready`: the
        tracks the sync's last phase would upgrade now (`auto_upgrade.plan`, quick: the cached rekordbox state, no read
        open of its library; a refusal that can't be told to still hold without one counts as holding), counting those
        that would wait for rekordbox, not the placements; `places`: the songs it would put their parked better version
        in for (Download again on a missing file; with the switch off too), counting those that would wait;
        `place_notes`: `{closed, open}` the sentence for them (`engine_words.place_plan_line`, rekordbox closed / open), null
        with none. None when the switch is off and nothing is to be placed (or the settings file is unreadable) or there
        is no preview (no plan `prep`, so no questions to hold songs). `running`: whether rekordbox runs, asked once by the
        caller (`sync_preview`) and shared with the cached rekordbox state, so a preview costs one process check."""
        if prep is None:
            return None
        try:
            settings = load_settings(self._support.settings_file)
        except SettingsError:
            return None
        planned = auto_upgrade.plan(self._paths, state, {q.song_key for q in prep.plan.questions}, settings,
                                    running=lambda: running, place=self._svc.rekordbox_place(),
                                    status=self._rekordbox_status(running), quick=True)
        if planned is None:
            return None
        coming = [k for k in (*planned.run, *(k for k, _ in planned.waiting))]
        places = sum(1 for k in coming if k in planned.place)
        if not settings.auto_upgrade and places == 0:
            return None
        name = None
        if places == 1:  # the one song is named in the sentence
            name = engine_words.song_name(state["tracks"].get(next(k for k in coming if k in planned.place)) or {})
        notes = {"closed": engine_words.place_plan_line(places, False, name),
                 "open": engine_words.place_plan_line(places, True, name)} if places else None
        return {"on": bool(settings.auto_upgrade), "ready": len(coming) - places, "places": places, "place_notes": notes}

    def _checked_batches(self, state: dict) -> dict[int, AiffBatchRow]:
        """The AIFF batches the open rekordbox checks belong to, by id: To-do names the checks of a sync's Auto-upgrade
        batch differently (`started_by`) and says "Made AIFF" for a Convert batch (`kind`)."""
        ids = {c["batch"] for e in state["tracks"].values() if (c := e.get("rekordbox_check")) and c.get("batch")}
        if not ids:
            return {}
        with self._move_log() as conn:
            if conn is None:
                return {}
            rows = (db.aiff_batch(conn, i) for i in sorted(ids))
            return {r.id: r for r in rows if r is not None}

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

    def _plan(self, *, strict: bool = False) -> run.Prepared | None:
        """The Sync plan, derived from the stored read (issue 39 phase 2, D22): `run.prepared_from_read` on library.db's
        newest good sync read, the records and the settings as they are now. Never stored: every process that asks gets
        the plan for the library as it is, after any read or write, so no writer re-plans anything. None before the
        first good read (and while no library is bound or library.db does not exist yet). Kept for the newest key
        `(library folder, newest read id of any kind, the records' generation, sha256 of settings.json, today)`: a check
        read may replace a record the plan's songs come from, a write changes the generation, and the planner plans
        with today's date (budgets, first checks). A settings.json or state that can't be read gives no plan (None),
        as `PreviewStore` did, so a page that only shows what there is keeps working; `strict` (a Sync preview and a
        sync) raises the SettingsError / StateError instead."""
        return self._plan_and_head(strict=strict)[1]

    def _plan_and_head(self, *, strict: bool = False) -> tuple[ReadHead | None, run.Prepared | None]:
        """`_plan`'s answer with the stored read's head, read in one snapshot of library.db."""
        head, prep, _ = self._derive(True, strict)
        return head, prep

    def _derive(self, derive: bool, strict: bool) -> tuple[ReadHead | None, run.Prepared | None, Exception | None]:
        """(the stored read's head, its plan, why there is no plan though there is a good read). `derive` False: the head
        only (and settings.json read, to name a refusal). Not strict: a SettingsError / StateError from reading library.db, settings.json or the state is the third
        answer, never raised."""
        head = None
        try:
            paths = self._paths
        except NoLibrary:
            return None, None, None
        try:
            loaded = None
            with self._move_log() as conn:
                if conn is None:
                    return None, None, None
                with db.read_snapshot(conn):  # the head, the generation and the read are one moment of library.db
                    head = db.read_head(conn)
                    if head is None or head.sync_id is None:
                        return head, None, None
                    if not derive:
                        load_settings(self._support.settings_file)  # the one refusal a poll can name without a plan
                        return head, None, None
                    key = (str(paths.root), head.current, db._generation(conn), self._settings_hash(), self._today())
                    with self._plan_lock:
                        cached = self._plan_cache
                    if cached is not None and cached[0] == key:
                        return head, cached[1], None
                    loaded = db.load_read(conn)
            if loaded is None:  # the read went meanwhile (library.db replaced): no plan
                return head, None, None
            prep = run.prepared_from_read(paths, loaded)  # no lock held: two threads may both derive, the second stores
        except (SettingsError, StateError) as e:
            if strict:
                raise
            return head, None, e
        with self._plan_lock:
            self._plan_cache = (key, prep)
        return head, prep, None

    def _settings_hash(self) -> str:
        try:
            return hashlib.sha256(self._support.settings_file.read_bytes()).hexdigest()
        except FileNotFoundError:
            return ""

    def _read_view(self, *, plan: bool = True, strict: bool = False) -> views.ReadView:
        """What the pages show of the stored read: the derived plan and the newest sync read's problem and words (a
        failed first read shows its problem with no plan), with the window's `auto_read` and whether playlists.txt's
        lines are still those the plan was made for. `plan` False (the window's poll): the head only, nothing derived (a
        settings.json that is refused is still named).
        A plan that can't be derived (settings.json refused) shows that as the problem, with the read's time and name
        and no plan; `strict` raises it instead (the Sync preview answers it as an error)."""
        head, prep, error = self._derive(plan, strict)
        if head is None:
            return views.ReadView(auto_read=self._store.auto_read)
        label = None if head.sync_id is None else db.read_label(head.sync_id)
        if error is not None:
            problem, message = (problem_of(error) if isinstance(error, SettingsError) else ("failed", str(error)))
            return views.ReadView(None, head.read_at, problem, None, message, label, self._store.auto_read, False)
        return views.ReadView(prep, head.read_at, head.problem, head.problem_service, head.message, label,
                              self._store.auto_read, self._lines_changed(head.lines))

    def _lines_changed(self, stored: tuple[tuple[str, str], ...] | None) -> bool:
        """playlists.txt's switched-on lines (folder, ref; `line_no` shifts with a comment) are not those the stored read
        was made for, `stored` (a line added, removed, switched or retargeted since). With no line on at all (or no
        file) they changed if the read had any; a file that can't be read otherwise: unchanged. No good read: False."""
        if stored is None:
            return False
        try:
            now = tuple((ln.folder, ln.ref) for ln in config.load_playlists(self._paths.playlists_file))
        except config.ConfigError as e:
            return e.kind == "not_set_up" and bool(stored)
        return now != stored

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

    def _paused_accounts(self, state: dict | None = None) -> frozenset[str]:
        """The account services paused today, counting the signs still waiting for the library lock. `state`: the
        snapshot the caller has read already."""
        return run.paused_now(self._paths, self._state() if state is None else state, self._today())

    def _images(self, prep: run.Prepared | None) -> dict[str, str]:
        """Each song's cover address from the plan's read (`prep`: the plan the caller asked once)."""
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
        with db.connect(self._paths.db_file, read_only=True) as conn:
            where = db.online_file(conn, file_id)
        return media_mod.file_inside(*where) if where is not None else None

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

    def _others(self, prep: run.Prepared | None) -> dict[str, str]:
        reports = self._reports()
        return views.todo_others(prep, reports[-1][1] if reports else None)

    def _todo(self, state: dict, filt: Collection[str] | None, show_hidden: bool, count_only: bool = False) -> dict:
        """views.todo (`filt`: the groups to list, None for every one) with the import's questions (the last plan's) and duplicates (the plan's same-song groups and the
        records' same-audio ones, each with its files). `count_only` (the sidebar's number): the records' groups are
        counted without loading their files (they are online and not held by how they are found), so only the plan's
        few same-song groups read theirs; the groups of the answer are then not listed. While an import folder is
        away right now every group's files are read, so a group with a file in it is left out of the count too. The plan is
        asked once, for the questions, the groups, the others and the covers."""
        views.not_a_string(filt)
        prep = self._plan()
        questions = list(prep.plan.questions) if prep else []
        groups = list(prep.plan.duplicates) if prep else []
        files: dict[str, list] = {}
        counted: set[str] = set()
        owners: dict[int, str] = {}
        away = self._away_roots()
        with self._move_log() as conn:
            if conn is not None:
                found = db.duplicate_groups(conn)
                # with a folder away now, a group may have a file in it: its files are read to tell (views.todo)
                counted = {g.id for g in found} if count_only and not away else set()
                groups += found
                files = {g.id: db.group_files(conn, g.id) for g in groups if g.id not in counted}
                owners = db.file_songs(conn, {i for g in groups if g.id in counted for i in g.file_ids})
        # the songs an open question or duplicate group asks about leave the CDJ group (their decision comes first)
        decided = views.decided_songs(state, questions, groups, files, counted, away, owners)
        # the sidebar's number needs neither rekordbox's state nor a look at each file
        running = None if count_only else bool(self._svc.rekordbox_running())  # once for the whole answer (a `ps`)
        rb = None if count_only else self._rekordbox_status(running)
        # the files whose presence the page needs live: a parked upgrade's (Same track) and the CDJ group's (Convert)
        members = {} if count_only else cdj.group_members(state, include_hidden=True, held=decided)
        present = None if count_only else {k: batches.present(self._paths, e) for k, e in state["tracks"].items()
                                           if e.get("upgrade") or k in members}
        rows = [] if count_only else self._aiff_batches()
        checked = {} if count_only else self._checked_batches(state)
        # Convert all's counts: what the CDJ plan can run now and what waits (only a page that shows the group asks)
        cdj_plan = self._cdj_plan(state, away, decided, running) if members and (filt is None or "cdj" in filt) else None
        # where a missing file was (the Missing files group's words); the sidebar's count needs none
        where = None
        if not count_only and any(file_missing(e) for e in state["tracks"].values()):
            where = self._place(state)
        cdj_all = views.cdj_counts(cdj_plan.to_dict()) if cdj_plan else (0, 0)
        return views.todo(state, filt, show_hidden, self._others(prep), self._today(), self._cover(self._images(prep)),
                          questions, groups, files, self._audio, counted, away, rb, present,
                          views.stopped_batch(rows, kinds=("upgrade",)), self._auto_upgrade_on(),
                          {i: r.started_by for i, r in checked.items()}, cdj_all,
                          views.stopped_batch(rows, scope="todo:"), {i: r.kind for i, r in checked.items()},
                          cdj_plan.waits if cdj_plan else None, decided, self._paths.root, where)

    def _place(self, state: dict) -> Callable[[str], str]:
        """A file's place in the Folder column's words (a Library folder's playlist name, an import folder's name): where
        a missing file was."""
        return views.sites(state, pf.load(self._paths.playlists_file).rows, self._records_and_folders()[1]).place

    def _cdj_plan(self, state: dict, away: Mapping[str, str], decided: frozenset[str] | set[str],
                  running: bool | None = None) -> plans.AiffPlan:
        """The `cdj` scope's plan for To-do, remembered on the records' generation (every write of songs, files or
        decisions bumps it), rekordbox's cache key (`_rekordbox_status`: master.db's change, whether it runs) and the
        folders away now: a To-do read that changed none of them opens no library of rekordbox's again. A state that
        carries no generation is planned every time. `decided`: `views.decided_songs`, which the plan leaves out.
        `running`: whether rekordbox runs, when the caller (`_todo`) has asked already: the plan reuses it."""
        self._rekordbox_status(running)  # first: it refreshes the key below
        with self._lock:
            rb_key = self._rb_cache[0] if self._rb_cache else None
            last = self._cdj_cache
        generation = state.get("generation")
        key = ((generation, rb_key, tuple(sorted(away.items())), tuple(sorted(decided)))
               if generation is not None else None)
        if key is not None and last is not None and last[0] == key:
            return last[1]
        plan, blind = self._planned_read(state, {"kind": "cdj"}, held=decided, running=running)
        # a plan made while a writer held rekordbox.lock took rekordbox's cached state and no lookup: not kept
        if key is not None and not blind:
            with self._lock:
                self._cdj_cache = (key, plan)
        return plan

    def _rekordbox_status(self, running: bool | None = None) -> rekordbox.Status:
        """`_rekordbox_read`'s status: what the screens and plans take of rekordbox's state. `running`: as there."""
        return self._rekordbox_read(running)[0]

    def _rekordbox_read(self, running: bool | None = None
                        ) -> tuple[rekordbox.Status, bool, str | None, tuple[int, int] | None]:
        """rekordbox's state for the screens, cached on master.db's modified time and size plus whether rekordbox runs
        (plan rekordbox B §4): one read open per change. A reader takes `rekordbox.lock` shared and without waiting
        (design §6.1): while a writer of any Discjockey process holds it master.db is never opened and the answer is the
        last value (or "ready" when there is none), `writing` True, with the time it was read (`as_of`). A write job that
        holds no rekordbox session does not stop the read: only a writer's lock does. Returns (status, writing, as_of,
        stat): `stat` is master.db's (modified time in ns, size) as that value was read, None without a library.
        `running`: the answer to "does rekordbox run" the caller already has for this read answer (the check is a `ps`
        of ~40 ms, so a bridge read asks once and hands it down); None asks now. Only reads pass it: whatever guards a
        write of rekordbox's files asks fresh at the write."""
        if running is None:
            running = bool(self._svc.rekordbox_running())
        with rb_lock.reader_lock(self._support.support) as free:
            with self._lock:
                last, at = self._rb_cache, self._rb_at
            if not free:
                if last is None:
                    return rekordbox.Status("ready", running, None, None, None, None, None), True, None, None
                return replace(last[1], running=running), True, at, last[0][2]
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
                return last[1], False, None, stat
            try:
                answer = rekordbox.status(place, lambda: running)
            except Exception:  # noqa: BLE001 - status() never raises for a library it can't read; this is for the rest
                answer = rekordbox.Status("unreadable", running, None, None, None, None, None)
            with self._lock:
                self._rb_cache = (key, answer)
                self._rb_at = self._svc.now().isoformat(timespec="seconds")
            return answer, False, None, stat

    def _aiff_batches(self) -> list[AiffBatchRow]:
        """The newest AIFF batches, newest first: where a stopped one is looked for (`views.stopped_batch`: Upgrade
        ready's, the CDJ group's and the Library header's "Resume · k left")."""
        with self._move_log() as conn:
            if conn is None:
                return []
            return db.aiff_batches(conn, 20)[0]

    def _tags(self, file: Path) -> audio.FileFacts:
        """`audio.file_facts` of a file, remembered by (path, size, mtime_ns) so that reopening the panel reads no file
        again (plan stage D §0.7). A file that can't be read raises as `file_facts` does and is not remembered."""
        stat = file.stat()
        key = (str(file), stat.st_size, stat.st_mtime_ns)
        with self._lock:
            found = self._tag_cache.get(key)
        if found is not None:
            return found
        found = audio.file_facts(file)
        with self._lock:
            if len(self._tag_cache) >= TAG_CACHE_MAX:
                self._tag_cache.clear()
            self._tag_cache[key] = found
        return found

    def _decided_now(self, state: dict, prep: run.Prepared | None) -> set[str]:
        """`views.decided_songs` for the records and the import's last plan as they are now: the songs the `cdj` scope
        leaves out (a Convert all and the plan read ask; To-do computes its own from what it has read). `prep`: the plan
        the caller asked."""
        questions = list(prep.plan.questions) if prep else []
        groups = list(prep.plan.duplicates) if prep else []
        files: dict[str, list] = {}
        with self._move_log() as conn:
            if conn is not None:
                groups += db.duplicate_groups(conn)
                files = {g.id: db.group_files(conn, g.id) for g in groups}
        return views.decided_songs(state, questions, groups, files, (), self._away_roots(), {})

    def _planned(self, state: dict, scope: dict, only: str | None = None, *, in_job: bool = False,
                 held: Collection[str] | None = None) -> plans.AiffPlan:
        """`_planned_read`'s plan."""
        return self._planned_read(state, scope, only, in_job=in_job, held=held)[0]

    def _planned_read(self, state: dict, scope: dict, only: str | None = None, *, in_job: bool = False,
                      held: Collection[str] | None = None, running: bool | None = None
                      ) -> tuple[plans.AiffPlan, bool]:
        """`aiff_plan.read_plan` for `scope` with one read open of rekordbox's library (the lookup of its tracks), and
        whether it was made blind. A read asked while a writer holds `rekordbox.lock` (any Discjockey process) takes
        rekordbox's cached state and no lookup instead (as `_rekordbox_status`); a job plans for itself (`in_job`,
        after its recovery, holding no reader lock: its own session takes the writer's). The `cdj` scope leaves out
        `held` (`_decided_now` when not given: what To-do shows as a question or a duplicate). `running`: whether rekordbox
        runs, when the caller has asked already for this read answer (a job's plan, `in_job`, always asks for itself)."""
        if held is None:
            held = self._decided_now(state, self._plan()) if scope.get("kind") == "cdj" else ()
        if in_job:
            return plans.read_plan(self._paths, state, scope, place=self._svc.rekordbox_place(),
                                   running=bool(self._svc.rekordbox_running()), only=only, tags=self._tags,
                                   held=held), False
        with contextlib.ExitStack() as hold:
            if hold.enter_context(rb_lock.reader_lock(self._support.support)):
                # the shared hold ends once master.db is closed (the lookups are done), not after the tag reads
                return plans.read_plan(self._paths, state, scope, place=self._svc.rekordbox_place(),
                                       running=bool(self._svc.rekordbox_running()) if running is None else running,
                                       only=only, tags=self._tags,
                                       held=held, released=hold.close), False
        return plans.plan(self._paths, state, scope, rb=self._rekordbox_status(running), entries=None, tags=self._tags,
                          only=only, held=held), True

    def _planned_reading(self, state: dict, scope: dict, only: str | None = None) -> plans.AiffPlan:
        """`_planned_reading_blind`'s plan."""
        return self._planned_reading_blind(state, scope, only)[0]

    def _planned_reading_blind(self, state: dict, scope: dict, only: str | None = None) -> tuple[plans.AiffPlan, bool]:
        """`_planned` for a read (the panel, a dry run, the plan a run binds): the facts of the scope's own files that
        have none stored are read in memory (`aiff_plan.with_facts`), none is stored. `FactsMissing` for more than a
        read takes (the command line's; the window plans on the facts stored). Also whether the plan was made blind (a
        writer held `rekordbox.lock`: rekordbox's cached state and no lookup of its tracks)."""
        held = self._decided_now(state, self._plan()) if scope.get("kind") == "cdj" else ()
        try:
            state = plans.with_facts(self._paths, state, scope, probe=self._svc.probe, held=held)
        except plans.FactsMissing:
            if self._via == "terminal":
                raise
            # the window has no action that reads facts: it plans on what is stored (files without facts left out)
        return self._planned_read(state, scope, only, held=held)

    def _aiff_scope(self, scope: object, kinds: Sequence[str] = plans.SCOPE_KINDS) -> dict:
        """A scope from the page as `aiff_plan.plan` takes it, or ValueError: `{kind: "tracks", tracks}`, `{kind:
        "lossless", view, key}` or `{kind: "cdj"}` (only those in `kinds`)."""
        kind = scope.get("kind") if isinstance(scope, dict) else None
        if kind not in kinds:
            raise ValueError(BAD_AIFF_SCOPE)
        if kind == "tracks":
            return {"kind": "tracks", "tracks": self._track_list(scope.get("tracks"))}
        if kind == "cdj":
            return {"kind": "cdj"}
        view, key = scope.get("view", "all"), scope.get("key")
        if view not in views.LIBRARY_VIEWS or (view in ("playlist", "folder") and not (isinstance(key, str) and key)):
            raise ValueError(BAD_AIFF_SCOPE)
        return {"kind": "lossless", "view": view, "key": key if view in ("playlist", "folder") else None}

    # --- read, any time ---

    @bridge
    def dashboard(self) -> dict:
        return self._dashboard_view()

    def _dashboard_view(self) -> dict:
        """The Dashboard's answer: the window's `dashboard` and the command line's `status` both carry it."""
        return views.dashboard(self._shown_state(), self._settings(), self._read_view(), self._reports(), self._folders(),
                               setup_status(self._support, self._paths, self._music_status(), self._svc.which),
                               self._today(), self._svc.now(),
                               self._reading(), self._logins())

    @bridge
    def sidebar(self) -> dict:
        return self._sidebar_view()

    @bridge
    def rekordbox_status(self) -> dict:
        """rekordbox on this Mac, now (issue 33 stage C): `{state: "ready" | "none" | "unreadable", running, problem,
        version, library, db_version, modified_at, size}` and the words `state_text` and `problem_text`. `problem` is what
        is wrong with a library (`unclean` | `busy` | `key` | `db_version` | `schema`), `version` rekordbox's own, `library`
        the path of master.db, `modified_at` (local ISO time) and `size` master.db's own, so "master.db was not touched
        meanwhile" can be checked; each is null where unknown (no library; or a writer holds the lock and nothing was read
        yet). The state is the cached answer of `_rekordbox_status` (one read open per change of master.db; while a writer
        of any Discjockey process holds `rekordbox.lock` it answers its last value with `writing: true` and `as_of`, the
        time that value was read), `running` is asked every time: the Sync page reads it when it opens and when the window
        gets focus again, to say that rekordbox must be quit before a start. Works without a music folder."""
        status, writing, as_of, stat = self._rekordbox_read()
        state_text, problem_text = rekordbox_words(status.state, status.problem)
        return {"state": status.state, "running": status.running, "state_text": state_text, "problem": status.problem,
                "problem_text": problem_text, "version": status.version, "library": status.library,
                "db_version": status.db_version,
                "modified_at": datetime.fromtimestamp(stat[0] / 1e9).isoformat(timespec="seconds") if stat else None,
                "size": stat[1] if stat else None,
                **({"writing": True, "as_of": as_of} if writing else {})}

    def _sidebar_view(self, also: Sequence[str] = ()) -> dict:
        """The sidebar's numbers; `also`: Favourites keys to resolve besides the stored ones (set_favourites asks
        which of the keys it is given exist right now)."""
        state = self._shown_state()
        count = self._todo(state, None, False, count_only=True)["chips"]["all"]
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
    def sync_preview(self, search: str = "") -> dict:
        """The plan as the Sync page shows it. `search` (the command line's `--search`; the window sends none) narrows
        the actions of `groups` to the songs the Library's search finds by that artist and title (`views.matches_search`),
        a group left with none is left out, and `search` says the words. Everything else, the counts, the estimate, the
        presets, `never`, `ambiguous`, `dropped` and `plan_id`, stays the whole plan's: a search only picks what to look at."""
        return self._sync_preview_view(search)

    def _sync_preview_view(self, search: str = "") -> dict:
        """`sync_preview`'s answer, for the bridge method and for `start_sync` (which plans on it): it stores the plan
        it shows (`_store_sync_plan`), `plan_id` None while nothing was read."""
        state = self._state()
        with self._move_log() as conn:
            folders, overrides = (db.watched_folders(conn), db.crate_overrides(conn)) if conn is not None else ([], {})
        lines = pf.load(self._paths.playlists_file).rows
        where = views.sites(state, lines, folders).place
        read = self._read_view(strict=True)  # a refused settings.json is the answer here, not an empty preview
        running = bool(self._svc.rekordbox_running())  # once for the whole answer: it is a `ps` of ~40 ms
        answer = views.sync_preview(read, state, self._settings(), self._today(), self._svc.now(),
                                    self._reading(), self._cover(self._images(read.prep)), self._logins(), where,
                                    views.song_places(state, lines, folders, overrides),
                                    self._auto_upgrade_ready(state, read.prep, running))
        if read.prep is not None:
            answer["plan_id"] = self._store_sync_plan(answer, state.get("generation"))
        if words := views.search_query(search):
            groups = [{**g, "actions": [a for a in g["actions"] if views.matches_search(words, a["artist"], a["title"])]}
                      for g in answer["groups"]]
            answer["groups"] = [g for g in groups if g["actions"]]
            answer["search"] = search.strip()
        return answer

    def _store_sync_plan(self, preview: dict, generation: int | None) -> str:
        """Stores the plan a Sync preview answers (design §7.1, §9.2) where every process finds it, and returns its id:
        the actions the preview groups, by their ids, as `(kind, track_id, to_dir)`, with the read and the records'
        generation it was derived from. A preview is asked for on every data change, so the plan is saved when its id
        is another than the last one this window saved, its actions' targets differ from that save's (the id is a hash
        of the action ids only), or that save is over an hour old (a plan is good for 24 hours from its last save). A
        save that fails (the support folder can't be written) is the preview's problem."""
        items = {a["id"]: {"kind": a["kind"], "track_id": a["track_id"], "to_dir": a["to_dir"]}
                 for g in preview["groups"] for a in g["actions"]}
        root = self._plan_root()
        identifier = plan_store.plan_id(SYNC_PLAN, root, list(items))
        now = datetime.now()  # as plan_store reads the clock: it is the plan's own 24 hours
        with self._lock:
            last = self._saved_plan
        if last is None or last[0] != identifier or last[1] != items or now - last[2] > PLAN_RESAVE:
            plan_store.save(self._support.support, SYNC_PLAN, root, items,
                            {"read_id": preview["read_id"], "generation": generation, "command": "sync run"}, now=now)
            with self._lock:
                self._saved_plan = (identifier, items, now)
        return identifier

    @bridge
    def refresh(self, auto: bool = False) -> dict:
        """auto: the hub's own read (when it opens, or the Sync page when it opens first). Only one per session
        starts, whatever its outcome; later ones are refused, so a stopped or failed read is never redone by itself."""
        with self._auto_lock:
            if auto and self._store.auto_read:
                raise OpProblem(AUTO_READ_DONE, "refused")
            read = refresh_work(self._paths, self._svc.now, infos={},
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
        user stopped one (it stays stopped in library.db, for every window and process) or something else is writing (the
        import then waits for Continue import or the next window). Only the window's own first read gets here, never a
        Sync page's ↻ Read playlists."""
        if self._import_auto_done:
            return
        try:
            if self._import_stopped_at() is not None:
                return
            if importer.files_waiting(self._paths) > 0:
                self._start_import()
            self._import_auto_done = True
        except (Busy, NoLibrary, StateError):
            return
        except Exception:  # noqa: BLE001 - a failed start is never worth ending the read that called it
            log.warning("starting the import by itself failed", exc_info=True)

    def _start_import(self, folder: Path | str | None = None):
        """The import as a write job (Busy when another job or a terminal run holds the library)."""
        stopped = self._import_stopped_at()
        if stopped is not None:  # cleared before it starts: it may be stopped at once
            self._store_import_stopped(None)
        try:
            return self._jobs.start("import", import_work(self._paths, self._plan, self._svc.now, folder=folder,
                                                          on_stopped=self._note_stopped))
        except BaseException:
            if stopped is not None:  # a start that failed leaves the stop as it was
                try:
                    self._store_import_stopped(datetime.fromisoformat(stopped))
                except Exception:  # noqa: BLE001 - the start's own error is the one to show
                    log.warning("could not put back that the import was stopped", exc_info=True)
            raise

    def _import_stopped_at(self) -> str | None:
        """When the user stopped the import (library.db's `import_state`), None while none is stopped or there is no
        library.db yet."""
        if not self._paths.db_file.exists():
            return None
        with self._move_log() as conn:
            return db.import_stopped_at(conn)

    def _store_import_stopped(self, at: datetime | None) -> None:
        if self._paths.db_file.exists():  # no records yet: nothing could have been stopped, nothing to clear
            self._brief_write(lambda conn: db.set_import_stopped(conn, at))

    def _note_stopped(self) -> None:
        """The import job was stopped: remembered in library.db so the window and every other process know (D14). A
        write that can't be made must not replace the job's own `stopped` ending: it is logged, and the import then
        starts by itself again at the next window."""
        try:
            self._store_import_stopped(self._svc.now())
        except Exception:  # noqa: BLE001
            log.warning("could not note that the import was stopped", exc_info=True)

    @bridge
    def stop_refresh(self) -> dict:
        return {"stopped": self._jobs.stop_refresh()}

    @bridge
    def job_status(self) -> dict:
        read = self._read_view(plan=False)  # the head only: this runs on every window refresh, no plan is derived
        return {**self._jobs.status(), "read_status": views.read_status(read, self._svc.now(), self._reading(),
                                                                           self._logins()),
                "last_sync": self._last_sync()}

    @bridge
    def job_events(self, job_id: str, after: int = 0) -> dict:
        """The events of any job of this support folder (the window's own, the Terminal's) from position `after` on, at
        most `JOB_EVENTS_PAGE` lines, as `job follow --jsonl` reads them: `events.jsonl`, then the rolling tail.
        Positions count the lines of the files (a line that does not parse is skipped from `events` but has its place),
        so `next` is the `after` of the following call. The window sends only 0 or the `next` it was given: the reader
        that delivered up to there is kept (`_FollowReader`) and reads on; any other `after` starts a fresh one. Once
        `done`, `finished` is the job's end as the window's `JobFinished` (from its `result.json`, `jobs.finished_of`;
        `worker_lost` when it left none), so a follower need not find it among the lines: the file has none when the
        worker died, and may hold another job's (a retry's) before the last."""
        files = registry.Registry(self._support.support).get(job_id)
        state = files.state()
        status = state.get("status")  # before the lines: an ended job's last events are in them
        after = max(0, int(after))
        with self._events_lock:
            follow = self._event_readers.pop(job_id, None)
            if follow is None or follow.count != after:
                follow = _FollowReader(registry.EventReader(files.dir), after)
            lines = follow.take(JOB_EVENTS_PAGE)
            self._event_readers[job_id] = follow  # now the most recent
            while len(self._event_readers) > JOB_EVENTS_READERS:
                self._event_readers.popitem(last=False)
            next_ = follow.count
        events = []
        for line in lines:
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if isinstance(data, dict):
                events.append(data)
        done = status in ("done", "lost") and len(lines) < JOB_EVENTS_PAGE
        return {"events": events, "next": next_, "status": status, "done": done,
                "finished": event_dict(finished_of(job_id, state.get("kind") or "", files)) if done else None}

    def _last_sync(self) -> dict | None:
        """The newest sync of this music folder in the registry (any `via`: the window's or the terminal's, a queued one
        of the terminal included: its kind is still its method name `start_sync`), as `{job,
        args: {plan_id, selected}, ended}`: what the run list shows after a reload and `job show` says of what was
        ticked. Null with no sync, no library, or no registry. The recorded args are read defensively (an older or
        hand-made record has none): a plan id that is no string is None, `selected` keeps its strings."""
        registry_ = self._jobs.registry
        if registry_ is None or self._bound is None:
            return None
        state = next((s for s in registry_.list(self._bound.root)
                      if s.get("kind") == "sync" or s.get("method") == "start_sync"), None)  # a queued Terminal one: its method
        if state is None:
            return None
        args = state.get("args") if isinstance(state.get("args"), dict) else {}
        plan_id, selected = args.get("plan_id"), args.get("selected")
        return {"job": state.get("id"),
                "args": {"plan_id": plan_id if isinstance(plan_id, str) else None,
                         "selected": [i for i in selected if isinstance(i, str)] if isinstance(selected, list) else []},
                "ended": state.get("ended")}

    @bridge
    def library(self, view: str = "all", key: str | None = None, query: str = "", filter: str = "all",
                sort: str | None = None) -> dict:
        """One view of the library (views.library): view "all" | "unlisted" | "playlist" | "folder"; key the playlist's
        folder name or the folder's path for the last two; sort None = the view's own order. An unknown playlist or
        folder is not an error: the answer says `empty: "gone"`."""
        state = self._state()
        return self._library_view(state, view, key, query, filter, sort)

    def _library_view(self, state: dict, view: str, key: str | None, query: str, filter: str, sort: str | None) -> dict:
        """`library`'s answer for `state` (the arguments are checked here): what the window shows and `select_listing`
        reads its ids from."""
        if view not in views.LIBRARY_VIEWS:
            raise ValueError(f"view must be one of {', '.join(views.LIBRARY_VIEWS)}")
        if view in ("playlist", "folder") and not key:
            raise ValueError(f"a {view} view needs its key")
        if filter not in views.LIBRARY_FILTERS:
            raise ValueError(f"filter must be one of {', '.join(views.LIBRARY_FILTERS)}")
        records, folders = self._records_and_folders()
        prep = self._plan()
        return views.library(state, view, key, query, filter, sort, self._cover(self._images(prep)),
                             self._away_by_root(folders), lines=pf.load(self._paths.playlists_file).rows,
                             records=records, watched=folders, fetched=prep.fetched if prep else [],
                             planned={k: t["aliases"] for k, t in (prep.state["tracks"] if prep else {}).items()
                                      if t.get("aliases")},
                             aiff_stopped=views.stopped_batch(self._aiff_batches(), scope="library:"))

    @bridge
    def track(self, track_id: str) -> dict:
        state = self._state()
        e = self._entry(state, track_id)
        prep = self._plan()
        if prep is not None:  # the aliases the last read's linking added (a Qobuz track linked to this song) count too
            planned = (prep.state["tracks"].get(track_id) or {}).get("aliases") or []
            e = {**e, "aliases": list(dict.fromkeys([*(e.get("aliases") or []), *planned]))}
        # whether the file is at its path: asked for this one track only, since the last scan may be old
        exists = not e.get("path") or (self._paths.root / e["path"]).exists()
        with self._move_log() as conn:
            folders = db.watched_folders(conn) if conn is not None else []
        lines = pf.load(self._paths.playlists_file).rows
        place_of = views.sites(state, lines, folders).place
        where = place_of(e["path"]) if e.get("path") else None
        rb = self._rekordbox_status()
        detail = views.track_detail(track_id, e, prep.fetched if prep else [], self._today(),
                                    self._cover(self._images(prep)), self._audio, self._away_by_root(folders), exists, where,
                                    rb, self._auto_upgrade_on(), state, place_of)
        # what Convert and Rename would do for this file (null: no file, a download, a better version waiting)
        detail["aiff"] = plans.file_answer(self._paths, state, track_id, rb=rb, tags=self._tags) if exists else None
        return {"track": detail}

    @bridge
    def aiff_plan(self, scope: dict, only: str | None = None) -> dict:
        """What Make all lossless files AIFF, a selection's Convert or the CDJ group's Convert all would do (`{plan:
        AiffPlan}`, aiff_plan.AiffPlan.to_dict): `scope` `{kind: "tracks", tracks: [key, …]}`, `{kind: "lossless", view,
        key}` or `{kind: "cdj"}`. One read, off the window's thread like `spectrum` (pywebview gives every call its own);
        the tags of the files that need them are remembered, so reopening the panel is quick. The run plans again. Own
        files whose facts are not stored yet (a library from before the facts were kept) are read in memory, never
        stored (`aiff_plan.with_facts`): up to 50; with more the command line's answer is `refused` (`facts_missing`,
        `next: library facts`) and the window's plans on the stored facts alone (files without facts left out). `only`
        `"rename"` (the command line's `aiff rename --dry-run`) plans Rename's answer alone, as `rename` runs it: a file that needs a Convert is left as it is. While a writer of any
        Discjockey process holds `rekordbox.lock` master.db is not opened: the plan takes rekordbox's cached state and no lookup, and its
        `rekordbox` part says `writing: true`."""
        if only not in (None, "rename"):
            raise ValueError(BAD_AIFF_ONLY)
        plan, blind = self._planned_reading_blind(self._state(), self._aiff_scope(scope), only)
        answer = plan.to_dict()
        if blind:
            answer["rekordbox"] = {**answer["rekordbox"], "writing": True}
        return {"plan": answer}

    @bridge
    def todo(self, filter: str | list[str] = "all", show_hidden: bool = False) -> dict:
        """The To-do page's groups. `filter`: one group key, `all`, or a list of keys (each text may hold several,
        comma-separated); the groups come in the window's order whatever order they were named in."""
        texts = [filter] if isinstance(filter, str) or filter is None else filter
        keys = [word.strip() for text in texts for word in (text or "").split(",") if word.strip()]
        for key in keys:
            if key != "all" and key not in views.TODO_GROUP_KEYS:
                raise BadId("usage", f"There is no to-do group called {key}. The groups are "
                                          f"{', '.join(views.TODO_GROUP_KEYS)}.")
        state = self._state()
        return self._todo(state, None if not keys or "all" in keys else keys, bool(show_hidden))

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
        it couldn't read, how many wait, and whether the user stopped the import (kept in library.db until Continue import; plan library stage 4
        I11)."""
        paths = self._paths
        state = self._state()
        job = self._jobs.running()
        phase = None
        if job is not None and job.kind == "import":
            phase = (job.last.get("ImportProgress") or {}).get("phase", "scan")
        with self._move_log() as conn:
            stopped = False
            if conn is None:  # no library.db yet: only the Library, nothing imported; its files as "All tracks" counts
                rows, counts, unreadable, waiting, overrides = [WatchedFolder(0, paths.library, "library")], {}, [], 0, {}
            else:
                stopped = db.import_stopped_at(conn) is not None
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
                                     waiting, stopped, phase, crates)

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
        return views.limits(self._service(service), self._shown_state(), self._settings(), self._plan(), self._today())

    @bridge
    def limits_what_if(self, service: str, limit: int, extra_today: int = 0) -> dict:
        service, limit, extra_today = self._service(service, set_up=True), int(limit), int(extra_today)
        if not 1 <= limit <= MAX_DAILY_LIMIT or not 0 <= extra_today <= MAX_EXTRA:
            raise ValueError(f"The daily limit goes from 1 to {MAX_DAILY_LIMIT}, the extra for today from 0 to "
                             f"{MAX_EXTRA}.")
        return views.limits_what_if(service, limit, extra_today, self._shown_state(), self._settings(), self._plan(),
                                    self._today())

    @bridge
    def runs(self, since: str | None = None) -> dict:
        """The runs, newest first. `since` (an ISO time; the command line's `--since` resolves to one) keeps the runs
        that started at or after it; the window sends none."""
        return {"runs": [r for r in views.runs(self._reports()) if since_mod.after(r["started"], since)]}

    @bridge
    def run(self, run_id: str) -> dict:
        """One run's end screen. `run_id` is the report's stamp; the command line also says `report:<stamp>` or `last`
        (the newest report)."""
        reports = dict(self._reports())
        text = run_id[len("report:"):] if isinstance(run_id, str) and run_id.startswith("report:") else run_id
        if text == "last":
            if not reports:
                raise OpProblem("There is no run report yet.", "refused")
            text = max(reports)
        found = reports.get(text) if isinstance(text, str) and RUN_ID.fullmatch(text) else None
        if found is None:
            raise OpProblem("That run report is not there any more.", "refused")
        run_id = text
        return {"run": views.run_detail(run_id, found, self._state(), cover=self._cover(self._images(self._plan())),
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
    def setup_status(self) -> dict:
        return setup_status(self._support, self._bound, self._music_status(), self._svc.which, self._svc.home)

    @bridge
    def downloads_view(self) -> dict:
        """The source ladder and the account panels (Settings, Setup): each source's state and the library by rung.
        Without a music folder the library counts are zero."""
        return {"downloads": self._downloads()}

    def _downloads(self, records: bool = True) -> dict:
        """`views.downloads` for the settings as they are now (`downloads_view`'s answer and `doctor`'s read).
        `records` False: counted on an empty library, for `doctor` while library.db cannot be read."""
        settings = self._settings()
        names = {s: profile_name(a.browser, a.profile, self._svc.home) for s, a in settings.accounts.items()}
        qobuz_ok = setup_status(self._support, self._bound, self._music_status(), self._svc.which)["qobuz"]
        state = self._shown_state() if self._bound is not None and records else library.empty_state()
        return views.downloads(state, settings, qobuz_ok, names, self._today())

    # --- other ---

    @bridge
    def show_in_finder(self, track_id: str, which: str = "current", print_only: bool = False) -> dict:
        return self._opened(self._svc.reveal, self._paths.root / self._file_of(track_id, which), print_only)

    @bridge
    def reveal(self, rel_path: str, print_only: bool = False) -> dict:
        """Shows a place in Finder: a path inside the music folder (relative), or an absolute path inside a watched
        import folder (the folder itself, a crate): only places the library knows, never any path the page names."""
        place = self._watched_place(rel_path) if str(rel_path).startswith("/") else self._inside_root(rel_path)
        return self._opened(self._svc.reveal, place, print_only)

    @staticmethod
    def _opened(opener: Callable[..., object], target: Path | str, print_only: bool) -> dict:
        """What the openers answer (`Opened`): the place or web address, whether it was opened, and `text` that says so.
        Every check ran before this; `print_only` (the command line's `--print`) opens nothing."""
        if not print_only:
            opener(target)
        say = engine_words.NOT_OPENED if print_only else engine_words.OPENED
        return {"target": str(target), "opened": not print_only, "text": say.format(target=target)}

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
    def open_report(self, run_id: str, print_only: bool = False) -> dict:
        """A run's report (`run_id`, the stamp) in its app, or the buy list (`not-lossless`, `.discjockey/not_lossless.md`)."""
        if run_id == "not-lossless":
            if not self._paths.not_lossless_md.is_file():
                raise OpProblem(engine_words.NO_BUY_LIST, "refused")
            return self._opened(self._svc.open_path, self._paths.not_lossless_md, print_only)
        if not RUN_ID.fullmatch(run_id or ""):
            raise ValueError("That is not a run report.")
        return self._opened(self._svc.open_path, self._inside_root(f"{library.DATA_DIR}/reports/{run_id}.md"), print_only)

    @bridge
    def open_licenses(self, print_only: bool = False) -> dict:
        """Settings -> About: the licences of everything Discjockey bundles, in Finder (spec public-release §6.5)."""
        folder = tools.licenses_dir()
        if not folder.is_dir():
            raise OpProblem("The licences folder is missing from this copy of Discjockey.", "refused")
        return self._opened(self._svc.open_path, folder, print_only)

    @bridge
    def open_external(self, url: str, print_only: bool = False) -> dict:
        """Websites open in the system browser, never inside the hub window."""
        if not re.fullmatch(r"https?://[^\s]+", url or ""):
            raise ValueError("Only web links (http:// or https://) can be opened.")
        return self._opened(self._svc.open_url, url, print_only)

    @bridge
    def app_update(self, check: bool = False) -> dict:
        """Is a newer Discjockey out (spec public-release §8)? {state: available | up_to_date | unknown, current, latest,
        url, ran_check, checked_at, message}. Without `check` never the network: the window's check keeps the answer in
        memory, and a process that runs none (the command line) reads the cache while it is a day old at most. With `check`
        this call ran the update check (`Checker.check`: GitHub only when the cache is a day old or missing, never for a
        developer's version): `ran_check` says so, `checked_at` is when the last answer was fetched (null: never), and a
        check that ends `unknown` says why in `message` (a developer's version asked nobody; else GitHub gave no answer).
        Works without a music folder."""
        if check:
            self._update.check()
        else:
            self._update.load_cache()
        status = self._update.status()
        message = None
        if check and status["state"] == "unknown":
            message = engine_words.UPDATE_NO_ANSWER_DEV if self._update.developer_version else engine_words.UPDATE_NO_ANSWER_OFFLINE
        return {**status, "ran_check": bool(check), "checked_at": self._update.cached_at(), "message": message}

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
        """Searches and previews would send requests next to a paced sync of this support folder (this window's, a
        terminal's or the console's): `Jobs.sync_running`."""
        if self._jobs.sync_running():
            raise Busy(SYNC_RUNNING, "sync_running")

    def _spotify_track(self, track_id: str, e: dict) -> SourceTrack:
        prep = self._plan()
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
        """Today's Qobuz budget (it carries the stored failure streak: a Qobuz that failed three times in a row, in any
        process, stays paused until the next sync starts)."""
        return Budget(state, lambda: library.save_state(self._paths, state), self._settings())

    def _account_budgets(self, state: dict) -> dict[str, Budget]:
        """Today's budget of each account that is set up (a paused account stays paused until the next sync)."""
        return run.account_budgets(state, lambda: library.save_state(self._paths, state), self._settings())

    def _single(self, kind: str, track_id: str, do, expect: str | None = None) -> dict:
        """A single operation as a write job (spec 6.7): recovery first, precondition (the record's `rev` is `expect`,
        when one is given), the change, not_lossless.md and the operations log."""
        def work(ctx) -> dict:
            done = ops.run_single(self._paths, kind, track_id, expect, lambda state: do(state, ctx),
                                  now=self._svc.now)
            return {"track_id": track_id, "result": asdict(done.result),
                    "recovered": [[message, ok] for message, ok in done.recovered]}

        return {"job_id": self._jobs.start(kind, work, track_id=track_id).id}

    def _replace_with(self, track_id: str, find: Callable, expect: str | None = None) -> dict:
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
                pacer = self._svc.pacer(self._paths.support, ctx.emit, ctx.token)
                if find.needs_qobuz and find.cand is None and qobuz is not None:
                    pacer.before_qobuz_search()  # a pasted Qobuz link: its track lookup is a Qobuz request
                cand = find(qobuz, fallback)
                return ops.use_candidate(self._paths, state, track_id, cand, qobuz=qobuz, fallback=fallback,
                                         budget=budget, track=self._spotify_track(track_id, e), emit=ctx.emit,
                                         token=ctx.token, process=self._svc.process, accounts=accounts,
                                         now=self._svc.now, pacer=pacer)
            finally:
                if qobuz is not None:
                    qobuz.close()
        return self._single(find.kind, track_id, do, expect)

    def _on_drop(self, event: dict) -> None:
        """pywebview's drop handler on the page (app.py): tells the page which file was dropped, remembering nothing
        (the page passes the path back in `add_bought_file`). Runs on a thread of its own; never raises."""
        try:
            files = (event.get("dataTransfer") or {}).get("files") or []
            found = next((f for f in files if f.get("pywebviewFullPath")), None)
            if found is None:
                self._emit(FileDropped("", None, False, "Discjockey could not see where this file is. Drag it "
                                                        "from a Finder window."))
                return
            path = Path(found["pywebviewFullPath"])
            problem = _file_problem(path)
            self._emit(FileDropped(path.name, str(path), problem is None, problem or ""))
        except Exception:
            traceback.print_exc()

    # --- playlists (playlists.txt stays the source of truth) ---

    def _clear_read_problem(self, service: str, kinds: frozenset[str] | None = None, message: str | None = None) -> None:
        """A login for `service` was just made: the stored read's problem about it is out of date
        (`db.clear_read_problem`), so every process stops showing it."""
        if self._bound is not None:
            run.clear_read_problem(self._bound, service, kinds, message)

    def _stored_playlists(self) -> tuple[dict, dict]:
        """(every stored record's tracks by playlist ref, every stored playlist info by ref): what the reads found,
        the Sync page's and the Playlists page's own (library.db; empty before there is one)."""
        with self._move_log() as conn:
            return (db.stored_tracks(conn), db.stored_infos(conn)) if conn is not None else ({}, {})

    def _tracks_by_id(self) -> dict:
        return self._stored_playlists()[0]

    def _store_check(self, fetched: models.FetchedPlaylist, started: datetime) -> None:
        """Keeps the tracks of one playlist read for the Playlists page (a pasted link, an edited line) as a check
        read: it never prunes, and a newer read of the same playlist is kept over it."""
        run.store_read(self._paths, models.StoredRead("check", started, [fetched]), keep=None)

    @bridge
    def playlists(self) -> dict:
        tracks, infos = self._stored_playlists()
        return views.playlists(pf.load(self._paths.playlists_file), tracks, infos,
                               self._state(), self._cover(self._images(self._plan())),
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
            self._need_liked_music()
        reader = source.open(self._support, CancelToken())
        signs: list[tuple[str, str, str]] = []
        reader.on_signal = lambda *sign: signs.append(sign)
        reader.paused = self._paused_accounts()  # the reader refuses Liked music while paused (D6)
        started = datetime.now()  # the clock the stored reads' order is by (run.prepare stamps its reads the same way)
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
            run.store_infos(self._paths, {ref: info}, self._svc.now())
            if fetched is None and info.readable:
                fetched = reader.fetch(PlaylistLine(suggest_folder(info.name), pid, 0, service))
            if fetched is not None:
                self._store_check(fetched, started)
                tracks = len(fetched.tracks)
        finally:
            self._close(reader)
            self._record_signs(signs)  # a bot check met by the Liked music read: the account's warning sign
        return {"playlist_id": ref, "service": service, "service_name": PLAYLIST_SERVICES[service], "link": link,
                "info": views.info_dict(info), "tracks": tracks, "readable": info.readable,
                "suggested_folder": suggest_folder(info.name),
                "hint": None if info.readable else source.UNREADABLE_HINT}

    @bridge
    def preview_playlist_change(self, lines: list | None = None, op: PlaylistOp | None = None,
                                read_unread: bool = False) -> dict:
        """"What this change does": the pure planner on the last playlists read, for edited (unsaved) `lines` or, with
        `lines` None, for the file's rows now; with `op` (one change, `PlaylistOp`) the rows after that change. No file
        changes. Only with `read_unread` (the window) a switched-on line not read yet is read once and stored, and a
        running sync refuses the preview; without it nothing goes to the network, library.db is not written, and the
        lines not read yet are named in `unknown` and `next`. The answer is `_change_answer`'s."""
        if read_unread:
            self._no_sync_running()
        loaded = pf.load(self._paths.playlists_file)
        base = loaded.rows if lines is None else rows_from(lines)
        rows = base if op is None else pf.apply(base, self._op(op, base))
        if read_unread:
            self._read_unread(rows)
        return self._change_answer(loaded.rows, rows, loaded.version)

    def _read_unread(self, rows: list[pf.Row]) -> None:
        """Reads once each switched-on playlist of `rows` the stored reads don't hold (one reader per service; a service
        that is not connected, a playlist it won't show and your SoundCloud likes are skipped) and stores what it found."""
        tracks = self._tracks_by_id()
        unread = [r for r in rows if r.enabled and r.ref not in tracks]
        paused = self._paused_accounts()
        signs: list[tuple[str, str, str]] = []
        try:
            for service in dict.fromkeys(r.service for r in unread):
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
                            started = datetime.now()  # before the fetch: reads are ordered by when they started
                            self._store_check(reader.fetch(PlaylistLine("x", found[1], 0, service)), started)
                        except sources.SourceError:
                            continue
                finally:
                    self._close(reader)
        finally:
            self._record_signs(signs)

    def _change_answer(self, old: list[pf.Row], rows: list[pf.Row], version: str) -> dict:
        """The answer of a change preview (`ChangePreview`), also what a save that needs a choice hands back: what the
        change from `old` (the file's rows, whose `version` it is) to `rows` does to the library on the last playlists
        read, with `problem` (what would make the save refuse), `lines` (the rows after the change) and, when a line's
        playlist is not read yet, `next`: the command that reads it."""
        tracks = self._tracks_by_id()
        problem = None
        try:
            pf.validate(rows)
        except config.ConfigError as e:
            problem = str(e)
        state = self._state()
        money = views.gate(views.moneys(state, self._settings(), self._today()))
        change = views.playlist_change(old, rows, tracks, state, state["files"], self._today(), money,
                                       self._cover(self._images(self._plan())), library_dirs=tidy.library_dirs(self._paths),
                                       rename_offer=tidy.rename_offer, placement=pf.placement(rows, tracks, state),
                                       retargeted=pf.retargeted(old, rows, tracks, state))
        answer = {**change, "problem": problem, "version": version,
                  "lines": [{"folder": r.folder, "link": r.link, "enabled": r.enabled} for r in rows]}
        if change["unknown"]:
            link_of: dict[str, str] = {}
            for r in rows:
                link_of.setdefault(r.ref, r.link)
            answer["next"] = [{"run": shlex.join(["playlist", "check", link_of[ref]]), "why": playlist_words.PLAYLIST_CHECK_COUNT_WHY}
                              for ref in dict.fromkeys(change["unknown"])]
        return answer

    def _need_liked_music(self) -> None:
        """Liked music is read through the YouTube login, so it is a choice in Settings (D9): `setting_off` while it is off."""
        if not self._settings().reads_liked_music:
            raise sources.SourceError(youtube_music.SETTING_OFF, "setting_off", youtube_music.SERVICE, youtube_music.SETTING)

    def _op(self, op: object, rows: list[pf.Row]) -> dict:
        """The change `op` made ready to apply to `rows`: checked, and for an add its folder filled (the suggested one of
        the playlist's stored read) and the refusals that need Settings, the library or the stored reads said before any
        job starts. Pure of the network: a link that names no playlist before it is opened is told to `playlist check`."""
        checked = pf.check_op(op)
        if checked["op"] != "add":
            return checked
        url = checked["url"]
        try:
            link = pf.clean_link(url)
        except ValueError:  # a short link names no playlist until it is opened, and a preview opens nothing
            raise BadId("usage", playlist_words.PLAYLIST_ADD_LINK,
                        next=[{"run": shlex.join(["playlist", "check", url]), "why": playlist_words.PLAYLIST_CHECK_LINK_WHY}]) from None
        if pf.listed(rows, link) is not None:
            raise ValueError(playlist_words.PLAYLIST_LISTED)
        ref = token(*sources.recognise(link))
        if ref == pf.LIKED_MUSIC_REF:
            self._need_liked_music()
        if "folder" in checked:
            return checked
        info = self._stored_playlists()[1].get(ref)
        if info is None:
            raise BadId("usage", playlist_words.PLAYLIST_ADD_NEEDS_FOLDER,
                        next=[{"run": shlex.join(["playlist", "check", url]), "why": playlist_words.PLAYLIST_CHECK_NAME_WHY}])
        return {**checked, "folder": suggest_folder(info.name)}

    def _keep_copy(self, data: bytes) -> str:
        """Keeps `data` (playlists.txt as it was) in `<music>/.discjockey/playlists/<stamp>.txt` for the undo that puts it
        back, `<stamp>_2.txt` ... when the second is taken, and the newest `PLAYLIST_COPIES` of them (by stamp, then
        number: `_10` comes after `_2`). Returns the absolute path."""
        folder = self._paths.playlist_copies
        folder.mkdir(parents=True, exist_ok=True)
        stamp = self._svc.now().strftime("%Y-%m-%d_%H%M%S")
        n, path = 1, folder / f"{stamp}.txt"
        while path.exists():
            n += 1
            path = folder / f"{stamp}_{n}.txt"
        path.write_bytes(data)
        kept = sorted(((m[1], int(m[2] or 1), f) for f in folder.iterdir() if (m := COPY_NAME.fullmatch(f.name))))
        for _, _, old in kept[:-PLAYLIST_COPIES]:
            if old != path:
                old.unlink(missing_ok=True)
        return str(path)

    @bridge
    def save_playlists(self, lines: list | None = None, loaded_version: str | None = None,
                       files: SaveFiles | None = None, op: PlaylistOp | None = None) -> dict:
        """Writes playlists.txt: the rows `lines` (the window's whole list), or one change `op` (`PlaylistOp`) made to
        the file's rows under the lock; exactly one of the two. `loaded_version` is the file's version the caller read:
        a different one refuses the save (None: no check). `files` is the answer to the save question when the change
        retargets files: `{choice: "leave"|"move", renames: [[old, new]], moves: [[file_id, from_path]]}`; an absent
        `renames` is every folder rename the question offers; an absent `moves` is every ticked file that no chosen rename
        carries (`views.save_offers`). "move" renames the chosen folders on
        disk and moves the chosen files (move batches, undoable); "leave" makes the files this save would have moved
        the user's own placement (P1). A change `op` that would put files elsewhere with no `files` is refused
        (`needs_choice`) with the change preview as its data. A save that changes the file is logged for `history` with
        the file as it was. The result is `{version, batches: [BatchResultJSON]}`; a Stop after the save still delivers
        the batches so far."""
        if lines is not None and op is not None:
            raise ValueError(playlist_words.SAVE_LINES_OR_OP)
        if lines is None and op is None:
            raise ValueError(playlist_words.SAVE_NOTHING)
        choice = save_choice(files)
        if op is None:
            rows, filled = rows_from(lines), None
        else:
            now = pf.load(self._paths.playlists_file).rows
            filled = self._op(op, now)
            pf.apply(now, filled)  # refused here, before a job starts, when it can't be made

        def work(ctx) -> dict:
            path = self._paths.playlists_file
            before = pf.load(path)
            if loaded_version is not None and before.version != loaded_version:
                if filled is None:
                    raise pf.PlaylistsChanged(pf.CHANGED_ELSEWHERE)
                raise OpProblem(playlist_words.PLAYLISTS_VERSION_CHANGED, "changed", reason="version_changed",
                                next=[{"run": "playlist list", "why": playlist_words.PLAYLISTS_LIST_WHY}])
            new_rows = rows if filled is None else pf.apply(before.rows, filled)  # no rows on the command line or in a job file
            answer = None
            if filled is not None and files is None:
                answer = self._change_answer(before.rows, new_rows, before.version)
                if answer["problem"] is None and answer["tidy"] is not None:
                    n = len(answer["tidy"]["rows"])
                    raise OpProblem(engine_words.plural(n, playlist_words.SAVE_NEEDS_CHOICE_ONE, playlist_words.SAVE_NEEDS_CHOICE), "refused",
                                    reason="needs_choice",
                                    data={k: v for k, v in answer.items() if k not in ("lines", "unknown", "next")})
            picked = choice
            if choice is not None and choice.files == "move" and (files.get("renames") is None or files.get("moves") is None):
                offers = views.save_offers(answer or self._change_answer(before.rows, new_rows, before.version),
                                           files.get("renames"))
                picked = save_choice({"renames": offers[0], "moves": offers[1], **files})
            retargeted, all_renames = {}, []
            if picked is not None:  # the targets before the save are what the save changes
                retargeted = pf.retargeted(before.rows, new_rows, self._tracks_by_id(), self._state())
                all_renames = pf.renames(before.rows, new_rows)
            data = path.read_bytes() if path.exists() else b""
            copy = self._keep_copy(data) if filled is None or filled["op"] == "edit" else None
            try:
                version = pf.save(path, new_rows, before.version)
            except BaseException:
                if copy is not None:
                    Path(copy).unlink(missing_ok=True)
                raise
            if version != before.version:
                operation, message, undo = pf.change_log(before.rows, filled, copy)
                ops.log_change(self._paths, self._svc.now(), "playlists", operation, message, undo, version=version)
            elif copy is not None:  # nothing changed: nothing to undo
                Path(copy).unlink(missing_ok=True)
            if picked is None:
                return {"version": version, "batches": []}
            try:
                done = tidy.after_save(self._paths, retargeted, picked, emit=ctx.emit, token=ctx.token,
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
            with db.connect(self._paths.db_file, read_only=True) as conn:
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
        return views.tidy_preview(planner.tidy_rows(state), state, self._cover(self._images(self._plan())))

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
        state = self._state()
        e = self._entry(state, track_id)
        track = self._spotify_track(track_id, e)
        notes = []
        if streak_stopped(state):  # paused after failed requests in a row (any process's): not asked at all
            qobuz = None
            notes.append(QOBUZ_PAUSED_NOTE)
        else:
            try:
                qobuz = self._svc.open_qobuz(self._support)
            except QobuzNotSetUp:
                qobuz = None  # candidates.search says so itself
            except QobuzError as err:
                qobuz = None
                notes.append(f"Qobuz was not searched: {login_problem(err)}")
        try:
            pacer = self._svc.pacer(self._paths.support, no_emit, CancelToken())
            found, more = candidates.search(track, e, qobuz, self._svc.fallback(),
                                            skip=candidates.protected(self._paths), pace=pacer.before_qobuz_search)
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
    def start_sync(self, plan_id: str | None = None, selected: list | None = None, how_many: str | None = None) -> dict:
        """Starts the sync of the plan `plan_id` (a Sync preview's, `_store_sync_plan`) that runs only the actions
        `selected` (their ids in the plan); the rest of the plan is left out of the run, and what the run's fresh plan
        has that the plan did not is `new_since_plan` in its result. No plan id: the plan of a fresh preview
        (`_sync_preview_view`, which plans on the stored read), `not_set_up` while nothing was read. No `selected`: what
        `how_many` ticks of the plan's actions as the window's chip does (`views.ticks`: 5, 10, 25, 50, `fits` today's
        allowance, `all`, or a number of downloads; every other action of the plan is in), the preview's default chip
        when none is given. `selected` belongs to a plan (`plan_id`) and not with `how_many`. A plan that is unknown or
        expired answers `bad_args` / `refused` (the window then reads a new preview). A Terminal sync's registry record
        says the plan and the ids chosen (`job_status().last_sync`), not the words of its command line."""
        plan_id, planned, chosen = self._sync_start_checked(plan_id, selected, how_many)
        if (files := self._jobs.inline) is not None:  # a Terminal sync: its record says what runs, not what the line typed
            files.update(args={"plan_id": plan_id, "selected": chosen, **({"how_many": how_many} if how_many is not None else {})})
            files.flush()
        job = self._jobs.start("sync", sync_work(self._paths, planned, chosen, self._svc.now,
                                                 self._rekordbox_services(), pacer=self._svc.pacer))
        return {"job_id": job.id}

    def _sync_start_checked(self, plan_id: str | None, selected: list | None, how_many: str | None
                            ) -> tuple[str, dict[str, tuple[str, str, str]], list[str]]:
        """Everything `start_sync` refuses before a job exists, and what it runs: the plan's id, its actions by id
        (`_planned_actions`) and the ids chosen. The Terminal asks it first (`CliApi.prejob_start_sync`), so a refusal
        starts no worker and leaves no job record. Raises what `start_sync` answers as a problem."""
        if selected is not None and not isinstance(selected, (list, tuple)):
            raise ValueError("`selected` is a list of action ids of the plan.")
        if selected is not None and plan_id is None:
            raise BadId("usage", engine_words.SYNC_IDS_NEED_PLAN)
        if selected is not None and how_many is not None:
            raise BadId("conflicting_flags", engine_words.SYNC_IDS_OR_HOW_MANY)
        n = self._how_many_n(how_many)
        preview = None
        if plan_id is None:  # `selected` is None too: the stored read's plan, as a fresh preview shows it
            preview = self._sync_preview_view()
            if (plan_id := preview["plan_id"]) is None:
                raise OpProblem(engine_words.SYNC_NEEDS_READ, "refused", reason="not_set_up",
                                next=[{"run": "sync read", "why": "reads your playlists, so there is a plan"}])
        # the plan it was given is checked before anything is planned: a refused start stores no plan
        planned = self._planned_actions(plan_store.load(self._support.support, plan_id, self._plan_root()))
        if selected is None:
            preview = preview or self._sync_preview_view()
            chosen = self._ticked_by_how_many(preview, planned, how_many, n)
        else:
            chosen = list(selected)
            for act in chosen:
                if not isinstance(act, str) or act not in planned:
                    raise ValueError(f"{act!r} is not an action of the plan {plan_id}.")
        return plan_id, planned, chosen

    @staticmethod
    def _how_many_n(how_many: str | None) -> int | str | None:
        """`start_sync`'s `how_many` checked: None, `fits`, `all` or a whole number (as a number, or its digits)."""
        if how_many is None:
            return None
        text = str(how_many).strip().lower()
        if text in ("fits", "all"):
            return text
        if not re.fullmatch(r"[0-9]+", text):
            raise BadId("usage", engine_words.BAD_HOW_MANY)
        return int(text)

    def _ticked_by_how_many(self, preview: Mapping, planned: Mapping, how_many: str | None, n: int | str | None
                            ) -> list[str]:
        """The ids `start_sync` runs when it is given no list: what `views.ticks` ticks of the preview's rows that the
        plan holds. `n`: `_how_many_n`'s answer. None: the preview's default chip (its downloads; no chip means nothing
        is in scope, so nothing runs); `fits`: what today's allowance leaves (no daily limit: every download);
        `all`: every download."""
        rows = [a for g in preview["groups"] for a in g["actions"] if a["id"] in planned]
        if how_many is None:
            chip = next((p for p in preview["presets"] if p["key"] == preview["default_how_many"]), None)
            if chip is None:
                return []
            n = chip["downloads"]
        elif n == "fits":
            n = preview["estimate"]["left"] if preview["estimate"] is not None else None
        elif n == "all":
            n = None
        settings = self._settings()
        return views.ticks(rows, n, settings.scope_off, settings.weekly_off)

    @bridge
    def stop(self, job_id: str | None = None) -> dict:
        """Stop safely: the running write job (a sync, a download, a Spotify login) ends after its current step. With a
        `job_id` (any job of this support folder, the Terminal's too): writes that job's stop file, what `job stop` does,
        when it is queued, running or stopping; `stopped` is false for one that has ended."""
        if job_id is None:
            return {"stopped": self._jobs.stop()}
        files = registry.Registry(self._support.support).get(job_id)
        if files.state().get("status") not in registry.ACTIVE:
            return {"stopped": False}
        files.request_stop()
        return {"stopped": True}

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

        return {"job_id": self._settings_job("save_limits", work).id}

    @bridge
    def mark_warnings_seen(self, service: str) -> dict:
        """"Got it" on the Download limits page: the service's warning signs up to now are no longer new (the card and
        the sidebar dot go quiet); they stay listed until they drop out of the 14 days."""
        service = self._service(service, set_up=True)

        def work(ctx) -> dict:
            until = self._svc.now().isoformat(timespec="seconds")
            self._update_settings(lambda s: s.with_seen(service, until))
            return {"service": service, "seen_until": until}

        return {"job_id": self._settings_job("mark_warnings_seen", work).id}

    @bridge
    def hide(self, track_id: str, hidden: bool, expect: str | None = None) -> dict:
        return self._single("hide" if hidden else "unhide", track_id,
                            lambda state, ctx: ops.set_hidden(self._paths, state, track_id, bool(hidden)), expect)

    @bridge
    def never_download(self, track_id: str, never: bool) -> dict:
        """"Never download" on the Sync page (or undo it): kept in state.json → never; the planner leaves the track
        out of every sync until undone. Nothing is downloaded or deleted. The preview moves the track at once."""
        prep = self._plan(strict=True)  # a plan that can't be derived is not "not in the plan"
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
            what = "never download" if never else "download allowed"  # not "download again": that is a missing file's (missing.py)
            ops.log_operation(self._paths, self._svc.now(), track_id, info, what, "done", what)
            return {"track_id": track_id, "never": bool(never)}

        return {"job_id": self._jobs.start("never_download", work, track_id=track_id).id}

    @bridge
    def rescan_library(self) -> dict:
        """The window opened, or came back to the front after a while (spec library §6.4): index Library/ against
        library.db, so files moved or replaced by hand are found. A write job (kind "scan"): busy/console as every
        write method; the page ignores those answers, a running sync scans by itself. The plan is derived from the
        records as they are (`_plan`), so Sync and To-do never show the plan from before the scan."""
        def work(ctx) -> dict:
            summary = library.scan_library(self._paths, ctx.emit)
            return {"moved": summary.moved, "new": summary.new, "gone": summary.gone, "missing": summary.missing,
                    "back": summary.back, "changed": summary.replaced, "copies": summary.copies}

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
        """"Continue import": the import again, where it stopped (also after a Stop, which holds the automatic start
        back, in every window, until this is run)."""
        return {"job_id": self._start_import().id}

    @bridge
    def remove_watched_folder(self, folder_id: int) -> dict:
        """Stops watching an import folder (D12; its files stay where they are): a write job (kind "folders"), its
        result `{name, files, redownload}` (`name` is for the command line's words; the window ignores it)."""
        folder = self._import_folder(folder_id)

        def change(ctx) -> dict:
            counts = folders_mod.remove(self._paths, folder.id, self._today(), emit=ctx.emit)
            return {"name": folder.path.name or str(folder.path), "files": counts.files, "redownload": counts.redownload}

        return {"job_id": self._jobs.start("folders", change).id}

    @bridge
    def answer_same_song(self, song_key: str, own_key: str, same: bool) -> dict:
        """"Is this the same song?" answered (a write job, kind "answer"): the plan is made again, so the file is
        linked to the playlist song (yes) or the song downloads at the next sync (no)."""
        if not (isinstance(song_key, str) and isinstance(own_key, str) and isinstance(same, bool)):
            raise ValueError(NOT_ANSWERABLE)

        def change(ctx) -> dict:
            folders_mod.answer_same_song(self._paths, song_key, own_key, same, self._svc.now())
            return {}

        return {"job_id": self._jobs.start("answer", change).id}

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

        return {"job_id": self._jobs.start("answer", change).id}

    @bridge
    def keep_file(self, group_id: str, file_id: int, paths: list[str]) -> dict:
        """Duplicates' "keep this file" (a write job, kind "supersede"; nothing is deleted): every other file of the
        group goes to Superseded/, one engine job (`folders.keep_file`). `paths`: the group's files' paths as the card
        showed them (`changed` when they are not the group's any more, whatever its file ids say, and the group stays as
        it was). The result is `{results, recovered, kept_track}`: a report line per moved file, without a track's
        row; a move that was refused (or any error) stops the job, the files moved before it stay moved and the
        failed job's result lists them."""
        if (not isinstance(group_id, str) or isinstance(file_id, bool) or not isinstance(file_id, int)
                or not _paths_list(paths)):
            raise ValueError(NOT_ANSWERABLE)
        ids = db.group_ids(group_id)

        def change(ctx) -> dict:
            tracks = self._state()["tracks"]
            held = {t.get("file_id"): (k, t) for k, t in tracks.items() if t.get("file_id") in ids}

            def body(kept: folders_mod.KeptFile) -> dict:
                results = []
                for moved_id, dst in kept.moved:
                    key, e = held.get(moved_id, (None, {}))
                    results.append(asdict(Result(
                        "replaced", e.get("folder") or "", e.get("artist") or "", e.get("title") or "", key,
                        folders_mod.MOVED.format(dst=dst), e.get("status"), e.get("source"), e.get("cutoff_hz"), dst)))
                return {"results": results, "recovered": [], "kept_track": kept.kept_track}

            done: list[tuple[int, str]] = []  # the moves made so far, whatever ends the call
            try:
                kept = folders_mod.keep_file(self._paths, group_id, file_id, paths, emit=ctx.emit, now=self._svc.now,
                                             moved_out=done)
            except BaseException as e:
                if done or isinstance(e, folders_mod.KeepStopped):
                    ctx.failed_result = body(folders_mod.KeptFile(list(done), None))
                raise
            ctx.message = kept.words()
            return body(kept)

        return {"job_id": self._jobs.start("supersede", change).id}

    @bridge
    def add_bought_file(self, track_id: str, path: str, expect: str | None = None) -> dict:
        """Adds the file at `path` (the dropped file's, from `FileDropped`) as the bought version of the track
        (a write job): the path must be absolute, of a file this process can read; refused before a job starts."""
        if not isinstance(path, str) or not path:
            raise ValueError(NO_PATH)
        if (problem := _file_problem(path)) is not None:
            raise OpProblem(problem, "refused")
        return self._single("add_bought_file", track_id, lambda state, ctx: ops.add_bought_file(
            self._paths, state, track_id, Path(path), analyze=self._svc.analyze, now=self._svc.now), expect)

    @bridge
    def use_candidate(self, track_id: str, candidate: dict, expect: str | None = None) -> dict:
        cand = to_candidate(candidate)

        def find(qobuz, fallback):
            return cand

        find.kind, find.needs_qobuz, find.cand = "use_candidate", cand.source == "qobuz", cand
        return self._replace_with(track_id, find, expect)

    @bridge
    def use_link(self, track_id: str, url: str, expect: str | None = None) -> dict:
        source, _ = candidates.parse_link(url)  # a plain message at once for links Discjockey can't use

        def find(qobuz, fallback):
            try:
                return candidates.link_candidate(url, qobuz, fallback)
            except ValueError as e:
                raise OpProblem(str(e)) from None

        find.kind, find.needs_qobuz, find.cand = "use_link", source == "qobuz", None
        return self._replace_with(track_id, find, expect)

    @bridge
    def reject_current(self, track_id: str, expect: str | None = None) -> dict:
        return self._single("reject_current", track_id,
                            lambda state, ctx: ops.reject_current(self._paths, state, track_id, now=self._svc.now),
                            expect)

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
        a real one): whether it runs, where its library is, and how two files are compared; `via` is where the sync's
        Auto-upgrade batch says it started."""
        return {"running": self._svc.rekordbox_running, "place": self._svc.rekordbox_place(),
                "compare": self._svc.compare, "now": self._svc.now, "via": self._via}

    def _rekordbox_options(self, ctx, state: dict) -> dict:
        return {"emit": ctx.emit, "token": ctx.token, "now": self._svc.now, "state": state,
                "running": self._svc.rekordbox_running, "place": self._svc.rekordbox_place()}

    def _check_rev(self, state: dict, track_id: str, expect: str | None, operation: str) -> None:
        """A single-track write's precondition: the song is still there and, when `expect` (a `rev`) is given, its
        record still has that rev; else `changed` (with its operations-log line, as `ops.run_single` writes it) and
        nothing is done."""
        e = state["tracks"].get(track_id)
        if e is None or (expect is not None and models.rev(e) != expect):
            ops.log_operation(self._paths, self._svc.now(), track_id, e, operation, "changed", ops.CHANGED)
            if e is None:
                raise OpProblem(ops.CHANGED, "changed")
            raise ops.changed(track_id, e)

    def _batch_work(self, make: Callable[[], int] | None, resume: int | None, *, alone: bool,
                    left: Sequence[batches.ItemResult] = (), extra: Mapping | None = None,
                    expect: tuple[str, str] | None = None):
        """A Same track batch as a write job: `make()` records a new batch of the chosen tracks (after recovery), or
        `resume` names a stopped one (a Convert batch too). The result is a BatchResult dict (+ `recovered`); a Stop,
        rekordbox opened (`rekordbox_open`), another window changing rekordbox (`busy`) and a batch with nothing to do
        (`refused`) end the job as a problem that still carries the batch (`JobFinished.result`), so the page can show
        where it stopped and Resume. `alone`: a batch of one track that meets rekordbox open or busy before anything
        ran is closed instead of left stopped (the track simply stays where it was; `batches.close_unrun`). `left`: songs
        a plan left out of the batch (`_each_work`'s words: they end as skipped); `extra`: what else the result says.
        `expect`: (song, rev) of a one-song batch whose record must still have that rev."""
        def work(ctx) -> dict:
            state, recovered = self._begin()
            if expect is not None:
                self._check_rev(state, *expect, batches.OPERATIONS["same_track"])
            if resume is not None and self._stopped_aiff(resume).state != "stopped":
                # read under the library lock, after recovery: a batch a crash left `running` is stopped by now
                raise OpProblem(NOT_STOPPED, "refused", reason="not_stopped")
            batch_id = resume if resume is not None else make()
            return self._run_batch(ctx, state, recovered, batch_id, resume is not None, alone, left, extra)
        return work

    def _run_batch(self, ctx, state: dict, recovered: list, batch_id: int, resuming: bool, alone: bool,
                   left: Sequence[batches.ItemResult] = (), extra: Mapping | None = None) -> dict:
        """Runs (or resumes) AIFF batch `batch_id` as `_batch_work` says. `left`: the songs a Convert or Rename plan left
        out of the batch (never items): a batch that ends normally lists them as skipped, as the console does."""
        options = self._rekordbox_options(ctx, state)
        call = batches.resume if resuming else batches.run
        try:
            result = call(self._paths, batch_id, compare=self._svc.compare, **options)
        except (batches.Stopped, batches.RekordboxOpen, batches.Refused, batches.Busy) as e:
            result = e.result if hasattr(e, "result") else batches.result_of(self._paths, batch_id)
            if alone and not isinstance(e, (batches.Stopped, batches.Refused)) and result.total == 1 \
                    and not result.done:
                result = batches.close_unrun(self._paths, batch_id, "busy" if isinstance(e, batches.Busy)
                                             else "rekordbox_open", str(e), now=self._svc.now)
            if isinstance(e, batches.RekordboxOpen) and result.state == "stopped":
                e.stopped_batch(result.batch)  # the batch waits: its Resume is what the person does after quitting
            ctx.failed_result = {**result.to_dict(), "recovered": recovered, **(extra or {})}
            raise
        body = result.to_dict()
        if left:
            body = {**body, "total": body["total"] + len(left), "skipped": body["skipped"] + len(left),
                    "results": [*body["results"], *(r.to_dict() for r in left)]}
        return {**body, "recovered": recovered, **(extra or {})}

    def _aiff_work(self, scope: dict, *, only: str | None, started_by: str, batch_scope: str,
                   run: Collection[str] | None = None, left: Sequence[batches.ItemResult] = (),
                   extra: Mapping | None = None):
        """Convert, Give it its clean name and Make all lossless files AIFF as one write job: recovery, the facts fill
        (own files with no stored audio facts, as the console does first), the plan again for `scope` (`only` "rename":
        Rename's answer alone), the batch of its items (`batches.start`) and its run. A plan with nothing in it ends
        the job `refused` with the words of `batches.Refused` (the one song's own, or "None of these can be changed
        right now.") for a selection and `NOTHING_TO_CHANGE` for a view or the CDJ group; the songs left as they are
        come in the result as skipped. A selection of one is `alone` (see `_batch_work`). `run` (a run with a plan):
        only these songs of the plan are batch items; `left`: the songs the plan's answer changed for (skipped,
        `changed`), `extra`: what else the result says (`new_since_plan`)."""
        alone = scope["kind"] == "tracks" and len(scope["tracks"]) == 1

        def work(ctx) -> dict:
            state, recovered = self._begin()
            importer.fill_facts(self._paths, emit=ctx.emit, token=ctx.token, probe=self._svc.probe)
            state = library.load_state(self._paths)  # the fill wrote the facts the plan reads
            found = self._planned(state, scope, only, in_job=True)
            if run is not None:
                found = replace(found, items=tuple(i for i in found.items if i.track in run))
            action = only or "convert"
            skipped = [batches.ItemResult(s.track, action, "skipped", s.reason, s.message, None, None)
                       for s in found.skipped]
            skipped += left
            if not found.total:
                empty = batches.BatchResult(0, "done", None, len(skipped), 0, len(skipped), 0, skipped, None)
                ctx.failed_result = {**empty.to_dict(), "batch": None, "recovered": recovered, **(extra or {})}
                raise OpProblem(str(batches.Refused(empty)) if scope["kind"] == "tracks" else plans.NOTHING_TO_CHANGE,
                                "refused")
            batch_id = batches.start(self._paths, found.actions(), started_by=started_by, scope=batch_scope,
                                     via=self._via, now=self._svc.now)
            return self._run_batch(ctx, state, recovered, batch_id, False, alone, skipped, extra)
        return work

    def _aiff_plan_run(self, plan_id: str, scope: dict, only: str | None) -> tuple[list[str], list[batches.ItemResult], dict]:
        """A run with a plan (design §7.1) for an AIFF scope: the songs of the plan that still stand as the dry run saw
        them (`_bind_plan` against `aiff_plan`'s items as they are now: `Item.to_dict`, keyed by the song), those whose
        answer is another now (skipped, `changed`) and what the result adds (`new_since_plan`: the songs that have an
        item now and had none in the plan). For named songs, a plan song the person did not name is no `changed` row
        (as `_plan_run`); a plan of a view or of the CDJ group answers every item that no longer stands."""
        now = {i.track: i.to_dict() for i in self._planned_reading(self._state(), scope, only).items}
        plan, bound = self._bind_plan(plan_id, now)
        typed = set(scope["tracks"]) if scope["kind"] == "tracks" else None
        action = only or "convert"
        left = [batches.ItemResult(k, action, "skipped", "changed", PLAN_CHANGED_WORDS, None, None)
                for k in bound.changed if typed is None or k in typed]
        if plan.items and not bound.run:  # as `_plan_run` (a plan of no songs is a clean library)
            raise OpProblem(PLAN_NOTHING, "changed")
        return list(bound.run), left, {"new_since_plan": list(bound.new)} if bound.new else {}

    def _aiff_start(self, scope: dict, *, only: str | None, started_by: str, batch_scope: str, plan_id: str | None,
                    track_id: str | None = None):
        """Starts the AIFF batch job of `scope` (kind "aiff_batch"). With `plan_id` only the plan's songs that still
        stand run (`_aiff_plan_run`; a plan none of whose songs stands is `changed`, as for `upgrade`); a plan that had no
        items ends the job done with nothing in it (`total` 0): the plan was a clean library."""
        run, left, extra = None, [], {}
        if plan_id is not None:
            run, left, extra = self._aiff_plan_run(plan_id, scope, only)
            if not run:
                return {"job_id": self._jobs.start("aiff_batch", self._aiff_nothing(left, extra),
                                                   batch_kind="convert").id}
            if scope["kind"] == "tracks":
                scope = {"kind": "tracks", "tracks": run}
            track_id = scope["tracks"][0] if scope["kind"] == "tracks" and len(scope["tracks"]) == 1 else None
        work = self._aiff_work(scope, only=only, started_by=started_by, batch_scope=batch_scope, run=run, left=left,
                               extra=extra)
        return {"job_id": self._jobs.start("aiff_batch", work, track_id=track_id, batch_kind="convert").id}

    def _aiff_nothing(self, left: Sequence[batches.ItemResult], extra: Mapping):
        """A run whose plan has nothing that stands: the job ends done, no batch, the changed songs skipped."""
        def work(ctx) -> dict:
            _, recovered = self._begin()
            empty = batches.BatchResult(0, "done", None, len(left), 0, len(left), 0, list(left), None)
            return {**empty.to_dict(), "batch": None, "recovered": recovered, **extra}
        return work

    def _each_work(self, ids: list[str], mode: str, *, left: Sequence[batches.ItemResult] = (),
                   extra: Mapping | None = None, expect: str | None = None):
        """New track and Discard on a list (`mode` is the action each track runs: `add_new` | `discard`): one job, one
        track after the other (Stop between them, per-track results, no batch record, no Resume: each is quick and has
        its own undo). One track keeps the old single-track behaviour: the entry is checked against `expect` (its rev, when
        given) and a failure ends the job with its own words. The result is BatchResult-shaped (`batch` null). `left`: songs a plan
        left out (they end as skipped); `extra`: what else the result says."""
        one = len(ids) == 1

        def work(ctx) -> dict:
            state, recovered = self._begin()
            if one:
                self._check_rev(state, ids[0], expect, f"upgrade_{mode}")
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
            if not stopped:
                results += left
            count = lambda st: sum(1 for r in results if r.state == st)  # noqa: E731
            if count("done"):
                rep.write_not_lossless(self._paths, state)
            body = {"batch": None, "state": "stopped" if stopped else "done", "stop_reason": "stop" if stopped else None,
                    "total": len(results), "done": count("done"), "skipped": count("skipped"), "failed": count("failed"),
                    "results": [r.to_dict() for r in results], "backup": None, "recovered": recovered, **(extra or {})}
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
            # what each track's check said before the undo took it away: the words of a Convert's or a clean name's undo
            asked = batches.tracks_of(self._paths, target) if isinstance(target, int) else target
            was = {t: ((state["tracks"].get(t) or {}).get("rekordbox_check") or {}).get("reason") for t in asked}
            try:
                result = batches.undo(self._paths, target, **self._rekordbox_options(ctx, state))
            except (batches.RekordboxOpen, batches.UndoStopped) as e:
                ctx.failed_result = {**e.result.to_dict(), "recovered": recovered}
                raise
            body = {**result.to_dict(), "recovered": recovered,
                    "words": views.undone_words([was.get(r.track) for r in result.results if r.state == "undone"])}
            if result.total and not result.undone:
                ctx.failed_result = body
                raise OpProblem(result.results[0].message if result.total == 1 else UNDO_NONE, "refused")
            return body
        return work

    @bridge
    def rekordbox_checked(self, track_ids: list[str], batch_id: int | None = None) -> dict:
        """"Done, checked in rekordbox" for tracks (a batch card sends its done tracks): the reminders and with them
        the undo end. A write job (kind "rekordbox_checked"); the result lists the `checked` tracks, those with
        nothing to check (`not_checked`) and the engine's `results`. `batch_id` (the command line's `--batch`; then
        `track_ids` is empty): the tracks whose open check is that AIFF batch's (the window's batch card lists the
        same). A track a later batch or step changed again keeps that check and is in `newer` (track -> `aiff:N` of
        the later batch, or None). A batch whose tracks were all checked already is a finished job with nothing in it
        (`batch` says which); named tracks with nothing to check end `changed`."""
        if batch_id is not None:
            if track_ids:
                raise ValueError(BATCH_OR_TRACKS)
            self._stopped_aiff(batch_id)
            ids = None
        else:
            ids = self._track_list(track_ids)

        def work(ctx) -> dict:
            state, recovered = self._begin()
            later: dict = {}
            if ids is not None:
                wanted = ids
            else:
                def check_of(t: str) -> dict:
                    return (state["tracks"].get(t) or {}).get("rekordbox_check") or {}
                wanted = [t for t in state["tracks"] if check_of(t).get("batch") == batch_id]
                later = {t: (f"aiff:{check_of(t)['batch']}" if isinstance(check_of(t).get("batch"), int) else None)
                         for t in batches.tracks_of(self._paths, batch_id)
                         if check_of(t) and check_of(t).get("batch") != batch_id}
            before = {t: state["tracks"].get(t) for t in wanted}
            done = batches.checked(self._paths, wanted, state=state, now=self._svc.now)
            checked = [r.track_id for r in done]
            body = {"results": [asdict(r) for r in done], "checked": checked,
                    "not_checked": [] if ids is None else [t for t in ids if t not in checked], "recovered": recovered,
                    **({} if ids is not None else {"batch": batch_id, "newer": later})}
            if not checked and ids is not None and not self._skipped_check_is_ok:
                ctx.failed_result = body  # the skipped rows still say which tracks had nothing to check
                raise OpProblem(NOTHING_TO_CHECK, "changed")
            for t in checked:
                ops.log_operation(self._paths, self._svc.now(), t, before[t], "rekordbox_checked", "done",
                                  "checked in rekordbox")
            return body
        return {"job_id": self._jobs.start("rekordbox_checked", work,
                                           track_id=ids[0] if ids is not None and len(ids) == 1 else None).id}

    @staticmethod
    def _missing_action(action: object) -> str:
        """The action of a missing file's methods (`missing.ACTIONS`); anything else is `bad_args`."""
        if action not in missing.ACTIONS:
            raise BadId("usage", f"action must be one of {', '.join(missing.ACTIONS)}.")
        return action  # type: ignore[return-value]

    @bridge
    def missing_files_preview(self, track_ids: list[str], action: str) -> dict:
        """What Download again or Remove from library would do for songs whose file is missing, answered before it runs
        (issue 43, plan §4.4; the dry run of `missing download|remove`): `{action, items, n, skipped, words}` as
        `missing.preview` shapes it, one item per song with `will` and, when it can't, its `reason` and `words`. A song
        that is not missing (or is no song) is an item that will not run. Reads only. An unknown action is `bad_args`."""
        action = self._missing_action(action)
        ids = self._track_list(track_ids)
        state = self._state()
        return missing.preview(state, ids, action, self._place(state), self._today())

    @bridge
    def missing_files(self, track_ids: list[str], action: str) -> dict:
        """Download again (`download_again`) or Remove from library (`remove`) for songs whose file is missing: a write
        job (kind "missing_files"; the plan is made again, so the Sync page shows the planned download, or the placement in
        its Auto-upgrade line, at once). Each song is asked again when the job runs: one that changed since the click
        is `skipped` with its reason. The result is `{action, results, done, skipped, words}`; every song skipped ends the
        job `changed` with the same result kept. Remove is final (no undo) and deletes no music file: only the song's
        records and its parked download in Upgrades ready/. Nothing is removed without this call. Remove scans the
        watched folders first (inside the job), so a file put back since the last scan links again and its song is
        `skipped` as not missing."""
        action = self._missing_action(action)
        ids = self._track_list(track_ids)
        run_action = missing.download_again if action == missing.DOWNLOAD_AGAIN else missing.remove

        def work(ctx) -> dict:
            if action == missing.REMOVE:  # final: look at the folders first, so a file put back since the last scan
                library.scan_library(self._paths, ctx.emit)  # links again before anything is forgotten (FA)
            state, recovered = self._begin()
            results = run_action(self._paths, ids, now=self._svc.now, state=state)
            done = [r.track_id for r in results if r.state == "done"]
            body = {"action": action, "results": [r.to_dict() for r in results], "done": done,
                    "skipped": [r.track_id for r in results if r.state == "skipped"],
                    "words": missing.run_words(action, results, state), "recovered": recovered}
            if not done:
                ctx.failed_result = body
                raise OpProblem(body["words"], "changed")
            if action == missing.REMOVE:
                rep.write_not_lossless(self._paths, state)  # the removed songs leave that list
            return body

        return {"job_id": self._jobs.start("missing_files", work,
                                           track_id=ids[0] if len(ids) == 1 else None).id}

    def _plan_run(self, plan_id: str, mode: str, ids: list[str], state: dict, typed: set[str] | None = None
                  ) -> tuple[list[str], list[batches.ItemResult], dict]:
        """A run with a plan (design §7.1): the songs of `ids` that still stand as the dry run saw them (`_bind_plan`
        against what `upgrade_preview` says today), the songs it leaves as skipped (`changed`) and what the result adds
        (`new_since_plan`: the songs the plan did not have). `typed`: the songs the person named; a plan song they did not
        name was never asked for, so it is no `changed` row (None, Upgrade all: every plan song that does not stand now
        is `changed`). The words of the dry run are the one check of what changed: a song asked about again by the
        run itself, as always."""
        rows = batches.upgrade_preview(self._paths, state, ids, mode, self._rekordbox_status())["items"]
        _, bound = self._bind_plan(plan_id, {r["key"]: r for r in rows})
        if not bound.run:
            raise OpProblem(PLAN_NOTHING, "changed")
        action = batches.PREVIEW_MODES[mode]
        left = [batches.ItemResult(k, action, "skipped", "changed", PLAN_CHANGED_WORDS, None, None)
                for k in bound.changed if typed is None or k in typed]
        return list(bound.run), left, {"new_since_plan": list(bound.new)} if bound.new else {}

    @bridge
    def upgrade(self, track_ids: list[str], mode: str, plan_id: str | None = None, expect: str | None = None) -> dict:
        """Replaces tracks with their better versions. `same_track` is Same track for any format and runs one AIFF batch
        (job kind "upgrade_batch", result a BatchResult); `new_track` and `discard` run the tracks one after the other
        (kinds "upgrade_add_new" / "upgrade_discard", a BatchResult-shaped result without a batch). One track is a list
        of one. Progress is a BatchProgress event for all three. `plan_id` (the command line's `--plan`; Same track and
        New track only): runs only the songs of that plan that still stand (`_plan_run`); the others end as skipped.
        `expect` (the command line's `--if-rev`; one song only): the song's record must still have that rev."""
        if mode not in UPGRADE_MODES:
            raise ValueError(f"mode must be one of {', '.join(UPGRADE_MODES)}")
        ids = self._track_list(track_ids)
        if expect is not None and len(ids) != 1:
            raise BadId("usage", "--if-rev takes one song.")
        left: list[batches.ItemResult] = []
        extra: dict = {}
        if plan_id is not None:
            if mode == "discard":
                raise ValueError(PLAN_NOT_DISCARD)
            ids, left, extra = self._plan_run(plan_id, mode, ids, self._state(), typed=set(ids))
        track = ids[0] if len(ids) == 1 and not left else None
        if mode == "same_track":
            work = self._batch_work(lambda: batches.start(
                self._paths, [(t, "same_track") for t in ids], started_by="user", scope="selection", via=self._via,
                now=self._svc.now), None, alone=len(ids) == 1, left=left, extra=extra,
                expect=(ids[0], expect) if expect is not None and len(ids) == 1 else None)
            return {"job_id": self._jobs.start("upgrade_batch", work, track_id=track, batch_kind="upgrade").id}
        action = NEW_TRACK_ACTION[mode]
        return {"job_id": self._jobs.start(f"upgrade_{action}", self._each_work(ids, action, left=left, extra=extra, expect=expect),
                                           track_id=track, batch_kind="upgrade").id}

    def _upgrade_all_ids(self, state: dict) -> list[str]:
        """What Upgrade all runs: the songs of To-do's Upgrade ready group whose Same track can run (`select`, the one
        answer the window's button, `upgrade_preview` and `select_listing` share)."""
        return select.upgrade_all_ids(self._todo(state, ("upgrade_ready",), False))

    @bridge
    def upgrade_all(self, plan_id: str | None = None) -> dict:
        """Upgrade all: Same track for every parked upgrade the To-do list shows as possible (the group's `all.n`), as
        one batch started by `upgrade_all` (job kind "upgrade_batch"). `plan_id` (the command line's `--plan`): only the
        songs of that plan that still stand. The command line refuses while a stopped upgrade batch waits (`_resume_first`:
        the window hides the button then and shows Resume)."""
        state = self._state()
        ids = self._upgrade_all_ids(state)
        if not ids:
            raise OpProblem(NO_UPGRADES, "refused")
        if self._resume_first and (stopped := views.stopped_batch(self._aiff_batches(), kinds=("upgrade",))):
            raise OpProblem(RESUME_FIRST, "refused", reason="not_stopped",
                            next=[{"run": f"batch resume aiff:{stopped[0]}", "why": f"{stopped[1]} left to do"}])
        left: list[batches.ItemResult] = []
        extra: dict = {}
        if plan_id is not None:
            ids, left, extra = self._plan_run(plan_id, "same_track", ids, state)
        work = self._batch_work(lambda: batches.start(
            self._paths, [(t, "same_track") for t in ids], started_by="upgrade_all", via=self._via,
            now=self._svc.now), None, alone=False, left=left, extra=extra)
        return {"job_id": self._jobs.start("upgrade_batch", work, batch_kind="upgrade").id}

    def _selection_job(self, kind_only: str | None, track_ids: list[str], origin: str, plan_id: str | None = None):
        """Convert and Give it its clean name on songs: one AIFF batch (job kind "aiff_batch", result a BatchResult;
        a refusal still carries the songs left as they are). `origin` is where the page started it; the batch's scope
        says so ("library:selection", "todo:selection") for Resume to show in the same place. `plan_id`: see
        `_aiff_start`."""
        if origin not in AIFF_ORIGINS:
            raise ValueError(f"origin must be one of {', '.join(AIFF_ORIGINS)}")
        scope = self._aiff_scope({"kind": "tracks", "tracks": track_ids})
        return self._aiff_start(scope, only=kind_only, started_by="user", plan_id=plan_id,
                                batch_scope="selection" if self._via == "terminal" else f"{origin}:selection",
                                track_id=scope["tracks"][0] if len(scope["tracks"]) == 1 else None)

    @bridge
    def convert(self, track_ids: list[str], origin: str = "library", plan_id: str | None = None) -> dict:
        """Convert to AIFF for songs, or "only the name" for a clean AIFF (`eligible.aiff_action` decides per file, so
        the page never has to): one AIFF batch, job kind "aiff_batch", result a BatchResult, progress BatchProgress.
        `origin` "library" | "todo". One song is a batch of one (`alone`: rekordbox open or busy before anything ran
        closes it instead of leaving a Resume). `plan_id` (the command line's `--plan`): only the named songs of that
        plan that still stand run; the others are `skipped` (`changed`), and `new_since_plan` lists the named songs
        the plan did not have."""
        return self._selection_job(None, self._track_list(track_ids), origin, plan_id)

    @bridge
    def rename(self, track_ids: list[str], plan_id: str | None = None) -> dict:
        """Give it its clean name for songs (Rename's answer alone: a file that needs a Convert is left as it is): one
        AIFF batch like `convert`, started from the Library. `plan_id`: as `convert`'s."""
        return self._selection_job("rename", self._track_list(track_ids), "library", plan_id)

    @bridge
    def make_aiff(self, scope: dict, plan_id: str | None = None) -> dict:
        """Make all lossless files AIFF (`{kind: "lossless", view, key}`) or the CDJ group's Convert all (`{kind:
        "cdj"}`): plans again at its start and runs the plan's items as one AIFF batch (`started_by` `make_aiff` /
        `cdj_all`, scope "library:<view>[:<key>]" / "todo:cdj"). Job kind "aiff_batch"; nothing to change ends it
        `refused` ("Nothing to change: these are clean AIFFs already."). `plan_id` (the command line's `--plan`): only
        the items of that plan that still stand run, the others are `skipped` (`changed`), `new_since_plan` lists the
        files the plan did not have; a plan with nothing standing ends the job done with `total` 0."""
        found = self._aiff_scope(scope, ("lossless", "cdj"))
        if found["kind"] == "cdj":
            return self._aiff_start(found, only=None, started_by="cdj_all", batch_scope="todo:cdj", plan_id=plan_id)
        where = ":".join(p for p in (found["view"], found["key"]) if p)
        return self._aiff_start(found, only=None, started_by="make_aiff", batch_scope=f"library:{where}",
                                plan_id=plan_id)

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
        "batch_resume"); the result is a BatchResult. The job snapshot's `batch_kind` is the stopped batch's own kind.
        A batch that ended (`done`) is `refused` / `not_stopped` at once; for any other the job decides after its
        recovery, under the library lock: a batch a crash left `running` is stopped by then and resumes, one that is
        still not stopped is `not_stopped`, one that really runs in another process is `busy`."""
        row = self._stopped_aiff(batch_id)
        if row.state == "done":  # a stopped or running one starts the job: whether it is stopped is read under the lock
            raise OpProblem(NOT_STOPPED, "refused", reason="not_stopped")
        return {"job_id": self._jobs.start("batch_resume", self._batch_work(None, batch_id, alone=False),
                                           batch_kind=row.kind).id}

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

    def _tool_presence(self) -> dict[str, bool]:
        """Each program Discjockey needs from this Mac -> whether it is there."""
        return {tool: self._svc.which(tool) is not None for tool in TOOL_HINTS}

    @bridge
    def setup_check_tools(self) -> dict:
        """ffmpeg/ffprobe/deno and the download tools' versions. An unexpected error reading the versions only
        empties `download_tools` (with `download_tools_problem`); the rest of the check still answers."""
        tools_ = self._tool_presence()
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

        return {"job_id": self._settings_job("setup_save_client_id", work).id}

    def _save_spotify_app(self, client_id: str, user: str | None) -> None:
        """.spotify_app.json: the Client ID and, after a login, the account's display name (Settings: "connected as")."""
        data = {"client_id": client_id, **({"user": user} if user else {})}
        with library.support_lock(self._support.support):
            library.write_json_atomic(self._support.spotify_app, data, parents=True)  # the support folder may be new

    @bridge
    def spotify_sign_out(self) -> dict:
        """Forgets the Spotify login (the Client ID stays, so Connect signs in again in one step)."""
        def work(ctx) -> dict:
            with library.support_lock(self._support.support):
                self._support.spotify_token.unlink(missing_ok=True)
            try:
                client_id = json.loads(self._support.spotify_app.read_text(encoding="utf-8"))["client_id"]
            except (OSError, ValueError, KeyError, TypeError):
                return {}
            self._save_spotify_app(client_id, None)
            return {}

        return {"job_id": self._settings_job("spotify_sign_out", work).id}

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
            self._clear_read_problem("spotify")  # a read problem about Spotify's login is out of date now
            return {"user": name}

        return {"job_id": self._settings_job("setup_spotify_login", work).id}

    @bridge
    def setup_skip_spotify(self) -> dict:
        """"I don't use Spotify": the Spotify step counts as done and playlists come from the other services' links. Connecting
        Spotify later (setup or Settings) un-skips it."""
        def work(ctx) -> dict:
            self._update_settings(lambda s: replace(s, spotify_skipped=True))
            return {}

        return {"job_id": self._settings_job("setup_skip_spotify", work).id}

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

        return {"job_id": self._settings_job("set_read_liked_music", work).id}

    @bridge
    def set_auto_upgrade(self, on: bool) -> dict:
        """"Upgrade automatically when I sync" (Settings, Setup; issue 33 stage C): whether a sync ends with Same track
        for every upgrade that needs no decision, while rekordbox is closed. On by default. Turning it off never touches
        the upgrades waiting (they wait in To-do); turning it on moves nothing until the next sync."""
        if not isinstance(on, bool):
            raise OpProblem("on must be true or false.", "refused")

        def work(ctx) -> dict:
            self._update_settings(lambda s: replace(s, auto_upgrade=on))
            return {"auto_upgrade": on}  # the value as saved: the command line says it (the window ignores it)

        return {"job_id": self._settings_job("set_auto_upgrade", work).id}

    @bridge
    def sync_scope(self) -> dict:
        """The Sync scope (issue 39 V2.5b; settings.json `sync_scope`): the playlists and folders left out of a sync
        (`off`, each with its name) and the weekly kinds switched off (`weekly_off`, each with its label). The window and
        an agent read the same value; nothing listed means everything is on. A settings.json that can't be read has
        the defaults. Works with no music folder (the names then are the targets)."""
        return self._scope_view(self._settings())

    def _scope_view(self, settings: Settings) -> dict:
        """A scope as `SyncScope` words it: a playlist target by its playlists.txt line's folder name, a folder target
        by the last part of its path; one that no line or folder has any more keeps the target as its name (a folder on
        a drive that is away comes back)."""
        folders: dict[str, str] = {}
        if self._bound is not None:
            try:
                folders = {f"playlist:{r.ref}": r.folder for r in pf.load(self._bound.playlists_file).rows if r.ref}
            except (OSError, ValueError):  # not readable or not text (UnicodeDecodeError): the targets name themselves
                folders = {}

        def name(target: str) -> str:
            if target in folders:
                return folders[target]
            last = target[len("folder:"):].rstrip("/").rsplit("/", 1)[-1] if target.startswith("folder:") else ""
            return last or target

        return {"off": [{"target": t, "name": name(t)} for t in settings.scope_off],
                "weekly_off": [{"kind": k, "label": engine_words.SCOPE_KIND_LABELS[k]} for k in settings.weekly_off]}

    @bridge
    def set_sync_scope(self, on: list[str], off: list[str]) -> dict:
        """Switches collections and weekly kinds in or out of the Sync scope (the browser column's and the Sync panel's
        switches, `sync scope on|off`): `off` leaves each item out, `on` takes it back in; an item is a playlist or
        folder target (`playlist:<ref>`, `folder:<path>`) or `kind:retry` / `kind:weekly`. A settings job (kind
        `set_sync_scope`, no library lock for its run; the result is the `SyncScope` as saved). The order of what is
        left out is kept, a new item goes last, none twice. A switch says the value wanted, so there is no `expect`:
        the last write wins. Anything else, or an item in both lists, is `refused` before a job starts."""
        ons, offs = self._scope_items(on, "on"), self._scope_items(off, "off")
        both = next((i for i in ons if i in offs), None)
        if both is not None:
            raise OpProblem(f"{both} is in both lists: say on or off for it, not both.", "refused")

        def work(ctx) -> dict:
            def change(s: Settings) -> Settings:
                targets = [t for t in offs if not t.startswith("kind:")]
                kinds = [t[len("kind:"):] for t in offs if t.startswith("kind:")]
                return replace(s, scope_off=tuple(dict.fromkeys([*(t for t in s.scope_off if t not in ons), *targets])),
                               weekly_off=tuple(dict.fromkeys([*(k for k in s.weekly_off if f"kind:{k}" not in ons),
                                                               *kinds])))

            return self._scope_view(self._update_settings(change))

        return {"job_id": self._settings_job("set_sync_scope", work).id}

    @staticmethod
    def _scope_items(items, which: str) -> list[str]:
        """The items of one list of `set_sync_scope`, each a collection target or a weekly kind (`kind:retry` /
        `kind:weekly`), repeats dropped; `refused` naming the first that is not."""
        if not isinstance(items, list):
            raise OpProblem(f"{which} must be a list of playlists, folders and kinds.", "refused")
        for item in items:
            if not isinstance(item, str) or not (is_scope_target(item) or (
                    item.startswith("kind:") and item[len("kind:"):] in SCOPE_KINDS)):
                raise OpProblem(f"{item!r} is not a playlist (playlist:<ref>), a folder (folder:<path>) or a weekly kind "
                                f"(kind:retry, kind:weekly).", "refused")
        return list(dict.fromkeys(items))

    @bridge
    def add_liked_music(self) -> dict:
        """"Add Liked music to Playlists" (sources-round D8): appends `Liked_music = <its link>` to the end of
        playlists.txt (YouTube Music shares no link for it). Refused with `setting_off` while the choice is off and
        `exists` when a Liked music line is listed already, on or off. Answers `{folder}`."""
        def work(ctx) -> dict:
            self._need_liked_music()
            loaded = pf.load(self._paths.playlists_file)
            if pf.lists_liked_music(loaded.rows):
                raise OpProblem(LIKED_LISTED, "exists")
            taken = {fold(r.folder) for r in loaded.rows}
            folder, n = youtube_music.LIKED_MUSIC_FOLDER, 1
            while fold(folder) in taken:  # a folder of that name is another playlist's: add a number
                n += 1
                folder = f"{youtube_music.LIKED_MUSIC_FOLDER}_{n}"
            link = youtube_music.canonical_link(youtube_music.LIKED_MUSIC)
            version = pf.save(self._paths.playlists_file, [*loaded.rows, pf.Row(folder, link)], loaded.version)
            operation, message, undo = pf.change_log(loaded.rows, {"op": "add", "url": link, "folder": folder}, None)
            ops.log_change(self._paths, self._svc.now(), "playlists", operation, message, undo, version=version)
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
            self._clear_read_problem("qobuz")  # a read problem about Qobuz's login is out of date now
            return {}

        return {"job_id": self._settings_job("setup_qobuz_login", work).id}

    def _check_record(self, check: dict) -> dict:
        """A login check as settings.json keeps it (Settings shows "checked today" without checking again)."""
        return {"ok": check["ok"], "problem": check["problem"], "kbps": check["kbps"],
                "at": self._svc.now().isoformat(timespec="seconds")}

    def _account(self, service: str, browser: str | None = None) -> None:
        if service not in ACCOUNTS:
            raise ValueError(f"service must be one of {', '.join(ACCOUNTS)}")
        if browser is not None and browser not in BROWSERS:
            raise ValueError(f"browser must be one of {', '.join(BROWSERS)}")

    def _update_settings(self, change: Callable[[Settings], Settings]) -> Settings:
        """The file as it is now, changed, saved: every settings write in the hub goes through here. One writer at a
        time (spec settings-setup §13). Lock order is support, library, rekordbox.lock: the support lock is taken
        first and keeps every other process's saves of settings.json from being lost; the library lock is taken inside
        it for the moment of the save (`lock_briefly`: a settings job holds none for its run, a sign-in's or a page
        check's save holds none at all) and raises Busy (busy / console) instead of waiting. The mutex keeps this
        process's saves in order. Returns what it saved."""
        with self._settings_mutex, library.support_lock(self._support.support), self._jobs.lock_briefly():
            return update_settings_held(self._support.settings_file, change)

    @bridge
    def setup_skip_qobuz(self) -> dict:
        """"I don't have Qobuz": the sync starts at the SoundCloud originals and the account sources."""
        def work(ctx) -> dict:
            self._update_settings(lambda s: replace(s, qobuz_skipped=True))
            return {}

        return {"job_id": self._settings_job("setup_skip_qobuz", work).id}

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
            check = self._svc.fallback(emit=ctx.emit, check=ctx.token.check).check_account(
                service, browser, profile, self._svc.pacer(self._support.support, ctx.emit, ctx.token))
            return self._account_result(service, browser, profile, check)

        return {"job_id": self._settings_job("setup_account", work).id}

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
            self._clear_read_problem("soundcloud", frozenset({"login_expired"}))  # not offline
            # only the likes hint (W8) is about the login: a private set's "doesn't show this playlist" stays
            self._clear_read_problem("soundcloud", frozenset({"playlist_unreadable"}), soundcloud.LIKES_HINT)
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
        for b in browsers.installed(home, self._svc.applications):
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
        if browser not in browsers.installed(self._svc.home, self._svc.applications):
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
            check = self._svc.fallback(emit=ctx.emit, check=ctx.token.check).check_account(
                service, browser, found, self._svc.pacer(self._support.support, ctx.emit, ctx.token))
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
    def open_privacy_settings(self, print_only: bool = False) -> dict:
        """System Settings at Full Disk Access (Safari's logins need it)."""
        return self._opened(self._svc.open_url, _PRIVACY_SETTINGS, print_only)

    @bridge
    def qobuz_check_login(self) -> dict:
        """Settings' "Check again" for Qobuz: logs in with the saved login and searches once; records the outcome
        (login_failed only when Qobuz refuses the login; being offline or a Qobuz hiccup records nothing)."""
        self._no_sync_running()

        def work(ctx) -> dict:
            source = None
            # the check's two Qobuz requests (login, search) take their slot first: a pacer error is not "couldn't reach"
            self._svc.pacer(self._support.support, ctx.emit, ctx.token).before_qobuz_search()
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
                self._clear_read_problem("qobuz")  # the saved login works: a stored Qobuz read problem is out of date
            if not found:
                raise OpProblem("Logged in to Qobuz, but a test search found nothing.", "failed")
            return {}

        return {"job_id": self._settings_job("qobuz_check_login", work).id}

    @bridge
    def setup_forget_account(self, service: str) -> dict:
        self._account(service)

        def work(ctx) -> dict:
            self._update_settings(lambda s: s.with_account(service, None))
            return {"service": service}

        return {"job_id": self._settings_job("setup_forget_account", work).id}

    def _library_job_elsewhere(self) -> dict | None:
        """A write job of another process of this support folder, from the registry: a running job that holds the
        library lock (`catalog.holds_library`). `{job, via, command}`, or None. This process's own jobs (the one a worker
        runs, the ones the window started: `Jobs.own_ids`) never count: their own `busy` is `Jobs.start`'s."""
        own = self._jobs.own_ids
        for state in registry.Registry(self._support.support).list(all=True):
            if state.get("status") not in registry.HOLDING or state.get("id") in own:
                continue
            if catalog.holds_library(state):
                return {"job": state["id"], "via": state.get("via"), "command": state.get("command")}
        return None

    def _job_record(self) -> dict:
        """What a job this window starts says about itself in the registry: `method` and `args` of the bridge call it
        started in (`CALL`; none outside a call), the catalogue `command` of that method, no secret argument
        (`catalog.public_args`), and the `roots` as the command line writes them (`cli/call.start_job`)."""
        method, args = CALL.get() or (None, {})
        entries = catalog.by_method(method) if method else []
        public = catalog.public_args(method, args)
        try:
            place = self._svc.rekordbox_place()
        except Exception:  # noqa: BLE001  rekordbox's folder is a fact of the record, never a reason not to start
            place = None
        return {"method": method, "command": " ".join(catalog.primary(entries).command) if entries else "",
                "args": json.loads(json.dumps(public, default=str)),
                "roots": {"music": str(self._bound.root) if self._bound is not None else None,
                          "support": str(self._support.support),
                          "rekordbox": str(place.db.parent) if place is not None else None,
                          "rekordbox_share": str(place.share) if place is not None else None, "sandbox": None}}

    def _registered_envelope(self, job: Job) -> dict:
        """`result.json` of a job the window started: the envelope a worker writes for the same job."""
        state = job.files.state() if job.files is not None else {}
        return self._job_envelope(state.get("command") or "", state.get("method"), job, job.id)

    def _job_envelope(self, command: str, method: str | None, job: Job, job_id: str) -> dict:
        """The envelope of a job that ran (`JobFinished`), for the worker and the window's jobs alike: `result` is the
        data of a success, or what a failed job left. A run whose items end in a state its entry counts
        (`Entry.partial`) is `partial`; the words beside the result (`_result_words`: the batch's id, the steps for the
        person, what to run next) are added."""
        done = job.finished or {}
        result = done.get("result") or {}
        try:
            words = self._result_words(method, result) if method and result else {}
        except Exception:  # noqa: BLE001  words are an extra: a failure to find them leaves the answer as it is
            log.warning("the words of %s could not be found", method, exc_info=True)
            words = {}
        entry = catalog.entry_of(method, command) if method else None
        if done.get("ok"):
            rows = (words.get("data") or {}).get("results", result.get("results"))  # the words' rows carry `state` where the engine's do not
            outcome = words.get("outcome") or outcomes.run_outcome(rows, entry.partial if entry else ())  # words may say `ok`: nothing to do is no partial
            return outcomes.envelope(command, outcome, message=done.get("message") or words.get("message") or None,
                                     data={**result, **(words.get("data") or {})}, next=words.get("next") or (),
                                     person_steps=words.get("person_steps") or (), job=job_id)
        fields = outcomes.problem_fields(done.get("problem") or "crashed", job.error)
        data = {**result, **(words.get("data") or {}), **(fields["data"] or {})} or None
        return outcomes.envelope(command, fields["outcome"], reason=fields["reason"], message=done.get("message"),
                                 data=data, next=[*fields["next"], *(words.get("next") or ())],
                                 person_steps=[*fields["person_steps"], *(words.get("person_steps") or ())], job=job_id)

    def _settings_job(self, kind: str, work) -> Job:
        """A job whose work writes only the support folder (settings.json, the login files; Settings, Setup, Download
        limits): it holds no library lock for its run, as the lock order is support, library, rekordbox.lock and a
        settings write takes the support lock first, then the library lock briefly inside it (`_update_settings`).
        It waits for the hub's other jobs like any write job (`busy`), and a terminal run holding the library answers
        `console`."""
        return self._jobs.start(kind, work, hold_library=False)

    def _support_job(self, kind: str, work) -> Job:
        """A support-only job (design §6.1: `tools update`, `tools rollback`): refused `busy` while a write job of this
        support folder runs, in this process (`Jobs.start`) or another (the registry); it takes no library lock, only the
        support lock inside its work."""
        holder = self._library_job_elsewhere()
        if holder is not None:
            raise Busy("Another Discjockey job is working on your music folder. Wait until it has finished.", "busy",
                       reason="library_lock", data={"holder": holder})
        return self._jobs.start(kind, work, hold_library=False)

    def _result_words(self, method: str, result: dict) -> dict:
        """What the command line says beside a finished write's `result` (design §4.4, §8.3): `{message, data, next,
        person_steps}`, each left out when there is nothing to add. Upgrade's results (Same track, New track, Discard,
        Upgrade all) name their batch as `aiff:<n>`, give each done song the steps only a person can do in rekordbox
        (`results[].person_steps`: a New track's file to relocate to, a Same track's tag to reload) and say them once
        for the whole run. An undo says how many tracks went back; "Done, checked" gives each track a row, `done` or
        `skipped` (nothing to check; `outcome: "ok"` when no track had one), and says that the undo ended. Read only: it looks at the records after the job. A
        method with no words says nothing. Download again and Remove from library (and their preview) give their one line
        (`words`); their rows already carry theirs."""
        if method in ("upgrade", "upgrade_all") and isinstance(result.get("results"), list):
            return self._upgrade_words(result)
        if method == "batch_resume" and isinstance(result.get("results"), list):
            return self._upgrade_words(result)
        if method == "aiff_plan" and isinstance(result.get("plan"), dict):
            plan = result["plan"]  # a dry run that has nothing to change and nothing waiting says so, as the window's panel does
            clean = not (plan.get("total") or plan.get("waiting") or plan.get("skipped")) and "total" in plan
            if clean:
                return {"message": plans.NOTHING_TO_CHANGE}
            if lossy := plan.get("lossy"):  # lossy files grow when they become AIFF (the console's old line)
                return {"message": engine_words.LOSSY_NOTE.format(n=lossy, are="is" if lossy == 1 else "are")}
            return {}
        if method in ("missing_files", "missing_files_preview") and isinstance(result.get("words"), str):
            return {"message": result["words"]}  # the rows already carry their words (`results[].words`, `items[].words`)
        if method in ("undo_upgrade", "batch_undo") and isinstance(result.get("results"), list):
            return self._undo_words(result)
        if method == "rekordbox_checked" and isinstance(result.get("checked"), list):
            return self._checked_words(result)
        if method == "rekordbox_restore" and "saved_current" in result:
            return self._restore_words(result)
        if method == "auto_upgrade_run" and "auto_upgrade" in result:
            return self._phase_words(result)
        if method == "start_sync" and isinstance(result.get("report"), str):
            return self._sync_words(result)
        if method == "auto_upgrade_preview" and "auto_upgrade" in result:
            return {"message": engine_words.AUTO_UPGRADE_OFF} if result["auto_upgrade"] is None else {}
        if method == "set_auto_upgrade" and isinstance(result.get("auto_upgrade"), bool):
            return {"message": engine_words.AUTO_UPGRADE_SET[result["auto_upgrade"]]}
        if method == "removal_preview" and "files" in result:
            return {"message": engine_words.removal_words(result["files"], result["redownload"])}
        if method == "remove_watched_folder" and "files" in result:
            return {"message": f"{engine_words.REMOVED.format(name=result['name'])} "
                               f"{engine_words.removal_words(result['files'], result['redownload'])}"}
        if method == "check_import_folder" and result.get("message"):  # a folder that cannot be watched says why
            return {"message": result["message"]}
        if method == "check_import_folder" and result.get("usable") and result.get("merge_hints"):
            return {"message": " ".join(result["merge_hints"])}  # W5: the watched folders it would take over
        if method == "fill_facts" and "total" in result:
            return self._facts_words(result)
        if method in ("convert", "rename", "make_aiff") and result.get("batch") is None and result.get("total") == 0 \
                and result.get("state") == "done" \
                and not result.get("new_since_plan"):
            return {"message": plans.NOTHING_TO_CHANGE}  # a plan whose files are all clean AIFFs already
        if method in ("convert", "rename", "make_aiff") and isinstance(result.get("results"), list) and result.get("total"):
            return self._upgrade_words(result, aiff=True)
        return {}

    def _sync_words(self, result: dict) -> dict:
        """`sync run`'s words, from the run's report (`report.write_run`'s `.json` beside the `.md` the result names):
        `data.counts` (each report section with a result: its key -> how many), `data.failed` (the errors section's
        results, `text` the result's note) and the outcome by the failures: `partial` when something was done too
        (`report.DONE_SECTIONS`), `failed` when nothing was; no failures, no `outcome` (the run's own). The Auto-upgrade
        phase's batch, the steps only a person can do in rekordbox for it and what to run next are the phase alone's
        (`_phase_steps`). A report that cannot be read says nothing, except that a run that ended with a failing exit
        code is `failed` (it must not answer `ok`)."""
        try:
            data = json.loads(Path(result["report"]).with_suffix(".json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"outcome": "failed"} if result.get("exit_code") else {}
        rows = [r for r in data.get("results") or [] if isinstance(r, dict)]
        counts = {key: n for key, _ in rep.SECTIONS if (n := sum(1 for r in rows if r.get("section") == key))}
        failed = [{"track_id": r.get("track_id"), "artist": r.get("artist") or "", "title": r.get("title") or "",
                   "text": r.get("note") or ""} for r in rows if r.get("section") == "errors"]
        out: dict = {"data": {"counts": counts, "failed": failed}}
        if failed:
            out["outcome"] = "partial" if rep.DONE_SECTIONS & counts.keys() else "failed"
        if isinstance(data.get("auto_upgrade"), dict):
            steps = self._phase_steps(data["auto_upgrade"])
            out["data"].update(steps.get("data") or {})
            out.update({key: steps[key] for key in ("next", "person_steps") if steps.get(key)})
        return out

    def _phase_steps(self, block: dict) -> dict:
        """The Auto-upgrade phase's batch (`data.batch_id`), what to run next (`next`) and the steps only a person can do
        in rekordbox (`person_steps`: the upgrade batch's own words, `_upgrade_words`), each left out when there is none.
        `block` is `auto_upgrade.Outcome.to_dict()`. `sync run --auto-upgrade-only` (`_phase_words`) and a whole
        `sync run` (`_sync_words`) say them through this one rule."""
        rows = block["results"]
        batch = {"batch": block["batch"], "done": block["done"], "total": len(rows), "skipped": 0,
                 "failed": block["failed"], "results": [{"track": r["track"], "state": r["state"],
                                                         "action": r.get("action", "same_track")}
                                                        for r in rows if r["state"] in ("done", "failed")]}
        words = self._upgrade_words(batch) if isinstance(block["batch"], int) else {}
        out: dict = {}
        if "batch_id" in (words.get("data") or {}):
            out["data"] = {"batch_id": words["data"]["batch_id"]}
        if words.get("next"):
            out["next"] = [*words["next"]]
        if words.get("person_steps"):
            out["person_steps"] = words["person_steps"]
        return out

    def _phase_words(self, result: dict) -> dict:
        """`sync run --auto-upgrade-only`: with the switch off, that nothing was moved (`ok`); else the phase's one line
        (`report.auto_upgrade_line`), the run's outcome (`partial` or `failed` by the tracks that failed only: a track
        that waits or was refused is not a failure), its batch, steps and next (`_phase_steps`) and the report to read."""
        block = result["auto_upgrade"]
        if block is None:
            return {"message": engine_words.AUTO_UPGRADE_OFF}
        out: dict = {"outcome": outcomes.run_outcome(block["results"], catalog.AUTO_UPGRADE_PARTIAL),
                     "message": rep.auto_upgrade_line(block) or engine_words.AUTO_UPGRADE_NOTHING}
        steps = self._phase_steps(block)
        if steps.get("data"):
            out["data"] = steps["data"]
        out["next"] = [*(steps.get("next") or ())]
        if result.get("report"):
            out["next"].append({"run": f"report show {result['report']}", "why": "what this run did, track by track"})
        if steps.get("person_steps"):
            out["person_steps"] = steps["person_steps"]
        return out

    @staticmethod
    def _facts_words(result: dict) -> dict:
        """`library facts`: how many files were read, how many could not be."""
        total, filled = result["total"], result["filled"]
        if not total:
            return {"message": engine_words.FACTS_NONE}
        message = engine_words.FACTS_READ.format(n=filled, s="" if filled == 1 else "s")
        if filled < total:
            left = total - filled
            message += " " + engine_words.FACTS_UNREADABLE.format(n=left, s="" if left == 1 else "s",
                                                                 stay="stays" if left == 1 else "stay")
        return {"message": message}

    def _restore_words(self, result: dict) -> dict:
        """`rekordbox restore`: what was put back, where the library as it was is saved, and (when some tracks now point
        at files Discjockey moved to `Superseded/`) the batches to undo first."""
        out: dict = {"message": engine_words.RESTORED.format(backup=result["restored"], saved=result["saved_current"])}
        if result["missing_after"]:
            out["message"] += " " + engine_words.MISSING_AFTER.format(n=len(result["missing_after"]))
            out["next"] = [{"run": "batch list", "why": "the batches to undo so these tracks find their files again"}]
        return out

    def _upgrade_words(self, result: dict, aiff: bool = False) -> dict:
        """The words of an upgrade's batch, a resumed one and (`aiff`) a Convert, Rename or Make all lossless files AIFF
        run: its `batch_id`, what to run next, the steps for the person and the one line that says what was done (an
        AIFF run says it in its own words; it points at `check list` only when a step is left in rekordbox)."""
        out: dict = {}
        results = result["results"]
        if isinstance(result.get("batch"), int):
            batch = f"aiff:{result['batch']}"
            out["data"] = {"batch_id": batch}
            if result.get("state") == "stopped" and result.get("stop_reason") == "busy":
                out["next"] = [{"run": f"batch resume {batch}",
                                "why": "carries on where it stopped, once the other Discjockey is done"}]
            if result.get("done"):
                out["next"] = [*out.get("next", ()), {"run": f"batch show {batch}", "why": "every song of this batch"},
                               *([] if aiff else [{"run": "check list", "why": "what is left to do in rekordbox"}])]
        if aiff:
            out["message"] = engine_words.aiff_summary(results, result["done"], result["skipped"] + result["failed"])
        else:
            parts = [f"{result['done']} of {result['total']} {'song' if result['total'] == 1 else 'songs'} done"]
            parts += [f"{n} {word}" for word, n in (("skipped", result.get("skipped")), ("failed", result.get("failed")))
                      if n]
            out["message"] = ", ".join(parts) + "."
        tracks = library.load_state(self._paths)["tracks"] if self._paths and any(
            r.get("state") == "done" and r.get("action") != "discard" for r in results) else {}
        steps, grouped, rows = [], {"reload_tag": [], "look": []}, []
        for r in results:
            mine = []
            if r.get("state") == "done" and r.get("action") != "discard":  # a discard changes no file, so nothing to check
                its = r.get("path") or (tracks.get(r["track"]) or {}).get("path")  # a placement's row carries none: the song's file now
                new_file = str(self._paths.root / its) if r.get("action") in ("add_new", "place") and its else None
                mine = engine_words.person_steps(r["track"], (tracks.get(r["track"]) or {}).get("rekordbox_check"), new_file)
                for step in mine:
                    (steps if step["id"] == "step:relocate_new" else grouped[step["id"].removeprefix("step:")]).append(step)
            rows.append({**r, "person_steps": mine})
        for name, group in grouped.items():  # one step per kind: reload the tags of these, have a look at those
            if group:
                keys = " ".join(step["then"].removeprefix("check done ") for step in group)
                then = f"check done --batch aiff:{result['batch']}" if isinstance(result.get("batch"), int) else f"check done {keys}"
                steps.append({**outcomes.person_step(name, tracks=keys), "then": then})
        out["data"] = {**out.get("data", {}), "results": rows}
        if steps:
            out["person_steps"] = steps
            if aiff and isinstance(result.get("batch"), int) and result.get("done"):
                out["next"] = [*out.get("next", ()), {"run": "check list", "why": "what is left to do in rekordbox"}]
        return out

    def _undo_words(self, result: dict) -> dict:
        """`track undo`: how many tracks went back; each track that now has its better version waiting again is
        `upgrade list`'s."""
        undone = [r["track"] for r in result["results"] if r.get("state") == "undone"]
        total = len(result["results"])
        out: dict = {"message": f"{len(undone)} of {total} {'track' if total == 1 else 'tracks'} undone."}
        tracks = library.load_state(self._paths)["tracks"] if self._paths and undone else {}
        if any((tracks.get(t) or {}).get("upgrade") for t in undone):
            out["next"] = [{"run": "upgrade list", "why": "the better versions wait there again"}]
        return out

    def _checked_words(self, result: dict) -> dict:
        """`check done`: a row per track (`done`, or `skipped` when it had nothing to check), what the answer says:
        the reminder and the undo of these tracks are over."""
        notes = {r["track_id"]: r.get("note") for r in result.get("results") or ()}
        rows = [{"track": t, "action": "check", "state": "done", "reason": None, "message": notes.get(t)}
                for t in result["checked"]]
        rows += [{"track": t, "action": "check", "state": "skipped", "reason": "nothing_to_check",
                  "message": NOTHING_TO_CHECK_ONE} for t in result.get("not_checked") or ()]
        newer = result.get("newer") or {}
        rows += [{"track": t, "action": "check", "state": "skipped", "reason": "newer_batch",
                  "message": NEWER_CHECK.format(later=b) if b else NEWER_CHECK_STEP.format(track=t)}
                 for t, b in newer.items()]
        checked, skipped = len(result["checked"]), len(result.get("not_checked") or ()) + len(newer)
        if not checked:  # nothing to check is no error (an `--all` with none open, or only such tracks named): ok, total 0
            return {"message": NOTHING_TO_CHECK, "outcome": "ok",
                    "data": {"results": rows, "total": 0, "done": 0, "skipped": skipped, "failed": 0}}
        message = f"{checked} of {len(rows)} tracks checked in rekordbox." if skipped else \
            f"{checked} {'track' if checked == 1 else 'tracks'} checked in rekordbox."
        message += CHECK_ENDS_UNDO
        if skipped:
            message += f" {skipped - len(newer)} had nothing to check." if skipped > len(newer) else ""
            if newer:
                message += f" {len(newer)} belong{'s' if len(newer) == 1 else ''} to a later change."
        return {"message": message, "data": {"results": rows, "total": len(rows), "done": checked, "skipped": skipped,
                                             "failed": 0}}

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

        return {"job_id": self._support_job("update_tools", work).id}

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

        return {"job_id": self._support_job("rollback_tools", work).id}

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
            with library.support_lock(self._support.support), \
                    contextlib.nullcontext() if gone else self._jobs.lock_briefly():  # support first, then library
                c.path.mkdir(parents=True, exist_ok=True)
                library.write_music_folder_held(self._support.support, c.path)
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


class CliApi(HubApi):
    """What the command line calls: every `HubApi` method plus the `cli_first` ones. A separate class, because
    pywebview exposes every public name of the object it is given, and the window sees exactly the contract
    (tests/test_hub_api.py): the window's `HubApi` has none of these."""

    RESOLVERS = {"track": "_resolve_track", "upgrade_way": "_resolve_upgrade_way", "aiff": "_resolve_aiff",
                 "collection": "_resolve_collection", "folder": "_resolve_folder", "batch": "_resolve_batch",
                 "report": "_resolve_report", "since": "_resolve_since", "moves": "_resolve_moves",
                 "place": "_resolve_place", "report_file": "_resolve_report_file"}  # kind -> the method that makes it (grows per group)
    _resume_first = True
    _skipped_check_is_ok = True
    _via = "terminal"

    # --- plans (design §7.1): the command line's call path saves a dry run's plan (`save_plan`) and says when its scan
    # was (`scan_next`); a write method that takes `plan_id` binds it (`HubApi._bind_plan`). Plain methods, not bridge
    # methods: the window's HubApi has none of the public ones

    def save_plan(self, kind: str, answer: Mapping, command: str) -> str | None:
        """Stores the plan of a dry run's `answer` (`plan_store.save`; its `items`, each with a `key`, are the plan's
        items, its `plan_extra` what else the run needs) and returns the id; None when the answer lists no items (a
        what-if or a question is not a plan). `command` is the command line of the dry run, which an expired plan
        says to repeat."""
        items = plan_store.items_of(answer)
        if items is None and isinstance(answer.get("plan"), Mapping):
            items = self._aiff_items(answer["plan"])
        phase = answer.get("auto_upgrade")  # the phase alone (`Outcome`): its rows, keyed by song; `sync_preview`'s is a summary
        if items is None and isinstance(phase, Mapping) and isinstance(phase.get("results"), list):
            items = {r["track"]: dict(r) for r in phase["results"]}
        if items is None or kind in NO_PLAN_COMMANDS:
            return None
        extra = {**(answer.get("plan_extra") or {}), "command": command}
        if answer.get("mode"):  # `upgrade apply`'s two ways are two plans of the same songs
            kind = f"{kind} {answer['mode']}"
        return plan_store.save(self._support.support, kind, self._plan_root(), items, extra)

    @staticmethod
    def _aiff_items(plan: Mapping) -> dict[str, dict] | None:
        """The items of an `aiff_plan` answer (`{plan: AiffPlan}`: each item is keyed by its `track`, the song) as a
        plan's items: the rows `_aiff_plan_run` holds the run against. None when it has no list of them."""
        rows = plan.get("items")
        if not isinstance(rows, list) or not all(isinstance(r, Mapping) and isinstance(r.get("track"), str) for r in rows):
            return None
        return {r["track"]: dict(r) for r in rows}

    # --- the checks before a job (`call._prejob`): a write job's own refusals answered before any job is made. `prejob_<m>`
    # is `<m>`'s checks alone, answered like a method (`{ok: true}` or the problem), changing nothing: a refusal starts
    # no worker and leaves no job record, as the window's refusal starts no job. Plain methods (the window has none).

    @_answering
    def prejob_start_sync(self, plan_id: str | None = None, selected: list | None = None, how_many: str | None = None) -> dict:
        """`start_sync`'s refusals (an unknown or expired plan, action ids without a plan, a bad `how_many`, no stored
        read yet) answered before the job: `{ok: true}` when `start_sync` would start the sync."""
        self._sync_start_checked(plan_id, selected, how_many)
        return {}

    @cli_first
    def result_words(self, method: str, result: dict) -> dict:
        """What the command line says beside a finished write's `result` (design §4.4, §8.3): `{message, data, next,
        person_steps}`, each left out when there is nothing to add. `HubApi._result_words` finds them (the window's jobs
        write the same words into their `result.json`); read only: it looks at the records after the job."""
        return self._result_words(method, result)

    @cli_first
    def auto_upgrade_preview(self) -> dict:
        """`sync run --auto-upgrade-only --dry-run`: what the sync's last phase would do now (`run.auto_upgrade_only` with
        `dry_run`: the records read only, nothing written, no report). `{auto_upgrade, start_note}`: the phase's block
        (`auto_upgrade.Outcome`, `dry_run: true`; its rows are the plan's items, each with its `action`: `same_track` or
        `place`, a missing song's parked better version) or null when Settings' switch is off and no placement is
        coming (with the switch off the block holds the placements alone), and the Sync page's before-start line for
        it (`auto_upgrade.start_note`; null when nothing is coming).
        Settings are read strictly, as a sync reads them: a file it cannot read is `config_invalid`."""
        found = run.auto_upgrade_only(self._paths, load_settings(self._support.settings_file), dry_run=True,
                                      rekordbox=self._rekordbox_services())
        block = found.outcome.to_dict() if found.outcome else None
        return {"auto_upgrade": block, "start_note": auto_upgrade.start_note(block)}

    @cli_first
    def auto_upgrade_run(self, plan_id: str | None = None) -> dict:
        """`sync run --auto-upgrade-only`: the sync's last phase alone (`run.auto_upgrade_only`: no playlists are read,
        the planner never runs) as a write job (kind "auto_upgrade"). The result is `{exit_code, report, auto_upgrade, recovered}`:
        the report's id (`report:<stamp>`: `report show` takes it; null with the switch off) and the phase's block
        (`auto_upgrade.Outcome`; null when Settings' switch is off and no placement was coming, which is read inside the job
        under the library lock; with the switch off the placements run alone, in a batch started by `download_again`).
        rekordbox open: every upgrade of the set waits (`rekordbox_open`), nothing is moved, the job is done. A Stop ends it
        `stopped` once the records are saved. `plan_id` (`--plan`): only the tracks of that plan that still stand run; a
        track whose answer changed waits (`changed`), the ones new since the plan are in `new_since_plan`."""
        only, changed, extra = None, (), {}
        if plan_id is not None:
            preview = self.auto_upgrade_preview()  # a file it cannot read answers its own failure, not `changed`
            if not preview.get("ok"):
                return preview
            only, changed, extra = self._phase_plan(plan_id, preview)

        def work(ctx) -> dict:
            settings = load_settings(self._support.settings_file)
            try:
                found = run.auto_upgrade_only(self._paths, settings, emit=ctx.emit, token=ctx.token,
                                              rekordbox=self._rekordbox_services(), only=only, changed=changed)
            except run.RunCrashed as e:
                ctx.failed_result = {"exit_code": 1, "report": f"report:{e.report.stem}", "auto_upgrade": None,
                                     "recovered": [], **extra}
                raise
            result = {"exit_code": found.code, "report": f"report:{found.report.stem}" if found.report else None,
                      "auto_upgrade": found.outcome.to_dict() if found.outcome else None,
                      "recovered": [[m, ok] for m, ok in found.recovered], **extra}
            if found.code == 130:  # Stop: what was done is saved, the answer is `stopped` and still carries the block
                ctx.failed_result = result
                raise Cancelled()
            return result
        return {"job_id": self._jobs.start("auto_upgrade", work).id}

    def _phase_plan(self, plan_id: str, preview: dict) -> tuple[set[str], tuple[str, ...], dict]:
        """A run with a plan for the phase alone (design §7.1): the songs of the plan that still stand as the dry run saw
        them (`_bind_plan` against the rows `preview`, today's `auto_upgrade_preview`, gives), those whose row is another
        now, and what the result adds (`new_since_plan`). A plan none of whose rows stands is `changed`, as for `upgrade`."""
        block = preview.get("auto_upgrade") or {}
        plan, bound = self._bind_plan(plan_id, {r["track"]: r for r in block.get("results") or ()})
        if plan.items and not bound.run:
            raise OpProblem(PLAN_NOTHING, "changed")
        return set(bound.run), bound.changed, {"new_since_plan": list(bound.new)} if bound.new else {}

    def scan_next(self) -> list[dict]:
        """The `next` of a dry run that planned on the last scan: `library scan` when Library/ or a watched folder was
        changed after that scan (or was never scanned), else nothing. Read only (the folders' modified times against the
        stored scan times); a library that cannot be read says nothing."""
        bound = self._bound
        if bound is None:
            return []
        try:
            with self._move_log() as conn:
                scans = db.scan_times(conn) if conn is not None else [(bound.library, None)]
        except (sqlite3.Error, StateError):
            return []
        for folder, scanned in scans:
            try:
                changed = datetime.fromtimestamp(Path(folder).stat().st_mtime)
                stale = scanned is None or changed > datetime.fromisoformat(scanned)
            except (OSError, ValueError):
                continue  # a drive that is away, or a time that cannot be read: nothing to say
            if stale:
                return [{"run": "library scan", "why": SCAN_OLDER}]
        return []

    @cli_first
    def resolve(self, kind: str, values: list[str]) -> dict:
        """The one place that turns what a person typed into the argument a method takes (the command line never looks
        anything up itself; issue 39 design §3). `kind` is an `Arg.resolve` name of the catalogue, `values` the texts
        in the order typed. Answers `{"kind": kind, "resolved": [...]}`: one resolved argument per value, same order,
        every kind in this one shape. A text no id can be made of is `bad_args` (`unknown_id` / `bad_id_kind`); a kind
        nobody resolves yet is a failure. Kinds so far: `track` (a song key as it is, or the path of a file of the
        library, absolute or relative to the music folder, to its song key) and `collection` (`all`, `unlisted`,
        `playlist:<name>`, `folder:<path>`, to `{view, key}`; an unknown one is `unknown_id`), `place` (`open folder`'s
        word, to the path `reveal` takes) and `report_file` (`report:<stamp>`, `last` or `not-lossless`)."""
        resolver = self.RESOLVERS.get(kind)
        if resolver is None:
            raise OpProblem(f"Discjockey cannot turn {kind} words into an id yet.", "failed")
        extra = {"state": self._state()} if kind == "track" else {}  # the records once for the whole call
        return {"kind": kind, "resolved": [getattr(self, resolver)(text, **extra) for text in values]}

    @cli_first
    def fill_facts(self) -> dict:
        """`library facts`: reads the audio facts of every own file that has none stored (codec, rate, bit depth,
        bitrate: the plans of Convert and the CDJ group need them; files that were there before they were kept have none)
        and stores them, as one write job (kind "facts") under the library lock. A file ffprobe finds no sound in is
        marked and left out until it changes. The result is `{total, filled, unreadable}`: the files that lacked facts,
        those read, those that could not be (a second run: `total` 0). Progress is the import's "facts" phase."""
        self._need_library()

        def work(ctx) -> dict:
            self._begin()  # interrupted steps finished first, as every write job; makes library.db when there is none
            with db.connect(self._paths.db_file, read_only=True) as conn:
                total = db.facts_missing(conn)
            filled = importer.fill_facts(self._paths, emit=ctx.emit, token=ctx.token, probe=self._svc.probe) if total else 0
            return {"total": total, "filled": filled, "unreadable": total - filled}
        return {"job_id": self._jobs.start("facts", work).id}

    @cli_first
    def facts_preview(self) -> dict:
        """The dry run of `library facts`: how many own files lack stored facts (`{total}`). A read: library.db opens
        read-only, nothing is stored, no lock is taken."""
        self._need_library()
        if not self._paths.db_file.exists():
            return {"total": 0}
        with self._move_log() as conn:
            return {"total": db.facts_missing(conn) if conn is not None else 0}

    @cli_first
    def settings_view(self) -> dict:
        """`settings show`: what Settings holds, in the window's words where it has them. Needs no music folder (the
        settings file is the support folder's). `{music_folder, auto_upgrade, read_liked_music, daily_qobuz_limit,
        qobuz_skipped, spotify_skipped, import_skipped, qobuz_last_check, extra, warnings_seen, accounts, labels}`:
        `music_folder` is the chosen folder (null: not chosen yet), `read_liked_music` is the switch as the page shows
        it (on only with a YouTube login), `qobuz_last_check` the last Qobuz login check (`{ok, problem, kbps, at}` or
        null), `extra` Qobuz's one-time extra (`{date, amount}` or null), `warnings_seen` per service the time its
        warning signs were last seen ("Got it"), `accounts` the YouTube and SoundCloud logins that are set up, each
        `{browser, browser_name, profile, profile_name, daily_limit, extra, last_check, liked_only}`, `labels` the
        page's names of the two switches. The file is read strictly as a sync reads it: one that cannot be read is
        `config_invalid`. A read: no lock."""
        settings = load_settings(self._support.settings_file)
        home = self._svc.home
        accounts = {s: {"browser": a.browser, "browser_name": BROWSERS[a.browser], "profile": a.profile,
                        "profile_name": profile_name(a.browser, a.profile, home), "daily_limit": a.daily_limit,
                        "extra": extra_json(a.extra_date, a.extra_amount),
                        "last_check": dict(a.last_check) if a.last_check else None, "liked_only": a.liked_only}
                    for s, a in settings.accounts.items()}
        return {"music_folder": self._music_status()["path"], "auto_upgrade": settings.auto_upgrade,
                "read_liked_music": settings.reads_liked_music, "daily_qobuz_limit": settings.daily_qobuz_limit,
                "qobuz_skipped": settings.qobuz_skipped, "spotify_skipped": settings.spotify_skipped,
                "import_skipped": settings.import_skipped,
                "qobuz_last_check": dict(settings.qobuz_last_check) if settings.qobuz_last_check else None,
                "extra": extra_json(settings.extra_date, settings.extra_amount),
                "warnings_seen": dict(settings.warnings_seen), "accounts": accounts,
                "labels": {"auto_upgrade": engine_words.AUTO_UPGRADE_LABEL,
                           "read_liked_music": engine_words.LIKED_MUSIC_LABEL}}

    @cli_first
    def freshness(self) -> dict:
        """How fresh the answers are, for the command line's `as_of`: `{scanned_at, read_at}`, each an ISO time or None.
        `scanned_at` is when the index was last scanned (a watched folder's last scan), `read_at` when the playlists
        were last read; both come from the stored records, never from a scan or a fetch. None for both while there is no
        music folder, no library.db yet, or nothing was scanned or read."""
        bound = self._bound
        if bound is None:
            return {"scanned_at": None, "read_at": None}
        with self._move_log() as conn:
            scanned, read = db.freshness(conn) if conn is not None else (None, None)
        return {"scanned_at": scanned, "read_at": read}

    def _resolve_track(self, text: str, state: dict | None = None) -> str:
        """A song key as typed, or the path of a file of the library as its key; a well-formed key the records lack is
        `unknown_id` (nothing was looked at: the whole command is `bad_args`)."""
        state = state if state is not None else self._state()
        found = parse_id(text, ("track",))
        if found.kind == "track" and found.value != "-":
            key = str(found.value)
        elif found.kind != "path":
            raise BadId("unknown_id", "A song key is missing: say a key or the path of a file of your library.")
        else:
            key = self._song_holding(text, state)
            if key is None:
                raise BadId("unknown_id", f"Your library has no track with the file {text}.")
        if key not in state["tracks"]:
            raise BadId("unknown_id", engine_words.NO_SONG.format(key=key))
        return key

    def _resolve_collection(self, text: str) -> dict:
        """`--in`: a collection of the Library as `{view, key}`: `all`, `unlisted`, `playlist:<name>` (the folder name of
        a playlists.txt line, any case; a bare name is one too) or `folder:<path>` (a Library folder or a watched
        folder's path; a path inside the music folder may be absolute). A playlist or folder nothing is known by is
        `bad_args`, `unknown_id`, in the words `NO_PLAYLIST` / `NO_FOLDER`."""
        word = text.strip()
        if word in ("all", "unlisted"):
            return {"view": word, "key": None}
        kind, colon, name = word.partition(":")
        name = name.strip() if colon else word
        lines = plans.view_inputs(self._paths, "playlist", None, None, None)[0]
        if kind == "folder" and colon and name:
            return {"view": "folder", "key": self._collection_folder(name)}
        if (kind == "playlist" and colon) or not colon:
            found = next((r.folder for r in lines if fold(r.folder) == fold(name)), None)
            if found is None or not name:
                raise BadId("unknown_id", engine_words.NO_PLAYLIST.format(name=name))
            return {"view": "playlist", "key": found}
        raise BadId("usage", engine_words.BAD_COLLECTION)

    def _resolve_folder(self, text: str) -> int:
        """`folder remove <folder>`: a watched import folder, typed as its path (absolute, `~` or relative to where the
        command runs) or as `folder:<path>`, to its folder id. The Library, a folder nobody watches (or no music folder
        yet) is `bad_args`, `unknown_id`, in the words `NOT_WATCHED` / `LIBRARY_NOT_REMOVABLE`."""
        word = text.strip()
        if word.startswith("folder:"):
            word = word[len("folder:"):].strip()
        if not word:
            raise BadId("usage", engine_words.BAD_FOLDER)
        typed = {fold(os.path.abspath(os.path.expanduser(word))), fold(os.path.realpath(os.path.expanduser(word)))}
        with self._move_log() as conn:
            rows = db.watched_folders(conn) if conn is not None else []
        for f in rows:
            if fold(os.path.normpath(str(f.path))) in typed:
                if f.kind != "import":
                    raise BadId("unknown_id", engine_words.LIBRARY_NOT_REMOVABLE.format(path=word))
                return f.id
        raise BadId("unknown_id", engine_words.NOT_WATCHED.format(path=word))

    def _collection_folder(self, name: str) -> str:
        """The key of the folder view for a typed path (see `_resolve_collection`); BadId when no folder is there."""
        typed = Path(os.path.expanduser(name))
        root = self._paths.root
        if typed.is_absolute() and typed.is_relative_to(root):
            key = typed.relative_to(root).as_posix()
        else:
            key = typed.as_posix()
        key = key.rstrip("/") or key
        if ".." in PurePosixPath(key).parts:  # a way out of the place the typed folder is looked for in
            raise BadId("unknown_id", engine_words.NO_FOLDER.format(path=name))
        lines, _, watched = plans.view_inputs(self._paths, "folder", None, None, None)
        library = root.resolve() / "Library"  # a folder the sidebar has not listed yet (empty): only below Library/
        if views.view_known(self._state(), "folder", key, lines=lines, watched=watched) or (
                not typed.is_absolute() and (root / key).is_dir() and (root / key).resolve().is_relative_to(library)):
            return key
        raise BadId("unknown_id", engine_words.NO_FOLDER.format(path=name))

    def _resolve_place(self, text: str) -> str:
        """`open folder <place>`: the path `reveal` takes. `all` is the Library, `playlist:<name>` (only with the prefix)
        its folder, `folder:<path>` a folder of the collections; `unlisted` is no folder. Any other text is a path, never
        a playlist: relative to the music folder as typed, an absolute one inside the music folder made relative, any
        other absolute one as typed (`reveal` refuses what is no place of the library). A bare word is not
        `_resolve_collection`'s playlist here: `Superseded` is the folder."""
        word = text.strip()
        if word == "all":
            return "Library"
        if word == "unlisted":
            raise BadId("usage", engine_words.NO_PLACE)
        if word.startswith("playlist:"):
            return f"Library/{self._resolve_collection(word)['key']}"
        if word.startswith("folder:"):
            return self._collection_folder(word[len("folder:"):].strip())
        typed = Path(os.path.expanduser(word))
        if typed.is_absolute() and typed.is_relative_to(self._paths.root):
            return typed.relative_to(self._paths.root).as_posix() or "."
        return word

    def _resolve_report_file(self, text: str) -> str:
        """`open report`: `not-lossless` (the buy list) as it is, else a report as `_resolve_report` makes it."""
        return "not-lossless" if text.strip() == "not-lossless" else self._resolve_report(text)

    def _resolve_aiff(self, text: str) -> int:
        """`--batch`: the AIFF batch `aiff:<n>` as its number. A bare number or a move batch is `bad_id_kind`, a batch
        that was never made `unknown_id`."""
        found = parse_id(text, ("aiff",))
        with self._move_log() as conn:
            row = db.aiff_batch(conn, found.value) if conn is not None else None
        if row is None:
            raise BadId("unknown_id", f"There is no AIFF batch {found.value}.")
        return int(found.value)

    def _resolve_moves(self, text: str) -> int:
        """`batch undo moves:<n>`: the move batch as its number. A bare number or an AIFF batch is `bad_id_kind`, a batch
        that was never made `unknown_id`."""
        found = parse_id(text, ("moves",))
        with self._move_log() as conn:
            row = db.batch(conn, found.value) if conn is not None else None
        if row is None:
            raise BadId("unknown_id", f"There is no move batch {found.value}.")
        return int(found.value)

    def _resolve_batch(self, text: str) -> str:
        """`batch show`: a batch as typed, `aiff:<n>` or `moves:<n>` (a bare number is `bad_id_kind`); `batch_detail`
        reads it again and says when no batch has it."""
        parse_id(text, BATCH_KINDS)
        return text.strip()

    def _resolve_report(self, text: str) -> str:
        """`report show`, `open report`: `report:<stamp>`, the bare stamp or `last` (the newest report) as the bare
        stamp. Another kind of id is `bad_id_kind`; a stamp with no report, or `last` with none at all, `unknown_id`."""
        found = parse_id(text, ("report",))
        stamps = [stamp for stamp, _ in self._reports()]
        if found.value == "last":
            if not stamps:
                raise BadId("unknown_id", engine_words.NO_REPORT_YET)
            return max(stamps)
        if found.value not in stamps:
            raise BadId("unknown_id", engine_words.NO_REPORT.format(stamp=found.value))
        return str(found.value)

    def _resolve_since(self, text: str) -> str:
        """`--since`: today, yesterday, `<n>d`, `<n>h`, a date or a time (`since.parse`) as an ISO time with its zone,
        to the second. Anything else is `bad_args`, `usage`, in the words `BAD_SINCE`."""
        return since_mod.parse(text, self._svc.now()).isoformat(timespec="seconds")

    def _resolve_upgrade_way(self, text: str) -> str:
        """`--way`: `same-track` or `new-track` (the snake_case spellings too) as the bridge's mode."""
        found = {"same-track": "same_track", "new-track": "new_track"}.get(text.strip().lower().replace("_", "-"))
        if found is None:
            raise BadId("usage", f"--way is same-track or new-track, not {text}.")
        return found

    def _song_holding(self, text: str, state: dict | None = None) -> str | None:
        """The song key whose file is the path `text` (absolute, or relative to the music folder), else None."""
        root = self._paths.root
        typed = Path(os.path.expanduser(text))
        wanted = os.path.normpath(typed if typed.is_absolute() else root / typed)
        for key, e in (state or self._state())["tracks"].items():
            if e.get("path") and os.path.normpath(root / e["path"]) == wanted:
                return key
        return None

    @cli_first
    def find_tracks(self, words: str | list[str] | None = None, path: str | None = None) -> dict:
        """Finds songs without knowing their ids (design §3, R28): `{rows: [{track_id, artist, title, rel_path, path}],
        total}`, in artist then title order. `words` (one text, or the words of one) match the artist and title
        together, every word somewhere in them, ignoring case and accents ("Beyonce" finds "Beyoncé"; the Library's
        own search ignores case only, this one is a superset of it). `path` (absolute, or relative to the music
        folder) finds the song that holds that file. Songs without a file are found too (`path` and `rel_path`
        null); `path` is absolute, `rel_path` relative to the music folder (null for a file of an import folder, whose
        path is not under it). With no hit, the answer says so (`total` 0) and, when the playlists were read before
        the last change of playlists.txt or more than a day ago (or never), carries `next: sync read`: a song added
        to a playlist since is in no record yet, which is where "why didn't X download?" starts."""
        if isinstance(words, (list, tuple)):
            words = " ".join(words)
        wanted = (words or "").split()
        if not wanted and not path:
            raise BadId("unknown_id", "Say some words of the artist or title, or --path <file>.")
        root = self._paths.root
        state = self._state()
        tracks = state["tracks"]
        keys = list(tracks)
        if path:
            held = self._song_holding(path, state)
            keys = [held] if held is not None else []
        needles = [search_fold(w) for w in wanted]
        rows = []
        for key in keys:
            e = tracks[key]
            haystack = search_fold(f"{e['artist']} {e['title']}")
            if all(n in haystack for n in needles):
                absolute = None if not e.get("path") else str(root / e["path"])
                rows.append({"track_id": key, "artist": e["artist"], "title": e["title"],
                             "rel_path": e["path"] if e.get("path") and not PurePosixPath(e["path"]).is_absolute() else None,
                             "path": absolute})
        rows.sort(key=lambda r: (search_fold(r["artist"]), search_fold(r["title"]), r["track_id"]))
        answer: dict = {"rows": rows, "total": len(rows)}
        if not rows and self._read_is_old():
            answer["next"] = [{"run": "sync read", "why": "the playlists were read before their last change, or more "
                                                          "than a day ago: a song added to one since is in no record yet"}]
        return answer

    @cli_first
    def rekordbox_preview(self, track_id: str | None = None, path: str | None = None) -> dict:
        """What Same track, Convert and Rename would do for one file, and what rekordbox holds for it (design §5.2; the
        engine's `rekordbox/preview.py`): the song `track_id` (its key) or any file `path`, exactly one of them.
        Read only: it decodes the file (a few seconds), takes no library lock, and holds the shared `rekordbox.lock` only
        while master.db is open; with a writer holding it master.db is not opened, `rekordbox.writing` is true and the
        timing `unreadable`. A file the library does not know still gets the rekordbox part. Each entry of the rekordbox
        part has its `folder_path`, its analysis files (`content_file`: `path`, `hash`, `size`, `updated_at`) and its
        `updated_at`; the words (`<fact>_text`) stand beside the facts. A song the library does not know is `refused`,
        a file that is not there `refused` with the reason `file_missing` or `away`, one that cannot be read `failed`."""
        if (track_id is None) == (path is None):
            raise BadId("conflicting_flags" if track_id is not None else "usage",
                        "Say either a song or --path <file>, not both." if track_id is not None
                        else "Say which file: a song of your library or --path <file>.")
        paths = self._paths if track_id is not None else self._bound  # a file needs no music folder
        writing: list[bool] = []

        @contextlib.contextmanager
        def reading():
            with rb_lock.reader_lock(self._support.support) as free:
                if not free:
                    writing.append(True)
                yield free

        answer = rb_preview.preview(paths, track=track_id, path=path, reading=reading)
        if writing:
            answer["rekordbox"]["writing"] = True
        return preview_words(answer)

    # --- does rekordbox match the library? (`rekordbox match`, `library superseded`; `doctor` calls the helpers) ---

    def _read_rekordbox(self, reading: Callable) -> tuple[dict, str | None, object]:
        """`reading(master)` on rekordbox's library, opened as `rekordbox_preview` does (read-only, `rekordbox.lock`
        shared and without waiting: while a writer holds it master.db is never opened). Returns (the `MatchRekordbox`
        part, the words that say why nothing was read or None, what `reading` returned or None). No library on this Mac,
        a library that cannot be read and a writer are all answered here, never raised."""
        def part(state: str, problem: str | None = None, writing: bool = False) -> dict:
            return {"state": state, "state_text": rekordbox_words(state, problem)[0], "writing": writing}

        place = self._svc.rekordbox_place()
        if place is None or not place.db.is_file():
            return part("none"), engine_words.MATCH_NO_REKORDBOX, None
        running = bool(self._svc.rekordbox_running())
        with rb_lock.reader_lock(self._support.support) as free:
            if not free:
                return part("unreadable", writing=True), engine_words.WRITING_WORDS, None
            try:
                return part("ready"), None, rb_match.read(place, running, reading)
            except rekordbox.Unreadable as e:
                state_text, problem_text = rekordbox_words("unreadable", e.problem)
                return part("unreadable", e.problem), problem_text or state_text, None

    def _library_files(self, state: dict) -> dict[str, tuple[str, Path]]:
        """The folded absolute path of every song's current file -> (the song's key, the file's path)
        (`rekordbox.match.classify`'s `library_files`)."""
        root = self._paths.root
        return {fold(str(root / e["path"])): (key, root / e["path"]) for key, e in state["tracks"].items() if e.get("path")}

    def _match_view(self, state: dict, view: str, key: str | None) -> tuple[frozenset[str], frozenset[str]]:
        """What `rekordbox match --in C` narrows to: the folded folders that hold the files of the songs the view shows
        and where each of them goes when it is superseded, and those songs' keys."""
        shown = self._library_view(state, view, key, "", "all", None)
        rows = [r for r in (*shown["rows"], *(shown.get("also") or ())) if r.get("path")]
        root = self._paths.root
        folders: set[str] = set()
        with self._move_log() as conn:
            for r in rows:
                watched = db.watched_root(conn, r["path"]) if conn is not None else None
                folders.add(fold(str((root / r["path"]).parent)))
                folders.add(fold(str(root / planner.superseded_dir(r["path"], watched))))
        return frozenset(folders), frozenset(r["track_id"] for r in rows)

    def _match(self, state: dict, view: str = "all", key: str | None = None) -> dict:
        """`rekordbox_match`'s answer: reads rekordbox's tracks, classifies them against the library's files and puts
        the findings in the words. The one computation `rekordbox_match` and `_match_counts` share."""
        root = self._paths.root
        rb, why, tracks = self._read_rekordbox(lambda library: library.tracks())
        counts = dict.fromkeys(("matched", "missing", "superseded", "away", "not_in_library", "not_in_rekordbox",
                                "outside"), 0)
        entries: list[dict] = []
        if tracks is not None:
            with self._move_log() as conn:
                folders = [f for f in (db.watched_folders(conn) if conn is not None else []) if f.kind == "import"]
            found = rb_match.classify(
                tracks, root=root, roots=[root, *(f.path for f in folders)], library_files=self._library_files(state),
                away_roots=[Path(p) for p in self._away_by_root(folders)], exists=rb_match.present)
            if view != "all" or key is not None:
                near, keys = self._match_view(state, view, key)
                found = [r for r in found if (r.key in keys if r.entry is None
                                               else fold(os.path.dirname(r.entry.folder_path)) in near)]
            for r in found:
                counts[r.kind] += 1
                if r.kind in rb_match.LISTED:
                    entries.append(self._match_row(state, r))
        problems = counts["missing"] + counts["superseded"] + counts["not_in_library"]
        return {"entries": entries, "counts": counts, "rekordbox": rb,
                "text": why or engine_words.match_text(problems, counts["not_in_rekordbox"])}

    def _match_row(self, state: dict, row: rb_match.Row) -> dict:
        """One finding as `MatchRow`: a rekordbox track by its own path, title and artist, a file rekordbox lacks by the
        library's."""
        root = self._paths.root
        if row.entry is not None:
            path, artist, title, rekordbox_id = row.entry.folder_path, row.entry.artist, row.entry.title, row.entry.id
        else:
            song = state["tracks"][row.key]
            path, artist, title, rekordbox_id = str(root / song["path"]), song["artist"], song["title"], None
        try:
            rel = Path(path).relative_to(root).as_posix()
        except ValueError:
            rel = None
        return {"kind": row.kind, "kind_text": engine_words.MATCH_KINDS[row.kind], "path": path, "rel_path": rel,
                "track_id": row.key, "rekordbox_id": rekordbox_id, "artist": artist or None, "title": title or None}

    def _match_counts(self, state: dict) -> tuple[dict | None, str | None]:
        """`rekordbox match`'s counts for the whole library (`MatchCounts`), for `doctor` and `status --ready`, and why
        there are none: (None, the words) when rekordbox has a library here that cannot be read now or is being written,
        (None, None) when it has no library here (nothing to compare)."""
        answer = self._match(state)
        rb = answer["rekordbox"]["state"]
        return (answer["counts"], None) if rb == "ready" else (None, answer["text"] if rb == "unreadable" else None)

    @cli_first
    def rekordbox_match(self, view: str = "all", key: str | None = None) -> dict:
        """Does rekordbox match your files? (design §5.3; `rekordbox.match`): the rekordbox tracks whose file is missing,
        is in `Superseded/`, is on a drive that is not connected or is in your music folder but no song's file, and
        the files of your library that no rekordbox track holds. A track whose file is there but elsewhere (your own
        files) is counted (`counts.outside`) and never listed. `view` and `key` narrow it to a collection (`--in`): the
        tracks in the folders of its songs' files and of their Superseded/ places, and its songs' files that rekordbox
        lacks. Read only: master.db is opened read-only under the shared `rekordbox.lock`; with a writer holding it
        nothing is read and `rekordbox.writing` is true. No rekordbox library, one that cannot be read or a writer:
        `entries` empty, `counts` 0 and `text` says why."""
        return self._match(self._state(), view, key)

    def _superseded_files(self) -> list[tuple[Path, int]]:
        """The files under `<music folder>/Superseded/` (dot files and folders skipped) with their sizes, by path."""
        found: list[tuple[Path, int]] = []
        for folder, names, files in os.walk(self._paths.superseded):
            names[:] = [n for n in names if not n.startswith(".")]
            for name in files:
                path = Path(folder) / name
                try:
                    stat = path.lstat()
                except OSError:
                    continue
                if not name.startswith(".") and S_ISREG(stat.st_mode):
                    found.append((path, stat.st_size))
        return sorted(found, key=lambda f: f[0].relative_to(self._paths.superseded).as_posix())

    def _superseded_size(self) -> tuple[int, int]:
        """(how many files, how many bytes) `Superseded/` holds: the numbers `library superseded` prints, for `doctor`."""
        files = self._superseded_files()
        return len(files), sum(size for _, size in files)

    @cli_first
    def library_superseded(self) -> dict:
        """What sits in `Superseded/`: the files (never deleted by Discjockey: `note` says so), their sizes and, for
        each, how many rekordbox tracks still point at it (`rekordbox`; 0 for all when rekordbox cannot be read, which
        `rekordbox.state` says). `next` says how to show them in the Finder and, when rekordbox still uses some, which
        tracks (`rekordbox match`). No folder or an empty one: no files and `text` says it is empty."""
        files = self._superseded_files()
        rb, _, index = self._read_rekordbox(lambda library: library.index())
        root = self._paths.root
        rows = [{"path": str(path), "rel_path": path.relative_to(root).as_posix(), "size": size,
                 "size_text": convert.size_text(size),
                 "rekordbox": len(index.by_path.get(fold(str(path)), ())) if index is not None else 0}
                for path, size in files]
        size, held = sum(r["size"] for r in rows), sum(1 for r in rows if r["rekordbox"])
        readable = rb["state"] != "unreadable"  # no library at all still answers "none of them"
        answer = {"files": rows, "total": len(rows), "size": size, "size_text": convert.size_text(size), "held": held,
                  "rekordbox": rb, "note": engine_words.DELETE_SUPERSEDED,
                  "text": engine_words.superseded_text(len(rows), size, held if readable else None)
                  if rows else engine_words.NO_SUPERSEDED}
        if rows:
            answer["next"] = [{"run": "open folder Superseded", "why": engine_words.SUPERSEDED_WHY_OPEN},
                              *([{"run": "rekordbox match", "why": engine_words.SUPERSEDED_WHY_MATCH}]
                                if held else [])]
        return answer

    def _unreadable_roots(self, folders: Iterable[Path]) -> tuple[str, ...]:
        """The folders among `folders` that macOS does not let this process list (a `PermissionError`: the app the command
        runs in was not allowed into them). A folder that is not there or fails otherwise is another check's finding."""
        found = []
        for folder in folders:
            try:
                with os.scandir(folder) as entries:
                    next(entries, None)
            except PermissionError:
                found.append(str(folder))
            except OSError:
                continue
        return tuple(found)

    @cli_first
    def doctor(self) -> dict:
        """Everything that is wrong, and what to do about it (design §5.3; `hub/doctor.py` holds the checks): the setup
        (music folder, programs, logins), the machine (whether each root can be read, rekordbox, a lock held by something
        the job list does not know, jobs that stopped without finishing this week) and, with a music folder, the library
        itself: cut-off file steps, watched folders on a drive that is not connected, a source paused today, files out
        of place, Superseded/, rekordbox tracks on missing or superseded files, stopped batches, open rekordbox checks,
        files that won't play well on CDJs, songs without a file and better versions waiting. Works without a music
        folder: the checks that need one are `skipped` and `music_folder` says why. Read only: it takes `rekordbox.lock`
        shared to read rekordbox's state, finishes no cut-off step and takes no other lock; the library checks come from
        `library.db` opened read-only."""
        return self._doctor(None)

    def _doctor(self, dashboard: dict | None) -> dict:
        """`doctor`'s answer. `dashboard`: the Dashboard's answer when the caller has built it already (`status`), so
        the library checks read the number of songs still to load from it and the plan is not derived twice."""
        music = self._music_status()
        bound = music["state"] == "ok"
        present = self._tool_presence()
        rows: list[WatchedFolder] = []
        pending = False
        facts = self._NO_LIBRARY_FACTS
        paused: frozenset[str] = frozenset()
        records_problem = None
        if bound:
            try:
                state = self._state()  # the one read of the records: everything below reads from the same file
                with self._move_log() as conn:
                    if conn is not None:
                        rows, pending = db.watched_folders(conn), db.has_pending(conn)
                paused = self._paused_accounts(state)
                facts = self._library_facts(state, dashboard)
            except StateError as e:  # library.db cannot be read: `doctor` says so and skips what reads it
                rows, pending, facts, records_problem = [], False, self._NO_LIBRARY_FACTS, str(e)
            facts = {**facts, **self._superseded_facts()}  # a folder walk: it needs no records
        away = self._away_folders(rows)
        place = self._svc.rekordbox_place()
        roots = [*([self._paths.root] if bound else []), *(f.path for f in rows if f.id not in away),
                 *([place.db.parent] if place is not None else [])]
        status = self._rekordbox_status()
        registry_ = self._jobs.registry
        listed = registry_.list(self._paths.root if bound else None) if registry_ is not None else []
        return doctor_mod.answer(doctor_mod.Inputs(
            music_state=music["state"], music_path=music["path"] or "",
            missing_tools=tuple((tool, TOOL_HINTS[tool]) for tool, there in present.items() if not there),
            downloads=self._downloads(records_problem is None),
            paused_accounts=paused,
            unreadable_folders=self._unreadable_roots(roots), app=engine_words.running_app(os.environ),
            rekordbox_state=status.state, rekordbox_problem=status.problem, lock_holder=self._jobs.console_holder(),
            jobs=tuple(doctor_mod.JobRow(str(s.get("id")), str(s.get("status")), str(s.get("started")))
                       for s in listed),
            now=self._svc.now(), pending=pending, away_folders=tuple(str(f.path) for f in rows if f.id in away),
            records_problem=records_problem, **facts), bound)

    # what `Inputs` holds while no music folder is bound (the checks that read it are skipped then)
    _NO_LIBRARY_FACTS = {"tidy_rows": 0, "superseded_files": 0, "superseded_bytes": 0, "rekordbox_match": None,
                         "rekordbox_match_why": None, "stopped_batches": (), "check_tracks": 0, "cdj_files": 0,
                         "missing_files": 0, "upgrades_ready": 0, "to_load": 0}

    def _superseded_facts(self) -> dict:
        files, size = self._superseded_size()
        return {"superseded_files": files, "superseded_bytes": size}

    def _library_facts(self, state: dict, dashboard: dict | None) -> dict:
        """The facts of `doctor`'s checks (`Inputs`) that come from the library's records, each read once: the To-do
        answer's counts, the tidy-up's rows, rekordbox's match counts (and why there are none), the stopped AIFF batches
        and the Dashboard's songs still to load. `state`: the snapshot already read."""
        todo = self._todo(state, None, False)
        if dashboard is None:
            dashboard = self._dashboard_view()
        match, match_why = self._match_counts(state)
        return {"tidy_rows": len(planner.tidy_rows(state)), "rekordbox_match": match, "rekordbox_match_why": match_why,
                "stopped_batches": tuple(r["id"] for r in self._batch_rows("aiff") if r["state"] == "stopped"),
                "check_tracks": todo["check_tracks"], "cdj_files": todo["chips"]["cdj"],
                "missing_files": todo["chips"]["missing_file"], "upgrades_ready": todo["chips"]["upgrade_ready"],
                "to_load": dashboard["tiles"]["still_to_load"]["count"] or 0}

    @cli_first
    def status_view(self, ready: bool = False) -> dict:
        """What the window's Dashboard and navigation show, the jobs that run now and what needs a person (design §5.3):
        `{dashboard, nav, jobs, ready}` and, while a running job waits for something only a person can do,
        `person_steps` (its live steps, as `job show` says them). `dashboard` is `dashboard()`'s answer; `nav` the
        sidebar's four numbers (`todo`, `all_tracks`, `not_in_playlist`, `limits_warning`); `jobs` every job of this music
        folder that has not ended (`queued`, `running`, `stopping`), newest first, with `line`, its progress in one line.
        `ready` (the command line's `--ready`, "is my library ready for a gig?") is the problems of `doctor` that a gig
        depends on, taken from the same `doctor` call (never a count of its own), none when it is ready; null without it;
        `ready_text` says the verdict in one sentence (with `--ready` only).
        Read only: with `ready` it takes `rekordbox.lock` shared as `doctor` does."""
        dashboard = self._dashboard_view()
        sidebar = self._sidebar_view()
        registry_ = self._jobs.registry
        states = [s for s in registry_.list(self._paths.root) if s.get("status") in registry.ACTIVE] if registry_ else []
        answer = {"dashboard": dashboard,
                  "nav": {k: sidebar[k] for k in ("todo", "all_tracks", "not_in_playlist", "limits_warning")},
                  "jobs": [{"id": s["id"], "command": s["command"], "via": s["via"], "status": s["status"],
                            "line": (s.get("progress") or {}).get("line"), "started": s["started"]} for s in states],
                  "ready": [p for p in self._doctor(dashboard)["problems"] if p["gig"]] if ready else None}
        if answer["ready"] is not None:
            answer["ready_text"] = engine_words.ready_text(len(answer["ready"]))
        if steps := [step for s in states for step in s.get("person_steps") or ()]:
            answer["person_steps"] = steps
        return answer

    @cli_first
    def select_listing(self, listing: dict) -> dict:
        """Which songs a listing selects (design §7.3: `--rows` and `--all` of a bulk write): `{ids}`, every song the
        screen of that listing shows, each once, in the order shown (`hub/select.py` says the words of a listing: the
        Library's `in` / `search` / `quality`, To-do's `group` / `hidden`, or a verb's own "all"). Read only, on the last
        scan; the answer is what `library list` / `todo list` with the same words print, a playlist's `also` rows
        included and the rows without a file left out. A verb's "all" that selects none adds `message`, what the window
        says then. Rename's "all" with a `plan` (the command line's `--plan`) answers the plan's songs too, after today's.
        (`select` is the window's own call, which tells the hub where a dropped file goes.)"""
        want = select.parse(listing)
        state = self._state()
        if want.verb_all == select.UPGRADE_ALL:
            return self._nothing_left({"ids": self._upgrade_all_ids(state)}, NO_UPGRADES)
        if want.verb_all == select.CHECK_DONE:
            return self._nothing_left({"ids": select.check_done_ids(self._todo(state, ("rekordbox_check",), False))},
                                      NOTHING_TO_CHECK)
        if want.verb_all in (select.DOWNLOAD_AGAIN, select.REMOVE_MISSING):
            ids = (select.download_again_ids if want.verb_all == select.DOWNLOAD_AGAIN else select.remove_missing_ids)(
                self._todo(state, ("missing_file",), False))
            return self._nothing_left({"ids": ids}, NO_MISSING_LEFT[want.verb_all])
        if want.verb_all == select.RENAME_ALL:
            ids = self._rename_all_ids(state, want.view, want.key)
            if want.plan is not None:  # a run with a plan answers for the plan's songs too (design §7.1)
                plan = self._bind_plan(want.plan, {})[0]
                ids = [*ids, *(k for k in plan.items if k not in ids)]
            return self._nothing_left({"ids": ids}, plans.NOTHING_TO_CHANGE)
        if want.source == "todo":
            return {"ids": select.todo_ids(self._todo(state, None if want.group == "all" else (want.group,), want.hidden))}
        view, key = want.view, want.key
        if view == "folder":
            key = self._folder_key(key or "")
        elif view == "playlist":  # a playlist nothing is called is `unknown_id`, not an empty list
            key = self._resolve_collection(f"playlist:{key}")["key"]
        return {"ids": select.library_ids(self._library_view(state, view, key, want.search, want.quality, None))}

    def _rename_all_ids(self, state: dict, view: str, key: str | None) -> list[str]:
        """What Rename all gives its clean name: the own clean AIFFs of the collection whose name isn't clean, as Rename's
        own answer says (`aiff_plan` with `only` rename, on files whose facts are read in memory). The collection is
        resolved as `--in` does (`_resolve_collection`: an unknown playlist or folder is `unknown_id`)."""
        found = self._resolve_collection(view if key is None else f"{view}:{key}")
        scope = {"kind": "lossless", **found}
        return [i.track for i in self._planned_reading(state, scope, "rename").items]

    @staticmethod
    def _nothing_left(answer: dict, words: str) -> dict:
        """A verb's "all" that selects no song says so in the window's words (`message`): a command that finds nothing
        left to do answers `ok` with that, not `refused` (design §4.3, R29)."""
        return answer if answer["ids"] else {**answer, "message": words}

    def _folder_key(self, typed: str) -> str:
        """The key the Library's folder view takes for a folder typed as `folder:<path>`: a path inside the music folder
        is `Library/<name>` as the sidebar writes it (the typed path may be absolute or relative to the music folder),
        any other path stays as it is (a watched import folder, a crate)."""
        path = Path(os.path.expanduser(typed))
        if path.is_absolute():
            try:
                return path.relative_to(self._paths.root).as_posix()
            except ValueError:
                return str(path)
        return PurePosixPath(os.path.normpath(typed)).as_posix()

    @cli_first
    def upgrade_preview(self, track_ids: list[str] | None = None, mode: str = "same_track", all: bool = False) -> dict:
        """What an upgrade would do, answered before it runs (design §7.1: the dry run of `upgrade apply`, and what Upgrade
        all would start): `{mode, total, planned, skipped, items, space, rekordbox}` (`batches.upgrade_preview`). One
        item per song, `{key, action, state: planned | skipped, reason, file, new_file, superseded}`; `space` is what the
        new files need per drive; `rekordbox.needs_rekordbox_closed` says a Same track must wait for rekordbox to be
        quit. `mode` `same_track`, `new_track` or `discard` (Discard's items: the current file that stays and the parked
        download that is deleted); `all` the songs Upgrade all would run (Same track
        only), instead of `track_ids`. Reads only: no file is decoded, nothing is stored."""
        if mode not in (*batches.PREVIEW_MODES, "discard"):
            raise BadId("usage", f"mode must be one of {', '.join((*batches.PREVIEW_MODES, 'discard'))}.")
        if all and track_ids:
            raise BadId("conflicting_flags", "Name the songs, or ask for all of them: not both.")
        if all and mode != "same_track":
            raise BadId("conflicting_flags", select.ALL_IS_SAME_TRACK)
        state = self._state()
        if all:
            ids = self._upgrade_all_ids(state)
        elif track_ids is None:
            raise BadId("usage", "Name the songs, or ask for all of them.")  # `[]` is a list that picked none
        else:
            ids = self._track_list(track_ids) if track_ids else []  # no songs (a selection that found none): total 0
        if mode == "discard":
            return batches.discard_preview(self._paths, state, ids)
        return batches.upgrade_preview(self._paths, state, ids, mode, self._rekordbox_status())

    @cli_first
    def undo_upgrade_preview(self, track_ids: list[str]) -> dict:
        """What `undo_upgrade` of these songs would do, before it runs (design §7.4: the dry run of `track undo`):
        `{total, planned, skipped, items, rekordbox}` (`batches.track_undo_preview`). One item per song, `{key, action:
        "undo", state: planned | skipped, reason, message, file, step}`: a song `upgrades.can_undo` says no to is
        `skipped` with its reason and words. Reads only; whether a file changed since is only known when the undo runs."""
        ids = self._track_list(track_ids)
        return batches.track_undo_preview(self._state(), ids, self._svc.rekordbox_running(), self._paths.root)

    @cli_first
    def batch_undo_preview(self, batch_id: int) -> dict:
        """What `batch_undo` of this AIFF batch would do, before it runs (design §7.4: the dry run of `batch undo
        aiff:<n>`): `{batch: "aiff:<n>", total, planned, skipped, items, rekordbox}` as `undo_upgrade_preview` answers it, one
        item per `done` song of the batch, newest first (the order an undo goes). A song `upgrades.can_undo` says no to is
        `skipped` with its reason and words. Reads only; whether a file changed since is only known when the undo runs."""
        self._stopped_aiff(batch_id)
        return batches.batch_undo_preview(self._paths, self._state(), batch_id, self._svc.rekordbox_running())

    @cli_first
    def rekordbox_backups(self) -> dict:
        """The copies of rekordbox's library Discjockey made, newest first (each batch that wrote rekordbox keeps one; a
        restore saves the library it replaced as one): `{backups: [{id, created, batches, tracks, size}]}`. `id` is the name
        `rekordbox_restore` takes, `batches` the AIFF batches (ids) that wrote under it, `tracks` how many tracks' analysis
        files it holds and `size` its bytes. Reads only the backups' own folders under `.discjockey/`: no lock, rekordbox's
        library is never opened."""
        return {"backups": [{"id": b.id, "created": b.created, "batches": b.batches, "tracks": b.tracks, "size": b.size}
                            for b in rb_backup.backups(self._paths)]}

    @cli_first
    def rekordbox_restore(self, backup: str) -> dict:
        """The last resort (design §7.4: `rekordbox restore <backup> --yes`): puts rekordbox's whole library back as the
        backup holds it, as one write job (kind "rekordbox_restore"). Needs rekordbox closed (`rekordbox_open`); another
        Discjockey process changing rekordbox's library is `busy`; a library that is not this Mac's, a damaged backup, one
        left by a crash (`unclean`) or no rekordbox library at all is `refused` (`data.why` names which). Saves the current
        library first. The result is `{restored, saved_current, missing_after, recovered}`; `missing_after` lists the tracks
        that now point at a file that is not there (`[{id, path, was}]`: Discjockey moved it to `Superseded/` since). A
        name no backup has is `bad_args` / `unknown_id`, before anything starts."""
        if rb_backup.find(self._paths, backup) is None:
            raise BadId("unknown_id", engine_words.RESTORE_REFUSED["not_found"])

        def work(ctx) -> dict:
            state, recovered = self._begin()
            try:
                done = rb_backup.restore(self._paths, self._svc.rekordbox_place(), backup,
                                         running=self._svc.rekordbox_running)
            except rb_backup.RestoreRefused as e:
                raise self._restore_refusal(e) from None
            except rb_backup.WriteRefused as e:  # master.db changed while the current library was saved: nothing written
                raise OpProblem(engine_words.RESTORE_REFUSED["changed"], "refused", data={"why": e.reason}) from None
            return {"restored": backup, "saved_current": done.saved_current, "missing_after": done.missing_after,
                    "recovered": recovered}
        return {"job_id": self._jobs.start("rekordbox_restore", work).id}

    @cli_first
    def rekordbox_restore_preview(self, backup: str) -> dict:
        """What `rekordbox_restore` of this backup would leave behind, before it runs (the dry run of `rekordbox restore`):
        `{backup, missing_after, rekordbox}`. `missing_after` is the restore's own list (`[{id, path, was}]`: the tracks
        that would point at a file that is not there), `rekordbox` is `{running, needs_rekordbox_closed}`: a restore only
        runs with rekordbox quit. Takes no lock beyond the shared `rekordbox.lock` while master.db is read; with a writer
        holding it master.db is not opened: `missing_after` is null and `rekordbox.writing` true; a library that can't be read
        (it is what a restore can repair) gives null and `rekordbox.unreadable` true. Nothing is saved or
        changed. The refusals of the restore itself (a damaged backup, another library, no rekordbox library) are
        `refused`; a name no backup has is `bad_args` / `unknown_id`."""
        running = bool(self._svc.rekordbox_running())
        shown = {"running": running, "needs_rekordbox_closed": True}
        with rb_lock.reader_lock(self._support.support) as free:
            if not free:
                return {"backup": backup, "missing_after": None, "rekordbox": {**shown, "writing": True}}
            try:
                missing = rb_backup.preview(self._paths, self._svc.rekordbox_place(), backup, running)
            except rb_backup.RestoreRefused as e:
                if e.reason == "not_found":
                    raise BadId("unknown_id", engine_words.RESTORE_REFUSED["not_found"]) from None
                raise self._restore_refusal(e) from None
        if missing is None:  # the current library can't be read: what a restore would leave missing is not known
            return {"backup": backup, "missing_after": None, "rekordbox": {**shown, "unreadable": True}}
        return {"backup": backup, "missing_after": missing, "rekordbox": shown}

    @staticmethod
    def _restore_refusal(e: "rb_backup.RestoreRefused") -> OpProblem:
        """A restore's refusal as the problem the answer carries: rekordbox open needs the person; the rest is `refused`
        with the engine's words and `data.why` (`unclean` is also its own reason)."""
        words = engine_words.RESTORE_REFUSED[e.reason]
        if e.reason == "rekordbox_open":
            return OpProblem(words, "rekordbox_open")
        return OpProblem(words, "refused", reason="unclean" if e.reason == "unclean" else None, data={"why": e.reason})

    @cli_first
    def batches(self, kind: str | None = None, since: str | None = None) -> dict:
        """The batches Discjockey made, AIFF batches (Same track, Convert, Rename) and move batches (tidy-ups, saves,
        folder renames, undos) in one list, newest first (`kind`: `aiff` or `moves` for one of them; `since`: an ISO time,
        the command line's `--since` resolves to one, keeps the batches that started at or after it). `{batches, total}`;
        `total` counts every batch of the kind and since asked for (the list is as long: `--json` pages it, the envelope's
        `page` says where). A row: `id` (`aiff:12` or `moves:12`, the id every other command takes), `kind`, `what` (an
        AIFF batch's `upgrade` | `convert` | `mixed`; a move batch's title), `started_by`, `state` (`running` |
        `stopped` | `done`), `stop_reason`, `started`, `ended`, `total`, `done`, `skipped`, `failed`, `planned`, `undone`
        (items; for a move batch `done` is the files moved), `backup` (the rekordbox backup an AIFF batch made), `via`
        (`window` | `terminal`: where it started), `scope` (what was picked for an AIFF batch: `selection`,
        `library:<view>[:<key>]`, `todo:cdj`, …; null for a move batch), and for a move batch `undone_by` (the id of the
        batch that undid it)."""
        if kind not in (None, *BATCH_KINDS):
            raise BadId("usage", f"A batch kind is aiff or moves, not {kind}.")
        rows = [r for r in self._batch_rows(kind) if since_mod.after(r["started"], since)]
        return {"batches": rows, "total": len(rows)}

    def _batch_rows(self, kind: str | None = None) -> list[dict]:
        """Every batch of `kind` (None: both) as a `BatchRow`, newest first."""
        rows: list[dict] = []
        with self._move_log() as conn:
            if conn is not None:
                if kind in (None, "aiff"):
                    rows += [views.aiff_batch_row(b) for b in db.aiff_batches(conn, -1)[0]]  # SQLite's LIMIT -1: no limit
                if kind in (None, "moves"):
                    rows += [self._moves_batch_row(conn, b) for b in db.batches(conn, -1)[0]]
        rows.sort(key=lambda r: (r["started"], r["batch"], r["kind"]), reverse=True)
        return rows

    def _moves_batch_row(self, conn, b: BatchRow) -> dict:
        return views.moves_batch_row(b, self._batch_title(conn, b), db.planned_moves(conn, b.id))

    @cli_first
    def batch_detail(self, batch: str) -> dict:
        """One batch by its typed id (`aiff:12` or `moves:12`; a bare number is `bad_args`: the two kinds count
        separately): its row as `batches` lists it, and under `results` (an AIFF batch: each item with its `name`,
        `action`, `state`, `reason`, `message`, the new file's `path` and what was written to rekordbox,
        `rekordbox.entries` and `kept`) or `moves` (a move batch: each move as the records keep it, with `text` for
        one that was not made). An id no batch has is `bad_args` / `unknown_id`."""
        found = parse_id(batch, BATCH_KINDS)
        paths = self._paths
        with self._move_log() as conn:
            if found.kind == "aiff":
                row = db.aiff_batch(conn, found.value) if conn is not None else None
                if row is None:
                    raise BadId("unknown_id", f"There is no AIFF batch {found.value}.")
                tracks = self._state()["tracks"]
                result = batches.result_of(paths, found.value).to_dict()
                items = [{**item, "name": self._track_name(tracks, item["track"])} for item in result["results"]]
                return {**views.aiff_batch_row(row), "results": items}
            row = db.batch(conn, found.value) if conn is not None else None
            if row is None:
                raise BadId("unknown_id", f"There is no move batch {found.value}.")
            return {**self._moves_batch_row(conn, row), "moves": views.batch_moves(db.batch_moves(conn, found.value))}

    @cli_first
    def history(self, since: str | None = None) -> dict:
        """What changed, newest first, and how to undo it: the sync runs, the batches (AIFF and moves) and the single
        steps of the operations log that no AIFF batch made (`history.entries` holds the rule). `since` is an ISO time
        (the command line's `--since` resolves to one). An entry: `kind` (`run` | `batch` | `operation`), `id` (what the
        commands take; null for a step), `at`, `text`, `undo` (the command that undoes it) or `cant_text` (why nothing
        does: exactly one is set), and for a step `track_id`, `artist`, `title`. A change to playlists.txt is a step whose
        `text` is its logged message and whose `undo` carries `--if-version <the file's version>`."""
        def built(method: str | None, command: str) -> bool:
            if method is None:  # the words of a change's undo name no method: a command the line runs, not a dry run alone
                return any(" ".join(e.command) == command and not e.planned and e.kind not in ("W", "dropped")
                           and not catalog.stands_in(e) for e in catalog.ENTRIES)
            entry = catalog.entry_of(method, command)
            return entry is not None and entry.planned is None

        paths = self._paths
        rows = self._batch_rows()
        results = {r["batch"]: batches.result_of(paths, r["batch"]).results for r in rows if r["kind"] == "aiff"}
        batch_tracks = {n: frozenset(i.track for i in items) for n, items in results.items()}
        batch_actions = {n: frozenset(i.action for i in items) for n, items in results.items()}
        with self._move_log() as conn:  # a move batch whose files moved again has done moves and nothing to undo
            move_undoable = {} if conn is None else {b.id: b.undoable for b in db.batches(conn, -1)[0]}
        found = history_mod.entries(
            views.runs(self._reports()), rows, self._operations(), tracks=self._state()["tracks"],
            batch_tracks=batch_tracks, batch_actions=batch_actions, move_undoable=move_undoable,
            finished_order=batches.finished_order(paths), built=built, now=self._svc.now(), since=since,
            current={"playlists": pf.load(paths.playlists_file).version})
        return {"entries": found, "since": since}

    def _operations(self) -> list[tuple[int, dict]]:
        """The lines of the operations log with their 0-based line numbers (the numbering `batches.finished_order`
        uses); a line that cannot be read is skipped and its number kept."""
        try:
            lines = self._paths.operations_log.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for n, line in enumerate(lines):
            try:
                op = json.loads(line)
            except ValueError:
                continue
            if isinstance(op, dict):
                out.append((n, op))
        return out

    @staticmethod
    def _track_name(tracks: dict, key: str) -> str:
        e = tracks.get(key)
        return f"{e['artist']} - {e['title']}" if e else key

    def _read_is_old(self) -> bool:
        """Whether the last read of the playlists is older than a day or than playlists.txt's last change (or there was
        none)."""
        read_at = self.freshness()["read_at"]
        if read_at is None:
            return True
        read = datetime.fromisoformat(read_at)
        if self._svc.now() - read > timedelta(days=1):
            return True
        try:
            return datetime.fromtimestamp(self._paths.playlists_file.stat().st_mtime) > read
        except OSError:
            return False
