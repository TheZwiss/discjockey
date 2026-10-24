"""The bridge's tidy-up, move log and undo, and the save question (plan library stage 2, group 5)."""
import pytest
from hub_helpers import ID1, ID2, LOSSY, PLAYLISTS, TRACKS, fake_spotify, make_api, make_root, refreshed, wait_job

from discjockey import library, tidy
from discjockey.library import Paths, load_state, run_lock

HARD = ("Hard_Bounce", f"https://open.spotify.com/playlist/{ID1}", True)
POWER = ("Powertrance", f"https://open.spotify.com/playlist/{ID2}", True)
SWAPPED = [{"folder": f, "link": link, "enabled": on} for f, link, on in (POWER, HARD)]


@pytest.fixture
def root(tmp_path, monkeypatch):
    fake_spotify(monkeypatch, TRACKS)
    return make_root(tmp_path)


def moves(row):
    return [[row["file_id"], row["from_path"]]]


def swapped_preview(api, rec):
    """The save preview of the swapped playlists, after the hub has read them: its tidy rows."""
    refreshed(api, rec)
    return api.preview_playlist_change(SWAPPED)["tidy"]["rows"]


def place_elsewhere(root, *keys):
    """The files of these songs in a folder the playlist order doesn't put them in."""
    state = load_state(root)
    (root.root / "Library" / "Elsewhere").mkdir(exist_ok=True)
    for key in keys:
        e = state["tracks"][key]
        new = f"Library/Elsewhere/{e['path'].rsplit('/', 1)[1]}"
        (root.root / e["path"]).rename(root.root / new)
        state["tracks"][key] = {**e, "path": new}
    library.save_state(root, state)


def place_t2_elsewhere(root):
    """t2's file in a folder the playlist order doesn't put it in, so a tidy-up has something to do."""
    state = load_state(root)
    e = state["tracks"]["t2"]
    new = "Library/Elsewhere/Armin Hermann - Get Naughty.aiff"
    (root.root / "Library" / "Elsewhere").mkdir()
    (root.root / e["path"]).rename(root.root / new)
    library.save_state(root, {**state, "tracks": {**state["tracks"], "t2": {**e, "path": new}}})
    return new


def test_the_reads_answer_empty_while_nothing_was_ever_moved(tmp_path, monkeypatch):
    fake_spotify(monkeypatch, TRACKS)
    root = Paths(tmp_path, support=tmp_path / ".support")
    (root.library).mkdir(parents=True)
    root.data.mkdir()
    root.support.mkdir(parents=True)
    root.playlists_file.write_text(PLAYLISTS)
    api, _ = make_api(root)
    assert api.move_batches() == {"ok": True, "batches": [], "total": 0}
    assert api.tidy_preview()["empty"] and api.tidy_preview()["rows"] == []
    assert api.undo_preview(1)["kind"] == "refused"
    assert api.playlists()["tidy"] == {"waiting": 0}


def test_tidy_preview_lists_the_files_out_of_place_and_the_page_counts_them(root):
    place_t2_elsewhere(root)
    api, _ = make_api(root)
    page = api.tidy_preview()
    assert page["ok"] and [r["track_id"] for r in page["rows"]] == ["t2"] and page["ticked"] == 1
    assert (page["rows"][0]["from"], page["rows"][0]["to"]) == ("Elsewhere", "Hard_Bounce/not_lossless")
    assert api.playlists()["tidy"] == {"waiting": 1}


def test_a_tidy_up_job_moves_the_file_logs_the_batch_and_undo_puts_it_back(root):
    old = place_t2_elsewhere(root)
    api, rec = make_api(root)
    row = api.tidy_preview()["rows"][0]
    f = wait_job(api, rec, api.tidy_up(moves(row)))
    assert f.ok and f.kind == "tidy"
    assert f.result["title"] == "Tidy-up" and f.result["moved"] == 1 and f.result["skipped"] == []
    assert f.result["headline"] == "Moved 1 file." and f.result["stopped"] is False
    assert load_state(root)["tracks"]["t2"]["path"] == LOSSY and not (root.root / old).exists()
    assert any(type(e).__name__ == "MovesProgress" for e in rec.events)
    log = api.move_batches()
    assert log["total"] == 1 and log["batches"][0]["summary"] == "1 file moved"
    assert (log["batches"][0]["id"], log["batches"][0]["undoable"]) == (f.result["batch_id"], 1)
    preview = api.undo_preview(f.result["batch_id"])
    assert preview["ok"] and preview["moving"] == 1 and preview["nothing_left"] is False
    assert preview["title"] == "Tidy-up" and preview["rows"][0]["skip"] is None
    undone = wait_job(api, rec, api.undo_moves(f.result["batch_id"]))
    assert undone.ok and undone.kind == "undo_moves" and undone.result["headline"] == "Moved 1 file back."
    assert undone.result["title"] == "Undo of: Tidy-up" and (root.root / old).exists()
    assert api.move_batches()["batches"][0]["undone_by"] is None
    assert api.move_batches()["batches"][1]["undone_by"] == undone.result["batch_id"]


