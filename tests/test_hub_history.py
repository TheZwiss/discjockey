"""`history.entries` (issue 39, phase 3, V3.3a): the pure rule that puts runs, batches and logged steps in one list with
each one's undo. Plain inputs; the command line's own pages are in tests/test_cli_history.py."""
import ast
from datetime import datetime
from pathlib import Path

import pytest

from discjockey import batches as batch_rule, folders, words
from discjockey.hub import history

NOW = datetime(2026, 11, 13, 12, 0, 0)
BUILT = {("batch_undo", "batch undo"), ("undo_upgrade", "track undo")}  # what the catalogue has built (phase 3)
UNDOABLE = {"path": "Library/A - B.aiff", "rekordbox_check": {"undo": {"file": "Library/A - B.aiff"}}}


def run(stamp="2026-11-10_110000", kind="sync", line=None):
    day, clock = stamp.split("_")
    return {"id": f"report:{stamp}", "run_id": stamp, "started": f"{day}T{clock[:2]}:{clock[2:4]}:00", "kind": kind,
            "counts": {"lossless": 2, "lossy": 1, "problems": 0, "moved": 3},
            "auto_upgrade": {"line": line} if line else None}


def aiff(n=1, started="2026-11-10T09:00:00", ended="2026-11-10T09:01:00", what="upgrade", started_by="user",
         state="done", done=2, total=2, undone=0):
    return {"id": f"aiff:{n}", "kind": "aiff", "batch": n, "what": what, "started_by": started_by, "state": state,
            "started": started, "ended": ended, "total": total, "done": done, "skipped": total - done - undone,
            "undone": undone, "undone_by": None}


def moves(n=1, started="2026-11-11T12:00:00", what="Tidy-up", started_by="tidy", state="done", done=3, skipped=1,
          undone_by=None):
    return {"id": f"moves:{n}", "kind": "moves", "batch": n, "what": what, "started_by": started_by, "state": state,
            "started": started, "ended": started, "total": done + skipped, "done": done, "skipped": skipped, "undone": 0,
            "undone_by": undone_by}


def op(operation, track="t1", time="2026-11-12T10:00:00", result="done", artist="A", title="B"):
    return {"time": time, "track_id": track, "artist": artist, "title": title, "operation": operation, "result": result,
            "message": ""}


def make(runs=(), batches=(), operations=(), *, tracks=None, batch_tracks=None, finished=None, built=BUILT, since=None):
    """`operations` are the lines in order: line numbers are their positions. `finished`: track -> line, by default the
    last line of each upgrade-like step, as `batches._finished_order` reads the log."""
    numbered = list(enumerate(operations))
    if finished is None:
        finished = {o["track_id"]: n for n, o in numbered
                    if o["operation"].startswith(batch_rule.LOG_PREFIXES) and o["result"] == "done"}
    return history.entries(list(runs), list(batches), numbered, tracks={"t1": UNDOABLE} if tracks is None else tracks,
                           batch_tracks=batch_tracks or {}, finished_order=finished,
                           built=lambda method, command: (method, command) in built, now=NOW, since=since)


def one(entry_list):
    (entry,) = entry_list
    return entry


def test_a_run_lists_what_it_did_and_says_a_download_stays():
    e = one(make(runs=[run()]))
    assert (e["kind"], e["id"], e["at"], e["undo"], e["cant_text"]) == (
        "run", "report:2026-11-10_110000", "2026-11-10T11:00:00", None, words.RUN_CANT)
    assert e["text"] == "Sync: 2 lossless, 1 lossy, 3 moved, 0 to look at"
    assert (e["track_id"], e["artist"], e["title"]) == (None, None, None)


def test_an_auto_upgrade_only_run_says_its_line_or_that_there_was_nothing():
    assert one(make(runs=[run(kind="auto_upgrade_only", line="Upgraded 2 tracks.")]))["text"] == (
        "Auto-upgrade alone: Upgraded 2 tracks.")
    assert one(make(runs=[run(kind="auto_upgrade_only")]))["text"] == "Auto-upgrade alone: nothing to do"


