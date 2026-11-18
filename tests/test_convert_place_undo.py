"""The placement for a missing file (`convert.place_parked`, issue 43, plan §4.5.3): its Undo (through
`upgrades.undo`, from the check's Undo and `track undo`) and its crash recovery at every cut point. The rolled-back
state is the song missing and marked, the parked download back in `Upgrades ready/`, nothing of rekordbox changed;
the undone state is the same, with the first `missing_since` and the row's old facts written back. Libraries in
tmp_path only (tests/convert_helpers.py, the helpers of tests/test_convert_place.py)."""
from __future__ import annotations

import numpy as np
import pytest

from audio_helpers import needs_ffmpeg
from convert_helpers import (
    AFTER_COMMIT, BEFORE_COMMIT, PARKED, TID, PowerOff, make_env, never, next_start, power_off, power_off_undo,
    session,
)
from discjockey import batches, convert, db, library, missing, rbstep, upgrades
from discjockey.align import Alignment
from discjockey.library import load_state
from discjockey.models import FileAudio
from discjockey.rekordbox import anlz, master
from discjockey.upgrades import UNDO_REFUSED, UndoRefused, UpgradeProblem
from rekordbox_helpers import diff, dump, writer
from test_convert_place import NEW, NOT_LOSSLESS_AIFF, SHIFTED, SINCE, make_missing, place, row_of

pytestmark = needs_ffmpeg
NAME = "Artist - Song"
STAMPS = {"rb_local_usn", "updated_at"}
FILE_COLUMNS = ("id, folder, path, size, mtime_ns, content_key, placed_by, missing_since, online, held, file_codec, "
                "file_rate, file_bits, file_kbps")
AFTER_COMMIT_WITHOUT_SUPERSEDED = [at for at in AFTER_COMMIT if at != "superseded"]  # a placement has no such step


def snapshot(env) -> dict:
    with db.connect(env.paths.db_file) as conn:
        files = conn.execute(f"SELECT {FILE_COLUMNS} FROM files ORDER BY id").fetchall()
    return {"music": env.music(), "rb": dump(env.place.db) if env.place else None, "anlz": env.anlz_files(),
            "entry": load_state(env.paths)["tracks"][TID], "files": files}


def make_placed_env(tmp_path, monkeypatch, **kw):
    """A missing song whose row has the old file's facts stored and is the user's own (so the undo has something to
    put back); (env, the snapshot before the placement)."""
    env = make_missing(tmp_path, monkeypatch, **kw)
    with db.connect(env.paths.db_file) as conn:
        (file_id,) = conn.execute("SELECT id FROM files").fetchone()
        db.set_file_facts(conn, file_id, FileAudio("pcm_s16be", 44100, 16, 1411))
        conn.execute("UPDATE files SET placed_by = 'user'")
        conn.commit()
    return env, snapshot(env)


def placed(tmp_path, monkeypatch, **kw):
    env, before = make_placed_env(tmp_path, monkeypatch, **kw)
    place(env)
    return env, before


def undo(env, state=None, s=None):
    state = load_state(env.paths) if state is None else state
    return upgrades.undo(env.paths, state, TID, session=s), state


def assert_rolled_back(env, before, state):
    """Everything as before the placement: the song missing and marked, its parked download waiting."""
    now = snapshot(env)
    assert now == before
    assert state["pending"] == [] and load_state(env.paths)["pending"] == []
    assert (env.paths.root / PARKED).is_file() and not (env.paths.root / NEW).exists()
    assert not (env.paths.tmp / TID).exists() and not env.paths.undo.exists()


