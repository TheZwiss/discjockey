"""rekordbox's master.db, read only (discjockey/rekordbox/master.py): the keyed open, the guards, no trace beside the
library, and finding the tracks that hold a file. Every library here is built by rekordbox_helpers.make_master."""
from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest
import sqlcipher3

from discjockey.rekordbox import KEYS, Place, Status, Unreadable, locate, open_read, status
from discjockey.rekordbox.master import READ_COLUMNS, connect, leftovers
from rekordbox_helpers import make_master, snapshot, writer

ROWS = [{"ID": "1", "path": "/Users/dj/Music/Artist - Song.mp3", "artist": "Artist", "album": "Album",
         "label": "Label", "ISRC": "GBXXX2600001", "Commnt": "warm-up", "Title": "Song", "cues": 3}]


def place_of(folder: Path) -> Place:
    return locate(env={"DISCJOCKEY_REKORDBOX": str(folder)})


def library(tmp_path: Path, rows=ROWS, **kw) -> Place:
    make_master(tmp_path / "rb", rows, **kw)
    return place_of(tmp_path / "rb")


def closed():
    return False


def open_now():
    return True


# --- open and guards ---

def test_the_key_opens_the_library(tmp_path):
    place = library(tmp_path)
    assert status(place, closed) == Status("ready", False, None, str(place.db), None, "6000", "1234567890")


def test_status_finds_the_library_through_locate_and_asks_ps_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr("discjockey.rekordbox.process.running", lambda: True)
    place = library(tmp_path)
    assert status(place).running is True


def test_a_wrong_key_is_unreadable(tmp_path):
    place = library(tmp_path, key="ab" * 32)
    st = status(place, closed)
    assert (st.state, st.problem, st.db_version) == ("unreadable", "key", None)


def test_a_failed_open_while_rekordbox_runs_is_busy_not_unreadable(tmp_path):
    place = library(tmp_path, key="ab" * 32)
    st = status(place, open_now)
    assert (st.state, st.running, st.problem) == ("ready", True, "busy")


def test_another_database_version_is_unreadable(tmp_path):
    st = status(library(tmp_path, version="5999"), closed)
    assert (st.state, st.problem, st.db_version, st.dbid) == ("unreadable", "db_version", "5999", "1234567890")


@pytest.mark.parametrize("drop", [{"djmdContent": ("Commnt",)}, {"djmdContent": ("rb_local_deleted",)},
                                  {"djmdLabel": ("Name",)}, {"djmdCue": ("ContentID",)}, {"djmdAlbum": None},
                                  {"agentRegistry": ("int_1",)}, {"djmdProperty": ("DBID",)}])
def test_a_missing_read_column_is_a_schema_problem(tmp_path, drop):
    st = status(library(tmp_path, drop=drop), closed)
    assert (st.state, st.problem) == ("unreadable", "schema")


def test_every_read_column_is_in_the_fixture():
    from rekordbox_helpers import TABLES
    for table, columns in READ_COLUMNS.items():
        assert set(columns) <= {name for name, _ in TABLES[table]}, table


@pytest.mark.parametrize("names", [("-wal",), ("-shm",), ("-wal", "-shm")])
def test_leftover_wal_files_while_rekordbox_is_closed_are_unclean(tmp_path, names):
    place = library(tmp_path)
    for suffix in names:
        place.db.with_name("master.db" + suffix).write_bytes(b"")
    st = status(place, closed)
    assert (st.state, st.problem, st.db_version) == ("ready", "unclean", "6000")


def test_no_library_is_none(tmp_path):
    assert status(locate(), closed) == Status("none", False, None, None, None, None, None)
    (tmp_path / "rb5").mkdir()
    (tmp_path / "rb5" / "datafile.edb").write_bytes(b"x")
    assert status(place_of(tmp_path / "rb5"), closed).state == "none"


def test_a_library_gone_since_locate_is_none(tmp_path):
    place = library(tmp_path)
    place.db.unlink()
    assert status(place, closed).state == "none"


def test_a_file_that_isnt_a_database_is_unreadable(tmp_path):
    (tmp_path / "rb").mkdir()
    (tmp_path / "rb" / "master.db").write_bytes(b"\0" * 4096)
    assert status(place_of(tmp_path / "rb"), closed).problem == "key"