@pytest.mark.parametrize("what, started_by, text", [
    ("upgrade", "user", "Better versions put in · 2 of 2 done"),
    ("convert", "make_aiff", "Made AIFF · 2 of 2 done"),
    ("mixed", "cdj_all", "Better versions put in and made AIFF · 2 of 2 done"),
    ("upgrade", "auto_upgrade", "Upgraded during your sync · 2 of 2 done"),
    ("upgrade", "download_again", "Upgraded during your sync · 2 of 2 done")])
def test_an_aiff_batch_says_what_it_did(what, started_by, text):
    assert one(make(batches=[aiff(what=what, started_by=started_by)]))["text"] == text


def test_a_done_aiff_batch_is_undone_by_batch_undo_and_a_move_batch_by_a_command_that_is_not_built_yet():
    second, first = make(batches=[aiff(), moves()])  # the move batch started later
    assert (first["kind"], first["id"], first["undo"], first["cant_text"]) == ("batch", "aiff:1", "batch undo aiff:1", None)
    assert (second["id"], second["text"]) == ("moves:1", "Tidy-up · 3 files moved · 1 not moved")
    assert second["undo"] is None and second["cant_text"] == words.UNDO_NOT_YET.format(command="batch undo moves:1")
    (built_too,) = make(batches=[moves()], built=BUILT | {("undo_moves", "batch undo")})
    assert built_too["undo"] == "batch undo moves:1" and built_too["cant_text"] is None


@pytest.mark.parametrize("batch, cant", [
    (aiff(state="running", ended=None), words.STILL_RUNNING),
    (aiff(started_by="undo"), words.WAS_UNDO),
    (aiff(done=0, undone=2), words.UNDONE),
    (aiff(done=0, total=2), words.NOTHING_DONE),
    (moves(state="running"), words.STILL_RUNNING),
    (moves(started_by="undo"), words.WAS_UNDO),
    (moves(undone_by="moves:3"), words.UNDONE_BY.format(id="moves:3")),
    (moves(done=0), words.NOTHING_DONE)])
def test_a_batch_that_cannot_be_undone_says_why(batch, cant):
    e = one(make(batches=[batch]))
    assert e["undo"] is None and e["cant_text"] == cant


def test_a_stopped_or_partly_undone_aiff_batch_can_still_be_undone():
    stopped, partly = (one(make(batches=[b])) for b in (aiff(state="stopped", done=1, total=2),
                                                         aiff(done=1, undone=1)))
    assert stopped["undo"] == partly["undo"] == "batch undo aiff:1"


def test_a_step_names_the_song_and_what_happened():
    e = one(make(operations=[op("hide", artist="Armin", title="Naughty")], built=BUILT | {("hide", "track unhide")}))
    assert (e["kind"], e["id"], e["at"], e["text"], e["track_id"], e["artist"], e["title"]) == (
        "operation", None, "2026-11-12T10:00:00", "Armin - Naughty: hidden", "t1", "Armin", "Naughty")
    assert e["undo"] == "track unhide t1" and e["cant_text"] is None
    assert one(make(operations=[op("move_to_superseded", track="", artist=None, title=None)]))["text"] == (
        words.OPERATION_WORDS[folders.SUPERSEDE])
    assert one(make(operations=[op("something new")]))["text"] == "A - B: something new"


@pytest.mark.parametrize("name", sorted(history._TRACK_UNDO))
def test_the_latest_step_of_a_song_is_undone_by_track_undo(name):
    e = one(make(operations=[op(name)]))
    assert (e["undo"], e["cant_text"]) == ("track undo t1", None)


def test_a_step_that_is_not_the_latest_or_cannot_be_undone_says_why():
    latest, earlier = make(operations=[op("upgrade_same_track", time="2026-11-12T10:00:00"),
                                      op("aiff_rename", time="2026-11-12T11:00:00")])
    assert latest["undo"] == "track undo t1"
    assert (earlier["undo"], earlier["cant_text"]) == (None, words.LATER_STEP)
    changed = one(make(operations=[op("aiff_convert")], tracks={"t1": {"path": "Library/other.aiff",
                                                                          "rekordbox_check": {"undo": {"file": "x"}}}}))
    assert changed["cant_text"] == words.CANT_UNDO_NOW
    assert one(make(operations=[op("aiff_convert")], tracks={}))["cant_text"] == words.SONG_GONE
    assert one(make(operations=[op("aiff_convert")], built=set()))["cant_text"] == words.UNDO_NOT_YET.format(
        command="track undo t1")


