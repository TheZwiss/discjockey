"""The bridge side of issue 33 stage C (plan rekordbox stage C §4, §5 C4): Auto-upgrade's switch (`set_auto_upgrade`,
`setup_status().auto_upgrade`), `rekordbox_status`, the Sync page's `sync_preview().auto_upgrade`, the marks on a parked
upgrade (`upgrade_block.auto_refused` / `auto_waits`, To-do's row details), the To-do item of an Auto-upgrade batch, the
end screen's `run_detail().auto_upgrade`, and a hub sync that passes its services and its Stop to the phase. A fixture
rekordbox and a tmp music folder (`batch_helpers.make_lib`); the services are replaced, so nothing real is touched."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from batch_helpers import make_lib, needs_ffmpeg, prepared
from convert_helpers import EXACT
from discjockey import auto_upgrade, batches, library, report
from discjockey.events import BatchProgress
from discjockey.hub import views
from discjockey.library import load_state, save_state
from discjockey.models import Question, SourceTrack
from discjockey.rekordbox.locate import Place
from discjockey.settings import Settings, load_settings, save_settings
from hub_helpers import fake_spotify, make_api, make_root, make_unbound_api, wait_job

NOW = datetime(2026, 11, 9, 21, 4)


def group(api, key="upgrade_ready"):
    return next((g for g in api.todo("all", False)["groups"] if g["key"] == key), None)


def details(api):
    return [i["detail"] for i in group(api)["items"]]


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


def mark(lib, i, **fields):
    """Puts `fields` on the parked upgrade of song `i` (the records the phase writes)."""
    state = load_state(lib.paths)
    state["tracks"][lib.tracks[i]]["upgrade"].update(fields)
    save_state(lib.paths, state)


def preview(api, lib, questions=()):
    """The Sync page has a preview: the library's records as the plan state, without a playlist read."""
    api._store.ready(prepared(lib, questions=questions), NOW)
    return api.sync_preview()


# --- the switch ---

def test_the_switch_is_on_by_default_and_saves_at_once(tmp_path):
    paths = make_root(tmp_path)
    api, rec = make_api(paths)
    assert api.setup_status()["auto_upgrade"] is True
    f = wait_job(api, rec, api.set_auto_upgrade(False))
    assert (f.ok, f.kind, f.result) == (True, "set_auto_upgrade", {})
    assert load_settings(paths.settings_file).auto_upgrade is False and api.setup_status()["auto_upgrade"] is False
    assert wait_job(api, rec, api.set_auto_upgrade(True)).ok
    assert load_settings(paths.settings_file).auto_upgrade is True


def test_the_switch_changes_nothing_else_in_settings(tmp_path):
    paths = make_root(tmp_path)
    save_settings(paths.settings_file, Settings(qobuz_skipped=True, read_liked_music=False))
    api, rec = make_api(paths)
    assert wait_job(api, rec, api.set_auto_upgrade(False)).ok
    assert load_settings(paths.settings_file) == Settings(qobuz_skipped=True, auto_upgrade=False)


@pytest.mark.parametrize("bad", ["yes", 1, None, [True]])
def test_the_switch_must_be_true_or_false(tmp_path, bad):
    api, _ = make_api(make_root(tmp_path))
    answer = api.set_auto_upgrade(bad)
    assert answer == {"ok": False, "kind": "refused", "message": "on must be true or false."}


def test_a_settings_file_the_sync_cannot_read_shows_the_switch_off(tmp_path):
    paths = make_root(tmp_path)
    paths.settings_file.write_text('{"auto_upgrade": "yes"}')
    api, _ = make_api(paths)
    assert api.setup_status()["auto_upgrade"] is False


def test_the_switch_is_the_setup_wizards_too_without_a_music_folder(tmp_path):
    api, _ = make_unbound_api(tmp_path / "support")
    assert api.setup_status()["auto_upgrade"] is True


# --- rekordbox_status ---

