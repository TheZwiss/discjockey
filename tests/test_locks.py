"""Locks across processes (issue 39, group 1.7; design §6.1): the support lock around every read-change-write of the
support folder's files, the shared `rekordbox.lock` of readers and the writer's retry, and `tools update` refused while
a write job runs. The two-process tests start real children on scratch folders (`tmp_path`); the `procs` fixture
kills what a test left and fails it when a child outlives it."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from batch_helpers import make_lib, needs_ffmpeg
from hub_helpers import make_api, make_unbound_api, services, wait_job
from discjockey import library, rekordbox, tool_updates
from discjockey.hub import catalog, registry
from discjockey.rekordbox import lock as rb_lock
from discjockey.settings import Settings, load_settings, save_settings, update_settings

REPO = Path(__file__).resolve().parent.parent

COUNTER = """
import sys
from dataclasses import replace
from pathlib import Path
from discjockey.settings import update_settings
path, n = Path(sys.argv[1]), int(sys.argv[2])
sys.stdin.readline()  # the start signal: both children begin together
for _ in range(n):
    update_settings(path, lambda s: replace(s, daily_qobuz_limit=s.daily_qobuz_limit + 1))
"""

HOLD = """
import sys
from pathlib import Path
from discjockey import library
from discjockey.rekordbox import lock
support, which = Path(sys.argv[1]), sys.argv[2]
hold = library.support_lock if which == "support" else lock.writer_lock
with hold(support):
    print("held", flush=True)
    sys.stdin.read()  # held until the parent closes stdin
