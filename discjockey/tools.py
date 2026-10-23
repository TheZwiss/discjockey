"""The programs Discjockey runs and the download tools it imports (spec public-release §6.1, §6.4).

- Bundled programs: the app carries ffmpeg, ffprobe and deno in Contents/Resources/bin; activate() puts that folder
  first on PATH, so every ["ffmpeg", ...] call, streamrip and yt-dlp (which looks for deno on PATH) use them. A source
  checkout has no such folder and keeps using Homebrew's.
- The updatable yt-dlp: <support>/tools/<version>/ holds a newer yt-dlp and yt-dlp-ejs (tool_updates.py fetches them)
  and <support>/tools/current points at the one to use. activate() puts it first on sys.path, but only when it is newer
  than the built-in copy: an app release with a newer yt-dlp is never shadowed by an old update.
- The check: `Discjockey --check-tools <folder>` (`python -m discjockey --check-tools <folder>` in a checkout) imports
  a candidate folder in a process of its own and prints its versions; tool_updates only uses a folder that passed.

Imports nothing that imports yt_dlp: activate() has to run before the first `import yt_dlp`.
"""
from __future__ import annotations

import fcntl
import importlib
import importlib.machinery
import importlib.resources
import json
import os
import re
import shutil
import sys
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path

from . import REPO, library

CHECK_FLAG = "--check-tools"
TOOLS_DIR = "tools"
CURRENT = "current"
PARTIAL_PREFIX = ".partial-"
YT_DLP = "yt_dlp"
EJS = "yt_dlp_ejs"
_NUMERIC = re.compile(r"[0-9]+(\.[0-9]+)*")
_VERSION_LINE = re.compile(r"""^__version__\s*=\s*(?:version\s*=\s*)?['"]([^'"]+)['"]""", re.M)
_VERSION_FILE = {YT_DLP: "version.py", EJS: "_version.py"}


def is_frozen() -> bool:
    """True inside the built Discjockey.app (PyInstaller sets sys.frozen)."""
    return bool(getattr(sys, "frozen", False))


def program_dir() -> Path:
    """Discjockey's own folder: the .app bundle when frozen, the source checkout otherwise. A music folder inside it
    is refused (library.check_music_folder): the app is replaced whole on every update."""
    if not is_frozen():
        return REPO
    exe = Path(sys.executable).resolve()
    return next((p for p in exe.parents if p.suffix == ".app"), exe.parent)


LICENSES = "licenses"


def licenses_dir() -> Path:
    """The licences of everything Discjockey bundles (spec public-release §6.5): Contents/Resources/licenses in the
    app (packaging/collect_licenses.py), the hand-kept part in packaging/licenses in a checkout."""
    if is_frozen():
        return program_dir() / "Contents" / "Resources" / LICENSES
    return REPO / "packaging" / LICENSES


def bundled_bin() -> Path | None:
    """The app's Contents/Resources/bin (ffmpeg, ffprobe, deno); None in a source checkout."""
    if not is_frozen():
        return None
    folder = program_dir() / "Contents" / "Resources" / "bin"
    return folder if folder.is_dir() else None


# --- versions ---

def parse_version(text: str | None) -> tuple[int, ...] | None:
    """"2026.10.21" -> (2026, 10, 21). "2025.01.15" (yt-dlp's spelling) equals "2025.1.15" (PyPI's). None for
    anything that isn't dot-separated numbers."""
    if not text or not _NUMERIC.fullmatch(text):
        return None
    return tuple(int(part) for part in text.split("."))


def newer(a: str | None, b: str | None) -> bool:
    """`a` is a version and strictly newer than `b`; any version beats an unknown `b`."""
    pa, pb = parse_version(a), parse_version(b)
    return pa is not None and (pb is None or pa > pb)


def same_version(a: str | None, b: str | None) -> bool:
    pa = parse_version(a)
    return pa is not None and pa == parse_version(b)