def assert_undone(env, before, state):
    """As before the placement, but for what an undo leaves: `file_gone` cleared (Download again is offered), the
    placed file's render in .discjockey/undo/ (the clean-up deletes it)."""
    now = snapshot(env)
    assert now["music"] == before["music"] and now["anlz"] == before["anlz"] and now["files"] == before["files"]
    if env.place:
        for table, _id, column, _old, _new in diff(before["rb"], now["rb"]):
            assert column in STAMPS or (table == "agentRegistry" and column == "int_1"), (table, _id, column)
    entry = now["entry"]
    assert entry["file_gone"] is None and entry["missing_since"] == SINCE
    kept = lambda e: {k: v for k, v in e.items() if k != "file_gone" and v is not None}  # noqa: E731
    assert kept(entry) == kept(before["entry"])
    assert state["pending"] == [] and load_state(env.paths)["pending"] == []
    assert missing.why_not(TID, entry, state, "download_again") is None
    assert not (env.paths.tmp / TID).exists()
    library.clear_tmp(env.paths, load_state(env.paths))
    assert not env.paths.undo.exists() or not list(env.paths.undo.rglob("*.aiff"))


# --- the undo ---

def test_undo_puts_the_missing_state_back_and_the_song_can_be_placed_again(tmp_path, monkeypatch):
    env, before = placed(tmp_path, monkeypatch)
    root = env.paths.root
    new_bytes = (root / NEW).read_bytes()
    assert diff(before["rb"], dump(env.place.db))  # the placement changed rekordbox
    r, state = undo(env)
    assert (r.section, r.path) == ("upgrade_undone", NOT_LOSSLESS_AIFF)
    assert r.note == (f"the song's file is missing again ({NOT_LOSSLESS_AIFF}); the lossless version waits in "
                      f"{PARKED} again")
    assert row_of(env)["FolderPath"] == str(root / env.old)
    (render,) = env.paths.undo.rglob("*.aiff")  # Discjockey's render, for the clean-up; the download is back
    assert render.read_bytes() == new_bytes and not (root / NEW).exists() and (root / PARKED).is_file()
    assert_undone(env, before, state)

    # the row is a missing one again, so Download again places it a second time, as the first
    again, state = place(env)
    assert again.path == NEW and (root / NEW).read_bytes() == new_bytes


def test_undo_from_track_undo_and_in_a_batchs_session(tmp_path, monkeypatch):
    env, before = placed(tmp_path, monkeypatch)
    done = batches.undo(env.paths, [TID], running=never, place=env.place)
    assert (done.undone, done.refused, done.failed) == (1, 0, 0) and done.results[0].state == "undone"
    assert_undone(env, before, load_state(env.paths))
    (tmp_path / "again").mkdir()
    env, before = placed(tmp_path / "again", monkeypatch)
    with session(env) as s:
        _r, state = undo(env, s=s)
        assert s.backup is not None  # the undo's write, too, comes after a backup
    assert_undone(env, before, state)


@pytest.mark.parametrize("alignment", [Alignment("different", text="other edit"), None])
def test_undo_of_a_placement_that_left_rekordbox_alone_needs_no_rekordbox(tmp_path, monkeypatch, alignment):
    env, before = placed(tmp_path, monkeypatch, alignment=alignment)
    assert state_check(env)["repointed"] is False and state_check(env)["undo"]["repoint"] is None
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: True)  # open: doesn't matter here
    _r, state = undo(env)
    assert dump(env.place.db) == before["rb"]  # not a stamp changed
    assert_undone(env, before, state)


def state_check(env) -> dict:
    return load_state(env.paths)["tracks"][TID]["rekordbox_check"]


def test_without_rekordbox_the_placement_is_undone_too(tmp_path, monkeypatch):
    env, before = placed(tmp_path, monkeypatch, rekordbox=False)
    _r, state = undo(env)
    assert_undone(env, before, state)


def test_a_user_edit_in_rekordbox_after_the_placement_stays_through_the_undo(tmp_path, monkeypatch):
    env, before = placed(tmp_path, monkeypatch, row={"Title": "My Edit Name"})
    con = writer(env.place.db)
    con.execute("UPDATE djmdContent SET ISRC = 'MINE' WHERE ID = '1'")
    con.commit()
    con.close()
    r, _state = undo(env)
    assert "Kept" not in r.note  # the placement wrote no text column, so the undo has none to keep or put back
    row = row_of(env)
    assert row["ISRC"] == "MINE" and row["Title"] == "My Edit Name" and row["FolderPath"] == str(env.paths.root / env.old)


# --- refusals: the same as a Same track undo, with nothing changed ---

