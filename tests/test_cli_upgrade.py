"""Group V1.11, part a (issue 39, design §4.3, §5.2, §7): `upgrade apply` through the command line, end to end, on a fixture
library and a fixture rekordbox (`batch_helpers.make_lib`): Same track as one AIFF batch, New track one after the other,
`--all`, `--plan`, the outcomes (`partial`, nothing left, rekordbox open) and the bridge's mode enum.

A job's worker normally is another process. Here it runs in this one (`inline_workers`): the same `worker.main`, spawn
and registry, with the compare of two files answering "the same edit" (the real compare says "different" for fixtures)
and the process check of rekordbox the test's. The text page of a run is pinned by `tests/cli_golden/upgrade_apply.txt`.
Part b's commands (`upgrade discard`, `track undo`, `check done`) reuse `inline_workers`, `run_json` and `lib`; their
text pages are pinned by `tests/cli_golden/{upgrade_discard,track_undo,check_done}.txt`."""
from __future__ import annotations

import re
import copy
import json
import os
import signal
import types
from contextlib import contextmanager

import pytest
from hub_helpers import cmd

from batch_helpers import make_lib, needs_ffmpeg, use
from convert_helpers import EXACT
from discjockey import batches, db, library, upgrades
from discjockey.cli import bind, call, worker
import discjockey.cli as cli
from discjockey.hub import api as api_words, catalog, ids, select
from discjockey.rekordbox import backup as rbbackup, process
from discjockey.rekordbox import session as rbsession

pytestmark = needs_ffmpeg

OK, FAILED, BAD_ARGS, NEEDS_PERSON, PARTIAL, REFUSED = 0, 1, 2, 4, 6, 7
SAME, NEW = ["--way", "same-track"], ["--way", "new-track"]


STOP: dict = {"after": None, "seen": 0, "at_start": False}  # `at_start`: Stop is pressed before the first track


@pytest.fixture
def inline_workers(monkeypatch):
    """Every job a command starts runs in this process, through the real `worker.main`."""
    real = bind.headless
    STOP.update(after=None, seen=0, at_start=False)

    def headless(resolved, **kw):
        api = real(resolved, **kw)

        def compare(a, b):  # a Stop pressed while the song `STOP["after"]` is being measured
            STOP["seen"] += 1
            if STOP["seen"] == STOP["after"]:
                api._jobs.inline_token.cancel()
            return EXACT
        api._svc.compare = compare
        if STOP["at_start"] and kw.get("job") is not None:  # the worker's api, not the client's
            api._jobs.inline_token.cancel()
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
    monkeypatch.setattr(ids, "SPOTIFY_ID", re.compile(r"[A-Za-z0-9]{2,22}"))  # the fixture's keys (t1, t2…) pass as song keys; the real resolver runs

    def make(kinds):
        found = make_lib(tmp_path, monkeypatch, kinds)
        use(found, monkeypatch)
        monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(found.paths.support))
        return found
    return make


@pytest.fixture
def stale_keys(monkeypatch):
    """A test of the engine's per-song answer for a key the records lack (a song gone between the line and the run):
    the real resolver would refuse the line first (`unknown_id`), so the key reaches the engine as typed."""
    from discjockey.hub.api import CliApi
    monkeypatch.setattr(CliApi, "_resolve_track", lambda self, text, state=None: text)


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
    assert [n["run"] for n in env["next"]] == [cmd("batch show aiff:1"), cmd("check list")]
    # every track's rekordbox text was written (or rekordbox has no such track): nothing to reload, just a look
    assert [r["person_steps"][0]["id"] for r in data["results"]] == ["step:look"] * 3
    [step] = env["person_steps"]
    assert step["id"] == "step:look" and step["then"] == cmd("check done --batch aiff:1")
    assert step["say"].startswith("In rekordbox, have a look at ") and all(t in step["say"] for t in found.tracks)
    assert found.row(0)["FolderPath"].endswith("Song 0.aiff")  # rekordbox's row points at the new file
    assert data["backup"]  # rekordbox's library was backed up before the batch wrote to it
    assert data["results"][2]["rekordbox"] is None  # rekordbox does not hold the third
    for r in data["results"][:2]:
        assert set(r["rekordbox"]) == {"entries", "kept"} and isinstance(r["rekordbox"]["entries"], list), r


