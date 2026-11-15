"""The console commands of issue 33's stage B (discjockey/batch_cmd.py; plan stage B §2, §5.2 B6): `upgrade apply |
discard | undo`, `batch resume | undo` and `rekordbox checked | backups | restore` (`batch list` and `batch show` are
the new command line's, tests/test_cli_batches.py), through
`cli.main` on a library and a fixture rekordbox built in tmp_path. Exit codes 0-5, the JSON shapes, `--dry-run`
writing nothing, `restore` needing `--yes`, Busy, rekordbox open and Stop. Nothing real is read: the music folder and
rekordbox come from `DISCJOCKEY_SUPPORT` / `DISCJOCKEY_REKORDBOX`, which `make_lib` and `use` set."""
from __future__ import annotations

import json
import signal
import threading
from contextlib import contextmanager

import pytest

from batch_helpers import DIFFERENT, Lib, make_lib, needs_ffmpeg, use
from convert_helpers import EXACT
from discjockey import align, batch_cmd, batches, cli, db, library, report
from discjockey.cli import legacy
from discjockey.events import CancelToken
from discjockey.library import load_state, save_state
from discjockey.rekordbox import backup as rbbackup
from discjockey.rekordbox import process
from discjockey.rekordbox import session as rbsession

pytestmark = needs_ffmpeg

OK, FAILED, NO_LIBRARY, BUSY, REKORDBOX_OPEN, STOPPED = 0, 1, 2, 3, 4, 5
SAME = ["--way", "same-track"]


def make(tmp_path, monkeypatch, kinds: list[str], sub: str | None = None) -> Lib:
    """A library the console finds, whose parked upgrades are all the same edit (the real compare says "different
    edit" for the fixture files, so every test lines them up by hand). `sub`: a second library in the same test."""
    if sub:
        tmp_path = tmp_path / sub
        tmp_path.mkdir()
    lib = make_lib(tmp_path, monkeypatch, kinds)
    use(lib, monkeypatch)
    monkeypatch.setattr(align, "compare_files", lambda a, b: EXACT)
    return lib


def run(argv: list[str], capsys) -> tuple[int, str, str]:
    """`upgrade apply` and `upgrade discard` are the new command line's now (tests/test_cli_upgrade.py); this file pins
    the old handler, which stays until V1.12 deletes it with `batch_cmd.py`, so those words go through the old parser
    here."""
    code = legacy.main(argv) if argv[:2] in (["upgrade", "apply"], ["upgrade", "discard"]) else cli.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def run_json(argv: list[str], capsys) -> tuple[int, dict]:
    code, out, _err = run([*argv, "--json"], capsys)
    return code, json.loads(out)          # exactly one JSON object on stdout


def rekordbox_open(monkeypatch, on: bool = True) -> None:
    monkeypatch.setattr(process, "running", lambda: on)


def n_batches(lib: Lib) -> int:
    with db.connect(lib.paths.db_file) as conn:
        return db.aiff_batches(conn)[1]


def untouched(lib: Lib):
    """Everything a command could change: the music files, rekordbox's library, the records, the batches."""
    return lib.music(), lib.dump(), load_state(lib.paths)["tracks"], n_batches(lib), rbbackup.backups(lib.paths)


# --- no music folder ---

COMMANDS = [["upgrade", "discard", "t1"], ["upgrade", "undo", "t1"],
            ["batch", "resume", "1"], ["batch", "undo", "1"],
            ["rekordbox", "checked", "t1"], ["rekordbox", "backups"], ["rekordbox", "restore", "x", "--yes"]]


@pytest.mark.parametrize("argv", COMMANDS, ids=lambda a: " ".join(a))
def test_no_music_folder_is_exit_2(argv, capsys):
    code, data = run_json(argv, capsys)           # conftest: an empty support folder, so Setup was never done
    assert code == NO_LIBRARY
    assert (data["ok"], data["kind"], data["reason"]) == (False, "refused", "no_library")
    assert "music folder" in data["message"]


