"""library.db's move log: batches and their moves, written and read (plan library stage 2, group 1)."""
import json
from datetime import datetime

import pytest

from discjockey import db
from discjockey.models import BatchRow, MoveRow, PlannedMove

NOW = datetime(2026, 10, 24, 12, 0, 0)
LATER = datetime(2026, 10, 24, 12, 5, 0)
ONE = "Library/Old/A - One.aiff"
TWO = "Library/Old/B - Two.aiff"
THREE = "Library/Old2/C - Three.aiff"
LOOSE = "Old/sub/Loose.aiff"  # an unlinked row (a file the user put there)


def entry(artist, title, path):
    e = dict.fromkeys(db.ENTRY_KEYS)
    e.update(aliases=[], artist=artist, title=title, folder="Old", in_playlists=True, rejected_sources=[],
             path=path, status="lossless")
    return e


def facts(path):
    return db.FileFacts(len(path), 1000, f"key-{path}")


@pytest.fixture
def log(tmp_path):
    library = tmp_path / "music" / "Library"
    library.mkdir(parents=True)
    path = tmp_path / "library.db"
    db.create(path, {"tracks": {"sp1": entry("A", "One", ONE), "sp2": entry("B", "Two", TWO),
                                "sp3": entry("C", "Three", THREE)}}, library=library, facts=facts, now=NOW)

    class Log:
        def __init__(self):
            self.path, self.library = path, library
            self.conn = db.connect(path)
            self.conn.execute("INSERT INTO files (folder, path, content_key, placed_by, first_seen, last_seen) "
                              "VALUES (1, ?, 'key-loose', 'import', 'x', 'x')", (LOOSE,))
            self.ids = dict(self.rows("SELECT s.key, f.id FROM files f JOIN songs s ON s.id = f.song"))

        def rows(self, sql, *args):
            return self.conn.execute(sql, args).fetchall()

        def place(self, file_id):
            return self.conn.execute("SELECT path, placed_by FROM files WHERE id = ?", (file_id,)).fetchone()

        def file_move(self, key, src, dst, **kw):
            return PlannedMove(kind="file", file_id=self.ids[key], label=key, src=src, dst=dst,
                               content_key=f"key-{src}", placed_before="app", placed_after="app", **kw)

        def batch(self, moves, started_by="tidy", **kw):
            kw.setdefault("about", None)
            kw.setdefault("undoes", None)
            return db.start_batch(self.conn, started_by=started_by, moves=moves, now=NOW, **kw)

        def move_ids(self, batch):
            return [m.id for m in db.batch_moves(self.conn, batch)]

    log = Log()
    yield log
    log.conn.close()


def folder_move(src="Library/Old", dst="Library/New"):
    return PlannedMove(kind="folder", file_id=None, label=src.split("/")[-1], src=src, dst=dst, content_key=None,
                       placed_before=None, placed_after=None)


# --- 1.2 writes ---

def test_a_batch_records_planned_and_pre_skipped_moves_in_order(log):
    moves = [log.file_move("sp1", ONE, "Library/New/A - One.aiff"),
             log.file_move("sp2", TWO, "Library/New/B - Two.aiff", skip=("name_taken", None)),
             log.file_move("sp3", THREE, "Library/New/C - Three.aiff", skip=("failed", "the drive is full"))]
    batch = log.batch(moves)
    assert log.rows("SELECT started, finished, started_by, about, undoes FROM move_batches") == [
        ("2026-10-24T12:00:00", None, "tidy", None, None)]
    rows = db.batch_moves(log.conn, batch)
    assert [(m.seq, m.state, m.reason, m.detail) for m in rows] == [
        (0, "planned", None, None), (1, "skipped", "name_taken", None), (2, "skipped", "failed", "the drive is full")]
    first = rows[0]
    assert first == MoveRow(id=first.id, batch=batch, seq=0, kind="file", file_id=log.ids["sp1"], label="sp1", src=ONE,
                            dst="Library/New/A - One.aiff", content_key=f"key-{ONE}", placed_before="app",
                            placed_after="app", state="planned", reason=None, detail=None, now_path=ONE,
                            now_key=f"key-{ONE}")
    assert db.open_batches(log.conn) == [batch]


def test_a_rename_batch_keeps_what_it_renamed(log):
    batch = log.batch([folder_move()], started_by="rename", about={"from": "Old", "to": "New"})
    assert json.loads(log.rows("SELECT about FROM move_batches WHERE id = ?", batch)[0][0]) == {"from": "Old",
                                                                                                  "to": "New"}
    undo = log.batch([], started_by="undo", undoes=batch)
    assert log.rows("SELECT undoes FROM move_batches WHERE id = ?", undo) == [(batch,)]