def test_rekordbox_status_answers_the_cached_state_and_asks_whether_it_runs_each_time(hub):
    lib, rb, api, rec = hub(["mp3"])
    assert api.rekordbox_status() == {"ok": True, "state": "ready", "running": False}
    rb.running = True
    assert api.rekordbox_status() == {"ok": True, "state": "ready", "running": True}
    rb.running = False
    assert api.rekordbox_status()["running"] is False


def test_rekordbox_status_says_none_and_unreadable_and_works_without_a_music_folder(tmp_path, monkeypatch):
    empty = tmp_path / "no rekordbox"
    empty.mkdir()
    api, _ = make_unbound_api(tmp_path / "support", rekordbox_running=lambda: True,
                              rekordbox_place=lambda: Place(empty / "master.db", empty / "share", "override", None))
    assert api.rekordbox_status() == {"ok": True, "state": "none", "running": True}
    lib = make_lib(tmp_path, monkeypatch, ["mp3"])
    lib.place.db.write_bytes(b"not a database")
    api, _ = make_api(lib.paths, rekordbox_running=lambda: False, rekordbox_place=lambda: lib.place)
    assert api.rekordbox_status() == {"ok": True, "state": "unreadable", "running": False}


# --- sync_preview().auto_upgrade ---

@needs_ffmpeg
def test_the_preview_counts_what_the_phase_would_upgrade_and_opens_nothing_of_rekordbox(hub, monkeypatch):
    lib, rb, api, rec = hub(["mp3", "aiff", "stale", "mp3_free"])
    assert api.rekordbox_status()["state"] == "ready"                   # the cached state is the one read open
    opened = []
    real = auto_upgrade.master.open_read
    monkeypatch.setattr(auto_upgrade.master, "open_read", lambda *a, **k: opened.append(1) or real(*a, **k))
    out = preview(api, lib)["auto_upgrade"]
    assert out == {"on": True, "ready": 3}                              # the mp3, the aiff, the free mp3 (not the stale)
    assert group(api)["all"]["n"] == out["ready"]                       # Upgrade all's own count
    planned = auto_upgrade.plan(lib.paths, load_state(lib.paths), set(), Settings(), running=lambda: False,
                                place=lib.place)
    assert len(planned.run) == out["ready"]
    assert opened == [1]                                                # only this test's own plan() call above


@needs_ffmpeg
def test_the_preview_counts_the_upgrades_that_wait_for_rekordbox_too(hub):
    lib, rb, api, rec = hub(["mp3", "aiff"], running=True)
    assert preview(api, lib)["auto_upgrade"] == {"on": True, "ready": 2}
    rb.running = False
    assert api.sync_preview()["auto_upgrade"] == {"on": True, "ready": 2}


@needs_ffmpeg
def test_the_preview_is_null_when_the_switch_is_off_or_there_is_no_preview(hub):
    lib, rb, api, rec = hub(["mp3"])
    assert api.sync_preview()["auto_upgrade"] is None and api.sync_preview()["empty"] == "no_preview"
    assert preview(api, lib)["auto_upgrade"] == {"on": True, "ready": 1}
    save_settings(lib.paths.settings_file, Settings(auto_upgrade=False))
    assert api.sync_preview()["auto_upgrade"] is None
    lib.paths.settings_file.write_text('{"auto_upgrade": 7}')          # a file the sync would refuse
    assert api.sync_preview()["auto_upgrade"] is None


@needs_ffmpeg
def test_a_song_waiting_for_an_answer_and_a_hidden_one_are_not_counted(hub):
    lib, rb, api, rec = hub(["mp3", "aiff", "aiff"])
    state = load_state(lib.paths)
    state["tracks"][lib.tracks[2]]["hidden"] = True
    save_state(lib.paths, state)
    track = SourceTrack(lib.tracks[1], "Song 1", ("Artist",), "Album", None, 30000, None)
    question = Question(lib.tracks[1], track, "A", "own:1", 1, "artist", None)
    assert preview(api, lib, [question])["auto_upgrade"]["ready"] == 1


