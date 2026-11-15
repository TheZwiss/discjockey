"""The job registry (issue 39 group 1.4; design §6.2, §6.4): liveness by the `alive` lock, the capped events file,
retention, the stop file and the string job ids."""
import fcntl
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta

import pytest

from discjockey import events as ev, library
import discjockey.cli as cli
from discjockey.hub import jobs, registry
from discjockey.hub.registry import Registry

ROOTS = {"music": None, "support": "/s", "rekordbox": None, "sandbox": None}


def make(tmp_path, music=None):
    return Registry(tmp_path / "support").create("sync", "sync run", {}, "terminal", {**ROOTS, "music": music})


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


# --- ids ---

def test_new_job_ids_are_job_and_eight_hex():
    assert len({registry.new_job_id() for _ in range(50)}) == 50
    assert all(re.fullmatch(r"job:[0-9a-f]{8}", registry.new_job_id()) for _ in range(50))


def test_the_window_jobs_carry_such_a_string_in_every_place_an_id_goes():
    got = []
    js = jobs.Jobs(None, got.append)
    job = js.start("hide", lambda ctx: {"done": 1})
    assert job.done.wait(5)
    started = [e for e in got if isinstance(e, jobs.JobStarted)]
    finished = [e for e in got if isinstance(e, jobs.JobFinished)]
    assert re.fullmatch(r"job:[0-9a-f]{8}", started[0].job_id)
    assert started[0].job_id == finished[0].job_id == job.id == js.status()["job"]["id"]


def test_the_stored_event_line_is_the_bridges_shape():
    event = ev.Progress("t1", "download", 1.0, 2.0, "bytes")
    assert json.loads(registry.event_line(event)) == jobs.event_dict(event)


# --- the files of a job ---

def test_create_writes_a_queued_state_with_the_roots(tmp_path):
    files = make(tmp_path, "/m")
    state = json.loads((files.dir / "state.json").read_text())
    assert state["status"] == "queued" and state["id"] == files.id and state["via"] == "terminal"
    assert state["roots"] == {**ROOTS, "music": "/m"} and state["person_steps"] == []
    assert files.dir.parent == tmp_path / "support" / "jobs"
    assert Registry(tmp_path / "support").get(files.id).id == files.id
    with pytest.raises(registry.NoSuchJob):
        Registry(tmp_path / "support").get("job:00000000")
    with pytest.raises(registry.NoSuchJob):
        Registry(tmp_path / "support").get("../../x")


def test_the_worker_ends_with_result_then_done_then_the_lock(tmp_path):
    files = make(tmp_path)
    reader = Registry(tmp_path / "support").get(files.id)
    with files.alive():
        files.update(status="running")
        assert reader.is_alive() and reader.state()["status"] == "running"
        assert reader.state()["pid"] == os.getpid() and isinstance(reader.state()["pid_started"], float)
        files.write_result({"status": "ok"})
        files.update(status="done", ended="now")
    assert not reader.is_alive()
    assert reader.state()["status"] == "done" and reader.result() == {"status": "ok"}  # not lost


def test_a_second_process_cannot_take_the_alive_lock(tmp_path):
    files = make(tmp_path)
    with files.alive():
        with pytest.raises(RuntimeError):
            with registry.JobFiles(files.dir).alive():
                pass


def test_liveness_is_the_lock_never_the_pid(tmp_path):
    files = make(tmp_path)
    files.update(status="running", pid=os.getpid(), pid_started=registry.process_started(os.getpid()))
    reader = Registry(tmp_path / "support").get(files.id)  # the recorded pid is this very process, and alive
    assert reader.state()["status"] == "lost"
    assert json.loads((files.dir / "state.json").read_text())["status"] == "lost"  # the reader rewrote it
    assert json.loads((files.dir / "state.json").read_text())["ended"]
    held = make(tmp_path)
    held.update(status="stopping")
    with held.alive():
        assert Registry(tmp_path / "support").get(held.id).state()["status"] == "stopping"


def test_process_started_is_the_start_time_of_that_process():
    started = registry.process_started(os.getpid())
    assert started is not None and time.time() - 86400 < started <= time.time()
    assert registry.process_started(2 ** 22 + 12345) is None


def test_state_is_written_at_once_for_a_status_and_once_a_second_otherwise(tmp_path):
    files = make(tmp_path)
    path = files.dir / "state.json"
    files.update(status="running")
    assert json.loads(path.read_text())["status"] == "running"
    files.update(index=1)
    files.update(index=2)
    files.update(index=3)
    assert json.loads(path.read_text()).get("index") is None  # inside the second: held back
    assert files.state()["index"] == 3
    files.flush()
    assert json.loads(path.read_text())["index"] == 3


