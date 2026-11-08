"""A convert step cut off at every point (plan stage B §1.8, §5.2 B3): before rekordbox's commit the next start puts
everything back as it was (files, analysis files, master.db row by row), after it the step is finished. rekordbox open
while analysis files must come back → the step waits; another rekordbox library → the files only; the batch →
stopped. A power cut is `PowerOff`: no clean-up of the step runs after it (as when the Mac goes off)."""
from __future__ import annotations

import shutil

import pytest

from audio_helpers import needs_ffmpeg
from convert_helpers import NEW, TID, batch_row, make_env, run, start_batch
from discjockey import convert, library
from discjockey.library import load_state
from discjockey.rekordbox import anlz, master
from discjockey.rekordbox.session import Session
from rekordbox_helpers import dump, make_master, writer

pytestmark = needs_ffmpeg
NAME = "Artist - Song"


class PowerOff(BaseException):
    """The Mac went off: nothing after it runs."""


MARKS = {"backed_up": 1, "placed": 2, "record": 3, "committed_unmarked": 4, "committed": 4, "superseded": 5}
BEFORE_COMMIT = ["rendered", "journaled", "backed_up", "placed", "record"]
AFTER_COMMIT = ["committed_unmarked", "committed", "superseded", "ended"]


def power_off(monkeypatch, at: str) -> None:
    """Cut the step at `at`: after the render, the journal, a mark (written first, except `committed_unmarked`:
    rekordbox committed, its mark not written), or inside the end."""
    def die(*a, **k):
        raise PowerOff

    for name in ("_drop", "_roll_back", "_settle"):  # the step's own clean-up never runs after a power cut
        monkeypatch.setattr(convert, name, die)
    if at == "rendered":
        monkeypatch.setattr(convert, "journal_op", die)
        return
    if at == "journaled":
        monkeypatch.setattr(Session, "ensure_backup", die)
        return
    if at == "ended":
        monkeypatch.setattr(convert, "end_op", die)
        return
    real, calls = convert.mark_op, {"n": 0}

    def mark(paths, state, op):
        calls["n"] += 1
        if calls["n"] == MARKS[at]:
            if at != "committed_unmarked":
                real(paths, state, op)
            raise PowerOff
        real(paths, state, op)
    monkeypatch.setattr(convert, "mark_op", mark)


def crash(env, monkeypatch, at, batch=None):
    with monkeypatch.context() as m:
        power_off(m, at)
        with pytest.raises(PowerOff):
            run(env, batch=batch)


def next_start(env):
    state = load_state(env.paths)
    library.clear_tmp(env.paths, state)
    messages = library.recover_pending(env.paths, state)
    library.clear_tmp(env.paths, state)
    return messages, state


def snapshot(env):
    return env.music(), dump(env.place.db), env.anlz_files(), load_state(env.paths)["tracks"][TID]


def assert_as_before(env, before, state):
    music, master_rows, analysis, entry = before
    assert env.music() == music
    assert dump(env.place.db) == master_rows
    assert env.anlz_files() == analysis
    assert state["pending"] == [] and load_state(env.paths)["pending"] == []
    assert load_state(env.paths)["tracks"][TID] == entry
    assert not (env.paths.tmp / TID).exists() and not env.paths.undo.exists()


def assert_finished(env, state):
    e = load_state(env.paths)["tracks"][TID]
    assert state["pending"] == [] and load_state(env.paths)["pending"] == []
    assert e["path"] == NEW and e["upgrade"] is None and (env.paths.root / NEW).is_file()
    assert (env.paths.root / env.superseded).is_file() and not (env.paths.root / env.old).exists()
    assert (env.paths.root / e["rekordbox_check"]["undo"]["held"]).is_file()
    with master.open_read(env.place, False) as m:
        assert m.con.execute("SELECT FolderPath FROM djmdContent WHERE ID = '1'").fetchone()[0] == \
            str(env.paths.root / NEW)
    assert not (env.paths.tmp / TID).exists()
    return e


@pytest.mark.parametrize("at", BEFORE_COMMIT)
def test_a_crash_before_the_commit_puts_everything_back(tmp_path, monkeypatch, at):
    env = make_env(tmp_path, monkeypatch)
    before = snapshot(env)
    crash(env, monkeypatch, at)
    messages, state = next_start(env)
    assert messages == ([] if at == "rendered" else [(convert.NOT_FINISHED.format(name=NAME), False)])
    assert_as_before(env, before, state)


@pytest.mark.parametrize("at", AFTER_COMMIT)
def test_a_crash_after_the_commit_finishes_the_step(tmp_path, monkeypatch, at):
    env = make_env(tmp_path, monkeypatch)
    old = (env.paths.root / env.old).read_bytes()
    crash(env, monkeypatch, at)
    messages, state = next_start(env)
    assert messages == [(convert.FINISHED.format(name=NAME), True)]
    e = assert_finished(env, state)
    assert (env.paths.root / env.superseded).read_bytes() == old
    assert e["rekordbox_check"]["undo"]["repoint"]["dbid"] == "1234567890"  # journaled before the commit
    assert anlz.ppth(anlz.read(env.dat())) == "?/Artist - Song.aiff"


def splice_now(env):
    """What a crash inside rekordbox's transaction leaves: the analysis files already hold the new bytes."""
    for path in (env.dat(), env.dat().with_suffix(".EXT")):
        path.write_bytes(anlz.splice_ppth(anlz.read(path), "?/Artist - Song.aiff"))


