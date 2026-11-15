"""The job client (issue 39 group 1.6; design §6.4 and §6.5): the default waits, `--detach`, `--wait`, the first stderr
line, `job follow` (text and `--jsonl`), `job wait`, `job stop [--now]`, `job list` / `job show`, Ctrl-C in an attached
client, and the RJ path of `call.run`.

Most tests read and write hand-made job folders (`make_job`: the registry's own calls, the `alive` lock held by this
process while the job "runs"), because the client only ever sees files. The tests that need a worker spawn the real one
through the worker tests' shims (scratch support and rekordbox folders, `env` kills what it started and fails a test that
leaves a `job _worker` or a `caffeinate` behind). The 90 s default wait is shortened through `DISCJOCKEY_DEFAULT_WAIT_S`,
which the worker never reads."""
import json
import os
import re
import signal
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from hub_helpers import choose_music
from test_cli_worker import SHIM, Env, wait_for

import discjockey.cli as cli
from discjockey import events as ev
from discjockey.cli import call, envelope, follow, housekeeping, parser
from discjockey.hub import catalog, registry
from discjockey.hub.registry import Registry
from discjockey.models import Action, SourceTrack

RJ_SHIM = SHIM.replace("A.CliApi.rescan_library = A.bridge(scan)", """
def plan(self, scope):
    pathlib.Path(marker).write_text("started")
    end = time.monotonic() + 60
    while time.monotonic() < end and not gate.exists():
        time.sleep(0.02)
    return {"plan": {"items": []}}

A.CliApi.aiff_plan = A.bridge(plan)""")


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)
    choose_music(tmp_path / "music", monkeypatch)
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(tmp_path / "rekordbox-scratch"))
    monkeypatch.setattr(follow, "stdout_is_terminal", lambda: False)  # pytest's stdout: an agent's pipe
    try:
        yield e
    finally:
        e.finish()


class Jobs:
    """Hand-made job folders in the scratch support folder."""

    def __init__(self, env):
        self.env, self.held = env, []

    def make(self, status="running", *, method="rescan_library", via="terminal", started=None, result=None,
             events=(), steps=(), progress=None, log=None):
        files = self.env.registry.create("scan", "library scan", {}, via, self.env.roots())
        files.update(method=method, status=status if status in registry.ACTIVE else "running", person_steps=list(steps),
                     **({"started": started} if started else {}), **({"progress": progress} if progress else {}))
        if events:
            writer = files.events()
            for event in events:
                writer.emit(event)
            writer.close()
        if log:
            (files.dir / "log.txt").write_text(log)
        files.flush()
        self.env.seen.add(files.id)
        if status in registry.ACTIVE:
            self.held.append(files)  # the claim stays: the job is alive while the test holds it
        else:
            self.end(files, result or envelope.envelope("library scan", "ok", job=files.id), status)
        return files

    def end(self, files, result, status="done"):
        files.write_result(result)
        files.update(status=status, ended="2026-11-15T10:00:00+01:00")
        files.flush()
        files.release_claim()

    def release(self):
        for files in self.held:
            files.release_claim()


@pytest.fixture
def jobs(env):
    j = Jobs(env)
    try:
        yield j
    finally:
        j.release()


def reader_of(env, files):
    return Registry(env.paths.support).get(files.id)


def after(delay, fn):
    timer = threading.Timer(delay, fn)
    timer.daemon = True
    timer.start()
    return timer


def rescan():
    return catalog.by_method("rescan_library")[0]


def shim_argv(env, mode, name):
    marker = env.tmp / name
    return marker, lambda i: [sys.executable, "-c", SHIM, i, mode, str(marker)]


def open_gate(marker):
    Path(str(marker) + ".gate").write_text("go")


def run_json(argv, capsys):
    code = cli.main([*argv, "--json"])
    out, err = capsys.readouterr()
    assert len(out.splitlines()) == 1, out
    return code, json.loads(out), err