def refused(env, state=None, expect=UpgradeProblem, **match):
    after = snapshot(env)
    state = load_state(env.paths) if state is None else state
    with pytest.raises(expect, **match) as err:
        upgrades.undo(env.paths, state, TID)
    assert snapshot(env) == after and state["pending"] == [] and load_state(env.paths)["pending"] == []
    return err.value


def test_refused_while_rekordbox_runs(tmp_path, monkeypatch):
    env, _before = placed(tmp_path, monkeypatch)
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: True)
    err = refused(env, expect=UndoRefused)
    assert err.reason == "rekordbox_open" and str(err) == UNDO_REFUSED["rekordbox_open"]


def test_refused_for_a_track_relocated_in_rekordbox(tmp_path, monkeypatch):
    env, _before = placed(tmp_path, monkeypatch)
    con = writer(env.place.db)
    con.execute("UPDATE djmdContent SET FolderPath = '/Users/dj/Music/Elsewhere.aiff' WHERE ID = '1'")
    con.commit()
    con.close()
    assert refused(env, expect=UndoRefused).reason == "relocated"


def test_refused_when_the_new_files_audio_changed(tmp_path, monkeypatch):
    env, _before = placed(tmp_path, monkeypatch)
    path = env.paths.root / NEW
    data = bytearray(path.read_bytes())
    at = data.index(b"SSND") + 16
    data[at:at + 200] = bytes(b ^ 0x55 for b in data[at:at + 200])
    path.write_bytes(bytes(data))
    refused(env, match="changed since the upgrade")


def test_refused_when_the_kept_download_is_gone(tmp_path, monkeypatch):
    env, _before = placed(tmp_path, monkeypatch)
    (env.paths.root / state_check(env)["undo"]["held"]).unlink()
    refused(env, match="kept for the undo is gone")


@pytest.mark.parametrize("where", [NOT_LOSSLESS_AIFF, PARKED])
def test_refused_when_another_file_is_where_something_goes_back(tmp_path, monkeypatch, where):
    env, _before = placed(tmp_path, monkeypatch)
    (env.paths.root / where).parent.mkdir(parents=True, exist_ok=True)
    (env.paths.root / where).write_bytes(b"another file")
    refused(env, match=f"Another file is at {where}")


def test_refused_when_a_newer_version_waits_or_the_song_has_another_file(tmp_path, monkeypatch):
    env, _before = placed(tmp_path, monkeypatch)
    state = load_state(env.paths)
    state["tracks"][TID] = {**state["tracks"][TID], "upgrade": {"file": "Upgrades ready/A/Other.aiff"}}
    refused(env, state, match="Another better version is waiting")
    state = load_state(env.paths)
    state["tracks"][TID] = {**state["tracks"][TID], "path": "Library/A/Mine.aiff"}
    refused(env, state, match="another file now")


def test_rekordbox_opening_at_the_commit_rolls_the_undo_back(tmp_path, monkeypatch):
    env, _before = placed(tmp_path, monkeypatch)
    after = snapshot(env)
    calls = {"n": 0}

    def running():  # closed for the start, the read, the backup and the write's open; open at the commit check
        calls["n"] += 1
        return calls["n"] > 4

    state = load_state(env.paths)
    with session(env, running=running) as s, pytest.raises(UndoRefused) as err:
        upgrades.undo(env.paths, state, TID, session=s)
    assert err.value.reason == "rekordbox_open" and calls["n"] == 5
    assert snapshot(env) == after and state["pending"] == [] and load_state(env.paths)["pending"] == []


def test_done_checked_deletes_the_kept_download_and_nothing_else(tmp_path, monkeypatch):
    env, _before = placed(tmp_path, monkeypatch)
    state = load_state(env.paths)
    u = state["tracks"][TID]["rekordbox_check"]["undo"]
    assert (env.paths.root / u["held"]).is_file()
    library.forget_undo(env.paths, u)
    assert not (env.paths.root / u["held"]).exists() and (env.paths.root / NEW).is_file()
    assert not (env.paths.root / "Superseded").exists()


# --- a cut in the undo ---

