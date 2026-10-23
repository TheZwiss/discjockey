import random
from datetime import date, datetime

import pytest

from discjockey.events import Cancelled, CancelToken, Waiting
from discjockey.pacing import AUTO_STOP_AFTER, Budget, Pacer, record_signal
from discjockey.settings import Account, Settings

TODAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 20, 21, 0, 0)


def budget(days=None, limit=60, extra=None, today=TODAY):
    state = {"qobuz_usage": {"days": dict(days or {}), "signals": []}}
    saves = []
    s = Settings(limit, extra[0] if extra else None, extra[1] if extra else 0)
    day = [today]
    b = Budget(state, lambda: saves.append(1), s, today=lambda: day[0], now=lambda: NOW)
    return b, state, saves, day


def test_full_day_yesterday_means_plain_limit():
    b, *_ = budget({"2026-10-19": 60})
    assert (b.carry_over(), b.allowance()) == (0, 60)


def test_quiet_day_yesterday_carries_over_at_most_a_third():
    b, *_ = budget({})
    assert (b.carry_over(), b.allowance()) == (20, 80)
    b, *_ = budget({"2026-10-19": 50})
    assert (b.carry_over(), b.allowance()) == (10, 70)


def test_only_yesterday_carries_over():
    b, *_ = budget({"2026-10-17": 0, "2026-10-19": 60})  # a quiet day earlier in the week does not add up
    assert b.allowance() == 60


def test_one_time_extra_only_on_its_day():
    b, *_ = budget({"2026-10-19": 60}, extra=("2026-10-20", 25))
    assert b.allowance() == 85
    b, *_ = budget({"2026-10-19": 60}, extra=("2026-10-19", 25))
    assert b.allowance() == 60


def test_count_saves_and_exhausts():
    b, state, saves, _ = budget({"2026-10-19": 60}, limit=2)
    b.count()
    b.count()
    assert b.exhausted() and b.remaining() == 0
    assert state["qobuz_usage"]["days"]["2026-10-20"] == 2 and len(saves) == 2


def test_old_days_are_pruned():
    b, state, *_ = budget({"2026-01-01": 5, "2026-10-19": 3})
    b.count()
    assert "2026-01-01" not in state["qobuz_usage"]["days"]


def test_budget_resets_next_day():
    b, state, saves, day = budget({"2026-10-20": 80})
    assert b.exhausted()
    day[0] = date(2026, 10, 21)  # the run continues past midnight
    assert not b.exhausted()
    assert b.allowance() == 60  # yesterday was fully used, nothing carries over


def test_auto_stop_after_failures_in_a_row():
    b, state, *_ = budget({})
    for _ in range(AUTO_STOP_AFTER - 1):
        b.failed("timeout")
    assert not b.exhausted()
    b.failed("timeout")
    assert b.exhausted() and "paused" in b.why_exhausted()
    kinds = [s["kind"] for s in state["qobuz_usage"]["signals"]]
    assert kinds == ["download_rejected"] * AUTO_STOP_AFTER + ["auto_stop"]


def test_success_resets_the_failure_streak():
    b, *_ = budget({})
    b.failed("x")
    b.failed("x")
    b.count()
    b.failed("x")
    assert not b.stopped


def test_successful_searches_end_a_row_of_failed_searches():
    b, *_ = budget()
    for _ in range(5):
        b.failed("search broke", "search_failed")
        b.succeeded()
    assert not b.stopped
    for _ in range(AUTO_STOP_AFTER):
        b.failed("search broke", "search_failed")
    assert b.stopped


def test_successful_searches_do_not_end_a_row_of_failed_downloads():
    # every track starts with a search, so otherwise downloads that keep failing would never pause Qobuz
    b, *_ = budget()
    for _ in range(AUTO_STOP_AFTER):
        b.succeeded()
        b.failed("preview only", "preview_only")
    assert b.stopped


def test_signals_are_capped():
    state = {}
    for i in range(250):
        record_signal(state, "download_rejected", str(i), NOW)
    signals = state["qobuz_usage"]["signals"]
    assert len(signals) == 200 and signals[-1]["message"] == "249"


