"""The bridge side of issue 33 stage B (plan rekordbox B §4, §5.2 B7): upgrades as lists, the Same track batch as a job
with progress, Stop and Resume, `rekordbox_open` as a problem, Upgrade all, batch undo, the batch check item on
To-do, the upgrade block's new fields and the cached rekordbox state. A fixture rekordbox and a tmp music folder
(`batch_helpers.make_lib`); the services are replaced, so nothing real is touched."""
from __future__ import annotations

import pytest

from batch_helpers import DIFFERENT, make_lib, needs_ffmpeg
from convert_helpers import EXACT
from discjockey import db, rekordbox
from discjockey.events import BatchProgress
from discjockey.library import load_state
from hub_helpers import make_api, wait_job

pytestmark = needs_ffmpeg


class Rekordbox:
    """The hub's view of rekordbox for one test: whether it runs, and the fixture library."""

    def __init__(self, lib, running=False):
        self.lib, self.running = lib, running

    def services(self, **kw):
        return {"compare": lambda a, b: EXACT, "rekordbox_running": lambda: self.running,
                "rekordbox_place": lambda: self.lib.place, **kw}


@pytest.fixture
def hub(tmp_path, monkeypatch):
    def build(kinds, running=False, **kw):
        lib = make_lib(tmp_path, monkeypatch, kinds)
        rb = Rekordbox(lib, running)
        api, rec = make_api(lib.paths, **rb.services(**kw))
        return lib, rb, api, rec
    return build


def group(api, key, show_hidden=False):
    return next((g for g in api.todo("all", show_hidden)["groups"] if g["key"] == key), None)


def progress(rec):
    return [(e.batch_id, e.done, e.total, e.track_id) for e in rec.events if isinstance(e, BatchProgress)]


def test_upgrade_takes_a_list_of_song_keys(hub):
    lib, rb, api, rec = hub(["mp3"])
    for bad in ("t0aaaaaaa", [], [3], None, ["t0aaaaaaa", ""]):
        assert api.upgrade(bad, "swap")["kind"] == "refused"
    assert api.upgrade(lib.tracks, "explode")["kind"] == "refused"
    assert api.undo_upgrade("t0aaaaaaa")["kind"] == "refused"
    assert api.rekordbox_checked([])["kind"] == "refused"
    assert api.batch_resume(99)["kind"] == "refused" and api.batch_undo(True)["kind"] == "refused"


def test_same_track_for_a_list_is_one_batch_with_progress(hub):
    lib, rb, api, rec = hub(["mp3", "aiff"])
    f = wait_job(api, rec, api.upgrade(lib.tracks, "swap"))
    assert f.ok and f.kind == "upgrade_batch"
    r = f.result
    assert (r["state"], r["total"], r["done"], r["skipped"], r["failed"], r["recovered"]) == ("done", 2, 2, 0, 0, [])
    assert set(r) == {"batch", "state", "stop_reason", "total", "done", "skipped", "failed", "results", "backup",
                      "recovered"}
    assert [i["state"] for i in r["results"]] == ["done", "done"] and r["backup"]
    assert [p[1:] for p in progress(rec)] == [(0, 2, lib.tracks[0]), (1, 2, lib.tracks[1]), (2, 2, None)]
    assert lib.entry(0)["path"].endswith(".aiff") and lib.row(0)["FileType"] == 12
    with db.connect(lib.paths.db_file) as conn:
        assert db.aiff_batch(conn, r["batch"]).started_by == "user"


def test_one_track_is_a_list_of_one_and_a_refusal_keeps_its_words(hub):
    lib, rb, api, rec = hub(["stale"])
    f = wait_job(api, rec, api.upgrade(lib.tracks, "swap"))
    assert (f.ok, f.problem, f.kind) == (False, "refused", "upgrade_batch")
    assert f.result["skipped"] == 1 and f.result["results"][0]["reason"] == "needs_choice"


def test_rekordbox_open_stops_a_batch_and_resume_finishes_it(hub):
    lib, rb, api, rec = hub(["mp3", "mp3"], running=True)
    before = lib.dump()
    f = wait_job(api, rec, api.upgrade(lib.tracks, "swap"))
    assert (f.ok, f.problem) == (False, "rekordbox_open") and "Quit rekordbox" in f.message
    r = f.result
    assert (r["state"], r["stop_reason"], r["done"]) == ("stopped", "rekordbox_open", 0)
    assert [i["state"] for i in r["results"]] == ["planned", "planned"] and lib.dump() == before
    assert group(api, "upgrade_ready")["stopped"] == {"batch_id": r["batch"], "left": 2}
    rb.running = False                                  # the user quit rekordbox
    f = wait_job(api, rec, api.batch_resume(r["batch"]))
    assert f.ok and f.kind == "batch_resume" and (f.result["state"], f.result["done"]) == ("done", 2)
    assert group(api, "upgrade_ready") is None


