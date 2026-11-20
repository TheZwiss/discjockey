import json
import os
import threading
import time
from contextlib import contextmanager

import pytest

from discjockey import events as ev, library, qobuz, run
from discjockey.events import AccountUsage, ActionFinished, Cancelled, Message, PlannedAction, Progress, Result, RunStarted
from discjockey.hub import jobs, outcomes, registry
from discjockey.hub.api import HubApi, bridge
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


@pytest.mark.shapes_unchecked  # a stub's result under a real job kind
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


@pytest.mark.shapes_unchecked  # a stub's result under a real job kind
def test_the_started_event_carries_the_batch_kind_the_snapshot_does(env):
    paths, js, rec, _ = env
    job = js.start("aiff_batch", lambda ctx: {}, batch_kind="convert")
    assert job.done.wait(5)
    other = js.start("hide", lambda ctx: None, track_id="t1")
    assert other.done.wait(5)
    assert rec.of(jobs.JobStarted) == [jobs.JobStarted(job.id, "aiff_batch", None, "convert"),
                                       jobs.JobStarted(other.id, "hide", "t1", None)]
    assert job.snapshot()["batch_kind"] == "convert"


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
    monkeypatch.setattr(js, "_console_busy", lambda: None)  # the check came just before the console took the lock
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


@pytest.mark.shapes_unchecked  # a stub's result under a real job kind
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
        return {"actions": 9, "read_id": "read:1"}

    job = js.start_refresh(work)
    time.sleep(0.05)
    t0 = time.monotonic()
    assert js.stop_refresh() and job.done.wait(2) and time.monotonic() - t0 < 2
    assert rec.of(jobs.JobFinished)[-1].problem == "stopped" and not js.status()["refresh_running"]
    assert not js.stop_refresh()  # already stopped
    again = js.start_refresh(lambda ctx: {"actions": 1, "read_id": "read:2"})
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


@pytest.mark.shapes_unchecked  # a stub's result under a real job kind
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


@pytest.mark.shapes_unchecked  # a stub's result under a real job kind
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


# --- the window's jobs in the registry (issue 39 phase 2, V2.1a) ---

from hub_helpers import make_api, make_root  # noqa: E402


@pytest.fixture
def hub(tmp_path):
    """A hub bound to a small library: its window jobs write to `<support>/jobs/`."""
    paths = make_root(tmp_path / "music")
    api, rec = make_api(paths)
    return api, paths, registry.Registry(paths.support)


def stand_in(monkeypatch, name, fn):
    """`fn` as the window's bridge method `name` (the call's name is what a job's record says it was started by)."""
    fn.__name__ = name
    monkeypatch.setattr(HubApi, name, bridge(fn))


class Gated:
    """A bridge method of the window that starts one job whose work waits for `release`."""

    def __init__(self, monkeypatch, name, start):
        self.release, self.running = threading.Event(), threading.Event()
        stand_in(monkeypatch, name, start(self))


def a_write(g):
    def hide(self, track_id: str, hidden: bool):
        def work(ctx):
            ctx.emit(ev.MovesProgress(1, 3, 4))
            g.running.set()
            g.release.wait(10)
            return {"track_id": track_id}
        return {"job_id": self._jobs.start("hide", work, track_id=track_id).id}
    return hide


def wait_ended(job, files):
    assert job.done.wait(10)
    for _ in range(500):  # the thread lets go of `alive` a moment after the end
        if not files.is_alive():
            return
        time.sleep(0.01)
    raise AssertionError("the job still holds its alive lock")


