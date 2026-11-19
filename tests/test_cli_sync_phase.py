"""Group V1.14, part a (issue 39, design §5.2, §7.1, §15 stage C): `sync run --auto-upgrade-only`, the sync's Auto-upgrade
phase alone, through the command line on a fixture library and a fixture rekordbox (`batch_helpers.make_lib`).

The phase never plans and never reads the playlists (`run.auto_upgrade_only`); its job runs in this process
(`test_cli_upgrade.inline_workers`: the same worker, spawn and registry). Its text page is pinned by
`tests/cli_golden/sync_run.txt`; its dry run is a row of T9 (`test_cli_dryrun.T9`) and its locks a row of T10
(`test_cli_locks.DRIVERS`)."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
from hub_helpers import cmd

from batch_helpers import needs_ffmpeg
from discjockey import library
from discjockey import words as engine_words
from discjockey.cli import bind, parser
from discjockey.hub import catalog
from discjockey.hub.api import CliApi
from discjockey.rekordbox import process
from discjockey.settings import Settings, load_settings, save_settings
from test_cli_upgrade import STOP, batches_of, inline_workers, lib, run, run_json  # noqa: F401 - fixtures

pytestmark = needs_ffmpeg

OK, BAD_ARGS = 0, 2
PHASE = ["sync", "run", "--auto-upgrade-only"]


def tree(root: Path, skip: tuple[Path, ...] = ()) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*"))
            if p.is_file() and not any(p.is_relative_to(s) for s in skip)}


def hide(found, i: int, hidden: bool) -> None:
    """To-do's Hide on song `i` (the window's; the command line has no `track hide` yet): a hidden song is not in the set."""
    state = library.load_state(found.paths)
    state["tracks"][found.tracks[i]]["hidden"] = hidden
    library.save_state(found.paths, state)


def upgrade_listing(capsys) -> list[str]:
    code, env = run_json(["upgrade", "list"], capsys)
    assert code == OK
    return [row["track_id"] for row in env["data"]["groups"][0]["items"]]


# --- the phase alone ---

def test_the_phase_alone_upgrades_two_same_edit_tracks_in_one_auto_upgrade_batch_and_files_its_report(lib, capsys):
    found = lib(["mp3", "mp3"])
    code, env = run_json(PHASE, capsys)
    assert (code, env["outcome"], env["command"]) == (OK, "ok", "sync run"), env
    block = env["data"]["auto_upgrade"]
    assert (block["done"], block["waiting"], block["refused"], block["failed"], block["dry_run"]) == (2, 0, 0, 0, False)
    assert [r["state"] for r in block["results"]] == ["done", "done"] and block["batch"] == 1 and block["backup"]
    [row] = batches_of(found)
    assert (row.id, row.started_by, row.state, row.scope, row.via) == (1, "auto_upgrade", "done", "sync", "terminal")
    assert found.row(0)["FolderPath"].endswith("Song 0.aiff")  # rekordbox's row points at the new file
    assert env["message"] == "Upgraded 2 tracks; your cues stayed."
    assert [n["run"] for n in env["next"]] == [cmd("batch show aiff:1"), cmd("check list"),
                                                     cmd(f"report show {env['data']['report']}")]
    assert env["data"]["batch_id"] == "aiff:1" and [s["id"] for s in env["person_steps"]] == ["step:look"]
    # the report: a run of its own kind that holds the block
    code, shown = run_json(["report", "show", "last"], capsys)
    run_data = shown["data"]["run"]
    assert (code, run_data["kind"], run_data["auto_upgrade"]["done"], run_data["auto_upgrade"]["batch"]) == (OK, "auto_upgrade_only", 2, 1)
    assert env["data"]["report"] == f"report:{run_data['run_id']}"
    md = (found.paths.reports / f"{run_data['run_id']}.md").read_text()
    assert md.startswith("# Discjockey Auto-upgrade run ") and "Upgraded 2 tracks" in md
    assert [r["section"] for r in run_data["sections"]["upgraded"]] == ["upgraded"] * 2
    assert not found.paths.playlists_file.exists()  # no playlist was read or written: the planner never ran


def test_rekordbox_running_makes_both_upgrades_wait_and_moves_nothing_with_exit_0(lib, capsys, monkeypatch):
    found = lib(["mp3", "mp3"])
    monkeypatch.setattr(process, "running", lambda: True)
    before = [found.entry(i)["path"] for i in range(2)]
    code, env = run_json(PHASE, capsys)
    assert (code, env["outcome"], env["reason"]) == (OK, "ok", None), env
    block = env["data"]["auto_upgrade"]
    assert (block["done"], block["waiting"], block["batch"], block["backup"]) == (0, 2, None, None)
    assert [(r["state"], r["reason"]) for r in block["results"]] == [("waiting", "rekordbox_open")] * 2
    assert batches_of(found) == [] and [found.entry(i)["path"] for i in range(2)] == before
    assert found.entry(0)["upgrade"]["auto_waits"]  # the To-do page marks them: "Waits for rekordbox to be closed"
    assert env["message"] == "2 upgrades wait for rekordbox to be closed." == engine_words.waiting_line(2)
    assert run_json(["report", "show", "last"], capsys)[1]["data"]["run"]["kind"] == "auto_upgrade_only"
    monkeypatch.setattr(process, "running", lambda: False)  # quit rekordbox: the same command now upgrades both
    code, env = run_json(PHASE, capsys)
    assert (code, env["data"]["auto_upgrade"]["done"]) == (OK, 2)


def test_a_track_that_fails_makes_the_run_partial_and_a_wait_does_not():
    api = CliApi.__new__(CliApi)
    row = lambda track, state: {"track": track, "state": state, "reason": None}  # noqa: E731
    block = lambda *rows: {"auto_upgrade": {"batch": None, "done": 0, "failed": 0, "waiting": 0, "refused": 0,  # noqa: E731
                                            "results": list(rows)}}
    words = lambda *rows: CliApi.result_words.__wrapped__(api, "auto_upgrade_run", block(*rows))  # noqa: E731
    assert words(row("a", "waiting"), row("b", "refused"))["outcome"] == "ok"
    assert words(row("a", "done"), row("b", "failed"))["outcome"] == "partial"
    assert words(row("a", "failed"))["outcome"] == "failed"
    assert catalog.AUTO_UPGRADE_PARTIAL == ("failed",)


def test_a_stop_during_the_phase_ends_it_stopped_with_exit_130_keeps_the_block_and_saves_the_records(lib, capsys):
    found = lib(["mp3", "mp3"])
    STOP["after"] = 1  # Stop is pressed while the first track is being measured
    code, env = run_json(PHASE, capsys)
    assert (code, env["outcome"], env["reason"]) == (5, "stopped", "stop"), env
    assert env["data"]["exit_code"] == 130 and env["data"]["report"]
    block = env["data"]["auto_upgrade"]
    assert block["stopped"] is True and (block["done"], block["waiting"]) == (1, 1)
    assert [(r["state"], r["reason"]) for r in block["results"]] == [("done", None), ("waiting", "not_reached")]
    assert found.entry(0)["path"].endswith("Song 0.aiff") and found.entry(1)["path"] == found.olds[1]  # saved as it stood
    assert found.entry(1)["upgrade"]  # the second still waits in To-do
    [row] = batches_of(found)
    assert (row.started_by, row.state) == ("auto_upgrade", "done")  # `end_auto` closed it: no Resume, the rest skipped


def test_a_crash_in_the_phase_is_filed_as_a_report_with_its_note_and_answers_failed_with_no_block(lib, capsys, monkeypatch):
    from discjockey import auto_upgrade

    def boom(*args, **kwargs):
        raise RuntimeError("disk fell off")
    found = lib(["mp3", "mp3"])
    monkeypatch.setattr(auto_upgrade, "run_phase", boom)
    code, env = run_json(PHASE, capsys)
    assert code != OK and env["outcome"] == "failed", env
    assert env["data"]["exit_code"] == 1 and env["data"]["auto_upgrade"] is None and env["data"]["recovered"] == []
    stamp = env["data"]["report"].removeprefix("report:")
    md = (found.paths.reports / f"{stamp}.md").read_text()
    assert "disk fell off" in md and auto_upgrade.STEP in md  # the crash note names what the run was doing
    assert found.entry(0)["path"] == found.olds[0] and batches_of(found) == []


def test_a_track_that_fails_makes_the_run_partial_with_exit_code_1_and_the_other_track_is_done(lib, capsys, monkeypatch):
    found = lib(["mp3", "mp3"])
    inline = bind.headless
    calls: list[int] = []

    def headless(resolved, **kw):
        api = inline(resolved, **kw)
        measure = api._svc.compare

        def compare(a, b):  # the first track's two files cannot be measured
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("cannot read the file")
            return measure(a, b)
        api._svc.compare = compare
        return api
    monkeypatch.setattr(bind, "headless", headless)
    code, env = run_json(PHASE, capsys)
    assert (code, env["outcome"]) == (6, "partial"), env
    assert env["data"]["exit_code"] == 1
    block = env["data"]["auto_upgrade"]
    assert (block["done"], block["failed"]) == (1, 1)
    assert sorted(r["state"] for r in block["results"]) == ["done", "failed"]
    assert found.entry(1)["path"].endswith("Song 1.aiff") and found.entry(0)["path"] == found.olds[0]


def test_steps_recovered_at_the_start_of_the_phase_are_in_the_result(lib, capsys, monkeypatch):
    lib(["mp3"])
    monkeypatch.setattr(library, "recover_pending", lambda paths, state: [("Finished moving Song 0.", True)])
    code, env = run_json(PHASE, capsys)
    assert (code, env["outcome"]) == (OK, "ok"), env
    assert env["data"]["recovered"] == [["Finished moving Song 0.", True]]


def test_a_track_whose_batch_never_ran_keeps_its_recorded_refusal(lib, capsys):
    from discjockey.rekordbox import lock
    found = lib(["mp3"])
    state = library.load_state(found.paths)
    record = {"reason": "timing", "message": "its timing cannot be measured", "at": "2026-11-01T10:00:00",
              "anlz": {"ANLZ0000.DAT": 1}, "free": None, "files": None}
    state["tracks"][found.tracks[0]]["upgrade"]["auto_refused"] = record
    library.save_state(found.paths, state)
    with lock.writer_lock(found.paths.support):  # another window or the Terminal is changing rekordbox's library
        code, env = run_json(PHASE, capsys)
    assert code == OK, env
    assert [(r["state"], r["reason"]) for r in env["data"]["auto_upgrade"]["results"]] == [("waiting", "busy")]
    assert found.entry(0)["upgrade"]["auto_refused"] == record  # not tried, so what was recorded still stands


# --- the dry run ---

def test_the_dry_run_writes_nothing_and_has_the_start_note_and_the_block(lib, capsys, monkeypatch):
    found = lib(["mp3", "mp3"])
    support, music, rekordbox = found.paths.support, found.paths.root, found.folder
    skip = (support / "plans", support / "cache")
    snapshot = lambda: [tree(f, skip) for f in (support, music, rekordbox)]  # noqa: E731
    before = snapshot()
    code, env = run_json([*PHASE, "--dry-run"], capsys)
    assert (code, env["outcome"], env["job"]) == (OK, "ok", None), env
    assert snapshot() == before and not (support / "jobs").exists() and not found.paths.reports.exists()
    data = env["data"]
    assert data["start_note"] == engine_words.auto_plan_line(2) == "2 upgrades go in at the end; cues stay."
    block = data["auto_upgrade"]
    assert (block["dry_run"], block["batch"], block["backup"]) == (True, None, None)
    assert [(r["state"], r["how"]) for r in block["results"]] == [("would", "new_aiff")] * 2
    assert data["plan_id"].startswith("plan:") and env["as_of"]["scanned_at"] is None
    monkeypatch.setattr(process, "running", lambda: True)  # rekordbox open: the Sync page's other line
    _, env = run_json([*PHASE, "--dry-run"], capsys)
    assert env["data"]["start_note"] == engine_words.before_start_line(2)
    assert [r["state"] for r in env["data"]["auto_upgrade"]["results"]] == ["waiting"] * 2
    assert snapshot() == before


# --- the switch ---

def test_with_the_switch_off_the_phase_answers_ok_with_no_block_and_moves_nothing(lib, capsys):
    found = lib(["mp3", "mp3"])
    save_settings(found.paths.settings_file, Settings(auto_upgrade=False))  # `settings set` is the next group's
    code, env = run_json(PHASE, capsys)
    assert (code, env["outcome"], env["job"] is not None) == (OK, "ok", True), env
    assert env["data"]["auto_upgrade"] is None and env["data"]["report"] is None
    assert env["message"] == "Auto-upgrade is off, so nothing was moved." == engine_words.AUTO_UPGRADE_OFF
    assert batches_of(found) == [] and not found.paths.reports.exists()
    assert found.entry(0)["path"] == found.olds[0] and found.entry(1)["upgrade"]
    assert upgrade_listing(capsys) == found.tracks  # `upgrade list` still lists them
    code, env = run_json([*PHASE, "--dry-run"], capsys)  # the dry run says the same, and makes no plan
    assert (code, env["message"]) == (OK, engine_words.AUTO_UPGRADE_OFF)
    assert env["data"]["auto_upgrade"] is None and env["data"]["start_note"] is None and "plan_id" not in env["data"]
    assert load_settings(found.paths.settings_file).auto_upgrade is False


def test_a_settings_file_the_sync_cannot_read_is_config_invalid_and_moves_nothing(lib, capsys):
    found = lib(["mp3"])
    found.paths.settings_file.write_text('{"auto_upgrade": "yes"}')
    code, env = run_json(PHASE, capsys)
    assert code != OK and env["outcome"] == "failed" and env["reason"] == "config_invalid", env
    assert batches_of(found) == [] and found.entry(0)["path"] == found.olds[0]


def test_a_plan_with_a_settings_file_that_cannot_be_read_is_config_invalid_not_changed(lib, capsys):
    found = lib(["mp3"])
    _, dry = run_json([*PHASE, "--dry-run"], capsys)
    found.paths.settings_file.write_text('{"auto_upgrade": "yes"}')
    code, env = run_json([*PHASE, "--plan", dry["data"]["plan_id"]], capsys)
    assert (code, env["outcome"], env["reason"]) == (1, "failed", "config_invalid"), env
    assert batches_of(found) == [] and found.entry(0)["path"] == found.olds[0]


# --- the line ---

def test_without_the_switch_of_its_own_sync_run_is_a_usage_error_naming_the_whole_sync(lib, capsys):
    lib(["mp3"])
    for argv in (["sync", "run"], ["sync", "run", "--dry-run"], ["sync", "run", "--plan", "plan:000000000000"]):
        code, env = run_json(argv, capsys)
        assert (code, env["outcome"], env["reason"]) == (BAD_ARGS, "bad_args", "usage"), argv
        assert "--auto-upgrade-only" in env["message"] and "`discjockey --yes`" in env["message"]


def test_help_lists_the_phase_alone_with_its_flags_and_locks(capsys):
    code, env = run_json(["help"], capsys)
    [entry] = [c for c in env["data"]["commands"] if c["command"] == "sync run"]
    assert entry["kind"] == "J" and entry["dry_run"] and not entry["needs_yes"]
    assert {"--auto-upgrade-only", "--dry-run"} <= set(entry["flags"])
    assert [a["word"] for a in entry["args"]] == ["--plan"]
    assert set(entry["locks"]) == {"library", "rekordbox_r", "rekordbox_w"} and entry["example"] == catalog.entry_of(
        "auto_upgrade_run", "sync run").example
    assert parser.parse(PHASE).flags.auto_upgrade_only


# --- --plan ---

def test_a_run_with_a_plan_runs_the_tracks_that_still_stand_and_leaves_the_one_that_changed(lib, capsys):
    found = lib(["mp3", "mp3"])
    _, dry = run_json([*PHASE, "--dry-run"], capsys)
    plan_id = dry["data"]["plan_id"]
    assert run_json(["upgrade", "discard", found.tracks[1], "--yes"], capsys)[0] == OK  # the second changed since the plan
    code, env = run_json([*PHASE, "--plan", plan_id], capsys)
    assert (code, env["outcome"]) == (OK, "ok"), env
    rows = {r["track"]: r for r in env["data"]["auto_upgrade"]["results"]}
    assert [(t, r["state"], r["reason"]) for t, r in rows.items()] == [
        (found.tracks[0], "done", None), (found.tracks[1], "waiting", "changed")]
    assert found.entry(0)["path"].endswith("Song 0.aiff") and "new_since_plan" not in env["data"]


def test_a_plan_none_of_whose_tracks_stands_is_changed_and_an_unknown_one_is_bad_args(lib, capsys):
    found = lib(["mp3"])
    _, dry = run_json([*PHASE, "--dry-run"], capsys)
    assert run_json(["upgrade", "discard", found.tracks[0], "--yes"], capsys)[0] == OK
    code, env = run_json([*PHASE, "--plan", dry["data"]["plan_id"]], capsys)
    assert (code, env["outcome"], env["reason"]) == (7, "refused", "changed") and batches_of(found) == []
    code, env = run_json([*PHASE, "--plan", "plan:abcdefabcdef"], capsys)
    assert (code, env["outcome"], env["reason"]) == (BAD_ARGS, "bad_args", "unknown_id")


def test_a_track_new_since_the_plan_is_listed_and_left_for_the_next_run(lib, capsys):
    found = lib(["mp3", "mp3"])
    hide(found, 1, True)  # the plan is made while only the first stands
    _, dry = run_json([*PHASE, "--dry-run"], capsys)
    assert [r["track"] for r in dry["data"]["auto_upgrade"]["results"]] == [found.tracks[0]]
    hide(found, 1, False)  # now the second is ready: new since the plan
    code, env = run_json([*PHASE, "--plan", dry["data"]["plan_id"]], capsys)
    assert (code, env["outcome"]) == (OK, "ok"), env
    assert [r["track"] for r in env["data"]["auto_upgrade"]["results"]] == [found.tracks[0]]
    assert env["data"]["new_since_plan"] == [found.tracks[1]] and found.entry(1)["path"] == found.olds[1]


def test_without_a_music_folder_the_phase_is_refused_no_library_and_its_dry_run_too(inline_workers, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(tmp_path / "support"))
    for argv in (PHASE, [*PHASE, "--dry-run"]):
        code, env = run_json(argv, capsys)
        assert (code, env["outcome"], env["reason"]) == (7, "refused", "no_library"), argv


# --- reading rekordbox beside a writer ---

def test_the_phase_reads_rekordboxs_library_only_when_no_other_writer_holds_it(lib):
    from discjockey import auto_upgrade
    from discjockey.rekordbox import lock
    found = lib(["mp3"])
    state = library.load_state(found.paths)
    read = lambda: auto_upgrade.stamps(found.paths, found.tracks, state, running=lambda: False, place=found.place)  # noqa: E731
    assert read()[found.tracks[0]] is not None  # nobody writes: the analysis files are read
    with lock.writer_lock(found.paths.support):  # another window or the Terminal changes rekordbox: nothing is opened
        assert read() == {found.tracks[0]: None}
        planned = auto_upgrade.plan(found.paths, state, (), Settings(), running=lambda: False, place=found.place)
    assert planned.run == found.tracks  # the set is still told (a library it cannot ask is taken as readable)


# --- the page ---

def test_golden_the_page_of_the_phase_alone(lib, capsys, tmp_path):
    from test_cli_golden import WRITES, check_golden
    lib(["mp3", "aiff"])
    code, out, err = run(PHASE, capsys)
    assert code == OK and "sync_run" in WRITES
    text = out.replace(str(tmp_path), "<tmp>")
    text = re.sub(r"report:\d{4}-\d{2}-\d{2}_\d{6}", "report:<stamp>", text)
    text = re.sub(r"\d{8}T\d{6}Z(?:-\d+)?", "<backup>", text)
    check_golden("sync_run", text)
    assert "Your turn: " in err and f"Next: {cmd('batch show aiff:1')}" in err


# --- placements (issue 43 E4b2): a missing song's parked better version, with the switch off too ---

def test_the_preview_lists_a_placement_and_a_plan_bound_by_id_keeps_its_row(lib, capsys):
    from test_place_phase import mark_missing
    found = lib(["aiff", "mp3"])
    save_settings(found.paths.settings_file, Settings(auto_upgrade=False))
    mark_missing(found, 0)  # Download again was pressed for it; the second song is an upgrade the switch leaves parked
    code, dry = run_json([*PHASE, "--dry-run"], capsys)
    assert code == OK, dry
    block = dry["data"]["auto_upgrade"]
    assert block is not None and block["dry_run"] is True
    assert [(r["track"], r["state"], r["action"], r["how"]) for r in block["results"]] == [
        (found.tracks[0], "would", "place", "placed")]
    assert dry["data"]["start_note"] == "Artist – Song 0 gets its better version at the end of the sync."
    assert dry["data"]["plan_id"].startswith("plan:")
    code, env = run_json([*PHASE, "--plan", dry["data"]["plan_id"]], capsys)
    assert (code, env["outcome"]) == (OK, "ok"), env
    [row] = env["data"]["auto_upgrade"]["results"]
    assert (row["track"], row["state"], row["action"], row["how"]) == (found.tracks[0], "done", "place", "placed")
    assert found.entry(0)["path"].endswith("Artist - Song 0.aiff") and found.entry(1)["path"] == found.olds[1]
    [batch] = batches_of(found)
    assert (batch.started_by, batch.state) == ("download_again", "done")


def test_a_plan_whose_placement_no_longer_stands_is_changed(lib, capsys):
    from test_place_phase import mark_missing
    found = lib(["aiff"])
    save_settings(found.paths.settings_file, Settings(auto_upgrade=False))
    mark_missing(found, 0)
    _, dry = run_json([*PHASE, "--dry-run"], capsys)
    state = library.load_state(found.paths)
    state["tracks"][found.tracks[0]]["file_gone"] = None  # the mark is gone (the file came back, or it was undone)
    library.save_state(found.paths, state)
    code, env = run_json([*PHASE, "--plan", dry["data"]["plan_id"]], capsys)
    assert (code, env["outcome"], env["reason"]) == (7, "refused", "changed") and batches_of(found) == []


def test_a_placement_of_a_different_edit_under_a_new_name_has_the_new_file_step_with_its_path(lib, capsys):
    from discjockey.align import Alignment
    from test_place_phase import mark_missing
    found = lib(["mp3", "aiff"])  # the mp3 is placed as an AIFF under a new name; the aiff takes its missing file's name
    save_settings(found.paths.settings_file, Settings(auto_upgrade=False))
    for i in (0, 1):
        mark_missing(found, i)
    state = library.load_state(found.paths)
    state["tracks"][found.tracks[0]]["upgrade"]["alignment"] = Alignment("different", text="x").to_dict()
    library.save_state(found.paths, state)
    code, env = run_json(PHASE, capsys)
    assert (code, env["outcome"]) == (OK, "ok"), env
    assert [(r["track"], r["state"], r["action"]) for r in env["data"]["auto_upgrade"]["results"]] == [
        (found.tracks[0], "done", "place"), (found.tracks[1], "done", "place")]
    new_file = str(found.paths.root / found.entry(0)["path"])
    steps = {s["id"]: s for s in env["person_steps"]}
    assert set(steps) == {"step:relocate_new", "step:look"}, steps
    assert new_file in steps["step:relocate_new"]["say"] and steps["step:relocate_new"]["then"] == cmd(
        f"check done {found.tracks[0]}")
    assert found.tracks[1] in steps["step:look"]["say"] and new_file not in steps["step:look"]["say"]
