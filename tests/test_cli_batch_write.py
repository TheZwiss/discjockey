"""Group V1.12, part a (issue 39, design §5.2, §6.6, §7.4): `batch resume aiff:<n>` and `batch undo aiff:<n> --yes
[--dry-run]` through the command line, end to end, on a fixture library and a fixture rekordbox (`batch_helpers.make_lib`),
and the two facts a batch records since schema 10: where it started (`via`) and its real scope.

A job's worker runs in this process (`inline_workers` of tests/test_cli_upgrade.py, which also holds `lib`, `run_json` and
`untouched`). The text pages are pinned by `tests/cli_golden/{batch_resume,batch_undo}.txt`. The schema step has its tests in
tests/test_db.py (`version_9`)."""
from __future__ import annotations

import re

import pytest

from batch_helpers import needs_ffmpeg
from discjockey import batches, db, library
from discjockey.hub import api as api_words, catalog, views
from discjockey.hub.api import CliApi, HubApi
from discjockey.rekordbox import process
from test_cli_upgrade import (  # noqa: F401 - the fixtures and helpers of the other command tests
    NEEDS_PERSON, NEW, OK, PARTIAL, REFUSED, SAME, STOP, batches_of, inline_workers, lib, run, run_json, untouched)

pytestmark = needs_ffmpeg

BAD_ARGS, BUSY, STOPPED = 2, 3, 5


def stopped_batch(found, capsys, monkeypatch, tracks=None) -> str:
    """A stopped batch of `tracks`: rekordbox opened before the first one, so every item is still planned."""
    monkeypatch.setattr(process, "running", lambda: True)
    code, env = run_json(["upgrade", "apply", *(tracks or found.tracks), *SAME], capsys)
    assert (code, env["reason"]) == (NEEDS_PERSON, "rekordbox_open"), env
    monkeypatch.setattr(process, "running", lambda: False)
    return env["person_steps"][0]["then"].removeprefix("batch resume ")


# --- batch resume ---

def test_a_stopped_batch_resumes_its_planned_items_and_names_what_is_left_to_do(lib, capsys, monkeypatch):
    found = lib(["mp3", "mp3", "mp3"])
    STOP["after"] = 1
    code, env = run_json(["upgrade", "apply", "--all"], capsys)
    assert (code, env["reason"]) == (STOPPED, "stop")
    assert [r["state"] for r in env["data"]["results"]] == ["done", "planned", "planned"]
    STOP["after"], STOP["seen"] = None, 0
    code, env = run_json(["batch", "resume", "aiff:1"], capsys)
    assert (code, env["outcome"], env["job"] is not None) == (OK, "ok", True), env
    data = env["data"]
    assert (data["batch_id"], data["state"], data["total"], data["done"]) == ("aiff:1", "done", 3, 3)
    assert [r["state"] for r in data["results"]] == ["done"] * 3
    assert env["message"] == "3 of 3 songs done."
    assert [n["run"] for n in env["next"]] == ["batch show aiff:1", "check list"]
    [step] = [s for s in env["person_steps"] if s["id"] == "step:reload_tag"]
    assert step["then"] == "check done --batch aiff:1"
    assert all(found.entry(i)["path"].endswith(f"Song {i}.aiff") for i in range(3))
    assert [(b.id, b.state) for b in batches_of(found)] == [(1, "done")]  # the same batch, not a second one


def test_resume_after_rekordbox_quit_runs_the_whole_stopped_batch(lib, capsys, monkeypatch):
    found = lib(["mp3", "aiff"])
    batch = stopped_batch(found, capsys, monkeypatch)
    assert batch == "aiff:1"
    code, env = run_json(["batch", "resume", batch], capsys)
    assert (code, env["outcome"], env["data"]["done"]) == (OK, "ok", 2), env
    assert batches_of(found)[0].state == "done" and found.entry(0)["path"].endswith("Song 0.aiff")


