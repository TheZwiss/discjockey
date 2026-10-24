"""The tidy-up engine (plan library stage 2, group 3): batches, undo, the save's choice, recovery. tmp_path only."""
import errno
import os
import sqlite3
from datetime import datetime

import pytest

from discjockey import db, library, planner, quality, tidy
from discjockey.events import CancelToken, MovesProgress, no_emit
from discjockey.library import Paths, empty_state, load_state, save_state
from discjockey.models import MoveRow, PlannedMove, SaveChoice
from discjockey.playlists_file import Row

LINK1 = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
LINK2 = "https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd"


@pytest.fixture
def paths(tmp_path):
    p = Paths(tmp_path, support=tmp_path / ".support")
    p.library.mkdir(parents=True)
    p.data.mkdir()
    return p


def touch(paths, rel, data):
    f = paths.root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return f


def playlists(paths, *lines):
    paths.playlists_file.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def library_with(paths, *songs):
    """songs: (key, folder the playlist order puts it in, folder it is in now). Each file has its own bytes."""
    s = empty_state()
    for key, folder, where in songs:
        rel = f"Library/{where}/A - {key}.aiff"
        touch(paths, rel, f"audio of {key}".encode())
        s["tracks"][key] = {"artist": "A", "title": key, "path": rel, "status": "lossless", "folder": folder,
                            "in_playlists": True}
    save_state(paths, s)
    return load_state(paths)


def sent(state, *keys):
    return [(state["tracks"][k]["file_id"], state["tracks"][k]["path"]) for k in keys]


def placed(paths, key):
    return load_state(paths)["tracks"][key]["placed_by"]


def mark_user(paths, state, *keys):
    with db.connect(paths.db_file) as conn:
        db.set_placed_by(conn, [state["tracks"][k]["file_id"] for k in keys], "user")


def moves_of(paths, batch_id):
    with db.connect(paths.db_file) as conn:
        return db.batch_moves(conn, batch_id)


def open_batches(paths):
    with db.connect(paths.db_file) as conn:
        return db.open_batches(conn)


# --- 3.2 tidy_up ---

def test_a_batch_moves_the_sent_files_and_their_rows_follow(paths):
    state = library_with(paths, ("s1", "A", "B"), ("s2", "A", "B"))
    mark_user(paths, state, "s2")
    progress = []
    result = tidy.tidy_up(paths, sent(state, "s1", "s2"), emit=progress.append)
    assert result.moved == 2 and result.skipped == () and not result.stopped and result.started_by == "tidy"
    after = load_state(paths)
    assert [after["tracks"][k]["path"] for k in ("s1", "s2")] == ["Library/A/A - s1.aiff", "Library/A/A - s2.aiff"]
    assert (paths.library / "A" / "A - s2.aiff").read_bytes() == b"audio of s2"  # the same file, the same name
    assert placed(paths, "s2") == "app"  # a file a tidy-up moves follows the order from then on
    assert [e for e in progress if isinstance(e, MovesProgress)] == [MovesProgress(result.batch_id, 1, 2),
                                                                     MovesProgress(result.batch_id, 2, 2)]
    log = moves_of(paths, result.batch_id)
    assert [(m.state, m.placed_before, m.placed_after) for m in log] == [("done", "app", "app"),
                                                                         ("done", "user", "app")]
    assert open_batches(paths) == []


def test_nothing_sent_is_no_batch(paths):
    library_with(paths, ("s1", "A", "B"))
    assert tidy.tidy_up(paths, []).batch_id is None