# --- the default waits ---

def test_no_flag_and_stdout_a_terminal_follows_to_the_end(env, monkeypatch):
    monkeypatch.setattr(follow, "stdout_is_terminal", lambda: True)
    monkeypatch.setenv(follow.WAIT_ENV, "0.2")  # a terminal ignores the 90 s default
    marker, argv = shim_argv(env, "gate", "tty")
    after(1.0, lambda: open_gate(marker))
    started = time.monotonic()
    answer = call.start_job(rescan(), {}, "library scan", parser.Flags(), argv=argv)
    env.seen.add(answer["job"])
    assert answer["outcome"] == "ok" and time.monotonic() - started >= 0.9


def test_no_flag_and_stdout_not_a_terminal_waits_the_default_then_says_running(env, monkeypatch):
    monkeypatch.setenv(follow.WAIT_ENV, "1")  # the short stand-in of the 90 s
    assert follow.DEFAULT_WAIT_S == 90.0
    marker, argv = shim_argv(env, "gate", "agent")
    started = time.monotonic()
    answer = call.start_job(rescan(), {}, "library scan", parser.Flags(), argv=argv)
    env.seen.add(answer["job"])
    assert 0.9 <= time.monotonic() - started < 8
    assert (answer["outcome"], answer["reason"], envelope.exit_code(answer)) == ("running", "still_running", 8)
    assert answer["job"] == answer["data"]["job"] and answer["data"]["status"] == "running"
    open_gate(marker)
    wait_for(lambda: reader_of(env, env.registry.get(answer["job"])).result() is not None)


def test_wait_1_on_a_long_job_is_running_with_the_progress_and_the_live_person_steps(env, jobs):
    steps = [{"step": "sign_in", "say": "Sign in to Qobuz in the window."}]
    files = jobs.make(progress={"step": "download", "done": 2, "total": 9, "item": "A - B", "message": None}, steps=steps)
    answer = follow.drive(reader_of(env, files), "sync run", parser.Flags(wait=1), wait=1, events=None, own=True)
    assert (answer["outcome"], answer["reason"]) == ("running", "still_running") and envelope.exit_code(answer) == 8
    assert answer["job"] == files.id
    assert answer["data"]["progress"] == {"step": "download", "done": 2, "total": 9, "item": "A - B", "message": None}
    assert answer["data"]["person_steps"] == steps and answer["person_steps"] == steps
    assert answer["next"][0]["run"].endswith(f"job wait {files.id} --wait 1")


def test_wait_1_with_a_real_worker_answers_running_and_the_job_goes_on(env):
    marker, argv = shim_argv(env, "gate", "wait1")
    answer = call.start_job(rescan(), {}, "library scan", parser.Flags(wait=1), argv=argv)
    env.seen.add(answer["job"])
    assert (answer["outcome"], envelope.exit_code(answer)) == ("running", 8) and answer["job"]
    reader = env.registry.get(answer["job"])
    assert reader.state()["status"] == "running" and reader.is_alive()
    open_gate(marker)
    wait_for(lambda: reader.result() is not None and not reader.is_alive())
    assert reader.result()["outcome"] == "ok"


# --- --detach ---

def test_detach_returns_once_the_worker_runs_with_exit_0(env):
    marker, argv = shim_argv(env, "gate", "detach")
    answer = call.start_job(rescan(), {}, "library scan", parser.Flags(detach=True), argv=argv)
    env.seen.add(answer["job"])
    assert (answer["outcome"], envelope.exit_code(answer)) == ("ok", 0)
    assert answer["job"] and answer["data"] == {"job": answer["job"], "status": "running"}
    open_gate(marker)
    wait_for(lambda: env.registry.get(answer["job"]).result() is not None)