@needs_ffmpeg
def test_a_recorded_refusal_counts_as_holding_when_only_a_read_of_rekordbox_could_tell(hub):
    lib, rb, api, rec = hub(["mp3", "mp3", "aiff"])
    mark(lib, 0, auto_refused={"reason": "not_analysed", "message": "m", "at": "2026-11-09T21:04:00", "anlz": {},
                               "free": None, "files": None})
    mark(lib, 1, auto_refused={"reason": "space", "message": "m", "at": "2026-11-09T21:04:00", "anlz": None,
                               "free": 10**15, "files": None})                  # drives have less free: it holds
    assert preview(api, lib)["auto_upgrade"]["ready"] == 1                       # only the aiff
    mark(lib, 1, auto_refused={"reason": "space", "message": "m", "at": "2026-11-09T21:04:00", "anlz": None,
                               "free": 1, "files": None})                       # more is free now: tried again
    assert api.sync_preview()["auto_upgrade"]["ready"] == 2


@needs_ffmpeg
def test_the_preview_ready_equals_what_the_phase_waits_for_with_rekordbox_running(hub):
    lib, rb, api, rec = hub(["mp3", "mp3", "mp3_plain", "aiff"], running=True)
    mark(lib, 2, auto_refused={"reason": "not_analysed", "message": "m", "at": "2026-11-09T21:04:00", "anlz": {"x": 1},
                               "free": None, "files": None})                    # held: not read while rekordbox runs
    mark(lib, 1, auto_refused={"reason": "space", "message": "m", "at": "2026-11-09T21:04:00", "anlz": None,
                               "free": 10**15, "files": None})
    ready = preview(api, lib)["auto_upgrade"]["ready"]
    planned = auto_upgrade.plan(lib.paths, load_state(lib.paths), set(), Settings(), running=lambda: True,
                                place=lib.place)
    assert ready == len(planned.waiting) == 2 and len(planned.refused) == 2     # the end screen says "2 wait" too


# --- the marks on a parked upgrade ---

@needs_ffmpeg
def test_the_upgrade_block_carries_the_refusal_and_the_waiting_mark(hub):
    lib, rb, api, rec = hub(["mp3", "aiff"])
    t = lambda i: api.track(lib.tracks[i])["track"]["upgrade"]       # noqa: E731
    assert (t(0)["auto_refused"], t(0)["auto_waits"]) == (None, False)
    mark(lib, 0, auto_refused={"reason": "timing", "message": "It would not line up.", "at": "2026-11-09T21:04:00",
                               "anlz": {"a": 1}, "free": None, "files": None})
    mark(lib, 1, auto_waits="2026-11-09T21:04:00")
    assert t(0)["auto_refused"] == {"reason": "timing", "message": "It would not line up.",
                                    "at": "2026-11-09T21:04:00"}
    assert (t(1)["auto_waits"], t(1)["auto_refused"]) == (True, None)
    save_settings(lib.paths.settings_file, Settings(auto_upgrade=False))
    assert t(1)["auto_waits"] is False                                    # the switch off hides the mark
    assert t(0)["auto_refused"]["reason"] == "timing"                     # a refusal stays what it was
    lib.paths.settings_file.write_text('{"auto_upgrade": 7}')
    assert t(1)["auto_waits"] is False


@needs_ffmpeg
def test_the_waiting_mark_shows_only_while_same_track_could_run(hub):
    lib, rb, api, rec = hub(["mp3", "stale"])
    mark(lib, 0, auto_waits="2026-11-09T21:04:00")
    mark(lib, 1, auto_waits="2026-11-09T21:04:00")                       # a different edit: it needs a choice
    ups = [api.track(t)["track"]["upgrade"] for t in lib.tracks]
    assert [(u["swap_possible"], u["auto_waits"]) for u in ups] == [(True, True), (False, False)]


