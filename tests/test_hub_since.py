"""`--since` (issue 39, design §5.3): `since.parse` against a fixed clock and `since.after`, the one comparison."""
from datetime import datetime, timedelta, timezone

import pytest

from discjockey import words
from discjockey.hub import since
from discjockey.hub.ids import BadId

PLUS_ONE = timezone(timedelta(hours=1))
NOW = datetime(2026, 11, 20, 15, 30, 45, tzinfo=PLUS_ONE)  # a fixed clock in a fixed zone: no daylight saving to cross


def test_each_form_against_a_fixed_now():
    at = lambda *a: datetime(*a, tzinfo=PLUS_ONE)
    assert since.parse("today", NOW) == at(2026, 11, 20)
    assert since.parse("yesterday", NOW) == at(2026, 11, 19)
    assert since.parse("3d", NOW) == at(2026, 11, 17, 15, 30, 45)
    assert since.parse("12h", NOW) == at(2026, 11, 20, 3, 30, 45)
    assert since.parse("2026-11-01", NOW) == at(2026, 11, 1)
    assert since.parse("2026-11-20T18:00", NOW) == at(2026, 11, 20, 18)  # no zone: the clock's own
    assert since.parse("2026-11-20T18:00:00+00:00", NOW) == datetime(2026, 11, 20, 18, tzinfo=timezone.utc)
    assert since.parse(" Today ", NOW) == at(2026, 11, 20)  # case and the spaces around are not the person's meaning
    assert since.parse("3D", NOW) == since.parse("3d", NOW)
    assert all(since.parse(t, NOW).tzinfo is not None for t in ("today", "3d", "2026-11-01", "2026-11-20T18:00"))


def test_a_clock_with_no_zone_is_local_and_the_answer_is_aware():
    naive = datetime(2026, 11, 20, 15, 30)
    assert since.parse("today", naive) == datetime(2026, 11, 20).astimezone()
    assert since.parse("2h", naive) == datetime(2026, 11, 20, 13, 30).astimezone()
    assert since.parse("2026-11-20T18:00", naive) == datetime(2026, 11, 20, 18).astimezone()
    assert since.parse("1d", naive).tzinfo is not None


@pytest.mark.parametrize("text", ["0d", "-1d", "3w", "", "yesterdy", "1.5h", "2026-13-01", "soon"])
def test_anything_else_is_a_usage_error_in_the_words(text):
    with pytest.raises(BadId) as caught:
        since.parse(text, NOW)
    assert caught.value.reason == "usage" and caught.value.message == words.BAD_SINCE.format(text=text)


def test_after_keeps_what_is_not_older_than_since_and_what_it_cannot_read():
    cut = "2026-11-20T00:00:00+01:00"
    assert since.after("2026-11-10T11:00:00", None) and since.after(None, None)
    assert not since.after("2026-11-19T23:59:59+01:00", cut)
    assert since.after("2026-11-20T00:00:00+01:00", cut)  # at the cut: kept
    assert since.after("2026-11-19T23:00:00+00:00", cut)  # the same moment, another zone
    assert not since.after("2026-11-19T22:59:59+00:00", cut)
    assert since.after("2026-11-20T00:00:01", cut) == (datetime(2026, 11, 20, 0, 0, 1).astimezone()
                                                       >= datetime.fromisoformat(cut))  # no zone: local
    assert since.after(None, cut) and since.after("", cut) and since.after("last tuesday", cut)  # unreadable: kept
