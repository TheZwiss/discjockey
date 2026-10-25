"""folders.py: checking, adding and removing watched folders, the same-song answer, and the Duplicates question's
"Keep both" and "Move to Superseded" on one drive and across two (plan library stage 4, tasks 4.5 and 4.6)."""
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from audio_helpers import music, needs_ffmpeg, write_aiff
from discjockey import db, folders, importer, library
from discjockey.events import CancelToken
from discjockey.library import Paths, empty_state, load_state, save_state
from discjockey.ops import CHANGED, OpProblem
from discjockey.quality import AudioInfo

NOW = datetime(2026, 10, 25, 12, 0, 0)
KEPT = "Library/House/Example Artist - Kept.aiff"


@pytest.fixture
def paths(tmp_path):
    p = Paths(tmp_path / "music", support=tmp_path / "support")
    p.library.mkdir(parents=True)
    p.support.mkdir()
    save_state(p, empty_state())
    return p


def check(paths, path, tmp_path):
    return folders.check_import_folder(path, paths=paths, support=paths.support, program=tmp_path / "app",
                                       home=Path("/Users/you"))  # made up: tmp_path is never above it


def do_import(paths):
    return importer.run_import(paths, token=CancelToken(), link=lambda: None,
                               probe=lambda p: AudioInfo("pcm_s16be", 44100, 1.0),
                               inspect=lambda p: ("pcm_s16be", None))


def playlist_song(paths, seed=1):
    """A playlist song (sp1) whose file Discjockey placed in Library/House/."""
    (paths.root / KEPT).parent.mkdir(parents=True, exist_ok=True)
    write_aiff(paths.root / KEPT, music(1, seed))
    s = load_state(paths)
    s["tracks"]["sp1"] = {"artist": "Example Artist", "title": "Kept", "folder": "House", "path": KEPT,
                          "status": "lossless", "source": "qobuz", "source_id": "123", "source_format": "flac",
                          "cutoff_hz": None, "source_kbps": None}
    save_state(paths, s)
    library.scan_library(paths, analyze=lambda p: ("pcm_s16be", None))


def group(paths):
    with db.connect(paths.db_file) as conn:
        groups = db.duplicate_groups(conn)
        assert len(groups) == 1
        return groups[0].id, db.group_files(conn, groups[0].id)


def log_lines(paths):
    return [json.loads(line) for line in paths.operations_log.read_text().splitlines()]


# --- 4.5 folders ---

def test_a_folder_of_ones_own_can_be_watched(paths, tmp_path):
    folder = tmp_path / "Example Drive" / "Music"
    folder.mkdir(parents=True)
    c = check(paths, folder, tmp_path)
    assert (c.usable, c.problem, c.kind, c.merges) == (True, None, "import", ())
    assert folders.problem_words(c) is None