@pytest.mark.shapes_unchecked  # a stub's result under a real job kind
def test_a_window_write_job_is_in_the_registry(hub, monkeypatch):
    api, paths, reg = hub
    g = Gated(monkeypatch, "hide", a_write)
    answer = api.hide("t1", True)
    assert answer["ok"] and g.running.wait(10)
    job = api._jobs.current
    files = reg.get(answer["job_id"])
    state = files.state()
    assert files.is_alive() and state["id"] == job.id == answer["job_id"]  # alive while it runs
    assert (state["via"], state["kind"], state["status"], state["method"]) == ("window", "hide", "running", "hide")
    assert (state["command"], state["args"], state["library_lock"]) == ("track hide", {"track_id": "t1", "hidden": True}, True)
    assert state["pid"] == os.getpid() and state["roots"]["music"] == str(paths.root)
    assert state["roots"]["support"] == str(paths.support) and state["roots"]["sandbox"] is None
    assert job.id in api._jobs.own_ids
    g.release.set()
    wait_ended(job, files)
    state = files.state()
    assert (state["status"], state["progress"]["line"]) == ("done", "3 of 4") and state["ended"]
    result = files.result()
    assert (result["outcome"], result["command"], result["job"]) == ("ok", "track hide", job.id)
    assert result["data"] == {"track_id": "t1"}
    types = [json.loads(line)["type"] for line in (files.dir / "events.jsonl").read_text().splitlines()]
    assert types == ["JobStarted", "MovesProgress", "JobFinished"]


def test_a_refresh_and_a_sign_in_are_registered_too_without_the_library_lock(hub, monkeypatch):
    api, paths, reg = hub
    g = Gated(monkeypatch, "refresh", lambda g: lambda self, auto=False: {
        "job_id": self._jobs.start_refresh(lambda ctx: (g.running.set(), g.release.wait(10)) and None).id})
    answer = api.refresh()
    assert g.running.wait(10)
    files = reg.get(answer["job_id"])
    state = files.state()
    assert (state["via"], state["kind"], state["method"], state["command"], state["library_lock"], state["status"]) == (
        "window", "refresh", "refresh", "sync read", False, "running")
    assert files.is_alive()
    g.release.set()
    wait_ended(api._jobs.refresh, files)
    assert files.state()["status"] == "done" and files.result()["outcome"] == "ok"

    s = Gated(monkeypatch, "account_sign_in", lambda g: lambda self, service, browser=None: {
        "job_id": self._jobs.start_sign_in("account_sign_in", lambda ctx: (g.running.set(), g.release.wait(10)) and None).id})
    answer = api.account_sign_in("youtube", "chrome")
    assert s.running.wait(10)
    files = reg.get(answer["job_id"])
    assert (files.state()["kind"], files.state()["library_lock"], files.state()["args"]) == (
        "account_sign_in", False, {"service": "youtube", "browser": "chrome"})
    s.release.set()
    wait_ended(api._jobs.sign_in, files)


def test_a_window_job_keeps_the_password_out_of_its_files(hub, monkeypatch):
    api, paths, reg = hub
    monkeypatch.setattr(qobuz, "password_login", lambda *a: None)
    answer = api.setup_qobuz_login("dj@example.org", "s3cret-pw-1")
    assert answer["ok"]
    job = api._jobs.current
    files = reg.get(answer["job_id"])
    wait_ended(job, files)
    state = files.state()
    assert state["args"] == {"email": "dj@example.org"} and state["command"] == "login qobuz"
    assert state["library_lock"] is False  # a settings job holds no library lock
    for path in files.dir.iterdir():
        if path.is_file():
            assert "s3cret-pw-1" not in path.read_text(), path.name


