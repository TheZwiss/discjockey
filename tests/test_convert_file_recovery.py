"""Convert to AIFF cut off and undone (discjockey/convert.py `convert_file`, `undo_convert` without a kept download;
plan stage D §5 D2; design rekordbox-repoint §5.8, §5.9): a crash at every mark of the step is rolled back before
rekordbox's commit and finished after it (the new file's facts and `placed_by` included), the batch is `stopped`; the
undo puts the old file, rekordbox's row, the song's records and the file row's facts back, refuses what it can't put
back safely, and is itself finished or rolled back at the next start. Libraries in tmp_path only."""
from __future__ import annotations

import pytest
from mutagen.aiff import AIFF

from audio_helpers import needs_ffmpeg
from convert_helpers import (
    AFTER_COMMIT, BEFORE_COMMIT, TID, PowerOff, batch_row, file_facts_row, make_own, next_start, power_off,
    power_off_undo, run_file, session, start_file_batch,
)
from discjockey import convert, library, upgrades
from discjockey.library import load_state
from discjockey.rekordbox import anlz, backup, master
from discjockey.upgrades import UNDO_REFUSED, UndoRefused, UpgradeProblem
from rekordbox_helpers import diff, dump, writer

pytestmark = needs_ffmpeg
NAME = "Artist - Song"
NEW = "Library/A/not_lossless/Artist - Song.aiff"
OLD_FACTS = (("A/Old Name.mp3", "import", "mp3", 44100, None, 64),)
STAMPS = {"rb_local_usn", "updated_at"}
LOOKUPS = {"djmdArtist", "djmdAlbum", "djmdLabel"}
said = upgrades.conversion_words  # a Convert says "conversion" where Same track says "replace" or "upgrade"


def snapshot(env):
    return env.music(), dump(env.place.db), env.anlz_files(), load_state(env.paths)["tracks"][TID], file_facts_row(env)


def crash(env, monkeypatch, at, batch=None):
    with monkeypatch.context() as m:
        power_off(m, at)
        with pytest.raises(PowerOff):
            run_file(env, batch=batch)


def converted(env):
    before = snapshot(env)
    _r, state = run_file(env)
    return before, state


# --- the step cut off ---

def assert_as_before(env, before, state):
    music, master_rows, analysis, entry, facts = before
    assert env.music() == music and dump(env.place.db) == master_rows and env.anlz_files() == analysis
    assert state["pending"] == [] and load_state(env.paths)["pending"] == []
    assert load_state(env.paths)["tracks"][TID] == entry and file_facts_row(env) == facts == OLD_FACTS
    assert not (env.paths.tmp / TID).exists() and not env.paths.undo.exists()


@pytest.mark.parametrize("at", BEFORE_COMMIT)
def test_a_crash_before_the_commit_puts_everything_back(tmp_path, monkeypatch, at):
    env = make_own(tmp_path, monkeypatch)
    before = snapshot(env)
    crash(env, monkeypatch, at)
    messages, state = next_start(env)
    assert messages == ([] if at == "rendered" else [(said(convert.NOT_FINISHED).format(name=NAME), False)])
    assert_as_before(env, before, state)
    _r, state = run_file(env)  # and the step can be run again
    assert state["tracks"][TID]["path"] == NEW


@pytest.mark.parametrize("at", AFTER_COMMIT)
def test_a_crash_after_the_commit_finishes_the_step(tmp_path, monkeypatch, at):
    env = make_own(tmp_path, monkeypatch)
    old = (env.paths.root / env.old).read_bytes()
    crash(env, monkeypatch, at)
    messages, state = next_start(env)
    assert messages == [(said(convert.FINISHED).format(name=NAME), True)]
    now = load_state(env.paths)
    e = now["tracks"][TID]
    assert state["pending"] == [] and now["pending"] == []
    assert e["path"] == NEW and (env.paths.root / NEW).is_file() and not (env.paths.root / env.old).exists()
    assert (env.paths.root / env.superseded).read_bytes() == old
    assert e["rekordbox_check"]["reason"] == "converted" and e["rekordbox_check"]["undo"]["held"] is None
    assert e["rekordbox_check"]["undo"]["repoint"]["dbid"] == "1234567890"  # journaled before the commit
    assert anlz.ppth(anlz.read(env.dat())) == "?/Artist - Song.aiff" and not (env.paths.tmp / TID).exists()
    # the file row: the new file's facts and Discjockey's name for it, as after an uninterrupted step
    assert file_facts_row(env) == (("A/not_lossless/Artist - Song.aiff", "app", "pcm_s16be", 44100, 16, 706),) \
        or file_facts_row(env)[0][1:5] == ("app", "pcm_s16be", 44100, 16)
    assert upgrades.can_undo(e)