def test_new_track_with_a_plan_runs_only_the_plans_items_and_says_where_to_relocate(lib, capsys):
    found = lib(["mp3", "aiff", "mp3_plain"])
    a, b, c = found.tracks
    code, plan = run_json(["upgrade", "apply", a, b, *NEW, "--dry-run"], capsys)
    assert code == OK and plan["data"]["mode"] == "new_track" and plan["data"]["planned"] == 2
    plan_id = plan["data"]["plan_id"]
    assert run_json(["upgrade", "discard", b, "--yes"], capsys)[0] == OK  # b changed since the plan; c is new
    code, env = run_json(["upgrade", "apply", a, b, c, *NEW, "--plan", plan_id], capsys)
    data = env["data"]
    assert code == PARTIAL and env["outcome"] == "partial", env
    assert [(r["track"], r["action"], r["state"], r["reason"]) for r in data["results"]] == [
        (a, "add_new", "done", None), (b, "add_new", "skipped", "changed")]
    assert data["new_since_plan"] == [c] and (data["done"], data["skipped"], data["total"]) == (1, 1, 2)
    assert found.entry(2)["upgrade"] and not found.entry(0)["upgrade"]  # c stayed parked, a was added
    [step] = env["person_steps"]
    new_file = str(found.paths.root / data["results"][0]["path"])
    assert step["id"] == "step:relocate_new" and new_file in step["say"] and step["then"] == cmd(f"check done {a}")
    assert data["results"][0]["person_steps"] == [{**step, "then": f"check done {a}"}]  # the envelope's `then` is a full command line
    assert env["next"] == []  # a New track has no batch
    assert batches_of(found) == [] and rbbackup.backups(found.paths) == []  # no batch record, rekordbox never opened


def test_a_dry_run_still_answers_while_the_library_and_rekordbox_writer_locks_are_held(lib, capsys):
    found = lib(["mp3", "aiff"])
    before = untouched(found)
    with library.run_lock(found.paths.lock), rbsession.writer_lock(found.paths.support):  # busy would be exit 3
        code, env = run_json(["upgrade", "apply", "--all", "--dry-run"], capsys)
    assert (code, env["outcome"], env["data"]["planned"]) == (OK, "ok", 2)
    assert untouched(found) == before and rbbackup.backups(found.paths) == []


def test_a_plan_run_asks_only_about_the_songs_it_names(lib, capsys):
    found = lib(["mp3", "aiff", "mp3_free"])
    a, b, c = found.tracks
    code, plan = run_json(["upgrade", "apply", a, b, c, *SAME, "--dry-run"], capsys)
    code, env = run_json(["upgrade", "apply", a, b, *SAME, "--plan", plan["data"]["plan_id"]], capsys)  # c was not named
    assert (code, env["outcome"]) == (OK, "ok"), env
    assert [(r["track"], r["state"]) for r in env["data"]["results"]] == [(a, "done"), (b, "done")]
    assert env["data"]["total"] == 2 and env["data"]["skipped"] == 0
    assert found.entry(2)["upgrade"]  # c stayed parked


def test_all_with_a_plan_runs_what_the_plan_had_and_every_missing_song_is_changed(lib, capsys):
    found = lib(["mp3", "aiff"])
    code, plan = run_json(["upgrade", "apply", "--all", "--dry-run"], capsys)
    assert code == OK and plan["data"]["planned"] == 2
    code, env = run_json(["upgrade", "apply", "--all", "--plan", plan["data"]["plan_id"]], capsys)
    assert (code, env["outcome"], env["data"]["done"], env["data"]["total"]) == (OK, "ok", 2, 2)


def test_a_same_track_plan_with_a_changed_song_runs_the_rest_and_says_changed(lib, capsys):
    found = lib(["mp3", "aiff", "mp3_free"])
    a, b, c = found.tracks
    code, plan = run_json(["upgrade", "apply", a, b, c, *SAME, "--dry-run"], capsys)
    assert run_json(["upgrade", "discard", b, "--yes"], capsys)[0] == OK  # b changed since the plan
    code, env = run_json(["upgrade", "apply", a, b, c, *SAME, "--plan", plan["data"]["plan_id"]], capsys)
    assert (code, env["outcome"]) == (PARTIAL, "partial"), env
    assert [(r["track"], r["state"], r["reason"]) for r in env["data"]["results"]] == [
        (a, "done", None), (c, "done", None), (b, "skipped", "changed")]
    assert env["data"]["batch_id"] == "aiff:1"


