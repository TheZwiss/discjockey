"""The bridge side of issue 33's stage D (plan rekordbox stage D §4, §5 D6b): `track().aiff`, the `aiff_plan` read with its
tag cache, the jobs `convert`, `rename` and `make_aiff` (kind `aiff_batch`), their refusals, a stopped Convert batch
resumed and undone through the unchanged `batch_resume` / `batch_undo` / `undo_upgrade` / `rekordbox_checked`, and the
wiring of D6a's views (the CDJ group's counts and Resume, Upgrade ready's Resume, the Library's `aiff_stopped`). Own
files and a fixture rekordbox in tmp_path (`batch_helpers.make_own_lib`); the services are replaced."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from batch_helpers import make_lib, make_own_lib, needs_ffmpeg
from convert_helpers import EXACT
from discjockey import aiff_plan, audio, batches, db
from discjockey.events import BatchProgress
from hub_helpers import make_api, wait_job

pytestmark = needs_ffmpeg

# make_own_lib's songs, by index: 0 mp3 (in rekordbox), 1 mp3_free, 2 clean (a messy name, in rekordbox), 3 clean_free,
# 4 named (a clean AIFF at its clean name), 5 chain (an AIFF 24/96 at its clean name, in rekordbox)
KINDS = ["mp3", "mp3_free", "clean", "clean_free", "named", "chain"]
NOTHING = "Nothing to change: these are clean AIFFs already."


class Box:
    """The hub's view of rekordbox for one test: whether it runs, and the fixture library."""

    def __init__(self, lib, running=False):
        self.lib, self.running = lib, running

    def services(self):
        return {"compare": lambda a, b: EXACT, "rekordbox_running": lambda: self.running,
                "rekordbox_place": lambda: self.lib.place}


@pytest.fixture
def hub(tmp_path, monkeypatch):
    def build(kinds=KINDS, running=False):
        lib = make_own_lib(tmp_path, monkeypatch, kinds)
        box = Box(lib, running)
        api, rec = make_api(lib.paths, **box.services())
        return lib, box, api, rec
    return build


def progress(rec):
    return [(e.done, e.total, e.track_id) for e in rec.events if isinstance(e, BatchProgress)]


def batch_row(lib, batch_id):
    with db.connect(lib.paths.db_file) as conn:
        return db.aiff_batch(conn, batch_id)


def group(api, key):
    return next((g for g in api.todo("all")["groups"] if g["key"] == key), None)


def cdj_group(api):
    return group(api, "cdj")


def set_rate(lib, i, rate):
    """File i's stored rate: 192 kHz is a file the club players refuse (the CDJ group)."""
    with db.connect(lib.paths.db_file) as conn:
        conn.execute("UPDATE files SET file_rate = ? WHERE id = ?", (rate, db.file_id_at(conn, lib.olds[i])))


def set_kbps(lib, i, kbps):
    """File i's stored bitrate: above 320 kbps is a file the club players refuse (and Convert can still make an AIFF)."""
    with db.connect(lib.paths.db_file) as conn:
        conn.execute("UPDATE files SET file_kbps = ? WHERE id = ?", (kbps, db.file_id_at(conn, lib.olds[i])))


# --- track().aiff ---

def test_a_track_says_what_convert_or_rename_would_do(hub):
    lib, box, api, rec = hub()
    mp3 = api.track(lib.tracks[0])["track"]["aiff"]
    assert set(mp3) == {"action", "why_not", "kind", "from", "to", "name_now", "new_name", "bytes", "lossy", "cdj"}
    assert (mp3["action"], mp3["why_not"], mp3["kind"], mp3["lossy"]) == ("convert", None, "mp3", True)
    assert mp3["to"] == "AIFF · 16-bit · 44.1 kHz" and mp3["from"].startswith("MP3") and mp3["bytes"] > 0
    assert (mp3["name_now"], mp3["new_name"]) == ("Old 0.mp3", "Artist - Song 0.aiff")
    name = api.track(lib.tracks[2])["track"]["aiff"]
    assert (name["action"], name["kind"], name["to"], name["bytes"], name["lossy"]) == ("rename", "name", None, 0, False)
    assert (name["name_now"], name["new_name"]) == ("Messy 2.aiff", "Artist - Song 2.aiff")
    clean = api.track(lib.tracks[4])["track"]["aiff"]
    assert (clean["action"], clean["why_not"], clean["new_name"]) == (None, "named_already", None)
    assert clean["from"] == "AIFF · 16-bit · 44.1 kHz" and clean["name_now"] == "Artist - Song 4.aiff"
    chain = api.track(lib.tracks[5])["track"]["aiff"]
    assert (chain["action"], chain["kind"], chain["name_now"], chain["new_name"]) == \
        ("convert", "aiff_hires", "Artist - Song 5.aiff", "Artist - Song 5.aiff")