def test_analysis_files_written_before_a_crash_come_back_from_the_backup(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    before = snapshot(env)
    crash(env, monkeypatch, "placed")
    splice_now(env)
    messages, state = next_start(env)
    assert messages == [(convert.NOT_FINISHED.format(name=NAME), False)]
    assert_as_before(env, before, state)


def test_rekordbox_open_while_analysis_files_must_come_back_waits(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    before = snapshot(env)
    crash(env, monkeypatch, "placed")
    splice_now(env)
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: True)
    messages, state = next_start(env)
    assert messages == [(convert.WAIT_REKORDBOX.format(name=NAME), False)]
    assert len(load_state(env.paths)["pending"]) == 1 and (env.paths.root / NEW).is_file()  # nothing decided yet
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: False)
    messages, state = next_start(env)
    assert messages == [(convert.NOT_FINISHED.format(name=NAME), False)]
    assert_as_before(env, before, state)


def test_a_commit_still_in_rekordboxs_wal_counts_as_committed(tmp_path, monkeypatch):
    """A crash right after COMMIT leaves the change in master.db-wal (rekordbox's WAL mode); recovery reads it."""
    env = make_env(tmp_path, monkeypatch)
    crash(env, monkeypatch, "placed")
    con = writer(env.place.db)
    con.execute("UPDATE djmdContent SET FolderPath = ? WHERE ID = '1'", (str(env.paths.root / NEW),))
    con.commit()
    kept = tmp_path / "kept"
    kept.mkdir()
    files = [env.place.db.with_name("master.db" + s) for s in ("", "-wal", "-shm")]
    for f in files:
        shutil.copyfile(f, kept / f.name)  # as the files were when the writer died
    con.close()
    for f in files:
        shutil.copyfile(kept / f.name, f)
    messages, state = next_start(env)
    assert messages == [(convert.FINISHED.format(name=NAME), True)]
    e = load_state(env.paths)["tracks"][TID]
    assert e["path"] == NEW and (env.paths.root / env.superseded).is_file()


def test_a_track_rekordbox_changed_since_needs_the_users_help(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    music = env.music()
    crash(env, monkeypatch, "placed")
    con = writer(env.place.db)
    con.execute("UPDATE djmdContent SET FolderPath = '/Users/dj/Music/Elsewhere.mp3' WHERE ID = '1'")
    con.commit()
    con.close()
    rows = dump(env.place.db)
    messages, state = next_start(env)
    assert messages == [(convert.NEEDS_HELP.format(name=NAME, old=env.old, new=NEW), False)]
    assert env.music() == music and dump(env.place.db) == rows and state["pending"] == []


@pytest.mark.parametrize("library_now", ["none", "another"])
@pytest.mark.parametrize("at", ["placed", "committed"])
def test_another_rekordbox_library_gets_only_the_files_resolved(tmp_path, monkeypatch, library_now, at):
    env = make_env(tmp_path, monkeypatch)
    music, analysis = env.music(), env.anlz_files()
    crash(env, monkeypatch, at)
    elsewhere = tmp_path / "elsewhere"
    if library_now == "another":
        make_master(elsewhere, [{"ID": "1", "path": str(env.paths.root / env.old)}], dbid="999")
    else:
        elsewhere.mkdir()
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(elsewhere))
    after = env.anlz_files()
    messages, state = next_start(env)
    assert env.anlz_files() == after  # this Mac's rekordbox (or none) is left alone
    if at == "placed":
        assert messages == [(convert.OTHER_MAC_UNDONE.format(name=NAME, old=env.old), False)]
        assert env.music() == music and after == analysis
    else:
        assert messages == [(convert.OTHER_MAC_DONE.format(name=NAME, new=NEW), True)]
        assert load_state(env.paths)["tracks"][TID]["path"] == NEW


@pytest.mark.parametrize("at, item, batch_state, why", [("placed", "planned", "stopped", "crash"),
                                                         ("committed", "done", "done", None)])
def test_the_interrupted_batch_is_stopped(tmp_path, monkeypatch, at, item, batch_state, why):
    """A batch the crash cut off offers Resume; one whose last item recovery finished has nothing left, so it ends
    (batches.recover)."""
    env = make_env(tmp_path, monkeypatch)
    batch = start_batch(env)
    crash(env, monkeypatch, at, batch=(batch, 0))
    next_start(env)
    row = batch_row(env, batch)
    assert (row.state, row.stop_reason, row.items[0].state) == (batch_state, why, item)


def test_a_step_with_a_file_on_a_drive_that_is_away_waits(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    crash(env, monkeypatch, "placed")
    real = library.online
    monkeypatch.setattr(library, "online", lambda p, roots: "Old Name" not in str(p) and real(p, roots))
    messages, state = next_start(env)
    assert len(messages) == 1 and "isn't connected" in messages[0][0] and messages[0][1] is False
    assert len(load_state(env.paths)["pending"]) == 1


@pytest.mark.parametrize("placed", [False, True])
def test_without_rekordbox_the_step_is_decided_by_the_placed_file(tmp_path, monkeypatch, placed):
    env = make_env(tmp_path, monkeypatch, rekordbox=False)
    music, entry = env.music(), load_state(env.paths)["tracks"][TID]
    with monkeypatch.context() as m:
        if placed:
            power_off(m, "backed_up")  # without rekordbox the first mark is `placed`
        else:
            power_off(m, "journaled")
            m.setattr(convert, "move_path", lambda *a, **k: (_ for _ in ()).throw(PowerOff()))
        with pytest.raises(PowerOff):
            run(env)
    messages, state = next_start(env)
    if placed:
        assert messages == [(convert.FINISHED.format(name=NAME), True)]
        assert load_state(env.paths)["tracks"][TID]["path"] == NEW
    else:
        assert messages == [(convert.NOT_FINISHED.format(name=NAME), False)]
        assert env.music() == music and load_state(env.paths)["tracks"][TID] == entry
