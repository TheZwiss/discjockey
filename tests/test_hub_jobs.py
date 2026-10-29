import threading
import time
from contextlib import contextmanager

import pytest

from discjockey import library, run
from discjockey.events import AccountUsage, ActionFinished, Cancelled, Message, PlannedAction, Progress, Result, RunStarted
from discjockey.hub import jobs
from discjockey.hub.jobs import Busy, Jobs
from discjockey.models import Protected
from discjockey.library import Paths, run_lock
from discjockey.ops import OpProblem


class Recorder:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def of(self, cls):
        return [e for e in self.events if isinstance(e, cls)]


@pytest.fixture
def env(tmp_path):
    paths = Paths(tmp_path, support=tmp_path / ".support")
    paths.data.mkdir()
    awake = []

    @contextmanager
    def fake_awake(reason):
        awake.append(("begin", reason))
        yield
        awake.append(("end", reason))

    rec = Recorder()
    return paths, Jobs(paths.lock, rec.emit, keep_awake=fake_awake), rec, awake


def test_a_job_holds_the_lock_and_keeps_the_mac_awake(env):
    paths, js, rec, awake = env
    seen = {}

    def work(ctx):
        with pytest.raises(library.LockHeld):  # a console run started now would have to wait
            with run_lock(paths.lock):
                pass
        seen["awake"] = list(awake)
        return {"done": 1}

    job = js.start("hide", work, track_id="t1")
    assert job.done.wait(5)
    assert seen["awake"] == [("begin", "Discjockey is changing your library")]
    assert awake[-1][0] == "end"
    started, finished = rec.of(jobs.JobStarted), rec.of(jobs.JobFinished)
    assert started == [jobs.JobStarted(job.id, "hide", "t1")]
    assert finished == [jobs.JobFinished(job.id, "hide", True, None, "", {"done": 1})]
    with run_lock(paths.lock):  # released afterwards
        pass


def test_only_one_write_job_at_a_time(env):
    paths, js, rec, _ = env
    release = threading.Event()
    job = js.start("sync", lambda ctx: release.wait(5) and None)
    with pytest.raises(Busy) as excinfo:
        js.start("hide", lambda ctx: None)
    assert excinfo.value.kind == "busy"
    release.set()
    assert job.done.wait(5)
    js.start("hide", lambda ctx: None).done.wait(5)  # fine again afterwards


def test_a_console_run_makes_jobs_wait(env):
    paths, js, rec, _ = env
    with run_lock(paths.lock):
        assert js.console_running()
        with pytest.raises(Busy) as excinfo:
            js.start("hide", lambda ctx: pytest.fail("must not run"))
        assert excinfo.value.kind == "console" and "terminal" in str(excinfo.value)
    assert not js.console_running()


def test_a_console_run_that_starts_in_the_same_moment(env, monkeypatch):
    paths, js, rec, _ = env
    monkeypatch.setattr(js, "console_running", lambda: False)  # the check came just before the console took the lock
    with run_lock(paths.lock):
        job = js.start("hide", lambda ctx: pytest.fail("must not run"))
        assert job.done.wait(5)
    finished = rec.of(jobs.JobFinished)[-1]
    assert (finished.ok, finished.problem) == (False, "console")


def test_own_job_is_not_mistaken_for_the_console(env):
    paths, js, rec, _ = env
    release = threading.Event()
    job = js.start("sync", lambda ctx: release.wait(5) and None)
    time.sleep(0.1)
    assert not js.console_running()
    release.set()
    job.done.wait(5)


def test_stop_sets_the_jobs_token(env):
    paths, js, rec, _ = env

    def work(ctx):
        while True:
            ctx.token.check()
            time.sleep(0.01)

    job = js.start("sync", work)
    assert js.stop() is True and job.done.wait(5)
    finished = rec.of(jobs.JobFinished)[-1]
    assert (finished.ok, finished.problem) == (False, "stopped")
    assert js.stop() is False  # nothing runs any more


@pytest.mark.parametrize("error,problem", [
    (run.SetupProblem("Spotify is not set up yet.", "not_set_up"), "not_set_up"),
    (OpProblem("This track changed in the meantime.", "changed"), "changed"),
    (ValueError("That is not a Spotify playlist link."), "refused"),
    (RuntimeError("boom"), "crashed"),
    (Protected("SoundCloud marks this upload as DRM-protected"), "protected"),
])
def test_problems_become_a_kind_and_a_plain_message(env, error, problem):
    paths, js, rec, _ = env

    def work(ctx):
        raise error

    js.start("x", work).done.wait(5)
    finished = rec.of(jobs.JobFinished)[-1]
    assert (finished.ok, finished.problem) == (False, problem)
    # a crash never shows the error itself, and a job that isn't a sync never says "the sync stopped"
    expected = jobs.UNEXPECTED if problem == "crashed" else str(error)
    assert expected in finished.message and "Traceback" not in finished.message


