"""Human-like pauses between requests to the accounts (one pacer for every process of this Mac: `SharedPacer`), and
the usage model of each account service (daily limit, carry-over, auto-stop, kept in the service's `usage` row)."""
from __future__ import annotations

import fcntl
import json
import math
import os
import random
import secrets
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from .accounts import ACCOUNTS, SERVICE_NAMES
from .events import CancelToken, Emit, Waiting, no_emit
from .library import write_json_atomic
from .settings import Settings

KEEP_DAYS = 60
KEEP_SIGNALS = 200
AUTO_STOP_AFTER = 3


def usage(state: dict, service: str = "qobuz") -> dict:
    return state.setdefault(f"{service}_usage", {"days": {}, "signals": []})


def record_signal(state: dict, kind: str, message: str, now: datetime, service: str = "qobuz") -> None:
    """Warning signs, shown on the hub's Download limits page.

    Qobuz: login_failed | search_failed | download_rejected | preview_only | duration_mismatch | auto_stop.
    YouTube Premium and SoundCloud Go+: accounts.SIGNALS."""
    signals = usage(state, service)["signals"]
    signals.append({"time": now.isoformat(timespec="seconds"), "kind": kind, "message": message})
    del signals[:-KEEP_SIGNALS]


# Signs that an account is being held back today: the reads of Liked music (sources-round D6) stay away from it. A bot
# check or "too many requests" is YouTube already doubting the account; auto_stop is Discjockey's own pause after
# failed requests in a row (hub/views.limit_cards shows the same pause)
PAUSE_SIGNALS = frozenset({"auto_stop", "bot_check", "rate_limited"})


def account_paused(state: dict, service: str, today: date) -> bool:
    """Whether `service`'s account is paused today: it has a pause sign (PAUSE_SIGNALS) recorded today. Pure."""
    day = today.isoformat()
    return any(s.get("kind") in PAUSE_SIGNALS and str(s.get("time", ""))[:10] == day
               for s in state.get(f"{service}_usage", {}).get("signals", []))


def paused_accounts(state: dict, today: date) -> frozenset[str]:
    """The account services (accounts.ACCOUNTS) paused today."""
    return frozenset(s for s in ACCOUNTS if account_paused(state, s, today))


def streak_stopped(state: dict, service: str = "qobuz") -> bool:
    """Whether `service` is paused by the auto-stop (a stored streak with `stopped`): what a search outside a sync reads
    before it asks the service anything. Pure."""
    streak = state.get(f"{service}_usage", {}).get("streak")
    return isinstance(streak, dict) and streak.get("stopped") is True