@needs_ffmpeg
def test_todo_rows_say_waiting_and_say_why_a_track_was_not_upgraded(hub):
    lib, rb, api, rec = hub(["mp3", "mp3", "mp3", "mp3", "aiff", "stale"])
    base = {"at": "2026-11-09T21:04:00", "anlz": {}, "free": None, "files": None}
    mark(lib, 0, auto_waits="2026-11-09T21:04:00")
    mark(lib, 1, auto_refused={**base, "reason": "timing", "message": "x"})
    mark(lib, 2, auto_refused={**base, "reason": "not_analysed", "message": "x"})
    mark(lib, 3, auto_refused={**base, "reason": "cloud", "message": "x"})
    mark(lib, 4, auto_refused={**base, "reason": "space", "message": "x"})
    mark(lib, 5, auto_refused={**base, "reason": "needs_choice", "message": "x"},
         alignment={"result": "unknown", "text": ""})                  # the two files could not be compared
    words = {i["track_id"]: i["detail"] for i in group(api)["items"]}
    assert [words[t] for t in lib.tracks] == [
        "Waits for rekordbox to be closed",
        "Not upgraded at your sync · couldn't line it up",
        "Not upgraded at your sync · not analysed in rekordbox",
        "Not upgraded at your sync · in Cloud Library Sync",
        "Not upgraded at your sync · not enough free space",
        "Not upgraded at your sync · couldn't compare it"]


@needs_ffmpeg
def test_todo_waiting_beats_a_refusal_and_the_switch_off_shows_the_old_line(hub):
    lib, rb, api, rec = hub(["mp3", "mp3"])
    mark(lib, 0, auto_waits="2026-11-09T21:04:00",
         auto_refused={"reason": "timing", "message": "x", "at": "a", "anlz": {}, "free": None, "files": None})
    assert details(api)[0] == "Waits for rekordbox to be closed"
    save_settings(lib.paths.settings_file, Settings(auto_upgrade=False))
    assert details(api)[0] == "Not upgraded at your sync · couldn't line it up"      # the refusal is a fact
    mark(lib, 0, auto_refused=None)
    assert details(api)[0] == "Lossless ready · cues can stay"                      # waiting is not shown while off


@needs_ffmpeg
def test_a_refusal_that_the_file_has_outgrown_is_not_shown(hub):
    lib, rb, api, rec = hub(["mp3"])
    mark(lib, 0, auto_refused={"reason": "needs_choice", "message": "x", "at": "a", "anlz": None, "free": None,
                               "files": {}}, alignment={"result": "different", "text": "no"})
    assert details(api) == ["Lossless ready · different edit"]


# --- the To-do item of an Auto-upgrade batch ---

@needs_ffmpeg
def test_the_checks_of_an_auto_upgrade_batch_are_named_for_the_sync(hub):
    lib, rb, api, rec = hub(["mp3", "aiff", "mp3"])
    options = {"running": lambda: False, "place": lib.place, "compare": lambda a, b: EXACT, "now": lambda: NOW}
    mine = batches.start(lib.paths, [(t, "same_track") for t in lib.tracks[:2]], started_by="auto_upgrade",
                         scope="sync")
    batches.run(lib.paths, mine, state=load_state(lib.paths), **options)
    by_hand = batches.start(lib.paths, [(lib.tracks[2], "same_track")], started_by="user")
    batches.run(lib.paths, by_hand, state=load_state(lib.paths), **options)
    items = {i["key"]: i for i in group(api, "rekordbox_check")["items"] if i.get("batch")}
    assert items == {f"batch:{mine}": items[f"batch:{mine}"]}
    item = items[f"batch:{mine}"]
    assert item["batch"]["started_by"] == "auto_upgrade" and item["batch"]["size"] == 2
    assert item["detail"].endswith(" · Upgraded during your sync") and "Same track" not in item["detail"]
    single = next(i for i in group(api, "rekordbox_check")["items"] if i["track_id"] == lib.tracks[2])
    assert "batch" not in single or single.get("batch") is None