def test_detach_returns_a_busy_envelope_within_wait_busy_plus_5_seconds(env):
    first = env.start("gate")
    wait_for(first.started)
    marker, argv = shim_argv(env, "quick", "busy")
    started = time.monotonic()
    answer = call.start_job(rescan(), {}, "library scan", parser.Flags(detach=True, wait_busy=1), argv=argv)
    env.seen.add(answer["job"])
    assert time.monotonic() - started <= 1 + 5
    assert (answer["outcome"], answer["reason"], envelope.exit_code(answer)) == ("busy", "library_lock", 3)
    first.open_gate()
    wait_for(first.ended)


# --- the first stderr line ---

def test_the_first_stderr_line_names_the_job_before_anything_else(env, capsys):
    marker, argv = shim_argv(env, "gate", "first")
    answer = call.start_job(rescan(), {}, "library scan", parser.Flags(detach=True), argv=argv)
    env.seen.add(answer["job"])
    err = capsys.readouterr().err.splitlines()
    path = housekeeping.command_path()
    assert err[0] == f"Job {answer['job']} started (follow: {path} job follow {answer['job']})"
    assert re.fullmatch(r"Job job:[0-9a-f]{8} started \(follow: .+ job follow job:[0-9a-f]{8}\)", err[0])
    open_gate(marker)
    wait_for(lambda: env.registry.get(answer["job"]).result() is not None)


# --- job follow ---

TRACK = SourceTrack("1", "Title", ("Artist",), "", None, 1000, None)
ACTION = Action("acquire", "t1", "Hard Bounce", TRACK, (0, 0))
EVENTS = [ev.ActionStarted(1, 2, ACTION), ev.StepChanged("t1", "download"), ev.Message("info", "Halfway there."),
          ev.Message("info", "All done.")]


def test_revive_makes_the_engines_events_from_their_lines():
    for event in EVENTS:
        assert follow.revive(json.loads(registry.event_line(event))) == event
    assert follow.revive({"type": "JobStarted"}) is None and follow.revive({"type": "Truncated"}) is None


def test_job_follow_text_is_the_consoles_progress_lines(env, jobs, capsys):
    files = jobs.make("done", events=EVENTS)
    code = cli.main(["job", "follow", files.id])
    out = capsys.readouterr().out
    assert code == 0
    assert "[1/2] Downloading [Hard Bounce] Artist - Title" in out and "Halfway there." in out and "All done." in out


def test_job_follow_jsonl_is_one_event_per_line_then_the_envelope(env, jobs, capsys):
    files = jobs.make("done", events=EVENTS)
    code = cli.main(["job", "follow", files.id, "--jsonl"])
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert code == 0
    assert lines[0]["event"] == "Job" and lines[0]["state"] == "started" and lines[0]["job"] == files.id
    assert [x["type"] for x in lines[1:5]] == ["ActionStarted", "StepChanged", "Message", "Message"]
    assert lines[5]["event"] == "Job" and lines[5]["state"] == "ended" and lines[5]["outcome"] == "ok"
    assert lines[-1]["v"] == 1 and lines[-1]["outcome"] == "ok" and len(lines) == 7


def test_job_follow_from_end_starts_at_the_tail(env, jobs, capsys):
    files = jobs.make("done", events=EVENTS)
    code = cli.main(["job", "follow", files.id, "--from-end"])
    out = capsys.readouterr().out
    assert code == 0 and "Halfway there." not in out and "All done." not in out


def test_a_follower_reads_the_head_then_the_rolling_tail_through_a_compaction(tmp_path):
    """The follower keeps up event by event (it waits for each one), so the compaction never outruns it; a burst larger
    than the tail would lose events by design (the next two tests force the interleavings that must not)."""
    folder = tmp_path / "job"
    folder.mkdir()
    writer = registry.EventsWriter(folder, head=3, tail=5)
    reader = follow.EventReader(folder)
    seen = []

    def emit_and_read(first, last):
        for n in range(first, last):
            writer.emit(ev.Message("info", f"m{n}"))
            wait_for(lambda: seen.extend(json.loads(line)["text"] for line in reader.read()) or len(seen) > n)

    emit_and_read(0, 6)  # 3 in the head, 3 in the tail
    emit_and_read(6, 16)  # the tail reaches 10 lines, 2 x 5: compacted to the last 5, twice over
    emit_and_read(16, 20)
    writer.close()
    seen.extend(json.loads(line)["text"] for line in reader.read())
    assert seen == [f"m{n}" for n in range(20)]


