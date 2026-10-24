"""Everything about the library on disk: where things live (the music folder, its .discjockey/, the support
folder), the lock, its records (library.db through db.py; state.json before the migration), names, safe renames,
the scan."""
from __future__ import annotations

import fcntl
import itertools
import json
import os
import shutil
import signal
import sqlite3
import stat
import threading
import time
import unicodedata
from collections.abc import Callable, Collection, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from .content_key import content_key
from .events import Emit, Message, no_emit
from .models import ScanSummary
from .names import fold

STATE_VERSION = 1


SUPPORT_ENV = "DISCJOCKEY_SUPPORT"  # tests and developer runs against a scratch library
DATA_DIR = ".discjockey"  # the library's own files inside the music folder


@dataclass(frozen=True, kw_only=True)
class SupportPaths:
    """What belongs to this Mac and user, not to one library (spec public-release §4): the music folder's place,
    settings, logins, caches. ~/Library/Application Support/Discjockey, or $DISCJOCKEY_SUPPORT."""
    support: Path

    @property
    def config_file(self) -> Path:
        return self.support / "config.json"

    @property
    def settings_file(self) -> Path:
        return self.support / "settings.json"

    @property
    def spotify_app(self) -> Path:
        return self.support / ".spotify_app.json"

    @property
    def spotify_token(self) -> Path:
        return self.support / ".spotify_token.json"

    @property
    def streamrip_dir(self) -> Path:
        return self.support / "streamrip"

    @property
    def cache(self) -> Path:
        return self.support / "cache"

    @property
    def window_file(self) -> Path:
        """The window's page-server port, kept so its saved settings keep their address (hub/window_port.py)."""
        return self.support / "window.json"

    @property
    def window_lock(self) -> Path:
        """Held while a Discjockey window uses this support folder (hub/window_port.py)."""
        return self.support / ".window.lock"


@dataclass(frozen=True)
class Paths(SupportPaths):
    """One library: `root` is the music folder the user chose (what rekordbox points at), with Discjockey's own files
    for it in root/.discjockey/; `support` is this Mac's support folder. Every path in state.json is relative to
    root. .tmp/ is inside root on purpose: run_op renames from it into Library/, which is only atomic on one drive."""
    root: Path

    @property
    def db_file(self) -> Path:
        """The library's records (db.py owns what is in it)."""
        return self.data / "library.db"

    @property
    def state_backup(self) -> Path:
        """state.json as it was when it moved into library.db (the migration's backup)."""
        return self.data / "state.v1.json"

    @property
    def library(self) -> Path:
        return self.root / "Library"

    @property
    def superseded(self) -> Path:
        return self.root / "Superseded"

    @property
    def upgrades_ready(self) -> Path:
        return self.root / "Upgrades ready"

    @property
    def playlists_file(self) -> Path:
        return self.root / "playlists.txt"

    @property
    def data(self) -> Path:
        return self.root / DATA_DIR

    @property
    def state_file(self) -> Path:
        """Before the migration the records; after it a stub that stops an older Discjockey."""
        return self.data / "state.json"

    @property
    def tmp(self) -> Path:
        return self.data / ".tmp"

    @property
    def reports(self) -> Path:
        return self.data / "reports"

    @property
    def not_lossless_md(self) -> Path:
        return self.data / "not_lossless.md"

    @property
    def lock(self) -> Path:
        return self.data / ".lock"

    @property
    def operations_log(self) -> Path:
        return self.reports / "operations.jsonl"


@dataclass(frozen=True)
class Resolved:
    """Where Discjockey stands when it starts: `paths` when the chosen music folder is there; otherwise `problem` says
    why not — "not_chosen" (no folder chosen yet: Setup's first step) or "missing" (config.json names a folder that
    isn't there, e.g. on an unplugged drive; `music_folder` is that folder)."""
    support: Path
    paths: Paths | None
    problem: str | None
    music_folder: Path | None