def test_resume_with_rekordbox_still_open_needs_the_person_and_keeps_the_batch_stopped(lib, capsys, monkeypatch):
    found = lib(["mp3", "mp3_plain"])
    stopped_batch(found, capsys, monkeypatch)
    monkeypatch.setattr(process, "running", lambda: True)
    before = untouched(found)
    code, env = run_json(["batch", "resume", "aiff:1"], capsys)
    assert (code, env["outcome"], env["reason"]) == (NEEDS_PERSON, "needs_person", "rekordbox_open")
    assert [(s["id"], s["then"]) for s in env["person_steps"]] == [("step:quit_rekordbox", "batch resume aiff:1")]
    assert untouched(found) == before and batches_of(found)[0].state == "stopped"


def test_resume_of_a_batch_that_is_not_stopped_is_refused_with_the_windows_words(lib, capsys):
    found = lib(["mp3"])
    assert run_json(["upgrade", "apply", found.tracks[0], *SAME], capsys)[0] == OK
    before = untouched(found)
    code, env = run_json(["batch", "resume", "aiff:1"], capsys)
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "not_stopped")
    assert env["message"] == api_words.NOT_STOPPED
    assert untouched(found) == before


def test_resume_takes_a_typed_aiff_id_only_and_an_unknown_one_is_bad_args(lib, capsys):
    lib(["mp3"])
    for text, reason in (("1", "bad_id_kind"), ("moves:1", "bad_id_kind"), ("aiff:99", "unknown_id")):
        code, env = run_json(["batch", "resume", text], capsys)
        assert (code, env["outcome"], env["reason"]) == (BAD_ARGS, "bad_args", reason), text
    code, env = run_json(["batch", "resume"], capsys)
    assert (code, env["outcome"]) == (BAD_ARGS, "bad_args") and "BATCH_ID" in env["message"]


def test_resume_while_the_library_lock_is_held_is_busy_and_changes_nothing(lib, capsys, monkeypatch):
    found = lib(["mp3", "mp3_plain"])
    stopped_batch(found, capsys, monkeypatch)
    before = untouched(found)
    with library.run_lock(found.paths.lock):
        code, env = run_json(["batch", "resume", "aiff:1"], capsys)
    assert (code, env["outcome"]) == (BUSY, "busy")
    assert untouched(found) == before


def test_stop_during_a_resume_is_exit_5_and_the_batch_can_be_resumed_again(lib, capsys, monkeypatch):
    found = lib(["mp3", "mp3", "mp3"])
    stopped_batch(found, capsys, monkeypatch)
    STOP["after"], STOP["seen"] = 1, 0
    code, env = run_json(["batch", "resume", "aiff:1"], capsys)
    assert (code, env["outcome"], env["reason"]) == (STOPPED, "stopped", "stop")
    assert [r["state"] for r in env["data"]["results"]] == ["done", "planned", "planned"]
    STOP["after"] = None
    code, env = run_json(["batch", "resume", "aiff:1"], capsys)
    assert (code, env["outcome"], env["data"]["done"]) == (OK, "ok", 3)


def test_a_resume_that_skips_an_item_is_partial_and_names_it(lib, capsys, monkeypatch):
    found = lib(["mp3", "mp3", "mp3"])
    batch = stopped_batch(found, capsys, monkeypatch)
    found.paths.root.joinpath(found.olds[1]).unlink()  # the file of the second song is gone: its item is skipped
    code, env = run_json(["batch", "resume", batch], capsys)
    assert (code, env["outcome"]) == (PARTIAL, "partial")
    assert [r["state"] for r in env["data"]["results"]] == ["done", "skipped", "done"]


# --- batch undo ---

def done_batch(found, capsys, tracks=None) -> None:
    code, env = run_json(["upgrade", "apply", *(tracks or found.tracks), *SAME], capsys)
    assert code == OK, env


