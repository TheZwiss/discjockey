"""Undo of Give it its clean name (rename.undo_rename through upgrades.undo; design rekordbox-repoint §5.9, plan stage D
§1.2, §5 D3): the file back to its old name, rekordbox's identity columns and `PPTH` back where they still hold what the
step wrote (the rest of the track untouched), the refusals with nothing changed, and a crash at every mark of the undo
finished or rolled back at the next start (`recover_rename_undo`). Libraries in tmp_path only."""
from __future__ import annotations

from pathlib import Path

import pytest

from audio_helpers import needs_ffmpeg
from convert_helpers import TID, PowerOff, session
from discjockey import convert, library, rename, report, upgrades
from discjockey.library import load_state
from discjockey.rekordbox import anlz, master
from discjockey.rekordbox import write as rbwrite
from discjockey.upgrades import UNDO_REFUSED, UNDO_REFUSED_RENAMED, UndoRefused, UpgradeProblem
from rekordbox_helpers import diff, dump, writer
from rename_helpers import CLEAN, OLD, file_facts_row, make_clean, next_start, power_off_undo, run_rename

pytestmark = needs_ffmpeg
NAME = "Artist - Song"
STAMPS = {"rb_local_usn", "updated_at"}


def snapshot(env):
    return (env.music(), dump(env.place.db) if env.place else None, env.anlz_files(),
            load_state(env.paths)["tracks"][TID], file_facts_row(env))


def renamed(tmp_path, monkeypatch, **kw):
    env = make_clean(tmp_path, monkeypatch, **kw)
    before = snapshot(env)
    run_rename(env)
    return env, before


def undo(env, state=None, s=None):
    state = load_state(env.paths) if state is None else state
    return upgrades.undo(env.paths, state, TID, session=s), state


def assert_back(env, before, state):
    music, rows, analysis, entry, facts = before
    assert env.music() == music and env.anlz_files() == analysis
    if rows is not None:
        for table, _id, column, _old, _new in diff(rows, dump(env.place.db)):
            assert column in STAMPS or table == "agentRegistry", (table, column)
    now = load_state(env.paths)
    assert state["pending"] == [] and now["pending"] == []
    assert {k: now["tracks"][TID].get(k) for k in entry} == entry and file_facts_row(env) == facts


def row_of(env) -> dict:
    with master.open_read(env.place, False) as m:
        cur = m.con.execute("SELECT * FROM djmdContent WHERE ID = '1'")
        return dict(zip([c[0] for c in cur.description], cur.fetchone()))


def test_undo_puts_the_old_name_and_rekordbox_back(tmp_path, monkeypatch):
    env, before = renamed(tmp_path, monkeypatch)
    assert upgrades.can_undo(load_state(env.paths)["tracks"][TID])
    r, state = undo(env)
    assert (r.section, r.path, r.note) == ("upgrade_undone", OLD, "the file is named Old Name.aiff again")
    assert_back(env, before, state)
    assert not upgrades.can_undo(state["tracks"][TID])  # the check before the step (none) is back: one step only
    assert row_of(env)["FolderPath"] == str(env.paths.root / OLD) and anlz.ppth(anlz.read(env.dat())) == "?/Old Name.aiff"


def test_undo_in_a_batchs_session(tmp_path, monkeypatch):
    env, before = renamed(tmp_path, monkeypatch)
    with session(env) as s:
        _r, state = undo(env, s=s)
        assert s.backup is not None  # the undo's write, too, comes after a backup
    assert_back(env, before, state)


def test_org_folder_path_goes_back_only_where_the_step_changed_it(tmp_path, monkeypatch):
    old_abs = str(tmp_path / "music" / OLD)
    env, before = renamed(tmp_path, monkeypatch, row={"OrgFolderPath": old_abs})
    assert row_of(env)["OrgFolderPath"] == str(env.paths.root / CLEAN)
    _r, state = undo(env)
    assert row_of(env)["OrgFolderPath"] == old_abs
    assert_back(env, before, state)


def test_what_the_user_changed_in_rekordbox_since_stays(tmp_path, monkeypatch):
    env, _before = renamed(tmp_path, monkeypatch)
    con = writer(env.place.db)
    con.execute("UPDATE djmdContent SET ISRC = 'MINE', Rating = 5 WHERE ID = '1'")
    con.commit()
    con.close()
    undo(env)
    row = row_of(env)
    assert (row["ISRC"], row["Rating"]) == ("MINE", 5) and row["FolderPath"] == str(env.paths.root / OLD)


def test_no_rekordbox_track_needs_no_rekordbox(tmp_path, monkeypatch):
    env, before = renamed(tmp_path, monkeypatch, holds_file=False)
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: True)  # open: doesn't matter here
    _r, state = undo(env)
    assert_back(env, before, state)


# --- refusals: nothing changed ---

def refused(env, error, words=None):
    after = snapshot(env)
    state = load_state(env.paths)
    with pytest.raises(error) as err:
        upgrades.undo(env.paths, state, TID)
    assert snapshot(env) == after and state["pending"] == []
    return err.value