def test_a_track_says_why_cdj_refuses_its_file(hub):
    lib, box, api, rec = hub(["clean"])
    set_rate(lib, 0, 192000)
    got = api.track(lib.tracks[0])["track"]["aiff"]
    assert got["cdj"]["short"] and got["cdj"]["words"]


def test_a_track_has_no_answer_without_a_file_for_a_download_or_with_a_better_version_waiting(hub, tmp_path, monkeypatch):
    lib, box, api, rec = hub(["mp3", "mp3_free"])
    (lib.paths.root / lib.olds[1]).unlink()
    assert api.track(lib.tracks[1])["track"]["aiff"] is None
    (tmp_path / "d").mkdir()
    down = make_lib(tmp_path / "d", monkeypatch, ["mp3"])        # a download with a parked upgrade
    api2, _ = make_api(down.paths, **Box(down).services())
    assert api2.track(down.tracks[0])["track"]["aiff"] is None


# --- aiff_plan ---

def test_the_plan_read_answers_every_scope_in_one_shape(hub):
    lib, box, api, rec = hub()
    one = api.aiff_plan({"kind": "tracks", "tracks": [lib.tracks[0], lib.tracks[4]]})["plan"]
    assert set(one) == {"scope", "items", "skipped", "waiting", "kinds", "lossy", "total", "space", "superseded_bytes",
                        "rekordbox"}
    assert (one["scope"]["label"], one["total"], one["lossy"]) == ("Selection", 1, 1)
    assert [s["reason"] for s in one["skipped"]] == ["named_already"]
    assert one["rekordbox"]["needs_closed"] is True
    every = api.aiff_plan({"kind": "lossless", "view": "all"})["plan"]
    assert every["scope"] == {"kind": "lossless", "view": "all", "key": None, "label": "All tracks"}
    assert [i["track"] for i in every["items"]] == [lib.tracks[2], lib.tracks[3], lib.tracks[5]]   # lossy mp3s are not in
    assert every["skipped"] == []
    assert api.aiff_plan({"kind": "cdj"})["plan"]["total"] == 0


@pytest.mark.parametrize("scope", [None, "cdj", {}, {"kind": "all"}, {"kind": "tracks", "tracks": []},
                                   {"kind": "tracks", "tracks": "t0"}, {"kind": "lossless", "view": "elsewhere"},
                                   {"kind": "lossless", "view": "playlist"}, {"kind": "lossless", "view": "folder", "key": 3}])
def test_a_scope_that_is_none_is_refused(hub, scope):
    lib, box, api, rec = hub(["mp3"])
    assert api.aiff_plan(scope)["kind"] == "refused"


def test_the_tags_of_a_file_are_read_once_until_the_file_changes(hub, monkeypatch):
    lib, box, api, rec = hub(["clean", "named"])
    reads = []
    real = audio.file_facts
    monkeypatch.setattr(audio, "file_facts", lambda p: reads.append(p) or real(p))
    scope = {"kind": "lossless", "view": "all"}
    api.aiff_plan(scope)
    first = len(reads)
    assert first >= 2                                        # the two own AIFFs in the library format
    api.aiff_plan(scope)
    api.track(lib.tracks[0])
    assert len(reads) == first                               # the panel again, a details card: no file read
    file = lib.paths.root / lib.olds[0]
    file.write_bytes(file.read_bytes() + b"\0")              # the file changed: its key is new
    api.aiff_plan(scope)
    assert len(reads) > first