def test_undo_without_yes_is_refused_with_the_dry_run_and_changes_nothing(lib, capsys):
    found = lib(["mp3", "mp3"])
    done_batch(found, capsys)
    before = untouched(found)
    code, env = run_json(["batch", "undo", "aiff:1"], capsys)
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "needs_yes")
    assert env["message"] == catalog.CONFIRM["batch undo"] and env["job"] is None
    data = env["data"]
    assert (data["batch"], data["total"], data["planned"], data["skipped"]) == ("aiff:1", 2, 2, 0)
    assert "plan_id" not in data
    assert untouched(found) == before


def test_undo_puts_back_every_track_newest_first_and_says_how_many(lib, capsys):
    found = lib(["mp3", "mp3"])
    original = [(found.paths.root / p).read_bytes() for p in found.olds]
    done_batch(found, capsys)
    code, env = run_json(["batch", "undo", "aiff:1", "--yes"], capsys)
    assert (code, env["outcome"], env["message"]) == (OK, "ok", "2 of 2 tracks undone."), env
    data = env["data"]
    assert (data["total"], data["undone"], data["refused"], data["failed"]) == (2, 2, 0, 0)
    assert [r["track"] for r in data["results"]] == [found.tracks[1], found.tracks[0]]  # newest first
    assert [(found.paths.root / p).read_bytes() for p in found.olds] == original
    assert found.entry(0)["path"] == found.olds[0] and found.entry(0)["upgrade"]
    assert env["next"] == [{"run": "upgrade list", "why": "the better versions wait there again"}]
    assert [i.state for i in found.batch(1).items] == ["undone", "undone"]
    code, env = run_json(["batch", "undo", "aiff:1", "--yes"], capsys)  # nothing left to put back
    assert (code, env["outcome"], env["data"]["total"]) == (OK, "ok", 0)


def test_undo_with_rekordbox_open_undoes_nothing_and_needs_the_person(lib, capsys, monkeypatch):
    found = lib(["mp3", "mp3"])
    done_batch(found, capsys)
    monkeypatch.setattr(process, "running", lambda: True)
    before = untouched(found)
    code, env = run_json(["batch", "undo", "aiff:1", "--yes"], capsys)
    assert (code, env["outcome"], env["reason"]) == (NEEDS_PERSON, "needs_person", "rekordbox_open") and code == 4
    assert [(s["id"], s["then"]) for s in env["person_steps"]] == [("step:quit_rekordbox", "the same command")]
    assert [r["state"] for r in env["data"]["results"]] == ["waiting", "waiting"]
    assert untouched(found) == before
    monkeypatch.setattr(process, "running", lambda: False)  # the same command, once rekordbox is quit
    assert run_json(["batch", "undo", "aiff:1", "--yes"], capsys)[0] == OK


def test_undo_dry_run_says_per_item_whether_it_can_be_undone_and_why_not(lib, capsys, monkeypatch):
    found = lib(["mp3", "mp3", "mp3"])
    done_batch(found, capsys)
    assert run_json(["check", "done", found.tracks[0]], capsys)[0] == OK  # ends the undo of the first
    monkeypatch.setattr(process, "running", lambda: True)
    before = untouched(found)
    code, env = run_json(["batch", "undo", "aiff:1", "--dry-run"], capsys)
    assert (code, env["outcome"]) == (OK, "ok")
    data = env["data"]
    assert [r["key"] for r in data["items"]] == [found.tracks[2], found.tracks[1], found.tracks[0]]  # newest first
    rows = {r["key"]: r for r in data["items"]}
    assert (rows[found.tracks[0]]["state"], rows[found.tracks[0]]["reason"]) == ("skipped", "nothing_to_undo")
    assert rows[found.tracks[0]]["message"] == api_words.batches.upgrades.UNDO_BLOCKED["nothing_to_undo"]
    for key in found.tracks[1:]:
        assert (rows[key]["state"], rows[key]["reason"], rows[key]["step"]) == ("planned", None, "convert")
    assert (data["batch"], data["total"], data["planned"], data["skipped"]) == ("aiff:1", 3, 2, 1)
    assert data["rekordbox"] == {"running": True, "needs_rekordbox_closed": True}
    assert "plan_id" not in data and untouched(found) == before