"""


class Procs:
    def __init__(self):
        self.started: list[subprocess.Popen] = []

    def spawn(self, script: str, *args) -> subprocess.Popen:
        p = subprocess.Popen([sys.executable, "-c", script, *map(str, args)], cwd=REPO, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True)
        self.started.append(p)
        return p

    def holder(self, support: Path, which: str) -> subprocess.Popen:
        """A child that holds the support lock (`which` "support") or `rekordbox.lock` (`"writer"`) until released."""
        p = self.spawn(HOLD, support, which)
        assert p.stdout.readline().strip() == "held"
        return p

    def release(self, p: subprocess.Popen) -> None:
        p.stdin.close()
        assert p.wait(10) == 0

    def finish(self) -> None:
        left = [p for p in self.started if p.poll() is None]
        for p in left:
            p.kill()
            p.wait(10)
        assert not left, "a child process outlived its test"


@pytest.fixture
def procs():
    p = Procs()
    try:
        yield p
    finally:
        p.finish()


@pytest.fixture
def support(tmp_path):
    folder = tmp_path / "support"
    folder.mkdir()
    return folder


# --- the support lock ---

def test_two_processes_saving_settings_at_once_lose_neither_change(procs, support):
    path = support / "settings.json"
    save_settings(path, Settings(daily_qobuz_limit=100))
    children = [procs.spawn(COUNTER, path, 40) for _ in range(2)]
    for p in children:  # the start signal, then each ends by itself
        p.stdin.write("go\n")
        p.stdin.flush()
    for p in children:
        assert p.wait(60) == 0
    assert load_settings(path).daily_qobuz_limit == 180


def test_the_support_lock_waits_two_seconds_then_answers_busy_support_lock(procs, support):
    assert (library.SUPPORT_WAIT_S, rb_lock.WRITER_WAIT_S) == (2.0, 2.0)
    holder = procs.holder(support, "support")
    started = time.monotonic()
    with pytest.raises(library.SupportBusy) as raised:
        with library.support_lock(support):
            pytest.fail("the lock was taken while another process held it")
    assert 1.8 <= time.monotonic() - started < 6
    assert raised.value.reason == "support_lock"
    procs.release(holder)
    with library.support_lock(support):  # let go when the holder ended
        pass


def test_a_busy_support_lock_is_a_busy_answer_with_the_reason_of_its_own(procs, support, monkeypatch):
    monkeypatch.setattr(library, "SUPPORT_WAIT_S", 0.3)
    api, _ = make_unbound_api(support)
    holder = procs.holder(support, "support")
    answer = api.setup_skip_import()
    assert (answer["ok"], answer["kind"], answer["outcome"], answer["reason"]) == (False, "busy", "busy", "support_lock")
    assert not (support / "settings.json").exists()  # nothing was saved
    procs.release(holder)
    assert api.setup_skip_import() == {"ok": True}
    assert load_settings(support / "settings.json").import_skipped is True


def test_a_save_inside_a_job_that_meets_the_support_lock_keeps_its_reason(procs, support, monkeypatch):
    """The job ends `busy`; the worker names the support lock as the reason, not the library."""
    from discjockey.cli import envelope, worker
    monkeypatch.setattr(library, "SUPPORT_WAIT_S", 0.3)
    api, rec = make_unbound_api(support)
    holder = procs.holder(support, "support")
    finished = wait_job(api, rec, api.setup_skip_qobuz())
    job = api._jobs.current
    assert (finished.ok, finished.problem) == (False, "busy") and job.error.reason == "support_lock"
    files = type("F", (), {"id": "job:00000000", "dir": support / "jobs" / "job:00000000"})()
    env = worker._busy("login skip qobuz", files, {}, job)
    assert (env["outcome"], env["reason"]) == ("busy", "support_lock")
    procs.release(holder)
    assert envelope.exit_code(env) == 3


def test_every_write_site_of_the_support_folder_holds_the_support_lock(support, monkeypatch):
    """The sites the group wrapped, one by one, each with a lock that records (check first: the list in the commit)."""
    from discjockey import qobuz
    from discjockey.sources import spotify
    taken = []
    real = library.support_lock

    def recording(folder):
        taken.append(Path(folder))
        return real(folder)

    monkeypatch.setattr(library, "support_lock", recording)
    update_settings(support / "settings.json", lambda s: s)
    library.write_music_folder(support, support / "music")
    spotify._save_token(support / ".spotify_token.json", {"access_token": "a"})
    api, rec = make_unbound_api(support)
    assert wait_job(api, rec, api.setup_save_client_id("0" * 32)).ok
    qobuz.write_config(library.SupportPaths(support=support))
    assert taken == [support] * 5
    assert tool_updates.library is library  # update / rollback take it through the same function


# --- tools: a support-only job ---

def test_tools_update_takes_the_support_lock_for_its_whole_run(procs, support, monkeypatch):
    monkeypatch.setattr(library, "SUPPORT_WAIT_S", 0.3)
    holder = procs.holder(support, "support")
    for call in (lambda: tool_updates.update(support, fetch=lambda url: b"", run=lambda *a, **k: None),
                 lambda: tool_updates.rollback(support)):
        with pytest.raises(library.SupportBusy):
            call()
    procs.release(holder)


def _running_job(support: Path, method: str, status: str = "running") -> registry.JobFiles:
    files = registry.Registry(support).create(method, "x", {}, "terminal", {})
    files.update(method=method, status=status)
    files.flush()
    return files


def test_tools_update_is_busy_while_a_registry_write_job_runs_and_takes_no_library_lock(support, tmp_path, monkeypatch):
    taken = []
    real = library.run_lock
    monkeypatch.setattr(library, "run_lock", lambda path: taken.append(path) or real(path))
    paths = library.Paths(tmp_path / "music", support=support)
    paths.data.mkdir(parents=True)
    api, rec = make_api(paths)
    files = _running_job(support, "rescan_library")  # `library scan`: its catalogue entry holds the library
    try:
        answer = api.update_tools()
        assert (answer["ok"], answer["kind"], answer["reason"]) == (False, "busy", "library_lock")
        assert answer["data"]["holder"]["job"] == files.id
        assert api.rollback_tools()["kind"] == "busy"
    finally:
        files.update(status="done")
        files.flush()
        files.release_claim()
    assert taken == []  # nothing took the library lock, not even to be refused
    answer = api.update_tools()  # the job is over (its claim let go): not refused any more
    assert answer["ok"], answer
    finished = wait_job(api, rec, answer)
    assert finished.problem == "failed"  # no network in tests: it got as far as asking
    assert taken == []  # a support-only job never takes the library lock
    assert (support / ".support.lock").exists()


def test_a_running_job_that_holds_no_library_lock_does_not_stop_tools_update(support, tmp_path):
    paths = library.Paths(tmp_path / "music", support=support)
    paths.data.mkdir(parents=True)
    api, rec = make_api(paths)
    files = _running_job(support, "rekordbox_status")  # a read: no library lock in its entry
    try:
        assert api.update_tools()["ok"]
        wait_job(api, rec, {"ok": True, "job_id": api._jobs.current.id})
    finally:
        files.update(status="done")
        files.release_claim()


# --- rekordbox readers ---

def test_a_reader_never_makes_a_writer_busy_and_a_writer_makes_the_reader_say_so(support):
    with rb_lock.reader_lock(support) as free:
        assert free is True
        with rb_lock.reader_lock(support) as second:  # readers share
            assert second is True
    with rb_lock.writer_lock(support):
        with rb_lock.reader_lock(support) as free:
            assert free is False


def test_the_writer_retries_while_a_reader_holds_and_goes_on_when_it_lets_go(support):
    import threading
    release = threading.Event()
    held = threading.Event()

    def reader():
        with rb_lock.reader_lock(support) as free:
            assert free
            held.set()
            release.wait(5)

    t = threading.Thread(target=reader)
    t.start()
    try:
        assert held.wait(5)
        threading.Timer(0.3, release.set).start()
        started = time.monotonic()
        with rb_lock.writer_lock(support):  # the reader's brief hold: the writer waited, never `Busy`
            waited = time.monotonic() - started
        assert 0.2 <= waited < 2.0
    finally:
        release.set()
        t.join(5)


def test_the_writer_is_busy_after_two_seconds_when_another_writer_holds(procs, support):
    holder = procs.holder(support, "writer")
    started = time.monotonic()
    with pytest.raises(rb_lock.Busy) as raised:
        with rb_lock.writer_lock(support):
            pytest.fail("two writers")
    assert 1.8 <= time.monotonic() - started < 6 and raised.value.reason == "rekordbox_lock"
    procs.release(holder)


def test_a_reader_without_a_support_folder_or_a_writable_one_reads_as_before(tmp_path):
    with rb_lock.reader_lock(tmp_path / "not-there") as free:
        assert free is True
    assert not (tmp_path / "not-there").exists()  # a read makes no folder


def test_status_with_a_writer_holding_answers_writing_with_the_last_value_and_as_of(procs, support, monkeypatch):
    api, _ = make_unbound_api(support)
    first = api.rekordbox_status()
    assert first == {"ok": True, "state": "none", "running": False}  # nobody writes: no `writing` key
    boom = lambda *a, **k: pytest.fail("master.db was opened while a writer held rekordbox.lock")  # noqa: E731
    monkeypatch.setattr(rekordbox, "status", boom)
    holder = procs.holder(support, "writer")
    again = api.rekordbox_status()
    assert again == {"ok": True, "state": "none", "running": False, "writing": True, "as_of": "2026-10-20T21:47:00"}
    procs.release(holder)


def test_status_with_a_writer_and_nothing_read_yet_answers_ready_writing_without_as_of(procs, support, monkeypatch):
    api, _ = make_unbound_api(support)
    monkeypatch.setattr(rekordbox, "status", lambda *a, **k: pytest.fail("opened"))
    holder = procs.holder(support, "writer")
    assert api.rekordbox_status() == {"ok": True, "state": "ready", "running": False, "writing": True, "as_of": None}
    procs.release(holder)


@needs_ffmpeg
def test_todo_and_track_never_open_master_db_while_a_writer_holds_rekordbox_lock(procs, tmp_path, monkeypatch):
    from discjockey.rekordbox import master
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "clean"])
    api, rec = make_api(lib.paths, rekordbox_running=lambda: False, rekordbox_place=lambda: lib.place)
    todo, track = api.todo(), api.track(lib.tracks[0])  # the first reads open it and fill the cache
    assert todo["ok"] and track["ok"]
    opened = []
    real = master.open_read
    monkeypatch.setattr(master, "open_read", lambda *a, **k: opened.append(a) or real(*a, **k))
    monkeypatch.setattr(rekordbox, "status", lambda *a, **k: pytest.fail("master.db was opened"))
    with open(lib.place.db, "ab") as f:  # master.db changed: a free reader would open it again
        f.write(b"\0")
    holder = procs.holder(lib.paths.support, "writer")
    assert api.todo()["ok"] and api.track(lib.tracks[0])["track"]["upgrade"] is not None
    assert api.rekordbox_status()["writing"] is True and opened == []
    procs.release(holder)


# --- the catalogue's `locks` column ---

def test_the_locks_words_are_the_four_of_the_design():
    assert catalog.LOCKS == ("library", "support", "rekordbox_w", "rekordbox_r")
    assert all(e.locks <= set(catalog.LOCKS) for e in catalog.ENTRIES)