def test_job_stop_reaches_a_window_job_between_items_and_inside_a_sleep(hub, monkeypatch):
    from discjockey.cli import follow
    api, paths, reg = hub
    for name, wait in (("items", lambda ctx: [(ctx.token.check(), time.sleep(0.01)) for _ in iter(int, 1)]),
                       ("sleep", lambda ctx: ctx.token.sleep(60))):
        g = Gated(monkeypatch, "hide", lambda g: lambda self, track_id, hidden: {
            "job_id": self._jobs.start("hide", lambda ctx: (g.running.set(), wait(ctx))[1]).id})
        answer = api.hide("t1", True)
        assert g.running.wait(10)
        job = api._jobs.current
        files = reg.get(answer["job_id"])
        refused = follow.stop("job stop", files, now=True)  # the window offers only "Stop safely"
        assert (refused["outcome"], refused["reason"]) == ("refused", "window_job") and not files.stop_requested()
        files.request_stop()
        began = time.monotonic()
        wait_ended(job, files)
        assert time.monotonic() - began < 2.5, name
        result = files.result()
        assert (result["outcome"], result["reason"]) == ("stopped", "stop") and files.state()["status"] == "done"


def test_a_failed_window_job_ends_failed_with_its_reason(hub, monkeypatch):
    api, paths, reg = hub

    def boom(ctx):
        raise RuntimeError("it broke")

    stand_in(monkeypatch, "hide", lambda self, track_id, hidden: {"job_id": self._jobs.start("hide", boom).id})
    answer = api.hide("t1", True)
    job = api._jobs.current
    files = reg.get(answer["job_id"])
    wait_ended(job, files)
    result = files.result()
    assert (result["outcome"], result["reason"]) == ("failed", "crashed") and result["message"]
    assert files.state()["status"] == "done"


def test_own_ids_hold_a_started_window_job_and_an_adopted_one(tmp_path):
    reg = registry.Registry(tmp_path / "support")
    own = reg.create("scan", "library scan", {}, "terminal", {})
    js = jobs.Jobs(None, lambda e: None, inline=own)
    assert js.own_ids == {own.id}
    own.release_claim()


@pytest.mark.shapes_unchecked  # a stub's result under a real job kind
def test_the_library_job_elsewhere_ignores_the_windows_own_job_and_names_a_foreign_one(hub, monkeypatch):
    api, paths, reg = hub
    g = Gated(monkeypatch, "hide", a_write)
    answer = api.hide("t1", True)
    assert g.running.wait(10)
    job = api._jobs.current
    assert api._library_job_elsewhere() is None  # it is this process's own, whatever its record says
    foreign = reg.create("scan", "library scan", {}, "terminal", {})  # another process's (the claim stays: it is alive)
    foreign.update(method="rescan_library", status="queued", library_lock=True)
    foreign.flush()
    assert api._library_job_elsewhere() is None  # still waiting for the lock: not a holder
    foreign.update(status="running")
    foreign.flush()
    assert api._library_job_elsewhere() == {"job": foreign.id, "via": "terminal", "command": "library scan"}
    foreign.update(status="done")
    foreign.flush()
    foreign.release_claim()
    g.release.set()
    wait_ended(job, reg.get(answer["job_id"]))


@pytest.mark.shapes_unchecked  # a stub's result under a real job kind
def test_a_window_job_carries_the_same_words_a_workers_does(hub, monkeypatch):
    api, paths, reg = hub
    done = {"track": "t2", "action": "same_track", "state": "done", "reason": None, "message": None, "path": None,
            "rekordbox": None}
    result = {"batch": 5, "total": 1, "done": 1, "skipped": 0, "failed": 0, "results": [done]}
    stand_in(monkeypatch, "upgrade", lambda self, track_ids, way="": {
        "job_id": self._jobs.start("upgrade_batch", lambda ctx: result, batch_kind="upgrade").id})
    answer = api.upgrade(["t2"], "same")
    job = api._jobs.current
    files = reg.get(answer["job_id"])
    wait_ended(job, files)
    words = api._result_words("upgrade", result)
    env = files.result()
    assert env["outcome"] == "ok" and env["command"] == "upgrade apply"
    assert env["next"] == words["next"] and env["person_steps"] == words.get("person_steps", [])
    assert env["data"]["batch_id"] == "aiff:5" and env["message"] == "1 of 1 song done."


# --- other processes' jobs, from the registry (issue 39 phase 2, V2.1b) ---

