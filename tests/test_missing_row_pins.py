"""Issue 43 §3, the rows that stay as they are: a song whose file waits as missing keeps its path and its mark, the
live disk check says the file is not there, and every step that needs the file refuses it by the old paths. These pin
that nothing acts on a missing row (a file back on disk is simply there again: the check is the disk's, not the mark's)."""
from __future__ import annotations

import pytest

from discjockey import batches, convert, upgrades
from discjockey.library import Paths, empty_state
from discjockey.models import file_missing
from discjockey.planner import ENTRY_KEYS
from discjockey.rekordbox import Status
from discjockey.rekordbox.eligible import Skip, convert as convert_verdict, rename, same_track, same_track_quick
from discjockey.upgrades import UpgradeProblem

READY = Status("ready", False, "7.0.0", "/rb/master.db", None, "6000", "1")
CURRENT = "Library/A/not_lossless/Artist - Song.flac"
PARKED = "Upgrades ready/A/Artist - Song.aiff"
TID = "t1aaaaaaa"
SINCE = "2026-11-10T09:00:00"


def entry(**kw):
    e = dict.fromkeys(ENTRY_KEYS)
    e.update(aliases=[], artist="Artist", title="Song", duration_ms=180000, folder="A", path=CURRENT,
             status="not_lossless", source="manual", rejected_sources=[], in_playlists=False, missing_since=SINCE,
             upgrade={"file": PARKED, "source": "qobuz", "source_id": "q1", "source_format": "flac",
                      "found": "2026-11-01", "alignment": {"result": "exact", "text": "x"}})
    e.update(kw)
    return e


@pytest.fixture
def env(tmp_path):
    """A missing row: the parked upgrade is there, the current file is not."""
    paths = Paths(tmp_path, support=tmp_path / ".support")
    (paths.root / PARKED).parent.mkdir(parents=True)
    (paths.root / PARKED).write_bytes(b"new audio")
    state = empty_state()
    state["tracks"][TID] = entry()
    return paths, state


def why(verdict):
    return verdict.reason if isinstance(verdict, Skip) else None


def test_the_live_disk_check_calls_a_missing_row_missing_and_one_on_an_absent_drive_away(env):
    paths, state = env
    e = state["tracks"][TID]
    assert file_missing(e) and batches.present(paths, e) == "missing"
    assert batches.present(paths, {**e, "path": "/Volumes/Nowhere Drive/Music/x.flac"}) == "away"
    assert batches.present(paths, {**e, "path": None}) == "missing"
    (paths.root / CURRENT).parent.mkdir(parents=True)
    (paths.root / CURRENT).write_bytes(b"back")  # its file is back before the next scan: it is simply there
    assert batches.present(paths, e) == "here"


def test_every_step_that_needs_the_file_skips_a_missing_row_with_file_missing(env):
    paths, state = env
    e = state["tracks"][TID]
    present = batches.present(paths, e)
    assert why(same_track_quick(e, READY, present)) == "file_missing"
    assert why(same_track(e, None, READY, None, present=present)) == "file_missing"
    assert why(convert_verdict(e, None, READY, None, present=present)) == "file_missing"
    assert why(rename(e, None, READY, None, present=present)) == "file_missing"
    assert batches.quick_reason(paths, e, READY) == "file_missing"
    assert batches.quick_reason(paths, entry(upgrade=None), READY) == "no_upgrade"  # nothing parked: say that


def test_same_track_swap_and_add_as_new_refuse_a_missing_row_and_change_nothing(env):
    paths, state = env
    upgrade = dict(state["tracks"][TID]["upgrade"])
    before = {**state["tracks"][TID]}
    for step in (lambda: upgrades.swap(paths, state, TID, upgrade),
                 lambda: upgrades.add_new(paths, state, TID, upgrade),
                 lambda: upgrades.check(paths, state, TID),
                 lambda: convert.same_track(paths, state, TID, upgrade, session=None)):
        with pytest.raises(UpgradeProblem, match="Run a sync first"):
            step()
    assert state["tracks"][TID] == before and (paths.root / PARKED).read_bytes() == b"new audio"


def test_discard_needs_no_current_file_and_works_for_a_missing_row(env):
    paths, state = env
    upgrades.discard(paths, state, TID, dict(state["tracks"][TID]["upgrade"]))
    e = state["tracks"][TID]
    assert e["upgrade"] is None and e["missing_since"] == SINCE and e["path"] == CURRENT
    assert not (paths.root / PARKED).exists()
