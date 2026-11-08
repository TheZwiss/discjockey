"""Undo of an upgrade (upgrades.undo): Swap and Add as new file put back as they were while the rekordbox check
stands. Add as new file comes in two kinds: renamed (`add_new`: rekordbox's timing unknown, the download itself is
the new file) and rendered (`add_new_rendered`: lined up, the download kept for the undo). Temp libraries only; tiny
byte files (the content key falls back to the whole file)."""
import copy
import os
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from discjockey import db, library, ops, upgrades
from discjockey.align import Alignment
from discjockey.hub.views import todo
from discjockey.library import Paths, clear_tmp, empty_state, load_state, recover_pending, save_state
from discjockey.planner import ENTRY_KEYS
from discjockey.report import SWAPPED_CHECK, SWAPPED_MOVED_CHECK, check_text
from discjockey.upgrades import UpgradeProblem
from hub_helpers import records

TID = "t1aaaaaaa"
CURRENT = "Library/A/not_lossless/Artist - Song.aiff"
ROOT_NAME = "Library/A/Artist - Song.aiff"
PARKED = "Upgrades ready/A/Artist - Song.aiff"
SUPERSEDED = "Superseded/A/Artist - Song.aiff"
BACKUP = "Superseded/A/Artist - Song (lossy).aiff"
OLD, PARKED_AUDIO, NEW = b"old audio " * 1000, b"new audio " * 1000, b"NEW AUDIO " * 1200
SHIFT = Alignment("shifted", 4, 0.091, 0.0, "lines up after shifting by 0 ms")
NOW = lambda: datetime(2026, 10, 31, 12, 0)  # noqa: E731


class Crash(BaseException):
    pass


def make_entry():
    e = dict.fromkeys(ENTRY_KEYS)
    e.update(aliases=[], artist="Artist", title="Song", duration_ms=40000, folder="A", path=CURRENT,
             status="not_lossless", source="youtube_music", source_id="y1", source_format="opus", cutoff_hz=16000,
             source_how="fallback",
             rejected_sources=[], in_playlists=True, added="2026-10-01T10:00:00", last_attempt="2026-10-01",
             last_upgrade_check="2026-10-10",
             upgrade={"file": PARKED, "source": "qobuz", "source_id": "q1", "source_format": "flac",
                      "how": "exact", "found": "2026-10-10", "alignment": SHIFT.to_dict()})
    return e