def test_a_file_that_changed_since_the_list_is_not_moved_and_the_result_says_why(root):
    place_t2_elsewhere(root)
    api, rec = make_api(root)
    row = api.tidy_preview()["rows"][0]
    f = wait_job(api, rec, api.tidy_up([[row["file_id"], "Library/Somewhere/else.aiff"]]))
    assert f.ok and f.result["moved"] == 0 and f.result["headline"] == "Moved 0 files. 1 not moved:"
    assert f.result["skipped"][0]["text"] == "Changed since the list was shown"


def test_the_write_jobs_answer_busy_and_console_and_refuse_malformed_input(root):
    place_t2_elsewhere(root)
    api, rec = make_api(root)
    row = api.tidy_preview()["rows"][0]
    with run_lock(root.lock):
        assert api.tidy_up(moves(row))["kind"] == "console"
    for bad in (None, "x", [], [[1]], [[True, "a"]], [["1", "a"]], [[1, ""]], [[1, "a", "b"]], [{"file_id": 1}]):
        assert api.tidy_up(bad)["kind"] == "refused", bad
    assert api.undo_moves("1")["kind"] == "refused" and api.undo_moves(True)["kind"] == "refused"
    assert api._jobs.current is None  # none of them started a job
    assert load_state(root)["tracks"]["t2"]["path"].startswith("Library/Elsewhere/")


def test_a_move_list_that_is_not_a_list_is_malformed_and_an_empty_one_is_nothing_chosen(root):
    api, _ = make_api(root)
    for bad in (None, "x", {"a": 1}, 7):
        answer = api.tidy_up(bad)
        assert answer["kind"] == "refused" and answer["message"].startswith("Each file to move needs"), bad
    assert api.tidy_up([])["message"] == "No files were chosen to move."


def test_undoing_a_batch_nobody_recorded_is_refused_before_a_job_starts(root):
    api, rec = make_api(root)
    answer = api.undo_moves(99)  # no library.db yet
    assert answer["kind"] == "refused" and answer["message"] == "Discjockey has no record of these moves."
    place_t2_elsewhere(root)
    row = api.tidy_preview()["rows"][0]
    assert wait_job(api, rec, api.tidy_up(moves(row))).ok  # now there is a batch 1, and no batch 99
    assert api.undo_moves(99)["kind"] == "refused" and api._jobs.current.id == 1  # no second job started
    with run_lock(root.lock):
        assert api.undo_moves(1)["kind"] == "console"


def stop_after_the_first_move(api, monkeypatch):
    real = library.run_op

    def run_op(*args, **kwargs):
        real(*args, **kwargs)
        api.stop()
    monkeypatch.setattr(library, "run_op", run_op)


def test_a_stopped_tidy_up_still_delivers_its_result_and_stays_stopped(root, monkeypatch):
    api, rec = make_api(root)
    place_elsewhere(root, "t1", "t2")
    rows = api.tidy_preview()["rows"]
    assert len(rows) == 2
    stop_after_the_first_move(api, monkeypatch)
    f = wait_job(api, rec, api.tidy_up([[r["file_id"], r["from_path"]] for r in rows]))
    assert (f.ok, f.problem) == (False, "stopped")
    assert f.result["stopped"] is True and f.result["moved"] == 1 and f.result["title"] == "Tidy-up"
    assert [s["text"] for s in f.result["skipped"]] == ["Not moved: the moves were stopped first"]


def test_a_stopped_undo_delivers_its_result_too(root, monkeypatch):
    api, rec = make_api(root)
    place_elsewhere(root, "t1", "t2")
    rows = api.tidy_preview()["rows"]
    done = wait_job(api, rec, api.tidy_up([[r["file_id"], r["from_path"]] for r in rows]))
    assert done.ok and done.result["moved"] == 2
    stop_after_the_first_move(api, monkeypatch)
    f = wait_job(api, rec, api.undo_moves(done.result["batch_id"]))
    assert (f.ok, f.problem) == (False, "stopped")
    assert f.result["stopped"] is True and f.result["moved"] == 1 and f.result["title"] == "Undo of: Tidy-up"
    assert f.result["headline"].startswith("Moved 1 file back.")


def save(api, rec, files):
    return wait_job(api, rec, api.save_playlists(SWAPPED, api.playlists()["version"], files))