def test_a_taken_name_a_vanished_file_and_a_refused_move_are_skipped_and_the_rest_move(paths, monkeypatch):
    state = library_with(paths, ("s1", "A", "B"), ("s2", "A", "B"), ("s3", "A", "B"), ("s4", "A", "B"))
    touch(paths, "Library/A/A - s1.aiff", b"someone else's file")  # taken since the preview
    (paths.library / "B" / "A - s2.aiff").unlink()  # gone since the preview
    real = os.rename

    def rename(src, dst):
        if str(src).endswith("A - s3.aiff"):
            raise PermissionError(errno.EACCES, "Permission denied")
        real(src, dst)
    monkeypatch.setattr(os, "rename", rename)
    result = tidy.tidy_up(paths, sent(state, "s1", "s2", "s3", "s4"))
    assert result.moved == 1
    assert [(m.label, m.reason, m.detail) for m in result.skipped] == [
        ("A - s1", "name_taken", None), ("A - s2", "not_found", None),
        ("A - s3", "failed", "Discjockey isn't allowed to change that folder")]
    assert (paths.library / "A" / "A - s1.aiff").read_bytes() == b"someone else's file"
    assert (paths.library / "B" / "A - s1.aiff").exists() and (paths.library / "B" / "A - s3.aiff").exists()
    assert load_state(paths)["tracks"]["s4"]["path"] == "Library/A/A - s4.aiff"
    assert load_state(paths)["pending"] == []


def test_a_name_refused_by_the_disk_at_move_time_is_name_taken(paths, monkeypatch):
    state = library_with(paths, ("s1", "A", "B"))
    real = library.safe_rename

    def taken(root, src, dst):  # another program put a file there after the scan
        touch(paths, dst, b"in the way")
        real(root, src, dst)
    monkeypatch.setattr(library, "safe_rename", taken)
    result = tidy.tidy_up(paths, sent(state, "s1"))
    assert [m.reason for m in result.skipped] == ["name_taken"]
    assert (paths.library / "B" / "A - s1.aiff").read_bytes() == b"audio of s1"


def test_a_file_whose_path_changed_since_the_list_was_shown_is_not_moved(paths):
    state = library_with(paths, ("s1", "A", "B"))
    result = tidy.tidy_up(paths, [(state["tracks"]["s1"]["file_id"], "Library/C/A - s1.aiff")])
    assert [m.reason for m in result.skipped] == ["changed"] and result.moved == 0
    assert (paths.library / "B" / "A - s1.aiff").exists()


def test_a_file_id_without_a_row_is_logged_as_not_found(paths):
    library_with(paths, ("s1", "A", "B"))
    result = tidy.tidy_up(paths, [(999, "Library/B/A - gone.aiff")])
    assert [(m.label, m.reason) for m in result.skipped] == [("A - gone", "not_found")]


def test_a_song_gone_between_planning_and_its_move_is_not_found(paths):
    state = library_with(paths, ("s1", "A", "B"))
    e = state["tracks"]["s1"]
    batch = tidy._start(paths, "tidy", [PlannedMove("file", e["file_id"], "A - s1", e["path"],
                                                    "Library/A/A - s1.aiff", None, "app", "app")], datetime.now)
    del state["tracks"]["s1"]
    result = tidy._run(paths, state, batch, "tidy", emit=no_emit, token=CancelToken(), now=datetime.now)
    assert [m.reason for m in result.skipped] == ["not_found"] and (paths.library / "B" / "A - s1.aiff").exists()


def test_a_move_the_records_refuse_is_failed_in_words_that_say_it_moved(paths, monkeypatch):
    state = library_with(paths, ("s1", "A", "B"))

    def refused(conn, move_id):
        raise sqlite3.IntegrityError("UNIQUE constraint failed: files.folder, files.path")
    monkeypatch.setattr(db, "finish_move", refused)
    result = tidy.tidy_up(paths, sent(state, "s1"))
    assert [(m.reason, m.detail) for m in result.skipped] == [("failed", tidy.MOVED_NOT_RECORDED)]
    assert "playlists.txt" not in tidy.MOVED_NOT_RECORDED and "records" not in tidy.MOVED_NOT_RECORDED
    assert (paths.library / "A" / "A - s1.aiff").exists()  # the record says what happened on disk