@pytest.mark.parametrize("name, cant", [
    ("upgrade_discard", words.DISCARD_CANT), ("undo_upgrade", words.WAS_UNDO), ("undo_convert", words.WAS_UNDO),
    ("undo_rename", words.WAS_UNDO), ("rekordbox_checked", words.CHECKED_CANT),
    ("move_to_superseded", words.SUPERSEDED_CANT), ("download again", words.DOWNLOAD_CANT),
    ("removed from library", words.REMOVED_CANT), ("add_bought_file", words.NEW_VERSION_CANT),
    ("use_candidate", words.NEW_VERSION_CANT), ("use_link", words.NEW_VERSION_CANT),
    ("reject_current", words.UNKNOWN_CANT), ("not a name anyone writes", words.UNKNOWN_CANT)])
def test_a_step_nothing_undoes_says_why(name, cant):
    e = one(make(operations=[op(name)]))
    assert (e["undo"], e["cant_text"]) == (None, cant)


@pytest.mark.parametrize("name, command", [("never download", "track download t1"), ("download allowed", "track never t1"),
                                           ("hide", "track unhide t1"), ("unhide", "track hide t1")])
def test_the_switches_are_undone_by_their_opposite_once_it_is_built(name, command):
    planned = one(make(operations=[op(name)]))
    assert planned["undo"] is None and planned["cant_text"] == words.UNDO_NOT_YET.format(command=command)
    verb = tuple(command.split()[:2])
    method = "never_download" if name.startswith(("never", "download allowed")) else "hide"
    built = one(make(operations=[op(name)], built=BUILT | {(method, " ".join(verb))}))
    assert (built["undo"], built["cant_text"]) == (command, None)


def test_exactly_one_of_undo_and_cant_text_is_set_for_every_entry():
    names = sorted(history.OPERATIONS) + ["other"]
    ops = [op(name, track=f"t{n}") for n, name in enumerate(names)]
    listed = make(runs=[run()], batches=[aiff(), moves(), aiff(2, state="running")], operations=ops,
                  tracks={f"t{n}": UNDOABLE for n in range(len(names))}, built=BUILT | {("hide", "track hide")})
    assert len(listed) == 4 + len(names)
    assert all((e["undo"] is None) != (e["cant_text"] is None) for e in listed)


def test_a_step_an_aiff_batch_made_is_not_listed_but_the_same_step_outside_it_is():
    batch = aiff(started="2026-11-10T09:00:00", ended="2026-11-10T09:01:00")
    inside = op("upgrade_same_track", "t1", "2026-11-10T09:00:30")
    later = op("upgrade_same_track", "t1", "2026-11-10T09:02:00")
    other_song = op("upgrade_same_track", "t9", "2026-11-10T09:00:30")
    batch_only = op("hide", "t1", "2026-11-10T09:00:30")
    listed = make(batches=[batch], operations=[inside, later, other_song, batch_only], batch_tracks={1: {"t1"}},
                  tracks={"t1": UNDOABLE, "t9": UNDOABLE})
    # newest first; the two steps of one second: the later log line first
    assert [(e["kind"], e["id"] or e["text"]) for e in listed] == [
        ("operation", "A - B: better version put in"), ("operation", "A - B: hidden"),
        ("operation", "A - B: better version put in"), ("batch", "aiff:1")]
    assert [e["track_id"] for e in listed[:3]] == ["t1", "t1", "t9"]  # `inside` and `other_song` are not both listed


def test_a_step_is_folded_from_the_second_the_batch_started_and_a_running_batch_runs_until_now():
    started = "2026-11-10T09:00:00.700000"  # the log is written to the second: its first line is dated .0
    first = op("aiff_convert", "t1", "2026-11-10T09:00:00")
    assert [e["kind"] for e in make(batches=[aiff(started=started)], operations=[first], batch_tracks={1: {"t1"}})] == ["batch"]
    running = aiff(state="running", ended=None, started="2026-11-13T11:00:00")
    step = op("aiff_convert", "t1", "2026-11-13T11:30:00")
    assert [e["kind"] for e in make(batches=[running], operations=[step], batch_tracks={1: {"t1"}})] == ["batch"]


