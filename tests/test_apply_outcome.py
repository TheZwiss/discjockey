from datetime import datetime

import pytest

from discjockey.models import Action, Outcome, Placed, SpotifyTrack
from discjockey.planner import ENTRY_KEYS, apply_outcome

NOW = datetime(2026, 10, 20, 12, 30, 0)
T = SpotifyTrack("t1", "Song", ("Artist", "Other"), "Album", None, 180000, "DE1")


def act(kind, aliases=()):
    return Action(kind, "t1", "A", T, (0, 0), aliases=aliases)


def placed(status="lossless", path="Library/A/Artist - Song.aiff", source="qobuz"):
    return Outcome("placed", Placed(path, status, source, "q1", "flac", None), rejected=("youtube:y1",))


def existing(**kw):
    e = dict.fromkeys(ENTRY_KEYS)
    e.update(aliases=[], isrc="DE1", artist="Artist", title="Song", duration_ms=180000, folder="A",
             path="Library/A/not_lossless/Artist - Song.aiff", status="not_lossless", source="youtube",
             source_id="y0", source_format="opus", cutoff_hz=20000, rejected_sources=["qobuz:9"],
             in_playlists=True, added="2026-10-01T10:00:00", last_attempt="2026-10-01",
             last_upgrade_check="2026-10-01")
    e.update(kw)
    return e


def test_new_track_placed_has_every_key():
    e = apply_outcome(None, act("acquire", aliases=("t2",)), placed(), NOW)
    assert set(e) == set(ENTRY_KEYS)
    assert e["aliases"] == ["t2"]
    assert (e["artist"], e["title"], e["isrc"], e["duration_ms"]) == ("Artist", "Song", "DE1", 180000)
    assert (e["status"], e["path"], e["source"], e["source_id"]) == ("lossless", "Library/A/Artist - Song.aiff", "qobuz", "q1")
    assert e["added"] == "2026-10-20T12:30:00"
    assert e["last_attempt"] == e["last_upgrade_check"] == "2026-10-20"
    assert e["rejected_sources"] == ["youtube:y1"]
    assert e["in_playlists"] is True


def test_missing():
    e = apply_outcome(None, act("acquire"), Outcome("missing", rejected=("qobuz:5",)), NOW)
    assert e["status"] == "missing" and e["path"] is None and e["source"] is None
    assert e["last_attempt"] == "2026-10-20"
    assert e["rejected_sources"] == ["qobuz:5"]


def test_errored_new_track_creates_nothing():
    assert apply_outcome(None, act("acquire"), Outcome("errored", rejected=("qobuz:5",)), NOW) is None


def test_errored_existing_entry_only_merges_rejected():
    before = existing()
    e = apply_outcome(before, act("acquire"), Outcome("errored", rejected=("qobuz:5",)), NOW)
    assert e["rejected_sources"] == ["qobuz:5", "qobuz:9"]
    assert {k: v for k, v in e.items() if k != "rejected_sources"} == {
        k: v for k, v in before.items() if k != "rejected_sources"}


def test_upgrade_checked_without_result():
    e = apply_outcome(existing(), act("upgrade"), Outcome("checked", rejected=("qobuz:7",)), NOW)
    assert e["status"] == "not_lossless"
    assert e["last_upgrade_check"] == "2026-10-20"
    assert "qobuz:7" in e["rejected_sources"]


@pytest.mark.parametrize("kind", ["checked", "queued", "errored", "parked"])
def test_upgrade_check_never_marks_the_current_file_wrong(kind):
    # the current upload's account stream that came out no better is declined, not "wrong song" (rejected_sources)
    out = Outcome(kind, rejected=("youtube:y0", "qobuz:7"), upgrade=UPGRADE if kind == "parked" else None)
    e = apply_outcome(existing(declined_streams=["youtube:y9"]), act("upgrade"), out, NOW)
    assert e["rejected_sources"] == ["qobuz:7", "qobuz:9"]
    assert e["declined_streams"] == ["youtube:y0", "youtube:y9"]


def test_a_queued_check_notes_only_a_qobuz_search_that_ran():
    e = apply_outcome(existing(), act("upgrade"), Outcome("queued", qobuz_searched=True), NOW)
    assert e["qobuz_searched"] == "2026-10-20" and e["last_upgrade_check"] == "2026-10-01"
    e = apply_outcome(existing(qobuz_searched="2026-10-15"), act("upgrade"), Outcome("queued"), NOW)
    assert e["qobuz_searched"] == "2026-10-15"  # failed or left out this time: the earlier search still counts


def test_skipped_leaves_entry_unchanged():
    before = existing()
    assert apply_outcome(before, act("upgrade"), Outcome("skipped"), NOW) == before


def test_bought_file_on_missing_entry():
    before = existing(status="missing", path=None, source=None, source_id=None, source_format=None, cutoff_hz=None)
    out = Outcome("placed", Placed("Library/A/Artist - Song.wav", "lossless", "manual", None, "pcm_s16le", None))
    e = apply_outcome(before, act("adopt_bought"), out, NOW)
    assert (e["status"], e["source"], e["source_id"]) == ("lossless", "manual", None)
    assert e["last_attempt"] == "2026-10-01"


UPGRADE = {"file": "Upgrades ready/A/Artist - Song.aiff", "source": "qobuz", "source_id": "q1",
           "source_format": "flac", "found": "2026-10-20",
           "alignment": {"result": "exact", "offset_samples": 0, "offset_ms": 0.0, "drift_ms": 0.0,
                         "text": "matches exactly"}}


def test_upgrade_parked_keeps_the_current_file():
    before = existing()
    e = apply_outcome(before, act("upgrade"), Outcome("parked", rejected=("qobuz:7",), upgrade=UPGRADE), NOW)
    assert e["upgrade"] == UPGRADE and e["last_upgrade_check"] == "2026-10-20"
    assert (e["status"], e["path"], e["source"]) == (before["status"], before["path"], before["source"])
    assert "qobuz:7" in e["rejected_sources"]


def test_new_entries_have_no_upgrade():
    assert apply_outcome(None, act("acquire"), placed(), NOW)["upgrade"] is None


@pytest.mark.parametrize("kind,outcome", [
    ("adopt_bought", Outcome("placed", Placed("Library/A/Artist - Song.wav", "lossless", "manual", None, "pcm_s16le",
                                              None))),
    ("acquire", placed()),
    ("acquire", Outcome("missing")),
])
def test_a_new_file_another_way_makes_a_parked_upgrade_stale(kind, outcome):
    e = apply_outcome(existing(upgrade=UPGRADE), act(kind), outcome, NOW)
    assert e["upgrade"] is None


def test_errored_keeps_a_parked_upgrade():
    e = apply_outcome(existing(upgrade=UPGRADE), act("acquire"), Outcome("errored"), NOW)
    assert e["upgrade"] == UPGRADE
