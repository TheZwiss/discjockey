"""Auto-upgrade (discjockey/auto_upgrade.py; plan stage C §0.3-§0.7, §1.2, §5 C1 and C2): which tracks the phase would
run, wait with or leave alone, when a recorded refusal still holds, the analysis stamps it holds on, and the phase
itself with its batch, results and records. Libraries and the fixture rekordbox are built in tmp_path
(`batch_helpers.make_lib`); nothing real is read."""
from __future__ import annotations

import fcntl
import os
from pathlib import Path

import pytest

from batch_helpers import DIFFERENT, make_lib, needs_ffmpeg
from convert_helpers import EXACT, NOW
from discjockey import auto_upgrade, batches, convert, db, upgrades
from discjockey.align import Alignment
from discjockey.auto_upgrade import Outcome, Planned, free_now, plan, refusal_holds, run_phase, stamps
from discjockey.events import BatchProgress, CancelToken, Message
from discjockey.library import load_state, save_state
from discjockey.rekordbox import backup as rbbackup
from discjockey.report import RunLog
from discjockey.rekordbox import master
from discjockey.rekordbox.locate import Place
from discjockey.settings import Settings
from hub_helpers import make_api
from rekordbox_helpers import KEYS, _open

never = lambda: False  # noqa: E731
ON, OFF = Settings(), Settings(auto_upgrade=False)


def ready(lib, **kw) -> Planned:
    """`plan` for `lib` as the sync would ask it: the switch on, rekordbox closed unless `running` says otherwise."""
    kw.setdefault("running", never)
    kw.setdefault("place", lib.place)
    answer = plan(lib.paths, load_state(lib.paths), kw.pop("held", ()), ON, **kw)
    assert answer is not None
    return answer


def record(lib, i: int, **fields) -> None:
    """Writes an `auto_refused` record on track i's parked upgrade."""
    state = load_state(lib.paths)
    up = state["tracks"][lib.tracks[i]]["upgrade"]
    up["auto_refused"] = {"reason": "not_analysed", "message": "m", "at": "2026-11-09T10:00:00", "anlz": None,
                          "free": None, **fields}
    save_state(lib.paths, state)


def anlz_files(lib, i: int) -> list[Path]:
    return sorted((lib.folder / "share/PIONEER/USBANLZ").glob(f"*/{i + 1}/ANLZ0000.*"))


# --- refusal_holds (pure, plan §0.7) ---

THEN = {"PIONEER/USBANLZ/000/1/ANLZ0000.DAT": 10, "PIONEER/USBANLZ/000/1/ANLZ0000.EXT": 20}


@pytest.mark.parametrize("reason", ["timing", "not_analysed", "cloud"])
def test_an_analysis_refusal_holds_while_the_analysis_files_are_the_same_set_with_the_same_mtimes(reason):
    rec = {"reason": reason, "anlz": dict(THEN)}
    assert refusal_holds(rec, dict(THEN), None)
    assert refusal_holds(rec, dict(reversed(list(THEN.items()))), 123)                   # order and free space don't matter
    changed = {**THEN, "PIONEER/USBANLZ/000/1/ANLZ0000.EXT": 21}                           # rekordbox analysed it again
    added = {**THEN, "PIONEER/USBANLZ/000/1/ANLZ0000.2EX": 30}                             # a file that wasn't there
    removed = {"PIONEER/USBANLZ/000/1/ANLZ0000.DAT": 10}
    for now in (changed, added, removed, {}):
        assert not refusal_holds(rec, now, None), now


@pytest.mark.parametrize("reason", ["timing", "not_analysed", "cloud"])
def test_an_analysis_refusal_without_a_readable_stamp_never_holds(reason):
    assert not refusal_holds({"reason": reason, "anlz": None}, dict(THEN), None)         # the record could not be read
    assert not refusal_holds({"reason": reason, "anlz": dict(THEN)}, None, None)         # the files can't be read now
    assert not refusal_holds({"reason": reason, "anlz": None}, None, None)
    assert not refusal_holds({"reason": reason}, {}, None)                                # no stamp in the record at all
    assert refusal_holds({"reason": reason, "anlz": {}}, {}, None)                       # "no analysis" is a stamp too


def test_a_space_refusal_holds_at_equal_free_space_and_below_not_above():
    rec = {"reason": "space", "free": 1000, "anlz": None}
    assert refusal_holds(rec, None, 1000) and refusal_holds(rec, None, 10)
    assert not refusal_holds(rec, None, 1001)
    assert not refusal_holds(rec, None, None)                                              # free space not readable
    assert not refusal_holds({"reason": "space", "free": None}, None, 5)
    assert not refusal_holds({"reason": "space", "free": True}, None, 0)                   # a bool is no size


def test_an_unknown_reason_or_a_record_without_one_never_holds():
    for rec in ({"reason": "changed", "anlz": dict(THEN), "free": 5}, {"reason": None}, {}):
        assert not refusal_holds(rec, dict(THEN), 1)


def test_the_outcome_is_the_runs_block():
    out = Outcome(12, "2026-11-09T21-04-11Z", 9, 3, 1, 0, False, False,
                  [{"track": "local:41", "name": "A - T", "state": "done", "reason": None, "message": "m",
                    "how": "new_aiff"}])
    assert list(out.to_dict()) == ["batch", "backup", "done", "waiting", "refused", "failed", "stopped", "dry_run",
                                   "results"]
    assert out.to_dict()["results"][0]["state"] == "done" and out.to_dict()["batch"] == 12


