"""Updating the download tools without an app release (spec public-release §6.4): yt-dlp and the yt-dlp-ejs it pins,
from PyPI, into <support>/tools/<version>/, with <support>/tools/current pointing at the one to use (tools.activate
puts it on sys.path at the next start, when it is newer than the built-in copy).

A new folder is used only after both wheels matched PyPI's SHA-256 and the folder passed `--check-tools` in a
process of its own; until then `current` is untouched and a half-made folder (.partial-<version>) is removed. The
folder used before stays for one step back (rollback). The folder this process imported yt-dlp from is never
deleted: yt-dlp imports its extractors lazily. streamrip only changes with app releases. Nothing here touches the
source checkout: uv.lock is a developer's to bump."""
from __future__ import annotations

import compileall
import errno
import hashlib
import importlib.metadata
import io
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import zipfile
import zlib
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from . import tools

log = logging.getLogger(__name__)

PYPI_LATEST = "https://pypi.org/pypi/{name}/json"
PYPI_RELEASE = "https://pypi.org/pypi/{name}/{version}/json"
TIMEOUT_S = 60
CHECK_TIMEOUT_S = 120
CHECK_POLL_S = 0.2
MAX_UNPACKED_BYTES = 200 * 1024 * 1024  # per wheel; the real ones unpack to a few MB
_EJS_PIN = re.compile(r"""^yt-dlp-ejs\s*==\s*([0-9][0-9.]*)\s*;.*\bextra\s*==\s*["']default["']""")

OFFLINE = "Couldn't reach the download server. Check your internet connection and try again. Nothing was changed."
SERVER_ERROR = "The download server has a problem right now. Try again later. Nothing was changed."
BAD_ANSWER = "The download server gave an answer Discjockey doesn't understand. Try again later. Nothing was changed."
NO_WHEEL = "The newest yt-dlp can't be installed on this Mac yet. Nothing was changed."
DAMAGED = "The download was damaged, so it wasn't used. Try again later. Nothing was changed."
CHECK_FAILED = "The new yt-dlp didn't pass its test, so Discjockey keeps the one it has. Try again in a day or two."
DISK = "Couldn't save the download tools ({reason}). Nothing was changed."
NOTHING_TO_UNDO = "There is no earlier version to go back to."


class HttpStatus(OSError):
    """The server answered, but with an error status (404, 429, 500...): not the same as being offline."""

    def __init__(self, status: int, url: str):
        super().__init__(f"HTTP {status} for {url}")
        self.status = status


class ToolsError(Exception):
    """A plain sentence for the user; the tools in use are as they were. `kind`: the bridge's problem kind."""

    def __init__(self, message: str, kind: str = "failed"):
        super().__init__(message)
        self.kind = kind


def http_get(url: str) -> bytes:
    """One GET (PyPI's JSON API and its files). conftest replaces it: no network in tests."""
    import requests
    response = requests.get(url, timeout=TIMEOUT_S, headers={"User-Agent": "Discjockey"})
    if response.status_code >= 400:
        raise HttpStatus(response.status_code, url)
    return response.content


# --- PyPI ---

def _get(fetch: Callable[[str], bytes], url: str) -> bytes:
    """One download. ToolsError: OFFLINE when the server can't be reached, SERVER_ERROR when it answered with an
    error status. The detail goes to the log."""
    try:
        return fetch(url)
    except HttpStatus as e:
        log.warning("download tools: %s", e)
        raise ToolsError(SERVER_ERROR) from None
    except Exception as e:  # requests' connection errors and timeouts
        log.warning("download tools: %s: %s", type(e).__name__, e)
        raise ToolsError(OFFLINE) from None


def _disk_error(e: OSError) -> ToolsError:
    """A disk problem in plain words; the OS's own text only goes to the log."""
    log.warning("download tools: disk error: %s", e)
    if e.errno in (errno.ENOSPC, errno.EDQUOT):
        reason = "the disk is full"
    elif e.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
        reason = "Discjockey isn't allowed to write there"
    else:
        reason = "the disk refused"
    return ToolsError(DISK.format(reason=reason))