# --- while rekordbox runs (check first: a mode=ro open shares rekordbox's -wal/-shm and sees its commits) ---

def test_a_read_while_rekordbox_runs_sees_what_it_committed(tmp_path):
    place = library(tmp_path)
    rekordbox = writer(place.db)
    try:
        rekordbox.execute("INSERT INTO djmdContent (ID, FolderPath, FileType, rb_local_deleted) "
                          "VALUES ('2', '/Users/dj/Music/New.aiff', 12, 0)")
        rekordbox.commit()
        assert len(leftovers(place.db)) == 2
        assert status(place, open_now) == Status("ready", True, None, str(place.db), None, "6000", "1234567890")
        with open_read(place, True) as master:
            assert [e.id for e in master.entries_for(Path("/Users/dj/Music/New.aiff"))] == ["2"]
            with pytest.raises(sqlcipher3.OperationalError):
                master.con.execute("UPDATE djmdContent SET Title = 'x'")
    finally:
        rekordbox.close()


# --- no trace, read only ---

@pytest.mark.parametrize("running", [closed, open_now])
def test_reading_leaves_the_library_folder_as_it_was(tmp_path, running):
    place = library(tmp_path)
    before = snapshot(place.db.parent)
    status(place, running)
    with open_read(place, running()) as master:
        master.cue_counts([e.id for e in master.entries_for(Path(ROWS[0]["path"]))])
    assert snapshot(place.db.parent) == before


def test_a_write_through_the_connection_fails(tmp_path):
    place = library(tmp_path)
    with open_read(place, False) as master:
        with pytest.raises(sqlcipher3.OperationalError, match="readonly"):
            master.con.execute("UPDATE djmdContent SET Title = 'x'")
        assert not hasattr(master, "commit")
    with open_read(place, False) as master:
        assert master.entries_for(Path(ROWS[0]["path"]))[0].title == "Song"


def test_open_read_raises_unreadable_with_the_problem(tmp_path):
    with pytest.raises(Unreadable) as e:
        with open_read(library(tmp_path, version="7000"), False):
            pass
    assert (e.value.problem, e.value.db_version) == ("db_version", "7000")


def test_connect_wants_a_hex_key_and_closes_on_a_wrong_one(tmp_path):
    db = make_master(tmp_path / "rb", ROWS)
    with pytest.raises(ValueError):
        connect(db, "'; DROP TABLE x; --")
    with pytest.raises(sqlcipher3.DatabaseError):
        connect(db, "cd" * 32)
    con = connect(db, KEYS[0])
    assert con.execute("SELECT DBVersion FROM djmdProperty").fetchone() == ("6000",)
    con.close()


# --- finding the track ---

def entries(tmp_path, rows, path):
    with open_read(library(tmp_path, rows), False) as master:
        return master.entries_for(Path(path))


def test_the_entry_carries_its_fields(tmp_path):
    [entry] = entries(tmp_path, ROWS, ROWS[0]["path"])
    assert entry.id == "1" and entry.folder_path == ROWS[0]["path"]
    assert (entry.file_name, entry.file_type, entry.title) == ("Artist - Song.mp3", 1, "Song")
    assert (entry.artist, entry.album, entry.label) == ("Artist", "Album", "Label")
    assert (entry.isrc, entry.comment, entry.cloud) == ("GBXXX2600001", "warm-up", False)
    assert entry.analysis_path == "/PIONEER/USBANLZ/000/1/ANLZ0000.DAT"
    assert entry.created_at == "2026-01-02 03:04:05.678 +00:00"


def test_no_lookup_ids_give_empty_names_and_no_analysis_is_none(tmp_path):
    rows = [{"ID": "1", "path": "/m/a.aiff", "AnalysisDataPath": "", "ArtistID": "gone", "Title": None}]
    [entry] = entries(tmp_path, rows, "/m/a.aiff")
    assert (entry.artist, entry.album, entry.label, entry.title, entry.analysis_path) == ("", "", "", "", None)
    assert entry.file_type == 12


