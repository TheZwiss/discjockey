"""Human-like pauses between downloads, and the usage model of each account service (daily limit, carry-over,
auto-stop)."""
from __future__ import annotations

import random
import time
from datetime import date, datetime, timedelta
from typing import Callable

from .accounts import SERVICE_NAMES
from .events import CancelToken, Emit, Waiting, no_emit
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


class Budget:
    """How many downloads one service (Qobuz, YouTube Premium, SoundCloud Go+) may make today.

    Allowance = daily limit + carry-over + one-time extra. Carry-over: whatever of yesterday's limit was not used,
    at most a third of the limit (60/day -> up to 80 after a quiet day). Unused days are never banked further,
    because one big burst after a break looks more like a bot than steady use.
    After AUTO_STOP_AFTER failed searches/downloads in a row, the service is paused for the rest of this run.
    A successful download ends the row; a successful search ends it only if no download in it failed, because
    every track starts with a search and a working search does not show that the service lets us download.
    """

    def __init__(self, state: dict, save: Callable[[], None], settings: Settings,
                 today: Callable[[], date] = date.today, now: Callable[[], datetime] = datetime.now,
                 service: str = "qobuz"):
        self.state, self.save, self.settings, self.today, self.now = state, save, settings, today, now
        self.service, self.name = service, SERVICE_NAMES[service]
        self.failures_in_a_row = 0
        self.download_failed_in_row = False
        self.stopped = False

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
        self.save()

    def succeeded(self) -> None:
        """A search (or a format listing) worked (see the class docstring for why it does not end a row of failed
        downloads)."""
        if not self.download_failed_in_row:
            self.failures_in_a_row = 0

    def failed(self, message: str, kind: str = "download_rejected") -> None:
        """A search or download failed. kind: a warning sign of this service (record_signal)."""
        self.failures_in_a_row += 1
        if kind != "search_failed":
            self.download_failed_in_row = True
        record_signal(self.state, kind, message, self.now(), self.service)
        if self.failures_in_a_row >= AUTO_STOP_AFTER and not self.stopped:
            self.stopped = True
            record_signal(self.state, "auto_stop", f"{AUTO_STOP_AFTER} {self.name} requests failed in a row; "
                                                   f"{self.name} paused for this run.", self.now(), self.service)
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


class Pacer:
    def __init__(self, emit: Emit = no_emit, token: CancelToken | None = None,
                 sleep: Callable[[float], None] = time.sleep, rng: random.Random | None = None):
        self.emit, self.token, self.sleep = emit, token or CancelToken(), sleep
        self.rng = rng or random.Random()
        self.since_break = 0
        self.next_break = self.rng.randint(10, 15)
        self.account_breaks: dict[str, list[int]] = {}

    def before_qobuz_search(self) -> None:
        self.wait(self.rng.uniform(2, 5), "search", "Short pause before searching Qobuz", "qobuz")

    def between_qobuz_downloads(self) -> None:
        self.wait(self.rng.uniform(20, 60), "between", "Protection pause between Qobuz downloads", "qobuz")
        self.since_break += 1
        if self.since_break >= self.next_break:
            self.wait(self.rng.uniform(120, 300), "break", "Longer break so the account looks less like a bot", "qobuz")
            self.since_break = 0
            self.next_break = self.rng.randint(10, 15)

    def between_account_downloads(self, service: str) -> None:
        """Qobuz's protection for YouTube Premium and SoundCloud Go+: 20-60 s, and a 2-5 min break every 10-15
        downloads, counted per service."""
        name = SERVICE_NAMES[service]
        self.wait(self.rng.uniform(20, 60), "between", f"Protection pause between {name} downloads", service)
        if service not in self.account_breaks:
            self.account_breaks[service] = [0, self.rng.randint(10, 15)]
        count = self.account_breaks[service]
        count[0] += 1
        if count[0] >= count[1]:
            self.wait(self.rng.uniform(120, 300), "break", f"Longer break so your {name} account looks less like a bot",
                      service)
            self.account_breaks[service] = [0, self.rng.randint(10, 15)]

    def between_fallback_downloads(self) -> None:
        self.wait(self.rng.uniform(3, 8), "fallback", "Pause before the next YouTube/SoundCloud download")

    def wait(self, seconds: float, kind: str, label: str, service: str = "") -> None:
        remaining = seconds
        while remaining > 0:
            self.token.check()
            self.emit(Waiting(kind, label, remaining, seconds, service))
            step = min(1.0, remaining)
            self.sleep(step)
            remaining -= step
        self.emit(Waiting(kind, label, 0.0, seconds, service))
        self.token.check()


class NoPacer:
    def before_qobuz_search(self) -> None:
        pass

    def between_qobuz_downloads(self) -> None:
        pass

    def between_fallback_downloads(self) -> None:
        pass

    def between_account_downloads(self, service: str) -> None:
        pass
