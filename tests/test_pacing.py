import json
import os
import random
from datetime import date, datetime

import pytest

from discjockey.events import Cancelled, CancelToken, Waiting
from discjockey import pacing
from discjockey.pacing import AUTO_STOP_AFTER, Budget, SharedPacer, record_signal, streak_stopped
from discjockey.settings import Account, Settings
from pace_helpers import FakeClock, pacer as make_pacer

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
        "message": "3 YouTube Premium requests failed in a row; YouTube Premium paused until the next sync."}


def test_an_account_is_paused_today_by_a_pause_sign_of_today():
    from datetime import date

    today = date(2026, 11, 5)
    state = {"youtube_usage": {"days": {}, "signals": [
        {"time": "2026-11-04T23:59:00", "kind": "bot_check", "message": "yesterday"},
        {"time": "2026-11-05T08:00:00", "kind": "premium_missing", "message": "not a pause"},
        {"time": "2026-11-05T09:00:00", "kind": "download_rejected", "message": "not a pause"}]}}
    assert not pacing.account_paused(state, "youtube", today)
    assert not pacing.account_paused({}, "youtube", today) and not pacing.account_paused(state, "soundcloud", today)
    for kind in ("bot_check", "rate_limited", "auto_stop"):
        paused = {"youtube_usage": {"days": {}, "signals": [
            *state["youtube_usage"]["signals"], {"time": "2026-11-05T10:00:00", "kind": kind, "message": "m"}]}}
        assert pacing.account_paused(paused, "youtube", today)
        assert pacing.paused_accounts(paused, today) == {"youtube"}
        assert pacing.paused_accounts(paused, date(2026, 11, 6)) == frozenset()


def test_a_recorded_bot_check_pauses_the_account_for_the_rest_of_the_day():
    from datetime import date, datetime

    state = {}
    pacing.record_signal(state, "bot_check", "m", datetime(2026, 11, 5, 10, 0), "youtube")
    assert pacing.account_paused(state, "youtube", date(2026, 11, 5))


# --- the failure streak is kept in the service's usage row ---

def test_the_streak_is_saved_with_every_change_and_loaded_again():
    b, state, saves, _ = budget({})
    b.failed("x")
    assert state["qobuz_usage"]["streak"] == {"failures_in_a_row": 1, "download_failed_in_row": True, "stopped": False}
    again = Budget(state, lambda: None, Settings(60), today=lambda: TODAY, now=lambda: NOW)
    assert (again.failures_in_a_row, again.download_failed_in_row, again.stopped) == (1, True, False)
    again.failed("x")
    again.failed("x")
    assert again.stopped and state["qobuz_usage"]["streak"]["stopped"] is True
    assert Budget(state, lambda: None, Settings(60), today=lambda: TODAY, now=lambda: NOW).stopped
    assert streak_stopped(state) and not streak_stopped(state, "youtube") and not streak_stopped({})
    again.count()  # a download that worked ends the row (the pause itself stays until a sync starts)
    assert state["qobuz_usage"]["streak"] == {"failures_in_a_row": 0, "download_failed_in_row": False, "stopped": True}


def test_a_missing_or_garbled_streak_is_a_fresh_one():
    for streak in (None, "x", {"failures_in_a_row": "2", "download_failed_in_row": 1, "stopped": "yes"}):
        state = {"qobuz_usage": {"days": {}, "signals": [], "streak": streak}}
        b = Budget(state, lambda: None, Settings(60), today=lambda: TODAY, now=lambda: NOW)
        assert (b.failures_in_a_row, b.download_failed_in_row, b.stopped) == (0, False, False)
    assert Budget({}, lambda: None, Settings(60)).stopped is False


def test_a_search_that_works_saves_only_when_it_ends_a_row():
    b, state, saves, _ = budget({})
    b.succeeded()
    assert saves == [] and "streak" not in state["qobuz_usage"]
    b.failed("search broke", "search_failed")
    assert len(saves) == 1
    b.succeeded()
    assert len(saves) == 2 and state["qobuz_usage"]["streak"]["failures_in_a_row"] == 0
    b.succeeded()
    assert len(saves) == 2  # nothing changed: library.db is not written


