"""Group V1.12 (issue 39, design §5.2, §6.6, §7.4): `batch resume aiff:<n>` and `batch undo aiff:<n> --yes [--dry-run]`
(part a) and `rekordbox backups` and `rekordbox restore <backup> --yes [--dry-run]` (part b) through the command line, end
to end, on a fixture library and a fixture rekordbox (`batch_helpers.make_lib`), the two facts a batch records since schema
10 (where it started, `via`, and its real scope), the engine behaviour the deleted `batch_cmd` / `upgrades_cmd` tests pinned
that no other test did, and the removal of those modules and their words.

A job's worker runs in this process (`inline_workers` of tests/test_cli_upgrade.py, which also holds `lib`, `run_json` and
`untouched`). The text pages are pinned by `tests/cli_golden/{batch_resume,batch_undo}.txt`. The schema step has its tests in
tests/test_db.py (`version_9`)."""
from __future__ import annotations

import json
import re

import pytest

from batch_helpers import needs_ffmpeg
from discjockey import batches, db, library, words
from discjockey.hub import api as api_words, catalog, views
from discjockey.hub.api import CliApi, HubApi
from discjockey.rekordbox import backup as rbbackup, lock as rb_lock, process
from discjockey.rekordbox import session as rbsession
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


def test_resume_of_a_batch_a_crash_left_running_recovers_it_and_finishes_it(lib, capsys, monkeypatch):
    found = lib(["mp3", "aiff"])
    stopped_batch(found, capsys, monkeypatch)
    with db.connect(found.paths.db_file) as conn:  # the process died mid-batch: the row still says running
        db.set_aiff_batch(conn, 1, state="running", stop_reason=None)
    assert batches_of(found)[0].state == "running"
    with library.run_lock(found.paths.lock):  # one that really runs in another process is busy, not "not stopped"
        code, env = run_json(["batch", "resume", "aiff:1"], capsys)
        assert (code, env["outcome"]) == (BUSY, "busy"), env
    code, env = run_json(["batch", "resume", "aiff:1"], capsys)
    assert (code, env["outcome"], env["data"]["done"]) == (OK, "ok", 2), env
    assert batches_of(found)[0].state == "done"
    code, env = run_json(["batch", "resume", "aiff:1"], capsys)  # now it has ended: nothing to resume
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "not_stopped")


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


def later_batch_did(found, track: str) -> int:
    """A later batch that also did `track` (its item `done`), as a second pass over one song leaves it."""
    batch = batches.start(found.paths, [(track, "same_track")], via="terminal")
    with db.connect(found.paths.db_file) as conn:
        db.set_aiff_item(conn, batch, 0, "done")
    return batch


def test_undo_of_a_batch_leaves_a_track_a_later_batch_did_again_and_names_that_batch(lib, capsys):
    found = lib(["mp3", "mp3"])
    done_batch(found, capsys)
    later = later_batch_did(found, found.tracks[0])
    before = untouched(found)
    code, env = run_json(["batch", "undo", "aiff:1", "--dry-run"], capsys)
    assert (code, env["outcome"]) == (OK, "ok")
    rows = {r["key"]: r for r in env["data"]["items"]}
    assert (rows[found.tracks[0]]["state"], rows[found.tracks[0]]["reason"]) == ("skipped", "newer_batch")
    assert rows[found.tracks[0]]["message"] == batches.NEWER_BATCH.format(later=f"aiff:{later}")
    assert (rows[found.tracks[1]]["state"], rows[found.tracks[1]]["reason"]) == ("planned", None)
    assert (env["data"]["planned"], env["data"]["skipped"]) == (1, 1) and untouched(found) == before
    code, env = run_json(["batch", "undo", "aiff:1", "--yes"], capsys)
    assert (code, env["outcome"], env["message"]) == (PARTIAL, "partial", "1 of 2 tracks undone."), env
    states = {r["track"]: (r["state"], r["reason"]) for r in env["data"]["results"]}
    assert states == {found.tracks[1]: ("undone", None), found.tracks[0]: ("refused", "newer_batch")}
    assert found.entry(0)["path"] != found.olds[0]  # the track the later batch changed was not put back
    assert [i.state for i in found.batch(1).items] == ["done", "undone"]
    assert [i.state for i in found.batch(later).items] == ["done"]
    with db.connect(found.paths.db_file) as conn:  # once the later batch is undone, the earlier one's turn comes
        db.set_aiff_item(conn, later, 0, "undone")
    code, env = run_json(["batch", "undo", "aiff:1", "--yes"], capsys)
    assert (code, env["outcome"], env["data"]["undone"]) == (OK, "ok", 1), env
    assert found.entry(0)["path"] == found.olds[0] and [i.state for i in found.batch(1).items] == ["undone"] * 2