def test_the_two_ways_of_the_same_songs_are_two_plans(lib, capsys):
    found = lib(["mp3", "aiff"])
    same = run_json(["upgrade", "apply", *found.tracks, *SAME, "--dry-run"], capsys)[1]["data"]["plan_id"]
    new = run_json(["upgrade", "apply", *found.tracks, *NEW, "--dry-run"], capsys)[1]["data"]["plan_id"]
    assert same != new
    code, env = run_json(["upgrade", "apply", *found.tracks, *SAME, "--plan", same], capsys)  # not overwritten by the other
    assert (code, env["outcome"]) == (OK, "ok"), env


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
    assert (step["id"], step["then"]) == ("step:quit_rekordbox", None)
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
    assert [s["then"] for s in env["person_steps"]] == [cmd("batch resume aiff:1")]
    [row] = batches_of(found)
    assert row.state == "stopped"
    code, env = run_json(["upgrade", "apply", "--all"], capsys)  # Upgrade all while a stopped batch waits: resume it
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "not_stopped")
    assert env["next"][0]["run"] == cmd("batch resume aiff:1") and len(batches_of(found)) == 1


def test_new_track_with_every_name_taken_fails_that_song_and_still_does_the_next(lib, capsys):
    """Engine behaviour of the retired console (`upgrades_cmd`): a song whose new file has no free name is a failed item with
    its words (no traceback), nothing of it changes, and the next song is still done."""
    found = lib(["mp3", "mp3"])
    for stem in ("Artist - Song 0", f"Artist - Song 0 [{found.tracks[0][:6]}]", f"Artist - Song 0 [{found.tracks[0]}]"):
        (found.paths.root / f"Library/A/{stem}.aiff").write_bytes(b"user file")
    code, env = run_json(["upgrade", "apply", *found.tracks, *NEW], capsys)
    assert (code, env["outcome"]) == (PARTIAL, "partial"), env
    first, second = env["data"]["results"]
    assert (first["state"], second["state"]) == ("failed", "done") and first["message"] == "Could not add Artist - Song 0."
    assert found.entry(0)["path"] == found.olds[0] and found.entry(0)["upgrade"]  # nothing changed for the first
    assert (found.paths.root / "Library/A/Artist - Song 0.aiff").read_bytes() == b"user file"


def test_a_same_track_swap_that_breaks_midway_fails_the_item_and_leaves_the_song_as_it_was(lib, capsys, monkeypatch):
    found = lib(["aiff"])  # an AIFF: Same track swaps the audio under the file (`upgrades.build_staged`)

    def broken(parked, staged, n):
        raise OSError("Input/output error")

    monkeypatch.setattr(upgrades, "build_staged", broken)
    before = found.music(), found.dump()
    code, env = run_json(["upgrade", "apply", found.tracks[0], *SAME], capsys)
    assert (code, env["outcome"]) == (FAILED, "failed"), env
    [row] = env["data"]["results"]
    assert row["state"] == "failed" and "Input/output error" in row["message"]
    assert (found.music(), found.dump()) == before and found.entry(0)["upgrade"]
    assert library.load_state(found.paths)["pending"] == []


def test_an_unknown_song_is_skipped_and_a_batch_of_skips_is_refused(lib, stale_keys, capsys):
    found = lib(["mp3", "stale"])
    code, env = run_json(["upgrade", "apply", "nope", found.tracks[0], *SAME], capsys)
    assert (code, env["outcome"]) == (PARTIAL, "partial")
    assert [(r["state"], r["reason"]) for r in env["data"]["results"]] == [("skipped", "no_upgrade"), ("done", None)]
    code, env = run_json(["upgrade", "apply", found.tracks[1], *SAME], capsys)  # only a song that needs a choice
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "refused")
    assert env["data"]["results"][0]["reason"] == "needs_choice" and found.entry(1)["upgrade"]


def test_the_library_lock_held_is_busy_exit_3_and_nothing_starts(lib, capsys):
    found = lib(["mp3"])
    for argv in (["upgrade", "apply", "--all"], ["upgrade", "apply", found.tracks[0], *NEW]):
        with library.run_lock(found.paths.lock):
            code, env = run_json(argv, capsys)
        assert (code, env["outcome"]) == (3, "busy"), argv
    assert batches_of(found) == [] and found.entry(0)["upgrade"]


def test_stop_between_tracks_is_exit_5_keeps_what_is_done_and_leaves_the_batch_to_resume(lib, capsys):
    found = lib(["mp3", "mp3", "mp3"])
    STOP["after"] = 1
    code, env = run_json(["upgrade", "apply", "--all"], capsys)
    assert (code, env["outcome"], env["reason"]) == (5, "stopped", "stop")
    assert env["message"] == "Stopped after 1 of 3."
    data = env["data"]
    assert (data["state"], data["done"], [r["state"] for r in data["results"]]) == ("stopped", 1, ["done", "planned", "planned"])
    assert found.entry(0)["path"].endswith("Song 0.aiff") and found.entry(1)["path"] == found.olds[1]
    [row] = batches_of(found)
    assert row.state == "stopped"


