"""Moves across drives (plan library stage 4, I7): library.move_path, run_op's crossing renames and their recovery,
and the file journal (library.move_files). A second drive is simulated by replacing library.device."""
import errno
import os
from datetime import datetime
from pathlib import Path

import pytest

from discjockey import db, library
from discjockey.library import Paths, empty_state, load_state, move_path, recover_pending, run_op, save_state


@pytest.fixture
def paths(tmp_path):
    p = Paths(tmp_path / "Music", support=tmp_path / ".support")
    (p.library / "A").mkdir(parents=True)
    p.data.mkdir()
    return p


@pytest.fixture
def other(tmp_path, monkeypatch):
    """A folder on "another drive": library.device says 2 for anything in it, 1 elsewhere."""
    drive = tmp_path / "Other"
    drive.mkdir()
    monkeypatch.setattr(library, "device", lambda p: 2 if Path(p).is_relative_to(drive) else 1)
    return drive


def touch(path: Path, data=b"audio") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def staged_of(dst: Path) -> Path:
    return dst.with_name(f".{dst.name}{library.STAGED_SUFFIX}")


# --- 2.1 one rename ---

def test_on_one_drive_it_is_a_rename(paths):
    src = touch(paths.library / "A/x.aiff")
    ino = src.stat().st_ino
    move_path(paths.root, "Library/A/x.aiff", "Library/B/x.aiff", "Library/B/.x.aiff.discjockey-move")
    dst = paths.library / "B/x.aiff"
    assert not src.exists() and dst.stat().st_ino == ino  # the same file, not a copy
    assert not staged_of(dst).exists()


def test_to_another_drive_it_copies_verifies_renames_then_removes_the_source(paths, other):
    src = touch(paths.library / "A/x.aiff", b"the audio")
    os.utime(src, ns=(1_000_000_000, 2_000_000_000))
    dst = other / "Music/x.aiff"
    move_path(paths.root, "Library/A/x.aiff", str(dst), library.staging_path(str(dst)), [paths.root, other])
    assert not src.exists() and dst.read_bytes() == b"the audio"
    assert dst.stat().st_mtime_ns == 2_000_000_000  # the next scan sees the same file
    assert not staged_of(dst).exists()


def test_the_staged_copy_is_hidden_beside_the_target_with_no_audio_extension():
    assert library.staging_path("/Volumes/Example/Music/A - S.flac") == "/Volumes/Example/Music/.A - S.flac.discjockey-move"
    assert library.staging_path("Library/F/A - S.aiff") == "Library/F/.A - S.aiff.discjockey-move"


def test_a_full_drive_leaves_the_source_and_no_staged_copy(paths, other, monkeypatch):
    src = touch(paths.library / "A/x.aiff")
    dst = other / "x.aiff"

    def full(fd):
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(library, "full_fsync", full)
    with pytest.raises(OSError) as e:
        move_path(paths.root, "Library/A/x.aiff", str(dst), library.staging_path(str(dst)))
    assert e.value.errno == errno.ENOSPC
    assert src.read_bytes() == b"audio" and not dst.exists() and not staged_of(dst).exists()


def test_a_copy_that_does_not_match_raises_and_keeps_the_source(paths, other, monkeypatch):
    src = touch(paths.library / "A/x.aiff")
    dst = other / "x.aiff"
    monkeypatch.setattr(library, "file_sha256", lambda p: "0" * 64)
    with pytest.raises(OSError, match="didn't match"):
        move_path(paths.root, "Library/A/x.aiff", str(dst), library.staging_path(str(dst)))
    assert src.exists() and not dst.exists() and not staged_of(dst).exists()


def test_a_taken_target_on_another_drive_is_refused_before_copying(paths, other):
    src = touch(paths.library / "A/x.aiff")
    dst = touch(other / "x.aiff", b"someone else's")
    with pytest.raises(FileExistsError):
        move_path(paths.root, "Library/A/x.aiff", str(dst), library.staging_path(str(dst)))
    assert src.exists() and dst.read_bytes() == b"someone else's" and not staged_of(dst).exists()


