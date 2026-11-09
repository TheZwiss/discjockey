"""`<support>/rekordbox.lock`: one Discjockey writer of rekordbox's library per Mac (design rekordbox-repoint §5.3
guard 6). A batch's `Session`, a backup `restore` and a crash recovery of rekordbox's analysis files hold it while
they change anything of rekordbox's; the lock is an flock, taken without waiting, so another holder (another window,
the Terminal, another music folder on this Mac) is `Busy`. Its own module so `session` and `backup` share it."""
from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

BUSY = "Discjockey is already changing your rekordbox library in another window or the Terminal."
LOCK_NAME = "rekordbox.lock"


class Busy(Exception):
    """Another Discjockey process holds `rekordbox.lock`."""

    def __init__(self):
        super().__init__(BUSY)


@contextmanager
def writer_lock(support: Path) -> Iterator[None]:
    """Holds `rekordbox.lock` for the block, else raises `Busy` at once."""
    support.mkdir(parents=True, exist_ok=True)
    fd = os.open(support / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy() from None
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