def test_a_music_folder_that_is_gone_says_so(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3"])
    gone = lib.paths.root.rename(tmp_path / "moved")
    code, out, _ = run(["rekordbox", "backups"], capsys)
    assert code == NO_LIBRARY and "isn't there" in out and str(lib.paths.root) in out
    gone.rename(lib.paths.root)


# --- upgrade list (the command line's `todo` read: discjockey/cli/render/todo.py, tests/test_cli_reads.py) ---

def listed(capsys, *argv: str) -> list[dict]:
    """The items `upgrade list` answers, in its one group."""
    code, env = run_json(["upgrade", "list", *argv], capsys)
    assert code == OK and env["outcome"] == "ok"
    return [item for g in env["data"]["groups"] for item in g["items"]]


def test_list_shows_what_waits_and_why_same_track_cannot_run(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "stale", "aiff", "mp3"])
    state = load_state(lib.paths)
    state["tracks"][lib.tracks[3]]["hidden"] = True                    # hidden upgrades aren't listed (as in To-do)
    save_state(lib.paths, state)
    before = untouched(lib)
    with library.run_lock(lib.paths.lock):                              # a read takes no lock: busy doesn't matter
        items = listed(capsys)
    assert [i["track_id"] for i in items] == lib.tracks[:3]
    first, stale, third = items
    assert (first["artist"], first["title"], first["folder"], first["path"]) == ("Artist", "Song 0", "A", lib.olds[0])
    assert first["upgrade_ready"] is True and first["same_track"] is None and third["same_track"] is None
    assert (stale["same_track"], stale["detail"]) == ("needs_choice", "Lossless ready · different edit")
    code, out, _ = run(["upgrade", "list"], capsys)
    assert code == OK and "Artist" in out and "Song 0" in out and "Upgrade ready" in out
    assert untouched(lib) == before


def test_the_waiting_mark_is_listed_only_while_same_track_can_run(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "stale"])      # the second one is stored as a different edit
    state = load_state(lib.paths)
    for key in lib.tracks:
        state["tracks"][key]["upgrade"]["auto_waits"] = "2026-11-09T10:00:00"
    save_state(lib.paths, state)
    items = listed(capsys)
    assert [(i["same_track"], i["detail"] == "Waits for rekordbox to be closed") for i in items] == [
        (None, True), ("needs_choice", False)]               # the hub's To-do shows no "waits" over it either
    code, out, _ = run(["upgrade", "list"], capsys)
    assert out.count("Waits for rekordbox to be closed") == 1


def test_list_shows_the_syncs_refusal_and_the_waiting_mark_while_the_switch_is_on(tmp_path, monkeypatch, capsys):
    from dataclasses import replace

    from discjockey.settings import load_settings, save_settings
    lib = make(tmp_path, monkeypatch, ["mp3", "aiff", "mp3"])
    state = load_state(lib.paths)
    record = {"reason": "not_analysed", "message": "rekordbox hasn't analysed this track yet.",
              "at": "2026-11-09T10:00:00", "anlz": {}, "free": None, "files": None}
    state["tracks"][lib.tracks[0]]["upgrade"]["auto_refused"] = record
    state["tracks"][lib.tracks[1]]["upgrade"]["auto_waits"] = "2026-11-09T10:00:00"
    save_state(lib.paths, state)
    first, second, third = listed(capsys)
    assert first["detail"] == "Not analysed in rekordbox · not upgraded at your sync"
    assert second["detail"] == "Waits for rekordbox to be closed" and third["detail"] != second["detail"]
    code, out, _ = run(["upgrade", "list"], capsys)
    assert "Not analysed in rekordbox · not upgraded at your sync" in out
    assert "Waits for rekordbox to be closed" in out
    save_settings(lib.paths.settings_file, replace(load_settings(lib.paths.settings_file), auto_upgrade=False))
    first, second, third = listed(capsys)                               # switch off: the waiting mark is hidden
    assert second["detail"] != "Waits for rekordbox to be closed"
    assert first["detail"] == "Not analysed in rekordbox · not upgraded at your sync"