def test_undo_refused_while_rekordbox_runs(tmp_path, monkeypatch):
    env, _ = renamed(tmp_path, monkeypatch)
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: True)
    err = refused(env, UndoRefused)
    assert err.reason == "rekordbox_open" and str(err) == UNDO_REFUSED_RENAMED["rekordbox_open"]
    assert "old name" in str(err) and str(err) != UNDO_REFUSED["rekordbox_open"]


def test_a_track_moved_in_rekordbox_since_is_refused(tmp_path, monkeypatch):
    env, _ = renamed(tmp_path, monkeypatch)
    con = writer(env.place.db)
    con.execute("UPDATE djmdContent SET FolderPath = '/Users/dj/Music/Elsewhere.aiff' WHERE ID = '1'")
    con.commit()
    con.close()
    err = refused(env, UndoRefused)
    assert err.reason == "relocated" and str(err) == UNDO_REFUSED_RENAMED["relocated"]


def test_another_file_at_the_old_name_is_refused(tmp_path, monkeypatch):
    env, _ = renamed(tmp_path, monkeypatch)
    (env.paths.root / OLD).write_bytes(b"someone else's file")
    err = refused(env, UpgradeProblem)
    assert str(err) == f"Another file is at {OLD} now, so the clean-name change can't be undone. Nothing was changed."
    assert (env.paths.root / OLD).read_bytes() == b"someone else's file"


def test_another_tracks_file_at_the_old_name_is_refused(tmp_path, monkeypatch):
    env, _ = renamed(tmp_path, monkeypatch)
    state = load_state(env.paths)
    state["tracks"]["t2bbbbbbb"] = {**state["tracks"][TID], "path": OLD, "title": "Other"}
    library.save_state(env.paths, state)
    assert "Another file is at" in str(refused(env, UpgradeProblem))


def test_a_file_whose_audio_changed_is_refused(tmp_path, monkeypatch):
    env, _ = renamed(tmp_path, monkeypatch)
    (env.paths.root / CLEAN).write_bytes(b"not the audio any more")
    assert "clean-name change" in str(refused(env, UpgradeProblem))


def test_a_newer_version_waiting_or_another_file_or_nothing_to_undo_is_refused(tmp_path, monkeypatch):
    env, _ = renamed(tmp_path, monkeypatch)
    state = load_state(env.paths)
    e = state["tracks"][TID]
    for change, words in (({"upgrade": {"file": "Upgrades ready/A/x.aiff"}}, "Another better version is waiting"),
                          ({"path": "Library/A/Elsewhere.aiff"}, "This track has another file now"),
                          ({"rekordbox_check": None}, upgrades.NOTHING_TO_UNDO)):
        state["tracks"][TID] = {**e, **change}
        with pytest.raises(UpgradeProblem, match=words):
            upgrades.undo(env.paths, state, TID)
    assert (env.paths.root / CLEAN).is_file() and not (env.paths.root / OLD).exists()


def test_the_other_refusal_words_say_the_clean_name(tmp_path, monkeypatch):
    for reason in ("rekordbox_unreadable", "other_library"):
        assert "clean name" in str(UndoRefused(reason, renamed=True)) and "upgrade" not in str(UndoRefused(reason, renamed=True))
    assert str(UndoRefused("unclean", renamed=True)) == UNDO_REFUSED["unclean"]
    assert str(UndoRefused("busy", converted=True)) == upgrades.conversion_words(UNDO_REFUSED["busy"])


# --- a crash in the undo ---

def crash(env, monkeypatch, at):
    with monkeypatch.context() as m:
        power_off_undo(m, at)
        with pytest.raises(PowerOff):
            undo(env)


@pytest.mark.parametrize("at", ["journaled", "restored", "outcome"])
def test_a_crash_before_the_commit_rolls_the_undo_back(tmp_path, monkeypatch, at):
    env, _before = renamed(tmp_path, monkeypatch)
    after = snapshot(env)
    crash(env, monkeypatch, at)
    messages, state = next_start(env)
    assert messages == [(rename.UNDO_NOT_FINISHED.format(name=NAME), False)]
    assert snapshot(env) == after and state["pending"] == []
    undo(env)  # and it can be undone again
    assert row_of(env)["FolderPath"] == str(env.paths.root / OLD)


@pytest.mark.parametrize("at", ["committed_unmarked", "committed", "ended"])
def test_a_crash_after_the_commit_finishes_the_undo(tmp_path, monkeypatch, at):
    env, before = renamed(tmp_path, monkeypatch)
    crash(env, monkeypatch, at)
    messages, state = next_start(env)
    assert messages == [(rename.UNDO_FINISHED.format(name=NAME), True)]
    assert_back(env, before, state)


def test_a_crash_without_rekordbox_is_finished(tmp_path, monkeypatch):
    env, before = renamed(tmp_path, monkeypatch, holds_file=False)
    crash(env, monkeypatch, "restored")
    messages, state = next_start(env)
    assert messages == [(rename.UNDO_FINISHED.format(name=NAME), True)]
    assert_back(env, before, state)


