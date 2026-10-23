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
    with pytest.raises(ValueError, match="belongs to both"):
        db.create(tmp_path / "library.db", state, library=library, facts=no_facts, now=NOW)


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


def test_snapshot_follows_a_moved_music_folder(tmp_path, library):
    path = fresh(tmp_path, library, {"tracks": {"sp1": entry("A", "One", "Library/House/A - One.aiff")}})
    moved = tmp_path / "Volumes" / "New" / "Library"
    with db.connect(path) as conn:
        snap = db.snapshot(conn, moved)
        assert conn.execute("SELECT path FROM watched_folders").fetchone()[0] == moved.as_posix()
    assert snap["tracks"]["sp1"]["path"] == "Library/House/A - One.aiff"


def test_an_empty_database_has_the_default_records(tmp_path, library):
    with db.connect(fresh(tmp_path, library)) as conn:
        snap = db.snapshot(conn, library)
    assert snap == {"version": 2, "tracks": {}, "pending": [], "never": {},
                    "qobuz_usage": {"days": {}, "signals": []}, "ambiguous": {}, "files": []}
