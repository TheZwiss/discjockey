"""library.db's AIFF batches (issue 33 stage B, plan §1.7): batches and their items written and read, outside library
state, and `end_step(item=…)` closing an item in the transaction that ends a step."""
from datetime import datetime

import pytest

from discjockey import db
from discjockey.models import AiffBatchRow, AiffItemRow

NOW = datetime(2026, 11, 8, 12, 0, 0)
LATER = datetime(2026, 11, 8, 12, 5, 0)
ITEMS = [("sp1", "same_track"), ("sp2", "same_track"), ("sp3", "same_track")]


def entry(artist, title, path):
    e = dict.fromkeys(db.ENTRY_KEYS)
    e.update(aliases=[], artist=artist, title=title, folder="House", in_playlists=True, rejected_sources=[],
             path=path, status="lossless")
    return e


def facts(path):
    return db.FileFacts(len(path), 1000, f"key-{path}")


@pytest.fixture
def conn(tmp_path):
    library = tmp_path / "music" / "Library"
    library.mkdir(parents=True)
    path = tmp_path / "library.db"
    db.create(path, {"tracks": {"sp1": entry("A", "One", "Library/House/A - One.aiff")}}, library=library,
              facts=facts, now=NOW)
    conn = db.connect(path)
    conn.library = library
    yield conn
    conn.close()


def states(conn, batch):
    return [(i.seq, i.track, i.state) for i in db.aiff_batch(conn, batch).items]


# --- writes and reads ---

def test_a_batch_records_every_item_planned_in_order_and_starts_running(conn):
    batch = db.start_aiff_batch(conn, "upgrade", "user", "3 selected", ITEMS, NOW)
    row = db.aiff_batch(conn, batch)
    assert row == AiffBatchRow(id=batch, kind="upgrade", started_by="user", scope="3 selected",
                               started="2026-11-08T12:00:00", ended=None, state="running", stop_reason=None,
                               backup=None, counts={"planned": 3, "done": 0, "skipped": 0, "failed": 0, "undone": 0},
                               items=tuple(AiffItemRow(i, t, a, "planned", None, None)
                                           for i, (t, a) in enumerate(ITEMS)))
    assert db.running_aiff_batches(conn) == [batch]


def test_an_unknown_kind_starter_or_action_writes_nothing(conn):
    for args in (("move", "user", None, ITEMS), ("upgrade", "robot", None, ITEMS),
                 ("upgrade", "user", None, [("sp1", "same_track"), ("sp2", "explode")])):
        with pytest.raises(ValueError):
            db.start_aiff_batch(conn, *args, NOW)
    assert db.aiff_batches(conn) == ([], 0)
    assert conn.execute("SELECT COUNT(*) FROM aiff_items").fetchone()[0] == 0


def test_an_empty_batch_is_allowed_and_a_missing_one_is_none(conn):
    batch = db.start_aiff_batch(conn, "mixed", "make_aiff", None, [], NOW)
    assert db.aiff_batch(conn, batch).items == () and db.aiff_batch(conn, batch + 1) is None


def test_items_take_their_state_reason_and_result_and_counts_follow(conn):
    batch = db.start_aiff_batch(conn, "upgrade", "upgrade_all", None, ITEMS, NOW)
    db.set_aiff_item(conn, batch, 0, "done", None, {"path": "Library/House/A - One.aiff", "kept": ["title"]})
    db.set_aiff_item(conn, batch, 1, "skipped", "cloud")
    db.set_aiff_item(conn, batch, 2, "failed", "The drive is full.", "words as a result")
    row = db.aiff_batch(conn, batch)
    assert row.counts == {"planned": 0, "done": 1, "skipped": 1, "failed": 1, "undone": 0}
    assert [(i.state, i.reason, i.result) for i in row.items] == [
        ("done", None, {"path": "Library/House/A - One.aiff", "kept": ["title"]}),
        ("skipped", "cloud", None), ("failed", "The drive is full.", "words as a result")]
    db.set_aiff_item(conn, batch, 0, "undone")
    assert db.aiff_batch(conn, batch).counts["undone"] == 1


def test_a_bad_state_or_a_missing_item_is_a_value_error_and_changes_nothing(conn):
    batch = db.start_aiff_batch(conn, "upgrade", "user", None, ITEMS, NOW)
    for args in ((batch, 0, "sleeping"), (batch, 9, "done"), (batch + 1, 0, "done")):
        with pytest.raises(ValueError):
            db.set_aiff_item(conn, *args)
    assert states(conn, batch) == [(0, "sp1", "planned"), (1, "sp2", "planned"), (2, "sp3", "planned")]


def test_a_batch_stops_with_its_reason_keeps_its_backup_and_ends(conn):
    batch = db.start_aiff_batch(conn, "upgrade", "user", None, ITEMS, NOW)
    db.set_aiff_batch(conn, batch, state="stopped", stop_reason="rekordbox_open", backup="20261108T120100Z")
    row = db.aiff_batch(conn, batch)
    assert (row.state, row.stop_reason, row.backup, row.ended) == ("stopped", "rekordbox_open", "20261108T120100Z", None)
    assert db.running_aiff_batches(conn) == []
    db.set_aiff_batch(conn, batch, state="running")  # Resume: the reason clears, the backup stays
    row = db.aiff_batch(conn, batch)
    assert (row.state, row.stop_reason, row.backup) == ("running", None, "20261108T120100Z")
    db.set_aiff_batch(conn, batch, state="done", ended=LATER)
    row = db.aiff_batch(conn, batch)
    assert (row.state, row.ended, row.backup) == ("done", "2026-11-08T12:05:00", "20261108T120100Z")


