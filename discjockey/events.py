"""What the core tells its front ends (console now, hub window later), and how they ask it to stop.

The core never prints. It calls `emit(event)` with one of the records below; a front end decides how to show it.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from .models import Action

STEPS = ("search", "download", "check", "convert", "analyse", "compare")


class Cancelled(BaseException):
    """The user asked to stop. A BaseException so that `except Exception` handlers never swallow it."""


class CancelToken:
    """Set from any thread (Ctrl-C handler, hub button); checked by the core between and inside steps."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise Cancelled()

    def sleep(self, seconds: float) -> None:
        """Waits, but wakes up at once (raising Cancelled) when Stop is pressed."""
        self._event.wait(max(0.0, seconds))
        self.check()


@dataclass(frozen=True)
class Result:
    """The outcome of one action (or one report line). `section` is a report.SECTIONS key."""
    section: str
    folder: str
    artist: str
    title: str
    track_id: str | None = None
    note: str = ""
    status: str | None = None
    source: str | None = None
    cutoff_hz: int | None = None
    path: str | None = None
    error_kind: str | None = None  # errors: network | qobuz | other; not found: not_found
    found_status: str | None = None  # upgrade_ready: the found file's status (`status` stays the current file's)


@dataclass(frozen=True)
class PlannedAction:
    """One action of a run, in the order the run does them."""
    kind: str  # move | adopt | adopt_bought | acquire | upgrade
    track_id: str
    title: str
    artist: str
    image_url: str | None = None  # Spotify's cover, for the rows of the running list


@dataclass(frozen=True)
class RunStarted:
    total: int
    actions: tuple[PlannedAction, ...] = ()


@dataclass(frozen=True)
class ActionStarted:
    index: int  # 1-based
    total: int
    action: Action


@dataclass(frozen=True)
class StepChanged:
    track_id: str
    step: str  # one of STEPS


@dataclass(frozen=True)
class Progress:
    track_id: str
    step: str
    done: float
    total: float | None
    unit: str  # "bytes" | "seconds"


@dataclass(frozen=True)
class Waiting:
    kind: str  # "search" | "between" | "break" | "fallback"
    label: str
    remaining: float
    total: float
    service: str = ""  # "qobuz", "youtube" or "soundcloud" for that account's pauses; "" for the free sources


@dataclass(frozen=True)
class SourceChosen:
    """A download starts: from where, found how (exact | isrc | name | fallback | chosen), and the candidate's title."""
    track_id: str
    source: str
    query_kind: str
    title: str
    duration_s: float | None


@dataclass(frozen=True)
class Checked:
    """The length check after a download: the file's length against the playlist track's (ok: within 3 s)."""
    track_id: str
    file_duration_s: float
    track_duration_s: float
    codec: str
    ok: bool


@dataclass(frozen=True)
class AccountUsage:
    """After each download that counts toward a service's daily limit (Qobuz, YouTube Premium, SoundCloud Go+)."""
    service: str
    used: int
    allowance: int


@dataclass(frozen=True)
class ActionFinished:
    action: Action
    result: Result


@dataclass(frozen=True)
class RunFinished:
    exit_code: int  # 0 ok, 1 some tracks failed, 130 stopped
    report_path: str


@dataclass(frozen=True)
class ReadingPlaylist:
    """Before each playlist is read from Spotify: index counts from 1."""
    index: int
    total: int
    folder: str


@dataclass(frozen=True)
class MovesProgress:
    """After each move of a move batch (a tidy-up, a folder rename, an undo): `done` of `total` moves handled."""
    batch_id: int
    done: int
    total: int


@dataclass(frozen=True)
class Message:
    level: str  # "info" | "warning" | "debug"
    text: str


Emit = Callable[[object], None]

# Words in an error message that mean "the internet connection (or the site) could not be reached".
NETWORK_HINTS = (
    "no connection", "cannot connect to host", "nodename nor servname", "name or service not known",
    "temporary failure in name resolution", "network is unreachable", "connection refused", "connection reset",
    "connection aborted", "max retries exceeded", "timed out", "did not answer within", "unable to download webpage",
    "failed to resolve", "urlopen error", "errno 8]", "errno 51]", "errno 60]", "errno 65]",
)


def error_kind(errors: list[str]) -> str:
    """network | qobuz | other, for the "NO INTERNET" badge and the to-do list."""
    text = " ".join(errors).lower()
    if any(hint in text for hint in NETWORK_HINTS):
        return "network"
    if "qobuz" in text:
        return "qobuz"
    return "other"


def no_emit(event: object) -> None:
    pass


class Tracker:
    """Per-track step and progress reporting; also the place where downloads and conversions notice a stop."""

    def __init__(self, emit: Emit, token: CancelToken, track_id: str, min_interval: float = 0.25,
                 clock: Callable[[], float] = time.monotonic):
        self.emit, self.token, self.track_id = emit, token, track_id
        self.min_interval, self.clock = min_interval, clock
        self.current = ""
        self._last = float("-inf")

    def step(self, name: str) -> None:
        self.token.check()
        self.current = name
        self.emit(StepChanged(self.track_id, name))

    def progress(self, done: float, total: float | None, unit: str) -> None:
        self.token.check()
        now = self.clock()
        finished = total is not None and done >= total
        if not finished and now - self._last < self.min_interval:
            return
        self._last = now
        self.emit(Progress(self.track_id, self.current, done, total, unit))


def null_tracker() -> Tracker:
    return Tracker(no_emit, CancelToken(), "", min_interval=0)