class Budget:
    """How many downloads one service (Qobuz, YouTube Premium, SoundCloud Go+) may make today.

    Allowance = daily limit + carry-over + one-time extra. Carry-over: whatever of yesterday's limit was not used,
    at most a third of the limit (60/day -> up to 80 after a quiet day). Unused days are never banked further,
    because one big burst after a break looks more like a bot than steady use.
    After AUTO_STOP_AFTER failed searches/downloads in a row, the service is paused until the next sync starts
    (`run.clear_streaks`), for every process: the row of failures is the service's `usage` row's `streak`, loaded
    here and saved with every change, under the caller's library lock.
    A successful download ends the row; a successful search ends it only if no download in it failed, because
    every track starts with a search and a working search does not show that the service lets us download.
    """

    def __init__(self, state: dict, save: Callable[[], None], settings: Settings,
                 today: Callable[[], date] = date.today, now: Callable[[], datetime] = datetime.now,
                 service: str = "qobuz"):
        self.state, self.save, self.settings, self.today, self.now = state, save, settings, today, now
        self.service, self.name = service, SERVICE_NAMES[service]
        streak = state.get(f"{service}_usage", {}).get("streak")
        streak = streak if isinstance(streak, dict) else {}
        failures = streak.get("failures_in_a_row")
        self.failures_in_a_row = failures if isinstance(failures, int) and not isinstance(failures, bool) else 0
        self.download_failed_in_row = streak.get("download_failed_in_row") is True
        self.stopped = streak.get("stopped") is True

    def _keep_streak(self) -> None:
        usage(self.state, self.service)["streak"] = {"failures_in_a_row": self.failures_in_a_row,
                                                     "download_failed_in_row": self.download_failed_in_row,
                                                     "stopped": self.stopped}

    def _days(self) -> dict:
        return usage(self.state, self.service)["days"]

    def limit(self) -> int:
        return self.settings.limit_of(self.service)

    def used_today(self) -> int:
        return self._days().get(self.today().isoformat(), 0)

    def carry_over(self) -> int:
        limit = self.limit()
        yesterday = (self.today() - timedelta(days=1)).isoformat()
        return min(limit // 3, max(0, limit - self._days().get(yesterday, 0)))

    def allowance(self) -> int:
        return self.limit() + self.carry_over() + self.settings.extra_of(self.service, self.today())

    def remaining(self) -> int:
        return max(0, self.allowance() - self.used_today())

    def exhausted(self) -> bool:
        return self.stopped or self.remaining() == 0

    def why_exhausted(self) -> str:
        if self.stopped:
            return f"{self.name} paused after {AUTO_STOP_AFTER} failed requests in a row"
        return f"daily {self.name} limit reached"

    def count(self) -> None:
        days = self._days()
        today = self.today()
        days[today.isoformat()] = days.get(today.isoformat(), 0) + 1
        usage(self.state, self.service)["last_download"] = self.now().isoformat(timespec="seconds")
        oldest = (today - timedelta(days=KEEP_DAYS)).isoformat()
        for day in [d for d in days if d < oldest]:
            del days[day]
        self.failures_in_a_row = 0
        self.download_failed_in_row = False
        self._keep_streak()
        self.save()

    def succeeded(self) -> None:
        """A search (or a format listing) worked (see the class docstring for why it does not end a row of failed
        downloads). Saved only when it ended a row: a working search must not write library.db every time."""
        if not self.download_failed_in_row and self.failures_in_a_row:
            self.failures_in_a_row = 0
            self._keep_streak()
            self.save()

    def failed(self, message: str, kind: str = "download_rejected") -> None:
        """A search or download failed. kind: a warning sign of this service (record_signal)."""
        self.failures_in_a_row += 1
        if kind != "search_failed":
            self.download_failed_in_row = True
        record_signal(self.state, kind, message, self.now(), self.service)
        if self.failures_in_a_row >= AUTO_STOP_AFTER and not self.stopped:
            self.stopped = True
            record_signal(self.state, "auto_stop", f"{AUTO_STOP_AFTER} {self.name} requests failed in a row; "
                                                   f"{self.name} paused until the next sync.", self.now(), self.service)
        self._keep_streak()
        self.save()

    def note(self, kind: str, message: str) -> None:
        """A warning sign that does not count toward the auto-stop (e.g. duration_mismatch: a preview)."""
        record_signal(self.state, kind, message, self.now(), self.service)
        self.save()

    def describe(self) -> str:
        limit = self.limit()
        parts = [f"{limit}"]
        if self.carry_over():
            parts.append(f"{self.carry_over()} carried over from yesterday")
        extra = self.settings.extra_of(self.service, self.today())
        if extra:
            parts.append(f"{extra} extra for today")
        detail = f" ({' + '.join(parts)})" if len(parts) > 1 else ""
        return f"{self.name} today: {self.used_today()} of {self.allowance()} used{detail}."


PACE_FILE, PACE_LOCK = "pace.json", "pace.lock"  # in the support folder: the accounts belong to it, not to a library
SEARCH_GAP = (2, 5)  # seconds between two Qobuz requests of this Mac
DOWNLOAD_GAP = (20, 60)  # seconds from the end of a download of an account service to the start of the next
BREAK_GAP = (120, 300)  # the gap that replaces it after BREAK_EVERY downloads
BREAK_EVERY = (10, 15)  # downloads of one service between two breaks (drawn again after each)
IDLE_RESTARTS_COUNT_S = 600  # a service without a download for this long starts counting toward its break again
IN_FLIGHT_STALE_S = 1800  # a claimed download that has not ended after this long is taken as lost
WATCH_STEP_S = 1.0  # how often a wait looks at the file again (and at Stop)
CLOCK_SKEW_S = 60  # the wall clock stepped back: a stored time further ahead than this is not believed


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) \
        else None