def test_a_crash_without_rekordbox_is_decided_by_whether_the_new_file_is_in_place(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch, holds_file=False)
    before = snapshot(env)
    with monkeypatch.context() as m:
        power_off(m, "backed_up")  # without a rekordbox track the first mark is `placed`
        with pytest.raises(PowerOff):
            run_file(env)
    assert (env.paths.root / NEW).is_file() and (env.paths.root / env.old).is_file()
    messages, state = next_start(env)
    assert messages == [(said(convert.FINISHED).format(name=NAME), True)]
    assert load_state(env.paths)["tracks"][TID]["path"] == NEW and not (env.paths.root / env.old).exists()
    assert file_facts_row(env)[0][1:5] == ("app", "pcm_s16be", 44100, 16)
    assert before[1] == dump(env.place.db)  # rekordbox never touched


def test_the_batch_the_crash_interrupted_is_stopped(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    batch = start_file_batch(env)
    crash(env, monkeypatch, "placed", batch=(batch, 0))
    row = batch_row(env, batch)
    assert row.state == "running"
    next_start(env)
    row = batch_row(env, batch)
    assert (row.state, row.stop_reason) == ("stopped", "crash")
    assert [i.state for i in row.items] == ["planned"]  # Resume re-checks it


def test_analysis_files_written_before_a_crash_come_back_from_the_backup(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    before = snapshot(env)
    crash(env, monkeypatch, "placed")
    for path in (env.dat(), env.dat().with_suffix(".EXT")):  # a crash inside rekordbox's transaction
        path.write_bytes(anlz.splice_ppth(anlz.read(path), "?/Artist - Song.aiff"))
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: True)
    messages, _state = next_start(env)
    assert messages == [(said(convert.WAIT_REKORDBOX).format(name=NAME), False)]  # waits for rekordbox to quit
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: False)
    messages, state = next_start(env)
    assert messages == [(said(convert.NOT_FINISHED).format(name=NAME), False)]
    assert_as_before(env, before, state)