def test_list_with_nothing_waiting(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3"])
    assert run(["upgrade", "discard", lib.tracks[0]], capsys)[0] == OK
    code, env = run_json(["upgrade", "list"], capsys)
    assert code == OK and env["outcome"] == "ok" and env["data"]["groups"] == []
    code, out, _ = run(["upgrade", "list"], capsys)
    assert code == OK and "Upgrade ready" not in out


# --- upgrade apply is the new command line's (tests/test_cli_upgrade.py); what follows pins the old handler's other words,
# --- and uses it to make the batches they work on, until V1.12 deletes batch_cmd.py with this file ---

# --- New track, Discard, Undo ---

def test_discard_several_and_undo_several(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "mp3", "mp3"])
    code, data = run_json(["upgrade", "discard", lib.tracks[0], lib.tracks[1], "nope"], capsys)
    assert code == FAILED and data["ok"] is True and data["batch"] is None
    assert [(r["action"], r["state"]) for r in data["results"]] == [("discard", "done")] * 2 + [("discard", "skipped")]
    assert not lib.entry(0)["upgrade"] and not lib.entry(1)["upgrade"] and lib.entry(2)["upgrade"]
    assert (lib.paths.root / lib.olds[0]).is_file()                         # a discard keeps the current file
    code, out, _ = run(["upgrade", "discard", lib.tracks[2]], capsys)
    assert code == OK and out.splitlines() == ["Done: Artist - Song 2", "1 done."]
    # Undo: replace two tracks with New track, then undo both (newest first, one job)
    lib2 = make(tmp_path, monkeypatch, ["mp3", "mp3"], "two")
    before = lib2.music()
    assert run(["upgrade", "apply", *lib2.tracks, "--way", "new-track"], capsys)[0] == OK
    assert lib2.music() != before
    code, data = run_json(["upgrade", "undo", *lib2.tracks], capsys)
    assert code == OK and data["ok"] is True and (data["total"], data["undone"], data["refused"], data["failed"]) == (2, 2, 0, 0)
    assert sorted(r["track"] for r in data["results"]) == lib2.tracks
    assert set(data["results"][0]) == {"track", "state", "reason", "message"} and data["results"][0]["state"] == "undone"
    assert lib2.entry(0)["path"] == lib2.olds[0] and lib2.entry(0)["upgrade"]
    code, out, _ = run(["upgrade", "undo", lib2.tracks[0]], capsys)       # nothing left to undo: refused, exit 1
    assert code == FAILED and "Not undone: Artist - Song 0" in out
    code, data = run_json(["upgrade", "undo", lib2.tracks[0]], capsys)    # ... and ok is false, as the window's job
    assert code == FAILED and (data["ok"], data["kind"]) == (False, "refused")
    assert (data["total"], data["undone"], data["refused"]) == (1, 0, 1)
    assert data["message"] == data["results"][0]["message"]               # one track: its own words
    code, data = run_json(["upgrade", "undo", *lib2.tracks], capsys)      # several: the general sentence
    assert code == FAILED and (data["ok"], data["kind"], data["message"]) == (False, "refused",
                                                                              batches.NOTHING_UNDONE)


# --- Busy, rekordbox open, Stop ---

def test_the_library_lock_held_is_exit_3_and_nothing_starts(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3"])
    before = untouched(lib)
    for argv in (["upgrade", "apply", "--all", *SAME], ["upgrade", "apply", lib.tracks[0], "--way", "new-track"],
                 ["upgrade", "discard", lib.tracks[0]], ["upgrade", "undo", lib.tracks[0]],
                 ["batch", "resume", "1"], ["batch", "undo", "1"], ["rekordbox", "checked", lib.tracks[0]],
                 ["rekordbox", "restore", "x", "--yes"]):
        with library.run_lock(lib.paths.lock):
            code, data = run_json(argv, capsys)
        assert code == BUSY, argv
        assert (data["ok"], data["kind"], data["message"]) == (False, "busy", batch_cmd.LOCK_HELD), argv
    assert untouched(lib) == before


def test_rekordbox_lock_held_leaves_the_batch_stopped_and_resumable(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "aiff"])
    before = lib.music(), lib.dump()
    with rbsession.writer_lock(lib.paths.support):
        code, data = run_json(["upgrade", "apply", "--all", *SAME], capsys)
        assert code == BUSY and (data["ok"], data["kind"]) == (False, "busy")
        assert data["message"] == rbsession.BUSY
        assert (data["state"], data["stop_reason"], data["done"]) == ("stopped", "busy", 0)
        assert [r["state"] for r in data["results"]] == ["planned", "planned"]
        batch = data["batch"]
        code, out, _ = run(["upgrade", "apply", "--all", *SAME], capsys)
        assert code == BUSY and f"discjockey batch resume {batch + 1}" in out    # the human text names the way on
        code, data = run_json(["batch", "undo", str(batch)], capsys)               # an undo writes rekordbox too
        assert code == BUSY and (data["ok"], data["kind"], data["message"]) == (False, "busy", rbsession.BUSY)
    assert (lib.music(), lib.dump()) == before
    # the second try planned the same songs again: the first batch gave its unrun items up (one batch per song)
    code, env = run_json(["batch", "show", f"aiff:{batch}"], capsys)
    data = env["data"]
    assert code == OK and data["state"] == "done" and [(r["state"], r["reason"]) for r in data["results"]] == [
        ("skipped", "later_batch")] * 2
    code, data = run_json(["batch", "resume", str(batch)], capsys)
    assert code == FAILED and data["reason"] == "not_stopped"
    code, data = run_json(["batch", "resume", str(batch + 1)], capsys)
    assert code == OK and (data["state"], data["done"], data["batch"]) == ("done", 2, batch + 1)