def test_a_bad_batch_state_or_reason_or_id_is_a_value_error(conn):
    batch = db.start_aiff_batch(conn, "upgrade", "user", None, ITEMS, NOW)
    for kw in ({"state": "paused"}, {"state": "stopped", "stop_reason": "bored"}):
        with pytest.raises(ValueError):
            db.set_aiff_batch(conn, batch, **kw)
    with pytest.raises(ValueError):
        db.set_aiff_batch(conn, batch + 1, state="done")
    assert db.aiff_batch(conn, batch).state == "running"


def test_the_listing_is_newest_first_with_counts_and_no_items(conn):
    first = db.start_aiff_batch(conn, "upgrade", "user", None, ITEMS, NOW)
    second = db.start_aiff_batch(conn, "convert", "make_aiff", "House", ITEMS[:1], LATER)
    db.set_aiff_item(conn, first, 0, "done")
    rows, total = db.aiff_batches(conn)
    assert [r.id for r in rows] == [second, first] and total == 2
    assert all(r.items == () for r in rows)
    assert rows[1].counts["done"] == 1 and rows[1].counts["planned"] == 2
    assert [r.id for r in db.aiff_batches(conn, limit=1)[0]] == [second]
    assert db.aiff_batches(conn, limit=1)[1] == 2


def test_deleting_a_batch_takes_its_items_with_it(conn):
    batch = db.start_aiff_batch(conn, "upgrade", "user", None, ITEMS, NOW)
    conn.execute("DELETE FROM aiff_batches WHERE id = ?", (batch,))
    assert conn.execute("SELECT COUNT(*) FROM aiff_items").fetchone()[0] == 0


def test_the_database_itself_refuses_values_the_queries_would(conn):
    batch = db.start_aiff_batch(conn, "upgrade", "user", None, ITEMS, NOW)
    for sql in ("UPDATE aiff_batches SET state = 'paused'", "UPDATE aiff_batches SET stop_reason = 'bored'",
                "UPDATE aiff_items SET state = 'sleeping'", "UPDATE aiff_items SET action = 'explode'",
                f"INSERT INTO aiff_items (batch, seq, track, action, state) VALUES ({batch + 5}, 0, 'x', 'convert', 'planned')"):
        with pytest.raises(Exception, match="CHECK|FOREIGN KEY"):
            conn.execute(sql)


# --- outside library state ---

def test_batches_never_bump_the_generation_or_enter_the_snapshot(conn):
    before = (conn.execute("SELECT value FROM meta WHERE key = 'generation'").fetchone(),
              db.snapshot(conn, conn.library))
    batch = db.start_aiff_batch(conn, "upgrade", "user", None, ITEMS, NOW)
    db.set_aiff_item(conn, batch, 0, "done", None, {"a": 1})
    db.set_aiff_batch(conn, batch, state="done", ended=LATER)
    after = (conn.execute("SELECT value FROM meta WHERE key = 'generation'").fetchone(),
             db.snapshot(conn, conn.library))
    assert after == before


# --- end_step closes the item with the step ---

def journal(conn):
    op = {"kind": db.STEP, "track_id": "sp1", "entry": None}
    db.journal_step(conn, op, db._generation(conn))
    return op["op_id"]


def end(conn, op_id, **kw):
    return db.end_step(conn, op_id, {}, library=conn.library, facts=facts, now=LATER, **kw)


def test_end_step_marks_the_item_done_in_the_transaction_that_ends_the_step(conn):
    batch = db.start_aiff_batch(conn, "upgrade", "user", None, ITEMS, NOW)
    op_id = journal(conn)
    end(conn, op_id, item=(batch, 1, {"rekordbox": {"entries": ["7"], "kept": []}}))
    assert states(conn, batch) == [(0, "sp1", "planned"), (1, "sp2", "done"), (2, "sp3", "planned")]
    assert db.aiff_batch(conn, batch).items[1].result == {"rekordbox": {"entries": ["7"], "kept": []}}
    assert db.pending_ops(conn) == []


def test_end_step_without_an_item_touches_no_batch(conn):
    batch = db.start_aiff_batch(conn, "upgrade", "user", None, ITEMS, NOW)
    end(conn, journal(conn))
    assert [s for _, _, s in states(conn, batch)] == ["planned"] * 3


def test_an_item_that_is_not_there_leaves_the_step_unended_and_nothing_written(conn):
    batch = db.start_aiff_batch(conn, "upgrade", "user", None, ITEMS, NOW)
    op_id = journal(conn)
    generation = db._generation(conn)
    with pytest.raises(ValueError):
        end(conn, op_id, item=(batch, 9, None))
    assert [o["op_id"] for o in db.pending_ops(conn)] == [op_id] and db._generation(conn) == generation
    assert [s for _, _, s in states(conn, batch)] == ["planned"] * 3


def test_a_failure_while_ending_the_step_leaves_the_item_planned(conn, monkeypatch):
    batch = db.start_aiff_batch(conn, "upgrade", "user", None, ITEMS, NOW)
    op_id = journal(conn)

    def failing(*a, **k):
        raise RuntimeError("disk")
    monkeypatch.setattr(db, "_bump", failing)  # the last statement of end_step, after the item was written
    with pytest.raises(RuntimeError):
        end(conn, op_id, item=(batch, 0, None))
    monkeypatch.undo()
    assert [s for _, _, s in states(conn, batch)] == ["planned"] * 3
    assert [o["op_id"] for o in db.pending_ops(conn)] == [op_id]
