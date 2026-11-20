"""library.db's stage 5 tables: the playlists' read records, Favourites and crate visibility (plan library stage 5,
B1.2, B1.3; D1, D2, D15, I2). Never library state: no generation bump, never in the snapshot."""
import sqlite3
import threading
import time
import json
from datetime import datetime, timedelta

import pytest

from discjockey import db
from discjockey.models import (FetchedPlaylist, PlaylistInfo, PlaylistLine, PlaylistRecord, RecordedTrack, SourceTrack,
                               StoredRead)

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


def info(name, ref_id=BOUNCE):
    return PlaylistInfo("spotify", ref_id, name, "owner1", "Example Owner", False, "https://img.example/c.jpg", 12, True,
                        True)


def sync_read(reads, started=NOW, unread=(), lines=None):
    """A good sync read of `reads`; its lines are the reads' own unless `lines` says more (lines left out or unread)."""
    return StoredRead("sync", started, list(reads), lines if lines is not None else [fp.line for fp in reads],
                      list(unread))


def check_read(fp, started=NOW):
    return StoredRead("check", started, [fp])


def record(path, reads, now=NOW, keep=(BOUNCE, WARMUP)):
    with db.connect(path) as conn:
        return db.store_read(conn, sync_read(reads, now), keep, now=now)


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


def test_a_save_keeps_a_stored_key_that_is_absent_and_gone_in_its_place(path):
    resolving = {"a", "b", "c"}
    with db.connect(path) as conn:
        db.set_favourites(conn, ["gone0", "a", "gone1", "b", "gone2", "gone3", "c"])
        # "a" resolves and was left out: the user removed it. A gone key follows the nearest stored key before it
        # that is in the new list (the first leads); the users order of the rest is theirs
        db.set_favourites(conn, ["c", "b"], resolving)
        assert db.favourites(conn) == ["gone0", "gone1", "c", "b", "gone2", "gone3"]
        db.set_favourites(conn, ["b"], resolving)
        assert db.favourites(conn) == ["gone0", "gone1", "b", "gone2", "gone3"]
        db.set_favourites(conn, [], resolving)  # a briefly empty sidebar wipes none of them
        assert db.favourites(conn) == ["gone0", "gone1", "gone2", "gone3"]
        db.set_favourites(conn, ["gone1"], resolving)  # a key the request names is the user's, wherever it is
        assert db.favourites(conn) == ["gone0", "gone1", "gone2", "gone3"]
        db.set_favourites(conn, [])  # without `resolving` a set replaces everything
        assert db.favourites(conn) == []


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


def test_several_crate_switches_are_saved_all_or_none(path):
    one, two = "/Volumes/Example/Crates/One", "/Volumes/Example/Crates/Two"
    with db.connect(path) as conn:
        db.set_crates_shown(conn, [one, two], False)
        assert db.crate_overrides(conn) == {one: False, two: False}
        with pytest.raises(sqlite3.Error):
            db.set_crates_shown(conn, [one, object()], True)  # the second can't be stored: the first is not kept either
        assert db.crate_overrides(conn) == {one: False, two: False}
        db.set_crates_shown(conn, [one, two], None)
        assert db.crate_overrides(conn) == {}


# --- B1.2, B1.3: never library state, and a held write makes them wait ---

def every_write(conn, now=NOW):
    db.store_read(conn, sync_read([spotify_read(track("t1", "First Song"))], now), [BOUNCE], now=now)
    db.store_infos(conn, {BOUNCE: info("First Name")}, now)
    db.set_favourites(conn, [f"playlist:{BOUNCE}"])
    db.set_crate_shown(conn, "/Volumes/Example/Crates/Old", False)


def written(path):
    with db.connect(path) as conn:
        return (db.playlist_records(conn), db.stored_infos(conn), db.favourites(conn), db.crate_overrides(conn))


def test_no_write_bumps_the_generation_or_shows_in_the_snapshot(path):
    before = generation_and_snapshot(path)
    with db.connect(path) as conn:
        every_write(conn)
        db.set_crate_shown(conn, "/Volumes/Example/Crates/Old", None)
    assert generation_and_snapshot(path) == before