def test_rekordbox_open_is_exit_4_and_resume_finishes_after_it_quit(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "aiff"])
    rekordbox_open(monkeypatch)
    before = lib.music(), lib.dump()
    code, data = run_json(["upgrade", "apply", "--all", *SAME], capsys)
    assert code == REKORDBOX_OPEN and (data["ok"], data["kind"], data["reason"]) == (False, "rekordbox_open", "rekordbox_open")
    assert (data["state"], data["stop_reason"], data["done"], data["total"]) == ("stopped", "rekordbox_open", 0, 2)
    assert [r["state"] for r in data["results"]] == ["planned", "planned"] and data["backup"] is None
    assert (lib.music(), lib.dump()) == before
    batch = data["batch"]
    (row,) = batch_list(capsys)
    assert (row["id"], row["state"], row["stop_reason"], row["planned"]) == (f"aiff:{batch}", "stopped", "rekordbox_open", 2)
    code, out, _ = run(["batch", "resume", str(batch)], capsys)               # still open: still exit 4
    assert code == REKORDBOX_OPEN and f"discjockey batch resume {batch}" in out
    rekordbox_open(monkeypatch, False)
    code, data = run_json(["batch", "resume", str(batch)], capsys)
    assert code == OK and (data["state"], data["done"], data["batch"]) == ("done", 2, batch)


def test_a_batch_that_needs_no_rekordbox_write_runs_while_rekordbox_is_open(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["aiff", "mp3_free"])
    rekordbox_open(monkeypatch)
    code, data = run_json(["upgrade", "apply", "--all", *SAME], capsys)
    assert code == OK and data["done"] == 2 and data["backup"] is None


def test_a_batch_of_one_that_meets_rekordbox_open_is_closed_not_left_to_resume(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "mp3"])
    rekordbox_open(monkeypatch)
    before = lib.music(), lib.dump()
    code, data = run_json(["upgrade", "apply", lib.tracks[0], *SAME], capsys)
    assert code == REKORDBOX_OPEN and (data["ok"], data["kind"], data["reason"]) == (False, "rekordbox_open", "rekordbox_open")
    assert (data["state"], data["stop_reason"], data["done"], data["total"]) == ("done", None, 0, 1)
    assert [(r["state"], r["reason"]) for r in data["results"]] == [("skipped", "rekordbox_open")]
    assert (lib.music(), lib.dump()) == before and lib.entry(0)["upgrade"]       # still waiting in Upgrade ready
    code, out, _ = run(["upgrade", "apply", lib.tracks[0], *SAME], capsys)
    assert code == REKORDBOX_OPEN and "resume" not in out.lower()                   # nothing to resume
    assert all(b["state"] != "stopped" for b in batch_list(capsys))
    code, data = run_json(["batch", "resume", str(data["batch"])], capsys)
    assert code == FAILED and data["reason"] == "not_stopped"
    # several tracks, or Upgrade all with one: the batch stays stopped and resumable (as the window's)
    lib2 = make(tmp_path, monkeypatch, ["mp3"], "two")
    code, data = run_json(["upgrade", "apply", "--all", *SAME], capsys)
    assert code == REKORDBOX_OPEN and (data["state"], data["stop_reason"]) == ("stopped", "rekordbox_open")
    assert lib2.entry(0)["upgrade"]


def test_a_batch_of_one_that_meets_the_rekordbox_lock_is_closed_too(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "aiff"])
    with rbsession.writer_lock(lib.paths.support):
        code, data = run_json(["upgrade", "apply", lib.tracks[0], *SAME], capsys)
        assert code == BUSY and (data["ok"], data["kind"], data["message"]) == (False, "busy", rbsession.BUSY)
        assert (data["state"], data["done"]) == ("done", 0)
        assert [(r["state"], r["reason"]) for r in data["results"]] == [("skipped", "busy")]
        code, out, _ = run(["upgrade", "apply", lib.tracks[0], *SAME], capsys)
        assert code == BUSY and "resume" not in out.lower()
    code, data = run_json(["upgrade", "apply", lib.tracks[0], *SAME], capsys)       # the next try works
    assert code == OK and data["done"] == 1


def test_a_batch_stopped_by_rekordbox_midway_tells_the_console_way_on(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "mp3"])
    batch = batches.start(lib.paths, [(t, "same_track") for t in lib.tracks])
    result = batches.BatchResult(batch, "stopped", "rekordbox_open", 2, 1, 0, 0, [
        batches.ItemResult(lib.tracks[0], "same_track", "done", None, None, None, None),
        batches.ItemResult(lib.tracks[1], "same_track", "planned", None, None, None, None)], None)

    def call(_token):
        raise batches.RekordboxOpen(result)
    args = cli.parse_args(["batch", "resume", str(batch)])
    code = batch_cmd._finish(args, lib.paths, load_state(lib.paths), (), batch, call)
    out = capsys.readouterr().out
    assert code == REKORDBOX_OPEN
    assert f"stopped after 1 of 2. Quit rekordbox and run: discjockey batch resume {batch}." in out
    assert "press Resume" not in out                                      # that is the window's button