def test_a_row_of_failed_downloads_survives_a_search_that_works_in_the_stored_streak():
    b, state, saves, _ = budget({})
    b.failed("preview only", "preview_only")
    b.succeeded()
    assert state["qobuz_usage"]["streak"] == {"failures_in_a_row": 1, "download_failed_in_row": True, "stopped": False}


def test_the_auto_stop_says_it_lasts_until_the_next_sync():
    b, state, *_ = budget({})
    for _ in range(AUTO_STOP_AFTER):
        b.failed("timeout")
    assert state["qobuz_usage"]["signals"][-1]["message"] == "3 Qobuz requests failed in a row; Qobuz paused until the next sync."


# --- SharedPacer ---

def seen(p):
    return json.loads((p.support / "pace.json").read_text())["services"]


def put(support, service, **fields):
    entry = {"last_request_at": None, "last_download_end_at": None, "in_flight": None, "since_break": 0, "next_break": 12}
    path = support / "pace.json"
    data = json.loads(path.read_text()) if path.exists() else {"v": 1, "services": {}}
    data["services"][service] = {**entry, **fields}
    path.write_text(json.dumps(data))


def dead_pid():
    import subprocess

    child = subprocess.Popen(["true"])
    child.wait()
    return child.pid


def test_the_first_search_does_not_wait_and_the_next_waits_2_to_5_seconds(tmp_path):
    clock, events = FakeClock(), []
    p = make_pacer(tmp_path, events.append, clock=clock)
    p.before_qobuz_search()
    assert clock.slept == [] and events == []
    start = clock.now
    for _ in range(5):
        before = clock.now
        p.before_qobuz_search()
        assert 2 <= clock.now - before <= 5
    assert all(isinstance(e, Waiting) and e.kind == "search" and e.service == "qobuz" for e in events)
    assert events[0].remaining == events[0].total and events[-1].remaining == 0 and clock.now > start + 10


def test_two_pacers_space_searches_by_the_same_file(tmp_path):
    clock = FakeClock()
    a, b = make_pacer(tmp_path, clock=clock), make_pacer(tmp_path, clock=clock, rng=random.Random(2))
    stamps = []
    for p in (a, b, a, b, b):
        p.before_qobuz_search()
        stamps.append(clock.now)
    gaps = [later - earlier for earlier, later in zip(stamps, stamps[1:])]
    assert all(2 <= g <= 5 for g in gaps)


def test_a_search_slot_is_reserved_before_the_wait(tmp_path):
    clock = FakeClock()
    seen_in_file = []

    def sleep(seconds):
        seen_in_file.append(seen(a)["qobuz"]["last_request_at"])
        clock.sleep(seconds)

    a = SharedPacer(tmp_path, sleep=sleep, clock=clock.time, rng=random.Random(1))
    a.before_qobuz_search()
    a.before_qobuz_search()
    assert seen_in_file and seen_in_file[0] > clock.now - 6 and seen_in_file[0] >= 1_000_000 + 2  # the slot, ahead of the clock


def test_a_stored_request_time_far_ahead_does_not_hold_a_search_for_hours(tmp_path):
    clock = FakeClock()
    put(tmp_path, "qobuz", last_request_at=clock.now + 3 * 3600)  # the wall clock stepped back
    make_pacer(tmp_path, clock=clock).before_qobuz_search()
    assert clock.now - 1_000_000 <= 65


def test_a_download_waits_for_the_gap_after_the_other_pacers_download_ended(tmp_path):
    clock = FakeClock()
    a, b = make_pacer(tmp_path, clock=clock), make_pacer(tmp_path, clock=clock, rng=random.Random(2))
    a.between_qobuz_downloads()
    assert clock.slept == []  # nothing recent: no wait
    clock.now += 100  # the download takes a while
    a.downloaded("qobuz")
    ended = clock.now
    b.between_qobuz_downloads()
    assert 20 <= clock.now - ended <= 60
    assert seen(b)["qobuz"]["last_download_end_at"] == ended and seen(b)["qobuz"]["in_flight"]["pid"] == os.getpid()