def test_no_music_folder_is_refused_before_anything_starts(tmp_path, monkeypatch, capsys, inline_workers):
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(tmp_path / "empty-support"))
    code, env = run_json(["upgrade", "apply", "--all"], capsys)
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "no_library")


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


def test_a_window_still_gets_the_old_results_and_none_of_the_command_lines_words(lib, capsys, monkeypatch):
    import hub_helpers
    from discjockey.hub.api import HubApi
    found = lib(["mp3", "mp3"])
    monkeypatch.setattr(process, "running", lambda: True)
    assert run_json(["upgrade", "apply", *found.tracks, *SAME], capsys)[0] == NEEDS_PERSON  # leaves a stopped batch
    monkeypatch.setattr(process, "running", lambda: False)
    code, env = run_json(["upgrade", "apply", "--all"], capsys)  # the command line says: resume it first
    assert (code, env["reason"]) == (REFUSED, "not_stopped")
    assert HubApi._resume_first is False and api_words.CliApi._resume_first is True
    api, rec = hub_helpers.make_api(found.paths)  # the window's own HubApi: Upgrade all still starts a job
    answer = api.upgrade_all()
    assert answer["ok"] and answer["job_id"]
    finished = hub_helpers.wait_job(api, rec, answer)
    assert not hasattr(api, "result_words") and "person_steps" not in (finished.result or {})  # the window's contract


# --- the text page ---

def test_golden_the_page_of_a_new_track_apply(lib, capsys, tmp_path):
    from test_cli_golden import WRITES, check_golden
    found = lib(["mp3", "aiff"])
    code, out, err = run(["upgrade", "apply", *found.tracks, *NEW], capsys)
    assert code == OK and "upgrade_apply" in WRITES
    check_golden("upgrade_apply", out.replace(str(tmp_path), "<tmp>"))
    assert "Your turn: " in err and "relocate" in err and f"Then: {cmd('check done t1aaaaaaa')}" in err


# --- upgrade discard, track undo, check done (V1.11 part b) ---

def untouched(found):
    """Everything a command could change: the music files, rekordbox's library, the records, the batches."""
    return found.music(), found.dump(), library.load_state(found.paths)["tracks"], batches_of(found)


def test_discard_and_undo_without_yes_are_refused_with_the_dry_run_and_change_nothing(lib, stale_keys, capsys):
    found = lib(["mp3", "mp3"])
    assert run_json(["upgrade", "apply", found.tracks[0], *NEW], capsys)[0] == OK  # something to undo
    before = untouched(found)
    code, env = run_json(["upgrade", "discard", found.tracks[1], "nope"], capsys)
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "needs_yes")
    assert env["message"] == catalog.CONFIRM["upgrade discard"] and env["job"] is None
    data = env["data"]
    assert (data["mode"], data["total"], data["planned"], data["skipped"]) == ("discard", 2, 1, 1)
    first = data["items"][0]
    assert (first["key"], first["state"], first["file"], first["parked"]) == (
        found.tracks[1], "planned", str(found.paths.root / found.olds[1]),
        str(found.paths.root / found.entry(1)["upgrade"]["file"]))
    assert (data["items"][1]["state"], data["items"][1]["reason"]) == ("skipped", "no_upgrade")
    assert "plan_id" not in data  # Discard has no plan to run
    code, env = run_json(["track", "undo", found.tracks[0]], capsys)
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "needs_yes")
    assert env["message"] == catalog.CONFIRM["track undo"]
    [row] = env["data"]["items"]
    assert (row["key"], row["state"], row["reason"], row["step"]) == (found.tracks[0], "planned", None, "add_new")
    assert env["data"]["rekordbox"] == {"running": False, "needs_rekordbox_closed": False}
    assert "plan_id" not in env["data"]
    assert untouched(found) == before
    assert not (found.paths.support / "plans").exists()


def test_discard_with_yes_throws_the_new_versions_away_and_keeps_the_current_files(lib, stale_keys, capsys):
    found = lib(["mp3", "mp3", "mp3"])
    code, env = run_json(["upgrade", "discard", found.tracks[0], found.tracks[1], "nope", "--yes"], capsys)
    assert (code, env["outcome"]) == (PARTIAL, "partial")  # `nope` has nothing to discard: skipped
    data = env["data"]
    assert [(r["action"], r["state"]) for r in data["results"]] == [("discard", "done")] * 2 + [("discard", "skipped")]
    assert (data["done"], data["skipped"], data["total"]) == (2, 1, 3) and data["batch"] is None
    assert env["person_steps"] == [] and all(r["person_steps"] == [] for r in data["results"])
    assert not found.entry(0)["upgrade"] and not found.entry(1)["upgrade"] and found.entry(2)["upgrade"]
    assert (found.paths.root / found.olds[0]).is_file()  # the current file stays
    code, env = run_json(["upgrade", "discard", found.tracks[2], "--yes"], capsys)
    assert (code, env["outcome"], env["message"]) == (OK, "ok", "1 of 1 song done.")


