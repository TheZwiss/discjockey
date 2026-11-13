"""Give it its clean name (discjockey/rename.py `rename_file`; plan stage D §1.2, §5 D3; design rekordbox-repoint §7.1,
§5.5): the file moves to its clean name in its folder and every rekordbox track follows it (only the path columns,
`PPTH` and `contentFile` change; the audio, the tags and the file's facts stay), the name is the clean one or has the
song's ID when it is taken, a file rekordbox doesn't have is only moved, and every refusal leaves everything as it
was. Libraries in tmp_path (tests/rename_helpers.py); crash recovery is in test_rename_recovery.py."""
from __future__ import annotations

import hashlib

import pytest
from mutagen.aiff import AIFF

from audio_helpers import needs_ffmpeg
from convert_helpers import NOW, TID, file_facts_row, make_own, run_file, session
from discjockey import audio, convert, library, rename
from discjockey.library import load_state, save_state
from discjockey.names import fold
from discjockey.planner import ENTRY_KEYS
from discjockey.rekordbox import anlz, backup, eligible, master
from discjockey.rekordbox import write as rbwrite
from discjockey.rekordbox.session import RekordboxOpen, Session
from discjockey.rekordbox.write import RekordboxOpened
from rekordbox_helpers import TABLES, diff, dump, running_after, writer
from rename_helpers import CLEAN, ID_NAME, LOSSLESS, OLD, batch_row, make_clean, run_rename, start_rename_batch

pytestmark = needs_ffmpeg
T2 = "t2bbbbbbb"


def sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def row_of(env, row_id="1") -> dict:
    with master.open_read(env.place, False) as m:
        cur = m.con.execute("SELECT * FROM djmdContent WHERE ID = ?", (row_id,))
        return dict(zip([c[0] for c in cur.description], cur.fetchone()))


# --- the step: files, rows, records ---