def test_a_download_still_going_in_another_process_is_waited_for_with_the_gap_unknown(tmp_path):
    clock, events = FakeClock(), []
    put(tmp_path, "qobuz", in_flight={"pid": os.getppid(), "since": clock.now})

    def sleep(seconds):
        clock.sleep(seconds)
        if len(clock.slept) == 3:  # the other process's download ends
            put(tmp_path, "qobuz", last_download_end_at=clock.now)

    p = SharedPacer(tmp_path, events.append, sleep=sleep, clock=clock.time, rng=random.Random(1))
    p.between_qobuz_downloads()
    unknown = [e for e in events if e.remaining == e.total]
    assert len(unknown) >= 3 and all(e.kind == "between" for e in events)
    ended = 1_000_003.0
    assert 20 <= clock.now - ended <= 60
    assert events[-1].remaining == 0


def test_a_claim_of_a_dead_process_an_old_one_and_our_own_are_ignored(tmp_path):
    for flight in ({"pid": dead_pid(), "since": 1_000_000.0}, {"pid": os.getppid(), "since": 1_000_000.0 - 1801},
                   {"pid": os.getpid(), "since": 1_000_000.0}):
        clock = FakeClock()
        put(tmp_path, "qobuz", in_flight=flight, last_download_end_at=clock.now - 1000)
        make_pacer(tmp_path, clock=clock).between_qobuz_downloads()
        assert clock.slept == [], flight
        assert seen(make_pacer(tmp_path))["qobuz"]["in_flight"]["pid"] == os.getpid()


def test_downloaded_lets_go_of_our_claim_only(tmp_path):
    clock = FakeClock()
    p = make_pacer(tmp_path, clock=clock)
    p.between_account_downloads("youtube")
    clock.now += 5
    p.downloaded("youtube")
    assert seen(p)["youtube"]["in_flight"] is None and seen(p)["youtube"]["last_download_end_at"] == clock.now
    put(tmp_path, "youtube", in_flight={"pid": os.getppid(), "since": clock.now})
    p.downloaded("youtube")
    assert seen(p)["youtube"]["in_flight"]["pid"] == os.getppid()


def test_a_long_break_after_ten_to_fifteen_downloads(tmp_path):
    clock, events = FakeClock(), []
    p = make_pacer(tmp_path, events.append, clock=clock)
    totals = []
    for _ in range(16):
        before = clock.now
        p.between_qobuz_downloads()
        totals.append(clock.now - before)
        p.downloaded("qobuz")
    assert all(t == 0 or 20 <= t <= 60 or 120 <= t <= 300 for t in totals)
    assert sum(1 for t in totals if t > 60) == 1
    breaks = [e for e in events if e.kind == "break" and e.remaining == 0]
    assert len(breaks) == 1 and breaks[0].label == "Longer break so the account looks less like a bot"
    assert 10 <= totals.index(max(totals)) + 1 <= 15  # the 10th to 15th claim is the break


def test_ten_idle_minutes_count_as_the_break(tmp_path):
    clock = FakeClock()
    put(tmp_path, "qobuz", since_break=9, next_break=10, last_download_end_at=clock.now - 601)
    p = make_pacer(tmp_path, clock=clock)
    p.between_qobuz_downloads()  # would have been the break
    assert clock.slept == [] and seen(p)["qobuz"]["since_break"] == 1
    put(tmp_path, "qobuz", since_break=9, next_break=10, last_download_end_at=clock.now - 60)
    p.between_qobuz_downloads()
    assert clock.now - 1_000_000 >= 120 - 60 and seen(p)["qobuz"]["since_break"] == 0  # a break, and the count starts again


def test_breaks_and_gaps_are_counted_per_account_service(tmp_path):
    clock, events = FakeClock(), []
    p = make_pacer(tmp_path, events.append, clock=clock)
    for _ in range(16):
        p.between_account_downloads("soundcloud")
        p.downloaded("soundcloud")
    ends = [e for e in events if e.remaining == 0]
    assert {e.service for e in ends} == {"soundcloud"}
    assert [e.kind for e in ends].count("break") == 1
    assert ends[0].kind == "between" and ends[0].label == "Protection pause between SoundCloud Go+ downloads"
    assert [e.label for e in ends if e.kind == "break"] == ["Longer break so your SoundCloud Go+ account looks less like a bot"]
    assert "qobuz" not in seen(p)  # Qobuz's own count is untouched


