"""library.db: connection, schema version, the entry <-> rows mapping and the diffing save (plan library stage 1,
group 1)."""
import json
import sqlite3
import unicodedata
from datetime import datetime

import pytest

from discjockey import db
from discjockey.library import StateError

NOW = datetime(2026, 10, 23, 12, 0, 0)


def no_facts(path):
    return None


@pytest.fixture
def library(tmp_path):
    lib = tmp_path / "music" / "Library"
    lib.mkdir(parents=True)
    return lib


def fresh(tmp_path, library, state=None, facts=no_facts):
    path = tmp_path / "library.db"
    db.create(path, state or {"tracks": {}}, library=library, facts=facts, now=NOW)
    return path


# --- 1.1 connection, schema, version check ---

def test_connect_sets_the_binding_pragmas(tmp_path, library):
    path = fresh(tmp_path, library)
    with db.connect(path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA fullfsync").fetchone()[0] == 1
        assert conn.execute("PRAGMA checkpoint_fullfsync").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_the_connection_closes_at_the_end_of_its_with(tmp_path, library):
    path = fresh(tmp_path, library)
    with db.connect(path) as conn:
        pass
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_a_fresh_database_has_the_current_version(tmp_path, library):
    path = fresh(tmp_path, library)
    with db.connect(path) as conn:
        db.check(conn)
        version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
        created = conn.execute("SELECT value FROM meta WHERE key = 'created'").fetchone()[0]
    assert int(version) == db.SCHEMA_VERSION == 1
    assert created == "2026-10-23T12:00:00"


def test_create_refuses_an_existing_file(tmp_path, library):
    path = fresh(tmp_path, library)
    with pytest.raises(FileExistsError):
        db.create(path, {"tracks": {}}, library=library, facts=no_facts, now=NOW)


def test_a_newer_database_is_refused_with_the_words(tmp_path, library):
    path = fresh(tmp_path, library)
    with db.connect(path) as conn:
        conn.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
    with db.connect(path) as conn, pytest.raises(StateError) as e:
        db.check(conn)
    assert str(e.value) == ("This music folder was last used by a newer Discjockey. Update Discjockey, then try "
                            "again. Nothing was changed.")


def test_a_file_that_isnt_a_database_is_refused(tmp_path):
    path = tmp_path / "library.db"
    path.write_bytes(b"this is not a database at all, just some words " * 100)
    with pytest.raises(StateError) as e:
        with db.connect(path) as conn:
            db.check(conn)
    assert str(e.value).startswith("Discjockey can't read its records of this music folder (.discjockey/library.db): ")
    assert str(e.value).endswith(". Nothing was changed.")
    assert path.read_bytes() == b"this is not a database at all, just some words " * 100


def test_a_database_without_records_is_refused(tmp_path):
    path = tmp_path / "library.db"
    sqlite3.connect(path).close()
    with db.connect(path) as conn, pytest.raises(StateError, match="can't read its records"):
        db.check(conn)


def test_an_upgrade_step_is_applied_once_and_bumps_the_version(tmp_path, library, monkeypatch):
    path = fresh(tmp_path, library)
    calls = []

    def step(conn):
        calls.append(1)
        conn.execute("CREATE TABLE extra_v2 (id INTEGER PRIMARY KEY)")

    monkeypatch.setattr(db, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(db, "UPGRADES", {1: step})
    for _ in range(2):
        with db.connect(path) as conn:
            db.check(conn)
    assert calls == [1]
    with db.connect(path) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "2"
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'extra_v2'").fetchone()


def test_a_failing_upgrade_step_leaves_the_old_version(tmp_path, library, monkeypatch):
    path = fresh(tmp_path, library)

    def step(conn):
        conn.execute("CREATE TABLE half_done (id INTEGER PRIMARY KEY)")
        raise RuntimeError("disk full")

    monkeypatch.setattr(db, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(db, "UPGRADES", {1: step})
    with db.connect(path) as conn, pytest.raises(RuntimeError):
        db.check(conn)
    with db.connect(path) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "1"
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'half_done'").fetchone() is None


def test_create_builds_the_current_version_through_the_upgrade_steps(tmp_path, library, monkeypatch):
    monkeypatch.setattr(db, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(db, "UPGRADES", {1: lambda conn: conn.execute("CREATE TABLE extra_v2 (id INTEGER)")})
    path = fresh(tmp_path, library)
    with db.connect(path) as conn:
        db.check(conn)
        assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "2"
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'extra_v2'").fetchone()


# --- 1.2 entry <-> rows, create, snapshot ---

def entry(artist, title, path=None, **kw):
    e = dict.fromkeys(db.ENTRY_KEYS)
    e.update(aliases=[], artist=artist, title=title, folder="House", in_playlists=True, added="2026-10-01T10:00:00",
             rejected_sources=[], path=path, status="lossless" if path else "missing")
    if path:
        e.update(source="qobuz", source_id="123", source_format="flac 16/44.1", cutoff_hz=22000)
    e.update(kw)
    return e


def v1_state():
    """A state.json-shaped dict with every kind of entry the engine writes."""
    upgrade = {"file": "Upgrades ready/House/A - One.aiff", "source": "qobuz", "status": "lossless", "kbps": None,
               "cutoff_hz": 22000, "found": "2026-10-20"}
    return {
        "version": 1,
        "tracks": {
            "sp1": entry("A", "One", "Library/House/A - One.mp3", aliases=["sp1b", "sp1c"], isrc="GB123",
                         duration_ms=200000, status="not_lossless", source="youtube", source_id="yt1",
                         source_format="opus", cutoff_hz=16000, source_kbps=160, upgrade=upgrade,
                         free_downloads=["https://example.com/free"], last_upgrade_check="2026-10-20",
                         declined_streams=["youtube:yt1"]),
            "sp2": entry("B", "Two", last_attempt="2026-10-22", rejected_sources=["youtube:x"]),
            "sp3": entry("C", "Thrée", "Library/Techno/C - Thrée.aiff", hidden=True,
                         rekordbox_check={"reason": "wrong_song", "since": "2026-10-21"}, future_key={"a": [1, 2]}),
        },
        "pending": [{"track_id": "sp3", "renames": [["a", "b"]], "entry": None}],
        "never": {"sp9": {"artist": "Z", "title": "Never", "folder": "House", "at": "2026-10-02"}},
        "qobuz_usage": {"days": {"2026-10-22": 4}, "signals": [{"kind": "auto_stop", "at": "x"}]},
        "youtube_usage": {"days": {"2026-10-22": 2}, "signals": [], "last_download": "2026-10-22T10:00:00"},
    }


def without_read_only(tracks):
    return {k: {f: v for f, v in e.items() if f not in ("online", "placed_by")} for k, e in tracks.items()}


def fake_facts(present):
    def facts(path):
        return db.FileFacts(len(path), 1000 + len(path), f"key-{path}") if path in present else None
    return facts


def test_create_then_snapshot_gives_back_the_same_state(tmp_path, library):
    state = v1_state()
    path = fresh(tmp_path, library, state, fake_facts({"Library/House/A - One.mp3"}))
    with db.connect(path) as conn:
        snap = db.snapshot(conn, library)
    want = {k: {**e, "file_gone": None} for k, e in state["tracks"].items()}
    assert without_read_only(snap["tracks"]) == want
    for key in ("pending", "never", "qobuz_usage", "youtube_usage"):
        assert snap[key] == state[key]
    assert snap["version"] == 2
    assert snap["files"] == ["Library/House/A - One.mp3", "Library/Techno/C - Thrée.aiff"]
    assert snap["ambiguous"] == {}
    assert snap["tracks"]["sp1"]["online"] is True and snap["tracks"]["sp1"]["placed_by"] == "app"
    assert snap["tracks"]["sp2"]["online"] is False and snap["tracks"]["sp2"]["placed_by"] is None


def test_create_writes_the_expected_rows(tmp_path, library):
    path = fresh(tmp_path, library, v1_state(), fake_facts({"Library/House/A - One.mp3"}))
    with db.connect(path) as conn:
        folders = conn.execute("SELECT id, path, kind, added FROM watched_folders").fetchall()
        assert folders == [(1, library.as_posix(), "library", "2026-10-23T12:00:00")]
        ids = conn.execute("SELECT service, id, song FROM song_ids ORDER BY rowid").fetchall()
        assert ids == [("spotify", "sp1", 1), ("spotify", "sp2", 2), ("spotify", "sp3", 3),
                       ("spotify", "sp1b", 1), ("spotify", "sp1c", 1)]
        files = conn.execute("SELECT song, folder, path, size, mtime_ns, content_key, placed_by, online, first_seen, "
                             "status, source_kbps FROM files ORDER BY id").fetchall()
        mp3 = "Library/House/A - One.mp3"
        assert files == [(1, 1, "House/A - One.mp3", len(mp3), 1000 + len(mp3), f"key-{mp3}", "app", 1,
                          "2026-10-23T12:00:00", "not_lossless", 160),
                         (3, 1, "Techno/C - Thrée.aiff", None, None, None, "app", 1, "2026-10-23T12:00:00",
                          "lossless", None)]
        extra, gone = conn.execute("SELECT extra, file_gone FROM songs WHERE key = 'sp3'").fetchone()
        assert gone is None
        assert json.loads(extra) == {"hidden": True, "future_key": {"a": [1, 2]},
                                     "rekordbox_check": {"reason": "wrong_song", "since": "2026-10-21"}}
        assert conn.execute("SELECT extra FROM songs WHERE key = 'sp2'").fetchone()[0] is None
        assert conn.execute("SELECT service FROM usage ORDER BY service").fetchall() == [("qobuz",), ("youtube",)]


def test_rows_store_nfc_paths(tmp_path, library):
    decomposed = unicodedata.normalize("NFD", "Library/Techno/C - Thrée.aiff")
    path = fresh(tmp_path, library, {"tracks": {"sp3": entry("C", "Thrée", decomposed)}})
    with db.connect(path) as conn:
        assert conn.execute("SELECT path FROM files").fetchone()[0] == "Techno/C - Thrée.aiff"


def test_a_path_outside_every_watched_folder_is_refused(tmp_path, library):
    for bad in ("Music/A - One.aiff", "/Volumes/Other/A - One.aiff", "Library/"):
        with pytest.raises(ValueError):
            db.create(tmp_path / f"x{len(bad)}.db", {"tracks": {"sp1": entry("A", "One", bad)}}, library=library,
                      facts=no_facts, now=NOW)


def test_two_entries_on_one_file_are_refused(tmp_path, library):
    state = {"tracks": {"a": entry("A", "One", "Library/x.aiff"), "b": entry("B", "Two", "Library/x.aiff")}}
    with pytest.raises(StateError) as e:
        db.create(tmp_path / "library.db", state, library=library, facts=no_facts, now=NOW)
    assert str(e.value) == ("Two songs in Discjockey's records point at the same file, Library/x.aiff (A - One and "
                            "B - Two). Nothing was changed.")


def test_absent_keys_stay_absent_and_the_planner_sees_the_same_state(tmp_path, library):
    import copy
    from datetime import date

    from discjockey import planner
    legacy = entry("A", "One", "Library/House/A - One.aiff")
    for key in ("free_downloads", "in_playlists", "upgrade", "source_kbps"):  # written before these existed
        del legacy[key]
    nulled = entry("B", "Two", free_downloads=None, in_playlists=None)
    state = {"version": 1, "tracks": {"sp1": legacy, "sp2": nulled}, "pending": [], "never": {},
             "qobuz_usage": {"days": {}, "signals": []}}
    path = fresh(tmp_path, library, state)
    with db.connect(path) as conn:
        snap = db.snapshot(conn, library)
    assert set(without_read_only(snap["tracks"])["sp1"]) == set(legacy) | {"file_gone"}
    assert "free_downloads" in snap["tracks"]["sp2"] and snap["tracks"]["sp2"]["in_playlists"] is False
    files = ["Library/House/A - One.aiff"]
    today = date(2026, 10, 23)
    import dataclasses
    from_rows = planner.plan([], copy.deepcopy(snap), files, today)
    from_json = planner.plan([], copy.deepcopy(state), files, today)
    assert dataclasses.replace(from_rows, state=None) == dataclasses.replace(from_json, state=None)
    assert from_rows.state["tracks"]["sp1"]["in_playlists"] == from_json.state["tracks"]["sp1"]["in_playlists"]


def test_unreadable_names_what_went_wrong():
    assert "using it right now" in str(db.unreadable(sqlite3.OperationalError("database is locked")))
    assert "read-only" in str(db.unreadable(sqlite3.OperationalError("attempt to write a readonly database")))
    assert "damaged" in str(db.unreadable(sqlite3.DatabaseError("file is not a database")))


def test_a_failing_commit_is_rolled_back(tmp_path, library):
    path = fresh(tmp_path, library)
    with db.connect(path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            with db.transaction(conn):
                conn.execute("PRAGMA defer_foreign_keys = ON")  # the broken reference fails at COMMIT
                conn.execute("INSERT INTO files (song, folder, path, placed_by, first_seen, last_seen) "
                             "VALUES (999, 1, 'x', 'app', 'x', 'x')")
        assert not conn.in_transaction
        assert conn.execute("SELECT count(*) FROM files").fetchone() == (0,)


def test_snapshot_builds_ambiguous_and_files_from_rows(tmp_path, library):
    path = fresh(tmp_path, library, {"tracks": {"sp1": entry("A", "One", "Library/House/A - One.aiff")}})
    with db.connect(path) as conn:
        conn.execute("INSERT INTO watched_folders (path, kind, added) VALUES ('/Volumes/Mine', 'import', 'x')")
        conn.execute("UPDATE files SET ambiguous = ? WHERE song = 1",
                     (json.dumps(["Library/a/A - One.aiff", "/Volumes/Mine/A - One.aiff"]),))
        for folder, rel, online in ((2, "A - One.aiff", 1), (1, "a/A - One.aiff", 1), (2, "Gone.aiff", 0)):
            conn.execute("INSERT INTO files (folder, path, placed_by, online, first_seen, last_seen) "
                         "VALUES (?, ?, 'user', ?, 'x', 'x')", (folder, rel, online))
        snap = db.snapshot(conn, library)
    assert snap["ambiguous"] == {"sp1": ["Library/a/A - One.aiff", "/Volumes/Mine/A - One.aiff"]}
    assert snap["files"] == ["/Volumes/Mine/A - One.aiff", "Library/House/A - One.aiff", "Library/a/A - One.aiff"]


def test_snapshot_only_reads_and_save_follows_a_moved_music_folder(tmp_path, library):
    path = fresh(tmp_path, library, {"tracks": {"sp1": entry("A", "One", "Library/House/A - One.aiff")}})
    moved = tmp_path / "Volumes" / "New" / "Library"
    with db.connect(path) as writer, db.transaction(writer):  # another process is writing meanwhile
        with db.connect(path) as conn:
            snap = db.snapshot(conn, moved)
            assert conn.execute("SELECT path FROM watched_folders").fetchone()[0] == library.as_posix()
    assert snap["tracks"]["sp1"]["path"] == "Library/House/A - One.aiff"
    with db.connect(path) as conn:
        assert db.save(conn, snap, library=moved, facts=no_facts, now=NOW) == 2  # the path and qobuz_usage
        assert conn.execute("SELECT path FROM watched_folders").fetchone()[0] == moved.as_posix()
        assert db.save(conn, snap, library=moved, facts=no_facts, now=NOW) == 0


def test_an_empty_database_has_the_default_records(tmp_path, library):
    with db.connect(fresh(tmp_path, library)) as conn:
        snap = db.snapshot(conn, library)
    assert snap == {"version": 2, "tracks": {}, "pending": [], "never": {},
                    "qobuz_usage": {"days": {}, "signals": []}, "ambiguous": {}, "files": []}


# --- 1.3 the diffing save ---

ONE = "Library/House/A - One.mp3"
THREE = "Library/Techno/C - Thrée.aiff"


@pytest.fixture
def opened(tmp_path, library):
    """A database built from v1_state, its snapshot, and a save that reports what it changed."""
    present = {ONE, THREE}
    facts = fake_facts(present)
    path = fresh(tmp_path, library, v1_state(), facts)

    class Opened:
        def snap(self):
            with db.connect(path) as conn:
                return db.snapshot(conn, library)

        def save(self, state, **kw):
            with db.connect(path) as conn:
                return db.save(conn, state, library=library, facts=facts, now=datetime(2026, 10, 24, 9, 0, 0), **kw)

        def rows(self, sql, *args):
            with db.connect(path) as conn:
                return conn.execute(sql, args).fetchall()

    o = Opened()
    o.present = present
    return o


def test_an_unchanged_save_writes_nothing(opened):
    assert opened.save(opened.snap()) == 0


def test_one_changed_entry_writes_one_row(opened):
    state = opened.snap()
    state["tracks"]["sp2"]["last_attempt"] = "2026-10-24"
    assert opened.save(state) == 1
    assert opened.snap()["tracks"]["sp2"]["last_attempt"] == "2026-10-24"
    assert opened.save(opened.snap()) == 0


def test_read_only_keys_are_ignored(opened):
    state = opened.snap()
    state["tracks"]["sp1"].update(online=False, placed_by="user")
    state["files"] = ["Library/elsewhere.aiff"]
    state["ambiguous"] = {"sp1": ["Library/x.aiff"]}
    assert opened.save(state) == 0
    assert opened.snap()["tracks"]["sp1"]["placed_by"] == "app"


def test_extra_keys_and_file_gone_are_written(opened):
    state = opened.snap()
    state["tracks"]["sp3"]["rekordbox_check"] = None
    state["tracks"]["sp2"]["file_gone"] = "2026-10-24"
    assert opened.save(state) == 2
    snap = opened.snap()
    assert snap["tracks"]["sp3"]["rekordbox_check"] is None and snap["tracks"]["sp3"]["hidden"] is True
    assert snap["tracks"]["sp2"]["file_gone"] == "2026-10-24"


def test_changed_aliases_rewrite_the_song_ids(opened):
    state = opened.snap()
    state["tracks"]["sp1"]["aliases"] = ["sp1c", "sp1d"]
    assert opened.save(state) > 0
    assert opened.snap()["tracks"]["sp1"]["aliases"] == ["sp1c", "sp1d"]
    assert opened.rows("SELECT id FROM song_ids WHERE song = 1 ORDER BY rowid") == [("sp1",), ("sp1c",), ("sp1d",)]


def test_a_new_path_moves_the_row_in_place_rekeys_it_and_keeps_placed_by(opened):
    (file_id,) = opened.rows("SELECT id FROM files WHERE song = 3")[0]
    opened.rows("UPDATE files SET placed_by = 'user' WHERE id = ?", file_id)
    state = opened.snap()
    new = "Library/House/C - Thrée.aiff"
    opened.present.add(new)
    state["tracks"]["sp3"]["path"] = new
    assert opened.save(state) == 1
    assert opened.rows("SELECT id, path, placed_by, size, content_key, last_seen FROM files WHERE song = 3") == [
        (file_id, "House/C - Thrée.aiff", "user", len(new), f"key-{new}", "2026-10-24T09:00:00")]


def test_new_audio_under_the_same_path_rekeys_and_keeps_placed_by(opened, monkeypatch):
    opened.rows("UPDATE files SET placed_by = 'user', content_key = 'old' WHERE song = 1")
    state = opened.snap()
    state["tracks"]["sp1"].update(status="lossless", source="qobuz", source_id="q1", source_format="flac",
                                  cutoff_hz=22050, source_kbps=None)
    assert opened.save(state) == 1
    assert opened.rows("SELECT path, placed_by, content_key, status, source_id FROM files WHERE song = 1") == [
        ("House/A - One.mp3", "user", f"key-{ONE}", "lossless", "q1")]


def test_a_path_with_an_unlinked_row_links_that_row(opened):
    bought = "Library/House/B - Two.aiff"
    opened.rows("INSERT INTO files (folder, path, placed_by, first_seen, last_seen) "
                "VALUES (1, 'House/B - Two.aiff', 'user', 'x', 'x')")
    (bought_id,) = opened.rows("SELECT id FROM files WHERE path = 'House/B - Two.aiff'")[0]
    opened.present.add(bought)
    state = opened.snap()
    state["tracks"]["sp2"].update(path=bought, status="lossless", source=None, source_id=None)
    assert opened.save(state) == 1
    assert opened.rows("SELECT id, song, placed_by, status FROM files WHERE path = 'House/B - Two.aiff'") == [
        (bought_id, 2, "app", "lossless")]
    assert opened.rows("SELECT count(*) FROM files") == [(3,)]


def test_moving_onto_an_unlinked_row_releases_the_old_row(opened):
    opened.rows("INSERT INTO files (folder, path, placed_by, first_seen, last_seen) "
                "VALUES (1, 'House/A - One.aiff', 'user', 'x', 'x')")
    state = opened.snap()
    state["tracks"]["sp1"].update(path="Library/House/A - One.aiff", status="lossless")
    assert opened.save(state) == 2  # the new row linked, the old one unlinked (its file is still there)
    assert opened.rows("SELECT path, song FROM files WHERE path LIKE 'House/A - One%' ORDER BY path") == [
        ("House/A - One.aiff", 1), ("House/A - One.mp3", None)]


def test_missing_unlinks_a_file_that_is_still_there(opened):
    state = opened.snap()
    state["tracks"]["sp1"].update(path=None, status="missing", source=None)
    assert opened.save(state) == 1
    assert opened.rows("SELECT song FROM files WHERE path = 'House/A - One.mp3'") == [(None,)]
    assert opened.snap()["tracks"]["sp1"]["path"] is None


def test_missing_deletes_the_row_of_a_file_that_is_gone(opened):
    opened.present.discard(ONE)
    state = opened.snap()
    state["tracks"]["sp1"].update(path=None, status="missing")
    assert opened.save(state) == 1
    assert opened.rows("SELECT count(*) FROM files WHERE path = 'House/A - One.mp3'") == [(0,)]


def test_a_removed_key_deletes_the_song(opened):
    opened.present.discard(THREE)
    state = opened.snap()
    del state["tracks"]["sp3"], state["tracks"]["sp1"]
    assert opened.save(state) == 4  # two songs, one file row unlinked (still there), one deleted (gone)
    assert opened.rows("SELECT key FROM songs") == [("sp2",)]
    assert opened.rows("SELECT path, song FROM files") == [("House/A - One.mp3", None)]
    assert opened.rows("SELECT id FROM song_ids") == [("sp2",)]


def test_a_new_key_inserts_its_song_and_file(opened):
    state = opened.snap()
    new = "Library/House/D - Four.aiff"
    opened.present.add(new)
    state["tracks"]["sp4"] = entry("D", "Four", new, aliases=["sp4b"])
    assert opened.save(state) == 4  # song, its own id, one alias, one file
    snap = opened.snap()
    assert without_read_only({"sp4": snap["tracks"]["sp4"]})["sp4"] == {**state["tracks"]["sp4"], "file_gone": None}
    assert snap["tracks"]["sp4"]["placed_by"] == "app"


def test_two_songs_trading_places(opened):
    state = opened.snap()
    state["tracks"]["sp1"]["path"], state["tracks"]["sp3"]["path"] = THREE, ONE
    assert opened.save(state) == 2
    snap = opened.snap()
    assert (snap["tracks"]["sp1"]["path"], snap["tracks"]["sp3"]["path"]) == (THREE, ONE)
    assert opened.rows("SELECT count(*) FROM files") == [(2,)]


def test_two_songs_on_one_path_are_refused_and_nothing_is_written(opened):
    state = opened.snap()
    state["tracks"]["sp2"]["last_attempt"] = "2026-10-24"
    state["tracks"]["sp1"]["path"] = THREE
    with pytest.raises(StateError, match="point at the same file"):
        opened.save(state)
    assert opened.snap()["tracks"]["sp2"]["last_attempt"] == "2026-10-22"


def test_rekeyed_paths_get_their_facts_again(opened):
    state = opened.snap()
    assert opened.save(state) == 0
    opened.rows("UPDATE files SET content_key = 'before the swap' WHERE song = 1")
    assert opened.save(state, rekeyed={ONE}) == 1
    assert opened.rows("SELECT content_key FROM files WHERE song = 1") == [(f"key-{ONE}",)]


def test_a_rekeyed_path_whose_file_is_missing_keeps_its_row_for_the_scan(opened):
    state = opened.snap()
    before = opened.rows("SELECT size, mtime_ns, content_key FROM files WHERE song = 1")
    opened.present.discard(ONE)  # the file went away between the step and the save
    assert opened.save(state, rekeyed={ONE}) == 0
    assert opened.rows("SELECT size, mtime_ns, content_key FROM files WHERE song = 1") == before


def test_a_new_song_doesnt_take_an_alias_another_song_has(opened):
    state = opened.snap()
    state["tracks"]["sp1b"] = entry("E", "Five")
    opened.save(state)
    assert opened.rows("SELECT s.key FROM song_ids i JOIN songs s ON s.id = i.song WHERE i.id = 'sp1b'") == [("sp1",)]


def test_a_path_outside_the_watched_folders_is_a_value_error(opened):
    state = opened.snap()
    state["tracks"]["sp1"]["path"] = "Superseded/House/A - One.mp3"
    with pytest.raises(ValueError):
        opened.save(state)


def test_pending_is_replaced_when_it_differs(opened):
    state = opened.snap()
    op = {"track_id": "sp1", "renames": [["x", "y"]], "entry": None}
    state["pending"].append(op)
    assert opened.save(state) == 3  # one deleted, two inserted
    assert opened.snap()["pending"][-1] == op
    state["pending"] = []
    assert opened.save(state) == 2
    assert opened.snap()["pending"] == []


def test_never_and_usage_write_only_what_differs(opened):
    state = opened.snap()
    state["never"]["sp8"] = {"artist": "Y", "title": "T", "folder": "House", "at": "2026-10-24"}
    del state["never"]["sp9"]
    state["qobuz_usage"]["days"]["2026-10-24"] = 1
    state["soundcloud_usage"] = {"days": {}, "signals": []}
    assert opened.save(state) == 4
    snap = opened.snap()
    assert set(snap["never"]) == {"sp8"}
    assert snap["qobuz_usage"]["days"]["2026-10-24"] == 1
    assert snap["soundcloud_usage"] == {"days": {}, "signals": []}


def test_a_version_1_dict_is_never_saved(opened):
    state = v1_state()
    with pytest.raises(StateError):
        opened.save(state)


def test_a_user_placed_song_s_replacement_found_next_to_it_stays_the_user_s(opened):
    """A bought file next to the current one (or a candidate the scan indexed): the row found there is linked."""
    opened.rows("UPDATE files SET placed_by = 'user' WHERE song = 1")
    opened.rows("INSERT INTO files (folder, path, placed_by, first_seen, last_seen) "
                "VALUES (1, 'House/A - One.aiff', 'import', 'x', 'x')")
    opened.present.add("Library/House/A - One.aiff")
    state = opened.snap()
    state["tracks"]["sp1"].update(path="Library/House/A - One.aiff", status="lossless")
    opened.save(state)
    assert opened.rows("SELECT placed_by FROM files WHERE song = 1") == [("user",)]


@pytest.mark.parametrize("placed_by", ["user", "app"])
def test_a_replacement_at_a_new_path_keeps_the_old_file_s_placed_by(opened, placed_by):
    """Add as new, use a candidate, out of the not-lossless folder: the new file takes a new path."""
    opened.rows("UPDATE files SET placed_by = ? WHERE song = 1", placed_by)
    new = "Library/House/A - One.flac"
    opened.present.add(new)
    state = opened.snap()
    state["tracks"]["sp1"].update(path=new, status="lossless", source="qobuz", source_id="q9")
    opened.save(state)
    assert opened.rows("SELECT path, placed_by FROM files WHERE song = 1") == [("House/A - One.flac", placed_by)]


def test_a_new_row_for_a_song_keeps_the_old_file_s_placed_by(opened):
    """Two songs trading places: the second can't take the first's row, so it gets a new one."""
    opened.rows("UPDATE files SET placed_by = 'user' WHERE song = 1")
    state = opened.snap()
    one, three = state["tracks"]["sp1"]["path"], state["tracks"]["sp3"]["path"]
    state["tracks"]["sp1"]["path"], state["tracks"]["sp3"]["path"] = three, one
    opened.save(state)
    assert opened.rows("SELECT placed_by FROM files WHERE song = 1") == [("user",)]
    assert opened.rows("SELECT placed_by FROM files WHERE song = 3") == [("app",)]


def test_a_song_without_a_file_gets_one_placed_by_the_app(opened):
    new = "Library/House/B - Two.aiff"
    opened.present.add(new)
    state = opened.snap()
    state["tracks"]["sp2"].update(path=new, status="lossless")
    opened.save(state)
    assert opened.rows("SELECT placed_by FROM files WHERE song = 2") == [("app",)]
