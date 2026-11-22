"""`history` through the command line (issue 39 phase 3, V3.3a): runs, batches and logged steps in one list, newest
first, each with its undo or the words that say why none; `--since`, paging. The rule itself is pinned on plain inputs
in tests/test_hub_history.py; this file runs it on a library with records."""
import json
from datetime import datetime

import pytest
from hub_helpers import choose_music, make_root, services, write_state
from test_cli_batches import with_batches, with_report

import discjockey.cli as cli
from discjockey import db, library, words
from discjockey.cli import bind
from discjockey.hub.api import CliApi

STAMP = "2026-11-10_110000"
STEP = "2026-11-10T09:00:30"       # inside aiff:1 (09:00:00 to 09:01:00): that batch's own step
OUTSIDE = "2026-11-11T08:00:00"    # the same operation on the same song, after the batch
NEVER = "2026-11-12T10:00:00"


def log_line(time, track, operation, artist, title, result="done"):
    return json.dumps({"time": time, "track_id": track, "artist": artist, "title": title, "operation": operation,
                       "result": result, "message": ""})


@pytest.fixture
def lib(tmp_path, monkeypatch):
    paths = make_root(tmp_path)
    state = library.load_state(paths)
    state["tracks"]["t1"]["rekordbox_check"] = {"reason": "swapped", "since": "2026-11-11", "moved": False,
                                                "undo": {"kind": "swap", "file": state["tracks"]["t1"]["path"]}}
    write_state(paths, state)
    choose_music(tmp_path, monkeypatch)
    with_batches(paths)
    with_report(paths, STAMP)
    paths.operations_log.write_text("\n".join([
        log_line(STEP, "t1", "upgrade_same_track", "Vatoz Locoz", "Gimme Gimme"),
        "this line is not json",
        log_line(OUTSIDE, "t1", "upgrade_same_track", "Vatoz Locoz", "Gimme Gimme"),
        log_line(NEVER, "t3", "never download", "Some Artist", "Gone Track"),
        log_line("2026-11-12T11:00:00", "t3", "hide", "Some Artist", "Gone Track", result="failed"),
    ]) + "\n")
    return paths


def at(monkeypatch, moment: datetime):
    """The command line's api on the hub fixtures' services with the clock at `moment`: `today` and `7d` are read
    against it, never the real clock (the fixtures' dates are fixed)."""
    def default():
        resolved = library.resolve_paths()
        api = CliApi(resolved.support, None, services(now=lambda: moment))
        api._attach(resolved.paths)
        return api
    monkeypatch.setattr(bind, "default", default)