def test_a_qobuz_download_counts_as_a_qobuz_request_for_the_next_search(tmp_path):
    clock = FakeClock()
    p = make_pacer(tmp_path, clock=clock)
    p.between_qobuz_downloads()
    claimed = clock.now
    assert seen(p)["qobuz"]["last_request_at"] == claimed
    p.before_qobuz_search()
    assert 2 <= clock.now - claimed <= 5


def test_the_waits_carry_their_service(tmp_path):
    clock, events = FakeClock(), []
    p = make_pacer(tmp_path, events.append, clock=clock)
    p.before_qobuz_search()
    p.before_qobuz_search()
    p.downloaded("qobuz")
    p.between_qobuz_downloads()
    p.between_fallback_downloads()
    assert [e.service for e in events if e.remaining == 0] == ["qobuz", "qobuz", ""]
    assert [e.kind for e in events if e.remaining == 0] == ["search", "between", "fallback"]


def test_stop_during_a_pause_reacts_within_a_second_and_leaves_no_claim(tmp_path):
    clock, token = FakeClock(), CancelToken()
    put(tmp_path, "qobuz", last_download_end_at=clock.now)

    def sleep(seconds):
        clock.sleep(seconds)
        if len(clock.slept) == 3:
            token.cancel()

    p = SharedPacer(tmp_path, token=token, sleep=sleep, clock=clock.time, rng=random.Random(3))
    with pytest.raises(Cancelled):
        p.between_qobuz_downloads()
    assert len(clock.slept) == 3 and max(clock.slept) <= 1.0
    assert seen(p)["qobuz"]["in_flight"] is None and seen(p)["qobuz"]["since_break"] == 0


def test_stop_during_a_search_wait(tmp_path):
    clock, token = FakeClock(), CancelToken()
    p = SharedPacer(tmp_path, token=token, sleep=lambda s: (clock.sleep(s), token.cancel()), clock=clock.time,
                    rng=random.Random(3))
    p.before_qobuz_search()
    with pytest.raises(Cancelled):
        p.before_qobuz_search()


def test_an_unreadable_pace_file_counts_as_empty_and_is_rewritten(tmp_path):
    for content in ("{not json", json.dumps({"v": 2, "services": {}}), json.dumps([1]), json.dumps({"v": 1, "services": 3})):
        (tmp_path / "pace.json").write_text(content)
        clock = FakeClock()
        p = make_pacer(tmp_path, clock=clock)
        p.before_qobuz_search()
        assert clock.slept == []
        assert set(seen(p)) == {"qobuz"} and seen(p)["qobuz"]["last_request_at"] == clock.now, content


def test_a_service_record_with_wrong_fields_is_completed(tmp_path):
    (tmp_path / "pace.json").write_text(json.dumps({"v": 1, "services": {"qobuz": {
        "last_request_at": "soon", "in_flight": {"pid": 0, "since": 1}, "since_break": -3, "next_break": "x"}}}))
    clock = FakeClock()
    p = make_pacer(tmp_path, clock=clock)
    p.between_qobuz_downloads()
    entry = seen(p)["qobuz"]
    assert clock.slept == [] and entry["since_break"] == 1 and 10 <= entry["next_break"] <= 15
    assert entry["in_flight"]["pid"] == os.getpid()


def test_the_lock_is_not_held_while_waiting(tmp_path):
    import fcntl

    clock = FakeClock()
    put(tmp_path, "qobuz", last_download_end_at=clock.now)
    probes = []

    def sleep(seconds):
        with open(tmp_path / "pace.lock", "a+") as lock:  # would block (and fail the test by timeout) if held
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            probes.append(True)
        clock.sleep(seconds)

    SharedPacer(tmp_path, sleep=sleep, clock=clock.time, rng=random.Random(1)).between_qobuz_downloads()
    assert len(probes) >= 20


def test_no_product_code_builds_the_null_pacer():
    from pathlib import Path

    root = Path(pacing.__file__).parent
    builds = [str(f.relative_to(root)) for f in root.rglob("*.py") if "NoPacer(" in f.read_text(encoding="utf-8")]
    assert builds == []