def test_the_snapshot_keeps_the_last_event_of_each_kind_and_all_results(env):
    paths, js, rec, _ = env

    def work(ctx):
        ctx.emit(RunStarted(2, (PlannedAction("acquire", "t1", "One", "Artist"),)))
        for i in range(3):
            ctx.emit(Progress("t1", "download", i, 2, "bytes"))
        ctx.emit(ActionFinished(None, Result("new_lossless", "A", "Artist", "One", "t1")))
        ctx.emit(ActionFinished(None, Result("missing", "A", "Artist", "Two", "t2")))
        ctx.emit(Message("info", "done"))
        return None

    job = js.start("sync", work)
    job.done.wait(5)
    snap = js.status()["job"]
    assert snap["id"] == job.id and snap["kind"] == "sync" and snap["running"] is False
    assert snap["last"]["Progress"]["done"] == 2 and snap["last"]["RunStarted"]["total"] == 2
    assert [r["result"]["title"] for r in snap["results"]] == ["One", "Two"]
    assert snap["actions"] == [{"kind": "acquire", "track_id": "t1", "title": "One", "artist": "Artist",
                              "image_url": None}]
    assert snap["finished"]["ok"] is True
    assert len(rec.of(Progress)) == 3  # the window got every one


def test_the_snapshot_keeps_the_newest_account_usage_of_each_service(env):
    paths, js, rec, _ = env

    def work(ctx):
        ctx.emit(AccountUsage("qobuz", 1, 80))
        ctx.emit(AccountUsage("youtube", 3, 50))
        ctx.emit(AccountUsage("qobuz", 2, 80))
        return None

    js.start("sync", work).done.wait(5)
    snap = js.status()["job"]
    assert snap["usage"] == [{"type": "AccountUsage", "service": "qobuz", "used": 2, "allowance": 80},
                             {"type": "AccountUsage", "service": "youtube", "used": 3, "allowance": 50}]
    assert snap["last"]["AccountUsage"]["service"] == "qobuz"


def test_a_broken_event_does_not_break_the_job(env):
    paths, js, rec, _ = env
    job = js.start("sync", lambda ctx: ctx.emit(object()) or {"ok": 1})
    job.done.wait(5)
    assert rec.of(jobs.JobFinished)[-1].ok


def test_refresh_runs_without_the_lock_and_has_its_own_stop(env):
    paths, js, rec, _ = env
    seen = {}

    def work(ctx):
        with run_lock(paths.lock):  # read-only work never holds the lock, so it is free
            seen["lock"] = "free"
        while True:
            ctx.token.check()
            time.sleep(0.01)

    job = js.start_refresh(work)
    time.sleep(0.05)
    with pytest.raises(Busy):
        js.start_refresh(lambda ctx: None)
    assert js.stop_refresh() and job.done.wait(5)
    assert seen == {"lock": "free"}
    assert rec.of(jobs.JobFinished)[-1].problem == "stopped"


def test_stop_ends_a_refresh_at_once_even_while_its_work_is_stuck(env):
    """A refresh whose work does not look at the token (one slow request): Stop marks it stopped right away; what
    the work still sends or returns later never reaches the window, and a new read can start meanwhile."""
    paths, js, rec, _ = env
    release, ended = threading.Event(), threading.Event()

    def work(ctx):
        release.wait(10)
        ctx.emit(Message("info", "late"))
        ended.set()
        return {"actions": 9}

    job = js.start_refresh(work)
    time.sleep(0.05)
    t0 = time.monotonic()
    assert js.stop_refresh() and job.done.wait(2) and time.monotonic() - t0 < 2
    assert rec.of(jobs.JobFinished)[-1].problem == "stopped" and not js.status()["refresh_running"]
    assert not js.stop_refresh()  # already stopped
    again = js.start_refresh(lambda ctx: {"actions": 1})
    assert again.done.wait(5)
    release.set()
    assert ended.wait(5)
    time.sleep(0.05)
    finished = [e.job_id for e in rec.of(jobs.JobFinished)]
    assert finished == [job.id, again.id]  # the stuck one finished once, as stopped
    assert not [e for e in rec.of(Message) if e.text == "late"]
    assert job.finished["problem"] == "stopped"


def test_refresh_is_refused_while_the_hubs_own_sync_runs(env):
    paths, js, rec, _ = env
    release = threading.Event()
    job = js.start("sync", lambda ctx: release.wait(5) and None)
    with pytest.raises(Busy):
        js.start_refresh(lambda ctx: None)
    release.set()
    job.done.wait(5)