def history(argv, capsys):
    code = cli.main(["history", *argv, "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_history_lists_runs_batches_and_steps_newest_first_and_leaves_out_a_batchs_own_step(lib, capsys):
    code, env = history([], capsys)
    assert code == 0 and env["outcome"] == "ok" and env["data"]["since"] is None
    entries = env["data"]["entries"]
    assert [e["kind"] for e in entries] == ["batch", "operation", "batch", "operation", "run", "batch"]
    assert [e["id"] for e in entries] == ["aiff:2", None, "moves:1", None, "report:" + STAMP, "aiff:1"]
    assert [e["at"] for e in entries] == ["2026-11-12T18:30:00", NEVER, "2026-11-11T12:00:00", OUTSIDE,
                                          "2026-11-10T11:00:00", "2026-11-10T09:00:00"]
    assert all((e["undo"] is None) != (e["cant_text"] is None) for e in entries)   # a failed step is not listed


def test_each_entry_says_what_happened_and_how_to_undo_it_or_why_not(lib, capsys):
    _, env = history([], capsys)
    stopped, never, tidy, step, run, upgrade = env["data"]["entries"]
    assert (stopped["text"], stopped["undo"], stopped["cant_text"]) == (
        "Made AIFF · 0 of 1 done", None, words.NOTHING_DONE)
    assert never["text"] == "Some Artist - Gone Track: set to never download"
    assert (never["track_id"], never["artist"], never["title"]) == ("t3", "Some Artist", "Gone Track")
    assert never["undo"] is None and never["cant_text"] == words.UNDO_NOT_YET.format(command="track download t3")
    assert (tidy["text"], tidy["undo"], tidy["cant_text"]) == ("Tidy-up · 0 files moved · 1 not moved", None,
                                                              words.NOTHING_DONE)
    assert (step["text"], step["undo"], step["cant_text"]) == (
        "Vatoz Locoz - Gimme Gimme: better version put in", "track undo t1", None)
    assert run["text"] == "Sync: 2 lossless, 0 lossy, 0 moved, 0 to look at"
    assert (run["undo"], run["cant_text"]) == (None, words.RUN_CANT)
    assert (upgrade["text"], upgrade["undo"], upgrade["cant_text"]) == (
        "Better versions put in · 1 of 2 done", "batch undo aiff:1", None)


def test_the_undo_command_of_a_batch_is_a_line_the_parser_takes(lib, capsys):
    _, env = history([], capsys)
    (line,) = [e["undo"] for e in env["data"]["entries"] if e["undo"] and e["undo"].startswith("batch undo")]
    code = cli.main([*line.split(), "--dry-run", "--json"])
    assert code == 0 and json.loads(capsys.readouterr().out)["outcome"] == "ok"


def test_a_step_that_is_not_the_songs_latest_says_so(lib, capsys):
    lib.operations_log.write_text(lib.operations_log.read_text() + log_line(
        "2026-11-12T12:00:00", "t1", "aiff_rename", "Vatoz Locoz", "Gimme Gimme") + "\n")
    _, env = history([], capsys)
    steps = {e["text"].split(": ")[1]: e for e in env["data"]["entries"] if e["track_id"] == "t1"}
    assert steps["given its clean name"]["undo"] == "track undo t1"
    later = steps["better version put in"]
    assert (later["at"], later["undo"], later["cant_text"]) == (OUTSIDE, None, words.LATER_STEP)


def test_since_takes_an_iso_date_or_time(lib, capsys):
    _, env = history(["--since", "2026-11-11"], capsys)
    assert [e["at"] for e in env["data"]["entries"]] == ["2026-11-12T18:30:00", NEVER, "2026-11-11T12:00:00", OUTSIDE]
    assert env["data"]["since"].startswith("2026-11-11T00:00:00")
    _, env = history(["--since", "2026-11-11T12:00:00"], capsys)
    assert [e["id"] for e in env["data"]["entries"]] == ["aiff:2", None, "moves:1"]
    code, env = history(["--since", "soon"], capsys)
    assert code == 2 and (env["outcome"], env["reason"]) == ("bad_args", "usage")


def test_since_today_and_a_number_of_days_are_read_against_the_clock_of_the_api(lib, monkeypatch, capsys):
    at(monkeypatch, datetime(2026, 11, 13, 12, 0, 0))
    expected = {"today": 0, "1d": 1, "yesterday": 2, "3d": 4, "7d": 6}   # the fixtures' dates, from 11-10 to 11-12
    got = {word: len(history(["--since", word], capsys)[1]["data"]["entries"]) for word in expected}
    assert got == expected


def test_history_pages_through_the_envelope(lib, capsys):
    _, env = history(["--limit", "2"], capsys)
    assert [e["id"] for e in env["data"]["entries"]] == ["aiff:2", None]
    assert env["page"] == {"list": "entries", "offset": 0, "limit": 2, "total": 6, "next_offset": 2}
    _, env = history(["--limit", "2", "--offset", "4"], capsys)
    assert [e["id"] for e in env["data"]["entries"]] == ["report:" + STAMP, "aiff:1"] and env["page"]["next_offset"] is None


def test_history_text_page_prints_each_entry_with_its_undo(lib, capsys):
    assert cli.main(["history"]) == 0
    out = capsys.readouterr().out
    assert "batch undo aiff:1" in out and "track undo t1" in out and words.RUN_CANT in out


def test_history_of_a_library_with_nothing_in_it_is_an_empty_list(tmp_path, monkeypatch, capsys):
    make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    code, env = history([], capsys)
    assert code == 0 and env["data"] == {"entries": [], "since": None}


def test_history_needs_a_music_folder(tmp_path, capsys):
    code, env = history([], capsys)          # conftest: an empty support folder, no Setup done
    assert code == 7 and (env["outcome"], env["reason"]) == ("refused", "no_library")


def test_a_tidy_up_whose_files_moved_again_has_nothing_left_to_undo(lib, capsys):
    """A done move batch (one file moved, its file no longer where it went): the window reads "Nothing left to undo",
    and `history` does not offer `batch undo moves:2`."""
    from datetime import datetime

    from discjockey.models import PlannedMove
    with db.connect(lib.db_file) as conn:
        moves = [PlannedMove("file", None, "Song", "Library/Old/Song.aiff", "Library/New/Song.aiff", None, "import",
                             "playlist")]
        batch = db.start_batch(conn, started_by="tidy", about=None, undoes=None, moves=moves,
                               now=datetime(2026, 11, 12, 20, 0, 0))
        for move in db.batch_moves(conn, batch):
            db.finish_move(conn, move.id)
        db.close_batch(conn, batch, datetime(2026, 11, 12, 20, 0, 5))
    _, env = history([], capsys)
    (entry,) = [e for e in env["data"]["entries"] if e["id"] == f"moves:{batch}"]
    assert "1 file moved" in entry["text"]
    assert (entry["undo"], entry["cant_text"]) == (None, words.NOTHING_LEFT)


def test_a_step_that_was_undone_says_so_and_the_step_after_it_is_the_one_to_undo(lib, capsys):
    lib.operations_log.write_text("\n".join([
        log_line("2026-11-12T01:00:00", "t1", "upgrade_same_track", "Vatoz Locoz", "Gimme Gimme"),
        log_line("2026-11-12T02:00:00", "t1", "undo_upgrade", "Vatoz Locoz", "Gimme Gimme"),
        log_line("2026-11-12T03:00:00", "t1", "upgrade_same_track", "Vatoz Locoz", "Gimme Gimme"),
    ]) + "\n")
    _, env = history([], capsys)
    third, second, first = [e for e in env["data"]["entries"] if e["track_id"] == "t1"]
    assert (first["undo"], first["cant_text"]) == (None, words.UNDONE)
    assert (second["undo"], second["cant_text"]) == (None, words.WAS_UNDO)
    assert (third["undo"], third["cant_text"]) == ("track undo t1", None)


def test_a_batch_that_only_gave_clean_names_reads_as_the_window_words_it(lib, capsys):
    from datetime import datetime
    with db.connect(lib.db_file) as conn:
        batch = db.start_aiff_batch(conn, "convert", "make_aiff", None, [("t1", "rename")], datetime(2026, 11, 13, 9, 0, 0))
        db.set_aiff_item(conn, batch, 0, "done", None, {"path": "Library/Hard_Bounce/Vatoz Locoz - Gimme Gimme.aiff",
                                                           "note": "Renamed", "rekordbox": None})
        db.set_aiff_batch(conn, batch, state="done", ended=datetime(2026, 11, 13, 9, 1, 0))
    _, env = history([], capsys)
    (entry,) = [e for e in env["data"]["entries"] if e["id"] == f"aiff:{batch}"]
    assert entry["text"] == f"{words.BATCH_CLEAN_NAME} · 1 of 1 done"