@needs_ffmpeg
def test_the_checks_of_a_batch_started_by_hand_still_say_same_track(hub):
    lib, rb, api, rec = hub(["mp3", "aiff"])
    f = wait_job(api, rec, api.upgrade(lib.tracks, "swap"))
    assert f.ok
    item = next(i for i in group(api, "rekordbox_check")["items"] if i.get("batch"))
    assert item["batch"]["started_by"] == "user" and item["detail"].endswith(" · Same track")


# --- the end screen ---

def test_a_run_carries_its_auto_upgrade_block_and_the_line(tmp_path):
    paths = make_root(tmp_path)
    api, _ = make_api(paths)
    block = {"batch": 4, "backup": "2026-11-09T21-04-11Z", "done": 2, "waiting": 1, "refused": 0, "failed": 0,
             "stopped": False, "dry_run": False,
             "results": [{"track": "t2", "name": "A – B", "state": "done", "reason": None, "message": "m",
                          "how": "in_place"},
                         {"track": "t1", "name": "C – D", "state": "waiting", "reason": "rekordbox_open",
                          "message": "w", "how": None}]}
    data = {"started": "2026-11-09T21:00:00", "finished": "2026-11-09T21:05:00", "exit_code": 0, "auto_upgrade": block,
            "results": [{"section": "upgraded", "folder": "Hard_Bounce", "artist": "A", "title": "B",
                         "track_id": "t2", "status": "lossless", "note": "n", "path": None},
                        {"section": "upgrade_waits", "folder": "Hard_Bounce", "artist": "C", "title": "D",
                         "track_id": "t1", "status": "lossless", "note": "w", "path": None}]}
    summary = views.run_summary("2026-11-09_210000", data)
    assert summary["auto_upgrade"] == {**block, "line": "Upgraded 2 tracks; your cues stayed. 1 waits for rekordbox "
                                                        "to be closed."}
    assert summary["counts"] == {"lossless": 1, "lossy": 0, "problems": 0, "moved": 0}   # an upgrade is lossless
    detail = views.run_detail("2026-11-09_210000", data, load_state(paths))
    assert detail["auto_upgrade"]["line"] == summary["auto_upgrade"]["line"]
    assert [r["section"] for s in detail["sections"].values() for r in s] == ["upgraded", "upgrade_waits"]
    assert detail["for_rekordbox"] == {"new_files": 0, "folders": []}                    # not a new file for rekordbox


def test_a_run_without_the_block_has_none_and_an_empty_block_has_no_line():
    plain = views.run_summary("2026-11-09_210000", {"started": "2026-11-09T21:00:00", "exit_code": 0, "results": []})
    assert plain["auto_upgrade"] is None
    empty = {"batch": None, "backup": None, "done": 0, "waiting": 0, "refused": 0, "failed": 0, "stopped": False,
             "dry_run": False, "results": []}
    out = views.run_summary("2026-11-09_210000", {"exit_code": 0, "results": [], "auto_upgrade": empty})
    assert out["auto_upgrade"] == {**empty, "line": None}


def test_the_report_the_engine_writes_reads_back_through_run_detail(tmp_path):
    paths = make_root(tmp_path)
    log = report.RunLog(NOW)
    block = {"batch": None, "backup": None, "done": 0, "waiting": 0, "refused": 1, "failed": 0, "stopped": False,
             "dry_run": False, "results": [{"track": "t2", "name": "A – B", "state": "refused", "reason": "timing",
                                            "message": "x", "how": None}]}
    log.auto_upgrade = block
    path = report.write_run(paths, log, NOW, 0, load_state(paths))
    api, _ = make_api(paths)
    run_id = path.stem
    out = api.run(run_id)
    assert out["ok"] and out["run"]["auto_upgrade"]["line"] == "1 upgrade couldn't go in; To-do says why."
    assert api.runs()["runs"][0]["auto_upgrade"]["refused"] == 1