def test_discard_has_no_plan_and_one_song_with_nothing_to_discard_is_refused(lib, stale_keys, capsys):
    found = lib(["mp3"])
    code, env = run_json(["upgrade", "discard", found.tracks[0], "--plan", "plan:000000000000", "--yes"], capsys)
    assert (code, env["outcome"]) == (REFUSED, "refused") and "Discard has none" in env["message"]
    assert found.entry(0)["upgrade"]
    code, env = run_json(["upgrade", "discard", "nope", "--yes"], capsys)  # one song with no better version waiting
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "changed")


def test_a_discard_gives_no_reload_step_even_for_a_song_with_an_open_check(lib, capsys):
    found = lib(["mp3"])
    assert run_json(["upgrade", "apply", found.tracks[0], *SAME], capsys)[0] == OK  # a reload_tag check is open now
    api = bind.default()
    done = {"track": found.tracks[0], "action": "discard", "state": "done", "reason": None, "message": None,
            "path": None, "rekordbox": None}
    words = api.result_words("upgrade", {"batch": None, "total": 1, "done": 1, "skipped": 0, "failed": 0, "results": [done]})
    assert words["ok"] and "person_steps" not in words and words["data"]["results"][0]["person_steps"] == []
    same = api.result_words("upgrade", {"batch": None, "total": 1, "done": 1, "skipped": 0, "failed": 0,
                                        "results": [{**done, "action": "same_track"}]})
    assert [s["id"] for s in same["person_steps"]] == ["step:look"]  # Same track's repoint wrote rekordbox's text
    # a check whose text still has to be reloaded (a swap while rekordbox was open) keeps Reload Tag, apart from the looks
    state = library.load_state(found.paths)
    state["tracks"][found.tracks[0]]["rekordbox_check"]["reload_tag"] = True
    library.save_state(found.paths, state)
    mixed = api.result_words("upgrade", {"batch": 5, "total": 1, "done": 1, "skipped": 0, "failed": 0,
                                         "results": [{**done, "action": "same_track"}]})
    assert [s["id"] for s in mixed["person_steps"]] == ["step:reload_tag"]
    assert mixed["person_steps"][0]["then"] == "check done --batch aiff:5"


def test_track_undo_puts_new_tracks_back_and_a_second_undo_has_nothing_to_undo(lib, capsys):
    found = lib(["mp3", "mp3"])
    before = found.music()
    assert run_json(["upgrade", "apply", *found.tracks, *NEW], capsys)[0] == OK
    assert found.music() != before
    code, env = run_json(["track", "undo", *found.tracks, "--yes"], capsys)
    assert (code, env["outcome"], env["message"]) == (OK, "ok", "2 of 2 tracks undone.")
    data = env["data"]
    assert (data["total"], data["undone"], data["refused"], data["failed"]) == (2, 2, 0, 0)
    assert sorted(r["track"] for r in data["results"]) == sorted(found.tracks)
    assert found.entry(0)["path"] == found.olds[0] and found.entry(0)["upgrade"]
    assert env["next"] == [{"run": cmd("upgrade list"), "why": "the better versions wait there again"}]
    code, env = run_json(["track", "undo", found.tracks[0], "--yes"], capsys)  # nothing left: the job is refused
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "refused")
    assert env["message"] == env["data"]["results"][0]["message"] and env["data"]["undone"] == 0
    code, env = run_json(["track", "undo", *found.tracks, "--yes"], capsys)
    assert (code, env["outcome"], env["message"]) == (REFUSED, "refused", batches.NOTHING_UNDONE)


def test_track_undo_of_a_mix_is_partial_with_the_refused_track_in_the_results(lib, capsys):
    found = lib(["mp3", "mp3"])
    assert run_json(["upgrade", "apply", found.tracks[0], *NEW], capsys)[0] == OK
    code, env = run_json(["track", "undo", *found.tracks, "--yes"], capsys)  # the second was never replaced
    assert (code, env["outcome"], env["message"]) == (PARTIAL, "partial", "1 of 2 tracks undone.")
    states = {r["track"]: (r["state"], r["reason"]) for r in env["data"]["results"]}
    assert states[found.tracks[0]] == ("undone", None) and states[found.tracks[1]][0] == "refused"