@pytest.mark.parametrize("move", [
    PlannedMove("file", 1, "x", "/elsewhere/A - One.aiff", "Library/New/A - One.aiff", None, "app", "app"),
    PlannedMove("file", 1, "x", ONE, "Library/New/A - One (2).aiff", None, "app", "app"),  # would rename the file
    PlannedMove("file", 1, "x", ONE, "Library/New/A - One.aiff", None, "app", "app", skip=("gone", None)),
])
def test_a_bad_move_is_refused_and_nothing_is_written(log, move):
    with pytest.raises(ValueError):
        log.batch([log.file_move("sp2", TWO, "Library/New/B - Two.aiff"), move])
    assert log.rows("SELECT COUNT(*) FROM move_batches") == [(0,)]
    assert log.rows("SELECT COUNT(*) FROM moves") == [(0,)]


def test_an_unknown_kind_of_batch_is_refused(log):
    with pytest.raises(ValueError):
        log.batch([log.file_move("sp1", ONE, "Library/New/A - One.aiff")], started_by="sync")
    assert log.rows("SELECT COUNT(*) FROM move_batches") == [(0,)]


def test_an_undo_can_skip_a_folder_rename_whose_playlist_was_renamed_again(log):
    batch = log.batch([PlannedMove("folder", None, "New", "Library/New", "Library/Old", None, None, None,
                                   skip=("playlist_renamed", None))], started_by="undo")
    assert db.batch_moves(log.conn, batch)[0].reason == "playlist_renamed"


def test_paths_are_stored_nfc(log):
    batch = log.batch([log.file_move("sp1", ONE, "Library/Ne\u0301w/A - One.aiff")])
    assert db.batch_moves(log.conn, batch)[0].dst == "Library/N\u00e9w/A - One.aiff"


def test_finish_move_moves_the_row_and_sets_placed_by(log):
    move = PlannedMove("file", log.ids["sp1"], "A - One", ONE, "Library/New/A - One.aiff", f"key-{ONE}", "user",
                       "app")
    log.conn.execute("UPDATE files SET placed_by = 'user' WHERE id = ?", (log.ids["sp1"],))
    batch = log.batch([move])
    db.finish_move(log.conn, log.move_ids(batch)[0])
    assert log.place(log.ids["sp1"]) == ("New/A - One.aiff", "app")
    assert db.batch_moves(log.conn, batch)[0].state == "done"
    snap = db.snapshot(log.conn, log.library)["tracks"]["sp1"]
    assert (snap["path"], snap["placed_by"], snap["file_id"]) == ("Library/New/A - One.aiff", "app", log.ids["sp1"])


def test_finish_move_is_idempotent_when_the_save_already_wrote_the_path(log):
    batch = log.batch([log.file_move("sp1", ONE, "Library/New/A - One.aiff")])
    log.conn.execute("UPDATE files SET path = 'New/A - One.aiff', placed_by = 'user' WHERE id = ?", (log.ids["sp1"],))
    move = log.move_ids(batch)[0]
    db.finish_move(log.conn, move)
    db.finish_move(log.conn, move)
    assert log.place(log.ids["sp1"]) == ("New/A - One.aiff", "app")
    assert log.rows("SELECT COUNT(*) FROM files") == [(4,)]


def test_an_unlinked_row_left_at_the_target_gives_way(log):
    log.conn.execute("INSERT INTO files (folder, path, placed_by, first_seen, last_seen) "
                     "VALUES (1, 'New/A - One.aiff', 'import', 'x', 'x')")
    batch = log.batch([log.file_move("sp1", ONE, "Library/New/A - One.aiff")])
    db.finish_move(log.conn, log.move_ids(batch)[0])
    assert log.rows("SELECT id FROM files WHERE path = 'New/A - One.aiff'") == [(log.ids["sp1"],)]


def test_finishing_a_move_whose_file_row_is_gone_only_marks_it_done(log):
    batch = log.batch([log.file_move("sp1", ONE, "Library/New/A - One.aiff")])
    log.conn.execute("DELETE FROM files WHERE id = ?", (log.ids["sp1"],))
    before = log.rows("SELECT * FROM files ORDER BY id")
    db.finish_move(log.conn, log.move_ids(batch)[0])
    (m,) = db.batch_moves(log.conn, batch)
    assert (m.state, m.file_id, m.now_path, m.label) == ("done", None, None, "sp1")
    assert log.rows("SELECT * FROM files ORDER BY id") == before