@pytest.fixture
def watched(env):
    """The `env` jobs with a registry; `foreign` makes a job of another process in it."""
    paths, _, rec, awake = env
    reg = registry.Registry(paths.support)
    js = Jobs(paths.lock, rec.emit, registry=reg)
    return paths, js, rec, reg


class Foreign:
    """A job of another process: made with `Registry.create` in the test and kept alive by its claim, not through the
    `Jobs` under test."""

    def __init__(self, paths, reg, kind="sync", method="sync_run", library_lock=True, music="own", line="3 of 10"):
        roots = {"music": str(paths.root) if music == "own" else music}
        self.files = reg.create(kind, "sync run", {}, "terminal", roots)
        self.files.update(method=method, library_lock=library_lock, status="running", progress={"line": line})
        self.files.flush()

    @property
    def id(self):
        return self.files.id

    def line(self, text):
        self.files.update(progress={"line": text})
        self.files.flush()

    def end(self, outcome="ok", reason=None, message=None, data=None):
        self.files.write_result(outcomes.envelope("sync run", outcome, reason=reason, message=message, data=data,
                                                  job=self.id))
        self.files.update(status="done", ended="now")
        self.files.release_claim()

    def let_go(self):
        self.files.release_claim()  # the process died: nobody holds `alive`, the state still says running


def test_a_foreign_job_that_holds_the_library_is_named_and_followed(watched):
    paths, js, rec, reg = watched
    js.watch_registry(interval=0.05)
    try:
        other = Foreign(paths, reg)
        assert wait_for(lambda: jobs.ConsoleBusy(True, other.id, "sync", "3 of 10", "Sync running in the Terminal · 3 of 10") in rec.events)
        assert js.console_running()
        other.line("4 of 10")
        assert wait_for(lambda: rec.events[-1] == jobs.ConsoleBusy(True, other.id, "sync", "4 of 10",
                                                                     "Sync running in the Terminal · 4 of 10"))
        other.end()
        assert wait_for(lambda: rec.events[-1] == jobs.ConsoleBusy(False, None, None, None, None))
        assert not js.console_running()
    finally:
        js.close()
    assert [e for e in rec.of(jobs.JobFinished)][0].job_id == other.id


def test_the_first_look_sends_nothing_when_nothing_runs(watched):
    paths, js, rec, reg = watched
    js._look()
    js._look()
    assert rec.events == []


@pytest.mark.parametrize("outcome, reason, message, ok, problem", [
    ("ok", None, "Done.", True, None),
    ("partial", None, None, True, None),
    ("failed", "offline", None, False, "offline"),
    ("failed", "failed", "It broke.", False, "failed"),
    ("stopped", "stop", None, False, "stopped"),
])
def test_a_foreign_end_is_the_windows_job_finished(watched, outcome, reason, message, ok, problem):
    paths, js, rec, reg = watched
    other = Foreign(paths, reg)
    js._look()
    other.end(outcome, reason, message, {"actions": 4})
    js._look()
    [finished] = rec.of(jobs.JobFinished)
    assert (finished.job_id, finished.kind, finished.ok, finished.problem) == (other.id, "sync", ok, problem)
    assert finished.result == {"actions": 4}
    assert finished.message == (message or (outcomes.REASONS[reason].text if reason else ""))
    js._look()
    assert len(rec.of(jobs.JobFinished)) == 1  # once


def test_a_lost_foreign_job_and_a_gone_one_finish_as_failed_with_the_worker_lost_words(watched):
    paths, js, rec, reg = watched
    lost, gone = Foreign(paths, reg), Foreign(paths, reg, library_lock=False)
    js._look()
    lost.let_go()
    shutil_rmtree(gone.files.dir)  # pruned between two looks
    js._look()
    words = outcomes.REASONS["worker_lost"].text
    finished = {e.job_id: e for e in rec.of(jobs.JobFinished)}
    assert set(finished) == {lost.id, gone.id}
    for event in finished.values():
        assert (event.ok, event.problem, event.message, event.result) == (False, "failed", words, None)


