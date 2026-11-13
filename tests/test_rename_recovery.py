"""Give it its clean name cut off (discjockey/rename.py `recover_rename`; plan stage D §5 D3; design rekordbox-repoint
§5.8): a crash before rekordbox's commit moves the file back to its old name (no rekordbox write to undo, so it never
waits for rekordbox unless an analysis file was already written), after the commit the step is finished, a track
rekordbox changed meanwhile needs help, another rekordbox library is decided by the marks, the batch is `stopped`, and
`library.recover_pending` runs it all at the next start. Libraries in tmp_path only."""
from __future__ import annotations

import pytest

from audio_helpers import needs_ffmpeg
from convert_helpers import PowerOff, TID
from discjockey import convert, library, rename
from discjockey.library import load_state
from discjockey.rekordbox import anlz, backup
from rekordbox_helpers import dump, writer
from rename_helpers import (
    AFTER_COMMIT, BEFORE_COMMIT, CLEAN, OLD, batch_row, file_facts_row, make_clean, next_start, power_off, run_rename,
    start_rename_batch,
)

pytestmark = needs_ffmpeg
NAME = "Artist - Song"


def snapshot(env):
    return env.music(), dump(env.place.db) if env.place else None, env.anlz_files(), \
        load_state(env.paths)["tracks"][TID], file_facts_row(env)


def crash(env, monkeypatch, at, batch=None):
    with monkeypatch.context() as m:
        power_off(m, at)
        with pytest.raises(PowerOff):
            run_rename(env, batch=batch)


def assert_as_before(env, before, state):
    music, master_rows, analysis, entry, facts = before
    assert env.music() == music and env.anlz_files() == analysis
    assert env.place is None or dump(env.place.db) == master_rows
    assert state["pending"] == [] and load_state(env.paths)["pending"] == []
    assert load_state(env.paths)["tracks"][TID] == entry and file_facts_row(env) == facts


# --- the step cut off ---

@pytest.mark.parametrize("at", BEFORE_COMMIT)
def test_a_crash_before_the_commit_puts_the_file_back(tmp_path, monkeypatch, at):
    env = make_clean(tmp_path, monkeypatch)
    before = snapshot(env)
    crash(env, monkeypatch, at)
    assert (env.paths.root / CLEAN).exists() == (at in ("placed", "record"))  # the move is where it was cut
    messages, state = next_start(env)
    assert messages == [(rename.NOT_FINISHED.format(name=NAME), False)]
    assert_as_before(env, before, state)
    _r, state = run_rename(env)  # and the step can be run again
    assert state["tracks"][TID]["path"] == CLEAN


@pytest.mark.parametrize("at", AFTER_COMMIT)
def test_a_crash_after_the_commit_finishes_the_step(tmp_path, monkeypatch, at):
    env = make_clean(tmp_path, monkeypatch)
    before_bytes = (env.paths.root / OLD).read_bytes()
    crash(env, monkeypatch, at)
    messages, state = next_start(env)
    assert messages == [(rename.FINISHED.format(name=NAME), True)]
    now = load_state(env.paths)
    e = now["tracks"][TID]
    assert state["pending"] == [] and now["pending"] == []
    assert e["path"] == CLEAN and (env.paths.root / CLEAN).read_bytes() == before_bytes
    assert not (env.paths.root / OLD).exists()
    assert e["rekordbox_check"]["reason"] == "renamed"
    assert e["rekordbox_check"]["undo"]["repoint"]["dbid"] == "1234567890"  # journaled before the commit
    assert anlz.ppth(anlz.read(env.dat())) == "?/Artist - Song.aiff"
    ((path, placed_by, codec, rate, bits, _kbps),) = file_facts_row(env)  # the file row follows with its facts
    assert (path, placed_by, codec, rate, bits) == ("A/Artist - Song.aiff", "import", "pcm_s16be", 44100, 16)


def test_a_crash_without_rekordbox_is_decided_by_whether_the_file_is_at_its_new_name(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch, holds_file=False)
    before = snapshot(env)
    crash(env, monkeypatch, "journaled")  # cut before the move: the file never left
    messages, state = next_start(env)
    assert messages == [(rename.NOT_FINISHED.format(name=NAME), False)]
    assert_as_before(env, before, state)
    crash(env, monkeypatch, "backed_up")  # without a rekordbox track the first mark is `placed`: the move was made
    assert (env.paths.root / CLEAN).is_file() and not (env.paths.root / OLD).exists()
    messages, state = next_start(env)
    assert messages == [(rename.FINISHED.format(name=NAME), True)]
    assert load_state(env.paths)["tracks"][TID]["path"] == CLEAN
    assert before[1] == dump(env.place.db)  # rekordbox never touched