@pytest.fixture
def env(tmp_path, monkeypatch):
    paths = Paths(tmp_path, support=tmp_path / ".support")
    for rel, data in ((CURRENT, OLD), (PARKED, PARKED_AUDIO)):
        (paths.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (paths.root / rel).write_bytes(data)
    state = empty_state()
    state["tracks"][TID] = make_entry()
    save_state(paths, state)
    monkeypatch.setattr(upgrades, "build_staged", lambda parked, staged, n: staged.write_bytes(NEW))
    return paths, state


KINDS = ["swap", "add_new", "add_new_rendered"]


def step(paths, state, kind):
    up = dict(state["tracks"][TID]["upgrade"])
    if kind == "swap":
        return upgrades.swap(paths, state, TID, up, compare=lambda cur, new: SHIFT, now=NOW)
    d = 0 if kind == "add_new_rendered" else None  # rekordbox's timing known (an AIFF: 0) or not
    return upgrades.add_new(paths, state, TID, up, compare=lambda cur, new: SHIFT,
                            offset=lambda old: SimpleNamespace(samples=d), now=NOW)


def read(paths, rel):
    return (paths.root / rel).read_bytes() if (paths.root / rel).exists() else None


def assert_as_before(paths, state, original, inode=None):
    """Everything as before the step: the old file at its path, the parked one waiting, the entry, nothing kept."""
    assert read(paths, CURRENT) == OLD and read(paths, PARKED) == PARKED_AUDIO
    assert read(paths, ROOT_NAME) is None and read(paths, SUPERSEDED) is None and read(paths, BACKUP) is None
    if inode is not None:  # a swap's undo writes into the same file, so rekordbox keeps its entry
        assert os.stat(paths.root / CURRENT).st_ino == inode
    want = {"rekordbox_check": None, **original}  # (an entry read back from library.db also has its file row's fields)
    assert {k: state["tracks"][TID].get(k) for k in want} == want and state["pending"] == []
    assert records(load_state(paths)) == records(state)
    save_state(paths, state)  # the caller's snapshot is current: it goes on saving it
    assert [k for k, _ in upgrades.ready(state, ["A"])] == [TID]  # the upgrade offer shows again
    renders = [p.read_bytes() for p in paths.undo.rglob("*.aiff")] if paths.undo.exists() else []
    assert renders in ([], [NEW])  # a rendered add's render waits for the clean-up; nothing else is kept
    clear_tmp(paths, state)
    assert not paths.undo.exists() or not any(paths.undo.rglob("*.aiff"))


# --- the records the steps leave ---

def test_add_as_new_keeps_an_undo_in_its_check(env):
    paths, state = env
    original = copy.deepcopy(state["tracks"][TID])
    step(paths, state, "add_new")
    u = state["tracks"][TID]["rekordbox_check"]["undo"]
    assert (u["kind"], u["file"], u["old"]) == ("add_new", ROOT_NAME, SUPERSEDED)
    assert u["before"]["path"] == CURRENT and u["before"]["upgrade"] == original["upgrade"]
    assert u["file_key"].startswith("1:") and u["old_key"].startswith("1:") and u["file_key"] != u["old_key"]
    assert upgrades.can_undo(state["tracks"][TID])


def test_a_rendered_add_keeps_the_download_and_the_renders_key(env):
    paths, state = env
    original = copy.deepcopy(state["tracks"][TID])
    step(paths, state, "add_new_rendered")
    check = state["tracks"][TID]["rekordbox_check"]
    assert {k: v for k, v in check.items() if k != "undo"} == {
        "reason": "added_as_new", "since": "2026-10-31", "match": "shifted", "offset_ms": 0.091, "aligned": True}
    u = check["undo"]
    assert (u["kind"], u["file"], u["old"], u["rendered"]) == ("add_new", ROOT_NAME, SUPERSEDED, True)
    assert u["before"]["upgrade"] == original["upgrade"]
    assert u["file_key"] == library.content_key(paths.root / ROOT_NAME) and read(paths, ROOT_NAME) == NEW
    assert u["held"].startswith(f".discjockey/undo/{TID}/") and read(paths, u["held"]) == PARKED_AUDIO
    assert read(paths, PARKED) is None and not (paths.tmp / TID).exists()
    assert upgrades.can_undo(state["tracks"][TID])


def test_undo_of_a_rendered_add_refused_without_the_kept_download(env):
    paths, state = env
    step(paths, state, "add_new_rendered")
    (paths.root / state["tracks"][TID]["rekordbox_check"]["undo"]["held"]).unlink()
    with pytest.raises(UpgradeProblem, match="kept for the undo is gone, so the upgrade can't be undone"):
        upgrades.undo(paths, state, TID)
    assert read(paths, ROOT_NAME) == NEW and read(paths, SUPERSEDED) == OLD and state["pending"] == []


def test_swap_asks_for_a_rekordbox_check_with_an_undo_and_keeps_the_parked_download(env):
    paths, state = env
    step(paths, state, "swap")
    check = state["tracks"][TID]["rekordbox_check"]
    assert {k: v for k, v in check.items() if k != "undo"} == {
        "reason": "swapped", "since": "2026-10-31", "match": "shifted", "offset_ms": 0.091, "moved": True}
    assert check_text(check) == SWAPPED_MOVED_CHECK and check_text({**check, "moved": False}) == SWAPPED_CHECK
    u = check["undo"]
    assert (u["kind"], u["file"], u["old"]) == ("swap", ROOT_NAME, BACKUP)
    assert read(paths, PARKED) is None and read(paths, u["held"]) == PARKED_AUDIO  # kept out of Upgrades ready/
    assert u["held"].startswith(".discjockey/undo/")
    assert upgrades.can_undo(state["tracks"][TID])


def test_the_to_do_says_whether_undo_is_there(env):
    paths, state = env
    step(paths, state, "add_new")
    [group] = [g for g in todo(state, "all", False, {}, date(2026, 10, 31))["groups"] if g["key"] == "rekordbox_check"]
    assert group["items"][0]["can_undo"] is True


# --- undo ---

@pytest.mark.parametrize("kind", KINDS)
def test_undo_puts_everything_back(env, kind):
    paths, state = env
    original = copy.deepcopy(state["tracks"][TID])
    inode = os.stat(paths.root / CURRENT).st_ino
    step(paths, state, kind)
    r = upgrades.undo(paths, state, TID)
    assert (r.section, r.path, r.status) == ("upgrade_undone", CURRENT, "not_lossless")
    assert_as_before(paths, state, original, inode if kind == "swap" else None)


@pytest.mark.parametrize("kind", KINDS)
def test_the_step_moves_the_parked_how_into_the_entry_and_undo_puts_the_old_one_back(env, kind):
    paths, state = env
    assert state["tracks"][TID]["source_how"] == "fallback"
    step(paths, state, kind)
    assert state["tracks"][TID]["source_how"] == "exact"
    assert load_state(paths)["tracks"][TID]["source_how"] == "exact"
    upgrades.undo(paths, state, TID)
    assert state["tracks"][TID]["source_how"] == "fallback"


def test_an_upgrade_parked_before_how_existed_swaps_in_with_no_how(env):
    paths, state = env
    del state["tracks"][TID]["upgrade"]["how"]
    step(paths, state, "swap")
    assert state["tracks"][TID]["source_how"] is None


@pytest.mark.parametrize("kind", KINDS)
def test_undo_then_the_same_step_again_works(env, kind):
    paths, state = env
    step(paths, state, kind)
    upgrades.undo(paths, state, TID)
    step(paths, state, kind)
    assert upgrades.can_undo(state["tracks"][TID]) and read(paths, ROOT_NAME) is not None


@pytest.mark.parametrize("kind", ["add_new", "add_new_rendered"])
def test_undo_of_add_as_new_when_the_old_file_had_the_name(env, kind):
    paths, state = env
    (paths.root / CURRENT).rename(paths.root / ROOT_NAME)
    state["tracks"][TID]["path"] = ROOT_NAME
    original = copy.deepcopy(state["tracks"][TID])
    step(paths, state, kind)
    assert read(paths, ROOT_NAME) == (NEW if kind == "add_new_rendered" else PARKED_AUDIO)
    assert read(paths, SUPERSEDED) == OLD
    upgrades.undo(paths, state, TID)
    assert read(paths, ROOT_NAME) == OLD and read(paths, PARKED) == PARKED_AUDIO and read(paths, SUPERSEDED) is None
    assert state["tracks"][TID] == {"rekordbox_check": None, **original}


def test_undo_brings_back_a_check_that_stood_before(env):
    paths, state = env
    state["tracks"][TID]["rekordbox_check"] = {"reason": "wrong_song", "since": "2026-10-20"}
    step(paths, state, "add_new")
    upgrades.undo(paths, state, TID)
    assert state["tracks"][TID]["rekordbox_check"] == {"reason": "wrong_song", "since": "2026-10-20"}


# --- refusals: nothing changes ---

def files(paths):
    return {p.relative_to(paths.root).as_posix(): p.read_bytes() for p in paths.root.rglob("*.aiff")}


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("which", ["file", "old"])
def test_undo_refused_when_either_file_changed(env, kind, which):
    paths, state = env
    step(paths, state, kind)
    u = state["tracks"][TID]["rekordbox_check"]["undo"]
    (paths.root / u[which]).write_bytes(b"edited by another program " * 100)
    before, entry = files(paths), copy.deepcopy(state["tracks"][TID])
    with pytest.raises(UpgradeProblem, match="changed since the upgrade"):
        upgrades.undo(paths, state, TID)
    assert files(paths) == before and state["tracks"][TID] == entry and state["pending"] == []


@pytest.mark.parametrize("kind", KINDS)
def test_undo_refused_when_a_file_is_gone(env, kind):
    paths, state = env
    step(paths, state, kind)
    (paths.root / state["tracks"][TID]["rekordbox_check"]["undo"]["old"]).unlink()
    with pytest.raises(UpgradeProblem, match="is gone"):
        upgrades.undo(paths, state, TID)
    assert read(paths, ROOT_NAME) is not None and state["tracks"][TID]["status"] == "lossless"


@pytest.mark.parametrize("kind", KINDS)
def test_undo_refused_when_another_file_took_a_place(env, kind):
    paths, state = env
    step(paths, state, kind)
    (paths.root / PARKED).parent.mkdir(parents=True, exist_ok=True)
    (paths.root / PARKED).write_bytes(b"someone else's file")
    with pytest.raises(UpgradeProblem, match="Another file is at"):
        upgrades.undo(paths, state, TID)
    assert read(paths, PARKED) == b"someone else's file" and read(paths, ROOT_NAME) is not None


def test_undo_refused_when_a_newer_version_waits(env):
    paths, state = env
    step(paths, state, "add_new")
    state["tracks"][TID]["upgrade"] = {"file": "Upgrades ready/A/Artist - Song (2).aiff", "source": "qobuz",
                                       "source_id": "q9", "source_format": "flac", "found": "2026-10-31"}
    assert not upgrades.can_undo(state["tracks"][TID])
    with pytest.raises(UpgradeProblem, match="Another better version"):
        upgrades.undo(paths, state, TID)


def test_no_undo_for_a_step_from_before_undo_existed(env):
    paths, state = env
    step(paths, state, "add_new")
    del state["tracks"][TID]["rekordbox_check"]["undo"]  # what an older Discjockey wrote
    assert not upgrades.can_undo(state["tracks"][TID])
    with pytest.raises(UpgradeProblem, match="no upgrade to undo"):
        upgrades.undo(paths, state, TID)
    assert read(paths, ROOT_NAME) == PARKED_AUDIO and read(paths, SUPERSEDED) == OLD


# --- Done ends it ---

@pytest.mark.parametrize("kind", KINDS)
def test_undo_is_gone_after_done(env, kind):
    paths, state = env
    step(paths, state, kind)
    held = state["tracks"][TID]["rekordbox_check"]["undo"].get("held")
    ops.rekordbox_checked(paths, state, TID)
    assert not upgrades.can_undo(state["tracks"][TID])
    with pytest.raises(UpgradeProblem, match="no upgrade to undo"):
        upgrades.undo(paths, state, TID)
    if held:  # the kept download goes with it
        assert not (paths.root / held).exists() and not (paths.root / held).parent.exists()


def test_a_kept_download_no_record_names_is_cleaned_up(env):
    paths, state = env
    step(paths, state, "swap")
    held = state["tracks"][TID]["rekordbox_check"]["undo"]["held"]
    clear_tmp(paths, state)
    assert (paths.root / held).exists()  # still named by the check
    stray = paths.undo / "t9zzzzzzz" / "Other - Song.aiff"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"x")
    state["tracks"][TID]["rekordbox_check"] = {"reason": "wrong_song", "since": "2026-10-31"}  # a later step
    clear_tmp(paths, state)
    assert not (paths.root / held).exists() and not stray.exists() and not any(paths.undo.iterdir())
    clear_tmp(paths)  # without the records nothing kept is touched
    assert paths.undo.is_dir()