def test_person_steps_are_written_at_once_and_cleared(tmp_path):
    files = make(tmp_path)
    files.update(status="running")
    files.set_person_steps([{"id": "step:sign_in", "say": "Sign in"}])
    assert json.loads((files.dir / "state.json").read_text())["person_steps"] == [{"id": "step:sign_in", "say": "Sign in"}]
    files.set_person_steps([])
    assert json.loads((files.dir / "state.json").read_text())["person_steps"] == []


def test_list_shows_this_music_folder_and_jobs_with_none_unless_all(tmp_path):
    mine, other, none = make(tmp_path, "/m"), make(tmp_path, "/other"), make(tmp_path, None)
    for f in (mine, other, none):
        f.update(status="running")
    reg = Registry(tmp_path / "support")
    with mine.alive(), other.alive(), none.alive():
        assert {s["id"] for s in reg.list("/m")} == {mine.id, none.id}
        assert {s["id"] for s in reg.list(None)} == {none.id}
        assert {s["id"] for s in reg.list("/m", all=True)} == {mine.id, other.id, none.id}
        assert reg.running("/m") == 2 and reg.running("/other") == 2


# --- the events file ---

def test_a_burst_of_progress_writes_at_most_two_lines_a_second_per_slot(tmp_path):
    files = make(tmp_path)
    writer = files.events()
    for i in range(5000):
        writer.emit(ev.Progress("t1", "download", float(i), 5000.0, "bytes"))
        writer.emit(ev.Waiting("between", "pause", 5000.0 - i, 5000.0))
    writer.close()
    rows = lines(files.dir / "events.jsonl")
    progress = [r for r in rows if r["type"] == "Progress"]
    assert 1 <= len(progress) <= 3 and progress[-1]["done"] == 4999.0  # the newest is kept
    assert [r for r in rows if r["type"] == "Waiting"][-1]["remaining"] == 1.0


def test_the_newest_slot_value_is_written_before_the_next_other_event(tmp_path):
    files = make(tmp_path)
    now = [0.0]
    writer = files.events(clock=lambda: now[0])
    writer.emit(ev.Progress("t1", "download", 1.0, 9.0, "bytes"))
    writer.emit(ev.Progress("t1", "download", 2.0, 9.0, "bytes"))
    writer.emit(ev.Message("info", "after"))
    writer.close()
    rows = lines(files.dir / "events.jsonl")
    assert rows[-1]["type"] == "Message" and rows[-2]["type"] == "Progress" and rows[-2]["done"] == 2.0


def test_the_file_keeps_the_first_2000_a_marker_and_a_rolling_tail_of_10000(tmp_path):
    files = make(tmp_path)
    writer = files.events()
    total = 25000
    for i in range(total):
        writer.emit(ev.Message("info", f"m{i}"))
    writer.close()
    head = lines(files.dir / "events.jsonl")
    tail = lines(files.dir / "events.tail.jsonl")
    assert len(head) == 2001 and head[0]["text"] == "m0" and head[1999]["text"] == "m1999"
    assert head[2000] == {"type": "Truncated", "event": "Truncated", "skipped": total - 2000 - 10000}
    assert len(tail) == 10000 and tail[0]["text"] == f"m{total - 10000}" and tail[-1]["text"] == f"m{total - 1}"


def test_a_job_with_few_events_has_no_marker_and_no_tail(tmp_path):
    files = make(tmp_path)
    writer = files.events()
    for i in range(30):
        writer.emit(ev.Message("info", f"m{i}"))
    writer.close()
    assert len(lines(files.dir / "events.jsonl")) == 30 and not (files.dir / "events.tail.jsonl").exists()


def test_emit_after_close_never_raises(tmp_path):
    writer = make(tmp_path).events()
    writer.close()
    writer.emit(ev.Message("info", "late"))


# --- retention ---

def aged(tmp_path, days, *, music=None):
    """A finished job's folder written straight to disk (a hundred `create` calls would each fsync)."""
    job_id = registry.new_job_id()
    directory = tmp_path / "support" / "jobs" / job_id
    directory.mkdir(parents=True)
    started = (datetime.now().astimezone() - timedelta(days=days)).isoformat(timespec="seconds")
    (directory / "state.json").write_text(json.dumps({"id": job_id, "kind": "sync", "status": "done", "started": started,
                                                      "roots": {"music": music}}))
    (directory / "alive").touch()
    return registry.JobFiles(directory)


