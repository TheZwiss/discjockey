"""Undo of a Same track that made a new AIFF (convert.undo_convert through upgrades.undo; design rekordbox-repoint
§5.9, plan stage B §0.8, §1.8, §5.2 B4): the files and the analysis files back to the byte, master.db back row by row
except the stamps, the `localUpdateCount` row and the lookup rows the step made; the refusals with nothing changed;
a crash at every step of the undo finished or rolled back at the next start. Libraries in tmp_path only
(tests/convert_helpers.py)."""
from __future__ import annotations

from pathlib import Path

import pytest
from mutagen.aiff import AIFF

from audio_helpers import needs_ffmpeg
from convert_helpers import NEW, PARKED, TID, make_env, run, session
from discjockey import convert, library, upgrades
from discjockey.library import load_state
from discjockey.rekordbox import anlz, backup, master
from discjockey.rekordbox import write as rbwrite
from discjockey.upgrades import UNDO_REFUSED, UndoRefused, UpgradeProblem
from rekordbox_helpers import diff, dump, writer

pytestmark = needs_ffmpeg
NAME = "Artist - Song"
STAMPS = {"rb_local_usn", "updated_at"}
LOOKUPS = {"djmdArtist", "djmdAlbum", "djmdLabel"}


class PowerOff(BaseException):
    """The Mac went off: nothing after it runs."""


def snapshot(env):
    return env.music(), dump(env.place.db), env.anlz_files(), load_state(env.paths)["tracks"][TID]


def assert_back(env, before, state):
    """As before the upgrade: music and analysis files byte for byte, master.db row by row except plan §0.8's
    columns, the song as it was, nothing pending, and the AIFF gone at the clean-up."""
    music, rows, analysis, entry = before
    assert env.music() == music
    assert env.anlz_files() == analysis
    for table, _id, column, old, new in diff(rows, dump(env.place.db)):
        if column == "<row>":
            assert table in LOOKUPS and old is None, (table, _id)  # a lookup row the step made stays
        elif table == "agentRegistry":
            assert column == "int_1"
        else:
            assert column in STAMPS, (table, _id, column, old, new)
    now = load_state(env.paths)
    assert state["pending"] == [] and now["pending"] == []
    assert {k: now["tracks"][TID].get(k) for k in entry} == entry
    library.clear_tmp(env.paths, now)
    assert not env.paths.undo.exists() or not list(env.paths.undo.rglob("*.aiff"))


def upgraded(env, monkeypatch):
    before = snapshot(env)
    _r, state = run(env)
    return before, state


def undo(env, state=None, s=None):
    state = load_state(env.paths) if state is None else state
    return upgrades.undo(env.paths, state, TID, session=s), state