# --- crash safety ---

@pytest.mark.parametrize("kind,renames_done", [("add_new", 0), ("add_new", 1), ("add_new_rendered", 0),
                                                ("add_new_rendered", 1), ("add_new_rendered", 2)])
def test_a_crash_while_undoing_add_as_new_is_finished_at_the_next_start(env, monkeypatch, kind, renames_done):
    paths, state = env
    original = copy.deepcopy(state["tracks"][TID])
    step(paths, state, kind)
    real, done = library.move_path, []

    def power_off(*args, **kwargs):
        if len(done) == renames_done:
            raise Crash()
        done.append(real(*args, **kwargs))

    monkeypatch.setattr(library, "move_path", power_off)
    with pytest.raises(Crash):
        upgrades.undo(paths, state, TID)
    monkeypatch.setattr(library, "move_path", real)
    state = load_state(paths)
    assert bool(state["pending"]) == bool(renames_done)  # run_op drops a step that moved nothing at once
    recover_pending(paths, state)
    if renames_done:  # a file was placed: the step is finished
        assert_as_before(paths, state, original)
    else:  # nothing moved: the step is dropped, the upgrade stays and can still be undone
        assert state["pending"] == [] and upgrades.can_undo(state["tracks"][TID])
        upgrades.undo(paths, state, TID)
        assert_as_before(paths, state, original)