def test_a_single_track_meeting_rekordbox_open_leaves_nothing_to_resume(hub):
    lib, rb, api, rec = hub(["mp3"], running=True)
    f = wait_job(api, rec, api.upgrade(lib.tracks, "swap"))
    assert (f.ok, f.problem) == (False, "rekordbox_open")
    assert f.result["state"] == "done" and f.result["results"][0]["reason"] == "rekordbox_open"
    ready = group(api, "upgrade_ready")
    assert ready["stopped"] is None and ready["items"][0]["same_track"] is None   # still there to try again


def test_stop_ends_the_batch_after_the_item_in_work_and_resume_does_the_rest(hub):
    stop = []
    lib, rb, api, rec = hub(["mp3", "mp3"], compare=lambda a, b: stop.append(api.stop()) or EXACT)
    f = wait_job(api, rec, api.upgrade(lib.tracks, "swap"))
    assert (f.ok, f.problem, f.message) == (False, "stopped", "Stopped after 1 of 2.")
    assert [i["state"] for i in f.result["results"]] == ["done", "planned"] and f.result["stop_reason"] == "stop"
    assert group(api, "upgrade_ready")["stopped"]["left"] == 1
    f = wait_job(api, rec, api.batch_resume(f.result["batch"]))
    assert f.ok and (f.result["done"], f.result["state"]) == (2, "done")


def test_busy_rekordbox_lock_is_a_busy_problem_with_the_batch(hub):
    from discjockey.rekordbox import session as rbsession
    lib, rb, api, rec = hub(["mp3", "aiff"])
    with rbsession.writer_lock(lib.paths.support):
        f = wait_job(api, rec, api.upgrade(lib.tracks, "swap"))
    assert (f.ok, f.problem, f.message) == (False, "busy", rbsession.BUSY)
    assert (f.result["state"], f.result["stop_reason"]) == ("stopped", "busy")


def test_upgrade_all_takes_what_the_list_counts_and_starts_as_upgrade_all(hub):
    lib, rb, api, rec = hub(["mp3", "aiff", "stale"])
    ready = group(api, "upgrade_ready")
    assert ready["all"] == {"n": 2, "m": 1, "k": 0} and ready["stopped"] is None
    assert [i["same_track"] for i in ready["items"]] == [None, None, "needs_choice"]
    f = wait_job(api, rec, api.upgrade_all())
    assert f.ok and f.kind == "upgrade_batch" and (f.result["total"], f.result["done"]) == (2, 2)
    with db.connect(lib.paths.db_file) as conn:
        assert db.aiff_batch(conn, f.result["batch"]).started_by == "upgrade_all"
    assert group(api, "upgrade_ready")["all"] == {"n": 0, "m": 1, "k": 0}
    assert api.upgrade_all() == {"ok": False, "kind": "refused", "message": "None of these can be upgraded right now."}


def test_the_checks_of_a_batch_are_one_item_and_batch_undo_puts_them_back(hub):
    lib, rb, api, rec = hub(["mp3", "aiff", "mp3_free"])
    r = wait_job(api, rec, api.upgrade(lib.tracks, "swap")).result
    todo = api.todo()
    check = group(api, "rekordbox_check")
    [item] = check["items"]
    assert item["key"] == item["track_id"] == f"batch:{r['batch']}" and item["group"] == "rekordbox_check"
    b = item["batch"]
    assert (b["id"], b["size"], len(b["tracks"])) == (r["batch"], 3, 3) and b["started"]
    assert [t["track_id"] for t in b["tracks"]] == lib.tracks and all(t["can_undo"] for t in b["tracks"])
    assert [t["check"]["batch"] for t in b["tracks"]] == [{"id": r["batch"], "size": 3}] * 3
    mp3, aiff, free = (t["check"] for t in b["tracks"])
    assert (mp3["reason"], mp3["reload_tag"], mp3["rekordbox"]) == ("repointed", True, {"entries": 1, "kept": []})
    assert (aiff["reason"], aiff["rekordbox"]["entries"]) == ("swapped", 1) and free["rekordbox"] is None
    assert todo["chips"]["rekordbox_check"] == 1 and todo["chips"]["all"] == 1       # a batch counts as one to-do
    rb.running = True                                                                  # undo needs rekordbox closed
    f = wait_job(api, rec, api.batch_undo(r["batch"]))
    assert (f.ok, f.problem) == (False, "rekordbox_open") and f.result["undone"] == 0
    assert {x["state"] for x in f.result["results"]} == {"waiting"}
    rb.running = False
    f = wait_job(api, rec, api.batch_undo(r["batch"]))
    assert f.ok and f.kind == "batch_undo" and (f.result["batch"], f.result["undone"], f.result["total"]) == (r["batch"], 3, 3)
    assert [x["track"] for x in f.result["results"]] == lib.tracks[::-1]               # newest first
    assert group(api, "rekordbox_check") is None and group(api, "upgrade_ready")["all"]["n"] == 3