def test_the_done_lines_say_what_was_kept_and_when_rekordbox_had_no_track(tmp_path, monkeypatch):
    lib = make(tmp_path, monkeypatch, ["mp3"])
    state = load_state(lib.paths)

    def item(rb):
        return batches.ItemResult(lib.tracks[0], "same_track", "done", None, None, "Library/A/Song.aiff", rb)
    assert batch_cmd._item_lines(state, item({"entries": ["1"], "kept": ["title", "album"]})) == [
        "Upgraded: Artist - Song 0 → Song.aiff", "  Kept your own title / album in rekordbox."]   # the engine's " / "
    assert batch_cmd._item_lines(state, item({"entries": ["1"], "kept": []})) == [
        "Upgraded: Artist - Song 0 → Song.aiff"]
    assert batch_cmd._item_lines(state, item(None)) == [
        "Upgraded: Artist - Song 0 → Song.aiff", "  This file isn't in your rekordbox collection, so there was nothing "
        "to keep there."]


def test_undo_and_restore_refuse_while_rekordbox_is_open(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "mp3"])
    code, data = run_json(["upgrade", "apply", "--all", *SAME], capsys)
    batch, backup = data["batch"], data["backup"]
    rekordbox_open(monkeypatch)
    before = untouched(lib)
    for argv in (["batch", "undo", str(batch)], ["upgrade", "undo", *lib.tracks]):
        code, data = run_json(argv, capsys)
        assert code == REKORDBOX_OPEN and (data["ok"], data["kind"]) == (False, "rekordbox_open"), argv
        assert [r["state"] for r in data["results"]] == ["waiting", "waiting"] and data["undone"] == 0
    code, data = run_json(["rekordbox", "restore", backup, "--yes"], capsys)
    assert code == REKORDBOX_OPEN and (data["kind"], data["reason"]) == ("rekordbox_open", "rekordbox_open")
    assert data["message"] == batch_cmd.convert.REKORDBOX_OPEN
    assert untouched(lib) == before


REAL_INTERRUPTIBLE = batch_cmd._interruptible


def normal(monkeypatch) -> None:
    """No Stop any more: the real Ctrl-C handling and a compare that lines everything up."""
    monkeypatch.setattr(batch_cmd, "_interruptible", REAL_INTERRUPTIBLE)
    monkeypatch.setattr(align, "compare_files", lambda a, b: EXACT)


def tripping(monkeypatch, *, after: int = 0, twice: bool = False):
    """Replaces the Ctrl-C handling: the token is cancelled once `after` tracks were measured (0: before the first),
    or, with `twice`, the second Ctrl-C raises KeyboardInterrupt inside the track in work."""
    seen: dict = {}

    @contextmanager
    def fake(token: CancelToken):
        seen["token"] = token
        if not after and not twice:
            token.cancel()
        yield

    monkeypatch.setattr(batch_cmd, "_interruptible", fake)
    calls = []

    def compare(a, b):
        calls.append(1)
        if twice and len(calls) == after:
            raise KeyboardInterrupt
        if len(calls) == after and not twice:
            seen["token"].cancel()               # Stop pressed while this track is being measured
        return EXACT

    monkeypatch.setattr(align, "compare_files", compare)
    return seen


def test_stop_before_the_first_track_is_exit_5_and_resume_does_them_all(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "mp3"])
    tripping(monkeypatch)
    before = lib.music(), lib.dump()
    code, data = run_json(["upgrade", "apply", "--all", *SAME], capsys)
    assert code == STOPPED and (data["ok"], data["kind"]) == (False, "stopped")
    assert (data["state"], data["stop_reason"], data["done"]) == ("stopped", "stop", 0)
    assert data["message"] == "Stopped after 0 of 2." and [r["state"] for r in data["results"]] == ["planned"] * 2
    assert (lib.music(), lib.dump()) == before
    normal(monkeypatch)
    code, done = run_json(["batch", "resume", str(data["batch"])], capsys)
    assert code == OK and (done["state"], done["done"]) == ("done", 2)


def test_stop_between_tracks_keeps_what_is_done_and_resume_goes_on(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "mp3", "mp3"])
    tripping(monkeypatch, after=1)
    code, out, err = run(["upgrade", "apply", "--all", *SAME], capsys)
    assert code == STOPPED
    assert out.splitlines()[0] == "Upgraded: Artist - Song 0 → Artist - Song 0.aiff"
    assert "Waiting: Artist - Song 1" in out and "Stopped after 1 of 3." in out
    assert "Resume it with: discjockey batch resume 1" in out
    assert lib.entry(0)["path"].endswith("Song 0.aiff") and lib.entry(1)["path"] == lib.olds[1]
    code, env = run_json(["batch", "show", "aiff:1"], capsys)
    data = env["data"]
    assert code == OK and (data["state"], data["stop_reason"], data["done"], data["total"], data["planned"]) == (
        "stopped", "stop", 1, 3, 2)
    normal(monkeypatch)                                                  # the Stop is over
    code, data = run_json(["batch", "resume", "1"], capsys)
    assert code == OK and (data["state"], data["done"], data["batch"]) == ("done", 3, 1)
    assert [r["state"] for r in data["results"]] == ["done"] * 3