def test_undo_dry_run_only_reads_library_db(lib, capsys, monkeypatch):
    found = lib(["mp3", "mp3"])
    done_batch(found, capsys)
    real = db.connect

    def read_only_only(path, *, read_only=False, **kw):
        assert read_only, "a dry run opened library.db read-write"
        return real(path, read_only=True, **kw)
    before = untouched(found)
    with monkeypatch.context() as m:
        m.setattr(db, "connect", read_only_only)
        code, env = run_json(["batch", "undo", "aiff:1", "--dry-run"], capsys)
    assert (code, env["outcome"], env["data"]["planned"]) == (OK, "ok", 2), env
    assert untouched(found) == before


def test_undo_of_a_mix_is_partial_with_the_refused_track_in_the_results(lib, capsys):
    found = lib(["mp3", "mp3"])
    done_batch(found, capsys)
    assert run_json(["check", "done", found.tracks[0]], capsys)[0] == OK
    code, env = run_json(["batch", "undo", "aiff:1", "--yes"], capsys)
    assert (code, env["outcome"], env["message"]) == (PARTIAL, "partial", "1 of 2 tracks undone."), env
    states = {r["track"]: r["state"] for r in env["data"]["results"]}
    assert states == {found.tracks[1]: "undone", found.tracks[0]: "refused"}


def test_stop_during_a_batch_undo_is_exit_5_with_the_rest_waiting_and_a_second_undo_finishes(lib, capsys, monkeypatch):
    from discjockey import upgrades
    from discjockey.cli import bind
    found = lib(["mp3", "mp3", "mp3"])
    done_batch(found, capsys)
    started, real_headless, real_undo = [], bind.headless, upgrades.undo

    def headless(resolved, **kw):
        api = real_headless(resolved, **kw)
        started.append(api)
        return api

    def undo_then_stop(*args, **kw):  # Ctrl-C arrives while the first track is being put back
        done = real_undo(*args, **kw)
        started[-1]._jobs.inline_token.cancel()
        return done
    monkeypatch.setattr(bind, "headless", headless)
    monkeypatch.setattr(upgrades, "undo", undo_then_stop)
    code, env = run_json(["batch", "undo", "aiff:1", "--yes"], capsys)
    assert (code, env["outcome"], env["reason"]) == (STOPPED, "stopped", "stop"), env
    assert [r["state"] for r in env["data"]["results"]] == ["undone", "waiting", "waiting"]
    assert [i.state for i in found.batch(1).items] == ["done", "done", "undone"]  # what was undone stays undone
    monkeypatch.setattr(upgrades, "undo", real_undo)
    code, env = run_json(["batch", "undo", "aiff:1", "--yes"], capsys)
    assert (code, env["outcome"], env["data"]["undone"]) == (OK, "ok", 2), env
    assert [i.state for i in found.batch(1).items] == ["undone"] * 3


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

    def spy(self, scope, *, only, started_by, batch_scope, **plan):
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
    return re.sub(r"\d{8}T\d{6}Z(?:-\d+)?", "<backup>", text.replace(str(tmp_path), "<tmp>"))


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


# --- rekordbox backups and rekordbox restore (part b) ---

def with_backup(found, capsys, tracks=None) -> tuple[str, dict]:
    """A done batch of `tracks` (default: every song): the backup it made and its answer."""
    code, env = run_json(["upgrade", "apply", *(tracks or found.tracks), *SAME], capsys)
    assert code == OK, env
    return env["data"]["backup"], env["data"]


def kept(found):
    """Everything a restore could change: the music files, rekordbox's library, the records, the batches, the backups."""
    return untouched(found), rbbackup.backups(found.paths)