def test_track_undo_dry_run_says_per_track_whether_it_can_be_undone_and_why_not(lib, stale_keys, capsys):
    found = lib(["mp3", "mp3", "mp3"])
    assert run_json(["upgrade", "apply", *found.tracks[:2], *NEW], capsys)[0] == OK
    assert run_json(["check", "done", found.tracks[1]], capsys)[0] == OK  # ends the undo of the second
    before = untouched(found)
    code, env = run_json(["track", "undo", *found.tracks, "nope", "--dry-run"], capsys)
    assert code == OK and env["outcome"] == "ok"
    rows = {r["key"]: r for r in env["data"]["items"]}
    assert rows[found.tracks[0]]["state"] == "planned" and rows[found.tracks[0]]["step"] == "add_new"
    for key in (found.tracks[1], found.tracks[2], "nope"):
        assert (rows[key]["state"], rows[key]["reason"]) == ("skipped", "nothing_to_undo"), key
        assert rows[key]["message"] == upgrades.UNDO_BLOCKED["nothing_to_undo"]
    assert (env["data"]["total"], env["data"]["planned"], env["data"]["skipped"]) == (4, 1, 3)
    assert untouched(found) == before and "plan_id" not in env["data"]


def test_the_blockers_of_an_undo_are_the_engines_words():
    here = {"path": "a.aiff", "upgrade": None, "rekordbox_check": {"undo": {"file": "a.aiff", "kind": "swap"}}}
    assert upgrades.undo_blocker(here) is None and upgrades.can_undo(here)
    assert upgrades.undo_blocker({**here, "path": "b.aiff"}) == "other_file"
    assert upgrades.undo_blocker({**here, "upgrade": {"file": "x"}}) == "newer_waiting"
    assert upgrades.undo_blocker({**here, "rekordbox_check": None}) == "nothing_to_undo"
    assert upgrades.undo_blocker(None) == "nothing_to_undo" and not upgrades.can_undo({"path": "a"})
    assert set(upgrades.UNDO_BLOCKED) == {"nothing_to_undo", "other_file", "newer_waiting"}


def test_track_undo_of_a_same_track_needs_rekordbox_quit_and_changes_nothing(lib, capsys, monkeypatch):
    found = lib(["mp3", "mp3"])
    assert run_json(["upgrade", "apply", "--all"], capsys)[0] == OK
    monkeypatch.setattr(process, "running", lambda: True)
    before = untouched(found)
    code, env = run_json(["track", "undo", *found.tracks, "--dry-run"], capsys)
    assert env["data"]["rekordbox"] == {"running": True, "needs_rekordbox_closed": True}
    code, env = run_json(["track", "undo", *found.tracks, "--yes"], capsys)
    assert (code, env["outcome"], env["reason"]) == (NEEDS_PERSON, "needs_person", "rekordbox_open")
    assert [s["id"] for s in env["person_steps"]] == ["step:quit_rekordbox"]
    assert [r["state"] for r in env["data"]["results"]] == ["waiting", "waiting"]
    assert untouched(found) == before
    monkeypatch.setattr(process, "running", lambda: False)
    assert run_json(["track", "undo", *found.tracks, "--yes"], capsys)[0] == OK


def test_stop_before_the_first_track_is_exit_5_for_discard_and_undo_and_changes_nothing(lib, capsys):
    found = lib(["mp3", "mp3"])
    assert run_json(["upgrade", "apply", *found.tracks, *NEW], capsys)[0] == OK
    before = untouched(found)
    STOP["at_start"] = True
    for argv in (["track", "undo", *found.tracks, "--yes"], ["upgrade", "discard", *found.tracks, "--yes"]):
        code, env = run_json(argv, capsys)
        assert (code, env["outcome"], env["reason"]) == (5, "stopped", "stop"), argv
    assert untouched(found) == before


def test_discard_undo_and_check_take_the_library_lock_and_a_held_one_is_busy(lib, capsys):
    found = lib(["mp3"])
    for argv in (["upgrade", "discard", found.tracks[0], "--yes"], ["track", "undo", found.tracks[0], "--yes"],
                 ["check", "done", found.tracks[0]]):
        with library.run_lock(found.paths.lock):
            code, env = run_json(argv, capsys)
        assert (code, env["outcome"]) == (3, "busy"), argv
    assert found.entry(0)["upgrade"]