def crash_undo(env, monkeypatch, at):
    with monkeypatch.context() as m:
        power_off_undo(m, at, placed=True)
        with pytest.raises(PowerOff):
            undo(env)


@pytest.mark.parametrize("at", ["journaled", "outcome"])
def test_a_cut_before_the_undos_commit_leaves_the_placement_standing(tmp_path, monkeypatch, at):
    env, before = placed(tmp_path, monkeypatch)
    after = snapshot(env)
    crash_undo(env, monkeypatch, at)
    messages, state = next_start(env)
    assert messages == [(convert.UNDO_NOT_FINISHED.format(name=NAME), False)]
    assert snapshot(env) == after and state["pending"] == []
    _r, state = undo(env)  # and it can be undone again
    assert_undone(env, before, state)


@pytest.mark.parametrize("at", ["committed_unmarked", "committed", "ended"])
def test_a_cut_after_the_undos_commit_finishes_it_with_the_first_date_and_the_old_facts(tmp_path, monkeypatch, at):
    env, before = placed(tmp_path, monkeypatch)
    crash_undo(env, monkeypatch, at)
    messages, state = next_start(env)
    assert messages == [(convert.UNDO_FINISHED.format(name=NAME), True)]
    assert_undone(env, before, state)


def test_a_cut_at_the_start_of_the_undo_of_a_placement_without_rekordbox_is_finished(tmp_path, monkeypatch):
    env, before = placed(tmp_path, monkeypatch, rekordbox=False)
    crash_undo(env, monkeypatch, "journaled")
    messages, state = next_start(env)
    assert messages == [(convert.UNDO_FINISHED.format(name=NAME), True)]
    assert_undone(env, before, state)


def test_a_cut_at_the_end_of_the_undo_without_rekordbox_is_finished(tmp_path, monkeypatch):
    env, before = placed(tmp_path, monkeypatch, rekordbox=False)
    crash_undo(env, monkeypatch, "ended")
    messages, state = next_start(env)
    assert messages == [(convert.UNDO_FINISHED.format(name=NAME), True)]
    assert_undone(env, before, state)


# --- a cut in the placement itself: rolled back before rekordbox's commit, finished after it ---

def crash_place(env, monkeypatch, at):
    with monkeypatch.context() as m:
        power_off(m, at)
        with pytest.raises(PowerOff):
            place(env)


@pytest.mark.parametrize("at", BEFORE_COMMIT)
def test_a_cut_before_the_commit_rolls_back_to_a_missing_marked_song_that_places_again(tmp_path, monkeypatch, at):
    env, before = make_placed_env(tmp_path, monkeypatch)
    crash_place(env, monkeypatch, at)
    messages, state = next_start(env)
    assert messages == ([] if at == "rendered" else [(convert.PLACED_WORDS[convert.NOT_FINISHED].format(name=NAME), False)])
    assert_rolled_back(env, before, state)
    r, _state = place(env)  # the next sync tries again
    assert r.path == NEW and (env.paths.root / NEW).is_file()


@pytest.mark.parametrize("at", AFTER_COMMIT_WITHOUT_SUPERSEDED)
def test_a_cut_after_the_commit_finishes_the_placement(tmp_path, monkeypatch, at):
    env, before = make_placed_env(tmp_path, monkeypatch)
    crash_place(env, monkeypatch, at)
    messages, state = next_start(env)
    assert messages == [(convert.PLACED_WORDS[convert.FINISHED].format(name=NAME), True)]
    e = load_state(env.paths)["tracks"][TID]
    root = env.paths.root
    assert e["path"] == NEW and e["upgrade"] is None and e["file_gone"] is None and e["missing_since"] is None
    assert state["pending"] == [] and load_state(env.paths)["pending"] == []
    assert (root / NEW).is_file() and (root / e["rekordbox_check"]["undo"]["held"]).is_file()
    assert not (root / "Superseded").exists() and not (root / PARKED).exists() and not (env.paths.tmp / TID).exists()
    assert row_of(env)["FolderPath"] == str(root / NEW)
    assert e["rekordbox_check"]["undo"]["missing_since"] == SINCE  # the finished step still has its undo
    _r, state = undo(env)
    assert_undone(env, before, state)