def test_a_foreign_read_job_finishes_without_a_console_banner(watched):
    paths, js, rec, reg = watched
    other = Foreign(paths, reg, kind="scan", method="scan", library_lock=False)
    js._look()
    assert rec.events == []  # holds no library: nothing to wait for
    other.end()
    js._look()
    assert [type(e) for e in rec.events] == [jobs.JobFinished] and rec.events[0].kind == "scan"


def test_a_foreign_refresh_ending_during_the_windows_own_refresh_says_nothing(watched):
    paths, js, rec, reg = watched
    other = Foreign(paths, reg, kind="refresh", method="refresh", library_lock=False)
    js._look()
    release = threading.Event()
    own = js.start_refresh(lambda ctx: release.wait(5) and None)
    other.end()
    js._look()
    assert rec.of(jobs.JobFinished) == []
    release.set()
    assert own.done.wait(5)


def test_the_windows_own_jobs_are_never_foreign(watched):
    paths, js, rec, reg = watched
    release = threading.Event()
    job = js.start("sync", lambda ctx: release.wait(5) and None)
    js._look()
    assert js.console_running() is False and rec.of(jobs.ConsoleBusy) == []
    release.set()
    assert job.done.wait(5)
    js._look()
    assert [e.job_id for e in rec.of(jobs.JobFinished)] == [job.id]  # its own, from `start`, and no second one


def test_a_bare_lock_without_a_registry_entry_is_still_a_console_run(watched):
    paths, js, rec, reg = watched
    js._look()
    with run_lock(paths.lock):
        assert js.console_running()
        js._look()
        assert rec.events[-1] == jobs.ConsoleBusy(True, None, None, None,
                                                  "A Discjockey command is running in the Terminal")
    js._look()
    assert rec.events[-1] == jobs.ConsoleBusy(False, None, None, None, None) and not js.console_running()


def test_a_write_refused_while_a_foreign_job_holds_the_library_says_who(watched):
    paths, js, rec, reg = watched
    other = Foreign(paths, reg)
    holder = {"job": other.id, "via": "terminal", "kind": "sync", "line": "3 of 10",
              "text": "Sync running in the Terminal · 3 of 10"}
    with pytest.raises(Busy) as excinfo:  # before the watch has looked
        js.start("hide", lambda ctx: pytest.fail("must not run"))
    assert (excinfo.value.kind, str(excinfo.value), excinfo.value.data) == ("console", jobs.CONSOLE_TEXT, {"holder": holder})
    js._look()
    with pytest.raises(Busy) as excinfo:
        js.start("hide", lambda ctx: pytest.fail("must not run"))
    assert excinfo.value.data == {"holder": holder}
    with run_lock(paths.lock):  # the lock itself held as well: a brief save is refused with the holder too
        with pytest.raises(Busy) as excinfo:
            with js.lock_briefly():
                pytest.fail("must not run")
    assert excinfo.value.kind == "console" and excinfo.value.data == {"holder": holder}
    other.end()
    assert not js.console_running()  # a holder that has just ended is not waited for, though the look is a second old
    js.start("hide", lambda ctx: None).done.wait(5)


@pytest.mark.shapes_unchecked  # a stub's result under a real job kind
def test_a_queued_job_of_another_process_is_not_the_library_holder(watched):
    paths, js, rec, reg = watched
    waiting = Foreign(paths, reg)
    waiting.files.update(status="queued")  # a terminal job still waiting for the lock (`--wait-busy`)
    waiting.files.flush()
    js._look()
    assert not js.console_running() and rec.of(jobs.ConsoleBusy) == []
    assert js.start("hide", lambda ctx: {"n": 1}).done.wait(5)  # not refused: nobody holds the lock
    waiting.let_go()


