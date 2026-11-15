"""The job worker (issue 39 group 1.5; design §6.3): `job _worker <id>` runs a write job in its own process that
outlives the client, from `state.json` alone, with the signals, `--wait-busy`, `caffeinate`, the registry handoff
(no moment in which a created job is `lost`) and the first write end to end, `library scan`.

These tests start real worker processes. Every one has scratch support and rekordbox folders (`tmp_path`), and the
`env` fixture kills what it started and fails the test that leaves a `job _worker` or a `caffeinate` behind. Work that
must stay put (a scan of a fixture ends in milliseconds) runs through `SHIM`: the same spawn, claim and worker main,
with the method's work replaced by a controllable one (no production hook for it)."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import nullcontext
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from hub_helpers import choose_music, make_root

import discjockey.cli as cli
from discjockey import events as ev
from discjockey.cli import call, envelope, parser, worker
from discjockey.hub import catalog, jobs
from discjockey.hub.registry import Registry

SHIM = """
import json, os, pathlib, sys, time
from discjockey import tools
tools.activate()
from discjockey.hub import api as A
from discjockey.cli import worker
job_id, mode, marker = sys.argv[1:4]
gate = pathlib.Path(marker + ".gate")

def scan(self):
    def work(ctx):
        if mode == "roots":
            pathlib.Path(marker).write_text(json.dumps({
                "env_support": os.environ["DISCJOCKEY_SUPPORT"], "env_rekordbox": os.environ["DISCJOCKEY_REKORDBOX"],
                "paths_support": str(self._paths.support), "paths_root": str(self._paths.root)}))
            return {}
        pathlib.Path(marker).write_text("started")
        if mode == "crash":
            raise RuntimeError("the shim's work broke")
        if mode == "quick":
            return {"mode": mode}
        end = time.monotonic() + 60
        while time.monotonic() < end and not gate.exists():
            if mode != "blind":
                ctx.token.check()
            time.sleep(0.02)
        return {"mode": mode}
    return {"job_id": self._jobs.start("scan", work).id}

A.CliApi.rescan_library = A.bridge(scan)
sys.exit(worker.main([job_id]))
"""

CLIENT = """
import sys, time
from discjockey.cli import call, parser
from discjockey.hub import catalog
entry = catalog.by_method("rescan_library")[0]
env = call.start_job(entry, {}, "library scan", parser.Flags(), argv=lambda i: [sys.executable, "-c", sys.argv[1], i, "gate", sys.argv[2]])
print(env["job"], flush=True)
time.sleep(60)
"""


def wait_for(condition, timeout=20.0, step=0.02):
    """A bounded timed wait of the test's own for something another process does (never a wait without end)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = condition()
        if value:
            return value
        time.sleep(step)
    raise AssertionError("timed out waiting")


def ps_lines() -> list[str]:
    return subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=True).stdout.splitlines()


def leftovers(ids, pids) -> list[str]:
    """What of these jobs is still in `ps`: their worker processes and the `caffeinate` of their pids."""
    lines = ps_lines()
    workers = [ln for ln in lines if any(i in ln for i in ids) and ("job _worker" in ln or "worker.main" in ln)]
    awake = [ln for ln in lines if "caffeinate -i -w" in ln and any(f"-w {pid}" in ln for pid in pids)]
    return workers + awake


class Worker:
    """One spawned worker: its job folder, a reader of it, its process and its gate."""

    def __init__(self, files, process, marker):
        self.files, self.process, self.marker = files, process, marker
        self.reader = Registry(files.dir.parent.parent).get(files.id)

    @property
    def id(self):
        return self.files.id

    def state(self):
        return self.reader.state()

    def result(self):
        return self.reader.result()

    def started(self):
        return self.marker.exists()

    def open_gate(self):
        Path(str(self.marker) + ".gate").write_text("go")

    def ended(self):
        return self.result() is not None and not self.reader.is_alive()

    def signal(self, sig=signal.SIGINT):
        os.kill(self.state()["pid"], sig)


