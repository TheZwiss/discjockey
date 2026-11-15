"""Group V1.11, part a (issue 39, design §4.3, §5.2, §7): `upgrade apply` through the command line, end to end, on a fixture
library and a fixture rekordbox (`batch_helpers.make_lib`): Same track as one AIFF batch, New track one after the other,
`--all`, `--plan`, the outcomes (`partial`, nothing left, rekordbox open) and the bridge's mode enum.

A job's worker normally is another process. Here it runs in this one (`inline_workers`): the same `worker.main`, spawn
and registry, with the compare of two files answering "the same edit" (the real compare says "different" for fixtures)
and the process check of rekordbox the test's. The text page of a run is pinned by `tests/cli_golden/upgrade_apply.txt`.
Part b's commands (`upgrade discard`, `track undo`, `check done`) reuse `inline_workers`, `run_json` and `lib`."""
from __future__ import annotations

import json
import os
import signal
import types
from contextlib import contextmanager

import pytest

from batch_helpers import make_lib, needs_ffmpeg, use
from convert_helpers import EXACT
from discjockey import db
from discjockey.cli import bind, call, worker
import discjockey.cli as cli
from discjockey.hub import catalog, select
from discjockey.rekordbox import process

pytestmark = needs_ffmpeg

OK, FAILED, BAD_ARGS, NEEDS_PERSON, PARTIAL, REFUSED = 0, 1, 2, 4, 6, 7
SAME, NEW = ["--way", "same-track"], ["--way", "new-track"]


@pytest.fixture
def inline_workers(monkeypatch):
    """Every job a command starts runs in this process, through the real `worker.main`."""
    real = bind.headless

    def headless(resolved, **kw):
        api = real(resolved, **kw)
        api._svc.compare = lambda a, b: EXACT
        return api

    def spawn(files, argv=None):
        files.release_claim()  # the worker takes its own claim
        worker.main([files.id])
        return types.SimpleNamespace(wait=lambda timeout=None: 0, poll=lambda: 0)

    class NoCaffeinate:
        def __init__(self, wanted):
            pass

        def end(self):
            pass

    monkeypatch.setattr(bind, "headless", headless)
    monkeypatch.setattr(call, "spawn_worker", spawn)
    monkeypatch.setattr(worker, "Caffeinate", NoCaffeinate)
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", os.environ["DISCJOCKEY_SUPPORT"])  # the worker sets them: restored after
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", os.environ["DISCJOCKEY_REKORDBOX"])
    before = signal.getsignal(signal.SIGINT)
    yield
    signal.signal(signal.SIGINT, before)  # the worker ignores SIGINT when it ends


@pytest.fixture
def lib(tmp_path, monkeypatch, inline_workers):
    from discjockey.hub.api import CliApi
    monkeypatch.setattr(CliApi, "_resolve_track", lambda self, text: text)  # the fixture's keys are not real song keys

    def make(kinds):
        found = make_lib(tmp_path, monkeypatch, kinds)
        use(found, monkeypatch)
        monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(found.paths.support))
        return found
    return make


def run(argv, capsys):
    code = cli.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def run_json(argv, capsys) -> tuple[int, dict]:
    code, out, _ = run([*argv, "--json"], capsys)
    return code, json.loads(out)  # exactly one object on stdout


def batches_of(lib):
    with db.connect(lib.paths.db_file) as conn:
        return db.aiff_batches(conn)[0]


# --- apply ---

def test_same_track_on_three_tracks_is_one_aiff_batch_that_the_result_names(lib, capsys):
    found = lib(["mp3", "aiff", "mp3_free"])
    code, env = run_json(["upgrade", "apply", *found.tracks, *SAME], capsys)
    assert code == OK and env["outcome"] == "ok" and env["job"], env
    data = env["data"]
    assert (data["batch"], data["batch_id"], data["total"], data["done"]) == (1, "aiff:1", 3, 3)
    [row] = batches_of(found)
    assert (row.id, row.started_by, row.state) == (1, "user", "done")
    assert [n["run"] for n in env["next"]] == ["batch show aiff:1", "check list"]
    [step] = [s for s in env["person_steps"] if s["id"] == "step:reload_tag"]
    assert step["then"] == "check done --batch aiff:1" and all(t in step["say"] for t in found.tracks)
    assert [r["person_steps"][0]["id"] for r in data["results"]] == ["step:reload_tag"] * 3