def test_undo_upgrade_takes_a_list_and_fails_refused_when_nothing_could_be_undone(hub):
    lib, rb, api, rec = hub(["mp3", "aiff"])
    wait_job(api, rec, api.upgrade(lib.tracks, "swap"))
    f = wait_job(api, rec, api.undo_upgrade(lib.tracks))
    assert f.ok and f.kind == "undo_upgrade" and (f.result["undone"], f.result["batch"]) == (2, None)
    f = wait_job(api, rec, api.undo_upgrade(lib.tracks[:1]))                  # nothing left to undo
    assert (f.ok, f.problem) == (False, "refused") and f.message == f.result["results"][0]["message"]
    f = wait_job(api, rec, api.undo_upgrade(lib.tracks))
    assert (f.ok, f.problem, f.message) == (False, "refused", "None of these could be undone.")


def test_checked_for_a_list_ends_their_undo(hub):
    lib, rb, api, rec = hub(["mp3", "aiff"])
    wait_job(api, rec, api.upgrade(lib.tracks, "swap"))
    f = wait_job(api, rec, api.rekordbox_checked([*lib.tracks, "nope"]))
    assert f.ok and f.kind == "rekordbox_checked"
    assert (f.result["checked"], f.result["not_checked"]) == (lib.tracks, ["nope"])
    assert all(load_state(lib.paths)["tracks"][t]["rekordbox_check"] is None for t in lib.tracks)
    f = wait_job(api, rec, api.rekordbox_checked(lib.tracks))
    assert (f.ok, f.problem) == (False, "changed")


def test_new_track_and_discard_run_a_list_one_after_the_other(hub):
    lib, rb, api, rec = hub(["mp3", "mp3", "mp3"])
    f = wait_job(api, rec, api.upgrade([*lib.tracks[:2], "nope"], "discard"))
    assert f.ok and f.kind == "upgrade_discard" and f.result["batch"] is None
    assert (f.result["total"], f.result["done"], f.result["skipped"]) == (3, 2, 1)
    assert [(i["state"], i["reason"]) for i in f.result["results"]] == [("done", None)] * 2 + [("skipped", "no_upgrade")]
    assert [p[1:] for p in progress(rec)][-1] == (3, 3, None) and progress(rec)[0][0] == 0
    assert not lib.entry(0)["upgrade"] and lib.entry(2)["upgrade"]
    api.todo()                                                                    # the page shows the track
    f = wait_job(api, rec, api.upgrade(lib.tracks[2:], "add_new"))               # one track: the old single-track call
    assert f.ok and f.kind == "upgrade_add_new" and f.result["done"] == 1 and f.result["results"][0]["path"]
    f = wait_job(api, rec, api.upgrade(lib.tracks[:1], "discard"))               # no upgrade waits any more
    assert (f.ok, f.problem) == (False, "changed")


def test_stop_between_the_tracks_of_a_list_keeps_the_rest_planned(hub):
    lib, rb, api, rec = hub(["mp3", "mp3"], compare=lambda a, b: (api.stop(), EXACT)[1])
    f = wait_job(api, rec, api.upgrade(lib.tracks, "add_new"))
    assert (f.ok, f.problem, f.message) == (False, "stopped", "Stopped after 1 of 2."), f.result
    assert [i["state"] for i in f.result["results"]] == ["done", "planned"], f.result["results"]
    assert f.result["batch"] is None