def test_failed_details_are_plain_words():
    assert tidy.failed_detail(OSError(errno.ENOSPC, "No space left on device")) == "the drive is full"
    assert tidy.failed_detail(OSError(errno.EROFS, "Read-only file system")) == "the drive is read-only"
    assert tidy.failed_detail(OSError(errno.EIO, "Input/output error")) == "input/output error"


def test_stop_after_the_first_file_closes_the_batch_with_the_rest_stopped(paths):
    state = library_with(paths, ("s1", "A", "B"), ("s2", "A", "B"))
    token = CancelToken()
    with pytest.raises(tidy.Stopped) as stopped:
        tidy.tidy_up(paths, sent(state, "s1", "s2"), token=token,
                     emit=lambda e: token.cancel() if isinstance(e, MovesProgress) else None)
    result = stopped.value.result
    assert result.stopped and result.moved == 1 and [m.reason for m in result.skipped] == ["stopped"]
    assert (paths.library / "B" / "A - s2.aiff").exists() and open_batches(paths) == []


# --- 3.2 rename_folder ---

def test_a_folder_rename_moves_linked_and_unlinked_rows_and_keeps_placed_by(paths):
    state = library_with(paths, ("s1", "New", "Old"), ("s2", "New", "Old"))
    mark_user(paths, state, "s2")
    touch(paths, "Library/Old/not_lossless/loose.mp3", b"no song's file")
    playlists(paths, f"New = {LINK1}")
    result = tidy.rename_folder(paths, "Old", "New")
    # the batch counts the files the folder carried: two songs and the loose file
    assert result.moved == 3 and result.started_by == "rename" and not (paths.library / "Old").exists()
    after = load_state(paths)
    assert after["tracks"]["s1"]["path"] == "Library/New/A - s1.aiff"
    assert after["tracks"]["s2"]["placed_by"] == "user"
    with db.connect(paths.db_file) as conn:
        assert {f.rel for f in db.known_files(conn)} == {"New/A - s1.aiff", "New/A - s2.aiff",
                                                          "New/not_lossless/loose.mp3"}
        rows, _ = db.batches(conn)
    assert rows[0].about == {"from": "Old", "to": "New"} and rows[0].moved == 3  # the batch summary counts files
    assert [m.files for m in moves_of(paths, result.batch_id)] == [3]
    assert paths.playlists_file.read_text().startswith("New = ")  # the save had already written it


def test_a_folder_rename_onto_a_taken_name_is_one_skipped_move(paths):
    library_with(paths, ("s1", "New", "Old"), ("s2", "X", "New"))
    playlists(paths, f"New = {LINK1}", f"X = {LINK2}")
    result = tidy.rename_folder(paths, "Old", "New")
    assert result.moved == 0 and [(m.kind, m.reason, m.detail) for m in result.skipped] == [
        ("folder", "name_taken", "folder_taken")]
    assert (paths.library / "Old" / "A - s1.aiff").exists()


def test_a_folder_name_with_a_slash_is_refused(paths):
    library_with(paths, ("s1", "New", "Old"))
    with pytest.raises(ValueError):
        tidy.rename_folder(paths, "Old", "../Elsewhere")


def test_rename_offer():
    rows = [Row("New", LINK1), Row("Other", LINK2)]
    assert tidy.rename_offer("Old", "New", rows, ["Old", "Other"]) is None
    assert tidy.rename_offer("old", "New", rows, ["Old"]) is None  # the disk ignores case
    assert tidy.rename_offer("Old", "New", rows, ["Other"]) == "no_folder"
    assert tidy.rename_offer("Old", "New", rows, ["Old", "new"]) == "folder_taken"
    assert tidy.rename_offer("Old", "New", [*rows, Row("Old", LINK2, enabled=False)], ["Old"]) == "folder_in_use"