class Env:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.paths = make_root(tmp_path / "music")
        self.registry = Registry(self.paths.support)
        self.workers: list[Worker] = []
        self.seen: set[str] = set()
        self.pids: set[int] = set()

    def roots(self, **over):
        return {"music": str(self.paths.root), "support": str(self.paths.support),
                "rekordbox": str(self.tmp / "rekordbox-scratch"), "sandbox": None, **over}

    def start(self, mode="gate", *, wait_busy=None, roots=None, registry_in=None, via_shim=True):
        reg = Registry(registry_in) if registry_in else self.registry
        files = reg.create("rescan_library", "library scan", {}, "terminal", roots or self.roots())
        files.update(method="rescan_library", wait_busy=wait_busy)
        files.flush()
        marker = self.tmp / f"marker-{len(self.workers)}"
        argv = [sys.executable, "-c", SHIM, files.id, mode, str(marker)] if via_shim else None
        process = call.spawn_worker(files, argv)
        files.release_claim()
        w = Worker(files, process, marker)
        self.workers.append(w)
        self.seen.add(files.id)
        return w

    def remember_pids(self):
        for w in self.workers:
            pid = w.state().get("pid")
            if pid:
                self.pids.add(pid)

    def finish(self):
        """Kills what is left, then checks that no worker or caffeinate of this test outlived it."""
        self.remember_pids()
        for w in self.workers:
            if w.process.poll() is None:
                w.process.kill()
            w.process.wait(10)
        for child in call._children:
            if child.poll() is None:
                child.kill()
            child.wait(10)
        for jobdir in (self.registry.root.iterdir() if self.registry.root.is_dir() else ()):
            self.seen.add(jobdir.name)
            state = Registry(self.paths.support).get(jobdir.name).state() if (jobdir / "state.json").is_file() else {}
            if state.get("pid"):
                self.pids.add(state["pid"])

        try:
            wait_for(lambda: not leftovers(self.seen, self.pids), timeout=10)
        except AssertionError:
            raise AssertionError(f"left behind: {leftovers(self.seen, self.pids)}") from None


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)
    choose_music(tmp_path / "music", monkeypatch)
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(tmp_path / "rekordbox-scratch"))
    try:
        yield e
    finally:
        e.finish()


# --- argv ---

