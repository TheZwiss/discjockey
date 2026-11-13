"""Same track for a file that isn't AIFF (discjockey/convert.py; plan stage B §1.8, §1.9, §5.2 B3): the new AIFF's
name, place, tags and timing, the rekordbox track pointed at it, the records, and every refusal with nothing written.
Each library and rekordbox library is built in tmp_path (tests/convert_helpers.py)."""
from __future__ import annotations

import numpy as np
import pytest
from mutagen.aiff import AIFF

from audio_helpers import needs_ffmpeg, pcm
from convert_helpers import (
    NEW, PARKED, TID, batch_row, exact, file_rows, make_env, never, run, session, start_batch,
)
from discjockey import convert, library, rbstep
from discjockey.align import Alignment
from discjockey.library import load_state
from discjockey.rekordbox import anlz, backup, master
from discjockey.rekordbox import write as rbwrite
from discjockey.rekordbox.write import RekordboxOpened
from rekordbox_helpers import dump, running_after

pytestmark = needs_ffmpeg


def ppth_of(path) -> str:
    return anlz.ppth(anlz.read(path))


def row_of(env, row_id="1") -> dict:
    with master.open_read(env.place, False) as m:
        cur = m.con.execute("SELECT * FROM djmdContent WHERE ID = ?", (row_id,))
        return dict(zip([c[0] for c in cur.description], cur.fetchone()))


@pytest.mark.parametrize("kind", ["lame", "notag", "m4a", "wav48"])
def test_the_new_aiff_sits_on_rekordboxs_timeline(tmp_path, monkeypatch, kind):
    """The audio is where rekordbox's cues sit: ffmpeg's decode of the old file moved by rekordbox's own offset d
    (exact to the sample: the parked download is that decode, L = 0)."""
    env = make_env(tmp_path, monkeypatch, kind)
    parked = pcm(env.paths.root / PARKED)
    r, state = run(env)
    out = pcm(env.paths.root / NEW)
    assert r.path == NEW and state["tracks"][TID]["path"] == NEW
    assert np.all(out[:env.d] == 0) and np.array_equal(out[env.d:], parked)
    assert (kind, env.d > 0) in (("lame", True), ("notag", False), ("m4a", True), ("wav48", False))


