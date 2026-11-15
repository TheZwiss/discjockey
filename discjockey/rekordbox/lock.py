"""`<support>/rekordbox.lock`: one Discjockey writer of rekordbox's library per Mac (design rekordbox-repoint §5.3
guard 6). A batch's `Session`, a backup `restore` and a crash recovery of rekordbox's analysis files hold it while
they change anything of rekordbox's; the lock is an flock, tried for up to 2 s, so another holder (another window,
the Terminal, another music folder on this Mac) is `Busy`. Readers of rekordbox's library take it shared and without
waiting (`reader_lock`): while a writer holds it they never open master.db, and a reader's brief hold never makes a
writer `Busy` (its 2 s retry). Its own module so `session` and `backup` share it."""
from __future__ import annotations

import fcntl
import os
import time
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from ..problem import Problem

BUSY = "Discjockey is already changing your rekordbox library in another window or the Terminal."
LOCK_NAME = "rekordbox.lock"
WRITER_WAIT_S, WRITER_RETRY_S = 2.0, 0.05


class Busy(Problem):
    """Another Discjockey process holds `rekordbox.lock` (`reason` rekordbox_lock; `Problem`'s fields)."""

    def __init__(self, *, next: Iterable[Mapping] = (), person_steps: Iterable[Mapping] = (),
                 data: Mapping | None = None):
        super().__init__(BUSY, reason="rekordbox_lock", next=next, person_steps=person_steps, data=data)


@contextmanager
def writer_lock(support: Path) -> Iterator[None]:
    """Holds `rekordbox.lock` exclusively for the block. Tries for up to `WRITER_WAIT_S` (a reader's shared hold is
    brief), then raises `Busy`."""
    support.mkdir(parents=True, exist_ok=True)
    fd = os.open(support / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        deadline = time.monotonic() + WRITER_WAIT_S
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise Busy() from None
                time.sleep(WRITER_RETRY_S)
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)


@contextmanager
def reader_lock(support: Path) -> Iterator[bool]:
    """A shared, non-blocking hold on `rekordbox.lock` for the block of a reader of rekordbox's library. Yields True
    while held (no writer can start meanwhile), False when a writer holds it: the reader then never opens master.db and
    answers its rekordbox part as `writing`. Never raises `Busy`. A reader never makes the file (a read, and a dry run
    that is one, writes nothing but its plan): a support folder or a lock file that is not there has had no writer, and
    a file that cannot be opened (a read-only disk) cannot tell: all yield True, as before the lock."""
    try:
        fd = os.open(support / LOCK_NAME, os.O_RDWR) if support.is_dir() else None
    except OSError:  # no file: no writer has held it yet; or one that cannot be opened
        fd = None
    if fd is None:
        yield True
        return
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        os.close(fd)