def test_the_worker_argv_of_a_checkout_and_of_the_built_app(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert call.worker_argv("job:0a1b2c3d") == [sys.executable, "-m", "discjockey", "job", "_worker", "job:0a1b2c3d"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)  # PyInstaller: the app's own program, no `-m`
    assert call.worker_argv("job:0a1b2c3d") == [sys.executable, "job", "_worker", "job:0a1b2c3d"]


def test_the_app_sends_the_hidden_worker_command_to_the_command_line(monkeypatch):
    """check first: app_main sends every argument it does not know to cli.main, which hands `job _worker` on."""
    from discjockey import app_main
    seen = []
    monkeypatch.setattr(worker, "main", lambda argv: seen.append(argv) or 0)
    monkeypatch.setattr(app_main.tools, "activate", lambda: None)
    assert app_main.main(["job", "_worker", "job:0a1b2c3d"]) == 0
    assert seen == [["job:0a1b2c3d"]]


def test_the_worker_command_is_hidden_from_help_and_the_parser(capsys):
    assert cli.main(["help", "--json"]) == 0
    assert "_worker" not in capsys.readouterr().out
    assert ("job", "_worker") not in parser.commands()


# --- T10: the worker ---

def test_a_worker_runs_holds_alive_and_ends_with_result_before_the_lock(env):
    w = env.start("gate")
    wait_for(w.started)
    state = w.state()
    assert state["status"] == "running" and w.reader.is_alive() and state["kind"] == "scan"
    assert state["pid"] == w.process.pid and state["pid_started"]
    assert os.getsid(w.process.pid) == w.process.pid  # a session of its own: nothing of the client's terminal reaches it
    assert not (w.files.dir / "result.json").exists()
    w.open_gate()
    wait_for(lambda: not w.reader.is_alive())
    state, result = w.state(), w.result()  # the lock is let go last: by now both are written
    assert state["status"] == "done" and state["ended"]
    assert (result["outcome"], result["job"], result["command"]) == ("ok", w.id, "library scan")
    assert result["data"] == {"mode": "gate"} and w.process.wait(10) == 0
    assert [json.loads(line)["type"] for line in (w.files.dir / "events.jsonl").read_text().splitlines()] == [
        "JobStarted", "JobFinished"]


def test_killing_the_client_leaves_the_worker_running_and_finishing(env, tmp_path):
    marker = tmp_path / "client-marker"
    client = subprocess.Popen([sys.executable, "-c", CLIENT, SHIM, str(marker)], stdout=subprocess.PIPE, text=True,
                              cwd=Path(call.tools.program_dir()))
    try:
        job_id = wait_for(lambda: client.stdout.readline().strip())
        reader = env.registry.get(job_id)
        env.seen.add(job_id)
        wait_for(marker.exists)
        client.kill()
        client.wait(10)
        assert reader.state()["status"] == "running" and reader.is_alive()  # the client's end changed nothing
        Path(str(marker) + ".gate").write_text("go")
        wait_for(lambda: reader.result() is not None and not reader.is_alive())
        assert reader.state()["status"] == "done" and reader.result()["outcome"] == "ok"
    finally:
        client.kill()
        client.wait(10)


def test_a_write_job_runs_under_its_own_caffeinate(env):
    w = env.start("gate")
    wait_for(w.started)
    pid = w.state()["pid"]
    wait_for(lambda: any(f"caffeinate -i -w {pid}" in ln for ln in ps_lines()))
    w.open_gate()
    wait_for(w.ended)
    wait_for(lambda: not any(f"caffeinate -i -w {pid}" in ln for ln in ps_lines()))  # ended with the worker


def test_the_workers_stderr_goes_to_log_txt(env):
    w = env.start("crash")
    wait_for(w.ended)
    assert "the shim's work broke" in (w.files.dir / "log.txt").read_text()  # the traceback of the crash
    result = w.result()
    assert (result["outcome"], result["reason"]) == ("failed", "crashed") and w.state()["status"] == "done"


def test_progress_fields_are_reduced_from_the_events(tmp_path):
    files = Registry(tmp_path / "support").create("scan", "library scan", {}, "terminal",
                                                  {"music": None, "support": "/s", "rekordbox": None, "sandbox": None})
    reducer = worker.Reducer(files)
    reducer(ev.RunStarted(total=4))
    reducer(ev.StepChanged("t1", "download"))
    reducer(ev.ActionFinished(None, None))
    reducer(ev.Message("info", "Half way."))
    reducer(ev.MovesProgress(1, 3, 4))
    assert files.state()["progress"] == {"step": "download", "done": 3, "total": 4, "item": None, "message": "Half way."}
    files.update(status="running")  # a status change writes at once, with the progress
    assert json.loads((files.dir / "state.json").read_text())["progress"]["done"] == 3


# --- the roots ---

def test_the_worker_works_from_the_roots_of_state_json_not_its_environment(env, tmp_path, monkeypatch):
    registry_home = tmp_path / "registry-home"  # where the spawner says the registry is (the one thing the environment says)
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(tmp_path / "somewhere-else"))
    w = env.start("roots", registry_in=registry_home,
                  roots=env.roots(support=str(env.paths.support), rekordbox=str(tmp_path / "rb-from-state")))
    wait_for(w.ended)
    seen = json.loads(w.marker.read_text())
    assert seen["env_support"] == str(env.paths.support) and seen["paths_support"] == str(env.paths.support)
    assert seen["env_rekordbox"] == str(tmp_path / "rb-from-state") and seen["paths_root"] == str(env.paths.root)
    assert w.files.dir.parent.parent == registry_home  # found through the registry the spawner named, nothing else


def test_a_job_without_a_rekordbox_folder_sees_no_rekordbox_library(env):
    w = env.start("roots", roots=env.roots(rekordbox=None))
    wait_for(w.ended)
    assert json.loads(w.marker.read_text())["env_rekordbox"] == ""  # set but empty: no library, never the real one


# --- busy and --wait-busy ---

