"""Test-only: a lock another process holds is answered "busy" after a short wait (installed by conftest.py)."""
import pytest

# A lock another process holds is answered "busy" after a short wait, not after two seconds.
#
# Production waits up to 2 s for `rekordbox.lock` and the support lock (a reader's shared hold is brief) before it
# answers busy. The tests that hold the lock themselves expect exactly that answer, and each one used to sit out the
# full 2 s. Here the waits are 0.4 s; the production values stay as they are, and
# tests/test_locks.py pins them and the full 2 s wait (`real_lock_waits`).

TEST_LOCK_WAIT_S = 0.4


@pytest.fixture(autouse=True)
def _short_lock_waits(request, monkeypatch):
    if request.node.get_closest_marker("real_lock_waits") is None:
        from discjockey import library
        from discjockey.rekordbox import lock
        monkeypatch.setattr(library, "SUPPORT_WAIT_S", TEST_LOCK_WAIT_S)
        monkeypatch.setattr(lock, "WRITER_WAIT_S", TEST_LOCK_WAIT_S)
