"""library.db's stage 5 tables: the playlists' read records, Favourites and crate visibility (plan library stage 5,
B1.2, B1.3; D1, D2, D15, I2). Never library state: no generation bump, never in the snapshot."""
import sqlite3
import threading
import time
from datetime import datetime

import pytest

from discjockey import db
from discjockey.models import FetchedPlaylist, PlaylistLine, PlaylistRecord, RecordedTrack, SourceTrack

NOW = datetime(2026, 10, 30, 9, 15, 0)
LATER = datetime(2026, 10, 31, 18, 40, 5)
BOUNCE = "0DiscjockeyExampleList"  # a Spotify ref is the bare id
WARMUP = "qobuz:4242"


@pytest.fixture
def path(tmp_path):
    library = tmp_path / "music" / "Library"
    library.mkdir(parents=True)
    p = tmp_path / "library.db"
    db.create(p, {"tracks": {}}, library=library, facts=lambda path: None, now=NOW)
    return p


def track(id, title, artists=("Example Artist",), duration_ms=180000, service="spotify"):
    return SourceTrack(id, title, artists, "Example Album", None, duration_ms, None, service)


def spotify_read(*tracks):
    return FetchedPlaylist(PlaylistLine("Hard_Bounce", BOUNCE, 1), list(tracks), [])


def qobuz_read(*tracks):
    return FetchedPlaylist(PlaylistLine("Warm_Up", "4242", 2, "qobuz"), list(tracks), [])


def record(path, reads, now=NOW, keep=(BOUNCE, WARMUP)):
    with db.connect(path) as conn:
        db.record_reads(conn, reads, now, keep)


def records(path):
    with db.connect(path) as conn:
        return db.playlist_records(conn)


def generation_and_snapshot(path):
    with db.connect(path) as conn:
        return conn.execute("SELECT value FROM meta WHERE key = 'generation'").fetchone()[0], db.snapshot(
            conn, path.parent / "music" / "Library")


# --- B1.2 the read records ---

def test_a_read_records_its_tracks_in_playlist_order_with_their_tokens_and_display_facts(path):
    record(path, [
        spotify_read(track("t1", "First Song", ("Example Artist", "Guest")), track("t2", "Second Song"),
                     track("t1", "First Song", ("Example Artist", "Guest"))),  # listed twice: two positions
        qobuz_read(track("77", "Warm Tune", ("Other Artist",), 0, "qobuz")),
    ])
    assert records(path) == {
        BOUNCE: PlaylistRecord("spotify", "2026-10-30T09:15:00", (
            RecordedTrack(1, "t1", "Example Artist", "First Song", 180000),
            RecordedTrack(2, "t2", "Example Artist", "Second Song", 180000),
            RecordedTrack(3, "t1", "Example Artist", "First Song", 180000))),
        WARMUP: PlaylistRecord("qobuz", "2026-10-30T09:15:00", (
            RecordedTrack(1, "qobuz:77", "Other Artist", "Warm Tune", None),)),  # no length known: None
    }


def test_a_later_read_replaces_the_record(path):
    record(path, [spotify_read(track("t1", "First Song"), track("t2", "Second Song"), track("t3", "Third Song"))])
    record(path, [spotify_read(track("t3", "Third Song"), track("t1", "First Song"))], LATER)
    assert records(path) == {BOUNCE: PlaylistRecord("spotify", "2026-10-31T18:40:05", (
        RecordedTrack(1, "t3", "Example Artist", "Third Song", 180000),
        RecordedTrack(2, "t1", "Example Artist", "First Song", 180000)))}


def test_a_playlist_read_empty_is_recorded_empty(path):
    record(path, [spotify_read(track("t1", "First Song"))])
    record(path, [spotify_read()], LATER)
    assert records(path) == {BOUNCE: PlaylistRecord("spotify", "2026-10-31T18:40:05", ())}


def test_a_playlist_not_read_this_time_keeps_its_record(path):
    """An unreadable playlist, or one switched off: the read has no entry for it, its line is still there."""
    record(path, [spotify_read(track("t1", "First Song")), qobuz_read(track("77", "Warm Tune", service="qobuz"))])
    before = records(path)[WARMUP]
    record(path, [spotify_read(track("t2", "Second Song"))], LATER)
    after = records(path)
    assert after[WARMUP] == before
    assert after[BOUNCE].read_at == "2026-10-31T18:40:05"


def test_records_of_playlists_no_longer_in_playlists_txt_are_dropped_with_their_tracks(path):
    record(path, [spotify_read(track("t1", "First Song")), qobuz_read(track("77", "Warm Tune", service="qobuz"))])
    record(path, [spotify_read(track("t1", "First Song"))], LATER, keep=[BOUNCE])
    assert list(records(path)) == [BOUNCE]
    with db.connect(path) as conn:
        assert conn.execute("SELECT DISTINCT playlist FROM playlist_tracks").fetchall() == [(BOUNCE,)]
    record(path, [], LATER, keep=[])  # every line gone
    assert records(path) == {}
    with db.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM playlist_tracks").fetchone()[0] == 0