def test_a_folder_move_rewrites_the_prefix_of_linked_and_unlinked_rows(log):
    # sp2 was moved by the save already (run_op applies its entry): its row is unaffected
    log.conn.execute("UPDATE files SET path = 'New/B - Two.aiff' WHERE id = ?", (log.ids["sp2"],))
    log.conn.execute("UPDATE files SET placed_by = 'user' WHERE id = ?", (log.ids["sp1"],))
    batch = log.batch([folder_move()], started_by="rename", about={"from": "Old", "to": "New"})
    db.finish_move(log.conn, log.move_ids(batch)[0])
    assert dict(log.rows("SELECT path, placed_by FROM files")) == {
        "New/A - One.aiff": "user", "New/B - Two.aiff": "app", "New/sub/Loose.aiff": "import",
        "Old2/C - Three.aiff": "app"}  # Old2/ isn't under Old/


def test_a_folder_move_with_unicode_names_rewrites_by_characters(log):
    log.conn.execute("UPDATE files SET path = 'Thr\u00e9e/A - One.aiff' WHERE id = ?", (log.ids["sp1"],))
    batch = log.batch([folder_move("Library/Thre\u0301e", "Library/Fo\u0308r")])  # decomposed, as the page may send
    db.finish_move(log.conn, log.move_ids(batch)[0])
    assert log.place(log.ids["sp1"])[0] == "F\u00f6r/A - One.aiff"


def test_skip_move_records_the_reason(log):
    batch = log.batch([log.file_move("sp1", ONE, "Library/New/A - One.aiff"),
                       log.file_move("sp2", TWO, "Library/New/B - Two.aiff")])
    first, second = log.move_ids(batch)
    db.skip_move(log.conn, first, "failed", "the drive is read-only")
    db.skip_move(log.conn, second, "changed")
    assert [(m.state, m.reason, m.detail) for m in db.batch_moves(log.conn, batch)] == [
        ("skipped", "failed", "the drive is read-only"), ("skipped", "changed", None)]
    assert log.place(log.ids["sp1"]) == ("Old/A - One.aiff", "app")


def test_a_done_move_isnt_skipped_and_a_skipped_one_isnt_finished(log):
    batch = log.batch([log.file_move("sp1", ONE, "Library/New/A - One.aiff"),
                       log.file_move("sp2", TWO, "Library/New/B - Two.aiff", skip=("offline", None))])
    first, second = log.move_ids(batch)
    db.finish_move(log.conn, first)
    with pytest.raises(ValueError):
        db.skip_move(log.conn, first, "failed")
    with pytest.raises(ValueError):
        db.finish_move(log.conn, second)
    with pytest.raises(ValueError):
        db.skip_move(log.conn, second, "no_such_reason")
    with pytest.raises(ValueError):
        db.finish_move(log.conn, 999)
    assert [m.state for m in db.batch_moves(log.conn, batch)] == ["done", "skipped"]
    assert log.place(log.ids["sp2"]) == ("Old/B - Two.aiff", "app")


def test_close_batch_turns_planned_moves_into_stopped(log):
    batch = log.batch([log.file_move("sp1", ONE, "Library/New/A - One.aiff"),
                       log.file_move("sp2", TWO, "Library/New/B - Two.aiff", skip=("name_taken", None)),
                       log.file_move("sp3", THREE, "Library/New/C - Three.aiff")])
    db.finish_move(log.conn, log.move_ids(batch)[0])
    db.close_batch(log.conn, batch, LATER)
    assert [(m.state, m.reason) for m in db.batch_moves(log.conn, batch)] == [
        ("done", None), ("skipped", "name_taken"), ("skipped", "stopped")]
    assert db.open_batches(log.conn) == []
    db.close_batch(log.conn, batch, datetime(2026, 10, 25))  # closing again keeps the first end
    assert log.rows("SELECT finished FROM move_batches") == [("2026-10-24T12:05:00",)]
    with pytest.raises(ValueError):
        db.close_batch(log.conn, 999, LATER)


