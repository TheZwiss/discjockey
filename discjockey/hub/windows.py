"""Which windows are open (design §6.6). Each window writes `<support>/windows/<pid>.json` (`pid`, `pid_started`,
`music`) and holds an `flock` on it while open; `count_open` counts the files whose lock is held, so a window that was
killed counts for nothing (the system lets its lock go) and a window start removes the files it left. The window's
own `<support>/.window.lock` (`window_port.py`) is never touched here: taking it to probe it could make a window that
is starting think it is not the first and lose its saved settings (R19)."""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import IO

from ..library import write_json_atomic
from . import registry

FOLDER = "windows"


def _folder(support: Path) -> Path:
    return Path(support) / FOLDER


def _files(support: Path) -> list[Path]:
    try:
        return sorted(_folder(support).glob("*.json"))
    except OSError:
        return []


class WindowFile:
    """This window's file, with its lock held until `close`."""

    def __init__(self, path: Path, lock: IO | None):
        self.path, self.lock = path, lock

    def close(self) -> None:
        """Lets go of the lock and removes the file (once)."""
        lock, self.lock = self.lock, None
        if lock is None:
            return
        try:
            self.path.unlink()
        except OSError:
            pass
        lock.close()  # closing the file lets go of the flock


def _remove_stale(support: Path) -> None:
    """Removes every window file whose lock nobody holds (its window is gone)."""
    for path in _files(support):
        try:
            with open(path, "a") as f:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue  # an open window
                path.unlink()  # still holding the lock: no window can have taken it meanwhile
        except OSError:
            continue


def register(support: Path, music: Path | str | None) -> WindowFile:
    """Writes this process's window file, holds its lock, and removes the files of windows that are gone. Never fails:
    a folder that can't be written leaves a `WindowFile` that holds nothing (the window just isn't counted)."""
    pid = os.getpid()
    path = _folder(support) / f"{pid}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _remove_stale(support)
        for _ in range(3):
            write_json_atomic(path, {"pid": pid, "pid_started": registry.process_started(pid),
                                     "music": str(music) if music is not None else None})
            f = open(path, "a")
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                same = os.stat(path).st_ino == os.fstat(f.fileno()).st_ino
            except OSError:
                same = False
            if same:  # not replaced or removed by another window's clean-up in between
                return WindowFile(path, f)
            f.close()
    except OSError:
        pass
    return WindowFile(path, None)


def count_open(support: Path) -> int:
    """How many windows are open: the files whose lock is held. A shared try, let go of at once."""
    held = 0
    for path in _files(support):
        try:
            with open(path, "r") as f:
                try:
                    fcntl.flock(f, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError:
                    held += 1
        except OSError:
            continue
    return held
