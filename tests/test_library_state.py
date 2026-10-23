import json
import os
import unicodedata

import pytest

from discjockey import library
from discjockey.library import (
    LockHeld, Paths, StateError, clear_tmp, empty_state, list_files, load_state, run_lock, save_state,
)


def test_load_missing_gives_empty_state(tmp_path):
    assert load_state(tmp_path / "state.json") == empty_state()


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "sub" / "state.json"
    s = empty_state()
    s["tracks"]["t1"] = {"title": "Ü"}
    save_state(path, s)
    assert load_state(path) == s
    assert not (tmp_path / "sub" / "state.json.tmp").exists()


def test_unknown_version_refused(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"version": 99, "tracks": {}}))
    with pytest.raises(StateError):
        load_state(path)


def test_failed_save_keeps_old_file(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    save_state(path, empty_state())
    before = path.read_text()

    def boom(*a):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    s = empty_state()
    s["tracks"]["t1"] = {}
    with pytest.raises(OSError):
        save_state(path, s)
    assert path.read_text() == before


def test_lock_blocks_second_holder(tmp_path):
    lock = tmp_path / ".lock"
    with run_lock(lock):
        with pytest.raises(LockHeld):
            with run_lock(lock):
                pass
    with run_lock(lock):
        pass


def test_list_files(tmp_path):
    p = Paths(tmp_path, support=tmp_path / ".support")
    (p.library / "A" / "not_lossless").mkdir(parents=True)
    (p.library / "A" / "x.aiff").write_bytes(b"")
    (p.library / "A" / "not_lossless" / "y.aiff").write_bytes(b"")
    (p.library / ".DS_Store").write_bytes(b"")
    (p.library / "A" / ".hidden").write_bytes(b"")
    nfd = unicodedata.normalize("NFD", "Mötley.aiff")
    (p.library / "A" / nfd).write_bytes(b"")
    assert list_files(p) == sorted([
        "Library/A/not_lossless/y.aiff",
        "Library/A/x.aiff",
        unicodedata.normalize("NFC", "Library/A/Mötley.aiff"),
    ])


def test_list_files_without_library(tmp_path):
    assert list_files(Paths(tmp_path, support=tmp_path / ".support")) == []


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


def test_state_is_written_out_fully_before_it_replaces_the_old_file(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(library, "full_fsync", lambda fd: events.append("file"))
    monkeypatch.setattr(library, "fsync_dir", lambda path: events.append(("dir", path)))
    save_state(tmp_path / "state.json", empty_state())
    assert events == ["file", ("dir", tmp_path)]  # the replace itself is on the drive too (a pending swap record)
