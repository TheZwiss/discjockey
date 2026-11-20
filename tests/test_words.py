"""The engine's own words that need no screen to test (`discjockey/words.py`)."""
from datetime import date

import pytest

from discjockey import words


@pytest.mark.parametrize("day, today, said", [
    (date(2026, 11, 12), date(2026, 11, 17), "12 Nov"),  # this year: no year
    (date(2026, 1, 1), date(2026, 12, 31), "1 Jan"),  # no zero in front of the day
    (date(2025, 11, 12), date(2026, 11, 17), "12 Nov 2025"),  # another year says it
    (date(2027, 3, 9), date(2026, 11, 17), "9 Mar 2027"),
    (date(2026, 12, 31), date(2026, 1, 1), "31 Dec"),
])
def test_short_day_names_the_month_in_english_and_the_year_only_when_it_isnt_this_one(day, today, said):
    assert words.short_day(day, today) == said


def test_short_day_never_follows_the_locale(monkeypatch):
    import locale
    monkeypatch.setattr(locale, "setlocale", lambda *a, **k: pytest.fail("the locale must not be used"))
    assert [words.short_day(date(2026, m, 1), date(2026, 6, 1)) for m in range(1, 13)] == [
        f"1 {mon}" for mon in ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")]


@pytest.mark.parametrize("fields, said", [
    ({"done": 3, "total": 12, "item": "Armin Hermann - Get Naughty", "message": "x"}, "3 of 12 · Armin Hermann - Get Naughty"),
    ({"done": 0, "total": 5, "item": None, "message": "Half way."}, "0 of 5"),  # a known total wins over the message
    ({"done": None, "total": None, "item": "A - B", "message": "Half way."}, "Half way."),  # no total: the message
    ({"done": None, "total": None, "item": "A - B", "message": None}, None),  # nothing to say
])
def test_job_line_says_the_count_then_the_message(fields, said):
    assert words.job_line(fields) == said