def support_dir(environ: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    environ = os.environ if environ is None else environ
    if environ.get(SUPPORT_ENV):
        return Path(environ[SUPPORT_ENV]).expanduser()
    return (home or Path.home()) / "Library" / "Application Support" / "Discjockey"


def read_music_folder(support: Path) -> Path | None:
    """The music folder config.json names. None when none was chosen: no file, or a file that names no absolute
    path (a damaged file then asks for the folder again instead of guessing)."""
    try:
        data = json.loads(SupportPaths(support=support).config_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    folder = data.get("music_folder") if isinstance(data, dict) else None
    return Path(folder) if isinstance(folder, str) and Path(folder).is_absolute() else None


def resolve_in(support: Path) -> Resolved:
    folder = read_music_folder(support)
    if folder is None:
        return Resolved(support, None, "not_chosen", None)
    if not folder.is_dir():  # never made here: an unplugged drive must not get a fresh empty library
        return Resolved(support, None, "missing", folder)
    return Resolved(support, Paths(folder, support=support), None, folder)


def resolve_paths(environ: Mapping[str, str] | None = None, home: Path | None = None) -> Resolved:
    """The support folder ($DISCJOCKEY_SUPPORT or Application Support) and the
    music folder its config.json names."""
    return resolve_in(support_dir(environ, home))


class LockHeld(Exception):
    pass


LOCK_PROBE = threading.Lock()
LOCK_TRIES, LOCK_RETRY_S = 6, 0.02


def try_flock(fd: int) -> bool:
    """One non-blocking try for the engine lock. LOCK_PROBE keeps the hub's console probe (jobs.lock_free) and a
    run_lock in this process from trying at the same moment, so the probe never makes the hub's own job "busy"."""
    with LOCK_PROBE:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
    return True


class NoLibrary(Exception):
    """No music folder to work in: none chosen yet, or the chosen one isn't there (an unplugged drive). The hub
    answers it as no_library; the console prints it and exits 2."""


MUSIC_GONE = ("Your music folder isn't there any more. Connect the drive it is on, then try again. "
              "Nothing was changed.")


@contextmanager
def run_lock(path: Path):
    """Exclusive for the whole run; the OS releases it if the process dies. Tries for about 100 ms before it gives
    up, so that a short probe from another process (the hub checking for a terminal run) is not taken for a run.
    The lock sits in the music folder's .discjockey/, which is made when needed; the music folder itself never is:
    a folder that went away (an unplugged drive) is NoLibrary, never a fresh empty library."""
    try:
        path.parent.mkdir(exist_ok=True)
    except FileNotFoundError:
        raise NoLibrary(MUSIC_GONE) from None
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        for attempt in range(LOCK_TRIES):
            if try_flock(fd):
                break
            if attempt < LOCK_TRIES - 1:
                time.sleep(LOCK_RETRY_S)
        else:
            raise LockHeld()
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)


class StateError(Exception):
    pass


def empty_state() -> dict:
    """The snapshot of a library with no records yet (plan library stage 1, I2)."""
    return {"version": 2, "tracks": {}, "pending": [], "qobuz_usage": {"days": {}, "signals": []}, "never": {},
            "ambiguous": {}, "files": []}


OLD_RECORDS = ("Discjockey tried to save its records in the old format (state.json) after they moved to "
               "library.db. Nothing was changed.")

_MIGRATING = threading.local()  # .on: this thread is migrating state.json, so an old-format save is allowed


def load_state(paths: Paths) -> dict:
    """The library's snapshot (I2), for reading: takes no lock and writes nothing. From library.db once there is
    one; before the migration from state.json (version 1, the read-only keys filled in), so the window can show a
    library before its first change migrates it; with neither, an empty library. library.db gone after the
    migration is StateError (spec library-and-sources §12), for readers and writers alike (db.migrate): the backup
    state.v1.json is never shown nor restored, it may not know what Discjockey did since."""
    from . import db
    if paths.db_file.exists():
        try:
            with db.connect(paths.db_file) as conn:
                db.check(conn)
                return db.snapshot(conn, paths.library)
        except sqlite3.Error as e:
            raise db.unreadable(e) from None
    if not paths.state_file.exists():
        return empty_state()
    if db.is_stub(paths.state_file):
        raise StateError(db.DB_MISSING)
    return _v1_snapshot(paths, _load_v1(paths.state_file))


def _v1_snapshot(paths: Paths, state: dict) -> dict:
    """A version-1 state.json with the read-only keys a snapshot has (nothing is indexed yet: every file the old
    records name counts as placed by the app and online)."""
    for e in state["tracks"].values():
        e["online"], e["placed_by"], e["held"] = bool(e.get("path")), "app" if e.get("path") else None, False
    state["ambiguous"] = {}
    state["files"] = _walk_files(paths)
    return state


def open_state(paths: Paths, emit: Emit = no_emit) -> dict:
    """The snapshot for a writer (the caller holds the lock): open_records, then load_state."""
    open_records(paths, emit)
    return load_state(paths)


def open_records(paths: Paths, emit: Emit = no_emit, *, recover: bool = True) -> bool:
    """A writer's open without the snapshot (the caller holds the lock). Moves state.json into library.db first when
    that hasn't happened yet (spec library-and-sources §5.3; its pending steps are finished on the way), gives a
    library that has neither file an empty library.db, and does the version check of every open. Without `recover`
    (a dry run: no music file is changed) a state.json that still has steps pending is left as it is, records and
    files alike, and the result is False; else True."""
    from . import db
    if not paths.root.is_dir():
        raise NoLibrary(MUSIC_GONE)
    if not recover and _pending_in_v1(paths):
        return False
    paths.data.mkdir(exist_ok=True)  # .discjockey/ only, never the music folder above it

    def finish(state: dict) -> None:
        for message, ok in recover_pending(paths, state):
            emit(Message("info" if ok else "warning", message))

    _MIGRATING.on = True
    try:
        db.migrate(paths, facts=file_facts(paths), now=datetime.now(), emit=emit, recover=finish)
    finally:
        _MIGRATING.on = False
    return True


def _pending_in_v1(paths: Paths) -> bool:
    """state.json still holds the records (version 1, not yet moved into library.db) and has steps pending: moving
    it would finish them first, which renames music files. Unreadable is False: the migration says why."""
    try:
        if not paths.state_file.exists() or json.loads(paths.state_file.read_bytes()).get("version") != STATE_VERSION:
            return False
        return bool(_load_v1(paths.state_file)["pending"])
    except (OSError, ValueError, StateError):
        return False


def _load_v1(path: Path) -> dict:
    """A version-1 state.json (empty when there is none). Any other version, among them the stub the migration
    to library.db leaves, is StateError with the words an older Discjockey prints for it."""
    if not path.exists():
        return {"version": STATE_VERSION, "tracks": {}, "pending": [], "qobuz_usage": {"days": {}, "signals": []},
                "never": {}}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("version") != STATE_VERSION:
        raise StateError(
            f"{path.name} has version {data.get('version')}, this Discjockey only knows version "
            f"{STATE_VERSION}. Nothing was changed."
        )
    data.setdefault("tracks", {})
    data.setdefault("pending", [])
    data.setdefault("qobuz_usage", {"days": {}, "signals": []})
    data.setdefault("never", {})  # Spotify id -> {artist, title, folder, at}: "never download" (the hub's Sync page)
    return data


def file_facts(paths: Paths) -> Callable[[str], object]:
    """db.py's `facts`: size, mtime and content key of the file at a snapshot path, None when no file is there. A
    file that is there but can't be read gets no key (NULL); the next scan reads it again."""
    from . import db

    def facts(path: str):
        p = paths.root / path  # an absolute path (a file of an import folder) stays itself
        try:
            st = os.stat(p)
        except (FileNotFoundError, NotADirectoryError):
            return None
        if not stat.S_ISREG(st.st_mode):
            return None
        try:
            key = content_key(p)
        except OSError:
            key = None
        return db.FileFacts(st.st_size, st.st_mtime_ns, key)
    return facts


def full_fsync(fd: int) -> None:
    """On macOS os.fsync only hands the data to the drive, which may still lose it in a power cut;
    F_FULLFSYNC asks the drive to write it out. Falls back to os.fsync where that is not supported."""
    try:
        fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
    except (AttributeError, OSError):
        os.fsync(fd)


def fsync_dir(path: Path) -> None:
    """Makes a rename into `path` survive a power cut."""
    fd = os.open(path, os.O_RDONLY)
    try:
        full_fsync(fd)
    finally:
        os.close(fd)


def write_json_atomic(path: Path, data, *, parents: bool = False, **dump) -> None:
    """The whole file or nothing, also across a power cut: a temp file beside it, written out to the drive, then
    renamed over it. Makes the folder it sits in (and, with parents=True, the folders above it)."""
    path.parent.mkdir(parents=parents, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, **dump)
        f.flush()
        full_fsync(f.fileno())
    os.replace(tmp, path)
    fsync_dir(path.parent)


def save_state(paths: Paths, state: dict, *, rekeyed: Collection[str] = ()) -> None:
    """Writes a snapshot back into library.db, only what changed, in one transaction (db.save). `rekeyed`: files
    whose audio Discjockey rewrote in place (a swap, a rename onto a name) without an entry field changing; their
    size and content key are read again so a later scan doesn't take them for files replaced outside Discjockey.
    A library with neither library.db nor state.json gets its library.db here (as open_state would). A version-1
    dict is written to state.json only during the migration (its pending steps are finished there), otherwise it
    is StateError. A vanished music folder (an unplugged drive) is NoLibrary, never a new empty library."""
    from . import db
    try:
        paths.data.mkdir(exist_ok=True)  # .discjockey/ itself, never the music folder above it
    except FileNotFoundError:
        raise NoLibrary(MUSIC_GONE) from None
    if state.get("version") == STATE_VERSION:
        if not getattr(_MIGRATING, "on", False):
            raise StateError(OLD_RECORDS)
        try:  # the new state.json (e.g. a pending swap) survives a power cut before going on
            write_json_atomic(paths.state_file, state, indent=2, ensure_ascii=False, sort_keys=True)
        except FileNotFoundError:
            raise NoLibrary(MUSIC_GONE) from None
        return
    facts, now = file_facts(paths), datetime.now()
    try:
        if not paths.db_file.exists():
            if paths.state_file.exists():  # migrated before (or still to migrate): never a fresh database over it
                raise StateError(db.DB_MISSING)
            db.create(paths.db_file, state, library=paths.library, facts=facts, now=now)
            return
        indexed = [p for p in rekeyed if p.startswith("Library/")]  # Superseded/ and .tmp/ have no rows
        with db.connect(paths.db_file) as conn:
            db.save(conn, state, library=paths.library, facts=facts, now=now, rekeyed=indexed)
    except sqlite3.Error as e:
        raise db.unreadable(e) from None


def write_music_folder(support: Path, folder: Path) -> None:
    """config.json: the music folder this Mac uses. Written whole or not at all."""
    write_json_atomic(SupportPaths(support=support).config_file, {"music_folder": str(folder)}, parents=True,
                      indent=2, ensure_ascii=False)


def _walk_files(paths: Paths) -> list[str]:
    """Every file in Library/ (root-relative, NFC), for a snapshot read from a state.json nothing has indexed yet."""
    out = []
    if not paths.library.exists():
        return out
    for dirpath, dirnames, filenames in os.walk(paths.library):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            rel = Path(dirpath, name).relative_to(paths.root).as_posix()
            out.append(unicodedata.normalize("NFC", rel))
    return sorted(out)


SWAP_PATH_KEYS = ("target", "staged", "backup", "parked")


def op_paths(op: dict) -> list[str]:
    """Every file a pending step names (its renames, and for a swap also target, staged, backup and parked)."""
    return [p for pair in op.get("renames", []) for p in pair] + [op[k] for k in SWAP_PATH_KEYS if op.get(k)]


def clear_tmp(paths: Paths, state: dict | None = None) -> None:
    """Empties .tmp/, except the folders of steps still pending in `state`: their downloaded file waits there
    for the next attempt to finish the step."""
    prefix = fold(paths.tmp.relative_to(paths.root).as_posix()) + "/"
    keep = set()
    for op in (state or {}).get("pending", []):
        for p in op_paths(op):
            if fold(p).startswith(prefix):
                keep.add(fold(p)[len(prefix):].split("/")[0])
    if paths.tmp.is_dir():
        for child in paths.tmp.iterdir():
            if fold(child.name) in keep:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
    paths.tmp.mkdir(parents=True, exist_ok=True)


def delete_parked(paths: Paths, rel: str | None) -> None:
    """Deletes one of Discjockey's own parked downloads in Upgrades ready/, and refuses any other path."""
    if not rel:
        return
    prefix = fold(paths.upgrades_ready.relative_to(paths.root).as_posix()) + "/"
    if not fold(rel).startswith(prefix) or ".." in PurePosixPath(rel).parts:
        raise ValueError(f"{rel} is not a parked upgrade, so Discjockey does not delete it")
    (paths.root / rel).unlink(missing_ok=True)


class NameReserver:
    """Picks final file names at execution time; never reuses a name on disk, in state or from this run."""

    def __init__(self, root: Path, state: dict):
        self.root = root
        self.taken: set[str] = set()
        for e in state["tracks"].values():
            if e.get("path"):
                self.taken.add(fold(e["path"]))
            if e.get("upgrade"):  # a parked better version keeps its name in Upgrades ready/
                self.taken.add(fold(e["upgrade"]["file"]))
        for op in state.get("pending", []):
            self.taken.update(fold(p) for p in op_paths(op))

    def is_taken(self, rel: str) -> bool:
        return fold(rel) in self.taken or (self.root / rel).exists()

    def release(self, rel: str) -> None:
        self.taken.discard(fold(rel))

    def choose(self, dest_dir: str, stem: str, ext: str, track_id: str) -> str:
        """The stem, else with the track ID. In Superseded/ a counter follows ("<stem> (2)", ...), so a replaced file
        always finds a place there."""
        names = [stem, f"{stem} [{track_id[:6]}]", f"{stem} [{track_id}]"]
        if fold(dest_dir).split("/")[0] == "superseded":
            names = itertools.chain(names, (f"{stem} ({n})" for n in itertools.count(2)))
        for candidate in names:
            rel = f"{dest_dir}/{candidate}{ext}"
            if not self.is_taken(rel):
                self.taken.add(fold(rel))
                return rel
        raise FileExistsError(f"no free file name for {stem}{ext} in {dest_dir}")


def safe_rename(root: Path, src: str, dst: str) -> None:
    """os.rename silently overwrites on macOS; this refuses instead."""
    s, d = root / src, root / dst
    if d.exists() and not (s.exists() and os.path.samefile(s, d)):
        raise FileExistsError(f"{dst} already exists")
    d.parent.mkdir(parents=True, exist_ok=True)
    os.rename(s, d)


@contextmanager
def deferred_interrupt():
    """Ctrl-C during the block is held back and raised when the block ends."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    received: list[int] = []
    old = signal.signal(signal.SIGINT, lambda signum, frame: received.append(signum))
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, old)
    if received:  # hand the Ctrl-C to whoever was listening before (default: KeyboardInterrupt)
        if callable(old):
            old(signal.SIGINT, None)
        elif old != signal.SIG_IGN:
            raise KeyboardInterrupt


def run_op(paths: Paths, state: dict, track_id: str, renames: list[tuple[str, str]], entry: dict | None, *,
           entries: Mapping[str, dict] | None = None, label: str | None = None) -> None:
    """Record the step as pending, do the renames, then apply the entry. Crash-safe (see recover_pending).
    `entries` (state key -> entry) are applied together with `entry`: a folder move changes many songs' paths in one
    step. `label` names the step in recover_pending's messages. The pending step stores either only when given."""
    with deferred_interrupt():
        op = {"track_id": track_id, "renames": [list(r) for r in renames], "entry": entry}
        if entries is not None:
            op["entries"] = dict(entries)
        if label is not None:
            op["label"] = label
        state.setdefault("pending", []).append(op)
        save_state(paths, state)
        done = 0
        try:
            for src, dst in renames:
                safe_rename(paths.root, src, dst)
                done += 1
        except BaseException:
            if done == 0:
                state["pending"].remove(op)
                save_state(paths, state)
            raise
        _apply_entries(state, op)
        state["pending"].remove(op)
        save_state(paths, state, rekeyed=[dst for _, dst in renames])


def _apply_entries(state: dict, op: dict) -> None:
    if op.get("entry") is not None:
        state["tracks"][op["track_id"]] = op["entry"]
    for key, e in (op.get("entries") or {}).items():
        state["tracks"][key] = e


def recover_pending(paths: Paths, state: dict) -> list[tuple[str, bool]]:
    """Finish or drop steps an earlier run was interrupted in, then close the move batches a crash left open
    (tidy.recover). Returns (message, ok) per step and per batch."""
    messages = []
    for op in list(state.get("pending", [])):
        if op.get("kind") == "swap":
            from .upgrades import recover_swap  # upgrades builds on this module
            messages.append(recover_swap(paths, state, op))
            continue
        e = op.get("entry") or {}
        name = op.get("label") or f"{e.get('artist', '?')} - {e.get('title', op['track_id'])}"
        problem, done_any = "", False
        for i, (src, dst) in enumerate(op["renames"]):
            s, d = (paths.root / src).exists(), (paths.root / dst).exists()
            if d and not s:
                done_any = True
                continue
            if s and d and any(fold(src) == fold(later_dst) and not (paths.root / later_src).exists()
                               for later_src, later_dst in op["renames"][i + 1:]):
                done_any = True  # moved away, then a later rename of this step took its name (add as new)
                continue
            if s and not d:
                try:
                    safe_rename(paths.root, src, dst)
                except OSError as e:  # e.g. permissions: keep the step pending and try again next start
                    problem = f"could not move {src} ({e})"
                    break
                done_any = True
                continue
            problem = f"both {src} and {dst} exist" if s else f"neither {src} nor {dst} exists"
            break
        if problem.startswith("could not move") and not done_any:
            messages.append((f"Could not finish an interrupted step for {name} yet: {problem}", False))
            continue
        if done_any:
            # once a file was placed, the entry must point at it, or the next run would mis-adopt it
            _apply_entries(state, op)
        if not problem:
            messages.append((f"Finished an interrupted step for {name}", True))
        elif done_any:
            messages.append((f"Finished most of an interrupted step for {name}, but {problem}", False))
        else:
            messages.append((f"Could not finish an interrupted step for {name}: {problem}", False))
        state["pending"].remove(op)
        save_state(paths, state, rekeyed=[dst for _, dst in op["renames"]])
    if state.get("version") == 2 and paths.db_file.exists():
        from . import db
        with db.connect(paths.db_file) as conn:
            stopped = bool(db.open_batches(conn))
        if stopped:
            from .tidy import recover  # tidy builds on this module
            messages += recover(paths, state)
    return messages


# --- the scan (spec library-and-sources §6) ---

SCANNED = "Checked your Library: {parts}."
SCAN_PARTS = (("moved", "file you moved", "files you moved"), ("new", "new file", "new files"),
              ("gone", "file gone", "files gone"), ("replaced", "file changed", "files changed"))
NOT_JUDGED = ("{path} was changed outside Discjockey, but Discjockey couldn't check its sound ({reason}). It keeps "
              "the quality it had.")


def scan_library(paths: Paths, emit: Emit = no_emit, *,
                 analyze: Callable[[Path], tuple[str, int | None]] | None = None,
                 key_of: Callable[[Path], str] = content_key, recover: bool = True) -> ScanSummary:
    """Indexes the watched folders (Library/) against library.db and writes what changed (the caller holds the
    lock; the records are opened, and migrated if needed, first): files moved by hand keep their song, new files
    are indexed, a file gone marks its song's file gone, and a song's file whose audio was replaced outside
    Discjockey is judged again the way a bought file is (`analyze`, quality.inspect) and counts as the user's own
    file from now on. The new audio is judged before anything is written and recorded together with its quality;
    a file the check fails on keeps its row as it was, so the next scan judges it again. Superseded/, Upgrades
    ready/ and .discjockey/ are never looked at. Nothing is scanned while a step is pending (its files are between
    two places; the next scan after it is finished sees them). One message, only when something changed (copies
    count as new files). `recover` as open_records: a dry run passes False, and a state.json with steps pending is
    then neither moved into library.db nor scanned."""
    from . import db, scanner
    from .quality import is_lossless_codec, verdict
    if analyze is None:
        from .quality import inspect as analyze
    if not open_records(paths, emit, recover=recover):
        return ScanSummary()
    try:
        with db.connect(paths.db_file) as conn:
            if db.has_pending(conn):
                return ScanSummary()
            folders = {f.id: f for f in db.watched_folders(conn)}
            known = db.known_files(conn)

            def snapshot_path(folder: int, rel: str) -> str:
                return db.snapshot_path(folders[folder].kind, folders[folder].path.as_posix(), rel)

            result = scanner.scan(list(folders.values()), known,
                                  exclude=[paths.superseded, paths.upgrades_ready, paths.data],
                                  snapshot_path=snapshot_path, key_of=key_of)
            linked = {f.id for f in known if f.linked}
            judged, failed = {}, set()
            for file_id, seen in result.replaced:
                if file_id not in linked:
                    continue  # nobody's file: nothing to judge it for
                path = snapshot_path(seen.folder, seen.rel)
                try:
                    codec, cutoff = analyze(paths.root / path)
                except Exception as e:  # noqa: BLE001 - a file the tools can't read keeps its old quality
                    emit(Message("warning", NOT_JUDGED.format(path=path, reason=str(e)[:200] or type(e).__name__)))
                    failed.add(file_id)
                    continue
                judged[file_id] = (verdict(is_lossless_codec(codec), cutoff), cutoff, codec)
            if failed:  # their rows stay as they are (held), old key included
                result.replaced = [r for r in result.replaced if r[0] not in failed]
                result.held = [*result.held, *failed]
            db.apply_scan(conn, result, datetime.now(), judged)
    except sqlite3.Error as e:
        raise db.unreadable(e) from None
    summary = ScanSummary(moved=len(result.moved), new=len(result.new), gone=len(result.gone),
                          replaced=len(result.replaced), copies=len(result.copies), offline=len(result.offline))
    counts = {"moved": summary.moved, "new": summary.new + summary.copies, "gone": summary.gone,
              "replaced": summary.replaced}
    parts = [f"{counts[k]} {one if counts[k] == 1 else many}" for k, one, many in SCAN_PARTS if counts[k]]
    if parts:
        emit(Message("info", SCANNED.format(parts=", ".join(parts))))
    return summary


# --- choosing the music folder (Setup, Settings, discjockey setup) ---

FOLDER_PROBLEMS = {
    "not_absolute": "Choose the folder with Choose…, or type its full path (starting with / or ~).",
    "not_a_folder": "That is a file, not a folder.",
    "system_folder": ("That folder belongs to macOS or holds your whole home folder. Choose a folder just for your "
                      "music, such as Music/Discjockey."),
    "inside_app": ("That folder is inside Discjockey itself, which is replaced on every update. Choose a folder "
                   "outside it."),
    "is_support_dir": "Discjockey keeps its own settings in that folder. Choose another one for your music.",
    "not_writable": "Discjockey can't write in that folder. Choose one of your own folders.",
}
SYSTEM_FOLDERS = (Path("/System"), Path("/Library"), Path("/Applications"), Path("/usr"), Path("/bin"), Path("/sbin"))
LIBRARY_MARKS = (DATA_DIR, "Library")  # folders that make a folder a Discjockey library (with playlists.txt)


@dataclass(frozen=True)
class FolderCheck:
    """What a folder would be as the music folder. `kind` (only when usable): new (Discjockey makes it) · empty ·
    discjockey_library (has .discjockey/, Library/ or playlists.txt: used as it is) · other_files (the page asks
    first: Discjockey adds its folders next to what's there)."""
    path: Path
    exists: bool
    usable: bool
    problem: str | None
    kind: str | None


def _system_folder(folder: Path, home: Path) -> bool:
    if folder in (Path("/"), Path("/Users"), Path("/Volumes")) or home.is_relative_to(folder):
        return True  # the disk, every user's folders, the drives' list, the home folder or above it
    return folder.is_relative_to(home / "Library") or any(folder.is_relative_to(p) for p in SYSTEM_FOLDERS)


def check_music_folder(folder: Path | str, *, support: Path, program: Path, home: Path) -> FolderCheck:
    """Never changes anything. `program`: Discjockey's own folder (tools.program_dir(): the app bundle, or the
    source checkout); `home`: the user's home folder."""
    path = Path(folder).expanduser()
    if not path.is_absolute():
        return FolderCheck(path, False, False, "not_absolute", None)
    path = path.resolve()  # a folder still to be made resolves as far as it exists
    exists = path.exists()

    def refuse(problem: str) -> FolderCheck:
        return FolderCheck(path, exists, False, problem, None)

    if exists and not path.is_dir():
        return refuse("not_a_folder")
    if _system_folder(path, home.resolve()):
        return refuse("system_folder")
    if path.is_relative_to(program.resolve()):
        return refuse("inside_app")
    if path.is_relative_to(support.resolve()):
        return refuse("is_support_dir")
    probe = path if exists else next(p for p in path.parents if p.exists())
    if not os.access(probe, os.W_OK | os.X_OK) or (exists and not os.access(path, os.R_OK)):
        return refuse("not_writable")
    if not exists:
        return FolderCheck(path, False, True, None, "new")
    try:
        names = [n for n in os.listdir(path) if not n.startswith(".")]
    except OSError:
        return refuse("not_writable")
    if any((path / m).is_dir() for m in LIBRARY_MARKS) or (path / "playlists.txt").is_file():
        kind = "discjockey_library"
    else:
        kind = "other_files" if names else "empty"
    return FolderCheck(path, True, True, None, kind)
