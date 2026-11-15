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
import json
import logging
import os
import secrets
import shutil
import threading
import time
from collections import deque
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .. import events as ev
from ..library import write_json_atomic
from ..problem import Problem
from . import ids

log = logging.getLogger(__name__)

KEEP_JOBS, KEEP_DAYS = 100, 30  # the newest 100 jobs stay, and every job of the last 30 days
HEAD_EVENTS, TAIL_EVENTS = 2000, 10000  # events.jsonl keeps the first 2 000; events.tail.jsonl the last 10 000
SLOT_FLUSH_S = 0.5  # a Progress or Waiting slot is written at most twice a second
STATE_WRITE_S = 1.0  # state.json changes other than a new status are written at most once a second
ACTIVE = ("queued", "running", "stopping")
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


class EventsWriter:
    """The one writer thread of a job's `events.jsonl`. `emit` only puts the event on a queue: it never blocks (beyond a
    very short lock) and never raises, because the engine calls it inside download callbacks and error handlers.

    `Progress` and `Waiting` are coalesced by slot (the latest of each slot) and written at most twice a second per
    slot. The file keeps the first `head` events; after those, the events go to `events.tail.jsonl`, which keeps
    (at least while running, exactly once closed) the last `tail`; what fell out of both is named by a `Truncated`
    marker as the last line of `events.jsonl`: `{"type": "Truncated", "event": "Truncated", "skipped": n}` (`type`
    is the key every event line has; `event` the one the design's decision names)."""

    def __init__(self, directory: Path, *, head: int = HEAD_EVENTS, tail: int = TAIL_EVENTS,
                 clock: Callable[[], float] = time.monotonic):
        self.head_path = directory / "events.jsonl"
        self.tail_path = directory / "events.tail.jsonl"
        self.head_limit, self.tail_limit, self.clock = head, tail, clock
        self._queue: deque = deque()
        self._cond = threading.Condition()
        self._closing = False
        self._head_lines: list[str] = []
        self._tail_lines: deque[str] = deque()  # what events.tail.jsonl holds now (before a compaction)
        self._after_head = 0  # events after the head, written so far
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
            self._write(event_line(event))
        elif self.clock() - self._last_slot.get(slot, float("-inf")) >= SLOT_FLUSH_S:
            self._pending.pop(slot, None)
            self._last_slot[slot] = self.clock()
            self._write(event_line(event))
        else:
            self._pending[slot] = event

    def _flush_due(self, *, final: bool) -> None:
        for slot, event in list(self._pending.items()):
            if final or self.clock() - self._last_slot.get(slot, float("-inf")) >= SLOT_FLUSH_S:
                del self._pending[slot]
                self._last_slot[slot] = self.clock()
                self._write(event_line(event))

    def _write(self, line: str) -> None:
        if len(self._head_lines) < self.head_limit:
            self._head_lines.append(line)
            self._head_file.write(line + "\n")
            return
        if self._tail_file is None:
            self._head_file.flush()  # a follower relies on it: a line in the tail means the head is complete on disk
            self._tail_file = open(self.tail_path, "a", encoding="utf-8")
        self._after_head += 1
        self._tail_lines.append(line)
        self._tail_file.write(line + "\n")
        if len(self._tail_lines) >= 2 * self.tail_limit:  # keeps the file from growing without end
            self._compact()

    def _skipped(self) -> int:
        return max(0, self._after_head - self.tail_limit)

    def _compact(self) -> None:
        while len(self._tail_lines) > self.tail_limit:
            self._tail_lines.popleft()
        if self._tail_file is not None:
            self._tail_file.close()
        tmp = self.tail_path.with_name(self.tail_path.name + ".tmp")
        tmp.write_text("".join(line + "\n" for line in self._tail_lines), encoding="utf-8")
        os.replace(tmp, self.tail_path)
        self._tail_file = open(self.tail_path, "a", encoding="utf-8")
        self._mark()

    def _mark(self) -> None:
        """Rewrites events.jsonl as the head and its marker when the count of skipped events changed."""
        skipped = self._skipped()
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
        """What the batch wrote reaches the files (a follower reads them), and the marker follows the count."""
        self._head_file.flush()
        if self._tail_file is not None:
            self._tail_file.flush()
        if self._skipped() and self._skipped() != self._marked and self._skipped() - self._marked >= self.tail_limit:
            self._mark()

    def _finish(self) -> None:
        try:
            if self._tail_file is not None:
                self._compact()
                self._tail_file.close()
            self._mark()
            self._head_file.close()
        except Exception:  # noqa: BLE001
            pass


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

    def create(self, kind: str, command: str, args: Mapping | None, via: str, roots: Mapping) -> JobFiles:
        """A new job's folder with its `state.json` as `queued`, and the `alive` lock already taken by the caller (the
        claim, see the handoff in the module's words): `files.release_claim()` once the worker has the lock, or
        `with files.alive():` to run the job in this process. `roots`: `{music, support, rekordbox, sandbox}`
        (`sandbox` is null until sandboxes exist)."""
        if via not in ("window", "terminal"):
            raise ValueError(f"via is window or terminal, not {via!r}")
        self.root.mkdir(parents=True, exist_ok=True)
        while True:
            job_id = new_job_id()
            try:
                (self.root / job_id).mkdir()
                break
            except FileExistsError:
                continue
        files = JobFiles(self.root / job_id)
        files.claim()  # before state.json exists: a reader that sees the job sees it alive
        files.update(id=job_id, kind=kind, command=command, args=dict(args or {}), via=via,
                     roots={"music": None, "support": None, "rekordbox": None, "sandbox": None, **roots},
                     pid=None, pid_started=None, status="queued", started=_now(), ended=None, person_steps=[])
        return files

    def get(self, job_id: str) -> JobFiles:
        try:
            ids.parse(job_id, ("job",))
        except ids.BadId:
            raise NoSuchJob(f"{job_id} is not a job id.", reason="unknown_id") from None
        directory = self.root / job_id
        if not (directory / "state.json").is_file():
            raise NoSuchJob(f"There is no job {job_id} here.", reason="unknown_id")
        return JobFiles(directory)

    def _folders(self) -> list[Path]:
        try:
            return [d for d in self.root.iterdir() if d.is_dir() and not d.name.startswith(".")]
        except OSError:
            return []

    def list(self, music: Path | str | None = None, all: bool = False) -> list[dict]:
        """The states of the jobs of the music folder `music` and of those with none (unless `all`), newest first."""
        found = []
        for directory in self._folders():
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