def test_the_holder_named_is_the_running_job_not_a_newer_queued_one(watched):
    paths, js, rec, reg = watched
    running = Foreign(paths, reg, line="2 of 9")
    waiting = Foreign(paths, reg)  # newer, so listed first
    waiting.files.update(status="queued")
    waiting.files.flush()
    js._look()
    with pytest.raises(Busy) as excinfo:
        js.start("hide", lambda ctx: pytest.fail("must not run"))
    assert excinfo.value.data["holder"]["job"] == running.id
    assert rec.of(jobs.ConsoleBusy) == [jobs.ConsoleBusy(True, running.id, "sync", "2 of 9",
                                                                      "Sync running in the Terminal · 2 of 9")]
    running.let_go()
    waiting.let_go()


def test_a_look_in_the_middle_of_the_windows_own_job_start_never_sees_it_as_foreign(watched, monkeypatch):
    paths, js, rec, reg = watched
    release = threading.Event()
    flush = registry.JobFiles.flush
    looked = []

    def flush_and_look(self):
        flush(self)
        if not looked:
            looked.append(1)
            js._look()  # the watch looking while `_new` has written the folder but not yet returned

    monkeypatch.setattr(registry.JobFiles, "flush", flush_and_look)
    job = js.start("hide", lambda ctx: release.wait(5) and None)
    assert looked
    js._look()
    assert rec.of(jobs.ConsoleBusy) == [] and rec.of(jobs.JobFinished) == []
    release.set()
    assert job.done.wait(5)
    js._look()
    assert [e.job_id for e in rec.of(jobs.JobFinished)] == [job.id]


@pytest.mark.shapes_unchecked  # a stub's result under a real job kind
def test_a_registry_that_fails_partway_leaves_no_record_and_no_lock(watched, monkeypatch):
    paths, js, rec, reg = watched

    def broken(self):
        raise OSError("disk full")

    monkeypatch.setattr(registry.JobFiles, "events", broken)
    job = js.start("hide", lambda ctx: {"n": 1})
    assert job.done.wait(5) and rec.of(jobs.JobFinished)[-1].ok  # it ran, unrecorded
    assert reg.list(all=True) == [] and js.own_ids == set()
    assert list(reg.root.glob("*")) == []  # the half-made folder (and its claim) went


@pytest.mark.shapes_unchecked  # a stub's result under a real job kind
def test_a_registry_that_cannot_be_pruned_does_not_stop_a_write(watched, monkeypatch):
    paths, js, rec, reg = watched

    def broken(self, now):
        raise FileNotFoundError("gone")

    monkeypatch.setattr(registry.Registry, "prune", broken)
    job = js.start("hide", lambda ctx: {"n": 1})
    assert job.done.wait(5) and rec.of(jobs.JobFinished)[-1].ok


def _a_job_that_waits(g, seen):
    """A hide whose work waits for `release` (looking at its token the while); `seen` is set once it has looked."""
    def hide(self, track_id: str, hidden: bool):
        def work(ctx):
            g.running.set()
            while not g.release.wait(0.02):
                if ctx.token.cancelled:
                    seen.set()
            return {"track_id": track_id}
        return {"job_id": self._jobs.start("hide", work, track_id=track_id).id}
    return hide


@pytest.mark.shapes_unchecked  # a stub's result under a real job kind
def test_a_stopped_window_job_shows_stopping_until_it_ends(hub, monkeypatch):
    api, paths, reg = hub
    seen = threading.Event()
    g = Gated(monkeypatch, "hide", lambda g: _a_job_that_waits(g, seen))
    answer = api.hide("t1", True)
    assert g.running.wait(10)
    job = api._jobs.current
    files = reg.get(answer["job_id"])
    assert files.state()["status"] == "running"
    assert api.stop()["ok"]
    assert wait_for(lambda: files.state()["status"] == "stopping")  # while the work still waits
    g.release.set()
    wait_ended(job, files)
    assert files.state()["status"] == "done"  # a late `stopping` never overwrites `done`