def test_the_file_gets_its_clean_name_and_rekordbox_follows(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    root = env.paths.root
    before_bytes = (root / OLD).read_bytes()
    before_entry = load_state(env.paths)["tracks"][TID]
    (facts_before,) = file_facts_row(env)
    r, state = run_rename(env)
    assert (r.section, r.path, r.status, r.source) == ("renamed", CLEAN, "lossless", "manual")
    assert r.note == "now named Artist - Song.aiff"
    assert (root / CLEAN).read_bytes() == before_bytes and not (root / OLD).exists()  # the same bytes: tags included
    assert not (root / "Superseded").exists() and not (root / ".discjockey/.tmp" / TID).exists()
    assert state["pending"] == [] and load_state(env.paths)["pending"] == []
    # the song: only its path changes (and the check); the file row follows with the facts it had
    e = state["tracks"][TID]
    assert {k: e[k] for k in ENTRY_KEYS if k not in ("path", "rekordbox_check")} == \
        {k: before_entry[k] for k in ENTRY_KEYS if k not in ("path", "rekordbox_check")}
    assert e["path"] == CLEAN and load_state(env.paths)["tracks"][TID]["path"] == CLEAN
    ((path, placed_by, codec, rate, bits, kbps),) = file_facts_row(env)
    assert (path, placed_by, codec, rate, bits) == ("A/Artist - Song.aiff", "import", "pcm_s16be", 44100, 16)
    assert (kbps, codec) == (facts_before[5], "pcm_s16be")  # the facts it had: nothing probed again changes them
    # rekordbox: the track plays the new name, its analysis files name it
    row = row_of(env)
    assert row["FolderPath"] == str(root / CLEAN) and row["FileNameL"] == "Artist - Song.aiff"
    assert anlz.ppth(anlz.read(env.dat())) == "?/Artist - Song.aiff"
    assert anlz.ppth(anlz.read(env.dat().with_suffix(".EXT"))) == "?/Artist - Song.aiff"
    (b,) = backup.backups(env.paths)
    assert (b.batches, b.tracks) == ([], 1)


def test_only_the_path_columns_ppth_and_contentfile_change(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    before = dump(env.place.db)
    run_rename(env)
    after = dump(env.place.db)
    changed = diff(before, after)
    assert {(t, c) for t, _i, c, *_ in changed} == {
        ("djmdContent", c) for c in ("FolderPath", "FileNameL", "rb_local_usn", "updated_at")
    } | {("contentFile", c) for c in ("Hash", "Size", "rb_local_usn", "updated_at")} | {("agentRegistry", "int_1")}
    for _t, _i, column, old, new in changed:  # what the new path columns say
        if column == "FolderPath":
            assert old == str(env.paths.root / OLD) and new == str(env.paths.root / CLEAN)
        if column == "FileNameL":
            assert (old, new) == ("Old Name.aiff", "Artist - Song.aiff")
    row, was = after["djmdContent"][0], before["djmdContent"][0]
    names = [n for n, _ in TABLES["djmdContent"]]
    for n, a, b in zip(names, was, row):  # facts, text, identity of the track: all as they were
        if n not in ("FolderPath", "FileNameL", "rb_local_usn", "updated_at"):
            assert a == b, n
    untouched = [t for t in before if t not in ("djmdContent", "contentFile", "agentRegistry")]
    assert all(after[t] == before[t] for t in untouched)  # cues, playlists, history, tags, lookup rows
    with master.open_read(env.place, False) as m:  # every contentFile row holds its file's MD5 and size again
        files = m.con.execute("SELECT Path, Hash, Size FROM contentFile").fetchall()
    assert len(files) == 4
    for path, digest, size in files:
        data = (env.folder / "share" / path.lstrip("/")).read_bytes()
        assert (digest, size) == (hashlib.md5(data).hexdigest(), len(data)), path  # rekordbox's own invariant


def test_org_folder_path_follows_only_when_it_equalled_the_old_path(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    old_abs = str(env.paths.root / OLD)
    con = writer(env.place.db)
    con.execute("UPDATE djmdContent SET OrgFolderPath = ?, rb_LocalFolderPath = '/Users/dj/Elsewhere.aiff'", (old_abs,))
    con.commit()
    con.close()
    run_rename(env)
    row = row_of(env)
    assert row["OrgFolderPath"] == str(env.paths.root / CLEAN)
    assert row["rb_LocalFolderPath"] == "/Users/dj/Elsewhere.aiff"  # it held another path: left as it was


def test_the_audio_and_tag_bytes_are_unchanged(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    before = sha(env.paths.root / OLD)
    tags_before = AIFF(str(env.paths.root / OLD)).tags.pprint()
    audio_before = audio.file_facts(env.paths.root / OLD)
    run_rename(env)
    assert sha(env.paths.root / CLEAN) == before
    assert AIFF(str(env.paths.root / CLEAN)).tags.pprint() == tags_before
    assert audio.file_facts(env.paths.root / CLEAN) == audio_before  # codec, rate, bits, tags, cover


def test_the_check_and_its_undo_record(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    old_key = library.content_key(env.paths.root / OLD)
    r, state = run_rename(env)
    check = state["tracks"][TID]["rekordbox_check"]
    assert {k: check[k] for k in ("reason", "since", "batch", "rekordbox")} == {
        "reason": "renamed", "since": "2026-11-08", "batch": None, "rekordbox": {"entries": ["1"], "kept": []}}
    undo = check["undo"]
    assert (undo["kind"], undo["file"], undo["old"], undo["file_key"]) == ("rename", CLEAN, OLD, old_key)
    assert undo["before"]["path"] == OLD and undo["repoint"]["dbid"] == "1234567890"
    assert undo["backup"] == backup.backups(env.paths)[0].id
    assert load_state(env.paths)["tracks"][TID]["rekordbox_check"] == check
    assert library.undo_paths(undo) == [OLD]  # the old name stays reserved while the undo stands


def test_the_batch_item_is_done_with_the_step(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    batch = start_rename_batch(env)
    r, _state = run_rename(env, batch=(batch, 0))
    (item,) = batch_row(env, batch).items
    assert item.state == "done" and item.result["path"] == CLEAN and item.result["note"] == r.note
    assert item.result["rekordbox"] == {"entries": ["1"], "kept": []}
    assert load_state(env.paths)["tracks"][TID]["rekordbox_check"]["batch"] == batch


# --- the name ---

def test_a_taken_clean_name_gets_the_songs_id(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    other = env.paths.root / CLEAN
    other.write_bytes(b"another file, not audio at all")
    r, state = run_rename(env)
    assert r.path == ID_NAME == state["tracks"][TID]["path"]
    assert other.read_bytes() == b"another file, not audio at all"  # never overwritten
    assert row_of(env)["FileNameL"] == "Artist - Song [t1aaaa].aiff"


def test_two_items_wanting_one_name_the_second_gets_the_id(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch, holds_file=False)
    root = env.paths.root
    second = "Library/A/Other.aiff"
    (root / second).write_bytes((root / OLD).read_bytes())
    state = load_state(env.paths)
    state["tracks"][T2] = {**state["tracks"][TID], "path": second}
    save_state(env.paths, state)
    state = load_state(env.paths)
    first, _ = run_rename(env, state=state)
    other, _ = run_rename(env, state=state, track=T2)
    assert first.path == CLEAN and other.path == "Library/A/Artist - Song [t2bbbb].aiff"
    assert (root / CLEAN).is_file() and (root / other.path).is_file() and not (root / second).exists()


def test_the_file_that_holds_the_id_name_because_the_clean_one_is_taken_is_named_already(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch, entry={"path": ID_NAME})
    (env.paths.root / CLEAN).write_bytes(b"another file")
    with pytest.raises(convert.Skipped) as err:
        run_rename(env)
    assert err.value.reason == "named_already"


@pytest.mark.parametrize("path", [CLEAN, "Library/A/artist - song.aiff", "Library/A/ARTIST - SONG.AIFF"])
def test_a_case_only_difference_is_named_already(tmp_path, monkeypatch, path):
    env = make_clean(tmp_path, monkeypatch, entry={"path": path})
    music, master_rows = env.music(), dump(env.place.db)
    with pytest.raises(convert.Skipped) as err:
        run_rename(env)
    assert err.value.reason == "named_already" and str(err.value) == convert.CONVERT_REFUSED["named_already"]
    assert env.music() == music and dump(env.place.db) == master_rows
    assert fold(rename.clean_path(env.paths, load_state(env.paths), TID, load_state(env.paths)["tracks"][TID])) \
        == fold(path)


def test_the_clean_name_is_made_in_the_files_own_folder_with_aiff_as_its_extension(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch, entry={"path": "Library/A/not_lossless/Old Name.aif"})
    r, _state = run_rename(env)
    assert r.path == "Library/A/not_lossless/Artist - Song.aiff"
    assert row_of(env)["FileType"] == 12 and row_of(env)["FileNameL"] == "Artist - Song.aiff"


# --- a file rekordbox doesn't have ---

@pytest.mark.parametrize("case", ["not_in_rekordbox", "no_rekordbox"])
def test_a_file_with_no_rekordbox_track_is_only_moved(tmp_path, monkeypatch, case):
    env = make_clean(tmp_path, monkeypatch, holds_file=case != "not_in_rekordbox", rekordbox=case != "no_rekordbox")
    master_rows = dump(env.place.db) if env.place else None
    analysis = env.anlz_files()
    r, state = run_rename(env)
    assert r.path == CLEAN and (env.paths.root / CLEAN).is_file() and not (env.paths.root / OLD).exists()
    assert r.note.endswith(convert.NO_TRACK_NOTE)
    assert env.place is None or dump(env.place.db) == master_rows  # rekordbox untouched
    assert env.anlz_files() == analysis and not backup.backups(env.paths)
    check = state["tracks"][TID]["rekordbox_check"]
    assert check["rekordbox"] is None and check["undo"]["repoint"] is None and check["undo"]["backup"] is None


# --- refusals: nothing moves, nothing is written ---

def assert_nothing_changed(env, music, master_rows, analysis, entry, *, backed_up=False):
    assert env.music() == music
    assert env.place is None or dump(env.place.db) == master_rows
    assert env.anlz_files() == analysis
    state = load_state(env.paths)
    assert state["pending"] == [] and state["tracks"][TID] == entry
    assert not (env.paths.tmp / TID).exists() and bool(backup.backups(env.paths)) == backed_up
    assert file_facts_row(env)[0][0] == "A/" + (entry["path"].rsplit("/", 1)[-1])


@pytest.mark.parametrize("case, reason, why", [
    ("unreadable", "rename_blocked", "rekordbox's library can't be opened"),
    ("cloud", "rename_blocked", "the track is in Cloud Library Sync"),
    ("unclean", "unclean", None), ("downloaded", "downloaded", None), ("no_name", "no_name", None),
    ("upgrade_waits", "upgrade_waits", None), ("needs_convert", "needs_convert", None)])
def test_refusals_change_nothing(tmp_path, monkeypatch, case, reason, why):
    kw = {"cloud": {"row": {"usn": 5}},
          "downloaded": {"entry": {"source": "qobuz", "status": "lossless"}},
          "no_name": {"entry": {"artist": " "}},
          "upgrade_waits": {"entry": {"upgrade": {"file": "Upgrades ready/A/Artist - Song.aiff", "source": "qobuz"}}}}
    env = make_clean(tmp_path, monkeypatch, **kw.get(case, {}))
    if case == "needs_convert":  # tags that don't say what the record says
        audio.write_tags(env.paths.root / OLD, title="Wrong", artists=("Wrong",), album="", isrc=None, label=None,
                         cover=None, comment="")
    if case == "unclean":
        env.place.db.with_name("master.db-wal").write_bytes(b"")
    if case == "unreadable":
        monkeypatch.setattr("discjockey.rekordbox.master.KEYS", ("00" * 32,))
    music, master_rows, analysis = env.music(), dump(env.place.db), env.anlz_files()
    entry = load_state(env.paths)["tracks"][TID]
    with pytest.raises(convert.Skipped) as err:
        run_rename(env)
    assert err.value.reason == reason
    if why:  # design §8's words with the cause's own
        assert str(err.value) == ("Discjockey can only give this file its new name while it can point your rekordbox "
                                  f"track at it, and it can't right now ({why}). Nothing was changed.")
    else:
        assert str(err.value) == (convert.REFUSED.get(reason) or convert.CONVERT_REFUSED[reason])
    if case == "unclean":
        env.place.db.with_name("master.db-wal").unlink()
    assert_nothing_changed(env, music, master_rows, analysis, entry)


def test_rekordbox_running_with_the_file_in_its_library_stops_the_batch_nothing_moved(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    music, master_rows, analysis = env.music(), dump(env.place.db), env.anlz_files()
    entry = load_state(env.paths)["tracks"][TID]
    with pytest.raises(RekordboxOpen):  # the batch's session refuses at its start when an item needs a write
        run_rename(env, running=lambda: True)
    assert_nothing_changed(env, music, master_rows, analysis, entry)
    with pytest.raises(RekordboxOpened):  # a session that let it through: the step itself stops the batch
        run_rename(env, running=lambda: True, need_write=False)
    assert_nothing_changed(env, music, master_rows, analysis, entry)
    with pytest.raises(RekordboxOpened):
        run_rename(env, running=running_after(2))  # closed at the session's start, open from then on
    assert_nothing_changed(env, music, master_rows, analysis, entry)


def test_rekordbox_running_while_the_file_isnt_in_its_library_still_only_moves_it(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch, holds_file=False)
    r, _state = run_rename(env, running=lambda: True, need_write=False)
    assert r.path == CLEAN and (env.paths.root / CLEAN).is_file()


def test_rekordbox_running_while_its_library_cant_be_read_stops_the_batch_not_a_refusal(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    monkeypatch.setattr("discjockey.rekordbox.master.KEYS", ("00" * 32,))
    music = env.music()
    state = load_state(env.paths)
    with Session.open(env.paths, place=env.place, running=lambda: True, items_need_write=lambda view: False) as s:
        with pytest.raises(RekordboxOpened):
            rename.rename_file(env.paths, state, TID, session=s, now=lambda: NOW)
    assert env.music() == music


def test_rekordbox_opening_at_the_commit_rolls_the_step_back(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    music, master_rows, analysis = env.music(), dump(env.place.db), env.anlz_files()
    entry = load_state(env.paths)["tracks"][TID]
    real = rbwrite.Writer.repoint
    monkeypatch.setattr(rbwrite.Writer, "repoint",
                        lambda self, c, a, **kw: real(self, c, a, **{**kw, "running": lambda: True}))
    with pytest.raises(RekordboxOpened):
        run_rename(env)
    assert_nothing_changed(env, music, master_rows, analysis, entry, backed_up=True)  # the batch's backup stays


def test_a_track_changed_meanwhile_is_refused_and_the_file_goes_back(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    music, analysis = env.music(), env.anlz_files()
    real = rbwrite.Writer.repoint

    def moved_meanwhile(self, changes, splices, **kw):
        self.con.execute("UPDATE djmdContent SET FolderPath = '/Users/dj/Music/Elsewhere.aiff' WHERE ID = '1'")
        return real(self, changes, splices, **kw)
    monkeypatch.setattr(rbwrite.Writer, "repoint", moved_meanwhile)
    with pytest.raises(convert.Skipped) as err:
        run_rename(env)
    assert err.value.reason == "changed" and str(err.value) == convert.REFUSED["changed"]
    assert env.music() == music and env.anlz_files() == analysis
    assert load_state(env.paths)["pending"] == [] and load_state(env.paths)["tracks"][TID]["path"] == OLD


@pytest.mark.parametrize("case", ["missing", "away"])
def test_a_file_that_is_gone_or_on_a_drive_that_is_away_is_refused(tmp_path, monkeypatch, case):
    env = make_clean(tmp_path, monkeypatch)
    master_rows, analysis = dump(env.place.db), env.anlz_files()
    entry = load_state(env.paths)["tracks"][TID]
    if case == "away":
        monkeypatch.setattr(library, "online", lambda path, roots: False)
    (env.paths.root / OLD).rename(env.paths.root / "A.bak")
    music = env.music()
    with pytest.raises(convert.Skipped) as err:
        run_rename(env)
    assert err.value.reason == ("file_missing" if case == "missing" else "away")
    assert env.music() == music and dump(env.place.db) == master_rows and env.anlz_files() == analysis
    assert load_state(env.paths)["tracks"][TID] == entry


def test_a_file_ffprobe_cant_read_is_a_failure_with_nothing_changed(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    (env.paths.root / OLD).write_bytes(b"not audio at all")
    music = env.music()
    with pytest.raises(convert.UpgradeProblem, match="couldn't read Old Name.aiff"):
        run_rename(env)
    assert env.music() == music and load_state(env.paths)["pending"] == []


def test_a_song_with_no_file_is_a_failure(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    state = load_state(env.paths)
    state["tracks"][TID]["path"] = None
    with pytest.raises(convert.UpgradeProblem, match="no file to rename"):
        run_rename(env, state=state)


def test_no_free_name_is_a_failure_with_nothing_changed(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    for name in ("Artist - Song", "Artist - Song [t1aaaa]", "Artist - Song [t1aaaaaaa]"):
        (env.paths.root / "Library/A" / f"{name}.aiff").write_bytes(b"x")
    music = env.music()
    with pytest.raises(convert.UpgradeProblem, match="no free name"):
        run_rename(env)
    assert env.music() == music


# --- nothing outside move_path ---

def test_every_file_move_goes_through_move_path_and_nothing_is_deleted(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    moves = []
    real = rename.move_path
    monkeypatch.setattr(rename, "move_path", lambda root, src, dst, staged, roots=None:
                        (moves.append((src, dst)), real(root, src, dst, staged, roots))[1])
    renames = []
    real_rename = library.os.rename
    monkeypatch.setattr(library.os, "rename", lambda s, d: (renames.append((str(s), str(d))), real_rename(s, d))[1])
    unlinked = []
    real_unlink = library.os.unlink
    monkeypatch.setattr(library.os, "unlink", lambda p, *a, **k: (unlinked.append(str(p)), real_unlink(p, *a, **k))[1])
    run_rename(env)
    assert moves == [(OLD, CLEAN)]
    assert [(s.split("/Library/")[-1], d.split("/Library/")[-1]) for s, d in renames
            if "/Library/" in s or "/Library/" in d] == [("A/Old Name.aiff", "A/Artist - Song.aiff")]
    assert not [u for u in unlinked if "/Library/" in u]  # no music file is deleted


def test_a_move_never_overwrites_a_file_that_appeared_at_the_new_name(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    real = rename.move_path

    def taken_meanwhile(root, src, dst, staged, roots=None):
        (root / dst).write_bytes(b"someone else's file")
        return real(root, src, dst, staged, roots)
    monkeypatch.setattr(rename, "move_path", taken_meanwhile)
    music_before = (env.paths.root / OLD).read_bytes()
    with pytest.raises(convert.UpgradeProblem, match="Nothing was changed"):
        run_rename(env)
    assert (env.paths.root / OLD).read_bytes() == music_before
    assert (env.paths.root / CLEAN).read_bytes() == b"someone else's file"
    assert load_state(env.paths)["pending"] == [] and load_state(env.paths)["tracks"][TID]["path"] == OLD


# --- the chain: Convert, then Give it its clean name ---

def test_convert_then_rename_an_aiff_that_held_the_clean_name_ends_at_the_clean_name(tmp_path, monkeypatch):
    """An AIFF with wrong tags at `Artist - Song.aiff`: Convert's new file takes the ID name (the old file holds the
    clean one until rekordbox's commit), the old one goes to Superseded/; the rename then takes the clean name, which
    nothing holds any more (the convert's own undo record reserved it: the new check replaces that record)."""
    env = make_own(tmp_path, monkeypatch, "aiff", entry={"path": CLEAN, "status": "lossless", "source_format": None})
    old_bytes = (env.paths.root / CLEAN).read_bytes()
    converted, state = run_file(env)
    assert converted.path == ID_NAME and (env.paths.root / "Superseded/A/Artist - Song.aiff").read_bytes() == old_bytes
    r, state = run_rename(env, state=state)
    assert r.path == CLEAN and state["tracks"][TID]["path"] == CLEAN
    root = env.paths.root
    assert (root / CLEAN).is_file() and not (root / ID_NAME).exists()
    assert (root / "Superseded/A/Artist - Song.aiff").read_bytes() == old_bytes
    assert AIFF(str(root / CLEAN)).tags["TIT2"].text == ["Song"]
    assert row_of(env)["FolderPath"] == str(root / CLEAN) and row_of(env)["FileNameL"] == "Artist - Song.aiff"
    assert anlz.ppth(anlz.read(env.dat())) == "?/Artist - Song.aiff"
    ((path, placed_by, codec, rate, bits, _kbps),) = file_facts_row(env)
    assert (path, placed_by, codec, rate, bits) == ("A/Artist - Song.aiff", "app", "pcm_s16be", 44100, 16)
    assert state["tracks"][TID]["rekordbox_check"]["reason"] == "renamed"
    assert eligible.rename(state["tracks"][TID], audio.file_facts(root / CLEAN), session_state(env), None,
                           clean_path=CLEAN) == eligible.Skip("named_already")  # a second Rename has nothing to do


def session_state(env):
    with session(env) as s:
        return s.state


# --- the pieces D3b and D4 build on ---

def test_clean_path_counts_the_files_own_name_as_free_and_says_none_without_a_name(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    state = load_state(env.paths)
    e = state["tracks"][TID]
    assert rename.clean_path(env.paths, state, TID, e) == CLEAN
    assert rename.clean_path(env.paths, state, TID, {**e, "artist": " "}) is None
    (env.paths.root / CLEAN).write_bytes(b"x")
    assert rename.clean_path(env.paths, state, TID, e) == ID_NAME


def test_a_pending_rename_reserves_both_of_its_names(tmp_path, monkeypatch):
    op = {"kind": "rename", "old": OLD, "new": CLEAN}
    assert library.op_paths(op) == [OLD, CLEAN] == library.op_paths({**op, "kind": "rename_undo"})
    assert library.RENAME_PATH_KEYS == ("old", "new")


def test_side_of_and_tracks_at_are_public(tmp_path, monkeypatch):
    env = make_clean(tmp_path, monkeypatch)
    old, new = str(env.paths.root / OLD), str(env.paths.root / CLEAN)
    assert convert.tracks_at("1234567890", {"1": (new, old)}) == "old"
    assert convert.tracks_at("1234567890", {"1": (old, new)}) == "new"
    assert convert.tracks_at("1234567890", {"1": (new, "/Users/dj/x.aiff")}) == "neither"
    assert convert.tracks_at("another dbid", {"1": (new, old)}) == "other"
    assert convert.side_of(env.paths, {"rekordbox": None, "new": OLD, "new_sha256": sha(env.paths.root / OLD)}) == "new"
    assert convert.side_of(env.paths, {"rekordbox": None, "new": CLEAN, "new_sha256": "0" * 64}) == "old"
