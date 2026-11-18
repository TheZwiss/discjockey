"""The placement for a missing file (`convert.place_parked`; issue 43, plan §4.5.2): Download again on a song whose
file is gone and whose better version is parked puts that version in where a redownload would have gone, and points
rekordbox's tracks of the missing file at it. Each library and rekordbox library is built in tmp_path
(tests/convert_helpers.py); the old file is deleted after the library is built, the way a scan finds it gone."""
from __future__ import annotations

import numpy as np
import pytest

from audio_helpers import needs_ffmpeg, pcm
from convert_helpers import (
    NOW, PARKED, TID, Env, PowerOff, batch_row, file_rows, make_env, never, next_start, power_off, session, song,
)
from discjockey import convert, db, library, rbstep
from discjockey.align import Alignment
from discjockey.library import load_state
from discjockey.rekordbox import backup, master
from discjockey.rekordbox import write as rbwrite
from discjockey.rekordbox.eligible import Eligible, Skip
from discjockey.rekordbox.master import Status
from discjockey.rekordbox.write import RekordboxOpened
from rekordbox_helpers import diff, dump, make_anlz, ppth_tag, running_after


pytestmark = needs_ffmpeg

SINCE = "2026-11-10T09:00:00"
SHIFTED = Alignment("shifted", 441, 10.0, 0.0, "matches, shifted by 10 ms")
NOT_LOSSLESS_AIFF = "Library/A/not_lossless/Old Name.aiff"  # a Discjockey download of a lossy source, as an AIFF
NEW = "Library/A/Artist - Song.aiff"


def upgrade_of(alignment: Alignment | None, **kw) -> dict:
    up = {**song("x")["upgrade"], **kw}
    up["alignment"] = None if alignment is None else alignment.to_dict()
    return up


def go_missing(env: Env, *, file_gone: bool = True) -> None:
    """The scan found the file gone (the row waits with its date), and the user pressed Download again."""
    (env.paths.root / env.old).unlink()
    with db.connect(env.paths.db_file) as conn:
        conn.execute("UPDATE files SET missing_since = ?", (SINCE,))
        if file_gone:
            conn.execute("UPDATE songs SET file_gone = '2026-11-18'")
        conn.commit()


def make_missing(tmp_path, monkeypatch, kind="aiff", *, alignment: Alignment | None = SHIFTED, entry=None, **kw) -> Env:
    path = (entry or {}).get("path", NOT_LOSSLESS_AIFF if kind == "aiff" else None)
    own = {"upgrade": upgrade_of(alignment), **(entry or {})}
    if path:
        own["path"] = path
    env = make_env(tmp_path, monkeypatch, kind, entry=own, **kw)
    go_missing(env)
    return env


def place(env: Env, *, running=never, batch=None, state=None):
    state = load_state(env.paths) if state is None else state
    with session(env, running, batch[0] if batch else None) as s:
        r = convert.place_parked(env.paths, state, TID, dict(state["tracks"][TID]["upgrade"]), session=s,
                                 now=lambda: NOW, batch=batch)
    return r, state


def row_of(env, row_id="1") -> dict:
    with master.open_read(env.place, False) as m:
        cur = m.con.execute("SELECT * FROM djmdContent WHERE ID = ?", (row_id,))
        return dict(zip([c[0] for c in cur.description], cur.fetchone()))


def file_ids(env) -> list[int]:
    with db.connect(env.paths.db_file) as conn:
        return [i for (i,) in conn.execute("SELECT id FROM files ORDER BY id")]


def missing_since(env) -> list:
    with db.connect(env.paths.db_file) as conn:
        return [m for (m,) in conn.execute("SELECT missing_since FROM files")]


IDENTITY_AND_FACTS = {"FolderPath", "FileNameL", "FileType", "FileSize", "BitDepth", "SampleRate", "BitRate", "Length",
                      "OrgFolderPath", "rb_LocalFolderPath", "rb_local_usn", "updated_at"}