def test_rename_offer_refuses_a_chain_and_one_folder_renamed_twice():
    # A -> B and B -> A: each old name is a folder of the new lines
    rows = [Row("B", LINK1), Row("A", LINK2)]
    assert tidy.rename_offer("A", "B", rows, ["A"]) == "folder_in_use"
    assert tidy.rename_offer("B", "A", rows, ["B"]) == "folder_in_use"
    # one playlist split into two lines: A -> B and A -> C
    rows = [Row("B", LINK1), Row("C", LINK1)]
    pairs = [("A", "B"), ("A", "C")]
    assert tidy.rename_offer("A", "B", rows, ["A"], pairs=pairs) == "folder_in_use"
    assert tidy.rename_offer("A", "C", rows, ["A"], pairs=pairs) == "folder_in_use"


# --- 3.3 undo ---

def tidied(paths, *songs, user=()):
    state = library_with(paths, *songs)
    mark_user(paths, state, *user)
    return state, tidy.tidy_up(paths, sent(state, *(k for k, _, _ in songs)))


def test_undo_moves_the_files_back_and_restores_placed_by(paths):
    _, done = tidied(paths, ("s1", "A", "B"), ("s2", "A", "B"), user=("s2",))
    result = tidy.undo(paths, done.batch_id)
    assert result.moved == 2 and result.started_by == "undo"
    after = load_state(paths)
    assert [after["tracks"][k]["path"] for k in ("s1", "s2")] == ["Library/B/A - s1.aiff", "Library/B/A - s2.aiff"]
    assert after["tracks"]["s2"]["placed_by"] == "user"
    assert [m.label for m in moves_of(paths, result.batch_id)] == ["A - s2", "A - s1"]  # reverse order
    with db.connect(paths.db_file) as conn:
        rows, _ = db.batches(conn)
    assert rows[0].undoes == done.batch_id and rows[1].undone_by == result.batch_id


def test_undo_skips_what_moved_on_or_lost_its_place(paths, monkeypatch):
    monkeypatch.setattr(quality, "inspect", lambda path: ("pcm_s16be", None))
    _, done = tidied(paths, ("s1", "A", "B"), ("s2", "A", "B"), ("s3", "A", "B"), ("s4", "A", "B"))
    touch(paths, "Library/A/A - s1.aiff", b"edited audio")  # its key changes
    (paths.library / "C").mkdir()
    os.rename(paths.library / "A" / "A - s2.aiff", paths.library / "C" / "A - s2.aiff")  # moved by hand
    touch(paths, "Library/B/A - s3.aiff", b"a new file in its old place")
    library.scan_library(paths)  # the preview reads the records as the last scan left them
    preview = tidy.undo_preview(paths, load_state(paths), done.batch_id)
    assert [(m.label, m.skip) for m in preview] == [("A - s4", None), ("A - s3", ("place_taken", None)),
                                                    ("A - s2", ("moved_on", None)), ("A - s1", ("moved_on", None))]
    result = tidy.undo(paths, done.batch_id)
    assert result.moved == 1 and [m.reason for m in result.skipped] == ["place_taken", "moved_on", "moved_on"]
    assert load_state(paths)["tracks"]["s4"]["path"] == "Library/B/A - s4.aiff"
    assert (paths.library / "A" / "A - s3.aiff").read_bytes() == b"audio of s3"


@pytest.mark.parametrize("field, value, reason", [("online", False, "offline"), ("held", True, "moved_on")])
def test_undo_skips_an_offline_or_held_file(paths, field, value, reason):
    _, done = tidied(paths, ("s1", "A", "B"))
    state = load_state(paths)
    state["tracks"]["s1"][field] = value
    assert [m.skip for m in tidy.undo_preview(paths, state, done.batch_id)] == [(reason, None)]


def test_a_refused_move_back_is_failed_and_the_file_stays(paths, monkeypatch):
    _, done = tidied(paths, ("s1", "A", "B"))

    def rename(src, dst):
        raise PermissionError(errno.EPERM, "Operation not permitted")
    monkeypatch.setattr(os, "rename", rename)
    result = tidy.undo(paths, done.batch_id)
    assert [(m.reason, m.detail) for m in result.skipped] == [
        ("failed", "Discjockey isn't allowed to change that folder")]
    assert load_state(paths)["tracks"]["s1"]["path"] == "Library/A/A - s1.aiff"