def test_save_with_move_saves_then_moves_the_chosen_files(root):
    api, rec = make_api(root)
    row = swapped_preview(api, rec)[0]
    f = save(api, rec, {"choice": "move", "renames": [], "moves": moves(row)})
    assert f.ok and f.result["version"] == api.playlists()["version"]
    assert [b["title"] for b in f.result["batches"]] == ["Saved playlists"] and f.result["batches"][0]["moved"] == 1
    assert load_state(root)["tracks"]["t2"]["path"].startswith("Library/Powertrance/")
    assert root.playlists_file.read_text().index("Powertrance") < root.playlists_file.read_text().index("Hard_Bounce")
    assert any(type(e).__name__ == "MovesProgress" for e in rec.events)
    assert api.move_batches()["batches"][0]["title"] == "Saved playlists"


def test_save_with_leave_makes_the_files_the_users_and_a_tidy_up_lists_them_apart(root):
    api, rec = make_api(root)
    swapped_preview(api, rec)
    f = save(api, rec, {"choice": "leave", "renames": [], "moves": []})
    assert f.ok and f.result["batches"] == []
    assert load_state(root)["tracks"]["t2"]["path"] == LOSSY
    page = api.tidy_preview()
    assert [(r["track_id"], r["yours"], r["ticked"]) for r in page["rows"]] == [("t2", True, False)]
    assert page["ticked"] == 0 and page["yours"]["movable"] == 1
    assert api.playlists()["tidy"] == {"waiting": 0}


def test_save_without_a_choice_only_saves(root):
    api, rec = make_api(root)
    f = save(api, rec, None)
    assert f.ok and f.result["batches"] == [] and load_state(root)["tracks"]["t2"]["path"] == LOSSY


def test_a_stopped_save_still_delivers_the_batches_so_far(root, monkeypatch):
    api, rec = make_api(root)
    place_elsewhere(root, "t1")  # a second file the order puts elsewhere
    rows = [*swapped_preview(api, rec), *api.tidy_preview()["rows"]]
    assert {r["track_id"] for r in rows} == {"t1", "t2"}
    stop_after_the_first_move(api, monkeypatch)
    f = save(api, rec, {"choice": "move", "renames": [], "moves": [m for r in rows for m in moves(r)]})
    assert (f.ok, f.problem) == (False, "stopped")
    assert root.playlists_file.read_text().index("Powertrance") < root.playlists_file.read_text().index("Hard_Bounce")
    assert f.result["version"] == api.playlists()["version"]
    [batch] = f.result["batches"]
    assert batch["stopped"] is True and batch["moved"] == 1 and batch["title"] == "Saved playlists"


def test_a_save_that_fails_after_the_file_was_written_still_delivers_the_new_version(root, monkeypatch):
    api, rec = make_api(root)
    row = swapped_preview(api, rec)[0]
    old = api.playlists()["version"]

    def boom(*args, **kwargs):
        raise RuntimeError("the records broke")
    monkeypatch.setattr(tidy, "after_save", boom)
    f = save(api, rec, {"choice": "move", "renames": [], "moves": moves(row)})
    assert not f.ok and f.problem != "stopped"
    new = api.playlists()["version"]
    assert new != old and f.result == {"version": new, "batches": []}  # the page can save again from here


def test_save_refuses_a_malformed_choice_before_anything_starts(root):
    api, rec = make_api(root)
    version = api.playlists()["version"]
    for bad in ("move", {"choice": "x"}, {"choice": "move", "moves": [[1]]}, {"choice": "move", "renames": [["a"]]},
                {"choice": "move", "renames": [["a/b", "c"]]}, {"choice": "move", "moves": "x"}):
        assert api.save_playlists(SWAPPED, version, bad)["kind"] == "refused", bad
    assert root.playlists_file.read_text() == PLAYLISTS and api._jobs.current is None


def test_save_can_rename_the_folder_on_disk_and_move_the_rest(root):
    api, rec = make_api(root)
    refreshed(api, rec)
    renamed = [{"folder": "Hard_New", "link": HARD[1], "enabled": True}, {"folder": "Powertrance", "link": POWER[1],
                                                                          "enabled": True}]
    change = api.preview_playlist_change(renamed)
    assert [(r["from"], r["to"], r["offered"]) for r in change["renames"]] == [("Hard_Bounce", "Hard_New", True)]
    assert {r["by_rename"] for r in change["tidy"]["rows"]} == {"Hard_Bounce"}
    sent = [m for r in change["tidy"]["rows"] for m in moves(r)]
    f = wait_job(api, rec, api.save_playlists(renamed, api.playlists()["version"], {
        "choice": "move", "renames": [["Hard_Bounce", "Hard_New"]], "moves": sent}))
    assert f.ok and [b["title"] for b in f.result["batches"]][0] == "Renamed Hard_Bounce to Hard_New"
    assert (root.library / "Hard_New").is_dir() and not (root.library / "Hard_Bounce").exists()
    assert load_state(root)["tracks"]["t2"]["path"] == LOSSY.replace("Hard_Bounce", "Hard_New")
