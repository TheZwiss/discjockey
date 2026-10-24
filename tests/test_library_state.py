import json
import os
import unicodedata

import pytest

from discjockey import db, library
from discjockey.library import (
    LockHeld, NoLibrary, Paths, StateError, clear_tmp, empty_state, load_state, open_state, run_lock, save_state,
)


def lib(tmp_path) -> Paths:
    p = Paths(tmp_path, support=tmp_path / ".support")
    p.data.mkdir(parents=True, exist_ok=True)
    return p


def v1(**tracks) -> dict:
    return {"version": 1, "tracks": tracks, "pending": [], "qobuz_usage": {"days": {}, "signals": []}, "never": {}}


def test_load_without_records_gives_empty_state(tmp_path):
    assert load_state(lib(tmp_path)) == empty_state()
    assert not lib(tmp_path).db_file.exists()  # a reader writes nothing


def test_save_and_load_roundtrip(tmp_path):
    p = lib(tmp_path)
    s = empty_state()
    s["tracks"]["t1"] = {"artist": "A", "title": "Ü", "folder": "F", "path": None, "status": "missing",
                         "hidden": True}
    save_state(p, s)  # a library with no records yet gets its library.db here
    got = load_state(p)
    assert got["version"] == 2
    assert {k: got["tracks"]["t1"][k] for k in ("artist", "title", "folder", "path", "status", "hidden")} == \
        s["tracks"]["t1"]
    assert not p.state_file.exists()


def test_unknown_version_refused(tmp_path):
    p = lib(tmp_path)
    p.state_file.write_text(json.dumps({"version": 99, "tracks": {}}))
    with pytest.raises(StateError, match="version 99"):
        load_state(p)
    with pytest.raises(StateError, match="version 99"):
        open_state(p)
    assert not p.db_file.exists()


def test_failed_save_keeps_the_old_records(tmp_path, monkeypatch):
    p = lib(tmp_path)
    save_state(p, empty_state())
    s = load_state(p)
    s["tracks"]["t1"] = {"artist": "A", "title": "B", "folder": "F", "path": "Library/F/A - B.aiff",
                         "status": "lossless"}
    (p.library / "F").mkdir(parents=True)
    (p.library / "F" / "A - B.aiff").write_bytes(b"audio")

    def boom(path):
        raise OSError("disk full")

    monkeypatch.setattr(library, "file_facts", lambda paths: boom)  # fails after the song row was written
    with pytest.raises(OSError):
        save_state(p, s)
    monkeypatch.undo()
    assert load_state(p)["tracks"] == {}  # one transaction: the song wasn't written without its file


def test_lock_blocks_second_holder(tmp_path):
    lock = tmp_path / ".lock"
    with run_lock(lock):
        with pytest.raises(LockHeld):
            with run_lock(lock):
                pass
    with run_lock(lock):
        pass


def test_a_state_json_not_yet_migrated_is_read_as_it_is(tmp_path):
    p = lib(tmp_path)
    (p.library / "A" / "not_lossless").mkdir(parents=True)
    (p.library / "A" / "x.aiff").write_bytes(b"")
    (p.library / "A" / "not_lossless" / "y.aiff").write_bytes(b"")
    (p.library / ".DS_Store").write_bytes(b"")
    (p.library / "A" / ".hidden").write_bytes(b"")
    (p.library / "A" / unicodedata.normalize("NFD", "Mötley.aiff")).write_bytes(b"")
    library.write_json_atomic(p.state_file, v1(t1={"artist": "A", "title": "x", "path": "Library/A/x.aiff"},
                                               t2={"artist": "B", "title": "y", "path": None}))
    got = load_state(p)
    assert got["version"] == 1
    assert (got["tracks"]["t1"]["online"], got["tracks"]["t1"]["placed_by"]) == (True, "app")
    assert (got["tracks"]["t2"]["online"], got["tracks"]["t2"]["placed_by"]) == (False, None)
    assert got["ambiguous"] == {}
    assert got["files"] == sorted([
        "Library/A/not_lossless/y.aiff",
        "Library/A/x.aiff",
        unicodedata.normalize("NFC", "Library/A/Mötley.aiff"),
    ])
    assert not p.db_file.exists()


def test_the_writer_migrates_state_json(tmp_path):
    p = lib(tmp_path)
    library.write_json_atomic(p.state_file, v1(t1={"artist": "A", "title": "x", "path": None, "status": "missing"}))
    got = open_state(p)
    assert got["version"] == 2 and got["tracks"]["t1"]["title"] == "x"
    assert json.loads(p.state_file.read_text()) == db.STUB
    assert json.loads(p.state_backup.read_text())["tracks"]["t1"]["title"] == "x"
    assert open_state(p) == got  # every later open: nothing to do


def test_the_writer_gives_a_new_library_its_records(tmp_path):
    p = Paths(tmp_path, support=tmp_path / ".support")
    assert open_state(p) == empty_state()
    assert p.db_file.exists() and json.loads(p.state_file.read_text()) == db.STUB


def test_the_writer_finishes_pending_steps_before_migrating(tmp_path):
    p = lib(tmp_path)
    (p.root / "Library" / "F").mkdir(parents=True)
    (p.root / "Library" / "F" / "A - x.aiff").write_bytes(b"audio")
    entry = {"artist": "A", "title": "x", "folder": "F", "path": "Library/F/A - x.aiff", "status": "lossless"}
    state = v1(t1={**entry, "path": None, "status": "missing"})
    state["pending"] = [{"track_id": "t1", "renames": [[".discjockey/.tmp/t1/a.aiff", "Library/F/A - x.aiff"]],
                         "entry": entry}]
    library.write_json_atomic(p.state_file, state)
    messages = []
    got = open_state(p, messages.append)
    assert got["pending"] == [] and got["tracks"]["t1"]["path"] == "Library/F/A - x.aiff"
    assert any("Finished an interrupted step" in m.text for m in messages)
    assert json.loads(p.state_backup.read_text())["pending"] == []  # recovered into state.json, then migrated


