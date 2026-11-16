"""Test-only: no test waits for the drive (installed by conftest.py)."""
import fcntl
import sqlite3

import pytest

from discjockey import db

# Discjockey asks the drive to write out what it saves: library.db commits run with `synchronous = FULL` and
# `fullfsync` (SQLite), and library.full_fsync is F_FULLFSYNC. On this Mac that is 20 ms per commit instead of 5, and
# 4 ms per call, and the convert, undo, batch and sync tests do hundreds of them. Those only matter when the power
# goes out, which no test cuts (a crash here is an exception, the data is in the OS either way). So the tests keep every
# call and every order of them, and only the drive is not asked: `fcntl.fcntl(fd, F_FULLFSYNC)` returns at once, and
# the three durability pragmas library.db's connection sets are answered as OFF. A test with `real_durability` runs with
# the real ones: the pragma pin (tests/test_db.py), one real `library.full_fsync` call (tests/test_library_state.py) and
# the six-minute timing test. What the suite no longer does in this process is make the drive flush at every save; the
# order and the calls of the flushes are still checked by the tests that record them.

_durable = False
_real_fcntl = fcntl.fcntl
_real_execute = sqlite3.Connection.execute
_OFF = {"PRAGMA synchronous = FULL": "PRAGMA synchronous = OFF", "PRAGMA fullfsync = ON": "PRAGMA fullfsync = OFF",
        "PRAGMA checkpoint_fullfsync = ON": "PRAGMA checkpoint_fullfsync = OFF"}


def _fcntl(fd, cmd, *a):
    if cmd == getattr(fcntl, "F_FULLFSYNC", None) and not _durable:
        return 0
    return _real_fcntl(fd, cmd, *a)


def _execute(self, sql, *a, **k):
    return _real_execute(self, sql if _durable else _OFF.get(sql, sql), *a, **k)


fcntl.fcntl = _fcntl
db._Connection.execute = _execute


@pytest.fixture(autouse=True)
def _durability(request):
    global _durable
    _durable = request.node.get_closest_marker("real_durability") is not None
    yield
    _durable = False