def test_backups_lists_the_copies_newest_first_with_the_batches_that_wrote_under_them(lib, capsys):
    found = lib(["mp3", "mp3"])
    code, env = run_json(["rekordbox", "backups"], capsys)
    assert (code, env["outcome"], env["data"]) == (OK, "ok", {"backups": []})
    backup, applied = with_backup(found, capsys)
    code, env = run_json(["rekordbox", "backups"], capsys)
    [only] = env["data"]["backups"]
    assert (code, env["outcome"]) == (OK, "ok") and set(only) == {"id", "created", "batches", "tracks", "size"}
    assert only["id"] == backup and only["batches"] == [applied["batch"]] and only["tracks"] == 2 and only["size"] > 0
    code, out, _ = run(["rekordbox", "backups"], capsys)
    assert backup in out and "Batches" in out


def test_backups_and_restore_dry_run_read_while_a_job_holds_the_library_and_rekordbox(lib, capsys):
    """Reads do not wait for a running job: the library lock and a rekordbox writer do not stop them."""
    found = lib(["mp3"])
    backup, _ = with_backup(found, capsys)
    with library.run_lock(found.paths.lock), rbsession.writer_lock(found.paths.support):
        for argv in (["rekordbox", "backups"], ["batch", "list"], ["batch", "show", "aiff:1"],
                     ["rekordbox", "restore", backup, "--dry-run"]):
            assert run_json(argv, capsys)[0] == OK, argv


def test_restore_without_yes_is_refused_with_what_it_would_leave_missing_and_changes_nothing(lib, capsys):
    found = lib(["mp3", "mp3"])
    backup, _ = with_backup(found, capsys)
    before = kept(found)
    code, env = run_json(["rekordbox", "restore", backup], capsys)
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "needs_yes") and env["job"] is None
    assert env["message"] == catalog.CONFIRM["rekordbox restore"]
    assert [m["id"] for m in env["data"]["missing_after"]] == ["1", "2"] and "saved_current" not in env["data"]
    assert kept(found) == before


def test_restore_dry_run_lists_the_missing_files_and_changes_and_saves_nothing(lib, capsys, monkeypatch):
    found = lib(["mp3", "mp3"])
    backup, _ = with_backup(found, capsys)
    monkeypatch.setattr(process, "running", lambda: True)  # a preview is not a restore: rekordbox may be open
    before = kept(found)
    code, env = run_json(["rekordbox", "restore", backup, "--dry-run"], capsys)
    assert (code, env["outcome"]) == (OK, "ok")
    data = env["data"]
    assert set(data) == {"backup", "missing_after", "rekordbox"}
    assert data["backup"] == backup and data["rekordbox"] == {"running": True, "needs_rekordbox_closed": True}
    assert [(m["id"], set(m)) for m in data["missing_after"]] == [("1", {"id", "path", "was"}),
                                                                  ("2", {"id", "path", "was"})]
    assert "saved_current" not in data and kept(found) == before
    assert not (found.paths.support / "plans").exists()  # a list of tracks is no plan to run


def test_restore_dry_run_takes_no_writer_lock_and_says_writing_while_a_writer_holds_it(lib, capsys):
    found = lib(["mp3"])
    backup, _ = with_backup(found, capsys)
    before = kept(found)
    with rbsession.writer_lock(found.paths.support):
        code, env = run_json(["rekordbox", "restore", backup, "--dry-run"], capsys)
    assert (code, env["outcome"]) == (OK, "ok")
    assert env["data"]["missing_after"] is None and env["data"]["rekordbox"]["writing"] is True  # master.db was not opened
    assert kept(found) == before
    code, env = run_json(["rekordbox", "restore", backup, "--dry-run"], capsys)
    assert env["data"]["missing_after"] and "writing" not in env["data"]["rekordbox"]


