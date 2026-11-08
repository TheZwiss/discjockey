"""Backups of rekordbox's library (discjockey/rekordbox/backup.py): what a backup holds, reuse while the library's
hash holds, a new one after an outside change, the copies a later batch needs, prune, and restore with its refusals.
Every library is built by make_master in tmp_path."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from discjockey.library import Paths
from discjockey.rekordbox import backup, master, write
from discjockey.rekordbox.locate import Place
from rekordbox_helpers import dump, make_master, snapshot, writer

OLD = "/Users/dj/Music/Old Song.mp3"


def setup(tmp_path, rows=None):
    folder = tmp_path / "rb"
    make_master(folder, rows or [{"ID": "100", "path": OLD}, {"ID": "200", "path": "/Users/dj/Music/Two.mp3"}],
                anlz=True)
    place = Place(folder / "master.db", folder / "share", "override", None)
    paths = Paths(tmp_path / "music", support=tmp_path / "support")
    (tmp_path / "music").mkdir()
    return paths, place


def folders(place, *ids):
    with master.open_read(place, False) as m:
        entries = {e.id: e for p in m.index().by_path for e in m.entries_for(Path(p))}
    return [(i, [write.analysis_folder(place, entries[i])]) for i in ids]


def touch_db(place, title="Changed"):
    con = writer(place.db)
    con.execute("UPDATE djmdContent SET Title = ? WHERE ID = '200'", (title,))
    con.commit()
    con.close()


def test_a_backup_holds_the_library_the_analysis_folders_and_a_manifest(tmp_path):
    paths, place = setup(tmp_path)
    b = backup.Backup.ensure(paths, place, dbid="1234567890", batch_id=7, tracks=folders(place, "100"),
                             db_version="6000")
    assert b.folder.parent == paths.data / "rekordbox" / "backups"
    assert len(b.id) == 16 and b.id.endswith("Z")
    assert (b.folder / "master.db").read_bytes() == place.db.read_bytes()
    [(_, [anlz_folder])] = folders(place, "100")
    copied = b.folder / "share" / anlz_folder.relative_to(place.share)
    assert sorted(p.name for p in copied.iterdir()) == sorted(p.name for p in anlz_folder.iterdir())
    assert all((copied / p.name).read_bytes() == p.read_bytes() for p in anlz_folder.iterdir())
    m = json.loads((b.folder / "manifest.json").read_text())
    assert m["dbid"] == "1234567890" and m["db_version"] == "6000" and m["batches"] == [7]
    assert m["master_sha256_before"] == backup.sha256_file(place.db) and m["master_sha256_after"] is None
    assert m["tracks"] == [{"track": "100", "folders": [str(anlz_folder.relative_to(place.share))]}]
    assert m["app_version"]


def test_a_backup_is_reused_while_the_library_is_unchanged_and_renewed_after_a_change(tmp_path):
    paths, place = setup(tmp_path)
    first = backup.Backup.ensure(paths, place, dbid="1234567890", batch_id=1, tracks=folders(place, "100"))
    first.close(place, batch_id=1)
    again = backup.Backup.ensure(paths, place, dbid="1234567890", batch_id=2, tracks=folders(place, "200"))
    assert again.id == first.id and again.manifest["batches"] == [1, 2]
    assert [t["track"] for t in again.manifest["tracks"]] == ["100", "200"]
    again.close(place, batch_id=2)
    touch_db(place)  # rekordbox changed the library since
    renewed = backup.Backup.ensure(paths, place, dbid="1234567890", batch_id=3, tracks=[])
    assert renewed.id != first.id and len(backup.backups(paths)) == 2


def test_a_folder_already_in_a_reused_backup_with_other_bytes_is_kept_for_its_batch(tmp_path):
    paths, place = setup(tmp_path)
    tracks = folders(place, "100")
    b = backup.Backup.ensure(paths, place, dbid=None, batch_id=1, tracks=tracks)
    dat = next(tracks[0][1][0].glob("*.DAT"))
    original = dat.read_bytes()
    dat.write_bytes(original + b"\0")
    b.add_tracks(place, 2, tracks)
    assert b.anlz_copy(place, dat, 1).read_bytes() == original
    assert b.anlz_copy(place, dat, 2).read_bytes() == original + b"\0"


def test_an_unclean_library_gets_no_backup(tmp_path):
    paths, place = setup(tmp_path)
    con = writer(place.db)
    con.execute("UPDATE djmdContent SET Title = 'x' WHERE ID = '200'")
    con.commit()
    with pytest.raises(write.WriteRefused) as e:
        backup.Backup.ensure(paths, place, dbid=None, batch_id=1, tracks=[])
    con.close()
    assert e.value.reason == "unclean" and backup.backups(paths) == []


def test_prune_keeps_the_named_ones_and_the_newest_three(tmp_path):
    paths, place = setup(tmp_path)
    ids = []
    for n in range(6):
        touch_db(place, f"t{n}")
        b = backup.Backup.ensure(paths, place, dbid=None, batch_id=n, tracks=[])
        b.manifest["created"] = f"2026-11-0{n + 1}T00:00:00+00:00"
        b._save()
        ids.append(b.id)
    removed = backup.prune(paths, {ids[0]})
    assert sorted(removed) == sorted(ids[1:3])
    assert sorted(i.id for i in backup.backups(paths)) == sorted([ids[0], *ids[3:]])


def test_restore_puts_both_sides_back_saves_the_current_first_and_lists_what_points_nowhere(tmp_path):
    old_file = tmp_path / "Old Song.mp3"
    rows = [{"ID": "100", "path": str(old_file)}, {"ID": "200", "path": "/Users/dj/Music/Two.mp3"}]
    paths, place = setup(tmp_path / "x", rows)
    old_db, share_before = place.db.read_bytes(), snapshot(place.share)
    b = backup.Backup.ensure(paths, place, dbid="1234567890", batch_id=1, tracks=folders(place, "100"))
    b.close(place)
    with master.open_read(place, False) as m:
        e = m.entries_for(old_file)[0]
    new = str(tmp_path / "x" / "Artist - Song.aiff")
    Path(new).write_bytes(b"aiff")
    change = write.row_change(e, new, file_size=4, channels=2, frames=44100, old_tags={}, clean={})
    files, _ = write.anlz_changes(place, e, new)
    with write.open_write(place, dbid=None, running=lambda: False) as w:
        w.repoint([change], files)
    after_db = dump(place.db)
    result = backup.restore(paths, place, b.id, running=lambda: False)
    assert place.db.read_bytes() == old_db
    assert [(p, s) for p, s, _ in snapshot(place.share)] == [(p, s) for p, s, _ in share_before]
    assert all(f.read_bytes() == (b.folder / "share" / f.relative_to(place.share)).read_bytes()
               for f in place.share.rglob("*") if f.is_file() and "/100/" in str(f))
    saved = backup.find(paths, result.saved_current)
    assert dump(saved.folder / "master.db") == after_db  # the library as it was before the restore is kept
    assert result.missing_after == [{"id": "100", "path": str(old_file), "was": new}]  # old file: not there
    assert not master.leftovers(place.db) and not list(place.share.rglob("*.dj-new"))


def test_restore_refuses_with_nothing_changed(tmp_path):
    paths, place = setup(tmp_path)
    b = backup.Backup.ensure(paths, place, dbid="1234567890", batch_id=1, tracks=[])
    b.close(place)
    before = snapshot(place.db.parent)
    with pytest.raises(backup.RestoreRefused) as e:
        backup.restore(paths, place, b.id, running=lambda: True)
    assert e.value.reason == "rekordbox_open"
    with pytest.raises(backup.RestoreRefused) as e:
        backup.restore(paths, place, "20000101T000000Z", running=lambda: False)
    assert e.value.reason == "not_found"
    with pytest.raises(backup.RestoreRefused) as e:
        backup.restore(paths, None, b.id, running=lambda: False)
    assert e.value.reason == "no_rekordbox"
    (b.folder / "master.db").write_bytes((b.folder / "master.db").read_bytes() + b"\0")
    with pytest.raises(backup.RestoreRefused) as e:
        backup.restore(paths, place, b.id, running=lambda: False)
    assert e.value.reason == "damaged"
    assert snapshot(place.db.parent) == before
    con = writer(place.db)
    con.execute("UPDATE djmdContent SET Title = 'x' WHERE ID = '200'")
    con.commit()
    with pytest.raises(backup.RestoreRefused) as e:
        backup.restore(paths, place, b.id, running=lambda: False)
    con.close()
    assert e.value.reason == "unclean"
    assert len(backup.backups(paths)) == 1 and os.path.exists(place.db)  # no saved copy was made for a refusal


def test_a_later_copy_follows_the_file_when_it_changes_again(tmp_path):
    """Undo sessions outside a batch all share `later/None/`: a second copy must not keep the first one's bytes."""
    paths, place = setup(tmp_path)
    tracks = folders(place, "100")
    b = backup.Backup.ensure(paths, place, dbid=None, batch_id=None, tracks=tracks)
    dat = next(tracks[0][1][0].glob("*.DAT"))
    original = dat.read_bytes()
    dat.write_bytes(original + b"\1")
    b.add_tracks(place, None, tracks)
    assert b.anlz_copy(place, dat, None).read_bytes() == original + b"\1"
    dat.write_bytes(original + b"\2")
    b.add_tracks(place, None, tracks)
    assert b.anlz_copy(place, dat, None).read_bytes() == original + b"\2"


