"""E4a (issue 39 phase 2): `job_events`, the window's read of any job's events.jsonl (+ its rolling tail), and
`stop(job_id)`, the window's "Stop safely" for a job another process runs."""
import ast
import json
from pathlib import Path

import pytest
from hub_helpers import make_unbound_api

import discjockey
from discjockey import events as ev
from discjockey.hub import registry
from discjockey.hub.api import JOB_EVENTS_PAGE
from discjockey.hub.registry import Registry

ROOTS = {"music": None, "support": "/s", "rekordbox": None, "rekordbox_share": None, "sandbox": None}


@pytest.fixture
def api(tmp_path):
    return make_unbound_api(tmp_path / "support")[0]


def new_job(api, status="running"):
    """A job of the support folder as a Terminal sync leaves it: its `alive` claim is held by this test."""
    files = Registry(api._support.support).create("sync", "sync run", {}, "terminal", ROOTS)
    files.update(status=status)
    return files


def write(files, count, **limits):
    """`count` events through the registry's own writer (`Message` lines "m0", "m1", …), then closed."""
    writer = files.events(**limits)
    for i in range(count):
        writer.emit(ev.Message("info", f"m{i}"))
    writer.close()


def texts(answer):
    return [e["text"] for e in answer["events"]]


def test_events_come_from_the_position_on_and_next_is_the_next_position(api):
    files = new_job(api)
    write(files, 5)
    first = api.job_events(files.id)
    assert first["ok"] and texts(first) == [f"m{i}" for i in range(5)] and first["events"][0]["type"] == "Message"
    assert (first["next"], first["done"], first["status"]) == (5, False, "running")
    assert api.job_events(files.id, 5)["events"] == [] and api.job_events(files.id, 5)["next"] == 5


def test_a_stopping_job_says_so(api):
    files = new_job(api, "stopping")
    write(files, 1)
    assert api.job_events(files.id)["status"] == "stopping"


def test_later_events_follow_on_and_done_comes_with_the_last_of_an_ended_job(api):
    files = new_job(api)
    write(files, 5)
    assert api.job_events(files.id)["next"] == 5
    files2 = files.events()  # a second writer appends to the same files, as the one job's writer does
    files2.emit(ev.Message("info", "m5"))
    files2.emit(ev.Message("info", "m6"))
    files2.close()
    files.update(status="done")
    second = api.job_events(files.id, 5)
    assert texts(second) == ["m5", "m6"] and second["next"] == 7
    assert (second["done"], second["status"]) == (True, "done")
    assert api.job_events(files.id, 7)["done"] is True  # asked again after the end: nothing more, still done


def test_a_fresh_hub_skips_what_was_delivered(api):
    files = new_job(api)
    write(files, 7)
    other = make_unbound_api(api._support.support)[0]
    assert texts(other.job_events(files.id, 5)) == ["m5", "m6"] and other.job_events(files.id, 5)["next"] == 7
    assert texts(api.job_events(files.id, 5)) == ["m5", "m6"]  # a reload: an `after` the reader did not deliver to
    assert api.job_events(files.id, 99)["events"] == [] and api.job_events(files.id, 99)["next"] == 99


def test_a_long_job_comes_in_answers_of_500_and_done_only_on_the_last(api):
    files = new_job(api, "done")
    write(files, 700)
    first = api.job_events(files.id)
    assert len(first["events"]) == JOB_EVENTS_PAGE == 500 and first["next"] == 500 and first["done"] is False
    second = api.job_events(files.id, first["next"])
    assert texts(second) == [f"m{i}" for i in range(500, 700)] and second["next"] == 700 and second["done"] is True
    # exactly 500 left is a full answer: the end is only known with the next, empty one
    files = new_job(api, "done")
    write(files, 500)
    full = api.job_events(files.id)
    assert full["done"] is False and api.job_events(files.id, full["next"])["done"] is True


def test_past_the_head_the_tail_follows_in_order_and_the_marker_never_shows(api):
    files = new_job(api, "done")
    write(files, 30, head=5, tail=10)
    lines = (files.dir / "events.jsonl").read_text()
    assert '"Truncated"' in lines  # the file does hold the marker
    answer = api.job_events(files.id)
    assert texts(answer) == [f"m{i}" for i in (*range(5), *range(20, 30))]
    assert all(e["type"] == "Message" for e in answer["events"]) and answer["next"] == 15 and answer["done"] is True


def test_a_line_that_does_not_parse_is_skipped_but_has_its_place(api):
    files = new_job(api)
    write(files, 2)
    with open(files.dir / "events.jsonl", "a", encoding="utf-8") as f:
        f.write("{not json\n[1, 2]\n")
        f.write(json.dumps({"type": "Message", "level": "info", "text": "after"}) + "\n")
    answer = api.job_events(files.id)
    assert texts(answer) == ["m0", "m1", "after"] and answer["next"] == 5


def test_an_unknown_or_malformed_id_is_bad_args_not_crashed(api):
    for job_id in ("job:00000000", "job:zz", "nonsense"):
        for answer in (api.job_events(job_id), api.stop(job_id)):
            assert (answer["ok"], answer["kind"]) == (False, "bad_args"), answer
    assert api.job_events("job:00000000")["reason"] == "unknown_id" and api.stop("job:00000000")["reason"] == "unknown_id"


def test_the_hub_keeps_at_most_4_readers_the_least_recent_dropped(api):
    jobs = [new_job(api) for _ in range(5)]
    for files in jobs:
        write(files, 2)
        assert api.job_events(files.id)["next"] == 2
    assert list(api._event_readers) == [f.id for f in jobs[1:]]
    assert texts(api.job_events(jobs[0].id, 2)) == []  # its reader was dropped: a fresh one skips 2 lines and still agrees


def test_stop_of_a_running_foreign_job_writes_its_stop_file(api):
    files = new_job(api)
    assert not files.stop_requested()
    assert api.stop(files.id) == {"ok": True, "stopped": True} and files.stop_requested()
    stopping = new_job(api, "stopping")
    assert api.stop(stopping.id)["stopped"] is True
    queued = new_job(api, "queued")
    assert api.stop(queued.id)["stopped"] is True


def test_stop_of_an_ended_job_does_nothing(api):
    for status in ("done", "lost"):
        files = new_job(api, status)
        assert api.stop(files.id) == {"ok": True, "stopped": False} and not files.stop_requested()


def test_stop_without_an_id_is_the_windows_own_job_as_before(api):
    assert api.stop() == {"ok": True, "stopped": False}  # none runs
    files = new_job(api)
    assert api.stop() == {"ok": True, "stopped": False} and not files.stop_requested()  # a foreign job is not its own


def test_no_module_of_the_hub_imports_the_command_line():
    """The hub is the engine's side of the line: `cli` imports it, never the other way (V2.1a)."""
    hub = Path(discjockey.__file__).parent / "hub"
    for path in hub.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                names = [(node.module or "", a.name) for a in node.names]
                absolute = node.level == 0 and (node.module or "").split(".")[:2] == ["discjockey", "cli"]
                relative = node.level >= 2 and ((node.module or "").split(".")[0] == "cli"
                                                or (not node.module and any(n == "cli" for _, n in names)))
                assert not (absolute or relative), f"{path} imports the command line"
            elif isinstance(node, ast.Import):
                assert not any(a.name.split(".")[:2] == ["discjockey", "cli"] for a in node.names), path