def test_two_workers_for_writes_at_once_one_runs_one_is_busy(env):
    first = env.start("gate")
    wait_for(first.started)
    second = env.start("quick")
    wait_for(second.ended)
    result = second.result()
    assert (result["outcome"], result["reason"]) == ("busy", "library_lock") and envelope.exit_code(result) == 3
    assert result["data"]["holder"] == {"job": first.id, "via": "terminal", "kind": "scan"}
    assert second.process.wait(10) == 3 and first.state()["status"] == "running"
    first.open_gate()
    wait_for(first.ended)
    assert first.result()["outcome"] == "ok"


def test_a_busy_library_nobody_registered_answers_console_with_an_unknown_holder(env):
    from discjockey import library
    with library.run_lock(env.paths.lock):  # a terminal run of the old kind, in this very process
        w = env.start("quick")
        wait_for(w.ended)
    result = w.result()
    assert (result["outcome"], result["reason"], result["data"]) == ("busy", "console", {"holder": {"via": "unknown"}})


def test_wait_busy_asks_again_until_the_library_is_free(env):
    first = env.start("gate")
    wait_for(first.started)
    second = env.start("quick", wait_busy=15)
    time.sleep(0.6)  # a bounded look: the second is waiting, not ended
    assert second.state()["status"] == "queued" and second.reader.is_alive() and second.result() is None
    first.open_gate()
    wait_for(second.ended, timeout=30)
    assert second.result()["outcome"] == "ok" and second.state()["status"] == "done"


def test_wait_busy_gives_up_when_its_seconds_are_over(env):
    first = env.start("gate")
    wait_for(first.started)
    second = env.start("quick", wait_busy=1)
    wait_for(second.ended, timeout=30)
    assert second.result()["outcome"] == "busy"


# --- signals ---

def test_one_sigint_stops_safely(env):
    w = env.start("gate")
    wait_for(w.started)
    w.signal()
    wait_for(w.ended)
    result = w.result()
    assert (result["outcome"], result["reason"]) == ("stopped", "stop") and envelope.exit_code(result) == 5
    assert w.state()["status"] == "done" and w.process.wait(10) == 5


def test_two_sigints_a_second_apart_stop_at_once(env):
    w = env.start("blind")  # work that never looks at its token: only the second press ends it
    wait_for(w.started)
    w.signal()
    time.sleep(ev.CTRL_C_REPEAT_S + 0.1)
    assert w.result() is None  # the first press asked politely; the work did not listen
    wait_for(lambda: w.state()["status"] == "stopping")  # and the registry says so (the ticker writes it)
    w.signal()
    wait_for(w.ended)
    assert w.result()["reason"] == "stop_now" and w.result()["outcome"] == "stopped"


def test_two_sigints_a_moment_apart_are_one(env):
    w = env.start("blind")
    wait_for(w.started)
    w.signal()
    time.sleep(0.2)
    w.signal()  # inside CTRL_C_REPEAT_S: ignored, as a console run does
    time.sleep(0.6)
    assert w.result() is None and w.reader.is_alive()
    time.sleep(ev.CTRL_C_REPEAT_S)
    w.signal()
    wait_for(w.ended)
    assert w.result()["reason"] == "stop_now"


def test_the_stop_file_cancels_the_job(env):
    w = env.start("gate")
    wait_for(w.started)
    w.reader.request_stop()
    wait_for(w.ended)
    assert w.result()["reason"] == "stop"


# --- lost ---

def test_a_killed_worker_is_lost_on_the_next_read_and_the_next_write_goes_on(env, capsys):
    w = env.start("gate")
    wait_for(w.started)
    pid = w.state()["pid"]
    os.kill(pid, signal.SIGKILL)
    w.process.wait(10)
    assert w.state()["status"] == "lost" and w.result() is None
    assert json.loads((w.files.dir / "state.json").read_text())["status"] == "lost"
    wait_for(lambda: not any(f"caffeinate -i -w {pid}" in ln for ln in ps_lines()))  # caffeinate went with it
    follow = env.start(via_shim=False)  # a real scan: its `recover_pending` runs at the next write as today
    wait_for(follow.ended, timeout=60)
    assert follow.result()["outcome"] == "ok" and set(follow.result()["data"]) == {"moved", "new", "gone", "changed", "copies"}


