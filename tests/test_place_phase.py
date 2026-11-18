"""The sync's last phase places the parked better version for songs the user asked to download again (issue 43, D9, plan
§4.5.4; the step is `convert.place_parked`, tests/test_convert_place.py). Every library and rekordbox library is built in
tmp_path (tests/convert_helpers.py, tests/batch_helpers.py); a missing file is a file deleted after the library is
built, with the row waiting as the scan leaves it."""
from __future__ import annotations

import json

import pytest

from audio_helpers import needs_ffmpeg
from batch_helpers import Lib, make_lib
from convert_helpers import NOW, PARKED, TID, exact, make_env, never
from discjockey import auto_upgrade, batches, convert, db, library, missing, report, run, words
from discjockey.align import Alignment
from discjockey.auto_upgrade import PLACE_WAITS, Planned, plan, run_phase
from discjockey.events import BatchProgress, CancelToken, Message, RunFinished
from discjockey.library import load_state, save_state
from discjockey.report import RunLog
from discjockey.settings import Settings

pytestmark = needs_ffmpeg

ON, OFF = Settings(), Settings(auto_upgrade=False)
SINCE = "2026-11-10T09:00:00"
ASKED = "2026-11-18"
SHIFTED = Alignment("shifted", 441, 10.0, 0.0, "matches, shifted by 10 ms")
OLD = "Library/A/not_lossless/Old Name.aiff"  # a Discjockey download of a lossy source, as an AIFF
NEW = "Library/A/Artist - Song.aiff"
LINED = "Its better version is in, at Artist - Song.aiff; rekordbox's track plays it with its cues."


def make_missing(tmp_path, monkeypatch, *, alignment=SHIFTED, asked: bool = True):
    """One song whose AIFF file is gone, with a parked lossless upgrade and a rekordbox track at the old path."""
    up = {"file": PARKED, "source": "qobuz", "source_id": "q1", "source_format": "flac", "found": "2026-10-10",
          "alignment": alignment.to_dict()}
    env = make_env(tmp_path, monkeypatch, "aiff", entry={"path": OLD, "upgrade": up})
    (env.paths.root / OLD).unlink()
    with db.connect(env.paths.db_file) as conn:
        conn.execute("UPDATE files SET missing_since = ?", (SINCE,))
        if asked:
            conn.execute("UPDATE songs SET file_gone = ?", (ASKED,))
        conn.commit()
    return env


def services(place, *, running=never, compare=exact) -> dict:
    return {"running": running, "place": place, "compare": compare, "now": lambda: NOW}


def phase(paths, place, *, settings=OFF, running=never, state=None, log=None, dry_run=False, token=None):
    """`run_phase` as the sync calls it: (outcome, state, log, events)."""
    state = load_state(paths) if state is None else state
    log = log or RunLog(NOW)
    events: list = []
    out = run_phase(paths, state, (), settings, log, emit=events.append, token=token, running=running, place=place,
                    compare=exact, now=lambda: NOW, dry_run=dry_run)
    return out, state, log, events


def aiff_batches(paths):
    with db.connect(paths.db_file) as conn:
        return [db.aiff_batch(conn, i) for (i,) in conn.execute("SELECT id FROM aiff_batches ORDER BY id")]


def rows(out) -> list[tuple[str, str, str | None]]:
    return [(r["track"], r["state"], r["reason"]) for r in out.results]


def mark_missing(lib: Lib, i: int, *, asked: bool = True) -> str:
    """Song i of a `make_lib` library: its file is gone (the row waits, as a scan leaves it) and, when `asked`, Download
    again was pressed."""
    state = load_state(lib.paths)
    e = state["tracks"][lib.tracks[i]]
    (lib.paths.root / e["path"]).unlink()
    e["file_gone"] = ASKED if asked else None
    save_state(lib.paths, state)
    with db.connect(lib.paths.db_file) as conn:
        conn.execute("UPDATE files SET missing_since = ? WHERE id = ?", (SINCE, db.file_id_at(conn, lib.olds[i])))
        conn.commit()
    return lib.olds[i]


def rb_path(env) -> str:
    from convert_helpers import Env  # noqa: F401 - the helper's own row reader is in test_convert_place
    from discjockey.rekordbox import master
    with master.open_read(env.place, False) as m:
        return m.con.execute("SELECT FolderPath FROM djmdContent WHERE ID = '1'").fetchone()[0]