def test_the_no_music_folder_refuses_the_new_words_too(tmp_path, monkeypatch, capsys, inline_workers):
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(tmp_path / "empty-support"))
    key = "a" * 22  # a song key (a Spotify id) of a library that is not there
    for argv in (["upgrade", "discard", key, "--yes"], ["track", "undo", key, "--yes"], ["check", "done", key],
                 ["check", "done", "--all"]):
        code, env = run_json(argv, capsys)
        assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "no_library"), argv


# --- check done ---

def apply_same(found, capsys, tracks=None):
    code, env = run_json(["upgrade", "apply", *(tracks or found.tracks), *SAME], capsys)
    assert code == OK, env
    return env["data"]["batch_id"]


def test_check_done_ends_the_check_and_its_undo_and_the_message_says_so(lib, capsys):
    found = lib(["mp3", "aiff"])
    apply_same(found, capsys)
    code, env = run_json(["check", "done", found.tracks[0]], capsys)
    assert (code, env["outcome"]) == (OK, "ok")
    assert env["message"] == "1 track checked in rekordbox." + api_words.CHECK_ENDS_UNDO
    data = env["data"]
    assert data["results"] == [{"track": found.tracks[0], "action": "check", "state": "done", "reason": None,
                                "message": "checked in rekordbox"}]
    assert (data["total"], data["done"], data["skipped"], data["checked"]) == (1, 1, 0, [found.tracks[0]])
    assert found.entry(0)["rekordbox_check"] is None and found.entry(1)["rekordbox_check"]
    code, env = run_json(["track", "undo", found.tracks[0], "--yes"], capsys)  # the check's undo ended with it
    assert (code, env["outcome"]) == (REFUSED, "refused")
    lines = [json.loads(line) for line in found.paths.operations_log.read_text(encoding="utf-8").splitlines()]
    [line] = [x for x in lines if x["operation"] == "rekordbox_checked"]
    assert (line["track_id"], line["result"]) == (found.tracks[0], "done")


def test_check_done_batch_checks_that_batchs_tracks_and_a_second_time_has_nothing_left(lib, capsys):
    found = lib(["mp3", "aiff", "mp3_free"])
    batch = apply_same(found, capsys)
    assert run_json(["check", "done", found.tracks[0]], capsys)[0] == OK  # one by hand first: not a problem
    code, env = run_json(["check", "done", "--batch", batch], capsys)
    assert (code, env["outcome"]) == (OK, "ok")
    assert [r["track"] for r in env["data"]["results"]] == found.tracks[1:] and env["data"]["batch"] == 1
    assert all(found.entry(i)["rekordbox_check"] is None for i in range(3))
    code, env = run_json(["check", "done", "--batch", batch], capsys)  # all checked: done, with nothing in it
    assert (code, env["outcome"], env["message"]) == (OK, "ok", api_words.NOTHING_TO_CHECK)
    assert (env["data"]["results"], env["data"]["total"]) == ([], 0)


def test_check_done_batch_ids_are_typed_and_checked(lib, capsys):
    found = lib(["mp3"])
    batch = apply_same(found, capsys)
    for text, reason in (("aiff:77", "unknown_id"), ("1", "bad_id_kind"), ("moves:1", "bad_id_kind")):
        code, env = run_json(["check", "done", "--batch", text], capsys)
        assert (code, env["outcome"], env["reason"]) == (2, "bad_args", reason), text
    code, env = run_json(["check", "done", found.tracks[0], "--batch", batch], capsys)
    assert (code, env["outcome"], env["reason"]) == (2, "bad_args", "conflicting_flags")
    code, env = run_json(["check", "done"], capsys)
    assert (code, env["reason"]) == (2, "usage") and "--batch <aiff:n>" in env["message"]
    code, env = run_json(["track", "undo"], capsys)  # a command with no batch says the shorter list
    assert (code, env["reason"]) == (2, "usage") and "--rows." in env["message"] and "--batch" not in env["message"]
    assert found.entry(0)["rekordbox_check"]