def _line(n: int) -> str:
    return json.dumps({"type": "Message", "level": "info", "text": f"m{n}"}) + "\n"


def test_the_head_is_read_after_the_tail_so_a_line_flushed_in_between_keeps_its_place(tmp_path, monkeypatch):
    """The writer flushes the head, then the tail. A reader that took the head first and the tail second could get the
    head's empty state and the tail's lines after the writer's flush: m3..m5 before m0..m2. Forced here: the writer's
    flush happens right before the reader's second file is opened."""
    folder = tmp_path / "job"
    folder.mkdir()
    (folder / "events.jsonl").write_text("")
    reader = follow.EventReader(folder)
    opened = []
    real_open = open

    def flush_before_the_second_file(path, *args, **kwargs):
        opened.append(path)
        if len(opened) == 2:  # the writer's flush: the head, then the tail
            (folder / "events.jsonl").write_text("".join(_line(n) for n in range(3)))
            (folder / "events.tail.jsonl").write_text("".join(_line(n) for n in range(3, 6)))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(follow, "open", flush_before_the_second_file, raising=False)
    first = [json.loads(line)["text"] for line in reader.read()]
    monkeypatch.undo()
    second = [json.loads(line)["text"] for line in reader.read()]
    assert first + second == [f"m{n}" for n in range(6)]


def test_the_writer_flushes_the_head_before_the_tail_file_exists(tmp_path):
    """What the reader's order relies on: a buffered head line is on disk when the first tail line is written."""
    folder = tmp_path / "job"
    folder.mkdir()
    writer = registry.EventsWriter(folder, head=2, tail=5)
    try:
        writer._write(_line(0).rstrip("\n"))
        writer._write(_line(1).rstrip("\n"))
        assert (folder / "events.jsonl").read_text() == ""  # buffered, not flushed
        writer._write(_line(2).rstrip("\n"))  # the first line of the tail
        assert (folder / "events.jsonl").read_text() == _line(0) + _line(1)
    finally:
        writer.close()


def test_a_compacted_tail_that_is_longer_than_before_is_not_read_from_the_old_offset(tmp_path):
    """The tail replaced by a compaction can be as long as, or longer than, the one the reader stopped in (and a file
    system may give it the old inode): the reader goes on only where the last line it saw still ends."""
    folder = tmp_path / "job"
    folder.mkdir()
    tail = folder / "events.tail.jsonl"
    tail.write_text("".join(_line(n) for n in range(3, 6)))
    reader = follow.EventReader(folder)
    assert [json.loads(line)["text"] for line in reader.read()] == ["m3", "m4", "m5"]
    with open(tail, "r+") as f:  # the same file, rewritten in place: m5 is in it, not where the reader stopped
        f.write("".join(_line(n) for n in range(5, 12)))
    assert [json.loads(line)["text"] for line in reader.read()] == [f"m{n}" for n in range(6, 12)]


def test_follow_ends_on_the_result_never_on_the_first_job_finished(env, jobs, capsys):
    """V1.5: a job that loses the library race under --wait-busy writes JobFinished(console) before it asks again."""
    finished = {"type": "JobFinished", "job_id": "x", "ok": False, "problem": "console"}
    files = jobs.make("running")
    with open(files.dir / "events.jsonl", "a") as f:
        f.write(json.dumps(finished) + "\n")
    code, env_, _ = run_json(["job", "wait", files.id, "--wait", "0.4"], capsys)
    assert (code, env_["outcome"], env_["job"]) == (8, "running", files.id)
    jobs.end(files, envelope.envelope("library scan", "ok", job=files.id))
    code, env_, _ = run_json(["job", "wait", files.id, "--wait", "5"], capsys)
    assert (code, env_["outcome"]) == (0, "ok")


