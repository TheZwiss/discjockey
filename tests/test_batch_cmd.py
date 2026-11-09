"""The console commands of issue 33's stage B (discjockey/batch_cmd.py; plan stage B §2, §5.2 B6): `upgrade list |
apply | discard | undo`, `batch list | show | resume | undo` and `rekordbox checked | backups | restore`, through
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
    code = cli.main(argv)
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

COMMANDS = [["upgrade", "list"], ["upgrade", "apply", "--all", *SAME], ["upgrade", "apply", "--all", *SAME, "--dry-run"],
            ["upgrade", "apply", "t1", "--way", "new-track"], ["upgrade", "discard", "t1"], ["upgrade", "undo", "t1"],
            ["batch", "list"], ["batch", "show", "1"], ["batch", "resume", "1"], ["batch", "undo", "1"],
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
    code, out, _ = run(["batch", "list"], capsys)
    assert code == NO_LIBRARY and "isn't there" in out and str(lib.paths.root) in out
    gone.rename(lib.paths.root)


# --- upgrade list ---

def test_list_shows_what_waits_and_why_same_track_cannot_run(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "stale", "aiff", "mp3"])
    state = load_state(lib.paths)
    state["tracks"][lib.tracks[3]]["hidden"] = True                    # hidden upgrades aren't listed (as in To-do)
    save_state(lib.paths, state)
    before = untouched(lib)
    with library.run_lock(lib.paths.lock):                              # a read takes no lock: busy doesn't matter
        code, data = run_json(["upgrade", "list"], capsys)
    assert code == OK and data["ok"] is True and data["count"] == 3
    assert [r["track"] for r in data["upgrades"]] == lib.tracks[:3]
    first, stale, third = data["upgrades"]
    assert set(first) == {"track", "artist", "title", "folder", "file", "parked", "now", "new", "alignment",
                          "same_track", "auto_refused", "auto_waits"}
    assert (first["artist"], first["title"], first["folder"], first["file"]) == ("Artist", "Song 0", "A", lib.olds[0])
    assert first["parked"] == "Upgrades ready/A/Artist - Song 0.aiff" and first["new"].startswith("Qobuz FLAC")
    assert (first["alignment"], first["same_track"], first["auto_refused"], first["auto_waits"]) == (
        "exact", None, None, False)
    assert (stale["alignment"], stale["same_track"]) == ("different", "needs_choice")
    assert third["same_track"] is None
    code, out, _ = run(["upgrade", "list"], capsys)
    assert code == OK and "Artist - Song 0" in out and "Same track: possible" in out
    assert "Same track: not now (it's a different edit, so you choose)" in out
    assert untouched(lib) == before


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
    code, data = run_json(["upgrade", "list"], capsys)
    first, second, third = data["upgrades"]
    assert code == OK and first["auto_refused"] == {k: record[k] for k in ("reason", "message", "at")}
    assert (first["auto_waits"], second["auto_waits"], second["auto_refused"]) == (False, True, None)
    assert (third["auto_refused"], third["auto_waits"]) == (None, False)
    code, out, _ = run(["upgrade", "list"], capsys)
    assert "    Not upgraded at your sync: rekordbox hasn't analysed this track yet." in out
    assert "    Waited for rekordbox to be closed at your last sync; it is upgraded at your next sync." in out
    save_settings(lib.paths.settings_file, replace(load_settings(lib.paths.settings_file), auto_upgrade=False))
    code, data = run_json(["upgrade", "list"], capsys)                  # switch off: the waiting mark is hidden
    assert [r["auto_waits"] for r in data["upgrades"]] == [False, False, False]
    assert data["upgrades"][0]["auto_refused"]["reason"] == "not_analysed"
    lib.paths.settings_file.write_text('{"auto_upgrade": 3}')           # a broken settings file is said, not guessed
    code, data = run_json(["upgrade", "list"], capsys)
    assert code == FAILED and (data["ok"], data["reason"]) == (False, "settings_invalid")


def test_list_with_nothing_waiting(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3"])
    assert run(["upgrade", "discard", lib.tracks[0]], capsys)[0] == OK
    code, out, _ = run(["upgrade", "list"], capsys)
    assert (code, out.strip()) == (OK, "No better versions are waiting.")
    assert run_json(["upgrade", "list"], capsys) == (OK, {"ok": True, "upgrades": [], "count": 0})


# --- upgrade apply: Same track ---

def test_apply_all_is_one_batch_and_exit_1_when_a_track_was_skipped(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "mp3_plain", "aiff", "stale"])
    code, data = run_json(["upgrade", "apply", "--all", *SAME], capsys)
    assert code == FAILED and data["ok"] is True                          # ran to its end: ok stays true, exit 1
    assert (data["state"], data["total"], data["done"], data["skipped"], data["failed"]) == ("done", 3, 2, 1, 0)
    assert [(r["track"], r["state"], r["reason"]) for r in data["results"]] == [
        (lib.tracks[0], "done", None), (lib.tracks[1], "skipped", "not_analysed"), (lib.tracks[2], "done", None)]
    assert set(data["results"][0]) == {"track", "action", "state", "reason", "message", "path", "rekordbox"}
    assert data["results"][0]["path"] == "Library/A/Artist - Song 0.aiff"
    assert data["results"][0]["rekordbox"] == {"entries": ["1"], "kept": []}
    assert lib.entry(0)["path"] == "Library/A/Artist - Song 0.aiff" and lib.row(0)["FolderPath"].endswith("Song 0.aiff")
    [only] = rbbackup.backups(lib.paths)
    assert data["backup"] == only.id
    with db.connect(lib.paths.db_file) as conn:
        [row], total = db.aiff_batches(conn)
    assert (row.id, row.started_by, row.state, total) == (data["batch"], "upgrade_all", "done", 1)
    assert lib.entry(1)["upgrade"] and lib.entry(3)["upgrade"]             # skipped ones stay parked


def test_apply_all_done_for_every_track_is_exit_0_with_the_words(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "aiff"])
    code, out, err = run(["upgrade", "apply", "--all", *SAME], capsys)
    assert code == OK
    assert out.splitlines()[:2] == ["Upgraded: Artist - Song 0 → Artist - Song 0.aiff", "Upgraded: Artist - Song 1 → Artist - Song 1.aiff"]
    assert "2 upgraded, your cues stayed." in out and report.USB_STEP in out
    assert err.splitlines() == ["1 of 2: Artist - Song 0", "2 of 2: Artist - Song 1"]   # progress goes to stderr
    assert lib.entry(0)["rekordbox_check"]["batch"] == lib.entry(1)["rekordbox_check"]["batch"]


def test_the_kept_note_is_told_when_the_dj_edited_the_title(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3"])
    from rekordbox_helpers import _open, KEYS
    con = _open(lib.place.db, KEYS[0])
    con.execute("UPDATE djmdContent SET Title = 'My own title' WHERE ID = '1'")
    con.commit()
    con.close()
    code, out, _ = run(["upgrade", "apply", lib.tracks[0], *SAME], capsys)
    assert code == OK and "Kept your own title in rekordbox." in out


def test_one_id_several_ids_and_all_give_the_same_results(tmp_path, monkeypatch, capsys):
    def results(sub, argv_for):
        lib = make(tmp_path, monkeypatch, ["mp3", "aiff", "mp3_free"], sub)
        code, data = run_json(argv_for(lib), capsys)
        return code, data["results"], data["done"]
    by_ids = results("a", lambda lib: ["upgrade", "apply", *lib.tracks, *SAME])
    by_all = results("b", lambda lib: ["upgrade", "apply", "--all", *SAME])
    assert by_ids == by_all and by_ids[0] == OK and by_ids[2] == 3
    one = results("c", lambda lib: ["upgrade", "apply", lib.tracks[1], *SAME])
    assert one[1] == [by_ids[1][1]] and one[2] == 1                       # the same per-track result for one id
    again = results("d", lambda lib: ["upgrade", "apply", lib.tracks[0], lib.tracks[0], lib.tracks[1], *SAME])
    assert again[1] == by_ids[1][:2]                                      # a repeated key counts once


def test_the_console_and_the_window_give_the_same_results_for_the_same_library(tmp_path, monkeypatch, capsys):
    """Plan §5.2 B6, "as the bridge": the same library through `api.upgrade(ids, "swap")` and `upgrade apply` ends
    with the same per-track results (the console does not carry its own rules)."""
    from hub_helpers import make_api, wait_job
    kinds = ["mp3", "aiff", "mp3_free", "mp3_plain", "stale"]
    (tmp_path / "hub").mkdir()
    hub_lib = make_lib(tmp_path / "hub", monkeypatch, kinds)
    api, rec = make_api(hub_lib.paths, compare=lambda a, b: EXACT, rekordbox_running=lambda: False,
                        rekordbox_place=lambda: hub_lib.place)
    finished = wait_job(api, rec, api.upgrade(hub_lib.tracks, "swap"))
    console_lib = make(tmp_path, monkeypatch, kinds, "console")
    code, data = run_json(["upgrade", "apply", *console_lib.tracks, *SAME], capsys)
    assert code == FAILED and data["ok"] is True               # some were skipped: ran to its end, exit 1
    assert finished.result["results"] == data["results"]
    assert [r["state"] for r in data["results"]] == ["done", "done", "done", "skipped", "skipped"]
    assert {k: finished.result[k] for k in ("state", "total", "done", "skipped", "failed")} == {
        k: data[k] for k in ("state", "total", "done", "skipped", "failed")}


def test_an_unknown_track_is_skipped_and_nothing_to_do_is_refused(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3"])
    code, data = run_json(["upgrade", "apply", "nope", lib.tracks[0], *SAME], capsys)
    assert code == FAILED and data["ok"] is True
    assert [(r["state"], r["reason"]) for r in data["results"]] == [("skipped", "no_upgrade"), ("done", None)]
    # a batch of nothing but a refusal: ok false, kind refused, the reason of the one track
    lib2 = make(tmp_path, monkeypatch, ["stale"], "two")
    code, data = run_json(["upgrade", "apply", lib2.tracks[0], *SAME], capsys)
    assert code == FAILED and (data["ok"], data["kind"], data["reason"]) == (False, "refused", "needs_choice")
    assert data["batch"] and data["results"][0]["state"] == "skipped"
    # --all with nothing Same track can run for
    code, data = run_json(["upgrade", "apply", "--all", *SAME], capsys)
    assert code == FAILED and (data["ok"], data["kind"], data["message"]) == (False, "refused", batch_cmd.NOTHING)
    assert data["batch"] is None and data["results"] == []


# --- upgrade apply --dry-run ---

def test_dry_run_changes_nothing_and_takes_no_lock(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "stale", "aiff", "mp3_plain"])
    before = untouched(lib)
    with library.run_lock(lib.paths.lock), rbsession.writer_lock(lib.paths.support):    # busy would be exit 3
        code, data = run_json(["upgrade", "apply", "--all", *SAME, "--dry-run"], capsys)
    assert code == OK and data["ok"] is True and data["dry_run"] is True and data["way"] == "same-track"
    assert (data["total"], data["planned"], data["skipped"]) == (3, 3, 0)    # --all: what Same track can run for
    first, aiff, plain = data["results"]
    assert [r["track"] for r in data["results"]] == [lib.tracks[0], lib.tracks[2], lib.tracks[3]]
    assert plain["state"] == "planned"                                    # the quick answer: the run may still skip it
    assert set(first) == {"track", "action", "state", "reason", "file", "new_file", "superseded"}
    root = lib.paths.root
    assert (first["state"], first["file"], first["new_file"], first["superseded"]) == (
        "planned", str(root / lib.olds[0]), str(root / "Library/A/Artist - Song 0.aiff"),
        str(root / "Superseded/A/Old 0.mp3"))
    assert aiff["new_file"] == aiff["file"] and aiff["superseded"].endswith("Artist - Song 2 (lossy).aiff")
    [place] = data["space"]
    assert set(place) == {"drive", "needed", "free", "enough"} and place["needed"] > 0 and place["enough"] is True
    assert data["rekordbox"] == {"state": "ready", "running": False, "needs_rekordbox_closed": False}
    assert untouched(lib) == before and not (lib.paths.root / ".discjockey" / "rekordbox").exists()


def test_the_new_track_dry_run_names_the_files_the_run_makes(tmp_path, monkeypatch, capsys):
    """An AIFF that already has the clean name moves away first, so the new file takes that very name (no ID)."""
    lib = make(tmp_path, monkeypatch, ["aiff", "mp3"])
    code, plan = run_json(["upgrade", "apply", *lib.tracks, "--way", "new-track", "--dry-run"], capsys)
    assert code == OK and plan["planned"] == 2
    code, data = run_json(["upgrade", "apply", *lib.tracks, "--way", "new-track"], capsys)
    assert code == OK
    for i, row in enumerate(plan["results"]):
        assert row["new_file"] == str(lib.paths.root / lib.entry(i)["path"])
    assert plan["results"][0]["new_file"].endswith("Library/A/Artist - Song 0.aiff")


def test_dry_run_names_what_it_would_skip_and_says_when_rekordbox_must_be_closed(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "stale"])
    rekordbox_open(monkeypatch)
    before = untouched(lib)
    code, out, _ = run(["upgrade", "apply", *lib.tracks, "nope", *SAME, "--dry-run"], capsys)
    assert code == OK
    assert out.splitlines()[0] == "Would upgrade: Artist - Song 0 → Artist - Song 0.aiff"
    assert "Skipped: Artist - Song 1 (it's a different edit, so you choose)" in out
    assert "Skipped: nope (no better version is waiting)" in out
    assert "1 would be upgraded, 2 skipped." in out and batch_cmd.convert.REKORDBOX_OPEN in out
    assert out.strip().endswith("Dry run: nothing was changed. The real run checks each track again.")
    code, data = run_json(["upgrade", "apply", lib.tracks[0], *SAME, "--dry-run"], capsys)
    assert data["rekordbox"] == {"state": "ready", "running": True, "needs_rekordbox_closed": True}
    assert untouched(lib) == before
    # New track: planned from the same names, nothing decoded
    code, data = run_json(["upgrade", "apply", lib.tracks[0], "--way", "new-track", "--dry-run"], capsys)
    assert code == OK and data["results"][0]["action"] == "add_new" and data["results"][0]["state"] == "planned"
    assert untouched(lib) == before


# --- upgrade apply: New track, Discard, Undo ---

def test_new_track_on_several_runs_them_one_by_one_without_a_batch(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "mp3", "mp3_free"])
    code, data = run_json(["upgrade", "apply", lib.tracks[0], lib.tracks[1], "nope", "--way", "new-track"], capsys)
    assert code == FAILED and data["ok"] is True and data["batch"] is None and data["backup"] is None
    assert (data["state"], data["total"], data["done"], data["skipped"]) == ("done", 3, 2, 1)
    assert [(r["action"], r["state"]) for r in data["results"]] == [("add_new", "done")] * 2 + [("add_new", "skipped")]
    assert data["results"][2]["reason"] == "no_upgrade"
    assert lib.entry(0)["path"] == "Library/A/Artist - Song 0.aiff" and lib.entry(1)["path"].endswith("Song 1.aiff")
    assert n_batches(lib) == 0 and rbbackup.backups(lib.paths) == []       # no batch record, no rekordbox write
    log = lib.paths.operations_log.read_text()
    assert log.count('"operation": "upgrade_add_new"') == 2
    code, out, err = run(["batch", "list"], capsys)
    assert out.strip() == "No batches yet."


def test_all_works_only_with_same_track(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3"])
    before = untouched(lib)
    code, data = run_json(["upgrade", "apply", "--all", "--way", "new-track"], capsys)
    assert code == FAILED and (data["ok"], data["kind"], data["reason"]) == (False, "refused", "all_needs_same_track")
    code, out, _ = run(["upgrade", "apply", "--all", "--way", "new-track"], capsys)
    assert code == FAILED and out.startswith("--all works only with --way same-track")
    assert untouched(lib) == before


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
    code, data = run_json(["batch", "show", str(batch)], capsys)
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
    code, out, _ = run(["batch", "list"], capsys)
    assert f"#{batch}" in out and "stopped, rekordbox_open" in out and "2 left" in out
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
    assert "stopped" not in run(["batch", "list"], capsys)[1]
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
    code, out, _ = run(["batch", "show", "1"], capsys)
    assert code == OK and "stopped, stop" in out and "1 of 3 done" in out and "2 left" in out
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

def test_batch_list_show_resume_and_undo(tmp_path, monkeypatch, capsys):
    lib = make(tmp_path, monkeypatch, ["mp3", "mp3_plain", "aiff"])
    assert run_json(["batch", "list"], capsys) == (OK, {"ok": True, "batches": [], "count": 0})
    code, applied = run_json(["upgrade", "apply", *lib.tracks, *SAME], capsys)
    batch = applied["batch"]
    code, data = run_json(["batch", "list"], capsys)
    assert code == OK and data["count"] == 1
    [row] = data["batches"]
    assert set(row) == {"batch", "kind", "started_by", "state", "stop_reason", "started", "ended", "total", "done",
                        "skipped", "failed", "planned", "undone", "backup"}
    assert (row["batch"], row["kind"], row["started_by"], row["state"], row["total"], row["done"], row["skipped"],
            row["backup"]) == (batch, "upgrade", "user", "done", 3, 2, 1, applied["backup"])
    code, out, _ = run(["batch", "list"], capsys)
    assert out.strip().startswith(f"#{batch}  ") and "2 of 3 done, 1 skipped" in out and out.strip().endswith("(user)")
    code, shown = run_json(["batch", "show", str(batch)], capsys)
    assert code == OK and shown["ok"] is True and shown["results"] == applied["results"]
    assert shown["batch"] == batch and shown["undone"] == 0 and shown["started_by"] == "user"
    code, out, _ = run(["batch", "show", str(batch)], capsys)
    assert "Upgraded: Artist - Song 0 → Artist - Song 0.aiff" in out and "Skipped: Artist - Song 1 (" in out
    # a finished batch has nothing to resume; an unknown one doesn't exist
    code, data = run_json(["batch", "resume", str(batch)], capsys)
    assert code == FAILED and (data["ok"], data["kind"], data["reason"]) == (False, "refused", "not_stopped")
    assert data["state"] == "done" and data["batch"] == batch
    for sub in ("show", "resume", "undo"):
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
    code, shown = run_json(["batch", "show", str(batch)], capsys)
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
        for argv in (["upgrade", "list"], ["batch", "list"], ["batch", "show", str(applied["batch"])],
                     ["rekordbox", "backups"]):
            assert run_json(argv, capsys)[0] == OK, argv