def test_new_track_with_a_plan_runs_only_the_plans_items_and_says_where_to_relocate(lib, capsys):
    found = lib(["mp3", "aiff", "mp3_plain"])
    a, b, c = found.tracks
    code, plan = run_json(["upgrade", "apply", a, b, *NEW, "--dry-run"], capsys)
    assert code == OK and plan["data"]["mode"] == "new_track" and plan["data"]["planned"] == 2
    plan_id = plan["data"]["plan_id"]
    code, env = run_json(["upgrade", "apply", a, c, *NEW, "--plan", plan_id], capsys)  # b is gone, c is new
    data = env["data"]
    assert code == PARTIAL and env["outcome"] == "partial", env
    assert [(r["track"], r["action"], r["state"], r["reason"]) for r in data["results"]] == [
        (a, "add_new", "done", None), (b, "add_new", "skipped", "changed")]
    assert data["new_since_plan"] == [c] and (data["done"], data["skipped"], data["total"]) == (1, 1, 2)
    assert found.entry(2)["upgrade"] and not found.entry(0)["upgrade"]  # c stayed parked, a was added
    [step] = env["person_steps"]
    new_file = str(found.paths.root / data["results"][0]["path"])
    assert step["id"] == "step:relocate_new" and new_file in step["say"] and step["then"] == f"check done {a}"
    assert data["results"][0]["person_steps"] == [step]
    assert env["next"] == []  # a New track has no batch


def test_a_plan_nobody_made_is_bad_args_and_a_plan_of_nothing_standing_is_refused(lib, capsys):
    found = lib(["mp3", "aiff"])
    code, env = run_json(["upgrade", "apply", found.tracks[0], *NEW, "--plan", "plan:000000000000"], capsys)
    assert (code, env["outcome"], env["reason"]) == (BAD_ARGS, "bad_args", "unknown_id")
    plan_id = run_json(["upgrade", "apply", found.tracks[0], *NEW, "--dry-run"], capsys)[1]["data"]["plan_id"]
    code, env = run_json(["upgrade", "apply", found.tracks[1], *NEW, "--plan", plan_id], capsys)  # not its song
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "changed")
    assert found.entry(0)["upgrade"] and found.entry(1)["upgrade"]


def test_a_discard_has_no_plan(lib):
    found = lib(["mp3"])
    answer = bind.default().upgrade(found.tracks, "discard", "plan:000000000000")
    assert (answer["ok"], answer["kind"]) == (False, "refused")


def test_without_way_named_songs_are_bad_args_and_the_way_is_checked(lib, capsys):
    found = lib(["mp3"])
    code, env = run_json(["upgrade", "apply", found.tracks[0]], capsys)
    assert (code, env["outcome"], env["reason"]) == (BAD_ARGS, "bad_args", "usage") and "--way" in env["message"]
    code, env = run_json(["upgrade", "apply", found.tracks[0], "--way", "discard"], capsys)
    assert (code, env["reason"]) == (BAD_ARGS, "usage") and "same-track or new-track" in env["message"]
    assert batches_of(found) == []


def test_all_means_same_track_and_all_with_new_track_is_bad_args_with_the_windows_words(lib, capsys):
    found = lib(["mp3", "aiff"])
    for extra in (["--dry-run"], []):
        code, env = run_json(["upgrade", "apply", "--all", *NEW, *extra], capsys)
        assert (code, env["outcome"], env["reason"]) == (BAD_ARGS, "bad_args", "conflicting_flags")
        assert env["message"] == select.ALL_IS_SAME_TRACK
    code, env = run_json(["upgrade", "apply", "--all", *SAME], capsys)  # the same words as the bare --all
    assert code == OK and env["data"]["done"] == 2
    [row] = batches_of(found)
    assert row.started_by == "upgrade_all"  # the window's Upgrade all, not a list of ids


def test_all_with_nothing_left_is_ok_with_total_0_and_the_windows_words(lib, capsys):
    found = lib(["mp3", "aiff"])
    assert run_json(["upgrade", "apply", "--all"], capsys)[0] == OK
    code, env = run_json(["upgrade", "apply", "--all"], capsys)  # a second time: nothing left
    assert (code, env["outcome"], env["message"]) == (OK, "ok", "None of these can be upgraded right now.")
    assert (env["data"]["total"], env["data"]["results"], env["job"]) == (0, [], None)
    assert len(batches_of(found)) == 1