def test_restore_dry_run_opens_the_live_library_shared_while_rekordbox_runs_with_wal_and_shm(lib, capsys, monkeypatch):
    found = lib(["mp3", "mp3"])
    backup, _ = with_backup(found, capsys)
    code, closed = run_json(["rekordbox", "restore", backup, "--dry-run"], capsys)
    assert code == OK and closed["data"]["missing_after"]
    for suffix in ("-wal", "-shm"):  # rekordbox is open: its journal files are beside the library
        found.place.db.with_name(found.place.db.name + suffix).write_bytes(b"")
    opened = []
    real = rbbackup.master.connect

    def watching(db, key, *, immutable=True, **kw):
        opened.append((db.name, immutable))
        return real(db, key, immutable=immutable, **kw)
    monkeypatch.setattr(rbbackup.master, "connect", watching)
    monkeypatch.setattr(process, "running", lambda: True)
    code, env = run_json(["rekordbox", "restore", backup, "--dry-run"], capsys)
    assert (code, env["outcome"]) == (OK, "ok")
    assert env["data"]["missing_after"] == closed["data"]["missing_after"]
    assert ("master.db", False) in opened  # the live library, shared: a live writer's pages are not read as immutable


def test_restore_dry_run_of_a_library_that_cannot_be_read_says_unreadable_not_crashed(lib, capsys):
    found = lib(["mp3"])
    backup, _ = with_backup(found, capsys)
    found.place.db.write_bytes(b"this is not a database" * 100)  # the repair case: restore is what fixes it
    code, env = run_json(["rekordbox", "restore", backup, "--dry-run"], capsys)
    assert (code, env["outcome"]) == (OK, "ok"), env
    assert env["data"]["missing_after"] is None and env["data"]["rekordbox"]["unreadable"] is True


def test_a_query_that_fails_on_the_library_is_unreadable_too(lib, monkeypatch):
    found = lib(["mp3"])

    class Broken:
        def execute(self, *a):
            raise rbbackup.master.sqlcipher3.DatabaseError("file is not a database")

        def close(self):
            pass
    monkeypatch.setattr(rbbackup.master, "connect", lambda *a, **kw: Broken())
    assert rbbackup._paths_of(found.place.db) is None
    assert rbbackup._missing_after(found.place.db, found.place.db) is None


def test_a_dry_run_makes_no_lock_file_and_a_restore_holds_it_only_while_it_runs(tmp_path, monkeypatch, lib, capsys):
    found = lib(["mp3"])
    with rbbackup.master.open_read(found.place, False) as m:  # a backup that names its library: restore may put it back
        dbid = m.dbid
    backup = rbbackup.Backup.ensure(found.paths, found.place, dbid=dbid, batch_id=None, tracks=[])
    backup.close(found.place)
    assert not (found.paths.support / rb_lock.LOCK_NAME).exists()
    assert run_json(["rekordbox", "restore", backup.id, "--dry-run"], capsys)[0] == OK
    assert not (found.paths.support / rb_lock.LOCK_NAME).exists()  # a reader never makes the file
    with rb_lock.writer_lock(found.paths.support):
        pass  # the restore's own hold ends with it: the next writer is not busy
    assert run_json(["rekordbox", "restore", backup.id, "--yes"], capsys)[0] == OK


def test_restore_puts_rekordbox_back_saves_the_current_library_and_lists_the_missing_files(lib, capsys):
    found = lib(["mp3", "mp3"])
    rb_before = found.dump()
    backup, _ = with_backup(found, capsys)
    assert found.dump() != rb_before
    current = rbbackup.sha256_file(found.place.db)  # the library as it is before the restore
    code, env = run_json(["rekordbox", "restore", backup, "--yes"], capsys)
    assert (code, env["outcome"], env["job"] is not None) == (OK, "ok", True), env
    data = env["data"]
    assert data["restored"] == backup and found.dump() == rb_before
    assert data["saved_current"] in [b.id for b in rbbackup.backups(found.paths)] and data["saved_current"] != backup
    saved_copy = rbbackup.backups_dir(found.paths) / data["saved_current"] / "master.db"
    assert rbbackup.sha256_file(saved_copy) == current  # the saved copy is the library that was replaced, byte for byte
    assert rbbackup.sha256_file(found.place.db) != current
    assert [m["id"] for m in data["missing_after"]] == ["1", "2"]
    assert all(set(m) == {"id", "path", "was"} for m in data["missing_after"])
    assert env["message"] == (words.RESTORED.format(backup=backup, saved=data["saved_current"]) + " "
                              + words.MISSING_AFTER.format(n=2))
    assert env["next"] == [{"run": "batch list", "why": "the batches to undo so these tracks find their files again"}]


