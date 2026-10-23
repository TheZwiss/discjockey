"""Everything about the library on disk: where things live (the music folder, its .discjockey/, the support
folder), the lock, state.json, names, safe renames."""
from __future__ import annotations

import fcntl
import itertools
import json
import os
import shutil
import signal
import threading
import time
import unicodedata
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

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
    return {"version": STATE_VERSION, "tracks": {}, "pending": [], "qobuz_usage": {"days": {}, "signals": []},
            "never": {}}


def load_state(path: Path) -> dict:
    if not path.exists():
        return empty_state()
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


def save_state(path: Path, state: dict) -> None:
    """Makes .discjockey itself, never the music folder above it: a vanished folder (an unplugged drive) is
    NoLibrary, not a new empty library."""
    # the new state.json (e.g. a pending swap) survives a power cut before going on
    try:
        write_json_atomic(path, state, indent=2, ensure_ascii=False, sort_keys=True)
    except FileNotFoundError:
        raise NoLibrary(MUSIC_GONE) from None


def write_music_folder(support: Path, folder: Path) -> None:
    """config.json: the music folder this Mac uses. Written whole or not at all."""
    write_json_atomic(SupportPaths(support=support).config_file, {"music_folder": str(folder)}, parents=True,
                      indent=2, ensure_ascii=False)


def list_files(paths: Paths) -> list[str]:
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


def run_op(paths: Paths, state: dict, track_id: str, renames: list[tuple[str, str]], entry: dict | None) -> None:
    """Record the step as pending, do the renames, then apply the entry. Crash-safe (see recover_pending)."""
    with deferred_interrupt():
        op = {"track_id": track_id, "renames": [list(r) for r in renames], "entry": entry}
        state.setdefault("pending", []).append(op)
        save_state(paths.state_file, state)
        done = 0
        try:
            for src, dst in renames:
                safe_rename(paths.root, src, dst)
                done += 1
        except BaseException:
            if done == 0:
                state["pending"].remove(op)
                save_state(paths.state_file, state)
            raise
        if entry is not None:
            state["tracks"][track_id] = entry
        state["pending"].remove(op)
        save_state(paths.state_file, state)


def recover_pending(paths: Paths, state: dict) -> list[tuple[str, bool]]:
    """Finish or drop steps an earlier run was interrupted in. Returns (message, ok) per step."""
    messages = []
    for op in list(state.get("pending", [])):
        if op.get("kind") == "swap":
            from .upgrades import recover_swap  # upgrades builds on this module
            messages.append(recover_swap(paths, state, op))
            continue
        e = op.get("entry") or {}
        name = f"{e.get('artist', '?')} - {e.get('title', op['track_id'])}"
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
        if done_any and op.get("entry") is not None:
            # once a file was placed, the entry must point at it, or the next run would mis-adopt it
            state["tracks"][op["track_id"]] = op["entry"]
        if not problem:
            messages.append((f"Finished an interrupted step for {name}", True))
        elif done_any:
            messages.append((f"Finished most of an interrupted step for {name}, but {problem}", False))
        else:
            messages.append((f"Could not finish an interrupted step for {name}: {problem}", False))
        state["pending"].remove(op)
        save_state(paths.state_file, state)
    return messages


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