WRITES = {
    "store_read": lambda conn: db.store_read(conn, sync_read([spotify_read(track("t2", "Second Song"))], LATER),
                                             [BOUNCE], now=LATER),
    "store_infos": lambda conn: db.store_infos(conn, {BOUNCE: info("Second Name")}, LATER),
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


# --- issue 39 phase 2 (V2.2a): the stored read ---

def full_track(id="t1"):
    """A track with every fact the planner reads, none of them at its default."""
    return SourceTrack(id, "Full Song", ("Example Artist", "Guest"), "Full Album", "https://img.example/a.jpg", 201000,
                       "USEX00000001", "spotify", "https://open.spotify.com/track/" + id, False, True)


def lines_of(*reads):
    return [fp.line for fp in reads]


def test_a_stored_read_comes_back_whole_and_equal(path):
    one, two = full_track("t1"), SourceTrack("77", "Warm Tune", (), "", None, 0, None, "qobuz")
    reads = [spotify_read(one, track("t2", "Second Song"), one), qobuz_read(two)]
    record(path, reads)
    with db.connect(path) as conn:
        db.store_infos(conn, {BOUNCE: info("Hard Bounce")}, NOW)
        loaded = db.load_read(conn)
    assert loaded.lines == lines_of(*reads) and loaded.unread == [] and loaded.read_at == NOW
    assert [fp.line for fp in loaded.fetched] == lines_of(*reads)
    assert [fp.tracks for fp in loaded.fetched] == [fp.tracks for fp in reads]  # equal, order and repeats kept
    assert loaded.fetched[0].tracks[0].artists == ("Example Artist", "Guest")  # a tuple again
    assert loaded.fetched[1].tracks[0].duration_ms == 0  # a NULL length back as 0
    assert [fp.skipped for fp in loaded.fetched] == [[], []]
    assert loaded.fetched[0].info == info("Hard Bounce") and loaded.fetched[1].info is None
    assert loaded.checked == {BOUNCE: tuple(reads[0].tracks), WARMUP: tuple(reads[1].tracks)}
    assert loaded.infos == {BOUNCE: info("Hard Bounce")}


def test_the_secret_link_token_and_the_label_are_stored_nowhere(path):
    secret = SourceTrack("900", "Private One", ("Example Artist",), "", None, 1000, None, "soundcloud",
                         "https://soundcloud.com/example/private-one/s-s3cr3t", secret_token="s-s3cr3t",
                         record_label="Example Label L")
    read = FetchedPlaylist(PlaylistLine("Private", "example/sets/p", 3, "soundcloud"), [secret], [])
    record(path, [read], keep=[read.line.ref])
    with db.connect(path) as conn:
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
            for row in conn.execute(f"SELECT * FROM {table}"):
                assert not any(isinstance(v, str) and ("s3cr3t" in v or "Example Label L" in v) for v in row), table
        (loaded,) = db.load_read(conn).fetched[0].tracks
    assert loaded.secret() is None and loaded.label is None
    assert loaded.link == "https://w.soundcloud.com/player/?url=https%3A//api.soundcloud.com/tracks/900"  # derived again
    assert loaded == SourceTrack("900", "Private One", ("Example Artist",), "", None, 1000, None, "soundcloud")


def test_an_older_sync_read_stores_nothing_and_answers_the_newer_ones_id(path):
    newer = record(path, [spotify_read(track("t2", "Newer Song"))], LATER)
    older = record(path, [spotify_read(track("t1", "Older Song"))], NOW)  # started earlier, finished later
    assert older == newer
    with db.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM reads").fetchone()[0] == 1
        assert [t.title for t in db.load_read(conn).fetched[0].tracks] == ["Newer Song"]


def test_a_check_read_older_than_a_stored_record_leaves_it_and_a_newer_one_replaces_it(path):
    record(path, [spotify_read(track("t2", "Sync Song"))], LATER)
    with db.connect(path) as conn:
        first = db.store_read(conn, check_read(spotify_read(track("t1", "Check Song")), NOW), None, now=NOW)
        assert db.stored_tracks(conn)[BOUNCE][0].title == "Sync Song"
        assert db.read_head(conn).current == first  # the check read is stored all the same
        db.store_read(conn, check_read(spotify_read(track("t3", "Newer Check")), LATER + timedelta(hours=1)), None)
        assert db.stored_tracks(conn)[BOUNCE][0].title == "Newer Check"
        assert db.load_read(conn).fetched[0].tracks[0].title == "Newer Check"  # the plan reads the records as they are


def test_read_ids_rise_and_a_pruned_one_never_comes_back(path):
    ids = [record(path, [spotify_read(track("t1", f"Song {n}"))], NOW + timedelta(minutes=n)) for n in range(3)]
    assert ids == [1, 2, 3]
    with db.connect(path) as conn:
        assert [r[0] for r in conn.execute("SELECT id FROM reads")] == [3]  # older ones pruned
        assert db.current_read_id(conn) == 3
        assert db.store_read(conn, sync_read([spotify_read()], NOW + timedelta(hours=1)), None, now=NOW) == 4
    assert db.read_label(4) == "read:4" and db.read_number("read:4") == 4
    for bad in ("x", "read:", "read:x", "read:-1", "reads:1", "read:1:2"):
        with pytest.raises(ValueError):
            db.read_number(bad)


def test_prune_keeps_a_read_a_record_still_names_and_a_check_read_does_not_prune(path):
    record(path, [spotify_read(track("t1", "A")), qobuz_read(track("77", "B", service="qobuz"))])
    with db.connect(path) as conn:
        db.store_read(conn, check_read(spotify_read(track("t2", "Check"))), None, now=NOW)  # id 2, older than read 3 below
    record(path, [spotify_read(track("t3", "C"))], LATER)  # replaces the Spotify record only: read 1 names Qobuz's
    with db.connect(path) as conn:
        assert [r[0] for r in conn.execute("SELECT id FROM reads ORDER BY id")] == [1, 3]


def test_a_first_failed_read_has_its_problem_and_no_good_read(path):
    failed = StoredRead("sync", NOW, [], None, [], "offline", "qobuz", "Qobuz can't be reached.")
    with db.connect(path) as conn:
        assert db.read_head(conn) is None
        assert db.store_read(conn, failed, None, now=NOW) == 1
        head = db.read_head(conn)
        assert (head.current, head.sync_id, head.read_at) == (1, None, None)
        assert (head.problem, head.problem_service, head.message) == ("offline", "qobuz", "Qobuz can't be reached.")
        assert db.load_read(conn) is None


def test_a_failed_read_keeps_the_last_good_tracks_and_a_good_one_clears_the_problem(path):
    record(path, [spotify_read(track("t1", "Good Song"))])
    failed = StoredRead("sync", LATER, [], None, [], "offline", "spotify", "No connection.")
    with db.connect(path) as conn:
        db.store_read(conn, failed, None, now=LATER)
        loaded = db.load_read(conn)
        assert [t.title for t in loaded.fetched[0].tracks] == ["Good Song"] and loaded.id == 1
        assert (loaded.problem, loaded.problem_service, loaded.message) == ("offline", "spotify", "No connection.")
        assert db.read_head(conn).sync_id == 1 and db.read_head(conn).current == 2
        db.store_read(conn, sync_read([spotify_read(track("t2", "Next Song"))], LATER + timedelta(hours=1)), None)
        loaded = db.load_read(conn)
        assert loaded.problem is None and loaded.message == "" and loaded.id == 3


def test_clear_read_problem_follows_the_three_cases(path):
    def fail(conn, problem, service, message, hours):
        db.store_read(conn, StoredRead("sync", NOW + timedelta(hours=hours), [], None, [], problem, service, message),
                      None, now=NOW)

    with db.connect(path) as conn:
        assert db.clear_read_problem(conn, "qobuz", None, None) is False  # nothing stored
        fail(conn, "login_expired", "qobuz", "Log in again.", 1)
        assert db.clear_read_problem(conn, "spotify", None, None) is False  # another service
        assert db.clear_read_problem(conn, "qobuz", frozenset({"offline"}), None) is False  # a login can't cure it
        assert db.clear_read_problem(conn, "qobuz", None, "other words") is False  # not this message
        assert db.read_head(conn).problem == "login_expired"
        assert db.clear_read_problem(conn, "qobuz", frozenset({"login_expired"}), "Log in again.") is True
        head = db.read_head(conn)
        assert (head.problem, head.problem_service, head.message) == (None, None, "")
        assert db.clear_read_problem(conn, "qobuz", None, None) is False  # nothing left to clear
        fail(conn, "login_expired", "qobuz", "Log in again.", 2)
        assert db.clear_read_problem(conn, "qobuz", None, None) is True


def test_a_line_switched_off_since_is_not_fetched_though_its_record_stays(path):
    liked_line = PlaylistLine("Liked", "LM", 3, "youtube_music")
    liked = FetchedPlaylist(liked_line, [track("v1", "Liked Song", service="youtube_music")], [])
    spotify = spotify_read(track("t1", "First Song"))
    lines = [spotify.line, liked_line]
    liked_ref = liked_line.ref
    with db.connect(path) as conn:
        db.store_read(conn, sync_read([spotify, liked], NOW, lines=lines), [BOUNCE, liked_ref], now=NOW)
        assert [fp.line.ref for fp in db.load_read(conn).fetched] == [BOUNCE, liked_ref]
        # Settings' choice is off now: the line is read-listed but left out, so it is neither fetched nor unread
        db.store_read(conn, sync_read([spotify], LATER, lines=lines), [BOUNCE, liked_ref], now=LATER)
        loaded = db.load_read(conn)
        assert [fp.line.ref for fp in loaded.fetched] == [BOUNCE] and loaded.unread == []
        assert liked_ref in db.playlist_records(conn)  # the Library page still shows it
        assert liked_ref in loaded.checked


def test_a_paused_line_is_unread_and_a_record_from_schema_11_cannot_be_rebuilt(path):
    spotify, qobuz = spotify_read(track("t1", "First Song")), qobuz_read(track("77", "Warm", service="qobuz"))
    record(path, [spotify, qobuz])
    with db.connect(path) as conn:
        conn.execute("UPDATE playlist_tracks SET id = NULL, artists = NULL WHERE playlist = ?", (WARMUP,))
        loaded = db.load_read(conn)
        assert [fp.line.ref for fp in loaded.fetched] == [BOUNCE] and loaded.unread == [WARMUP]
        assert WARMUP not in loaded.checked and WARMUP not in db.stored_tracks(conn)
        assert WARMUP in db.playlist_records(conn)  # the Library page answers from the old columns
        db.store_read(conn, sync_read([spotify], LATER, unread=[WARMUP], lines=lines_of(spotify, qobuz)), None,
                      now=LATER)
        assert db.load_read(conn).unread == [WARMUP]  # named once, not twice


def test_a_sync_read_drops_what_keep_leaves_out_and_a_check_read_never_prunes(path):
    record(path, [spotify_read(track("t1", "First Song")), qobuz_read(track("77", "Warm", service="qobuz"))])
    with db.connect(path) as conn:
        db.store_infos(conn, {BOUNCE: info("Hard Bounce"), WARMUP: info("Warm Up", "4242")}, NOW)
        db.store_read(conn, check_read(spotify_read(track("t2", "Pasted")), LATER), None, now=LATER)  # no keep
        assert set(db.stored_tracks(conn)) == {BOUNCE, WARMUP}
        db.store_read(conn, sync_read([spotify_read(track("t3", "Third"))], LATER + timedelta(hours=1)), [BOUNCE],
                      now=LATER)
        assert set(db.stored_tracks(conn)) == {BOUNCE} and set(db.stored_infos(conn)) == {BOUNCE}
        assert conn.execute("SELECT COUNT(*) FROM playlist_tracks WHERE playlist = ?", (WARMUP,)).fetchone()[0] == 0


def test_infos_are_replaced_by_ref_and_the_others_stay(path):
    with db.connect(path) as conn:
        db.store_infos(conn, {BOUNCE: info("One"), WARMUP: info("Two", "4242")}, NOW)
        db.store_infos(conn, {BOUNCE: info("One again")}, LATER)
        assert {ref: i.name for ref, i in db.stored_infos(conn).items()} == {BOUNCE: "One again", WARMUP: "Two"}
        assert db.current_read_id(conn) is None  # no read id change


def test_the_stored_read_json_is_what_the_plan_needs(path):
    spotify = spotify_read(track("t1", "First Song"))
    record(path, [spotify])
    with db.connect(path) as conn:
        lines, unread, refs = conn.execute("SELECT lines, unread, read_refs FROM reads").fetchone()
    assert json.loads(lines) == [{"folder": "Hard_Bounce", "playlist_id": BOUNCE, "line_no": 1, "service": "spotify"}]
    assert json.loads(unread) == [] and json.loads(refs) == [BOUNCE]