def test_undo_preview_of_a_library_without_records_is_empty(paths):
    assert tidy.undo_preview(paths, empty_state(), 1) == [] and not paths.db_file.exists()


def test_undo_of_an_undo_moves_the_files_again(paths):
    _, done = tidied(paths, ("s1", "A", "B"))
    back = tidy.undo(paths, done.batch_id)
    again = tidy.undo(paths, back.batch_id)
    assert again.moved == 1 and load_state(paths)["tracks"]["s1"]["path"] == "Library/A/A - s1.aiff"
    assert placed(paths, "s1") == "app"


def test_a_batch_with_nothing_left_gives_a_batch_of_skips(paths):
    _, done = tidied(paths, ("s1", "A", "B"))
    (paths.library / "C").mkdir()
    os.rename(paths.library / "A" / "A - s1.aiff", paths.library / "C" / "A - s1.aiff")
    result = tidy.undo(paths, done.batch_id)
    assert result.batch_id is not None and result.moved == 0 and [m.reason for m in result.skipped] == ["moved_on"]


def renamed(paths):
    library_with(paths, ("s1", "New", "Old"))
    playlists(paths, "# my playlists", f"New = {LINK1}", f"X = {LINK2}")
    return tidy.rename_folder(paths, "Old", "New")


def test_undo_of_a_folder_rename_renames_the_folder_and_the_playlist_back(paths):
    done = renamed(paths)
    touch(paths, "Library/New/A - since.aiff", b"downloaded since")  # goes back with the folder
    assert done.moved == 1  # renamed() has one song's file in the folder
    result = tidy.undo(paths, done.batch_id)
    assert result.moved == 2 and not (paths.library / "New").exists()  # and the file downloaded since goes along
    assert [m.files for m in moves_of(paths, result.batch_id)] == [2]
    assert (paths.library / "Old" / "A - since.aiff").exists()
    assert load_state(paths)["tracks"]["s1"]["path"] == "Library/Old/A - s1.aiff"
    assert paths.playlists_file.read_text() == f"# my playlists\nOld = {LINK1}\nX = {LINK2}\n"


def test_after_a_rename_and_its_undo_every_file_is_in_place(paths):
    done = renamed(paths)
    assert planner.out_of_place(load_state(paths)) == 0
    tidy.undo(paths, done.batch_id)
    after = load_state(paths)
    assert after["tracks"]["s1"]["folder"] == "Old"  # the playlist is called Old again, so are its songs' folders
    assert planner.out_of_place(after) == 0 and planner.tidy_rows(after) == []


def test_a_playlist_that_cannot_be_named_back_says_so_in_plain_words(paths, monkeypatch):
    def refused(paths, frm, to):
        raise PermissionError(1, "Operation not permitted: /x/playlists.txt")
    monkeypatch.setattr(tidy, "_rename_playlist", refused)
    move = MoveRow(1, 1, 0, "folder", None, "New", "Library/New", "Library/Old", None, None, None, "done", None,
                   None, None, None)
    text = tidy._playlist_follows(paths, move)
    assert text == tidy.NOT_RENAMED_BACK.format(to="Old")
    assert "playlists.txt" not in text and "Operation" not in text


def test_a_rename_on_its_own_gives_the_songs_the_new_folder(paths):
    library_with(paths, ("s1", "Old", "Old"), ("s2", "Old", "Elsewhere"))
    playlists(paths, f"New = {LINK1}")
    tidy.rename_folder(paths, "Old", "New")
    after = load_state(paths)
    assert [after["tracks"][k]["folder"] for k in ("s1", "s2")] == ["New", "New"]
    assert after["tracks"]["s2"]["path"] == "Library/Elsewhere/A - s2.aiff"  # only the folder's files move


