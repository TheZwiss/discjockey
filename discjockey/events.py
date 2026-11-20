"""What the core tells its front ends (console now, hub window later), and how they ask it to stop.

The core never prints. It calls `emit(event)` with one of the records below; a front end decides how to show it.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from .models import Action

STEPS = ("search", "download", "check", "convert", "analyse", "compare")


class Cancelled(BaseException):
    """The user asked to stop. A BaseException so that `except Exception` handlers never swallow it."""


CTRL_C_REPEAT_S = 1.0  # uv and caffeinate forward one Ctrl-C a second time: a second press sooner than this is ignored
STOP_CHECK_S = 0.5  # how often a stop file is looked for at most, and the longest step of a sleep


class CancelToken:
    """Set from any thread (Ctrl-C handler, hub button) or, with a stop file, from any process (`job stop` writes the
    file, design §6.4); checked by the core between and inside steps. `on_cancel` is called exactly once, the first time
    the token is cancelled (by `cancel()` or by the stop file being seen); an exception in it is swallowed."""

    def __init__(self, stop_file: Path | None = None, on_cancel: Callable[[], None] | None = None) -> None:
        self._event = threading.Event()
        self._stop_file = stop_file
        self._next_look = 0.0  # the monotonic time before which the file is not looked for again
        self._on_cancel = on_cancel
        self._told = False
        self._told_lock = threading.Lock()

    def _tell(self) -> None:
        if self._told or self._on_cancel is None:
            return
        with self._told_lock:
            if self._told or self._on_cancel is None:
                return
            self._told = True
        try:
            self._on_cancel()
        except Exception:  # noqa: BLE001  a callback never stops the stop
            pass

    def cancel(self) -> None:
        self._event.set()
        self._tell()

    @property
    def cancelled(self) -> bool:
        """The event is set or the stop file exists (one `stat` at most every 0.5 s; once seen, it stays)."""
        if self._event.is_set():
            self._tell()  # set by someone else (a sleep's wake-up): told at most once
            return True
        if self._stop_file is None:
            return False
        now = time.monotonic()
        if now < self._next_look:
            return False
        self._next_look = now + STOP_CHECK_S
        if self._stop_file.exists():
            self._event.set()
            self._tell()
            return True
        return False

    def check(self) -> None:
        if self.cancelled:
            raise Cancelled()

    def sleep(self, seconds: float) -> None:
        """Waits, but wakes up at once (raising Cancelled) when Stop is pressed, and within half a second of a stop file
        appearing: it waits in steps of at most 0.5 s and checks `cancelled` in each."""
        end = time.monotonic() + max(0.0, seconds)
        while True:
            left = end - time.monotonic()
            if left <= 0:
                break
            if self._event.wait(min(STOP_CHECK_S, left)):
                break
            if self.cancelled:
                break
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
    """A download starts: from where, found how (exact | isrc | name | fallback | chosen | upload), and the candidate's title."""
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
class BatchProgress:
    """How far an AIFF batch is (batches.run, plan rekordbox stage B §1.11): `done` of `total` items handled (done,
    skipped or failed; earlier runs of a resumed batch count); `track_id` / `name` the item now in work, both None
    after the last one. `lead` / `count`: the words the window shows for the phase ("Upgrading", "3 of 5 upgraded";
    "Putting in better versions", "3 of 5 put in"), made by `batches.progress_words` from what the batch's items do;
    empty where the event isn't the sync's phase (undo, add as new, discard)."""
    batch_id: int
    done: int
    total: int
    track_id: str | None
    name: str | None
    lead: str = ""
    count: str = ""


ImportPhase = Literal["scan", "facts", "tags", "sound", "link"]
IMPORT_PHASES: tuple[ImportPhase, ...] = ("scan", "facts", "tags", "sound", "link")


@dataclass(frozen=True)
class ImportProgress:
    """How far the import is (importer.run_import, plan library stage 4 I8): `phase` one of IMPORT_PHASES (looking
    for music files, reading what the files are (the audio facts), reading tags, checking the sound, linking to the
    playlists); `done` of `total` files of that
    phase (0 of 0 for scan and link); `unreadable`: the files this import couldn't read so far."""
    phase: ImportPhase
    done: int
    total: int
    unreadable: int


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