# --- the jobs ---

def test_convert_runs_one_aiff_batch_and_lists_what_it_left_as_it_is(hub):
    lib, box, api, rec = hub()
    f = wait_job(api, rec, api.convert([lib.tracks[0], lib.tracks[2], lib.tracks[4]], "library"))
    assert f.ok and f.kind == "aiff_batch"
    r = f.result
    assert (r["state"], r["total"], r["done"], r["skipped"], r["failed"]) == ("done", 3, 2, 1, 0)
    assert [(i["track"], i["state"], i["reason"]) for i in r["results"]] == [
        (lib.tracks[0], "done", None), (lib.tracks[2], "done", None), (lib.tracks[4], "skipped", "named_already")]
    assert r["results"][2]["message"] == "A clean AIFF with its clean name already." and r["backup"]
    row = batch_row(lib, r["batch"])
    assert (row.kind, row.started_by, row.scope) == ("convert", "user", "library:selection")
    assert [i.action for i in row.items] == ["convert", "rename"]
    assert progress(rec)[-1] == (2, 2, None)
    assert lib.entry(0)["path"].endswith(".aiff") and lib.entry(2)["path"] == "Library/A/Artist - Song 2.aiff"
    assert (lib.paths.root / "Superseded").exists()


def test_a_convert_started_in_to_do_says_so_and_a_bad_origin_is_refused(hub):
    lib, box, api, rec = hub()
    assert api.convert([lib.tracks[0]], "sync")["kind"] == "refused"
    for bad in ([], "t0", [3], None):
        assert api.convert(bad)["kind"] == "refused" and api.rename(bad)["kind"] == "refused"
    f = wait_job(api, rec, api.convert([lib.tracks[0], lib.tracks[1]], "todo"))
    assert f.ok and batch_row(lib, f.result["batch"]).scope == "todo:selection"


def test_rename_gives_the_clean_name_only_and_leaves_a_file_that_needs_a_convert(hub):
    lib, box, api, rec = hub()
    f = wait_job(api, rec, api.rename([lib.tracks[2], lib.tracks[0]]))
    assert f.ok and f.kind == "aiff_batch"
    r = f.result
    assert (r["total"], r["done"], r["skipped"]) == (2, 1, 1)
    assert r["results"][1]["reason"] == "needs_convert" and r["results"][1]["action"] == "rename"
    assert batch_row(lib, r["batch"]).kind == "convert" and lib.entry(0)["path"].endswith(".mp3")


def test_a_selection_with_nothing_to_change_is_refused_with_the_engines_words(hub):
    lib, box, api, rec = hub()
    f = wait_job(api, rec, api.convert([lib.tracks[4]]))
    assert (f.ok, f.problem, f.kind) == (False, "refused", "aiff_batch")
    assert f.message == "A clean AIFF with its clean name already."
    assert f.result["batch"] is None and [i["reason"] for i in f.result["results"]] == ["named_already"]
    f = wait_job(api, rec, api.rename([lib.tracks[4], lib.tracks[0]]))     # two songs, none to do
    assert f.message == batches.NOTHING_FILE_ELIGIBLE and f.message != "None of these can be upgraded right now."
    f = wait_job(api, rec, api.rename([lib.tracks[0]]))
    assert f.problem == "refused" and f.result["results"][0]["reason"] == "needs_convert"
    with db.connect(lib.paths.db_file) as conn:
        assert db.aiff_batches(conn)[1] == 0                  # a refusal records no batch


def test_make_aiff_runs_the_views_lossless_files_and_names_where_it_started(hub):
    lib, box, api, rec = hub()
    assert api.make_aiff({"kind": "tracks", "tracks": ["t0aaaaaaa"]})["kind"] == "refused"
    f = wait_job(api, rec, api.make_aiff({"kind": "lossless", "view": "all"}))
    assert f.ok and f.kind == "aiff_batch"
    r = f.result
    assert (r["total"], r["done"]) == (3, 3)                  # clean, clean_free and the 24/96 chain: the mp3s stay
    row = batch_row(lib, r["batch"])
    assert (row.kind, row.started_by, row.scope) == ("convert", "make_aiff", "library:all")
    assert lib.entry(0)["path"].endswith(".mp3")
    f = wait_job(api, rec, api.make_aiff({"kind": "lossless", "view": "all"}))
    assert (f.ok, f.problem, f.message) == (False, "refused", NOTHING)
    assert f.result["batch"] is None and f.result["results"] == []