def test_undo_of_a_folder_rename_skips_when_the_playlist_or_the_folder_changed(paths):
    done = renamed(paths)
    playlists(paths, f"Renamed again = {LINK1}", f"X = {LINK2}")
    assert [m.skip for m in tidy.undo_preview(paths, load_state(paths), done.batch_id)] == [
        ("playlist_renamed", None)]
    playlists(paths, f"New = {LINK1}", f"Old = {LINK2}")
    assert [m.skip for m in tidy.undo_preview(paths, load_state(paths), done.batch_id)] == [
        ("place_taken", tidy.NAME_USED)]
    playlists(paths, f"New = {LINK1}")
    (paths.library / "Old").mkdir()  # a folder called Old is back
    assert [m.skip for m in tidy.undo_preview(paths, load_state(paths), done.batch_id)] == [
        ("place_taken", tidy.FOLDER_THERE)]
    (paths.library / "Old").rmdir()
    os.rename(paths.library / "New", paths.library / "Moved")  # the folder renamed again by hand
    result = tidy.undo(paths, done.batch_id)
    assert result.moved == 0 and [m.reason for m in result.skipped] == ["moved_on"]
    assert paths.playlists_file.read_text() == f"New = {LINK1}\n"


def test_a_crash_between_the_folder_undo_and_the_name_write_is_finished_next_start(paths, monkeypatch):
    done = renamed(paths)

    def power_cut(paths_, m):
        raise SystemExit("power cut")
    monkeypatch.setattr(tidy, "_playlist_follows", power_cut)
    with pytest.raises(SystemExit):
        tidy.undo(paths, done.batch_id)
    monkeypatch.undo()
    assert (paths.library / "Old").is_dir() and paths.playlists_file.read_text().count("New = ") == 1
    state = load_state(paths)
    messages = library.recover_pending(paths, state)
    assert paths.playlists_file.read_text() == f"# my playlists\nOld = {LINK1}\nX = {LINK2}\n"
    assert messages == [(tidy.RECOVERED_UNDO.format(moved=1, left=0), True)] and open_batches(paths) == []


# --- 3.4 after_save ---

def test_leave_marks_only_the_retargeted_files_the_app_placed(paths):
    state = library_with(paths, ("s1", "A", "A"), ("s2", "A", "A"), ("s3", "A", "A"))
    mark_user(paths, state, "s2")
    results = tidy.after_save(paths, {"s1": "B", "s2": "B"}, SaveChoice("leave"))
    after = load_state(paths)
    assert results == [] and after["tracks"]["s1"]["folder"] == "B"
    assert [after["tracks"][k]["placed_by"] for k in ("s1", "s2", "s3")] == ["user", "user", "app"]
    assert after["tracks"]["s1"]["path"] == "Library/A/A - s1.aiff"  # nothing moved


@pytest.mark.parametrize("spelling", ["Library/Old/A - s2.aiff", "Library/New/A - s2.aiff"])
def test_move_with_a_rename_and_moves_gives_two_batches(paths, spelling):
    state = library_with(paths, ("s1", "New", "Old"), ("s2", "C", "Old"))
    playlists(paths, f"New = {LINK1}", f"C = {LINK2}")
    s2 = state["tracks"]["s2"]["file_id"]
    results = tidy.after_save(paths, {"s1": "New", "s2": "C"},
                              SaveChoice("move", renames=(("Old", "New"),), moves=((s2, spelling),)))
    assert [(r.started_by, r.moved) for r in results] == [("rename", 2), ("save", 1)]
    after = load_state(paths)
    assert after["tracks"]["s1"]["path"] == "Library/New/A - s1.aiff"
    assert after["tracks"]["s2"]["path"] == "Library/C/A - s2.aiff"