def test_undo_puts_everything_back_to_the_byte(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    before, _state = upgraded(env, monkeypatch)
    assert diff(before[1], dump(env.place.db))  # the step changed rekordbox
    r, state = undo(env)
    assert (r.section, r.path) == ("upgrade_undone", env.old)
    assert r.note == f"the old file is back at {env.old}; the lossless version waits in {PARKED} again"
    assert_back(env, before, state)
    assert upgrades.ready(state, ["A"])[0][0] == TID  # the upgrade waits again


def test_undo_in_a_batchs_session(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    before, _state = upgraded(env, monkeypatch)
    with session(env) as s:
        _r, state = undo(env, s=s)
        assert s.backup is not None  # the undo's write, too, comes after a backup
    assert_back(env, before, state)


def test_a_title_the_user_changed_since_stays(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch, row={"Title": "Old Title"},
                   entry={"title": "Song"})
    before, state = upgraded(env, monkeypatch)
    assert state["tracks"][TID]["rekordbox_check"]["rekordbox"]["kept"] == ["title"]  # the user's own title
    con = writer(env.place.db)
    con.execute("UPDATE djmdContent SET ISRC = 'MINE' WHERE ID = '1'")  # an edit after the upgrade
    con.commit()
    con.close()
    r, state = undo(env)
    assert r.note.endswith("Kept your own ISRC in rekordbox.")
    with library_row(env) as row:
        assert row["ISRC"] == "MINE" and row["Title"] == "Old Title"
        assert row["FolderPath"] == str(env.paths.root / env.old)
    assert env.music() == before[0] and env.anlz_files() == before[2]


class library_row:
    """The track's row now, as a dict (read-only)."""

    def __init__(self, env):
        self.env = env

    def __enter__(self):
        with master.open_read(self.env.place, False) as m:
            cur = m.con.execute("SELECT * FROM djmdContent WHERE ID = '1'")
            return dict(zip([c[0] for c in cur.description], cur.fetchone()))

    def __exit__(self, *exc):
        return False


def test_no_rekordbox_track_needs_no_rekordbox(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch, holds_file=False)
    before, _state = upgraded(env, monkeypatch)
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: True)  # open: doesn't matter here
    _r, state = undo(env)
    assert dump(env.place.db) == before[1]
    assert env.music() == before[0] and state["pending"] == []


# --- refusals: nothing changed ---

def assert_unchanged(env, after, state):
    assert (env.music(), dump(env.place.db), env.anlz_files()) == after[:3]
    assert load_state(env.paths)["tracks"][TID] == after[3] and state["pending"] == []


def test_undo_refused_while_rekordbox_runs(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    upgraded(env, monkeypatch)
    after = snapshot(env)
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: True)
    state = load_state(env.paths)
    with pytest.raises(UndoRefused) as err:
        upgrades.undo(env.paths, state, TID)
    assert err.value.reason == "rekordbox_open" and str(err.value) == UNDO_REFUSED["rekordbox_open"]
    assert_unchanged(env, after, state)


def test_undo_refused_for_a_relocated_track(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    upgraded(env, monkeypatch)
    con = writer(env.place.db)
    con.execute("UPDATE djmdContent SET FolderPath = '/Users/dj/Music/Elsewhere.aiff' WHERE ID = '1'")
    con.commit()
    con.close()
    after = snapshot(env)
    state = load_state(env.paths)
    with pytest.raises(UndoRefused) as err:
        upgrades.undo(env.paths, state, TID)
    assert err.value.reason == "relocated" and "relocated?" in str(err.value)
    assert_unchanged(env, after, state)


def test_undo_refused_when_the_new_file_changed(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    upgraded(env, monkeypatch)
    f = AIFF(str(env.paths.root / NEW))
    f.tags["TIT2"].text = ["Edited"]  # the audio stays (content key), the bytes don't
    f.save()
    after = snapshot(env)
    state = load_state(env.paths)
    with pytest.raises(UpgradeProblem, match="changed since the upgrade"):
        upgrades.undo(env.paths, state, TID)
    assert_unchanged(env, after, state)


def test_rekordbox_opening_at_the_commit_rolls_the_undo_back(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    upgraded(env, monkeypatch)
    after = snapshot(env)
    calls = {"n": 0}

    def running():  # closed for the start, the read, the backup and the write's open; open at the commit check
        calls["n"] += 1
        return calls["n"] > 4

    state = load_state(env.paths)
    with session(env, running=running) as s, pytest.raises(UndoRefused) as err:
        upgrades.undo(env.paths, state, TID, session=s)
    assert err.value.reason == "rekordbox_open" and calls["n"] == 5
    assert_unchanged(env, after, state)


# --- a crash at every step ---

MARKS = {"restored": 1, "outcome": 2, "committed_unmarked": 3, "committed": 3}


def power_off(monkeypatch, at):
    def die(*a, **k):
        raise PowerOff

    if at == "journaled":
        monkeypatch.setattr(convert, "move_path", die)
        monkeypatch.setattr(convert, "end_op", die)
        return
    if at == "ended":
        monkeypatch.setattr(convert, "_end_undo", die)
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


def crash(env, monkeypatch, at):
    with monkeypatch.context() as m:
        power_off(m, at)
        with pytest.raises(PowerOff):
            undo(env)


def next_start(env):
    state = load_state(env.paths)
    library.clear_tmp(env.paths, state)
    messages = library.recover_pending(env.paths, state)
    library.clear_tmp(env.paths, state)
    return messages, state


@pytest.mark.parametrize("at", ["journaled", "restored", "outcome"])
def test_a_crash_before_the_commit_leaves_the_upgrade_standing(tmp_path, monkeypatch, at):
    env = make_env(tmp_path, monkeypatch)
    before, _state = upgraded(env, monkeypatch)
    after = snapshot(env)
    crash(env, monkeypatch, at)
    messages, state = next_start(env)
    assert messages == [(convert.UNDO_NOT_FINISHED.format(name=NAME), False)]
    assert_unchanged(env, after, state)
    _r, state = undo(env)  # and it can be undone again
    assert_back(env, before, state)


@pytest.mark.parametrize("at", ["committed_unmarked", "committed", "ended"])
def test_a_crash_after_the_commit_finishes_the_undo(tmp_path, monkeypatch, at):
    env = make_env(tmp_path, monkeypatch)
    before, _state = upgraded(env, monkeypatch)
    crash(env, monkeypatch, at)
    messages, state = next_start(env)
    assert messages == [(convert.UNDO_FINISHED.format(name=NAME), True)]
    assert_back(env, before, state)


def test_analysis_files_a_cut_off_undo_wrote_get_the_new_path_again(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    before, _state = upgraded(env, monkeypatch)
    after = snapshot(env)
    crash(env, monkeypatch, "restored")
    rec = load_state(env.paths)["pending"][0]["rekordbox"]["record"]
    for a in rec["anlz"]:  # as a power cut between the undo's analysis-file writes and its commit leaves them
        rbwrite.replace_bytes(Path(a["path"]), anlz.splice_ppth(anlz.read(Path(a["path"])), a["old_ppth"]))
    assert env.anlz_files() != after[2]
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: True)
    messages, state = next_start(env)
    assert messages == [(convert.UNDO_WAIT_REKORDBOX.format(name=NAME), False)]
    assert len(load_state(env.paths)["pending"]) == 1
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: False)
    messages, state = next_start(env)
    assert messages == [(convert.UNDO_NOT_FINISHED.format(name=NAME), False)]
    assert_unchanged(env, after, state)


def test_a_track_rekordbox_changed_during_the_crash_needs_help(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    upgraded(env, monkeypatch)
    crash(env, monkeypatch, "restored")
    con = writer(env.place.db)
    con.execute("UPDATE djmdContent SET FolderPath = '/Users/dj/Music/Elsewhere.aiff' WHERE ID = '1'")
    con.commit()
    con.close()
    messages, state = next_start(env)
    assert messages == [(convert.UNDO_NEEDS_HELP.format(name=NAME, old=env.old, new=NEW), False)]
    assert state["pending"] == [] and state["tracks"][TID]["path"] == NEW
    assert (env.paths.root / NEW).is_file() and (env.paths.root / env.superseded).is_file()


# --- the kept files and backups ---

def test_done_checked_deletes_the_kept_download_and_frees_the_backup(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    upgraded(env, monkeypatch)
    state = load_state(env.paths)
    u = state["tracks"][TID]["rekordbox_check"]["undo"]
    assert u["backup"] and u["file_sha256"]
    named = u["backup"]
    for n in range(4):  # four newer backups, so the step's is past the newest 3
        newer = backup.backups_dir(env.paths) / f"20991231T00000{n}Z"
        newer.mkdir(parents=True)
        (newer / "manifest.json").write_text(f'{{"created": "2099-12-31T00:00:0{n}"}}')
    library.clear_tmp(env.paths, state)
    assert backup.find(env.paths, named) is not None  # kept: the undo record names it
    library.forget_undo(env.paths, u)
    state["tracks"][TID] = {**state["tracks"][TID], "rekordbox_check": None}
    library.save_state(env.paths, state)
    library.clear_tmp(env.paths, state)
    assert backup.find(env.paths, named) is None and not (env.paths.root / u["held"]).exists()
    assert (env.paths.root / env.superseded).is_file()  # the old file stays in Superseded/