def test_an_old_format_save_is_refused_outside_the_migration(tmp_path):
    p = lib(tmp_path)
    open_state(p)
    with pytest.raises(StateError, match="old format"):
        save_state(p, v1())
    assert json.loads(p.state_file.read_text()) == db.STUB


def test_missing_records_are_never_replaced_by_an_empty_library(tmp_path):
    p = lib(tmp_path)
    library.write_json_atomic(p.state_file, db.STUB)
    with pytest.raises(StateError, match="are missing"):
        load_state(p)
    with pytest.raises(StateError, match="are missing"):
        save_state(p, empty_state())
    assert not p.db_file.exists()


@pytest.mark.parametrize("backup", [True, False])
def test_missing_records_are_refused_by_reader_and_writer_and_never_rebuilt(tmp_path, backup):
    p = lib(tmp_path)
    library.write_json_atomic(p.state_file, v1(t1={"artist": "A", "title": "x", "path": None}))
    open_state(p)
    p.db_file.unlink()
    if not backup:
        p.state_backup.unlink()
    kept = p.state_backup.read_bytes() if backup else None
    for opener in (load_state, open_state):
        with pytest.raises(StateError) as excinfo:
            opener(p)
        assert str(excinfo.value) == ("Discjockey's records (library.db) are missing from the .discjockey folder. "
                                      "Nothing was changed. Put the file back, for example from Time Machine, and "
                                      "open Discjockey again.")
        assert not p.db_file.exists()
        assert (p.state_backup.read_bytes() == kept) if backup else not p.state_backup.exists()


def test_saving_into_a_music_folder_that_went_away_is_no_library(tmp_path):
    p = Paths(tmp_path / "gone", support=tmp_path / ".support")
    with pytest.raises(NoLibrary):
        save_state(p, empty_state())
    with pytest.raises(NoLibrary):
        open_state(p)
    assert not p.root.exists()


def test_clear_tmp(tmp_path):
    p = Paths(tmp_path, support=tmp_path / ".support")
    (p.tmp / "t1").mkdir(parents=True)
    (p.tmp / "t1" / "x.flac").write_bytes(b"x")
    clear_tmp(p)
    assert p.tmp.is_dir() and list(p.tmp.iterdir()) == []


def test_clear_tmp_keeps_files_a_pending_step_still_needs(tmp_path):
    p = Paths(tmp_path, support=tmp_path / ".support")
    for name in ("t1/x.flac", "t9/new.aiff", "loose.part"):
        (p.tmp / name).parent.mkdir(parents=True, exist_ok=True)
        (p.tmp / name).write_bytes(b"x")
    state = empty_state()
    state["pending"].append({"track_id": "t9", "renames": [[".discjockey/.tmp/t9/new.aiff", "Library/A/S.aiff"]],
                             "entry": None})
    clear_tmp(p, state)
    assert sorted(x.name for x in p.tmp.iterdir()) == ["t9"]
    assert (p.tmp / "t9" / "new.aiff").exists()


def test_clear_tmp_keeps_the_files_of_a_pending_swap(tmp_path):
    p = Paths(tmp_path, support=tmp_path / ".support")
    for name in ("t1/swap.aiff", "t1/backup.aiff", "t2/x.flac"):
        (p.tmp / name).parent.mkdir(parents=True, exist_ok=True)
        (p.tmp / name).write_bytes(b"x")
    state = empty_state()
    state["pending"].append({"kind": "swap", "track_id": "t1", "target": "Library/A/S.aiff",
                             "staged": ".discjockey/.tmp/t1/swap.aiff", "backup": "Superseded/A/S (lossy).aiff",
                             "parked": "Upgrades ready/A/S.aiff", "renames": [], "entry": None})
    clear_tmp(p, state)
    assert sorted(x.name for x in p.tmp.iterdir()) == ["t1"]
    assert sorted(x.name for x in (p.tmp / "t1").iterdir()) == ["backup.aiff", "swap.aiff"]


def test_full_fsync_asks_the_drive_to_write_out(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(library.fcntl, "fcntl", lambda fd, cmd, *a: calls.append(cmd))
    with open(tmp_path / "x", "wb") as f:
        library.full_fsync(f.fileno())
    assert calls == [library.fcntl.F_FULLFSYNC]


def test_full_fsync_falls_back_to_fsync(tmp_path, monkeypatch):
    def refuse(fd, cmd, *a):
        raise OSError("not supported on this disk")
    synced = []
    monkeypatch.setattr(library.fcntl, "fcntl", refuse)
    monkeypatch.setattr(library.os, "fsync", lambda fd: synced.append(fd))
    with open(tmp_path / "x", "wb") as f:
        library.full_fsync(f.fileno())
        assert synced == [f.fileno()]


def test_fsync_dir_syncs_the_folder_itself(tmp_path, monkeypatch):
    synced = []
    monkeypatch.setattr(library, "full_fsync", lambda fd: synced.append(os.fstat(fd).st_ino))
    library.fsync_dir(tmp_path)
    assert synced == [os.stat(tmp_path).st_ino]


def test_json_is_written_out_fully_before_it_replaces_the_old_file(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(library, "full_fsync", lambda fd: events.append("file"))
    monkeypatch.setattr(library, "fsync_dir", lambda path: events.append(("dir", path)))
    library.write_json_atomic(tmp_path / "state.json", {"version": 2})
    assert events == ["file", ("dir", tmp_path)]  # the replace itself is on the drive too (a pending swap record)