# --- the decision's repro ---

def test_the_parked_version_is_placed_and_the_track_follows_it_with_its_cues_and_text(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch, row={"Title": "My Edit Name", "Commnt": "gig notes", "album": "My Album"})
    parked = pcm(env.paths.root / PARKED)
    parked_bytes_len = len(parked)
    file_id = file_ids(env)
    before = dump(env.place.db)
    anlz_before = env.anlz_files()
    from discjockey.rekordbox import anlz
    heights_before = anlz.pwv3_heights(anlz.read(env.dat().with_suffix(".EXT")))
    r, state = place(env)
    root = env.paths.root

    # the file: the parked audio shifted by L (d = 0 for an AIFF), where the redownload would have gone
    out = pcm(root / NEW)
    assert r.path == NEW and state["tracks"][TID]["path"] == NEW
    assert len(out) == parked_bytes_len - 441 and np.array_equal(out, parked[441:])
    # nothing else moved: no Superseded/, the old file is not recreated, the parked download is kept for the undo
    assert not (root / "Superseded").exists() and not (root / env.old).exists() and not (root / PARKED).exists()
    held = state["tracks"][TID]["rekordbox_check"]["undo"]["held"]
    assert held.startswith(".discjockey/undo/") and np.array_equal(pcm(root / held), parked)
    assert sorted(p for p in env.music()) == [NEW]
    assert not (env.paths.tmp / TID).exists() and state["pending"] == []

    # the records: the song keeps its key and its file row (same id), the upgrade's quality, the mark cleared
    e = state["tracks"][TID]
    assert (e["status"], e["source"], e["source_id"], e["upgrade"], e["file_gone"], e["missing_since"]) == (
        "lossless", "qobuz", "q1", None, None, None)
    assert file_ids(env) == file_id and missing_since(env) == [None]
    assert file_rows(env) == [("A/Artist - Song.aiff", "app")]
    assert load_state(env.paths)["tracks"][TID] == e

    # the check
    check = e["rekordbox_check"]
    assert {k: check[k] for k in ("reason", "since", "match", "aligned", "repointed", "batch", "reload_tag")} == {
        "reason": "placed_missing", "since": "2026-11-08", "match": "shifted", "aligned": True, "repointed": True,
        "batch": None, "reload_tag": False}
    assert check["rekordbox"] == {"entries": ["1"], "kept": []}
    undo = check["undo"]
    assert (undo["kind"], undo["source"], undo["file"], undo["old"], undo["old_key"]) == (
        "convert", "upgrade", NEW, None, None)
    assert undo["file_key"] and undo["missing_since"] == SINCE and undo["held"] == held
    assert undo["before"]["path"] == NOT_LOSSLESS_AIFF and undo["before"]["upgrade"]["file"] == PARKED
    assert [x["id"] for x in undo["repoint"]["rows"]] == ["1"]

    # rekordbox: the track plays the new file; only identity and file facts changed, no text column, no cue, no grid
    row = row_of(env)
    assert row["FolderPath"] == str(root / NEW) and row["FileNameL"] == "Artist - Song.aiff"
    assert (row["FileType"], row["BitDepth"], row["SampleRate"], row["BitRate"]) == (12, 16, 44100, 1411)
    assert row["Title"] == "My Edit Name" and row["Commnt"] == "gig notes"
    changed = diff(before, dump(env.place.db))
    assert {table for table, *_ in changed} <= {"djmdContent", "contentFile", "agentRegistry"}  # contentFile: PPTH's hash
    assert {column for table, _id, column, *_ in changed if table == "djmdContent"} <= IDENTITY_AND_FACTS
    assert not any(c in ("Title", "Commnt", "ArtistID", "AlbumID", "LabelID", "ISRC") for _t, _i, c, *_ in changed)
    for suffix in (".DAT", ".EXT"):  # PPTH names the new file; the grid and the waveform are the bytes they were
        file = env.dat().with_suffix(suffix)
        assert anlz.ppth(anlz.read(file)) == "?/Artist - Song.aiff"
    assert anlz.beat_count(anlz.read(env.dat())) == 40
    assert np.array_equal(anlz.pwv3_heights(anlz.read(env.dat().with_suffix(".EXT"))), heights_before)
    assert env.anlz_files().keys() == anlz_before.keys()
    (b,) = backup.backups(env.paths)
    assert (b.batches, b.tracks) == ([], 1)
    assert "plays it" in r.note and "Superseded" not in r.note