# --- job wait ---

def test_job_wait_on_an_ended_job_prints_its_own_envelope_and_exit_code(env, jobs, capsys):
    result = envelope.envelope("sync run", "partial", message="Most of it.", data={"n": 3}, job="job:00000000")
    files = jobs.make("done", result=result)
    code, printed, _ = run_json(["job", "wait", files.id], capsys)
    assert code == 6 and printed == result


def test_job_wait_on_a_lost_job_is_worker_lost_and_points_at_job_show(env, jobs, capsys):
    files = jobs.make("running")
    files.release_claim()  # nobody holds the lock any more: the job is lost
    jobs.held.remove(files)
    code, printed, _ = run_json(["job", "wait", files.id], capsys)
    assert (code, printed["outcome"], printed["reason"]) == (1, "failed", "worker_lost")
    assert printed["next"][0]["run"].endswith(f"job show {files.id} --log") and printed["job"] == files.id
    assert reader_of(env, files).state()["status"] == "lost"


def test_an_unknown_job_is_bad_args(env, capsys):
    code, printed, _ = run_json(["job", "wait", "job:deadbeef"], capsys)
    assert (code, printed["outcome"], printed["reason"]) == (2, "bad_args", "unknown_id")


# --- job list and job show ---

def test_job_list_is_running_first_then_newest(env, jobs, capsys):
    old = jobs.make("done", started="2026-11-01T10:00:00+01:00")
    running = jobs.make("running", started="2026-11-02T10:00:00+01:00")
    new = jobs.make("done", started="2026-11-03T10:00:00+01:00")
    code, printed, _ = run_json(["job", "list"], capsys)
    assert code == 0 and [j["id"] for j in printed["data"]["jobs"]] == [running.id, new.id, old.id]
    assert printed["data"]["jobs"][0]["status"] == "running" and printed["data"]["jobs"][0]["roots"]["music"]
    code = cli.main(["job", "list"])
    assert code == 0 and running.id in capsys.readouterr().out


def test_job_show_has_the_state_the_last_events_the_result_and_with_log_the_log(env, jobs, capsys):
    files = jobs.make("done", events=EVENTS, log="a warning of the worker\n")
    code, printed, _ = run_json(["job", "show", files.id], capsys)
    data = printed["data"]
    assert code == 0 and data["state"]["id"] == files.id and data["result"]["outcome"] == "ok"
    assert [e["type"] for e in data["events"]] == ["ActionStarted", "StepChanged", "Message", "Message"]
    assert "log" not in data
    _, printed, _ = run_json(["job", "show", files.id, "--log"], capsys)
    assert printed["data"]["log"] == "a warning of the worker\n"


# --- job stop ---

def test_job_stop_writes_the_stop_file_and_the_worker_ends_stopped(env, capsys):
    w = env.start("gate")
    wait_for(w.started)
    code, printed, _ = run_json(["job", "stop", w.id], capsys)
    assert code == 0 and printed["outcome"] == "ok" and printed["data"]["status"] == "stopping"
    assert (w.files.dir / "stop").exists()
    wait_for(w.ended)
    assert w.result()["outcome"] == "stopped" and envelope.exit_code(w.result()) == 5
    code, printed, _ = run_json(["job", "wait", w.id], capsys)  # whoever waits on it gets exit 5
    assert code == 5 and printed["outcome"] == "stopped"