def test_the_upgrade_block_says_how_same_track_goes_and_why_not(hub):
    lib, rb, api, rec = hub(["mp3", "aiff", "stale"])
    ups = [api.track(t)["track"]["upgrade"] for t in lib.tracks]
    assert [(u["swap_possible"], u["swap_how"], u["why_not"]) for u in ups] == [
        (True, "new_aiff", None), (True, "in_place", None), (False, "new_aiff", "needs_choice")]
    assert ups[0]["rekordbox"] == {"state": "ready", "running": False} and ups[0]["auto_refused"] is None


def test_an_unreadable_library_blocks_same_track_for_other_formats_only(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff"])
    lib.place.db.write_bytes(b"not a database")
    api, rec = make_api(lib.paths, compare=lambda a, b: EXACT, rekordbox_running=lambda: False,
                        rekordbox_place=lambda: lib.place)
    ups = [api.track(t)["track"]["upgrade"] for t in lib.tracks]
    assert [(u["swap_possible"], u["why_not"]) for u in ups] == [(False, "rekordbox_unreadable"), (True, None)]
    assert ups[0]["rekordbox"]["state"] == "unreadable"
    assert group(api, "upgrade_ready")["all"] == {"n": 1, "m": 0, "k": 1}


def test_the_rekordbox_state_is_read_once_per_change_of_master_db(hub, monkeypatch):
    lib, rb, api, rec = hub(["mp3"])
    calls = []
    real = rekordbox.status
    monkeypatch.setattr(rekordbox, "status", lambda *a, **k: calls.append(1) or real(*a, **k))
    api.todo(), api.track(lib.tracks[0]), api.todo()
    assert len(calls) == 1
    rb.running = True                                       # rekordbox opened: another answer
    api.todo()
    assert len(calls) == 2
    with open(lib.place.db, "ab") as f:                     # master.db changed (size and time)
        f.write(b"\0")
    api.todo()
    assert len(calls) == 3
    api.todo()
    assert len(calls) == 3


def test_the_state_is_not_read_while_any_write_job_runs(hub, monkeypatch):
    """A sync, import or tidy-up runs the recovery first, which can finish a rekordbox write: no job is known to
    leave rekordbox alone, so the cached answer stays while one runs."""
    lib, rb, api, rec = hub(["mp3"])
    calls = []
    real = rekordbox.status
    monkeypatch.setattr(rekordbox, "status", lambda *a, **k: calls.append(1) or real(*a, **k))
    api.todo()
    assert len(calls) == 1
    rb.running = True                                       # rekordbox opened ...
    with open(lib.place.db, "ab") as f:                     # ... and master.db changed
        f.write(b"\0")
    with monkeypatch.context() as m:
        m.setattr(api._jobs, "running", lambda: type("J", (), {"kind": "sync"})())
        answer = api.todo()
        assert len(calls) == 1 and answer["groups"]         # the last value, no open
    api.todo()                                              # the job is over: the new state is read
    assert len(calls) == 2


def test_upgrade_all_tried_again_leaves_one_stopped_batch(hub):
    lib, rb, api, rec = hub(["mp3", "mp3"], running=True)
    first = wait_job(api, rec, api.upgrade_all()).result
    second = wait_job(api, rec, api.upgrade_all()).result
    assert first["batch"] != second["batch"] and second["state"] == "stopped"
    assert group(api, "upgrade_ready")["stopped"] == {"batch_id": second["batch"], "left": 2}   # one Resume
    with db.connect(lib.paths.db_file) as conn:
        old = db.aiff_batch(conn, first["batch"])
    assert (old.state, [i.reason for i in old.items]) == ("done", ["later_batch"] * 2)
    rb.running = False
    f = wait_job(api, rec, api.batch_resume(second["batch"]))
    assert f.ok and f.result["done"] == 2
    assert api.batch_resume(first["batch"])["kind"] == "refused"          # nothing to resume on the first one


def test_no_rekordbox_on_this_mac_is_an_answer_not_a_problem(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3"])
    api, rec = make_api(lib.paths, compare=lambda a, b: EXACT, rekordbox_running=lambda: False,
                        rekordbox_place=lambda: None)
    u = api.track(lib.tracks[0])["track"]["upgrade"]
    assert (u["swap_possible"], u["rekordbox"]["state"]) == (True, "none")
    f = wait_job(api, rec, api.upgrade(lib.tracks, "swap"))
    assert f.ok and f.result["done"] == 1 and f.result["results"][0]["rekordbox"] is None
    assert DIFFERENT.result == "different"                  # (the stale kind above stores this alignment)