def crash_swap_undo(env, monkeypatch, name, half=False, earlier=False, nth=1):
    """`earlier`: the pending row as a version before issue 25 wrote it (through the snapshot: no op_id). `nth`: the
    call of `name` the power cut comes at."""
    paths, state = env
    original = copy.deepcopy(state["tracks"][TID])
    inode = os.stat(paths.root / CURRENT).st_ino
    step(paths, state, "swap")
    real = getattr(upgrades, name)
    calls = []

    def boom(*args, **kwargs):
        calls.append(args)
        if len(calls) < nth:
            return real(*args, **kwargs)
        if half:  # _write_in_place(target, source, sha): half of the old content is on disk
            with open(args[0], "r+b") as f:
                f.write(args[1].read_bytes()[: len(OLD) // 2])
        raise Crash()

    monkeypatch.setattr(upgrades, name, boom)
    with pytest.raises(Crash):
        upgrades.undo(paths, state, TID)
    monkeypatch.setattr(upgrades, name, real)
    if earlier:
        with db.connect(paths.db_file) as conn, db.transaction(conn):
            conn.execute("UPDATE pending SET op = json_remove(op, '$.op_id')")
    on_disk = load_state(paths)
    assert [op["kind"] for op in on_disk["pending"]] == ["swap_undo"]
    assert ("op_id" in on_disk["pending"][0]) is not earlier  # journaled in library.db (issue 25), or the old way
    return paths, on_disk, original, inode


@pytest.mark.parametrize("earlier", [False, True], ids=["journal", "earlier row"])
@pytest.mark.parametrize("name,half,nth", [("_write_in_place", False, 1), ("_write_in_place", True, 1),
                                           ("safe_rename", False, 1), ("safe_rename", False, 2)],
                         ids=["before the write-back", "half written back", "written back", "file back home"])
def test_a_crash_while_undoing_a_swap_is_finished_at_the_next_start(env, monkeypatch, name, half, nth, earlier):
    paths, state, original, inode = crash_swap_undo(env, monkeypatch, name, half, earlier, nth)
    clear_tmp(paths, state)  # the kept download survives the clean-up while the step is pending
    [(message, ok)] = recover_pending(paths, state)
    assert ok and message == "Finished undoing the swap for Artist - Song"
    assert_as_before(paths, state, original, inode)


@pytest.mark.parametrize("earlier", [False, True], ids=["journal", "earlier row"])
def test_an_interrupted_swap_undo_without_its_backup_changes_nothing(env, monkeypatch, earlier):
    paths, state, _, _ = crash_swap_undo(env, monkeypatch, "_write_in_place", earlier=earlier)
    (paths.root / BACKUP).unlink()
    [(message, ok)] = recover_pending(paths, state)
    assert not ok and "was not undone" in message and state["pending"] == []
    assert read(paths, ROOT_NAME) == NEW and state["tracks"][TID]["status"] == "lossless"
    assert records(load_state(paths)) == records(state)
    save_state(paths, state)


@pytest.mark.parametrize("earlier", [False, True], ids=["journal", "earlier row"])
def test_an_interrupted_swap_undo_that_needs_help_stays_journaled(env, monkeypatch, earlier):
    paths, state, _, _ = crash_swap_undo(env, monkeypatch, "_write_in_place", half=True, earlier=earlier)
    (paths.root / BACKUP).unlink()
    [(message, ok)] = recover_pending(paths, state)
    assert not ok and "needs your help" in message
    save_state(paths, state)  # the caller's next save keeps the step for the start after
    assert [op["kind"] for op in load_state(paths)["pending"]] == ["swap_undo"]
    assert records(load_state(paths)) == records(state)