def test_a_source_that_cannot_be_removed_stays_the_only_file(paths, other, monkeypatch):
    src = touch(paths.library / "A/x.aiff")
    dst = other / "x.aiff"
    real = os.unlink

    def unlink(p, *a, **kw):
        if Path(p) == src:
            raise PermissionError(errno.EROFS, "Read-only file system")
        real(p, *a, **kw)
    monkeypatch.setattr(os, "unlink", unlink)
    with pytest.raises(library.SourceKept) as e:
        move_path(paths.root, "Library/A/x.aiff", str(dst), library.staging_path(str(dst)))
    assert e.value.errno == errno.EROFS
    assert src.exists() and not dst.exists() and not staged_of(dst).exists()


def test_a_staged_copy_an_earlier_try_left_is_replaced(paths, other):
    touch(paths.library / "A/x.aiff", b"full audio")
    dst = other / "x.aiff"
    touch(staged_of(dst), b"half")
    move_path(paths.root, "Library/A/x.aiff", str(dst), library.staging_path(str(dst)))
    assert dst.read_bytes() == b"full audio" and not staged_of(dst).exists()


# --- 2.2 run_op across drives and its recovery ---

def test_run_op_records_the_staged_copy_and_size_before_copying(paths, other, monkeypatch):
    touch(paths.library / "A/x.aiff", b"12345")
    dst = str(other / "x.aiff")
    seen = []
    real = library._copy_verified

    def copy(src, staged):
        seen.append(load_state(paths)["pending"][0])
        real(src, staged)
    monkeypatch.setattr(library, "_copy_verified", copy)
    s = empty_state()
    run_op(paths, s, "t1", [("Library/A/x.aiff", dst)], None)
    assert seen[0]["staged"] == {"0": library.staging_path(dst)} and seen[0]["size"] == {"0": 5}
    assert (other / "x.aiff").read_bytes() == b"12345" and load_state(paths)["pending"] == []


def test_a_step_on_one_drive_records_no_staging(paths, monkeypatch):
    touch(paths.library / "A/x.aiff")
    seen = []
    real = library.safe_rename

    def rename(root, src, dst):
        seen.append(load_state(paths)["pending"][0])
        real(root, src, dst)
    monkeypatch.setattr(library, "safe_rename", rename)
    run_op(paths, empty_state(), "t1", [("Library/A/x.aiff", "Library/B/x.aiff")], None)
    assert "staged" not in seen[0] and "size" not in seen[0]


def crossing_step(paths, other, *, src, staged, dst, staged_data=b"audio"):
    """A run_op step whose rename to the other drive was cut off, with the disk as a crash left it: the source,
    the staged copy and the target there or not."""
    target = other / "x.aiff"
    s = empty_state()
    s["pending"].append({"track_id": "t1", "renames": [["Library/A/x.aiff", str(target)]], "entry": None,
                         "label": "A - S", "staged": {"0": library.staging_path(str(target))},
                         "size": {"0": len(b"audio")}})
    save_state(paths, s)
    if src:
        touch(paths.library / "A/x.aiff")
    if staged:
        touch(staged_of(target), staged_data)
    if dst:
        touch(target, dst if isinstance(dst, bytes) else b"audio")
    return load_state(paths), paths.library / "A/x.aiff", target


@pytest.mark.parametrize("staged", [False, True])
def test_recovery_with_the_source_and_no_target_does_the_move_again(paths, other, staged):
    state, src, dst = crossing_step(paths, other, src=True, staged=staged, dst=False, staged_data=b"au")
    msgs = recover_pending(paths, state)
    assert msgs == [("Finished an interrupted step for A - S", True)]
    assert not src.exists() and dst.read_bytes() == b"audio" and not staged_of(dst).exists()
    assert load_state(paths)["pending"] == []