def test_recording_is_all_or_nothing(path):
    record(path, [spotify_read(track("t1", "First Song")), qobuz_read(track("77", "Warm Tune", service="qobuz"))])
    before = records(path)
    broken = qobuz_read(track("78", None, service="qobuz"))  # a title the table refuses (NOT NULL)
    with pytest.raises(sqlite3.IntegrityError):
        record(path, [spotify_read(track("t9", "New Song")), broken], LATER, keep=[WARMUP])
    assert records(path) == before


# --- B1.3 Favourites and crate visibility ---

def test_favourites_keep_the_users_order_and_a_set_replaces_them(path):
    with db.connect(path) as conn:
        assert db.favourites(conn) == []
        db.set_favourites(conn, ["playlist:qobuz:4242", "folder:Library/Old_Hardstyle", f"playlist:{BOUNCE}"])
        assert db.favourites(conn) == ["playlist:qobuz:4242", "folder:Library/Old_Hardstyle", f"playlist:{BOUNCE}"]
        db.set_favourites(conn, [f"playlist:{BOUNCE}", "playlist:qobuz:4242"])
        assert db.favourites(conn) == [f"playlist:{BOUNCE}", "playlist:qobuz:4242"]
        db.set_favourites(conn, [])
        assert db.favourites(conn) == []


def test_a_favourite_given_twice_keeps_its_first_place(path):
    with db.connect(path) as conn:
        db.set_favourites(conn, ["folder:/Volumes/Example/Crates/Old", f"playlist:{BOUNCE}",
                                 "folder:/Volumes/Example/Crates/Old"])
        assert db.favourites(conn) == ["folder:/Volumes/Example/Crates/Old", f"playlist:{BOUNCE}"]


def test_a_crate_switch_is_kept_until_it_is_removed(path):
    old, new = "/Volumes/Example/Crates/Old", "/Volumes/Example/Crates/New"
    with db.connect(path) as conn:
        assert db.crate_overrides(conn) == {}
        db.set_crate_shown(conn, old, False)
        db.set_crate_shown(conn, new, True)
        assert db.crate_overrides(conn) == {old: False, new: True}
        db.set_crate_shown(conn, old, True)
        assert db.crate_overrides(conn) == {old: True, new: True}
        db.set_crate_shown(conn, new, None)  # back to the default
        db.set_crate_shown(conn, "/Volumes/Example/Crates/Never", None)  # nothing to remove: no change
        assert db.crate_overrides(conn) == {old: True}


# --- B1.2, B1.3: never library state, and a held write makes them wait ---

def every_write(conn, now=NOW):
    db.record_reads(conn, [spotify_read(track("t1", "First Song"))], now, [BOUNCE])
    db.set_favourites(conn, [f"playlist:{BOUNCE}"])
    db.set_crate_shown(conn, "/Volumes/Example/Crates/Old", False)


def written(path):
    with db.connect(path) as conn:
        return db.playlist_records(conn), db.favourites(conn), db.crate_overrides(conn)


def test_no_write_bumps_the_generation_or_shows_in_the_snapshot(path):
    before = generation_and_snapshot(path)
    with db.connect(path) as conn:
        every_write(conn)
        db.set_crate_shown(conn, "/Volumes/Example/Crates/Old", None)
    assert generation_and_snapshot(path) == before


WRITES = {
    "record_reads": lambda conn: db.record_reads(conn, [spotify_read(track("t2", "Second Song"))], LATER, [BOUNCE]),
    "set_favourites": lambda conn: db.set_favourites(conn, ["folder:Library/Old_Hardstyle"]),
    "set_crate_shown": lambda conn: db.set_crate_shown(conn, "/Volumes/Example/Crates/Old", True),
}


def holder(path):
    """Another connection (a running job's) holding the write lock."""
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    conn.execute("BEGIN IMMEDIATE")
    return conn


@pytest.mark.parametrize("name", WRITES)
def test_a_write_waits_for_another_connections_write_transaction(path, name):
    with db.connect(path) as conn:
        every_write(conn)
    before = written(path)
    other = holder(path)
    release = threading.Timer(0.3, other.execute, ("COMMIT",))
    start = time.monotonic()
    release.start()
    try:
        with db.connect(path) as conn:  # the binding 5 s wait
            WRITES[name](conn)
    finally:
        release.join()
        other.close()
    assert time.monotonic() - start >= 0.25
    assert written(path) != before  # it waited, then wrote


@pytest.mark.parametrize("name", WRITES)
def test_a_write_still_held_up_after_the_wait_fails_cleanly(path, name):
    with db.connect(path) as conn:
        every_write(conn)
    before = written(path)
    other = holder(path)
    try:
        with db.connect(path) as conn:
            conn.execute("PRAGMA busy_timeout = 50")  # the binding 5 s, shortened for the test
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                WRITES[name](conn)
            assert not conn.in_transaction
    finally:
        other.execute("ROLLBACK")
        other.close()
    assert written(path) == before