@pytest.mark.shapes_unchecked  # a stub's result under a real job kind
def test_a_stop_file_on_a_window_job_shows_stopping_once_the_work_looks(hub, monkeypatch):
    api, paths, reg = hub
    seen = threading.Event()
    g = Gated(monkeypatch, "hide", lambda g: _a_job_that_waits(g, seen))
    answer = api.hide("t1", True)
    assert g.running.wait(10)
    job = api._jobs.current
    files = reg.get(answer["job_id"])
    files.request_stop()
    assert seen.wait(5) and wait_for(lambda: files.state()["status"] == "stopping")
    g.release.set()
    wait_ended(job, files)
    assert files.state()["status"] == "done"


@pytest.mark.shapes_unchecked  # a stub's result under a real job kind
def test_a_stop_asked_after_the_job_is_done_leaves_done(hub, monkeypatch):
    api, paths, reg = hub
    g = Gated(monkeypatch, "hide", a_write)
    answer = api.hide("t1", True)
    assert g.running.wait(10)
    job = api._jobs.current
    files = reg.get(answer["job_id"])
    g.release.set()
    wait_ended(job, files)
    job.token.cancel()  # too late
    assert files.state()["status"] == "done"


def test_a_cancel_token_tells_its_callback_once_and_survives_it_failing(tmp_path):
    told = []
    token = ev.CancelToken(tmp_path / "stop", on_cancel=lambda: (told.append(1), 1 / 0))
    assert not token.cancelled and told == []
    token.cancel()
    token.cancel()
    assert token.cancelled and told == [1]
    seen = []
    by_file = ev.CancelToken(tmp_path / "stop", on_cancel=lambda: seen.append(1))
    (tmp_path / "stop").write_text("")
    assert by_file.cancelled and by_file.cancelled
    by_file.cancel()
    assert seen == [1]


def test_the_watch_reads_a_settled_foreign_job_only_once(watched, monkeypatch):
    paths, js, rec, reg = watched
    done = []
    for _ in range(30):
        other = Foreign(paths, reg)
        other.end()
        done.append(other.id)
    ending = Foreign(paths, reg)
    js._look()
    read = []
    state = registry.JobFiles.state

    def counting(self):
        read.append(self.id)
        return state(self)

    monkeypatch.setattr(registry.JobFiles, "state", counting)
    js._look()
    assert not set(done) & set(read) and ending.id in read  # the 30 ended ones are not read again
    read.clear()
    ending.end()
    js._look()
    assert [e.job_id for e in rec.of(jobs.JobFinished)] == [ending.id]  # a foreign job that ends is still reported once
    read.clear()
    js._look()
    assert ending.id not in read and [e.job_id for e in rec.of(jobs.JobFinished)] == [ending.id]


def test_close_ends_a_running_read_and_a_waiting_sign_in_as_stopped(watched):
    paths, js, rec, reg = watched
    read = js.start_refresh(lambda ctx: ctx.token.sleep(30))
    sign_in = js.start_sign_in("account_sign_in", lambda ctx: ctx.token.sleep(30))
    assert wait_for(lambda: reg.get(read.id).state()["status"] == "running"
                    and reg.get(sign_in.id).state()["status"] == "running")
    js.close()
    for job in (read, sign_in):
        assert job.done.is_set()
        assert wait_for(lambda: not reg.get(job.id).is_alive())
        assert reg.get(job.id).state()["status"] == "done"
        assert reg.get(job.id).result()["outcome"] == "stopped"


def test_close_ends_the_registry_watch(watched):
    paths, js, rec, reg = watched
    js.watch_registry(interval=0.05)
    thread = js._watch
    assert thread.is_alive()
    t0 = time.monotonic()
    js.close()
    assert not thread.is_alive() and time.monotonic() - t0 < 2


def shutil_rmtree(path):
    import shutil
    shutil.rmtree(path)