@pytest.mark.parametrize("staged", [False, True])
def test_recovery_with_the_same_file_in_both_places_removes_the_source(paths, other, staged):
    state, src, dst = crossing_step(paths, other, src=True, staged=staged, dst=True)
    assert recover_pending(paths, state)[0][1] is True
    assert not src.exists() and dst.read_bytes() == b"audio" and not staged_of(dst).exists()


def test_recovery_with_a_different_file_at_the_target_is_both_exist(paths, other):
    state, src, dst = crossing_step(paths, other, src=True, staged=False, dst=b"another song")
    (message, ok), = recover_pending(paths, state)
    assert not ok and "both" in message
    assert src.read_bytes() == b"audio" and dst.read_bytes() == b"another song"  # nothing removed


@pytest.mark.parametrize("staged", [False, True])
def test_recovery_with_only_the_target_is_done(paths, other, staged):
    state, src, dst = crossing_step(paths, other, src=False, staged=staged, dst=True)
    assert recover_pending(paths, state)[0][1] is True
    assert dst.exists() and not staged_of(dst).exists()


def test_recovery_with_only_a_whole_staged_copy_gives_it_the_target_name(paths, other):
    state, src, dst = crossing_step(paths, other, src=False, staged=True, dst=False)
    assert recover_pending(paths, state)[0][1] is True
    assert dst.read_bytes() == b"audio" and not staged_of(dst).exists()


def test_recovery_with_only_a_partial_staged_copy_removes_it_and_says_neither_exists(paths, other):
    state, src, dst = crossing_step(paths, other, src=False, staged=True, dst=False, staged_data=b"aud")
    (message, ok), = recover_pending(paths, state)
    assert not ok and "neither" in message
    assert not staged_of(dst).exists() and not dst.exists()  # the source's drive is there: it is truly gone
    assert load_state(paths)["pending"] == []


def test_a_crash_between_the_copy_taking_its_name_and_the_source_removal_is_finished(paths, other, monkeypatch):
    src = touch(paths.library / "A/x.aiff")
    dst = other / "x.aiff"
    real_unlink, real_save, saves = os.unlink, library.save_state, []

    def unlink(p, *a, **kw):
        if Path(p) == src:
            raise SystemExit("power cut")
        real_unlink(p, *a, **kw)

    def save(paths_, state, **kw):
        if saves:
            raise SystemExit("power cut")  # nothing after the cut runs, not even the rollback
        saves.append(1)
        real_save(paths_, state, **kw)
    monkeypatch.setattr(os, "unlink", unlink)
    monkeypatch.setattr(library, "save_state", save)
    with pytest.raises(SystemExit):
        run_op(paths, empty_state(), "t1", [("Library/A/x.aiff", str(dst))], None, label="A - S")
    monkeypatch.undo()
    assert src.exists() and dst.exists()
    state = load_state(paths)
    assert recover_pending(paths, state) == [("Finished an interrupted step for A - S", True)]
    assert not src.exists() and dst.read_bytes() == b"audio" and load_state(paths)["pending"] == []


def test_op_paths_names_the_staged_copies_of_a_crossing_step():
    op = {"kind": "files", "renames": [["Library/A/x.aiff", "/Volumes/Example/x.aiff"]],
          "staged": {"0": "/Volumes/Example/.x.aiff.discjockey-move"}, "size": {"0": 5}}
    assert library.op_paths(op) == ["Library/A/x.aiff", "/Volumes/Example/x.aiff",
                                    "/Volumes/Example/.x.aiff.discjockey-move"]


# --- 2.3 the file journal ---

def one_song(paths):
    touch(paths.library / "A/S.aiff")
    s = empty_state()
    s["tracks"]["t1"] = {"artist": "A", "title": "S", "path": "Library/A/S.aiff", "status": "lossless"}
    save_state(paths, s)
    return load_state(paths)["tracks"]["t1"]["file_id"]


def generation(paths) -> int:
    with db.connect(paths.db_file) as conn:
        return db._generation(conn)


def pending(paths) -> list[dict]:
    return load_state(paths)["pending"]