def test_a_rename_refused_at_run_time_is_one_skipped_move_and_the_moves_still_run(paths):
    state = library_with(paths, ("s1", "New", "Old"), ("s2", "C", "B"), ("s3", "X", "New"), ("s4", "C", "Old"),
                         ("s5", "C", "Old"))
    playlists(paths, f"New = {LINK1}", f"C = {LINK2}")
    s4, s5 = state["tracks"]["s4"]["file_id"], state["tracks"]["s5"]["file_id"]
    moves = (*sent(state, "s2"), (s4, "Library/New/A - s4.aiff"), (s5, "Library/Old/A - s5.aiff"))
    results = tidy.after_save(paths, {"s1": "New", "s2": "C", "s4": "C", "s5": "C"},
                              SaveChoice("move", renames=(("Old", "New"),), moves=moves))
    assert [(r.started_by, r.moved, [m.reason for m in r.skipped]) for r in results] == [
        ("rename", 0, ["name_taken"]), ("save", 3, [])]
    assert load_state(paths)["tracks"]["s4"]["path"] == "Library/C/A - s4.aiff"  # found under its old spelling


def test_a_stop_during_a_save_keeps_the_batches_before_it(paths):
    state = library_with(paths, ("s1", "New", "Old"), ("s2", "C", "B"))
    playlists(paths, f"New = {LINK1}", f"C = {LINK2}")
    token = CancelToken()
    with pytest.raises(tidy.Stopped) as stopped:
        tidy.after_save(paths, {"s1": "New", "s2": "C"},
                        SaveChoice("move", renames=(("Old", "New"),), moves=tuple(sent(state, "s2"))), token=token,
                        emit=lambda e: token.cancel() if isinstance(e, MovesProgress) else None)
    assert [(r.started_by, r.moved, r.stopped) for r in stopped.value.results] == [("rename", 1, False),
                                                                                   ("save", 0, True)]


# --- 3.5 recovery ---

def test_a_crash_after_the_move_and_before_it_is_marked_done_is_finished_next_start(paths, monkeypatch):
    state = library_with(paths, ("s1", "A", "B"), ("s2", "A", "B"))
    mark_user(paths, state, "s1")

    def power_cut(conn, move_id):
        raise SystemExit("power cut")
    monkeypatch.setattr(db, "finish_move", power_cut)
    with pytest.raises(SystemExit):
        tidy.tidy_up(paths, sent(state, "s1", "s2"))
    monkeypatch.undo()
    assert open_batches(paths) != []
    messages = library.recover_pending(paths, load_state(paths))
    assert messages == [(tidy.RECOVERED.format(moved=1, left=1), True)]
    log = moves_of(paths, 1)
    assert [(m.state, m.reason) for m in log] == [("done", None), ("skipped", "stopped")]
    after = load_state(paths)
    assert after["tracks"]["s1"]["path"] == "Library/A/A - s1.aiff" and after["tracks"]["s1"]["placed_by"] == "app"
    assert after["tracks"]["s2"]["path"] == "Library/B/A - s2.aiff" and open_batches(paths) == []


def test_a_crash_before_the_move_leaves_the_file_where_it_was(paths, monkeypatch):
    state = library_with(paths, ("s1", "A", "B"))

    def power_cut(*a, **k):
        raise SystemExit("power cut")
    monkeypatch.setattr(library, "run_op", power_cut)
    with pytest.raises(SystemExit):
        tidy.tidy_up(paths, sent(state, "s1"))
    monkeypatch.undo()
    assert library.recover_pending(paths, load_state(paths)) == [(tidy.RECOVERED_NONE, True)]
    assert [(m.state, m.reason) for m in moves_of(paths, 1)] == [("skipped", "stopped")]
    assert (paths.library / "B" / "A - s1.aiff").exists() and placed(paths, "s1") == "app"