def test_no_rekordbox_track_for_the_file_places_it_lined_up_and_writes_nothing_of_rekordbox(tmp_path, monkeypatch):
    for rekordbox, holds in ((False, False), (True, False)):
        (tmp_path / f"{rekordbox}").mkdir()
        env = make_missing(tmp_path / f"{rekordbox}", monkeypatch, "lame", rekordbox=rekordbox, holds_file=holds,
                           alignment=SHIFTED)
        before = dump(env.place.db) if rekordbox else None
        analysis = env.anlz_files()
        parked = pcm(env.paths.root / PARKED)
        r, state = place(env)
        # d = 0 (no rekordbox, or no track holds the file): the download shifted by L alone, no backup
        assert np.array_equal(pcm(env.paths.root / r.path), parked[441:])
        check = state["tracks"][TID]["rekordbox_check"]
        assert (check["reason"], check["aligned"], check["repointed"], check["rekordbox"]) == (
            "placed_missing", True, False, None)
        assert check["undo"]["repoint"] is None and check["undo"]["held"]
        assert env.anlz_files() == analysis and backup.backups(env.paths) == []
        if rekordbox:
            assert dump(env.place.db) == before


# --- the timeline of a file that is gone ---

def no_grid(env: Env) -> None:
    """The track keeps its cues but has no grid and no waveform: nothing of it cares where the audio sits."""
    name = "Old Name.mp3"
    make_anlz(env.dat(), [ppth_tag("?/" + name)])
    env.dat().with_suffix(".EXT").unlink()


def test_a_lossy_file_that_is_gone_places_at_L_repointed_and_the_check_asks_to_look_at_the_cues(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch, "lame", entry={"path": "Library/A/Old Name.mp3"})
    parked = pcm(env.paths.root / PARKED)
    r, state = place(env)
    assert r.path == NEW and np.array_equal(pcm(env.paths.root / NEW), parked[441:])  # k = L, d unknown (not guessed)
    check = state["tracks"][TID]["rekordbox_check"]
    assert (check["aligned"], check["repointed"]) == (False, True)
    assert row_of(env)["FolderPath"] == str(env.paths.root / NEW)
    assert "check that the cues sit on the beat" in r.note


def test_a_lossy_file_without_cues_or_grid_is_aligned(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch, "lame", row={"cues": 0},
                   entry={"path": "Library/A/Old Name.mp3", "upgrade": upgrade_of(SHIFTED)})
    no_grid(env)
    go_missing(env)
    r, state = place(env)
    check = state["tracks"][TID]["rekordbox_check"]
    assert (check["aligned"], check["repointed"]) == (True, True)  # the track is pointed at the file all the same
    assert row_of(env)["FolderPath"] == str(env.paths.root / NEW)


def test_the_stored_codec_decides_d_when_the_file_has_one(tmp_path, monkeypatch):
    """The stored codec, not the extension, says the file was a format with no trim: d = 0, measured by nobody."""
    env = make_missing(tmp_path, monkeypatch, "lame", entry={"path": "Library/A/Old Name.mp3"})
    with db.connect(env.paths.db_file) as conn:
        conn.execute("UPDATE files SET file_codec = 'pcm_s16le', file_rate = 44100, file_bits = 16")
        conn.commit()
    r, state = place(env)
    assert state["tracks"][TID]["rekordbox_check"]["aligned"] is True