def test_move_files_moves_then_writes_the_rows_and_ends_the_journal_entry(paths):
    file_id = one_song(paths)
    before = generation(paths)
    library.move_files(paths, "supersede", [("Library/A/S.aiff", "Superseded/A/S.aiff")], ref=file_id,
                       label="A - S")
    assert (paths.superseded / "A/S.aiff").exists() and not (paths.library / "A/S.aiff").exists()
    state = load_state(paths)
    assert state["pending"] == [] and state["tracks"]["t1"]["path"] is None
    assert generation(paths) > before


def test_move_files_across_drives_goes_through_a_staged_copy(paths, monkeypatch):
    file_id = one_song(paths)
    paths.superseded.mkdir()
    monkeypatch.setattr(library, "device", lambda p: 2 if Path(p).is_relative_to(paths.superseded) else 1)
    copies = []
    real = library._copy_verified
    monkeypatch.setattr(library, "_copy_verified", lambda s, t: (copies.append(t), real(s, t)))
    library.move_files(paths, "supersede", [("Library/A/S.aiff", "Superseded/A/S.aiff")], ref=file_id,
                       label="A - S")
    assert copies == [paths.root / "Superseded/A/.S.aiff.discjockey-move"]
    assert (paths.superseded / "A/S.aiff").read_bytes() == b"audio" and not copies[0].exists()
    assert pending(paths) == []


def test_a_move_that_fails_before_any_file_moved_drops_its_journal_entry(paths):
    file_id = one_song(paths)
    touch(paths.superseded / "A/S.aiff", b"in the way")
    with pytest.raises(FileExistsError):
        library.move_files(paths, "supersede", [("Library/A/S.aiff", "Superseded/A/S.aiff")], ref=file_id,
                           label="A - S")
    assert pending(paths) == [] and load_state(paths)["tracks"]["t1"]["path"] == "Library/A/S.aiff"


def test_a_crash_after_the_renames_is_finished_by_the_next_recovery_on_a_current_state(paths, monkeypatch):
    file_id = one_song(paths)

    def cut(conn, op):
        raise SystemExit("power cut")
    monkeypatch.setattr(db, "finish_file_op", cut)
    with pytest.raises(SystemExit):
        library.move_files(paths, "supersede", [("Library/A/S.aiff", "Superseded/A/S.aiff")], ref=file_id,
                           label="A - S")
    monkeypatch.undo()
    state = load_state(paths)
    (op,) = state["pending"]
    assert op["kind"] == "files" and op["do"] == "supersede" and op["ref"] == file_id
    assert recover_pending(paths, state) == [("Finished an interrupted step for A - S", True)]
    assert state == load_state(paths)  # replaced in place with a fresh snapshot
    assert state["pending"] == [] and state["tracks"]["t1"]["path"] is None
    state["tracks"]["t1"]["title"] = "S (edit)"
    save_state(paths, state)  # its generation is the stored one: no STALE
    assert load_state(paths)["tracks"]["t1"]["title"] == "S (edit)"


def test_recovery_redoes_a_file_step_that_had_not_moved_its_file(paths):
    file_id = one_song(paths)
    with db.connect(paths.db_file) as conn:
        db.add_pending(conn, {"kind": "files", "do": "supersede", "ref": file_id, "heir": None, "label": "A - S",
                              "renames": [["Library/A/S.aiff", "Superseded/A/S.aiff"]], "staged": {}, "size": {}})
    state = load_state(paths)
    assert recover_pending(paths, state)[0][1] is True
    assert (paths.superseded / "A/S.aiff").exists() and state["tracks"]["t1"]["path"] is None
    assert state == load_state(paths)


def test_recovery_drops_a_file_step_whose_files_are_gone(paths):
    file_id = one_song(paths)
    (paths.library / "A/S.aiff").unlink()
    with db.connect(paths.db_file) as conn:
        db.add_pending(conn, {"kind": "files", "do": "supersede", "ref": file_id, "heir": None, "label": "A - S",
                              "renames": [["Library/A/S.aiff", "Superseded/A/S.aiff"]], "staged": {}, "size": {}})
    state = load_state(paths)
    (message, ok), = recover_pending(paths, state)
    assert not ok and "neither" in message
    assert state["pending"] == [] and state == load_state(paths)