def test_make_aiff_for_a_folder_view_names_its_key_in_the_scope(hub):
    lib, box, api, rec = hub()
    f = wait_job(api, rec, api.make_aiff({"kind": "lossless", "view": "unlisted"}))
    assert f.ok and batch_row(lib, f.result["batch"]).scope == "library:unlisted"


def test_the_cdj_group_counts_and_convert_all_runs_it(hub):
    lib, box, api, rec = hub()
    set_kbps(lib, 0, 400)                                     # files the club players refuse
    set_kbps(lib, 1, 400)
    group = cdj_group(api)
    assert [i["track_id"] for i in group["items"]] == [lib.tracks[0], lib.tracks[1]]
    assert group["all"] == {"n": 2, "k": 0} and group["stopped"] is None
    f = wait_job(api, rec, api.make_aiff({"kind": "cdj"}))
    assert f.ok
    row = batch_row(lib, f.result["batch"])
    assert (row.started_by, row.scope) == ("cdj_all", "todo:cdj") and f.result["done"] == 2


def test_the_cdj_groups_rows_and_head_agree_on_what_can_run_now(hub):
    lib, box, api, rec = hub(["mp3", "mp3_free", "clean"])
    for i in (0, 1):
        set_kbps(lib, i, 400)
    (lib.paths.root / lib.olds[1]).unlink()                   # waits: its file is gone
    group = cdj_group(api)
    rows = {i["track_id"]: i["aiff"] for i in group["items"]}
    assert rows == {lib.tracks[0]: None, lib.tracks[1]: "file_missing"}
    assert group["all"] == {"n": sum(why is None for why in rows.values()), "k": sum(why is not None for why in rows.values())}


def test_a_stopped_convert_all_is_the_cdj_groups_resume(hub):
    lib, box, api, rec = hub(["mp3", "mp3_free"], running=True)
    set_kbps(lib, 0, 400)
    set_kbps(lib, 1, 400)
    assert cdj_group(api)["all"] == {"n": 2, "k": 0}
    f = wait_job(api, rec, api.make_aiff({"kind": "cdj"}))
    assert (f.ok, f.problem) == (False, "rekordbox_open")
    assert cdj_group(api)["stopped"] == {"batch_id": f.result["batch"], "left": 2}
    assert api.library()["aiff_stopped"] is None
    box.running = False
    assert wait_job(api, rec, api.batch_resume(f.result["batch"])).ok
    assert cdj_group(api) is None                             # converted: no longer a file CDJs refuse


def test_the_facts_of_files_from_before_they_were_stored_are_filled_first(hub):
    lib, box, api, rec = hub(["clean", "chain"])
    with db.connect(lib.paths.db_file) as conn:
        conn.execute("UPDATE files SET file_codec = NULL, file_rate = NULL, file_bits = NULL, file_kbps = NULL")
    assert api.aiff_plan({"kind": "lossless", "view": "all"})["plan"]["total"] == 0     # nothing known yet
    f = wait_job(api, rec, api.make_aiff({"kind": "lossless", "view": "all"}))
    assert f.ok and f.result["done"] == 2
    progress = [(e.phase, e.done, e.total) for e in rec.events if type(e).__name__ == "ImportProgress"]
    assert progress == [("facts", 0, 2), ("facts", 2, 2)]     # its own phase: the hub says "Reading what your files are"


# --- stopped, resumed, undone ---