def test_a_second_ctrl_c_stops_at_once_with_the_batch_saved(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "mp3"])
    tripping(monkeypatch, after=2, twice=True)
    code, data = run_json(["upgrade", "apply", "--all", *SAME], capsys)
    assert code == STOPPED and (data["kind"], data["state"]) == ("stopped", "stopped")
    assert data["message"] == "Stopped. Everything finished so far is saved."
    assert [r["state"] for r in data["results"]] == ["done", "planned"]
    assert lib.entry(1)["path"] == lib.olds[1] and lib.entry(1)["upgrade"] and load_state(lib.paths)["pending"] == []


def test_stop_in_new_track_discard_and_undo(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "mp3"])
    tripping(monkeypatch)
    before = untouched(lib)
    for argv in (["upgrade", "apply", *lib.tracks, "--way", "new-track"], ["upgrade", "discard", *lib.tracks]):
        code, data = run_json(argv, capsys)
        assert code == STOPPED and (data["ok"], data["kind"], data["message"]) == (False, "stopped", "Stopped after 0 of 2.")
        assert [r["state"] for r in data["results"]] == ["planned", "planned"] and data["batch"] is None
    assert untouched(lib) == before
    normal(monkeypatch)
    assert run(["upgrade", "apply", *lib.tracks, "--way", "new-track"], capsys)[0] == OK
    tripping(monkeypatch)
    code, data = run_json(["upgrade", "undo", *lib.tracks], capsys)
    assert code == STOPPED and (data["ok"], data["kind"]) == (False, "stopped") and data["undone"] == 0
    assert [r["state"] for r in data["results"]] == ["waiting", "waiting"]


def test_the_ctrl_c_handler_stops_between_tracks_and_a_second_press_raises(monkeypatch):
    if threading.current_thread() is not threading.main_thread():
        pytest.skip("signals are installed in the main thread only")
    token = CancelToken()
    now = [100.0]
    monkeypatch.setattr(batch_cmd.time, "monotonic", lambda: now[0])
    before = signal.getsignal(signal.SIGINT)
    with batch_cmd._interruptible(token):
        handler = signal.getsignal(signal.SIGINT)
        assert handler is not before
        handler(signal.SIGINT, None)
        assert token.cancelled
        now[0] += 0.2
        handler(signal.SIGINT, None)                   # a forwarded repeat of the same press: ignored
        now[0] += 2
        with pytest.raises(KeyboardInterrupt):
            handler(signal.SIGINT, None)
    assert signal.getsignal(signal.SIGINT) is before     # restored


# --- batch list / show / resume / undo ---

def batch_list(capsys, *argv: str) -> list[dict]:
    """The rows `batch list` answers (the new command line's read: tests/test_cli_batches.py pins its shape)."""
    code, env = run_json(["batch", "list", *argv], capsys)
    assert code == OK and env["outcome"] == "ok"
    return env["data"]["batches"]


def test_batch_list_show_resume_and_undo(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "mp3_plain", "aiff"])
    assert batch_list(capsys) == []
    code, applied = run_json(["upgrade", "apply", *lib.tracks, *SAME], capsys)
    batch = applied["batch"]
    [row] = batch_list(capsys)
    assert (row["id"], row["batch"], row["what"], row["started_by"], row["state"], row["total"], row["done"],
            row["skipped"], row["backup"]) == (f"aiff:{batch}", batch, "upgrade", "user", "done", 3, 2, 1,
                                              applied["backup"])
    code, env = run_json(["batch", "show", f"aiff:{batch}"], capsys)
    shown = env["data"]
    assert code == OK and [(r["track"], r["state"], r["path"], r["rekordbox"]) for r in shown["results"]] == [
        (r["track"], r["state"], r["path"], r["rekordbox"]) for r in applied["results"]]
    assert shown["batch"] == batch and shown["undone"] == 0 and shown["started_by"] == "user"
    code, out, _ = run(["batch", "show", f"aiff:{batch}"], capsys)
    assert "Artist - Song 0" in out and "Library/A/Artist - Song 0.aiff" in out
    # a finished batch has nothing to resume; an unknown one doesn't exist
    code, data = run_json(["batch", "resume", str(batch)], capsys)
    assert code == FAILED and (data["ok"], data["kind"], data["reason"]) == (False, "refused", "not_stopped")
    assert data["state"] == "done" and data["batch"] == batch
    code, env = run_json(["batch", "show", "aiff:99"], capsys)
    assert code == 2 and (env["outcome"], env["reason"]) == ("bad_args", "unknown_id")
    for sub in ("resume", "undo"):
        code, data = run_json(["batch", sub, "99"], capsys)
        assert code == FAILED and (data["ok"], data["kind"], data["reason"]) == (False, "refused", "unknown_batch"), sub
        assert data["message"] == "There is no batch 99."
    # undo the whole batch: its done tracks come back, newest first
    done_before = lib.music()
    code, data = run_json(["batch", "undo", str(batch)], capsys)
    assert code == OK and (data["batch"], data["total"], data["undone"], data["refused"]) == (batch, 2, 2, 0)
    assert [r["track"] for r in data["results"]] == [lib.tracks[2], lib.tracks[0]]
    assert lib.entry(0)["path"] == lib.olds[0] and lib.entry(0)["upgrade"] and lib.row(0)["FolderPath"].endswith("Old 0.mp3")
    assert lib.music() != done_before
    code, env = run_json(["batch", "show", f"aiff:{batch}"], capsys)
    shown = env["data"]
    assert shown["undone"] == 2 and [r["state"] for r in shown["results"]] == ["undone", "skipped", "undone"]