def test_restore_waits_for_no_one_but_refuses_while_another_writer_holds_the_lock(tmp_path):
    from discjockey.rekordbox.session import Busy, Session
    paths, place = setup(tmp_path)
    b = backup.Backup.ensure(paths, place, dbid="1234567890", batch_id=1, tracks=folders(place, "100"))
    b.close(place)
    touch_db(place)
    before = snapshot(place.db.parent)
    with Session.open(paths, place=place, running=lambda: False, items_need_write=lambda v: True):
        with pytest.raises(Busy):
            backup.restore(paths, place, b.id, running=lambda: False)
    assert snapshot(place.db.parent) == before and len(backup.backups(paths)) == 1   # nothing changed, nothing saved
    backup.restore(paths, place, b.id, running=lambda: False)                          # the lock is free again


def test_restore_clears_leftovers_a_crash_left_beside_the_files(tmp_path):
    paths, place = setup(tmp_path)
    b = backup.Backup.ensure(paths, place, dbid="1234567890", batch_id=1, tracks=folders(place, "100"))
    b.close(place)
    [(_, [anlz_folder])] = folders(place, "100")
    stray = [place.db.with_name("master.db.dj-new"), *(p.with_name(p.name + ".dj-new") for p in anlz_folder.iterdir())]
    for p in stray:
        p.write_bytes(b"half")
    backup.restore(paths, place, b.id, running=lambda: False)
    assert not any(p.exists() for p in stray) and not list(place.share.rglob("*.dj-new"))


def test_the_running_check_is_looked_up_when_called(tmp_path, monkeypatch):
    """Left out, `running` is whatever `process.running` is now (tests, and the commands, replace it)."""
    paths, place = setup(tmp_path)
    b = backup.Backup.ensure(paths, place, dbid="1234567890", batch_id=1, tracks=[])
    b.close(place)
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: True)
    with pytest.raises(backup.RestoreRefused) as e:
        backup.restore(paths, place, b.id)
    assert e.value.reason == "rekordbox_open"
    with pytest.raises(write.WriteRefused) as w, write.open_write(place, dbid=None):
        pass
    assert w.value.reason == "rekordbox_open"
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: False)
    backup.restore(paths, place, b.id)