def test_restore_reads_rekordbox_s_library_only_while_it_holds_rekordbox_lock_exclusively(lib, capsys, monkeypatch):
    import fcntl
    import os
    found = lib(["mp3"])
    backup, _ = with_backup(found, capsys)
    seen = []
    real = rbbackup._verified

    def watching(b, place, running):
        fd = os.open(found.paths.support / rb_lock.LOCK_NAME, os.O_RDWR)
        try:  # a second descriptor asks for the shared hold a reader takes: the restore's exclusive hold refuses it
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            seen.append("shared hold granted")
        except BlockingIOError:
            seen.append("refused")
        finally:
            os.close(fd)
        return real(b, place, running)
    monkeypatch.setattr(rbbackup, "_verified", watching)
    code, env = run_json(["rekordbox", "restore", backup, "--yes"], capsys)
    assert (code, env["outcome"]) == (OK, "ok") and seen == ["refused"], (env, seen)


def test_a_restore_after_the_batches_were_undone_leaves_no_file_missing(lib, capsys):
    found = lib(["mp3"])
    backup, applied = with_backup(found, capsys)
    assert run_json(["batch", "undo", f"aiff:{applied['batch']}", "--yes"], capsys)[0] == OK  # the files are back first
    code, env = run_json(["rekordbox", "restore", backup, "--yes"], capsys)
    assert code == OK and env["data"]["missing_after"] == [] and env["next"] == []
    assert env["message"] == words.RESTORED.format(backup=backup, saved=env["data"]["saved_current"])


def test_restore_with_rekordbox_open_needs_the_person_and_changes_nothing(lib, capsys, monkeypatch):
    found = lib(["mp3", "mp3"])
    backup, _ = with_backup(found, capsys)
    monkeypatch.setattr(process, "running", lambda: True)
    before = kept(found)
    code, env = run_json(["rekordbox", "restore", backup, "--yes"], capsys)
    assert (code, env["outcome"], env["reason"]) == (NEEDS_PERSON, "needs_person", "rekordbox_open") and code == 4
    assert [(s["id"], s["then"]) for s in env["person_steps"]] == [("step:quit_rekordbox", "the same command")]
    assert env["message"] == words.RESTORE_REFUSED["rekordbox_open"] and kept(found) == before
    monkeypatch.setattr(process, "running", lambda: False)  # the same command, once rekordbox is quit
    assert run_json(["rekordbox", "restore", backup, "--yes"], capsys)[0] == OK


def test_restore_refuses_what_it_cannot_do_with_the_engines_words_and_changes_nothing(lib, capsys, monkeypatch, tmp_path):
    import json
    found = lib(["mp3"])
    backup, _ = with_backup(found, capsys)
    before = kept(found)
    folder = rbbackup.backups_dir(found.paths) / backup
    manifest = json.loads((folder / "manifest.json").read_text())
    for why, change in (("other_library", lambda: (folder / "manifest.json").write_text(
                            json.dumps({**manifest, "dbid": "the-dbid-of-another-library"}))),
                        ("damaged", lambda: (folder / "master.db").write_bytes(b"not rekordbox's library"))):
        change()
        code, env = run_json(["rekordbox", "restore", backup, "--yes"], capsys)
        assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "refused"), why
        assert env["data"]["why"] == why and env["message"] == words.RESTORE_REFUSED[why]
        code, env = run_json(["rekordbox", "restore", backup, "--dry-run"], capsys)  # the dry run refuses the same
        assert (code, env["outcome"], env["data"]["why"]) == (REFUSED, "refused", why)
        (folder / "manifest.json").write_text(json.dumps(manifest))
    assert [m for m in kept(found)[0][:2]] == [m for m in before[0][:2]]
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(tmp_path / "no-rekordbox-here"))
    for flag in ("--yes", "--dry-run"):
        code, env = run_json(["rekordbox", "restore", backup, flag], capsys)
        assert (code, env["outcome"], env["data"]["why"]) == (REFUSED, "refused", "no_rekordbox"), flag
        assert env["message"] == words.RESTORE_REFUSED["no_rekordbox"]
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(found.folder))
    assert untouched(found) == before[0]


