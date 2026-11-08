"""rekordbox's library written (discjockey/rekordbox/write.py): exactly design §5.5's columns change, the text columns
follow §5.11 (written where rekordbox still shows the old tag, the user's edit kept, lookup rows found or made with
rekordbox's scheme), the stamp numbers each row, the guards refuse with nothing written, rekordbox opening before the
commit rolls everything back, and undo puts back only what is still ours. Every library is built by make_master;
the whole-database compare is `dump`/`diff`."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from discjockey.rekordbox import anlz, master, write
from discjockey.rekordbox.locate import Place
from rekordbox_helpers import diff, dump, make_master, running_after, snapshot, writer

OLD = "/Users/dj/Music/Old Song.mp3"
NEW = "/Users/dj/Music/Artist - Song.aiff"
OLD_TAGS = {"title": "Song", "artist": "Artist", "album": "Album", "label": "Label", "isrc": "", "comment": ""}
CLEAN = {"title": "Song (Original Mix)", "artist": "New Artist", "album": "Album", "label": "Label",
         "isrc": "GBAAA0000001", "comment": "Qobuz · Lossless"}
STAMP_RE = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} \+00:00")


def never() -> bool:
    return False


def library(tmp_path, **row):
    folder = tmp_path / "rb"
    spec = {"ID": "100", "path": OLD, "Title": "Song", "artist": "Artist", "album": "Album", "label": "Label",
            "cues": 2, "playlists": 1, "FileSize": 5000, "BitRate": 320, "SampleRate": 48000, "Length": 30}
    spec.update(row)
    make_master(folder, [spec, {"ID": "200", "path": "/Users/dj/Music/Other.mp3", "artist": "Other"}], anlz=True)
    return Place(folder / "master.db", folder / "share", "override", None)


def entry(place, row_id="100", path=OLD) -> master.Entry:
    with master.open_read(place, False) as m:
        return next(e for e in m.entries_for(Path(path)) if e.id == row_id)


def plan(place, e=None, clean=CLEAN, new=NEW):
    e = e or entry(place)
    change = write.row_change(e, new, file_size=9000, channels=2, frames=44100 * 31 + 5, old_tags=OLD_TAGS,
                              clean=clean)
    files, others = write.anlz_changes(place, e, new)
    return change, files, others


def repoint(place, change, files, running=never):
    with write.open_write(place, dbid="1234567890", running=never) as w:
        return w.repoint([change], files, running=running)


def anlz_bytes(place) -> dict[str, bytes]:
    return {str(p.relative_to(place.share)): p.read_bytes() for p in sorted(place.share.rglob("*")) if p.is_file()}


def test_a_repoint_changes_exactly_the_designed_columns(tmp_path):
    place = library(tmp_path)
    before = dump(place.db)
    change, files, others = plan(place)
    assert others == [] and [Path(f.path).suffix for f in files] == [".2EX", ".DAT", ".EXT"]  # .3EX has no path
    done = repoint(place, change, files)
    after = dump(place.db)
    changed = {(t, i, c) for t, i, c, _, _ in diff(before, after)}
    content = {("djmdContent", "100", c) for c in ("FolderPath", "FileNameL", "FileType", "FileSize", "BitDepth",
                                                   "SampleRate", "BitRate", "Length", "Title", "ArtistID", "ISRC",
                                                   "Commnt", "rb_local_usn", "updated_at")}
    new_artist = done.created["djmdArtist"][0]
    cf = {(t, i, c) for t, i, c in changed if t == "contentFile"}
    assert changed == content | {("djmdArtist", new_artist, "<row>"), ("agentRegistry", "localUpdateCount", "int_1")} | cf
    assert {c for _, _, c in cf} == {"Hash", "Size", "rb_local_usn", "updated_at"} and len({i for _, i, _ in cf}) == 3
    row = next(r for r in after["djmdContent"] if r[0] == "100")
    names = [n for n, _ in __import__("rekordbox_helpers").TABLES["djmdContent"]]
    got = dict(zip(names, row))
    assert (got["FolderPath"], got["FileNameL"], got["FileType"], got["FileSize"], got["BitDepth"], got["SampleRate"],
            got["BitRate"], got["Length"]) == (NEW, "Artist - Song.aiff", 12, 9000, 16, 44100, 1411, 31)
    assert got["Title"] == CLEAN["title"] and got["ISRC"] == CLEAN["isrc"] and got["Commnt"] == CLEAN["comment"]
    assert got["OrgFolderPath"] == "" and got["rb_LocalFolderPath"] is None  # '' / NULL: not the old path, untouched
    assert not master.leftovers(place.db)  # the read-write connection closed cleanly (guard 4 holds after us)


def test_org_and_local_folder_path_follow_only_when_they_named_the_old_file(tmp_path):
    place = library(tmp_path, OrgFolderPath=OLD, rb_LocalFolderPath="/Volumes/Stick/Old Song.mp3")
    change, files, _ = plan(place)
    done = repoint(place, change, files)
    r = done.rows[0]
    assert r.identity_after["OrgFolderPath"] == NEW and r.identity_before["OrgFolderPath"] == OLD
    assert r.identity_after["rb_LocalFolderPath"] == "/Volumes/Stick/Old Song.mp3"
    place2 = library(tmp_path / "b", rb_LocalFolderPath=OLD)
    change, files, _ = plan(place2)
    assert repoint(place2, change, files).rows[0].identity_after["rb_LocalFolderPath"] == NEW


def test_each_changed_row_gets_its_own_number_and_the_count_ends_at_the_last(tmp_path):
    place = library(tmp_path)
    before = dump(place.db)
    count = next(r for r in before["agentRegistry"] if r[0] == "localUpdateCount")
    change, files, _ = plan(place)
    done = repoint(place, change, files)
    after = dump(place.db)
    usns = [r[-3] for t in ("djmdArtist", "contentFile", "djmdContent") for r in after[t]
            if (t, r[0]) in {(t2, i) for t2, i, *_ in diff(before, after)}]
    assert sorted(usns) == list(range(count[3] + 1, count[3] + 1 + 5))  # artist, track, 3 analysis files
    reg = next(r for r in after["agentRegistry"] if r[0] == "localUpdateCount")
    assert reg[3] == done.usn == count[3] + 5 and reg[-1] == count[-1]  # its updated_at stays, as rekordbox's does
    artist = next(r for r in after["djmdArtist"] if r[0] == done.created["djmdArtist"][0])
    content = next(r for r in after["djmdContent"] if r[0] == "100")
    assert artist[-3] < content[-3]  # made rows first, then the track, then its files
    assert STAMP_RE.fullmatch(done.stamp) and content[-1] == done.stamp


def test_text_written_where_rekordbox_shows_the_tag_and_kept_where_the_user_edited(tmp_path):
    place = library(tmp_path, Title="My own title")
    change, files, _ = plan(place)
    assert change.text["title"].kept and change.text["title"].write is None
    done = repoint(place, change, files)
    after = entry(place, path=NEW)
    assert after.title == "My own title" and done.rows[0].kept == ["title"]
    assert after.artist == "New Artist" and after.isrc == CLEAN["isrc"]
    assert set(done.rows[0].text) == {"artist", "isrc", "comment"}  # album and label already said the clean value


def test_a_lookup_row_is_found_lowest_id_first_deleted_ones_ignored(tmp_path):
    place = library(tmp_path)
    con = writer(place.db)
    for row_id, deleted in (("9", 1), ("70", 0), ("8", 0)):
        con.execute("INSERT INTO djmdArtist (ID, Name, rb_local_deleted) VALUES (?, ?, ?)",
                    (row_id, "New Artist", deleted))
    con.commit()
    con.close()
    before = dump(place.db)
    change, files, _ = plan(place)
    done = repoint(place, change, files)
    after = dump(place.db)
    assert done.created == {} and entry(place, path=NEW).artist_id == "8"
    assert before["djmdArtist"] == after["djmdArtist"]  # existing lookup rows byte-equal


def test_a_made_lookup_row_follows_rekordboxs_scheme(tmp_path):
    place = library(tmp_path)
    clean = {**CLEAN, "album": "New Album", "label": "New Label"}
    change, files, _ = plan(place, clean=clean)
    done = repoint(place, change, files)
    after = dump(place.db)
    from rekordbox_helpers import TABLES
    for table in ("djmdArtist", "djmdAlbum", "djmdLabel"):
        (new_id,) = done.created[table]
        row = dict(zip([n for n, _ in TABLES[table]], next(r for r in after[table] if r[0] == new_id)))
        assert new_id.isdigit() and 100 <= int(new_id) < 2 ** 32
        assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", row["UUID"])
        assert row.get("SearchStr") is None and row["usn"] is None
        assert (row["rb_local_deleted"], row["rb_local_synced"], row["rb_data_status"]) == (0, 0, 0)
        assert row["created_at"] == row["updated_at"] == done.stamp
    e = entry(place, path=NEW)
    assert (e.artist, e.album, e.label) == ("New Artist", "New Album", "New Label")


def test_contentfile_holds_the_new_analysis_files_md5_and_size_and_ppth_is_spliced(tmp_path):
    place = library(tmp_path)
    change, files, _ = plan(place)
    repoint(place, change, files)
    after = dump(place.db)
    for f in files:
        data = Path(f.path).read_bytes()
        assert data == f.new_bytes and anlz.ppth(anlz.parse(data)) == "?/Artist - Song.aiff"
        rel = "/" + str(Path(f.path).relative_to(place.share))
        row = next(r for r in after["contentFile"] if r[2] == rel)
        assert (row[3], row[4]) == (hashlib.md5(data).hexdigest(), len(data))
    assert not list(place.share.rglob("*.dj-new"))


def test_a_track_changed_since_the_plan_is_refused_with_nothing_written(tmp_path):
    place = library(tmp_path)
    change, files, _ = plan(place)
    con = writer(place.db)
    con.execute("UPDATE djmdContent SET FolderPath = '/Users/dj/Music/Moved.mp3' WHERE ID = '100'")
    con.commit()
    con.close()
    before, share = dump(place.db), anlz_bytes(place)
    with pytest.raises(write.WriteRefused) as e:
        repoint(place, change, files)
    assert e.value.reason == "changed" and dump(place.db) == before and anlz_bytes(place) == share


def test_an_analysis_file_changed_since_the_plan_is_refused(tmp_path):
    place = library(tmp_path)
    change, files, _ = plan(place)
    other = Path(files[1].path)
    other.write_bytes(other.read_bytes()[:-1] + b"\x01")
    before, share = dump(place.db), anlz_bytes(place)
    with pytest.raises(write.WriteRefused) as e:
        repoint(place, change, files)
    assert e.value.reason == "changed" and dump(place.db) == before and anlz_bytes(place) == share


@pytest.mark.parametrize("cloud", [{"usn": 5}, {"rb_local_synced": 1}])
def test_a_cloud_track_is_refused(tmp_path, cloud):
    place = library(tmp_path, **cloud)
    change, files, _ = plan(place)
    before = dump(place.db)
    with pytest.raises(write.WriteRefused) as e:
        repoint(place, change, files)
    assert e.value.reason == "cloud" and dump(place.db) == before


def test_rekordbox_opening_before_the_commit_rolls_everything_back(tmp_path):
    place = library(tmp_path)
    change, files, _ = plan(place)
    before, share = dump(place.db), anlz_bytes(place)
    with pytest.raises(write.RekordboxOpened):
        repoint(place, change, files, running=running_after(1))
    assert dump(place.db) == before and anlz_bytes(place) == share and not master.leftovers(place.db)


def test_the_guards_refuse_before_anything_opens_for_writing(tmp_path):
    place = library(tmp_path)
    with pytest.raises(write.WriteRefused) as e:
        with write.open_write(place, dbid="1234567890", running=lambda: True):
            pass
    assert e.value.reason == "rekordbox_open"
    with pytest.raises(write.WriteRefused) as e:
        with write.open_write(place, dbid="another", running=never):
            pass
    assert e.value.reason == "other_library"
    con = writer(place.db)  # a library left with -wal/-shm while rekordbox is closed: unclean
    con.execute("UPDATE djmdContent SET Title = 'x' WHERE ID = '200'")
    con.commit()
    leftover = snapshot(place.db.parent)
    with pytest.raises(write.WriteRefused) as e:
        with write.open_write(place, dbid="1234567890", running=never):
            pass
    assert e.value.reason == "unclean" and snapshot(place.db.parent) == leftover
    con.close()
    bad = tmp_path / "bad"
    make_master(bad, [{"path": OLD}], key="0" * 64)
    with pytest.raises(write.WriteRefused) as e:
        with write.open_write(Place(bad / "master.db", bad / "share", "override", None), dbid=None, running=never):
            pass
    assert e.value.reason == "rekordbox_unreadable" and not master.leftovers(bad / "master.db")


def test_write_text_changes_only_text_and_file_size(tmp_path):
    place = library(tmp_path, path=NEW, FileType=12)
    e = entry(place, path=NEW)
    before = dump(place.db)
    change = write.text_change(e, file_size=7777, old_tags=OLD_TAGS, clean=CLEAN)
    with write.open_write(place, dbid=None, running=never) as w:
        done = w.write_text([change])
    cols = {c for t, i, c, *_ in diff(before, dump(place.db)) if t == "djmdContent"}
    assert cols == {"FileSize", "Title", "ArtistID", "ISRC", "Commnt", "rb_local_usn", "updated_at"}
    assert done.rows[0].identity_before == done.rows[0].identity_after and done.anlz == []
    with pytest.raises(ValueError):
        with write.open_write(place, dbid=None, running=never) as w:
            w.write_text([write.RowChange("100", {}, {"FolderPath": "/x"})])


# --- undo ---

def test_undo_puts_back_identity_facts_text_and_analysis_files(tmp_path):
    place = library(tmp_path)
    before, share = dump(place.db), anlz_bytes(place)
    change, files, _ = plan(place)
    record = write.RepointRecord.from_dict(repoint(place, change, files).record().to_dict())  # through JSON's shape
    with write.open_write(place, dbid="1234567890", running=never) as w:
        out = w.undo_repoint(record)
    assert anlz_bytes(place) == share and set(out.anlz.values()) == {"restored"}
    changed = diff(before, dump(place.db))
    allowed = {"rb_local_usn", "updated_at", "int_1"}
    assert {c for t, i, c, *_ in changed if t != "djmdArtist"} <= allowed  # §0.8: only the stamp differs
    assert {t for t, i, c, *_ in changed if c == "<row>"} == {"djmdArtist"}  # the made artist row stays
    assert sorted(out.restored["100"]) == ["artist", "comment", "isrc", "title"]


def test_undo_keeps_what_the_user_did_since(tmp_path):
    place = library(tmp_path)
    change, files, _ = plan(place)
    record = repoint(place, change, files).record()
    con = writer(place.db)  # in rekordbox: a new title and a cue on the AIFF
    con.execute("UPDATE djmdContent SET Title = 'Edited' WHERE ID = '100'")
    con.execute("INSERT INTO djmdCue (ID, ContentID, InMsec) VALUES ('new-cue', '100', 5000)")
    con.commit()
    con.close()
    with write.open_write(place, dbid=None, running=never) as w:
        out = w.undo_repoint(record)
    e = entry(place)
    assert e.title == "Edited" and out.kept["100"] == ["title"] and e.artist == "Artist"
    assert any(r[0] == "new-cue" for r in dump(place.db)["djmdCue"])


def test_undo_refuses_a_relocated_track_with_nothing_changed(tmp_path):
    place = library(tmp_path)
    change, files, _ = plan(place)
    record = repoint(place, change, files).record()
    con = writer(place.db)
    con.execute("UPDATE djmdContent SET FolderPath = '/Users/dj/Elsewhere/Artist - Song.aiff' WHERE ID = '100'")
    con.commit()
    con.close()
    before, share = dump(place.db), anlz_bytes(place)
    with pytest.raises(write.WriteRefused) as e:
        with write.open_write(place, dbid=None, running=never) as w:
            w.undo_repoint(record)
    assert e.value.reason == "relocated" and dump(place.db) == before and anlz_bytes(place) == share


def test_undo_leaves_an_analysis_file_rekordbox_rewrote(tmp_path):
    place = library(tmp_path)
    change, files, _ = plan(place)
    record = repoint(place, change, files).record()
    dat = next(Path(f.path) for f in files if f.path.suffix == ".DAT")
    from rekordbox_helpers import write_track_anlz
    write_track_anlz(dat, "DAT", "?/Artist - Song (re-analysed).aiff")
    reanalysed = dat.read_bytes()
    with write.open_write(place, dbid=None, running=never) as w:
        out = w.undo_repoint(record)
    assert out.anlz[str(dat)] == "left" and dat.read_bytes() == reanalysed
    assert sorted(v for k, v in out.anlz.items() if k != str(dat)) == ["restored", "restored"]


def test_undo_rolls_back_when_rekordbox_opens_before_its_commit(tmp_path):
    place = library(tmp_path)
    change, files, _ = plan(place)
    record = repoint(place, change, files).record()
    before, share = dump(place.db), anlz_bytes(place)
    with pytest.raises(write.RekordboxOpened):
        with write.open_write(place, dbid=None, running=never) as w:
            w.undo_repoint(record, running=running_after(1))
    assert dump(place.db) == before and anlz_bytes(place) == share


def test_a_ppth_naming_another_file_is_left_alone(tmp_path):
    place = library(tmp_path, ppth="?/Something else.mp3")
    change, files, others = plan(place)
    assert files == [] and len(others) == 3