# --- a hub sync passes its services and its Stop to the phase ---

PLAYLIST_ID = "0DiscjockeyExampleList"


@pytest.fixture
def synced(tmp_path, monkeypatch):
    """A hub whose playlist (the lib's folder `A`) holds exactly its songs, read once: a plan with no action."""
    def build(kinds, running=False, **kw):
        lib = make_lib(tmp_path, monkeypatch, kinds)
        tracks = {PLAYLIST_ID: [SourceTrack(t, f"Song {i}", ("Artist",), "Album", None, 30000, None)
                                for i, t in enumerate(lib.tracks)]}
        fake_spotify(monkeypatch, tracks)
        lib.paths.playlists_file.write_text(f"A = https://open.spotify.com/playlist/{PLAYLIST_ID}\n")
        rb = Rekordbox(lib, running)
        api, rec = make_api(lib.paths, **rb.services(**kw))
        assert wait_job(api, rec, api.refresh()).ok
        return lib, rb, api, rec
    return build


@needs_ffmpeg
def test_a_hub_sync_with_rekordbox_open_upgrades_nothing_and_marks_the_waits(synced):
    lib, rb, api, rec = synced(["mp3", "aiff"], running=True)
    before = (lib.music(), lib.dump())
    f = wait_job(api, rec, api.start_sync([]))
    assert f.ok and f.result["exit_code"] == 0
    assert (lib.music(), lib.dump()) == before
    block = json.loads(open(f.result["report"].replace(".md", ".json")).read())["auto_upgrade"]
    assert (block["batch"], block["done"], block["waiting"]) == (None, 0, 2)
    assert all(load_state(lib.paths)["tracks"][t]["upgrade"]["auto_waits"] for t in lib.tracks)
    assert [d for d in details(api)] == ["Waits for rekordbox to be closed"] * 2
    assert api.runs()["runs"][0]["auto_upgrade"]["line"] == "2 upgrades wait for rekordbox to be closed."


@needs_ffmpeg
def test_a_hub_sync_with_rekordbox_closed_upgrades_as_one_batch_with_progress(synced):
    lib, rb, api, rec = synced(["mp3", "aiff"])
    f = wait_job(api, rec, api.start_sync([]))
    assert f.ok and f.result["exit_code"] == 0
    block = json.loads(open(f.result["report"].replace(".md", ".json")).read())["auto_upgrade"]
    assert (block["done"], block["waiting"]) == (2, 0) and lib.batch(block["batch"]).started_by == "auto_upgrade"
    assert [(e.done, e.total) for e in rec.events if isinstance(e, BatchProgress)] == [(0, 2), (1, 2), (2, 2)]
    assert group(api) is None                                                       # nothing waits in Upgrade ready


@needs_ffmpeg
def test_stop_reaches_the_phase_of_a_sync_that_had_nothing_else_to_do(synced):
    stops = []
    lib, rb, api, rec = synced(["mp3", "mp3"], compare=lambda a, b: stops.append(api.stop()) or EXACT)
    f = wait_job(api, rec, api.start_sync([]))
    assert f.ok and f.result["exit_code"] == 130                                    # a Stop ends the sync as stopped
    block = json.loads(open(f.result["report"].replace(".md", ".json")).read())["auto_upgrade"]
    assert (block["done"], block["waiting"], block["stopped"]) == (1, 1, True)
    assert [r["reason"] for r in block["results"] if r["state"] == "waiting"] == ["not_reached"]
    assert group(api)["all"]["n"] == 1
    assert library.load_state(lib.paths)["tracks"][lib.tracks[1]]["upgrade"]
    assert group(api)["stopped"] is None                                            # no Resume offered for the batch