def test_restore_of_a_backup_that_names_no_library_is_refused_when_this_one_can_be_read(lib, capsys):
    import json
    found = lib(["mp3"])
    backup, _ = with_backup(found, capsys)
    manifest_file = rbbackup.backups_dir(found.paths) / backup / "manifest.json"
    manifest = json.loads(manifest_file.read_text())
    manifest_file.write_text(json.dumps({**manifest, "dbid": None}))
    before = untouched(found)
    for flag in ("--yes", "--dry-run"):
        code, env = run_json(["rekordbox", "restore", backup, flag], capsys)
        assert (code, env["outcome"], env["data"]["why"]) == (REFUSED, "refused", "other_library"), flag
    assert untouched(found) == before


def test_restore_is_still_the_repair_for_a_library_that_cannot_be_read(lib, capsys):
    import json
    found = lib(["mp3"])
    backup, _ = with_backup(found, capsys)
    folder = rbbackup.backups_dir(found.paths) / backup
    manifest = json.loads((folder / "manifest.json").read_text())
    (folder / "manifest.json").write_text(json.dumps({**manifest, "dbid": None}))
    good = (folder / "master.db").read_bytes()
    found.place.db.write_bytes(b"damaged" * 1000)
    code, env = run_json(["rekordbox", "restore", backup, "--yes"], capsys)
    assert (code, env["outcome"]) == (OK, "ok"), env
    assert found.place.db.read_bytes() == good
    assert env["data"]["saved_current"] and env["data"]["missing_after"] == []


def test_restore_leftovers_beside_the_library_are_refused_as_unclean(lib, capsys):
    found = lib(["mp3"])
    backup, _ = with_backup(found, capsys)
    found.place.db.with_name("master.db-wal").write_bytes(b"")
    before = untouched(found)
    code, env = run_json(["rekordbox", "restore", backup, "--yes"], capsys)
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "unclean")
    assert env["message"] == words.RESTORE_REFUSED["unclean"] and untouched(found) == before
    assert env["data"]["why"] == "unclean"


def test_every_why_a_restore_can_be_refused_for_is_pinned_by_a_test(lib, capsys, monkeypatch):
    """`data.why` is the closed list agents read (`reason` is `refused` for most): the five that are `refused` are pinned
    here and by the tests of their own (`other_library`, `damaged`, `no_rekordbox`: ..._with_the_engines_words;
    `unclean`: ..._as_unclean); `rekordbox_open` is `needs_person` and `not_found` is `bad_args`."""
    assert set(words.RESTORE_REFUSED) == {"no_rekordbox", "not_found", "damaged", "other_library", "rekordbox_open",
                                          "unclean", "changed"}
    found = lib(["mp3"])
    backup, _ = with_backup(found, capsys)

    def stale(*a, **kw):
        raise rbbackup.WriteRefused("changed")
    monkeypatch.setattr(rbbackup, "_copy_checked", stale)  # rekordbox started in the gap between the check and the copy
    before = kept(found)
    code, env = run_json(["rekordbox", "restore", backup, "--yes"], capsys)
    assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "refused"), env
    assert env["data"]["why"] == "changed" and env["message"] == words.RESTORE_REFUSED["changed"]
    assert kept(found) == before


def test_restore_takes_a_backup_that_exists_and_an_unknown_name_is_bad_args(lib, capsys):
    found = lib(["mp3"])
    with_backup(found, capsys)
    before = kept(found)
    for flag in ("--yes", "--dry-run"):
        code, env = run_json(["rekordbox", "restore", "nope", flag], capsys)
        assert (code, env["outcome"], env["reason"]) == (BAD_ARGS, "bad_args", "unknown_id"), flag
        assert "rekordbox backups" in env["message"]
    code, env = run_json(["rekordbox", "restore"], capsys)
    assert (code, env["outcome"]) == (BAD_ARGS, "bad_args") and "BACKUP" in env["message"]
    assert kept(found) == before


def test_restore_while_another_writer_or_the_library_lock_is_held_is_busy_and_changes_nothing(lib, capsys):
    found = lib(["mp3"])
    backup, _ = with_backup(found, capsys)
    before = kept(found)
    with rbsession.writer_lock(found.paths.support):
        code, env = run_json(["rekordbox", "restore", backup, "--yes"], capsys)
        assert (code, env["outcome"], env["reason"]) == (BUSY, "busy", "rekordbox_lock")
    with library.run_lock(found.paths.lock):
        code, env = run_json(["rekordbox", "restore", backup, "--yes"], capsys)
        assert (code, env["outcome"]) == (BUSY, "busy")
    assert kept(found) == before