def test_console_watch_reports_changes(env):
    paths, js, rec, _ = env
    js.watch_console(interval=0.05)
    try:
        with run_lock(paths.lock):
            assert wait_for(lambda: jobs.ConsoleBusy(True) in rec.events)
        assert wait_for(lambda: rec.events[-1] == jobs.ConsoleBusy(False))
    finally:
        js.close()


def wait_for(cond, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_wait_for_the_job_to_end(env):
    paths, js, rec, _ = env
    js.start("sync", lambda ctx: time.sleep(0.1))
    assert js.wait(5) is True and js.running() is None


def test_keep_awake_does_not_fail_without_pyobjc(monkeypatch):
    import builtins
    real = builtins.__import__

    def no_foundation(name, *a, **k):
        if name == "Foundation":
            raise ImportError
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_foundation)
    with jobs.keep_awake("test"):
        pass


def test_cancelled_is_stopped(env):
    paths, js, rec, _ = env

    def work(ctx):
        raise Cancelled()

    js.start("x", work).done.wait(5)
    assert rec.of(jobs.JobFinished)[-1].problem == "stopped"


def test_lock_briefly_takes_the_lock_outside_a_job_and_never_twice_inside_one(env):
    paths, js, rec, _ = env
    with js.lock_briefly():  # a sign-in's settings save
        with pytest.raises(library.LockHeld):
            with run_lock(paths.lock):
                pass
        assert not js.console_running()  # our own save is no terminal run
    seen = {}

    def work(ctx):
        with js.lock_briefly():  # inside the write job: the lock is held already, nothing is taken
            seen["inside"] = True
        return {}

    assert js.start("save_limits", work).done.wait(5) and seen == {"inside": True}


def test_lock_briefly_answers_busy_or_console_instead_of_waiting(env):
    paths, js, rec, _ = env
    with run_lock(paths.lock):  # a terminal run
        with pytest.raises(Busy) as excinfo:
            with js.lock_briefly():
                pytest.fail("must not run")
        assert excinfo.value.kind == "console"
    release = threading.Event()
    job = js.start("sync", lambda ctx: release.wait(5) and None)
    with pytest.raises(Busy) as excinfo:
        with js.lock_briefly():
            pytest.fail("must not run")
    assert excinfo.value.kind == "busy"
    release.set()
    assert job.done.wait(5)
    with js.lock_briefly():  # free again
        pass


def at_once(call):
    """`call()`'s result or exception, failing the test if it waits (instead of hanging it)."""
    out = {}

    def target():
        try:
            out["value"] = call()
        except BaseException as e:  # noqa: BLE001 - handed to the test
            out["error"] = e
    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(2)
    assert not t.is_alive(), "waited instead of answering at once"
    if "error" in out:
        raise out["error"]
    return out["value"]


def test_a_scan_holds_the_file_lock_and_everything_else_answers_at_once(env):
    paths, js, rec, _ = env
    entered, release, seen = threading.Event(), threading.Event(), {}

    def scan():
        with js.scan_lock() as held:
            seen["held"] = held
            entered.set()
            release.wait(5)
    scanner = threading.Thread(target=scan)
    scanner.start()
    assert entered.wait(5) and seen["held"] is True
    with pytest.raises(library.LockHeld):
        with run_lock(paths.lock):  # a terminal run can't start meanwhile
            pass
    assert not js.console_running()  # our own scan is no terminal run
    with pytest.raises(Busy) as excinfo:
        at_once(lambda: js.start("sync", lambda ctx: None))
    assert excinfo.value.kind == "busy"

    def brief():
        with js.lock_briefly():
            pytest.fail("must not run")
    with pytest.raises(Busy):
        at_once(brief)

    def second_scan():
        with js.scan_lock() as held:
            return held
    assert at_once(second_scan) is False
    assert at_once(lambda: js.start_sign_in("sign_in", lambda ctx: None)).done.wait(5)
    assert at_once(lambda: js.start_refresh(lambda ctx: None)).done.wait(5)
    release.set()
    scanner.join(5)
    assert js.start("sync", lambda ctx: None).done.wait(5)  # free again


def test_a_scan_does_without_the_lock_while_someone_else_has_it(env):
    paths, js, rec, _ = env
    with run_lock(paths.lock):  # a terminal run
        with js.scan_lock() as held:
            assert held is False
    release = threading.Event()
    job = js.start("sync", lambda ctx: release.wait(5) and None)
    with js.scan_lock() as held:
        assert held is False
    release.set()
    assert job.done.wait(5)
    with js.scan_lock() as held:
        assert held is True