def test_batch_undo_lists_a_track_it_cannot_undo_and_is_exit_1(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "mp3"])
    code, data = run_json(["upgrade", "apply", "--all", *SAME], capsys)
    batch = data["batch"]
    from rekordbox_helpers import _open, KEYS
    con = _open(lib.place.db, KEYS[0])                      # the DJ relocated the first track in rekordbox
    con.execute("UPDATE djmdContent SET FolderPath = '/Users/dj/Music/Elsewhere.aiff' WHERE ID = '1'")
    con.commit()
    con.close()
    code, data = run_json(["batch", "undo", str(batch)], capsys)
    assert code == FAILED and data["ok"] is True and (data["undone"], data["refused"]) == (1, 1)
    assert [(r["track"], r["state"], r["reason"]) for r in data["results"]] == [
        (lib.tracks[1], "undone", None), (lib.tracks[0], "refused", "relocated")]
    code, out, _ = run(["batch", "undo", str(batch)], capsys)
    assert code == FAILED and "Not undone: Artist - Song 0 (" in out
    code, data = run_json(["batch", "undo", str(batch)], capsys)      # nothing left that can be undone: a refusal
    assert code == FAILED and (data["ok"], data["kind"], data["undone"], data["refused"]) == (False, "refused", 0, 1)
    assert "moved or removed in rekordbox" in data["message"]


# --- rekordbox checked ---

def test_checked_by_keys_and_by_batch(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "aiff", "mp3"])
    code, data = run_json(["upgrade", "apply", *lib.tracks, *SAME], capsys)
    batch = data["batch"]
    code, data = run_json(["rekordbox", "checked", lib.tracks[0], "nope"], capsys)
    assert code == FAILED and data == {"ok": True, "checked": [lib.tracks[0]], "not_checked": ["nope"]}
    assert lib.entry(0)["rekordbox_check"] is None and lib.entry(1)["rekordbox_check"]
    code, out, _ = run(["rekordbox", "checked", "--batch", str(batch)], capsys)    # the rest of the batch
    assert code == OK and out.splitlines() == ["Checked: Artist - Song 1", "Checked: Artist - Song 2"]
    assert lib.entry(2)["rekordbox_check"] is None
    code, data = run_json(["rekordbox", "checked", "--batch", str(batch)], capsys)  # nothing left to check
    assert code == OK and data == {"ok": True, "checked": [], "not_checked": []}
    code, data = run_json(["upgrade", "undo", lib.tracks[0]], capsys)               # "checked" ended the undo
    assert code == FAILED and data["refused"] == 1
    code, data = run_json(["rekordbox", "checked", "--batch", "77"], capsys)
    assert code == FAILED and (data["ok"], data["reason"]) == (False, "unknown_batch")


# --- rekordbox backups / restore ---

def test_checked_writes_operations_log_lines_and_batch_0_is_a_batch(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "aiff"])
    run_json(["upgrade", "apply", *lib.tracks, *SAME], capsys)
    assert run_json(["rekordbox", "checked", lib.tracks[0]], capsys)[0] == OK
    lines = [json.loads(line) for line in lib.paths.operations_log.read_text(encoding="utf-8").splitlines()]
    [line] = [x for x in lines if x["operation"] == "rekordbox_checked"]
    assert (line["track_id"], line["result"], line["artist"], line["title"]) == (
        lib.tracks[0], "done", "Artist", "Song 0")
    # `--batch 0` is a batch id (no such batch), not "no --batch given"
    code, data = run_json(["rekordbox", "checked", "--batch", "0"], capsys)
    assert code == FAILED and (data["ok"], data["reason"]) == (False, "unknown_batch")
    with pytest.raises(SystemExit):
        cli.parse_args(["rekordbox", "checked", lib.tracks[1], "--batch", "0"])      # both given is a usage error
    with pytest.raises(SystemExit):
        cli.parse_args(["rekordbox", "checked"])                                     # neither is too