# --- the decision's repro: Download again with the switch off, by `sync run --auto-upgrade-only` ---

def test_download_again_with_the_switch_off_places_the_parked_version_repoints_rekordbox_and_leaves_a_check(
        tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    events: list = []
    found = run.auto_upgrade_only(env.paths, OFF, emit=events.append, rekordbox=services(env.place))
    root = env.paths.root

    assert found.code == 0 and found.report is not None
    out = found.outcome
    assert (out.done, out.waiting, out.refused, out.failed, out.dry_run) == (1, 0, 0, 0, False)
    (row,) = out.results
    assert (row["track"], row["state"], row["action"], row["how"], row["message"]) == (TID, "done", "place", "placed",
                                                                                       LINED)
    # the file, the records: the song keeps its key and its file row; nothing waits any more
    assert (root / NEW).is_file() and not (root / PARKED).exists() and not (root / OLD).exists()
    e = load_state(env.paths)["tracks"][TID]
    assert (e["path"], e["upgrade"], e["file_gone"], e["missing_since"], e["status"]) == (NEW, None, None, None,
                                                                                         "lossless")
    assert rb_path(env) == str(root / NEW)  # rekordbox's track plays it now
    # the check card: the placement's own words and a step
    check = e["rekordbox_check"]
    assert (check["reason"], check["aligned"], check["repointed"]) == ("placed_missing", True, True)
    assert report.check_text(check) == report.PLACED_LINED_CHECK
    (step,) = words.person_steps(TID, check)
    assert step["say"].startswith(report.PLACED_LINED_CHECK) and step["id"] == "step:look"
    # the batch: the sync's last phase with the switch off, one placement, nothing else
    (batch,) = aiff_batches(env.paths)
    assert (batch.started_by, batch.kind, batch.scope, batch.state, batch.via) == ("download_again", "upgrade", "sync",
                                                                                   "done", "terminal")
    assert [(i.track, i.action, i.state) for i in batch.items] == [(TID, "place", "done")]
    assert batch.backup is not None
    with db.connect(env.paths.db_file) as conn:
        assert db.unfinished_aiff_batches(conn) == []
    # the run's report: its own section, the block, the end line
    data = json.loads(found.report.with_suffix(".json").read_text())
    assert data["kind"] == "auto_upgrade_only" and data["auto_upgrade"]["results"][0]["action"] == "place"
    assert [(r["section"], r["path"], r["status"]) for r in data["results"]
            if r["section"] != "rekordbox_check"] == [("placed_missing", NEW, "lossless")]
    text = found.report.read_text()
    assert "## Better version put in (its file was missing) (1)" in text and "## Upgraded" not in text
    assert report.auto_upgrade_line(out.to_dict()) == "1 missing song got its better version."
    assert [x.text for x in events if isinstance(x, Message)] == [words.placing_line(1)]
    assert isinstance(events[-1], RunFinished) and events[-1].exit_code == 0


def test_the_switch_on_runs_the_placements_first_in_the_same_batch(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["aiff", "mp3", "mp3_free"])
    mark_missing(lib, 1)
    before = lib.entry(2)["path"]
    out, state, log, events = phase(lib.paths, lib.place, settings=ON)
    assert rows(out) == [(lib.tracks[1], "done", None), (lib.tracks[0], "done", None), (lib.tracks[2], "done", None)]
    assert [r["action"] for r in out.results] == ["place", "same_track", "same_track"]
    assert [r["how"] for r in out.results] == ["placed", "in_place", "new_aiff"]
    (batch,) = aiff_batches(lib.paths)
    assert (batch.started_by, batch.kind) == ("auto_upgrade", "upgrade")
    assert [(i.track, i.action, i.state) for i in batch.items] == [
        (lib.tracks[1], "place", "done"), (lib.tracks[0], "same_track", "done"), (lib.tracks[2], "same_track", "done")]
    assert lib.entry(1)["path"] == "Library/A/Artist - Song 1.aiff" and lib.entry(2)["path"] != before
    assert [(r.section, r.track_id) for r in log.results] == [
        ("placed_missing", lib.tracks[1]), ("upgraded", lib.tracks[0]), ("upgraded", lib.tracks[2])]
    assert [x.text for x in events if isinstance(x, Message)] == [
        "Upgrading 2 tracks at the end of the sync...", words.placing_line(1)]
    assert {(e.lead, e.count) for e in events if isinstance(e, BatchProgress)} == {
        ("Upgrading", f"{n} of 3 done") for n in range(4)}
    assert report.auto_upgrade_line(out.to_dict()) == "Upgraded 2 tracks; your cues stayed. 1 missing song got its better version."


def test_with_the_switch_off_only_the_placements_run_and_the_upgrades_stay_parked(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["aiff", "mp3", "mp3_free"])
    mark_missing(lib, 1)
    kept = {i: (lib.entry(i)["path"], lib.entry(i)["upgrade"]) for i in (0, 2)}
    music = {k: v for k, v in lib.music().items() if k.startswith(("Library/A/Artist - Song 0", "Library/A/Old 2"))}
    out, _, _, events = phase(lib.paths, lib.place, settings=OFF)
    assert rows(out) == [(lib.tracks[1], "done", None)]
    assert [(e.lead, e.count) for e in events if isinstance(e, BatchProgress)] == [
        ("Putting in better versions", "0 of 1 put in"), ("Putting in better versions", "1 of 1 put in")]
    (batch,) = aiff_batches(lib.paths)
    assert (batch.started_by, [i.action for i in batch.items]) == ("download_again", ["place"])
    assert {i: (lib.entry(i)["path"], lib.entry(i)["upgrade"]) for i in (0, 2)} == kept
    assert {k: v for k, v in lib.music().items() if k in music} == music


def test_the_switch_off_with_nothing_to_place_plans_nothing_and_looks_at_nothing_of_rekordbox(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff"])
    mark_missing(lib, 0, asked=False)  # missing, but Download again was not pressed
    state = load_state(lib.paths)
    state["tracks"][lib.tracks[1]]["upgrade"] = None
    state["tracks"][lib.tracks[1]]["file_gone"] = ASKED  # asked, but nothing is parked for it
    assert missing.place_keys(state) == []
    ask = lambda: pytest.fail("looked at rekordbox")  # noqa: E731
    assert plan(lib.paths, state, (), OFF, running=ask, place=None) is None
    out = run_phase(lib.paths, state, (), OFF, RunLog(NOW), running=ask, place=None, now=lambda: NOW)
    assert out is None and aiff_batches(lib.paths) == []


# --- plan: the placements are in the set, first ---

def test_the_set_holds_the_placements_first_with_the_switch_on_and_alone_with_it_off(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["aiff", "mp3", "mp3_free", "mp3"])
    mark_missing(lib, 3)
    mark_missing(lib, 1)
    state = load_state(lib.paths)
    on = plan(lib.paths, state, (), ON, running=never, place=lib.place)
    assert on == Planned([lib.tracks[1], lib.tracks[3], lib.tracks[0], lib.tracks[2]], [], [], False,
                         frozenset({lib.tracks[1], lib.tracks[3]}))  # to-do's order: the same folder, then title
    off = plan(lib.paths, state, (), OFF, running=never, place=lib.place)
    assert off == Planned([lib.tracks[1], lib.tracks[3]], [], [], False, frozenset({lib.tracks[1], lib.tracks[3]}))
    waiting = plan(lib.paths, state, (), OFF, running=lambda: True, place=lib.place)
    assert waiting == Planned([], [(lib.tracks[1], "rekordbox_open"), (lib.tracks[3], "rekordbox_open")], [], True,
                              frozenset({lib.tracks[1], lib.tracks[3]}))


def test_a_file_back_on_disk_or_a_drive_that_is_away_leaves_the_song_out_of_the_set(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "mp3", "mp3"])
    for i in range(3):
        mark_missing(lib, i)
    (lib.paths.root / lib.olds[0]).parent.mkdir(exist_ok=True)
    (lib.paths.root / lib.olds[0]).write_bytes(b"x")  # its file is back before the scan relinks it
    real = batches.present
    monkeypatch.setattr(batches, "present", lambda paths, e: "away" if e["path"] == lib.olds[1] else real(paths, e))
    answer = plan(lib.paths, load_state(lib.paths), (), OFF, running=never, place=lib.place)
    assert answer.run == [lib.tracks[2]] and answer.place == {lib.tracks[2]}


def test_place_keys_are_the_marked_missing_songs_with_a_parked_upgrade_hidden_ones_included(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3"] * 7)
    for i in range(7):
        mark_missing(lib, i)
    state = load_state(lib.paths)
    tracks = state["tracks"]
    t = lib.tracks
    tracks[t[0]]["hidden"] = True                       # hidden: in (the user asked for it)
    tracks[t[1]]["upgrade"] = None                      # nothing parked
    tracks[t[2]]["file_gone"] = None                    # Download again was not pressed
    tracks[t[3]]["missing_since"] = None                # its file is not marked missing
    state["ambiguous"] = {t[4]: ["Library/A/x.mp3", "Library/B/x.mp3"]}  # found in several places
    tracks[t[5]]["online"] = False                      # its drive is not connected
    tracks[t[6]]["folder"], tracks[t[6]]["title"] = "A", "Aaa"          # to-do's order: folder, artist, title
    assert missing.place_keys(state) == [t[6], t[0]]
    assert missing.place_keys({"tracks": {}}) == []


# --- rekordbox running, Stop and the records ---

def test_rekordbox_open_at_the_start_waits_with_the_song_still_missing_and_the_next_phase_places_it(tmp_path,
                                                                                                    monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    out, state, log, events = phase(env.paths, env.place, running=lambda: True)
    assert rows(out) == [(TID, "waiting", "rekordbox_open")]
    assert out.results[0]["message"] == PLACE_WAITS["rekordbox_open"] == (
        "Waits for rekordbox to be closed: its better version goes in at your next sync.")
    assert (out.batch, out.backup, out.waiting) == (None, None, 1) and aiff_batches(env.paths) == []
    e = load_state(env.paths)["tracks"][TID]  # nothing placed, the song waits with its mark
    assert (e["path"], e["file_gone"], e["missing_since"]) == (OLD, ASKED, SINCE)
    assert e["upgrade"]["auto_waits"] == NOW.isoformat(timespec="seconds") and (env.paths.root / PARKED).is_file()
    assert [(r.section, r.note) for r in log.results] == [("upgrade_waits", PLACE_WAITS["rekordbox_open"])]
    assert events == [Message("info", words.place_waiting_line(1))]
    assert report.auto_upgrade_line(out.to_dict()) == "1 missing song waits for its better version until your next sync."
    again, _, _, _ = phase(env.paths, env.place)  # rekordbox closed at the next sync
    assert rows(again) == [(TID, "done", None)]
    e = load_state(env.paths)["tracks"][TID]
    assert (e["path"], e["upgrade"], e["file_gone"]) == (NEW, None, None)


@pytest.mark.parametrize("settings", [ON, OFF], ids=["switch on", "switch off"])
def test_an_unreadable_rekordbox_library_makes_the_placement_wait_instead_of_dropping_it(tmp_path, monkeypatch,
                                                                                       settings):
    from test_aiff_plan import UNREADABLE
    from discjockey.rekordbox import master
    lib = make_lib(tmp_path, monkeypatch, ["aiff", "mp3"])
    mark_missing(lib, 1)
    state = load_state(lib.paths)
    planned = plan(lib.paths, state, (), settings, running=never, place=lib.place, status=UNREADABLE)
    assert lib.tracks[1] in planned.place and lib.tracks[1] not in planned.run  # kept in the set, not dropped
    assert (lib.tracks[1], "rekordbox_unreadable") in planned.waiting
    assert PLACE_WAITS["rekordbox_unreadable"] == (
        "Discjockey can't open this rekordbox version's library yet, so it can't point your rekordbox track at the "
        "file; its better version goes in once it can.")
    # the phase: a row that waits with these words, no batch for it, no mark for rekordbox to be closed, the song missing
    monkeypatch.setattr(master, "status", lambda *a, **k: UNREADABLE)
    for dry_run in (True, False):
        out, state, log, events = phase(lib.paths, lib.place, settings=settings, dry_run=dry_run)
        mine = next(r for r in out.results if r["track"] == lib.tracks[1])
        assert (mine["state"], mine["reason"], mine["action"]) == ("waiting", "rekordbox_unreadable", "place")
        assert mine["message"] == PLACE_WAITS["rekordbox_unreadable"]
        e = load_state(lib.paths)["tracks"][lib.tracks[1]]
        assert e["file_gone"] == ASKED and "auto_waits" not in e["upgrade"] and e["path"] == lib.olds[1]
        assert (lib.paths.root / e["upgrade"]["file"]).is_file()
        note = auto_upgrade.start_note(out.to_dict())
        assert "Artist – Song 1 gets its better version at the end of the sync, once rekordbox is closed." in note
    assert (("upgrade_waits", PLACE_WAITS["rekordbox_unreadable"]) in [(r.section, r.note) for r in log.results])


def test_rekordbox_opening_while_the_placement_is_in_work_rolls_it_back_and_the_next_sync_tries_again(tmp_path,
                                                                                                      monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    flag, real = {"open": False}, convert.build_staged

    def render(*a, **k):
        real(*a, **k)
        flag["open"] = True  # rekordbox is opened while the placement is being prepared

    monkeypatch.setattr(convert, "build_staged", render)
    out, _, _, _ = phase(env.paths, env.place, running=lambda: flag["open"])
    assert rows(out) == [(TID, "waiting", "rekordbox_open")]
    (batch,) = aiff_batches(env.paths)
    assert (batch.state, [i.state for i in batch.items]) == ("done", ["skipped"])  # no Resume for it
    e = load_state(env.paths)["tracks"][TID]  # rolled back: missing, marked, parked, nothing of rekordbox written
    assert (e["path"], e["file_gone"], e["missing_since"]) == (OLD, ASKED, SINCE) and not (env.paths.root / NEW).exists()
    assert (env.paths.root / PARKED).is_file() and rb_path(env) == str(env.paths.root / OLD)
    flag["open"] = False
    monkeypatch.setattr(convert, "build_staged", real)
    again, _, _, _ = phase(env.paths, env.place, running=lambda: flag["open"])  # a rolled-back placement is tried again
    assert rows(again) == [(TID, "done", None)] and load_state(env.paths)["tracks"][TID]["path"] == NEW


def test_stop_before_the_placement_starts_leaves_it_for_the_next_sync(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    token = CancelToken()
    token.cancel()
    out, _, _, _ = phase(env.paths, env.place, token=token)
    assert rows(out) == [(TID, "waiting", "not_reached")] and out.stopped and aiff_batches(env.paths) == []
    assert out.results[0]["message"] == PLACE_WAITS["not_reached"]
    assert load_state(env.paths)["tracks"][TID]["file_gone"] == ASKED


def test_a_download_again_batch_cut_short_ends_through_end_auto_and_is_never_resumed(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    batch_id = batches.start(env.paths, [(TID, "place")], started_by=batches.DOWNLOAD_AGAIN, scope="sync", now=lambda: NOW)
    done = batches.end_auto(env.paths, batch_id, "not_reached", now=lambda: NOW)
    assert [(i.state, i.reason) for i in done.results] == [("skipped", "not_reached")] and done.state == "done"
    crashed = batches.start(env.paths, [(TID, "place")], started_by=batches.DOWNLOAD_AGAIN, scope="sync",
                            now=lambda: NOW)
    assert batches.recover(env.paths, now=lambda: NOW) == []  # a crash: ended the same way, nothing to resume
    with db.connect(env.paths.db_file) as conn:
        assert db.aiff_batch(conn, crashed).state == "done" and db.unfinished_aiff_batches(conn) == []
    other = batches.start(env.paths, [(TID, "same_track")], started_by="user", now=lambda: NOW)
    with pytest.raises(ValueError, match="sync's last phase"):
        batches.end_auto(env.paths, other, "not_reached")


def test_a_space_refusal_is_recorded_on_the_parked_upgrade_and_held_at_the_next_phase(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    free = {"v": 1000}
    monkeypatch.setattr(convert, "free_space", lambda path: free["v"])
    out, _, _, _ = phase(env.paths, env.place)
    assert rows(out) == [(TID, "refused", "space")] and out.results[0]["action"] == "place"
    record = load_state(env.paths)["tracks"][TID]["upgrade"]["auto_refused"]
    assert (record["reason"], record["free"]) == ("space", 1000)
    e = load_state(env.paths)["tracks"][TID]
    assert (e["path"], e["file_gone"]) == (OLD, ASKED)  # the song keeps its mark
    held, _, _, _ = phase(env.paths, env.place)  # nothing changed: not tried again
    assert rows(held) == [(TID, "refused", "space")] and aiff_batches(env.paths)[-1].id == aiff_batches(env.paths)[0].id
    assert len(aiff_batches(env.paths)) == 1
    free["v"] = 10_000_000_000
    freed, _, _, _ = phase(env.paths, env.place)
    assert rows(freed) == [(TID, "done", None)]


def test_a_parked_file_deleted_by_hand_is_a_failed_row_the_mark_stays_and_the_song_downloads_at_the_next_sync(
        tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    (env.paths.root / PARKED).unlink()
    out, state, log, _ = phase(env.paths, env.place)
    assert rows(out) == [(TID, "failed", None)]
    assert out.results[0]["message"] == convert.PARKED_GONE == (
        "Its better version was no longer in Upgrades ready, so it downloads at your next sync.")
    assert [r.section for r in log.results] == ["errors"]
    e = load_state(env.paths)["tracks"][TID]
    assert (e["upgrade"], e["file_gone"], e["path"]) == (None, ASKED, OLD)
    assert missing.place_keys(load_state(env.paths)) == []  # no parked upgrade any more: the planner downloads it


# --- undo and the mark ---

def test_an_undone_placement_is_never_placed_again_until_download_again_is_pressed(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    out, _, _, _ = phase(env.paths, env.place)
    undone = batches.undo(env.paths, out.batch, running=never, place=env.place, now=lambda: NOW)
    assert undone.undone == 1
    e = load_state(env.paths)["tracks"][TID]  # missing again, nothing asks for it any more
    assert (e["path"], e["file_gone"], e["missing_since"]) == (OLD, None, SINCE) and e["upgrade"]["file"]
    assert missing.place_keys(load_state(env.paths)) == []
    assert phase(env.paths, env.place)[0] is None and len(aiff_batches(env.paths)) == 1
    state = load_state(env.paths)
    state["tracks"][TID]["file_gone"] = ASKED  # the user presses Download again
    save_state(env.paths, state)
    again, _, _, _ = phase(env.paths, env.place)
    assert rows(again) == [(TID, "done", None)] and load_state(env.paths)["tracks"][TID]["path"] == NEW


# --- what it says before it runs ---

def test_the_dry_run_lists_a_would_row_with_the_action_and_says_it_with_the_switch_on_and_off(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["aiff", "mp3"])
    mark_missing(lib, 1)
    state = load_state(lib.paths)
    for settings in (ON, OFF):
        out, _, log, events = phase(lib.paths, lib.place, settings=settings, dry_run=True, state=state)
        expect = [(lib.tracks[1], "would", None)] + ([(lib.tracks[0], "would", None)] if settings is ON else [])
        assert rows(out) == expect and out.results[0]["action"] == "place" and out.results[0]["how"] == "placed"
        assert log.results == [] and events == [] and aiff_batches(lib.paths) == []
        note = auto_upgrade.start_note(out.to_dict())
        clause = "Artist – Song 1 gets its better version at the end of the sync."
        assert note == (f"{words.auto_plan_line(1)} {clause}" if settings is ON else clause)
    waiting, _, _, _ = phase(lib.paths, lib.place, settings=OFF, dry_run=True, state=state, running=lambda: True)
    assert rows(waiting) == [(lib.tracks[1], "waiting", "rekordbox_open")]
    assert auto_upgrade.start_note(waiting.to_dict()) == (
        "Artist – Song 1 gets its better version at the end of the sync, once rekordbox is closed.")
    both, _, _, _ = phase(lib.paths, lib.place, settings=ON, dry_run=True, state=state, running=lambda: True)
    assert auto_upgrade.start_note(both.to_dict()) == (
        f"{words.before_start_line(1)} Artist – Song 1 gets its better version at the end of the sync, once rekordbox "
        "is closed.")
    assert auto_upgrade.start_note({"results": []}) is None and auto_upgrade.start_note(None) is None


# --- the sync's own order: the planner has saved the folder first ---

class _NoDownloads:
    """Stands in for the plan's actions: nothing to download."""

    def __init__(self, paths, state, log, acquirer, inspect, *, emit, token, limit=None, where=None):
        pass

    def run(self, actions):
        pass


def test_the_sync_places_after_the_planner_saved_the_songs_current_folder(tmp_path, monkeypatch):
    """The planner moves a playlist song's `folder` (option A: the file stays, new downloads follow the playlist); the
    placement goes where a download would go now, so it must read the folder the planner just stored."""
    from discjockey.models import Plan
    env = make_missing(tmp_path, monkeypatch)
    monkeypatch.setattr(run, "Executor", _NoDownloads)
    monkeypatch.setattr(run, "fill_kbps", lambda *a, **k: 0)
    state = load_state(env.paths)
    state["tracks"][TID]["folder"] = "B"  # the planner's rule 2: the song belongs to playlist B now
    prep = run.Prepared(env.paths, state, OFF, Plan(state, [], [], []), RunLog(NOW))
    events: list = []
    code, path = run.execute(prep, None, emit=events.append, rekordbox=services(env.place))
    assert code == 0
    e = load_state(env.paths)["tracks"][TID]
    assert e["path"] == "Library/B/Artist - Song.aiff" and e["folder"] == "B" and (env.paths.root / e["path"]).is_file()
    data = json.loads(path.with_suffix(".json").read_text())
    assert data["auto_upgrade"]["done"] == 1 and [r["section"] for r in data["results"]][:1] == ["placed_missing"]
    kinds = [type(x).__name__ for x in events]
    assert kinds.index("BatchProgress") < kinds.index("RunFinished")


def test_a_quiet_sync_with_the_switch_off_still_places_and_one_with_nothing_to_place_looks_at_nothing(tmp_path,
                                                                                                      monkeypatch):
    from discjockey.models import Plan
    env = make_missing(tmp_path, monkeypatch)
    monkeypatch.setattr(run, "fill_kbps", lambda *a, **k: 0)
    state = load_state(env.paths)
    prep = run.Prepared(env.paths, state, OFF, Plan(state, [], [], []), RunLog(NOW))
    code, path = run.finish_quietly(prep, rekordbox=services(env.place))
    assert code == 0 and load_state(env.paths)["tracks"][TID]["path"] == NEW
    # the song is placed: nothing is left, so a second sync with the switch off does not look for rekordbox at all
    monkeypatch.setattr(run, "locate", lambda: pytest.fail("looked for rekordbox"))
    monkeypatch.setattr(run.process, "running", lambda: pytest.fail("asked whether rekordbox runs"))
    state = load_state(env.paths)
    again = run.Prepared(env.paths, state, OFF, Plan(state, [], [], []), RunLog(NOW))
    code, path = run.finish_quietly(again)
    assert code == 0 and "auto_upgrade" not in json.loads(path.with_suffix(".json").read_text())


def test_the_phase_alone_with_the_switch_off_and_nothing_to_place_writes_nothing(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch, asked=False)  # missing, but Download again was not pressed
    before = (env.music(), load_state(env.paths)["tracks"], aiff_batches(env.paths))
    found = run.auto_upgrade_only(env.paths, OFF, rekordbox=services(env.place))
    assert (found.code, found.report, found.outcome) == (0, None, None)
    assert (env.music(), load_state(env.paths)["tracks"], aiff_batches(env.paths)) == before
    assert not env.paths.reports.exists()
    dry = run.auto_upgrade_only(env.paths, OFF, dry_run=True, rekordbox=services(env.place))
    assert dry.outcome is None
    state = load_state(env.paths)
    state["tracks"][TID]["file_gone"] = ASKED
    save_state(env.paths, state)
    dry = run.auto_upgrade_only(env.paths, OFF, dry_run=True, rekordbox=services(env.place))
    assert [(r["state"], r["action"]) for r in dry.outcome.results] == [("would", "place")] and dry.report is None
    assert load_state(env.paths)["tracks"][TID]["path"] == OLD and aiff_batches(env.paths) == []


def test_a_scan_that_finds_the_file_back_first_clears_the_mark_and_nothing_is_placed(tmp_path, monkeypatch):
    env = make_missing(tmp_path, monkeypatch)
    old = env.paths.root / OLD
    old.parent.mkdir(parents=True, exist_ok=True)
    (env.paths.root / PARKED).replace(old)  # the user puts a file back at the old place (any audio: the scan links it)
    # the sync's scan relinks the row (E1/E2): the mark and the missing date go; the phase finds nothing to place
    with db.connect(env.paths.db_file) as conn:
        conn.execute("UPDATE files SET missing_since = NULL")
        conn.execute("UPDATE songs SET file_gone = NULL")
        conn.commit()
    state = load_state(env.paths)
    state["tracks"][TID]["upgrade"]["file"] = "Upgrades ready/A/never-there.aiff"
    assert missing.place_keys(state) == [] and phase(env.paths, env.place, state=state)[0] is None
    assert aiff_batches(env.paths) == []


# --- the words of the check, the section, the step ---

CHECKS = [
    ({"repointed": True, "aligned": True, "match": "shifted"}, report.PLACED_LINED_CHECK, "look"),
    ({"repointed": True, "aligned": False, "match": "shifted"}, report.PLACED_UNMEASURED_CHECK, "look"),
    ({"repointed": False, "aligned": True, "match": "exact"}, report.PLACED_CHECK, "look"),  # no rekordbox track held it
    ({"repointed": False, "aligned": True, "match": "different"}, report.PLACED_NEW_FILE_CHECK, "relocate_new"),
    ({"repointed": False, "aligned": False, "match": "different"}, report.PLACED_SAME_NAME_CHECK, "look"),
]


@pytest.mark.parametrize("fields, text, step", CHECKS)
def test_the_check_of_a_placement_has_its_words_and_step_for_each_case(fields, text, step):
    check = {"reason": "placed_missing", "since": "2026-11-18", "reload_tag": False, **fields}
    assert report.check_text(check) == text
    (found,) = words.person_steps("t1", check, "/music/Library/A/x.aiff")
    assert found["id"] == f"step:{step}" and found["say"].startswith(text)
    assert ("/music/Library/A/x.aiff" in found["say"]) is (step == "relocate_new")
    assert text.startswith("Its file was missing, so its better version took its place")


def test_the_report_has_the_section_after_swapped_and_the_run_summary_counts_it_as_lossless():
    keys = [k for k, _ in report.SECTIONS]
    assert keys.index("placed_missing") == keys.index("swapped") + 1
    assert dict(report.SECTIONS)["placed_missing"] == "Better version put in (its file was missing)"
    from discjockey.hub import views
    summary = views.run_summary("r", {"results": [{"section": "placed_missing", "status": "lossless"}]})
    assert summary["counts"]["lossless"] == 1


def test_the_console_lists_placements_apart_from_the_upgrades():
    from discjockey.console import upgrade_lines
    row = lambda k, a, state="would": {"track": k, "name": k, "state": state, "reason": None, "message": None,  # noqa: E731
                                       "how": "placed" if a == "place" else "in_place", "action": a}
    block = {"results": [row("a", "place"), row("b", "same_track")]}
    assert upgrade_lines(block, lambda k: f"Artist - {k}", full=True) == [
        "At the end, 1 upgrade goes in place of your files; your cues stay.", "  Artist - b (in place)",
        "1 missing song gets its better version at the end of the sync.", "  Artist - a"]


# --- the AIFF batch tables accept the new values after the schema step ---

def test_the_schema_step_lets_batches_name_the_placement_and_keeps_every_row():
    import sqlite3
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    for statement in db.SCHEMA_V1:
        conn.execute(statement)
    for version in range(1, 10):  # a version-10 database
        db.UPGRADES[version](conn)
    conn.execute("INSERT INTO aiff_batches (id, kind, started_by, started, state, via) "
                 "VALUES (7, 'upgrade', 'auto_upgrade', 'x', 'done', 'terminal')")
    conn.execute("INSERT INTO aiff_items (batch, seq, track, action, state, result) VALUES (7, 0, 't', 'same_track', "
                 "'done', '{\"note\": 1}')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO aiff_items (batch, seq, track, action, state) VALUES (7, 1, 't', 'place', 'planned')")
    db.UPGRADES[10](conn)
    conn.execute("INSERT INTO aiff_batches (id, kind, started_by, started, state) "
                 "VALUES (8, 'upgrade', 'download_again', 'y', 'running')")
    conn.execute("INSERT INTO aiff_items (batch, seq, track, action, state) VALUES (8, 0, 't', 'place', 'planned')")
    assert conn.execute("SELECT id, started_by, via FROM aiff_batches ORDER BY id").fetchall() == [
        (7, "auto_upgrade", "terminal"), (8, "download_again", "window")]
    assert conn.execute("SELECT batch, seq, action, result FROM aiff_items ORDER BY batch").fetchall() == [
        (7, 0, "same_track", '{"note": 1}'), (8, 0, "place", None)]
    conn.execute("DELETE FROM aiff_batches WHERE id = 8")  # the cascade still reaches the items
    assert conn.execute("SELECT COUNT(*) FROM aiff_items WHERE batch = 8").fetchone() == (0,)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'aiff_items'").fetchone()[0]
    assert "aiff_batches_new" not in sql and "REFERENCES" in sql  # the reference follows the rename
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'aiff_items_track'").fetchone()