def test_recovery_of_a_file_step_the_system_refuses_keeps_it_pending(paths, monkeypatch):
    file_id = one_song(paths)
    with db.connect(paths.db_file) as conn:
        db.add_pending(conn, {"kind": "files", "do": "supersede", "ref": file_id, "heir": None, "label": "A - S",
                              "renames": [["Library/A/S.aiff", "Superseded/A/S.aiff"]], "staged": {}, "size": {}})

    def refuse(root, src, dst):
        raise PermissionError(errno.EACCES, "Permission denied")
    monkeypatch.setattr(library, "safe_rename", refuse)
    state = load_state(paths)
    (message, ok), = recover_pending(paths, state)
    assert not ok and "yet" in message and len(pending(paths)) == 1


def test_recovery_of_a_file_step_the_records_refuse_drops_it_and_says_so(paths, monkeypatch):
    file_id = one_song(paths)
    with db.connect(paths.db_file) as conn:
        db.add_pending(conn, {"kind": "files", "do": "supersede", "ref": file_id, "heir": file_id + 99,
                              "label": "A - S", "renames": [["Library/A/S.aiff", "Superseded/A/S.aiff"]],
                              "staged": {}, "size": {}})
    state = load_state(paths)
    (message, ok), = recover_pending(paths, state)
    assert (message, ok) == (library.NOT_RECORDED.format(name="A - S"), False)
    assert state["pending"] == [] and (paths.superseded / "A/S.aiff").exists()


def test_a_file_step_and_an_entry_step_pending_together_both_finish(paths):
    file_id = one_song(paths)
    touch(paths.data / ".tmp/t2/new.aiff")
    s = load_state(paths)
    s["tracks"]["t2"] = {"artist": "B", "title": "T", "path": None, "status": "missing"}
    s["pending"].append({"track_id": "t2", "renames": [[".discjockey/.tmp/t2/new.aiff", "Library/A/T.aiff"]],
                         "entry": {**s["tracks"]["t2"], "path": "Library/A/T.aiff", "status": "lossless"}})
    save_state(paths, s)
    with db.connect(paths.db_file) as conn:  # journaled after the entry step: the snapshot lists it second
        db.add_pending(conn, {"kind": "files", "do": "supersede", "ref": file_id, "heir": None, "label": "A - S",
                              "renames": [["Library/A/S.aiff", "Superseded/A/S.aiff"]], "staged": {}, "size": {}})
    state = load_state(paths)
    assert [ok for _, ok in recover_pending(paths, state)] == [True, True]
    assert state == load_state(paths) and state["pending"] == []
    assert state["tracks"]["t2"]["path"] == "Library/A/T.aiff" and state["tracks"]["t1"]["path"] is None


# --- drives that aren't connected, sources that can't be removed (group 2 review) ---

@pytest.fixture
def drive(paths, tmp_path, monkeypatch):
    """An import folder `Volumes/Example/Music` on another drive (`Volumes/Example`, library.device says 2),
    watched in library.db."""
    root = tmp_path / "Volumes" / "Example"
    folder = root / "Music"
    folder.mkdir(parents=True)
    monkeypatch.setattr(library, "device", lambda p: 2 if Path(p).is_relative_to(root) else 1)
    if not paths.db_file.exists():
        save_state(paths, empty_state())
    with db.connect(paths.db_file) as conn:
        db.add_watched_folder(conn, folder, datetime.now())
    return folder


def unplug(folder: Path) -> None:
    folder.parent.rename(folder.parent.with_name("Example (away)"))


def plug(folder: Path) -> None:
    folder.parent.with_name("Example (away)").rename(folder.parent)


def test_a_move_onto_a_drive_that_is_not_connected_creates_nothing(paths, drive):
    touch(paths.library / "A/x.aiff")
    unplug(drive)
    dst = str(drive / "House/x.aiff")
    with pytest.raises(OSError) as e:
        move_path(paths.root, "Library/A/x.aiff", dst, library.staging_path(dst), library.watched_roots(paths))
    assert e.value.errno == errno.ENXIO
    assert not drive.parent.exists() and (paths.library / "A/x.aiff").exists()  # no folder where the drive was