def test_analysis_files_the_cut_off_write_changed_come_back_once_rekordbox_is_closed(tmp_path, monkeypatch):
    env, _before = renamed(tmp_path, monkeypatch)
    after = snapshot(env)
    crash(env, monkeypatch, "outcome")
    (op,) = load_state(env.paths)["pending"]
    for a in op["rekordbox"]["record"]["anlz"]:  # as a power cut between the analysis-file writes and the commit leaves them
        path = Path(a["path"])
        rbwrite.replace_bytes(path, anlz.splice_ppth(anlz.read(path), a["old_ppth"]))
    assert anlz.ppth(anlz.read(env.dat())) == "?/Old Name.aiff"
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: True)
    messages, _state = next_start(env)
    assert messages == [(convert.UNDO_WAIT_REKORDBOX.format(name=NAME), False)]
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: False)
    messages, state = next_start(env)
    assert messages == [(rename.UNDO_NOT_FINISHED.format(name=NAME), False)]
    assert snapshot(env) == after and state["pending"] == []


def test_a_track_rekordbox_changed_during_the_crash_needs_help_and_the_rename_stands(tmp_path, monkeypatch):
    env, _before = renamed(tmp_path, monkeypatch)
    crash(env, monkeypatch, "restored")
    con = writer(env.place.db)
    con.execute("UPDATE djmdContent SET FolderPath = '/Users/dj/Music/Elsewhere.aiff' WHERE ID = '1'")
    con.commit()
    con.close()
    (message, ok), = next_start(env)[0]
    assert not ok and message == rename.UNDO_NEEDS_HELP.format(name=NAME, old=OLD, new=CLEAN)
    assert load_state(env.paths)["tracks"][TID]["path"] == CLEAN and (env.paths.root / CLEAN).is_file()


@pytest.mark.parametrize("at, done", [("restored", False), ("committed", True)])
def test_another_rekordbox_library_is_decided_by_the_commit_mark(tmp_path, monkeypatch, at, done):
    env, _before = renamed(tmp_path, monkeypatch)
    crash(env, monkeypatch, at)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(empty))
    (message, ok), = next_start(env)[0]
    words = rename.UNDO_OTHER_MAC_DONE if done else rename.UNDO_OTHER_MAC_UNDONE
    assert (message, ok) == (words.format(name=NAME, old=OLD, new=CLEAN), done)
    assert load_state(env.paths)["tracks"][TID]["path"] == (OLD if done else CLEAN)


def test_an_unreadable_library_or_a_drive_that_is_away_makes_the_undo_wait(tmp_path, monkeypatch):
    env, _before = renamed(tmp_path, monkeypatch)
    crash(env, monkeypatch, "restored")
    with monkeypatch.context() as m:
        m.setattr(master, "KEYS", ("00" * 32,))
        assert next_start(env)[0] == [(convert.UNDO_UNREADABLE_WAIT.format(name=NAME), False)]
    with monkeypatch.context() as m:
        m.setattr(library, "online", lambda path, roots: False)
        (message, ok), = next_start(env)[0]
        assert not ok and "isn't connected" in message
    assert len(load_state(env.paths)["pending"]) == 1


# --- the pieces around it ---

def test_the_nested_undo_of_a_chain_keeps_its_names_and_backups(tmp_path, monkeypatch):
    convert_undo = {"kind": "convert", "source": "file", "old": "Superseded/A/x.aiff", "backup": "b1",
                    "before": {"path": "Library/A/x.aiff", "upgrade": None, "rekordbox_check": None}}
    outer = {"kind": "rename", "old": "Library/A/x [t1].aiff", "backup": "b2",
             "before": {"path": "Library/A/x [t1].aiff", "rekordbox_check": {"reason": "converted",
                                                                              "undo": convert_undo}}}
    assert library.undo_chain(outer) == [outer, convert_undo] and library.undo_chain(convert_undo) == [convert_undo]
    assert set(library.undo_paths(outer)) == {"Library/A/x [t1].aiff", "Library/A/x.aiff", "Superseded/A/x.aiff"}
    assert upgrades.fields_before({"rekordbox_check": {"reason": "converted", "undo": convert_undo}})[
        "rekordbox_check"] == {"reason": "converted"}
    assert upgrades.fields_before({"rekordbox_check": {"reason": "converted", "undo": convert_undo}}, keep_undo=True)[
        "rekordbox_check"]["undo"] == convert_undo


def test_the_report_says_renamed(tmp_path, monkeypatch):
    assert ("renamed", "Given its clean name (your cues stayed)") in report.SECTIONS
    assert report.check_text({"reason": "renamed", "rekordbox": {"entries": ["1"], "kept": []}}) == report.RENAMED_CHECK
    assert report.check_text({"reason": "renamed", "rekordbox": None}) == report.RENAMED_NO_TRACK_CHECK
    assert "isn't in your rekordbox collection" in report.RENAMED_NO_TRACK_CHECK
