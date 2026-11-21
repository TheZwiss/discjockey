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


@pytest.mark.parametrize("kind, said", [
    ("sync", "Sync"), ("refresh", "Playlists read"), ("tidy", "Tidy-up"), ("scan", "Library scan"),
    ("import", "Import"), ("aiff_batch", "AIFF conversion"), ("batch_resume", "AIFF batch"),
    ("upgrade_batch", "Upgrade"), ("auto_upgrade", "Auto-upgrade"), ("missing_files", "Missing files"),
    ("undo_moves", "Undo of a tidy-up"), ("undo_upgrade", "Undo of an upgrade"),
    ("use_candidate", "Download of a version"), ("use_link", "Download from a link"),
    ("supersede", "Same-song choice"), ("update_tools", "Tools update"), ("rollback_tools", "Tools rollback"),
    ("hide", "Hide"),  # a kind with no entry says its own name
    ("set_sync_scope", "Set sync scope"),
])
def test_job_title_names_the_job_kind_in_sentence_case(kind, said):
    assert words.job_title(kind) == said


def test_every_job_kind_with_a_result_has_a_title():
    from discjockey.hub import shapes
    titles = {kind: words.job_title(kind) for kind in shapes.RESULTS}
    assert all(title and "_" not in title and title[0].isupper() for title in titles.values()), titles


@pytest.mark.parametrize("kind, via, line, said", [
    ("sync", "terminal", "4 of 60", "Sync running in the Terminal · 4 of 60"),
    ("sync", "terminal", None, "Sync running in the Terminal"),  # no progress yet: no dangling dot
    ("tidy", "window", "12 of 80 · Techno", "Tidy-up running in another window · 12 of 80 · Techno"),
    ("scan", "window", None, "Library scan running in another window"),
    ("sync", None, "1 of 2", "Sync running in the Terminal · 1 of 2"),  # a record without `via` is told as the Terminal's
    (None, None, None, "A Discjockey command is running in the Terminal"),  # no registry entry: nobody can name it
    (None, "terminal", "4 of 60", "A Discjockey command is running in the Terminal"),  # a line alone names nothing
])
def test_holder_text_says_which_job_where_and_how_far(kind, via, line, said):
    assert words.holder_text(kind, via, line) == said


@pytest.mark.parametrize("via, said", [
    ("terminal", "In the Terminal"), ("window", "In another window"),
    (None, "In the Terminal"),  # a record without `via` is told as the Terminal's, as `holder_text` does
])
def test_holder_where_says_where_the_holder_runs(via, said):
    assert words.holder_where(via) == said