def test_a_step_still_pending_is_finished_first_and_its_move_counts_as_done(paths, monkeypatch):
    state = library_with(paths, ("s1", "A", "B"))
    real, saves = library.save_state, []

    def save(paths_, st, **kw):
        if saves:
            raise SystemExit("power cut")  # after the rename, before the entry is written
        saves.append(1)
        real(paths_, st, **kw)
    monkeypatch.setattr(library, "save_state", save)
    with pytest.raises(SystemExit):
        tidy.tidy_up(paths, sent(state, "s1"))
    monkeypatch.undo()
    messages = library.recover_pending(paths, load_state(paths))
    assert messages[-1] == (tidy.RECOVERED.format(moved=1, left=0), True)
    assert load_state(paths)["tracks"]["s1"]["path"] == "Library/A/A - s1.aiff"
    assert [m.state for m in moves_of(paths, 1)] == ["done"]


@pytest.mark.parametrize("moved", [True, False])
def test_a_stopped_folder_rename_is_worded_as_one(paths, monkeypatch, moved):
    library_with(paths, ("s1", "New", "Old"))
    playlists(paths, f"New = {LINK1}")

    def power_cut(*a, **k):
        raise SystemExit("power cut")
    monkeypatch.setattr(db, "finish_move", power_cut) if moved else monkeypatch.setattr(library, "run_op", power_cut)
    with pytest.raises(SystemExit):
        tidy.rename_folder(paths, "Old", "New")
    monkeypatch.undo()
    expected = (tidy.RECOVERED_RENAME.format(new="New") if moved else tidy.RECOVERED_RENAME_NONE.format(old="Old"))
    assert library.recover_pending(paths, load_state(paths)) == [(expected, True)]


@pytest.mark.parametrize("name, said", [
    ("/", "\u201c/\u201d can't be used"), (".", "\u201c.\u201d can't be used"), ("..", "\u201c..\u201d can't be used"),
    ("  ", "\u201c  \u201d can't be used"), (" a", "can't be used"), ("a ", "can't be used"),
    ("a/b", "can't be used"), ("a\\b", "can't be used"), (".hidden", "can't be used"),
    ("", "A folder name can't be empty."), (None, "can't be used"), (7, "\u201c7\u201d can't be used"),
])
def test_check_folder_names_refuses_what_is_not_one_plain_folder_name(name, said):
    with pytest.raises(ValueError, match=said.replace(".", r"\.")):
        tidy.check_folder_names("Fine", name)


def test_check_folder_names_accepts_plain_names():
    tidy.check_folder_names("Hard_Bounce", "Two words", "Caf\u00e9-2", "a.b")


def test_a_batch_found_open_after_a_crash_is_worded_by_the_kind_of_batch_it_is(paths):
    library_with(paths, ("s1", "New", "Old"))
    playlists(paths, f"New = {LINK1}")
    with db.connect(paths.db_file) as conn:
        for _ in range(25):  # more batches before it than a listing shows by default
            db.close_batch(conn, db.start_batch(conn, started_by="tidy", about=None, undoes=None, moves=[],
                                                now=datetime(2026, 1, 1)), datetime(2026, 1, 1))
        move = PlannedMove("folder", None, "Old", "Library/Old", "Library/New", None, None, None)
        db.start_batch(conn, started_by="rename", about={"from": "Old", "to": "New"}, undoes=None, moves=[move],
                       now=datetime(2026, 1, 2))
        assert tidy._started_by(conn, 26) == "rename" and tidy._started_by(conn, 99) == "tidy"


def test_a_stopped_undo_of_a_folder_rename_counts_the_files_it_moved_back():
    def move(kind, state, files=None):
        return MoveRow(id=1, batch=2, seq=0, kind=kind, file_id=None, label="x", src="Library/New",
                       dst="Library/Old", content_key=None, placed_before=None, placed_after=None, state=state,
                       reason=None, detail=None, now_path=None, now_key=None, files=files)
    said = tidy._recovered("undo", [move("folder", "done", 7), move("file", "planned")])
    assert said == tidy.RECOVERED_UNDO.format(moved=7, left=1)