def test_a_track_with_nothing_to_check_is_skipped_not_an_error(lib, capsys):
    found = lib(["mp3", "mp3_plain"])
    apply_same(found, capsys, found.tracks[:1])
    code, env = run_json(["check", "done", found.tracks[0], found.tracks[1]], capsys)  # the second was never replaced
    assert (code, env["outcome"], env["reason"]) == (PARTIAL, "partial", None)
    assert [(r["track"], r["state"], r["reason"]) for r in env["data"]["results"]] == [
        (found.tracks[0], "done", None), (found.tracks[1], "skipped", "nothing_to_check")]
    assert env["message"].startswith("1 of 2 tracks checked in rekordbox.") and env["message"].endswith("1 had nothing to check.")
    code, env = run_json(["check", "done", found.tracks[1]], capsys)  # only such tracks: nothing to do is no error
    assert (code, env["outcome"], env["reason"]) == (OK, "ok", None)
    assert [(r["track"], r["state"], r["reason"]) for r in env["data"]["results"]] == [
        (found.tracks[1], "skipped", "nothing_to_check")]
    assert (env["data"]["total"], env["data"]["done"], env["data"]["skipped"]) == (0, 0, 1)
    assert env["message"] == api_words.NOTHING_TO_CHECK
    from discjockey.hub.api import HubApi  # the window's job keeps ending `changed`
    assert HubApi._skipped_check_is_ok is False


def test_check_done_all_checks_every_open_check_and_with_none_open_is_ok_total_0(lib, capsys):
    found = lib(["mp3", "aiff"])
    apply_same(found, capsys)
    code, env = run_json(["check", "done", "--all"], capsys)
    assert (code, env["outcome"], env["data"]["done"], env["data"]["total"]) == (OK, "ok", 2, 2)
    code, env = run_json(["check", "done", "--all"], capsys)
    assert (code, env["outcome"], env["message"]) == (OK, "ok", api_words.NOTHING_TO_CHECK)
    assert (env["data"]["total"], env["data"]["results"], env["job"]) == (0, [], None)
    code, env = run_json(["check", "done", "--all", "--dry-run"], capsys)
    assert (code, env["reason"]) == (2, "usage")  # no dry run: the window doesn't ask


def test_the_bridge_takes_tracks_or_a_batch_for_a_check_but_not_both(lib):
    found = lib(["mp3"])
    api = bind.default()
    answer = api.rekordbox_checked(found.tracks, batch_id=1)
    assert (answer["ok"], answer["kind"]) == (False, "refused") and "not both" in answer["message"]
    assert api.rekordbox_checked([], batch_id=9)["message"] == api_words.NO_AIFF_BATCH
    assert api.rekordbox_checked([])["ok"] is False


# --- the text pages ---

def test_golden_the_pages_of_a_discard_an_undo_and_a_check(lib, capsys, tmp_path):
    from test_cli_golden import WRITES, check_golden
    found = lib(["mp3", "aiff"])
    assert run(["upgrade", "apply", found.tracks[0], *NEW], capsys)[0] == OK
    code, out, err = run(["upgrade", "discard", found.tracks[1], "--yes"], capsys)
    assert code == OK and "upgrade_discard" in WRITES
    check_golden("upgrade_discard", out.replace(str(tmp_path), "<tmp>"))
    code, out, err = run(["track", "undo", found.tracks[0], "--yes"], capsys)
    assert code == OK and "track_undo" in WRITES
    check_golden("track_undo", out.replace(str(tmp_path), "<tmp>"))
    assert run(["upgrade", "apply", found.tracks[0], *NEW], capsys)[0] == OK
    code, out, err = run(["check", "done", found.tracks[0]], capsys)
    assert code == OK and "check_done" in WRITES
    check_golden("check_done", out.replace(str(tmp_path), "<tmp>"))


def test_check_done_batch_leaves_a_song_a_later_batch_changed_again(lib, capsys):
    found = lib(["mp3", "aiff"])
    first = apply_same(found, capsys)
    run_json(["upgrade", "apply", found.tracks[0], *SAME], capsys)  # batch 2 exists (it found nothing to do here)
    state = library.load_state(found.paths)  # ...as if it had redone the first song: its open check is that batch's
    state["tracks"][found.tracks[0]]["rekordbox_check"]["batch"] = 2
    library.save_state(found.paths, state)
    before = copy.deepcopy(found.entry(0))
    code, env = run_json(["check", "done", "--batch", first], capsys)
    rows = {r["track"]: r for r in env["data"]["results"]}
    assert rows[found.tracks[1]]["state"] == "done"
    assert (rows[found.tracks[0]]["state"], rows[found.tracks[0]]["reason"]) == ("skipped", "newer_batch")
    assert "aiff:2" in rows[found.tracks[0]]["message"] and (code, env["outcome"]) == (PARTIAL, "partial")
    assert found.entry(0) == before and found.entry(1)["rekordbox_check"] is None  # check, undo and download stay
    code, env = run_json(["check", "done", "--batch", "aiff:2"], capsys)
    assert [r["track"] for r in env["data"]["results"]] == [found.tracks[0]] and code == OK
    assert found.entry(0)["rekordbox_check"] is None