def test_stopping_an_ended_job_is_refused_not_running(env, jobs, capsys):
    files = jobs.make("done")
    code, printed, _ = run_json(["job", "stop", files.id], capsys)
    assert (code, printed["outcome"], printed["reason"]) == (7, "refused", "not_running")
    assert not (files.dir / "stop").exists()


def test_current_is_the_one_running_write_job_of_this_music_folder(env, jobs, capsys):
    jobs.make("done", started="2026-11-04T10:00:00+01:00")
    read_job = jobs.make("running", method="aiff_plan", started="2026-11-05T10:00:00+01:00")
    write_job = jobs.make("running", started="2026-11-01T10:00:00+01:00")
    code, printed, _ = run_json(["job", "stop", "current"], capsys)
    assert code == 0 and printed["job"] == write_job.id
    assert (write_job.dir / "stop").exists() and not (read_job.dir / "stop").exists()


def test_current_with_nothing_running_is_refused_not_running(env, jobs, capsys):
    jobs.make("done")
    code, printed, _ = run_json(["job", "stop", "current"], capsys)
    assert (code, printed["reason"]) == (7, "not_running")


# --- job stop --now ---

def record_kills(monkeypatch):
    kills = []
    monkeypatch.setattr(follow.os, "kill", lambda pid, sig: kills.append((time.monotonic(), pid, sig)))
    return kills


def test_now_sends_sigint_twice_at_least_a_second_apart_while_alive_and_the_start_time_holds(env, jobs, monkeypatch, capsys):
    files = jobs.make("running")
    files.update(pid=os.getpid(), pid_started=registry.process_started(os.getpid()))
    files.flush()
    kills = record_kills(monkeypatch)
    code, printed, _ = run_json(["job", "stop", files.id, "--now"], capsys)
    assert code == 0 and printed["data"] == {"job": files.id, "status": "stopping", "now": True}
    assert [(pid, sig) for _, pid, sig in kills] == [(os.getpid(), signal.SIGINT)] * 2
    assert kills[1][0] - kills[0][0] >= 1.0 and (files.dir / "stop").exists()


def test_now_sends_no_signal_when_the_pids_start_time_is_not_the_workers(env, jobs, monkeypatch, capsys):
    files = jobs.make("running")
    files.update(pid=os.getpid(), pid_started=123.0)  # whatever has this pid now is not the process that ran the job
    files.flush()
    kills = record_kills(monkeypatch)
    code, printed, _ = run_json(["job", "stop", files.id, "--now"], capsys)
    assert (code, printed["outcome"], printed["reason"]) == (1, "failed", "worker_lost") and kills == []


def test_now_sends_no_signal_to_a_lost_job(env, jobs, monkeypatch, capsys):
    files = jobs.make("running")
    files.update(pid=os.getpid(), pid_started=registry.process_started(os.getpid()))
    files.flush()
    files.release_claim()  # nobody holds `alive`: lost
    jobs.held.remove(files)
    kills = record_kills(monkeypatch)
    code, printed, _ = run_json(["job", "stop", files.id, "--now"], capsys)
    assert (code, printed["reason"]) == (7, "not_running") and kills == []


def test_now_on_a_window_job_is_refused_window_job(env, jobs, monkeypatch, capsys):
    files = jobs.make("running", via="window")
    kills = record_kills(monkeypatch)
    code, printed, _ = run_json(["job", "stop", files.id, "--now"], capsys)
    assert (code, printed["outcome"], printed["reason"]) == (7, "refused", "window_job")
    assert kills == [] and not (files.dir / "stop").exists()
    code, printed, _ = run_json(["job", "stop", files.id], capsys)  # the safe stop is the window's own too
    assert code == 0 and (files.dir / "stop").exists()


def test_now_stops_a_worker_that_ignores_the_safe_stop(env, capsys):
    w = env.start("blind")  # its work never looks at its token: only the second SIGINT reaches it
    wait_for(w.started)
    code, printed, _ = run_json(["job", "stop", w.id, "--now"], capsys)
    assert code == 0 and printed["data"]["now"] is True
    wait_for(w.ended)
    assert (w.result()["outcome"], w.result()["reason"]) == ("stopped", "stop_now")