def test_backups_and_restore_with_no_music_folder_are_refused(tmp_path, monkeypatch, capsys, inline_workers):
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(tmp_path / "empty-support"))
    for argv in (["rekordbox", "backups"], ["rekordbox", "restore", "x", "--yes"],
                 ["rekordbox", "restore", "x", "--dry-run"]):
        code, env = run_json(argv, capsys)
        assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "no_library"), argv


def test_golden_the_page_of_a_restore(lib, capsys, tmp_path):
    from test_cli_golden import WRITES, check_golden
    found = lib(["mp3", "mp3"])
    backup, _ = with_backup(found, capsys)
    code, out, err = run(["rekordbox", "restore", backup, "--yes"], capsys)
    assert code == OK and "rekordbox_restore" in WRITES
    # the Path column is as wide as the temp folder: runs of spaces are squeezed, so the page is the same in any folder
    check_golden("rekordbox_restore", re.sub(r" {2,}", "  ", unstamped(out, tmp_path)))


# --- batches and the rekordbox lock (the old console tests that pinned engine behaviour, ported) ---

def test_a_batch_that_meets_the_rekordbox_lock_stays_stopped_and_resumes_after_it_is_free(lib, capsys):
    found = lib(["mp3", "aiff"])
    before = found.music(), found.dump()
    with rbsession.writer_lock(found.paths.support):
        code, env = run_json(["upgrade", "apply", "--all", *SAME], capsys)
        assert (code, env["outcome"], env["reason"]) == (BUSY, "busy", "rekordbox_lock"), env
        assert (env["data"]["batch_id"], env["data"]["state"]) == ("aiff:1", "stopped")  # the answer names the batch
        assert env["next"][0]["run"] == "batch resume aiff:1"
        [row] = run_json(["batch", "list"], capsys)[1]["data"]["batches"]  # the batch is there, stopped, nothing done
        assert (row["id"], row["state"], row["stop_reason"], row["done"], row["planned"]) == ("aiff:1", "stopped", "busy", 0, 2)
        code, env = run_json(["batch", "undo", "aiff:1", "--yes"], capsys)  # an undo writes rekordbox too
        assert (code, env["outcome"], env["reason"]) == (BUSY, "busy", "rekordbox_lock")
    assert (found.music(), found.dump()) == before
    code, env = run_json(["batch", "resume", "aiff:1"], capsys)
    assert (code, env["outcome"], env["data"]["done"]) == (OK, "ok", 2)


def test_wait_busy_does_not_retry_a_command_whose_busy_end_left_a_batch(lib, capsys):
    found = lib(["mp3", "aiff"])
    with rbsession.writer_lock(found.paths.support):
        code, env = run_json(["upgrade", "apply", "--all", *SAME, "--wait-busy", "30"], capsys)  # would wait 30 s if retried
    assert (code, env["outcome"], env["reason"]) == (BUSY, "busy", "rekordbox_lock"), env
    assert env["data"]["batch_id"] == "aiff:1" and env["next"][0]["run"] == "batch resume aiff:1"
    assert len(batches_of(found)) == 1  # no second batch, no `not_stopped` from a retry


def test_a_batch_of_one_that_meets_the_rekordbox_lock_is_closed_not_left_to_resume(lib, capsys):
    found = lib(["mp3", "aiff"])
    with rbsession.writer_lock(found.paths.support):
        code, env = run_json(["upgrade", "apply", found.tracks[0], *SAME], capsys)
        assert (code, env["outcome"], env["reason"]) == (BUSY, "busy", "rekordbox_lock")
        code, env = run_json(["batch", "show", "aiff:1"], capsys)
        assert (env["data"]["state"], env["data"]["done"]) == ("done", 0)  # closed: nothing to resume
        assert [(r["state"], r["reason"]) for r in env["data"]["results"]] == [("skipped", "busy")]
    assert all(b.state != "stopped" for b in batches_of(found))
    code, env = run_json(["upgrade", "apply", found.tracks[0], *SAME], capsys)  # the next try works
    assert (code, env["outcome"], env["data"]["done"]) == (OK, "ok", 1)