def test_a_first_download_still_makes_library_when_it_is_not_there_yet(paths):
    save_state(paths, empty_state())
    paths.library.joinpath("A").rmdir()
    paths.library.rmdir()
    touch(paths.data / ".tmp/t1/new.aiff")
    run_op(paths, load_state(paths), "t1", [(".discjockey/.tmp/t1/new.aiff", "Library/A/S.aiff")], None)
    assert (paths.library / "A/S.aiff").exists()  # Library/ is the music folder's, never a drive of its own


def test_without_watched_roots_a_move_never_makes_a_folder_outside_the_music_folder(paths, tmp_path):
    touch(paths.library / "A/x.aiff")
    with pytest.raises(OSError):
        move_path(paths.root, "Library/A/x.aiff", str(tmp_path / "Gone/Music/x.aiff"), None)
    assert not (tmp_path / "Gone").exists()


def from_the_drive(paths, drive, *, staged_data=None, dst=False):
    """A step moving `<drive>/x.aiff` into Library/ across drives, cut off: the source there, a staged copy and
    the target as asked."""
    src, target = drive / "x.aiff", paths.library / "A/x.aiff"
    touch(src)
    s = load_state(paths)
    s["pending"].append({"track_id": "t1", "renames": [[str(src), "Library/A/x.aiff"]], "entry": None,
                         "label": "A - S", "staged": {"0": "Library/A/.x.aiff.discjockey-move"},
                         "size": {"0": len(b"audio")}})
    save_state(paths, s)
    if staged_data is not None:
        touch(staged_of(target), staged_data)
    if dst:
        touch(target)
    return src, target


@pytest.mark.parametrize("dst", [False, True])
def test_while_the_source_drive_is_away_nothing_is_decided_and_once_back_the_move_is_checked(paths, drive, dst):
    src, target = from_the_drive(paths, drive, staged_data=b"audio", dst=dst)
    unplug(drive)
    (message, ok), = recover_pending(paths, load_state(paths))
    assert not ok and "yet" in message and "isn't connected" in message
    assert staged_of(target).read_bytes() == b"audio" and target.exists() == dst  # a whole copy, not renamed in
    assert len(load_state(paths)["pending"]) == 1
    plug(drive)
    assert recover_pending(paths, load_state(paths)) == [("Finished an interrupted step for A - S", True)]
    assert not src.exists() and target.read_bytes() == b"audio" and not staged_of(target).exists()
    assert load_state(paths)["pending"] == []


def test_a_step_waiting_for_an_unplugged_drive_blocks_the_scan_only_when_it_has_a_file_elsewhere(paths, drive):
    s = load_state(paths)
    s["pending"].append({"track_id": "t1", "renames": [[str(drive / "a.aiff"), str(drive / "B/a.aiff")]],
                         "entry": None})
    save_state(paths, s)
    unplug(drive)
    touch(paths.library / "A/new.aiff")
    library.scan_library(paths)
    assert "Library/A/new.aiff" in load_state(paths)["files"]  # every file of the step is on the drive that's away
    s = load_state(paths)
    s["pending"].append({"track_id": "t2", "renames": [[str(drive / "c.aiff"), "Library/A/c.aiff"]], "entry": None})
    save_state(paths, s)
    touch(paths.library / "A/newer.aiff")
    library.scan_library(paths)
    assert "Library/A/newer.aiff" not in load_state(paths)["files"]  # Library/A/c.aiff is visible to a scan


def refuse_removing(monkeypatch, path: Path):
    real = os.unlink

    def unlink(p, *a, **kw):
        if Path(p) == path:
            raise PermissionError(errno.EROFS, "Read-only file system")
        real(p, *a, **kw)
    monkeypatch.setattr(os, "unlink", unlink)