# --- the handoff: never lost between create and the worker's first breath ---

def test_a_job_is_alive_from_its_creation_to_its_end_and_never_lost(env):
    seen = set()
    files = env.registry.create("rescan_library", "library scan", {}, "terminal", env.roots())
    reader = env.registry.get(files.id)
    assert reader.state()["status"] == "queued" and reader.is_alive()  # claimed before state.json existed
    files.update(method="rescan_library", wait_busy=None)
    files.flush()
    marker = env.tmp / "marker-handoff"
    process = call.spawn_worker(files, [sys.executable, "-c", SHIM, files.id, "quick", str(marker)])
    env.seen.add(files.id)
    files.release_claim()  # the worker holds the lock through the descriptor it was handed
    end = time.monotonic() + 30
    while time.monotonic() < end:
        state = reader.state()
        seen.add(state["status"])
        if state["status"] == "done":
            break
    assert "lost" not in seen and "done" in seen
    assert process.wait(10) == 0 and reader.result()["outcome"] == "ok"


def test_a_creator_that_dies_before_the_worker_starts_leaves_a_lost_job(env, tmp_path):
    code = ("import sys, time\\nfrom discjockey.hub.registry import Registry\\n"
            "f = Registry(sys.argv[1]).create('x', 'library scan', {}, 'terminal', {'music': None, 'support': '/s', "
            "'rekordbox': None, 'sandbox': None})\\nprint(f.id, flush=True)\\ntime.sleep(60)\\n")
    client = subprocess.Popen([sys.executable, "-c", code.replace("\\n", "\n"), str(env.paths.support)],
                              stdout=subprocess.PIPE, text=True, cwd=Path(call.tools.program_dir()))
    try:
        reader = env.registry.get(wait_for(lambda: client.stdout.readline().strip()))
        assert reader.state()["status"] == "queued"
        client.kill()
        client.wait(10)
        assert reader.state()["status"] == "lost"
    finally:
        client.kill()
        client.wait(10)


def test_the_alive_descriptor_is_not_inherited_by_the_workers_children(env):
    """The worker marks the handed descriptor non-inheritable: caffeinate never holds a dead job alive."""
    w = env.start("gate")
    wait_for(w.started)
    pid = w.state()["pid"]
    wait_for(lambda: any(f"caffeinate -i -w {pid}" in ln for ln in ps_lines()))
    caffeinate = next(ln.split()[0] for ln in ps_lines() if f"caffeinate -i -w {pid}" in ln)
    opened = subprocess.run(["lsof", "-p", caffeinate], capture_output=True, text=True).stdout
    assert f"{w.id}/alive" not in opened
    w.open_gate()
    wait_for(w.ended)


# --- Jobs(inline=…) ---

def test_inline_jobs_adopt_the_job_id_and_run_on_the_calling_thread(tmp_path):
    files = Registry(tmp_path / "support").create("rescan_library", "library scan", {}, "terminal",
                                                  {"music": None, "support": "/s", "rekordbox": None, "sandbox": None})
    got, seen = [], {}
    js = jobs.Jobs(None, got.append, inline=files, keep_awake=lambda reason: nullcontext())

    def work(ctx):
        seen["thread"] = threading.current_thread()
        seen["token"] = ctx.token
        return {"n": 1}

    with files.alive():
        job = js.start("scan", work)
        assert job.done.is_set() and job.id == files.id  # returned after JobFinished, under the adopted id
        assert files.state()["status"] == "running" and files.state()["kind"] == "scan"
    assert seen["thread"] is threading.main_thread() and seen["token"] is js.inline_token
    assert [type(e).__name__ for e in got] == ["JobStarted", "JobFinished"] and got[-1].result == {"n": 1}
    assert not js.inline_token.cancelled
    files.request_stop()
    wait_for(lambda: js.inline_token.cancelled, timeout=3)  # the stop file is the token's: seen within half a second


# --- retention at a job's start ---