@pytest.mark.parametrize("query", ["/Users/dj/Music/Café - Été.mp3", "/users/DJ/music/CAFÉ - ÉTÉ.MP3"])
@pytest.mark.parametrize("stored", ["NFC", "NFD"])
def test_paths_match_across_unicode_forms_and_case(tmp_path, query, stored):
    rows = [{"ID": "1", "path": unicodedata.normalize(stored, "/Users/dj/Music/Café - Été.mp3")}]
    for form in ("NFC", "NFD"):
        assert [e.id for e in entries(tmp_path / form, rows, unicodedata.normalize(form, query))] == ["1"]


def test_another_file_does_not_match(tmp_path):
    assert entries(tmp_path, ROWS, "/Users/dj/Music/Artist - Song.aiff") == []
    assert entries(tmp_path / "2", ROWS, "/Users/dj/Music/Other/Artist - Song.mp3") == []


def test_deleted_and_streaming_rows_never_match(tmp_path):
    path = "/m/a.mp3"
    rows = [{"ID": "1", "path": path, "rb_local_deleted": 1}, {"ID": "2", "path": path, "FileType": 25},
            {"ID": "3", "path": path}]
    assert [e.id for e in entries(tmp_path, rows, path)] == ["3"]


def test_two_tracks_for_one_file_are_both_returned(tmp_path):
    rows = [{"ID": "7", "path": "/m/a.mp3"}, {"ID": "5", "path": "/m/b.mp3"}, {"ID": "6", "path": "/M/A.mp3"}]
    assert [e.id for e in entries(tmp_path, rows, "/m/a.mp3")] == ["7", "6"]


def test_a_path_through_a_linked_folder_matches_the_same_file(tmp_path):
    real = tmp_path / "music"
    real.mkdir()
    (real / "a.mp3").write_bytes(b"x")
    (tmp_path / "link").symlink_to(real)
    rows = [{"ID": "1", "path": str(tmp_path / "link" / "a.mp3")}, {"ID": "2", "path": str(tmp_path / "x/a.mp3")}]
    assert [e.id for e in entries(tmp_path / "db", rows, real / "a.mp3")] == ["1"]


def test_a_relative_path_is_matched_as_its_absolute_path(tmp_path, monkeypatch):
    monkeypatch.chdir("/")
    assert [e.id for e in entries(tmp_path, ROWS, "Users/dj/Music/Artist - Song.mp3")] == ["1"]


@pytest.mark.parametrize("cloud, expected", [({}, False), ({"usn": 12}, True), ({"rb_local_synced": 1}, True),
                                             ({"usn": None, "rb_local_synced": 0}, False)])
def test_cloud_comes_from_usn_or_rb_local_synced(tmp_path, cloud, expected):
    [entry] = entries(tmp_path, [{"ID": "1", "path": "/m/a.mp3", **cloud}], "/m/a.mp3")
    assert entry.cloud is expected


def test_cue_counts_count_live_cues_and_zero_for_none(tmp_path):
    place = library(tmp_path, [{"ID": "1", "path": "/m/a.mp3", "cues": 3}, {"ID": "2", "path": "/m/b.mp3"},
                               {"ID": "3", "path": "/m/c.mp3", "cues": 2}])
    with open_read(place, False) as master:
        master_con = master.con
        assert master.cue_counts(["1", "2", "3", "9"]) == {"1": 3, "2": 0, "3": 2, "9": 0}
    rekordbox = writer(place.db)
    rekordbox.execute("UPDATE djmdCue SET rb_local_deleted = 1 WHERE ContentID = '1' AND InMsec = 0")
    rekordbox.commit()
    rekordbox.close()
    with open_read(place, False) as master:
        assert master.con is not master_con
        assert master.cue_counts(["1"]) == {"1": 2}
        assert master.cue_counts([]) == {}


def test_many_ids_are_asked_in_chunks(tmp_path):
    rows = [{"ID": str(i), "path": f"/m/{i}.mp3", "cues": 1} for i in range(1, 1201)]
    with open_read(library(tmp_path, rows), False) as master:
        counts = master.cue_counts([str(i) for i in range(1, 1201)])
    assert len(counts) == 1200 and set(counts.values()) == {1}