def test_jobs_without_a_library_run_without_the_file_lock(tmp_path):
    js = Jobs(None, lambda e: None, keep_awake=lambda reason: contextmanager(lambda: (yield))())
    done = threading.Event()
    js.start("setup_skip_qobuz", lambda ctx: done.set())
    assert done.wait(5) and js.wait(5)
    assert js.console_running() is False
    with js.lock_briefly():
        pass
    lock = tmp_path / ".discjockey" / ".lock"
    js.bind(lock)
    with js.lock_briefly():
        assert lock.exists()


def test_a_job_after_the_music_folder_went_away_is_no_library(tmp_path):
    rec = Recorder()
    js = Jobs(tmp_path / "gone" / ".discjockey" / ".lock", rec.emit,
              keep_awake=lambda reason: contextmanager(lambda: (yield))())
    js.start("hide", lambda ctx: pytest.fail("must not run"))
    js.wait(5)
    fin = rec.of(jobs.JobFinished)[-1]
    assert (fin.ok, fin.problem) == (False, "no_library") and not (tmp_path / "gone").exists()


# --- the import as a job (plan library stage 4, D4, W6, W7) ---

def test_every_other_write_answers_busy_with_the_import_words_while_it_runs(env):
    from discjockey.hub.jobs import BUSY_TEXT, IMPORTING_TEXT, SCANNING_TEXT
    paths, js, rec, _ = env
    release = threading.Event()
    job = js.start("import", lambda ctx: release.wait(5) and None)
    try:
        with pytest.raises(Busy) as excinfo:
            js.start("hide", lambda ctx: None)
        assert (excinfo.value.kind, str(excinfo.value)) == ("busy", IMPORTING_TEXT)
        with pytest.raises(Busy) as excinfo, js.lock_briefly():
            pass
        assert str(excinfo.value) == IMPORTING_TEXT
    finally:
        release.set()
    assert job.done.wait(5)
    release.clear()
    other = js.start("sync", lambda ctx: release.wait(5) and None)
    with pytest.raises(Busy) as excinfo:
        js.start("import", lambda ctx: None)
    assert str(excinfo.value) == BUSY_TEXT  # the words belong to the import running, not to starting one
    release.set()
    other.done.wait(5)
    assert "importing" in IMPORTING_TEXT and "Settings → Watched folders" in IMPORTING_TEXT
    assert SCANNING_TEXT != IMPORTING_TEXT


@pytest.mark.parametrize("left,words", [
    (7, "Import stopped with 7 files to go. It carries on where it stopped."),
    (1, "Import stopped with 1 file to go. It carries on where it stopped."),
])
def test_a_stopped_import_finishes_stopped_with_its_result_and_its_words(env, left, words):
    from dataclasses import asdict
    from discjockey import importer
    paths, js, rec, _ = env
    result = importer.ImportResult(3, 3, 1, 0, left, True, None)

    def work(ctx):
        ctx.failed_result = asdict(result)
        raise importer.ImportStopped(result)

    js.start("import", work).done.wait(5)
    finished = rec.of(jobs.JobFinished)[-1]
    assert (finished.ok, finished.problem, finished.message) == (False, "stopped", words)
    assert finished.result["stopped"] is True and finished.result["left"] == left


def test_a_job_can_word_its_own_success(env):
    paths, js, rec, _ = env

    def work(ctx):
        ctx.message = "Imported 1 file."
        return {"files": 1}

    js.start("import", work).done.wait(5)
    finished = rec.of(jobs.JobFinished)[-1]
    assert (finished.ok, finished.message, finished.result) == (True, "Imported 1 file.", {"files": 1})
    js.start("hide", lambda ctx: None).done.wait(5)
    assert rec.of(jobs.JobFinished)[-1].message == ""  # no words unless the work sets them


def test_an_older_plan_arriving_late_leaves_the_newer_preview():
    from datetime import datetime
    from discjockey.hub.jobs import PreviewStore
    from discjockey.models import Plan
    from discjockey.run import Prepared
    from discjockey.settings import Settings

    def prep(generation):
        st = {"version": 2, "tracks": {}, "generation": generation}
        return Prepared(None, st, Settings(), Plan(st, [], [], []), None)

    store = PreviewStore()
    newer, older = prep(5), prep(3)
    store.ready(newer, datetime(2026, 10, 25, 12, 0))
    store.ready(older, datetime(2026, 10, 25, 12, 5))  # the opening scan's slow read finishes last
    assert store.prep is newer and store.read_at == datetime(2026, 10, 25, 12, 0)
    store.ready(prep(5), datetime(2026, 10, 25, 12, 6))  # the same records planned again is taken
    assert store.read_at == datetime(2026, 10, 25, 12, 6)
    store.ready(prep(7), datetime(2026, 10, 25, 12, 7))
    assert store.prep.state["generation"] == 7