def package_version(package_dir: Path) -> str | None:
    """The version a yt_dlp or yt_dlp_ejs package folder declares, read from its version file without importing."""
    name = _VERSION_FILE.get(package_dir.name)
    if name is None:
        return None
    try:
        match = _VERSION_LINE.search((package_dir / name).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
    return match.group(1) if match else None


def folder_version(folder: Path) -> str | None:
    """The yt-dlp version of an update folder that holds both packages; None when either is missing."""
    version = package_version(folder / YT_DLP)
    if parse_version(version) is None or package_version(folder / EJS) is None:
        return None
    return version


def inside(path: Path, folder: Path) -> bool:
    """`path` is `folder` or somewhere below it (both resolved)."""
    try:
        return path.resolve().is_relative_to(folder.resolve())
    except (OSError, RuntimeError):
        return False


# --- the update folders: <support>/tools/<version>/ and <support>/tools/current ---

def tools_root(support: Path) -> Path:
    return support / TOOLS_DIR


def current_folder(support: Path) -> Path | None:
    """The update folder `current` points at (resolved); None when there is none, it is broken or half there, or it
    points outside the tools folder."""
    root = tools_root(support)
    try:
        folder = (root / CURRENT).resolve(strict=True)
        root = root.resolve(strict=True)
    except (OSError, RuntimeError):  # missing, dangling, or a link loop
        return None
    if folder.parent != root or not folder.is_dir() or folder_version(folder) is None:
        return None
    return folder


def builtin_package(support: Path, path: list[str] | None = None) -> Path | None:
    """The yt_dlp package that came with the program (site-packages in a checkout, the app's own copy when frozen):
    looked up on `path` (sys.path) without the update folders, and without importing it."""
    root = tools_root(support)
    search = [entry for entry in (sys.path if path is None else path) if not inside(Path(entry or "."), root)]
    spec = importlib.machinery.PathFinder.find_spec(YT_DLP, search)
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(list(spec.submodule_search_locations)[0]).resolve()


def running_package() -> Path | None:
    """The yt_dlp package this process imported; None before the first import."""
    file = getattr(sys.modules.get(YT_DLP), "__file__", None)
    return Path(file).resolve().parent if file else None


def choose_override(support: Path, builtin_version: str | None) -> Path | None:
    """The update folder to put first on sys.path: `current`, only when it is newer than the built-in yt-dlp (an
    unknown built-in version counts as older)."""
    folder = current_folder(support)
    if folder is None or not newer(folder_version(folder), builtin_version):
        return None
    return folder


IN_USE = ".in-use"  # lock file in an update folder: a process running yt-dlp from it holds a shared flock on it
_held: list[int] = []  # the open lock files, kept for the life of the process


def hold_in_use(folder: Path) -> None:
    """Marks `folder` as in use by this process until it exits (a shared flock), so no other Discjockey process
    (e.g. `discjockey update` in Terminal) prunes it."""
    try:
        fd = os.open(folder / IN_USE, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
    except OSError:
        os.close(fd)
        return
    _held.append(fd)


def remove_unless_in_use(folder: Path) -> bool:
    """Deletes an update folder unless some process (this one too) holds its in-use lock. True when it is gone."""
    fd = None
    try:
        fd = os.open(folder / IN_USE, os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return False
    except OSError:  # no such folder, or one we can't write to: nothing holds a lock there
        if fd is not None:
            os.close(fd)
            fd = None
    try:
        shutil.rmtree(folder, ignore_errors=True)
    finally:
        if fd is not None:
            os.close(fd)
    return not folder.exists()


def insert_override(support: Path, path: list[str], modules: Mapping[str, object]) -> Path | None:
    """Puts the chosen update folder first on `path` (once). Never after yt_dlp or yt_dlp_ejs was imported: the
    process would mix two versions."""
    if YT_DLP in modules or EJS in modules:
        return None
    builtin = builtin_package(support, path)
    folder = choose_override(support, package_version(builtin) if builtin else None)
    if folder is None:
        return None
    if str(folder) not in path:
        path.insert(0, str(folder))
    hold_in_use(folder)
    return folder


@dataclass(frozen=True)
class Activation:
    bin_dir: Path | None  # the bundled programs' folder, first on PATH (None: a source checkout)
    override: Path | None  # the update folder, first on sys.path (None: the built-in yt-dlp)


def activate(environ: MutableMapping[str, str] | None = None, support: Path | None = None) -> Activation:
    """Once at start, before anything imports yt_dlp (discjockey/__main__.py; the app's own entry from phase 4).
    Calling it again changes nothing and reports the same Activation: `override` is the update folder in effect, also
    when the first call already inserted it and yt_dlp has been imported from it since."""
    environ = os.environ if environ is None else environ
    if is_frozen():
        sys.dont_write_bytecode = True  # nothing may be written into the signed bundle
    bin_dir = bundled_bin()
    if bin_dir is not None:
        rest = [p for p in environ.get("PATH", "").split(os.pathsep) if p and p != str(bin_dir)]
        environ["PATH"] = os.pathsep.join([str(bin_dir), *rest])
    support = library.support_dir(environ) if support is None else support
    override = insert_override(support, sys.path, sys.modules)
    if override is None:  # a second call, after yt_dlp was imported from the update folder
        running = running_package()
        if running is not None and inside(running, tools_root(support)):
            override = running.parent
    return Activation(bin_dir, override)


# --- the check, in a process of its own ---

def check_command(folder: Path) -> tuple[list[str], Path | None]:
    """How to test an update folder in a fresh process: (command, working folder). The app runs itself with
    --check-tools; a checkout runs `python -m discjockey`, which needs the checkout as its working folder."""
    if is_frozen():
        return [sys.executable, CHECK_FLAG, str(folder)], None
    return [sys.executable, "-m", "discjockey", CHECK_FLAG, str(folder)], REPO


def check_main(args: list[str]) -> int:
    """`--check-tools <folder>`: imports yt-dlp and yt-dlp-ejs from that folder (and nowhere else), makes a
    YoutubeDL, lists the extractors and finds the JavaScript solver. Never touches the network.

    Contract for the caller (tool_updates): a folder passed only if the process exited 0 AND its last stdout line is a
    JSON object holding string values for "yt-dlp" and "yt-dlp-ejs". Anything else is a failure, whatever the exit
    code: a candidate's own code runs here and may exit or print on its own. Failure: the reason on stderr, the last
    stdout line {"error": "..."}, exit 1 (SystemExit and KeyboardInterrupt raised by the candidate count as failures
    too); wrong arguments: exit 2."""
    if len(args) != 1:
        print(f"usage: {CHECK_FLAG} <folder>", file=sys.stderr)
        return 2
    try:
        versions = _check(Path(args[0]).expanduser().resolve())
    except BaseException as e:  # any import or API problem, even a sys.exit() in the candidate: don't use this folder
        reason = f"{type(e).__name__}: {e}"
        print(reason, file=sys.stderr)
        print(json.dumps({"error": reason}))
        return 1
    print(json.dumps(versions))
    return 0


def _check(folder: Path) -> dict:
    if YT_DLP in sys.modules or EJS in sys.modules:
        raise RuntimeError("yt-dlp was imported before the check")
    sys.path.insert(0, str(folder))
    yt_dlp = importlib.import_module(YT_DLP)
    ejs = importlib.import_module(EJS)
    for module in (yt_dlp, ejs):
        if not inside(Path(module.__file__), folder):
            raise RuntimeError(f"{module.__name__} came from {module.__file__}, not from {folder}")
    version = importlib.import_module(f"{YT_DLP}.version").__version__
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}):
        pass
    if not any(True for _ in importlib.import_module(f"{YT_DLP}.extractor").gen_extractor_classes()):
        raise RuntimeError("yt-dlp has no extractors")
    solver = importlib.resources.files(f"{EJS}.yt.solver")
    if not any(entry.name.endswith(".js") for entry in solver.iterdir()):
        raise RuntimeError("yt-dlp-ejs has no solver files")
    return {"yt-dlp": version, "yt-dlp-ejs": getattr(ejs, "version", None) or package_version(folder / EJS)}