def test_a_batch_that_needs_no_rekordbox_write_runs_while_rekordbox_is_open(lib, capsys, monkeypatch):
    found = lib(["aiff", "mp3_free"])  # an own AIFF and a file rekordbox does not hold: no rekordbox write
    monkeypatch.setattr(process, "running", lambda: True)
    code, env = run_json(["upgrade", "apply", "--all", *SAME], capsys)
    assert (code, env["outcome"], env["data"]["done"]) == (OK, "ok", 2), env
    assert env["data"]["backup"] is None and rbbackup.backups(found.paths) == []


def test_undo_lists_a_track_whose_rekordbox_row_was_moved_since_and_refuses_when_nothing_is_left(lib, capsys):
    from rekordbox_helpers import KEYS, _open
    found = lib(["mp3", "mp3"])
    done_batch(found, capsys)
    con = _open(found.place.db, KEYS[0])  # the DJ relocated the first track in rekordbox
    con.execute("UPDATE djmdContent SET FolderPath = '/Users/dj/Music/Elsewhere.aiff' WHERE ID = '1'")
    con.commit()
    con.close()
    code, env = run_json(["batch", "undo", "aiff:1", "--yes"], capsys)
    assert (code, env["outcome"]) == (PARTIAL, "partial")
    assert [(r["track"], r["state"], r["reason"]) for r in env["data"]["results"]] == [
        (found.tracks[1], "undone", None), (found.tracks[0], "refused", "relocated")]
    code, env = run_json(["batch", "undo", "aiff:1", "--yes"], capsys)  # nothing left that can be undone: a refusal
    assert (code, env["outcome"]) == (REFUSED, "refused") and (env["data"]["undone"], env["data"]["refused"]) == (0, 1)
    assert "moved or removed in rekordbox" in env["message"]


def test_a_music_folder_that_is_gone_is_refused_for_the_new_commands_too(lib, capsys, tmp_path):
    found = lib(["mp3"])
    gone = found.paths.root.rename(tmp_path / "moved")
    for argv in (["rekordbox", "backups"], ["batch", "list"]):
        code, env = run_json(argv, capsys)
        assert (code, env["outcome"], env["reason"]) == (REFUSED, "refused", "no_library"), argv
    gone.rename(found.paths.root)


def test_a_restore_after_an_apply_and_its_undo_gives_back_the_before_copy_byte_for_byte(lib, capsys):
    """What the rehearsal's step 8 does on a copy of the user's library: the batch's backup is master.db as it was
    before the batch, so the restore puts back exactly that, saves the undone library as a backup of its own and leaves
    nothing missing."""
    import hashlib
    found = lib(["mp3", "mp3"])
    before_sha = rbbackup.sha256_file(found.place.db)
    share_before = {p.relative_to(found.place.share).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(found.place.share.rglob("*")) if p.is_file()}
    backup, applied = with_backup(found, capsys)
    assert run_json(["batch", "undo", f"aiff:{applied['batch']}", "--yes"], capsys)[0] == OK
    code, env = run_json(["rekordbox", "backups"], capsys)
    assert [b["id"] for b in env["data"]["backups"]] == [backup]  # the undo made no backup of its own
    undone_sha = rbbackup.sha256_file(found.place.db)
    assert undone_sha != before_sha  # the undo writes rekordbox's usn and update times
    code, env = run_json(["rekordbox", "restore", backup, "--dry-run"], capsys)
    assert (code, env["data"]["missing_after"]) == (OK, []) and rbbackup.sha256_file(found.place.db) == undone_sha
    code, env = run_json(["rekordbox", "restore", backup, "--yes"], capsys)
    assert (code, env["outcome"], env["data"]["missing_after"]) == (OK, "ok", [])
    assert rbbackup.sha256_file(found.place.db) == before_sha
    assert not list(found.place.db.parent.glob("master.db-*"))  # no -wal / -shm beside the copy
    share_after = {p.relative_to(found.place.share).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(found.place.share.rglob("*")) if p.is_file()}
    assert share_after == share_before
    saved = rbbackup.backups_dir(found.paths) / env["data"]["saved_current"] / "master.db"
    assert rbbackup.sha256_file(saved) == undone_sha