def test_a_job_start_prunes_the_registry(env, monkeypatch):
    old = (datetime.now().astimezone() - timedelta(days=60)).isoformat(timespec="seconds")
    for _ in range(105):
        f = env.registry.create("sync", "sync run", {}, "terminal", env.roots())
        f.update(status="done", started=old)
        f.flush()
        f.release_claim()
    before = len(env.registry.list(all=True))
    assert before == 105
    entry = catalog.by_method("rescan_library")[0]
    answer = call.start_job(entry, {}, "library scan", parser.Flags(),
                            argv=lambda i: [sys.executable, "-c", SHIM, i, "quick", str(env.tmp / "marker-prune")])
    env.seen.add(answer["job"])
    assert len(env.registry.list(all=True)) == 101  # the newest 100 stayed, five older ones went, the new job came


# --- `library scan` end to end ---

def run_cli(argv, capsys):
    code = cli.main(argv)
    out = capsys.readouterr()
    return code, out.out


def test_library_scan_starts_a_worker_and_the_job_ends_ok(env, capsys):
    entry = catalog.by_method("rescan_library")[0]
    assert entry.kind == "J" and entry.locks == {"library"} and entry.example == "library scan" and not entry.planned
    code, out = run_cli(["library", "scan", "--json"], capsys)
    assert len(out.splitlines()) == 1
    first = json.loads(out)
    assert first["command"] == "library scan" and first["job"].startswith("job:")
    assert (first["outcome"], code) in (("ok", 0), ("running", 8))  # the client answers once the worker runs or ended
    reader = env.registry.get(first["job"])
    wait_for(lambda: reader.result() is not None and not reader.is_alive())
    result = reader.result()
    assert (result["outcome"], result["job"]) == ("ok", first["job"])
    assert set(result["data"]) == {"moved", "new", "gone", "changed", "copies"}
    state = reader.state()
    assert state["status"] == "done" and state["roots"]["music"] == str(env.paths.root) and state["via"] == "terminal"
    assert state["method"] == "rescan_library" and state["args"] == {} and state["kind"] == "scan"
    assert state["roots"]["support"] == str(env.paths.support) and state["roots"]["sandbox"] is None


def test_library_scan_without_a_music_folder_is_refused_by_the_worker(tmp_path, monkeypatch, capsys):
    support = tmp_path / "bare-support"
    support.mkdir()
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(support))
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(tmp_path / "rb"))
    code, out = run_cli(["library", "scan", "--json"], capsys)
    first = json.loads(out)
    try:
        reader = Registry(support).get(first["job"])
        wait_for(lambda: reader.result() is not None and not reader.is_alive())
        result = reader.result()
        assert (result["outcome"], result["reason"]) == ("refused", "no_library")
        assert code in (7, 8)
        pid = reader.state()["pid"]
    finally:
        for child in call._children:
            child.kill()
            child.wait(10)
    assert wait_for(lambda: not leftovers({first["job"]}, {pid}), timeout=10)


def test_a_flag_library_scan_does_not_take_is_bad_args_and_makes_no_job(env, capsys):
    code, out = run_cli(["library", "scan", "--dry-run", "--json"], capsys)
    assert code == 2 and json.loads(out)["outcome"] == "bad_args"  # no job was made for it
    assert env.registry.list(all=True) == []


def test_library_scan_prints_a_page_without_json(env, capsys):
    code, out = run_cli(["library", "scan"], capsys)
    assert code in (0, 8)  # the worker had ended (ok) or still ran (running) when the client answered
    jobs_made = env.registry.list(all=True)
    assert len(jobs_made) == 1
    env.seen.add(jobs_made[0]["id"])
    reader = env.registry.get(jobs_made[0]["id"])
    wait_for(lambda: reader.result() is not None and not reader.is_alive())


def test_a_worker_that_dies_at_once_is_a_lost_job_not_a_running_one(env):
    entry = catalog.by_method("rescan_library")[0]
    answer = call.start_job(entry, {}, "library scan", parser.Flags(),
                            argv=lambda i: [sys.executable, "-c", "import sys; sys.exit(3)"])
    env.seen.add(answer["job"])
    assert (answer["outcome"], answer["reason"]) == ("failed", "worker_lost") and envelope.exit_code(answer) == 1
    assert answer["data"]["log"].endswith("log.txt") and env.registry.get(answer["job"]).state()["status"] == "lost"