def test_same_track_for_an_mp3(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    old_bytes = (env.paths.root / env.old).read_bytes()
    parked_bytes = (env.paths.root / PARKED).read_bytes()
    r, state = run(env)
    root = env.paths.root
    # files: the new AIFF with the download's name and tags, the old one mirrored into Superseded/ under its name
    assert (root / env.superseded).read_bytes() == old_bytes and not (root / env.old).exists()
    assert str(AIFF(str(root / NEW)).tags["TIT2"]) == "Song" and str(AIFF(str(root / NEW)).tags["TPUB"]) == "Label"
    e = state["tracks"][TID]
    held = e["rekordbox_check"]["undo"]["held"]
    assert held.startswith(".discjockey/undo/") and (root / held).read_bytes() == parked_bytes
    assert not (root / PARKED).exists() and not (env.paths.tmp / TID).exists()
    # the record and its check
    assert (e["path"], e["status"], e["source"], e["upgrade"]) == (NEW, "lossless", "qobuz", None)
    check = e["rekordbox_check"]
    assert {k: check[k] for k in ("reason", "since", "match", "aligned", "batch")} == {
        "reason": "repointed", "since": "2026-11-08", "match": "exact", "aligned": True, "batch": None}
    assert check["rekordbox"] == {"entries": ["1"], "kept": []}
    undo = check["undo"]
    assert (undo["kind"], undo["file"], undo["old"]) == ("convert", NEW, env.superseded)
    assert undo["before"]["path"] == env.old and undo["before"]["upgrade"]["file"] == PARKED
    assert undo["file_key"] and undo["old_key"] and undo["repoint"]["dbid"] == "1234567890"
    assert [r_["id"] for r_ in undo["repoint"]["rows"]] == ["1"]
    assert load_state(env.paths)["tracks"][TID] == e and state["pending"] == []
    assert file_rows(env) == [("A/Artist - Song.aiff", "app")]
    # rekordbox: the track plays the new file, its analysis files name it, its title is the clean one
    row = row_of(env)
    assert row["FolderPath"] == str(root / NEW) and row["FileNameL"] == "Artist - Song.aiff"
    assert (row["FileType"], row["BitDepth"], row["SampleRate"], row["BitRate"]) == (12, 16, 44100, 1411)
    assert row["Title"] == "Song"
    assert ppth_of(env.dat()) == "?/Artist - Song.aiff"
    assert ppth_of(env.dat().with_suffix(".EXT")) == "?/Artist - Song.aiff"
    # one backup, holding the analysis as it was
    (b,) = backup.backups(env.paths)
    assert (b.batches, b.tracks) == ([], 1)
    assert "nothing to keep" not in r.note and "Kept" not in r.note


def test_the_users_own_rekordbox_title_is_kept_and_said(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch, row={"Title": "My Edit Name"})
    r, state = run(env)
    assert row_of(env)["Title"] == "My Edit Name"
    assert state["tracks"][TID]["rekordbox_check"]["rekordbox"]["kept"] == ["title"]
    assert r.note.endswith("Kept your own title in rekordbox.")


def set_old_comment(env, text):
    from mutagen.id3 import COMM, ID3, ID3NoHeaderError
    path = env.paths.root / env.old
    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        tags = ID3()
    tags.setall("COMM", [COMM(encoding=3, lang="eng", desc="", text=text)])
    tags.save(str(path))


def new_comment(env) -> str:
    return str(AIFF(str(env.paths.root / NEW)).tags.getall("COMM")[0].text[0])


def test_a_comment_of_the_users_own_stays_in_the_new_file_and_in_rekordbox(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch, row={"Commnt": "1A - Energy 6"})
    set_old_comment(env, "1A - Energy 6")                        # Mixed In Key's: key and energy
    r, state = run(env)
    assert new_comment(env) == "1A - Energy 6"                    # the download's quality line did not replace it
    assert row_of(env)["Commnt"] == "1A - Energy 6" and row_of(env)["ISRC"] == "ISRC00000001"
    assert state["tracks"][TID]["rekordbox_check"]["rekordbox"]["kept"] == []
    assert "Kept" not in r.note


def test_an_edited_comment_in_rekordbox_stays_when_the_old_file_had_a_quality_line(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch, row={"Commnt": "my gig notes"})
    set_old_comment(env, "YouTube Music OPUS · cutoff 16.0 kHz")
    _r, state = run(env)
    assert new_comment(env) == "Qobuz FLAC · verified lossless"    # our own line is replaced in the file
    assert row_of(env)["Commnt"] == "my gig notes"                 # rekordbox shows another text: the user's
    assert state["tracks"][TID]["rekordbox_check"]["rekordbox"]["kept"] == ["comment"]


def test_a_quality_line_of_ours_in_rekordbox_is_replaced(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch, row={"Commnt": "YouTube Music OPUS · cutoff 16.0 kHz"})
    set_old_comment(env, "YouTube Music OPUS · cutoff 16.0 kHz")
    _r, state = run(env)
    assert row_of(env)["Commnt"] == "Qobuz FLAC · verified lossless" == new_comment(env)
    assert state["tracks"][TID]["rekordbox_check"]["rekordbox"]["kept"] == []


def test_a_file_in_not_lossless_moves_up_and_a_taken_name_gets_an_id(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch, entry={"path": "Library/A/not_lossless/Old Name.mp3"})
    (env.paths.root / NEW).write_bytes(b"someone else's file")
    r, state = run(env)
    assert r.path.startswith("Library/A/Artist - Song ") and r.path.endswith(".aiff")  # the ID, only because taken
    assert (env.paths.root / NEW).read_bytes() == b"someone else's file"
    old = state["tracks"][TID]["rekordbox_check"]["undo"]["old"]
    assert old.startswith("Superseded/") and old.endswith("/Old Name.mp3") and (env.paths.root / old).is_file()
    assert row_of(env)["FolderPath"] == str(env.paths.root / r.path)


@pytest.mark.parametrize("rekordbox, holds_file", [(False, False), (True, False)])
def test_without_a_rekordbox_track_no_database_is_touched(tmp_path, monkeypatch, rekordbox, holds_file):
    env = make_env(tmp_path, monkeypatch, rekordbox=rekordbox, holds_file=holds_file)
    before = dump(env.place.db) if rekordbox else None
    analysis = env.anlz_files()
    r, state = run(env)
    assert r.path == NEW and (env.paths.root / env.superseded).is_file()
    assert r.note.endswith(rbstep.NO_TRACK_NOTE)
    check = state["tracks"][TID]["rekordbox_check"]
    assert check["rekordbox"] is None and check["undo"]["repoint"] is None
    assert env.anlz_files() == analysis and backup.backups(env.paths) == []
    if rekordbox:
        assert dump(env.place.db) == before
    # no rekordbox: d = 0, the download as it is
    assert (env.paths.root / NEW).read_bytes() == (env.paths.root / check["undo"]["held"]).read_bytes()


def test_the_batch_item_is_done_with_the_step(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    batch = start_batch(env)
    r, state = run(env, batch=(batch, 0))
    row = batch_row(env, batch)
    (item,) = row.items
    assert (item.state, item.result["path"], item.result["rekordbox"]) == ("done", NEW, {"entries": ["1"],
                                                                                         "kept": []})
    assert state["tracks"][TID]["rekordbox_check"]["batch"] == batch


# --- refusals: nothing written ---

def assert_nothing_changed(env, music, master, analysis):
    assert env.music() == music
    assert env.place is None or dump(env.place.db) == master
    assert env.anlz_files() == analysis
    state = load_state(env.paths)
    assert state["pending"] == [] and state["tracks"][TID]["upgrade"]["file"] == PARKED
    assert not (env.paths.tmp / TID).exists() and not env.paths.undo.exists()


def different(current, new):
    return Alignment("different", text="doesn't line up: a swap would shift your cue points")


def unknown(current, new):
    return Alignment("unknown", text="could not compare the two versions")


@pytest.mark.parametrize("case, reason", [
    ("different_edit", "needs_choice"), ("unknown_edit", "needs_choice"), ("not_analysed", "not_analysed"), ("timing", "timing"), ("cloud", "cloud"),
    ("space", "space"), ("unclean", "unclean"), ("unreadable", "rekordbox_unreadable")])
def test_refusals_change_nothing(tmp_path, monkeypatch, case, reason):
    kw = {"not_analysed": {"analysed": False}, "timing": {"extra_s": 0.03},
          "cloud": {"row": {"usn": 5}}}.get(case, {})
    env = make_env(tmp_path, monkeypatch, **kw)
    if case == "space":
        monkeypatch.setattr(convert, "free_space", lambda path: 1_000_000)
    if case == "unclean":
        env.place.db.with_name("master.db-wal").write_bytes(b"")
    if case == "unreadable":
        monkeypatch.setattr("discjockey.rekordbox.master.KEYS", ("00" * 32,))
    music, master, analysis = env.music(), dump(env.place.db), env.anlz_files()
    with pytest.raises(rbstep.Skipped) as e:
        run(env, compare=different if case == "different_edit" else unknown if case == "unknown_edit" else exact)
    assert e.value.reason == reason
    if case == "unknown_edit":  # design §8: the files could not be compared; never "isn't the same edit"
        assert str(e.value) == ("Discjockey couldn't compare the two files, so nothing was changed. Try again, or "
                                "choose New track.")
    if case == "different_edit":
        assert "isn't the same edit" in str(e.value)
    if case == "space":
        assert e.value.detail["free"] == 1_000_000 and "needed, 1 MB free" in str(e.value)
    elif reason in rbstep.REFUSED and case not in ("different_edit", "unknown_edit"):
        assert str(e.value) == rbstep.REFUSED[reason]
    if case == "unclean":
        env.place.db.with_name("master.db-wal").unlink()
    assert_nothing_changed(env, music, master, analysis)


def test_rekordbox_open_since_the_batch_began_stops_before_anything(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    music, master, analysis = env.music(), dump(env.place.db), env.anlz_files()
    with pytest.raises(RekordboxOpened):
        run(env, running=running_after(2))  # closed at the session's start, open from then on
    assert_nothing_changed(env, music, master, analysis)


def test_rekordbox_opening_at_the_commit_rolls_the_step_back(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    music, master, analysis = env.music(), dump(env.place.db), env.anlz_files()
    real = rbwrite.Writer.repoint
    monkeypatch.setattr(rbwrite.Writer, "repoint",
                        lambda self, c, a, **kw: real(self, c, a, **{**kw, "running": lambda: True}))
    with pytest.raises(RekordboxOpened):
        run(env)
    assert_nothing_changed(env, music, master, analysis)


def test_a_track_changed_meanwhile_is_refused_and_rolled_back(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    music, analysis = env.music(), env.anlz_files()
    real = rbwrite.Writer.repoint

    def moved_meanwhile(self, changes, splices, **kw):
        self.con.execute("UPDATE djmdContent SET FolderPath = '/Users/dj/Music/Elsewhere.mp3' WHERE ID = '1'")
        return real(self, changes, splices, **kw)
    monkeypatch.setattr(rbwrite.Writer, "repoint", moved_meanwhile)
    with pytest.raises(rbstep.Skipped) as e:
        run(env)
    assert e.value.reason == "changed" and str(e.value) == rbstep.REFUSED["changed"]
    assert env.music() == music and env.anlz_files() == analysis


def test_every_file_move_goes_through_move_path(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    moves = []
    real = convert.move_path
    monkeypatch.setattr(convert, "move_path", lambda root, src, dst, staged, roots=None:
                        (moves.append((src, dst)), real(root, src, dst, staged, roots))[1])
    renames = []
    real_rename = library.os.rename
    monkeypatch.setattr(library.os, "rename", lambda s, d: (renames.append((str(s), str(d))), real_rename(s, d))[1])
    run(env)
    assert moves == [(f".discjockey/.tmp/{TID}/convert.aiff", NEW), (env.old, env.superseded)]
    library_renames = [(s, d) for s, d in renames if "/Library/" in s or "/Library/" in d]
    assert len(library_renames) == 2  # the two moves, nothing else in Library/


def test_the_staged_aiff_reaches_an_import_folder_on_another_drive(tmp_path, tmp_path_factory, monkeypatch):
    music = tmp_path_factory.mktemp("drive") / "Music"
    env = make_env(tmp_path, monkeypatch, rekordbox=False, entry={"path": str(music / "Sub" / "x.mp3")}, watch=music)
    monkeypatch.setattr(library, "device", lambda p: 2 if str(p).startswith(str(music)) else 1)
    r, state = run(env)
    assert r.path == str(music / "Sub" / "Artist - Song.aiff") and (music / "Sub" / "Artist - Song.aiff").is_file()
    assert not any(p.name.startswith(".") for p in (music / "Sub").iterdir())
    assert (env.paths.root / "Superseded/Music/Sub/x.mp3").is_file()


def test_an_aiff_is_not_converted(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch, rekordbox=False)
    state = load_state(env.paths)
    state["tracks"][TID]["path"] = PARKED  # any AIFF
    with session(env, never) as s, pytest.raises(convert.UpgradeProblem):
        convert.same_track(env.paths, state, TID, dict(state["tracks"][TID]["upgrade"]), session=s)


def test_a_pending_convert_step_and_its_undo_record_keep_their_files():
    op = {"kind": "convert", "old": "Library/A/x.mp3", "new": "Library/A/Artist - Song.aiff",
          "superseded": "Superseded/A/x.mp3", "staged": ".discjockey/.tmp/t1/convert.aiff",
          "parked": PARKED, "held": ".discjockey/undo/t1/Artist - Song.aiff",
          "crossing": {"0": "Library/A/.Artist - Song.aiff.discjockey-move"}, "target": "ignored"}
    assert library.op_paths(op) == ["Library/A/x.mp3", "Library/A/Artist - Song.aiff", "Superseded/A/x.mp3",
                                    ".discjockey/.tmp/t1/convert.aiff", PARKED, ".discjockey/undo/t1/Artist - Song.aiff",
                                    "Library/A/.Artist - Song.aiff.discjockey-move"]
    undo = {"kind": "convert", "before": {"path": "Library/A/x.mp3", "upgrade": {"file": PARKED}},
            "held": ".discjockey/undo/t1/Artist - Song.aiff", "old": "Superseded/A/x.mp3"}
    assert library.undo_paths(undo) == ["Library/A/x.mp3", PARKED, ".discjockey/undo/t1/Artist - Song.aiff",
                                        "Superseded/A/x.mp3"]


def test_plan_names_and_space_needed_answer_the_dry_run_without_writing(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    state = load_state(env.paths)
    music = env.music()
    new, superseded = convert.plan_names(env.paths, state, TID, state["tracks"][TID], state["tracks"][TID]["upgrade"])
    assert (new, superseded) == (NEW, env.superseded)
    places = convert.space_needed(env.paths, env.paths.root / PARKED, new)
    assert places and all(need > 0 and convert.free_space(place) > 0 for place, need in places)
    assert len({need for _place, need in places}) == 1 and places[0][0] == env.paths.tmp
    assert env.music() == music and load_state(env.paths)["pending"] == []        # nothing written, nothing reserved
    r, _state = run(env)                                                           # and the step names the same
    assert (r.path, env.superseded) == (new, superseded)