def test_a_verified_copy_whose_source_cannot_be_removed_ends_the_step_in_two_places(paths, other, monkeypatch):
    state, src, dst = crossing_step(paths, other, src=True, staged=True, dst=True)
    refuse_removing(monkeypatch, src)
    (message, ok), = recover_pending(paths, state)
    assert (message, ok) == ("Could not finish an interrupted step for A - S: " + library.TWO_PLACES.format(
        src="Library/A/x.aiff", dst=str(dst), reason="Read-only file system"), False)
    assert src.exists() and dst.exists() and not staged_of(dst).exists()
    assert load_state(paths)["pending"] == []  # never retried forever


def test_a_redo_whose_source_cannot_be_removed_ends_the_step_with_the_file_where_it_was(paths, other, monkeypatch):
    state, src, dst = crossing_step(paths, other, src=True, staged=False, dst=False)
    refuse_removing(monkeypatch, src)
    (message, ok), = recover_pending(paths, state)
    assert not ok and "stays where it was" in message
    assert src.exists() and not dst.exists() and load_state(paths)["pending"] == []


def test_a_failing_folder_sync_after_the_rename_still_counts_the_move(paths, other, monkeypatch):
    src = touch(paths.library / "A/x.aiff")
    dst = other / "x.aiff"

    def fails(path):
        raise OSError(errno.EIO, "Input/output error")
    monkeypatch.setattr(library, "fsync_dir", fails)
    run_op(paths, empty_state(), "t1", [("Library/A/x.aiff", str(dst))], None)
    assert not src.exists() and dst.read_bytes() == b"audio" and load_state(paths)["pending"] == []


def test_a_source_cut_short_while_it_is_copied_fails_the_copy(paths, other, monkeypatch):
    src = touch(paths.library / "A/x.aiff", b"the whole audio")
    dst = other / "x.aiff"
    real = library.full_fsync

    def cut_short(fd):
        real(fd)
        os.truncate(src, 3)
    monkeypatch.setattr(library, "full_fsync", cut_short)
    with pytest.raises(OSError, match="didn't match"):
        move_path(paths.root, "Library/A/x.aiff", str(dst), library.staging_path(str(dst)))
    assert src.exists() and not dst.exists() and not staged_of(dst).exists()


def test_recovery_with_a_different_file_at_the_target_removes_the_staged_copy(paths, other):
    state, src, dst = crossing_step(paths, other, src=True, staged=True, dst=b"another song")
    (message, ok), = recover_pending(paths, state)
    assert not ok and "both" in message and not staged_of(dst).exists()
    assert src.read_bytes() == b"audio" and dst.read_bytes() == b"another song"


def test_a_redo_that_no_longer_crosses_removes_the_staged_copy(paths, other, monkeypatch):
    state, src, dst = crossing_step(paths, other, src=True, staged=True, dst=False, staged_data=b"au")
    monkeypatch.setattr(library, "device", lambda p: 1)  # e.g. the folder is on the music folder's drive now
    assert recover_pending(paths, state)[0][1] is True
    assert dst.read_bytes() == b"audio" and not staged_of(dst).exists()


def test_only_a_file_with_the_staging_name_is_removed_as_a_staged_copy(paths):
    music = touch(paths.library / "A/x.aiff")
    hidden_music = touch(paths.library / "A/.x.aiff")
    library._remove_staged(music)
    library._remove_staged(hidden_music)
    assert music.exists() and hidden_music.exists()


def test_a_ctrl_c_during_a_long_copy_stops_it_and_keeps_the_source(paths, other, monkeypatch):
    src = touch(paths.library / "A/x.aiff", b"x" * (3 << 20))
    dst = other / "x.aiff"
    monkeypatch.setattr(library, "interrupt_held", lambda: True)
    with pytest.raises(KeyboardInterrupt):
        run_op(paths, empty_state(), "t1", [("Library/A/x.aiff", str(dst))], None)
    assert src.stat().st_size == 3 << 20 and not dst.exists() and not staged_of(dst).exists()
    assert load_state(paths)["pending"] == []
