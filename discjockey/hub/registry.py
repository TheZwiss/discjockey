"""The job registry (issue 39, design §6.2): what every process that runs a job writes down in `<support>/jobs/<job id>/`
so any other process (a second terminal, an agent, the window) can see, wait for and stop it.

It lives in the support folder, never in the music folder: jobs exist without a music folder (Setup, `tools update`),
the registry must not vanish with an unplugged drive, and a sandbox clone must not inherit running jobs.

| file | what |
|---|---|
| `state.json` | id, kind, catalogue command, args, `via`, `roots`, `pid`, `pid_started`, `status`, `started`, `ended`, progress, `person_steps` |
| `alive` | an `flock` the process running the job holds for the job's whole life |
| `events.jsonl` | the events as the window receives them: the first 2 000, a `Truncated` marker, then see `events.tail.jsonl` |
| `events.tail.jsonl` | a rolling tail of the last 10 000 events |
| `result.json` | the final envelope |
| `log.txt` | warnings and tracebacks of that job |
| `stop` | present once someone asked the job to stop |

A job is `lost` when its `state.json` says `queued`, `running` or `stopping` and its `alive` lock is free: never decided
by the pid (pids are reused after a crash or a reboot). The reader that finds it lost rewrites `status: lost`. A worker
ends in this order: `result.json`, then `status: done`, then it lets go of the `alive` lock.

The handoff (so a job is never `lost` between its creation and its worker's first breath): `Registry.create` takes the
`alive` lock itself before `state.json` exists (the claim), the spawner passes that very descriptor to the worker
(`pass_fds`; a `flock` belongs to the open file, not to the process, so the lock stays held while either process has
it) and lets go of its own copy; the worker adopts the descriptor (`alive(fd=…)`). The job is therefore alive at every
instant, and lost only if both die.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import fcntl
import itertools
import json
import logging
import os
import secrets
import shutil
import threading
import time
from collections import deque
from collections.abc import Collection, Iterable, Mapping
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .. import events as ev, words
from ..library import write_json_atomic
from ..problem import Problem
from . import ids

log = logging.getLogger(__name__)

KEEP_JOBS, KEEP_DAYS = 100, 30  # the newest 100 jobs stay, and every job of the last 30 days
HEAD_EVENTS, TAIL_EVENTS = 2000, 10000  # events.jsonl keeps the first 2 000; events.tail.jsonl the last 10 000
# The events that give a run its structure (what a late follower counts its bars and lists from): the tail keeps them
# beyond its cap, in order, and drops only the other lines that fell out of it.
KEPT_TYPES = frozenset({"JobStarted", "RunStarted", "ActionStarted", "ActionFinished", "RunFinished", "JobFinished"})
SLOT_FLUSH_S = 0.5  # a Progress or Waiting slot is written at most twice a second
STATE_WRITE_S = 1.0  # state.json changes other than a new status are written at most once a second
ACTIVE = ("queued", "running", "stopping")
HOLDING = ("running", "stopping")  # a job that has the lock (a queued one is still waiting for it)
STATUSES = (*ACTIVE, "done", "lost")


class NoSuchJob(Problem):
    """No job with this id is in the registry (it ended long ago and was pruned, or never ran here)."""


def new_job_id() -> str:
    """`job:<8 hex>`; the window's jobs and the terminal's alike."""
    return ids.fmt("job", secrets.token_hex(4))


def process_started(pid: int) -> float | None:
    """The start time of process `pid` (seconds since 1970, from `proc_pidinfo`), or None when it can't be read. With the
    pid it tells a process from whatever reuses that pid later."""
    try:
        libproc = ctypes.CDLL(ctypes.util.find_library("proc") or "/usr/lib/libproc.dylib", use_errno=True)

        class BsdInfo(ctypes.Structure):  # struct proc_bsdinfo of <sys/proc_info.h>
            _fields_ = [("flags", ctypes.c_uint32), ("status", ctypes.c_uint32), ("xstatus", ctypes.c_uint32),
                        ("pid", ctypes.c_uint32), ("ppid", ctypes.c_uint32), ("uid", ctypes.c_uint32),
                        ("gid", ctypes.c_uint32), ("ruid", ctypes.c_uint32), ("rgid", ctypes.c_uint32),
                        ("svuid", ctypes.c_uint32), ("svgid", ctypes.c_uint32), ("rfu_1", ctypes.c_uint32),
                        ("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32), ("nfiles", ctypes.c_uint32),
                        ("pgid", ctypes.c_uint32), ("pjobc", ctypes.c_uint32), ("e_tdev", ctypes.c_uint32),
                        ("e_tpgid", ctypes.c_uint32), ("nice", ctypes.c_int32), ("start_tvsec", ctypes.c_uint64),
                        ("start_tvusec", ctypes.c_uint64)]

        info = BsdInfo()
        got = libproc.proc_pidinfo(ctypes.c_int(pid), 3, ctypes.c_uint64(0), ctypes.byref(info),
                                   ctypes.c_int(ctypes.sizeof(info)))  # 3 = PROC_PIDTBSDINFO
        if got != ctypes.sizeof(info) or info.pid != pid:
            return None
        return info.start_tvsec + info.start_tvusec / 1e6
    except (OSError, AttributeError, ValueError):
        return None


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def event_line(event: object) -> str:
    """One event as one line, the way the bridge sends it (`hub.jobs.event_dict`): `{"type": …, fields…}`."""
    return json.dumps({"type": type(event).__name__, **asdict(event)}, ensure_ascii=False)


def _slot(event: object) -> tuple | None:
    """The slot of an update of which only the latest is worth keeping (`hub.jobs._same_slot`'s rule), else None."""
    if isinstance(event, ev.Progress):
        return ("progress", event.track_id, event.step, event.unit)
    if isinstance(event, ev.Waiting):
        return ("waiting", event.kind)
    return None


def _is_structure(event: object) -> bool:
    """An event the tail keeps beyond its cap (`KEPT_TYPES`)."""
    return type(event).__name__ in KEPT_TYPES


class EventsWriter:
    """The one writer thread of a job's `events.jsonl`. `emit` only puts the event on a queue: it never blocks (beyond a
    very short lock) and never raises, because the engine calls it inside download callbacks and error handlers.

    `Progress` and `Waiting` are coalesced by slot (the latest of each slot) and written at most twice a second per
    slot. The file keeps the first `head` events; after those, the events go to `events.tail.jsonl`, which keeps
    (at least while running, exactly once closed) the last `tail` and, beyond them, the run's structure lines
    (`KEPT_TYPES`: a late follower still finds every `ActionFinished`); what fell out of both is named by a `Truncated`
    marker as the last line of `events.jsonl`: `{"type": "Truncated", "event": "Truncated", "skipped": n}` (`type`
    is the key every event line has; `event` the one the design's decision names; `n` counts the lines dropped)."""

    def __init__(self, directory: Path, *, head: int = HEAD_EVENTS, tail: int = TAIL_EVENTS,
                 clock: Callable[[], float] = time.monotonic):
        self.head_path = directory / "events.jsonl"
        self.tail_path = directory / "events.tail.jsonl"
        self.head_limit, self.tail_limit, self.clock = head, tail, clock
        self._queue: deque = deque()
        self._cond = threading.Condition()
        self._closing = False
        self._head_lines: list[str] = []
        self._tail_lines: deque[tuple[str, bool]] = deque()  # what events.tail.jsonl holds now: (line, kept)
        self._compact_at = 2 * tail  # the tail's length that asks for the next compaction
        self._dropped = 0  # lines that fell out of the tail and are in no file any more
        self._marked = 0  # the skipped count the marker on disk says
        self._last_slot: dict[tuple, float] = {}
        self._pending: dict[tuple, object] = {}
        self._head_file = open(self.head_path, "a", encoding="utf-8")
        self._tail_file = None
        self._thread = threading.Thread(target=self._loop, name="job-events", daemon=True)
        self._thread.start()

    def emit(self, event: object) -> None:
        try:
            with self._cond:
                if self._closing:
                    return
                slot = _slot(event)
                if slot is not None and self._queue and _slot(self._queue[-1]) == slot:
                    self._queue[-1] = event
                else:
                    self._queue.append(event)
                self._cond.notify()
        except Exception:  # noqa: BLE001
            pass

    def close(self, timeout: float = 10.0) -> None:
        """Writes what is left, makes the marker and the tail final, and ends the thread."""
        with self._cond:
            self._closing = True
            self._cond.notify_all()
        self._thread.join(timeout)

    # --- the writer thread ---

    def _loop(self) -> None:
        try:
            while True:
                with self._cond:
                    while not self._queue and not self._closing:
                        self._cond.wait(SLOT_FLUSH_S if self._pending else None)
                        if self._pending:
                            break
                    batch = list(self._queue)
                    self._queue.clear()
                    closing = self._closing and not batch
                for event in batch:
                    try:
                        self._take(event)
                    except Exception:  # noqa: BLE001  one event that can't be written must not stop the others
                        log.warning("a job event could not be written", exc_info=True)
                self._flush_due(final=closing)
                self._sync_files()
                if closing:
                    break
        except Exception:  # noqa: BLE001  a full disk must never stop the engine
            log.warning("the job's events file stopped", exc_info=True)
        finally:
            with self._cond:
                self._closing = True  # whatever is emitted from now on is dropped, never queued without end
                self._queue.clear()
            self._finish()

    def _take(self, event: object) -> None:
        slot = _slot(event)
        if slot is None:
            self._flush_due(final=True)  # keep the order: the newest slot values first
            self._write(event_line(event), _is_structure(event))
        elif self.clock() - self._last_slot.get(slot, float("-inf")) >= SLOT_FLUSH_S:
            self._pending.pop(slot, None)
            self._last_slot[slot] = self.clock()
            self._write(event_line(event), _is_structure(event))
        else:
            self._pending[slot] = event

    def _flush_due(self, *, final: bool) -> None:
        for slot, event in list(self._pending.items()):
            if final or self.clock() - self._last_slot.get(slot, float("-inf")) >= SLOT_FLUSH_S:
                del self._pending[slot]
                self._last_slot[slot] = self.clock()
                self._write(event_line(event), _is_structure(event))

    def _write(self, line: str, kept: bool = False) -> None:
        if len(self._head_lines) < self.head_limit:
            self._head_lines.append(line)
            self._head_file.write(line + "\n")
            return
        if self._tail_file is None:
            self._head_file.flush()  # a follower relies on it: a line in the tail means the head is complete on disk
            self._tail_file = open(self.tail_path, "a", encoding="utf-8")
        self._tail_lines.append((line, kept))
        self._tail_file.write(line + "\n")
        if len(self._tail_lines) >= self._compact_at:  # keeps the file from growing without end
            self._compact()

    def _compact(self) -> None:
        """Drops the lines older than the last `tail` that are not structure lines (`KEPT_TYPES`); those stay."""
        older = len(self._tail_lines) - self.tail_limit
        if older > 0:
            kept = [item for item in itertools.islice(self._tail_lines, older) if item[1]]
            self._dropped += older - len(kept)
            self._tail_lines = deque([*kept, *itertools.islice(self._tail_lines, older, None)])
        self._compact_at = len(self._tail_lines) + self.tail_limit  # the structure lines kept do not count to the next
        if self._tail_file is not None:
            self._tail_file.close()
        tmp = self.tail_path.with_name(self.tail_path.name + ".tmp")
        tmp.write_text("".join(line + "\n" for line, _ in self._tail_lines), encoding="utf-8")
        os.replace(tmp, self.tail_path)
        self._tail_file = open(self.tail_path, "a", encoding="utf-8")
        self._mark()

    def _mark(self) -> None:
        """Rewrites events.jsonl as the head and its marker when the count of skipped events changed."""
        skipped = self._dropped
        if skipped == self._marked:
            return
        self._marked = skipped
        self._head_file.close()
        tmp = self.head_path.with_name(self.head_path.name + ".tmp")
        marker = json.dumps({"type": "Truncated", "event": "Truncated", "skipped": skipped})
        tmp.write_text("".join(line + "\n" for line in self._head_lines) + marker + "\n", encoding="utf-8")
        os.replace(tmp, self.head_path)
        self._head_file = open(self.head_path, "a", encoding="utf-8")

    def _sync_files(self) -> None:
        """What the batch wrote reaches the files (a follower reads them); the marker follows each compaction."""
        self._head_file.flush()
        if self._tail_file is not None:
            self._tail_file.flush()

    def _finish(self) -> None:
        try:
            if self._tail_file is not None:
                self._compact()
                self._tail_file.close()
            self._mark()
            self._head_file.close()
        except Exception:  # noqa: BLE001
            pass


def _is_marker(line: str) -> bool:
    """The registry's `Truncated` marker: the last line of `events.jsonl`, rewritten as events are skipped."""
    return '"Truncated"' in line and line.startswith("{") and _type_of(line) == "Truncated"


def _type_of(line: str) -> str | None:
    try:
        return json.loads(line).get("type")
    except (ValueError, AttributeError):
        return None


class EventReader:
    """The new events of one job since the last `read`, in order: the head file by byte offset (it only grows, except
    that the registry rewrites it with a `Truncated` marker as its last line, which is never consumed), then the
    rolling tail (rewritten when it is compacted: found again by the last line seen).

    The writer flushes the head before the tail file exists, so a tail line on disk means the head is complete. That is
    why `read` takes its look at the tail first and at the head second: a head read first could miss lines the writer
    flushes before the tail read, and those would then come out after the tail's."""

    def __init__(self, directory: Path, *, from_end: bool = False):
        self.head, self.tail = directory / "events.jsonl", directory / "events.tail.jsonl"
        self._offset = 0
        self._tail_offset, self._last_tail = 0, b""  # where the tail's last line seen ends; that line with its newline
        if from_end:
            self.read()

    @staticmethod
    def _complete(blob: bytes) -> bytes:
        return blob[:blob.rfind(b"\n") + 1]

    @staticmethod
    def _decode(blob: bytes) -> list[str]:  # by newline only: `splitlines` would also cut at a raw U+2028 in a line
        return blob.decode("utf-8", "replace").split("\n")[:-1]

    def read(self) -> list[str]:
        tail = self._read_tail()
        out: list[str] = []
        try:
            with open(self.head, "rb") as f:
                f.seek(self._offset)
                blob = self._complete(f.read())
        except OSError:
            blob = b""
        for raw in blob.split(b"\n")[:-1]:
            line = raw.decode("utf-8", "replace")
            if _is_marker(line):
                break
            out.append(line)
            self._offset += len(raw) + 1
        return out + tail

    def _read_tail(self) -> list[str]:
        """The new lines of the tail, from one look at one file (a path read twice could be two files, the compaction
        replaces it). It goes on where it stopped when the last line seen still ends there; else the file was replaced
        and the lines after the last one seen are the new ones (all of it when that line is gone: the writer outran us)."""
        try:
            with open(self.tail, "rb") as f:
                start = self._tail_offset - len(self._last_tail)
                if self._last_tail and start >= 0:
                    f.seek(start)
                    if f.read(len(self._last_tail)) == self._last_tail:
                        return self._take(f.read(), self._tail_offset)
                f.seek(0)
                everything = f.read()
        except OSError:
            return []
        done = self._complete(everything)
        lines = self._decode(done)
        if self._last_tail:
            seen = self._last_tail[:-1].decode("utf-8", "replace")
            at = len(lines) - 1 - lines[::-1].index(seen) if seen in lines else -1
            lines = lines[at + 1:]
            self._tail_offset = len(done)
            if lines:
                self._last_tail = lines[-1].encode("utf-8") + b"\n"
            return lines
        return self._take(everything, 0)

    def _take(self, blob: bytes, offset: int) -> list[str]:
        done = self._complete(blob)
        self._tail_offset = offset + len(done)
        lines = self._decode(done)
        if lines:
            self._last_tail = lines[-1].encode("utf-8") + b"\n"
        return lines


class ProgressReducer:
    """The events of a job reduced to `state.json`'s `progress`: the step now running, how many of how many are done, the
    item in work, the last message and `line`, the one line the window's foot shows (`words.job_line`). Only what
    changed is handed to `JobFiles.update`, which rate-limits the write. The worker's job and the window's jobs both
    use it."""

    def __init__(self, files: "JobFiles"):
        self.files = files
        self.fields: dict = {"step": None, "done": None, "total": None, "item": None, "message": None, "line": None}
        self._lock = threading.Lock()

    def __call__(self, event: object) -> None:
        with self._lock:
            before = dict(self.fields)
            self._take(event)
            self.fields["line"] = words.job_line(self.fields)
            changed = self.fields != before
            now = dict(self.fields)
        if changed:
            self.files.update(progress=now)

    def _take(self, event: object) -> None:
        f = self.fields
        if isinstance(event, ev.RunStarted):
            f.update(done=0, total=event.total)
        elif isinstance(event, ev.ActionStarted):
            track = event.action.track
            f.update(done=event.index - 1, total=event.total, item=f"{', '.join(track.artists)} - {track.title}")
        elif isinstance(event, ev.ActionFinished):
            f["done"] = (f["done"] or 0) + 1
        elif isinstance(event, ev.StepChanged):
            f["step"] = event.step
        elif isinstance(event, ev.ReadingPlaylist):
            f.update(step="reading playlists", done=event.index - 1, total=event.total, item=event.folder)
        elif isinstance(event, (ev.MovesProgress, ev.BatchProgress)):
            f.update(done=event.done, total=event.total)
            if isinstance(event, ev.BatchProgress):
                f["item"] = event.name
        elif isinstance(event, ev.ImportProgress):
            f.update(step=event.phase, done=event.done, total=event.total)
        elif isinstance(event, ev.Message):
            f["message"] = event.text


class JobFiles:
    """One job's folder. The process that runs the job holds the `alive` lock (`with files.alive():`) and is the only
    one that writes `state.json` besides a reader that finds the job lost; every other process only reads, and asks
    for a stop with `request_stop`."""

    def __init__(self, directory: Path):
        self.dir = directory
        self.id = directory.name
        self._lock = threading.Lock()
        self._mine: dict | None = None  # the state as the writing process has it
        self._claim: int | None = None  # the `alive` descriptor the creator holds until the worker (or `alive()`) has it
        self._dirty = False
        self._written = float("-inf")

    # --- state ---

    @property
    def state_path(self) -> Path:
        return self.dir / "state.json"

    def state(self) -> dict:
        """The job's state as it is now. A job that is `queued`, `running` or `stopping` with nobody holding its `alive`
        lock is rewritten as `lost` first (never decided by the pid)."""
        with self._lock:
            if self._mine is not None:
                return dict(self._mine)
        state = _read_json(self.state_path) or {"id": self.id, "status": "lost"}
        if state.get("status") in ACTIVE and not self.is_alive():
            state = self._mark_lost()
        return state

    def _mark_lost(self) -> dict:
        state = _read_json(self.state_path) or {"id": self.id}  # a worker may have ended since: read again
        if state.get("status") in ACTIVE:
            state = {**state, "status": "lost", "ended": _now()}
            try:
                write_json_atomic(self.state_path, state)
            except OSError:
                pass
        return state

    def update(self, **fields) -> None:
        """Merges `fields` into the state. A new `status` is written at once; other changes at most once a second
        (the rest waits for the next call, `flush` or the end of `alive()`)."""
        with self._lock:
            if self._mine is None:
                self._mine = _read_json(self.state_path) or {"id": self.id}
            status_changed = "status" in fields and fields["status"] != self._mine.get("status")
            self._mine.update(fields)
            self._dirty = True
            if status_changed or "person_steps" in fields or time.monotonic() - self._written >= STATE_WRITE_S:
                self._write_locked()

    def update_if(self, statuses: tuple, **fields) -> bool:
        """Like `update`, but only while the status is one of `statuses` (loaded as `update` loads it); written at once.
        So a late `stopping` can never overwrite `done`. True when it wrote."""
        with self._lock:
            if self._mine is None:
                self._mine = _read_json(self.state_path) or {"id": self.id}
            if self._mine.get("status") not in statuses:
                return False
            self._mine.update(fields)
            self._write_locked()
            return True

    def flush(self) -> None:
        with self._lock:
            if self._dirty:
                self._write_locked()

    def _write_locked(self) -> None:
        write_json_atomic(self.state_path, self._mine)
        self._dirty = False
        self._written = time.monotonic()

    def set_person_steps(self, steps: Iterable[Mapping]) -> None:
        """The steps only a person can do, while the job waits for them (§6.5); `[]` once it moves on."""
        self.update(person_steps=[dict(step) for step in steps])

    # --- liveness ---

    def claim(self) -> int:
        """Takes the `alive` lock before a worker exists (`Registry.create` does) and keeps the descriptor: pass it to
        the worker with `pass_fds` and `release_claim` afterwards; or `alive()` of this same object adopts it. Raises
        `RuntimeError` when another process holds the lock."""
        if self._claim is not None:
            return self._claim
        fd = os.open(self.dir / "alive", os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise RuntimeError(f"{self.id} is already running in another process.") from None
        self._claim = fd
        return fd

    def release_claim(self) -> None:
        """Lets go of this process's copy of the claim (the worker's copy, if it got one, keeps the lock). Never call
        `flock(LOCK_UN)` for this: that would release the lock for every copy."""
        fd, self._claim = self._claim, None
        if fd is not None:
            os.close(fd)

    @contextmanager
    def alive(self, fd: int | None = None):
        """Holds the `alive` flock for the job's whole life, and writes the process's pid and start time. `fd`: a
        descriptor the spawner passed that already holds the lock (checked to be this job's `alive` file, and made
        non-inheritable so no child of the worker keeps a dead job alive); this object's own claim is used when it has
        one. Raises `RuntimeError` when another process already holds the lock."""
        if fd is not None:
            try:
                same = os.fstat(fd).st_ino == os.stat(self.dir / "alive").st_ino
            except OSError:
                same = False
            if not same:
                raise RuntimeError(f"{self.id}: the descriptor handed over is not this job's alive lock.")
            os.set_inheritable(fd, False)
        elif self._claim is not None:
            fd, self._claim = self._claim, None
        else:
            fd = os.open(self.dir / "alive", os.O_CREAT | os.O_RDWR, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                raise RuntimeError(f"{self.id} is already running in another process.") from None
        try:
            self.update(pid=os.getpid(), pid_started=process_started(os.getpid()))
            try:
                yield self
            finally:
                self.flush()
        finally:
            os.close(fd)  # closing the descriptor lets go of the lock

    def is_alive(self) -> bool:
        """Whether some process holds the `alive` lock: one `LOCK_SH | LOCK_NB` try, let go at once."""
        try:
            fd = os.open(self.dir / "alive", os.O_RDONLY)
        except OSError:
            return False
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            return False
        finally:
            os.close(fd)

    # --- events, result, stop ---

    def events(self, **options) -> EventsWriter:
        return EventsWriter(self.dir, **options)

    def write_result(self, envelope: Mapping) -> None:
        write_json_atomic(self.dir / "result.json", dict(envelope))

    def result(self) -> dict | None:
        return _read_json(self.dir / "result.json")

    def request_stop(self) -> None:
        """Asks the job to stop, from any process: the job's `CancelToken` watches this file (design §6.4)."""
        write_json_atomic(self.dir / "stop", {"asked": _now()})

    def stop_requested(self) -> bool:
        return (self.dir / "stop").exists()


class Registry:
    def __init__(self, support: Path):
        self.root = Path(support) / "jobs"

    def create(self, kind: str, command: str, args: Mapping | None, via: str, roots: Mapping, *,
               job_id: str | None = None) -> JobFiles:
        """A new job's folder with its `state.json` as `queued`, and the `alive` lock already taken by the caller (the
        claim, see the handoff in the module's words): `files.release_claim()` once the worker has the lock, or
        `with files.alive():` to run the job in this process. `roots`: `{music, support, rekordbox, sandbox}`
        (`sandbox` is null until sandboxes exist)."""
        if via not in ("window", "terminal"):
            raise ValueError(f"via is window or terminal, not {via!r}")
        self.root.mkdir(parents=True, exist_ok=True)
        if job_id is not None:
            (self.root / job_id).mkdir()
        else:
            while True:
                job_id = new_job_id()
                try:
                    (self.root / job_id).mkdir()
                    break
                except FileExistsError:
                    continue
        files = JobFiles(self.root / job_id)
        files.claim()  # before state.json exists: a reader that sees the job sees it alive
        try:
            files.update(id=job_id, kind=kind, command=command, args=dict(args or {}), via=via,
                         roots={"music": None, "support": None, "rekordbox": None, "rekordbox_share": None, "sandbox": None, **roots},
                         pid=None, pid_started=None, status="queued", started=_now(), ended=None, person_steps=[])
        except BaseException:
            files.release_claim()
            shutil.rmtree(files.dir, ignore_errors=True)
            raise
        return files

    def get(self, job_id: str) -> JobFiles:
        try:
            ids.parse(job_id, ("job",))
        except ids.BadId as e:
            raise NoSuchJob(e.message, reason=e.reason) from None
        directory = self.root / job_id
        if not (directory / "state.json").is_file():
            raise NoSuchJob(f"There is no job {job_id} here.", reason="unknown_id")
        return JobFiles(directory)

    def _folders(self) -> list[Path]:
        try:
            return [d for d in self.root.iterdir() if d.is_dir() and not d.name.startswith(".")]
        except OSError:
            return []

    def list(self, music: Path | str | None = None, all: bool = False, skip: Collection[str] = ()) -> list[dict]:
        """The states of the jobs of the music folder `music` and of those with none (unless `all`), newest first.
        Folders named in `skip` are not read at all (the watch's settled jobs)."""
        found = []
        for directory in self._folders():
            if directory.name in skip:
                continue
            state = JobFiles(directory).state()
            if "kind" not in state:
                continue
            wanted = (state.get("roots") or {}).get("music")
            if all or wanted is None or (music is not None and str(wanted) == str(music)):
                found.append(state)
        return sorted(found, key=lambda s: (s.get("started") or "", s.get("id") or ""), reverse=True)

    def prune(self, now: datetime) -> list[str]:
        """Removes the jobs beyond the newest `KEEP_JOBS` that are also older than `KEEP_DAYS` days. A job whose `alive`
        lock is held is never removed. Returns the ids removed."""
        if now.tzinfo is None:
            now = now.astimezone()
        cutoff = now - timedelta(days=KEEP_DAYS)
        rows = []
        for directory in self._folders():
            state = _read_json(directory / "state.json") or {}
            try:
                started = datetime.fromisoformat(state["started"])
                if started.tzinfo is None:
                    started = started.astimezone()
            except (KeyError, TypeError, ValueError):
                started = datetime.fromtimestamp(directory.stat().st_mtime).astimezone()
            rows.append((started, directory))
        rows.sort(key=lambda r: (r[0], r[1].name), reverse=True)
        removed = []
        for started, directory in rows[KEEP_JOBS:]:
            if started >= cutoff or JobFiles(directory).is_alive():
                continue
            shutil.rmtree(directory, ignore_errors=True)
            removed.append(directory.name)
        return removed

    def running(self, music: Path | str | None) -> int:
        """How many jobs of this music folder (or with none) run now."""
        return sum(1 for s in self.list(music) if s.get("status") in ACTIVE)