# --- the stamps of the analysis files ---

@needs_ffmpeg
def test_stamps_name_every_analysis_file_of_every_rekordbox_track_of_the_file(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "mp3_free", "mp3_plain"])
    got = stamps(lib.paths, lib.tracks, load_state(lib.paths), running=never, place=lib.place)
    assert got[lib.tracks[1]] == {}                                                        # rekordbox doesn't hold it
    assert set(got[lib.tracks[0]]) == {f"PIONEER/USBANLZ/000/1/ANLZ0000.{e}" for e in ("DAT", "EXT", "2EX", "3EX")}
    assert set(got[lib.tracks[2]]) == {f"PIONEER/USBANLZ/001/3/ANLZ0000.{e}" for e in ("DAT", "2EX", "3EX")}  # no .EXT
    assert got[lib.tracks[0]] == {f"PIONEER/USBANLZ/000/1/ANLZ0000.{p.suffix[1:]}": p.stat().st_mtime_ns
                                  for p in anlz_files(lib, 0)}
    ext = anlz_files(lib, 0)[1]
    os.utime(ext, ns=(ext.stat().st_atime_ns, ext.stat().st_mtime_ns + 5_000_000_000))      # analysed again
    after = stamps(lib.paths, lib.tracks, load_state(lib.paths), running=never, place=lib.place)
    assert after[lib.tracks[0]] != got[lib.tracks[0]] and after[lib.tracks[2]] == got[lib.tracks[2]]
    (ext.parent / "ANLZ0000.3EX").unlink()                                                 # a file went
    assert set(stamps(lib.paths, lib.tracks[:1], load_state(lib.paths), running=never, place=lib.place)[
        lib.tracks[0]]) == {f"PIONEER/USBANLZ/000/1/ANLZ0000.{e}" for e in ("DAT", "EXT", "2EX")}


@needs_ffmpeg
def test_stamps_are_none_for_a_track_whose_analysis_folder_cannot_be_read(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "mp3"])
    folder = anlz_files(lib, 0)[0].parent
    folder.chmod(0)
    try:
        got = stamps(lib.paths, lib.tracks, load_state(lib.paths), running=never, place=lib.place)
    finally:
        folder.chmod(0o755)
    assert got[lib.tracks[0]] is None and got[lib.tracks[1]]                                # the other one is unaffected
    record(lib, 0, reason="timing", anlz=got[lib.tracks[0]])
    assert ready(lib).run == lib.tracks                                                    # no stamp: never holds


@needs_ffmpeg
def test_stamps_take_one_read_open_for_all_tracks_and_none_for_no_tracks(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "mp3", "aiff"])
    opened = []
    real = master.open_read
    monkeypatch.setattr(master, "open_read", lambda *a, **k: opened.append(1) or real(*a, **k))
    stamps(lib.paths, lib.tracks, load_state(lib.paths), running=never, place=lib.place)
    assert len(opened) == 1
    assert stamps(lib.paths, [], load_state(lib.paths), running=never, place=lib.place) == {}
    assert len(opened) == 1


@needs_ffmpeg
def test_stamps_are_none_when_the_library_cannot_be_read(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff"])
    state = load_state(lib.paths)
    assert stamps(lib.paths, lib.tracks, state, running=never, place=None) == dict.fromkeys(lib.tracks)
    gone = Place(lib.folder / "nothing.db", lib.folder / "share", "override", None)
    assert stamps(lib.paths, lib.tracks, state, running=never, place=gone) == dict.fromkeys(lib.tracks)
    lib.place.db.write_bytes(b"not a database")
    assert stamps(lib.paths, lib.tracks, state, running=never, place=lib.place) == dict.fromkeys(lib.tracks)
    state["tracks"][lib.tracks[0]]["path"] = None                                          # a song without a file
    assert stamps(lib.paths, lib.tracks[:1], state, running=never, place=lib.place) == {lib.tracks[0]: None}


# --- plan: the set (§0.3) ---

@needs_ffmpeg
def test_the_switch_off_plans_nothing(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff"])
    assert plan(lib.paths, load_state(lib.paths), (), OFF, running=never, place=lib.place) is None
    assert plan(lib.paths, load_state(lib.paths), (), OFF, running=lambda: True, place=lib.place) is None


@needs_ffmpeg
def test_the_set_is_the_parked_same_edit_upgrades_in_to_dos_order(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "stale", "aiff", "mp3_free", "mp3_plain"])
    answer = ready(lib)
    # `stale` is a different edit: it waits for the user's choice, so the phase leaves it out
    assert answer == Planned([lib.tracks[i] for i in (0, 2, 3, 4)], [], [], False)


@needs_ffmpeg
def test_hidden_held_missing_away_and_unsound_tracks_stay_out_of_the_set(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "mp3", "mp3", "mp3", "aiff", "aiff"])
    state = load_state(lib.paths)
    state["tracks"][lib.tracks[0]]["hidden"] = True
    state["tracks"][lib.tracks[3]]["upgrade"] = None                                       # nothing waiting
    save_state(lib.paths, state)
    (lib.paths.root / lib.olds[1]).unlink()                                                # its file is gone
    real = batches.present
    monkeypatch.setattr(batches, "present", lambda paths, e: "away" if e["path"] == lib.olds[4] else real(paths, e))
    answer = ready(lib, held=[lib.tracks[2]])
    assert answer.run == [lib.tracks[5]] and answer.waiting == [] and answer.refused == []
    assert ready(lib).run == [lib.tracks[2], lib.tracks[5]]                                 # without the question held