def _fetch_json(fetch: Callable[[str], bytes], url: str) -> dict:
    data = _get(fetch, url)
    try:
        answer = json.loads(data)
    except ValueError:
        raise ToolsError(BAD_ANSWER) from None
    if not isinstance(answer, dict) or not isinstance(answer.get("info"), dict):
        raise ToolsError(BAD_ANSWER)
    return answer


def _wheel(release: dict) -> dict:
    """The release's pure-Python wheel: {url, sha256}. Discjockey only installs those (no native code)."""
    for f in release.get("urls") or []:
        name, sha = f.get("filename") or "", (f.get("digests") or {}).get("sha256")
        if (f.get("packagetype") == "bdist_wheel" and name.endswith("-py3-none-any.whl") and not f.get("yanked")
                and f.get("url") and sha):
            return {"url": f["url"], "sha256": sha.lower()}
    raise ToolsError(NO_WHEEL)


def ejs_pin(info: dict) -> str | None:
    """The yt-dlp-ejs version this yt-dlp asks for: its "default" extra pins it exactly."""
    for requirement in info.get("requires_dist") or []:
        match = _EJS_PIN.match(requirement.strip())
        if match:
            return match.group(1)
    return None


def _download(fetch: Callable[[str], bytes], wheel: dict) -> bytes:
    data = _get(fetch, wheel["url"])
    if hashlib.sha256(data).hexdigest() != wheel["sha256"]:
        raise ToolsError(DAMAGED)
    return data


def unpack(data: bytes, into: Path) -> None:
    """The wheel's packages (yt_dlp/, yt_dlp_ejs/) and .dist-info into `into`; nothing else (no scripts, no data
    files). A name that would land outside `into`, or a file that isn't a zip, is damaged."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ToolsError(DAMAGED) from None
    with archive:
        try:
            wanted, total = [], 0
            for member in archive.infolist():
                parts = Path(member.filename).parts
                if not parts or member.filename.startswith("/") or ".." in parts:
                    raise ToolsError(DAMAGED)
                if parts[0] in (tools.YT_DLP, tools.EJS) or parts[0].endswith(".dist-info"):
                    wanted.append(member)
                    total += member.file_size  # the reader stops at this size, so it is a real limit
            if total > MAX_UNPACKED_BYTES:  # a hostile archive must not fill the disk
                log.warning("download tools: wheel unpacks to %d bytes, limit %d", total, MAX_UNPACKED_BYTES)
                raise ToolsError(DAMAGED)
            for member in wanted:
                archive.extract(member, into)
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError, zlib.error) as e:
            log.warning("download tools: damaged wheel: %s: %s", type(e).__name__, e)  # a CRC error, a cut-off file
            raise ToolsError(DAMAGED) from None


def _kill_group(child: subprocess.Popen) -> None:
    """Ends the child and everything it started (its process group), and reaps it."""
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except OSError:  # already gone
        child.kill()
    child.wait()


def _run_stoppable(check: Callable[[], None]) -> Callable:
    """subprocess.run's signature (the part used here), but Stop ends it: `check()` is asked every CHECK_POLL_S and
    its Cancelled kills the child. Output goes to temporary files, so a chatty child can't fill a pipe."""
    def run(cmd, *, cwd=None, timeout=None, **_ignored):
        with tempfile.TemporaryFile("w+") as out, tempfile.TemporaryFile("w+") as err:
            child = None
            try:
                # its own process group: killing it takes anything it started along
                child = subprocess.Popen(cmd, cwd=cwd, stdout=out, stderr=err, text=True, start_new_session=True)
                end = time.monotonic() + timeout if timeout else None
                while child.poll() is None:
                    check()
                    if end is not None and time.monotonic() > end:
                        raise subprocess.TimeoutExpired(cmd, timeout)
                    time.sleep(CHECK_POLL_S)
            except BaseException:  # Stop, the time limit, Ctrl-C: the child must not outlive the update
                if child is not None:
                    _kill_group(child)
                raise
            out.seek(0)
            err.seek(0)
            return SimpleNamespace(returncode=child.returncode, stdout=out.read(), stderr=err.read())
    return run