def test_analysis_files_written_before_a_cut_come_back_from_the_backup(tmp_path, monkeypatch):
    env, before = make_placed_env(tmp_path, monkeypatch)
    crash_place(env, monkeypatch, "placed")
    for path in (env.dat(), env.dat().with_suffix(".EXT")):  # what a cut inside rekordbox's transaction leaves
        path.write_bytes(anlz.splice_ppth(anlz.read(path), "?/Artist - Song.aiff"))
    messages, state = next_start(env)
    assert messages == [(convert.PLACED_WORDS[convert.NOT_FINISHED].format(name=NAME), False)]
    assert_rolled_back(env, before, state)


def test_rekordbox_open_while_analysis_files_must_come_back_waits_then_rolls_back(tmp_path, monkeypatch):
    env, before = make_placed_env(tmp_path, monkeypatch)
    crash_place(env, monkeypatch, "placed")
    for path in (env.dat(), env.dat().with_suffix(".EXT")):
        path.write_bytes(anlz.splice_ppth(anlz.read(path), "?/Artist - Song.aiff"))
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: True)
    messages, _state = next_start(env)
    assert messages == [(convert.WAIT_REKORDBOX.format(name=NAME), False)]
    assert len(load_state(env.paths)["pending"]) == 1
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: False)
    messages, state = next_start(env)
    assert messages == [(convert.PLACED_WORDS[convert.NOT_FINISHED].format(name=NAME), False)]
    assert_rolled_back(env, before, state)


def test_a_track_rekordbox_changed_during_the_cut_needs_the_users_help_and_the_song_stays_missing(tmp_path, monkeypatch):
    env, before = make_placed_env(tmp_path, monkeypatch)
    crash_place(env, monkeypatch, "committed")
    con = writer(env.place.db)
    con.execute("UPDATE djmdContent SET FolderPath = '/Users/dj/Music/Elsewhere.aiff' WHERE ID = '1'")
    con.commit()
    con.close()
    after = dump(env.place.db)
    messages, state = next_start(env)
    root = env.paths.root
    assert messages == [(convert.PLACED_WORDS[convert.NEEDS_HELP].format(name=NAME, old=NOT_LOSSLESS_AIFF, new=NEW),
                         False)]
    assert dump(env.place.db) == after  # rekordbox left alone
    e = load_state(env.paths)["tracks"][TID]
    assert e["path"] == NOT_LOSSLESS_AIFF and e["missing_since"] == SINCE and e["upgrade"]["file"] == PARKED
    assert (root / PARKED).is_file() and not (root / NEW).exists() and state["pending"] == []


@pytest.mark.parametrize("at, finished", [("journaled", False), ("placed", True)])
def test_a_cut_in_a_placement_without_rekordbox_is_decided_by_the_placed_file(tmp_path, monkeypatch, at, finished):
    env, before = make_placed_env(tmp_path, monkeypatch, rekordbox=False)
    with monkeypatch.context() as m:
        die = _die
        for name in ("_drop", "_roll_back", "_settle"):
            m.setattr(convert, name, die)
        if at == "journaled":
            m.setattr(convert, "move_path", die)  # the cut falls before the file moves
        else:
            _cut_first_mark(m)
        with pytest.raises(PowerOff):
            place(env)
    messages, state = next_start(env)
    if finished:
        assert messages == [(convert.PLACED_WORDS[convert.FINISHED].format(name=NAME), True)]
        assert load_state(env.paths)["tracks"][TID]["path"] == NEW and (env.paths.root / NEW).is_file()
    else:
        assert messages == [(convert.PLACED_WORDS[convert.NOT_FINISHED].format(name=NAME), False)]
        assert_rolled_back(env, before, state)


def _die(*a, **k):
    raise PowerOff


def _cut_first_mark(monkeypatch):
    real = convert.mark_op

    def mark(paths, state, op):
        real(paths, state, op)
        raise PowerOff
    monkeypatch.setattr(convert, "mark_op", mark)

