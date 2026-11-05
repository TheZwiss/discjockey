"""Warning signs waiting for the library lock (pending_signs.py): kept in a file, counted for the pause, removed once."""
from datetime import date, datetime, timedelta

import pytest
from hub_helpers import make_root

from discjockey import pending_signs

NOW = datetime(2026, 11, 5, 12, 0)
SIGN = ("youtube", "bot_check", "YouTube's bot check came up while reading your Liked music.")


@pytest.fixture
def root(tmp_path):
    return make_root(tmp_path)


def test_a_sign_is_kept_on_disk_with_the_time_it_was_met(root):
    pending_signs.add(root, [SIGN], NOW)
    assert pending_signs.load(root) == [
        {"service": "youtube", "kind": "bot_check", "message": SIGN[2], "time": "2026-11-05T12:00:00"}]
    assert pending_signs.load(root) == pending_signs.load(root)  # reading takes nothing


def test_adding_nothing_makes_no_file(root):
    pending_signs.add(root, [], NOW)
    assert not root.pending_signs.exists() and pending_signs.load(root) == []


def test_removing_takes_one_waiting_sign_for_each_recorded_and_keeps_the_ones_added_meanwhile(root):
    pending_signs.add(root, [SIGN, SIGN], NOW)
    taken = pending_signs.load(root)
    pending_signs.add(root, [("youtube", "rate_limited", "m")], NOW)
    pending_signs.remove(root, taken)
    assert [s["kind"] for s in pending_signs.load(root)] == ["rate_limited"]
    pending_signs.remove(root, pending_signs.load(root))
    assert not root.pending_signs.exists()


def test_only_a_pause_sign_met_today_pauses(root):
    pending_signs.add(root, [SIGN], NOW)
    pending_signs.add(root, [("youtube", "cookies_unreadable", "m")], NOW + timedelta(days=1))
    assert pending_signs.paused(root, date(2026, 11, 5)) == {"youtube"}
    assert pending_signs.paused(root, date(2026, 11, 6)) == frozenset()  # the next day's only sign is no pause
    assert pending_signs.paused(root, date(2026, 11, 4)) == frozenset()


def test_a_file_that_cannot_be_read_counts_as_empty(root):
    root.data.mkdir(exist_ok=True)
    for junk in ("not json", '{"a": 1}', '[1, {"service": "youtube"}]'):
        root.pending_signs.write_text(junk)
        assert pending_signs.load(root) == []
    assert pending_signs.paused(root, date(2026, 11, 5)) == frozenset()