def _run_check(run: Callable, folder: Path, want: dict[str, str], check: Callable[[], None] | None = None) -> None:
    """The folder in a fresh process (tools.check_main); it must report exactly the versions just unpacked. With the
    real subprocess.run, `check()` (Stop) can end the child at any moment."""
    cmd, cwd = tools.check_command(folder)
    if run is subprocess.run and check is not None:  # the real thing (not a test's fake): Stop must be able to end it
        run = _run_stoppable(check)
    try:
        result = run(cmd, cwd=cwd, capture_output=True, text=True, timeout=CHECK_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        raise ToolsError(CHECK_FAILED) from None
    lines = (result.stdout or "").strip().splitlines()
    try:
        got = json.loads(lines[-1]) if result.returncode == 0 and lines else None
    except ValueError:
        got = None
    if not isinstance(got, dict) or not all(tools.same_version(got.get(k), v) for k, v in want.items()):
        raise ToolsError(CHECK_FAILED)


# --- the folders ---

_NO_FOLDER_SYNC = (errno.EINVAL, errno.ENOTSUP)


def _sync_to_disk(folder: Path) -> None:
    """Everything below `folder` (and the folders themselves) on disk, so a power loss can't leave a folder that
    looks whole with truncated files. macOS's fsync stops at the drive's cache; F_FULLFSYNC goes further."""
    def flush(path: Path, is_folder: bool) -> None:
        fd = os.open(path, os.O_RDONLY)
        try:
            try:
                import fcntl
                fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
            except (ImportError, AttributeError, OSError):
                try:
                    os.fsync(fd)
                except OSError as e:
                    # some filesystems can't sync a folder (EINVAL, ENOTSUP): that is no failure; any other error is
                    if not (is_folder and e.errno in _NO_FOLDER_SYNC):
                        raise
        finally:
            os.close(fd)

    for base, dirs, files in os.walk(folder):
        for name in files:
            flush(Path(base, name), False)
        flush(Path(base), True)


def _sync_folder(folder: Path) -> None:
    """The folder's own entries (a rename, a new link) on disk; best effort."""
    try:
        fd = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _named_folders(support: Path) -> list[Path]:
    """Every update folder (a real folder named by a version, whole or not), resolved."""
    try:
        entries = list(tools.tools_root(support).iterdir())
    except OSError:
        return []
    return [p.resolve() for p in entries if not p.is_symlink() and p.is_dir() and tools.parse_version(p.name)]


def _version_folders(support: Path) -> list[Path]:
    """The usable update folders (both packages there), resolved."""
    return [p for p in _named_folders(support) if tools.folder_version(p)]


def _point_current(support: Path, folder: Path | None) -> None:
    """`current` -> folder (a relative link, swapped in with one rename), or no `current` at all."""
    link = tools.tools_root(support) / tools.CURRENT
    if folder is None:
        link.unlink(missing_ok=True)
        return
    temp = link.with_name(f".{tools.CURRENT}-{os.getpid()}")
    temp.unlink(missing_ok=True)
    os.symlink(folder.name, temp)
    os.replace(temp, link)


def _remove(folder: Path, running: Path | None) -> None:
    """Deletes an update folder of Discjockey's own, unless this process imported yt-dlp from it or another
    Discjockey process holds its in-use lock."""
    if running is not None and tools.inside(running, folder):
        return
    tools.remove_unless_in_use(folder)


def _clear_leftovers(support: Path) -> None:
    """Half-made folders and links of an update that was stopped, crashed or lost power."""
    root = tools.tools_root(support)
    for entry in root.glob(f"{tools.PARTIAL_PREFIX}*"):
        shutil.rmtree(entry, ignore_errors=True)
    for entry in root.glob(f".{tools.CURRENT}-*"):
        entry.unlink(missing_ok=True)


def _next_version(support: Path, builtin_version: str | None) -> str | None:
    """The yt-dlp version the next start uses: `current` when it is newer than the built-in copy."""
    folder = tools.current_folder(support)
    version = tools.folder_version(folder) if folder else None
    return version if tools.newer(version, builtin_version) else builtin_version


def _other_folder(support: Path, current: Path) -> Path | None:
    """The newest kept update folder besides `current`: where a step back goes."""
    others = [p for p in _version_folders(support) if p != current]
    return max(others, key=lambda p: tools.parse_version(p.name), default=None)


def _after_rollback(support: Path, builtin_version: str | None) -> str | None:
    """The version the next start would use after rollback(); None when there is no update to step back from or
    stepping back would change nothing."""
    current = tools.current_folder(support)
    if current is None:
        return None
    other = _other_folder(support, current)
    other_version = tools.folder_version(other) if other else None
    back = other_version if tools.newer(other_version, builtin_version) else builtin_version
    return None if tools.same_version(back, _next_version(support, builtin_version)) else back


def _defaults(support: Path, running: Path | None, builtin: Path | None) -> tuple[Path | None, Path | None]:
    """This process's yt_dlp package and the built-in one, unless given (tests give them)."""
    builtin = builtin if builtin is not None else tools.builtin_package(support)
    if running is None:
        running = tools.running_package()
    if running is None:  # nothing imported yet: what activate() would pick
        override = tools.choose_override(support, tools.package_version(builtin) if builtin else None)
        running = override / tools.YT_DLP if override else builtin
    return running, builtin


def _version_of(package: Path | None) -> str | None:
    return tools.package_version(package) if package else None


# --- what the bridge and the console call ---

def update(support: Path, *, fetch: Callable[[str], bytes] | None = None, run: Callable | None = None,
           check: Callable[[], None] | None = None, running: Path | None = None,
           builtin: Path | None = None) -> tuple[dict, dict, bool]:
    """The newest yt-dlp (and the yt-dlp-ejs it pins), when it is newer than what the next start would use:
    downloaded, hash-checked, unpacked, tested in its own process, then `current`. (before, after, restart):
    {"yt-dlp": version} the next start uses before / after; restart: `after` isn't what this process runs. ToolsError
    when anything fails, and then `current` is as it was. `check()` raises Cancelled to stop (the hub's Stop)."""
    fetch = fetch or http_get  # looked up now: tests replace http_get
    run = run or subprocess.run
    check = check or (lambda: None)
    running, builtin = _defaults(support, running, builtin)
    running_version, builtin_version = _version_of(running), _version_of(builtin)
    before = {"yt-dlp": _next_version(support, builtin_version)}

    check()
    latest_release = _fetch_json(fetch, PYPI_LATEST.format(name="yt-dlp"))
    latest = latest_release["info"].get("version")
    if tools.parse_version(latest) is None:
        raise ToolsError(BAD_ANSWER)
    if not tools.newer(latest, before["yt-dlp"]):
        return before, before, not tools.same_version(before["yt-dlp"], running_version)
    yt_wheel = _wheel(latest_release)
    pin = ejs_pin(latest_release["info"])
    ejs_release = _fetch_json(fetch, PYPI_RELEASE.format(name="yt-dlp-ejs", version=pin) if pin
                              else PYPI_LATEST.format(name="yt-dlp-ejs"))
    ejs_version = pin or ejs_release["info"].get("version")
    ejs_wheel = _wheel(ejs_release)
    check()
    yt_data = _download(fetch, yt_wheel)
    check()
    ejs_data = _download(fetch, ejs_wheel)
    check()

    root = tools.tools_root(support)
    previous = tools.current_folder(support)
    final = root / latest
    partial = root / f"{tools.PARTIAL_PREFIX}{latest}"
    try:
        root.mkdir(parents=True, exist_ok=True)
        _clear_leftovers(support)
        partial.mkdir()
        unpack(yt_data, partial)
        unpack(ejs_data, partial)
        # The frozen app writes no bytecode of its own; without .pyc every start would compile yt-dlp again.
        compileall.compile_dir(str(partial), quiet=1, force=True, ddir=str(final))
        check()
        _run_check(run, partial, {"yt-dlp": latest, "yt-dlp-ejs": ejs_version}, check)
        check()
        _sync_to_disk(partial)
        if final.exists() and not (running is not None and tools.inside(running, final)):
            tools.remove_unless_in_use(final)
        if not final.exists():
            os.rename(partial, final)
        _point_current(support, final)
        _sync_folder(root)
    except OSError as e:
        raise _disk_error(e) from None
    finally:
        shutil.rmtree(partial, ignore_errors=True)
    keep = {final.resolve(), previous}
    for folder in _named_folders(support):  # also a broken one left from before
        if folder not in keep:
            _remove(folder, running)
    after = {"yt-dlp": _next_version(support, builtin_version)}
    return before, after, not tools.same_version(after["yt-dlp"], running_version)


def rollback(support: Path, *, running: Path | None = None,
             builtin: Path | None = None) -> tuple[dict, dict, bool]:
    """One step back: `current` -> the folder kept from before, or no `current` (the built-in yt-dlp) when there is
    none. The folder stepped back from is deleted unless this process runs it. Same answer as update();
    ToolsError(NOTHING_TO_UNDO, kind "refused") when stepping back would change nothing."""
    running, builtin = _defaults(support, running, builtin)
    builtin_version = _version_of(builtin)
    if _after_rollback(support, builtin_version) is None:
        raise ToolsError(NOTHING_TO_UNDO, "refused")
    current = tools.current_folder(support)
    before = {"yt-dlp": _next_version(support, builtin_version)}
    try:
        _point_current(support, _other_folder(support, current))
        _sync_folder(tools.tools_root(support))
    except OSError as e:
        raise _disk_error(e) from None
    _remove(current, running)
    after = {"yt-dlp": _next_version(support, builtin_version)}
    return before, after, not tools.same_version(after["yt-dlp"], _version_of(running))


def _streamrip_version() -> str | None:
    try:
        return importlib.metadata.version("streamrip")
    except importlib.metadata.PackageNotFoundError:  # a frozen app without its metadata
        return getattr(sys.modules.get("streamrip"), "__version__", None)


def status(support: Path, *, running: Path | None, builtin: Path | None) -> dict:
    """Settings → This Mac: per download tool {version this process runs, source "built_in"|"updated", waiting (the
    version the next start uses, when it differs), previous (what "Go back" would use)}."""
    running_version, builtin_version = _version_of(running), _version_of(builtin)
    upcoming = _next_version(support, builtin_version)
    yt = {"version": running_version,
          "source": "updated" if running is not None and tools.inside(running, tools.tools_root(support))
          else "built_in",
          "waiting": upcoming if upcoming and not tools.same_version(upcoming, running_version) else None,
          "previous": _after_rollback(support, builtin_version)}
    streamrip = {"version": _streamrip_version(), "source": "built_in", "waiting": None, "previous": None}
    return {"yt-dlp": yt, "streamrip": streamrip}


def current_status(support: Path) -> dict:
    """status() of this process."""
    running, builtin = _defaults(support, None, None)
    return status(support, running=running, builtin=builtin)


def update_line(before: dict, after: dict) -> str:
    """The console's line for update() or rollback()."""
    was, now = before.get("yt-dlp"), after.get("yt-dlp")
    if tools.same_version(was, now):
        return f"yt-dlp {now} is already the newest."
    return f"yt-dlp {was} -> {now}" if was else f"yt-dlp updated to {now}"