def test_a_batch_with_a_skip_is_partial_exit_6_never_ok_with_exit_1(lib, capsys):
    found = lib(["mp3", "mp3_plain", "aiff"])
    code, env = run_json(["upgrade", "apply", "--all"], capsys)
    assert code == PARTIAL == 6 and env["outcome"] == "partial" and env["reason"] is None
    assert (env["data"]["done"], env["data"]["skipped"], env["data"]["failed"]) == (2, 1, 0)
    assert env["message"] == "2 of 3 songs done, 1 skipped."
    assert found.entry(1)["upgrade"]  # the skipped one stays parked


def test_rekordbox_open_before_a_batch_of_one_track_needs_the_person_and_closes_the_batch(lib, capsys, monkeypatch):
    found = lib(["mp3"])
    monkeypatch.setattr(process, "running", lambda: True)
    code, env = run_json(["upgrade", "apply", found.tracks[0], *SAME], capsys)
    assert (code, env["outcome"], env["reason"]) == (NEEDS_PERSON, "needs_person", "rekordbox_open")
    [step] = env["person_steps"]
    assert (step["id"], step["then"]) == ("step:quit_rekordbox", "the same command")
    assert env["next"] == []  # nothing to resume: the batch is closed
    [row] = batches_of(found)
    assert row.state == "done" and found.entry(0)["upgrade"]
    monkeypatch.setattr(process, "running", lambda: False)  # the same command, once rekordbox is quit
    assert run_json(["upgrade", "apply", found.tracks[0], *SAME], capsys)[0] == OK


def test_rekordbox_open_midway_leaves_a_stopped_batch_and_the_step_says_to_resume_it(lib, capsys, monkeypatch):
    found = lib(["mp3", "mp3_plain"])
    monkeypatch.setattr(process, "running", lambda: True)
    code, env = run_json(["upgrade", "apply", *found.tracks, *SAME], capsys)
    assert (code, env["reason"]) == (NEEDS_PERSON, "rekordbox_open")
    assert [s["then"] for s in env["person_steps"]] == ["batch resume aiff:1"]
    [row] = batches_of(found)
    assert row.state == "stopped"
    code, env = run_json(["upgrade", "apply", "--all"], capsys)  # Upgrade all while a stopped batch waits: resume it
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "not_stopped")
    assert env["next"][0]["run"] == "batch resume aiff:1" and len(batches_of(found)) == 1


# --- the bridge's mode enum ---

def test_the_bridge_takes_same_track_new_track_and_discard_and_refuses_swap_and_add_new(lib):
    found = lib(["mp3"])
    api = bind.default()
    for old in ("swap", "add_new"):
        answer = api.upgrade(found.tracks, old)
        assert (answer["ok"], answer["kind"]) == (False, "refused") and "same_track, new_track, discard" in answer["message"]
    assert api.upgrade_preview(found.tracks, "swap")["kind"] == "bad_args"
    from discjockey.hub import api as hub_api
    assert hub_api.UPGRADE_MODES == ("same_track", "new_track", "discard")


def test_a_window_still_gets_the_old_results_and_none_of_the_command_lines_words(lib, capsys):
    found = lib(["mp3"])
    from hub_helpers import wait_job
    api = bind.default()
    assert not hasattr(type(api).upgrade, "resume_first") and api._resume_first
    from discjockey.hub.api import HubApi
    assert HubApi._resume_first is False  # only the command line refuses Upgrade all while a batch is stopped


# --- the text page ---

def test_golden_the_page_of_a_new_track_apply(lib, capsys, tmp_path):
    from pathlib import Path
    found = lib(["mp3", "aiff"])
    code, out, err = run(["upgrade", "apply", *found.tracks, *NEW], capsys)
    text = out.replace(str(tmp_path), "<tmp>")
    path = Path(__file__).parent / "cli_golden" / "upgrade_apply.txt"
    if os.environ.get("UPDATE_GOLDEN"):
        path.write_text(text)
    assert code == OK and text == path.read_text()
    assert "Your turn: " in err and "relocate" in err and "Then: check done t1aaaaaaa" in err