def test_a_stopped_convert_batch_offers_resume_where_it_started_and_nowhere_else(hub):
    lib, box, api, rec = hub(["mp3", "mp3", "clean"], running=True)
    before = lib.dump()
    f = wait_job(api, rec, api.make_aiff({"kind": "lossless", "view": "all"}))   # only the one clean AIFF: it needs rekordbox
    assert (f.ok, f.problem) == (False, "rekordbox_open") and f.result["stop_reason"] == "rekordbox_open"
    assert lib.dump() == before
    batch = f.result["batch"]
    assert api.library()["aiff_stopped"] == {"batch_id": batch, "left": 1}
    assert cdj_group(api) is None
    f = wait_job(api, rec, api.convert([lib.tracks[0], lib.tracks[1]], "todo"))
    assert f.problem == "rekordbox_open"
    todo_batch = f.result["batch"]
    assert api.library()["aiff_stopped"]["batch_id"] == batch  # a todo:* batch is not the Library header's
    box.running = False
    r = wait_job(api, rec, api.batch_resume(batch)).result
    assert (r["state"], r["done"]) == ("done", 1) and api.library()["aiff_stopped"] is None
    r = wait_job(api, rec, api.batch_resume(todo_batch)).result
    assert (r["state"], r["done"]) == ("done", 2)


def test_a_job_snapshot_carries_its_batch_kind_so_a_reload_tells_whose_batch_runs(hub):
    lib, box, api, rec = hub(["mp3", "mp3"], running=True)
    snap = lambda: api.job_status()["job"]
    f = wait_job(api, rec, api.convert([lib.tracks[0], lib.tracks[1]], "todo"))
    assert f.problem == "rekordbox_open" and snap()["batch_kind"] == "convert"
    box.running = False
    f = wait_job(api, rec, api.batch_resume(f.result["batch"]))
    assert f.ok and snap()["kind"] == "batch_resume" and snap()["batch_kind"] == "convert"   # not Same track's
    assert wait_job(api, rec, api.make_aiff({"kind": "lossless", "view": "all"})).problem == "refused"
    assert snap()["kind"] == "aiff_batch" and snap()["batch_kind"] == "convert"
    assert wait_job(api, rec, api.rescan_library()).ok         # a job that is no batch has none
    assert snap()["batch_kind"] is None


def test_a_stopped_cdj_batch_is_the_groups_resume_and_not_upgrade_readys(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "mp3"])      # downloads with a parked upgrade: Upgrade ready
    box = Box(lib, True)
    api, rec = make_api(lib.paths, **box.services())
    assert group(api, "upgrade_ready") is not None
    with db.connect(lib.paths.db_file) as conn:
        batch = db.start_aiff_batch(conn, "convert", "cdj_all", "todo:cdj", [(lib.tracks[0], "convert")],
                                    datetime(2026, 11, 13, 9, 0))
        db.set_aiff_batch(conn, batch, state="stopped", stop_reason="rekordbox_open")
    ready = group(api, "upgrade_ready")
    assert ready["stopped"] is None                            # a stopped Convert batch is no Resume for Same track
    with db.connect(lib.paths.db_file) as conn:
        same = db.start_aiff_batch(conn, "upgrade", "user", None, [(lib.tracks[1], "same_track")],
                                   datetime(2026, 11, 13, 9, 5))
        db.set_aiff_batch(conn, same, state="stopped", stop_reason="rekordbox_open")
    ready = group(api, "upgrade_ready")
    assert ready["stopped"] == {"batch_id": same, "left": 1}


def test_undo_check_and_undo_all_work_for_a_convert_batch_and_say_what_came_back(hub):
    lib, box, api, rec = hub(["mp3", "clean", "mp3"])
    f = wait_job(api, rec, api.convert(lib.tracks))
    assert f.ok and f.result["done"] == 3
    batch = f.result["batch"]
    group = api.todo()["groups"][0]
    assert group["key"] == "rekordbox_check" and group["items"][0]["batch"]["size"] == 3
    one = wait_job(api, rec, api.undo_upgrade([lib.tracks[1]]))
    assert one.ok and one.result["undone"] == 1 and one.result["words"] == "Clean name undone. Your old name is back."
    assert lib.entry(1)["path"] == lib.olds[1]
    two = wait_job(api, rec, api.undo_upgrade([lib.tracks[0]]))
    assert two.result["words"] == "Conversion undone. Your old file is back." and lib.entry(0)["path"] == lib.olds[0]
    f = wait_job(api, rec, api.batch_undo(batch))
    assert f.ok and f.result["undone"] == 1 and f.result["words"] == "Conversion undone. Your old file is back."
    assert lib.entry(2)["path"] == lib.olds[2]