def test_the_batch_the_crash_interrupted_is_stopped(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    batch = start_rename_batch(env)
    crash(env, monkeypatch, "placed", batch=(batch, 0))
    assert batch_row(env, batch).state == "running"
    next_start(env)
    row = batch_row(env, batch)
    assert (row.state, row.stop_reason) == ("stopped", "crash")
    assert [i.state for i in row.items] == ["planned"]  # Resume re-checks it


def test_a_crash_after_the_commit_marks_the_batch_item_done_with_the_step(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    batch = start_rename_batch(env)
    crash(env, monkeypatch, "committed", batch=(batch, 0))
    next_start(env)
    (item,) = batch_row(env, batch).items
    assert item.state == "done" and item.result["path"] == CLEAN


# --- rekordbox running, and what rekordbox changed ---

def test_recovery_before_anything_was_written_to_rekordbox_never_waits_for_it(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    before = snapshot(env)
    crash(env, monkeypatch, "placed")  # the file moved, rekordbox not touched
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: True)
    messages, state = next_start(env)
    assert messages == [(rename.NOT_FINISHED.format(name=NAME), False)]  # not "Quit rekordbox so …"
    assert_as_before(env, before, state)


def test_analysis_files_written_before_a_crash_come_back_from_the_backup_with_rekordbox_closed(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    before = snapshot(env)
    crash(env, monkeypatch, "placed")
    for path in (env.dat(), env.dat().with_suffix(".EXT")):  # a crash inside rekordbox's transaction
        path.write_bytes(anlz.splice_ppth(anlz.read(path), "?/Artist - Song.aiff"))
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: True)
    messages, _state = next_start(env)
    assert messages == [(rename.WAIT_REKORDBOX.format(name=NAME), False)]  # only now it waits for rekordbox to quit
    assert (env.paths.root / CLEAN).is_file()  # and the step stays pending
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: False)
    messages, state = next_start(env)
    assert messages == [(rename.NOT_FINISHED.format(name=NAME), False)]
    assert_as_before(env, before, state)


def test_a_track_rekordbox_changed_during_the_crash_needs_help_and_the_file_goes_back(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    crash(env, monkeypatch, "placed")
    con = writer(env.place.db)
    con.execute("UPDATE djmdContent SET FolderPath = '/Users/dj/Music/Elsewhere.aiff' WHERE ID = '1'")
    con.commit()
    con.close()
    messages, state = next_start(env)
    (message, ok), = messages
    assert not ok and message == rename.NEEDS_HELP.format(name=NAME, old=OLD, new=CLEAN)
    assert load_state(env.paths)["tracks"][TID]["path"] == OLD and (env.paths.root / OLD).is_file()
    assert not (env.paths.root / CLEAN).exists()


@pytest.mark.parametrize("at, done", [("placed", False), ("committed", True)])
def test_another_rekordbox_library_is_decided_by_the_commit_mark(tmp_path, monkeypatch, at, done):
    env = make_clean(tmp_path, monkeypatch)
    crash(env, monkeypatch, at)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(empty))  # this Mac has no rekordbox library now
    messages, state = next_start(env)
    words = rename.OTHER_MAC_DONE if done else rename.OTHER_MAC_UNDONE
    assert messages == [(words.format(name=NAME, old=OLD, new=CLEAN), done)]
    assert load_state(env.paths)["tracks"][TID]["path"] == (CLEAN if done else OLD)
    assert (env.paths.root / (CLEAN if done else OLD)).is_file()


def test_an_unreadable_library_makes_the_step_wait(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    crash(env, monkeypatch, "placed")
    monkeypatch.setattr("discjockey.rekordbox.master.KEYS", ("00" * 32,))
    messages, _state = next_start(env)
    assert messages == [(rename.UNREADABLE_WAIT.format(name=NAME), False)]
    assert (env.paths.root / CLEAN).is_file() and len(load_state(env.paths)["pending"]) == 1  # stays pending


def test_a_drive_that_is_away_makes_the_step_wait(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    crash(env, monkeypatch, "placed")
    monkeypatch.setattr(library, "online", lambda path, roots: False)
    messages, _state = next_start(env)
    (message, ok), = messages
    assert not ok and "isn't connected" in message
    assert len(load_state(env.paths)["pending"]) == 1


# --- a failure inside a running step is settled the same way, at once ---

def test_a_failure_after_the_commit_is_finished_right_away(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    real, calls = rename._finish, {"n": 0}

    def fails_once(paths, state, op):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("the disk said no")
        return real(paths, state, op)
    monkeypatch.setattr(rename, "_finish", fails_once)
    r, state = run_rename(env)  # recovery finished it: the result is the step's
    assert (r.section, r.path) == ("renamed", CLEAN) and calls["n"] == 2
    assert state["pending"] == [] and state["tracks"][TID]["path"] == CLEAN
    assert load_state(env.paths)["tracks"][TID]["rekordbox_check"]["reason"] == "renamed"


def test_a_failure_before_the_commit_puts_the_file_back_and_says_so(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    before = snapshot(env)

    def breaks(*a, **k):
        raise RuntimeError("the journal broke")
    monkeypatch.setattr(convert, "journal_record", breaks)  # raised inside rekordbox's transaction: rolled back
    with pytest.raises(convert.UpgradeProblem) as err:
        run_rename(env)
    assert "the journal broke" in str(err.value) and rename.NOT_FINISHED.format(name=NAME) in str(err.value)
    state = load_state(env.paths)
    assert (env.paths.root / OLD).is_file() and not (env.paths.root / CLEAN).exists()
    assert state["pending"] == [] and state["tracks"][TID] == before[3] and dump(env.place.db) == before[1]
    assert env.anlz_files() == before[2] and backup.backups(env.paths)  # the batch's backup stays