def test_set_placed_by_changes_only_what_differs(log):
    log.conn.execute("UPDATE files SET placed_by = 'user' WHERE id = ?", (log.ids["sp2"],))
    assert db.set_placed_by(log.conn, [log.ids["sp1"], log.ids["sp2"]], "user") == 1
    assert dict(log.rows("SELECT s.key, f.placed_by FROM files f JOIN songs s ON s.id = f.song")) == {
        "sp1": "user", "sp2": "user", "sp3": "app"}
    assert db.set_placed_by(log.conn, [], "user") == 0


# --- 1.3 reads ---

def moved(log, key, src, dst, **kw):
    """A batch with one file move, done: the row is at dst, as after a tidy-up."""
    batch = log.batch([log.file_move(key, src, dst)], **kw)
    db.finish_move(log.conn, log.move_ids(batch)[0])
    db.close_batch(log.conn, batch, LATER)
    return batch


def undoable(log, batch):
    return next(b.undoable for b in db.batches(log.conn)[0] if b.id == batch)


def test_a_done_move_at_its_target_with_the_same_key_is_undoable(log):
    batch = moved(log, "sp1", ONE, "Library/New/A - One.aiff")
    assert undoable(log, batch) == 1


def test_a_move_whose_key_changed_is_not_undoable(log):
    batch = moved(log, "sp1", ONE, "Library/New/A - One.aiff")
    log.conn.execute("UPDATE files SET content_key = 'other' WHERE id = ?", (log.ids["sp1"],))
    assert undoable(log, batch) == 0


def test_a_move_whose_row_is_gone_or_elsewhere_is_not_undoable(log):
    gone = moved(log, "sp1", ONE, "Library/New/A - One.aiff")
    elsewhere = moved(log, "sp2", TWO, "Library/New/B - Two.aiff")
    log.conn.execute("DELETE FROM files WHERE id = ?", (log.ids["sp1"],))
    log.conn.execute("UPDATE files SET path = 'Other/B - Two.aiff' WHERE id = ?", (log.ids["sp2"],))
    assert (undoable(log, gone), undoable(log, elsewhere)) == (0, 0)


def test_a_move_whose_old_place_is_taken_is_not_undoable(log):
    batch = moved(log, "sp1", ONE, "Library/New/A - One.aiff")
    log.conn.execute("INSERT INTO files (folder, path, placed_by, first_seen, last_seen) "
                     "VALUES (1, 'Old/A - One.aiff', 'import', 'x', 'x')")
    assert undoable(log, batch) == 0


def test_skipped_moves_are_never_undoable(log):
    batch = log.batch([log.file_move("sp1", ONE, "Library/New/A - One.aiff", skip=("offline", None))])
    assert undoable(log, batch) == 0


def test_a_folder_move_is_undoable_while_rows_sit_under_its_target(log):
    batch = log.batch([folder_move()], started_by="rename", about={"from": "Old", "to": "New"})
    db.finish_move(log.conn, log.move_ids(batch)[0])
    assert undoable(log, batch) == 1
    log.conn.execute("UPDATE files SET path = 'Newer' || substr(path, 4) WHERE path LIKE 'New/%'")
    assert log.rows("SELECT COUNT(*) FROM files WHERE path LIKE 'New%'") == [(3,)]  # Newer/..., not under New/
    assert undoable(log, batch) == 0


def test_batches_are_newest_first_with_counts_and_the_total(log):
    first = log.batch([log.file_move("sp1", ONE, "Library/New/A - One.aiff"),
                       log.file_move("sp2", TWO, "Library/New/B - Two.aiff", skip=("name_taken", None))])
    db.finish_move(log.conn, log.move_ids(first)[0])
    db.close_batch(log.conn, first, LATER)
    rename = log.batch([folder_move("Library/Old2", "Library/Two")], started_by="rename",
                       about={"from": "Old2", "to": "Two"})
    undo1 = log.batch([], started_by="undo", undoes=first)
    undo2 = log.batch([], started_by="undo", undoes=first)
    rows, total = db.batches(log.conn)
    assert total == 4 and [b.id for b in rows] == [undo2, undo1, rename, first]
    assert rows[-1] == BatchRow(id=first, started="2026-10-24T12:00:00", finished="2026-10-24T12:05:00",
                                started_by="tidy", about=None, undoes=None, moved=1, skipped=1, undoable=1,
                                undone_by=undo2)
    assert (rows[2].about, rows[2].moved, rows[2].undoable, rows[2].finished) == (
        {"from": "Old2", "to": "Two"}, 0, 0, None)
    assert rows[0].undoes == first and rows[0].undone_by is None
    limited, total = db.batches(log.conn, limit=2)
    assert [b.id for b in limited] == [undo2, undo1] and total == 4