def test_undoing_a_whole_convert_batch_says_it_for_several(hub):
    lib, box, api, rec = hub(["mp3", "clean"])
    batch = wait_job(api, rec, api.convert(lib.tracks)).result["batch"]
    f = wait_job(api, rec, api.batch_undo(batch))
    assert f.ok and f.result["undone"] == 2 and f.result["words"] == "Undone. Your old files and names are back."


def test_rekordbox_checked_ends_the_undo_of_a_convert(hub):
    lib, box, api, rec = hub(["mp3", "clean"])
    wait_job(api, rec, api.convert(lib.tracks))
    f = wait_job(api, rec, api.rekordbox_checked(lib.tracks))
    assert f.ok and f.result["checked"] == lib.tracks
    assert wait_job(api, rec, api.undo_upgrade([lib.tracks[0]])).ok is False


def test_one_song_alone_that_meets_an_open_rekordbox_leaves_no_resume(hub):
    lib, box, api, rec = hub(["mp3"], running=True)
    f = wait_job(api, rec, api.convert([lib.tracks[0]]))
    assert (f.ok, f.problem) == (False, "rekordbox_open")
    assert (f.result["state"], f.result["done"]) == ("done", 0)          # closed: nothing planned is left
    assert api.library()["aiff_stopped"] is None
    assert api.batch_resume(f.result["batch"])["kind"] == "refused"


# --- the shapes, pinned against the fixture the fake backend's test reads too ---

SHAPES = json.loads((Path(__file__).parent / "fixtures" / "hub_convert_shapes.json").read_text())


def keys(name):
    return set(SHAPES[name])


def test_every_shape_stage_d_adds_has_the_fixtures_keys(hub):
    lib, box, api, rec = hub()
    set_kbps(lib, 0, 400)
    (lib.paths.root / lib.olds[1]).unlink()                   # a song whose file is gone: it waits
    aiff = api.track(lib.tracks[0])["track"]["aiff"]
    assert set(aiff) == keys("track_aiff") and set(aiff["cdj"]) == keys("cdj_words")
    plan = api.aiff_plan({"kind": "tracks", "tracks": [lib.tracks[0], lib.tracks[1], lib.tracks[4]]})["plan"]
    assert set(plan) == keys("plan") and set(plan["rekordbox"]) == keys("plan_rekordbox")
    assert set(plan["items"][0]) == keys("plan_item") and set(plan["items"][0]["cdj"]) == keys("cdj_words")
    assert set(plan["skipped"][0]) == keys("plan_left") and set(plan["waiting"][0]) == keys("plan_waiting")
    assert set(plan["kinds"][0]) == keys("plan_kind") and set(plan["space"][0]) == keys("plan_space")
    cdj = cdj_group(api)
    assert set(cdj["all"]) == keys("cdj_group_all")
    assert set(cdj["items"][0]) >= keys("cdj_item_extra") and set(cdj["items"][0]["cdj"]) == keys("cdj_why")
    f = wait_job(api, rec, api.convert([lib.tracks[0], lib.tracks[2]]))
    assert set(f.result) == keys("batch_result") and set(f.result["results"][0]) == keys("item_result")
    item = group(api, "rekordbox_check")["items"][0]
    assert set(item["batch"]) == keys("batch") and set(item["batch"]["tracks"][0]["check"]) == keys("check_view")
    assert set(wait_job(api, rec, api.batch_undo(f.result["batch"])).result) == keys("undo_result_success")


def test_a_stopped_batch_has_the_fixtures_keys_in_the_library_and_in_to_do(tmp_path, monkeypatch):
    lib = make_own_lib(tmp_path, monkeypatch, ["mp3", "clean"])
    box = Box(lib, running=True)
    api, rec = make_api(lib.paths, **box.services())
    assert not wait_job(api, rec, api.make_aiff({"kind": "lossless", "view": "all"})).ok
    assert set(api.library()["aiff_stopped"]) == keys("stopped")