def test_undo_of_a_mix_is_partial_with_the_refused_track_in_the_results(lib, capsys):
    found = lib(["mp3", "mp3"])
    done_batch(found, capsys)
    assert run_json(["check", "done", found.tracks[0]], capsys)[0] == OK
    code, env = run_json(["batch", "undo", "aiff:1", "--yes"], capsys)
    assert (code, env["outcome"], env["message"]) == (PARTIAL, "partial", "1 of 2 tracks undone."), env
    states = {r["track"]: r["state"] for r in env["data"]["results"]}
    assert states == {found.tracks[1]: "undone", found.tracks[0]: "refused"}


def test_undo_takes_a_typed_aiff_id_only_and_the_move_batch_form_is_not_built_yet(lib, capsys):
    lib(["mp3"])
    for text, reason in (("1", "bad_id_kind"), ("moves:1", "bad_id_kind"), ("aiff:99", "unknown_id")):
        for flag in ("--yes", "--dry-run"):
            code, env = run_json(["batch", "undo", text, flag], capsys)
            assert (code, env["outcome"], env["reason"]) == (BAD_ARGS, "bad_args", reason), (text, flag)


def test_undo_while_the_library_lock_is_held_is_busy_and_a_dry_run_still_answers(lib, capsys):
    found = lib(["mp3"])
    done_batch(found, capsys)
    before = untouched(found)
    with library.run_lock(found.paths.lock):
        code, env = run_json(["batch", "undo", "aiff:1", "--yes"], capsys)
        assert (code, env["outcome"]) == (BUSY, "busy")
        code, env = run_json(["batch", "undo", "aiff:1", "--dry-run"], capsys)
        assert (code, env["outcome"]) == (OK, "ok")
    assert untouched(found) == before


def test_resume_and_undo_with_no_music_folder_are_refused(tmp_path, monkeypatch, capsys, inline_workers):
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(tmp_path / "empty-support"))
    for argv in (["batch", "resume", "aiff:1"], ["batch", "undo", "aiff:1", "--yes"],
                 ["batch", "undo", "aiff:1", "--dry-run"]):
        code, env = run_json(argv, capsys)
        assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "no_library"), argv


def test_the_windows_batch_methods_still_take_the_integer_the_window_sends(lib):
    import hub_helpers
    found = lib(["mp3"])
    api, rec = hub_helpers.make_api(found.paths)
    assert api.batch_resume(99)["kind"] == "refused" and api.batch_undo(True)["kind"] == "refused"
    assert not hasattr(api, "batch_undo_preview")  # the command line's dry run is not the window's
    assert hasattr(CliApi, "batch_undo_preview") and not hasattr(HubApi, "batch_undo_preview")


# --- via and scope ---

def test_a_batch_a_command_starts_says_terminal_and_the_scope_of_its_selection(lib, capsys):
    found = lib(["mp3", "mp3", "mp3"])
    assert run_json(["upgrade", "apply", found.tracks[0], *SAME], capsys)[0] == OK
    assert run_json(["upgrade", "apply", "--all"], capsys)[0] == OK
    named, every = sorted(batches_of(found), key=lambda b: b.id)
    assert (named.via, named.scope, named.started_by) == ("terminal", "selection", "user")
    assert (every.via, every.scope, every.started_by) == ("terminal", None, "upgrade_all")  # upgrade_all names no scope
    code, env = run_json(["batch", "list"], capsys)
    assert {(r["id"], r["via"], r["scope"]) for r in env["data"]["batches"]} == {
        ("aiff:1", "terminal", "selection"), ("aiff:2", "terminal", None)}
    code, env = run_json(["batch", "show", "aiff:1"], capsys)
    assert (env["data"]["via"], env["data"]["scope"]) == ("terminal", "selection")