# --- Ctrl-C in an attached client ---

def press_ctrl_c():
    os.kill(os.getpid(), signal.SIGINT)


def test_the_first_ctrl_c_writes_the_stop_file_and_a_second_a_second_later_asks_for_now(env, jobs, monkeypatch, capsys):
    files = jobs.make("running")
    asked = []
    monkeypatch.setattr(follow, "send_stop_now", lambda f: asked.append(f.id) or True)
    after(0.3, press_ctrl_c)
    after(0.6, press_ctrl_c)  # one press that arrived twice: ignored
    after(1.6, press_ctrl_c)
    after(2.2, lambda: jobs.end(files, envelope.envelope("library scan", "stopped", reason="stop", job=files.id), "done"))
    answer = follow.drive(reader_of(env, files), "library scan", parser.Flags(), wait=None, events=None, own=True)
    assert answer["outcome"] == "stopped" and (files.dir / "stop").exists()
    assert asked == [files.id]
    err = capsys.readouterr().err
    assert "Stopping safely" in err and "Stopping at once" in err


def test_ctrl_c_in_job_wait_leaves_the_job_running(env, jobs):
    files = jobs.make("running")
    after(0.3, press_ctrl_c)
    answer = follow.drive(reader_of(env, files), "job wait", parser.Flags(), wait=None, events=None, own=False)
    assert answer["outcome"] == "running" and not (files.dir / "stop").exists()


# --- the RJ path ---

def test_a_read_job_runs_as_a_job_without_the_library_lock(env):
    entry = replace(catalog.by_method("aiff_plan")[0], planned=None)
    assert entry.kind == "RJ"
    writer = env.start("gate")  # a write job holds the library
    wait_for(writer.started)
    marker = env.tmp / "rj-marker"
    started = []

    def go():
        started.append(call.start_job(entry, {"scope": {"kind": "cdj"}}, "aiff convert", parser.Flags(),
                                      argv=lambda i: [sys.executable, "-c", RJ_SHIM, i, "gate", str(marker)]))

    thread = threading.Thread(target=go)
    thread.start()
    wait_for(marker.exists)
    jobs_now = env.registry.list(all=True)
    rj = next(j for j in jobs_now if j.get("method") == "aiff_plan")
    env.seen.add(rj["id"])
    assert rj["status"] == "running" and rj["via"] == "terminal"
    open_gate(marker)
    thread.join(20)
    answer = started[0]
    assert (answer["outcome"], answer["job"]) == ("ok", rj["id"]) and answer["data"] == {"plan": {"items": []}}
    assert writer.state()["status"] == "running"  # the write job was never disturbed, and the read was not busy
    writer.open_gate()
    wait_for(writer.ended)


def test_call_run_hands_a_read_job_entry_to_the_job_client(monkeypatch):
    entry = replace(catalog.by_method("aiff_plan")[0], planned=None)
    seen = []
    monkeypatch.setattr(call, "start_job", lambda e, kw, command, flags: seen.append((e.method, kw, command)) or {"outcome": "ok"})
    call.run(entry, {"scope": {"kind": "cdj"}}, parser.Flags(), api=object(), exact=True)
    assert seen == [("aiff_plan", {"scope": {"kind": "cdj"}}, "aiff convert")]


# --- the words ---

def test_the_job_words_are_in_help_and_the_parser_but_not_the_worker(capsys):
    code, printed, _ = run_json(["help"], capsys)
    found = {c["command"] for c in printed["data"]["commands"]}
    assert code == 0 and {f"job {w}" for w in ("list", "show", "follow", "wait", "stop")} <= found
    assert parser.parse(["job", "stop", "current", "--now"]).args == {"job": "current", "now": True}