def test_backups_and_restore(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "mp3"])
    assert run_json(["rekordbox", "backups"], capsys) == (OK, {"ok": True, "backups": []})
    assert run(["rekordbox", "backups"], capsys)[1].strip() == "No backups yet."
    rb_before = lib.dump()
    code, applied = run_json(["upgrade", "apply", "--all", *SAME], capsys)
    assert lib.dump() != rb_before
    code, data = run_json(["rekordbox", "backups"], capsys)
    [only] = data["backups"]
    assert code == OK and set(only) == {"id", "created", "batches", "tracks", "size"}
    assert only["id"] == applied["backup"] and only["batches"] == [applied["batch"]] and only["tracks"] == 2
    code, out, _ = run(["rekordbox", "backups"], capsys)
    assert out.startswith(only["id"]) and out.strip().endswith("2 tracks")
    # without --yes nothing happens
    before = untouched(lib)
    code, data = run_json(["rekordbox", "restore", only["id"]], capsys)
    assert code == FAILED and (data["ok"], data["kind"], data["reason"]) == (False, "refused", "needs_yes")
    assert data["message"] == batch_cmd.NEEDS_YES and untouched(lib) == before
    # unknown name
    code, data = run_json(["rekordbox", "restore", "nope", "--yes"], capsys)
    assert code == FAILED and data["reason"] == "not_found" and "rekordbox backups" in data["message"]
    assert untouched(lib) == before
    # restore: rekordbox's library as before the batch; the tracks it pointed at the moved files are listed
    code, data = run_json(["rekordbox", "restore", only["id"], "--yes"], capsys)
    assert code == OK and data["ok"] is True and data["restored"] == only["id"]
    assert lib.dump() == rb_before
    assert data["saved_current"] in [b.id for b in rbbackup.backups(lib.paths)] and data["saved_current"] != only["id"]
    assert [m["id"] for m in data["missing_after"]] == ["1", "2"]
    assert all(set(m) == {"id", "path", "was"} for m in data["missing_after"])


def test_restore_words_and_a_restore_that_leaves_no_missing_file(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3"])
    code, applied = run_json(["upgrade", "apply", "--all", *SAME], capsys)
    assert run_json(["batch", "undo", str(applied["batch"])], capsys)[0] == OK     # the files are back first
    code, out, _ = run(["rekordbox", "restore", applied["backup"], "--yes"], capsys)
    lines = out.splitlines()
    assert code == OK and len(lines) == 1
    assert lines[0].startswith(f"Restored rekordbox's library from {applied['backup']}. Your library as it was is saved as ")
    code, data = run_json(["rekordbox", "restore", applied["backup"], "--yes"], capsys)
    assert code == OK and data["missing_after"] == []
    code, out, _ = run(["rekordbox", "restore", "nope"], capsys)
    assert code == FAILED and out.strip() == batch_cmd.NEEDS_YES


def test_restore_tells_how_many_tracks_point_at_files_that_moved(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "mp3"])
    code, applied = run_json(["upgrade", "apply", "--all", *SAME], capsys)
    code, out, _ = run(["rekordbox", "restore", applied["backup"], "--yes"], capsys)
    assert code == OK
    assert batch_cmd.MISSING_AFTER.format(n=2) in out.splitlines()[1] and "discjockey batch undo" in out


def test_restore_refuses_another_library_and_a_missing_one(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3"])
    code, applied = run_json(["upgrade", "apply", "--all", *SAME], capsys)
    before = untouched(lib)
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(tmp_path / "no-rekordbox-here"))
    code, data = run_json(["rekordbox", "restore", applied["backup"], "--yes"], capsys)
    assert code == FAILED and (data["kind"], data["reason"]) == ("refused", "no_rekordbox")
    assert data["message"] == batch_cmd.RESTORE_WORDS["no_rekordbox"]
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(lib.folder))
    assert untouched(lib) == before


# --- the lock-free reads ---

def test_reads_do_not_wait_for_a_running_job(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3"])
    code, applied = run_json(["upgrade", "apply", "--all", *SAME], capsys)
    with library.run_lock(lib.paths.lock), rbsession.writer_lock(lib.paths.support):
        for argv in (["batch", "list"], ["batch", "show", f"aiff:{applied['batch']}"],
                     ["rekordbox", "backups"]):
            assert run_json(argv, capsys)[0] == OK, argv