def test_the_new_file_goes_into_the_playlist_folder_never_the_import_folder(tmp_path, tmp_path_factory, monkeypatch):
    music = tmp_path_factory.mktemp("drive") / "Music"
    old = str(music / "Sub" / "x.mp3")
    env = make_env(tmp_path, monkeypatch, "lame", rekordbox=False, watch=music,
                   entry={"path": old, "upgrade": upgrade_of(SHIFTED), "folder": "Rehearsal"})
    go_missing(env)
    r, state = place(env)
    assert r.path == "Library/Rehearsal/Artist - Song.aiff"
    assert (env.paths.root / r.path).is_file() and not (music / "Sub").exists() or not any((music / "Sub").iterdir())
    assert file_rows(env) == [("Rehearsal/Artist - Song.aiff", "app")]


# --- a different edit, an unknown one: placed as it is ---

@pytest.mark.parametrize("alignment", [Alignment("different", text="doesn't line up"), Alignment("unknown"), None])
def test_a_different_or_unknown_edit_is_placed_as_it_is_and_rekordbox_is_left_alone(tmp_path, monkeypatch, alignment):
    env = make_missing(tmp_path, monkeypatch, alignment=alignment)
    parked_bytes = (env.paths.root / PARKED).read_bytes()
    before, analysis = dump(env.place.db), env.anlz_files()
    r, state = place(env)
    assert (env.paths.root / NEW).read_bytes() == parked_bytes  # k = 0: the download as it is
    check = state["tracks"][TID]["rekordbox_check"]
    assert (check["reason"], check["repointed"], check["rekordbox"]) == ("placed_missing", False, None)
    assert dump(env.place.db) == before and env.anlz_files() == analysis and backup.backups(env.paths) == []
    assert row_of(env)["FolderPath"] == str(env.paths.root / env.old)  # the old track keeps naming the missing file
    assert "isn't the same edit" in r.note
    e = state["tracks"][TID]
    assert (e["path"], e["upgrade"], e["file_gone"]) == (NEW, None, None) and missing_since(env) == [None]


# --- the precondition ---

def assert_untouched(env, music, master_db, analysis):
    assert env.music() == music and dump(env.place.db) == master_db and env.anlz_files() == analysis
    state = load_state(env.paths)
    assert state["pending"] == [] and state["tracks"][TID]["upgrade"]["file"] == PARKED
    assert state["tracks"][TID]["file_gone"] and not (env.paths.tmp / TID).exists() and not env.paths.undo.exists()