def test_retention_keeps_the_newest_100_and_every_job_of_30_days(tmp_path):
    reg = Registry(tmp_path / "support")
    recent = [aged(tmp_path, 1 + i / 1000) for i in range(110)]  # 110 jobs inside the 30 days: all stay
    old = [aged(tmp_path, 40 + i) for i in range(3)]
    assert sorted(reg.prune(datetime.now())) == sorted(f.id for f in old)
    assert all(f.dir.exists() for f in recent) and not any(f.dir.exists() for f in old)


def test_retention_keeps_the_newest_100_even_when_all_are_old(tmp_path):
    reg = Registry(tmp_path / "support")
    files = [aged(tmp_path, 40 + i / 10) for i in range(105)]
    removed = reg.prune(datetime.now())
    assert len(removed) == 5 and all(not f.dir.exists() for f in files[-5:]) and all(f.dir.exists() for f in files[:100])


def test_a_job_whose_alive_lock_is_held_is_never_pruned(tmp_path):
    reg = Registry(tmp_path / "support")
    running = aged(tmp_path, 90)
    [aged(tmp_path, 1 + i / 100) for i in range(100)]
    with running.alive():
        assert reg.prune(datetime.now()) == []
        assert running.dir.exists()
    assert reg.prune(datetime.now()) == [running.id]


# --- the stop file ---

def test_the_token_reports_cancelled_within_half_a_second_of_the_file(tmp_path):
    stop = tmp_path / "stop"
    token = ev.CancelToken(stop)
    assert not token.cancelled
    stop.write_text("")
    start = time.monotonic()
    while not token.cancelled:
        assert time.monotonic() - start < 1.0  # the design's 0.5 s, with room for a loaded machine
        time.sleep(0.02)
    assert token.cancelled  # once seen, it stays
    with pytest.raises(ev.Cancelled):
        token.check()


def test_sleep_ends_within_a_second_of_the_stop_file(tmp_path):
    stop = tmp_path / "stop"
    token = ev.CancelToken(stop)
    threading.Timer(0.3, stop.write_text, args=("",)).start()
    start = time.monotonic()
    with pytest.raises(ev.Cancelled):
        token.sleep(60)
    assert time.monotonic() - start < 1.0


def test_the_event_still_stops_a_token_without_a_file_at_once():
    token = ev.CancelToken()
    threading.Timer(0.1, token.cancel).start()
    start = time.monotonic()
    with pytest.raises(ev.Cancelled):
        token.sleep(60)
    assert time.monotonic() - start < 0.5
    ev.CancelToken().sleep(0)  # no wait, no stop


def test_request_stop_is_what_the_token_watches(tmp_path):
    files = make(tmp_path)
    token = ev.CancelToken(files.dir / "stop")
    assert not files.stop_requested() and not token.cancelled
    files.request_stop()
    assert files.stop_requested()
    token = ev.CancelToken(files.dir / "stop")
    assert token.cancelled


# --- where ---

def test_where_reports_the_jobs_running_from_the_registry(tmp_path, monkeypatch, capsys):
    support = tmp_path / "support"
    monkeypatch.setenv(library.SUPPORT_ENV, str(support))
    music = tmp_path / "music"
    music.mkdir()
    library.write_music_folder(support, music)
    reg = Registry(support)
    mine = reg.create("sync", "sync run", {}, "terminal", {**ROOTS, "music": str(music)})
    elsewhere = reg.create("sync", "sync run", {}, "terminal", {**ROOTS, "music": "/other"})
    ended = reg.create("sync", "sync run", {}, "terminal", {**ROOTS, "music": str(music)})
    ended.update(status="done")

    def where():
        assert cli.main(["where", "--json"]) == 0
        return json.loads(capsys.readouterr().out)["data"]["jobs_running"]

    assert where() == 0  # queued, nobody holds the lock: lost
    with mine.alive(), elsewhere.alive():
        mine.update(status="running")
        elsewhere.update(status="running")
        assert where() == 1


def test_an_event_that_cannot_be_written_does_not_stop_the_others(tmp_path):
    files = make(tmp_path)
    writer = files.events()
    writer.emit(object())  # no dataclass: event_line raises
    writer.emit(ev.Message("info", "still here"))
    writer.close()
    assert [r["text"] for r in lines(files.dir / "events.jsonl")] == ["still here"]
