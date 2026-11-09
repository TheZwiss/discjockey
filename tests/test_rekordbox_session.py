"""A batch's rekordbox side (discjockey/rekordbox/session.py): `rekordbox.lock`, the start check (rekordbox running
and a write needed → nothing changed), one read open per session, the backup before the first write, a fresh view
after it. Every library is built by make_master in tmp_path."""
from __future__ import annotations

import fcntl
import os
from pathlib import Path

import pytest

from discjockey.library import Paths
from discjockey.rekordbox import backup, master, session, write
from discjockey.rekordbox.locate import Place
from rekordbox_helpers import make_master, snapshot

OLD = "/Users/dj/Music/Old Song.mp3"
NEW = "/Users/dj/Music/Artist - Song.aiff"


def setup(tmp_path):
    folder = tmp_path / "rb"
    make_master(folder, [{"ID": "100", "path": OLD}, {"ID": "200", "path": "/Users/dj/Music/Two.mp3"}], anlz=True)
    paths = Paths(tmp_path / "music", support=tmp_path / "support")
    (tmp_path / "music").mkdir()
    return paths, Place(folder / "master.db", folder / "share", "override", None)


def never() -> bool:
    return False


def always() -> bool:
    return True


def test_a_second_session_is_busy(tmp_path):
    paths, place = setup(tmp_path)
    paths.support.mkdir()
    fd = os.open(paths.support / "rekordbox.lock", os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # another Discjockey holds it
    try:
        with pytest.raises(session.Busy) as e:
            with session.Session.open(paths, place=place, running=never, items_need_write=lambda v: True):
                pass
        assert str(e.value) == session.BUSY
    finally:
        os.close(fd)
    with session.Session.open(paths, place=place, running=never, items_need_write=lambda v: True):
        with pytest.raises(session.Busy):  # and inside one process too
            with session.Session.open(paths, place=place, running=never, items_need_write=lambda v: True):
                pass


def test_rekordbox_running_with_a_write_needed_stops_before_anything_changes(tmp_path):
    paths, place = setup(tmp_path)
    before = snapshot(tmp_path)
    seen = []
    with pytest.raises(session.RekordboxOpen):
        with session.Session.open(paths, place=place, running=always,
                                  items_need_write=lambda v: seen.append(v) or True):
            raise AssertionError("never gets here")
    assert isinstance(seen[0], master.RekordboxView)
    assert [p for p in snapshot(tmp_path) if "rekordbox.lock" not in p[0]] == before


def test_rekordbox_running_with_only_aiff_swaps_goes_on_but_never_writes(tmp_path):
    paths, place = setup(tmp_path)
    with session.Session.open(paths, place=place, running=always, items_need_write=lambda v: False) as s:
        assert s.state.state == "ready" and s.state.running and s.view() is not None
        with pytest.raises(write.WriteRefused) as e:
            with s.writer():
                pass
        assert e.value.reason == "rekordbox_open"
    assert backup.backups(paths) == []


def test_one_read_open_for_many_lookups(tmp_path):
    paths, place = setup(tmp_path)
    with session.Session.open(paths, place=place, running=never, items_need_write=lambda v: True) as s:
        for _ in range(3):
            v = s.view()
            assert [e.id for e in v.master.entries_for(Path(OLD), v.index)] == ["100"]
        assert s.opens == 1 and s.dbid == "1234567890" and not s.rekordbox_opened()


def test_the_first_write_makes_the_backup_and_a_later_view_sees_the_change(tmp_path):
    paths, place = setup(tmp_path)
    with session.Session.open(paths, place=place, running=never, items_need_write=lambda v: True,
                              batch_id=5) as s:
        v = s.view()
        e = v.master.entries_for(Path(OLD), v.index)[0]
        folder = write.analysis_folder(place, e)
        change = write.row_change(e, NEW, file_size=10, channels=2, frames=44100, old_tags={}, clean={})
        with s.writer([("track-1", [folder])]) as w:
            assert s._read is None  # the read connection closed before the write opened
            files, _ = write.anlz_changes(place, e, NEW, lambda p: s.backup.anlz_copy(place, p, 5))
            assert all(f.backup is not None and f.backup.is_file() for f in files)
            w.repoint([change], files)
        v = s.view()
        assert [x.id for x in v.master.entries_for(Path(NEW), v.index)] == ["100"]
        assert v.master.entries_for(Path(OLD), v.index) == [] and s.opens == 2
        b = s.backup
    assert b.manifest["batches"] == [5] and b.manifest["master_sha256_after"] == backup.sha256_file(place.db)
    assert not master.leftovers(place.db)


def test_rekordbox_opening_during_the_batch_is_seen(tmp_path):
    paths, place = setup(tmp_path)
    state = {"on": False}
    with session.Session.open(paths, place=place, running=lambda: state["on"], items_need_write=lambda v: True) as s:
        assert not s.rekordbox_opened()
        state["on"] = True
        assert s.rekordbox_opened()


def test_no_library_and_an_unreadable_one_are_answers(tmp_path):
    paths, place = setup(tmp_path)
    with session.Session.open(paths, place=None, running=never, items_need_write=lambda v: True) as s:
        assert s.state.state == "none" and s.view() is None
        with pytest.raises(write.WriteRefused):
            with s.writer():
                pass
    bad = tmp_path / "bad"
    make_master(bad, [{"path": OLD}], key="0" * 64)
    with session.Session.open(paths, place=Place(bad / "master.db", bad / "share", "override", None), running=never,
                              items_need_write=lambda v: True) as s:
        assert s.state.state == "unreadable" and s.state.problem == "key" and s.view() is None
    seen = []
    with pytest.raises(session.RekordboxOpen):  # can't read it while rekordbox runs: the items answer for None
        with session.Session.open(paths, place=Place(bad / "master.db", bad / "share", "override", None),
                                  running=always, items_need_write=lambda v: seen.append(v) or True):
            pass
    assert seen == [None]