@pytest.mark.parametrize("where, problem", [
    ("relative/Music", "not_absolute"),
    ("{tmp}/nowhere", "not_found"),
    ("{tmp}/a file.txt", "not_a_folder"),
    ("/System/Library", "system_folder"),
    ("{tmp}/support/Inside", "is_support_dir"),
    ("{tmp}/app/Music", "inside_app"),
    ("{tmp}/music/My Sets", "music"),
    ("{tmp}/music/Library/House", "music"),
    ("{tmp}", "holds_music"),
])
def test_folders_that_cant_be_watched_are_refused(paths, tmp_path, where, problem):
    (tmp_path / "a file.txt").write_text("x")
    for d in ("support/Inside", "app/Music", "music/My Sets", "music/Library/House"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    c = check(paths, where.format(tmp=tmp_path), tmp_path)
    assert (c.usable, c.problem) == (False, problem)
    assert folders.problem_words(c) == folders.IMPORT_PROBLEMS[problem]


def test_w5_words(paths, tmp_path):
    assert folders.problem_words(check(paths, paths.root / "Sets", tmp_path)) is not None
    (paths.root / "Sets").mkdir()
    assert folders.problem_words(check(paths, paths.root / "Sets", tmp_path)) == (
        "This is inside your music folder, which Discjockey watches already.")
    assert folders.problem_words(check(paths, tmp_path, tmp_path)) == (
        "This folder holds your music folder. Choose a folder inside it instead.")


def test_a_folder_inside_a_watched_folder_names_it(paths, tmp_path):
    outer = tmp_path / "Example Drive" / "Music"
    (outer / "House").mkdir(parents=True)
    folders.add(paths, outer, NOW)
    c = check(paths, outer / "House", tmp_path)
    assert (c.usable, c.problem, c.other) == (False, "watched", str(outer.resolve()))
    assert folders.problem_words(c) == f"This is inside {outer.resolve()}, which Discjockey watches already."
    again = check(paths, outer, tmp_path)
    assert (again.usable, again.problem) == (False, "already")


def test_a_folder_that_cant_be_read_is_refused(paths, tmp_path):
    folder = tmp_path / "Locked"
    folder.mkdir()
    folder.chmod(0)
    try:
        if os.access(folder, os.R_OK):
            pytest.skip("this user can read every folder")
        assert check(paths, folder, tmp_path).problem == "not_readable"
    finally:
        folder.chmod(0o755)


def test_a_folder_holding_watched_folders_merges_them(paths, tmp_path):
    drive = tmp_path / "Example Drive"
    (drive / "Music" / "House").mkdir(parents=True)
    (drive / "Sets").mkdir()
    inner = folders.add(paths, drive / "Music" / "House", NOW)
    sets = folders.add(paths, drive / "Sets", NOW)
    c = check(paths, drive, tmp_path)
    assert c.usable and set(c.merges) == {str((drive / "Music" / "House").resolve()), str((drive / "Sets").resolve())}
    assert sorted(folders.merge_hints(c)) == sorted(f"{m} is inside it and becomes part of it." for m in c.merges)
    added = folders.add(paths, drive, NOW)
    assert set(added.merged) == set(c.merges)
    with db.connect(paths.db_file) as conn:
        ids = {f.id for f in db.watched_folders(conn) if f.kind == "import"}
    assert ids == {added.id} and inner.id not in ids and sets.id not in ids


def test_a_library_without_records_yet_is_checked_against_the_music_folder(tmp_path):
    p = Paths(tmp_path / "music", support=tmp_path / "support")
    (tmp_path / "music" / "Sets").mkdir(parents=True)
    (tmp_path / "Elsewhere").mkdir()
    assert check(p, tmp_path / "music" / "Sets", tmp_path).problem == "music"
    assert check(p, tmp_path / "Elsewhere", tmp_path).usable
    assert not p.db_file.exists()  # a check writes nothing
    folders.add(p, tmp_path / "Elsewhere", NOW)  # adding opens the records first
    assert p.db_file.exists()


@needs_ffmpeg
def test_removal_counts_and_removing_a_folder(paths, tmp_path):
    folder = tmp_path / "Example Drive" / "Music"
    folder.mkdir(parents=True)
    for i in (1, 2):
        write_aiff(folder / f"Example Artist - Own {i}.aiff", music(1, seed=10 + i))
    fid = folders.add(paths, folder, NOW).id
    do_import(paths)
    assert folders.removal(paths, fid) == db.RemovalCounts(2, 0)
    assert folders.remove(paths, fid) == db.RemovalCounts(2, 0)
    assert not [k for k in load_state(paths)["tracks"] if k.startswith("local:")]
    assert sorted(p.name for p in folder.iterdir()) == ["Example Artist - Own 1.aiff", "Example Artist - Own 2.aiff"]
    with db.connect(paths.db_file) as conn:
        library_id = next(f.id for f in db.watched_folders(conn) if f.kind == "library")
    with pytest.raises(ValueError):
        folders.remove(paths, library_id)


# --- 4.6 answers ---

def test_the_same_song_answer_is_recorded(paths):
    folders.answer_same_song(paths, "sp1", "local:4", True, NOW)
    folders.answer_same_song(paths, "sp2", "local:5", False, NOW)
    with db.connect(paths.db_file) as conn:
        assert db.decisions(conn)["same_song"] == [["sp1", "local:4", "same"], ["sp2", "local:5", "not_same"]]
    with pytest.raises(ValueError):
        folders.answer_same_song(paths, "sp1", "sp2", True, NOW)


@needs_ffmpeg
def test_keep_both_ends_the_question(paths, tmp_path):
    folder = tmp_path / "Example Drive" / "Music"
    folder.mkdir(parents=True)
    write_aiff(folder / "Example Artist - Twice.aiff", music(1, seed=3))
    shutil.copy(folder / "Example Artist - Twice.aiff", folder / "Example Artist - Twice copy.aiff")
    folders.add(paths, folder, NOW)
    do_import(paths)
    gid, _ = group(paths)
    folders.keep_both(paths, gid, NOW)
    with db.connect(paths.db_file) as conn:
        assert db.duplicate_groups(conn) == []


# --- 4.6 move to Superseded ---

def copies(paths, tmp_path):
    folder = tmp_path / "Example Drive" / "Music"
    (folder / "House").mkdir(parents=True)
    write_aiff(folder / "House" / "Example Artist - Twice.aiff", music(1, seed=4))
    shutil.copy(folder / "House" / "Example Artist - Twice.aiff", folder / "Example Artist - Twice copy.aiff")
    folders.add(paths, folder, NOW)
    do_import(paths)
    return folder


@needs_ffmpeg
def test_a_copy_moves_to_superseded_mirroring_its_folder(paths, tmp_path):
    folder = copies(paths, tmp_path)
    gid, files = group(paths)
    moved = next(f for f in files if f.path.endswith("House/Example Artist - Twice.aiff"))
    messages = []
    dst = folders.supersede(paths, gid, moved.file_id, emit=messages.append, now=lambda: NOW)
    assert dst == "Superseded/Music/House/Example Artist - Twice.aiff"
    assert (paths.root / dst).is_file() and not (folder / "House" / "Example Artist - Twice.aiff").exists()
    assert (folder / "Example Artist - Twice copy.aiff").is_file()
    own = [e for k, e in load_state(paths)["tracks"].items() if k.startswith("local:")]
    assert [Path(e["path"]).name for e in own] == ["Example Artist - Twice copy.aiff"]
    line = log_lines(paths)[-1]
    assert (line["operation"], line["result"], line["message"]) == ("move_to_superseded", "done", f"Moved to {dst}.")
    assert [m.text for m in messages] == [f"Moved to {dst}."]
    with db.connect(paths.db_file) as conn:
        assert db.duplicate_groups(conn) == [] and db.pending_ops(conn) == []


def heir_setup(paths, tmp_path):
    """sp1's file in Library/House/ and a copy of it in an import folder, imported as an own song."""
    playlist_song(paths, seed=5)
    drive = tmp_path / "Example Drive" / "Music"
    drive.mkdir(parents=True)
    shutil.copy(paths.root / KEPT, drive / "Example Artist - Kept.aiff")
    folders.add(paths, drive, NOW)
    do_import(paths)
    gid, files = group(paths)
    library_file = next(f for f in files if f.song_key == "sp1")
    return drive, gid, library_file


@needs_ffmpeg
def test_the_own_copy_takes_over_the_playlist_song_whose_file_moves(paths, tmp_path):
    drive, gid, library_file = heir_setup(paths, tmp_path)
    dst = folders.supersede(paths, gid, library_file.file_id, now=lambda: NOW)
    assert dst == "Superseded/House/Example Artist - Kept.aiff" and (paths.root / dst).is_file()
    tracks = load_state(paths)["tracks"]
    assert tracks["sp1"]["path"] == str((drive / "Example Artist - Kept.aiff").resolve())
    assert not [k for k in tracks if k.startswith("local:")]  # its own song is gone: one file per song
    assert log_lines(paths)[-1]["track_id"] == "sp1" and log_lines(paths)[-1]["title"] == "Kept"


@needs_ffmpeg
def test_a_move_to_superseded_across_drives(paths, tmp_path, monkeypatch):
    drive, gid, library_file = heir_setup(paths, tmp_path)
    with db.connect(paths.db_file) as conn:
        own_file = next(f for f in db.group_files(conn, gid) if f.file_id != library_file.file_id)
    real = library.device
    monkeypatch.setattr(library, "device", lambda p: 2 if Path(p).is_relative_to(drive.resolve()) else real(p))
    before = (drive / "Example Artist - Kept.aiff").read_bytes()
    assert library.crosses(paths.root, own_file.path, "Superseded/Music/x.aiff")
    dst = folders.supersede(paths, gid, own_file.file_id, now=lambda: NOW)
    assert dst == "Superseded/Music/Example Artist - Kept.aiff"
    assert (paths.root / dst).read_bytes() == before
    assert not (drive / "Example Artist - Kept.aiff").exists()
    assert not [p for p in (paths.root / "Superseded").rglob(".*")]  # no staged copy left
    tracks = load_state(paths)["tracks"]
    assert tracks["sp1"]["path"] == KEPT and not [k for k in tracks if k.startswith("local:")]


@needs_ffmpeg
def test_a_group_that_changed_is_refused_and_nothing_moves(paths, tmp_path):
    folder = copies(paths, tmp_path)
    gid, files = group(paths)
    shutil.copy(folder / "Example Artist - Twice copy.aiff", folder / "Example Artist - Twice again.aiff")
    library.scan_library(paths, analyze=lambda p: ("pcm_s16be", None))  # a third copy: another group
    with pytest.raises(OpProblem) as refused:
        folders.supersede(paths, gid, files[0].file_id, now=lambda: NOW)
    assert (refused.value.kind, str(refused.value)) == ("changed", CHANGED)
    assert not (paths.root / "Superseded").exists()
    assert log_lines(paths)[-1]["result"] == "changed"


@needs_ffmpeg
def test_a_group_answered_keep_both_or_a_file_not_in_it_is_refused(paths, tmp_path):
    copies(paths, tmp_path)
    gid, files = group(paths)
    with pytest.raises(OpProblem):
        folders.supersede(paths, gid, 999, now=lambda: NOW)
    with pytest.raises(OpProblem):
        folders.supersede(paths, "not a group", files[0].file_id, now=lambda: NOW)
    folders.keep_both(paths, gid, NOW)
    with pytest.raises(OpProblem):
        folders.supersede(paths, gid, files[0].file_id, now=lambda: NOW)
    assert not (paths.root / "Superseded").exists()


@needs_ffmpeg
def test_a_refused_move_moves_nothing_and_says_why(paths, tmp_path, monkeypatch):
    folder = copies(paths, tmp_path)
    gid, files = group(paths)

    def refused(*a, **kw):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(library, "move_path", refused)
    with pytest.raises(OpProblem) as failed:
        folders.supersede(paths, gid, files[0].file_id, now=lambda: NOW)
    assert failed.value.kind == "failed" and str(failed.value).startswith("Nothing was moved: ")
    assert len(list(folder.rglob("*.aiff"))) == 2
    with db.connect(paths.db_file) as conn:
        assert db.pending_ops(conn) == [] and len(db.duplicate_groups(conn)) == 1


@needs_ffmpeg
def test_a_name_taken_in_superseded_gets_a_counter_never_an_id_for_an_own_song(paths, tmp_path):
    copies(paths, tmp_path)
    gid, files = group(paths)
    moved = next(f for f in files if f.path.endswith("House/Example Artist - Twice.aiff"))
    taken = paths.root / "Superseded/Music/House/Example Artist - Twice.aiff"
    taken.parent.mkdir(parents=True)
    taken.write_bytes(b"an earlier replaced file")
    dst = folders.supersede(paths, gid, moved.file_id, now=lambda: NOW)
    assert dst == "Superseded/Music/House/Example Artist - Twice (2).aiff"
    assert taken.read_bytes() == b"an earlier replaced file"