def test_a_batch_the_window_starts_says_window(lib):
    import hub_helpers
    found = lib(["mp3", "mp3"])
    api, rec = hub_helpers.make_api(found.paths, compare=lambda a, b: __import__("convert_helpers").EXACT)
    assert hub_helpers.wait_job(api, rec, api.upgrade([found.tracks[0]], "same_track")).ok
    assert hub_helpers.wait_job(api, rec, api.upgrade_all()).ok
    assert [(b.via, b.started_by) for b in sorted(batches_of(found), key=lambda b: b.id)] == [
        ("window", "user"), ("window", "upgrade_all")]


def test_a_convert_selection_is_selection_from_a_command_and_origin_selection_from_the_window(lib, monkeypatch):
    import hub_helpers
    found = lib(["mp3"])
    scopes = []

    def spy(self, scope, *, only, started_by, batch_scope):
        scopes.append((self._via, batch_scope))
        return lambda ctx: {}  # no batch: only the scope the api would record is looked at
    monkeypatch.setattr(HubApi, "_aiff_work", spy)
    window, rec = hub_helpers.make_api(found.paths)
    terminal = CliApi(found.paths.support, rec, hub_helpers.services())
    hub_helpers._MADE.append(terminal)
    terminal._attach(found.paths)
    terminal._jobs.keep_awake = hub_helpers._no_awake
    for api in (window, terminal):
        assert hub_helpers.wait_job(api, rec, api.convert(found.tracks, "todo")).ok
    assert scopes == [("window", "todo:selection"), ("terminal", "selection")]


def test_the_windows_resume_link_shows_a_stopped_terminal_batch_of_a_library_view(lib, capsys):
    import hub_helpers
    found = lib(["mp3", "mp3"])
    items = [(t, "convert") for t in found.tracks]
    batch = batches.start(found.paths, items, started_by="make_aiff", scope="library:playlist:House", via="terminal")
    with db.connect(found.paths.db_file) as conn:
        db.set_aiff_batch(conn, batch, state="stopped", stop_reason="rekordbox_open")
    api, rec = hub_helpers.make_api(found.paths)
    assert api.library()["aiff_stopped"] == {"batch_id": batch, "left": 2}  # the window lists the terminal's batch
    with db.connect(found.paths.db_file) as conn:
        rows = db.aiff_batches(conn)[0]
    assert views.stopped_batch(rows, scope="library:") == (batch, 2)
    assert views.stopped_batch(rows, scope="todo:") is None  # another place's batch is not this one's
    code, env = run_json(["batch", "list"], capsys)
    assert [(r["id"], r["via"], r["scope"], r["state"]) for r in env["data"]["batches"]] == [
        (f"aiff:{batch}", "terminal", "library:playlist:House", "stopped")]


# --- the text pages ---

def unstamped(text: str, tmp_path) -> str:
    """A page as the golden keeps it: no temp folder, no backup's time stamp."""
    return re.sub(r"\d{8}T\d{6}Z", "<backup>", text.replace(str(tmp_path), "<tmp>"))


def test_golden_the_pages_of_a_resume_and_an_undo(lib, capsys, tmp_path, monkeypatch):
    from test_cli_golden import WRITES, check_golden
    found = lib(["mp3", "aiff"])
    stopped_batch(found, capsys, monkeypatch)
    code, out, err = run(["batch", "resume", "aiff:1"], capsys)
    assert code == OK and "batch_resume" in WRITES
    check_golden("batch_resume", unstamped(out, tmp_path))
    assert "Your turn: " in err and "Then: check done --batch aiff:1" in err
    code, out, err = run(["batch", "undo", "aiff:1", "--yes"], capsys)
    assert code == OK and "batch_undo" in WRITES
    check_golden("batch_undo", unstamped(out, tmp_path))