class SharedPacer:
    """The pacing of every request that could make Qobuz or an account service doubt the account, for all processes of
    this Mac (design §7.5): one `<support>/pace.json`, read and written under an exclusive `flock` of `<support>/pace.lock`
    that is held only for that, never while waiting. Per service the file holds the time of its last request
    (Qobuz searches), the end of its last download, the download that has been claimed and not yet ended
    (`in_flight`: the claimant's pid, the time and which pacer of that process) and the count toward the next break.

    A search takes a slot 2-5 s after the previous Qobuz request. A download of Qobuz, YouTube Premium or SoundCloud Go+
    is claimed (`between_*`) once the gap since the previous download's end has passed, 20-60 s, or a 2-5 minute break
    after every 10-15 downloads of that service, and ended with `downloaded(service)`: the gap counts from there, so
    two processes asking at once start a gap apart. A claim of another live process (its pid answers, under 30
    minutes old) leaves the end, and so the gap's target, unknown: the wait looks again every second. Free YouTube and
    SoundCloud downloads keep their 3-8 s in this process only (`between_fallback_downloads`): they protect no account.

    Every `between_*` that returns must be followed by `downloaded` for the same service (a `finally`), and none whose
    wait ended in Cancelled has a claim to end. `clock` is the wall clock (times are shared by processes), `sleep` waits
    one step."""

    def __init__(self, support: Path, emit: Emit = no_emit, token: CancelToken | None = None, *,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.time,
                 rng: random.Random | None = None):
        self.support = Path(support)
        self.emit, self.token, self.sleep, self.clock = emit, token or CancelToken(), sleep, clock
        self.rng = rng or random.Random()
        self._id = secrets.token_hex(4)  # names this instance in its claims: two in one process are two claimants

    # --- the file ---

    @contextmanager
    def _locked(self):
        """Yields the `services` of pace.json (each one complete) under the exclusive lock, and writes the file back
        when the block changed it, or when it could not be read (an unreadable file counts as empty and is rewritten).
        Nothing is written when the block raises."""
        self.support.mkdir(parents=True, exist_ok=True)
        with open(self.support / PACE_LOCK, "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data, readable = self._read()
            before = json.dumps(data, sort_keys=True)
            yield data["services"]
            if not readable or json.dumps(data, sort_keys=True) != before:
                write_json_atomic(self.support / PACE_FILE, data)

    def _read(self) -> tuple[dict, bool]:
        """(the file's content with every service complete, whether the file was readable). No file is readable and empty."""
        try:
            raw = json.loads((self.support / PACE_FILE).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"v": 1, "services": {}}, True
        except (OSError, ValueError):
            return {"v": 1, "services": {}}, False
        services = raw.get("services") if isinstance(raw, dict) and raw.get("v") == 1 else None
        if not isinstance(services, dict):
            return {"v": 1, "services": {}}, False
        return {"v": 1, "services": {name: self._complete(entry) for name, entry in services.items()
                                     if isinstance(name, str)}}, True

    def _complete(self, entry: object) -> dict:
        """One service's record with every field there and of its type (what could not be read is as if never set)."""
        entry = entry if isinstance(entry, dict) else {}
        flight = entry.get("in_flight")
        pid, since = (flight.get("pid"), _number(flight.get("since"))) if isinstance(flight, dict) else (None, None)
        by = flight.get("by") if isinstance(flight, dict) else None
        held = {"pid": pid, "since": since, "by": by if isinstance(by, str) else None} \
            if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 and since is not None else None
        count, due = entry.get("since_break"), entry.get("next_break")
        return {"last_request_at": _number(entry.get("last_request_at")),
                "last_download_end_at": _number(entry.get("last_download_end_at")),
                "in_flight": held,
                "since_break": count if isinstance(count, int) and not isinstance(count, bool) and count >= 0 else 0,
                "next_break": due if isinstance(due, int) and not isinstance(due, bool) and due > 0
                else self.rng.randint(*BREAK_EVERY)}

    def _service(self, services: dict, name: str) -> dict:
        if name not in services:
            services[name] = self._complete(None)
        return services[name]

    def _blocked_by(self, flight: dict | None, now: float) -> bool:
        """Whether `flight` is a download of another claimant (another process, or another pacer of this one) that is
        still going on. A claim stamped ahead of the clock by more than the skew is not believed."""
        if flight is None or flight["by"] == self._id or now - flight["since"] >= IN_FLIGHT_STALE_S \
                or flight["since"] > now + CLOCK_SKEW_S:
            return False
        try:
            os.kill(flight["pid"], 0)
        except ProcessLookupError:
            return False
        except PermissionError:  # it exists, and is another user's
            return True
        except OSError:
            return False
        return True

    # --- the requests ---

    def before_qobuz_search(self) -> None:
        """Reserves the next slot 2-5 s after the previous Qobuz request (any process's: search or download) and waits
        for it."""
        with self._locked() as services:
            now = self.clock()
            s = self._service(services, "qobuz")
            last = s["last_request_at"]
            slot = now if last is None else max(now, min(last, now + CLOCK_SKEW_S) + self.rng.uniform(*SEARCH_GAP))
            s["last_request_at"] = slot
        self._wait_until(slot, slot - now, "search", "Short pause before searching Qobuz", "qobuz")

    def between_qobuz_downloads(self) -> None:
        self._claim("qobuz", "Protection pause between Qobuz downloads",
                    "Longer break so the account looks less like a bot")

    def between_account_downloads(self, service: str) -> None:
        """YouTube Premium and SoundCloud Go+ get Qobuz's protection: 20-60 s, and a 2-5 min break every 10-15
        downloads, counted per service (a format listing is a logged-in request too and is one claim with its download)."""
        name = SERVICE_NAMES[service]
        self._claim(service, f"Protection pause between {name} downloads",
                    f"Longer break so your {name} account looks less like a bot")

    def between_fallback_downloads(self) -> None:
        self.wait(self.rng.uniform(3, 8), "fallback", "Pause before the next YouTube/SoundCloud download")

    def downloaded(self, service: str) -> None:
        """The download (or format listing) that the last `between_*` for `service` started has ended, whatever came of
        it: the next gap counts from now, and this process's claim is let go."""
        with self._locked() as services:
            s = self._service(services, service)
            s["last_download_end_at"] = self.clock()
            flight = s["in_flight"]
            if flight is not None and (flight["by"] == self._id or (flight["by"] is None and flight["pid"] == os.getpid())):
                s["in_flight"] = None

    def _claim(self, service: str, label: str, break_label: str) -> None:
        """Waits until the download may start, then claims it (`in_flight`). A break is due (and is the gap) when this
        claim would be the 10th-15th since the last one; that is looked at again on every pass, since another process
        may have claimed meanwhile. One gap is drawn per kind, the first time that kind is due."""
        gaps: dict[bool, float] = {}
        waited = False
        while True:
            self.token.check()
            wait = None  # seconds to the next look: the target is known, or the claim of another process is unknown
            with self._locked() as services:
                now = self.clock()
                s = self._service(services, service)
                end = s["last_download_end_at"]
                if end is not None and now - end > IDLE_RESTARTS_COUNT_S:
                    s["since_break"] = 0  # ten minutes without a download count as the break
                due = s["since_break"] + 1 >= s["next_break"]
                if due not in gaps:
                    gaps[due] = self.rng.uniform(*(BREAK_GAP if due else DOWNLOAD_GAP))
                gap = gaps[due]
                kind, shown = ("break", break_label) if due else ("between", label)
                if self._blocked_by(s["in_flight"], now):
                    wait, left = WATCH_STEP_S, gap
                else:
                    end = s["last_download_end_at"]
                    left = 0.0 if end is None else min(end, now) + gap - now
                    if left > 0:
                        wait = min(WATCH_STEP_S, left)
                    else:
                        s["in_flight"] = {"pid": os.getpid(), "since": now, "by": self._id}
                        s["since_break"] += 1
                        if s["since_break"] >= s["next_break"]:
                            s["since_break"], s["next_break"] = 0, self.rng.randint(*BREAK_EVERY)
                        if service == "qobuz":  # a download is a request too: a search follows it 2-5 s later
                            s["last_request_at"] = max(now, s["last_request_at"] or now)
            if wait is None:
                if waited:
                    self.emit(Waiting(kind, shown, 0.0, gap, service))
                return
            waited = True
            self.emit(Waiting(kind, shown, left, gap, service))
            self.sleep(wait)

    # --- waiting ---

    def _wait_until(self, target: float, total: float, kind: str, label: str, service: str) -> None:
        """Counts down to `target` on the wall clock, a step a second, looking at Stop before each (nothing at all when
        there is nothing to wait for)."""
        remaining = target - self.clock()
        if remaining <= 0:
            return
        while remaining > 0:
            self.token.check()
            self.emit(Waiting(kind, label, remaining, total, service))
            self.sleep(min(WATCH_STEP_S, remaining))
            remaining = target - self.clock()
        self.emit(Waiting(kind, label, 0.0, total, service))
        self.token.check()

    def wait(self, seconds: float, kind: str, label: str, service: str = "") -> None:
        """A pause of this process alone (no file): the countdown of `Waiting` events, a step a second."""
        remaining = seconds
        while remaining > 0:
            self.token.check()
            self.emit(Waiting(kind, label, remaining, seconds, service))
            step = min(WATCH_STEP_S, remaining)
            self.sleep(step)
            remaining -= step
        self.emit(Waiting(kind, label, 0.0, seconds, service))
        self.token.check()


class NoPacer:
    """The tests' pacer that never waits (product code builds a SharedPacer)."""

    def before_qobuz_search(self) -> None:
        pass

    def between_qobuz_downloads(self) -> None:
        pass

    def between_fallback_downloads(self) -> None:
        pass

    def between_account_downloads(self, service: str) -> None:
        pass

    def downloaded(self, service: str) -> None:
        pass