def test_a_track_rekordbox_changed_during_the_crash_needs_help(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    crash(env, monkeypatch, "placed")
    con = writer(env.place.db)
    con.execute("UPDATE djmdContent SET FolderPath = '/Users/dj/Music/Elsewhere.mp3' WHERE ID = '1'")
    con.commit()
    con.close()
    messages, state = next_start(env)
    (message, ok), = messages
    assert not ok and message == said(convert.NEEDS_HELP).format(name=NAME, old=env.old, new=NEW)
    assert load_state(env.paths)["tracks"][TID]["path"] == env.old and (env.paths.root / env.old).is_file()
    assert not (env.paths.root / NEW).exists() and file_facts_row(env) == OLD_FACTS


# --- the undo ---

def assert_back(env, before, state):
    """As before the conversion: music and analysis files byte for byte, master.db row by row except the stamps and
    lookup rows, the song and its file row (facts, `placed_by`) as they were, nothing pending, the AIFF gone."""
    music, rows, analysis, entry, facts = before
    assert env.music() == music and env.anlz_files() == analysis
    for table, _id, column, old, new in diff(rows, dump(env.place.db)):
        if column == "<row>":
            assert table in LOOKUPS and old is None, (table, _id)
        elif table == "agentRegistry":
            assert column == "int_1"
        else:
            assert column in STAMPS, (table, _id, column, old, new)
    now = load_state(env.paths)
    assert state["pending"] == [] and now["pending"] == []
    assert {k: now["tracks"][TID].get(k) for k in entry} == entry
    assert file_facts_row(env) == facts == OLD_FACTS
    library.clear_tmp(env.paths, now)
    assert not env.paths.undo.exists() or not list(env.paths.undo.rglob("*.aiff"))


def undo(env, state=None, s=None):
    state = load_state(env.paths) if state is None else state
    return upgrades.undo(env.paths, state, TID, session=s), state


def test_undo_puts_everything_back(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    before, _state = converted(env)
    assert diff(before[1], dump(env.place.db))
    r, state = undo(env)
    assert (r.section, r.path, r.status) == ("upgrade_undone", env.old, "not_lossless")
    assert r.note == f"the old file is back at {env.old}"  # nothing waits in Upgrades ready/
    assert_back(env, before, state)
    assert state["tracks"][TID]["upgrade"] is None  # no upgrade is parked or handed back
    assert not upgrades.can_undo(state["tracks"][TID])  # the check is gone with the undo


def test_the_new_aiff_goes_to_the_clean_up_not_back_anywhere(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    converted(env)
    upgrades.undo(env.paths, load_state(env.paths), TID)
    (kept,) = list(env.paths.undo.rglob("*.aiff"))
    assert AIFF(str(kept)).tags["TIT2"].text == ["Song"]
    assert not (env.paths.root / NEW).exists()
    library.clear_tmp(env.paths, load_state(env.paths))
    assert not list(env.paths.undo.rglob("*.aiff"))  # its audio is the old file's: no reason to keep it


def test_undo_in_a_batchs_session(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    before, _state = converted(env)
    with session(env) as s:
        _r, state = undo(env, s=s)
        assert s.backup is not None  # the undo's write, too, comes after a backup
    assert_back(env, before, state)


def test_edits_made_since_stay_and_rekordboxs_facts_go_back(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch, row={"Title": "My Edit Name", "Rating": 4})
    before, state = converted(env)
    assert state["tracks"][TID]["rekordbox_check"]["rekordbox"]["kept"] == ["title"]
    con = writer(env.place.db)
    con.execute("UPDATE djmdContent SET Commnt = 'MINE', Rating = 5 WHERE ID = '1'")  # edits after the conversion
    con.execute("INSERT INTO djmdCue (ID, ContentID, InMsec, Kind, ContentUUID, UUID) "
                "VALUES ('c99', '1', 7000, 0, 'uuid-1', 'uc99')")
    con.commit()
    con.close()
    r, _state = undo(env)
    assert r.note.endswith("Kept your own comment in rekordbox.")
    with master.open_read(env.place, False) as m:
        cur = m.con.execute("SELECT * FROM djmdContent WHERE ID = '1'")
        row = dict(zip([c[0] for c in cur.description], cur.fetchone()))
        assert m.con.execute("SELECT COUNT(*) FROM djmdCue WHERE ID = 'c99'").fetchone()[0] == 1
    assert (row["Commnt"], row["Rating"], row["Title"]) == ("MINE", 5, "My Edit Name")
    assert row["FolderPath"] == str(env.paths.root / env.old) and row["FileNameL"] == "Old Name.mp3"
    assert (row["FileType"], row["SampleRate"], row["BitDepth"]) == (1, 0, 0)  # the facts of the file it plays again
    assert env.music() == before[0]


def test_no_rekordbox_track_needs_no_rekordbox_to_undo(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch, holds_file=False)
    before, _state = converted(env)
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: True)  # open: doesn't matter here
    _r, state = undo(env)
    assert dump(env.place.db) == before[1] and env.music() == before[0]
    assert state["pending"] == [] and file_facts_row(env) == OLD_FACTS


def assert_unchanged(env, after, state):
    assert (env.music(), dump(env.place.db), env.anlz_files()) == after[:3]
    assert load_state(env.paths)["tracks"][TID] == after[3] and state["pending"] == []
    assert file_facts_row(env) == after[4]


def test_undo_refused_while_rekordbox_runs(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    converted(env)
    after = snapshot(env)
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: True)
    state = load_state(env.paths)
    with pytest.raises(UndoRefused) as err:
        upgrades.undo(env.paths, state, TID)
    assert err.value.reason == "rekordbox_open" and str(err.value) == UNDO_REFUSED["rekordbox_open"]
    assert_unchanged(env, after, state)


def test_undo_refused_for_a_relocated_track(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    converted(env)
    con = writer(env.place.db)
    con.execute("UPDATE djmdContent SET FolderPath = '/Users/dj/Music/Elsewhere.aiff' WHERE ID = '1'")
    con.commit()
    con.close()
    after = snapshot(env)
    state = load_state(env.paths)
    with pytest.raises(UndoRefused) as err:
        upgrades.undo(env.paths, state, TID)
    assert err.value.reason == "relocated" and "moved or removed in rekordbox since the conversion" in str(err.value)
    assert_unchanged(env, after, state)


def test_undo_refused_when_the_new_files_audio_changed(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    converted(env)
    path = env.paths.root / NEW
    data = bytearray(path.read_bytes())
    at = data.index(b"SSND") + 16
    data[at:at + 200] = bytes(b ^ 0x55 for b in data[at:at + 200])  # other samples
    path.write_bytes(bytes(data))
    after = snapshot(env)
    state = load_state(env.paths)
    with pytest.raises(UpgradeProblem, match="changed since the conversion"):  # the words say "conversion"
        upgrades.undo(env.paths, state, TID)
    assert_unchanged(env, after, state)


def test_undo_refused_when_the_old_file_is_gone(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    converted(env)
    (env.paths.root / env.superseded).unlink()
    after = snapshot(env)
    state = load_state(env.paths)
    with pytest.raises(UpgradeProblem, match="is gone, so the conversion can't be undone"):
        upgrades.undo(env.paths, state, TID)
    assert_unchanged(env, after, state)


def test_undo_refused_when_a_file_is_in_the_way_of_the_old_name(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    converted(env)
    (env.paths.root / env.old).write_bytes(b"someone else's file")
    after = snapshot(env)
    state = load_state(env.paths)
    with pytest.raises(UpgradeProblem, match=f"Another file is at {env.old} now, so the conversion can't be undone"):
        upgrades.undo(env.paths, state, TID)
    assert_unchanged(env, after, state)


def test_undo_refused_when_the_song_has_another_file_or_a_better_version_now(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    converted(env)
    state = load_state(env.paths)
    after = snapshot(env)
    state["tracks"][TID]["upgrade"] = {"file": "Upgrades ready/A/x.aiff", "source": "qobuz"}
    with pytest.raises(UpgradeProblem, match="better version is waiting for this track now, so the conversion"):
        upgrades.undo(env.paths, state, TID)
    state["tracks"][TID]["upgrade"] = None
    state["tracks"][TID]["path"] = "Library/A/elsewhere.aiff"
    with pytest.raises(UpgradeProblem, match="another file now, so the conversion can't be undone"):
        upgrades.undo(env.paths, state, TID)
    assert (env.music(), dump(env.place.db)) == after[:2]


def test_rekordbox_opening_at_the_commit_rolls_the_undo_back(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    converted(env)
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


# --- a crash at every step of the undo ---

def crash_undo(env, monkeypatch, at):
    with monkeypatch.context() as m:
        power_off_undo(m, at)
        with pytest.raises(PowerOff):
            undo(env)


@pytest.mark.parametrize("at", ["journaled", "restored", "outcome"])
def test_a_crash_before_the_undos_commit_leaves_the_conversion_standing(tmp_path, monkeypatch, at):
    env = make_own(tmp_path, monkeypatch)
    before, _state = converted(env)
    after = snapshot(env)
    crash_undo(env, monkeypatch, at)
    messages, state = next_start(env)
    assert messages == [(said(convert.UNDO_NOT_FINISHED).format(name=NAME), False)]
    assert_unchanged(env, after, state)
    _r, state = undo(env)  # and it can be undone again
    assert_back(env, before, state)


@pytest.mark.parametrize("at", ["committed_unmarked", "committed", "ended"])
def test_a_crash_after_the_undos_commit_finishes_it(tmp_path, monkeypatch, at):
    env = make_own(tmp_path, monkeypatch)
    before, _state = converted(env)
    crash_undo(env, monkeypatch, at)
    messages, state = next_start(env)
    assert messages == [(said(convert.UNDO_FINISHED).format(name=NAME), True)]
    assert_back(env, before, state)


def test_a_crash_in_the_undo_without_rekordbox_is_finished(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch, holds_file=False)
    before, _state = converted(env)
    with monkeypatch.context() as m:
        power_off_undo(m, "ended")
        with pytest.raises(PowerOff):
            undo(env)
    messages, state = next_start(env)
    assert messages == [(said(convert.UNDO_FINISHED).format(name=NAME), True)]
    assert_back(env, before, state)


def test_done_checked_frees_the_backup_and_leaves_no_kept_file(tmp_path, monkeypatch):
    env = make_own(tmp_path, monkeypatch)
    converted(env)
    state = load_state(env.paths)
    u = state["tracks"][TID]["rekordbox_check"]["undo"]
    assert u["backup"] and u["file_sha256"] and u["held"] is None and u["audio"]["codec"] == "mp3"
    for n in range(4):  # four newer backups, so the step's is past the newest 3
        newer = backup.backups_dir(env.paths) / f"20991231T00000{n}Z"
        newer.mkdir(parents=True)
        (newer / "manifest.json").write_text(f'{{"created": "2099-12-31T00:00:0{n}"}}')
    library.clear_tmp(env.paths, state)
    assert backup.find(env.paths, u["backup"]) is not None  # kept: the undo record names it
    library.forget_undo(env.paths, u)  # nothing held: nothing to delete, and no error
    state["tracks"][TID] = {**state["tracks"][TID], "rekordbox_check": None}
    library.save_state(env.paths, state)
    library.clear_tmp(env.paths, state)
    assert backup.find(env.paths, u["backup"]) is None
    assert (env.paths.root / env.superseded).is_file()  # the old file stays in Superseded/


# --- words: a Convert never says "replace" or "upgrade" (plan stage D §3: "conversion" in the same sentence shape) ---

def test_a_converts_words_say_conversion_where_same_track_says_replace_or_upgrade():
    assert said(convert.FINISHED).format(name=NAME) == "Finished an interrupted conversion for Artist - Song."
    assert said(convert.NOT_FINISHED).format(name=NAME).startswith("The conversion for Artist - Song was not finished")
    assert said(convert.UNDO_FINISHED).format(name=NAME) == "Finished undoing the conversion for Artist - Song."
    assert said(convert.UNDO_NOT_FINISHED).format(name=NAME).startswith(
        "Undoing the conversion for Artist - Song was not finished: the conversion stands as it was")
    texts = [convert.WAIT_REKORDBOX, convert.NOT_FINISHED, convert.FINISHED, convert.NEEDS_HELP, convert.OTHER_MAC_DONE,
             convert.OTHER_MAC_UNDONE, convert.UNREADABLE_WAIT, convert.UNCLEAN_WAIT, convert.FINISHED_MOST,
             convert.COULD_NOT_FINISH, convert.STEP_FAILED, convert.STEP_NOT_FINISHED, convert.UNDO_FINISHED,
             convert.UNDO_NOT_FINISHED, convert.UNDO_NEEDS_HELP, convert.UNDO_WAIT_REKORDBOX, convert.UNDO_OTHER_MAC_DONE,
             convert.UNDO_OTHER_MAC_UNDONE, convert.UNDO_UNREADABLE_WAIT, convert.UNDO_UNCLEAN_WAIT, *UNDO_REFUSED.values()]
    for text in texts:
        assert "replace" not in said(text) and "upgrade" not in said(text).lower(), text
    assert "since the conversion" in UndoRefused("relocated", True).args[0]
    assert "since the replace" in UndoRefused("relocated").args[0]  # Same track's words stay