def test_a_file_back_since_the_plan_is_refused_and_nothing_is_placed(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    (env.paths.root / env.old).parent.mkdir(parents=True, exist_ok=True)
    (env.paths.root / env.old).write_bytes(b"the user put it back")
    music, db_before, analysis = env.music(), dump(env.place.db), env.anlz_files()
    with pytest.raises(rbstep.Skipped) as e:
        place(env)
    assert e.value.reason == "not_missing" and str(e.value) == rbstep.CONVERT_REFUSED["not_missing"]
    assert_untouched(env, music, db_before, analysis)


def test_a_row_nothing_marked_missing_is_refused_too(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    with db.connect(env.paths.db_file) as conn:
        conn.execute("UPDATE files SET missing_since = NULL")
        conn.commit()
    with pytest.raises(rbstep.Skipped) as e:
        place(env)
    assert e.value.reason == "not_missing"


def test_a_drive_that_is_away_is_refused(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    music, db_before, analysis = env.music(), dump(env.place.db), env.anlz_files()
    monkeypatch.setattr(library, "online", lambda path, roots: False)
    with pytest.raises(rbstep.Skipped) as e:
        place(env)
    assert e.value.reason == "away" and str(e.value) == rbstep.CONVERT_REFUSED["away"]
    assert_untouched(env, music, db_before, analysis)


def test_the_parked_file_deleted_by_hand_is_forgotten_and_the_mark_stays(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    (env.paths.root / PARKED).unlink()
    with pytest.raises(convert.UpgradeProblem) as e:
        place(env)
    assert e.value.forgotten
    state = load_state(env.paths)
    assert state["tracks"][TID]["upgrade"] is None and state["tracks"][TID]["file_gone"]  # the sync downloads it now
    assert state["tracks"][TID]["missing_since"] == SINCE and missing_since(env) == [SINCE]


# --- names, space, rekordbox opening ---

def test_a_name_taken_by_another_file_gets_the_id_as_for_a_download(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    (env.paths.root / NEW).write_bytes(b"someone else's file")
    r, state = place(env)
    assert r.path.startswith("Library/A/Artist - Song ") and r.path.endswith(".aiff") and r.path != NEW
    assert (env.paths.root / NEW).read_bytes() == b"someone else's file"


def test_an_aiff_at_the_clean_name_takes_the_same_path_without_an_id(tmp_path, monkeypatch):
    """The missing row names that very path: it is free (as for a redownload), so no ID is added and the row stays."""
    env = make_missing(tmp_path, monkeypatch, entry={"path": NEW})
    ids = file_ids(env)
    r, state = place(env)
    assert r.path == NEW and file_ids(env) == ids and missing_since(env) == [None]
    assert row_of(env)["FolderPath"] == str(env.paths.root / NEW)


def test_not_enough_space_changes_nothing(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    music, db_before, analysis = env.music(), dump(env.place.db), env.anlz_files()
    monkeypatch.setattr(convert, "free_space", lambda path: 1_000_000)
    with pytest.raises(rbstep.Skipped) as e:
        place(env)
    assert e.value.reason == "space" and e.value.detail["free"] == 1_000_000
    assert_untouched(env, music, db_before, analysis)


def test_rekordbox_open_since_the_batch_began_stops_before_anything(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    music, db_before, analysis = env.music(), dump(env.place.db), env.anlz_files()
    with pytest.raises(RekordboxOpened):
        place(env, running=running_after(2))
    assert_untouched(env, music, db_before, analysis)


def test_rekordbox_opening_at_the_commit_rolls_the_placement_back(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    music, db_before, analysis = env.music(), dump(env.place.db), env.anlz_files()
    real = rbwrite.Writer.repoint
    monkeypatch.setattr(rbwrite.Writer, "repoint",
                        lambda self, c, a, **kw: real(self, c, a, **{**kw, "running": lambda: True}))
    with pytest.raises(RekordboxOpened):
        place(env)
    assert_untouched(env, music, db_before, analysis)
    assert missing_since(env) == [SINCE]  # the song is still missing, marked, its parked download waiting


@pytest.mark.parametrize("case, reason", [("cloud", "cloud"), ("unreadable", "rekordbox_unreadable")])
def test_a_cloud_track_or_an_unreadable_library_refuses_the_repoint(tmp_path, monkeypatch, case, reason):
    env = make_missing(tmp_path, monkeypatch, row={"usn": 5} if case == "cloud" else None)
    if case == "unreadable":
        monkeypatch.setattr("discjockey.rekordbox.master.KEYS", ("00" * 32,))
    music, db_before, analysis = env.music(), dump(env.place.db), env.anlz_files()
    with pytest.raises(rbstep.Skipped) as e:
        place(env)
    assert e.value.reason == reason
    assert_untouched(env, music, db_before, analysis)


# --- the batch item and the journal ---

def test_the_batch_item_is_done_with_the_step_and_the_op_has_no_old_file(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    with db.connect(env.paths.db_file) as conn:
        batch = db.start_aiff_batch(conn, "upgrade", "user", None, [(TID, "same_track")], NOW)
    seen = []
    real = convert._execute
    monkeypatch.setattr(convert, "_execute", lambda paths, state, op, *a: (seen.append(op), real(paths, state, op, *a))[1])
    r, state = place(env, batch=(batch, 0))
    (op,) = seen
    assert (op["kind"], op["source"], op["superseded"], op["old_sha256"], op["old"]) == (
        "convert", "upgrade", None, None, NOT_LOSSLESS_AIFF)
    assert op["missing_since"] == SINCE and op["marks"]["backed_up"] and op["marks"]["committed"]
    (item,) = batch_row(env, batch).items
    assert (item.state, item.result["path"]) == ("done", NEW)
    assert state["tracks"][TID]["rekordbox_check"]["batch"] == batch


def test_every_file_move_goes_through_move_path(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    moves = []
    real = convert.move_path
    monkeypatch.setattr(convert, "move_path", lambda root, src, dst, staged, roots=None:
                        (moves.append((src, dst)), real(root, src, dst, staged, roots))[1])
    place(env)
    assert moves == [(f".discjockey/.tmp/{TID}/convert.aiff", NEW)]  # one move into Library/, nothing to Superseded/


# --- the pure helpers ---

def test_row_change_without_text_plans_no_text_column(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch, row={"Title": "My Edit Name"})
    with master.open_read(env.place, False) as m:
        (entry,) = m.entries_for(env.paths.root / env.old)
        with_text = rbwrite.row_change(entry, "/x/A.aiff", file_size=1, channels=2, frames=44100,
                                       old_tags={"title": "My Edit Name"}, clean={"title": "Song"})
        without = rbwrite.row_change(entry, "/x/A.aiff", file_size=1, channels=2, frames=44100,
                                     old_tags={"title": "My Edit Name"}, clean={"title": "Song"}, text=False)
    assert with_text.text and without.text == {} and without.after == with_text.after


def test_place_quick_and_place_answer_by_the_plan(tmp_path):
    from discjockey.rekordbox import eligible
    ready, unreadable = Status("ready", False, None, None, None, None, None), Status("unreadable", False, None, None, None, None, None)
    e = {"upgrade": {"file": PARKED}}
    assert eligible.place_quick({"upgrade": None}, ready, "missing") == Skip("no_upgrade")
    assert eligible.place_quick(e, ready, "here") == Skip("not_missing")
    assert eligible.place_quick(e, ready, "away") == Skip("away")
    assert eligible.place_quick(e, unreadable, "missing") == Skip("rekordbox_unreadable")
    assert eligible.place_quick(e, ready, "missing") == Eligible()
    # no timing, analysis or edit refusal: a different edit still places
    different = {"upgrade": {"file": PARKED, "alignment": {"result": "different"}}}
    assert eligible.place_quick(different, ready, "missing") == Eligible()
    assert {"not_missing", "away", "no_upgrade", "rekordbox_unreadable"} <= set(eligible.REASONS)


# --- a power cut: the step's own recovery (E4a2 adds its words and the rest of its cases) ---

def test_a_cut_after_the_commit_is_finished_at_the_next_start_with_no_superseded_step(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    power_off(monkeypatch, "committed")
    with pytest.raises(PowerOff):
        place(env)
    monkeypatch.undo()
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(env.folder))
    messages, state = next_start(env)
    e = state["tracks"][TID]
    assert [ok for _m, ok in messages] == [True] and e["path"] == NEW and e["upgrade"] is None
    assert e["file_gone"] is None and missing_since(env) == [None] and state["pending"] == []
    assert not (env.paths.root / "Superseded").exists() and row_of(env)["FolderPath"] == str(env.paths.root / NEW)


def test_a_cut_after_the_file_was_placed_is_rolled_back_and_the_song_stays_missing(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    power_off(monkeypatch, "placed")
    with pytest.raises(PowerOff):
        place(env)
    monkeypatch.undo()
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(env.folder))
    messages, state = next_start(env)
    e = state["tracks"][TID]
    assert [ok for _m, ok in messages] == [False] and e["path"] == NOT_LOSSLESS_AIFF and e["upgrade"]["file"] == PARKED
    assert e["file_gone"] and missing_since(env) == [SINCE] and (env.paths.root / PARKED).is_file()
    assert not (env.paths.root / NEW).exists() and row_of(env)["FolderPath"] == str(env.paths.root / env.old)