@needs_ffmpeg
def test_an_unreadable_library_keeps_only_the_aiff_swaps(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff"])
    lib.place.db.write_bytes(b"not a database")
    assert ready(lib).run == [lib.tracks[1]]


@needs_ffmpeg
def test_no_rekordbox_library_at_all_keeps_every_track(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff", "mp3_free"])
    assert ready(lib, place=None).run == lib.tracks


@needs_ffmpeg
def test_rekordboxs_status_is_asked_once_and_only_when_a_track_of_the_set_is_not_an_aiff(tmp_path, monkeypatch):
    asked = []
    real = master.status
    monkeypatch.setattr(master, "status", lambda *a, **k: asked.append(1) or real(*a, **k))
    for name in "abc":
        (tmp_path / name).mkdir()
    only_aiff = make_lib(tmp_path / "a", monkeypatch, ["aiff", "aiff"])
    assert ready(only_aiff).run == only_aiff.tracks and asked == []
    mixed = make_lib(tmp_path / "b", monkeypatch, ["aiff", "mp3", "mp3"])
    assert len(ready(mixed).run) == 3 and len(asked) == 1
    stale_only = make_lib(tmp_path / "c", monkeypatch, ["aiff", "stale"])                  # the MP3 is not in the set
    ready(stale_only)
    assert len(asked) == 1
    given = master.Status("unreadable", False, None, None, "key", None, None)             # the caller's own answer
    assert ready(mixed, status=given).run == [mixed.tracks[0]] and len(asked) == 1


# --- plan: rekordbox running (§0.4) ---

@needs_ffmpeg
def test_with_rekordbox_running_every_track_of_the_set_waits_and_no_stamp_is_read(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff", "stale", "mp3_plain"])
    record(lib, 3, anlz={"x": 1})
    asked = []
    real = master.status
    monkeypatch.setattr(master, "status", lambda *a, **k: asked.append(1) or real(*a, **k))
    monkeypatch.setattr(auto_upgrade, "stamps", lambda *a, **k: pytest.fail("stamps were read while rekordbox runs"))
    answer = ready(lib, running=lambda: True)
    assert answer == Planned([], [(lib.tracks[i], "rekordbox_open") for i in (0, 1, 3)], [], True)
    assert len(asked) == 1                                   # only its Status, as for Upgrade all's count


@needs_ffmpeg
def test_with_only_aiff_swaps_and_rekordbox_running_the_library_is_not_opened_at_all(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["aiff", "aiff"])
    for name in ("open_read", "status"):
        monkeypatch.setattr(master, name, lambda *a, **k: pytest.fail("rekordbox's library was opened"))
    assert ready(lib, running=lambda: True).waiting == [(k, "rekordbox_open") for k in lib.tracks]


@needs_ffmpeg
def test_running_is_asked_once_by_the_plan_itself(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff"])
    calls = []
    ready(lib, running=lambda: calls.append(1) or False)
    assert len(calls) == 1


# --- plan: recorded refusals (§0.7) ---

@needs_ffmpeg
def test_a_recorded_analysis_refusal_holds_until_rekordbox_analyses_the_track_again(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3_plain", "mp3"])
    stamp = stamps(lib.paths, lib.tracks, load_state(lib.paths), running=never, place=lib.place)
    record(lib, 0, reason="not_analysed", anlz=stamp[lib.tracks[0]])
    answer = ready(lib)
    assert answer.run == [lib.tracks[1]] and answer.waiting == []
    [(key, held)] = answer.refused
    assert key == lib.tracks[0] and held["reason"] == "not_analysed" and held["anlz"] == stamp[lib.tracks[0]]
    dat = anlz_files(lib, 0)[0]                                                            # rekordbox analyses it again
    os.utime(dat, ns=(dat.stat().st_atime_ns, dat.stat().st_mtime_ns + 5_000_000_000))
    assert ready(lib).run == lib.tracks and ready(lib).refused == []
    ext = dat.with_suffix(".EXT")                                                          # the first analysis adds a file
    record(lib, 0, reason="not_analysed", anlz=stamps(lib.paths, lib.tracks[:1], load_state(lib.paths), running=never,
                                                      place=lib.place)[lib.tracks[0]])
    assert ready(lib).refused != []
    ext.write_bytes(dat.read_bytes())
    assert ready(lib).run == lib.tracks


@needs_ffmpeg
def test_a_record_that_could_not_read_the_analysis_never_holds(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3_plain"])
    record(lib, 0, reason="timing", anlz=None)
    assert ready(lib).run == lib.tracks and ready(lib).refused == []


@needs_ffmpeg
def test_all_analysis_records_are_checked_with_one_read_open(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3_plain", "mp3", "mp3", "aiff"])
    stamp = stamps(lib.paths, lib.tracks, load_state(lib.paths), running=never, place=lib.place)
    for i, reason in ((0, "not_analysed"), (1, "timing"), (2, "cloud")):
        record(lib, i, reason=reason, anlz=stamp[lib.tracks[i]])
    opened = []
    real = master.open_read
    monkeypatch.setattr(master, "open_read", lambda *a, **k: opened.append(1) or real(*a, **k))
    answer = ready(lib)
    assert [k for k, _ in answer.refused] == lib.tracks[:3] and answer.run == [lib.tracks[3]]
    assert len(opened) == 2                                  # the status' open (an MP3 is in the set) + one for 3 stamps
    (tmp_path / "plain").mkdir()
    plain = make_lib(tmp_path / "plain", monkeypatch, ["mp3", "aiff"])
    opened.clear()
    ready(plain)                                             # no record: no stamps, only the status' one open
    assert len(opened) == 1


@needs_ffmpeg
def test_a_space_refusal_holds_until_the_drive_has_more_room(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "mp3"])
    record(lib, 0, reason="space", free=5_000_000, anlz=None)
    free = {"v": 5_000_000}
    monkeypatch.setattr(convert, "free_space", lambda path: free["v"])
    assert [k for k, _ in ready(lib).refused] == [lib.tracks[0]] and ready(lib).run == [lib.tracks[1]]
    free["v"] = 4_000_000
    assert ready(lib).refused != []
    free["v"] = 5_000_001
    assert ready(lib).refused == [] and ready(lib).run == lib.tracks
    assert free_now(lib.paths, load_state(lib.paths)["tracks"][lib.tracks[0]]) == 5_000_001


@needs_ffmpeg
def test_free_space_is_read_from_the_tracks_folder_and_only_for_space_records(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "mp3"])
    record(lib, 0, reason="space", free=1)
    asked = []
    monkeypatch.setattr(convert, "free_space", lambda path: asked.append(path) or 0)
    ready(lib)
    assert asked == [lib.paths.root / "Library/A"]
    monkeypatch.setattr(convert, "free_space", lambda path: (_ for _ in ()).throw(OSError("gone")))
    assert free_now(lib.paths, load_state(lib.paths)["tracks"][lib.tracks[0]]) is None
    assert ready(lib).run == lib.tracks                       # unreadable free space never holds


# --- plan against Upgrade all (§0.3) ---

def upgrade_all_set(api) -> set[str]:
    """What `HubApi.upgrade_all` would start: To-do's Upgrade ready items Same track can run for."""
    groups = api.todo("all", False)["groups"]
    return {i["track_id"] for g in groups if g["key"] == "upgrade_ready" for i in g["items"] if i["same_track"] is None}


def api_for(lib, running=False):
    return make_api(lib.paths, compare=lambda a, b: EXACT, rekordbox_running=lambda: running,
                    rekordbox_place=lambda: lib.place)[0]


@needs_ffmpeg
def test_the_set_equals_upgrade_alls_list(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff", "stale", "mp3_free", "mp3_plain", "mp3", "aiff"])
    state = load_state(lib.paths)
    state["tracks"][lib.tracks[0]]["hidden"] = True                                        # hidden
    save_state(lib.paths, state)
    (lib.paths.root / lib.olds[6]).unlink()                                                # the file is gone
    api = api_for(lib)
    mine = set(ready(lib).run)
    assert mine == upgrade_all_set(api) == {lib.tracks[i] for i in (1, 3, 4, 5)}


@needs_ffmpeg
def test_the_set_equals_upgrade_alls_list_with_an_unreadable_library(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff", "mp3_free"])
    lib.place.db.write_bytes(b"not a database")
    assert set(ready(lib).run) == upgrade_all_set(api_for(lib)) == {lib.tracks[1]}


@needs_ffmpeg
def test_the_set_equals_upgrade_alls_list_while_rekordbox_runs_it_waits_instead(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff", "stale"])
    api = api_for(lib, running=True)
    answer = ready(lib, running=lambda: True)
    assert {k for k, _ in answer.waiting} == upgrade_all_set(api) and answer.run == []


def unsupported_version(lib) -> None:
    """A rekordbox library of a version Discjockey doesn't know: unreadable, running or not."""
    con = _open(lib.place.db, KEYS[0])
    con.execute("UPDATE djmdProperty SET DBVersion = '5999'")
    con.commit()
    con.close()


@needs_ffmpeg
def test_the_set_equals_upgrade_alls_list_while_rekordbox_runs_on_a_library_it_cannot_read(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff", "mp3_free"])
    unsupported_version(lib)
    api = api_for(lib, running=True)
    answer = ready(lib, running=lambda: True)
    assert {k for k, _ in answer.waiting} == upgrade_all_set(api) == {lib.tracks[1]}   # the MP3s can't go: not waiting


@needs_ffmpeg
def test_a_held_question_keeps_the_song_out_exactly_as_to_do_does(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff"])
    from discjockey.hub import views
    held = {lib.tracks[0]}
    assert ready(lib, held=held).run == views.upgrade_ready_keys(load_state(lib.paths), held) == [lib.tracks[1]]


# --- the phase (plan §1.2, §5 C2) ---

def phase(lib, *, held=(), settings=ON, token=None, running=never, compare=lambda a, b: EXACT, dry_run=False,
          state=None, log=None):
    """`run_phase` as the sync calls it: returns (outcome, the state it worked on, the log, the events)."""
    state = load_state(lib.paths) if state is None else state
    log = log or RunLog(NOW)
    events: list = []
    out = run_phase(lib.paths, state, held, settings, log, emit=events.append, token=token, running=running,
                    place=lib.place, compare=compare, now=lambda: NOW, dry_run=dry_run)
    return out, state, log, events


def batch_count(lib) -> int:
    with db.connect(lib.paths.db_file) as conn:
        return db.aiff_batches(conn)[1]


def upgrade_of(lib, i: int) -> dict | None:
    return lib.entry(i)["upgrade"]


def untouched(lib):
    """Everything a phase could change: the music folder's bytes, rekordbox's library, the song records."""
    return lib.music(), lib.dump(), load_state(lib.paths)["tracks"], batch_count(lib)


def rows(out: Outcome) -> list[tuple[str, str, str | None]]:
    return [(r["track"], r["state"], r["reason"]) for r in out.results]


@needs_ffmpeg
def test_with_the_switch_off_the_phase_does_nothing_at_all(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff", "mp3_plain"])
    before = untouched(lib)
    for running in (never, lambda: True):
        out, _, log, events = phase(lib, settings=OFF, running=running)
        assert out is None and log.results == [] and log.auto_upgrade is None and events == []
    assert untouched(lib) == before


@needs_ffmpeg
def test_the_phase_upgrades_exactly_the_set_as_one_auto_batch_with_one_backup(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff", "stale", "mp3", "mp3", "mp3_free"])
    state = load_state(lib.paths)
    state["tracks"][lib.tracks[4]]["hidden"] = True
    save_state(lib.paths, state)
    out, state, log, events = phase(lib, held=[lib.tracks[3]])
    assert rows(out) == [(lib.tracks[i], "done", None) for i in (0, 1, 5)]
    assert (out.done, out.waiting, out.refused, out.failed, out.stopped, out.dry_run) == (3, 0, 0, 0, False, False)
    batch = lib.batch(out.batch)
    assert (batch.started_by, batch.scope, batch.state, batch.stop_reason) == ("auto_upgrade", "sync", "done", None)
    assert [i.state for i in batch.items] == ["done"] * 3 and batch.backup == out.backup is not None
    assert batch_count(lib) == 1 and [b.id for b in rbbackup.backups(lib.paths)] == [out.backup]   # one backup
    for i in (2, 3, 4):  # a different edit, a held question and a hidden track stay as they were
        assert upgrade_of(lib, i) and lib.entry(i)["path"] == lib.olds[i]
    assert (lib.paths.root / lib.olds[2]).is_file() and (lib.paths.root / lib.olds[3]).is_file()
    assert [(r.section, r.track_id) for r in log.results] == [("upgraded", lib.tracks[i]) for i in (0, 1, 5)]
    assert {(r.status, r.source) for r in log.results} == {("lossless", "qobuz")}
    assert [r.path for r in log.results] == [lib.entry(i)["path"] for i in (0, 1, 5)]
    assert log.auto_upgrade == out.to_dict() and state["tracks"][lib.tracks[0]]["path"] == lib.entry(0)["path"]
    assert out.results[0]["name"] == "Artist – Song 0" and [r["how"] for r in out.results] == \
        ["new_aiff", "in_place", "new_aiff"]
    assert [type(e) for e in events if not isinstance(e, BatchProgress)] == [Message]
    assert events[0].text == "Upgrading 3 tracks at the end of the sync..." and events[0].level == "info"
    assert isinstance(events[1], BatchProgress) and isinstance(events[-1], BatchProgress) and events[-1].done == 3


@needs_ffmpeg
def test_one_track_is_said_in_the_singular(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["aiff"])
    assert phase(lib)[3][0].text == "Upgrading 1 track at the end of the sync..."


@needs_ffmpeg
def test_a_phase_with_nothing_to_do_makes_an_empty_block_and_no_batch(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["stale"])
    before = untouched(lib)
    out, _, log, events = phase(lib)
    assert out == Outcome(None, None, 0, 0, 0, 0, False, False, []) and log.auto_upgrade == out.to_dict()
    assert log.results == [] and events == [] and untouched(lib) == before


@needs_ffmpeg
def test_a_dry_run_lists_what_it_would_do_and_writes_nothing(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff", "mp3_plain", "stale"])
    record(lib, 2, reason="not_analysed", anlz=stamps(lib.paths, [lib.tracks[2]], load_state(lib.paths), running=never,
                                                      place=lib.place)[lib.tracks[2]], message="held words")
    before = untouched(lib)
    out, state, log, events = phase(lib, dry_run=True, compare=lambda a, b: pytest.fail("compared in a dry run"))
    assert rows(out) == [(lib.tracks[0], "would", None), (lib.tracks[1], "would", None),
                         (lib.tracks[2], "refused", "not_analysed")]
    assert [r["how"] for r in out.results] == ["new_aiff", "in_place", "new_aiff"]
    assert (out.batch, out.backup, out.done, out.refused, out.dry_run) == (None, None, 0, 1, True)
    assert out.results[2]["message"] == "held words"
    assert log.results == [] and log.auto_upgrade is None and events == [] and untouched(lib) == before
    assert state == load_state(lib.paths)
    waiting, _, _, _ = phase(lib, dry_run=True, running=lambda: True)
    assert rows(waiting) == [(lib.tracks[i], "waiting", "rekordbox_open") for i in (0, 1, 2)] and waiting.waiting == 3
    assert untouched(lib) == before


@needs_ffmpeg
def test_stop_between_tracks_ends_the_batch_without_a_resume_and_keeps_the_done_one_undoable(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff", "mp3"])
    token = CancelToken()

    def compare(a, b):
        token.cancel()  # Stop is pressed while the first track is in work: it finishes, the others are not reached
        return EXACT

    out, state, log, _ = phase(lib, token=token, compare=compare)
    assert out.stopped and rows(out) == [(lib.tracks[0], "done", None), (lib.tracks[1], "waiting", "not_reached"),
                                         (lib.tracks[2], "waiting", "not_reached")]
    assert (out.done, out.waiting) == (1, 2) and out.results[1]["message"] == auto_upgrade.WAITS["not_reached"]
    batch = lib.batch(out.batch)
    assert batch.state == "done" and batch.backup == out.backup is not None
    assert [(i.state, i.reason) for i in batch.items] == [("done", None), ("skipped", "not_reached"),
                                                          ("skipped", "not_reached")]
    with db.connect(lib.paths.db_file) as conn:
        assert db.unfinished_aiff_batches(conn) == []            # nothing for To-do to resume
    assert [r.section for r in log.results] == ["upgraded", "upgrade_waits", "upgrade_waits"]
    assert all("auto_waits" not in (upgrade_of(lib, i) or {}) for i in (1, 2))   # not waiting for rekordbox
    undone = batches.undo(lib.paths, out.batch, running=never, place=lib.place, now=lambda: NOW)
    assert undone.undone == 1 and lib.entry(0)["path"] == lib.olds[0]


@needs_ffmpeg
def test_ctrl_c_files_what_was_done_and_is_raised_again(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "mp3", "mp3"])
    calls = []

    def compare(a, b):
        calls.append(1)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return EXACT

    log = RunLog(NOW)
    state = load_state(lib.paths)
    with pytest.raises(KeyboardInterrupt):
        phase(lib, compare=compare, log=log, state=state)
    block = log.auto_upgrade
    assert block["stopped"] and [r["state"] for r in block["results"]] == ["done", "waiting", "waiting"]
    assert {r["reason"] for r in block["results"][1:]} == {"not_reached"}
    assert [r.section for r in log.results] == ["upgraded", "upgrade_waits", "upgrade_waits"]
    assert lib.batch(block["batch"]).state == "done" and state["tracks"][lib.tracks[0]]["path"] != lib.olds[0]
    assert lib.entry(0)["path"] == state["tracks"][lib.tracks[0]]["path"]


@needs_ffmpeg
def test_rekordbox_open_at_the_start_does_nothing_and_marks_the_tracks_as_waiting(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff", "stale", "mp3_plain"])
    before = untouched(lib)
    out, state, log, events = phase(lib, running=lambda: True, compare=lambda a, b: pytest.fail("compared"))
    assert rows(out) == [(lib.tracks[i], "waiting", "rekordbox_open") for i in (0, 1, 3)]
    assert (out.batch, out.backup, out.done, out.waiting, out.stopped) == (None, None, 0, 3, False)
    assert batch_count(lib) == 0 and lib.music() == before[0] and lib.dump() == before[1]   # no batch, no backup
    assert not (lib.paths.data / "rekordbox").exists()
    marked = {k: e["upgrade"].get("auto_waits") for k, e in load_state(lib.paths)["tracks"].items()}
    assert marked == {lib.tracks[0]: NOW.isoformat(timespec="seconds"), lib.tracks[1]: NOW.isoformat(timespec="seconds"),
                      lib.tracks[2]: None, lib.tracks[3]: NOW.isoformat(timespec="seconds")}
    assert state["tracks"][lib.tracks[0]]["upgrade"]["auto_waits"] and "auto_refused" not in marked
    assert [(r.section, r.note) for r in log.results] == [("upgrade_waits", auto_upgrade.WAITS["rekordbox_open"])] * 3
    assert events == [Message("info", auto_upgrade.before_start_line(3))]
    assert log.auto_upgrade == out.to_dict()
    # rekordbox closed at the next sync: the marks go, the AIFFs go in, the unanalysed one is refused
    again, _, _, _ = phase(lib)
    assert rows(again) == [(lib.tracks[0], "done", None), (lib.tracks[1], "done", None),
                           (lib.tracks[3], "refused", "not_analysed")]
    assert "auto_waits" not in upgrade_of(lib, 3) and upgrade_of(lib, 3)["auto_refused"]["reason"] == "not_analysed"


def test_the_before_start_line_in_the_singular():
    assert auto_upgrade.before_start_line(1) == ("rekordbox is open: quit it before you start, so the sync can put 1 "
                                                 "upgrade in place at the end.")
    assert auto_upgrade.before_start_line(4).endswith("put 4 upgrades in place at the end.")


@needs_ffmpeg
def test_rekordbox_opening_mid_phase_rolls_the_track_in_work_back_and_the_rest_waits(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "mp3", "mp3"])
    flag, calls = {"open": False}, []

    def compare(a, b):
        calls.append(1)
        flag["open"] |= len(calls) == 2    # rekordbox is opened while the second track is in work
        return EXACT

    out, _, log, events = phase(lib, running=lambda: flag["open"], compare=compare)
    assert rows(out) == [(lib.tracks[0], "done", None), (lib.tracks[1], "waiting", "rekordbox_open"),
                         (lib.tracks[2], "waiting", "rekordbox_open")]
    assert not out.stopped and (out.done, out.waiting) == (1, 2) and out.backup is not None
    batch = lib.batch(out.batch)
    assert batch.state == "done" and [i.state for i in batch.items] == ["done", "skipped", "skipped"]
    for i in (1, 2):  # rolled back: file, record and rekordbox as they were; marked as waiting
        assert lib.entry(i)["path"] == lib.olds[i] and (lib.paths.root / lib.olds[i]).is_file()
        assert lib.row(i)["FolderPath"] == str(lib.paths.root / lib.olds[i])
        assert upgrade_of(lib, i)["auto_waits"] == NOW.isoformat(timespec="seconds")
    assert [r.section for r in log.results] == ["upgraded", "upgrade_waits", "upgrade_waits"]
    with db.connect(lib.paths.db_file) as conn:
        assert db.unfinished_aiff_batches(conn) == []
    flag["open"] = False
    again, _, _, _ = phase(lib, running=lambda: flag["open"])    # the next sync with rekordbox closed
    assert rows(again) == [(lib.tracks[i], "done", None) for i in (1, 2)]
    assert all(lib.entry(i)["upgrade"] is None for i in range(3))


@needs_ffmpeg
def test_another_window_changing_rekordbox_makes_every_track_wait_without_a_record(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff"])
    lib.paths.support.mkdir(parents=True, exist_ok=True)
    fd = os.open(lib.paths.support / "rekordbox.lock", os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        out, _, log, _ = phase(lib)
    finally:
        os.close(fd)
    assert rows(out) == [(lib.tracks[i], "waiting", "busy") for i in (0, 1)] and out.backup is None
    assert out.results[0]["message"] == auto_upgrade.WAITS["busy"]
    assert [i.state for i in lib.batch(out.batch).items] == ["skipped"] * 2 and lib.batch(out.batch).state == "done"
    assert all(set(upgrade_of(lib, i)) == {"file", "source", "source_id", "source_format", "found", "alignment"}
               for i in range(2))
    assert [r.section for r in log.results] == ["upgrade_waits"] * 2
    again, _, _, _ = phase(lib)                                              # the next sync simply tries again
    assert rows(again) == [(lib.tracks[i], "done", None) for i in (0, 1)]


@needs_ffmpeg
def test_a_failed_track_goes_to_errors_and_the_others_go_on(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["aiff", "aiff"])
    real = upgrades.swap

    def swap(paths, state, track, *a, **k):
        if track == lib.tracks[0]:
            raise RuntimeError("disk on fire")
        return real(paths, state, track, *a, **k)

    monkeypatch.setattr(upgrades, "swap", swap)
    out, _, log, _ = phase(lib)
    assert rows(out) == [(lib.tracks[0], "failed", None), (lib.tracks[1], "done", None)]
    assert (out.failed, out.done) == (1, 1)
    assert "disk on fire" in out.results[0]["message"]
    assert [(r.section, r.error_kind) for r in log.results] == [("errors", "other"), ("upgraded", None)]
    assert upgrade_of(lib, 0) and "auto_refused" not in upgrade_of(lib, 0)         # a failure is not recorded


# --- the records (plan §0.6, §0.7) ---

class Counting:
    """A `compare` that counts its calls."""

    def __init__(self, result=EXACT):
        self.calls, self.result = 0, result

    def __call__(self, a, b):
        self.calls += 1
        return self.result


@needs_ffmpeg
def test_a_refusal_is_recorded_with_its_stamps_and_not_decoded_again_until_rekordbox_analyses_again(tmp_path,
                                                                                                    monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3_plain", "aiff"])
    compare = Counting()
    out, state, log, _ = phase(lib, compare=compare)
    assert rows(out) == [(lib.tracks[0], "refused", "not_analysed"), (lib.tracks[1], "done", None)]
    assert (out.refused, out.done, compare.calls) == (1, 1, 2)
    record_ = upgrade_of(lib, 0)["auto_refused"]
    assert record_ == state["tracks"][lib.tracks[0]]["upgrade"]["auto_refused"]
    stamp = stamps(lib.paths, lib.tracks[:1], load_state(lib.paths), running=never, place=lib.place)[lib.tracks[0]]
    assert record_ == {"reason": "not_analysed", "message": out.results[0]["message"], "free": None, "anlz": stamp,
                       "at": NOW.isoformat(timespec="seconds")} and stamp
    assert out.results[0]["message"].startswith("rekordbox hasn't analysed this track yet")
    assert [(r.section, r.note) for r in log.results if r.track_id == lib.tracks[0]] == \
        [("upgrade_waits", out.results[0]["message"])]
    # the next sync: held, listed, not tried, no new batch or backup
    batches_before, before = batch_count(lib), lib.music()
    again, _, log2, events = phase(lib, compare=compare)
    assert rows(again) == [(lib.tracks[0], "refused", "not_analysed")] and compare.calls == 2
    assert (again.batch, again.backup, again.done, again.refused) == (None, None, 0, 1)
    assert again.results[0]["message"] == record_["message"] and events == []
    assert [r.section for r in log2.results] == ["upgrade_waits"] and lib.music() == before
    assert batch_count(lib) == batches_before
    # rekordbox analyses the track again (its analysis file's mtime changes): tried again, recorded again
    dat = anlz_files(lib, 0)[0]
    os.utime(dat, ns=(dat.stat().st_atime_ns, dat.stat().st_mtime_ns + 5_000_000_000))
    third, _, _, _ = phase(lib, compare=compare)
    assert rows(third) == [(lib.tracks[0], "refused", "not_analysed")] and compare.calls == 3
    assert third.batch is not None and upgrade_of(lib, 0)["auto_refused"]["anlz"] != stamp


@needs_ffmpeg
def test_a_space_refusal_is_tried_again_once_the_drive_has_more_room(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff"])
    free = {"v": 1000}
    monkeypatch.setattr(convert, "free_space", lambda path: free["v"])
    compare = Counting()
    out, _, _, _ = phase(lib, compare=compare)
    assert rows(out)[0] == (lib.tracks[0], "refused", "space") and "isn't enough free space" in out.results[0]["message"]
    rec = upgrade_of(lib, 0)["auto_refused"]
    assert (rec["reason"], rec["free"], rec["anlz"]) == ("space", 1000, None)   # measured at the refusal, not the item's
    calls = compare.calls
    held, _, _, _ = phase(lib, compare=compare)
    assert rows(held) == [(lib.tracks[0], "refused", "space")] and compare.calls == calls
    free["v"] = 10_000_000_000
    freed, _, _, _ = phase(lib, compare=compare)
    assert rows(freed) == [(lib.tracks[0], "done", None)] and compare.calls == calls + 1
    assert lib.entry(0)["upgrade"] is None


@needs_ffmpeg
def test_a_skip_the_phase_does_not_record_is_tried_at_the_next_sync(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff"])
    flag = {"busy": True}
    real = upgrades.swap

    def swap(paths, state, track, *a, **k):
        if flag["busy"]:
            raise convert.Skipped("changed", "Your rekordbox track changed while Discjockey was working on it, so "
                                  "nothing was changed. Try again.")
        return real(paths, state, track, *a, **k)

    monkeypatch.setattr(upgrades, "swap", swap)
    out, _, log, _ = phase(lib)
    assert rows(out) == [(lib.tracks[0], "done", None), (lib.tracks[1], "refused", "changed")] and out.refused == 1
    assert "auto_refused" not in upgrade_of(lib, 1) and [r.section for r in log.results] == ["upgraded", "upgrade_waits"]
    flag["busy"] = False
    again, _, _, _ = phase(lib)
    assert rows(again) == [(lib.tracks[1], "done", None)]


@needs_ffmpeg
def test_a_new_refusal_replaces_the_old_record_and_a_try_clears_the_waiting_mark(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3_plain", "mp3_plain"])
    state = load_state(lib.paths)
    for i, extra in ((0, {"auto_waits": "2026-11-01T10:00:00", "auto_refused": {"reason": "cloud", "message": "old",
                                                                               "at": "x", "anlz": {"a": 1}, "free": None}}),
                     (1, {"auto_waits": "2026-11-01T10:00:00"})):
        state["tracks"][lib.tracks[i]]["upgrade"].update(extra)
    save_state(lib.paths, state)
    out, _, _, _ = phase(lib)
    assert rows(out) == [(lib.tracks[i], "refused", "not_analysed") for i in (0, 1)]
    for i in (0, 1):
        up = upgrade_of(lib, i)
        assert "auto_waits" not in up and up["auto_refused"]["reason"] == "not_analysed" and up["auto_refused"]["message"] != "old"


@needs_ffmpeg
def test_a_held_refusal_reached_with_rekordbox_closed_loses_only_its_waiting_mark(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3_plain"])
    stamp = stamps(lib.paths, lib.tracks, load_state(lib.paths), running=never, place=lib.place)[lib.tracks[0]]
    state = load_state(lib.paths)
    state["tracks"][lib.tracks[0]]["upgrade"]["auto_waits"] = "2026-11-01T10:00:00"
    save_state(lib.paths, state)
    record(lib, 0, reason="not_analysed", anlz=stamp)
    state = load_state(lib.paths)
    state["tracks"][lib.tracks[0]]["upgrade"]["auto_waits"] = "2026-11-01T10:00:00"
    save_state(lib.paths, state)
    out, _, _, _ = phase(lib)
    assert rows(out) == [(lib.tracks[0], "refused", "not_analysed")] and out.batch is None
    assert set(upgrade_of(lib, 0)) >= {"auto_refused"} and "auto_waits" not in upgrade_of(lib, 0)
    # rekordbox open: a held refusal is not looked at, the track just waits
    waiting, _, _, _ = phase(lib, running=lambda: True)
    assert rows(waiting) == [(lib.tracks[0], "waiting", "rekordbox_open")] and "auto_refused" in upgrade_of(lib, 0)


# --- stage B's loose end: a re-measure that says "not the same edit" is stored (plan §7 C2 check first) ---

@needs_ffmpeg
def test_a_swap_that_measures_a_different_edit_stores_it_so_the_track_stops_being_offered(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["aiff"])
    state = load_state(lib.paths)
    up = dict(state["tracks"][lib.tracks[0]]["upgrade"])
    with pytest.raises(upgrades.NeedsChoice):
        upgrades.swap(lib.paths, state, lib.tracks[0], up, lambda a, b: DIFFERENT, lambda: NOW)
    assert lib.entry(0)["upgrade"]["alignment"] == DIFFERENT.to_dict() == state["tracks"][lib.tracks[0]]["upgrade"]["alignment"]
    assert lib.entry(0)["path"] == lib.olds[0]
    counted = Counting()
    out, _, _, _ = phase(lib, compare=counted)
    assert out.results == [] and counted.calls == 0        # out of the set: the sync does not decode it again


@needs_ffmpeg
def test_same_track_that_measures_a_different_edit_stores_it_too_and_an_unknown_measure_changes_nothing(tmp_path,
                                                                                                       monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3"])
    unknown = Counting(Alignment("unknown", text="could not compare the two versions"))
    out, _, _, _ = phase(lib, compare=unknown)
    assert rows(out) == [(lib.tracks[0], "refused", "needs_choice")] and unknown.calls == 1
    assert upgrade_of(lib, 0)["alignment"] == EXACT.to_dict()                          # unknown: the stored one stays
    different = Counting(DIFFERENT)
    out, _, _, _ = phase(lib, compare=different)
    assert rows(out) == [(lib.tracks[0], "refused", "needs_choice")] and "auto_refused" not in upgrade_of(lib, 0)
    assert upgrade_of(lib, 0)["alignment"] == DIFFERENT.to_dict() and lib.entry(0)["path"] == lib.olds[0]
    assert phase(lib, compare=different)[0].results == [] and different.calls == 1