def test_undo_steps_of_a_batch_are_folded_like_its_own():
    steps = [op("undo_upgrade", "t1", "2026-11-10T09:00:30")]
    assert [e["kind"] for e in make(batches=[aiff()], operations=steps, batch_tracks={1: {"t1"}})] == ["batch"]


def test_a_move_batch_folds_nothing():
    steps = [op("move_to_superseded", "t1", "2026-11-11T12:00:01")]
    assert [e["kind"] for e in make(batches=[moves()], operations=steps, batch_tracks={})] == ["operation", "batch"]


def test_a_step_that_did_not_finish_is_not_listed():
    assert make(operations=[op("hide", result="failed"), op("hide", result="changed")]) == []


def test_entries_are_newest_first_and_equal_times_keep_run_batch_step_order():
    at = "2026-11-10T11:00:00"
    listed = make(runs=[run("2026-11-10_110000"), run("2026-11-12_080000")],
                  batches=[aiff(started=at, ended=at), moves(started="2026-11-11T12:00:00")],
                  operations=[op("hide", "t1", at), op("unhide", "t1", at), op("hide", "t1", "2026-11-12T08:00:00")])
    assert [e["id"] or e["text"] for e in listed] == [
        "report:2026-11-12_080000", "A - B: hidden", "moves:1", "report:2026-11-10_110000", "aiff:1",
        "A - B: shown again", "A - B: hidden"]


def test_since_keeps_runs_batches_and_steps_from_that_time_on():
    everything = dict(runs=[run("2026-11-08_090000"), run("2026-11-12_080000")],
                      batches=[aiff(started="2026-11-08T09:00:00"), moves(started="2026-11-12T12:00:00")],
                      operations=[op("hide", time="2026-11-08T10:00:00"), op("unhide", time="2026-11-12T10:00:00")])
    assert len(make(**everything)) == 6
    kept = make(**everything, since="2026-11-10T00:00:00")
    assert sorted(e["kind"] for e in kept) == ["batch", "operation", "run"]
    assert all(e["at"] >= "2026-11-10" for e in kept)
    assert make(**everything, since="2026-11-13T00:00:00") == []


def test_a_stamp_that_cannot_be_read_is_kept_and_listed_last():
    odd = op("hide", time="not a time")
    listed = make(runs=[run()], operations=[odd], since="2026-11-01T00:00:00")
    assert [e["kind"] for e in listed] == ["run", "operation"]


# --- the names the code writes

CODE = Path(history.__file__).parents[1]


def _source_names() -> tuple[set[str], set[str]]:
    """The operation names the code passes to `log_operation` and to `HubApi._single` as plain strings, and the
    expressions it passes that are no string (their names are pinned by the constants below)."""
    literals, dynamic = set(), set()
    for source in CODE.rglob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            argument = node.args[4] if called == "log_operation" and len(node.args) > 4 else (
                node.args[0] if called == "_single" and node.args else None)
            if argument is None:
                continue
            names = [argument.body, argument.orelse] if isinstance(argument, ast.IfExp) else [argument]
            for name in names:
                if isinstance(name, ast.Constant):
                    literals.add(name.value)
                else:
                    dynamic.add(ast.unparse(name))
    return literals, dynamic


def test_history_knows_every_operation_name_the_code_writes():
    literals, dynamic = _source_names()
    written = {*batch_rule.OPERATIONS.values(), *batch_rule.UNDO_OPERATIONS.values(), folders.SUPERSEDE, *literals,
               "upgrade_add_new", "upgrade_discard",       # `f"upgrade_{mode}"`: `_each_work`'s two modes
               "use_candidate", "use_link"}                 # `find.kind`: `_replace_with`'s two
    assert written <= history.OPERATIONS
    assert history.OPERATIONS == set(words.OPERATION_WORDS)
    # a new call that builds its name some other way must be looked at, and its names added above
    assert dynamic == {"operation", "what", "f'upgrade_{mode}'", "SUPERSEDE", "UNDO_OPERATIONS[kind]",
                       "UNDO_OPERATIONS['rename']", "find.kind"}