def test_describe():
    b, *_ = budget({"2026-10-20": 37})
    assert b.describe() == "Qobuz today: 37 of 80 used (60 + 20 carried over from yesterday)."


def test_pacer_long_break_after_ten_to_fifteen_downloads():
    slept = []
    p = Pacer(sleep=slept.append, rng=random.Random(1))
    totals = []
    for _ in range(16):
        before = sum(slept)
        p.between_qobuz_downloads()
        totals.append(sum(slept) - before)
    assert all(20 <= t <= 60 or 140 <= t <= 360 for t in totals)
    assert sum(1 for t in totals if t > 60) == 1


def test_pacer_reports_the_countdown():
    events = []
    p = Pacer(emit=events.append, sleep=lambda s: None, rng=random.Random(2))
    p.before_qobuz_search()
    assert all(isinstance(e, Waiting) and e.kind == "search" for e in events)
    assert events[0].remaining == events[0].total and events[-1].remaining == 0


def test_stop_during_a_pause_reacts_within_a_second():
    token = CancelToken()
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        if len(slept) == 3:
            token.cancel()

    p = Pacer(token=token, sleep=sleep, rng=random.Random(3))
    with pytest.raises(Cancelled):
        p.between_qobuz_downloads()
    assert len(slept) == 3 and max(slept) <= 1.0


def test_failure_kinds_and_notes():
    b, state, *_ = budget({})
    b.failed("search broke", "search_failed")
    b.note("duration_mismatch", "30 s preview")
    assert [s["kind"] for s in state["qobuz_usage"]["signals"]] == ["search_failed", "duration_mismatch"]
    assert b.failures_in_a_row == 1  # notes do not count toward the auto-stop


def test_count_remembers_the_time_of_the_last_download():
    b, state, _, _ = budget()
    assert "last_download" not in state["qobuz_usage"]
    b.count()
    assert state["qobuz_usage"]["last_download"] == NOW.isoformat(timespec="seconds")


def account_budget(days=None, limit=30, service="youtube"):
    state = {f"{service}_usage": {"days": dict(days or {}), "signals": []}}
    s = Settings(accounts={service: Account("chrome", limit)})
    return Budget(state, lambda: None, s, today=lambda: TODAY, now=lambda: NOW, service=service), state


def test_an_account_has_its_own_days_carry_over_and_texts():
    b, state = account_budget({"2026-10-19": 20})
    assert (b.limit(), b.carry_over(), b.allowance()) == (30, 10, 40)
    b.count()
    assert state["youtube_usage"]["days"]["2026-10-20"] == 1 and "qobuz_usage" not in state
    assert b.describe() == "YouTube Premium today: 1 of 40 used (30 + 10 carried over from yesterday)."
    assert b.why_exhausted() == "daily YouTube Premium limit reached"


def test_an_account_auto_stops_under_its_own_name():
    b, state = account_budget()
    for _ in range(AUTO_STOP_AFTER):
        b.failed("Artist - Title: Sign in to confirm you're not a bot", "bot_check")
    assert b.exhausted() and b.why_exhausted() == "YouTube Premium paused after 3 failed requests in a row"
    assert state["youtube_usage"]["signals"][-1] == {
        "time": "2026-10-20T21:00:00", "kind": "auto_stop",
        "message": "3 YouTube Premium requests failed in a row; YouTube Premium paused for this run."}


def test_account_pauses_and_breaks_are_counted_per_service():
    events = []
    p = Pacer(events.append, sleep=lambda s: None, rng=random.Random(1))
    for _ in range(16):
        p.between_account_downloads("soundcloud")
    ends = [e for e in events if e.remaining == 0]
    assert {e.service for e in ends} == {"soundcloud"}
    assert [e.kind for e in ends].count("break") == 1
    assert ends[0].label == "Protection pause between SoundCloud Go+ downloads"
    assert p.since_break == 0  # Qobuz's own count is untouched


def test_qobuz_waits_carry_their_service():
    events = []
    p = Pacer(events.append, sleep=lambda s: None, rng=random.Random(1))
    p.before_qobuz_search()
    p.between_qobuz_downloads()
    p.between_fallback_downloads()
    assert [e.service for e in events if e.remaining == 0] == ["qobuz", "qobuz", ""]
