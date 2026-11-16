"""The job client (issue 39, design §6.4 and §6.5): everything a process does with a job it did not run itself, from the
registry's files alone (`hub/registry.py`): following its events, waiting for its end, listing, showing and stopping it.
`call.start_job` hands every job it starts to `attach`; the `job` words are `run`.

- **Waiting.** `drive` polls the job's folder. A job has ended when its status says `done` (its `result.json` is
  written first, §6.3 step 5) or `lost`; never when an event says so: a job that waits for the library under
  `--wait-busy` writes a `JobFinished(console)` into `events.jsonl` before it asks again. The answer of an ended job is
  its own envelope; a wait that ran out answers `running` (exit 8) with the job's id, its progress and its live person
  steps, and the job goes on.
- **The default wait** (§6.5): no flag and stdout a terminal follows to the end; otherwise `--wait 90` (agent shells
  kill a call after about two minutes). `DISCJOCKEY_DEFAULT_WAIT_S` replaces the 90 (tests; the worker never reads it).
- **Events.** `EventReader` reads `events.jsonl` (the first 2 000 events) and then `events.tail.jsonl` (a rolling tail),
  as the registry writes them. Text mode prints them through the console's `ConsolePrinter`; `--jsonl` prints each
  line as the file holds it, between `{"event": "Job", "state": "started"}` and `{"event": "Job", "state": "ended"}`.
- **Stopping.** `job stop` writes the stop file; `--now` (terminal jobs only) sends SIGINT twice, at least
  `CTRL_C_REPEAT_S` apart, and only while the job's `alive` lock is held and the pid's start time is the one the worker
  wrote, so a reused pid never gets a signal. In a client that started the job, the first Ctrl-C writes the stop file
  and a second one, a second later, is `--now`; in `job follow` and `job wait` Ctrl-C only leaves the job running."""
from __future__ import annotations

import dataclasses
import json
import os
import signal
import sys
import time
import types
import typing
from collections.abc import Callable
from pathlib import Path

from .. import events as ev
from ..console import ConsolePrinter
from ..events import CTRL_C_REPEAT_S
from ..hub import catalog, registry
from . import bind, envelope
from .parser import JOB_FOLLOW, JOB_LIST, JOB_SHOW, JOB_STOP, JOB_WAIT, Flags, Parsed

DEFAULT_WAIT_S = 90.0
WAIT_ENV = "DISCJOCKEY_DEFAULT_WAIT_S"  # replaces the 90 s default (a test's short one); no worker code reads it
START_WAIT_S = 15.0  # how long a client waits for a worker to leave `queued` (with --wait-busy: that much more)
POLL_S = 0.05
SHOWN_EVENTS = 20  # the last events `job show` prints
FIRST_LINE = "Job {job} started (follow: {path} job follow {job})"
NO_JOB = "No job of this music folder is running."
NO_JOB_YET = "There is no job here yet. `job list --all` lists every job."
WINDOW_STOP = "{job} belongs to the window, which stops its jobs with its own Stop button."


def command_path() -> str:
    from . import housekeeping  # housekeeping imports this module
    return housekeeping.command_path()


def default_wait() -> float:
    try:
        return float(os.environ[WAIT_ENV])
    except (KeyError, ValueError):
        return DEFAULT_WAIT_S


def stdout_is_terminal() -> bool:
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def first_line(job_id: str) -> str:
    return FIRST_LINE.format(job=job_id, path=command_path())


# --- events ---

def _build(cls: type, data: dict) -> object:
    hints = typing.get_type_hints(cls)
    return cls(**{f.name: _value(hints[f.name], data[f.name]) for f in dataclasses.fields(cls) if f.name in data})


def _value(hint: object, value: object) -> object:
    if value is None:
        return None
    origin, args = typing.get_origin(hint), typing.get_args(hint)
    if origin in (typing.Union, types.UnionType):
        return _value(next(a for a in args if a is not type(None)), value)
    if origin is tuple:
        return tuple(_value(args[0], v) for v in value)
    if origin is list:
        return [_value(args[0], v) for v in value]
    if dataclasses.is_dataclass(hint):
        return _build(hint, value)
    return value


def revive(data: dict) -> object | None:
    """The engine's event a line of `events.jsonl` was made from (`{"type": name, fields…}`), or None for a line that is
    no event of the engine (the job's own `JobStarted`, `Truncated`) or does not fit it any more."""
    cls = getattr(ev, str(data.get("type")), None)
    if not (isinstance(cls, type) and dataclasses.is_dataclass(cls)):
        return None
    try:
        return _build(cls, data)
    except (TypeError, ValueError, KeyError, StopIteration):
        return None


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


# --- the envelopes of a job's states ---

def live_steps(rec: dict) -> list[dict]:
    return list(rec.get("person_steps") or [])


def running_envelope(command: str, rec: dict, *, wait: float | None = None) -> dict:
    """`running` (exit 8): the job goes on. Its progress and the steps only a person can do come from `state.json`."""
    job_id = rec["id"]
    next_ = [{"run": f"{command_path()} job wait {job_id} --wait {int(wait) if wait else int(DEFAULT_WAIT_S)}",
              "why": "wait for it again"}]
    return envelope.problem(command, "running", "still_running", job=job_id, next=next_, person_steps=live_steps(rec),
                            data={"job": job_id, "status": rec.get("status"), "progress": rec.get("progress"),
                                  "person_steps": live_steps(rec)})


def ended_envelope(command: str, files: registry.JobFiles, rec: dict) -> dict:
    """The job's own envelope; a job that ended without one (its process died) is `failed` / `worker_lost`."""
    result = files.result()
    if result is not None:
        return result
    return envelope.problem(command, "failed", "worker_lost", job=files.id, data={"log": str(files.dir / "log.txt")},
                            next=[{"run": f"{command_path()} job show {files.id} --log", "why": "what the job wrote down"}])


def started_envelope(command: str, rec: dict) -> dict:
    """`--detach`: the job runs; its id is in `job`."""
    return envelope.envelope(command, "ok", message=f"{rec['id']} is running.", job=rec["id"], person_steps=live_steps(rec),
                             data={"job": rec["id"], "status": rec.get("status")},
                             next=[{"run": f"{command_path()} job wait {rec['id']} --wait {int(DEFAULT_WAIT_S)}",
                                    "why": "wait for it"}])


# --- stopping ---

def _signalable(files: registry.JobFiles) -> tuple[bool, int | None]:
    """(a signal may be sent, the pid): the `alive` lock is held and the pid's start time is the one the worker wrote."""
    rec = files.state()
    pid, started = rec.get("pid"), rec.get("pid_started")
    if rec.get("status") not in registry.ACTIVE or not files.is_alive():
        return False, None
    if pid is None:  # the worker has not written its pid yet: the stop file will reach it
        return True, None
    now = registry.process_started(pid)
    return (now is not None and started is not None and abs(now - started) < 0.01), pid


def send_stop_now(files: registry.JobFiles) -> bool:
    """SIGINT twice, `CTRL_C_REPEAT_S` apart (the worker takes the first as "stop safely" and the second as "at once"),
    each only after `_signalable` said yes. False: the job is lost (nothing alive with that pid and start time), and no
    signal went anywhere; True: the signals went, or the job had ended meanwhile."""
    for n in range(2):
        ok, pid = _signalable(files)
        if not ok:
            return n > 0
        if pid is None:
            return True
        try:
            os.kill(pid, signal.SIGINT)
        except OSError:
            return True
        if n == 0:
            time.sleep(CTRL_C_REPEAT_S + 0.05)
    return True


def stop(command: str, files: registry.JobFiles, *, now: bool = False) -> dict:
    rec = files.state()
    if rec.get("status") not in registry.ACTIVE:
        return envelope.problem(command, "refused", "not_running", job=files.id,
                                data={"job": files.id, "status": rec.get("status")})
    if now and rec.get("via") == "window":
        return envelope.problem(command, "refused", "window_job", WINDOW_STOP.format(job=files.id), job=files.id)
    files.request_stop()
    if now and not send_stop_now(files):
        return envelope.problem(command, "failed", "worker_lost", job=files.id,
                                message=f"{files.id} has no process any more (no signal was sent).",
                                next=[{"run": f"{command_path()} job show {files.id} --log", "why": "what the job wrote down"}])
    return envelope.envelope(command, "ok", message=f"Asked {files.id} to stop.", job=files.id,
                             data={"job": files.id, "status": "stopping", "now": now})


# --- waiting and following ---

class Interrupts:
    """Ctrl-C while a client waits: a press is noted (a second one sooner than `CTRL_C_REPEAT_S` is one press that
    arrived twice) and `drive` acts on it between two polls, never inside the handler."""

    def __init__(self):
        self.presses: list[float] = []
        self._previous = None

    def __enter__(self):
        try:
            self._previous = signal.signal(signal.SIGINT, self._on_press)
        except ValueError:  # not the main thread: no handler, the default stays
            self._previous = None
        return self

    def __exit__(self, *exc):
        if self._previous is not None:
            signal.signal(signal.SIGINT, self._previous)
        return False

    def _on_press(self, signum, frame) -> None:
        now = time.monotonic()
        if not self.presses or now - self.presses[-1] >= CTRL_C_REPEAT_S:
            self.presses.append(now)


def _job_line(job_id: str, state: str, **fields) -> str:
    return json.dumps({"event": "Job", "state": state, "job": job_id, **fields}, ensure_ascii=False)


def drive(files: registry.JobFiles, command: str, flags: Flags, *, wait: float | None, events: str | None,
          own: bool, from_end: bool = False, now: Callable[[], float] = time.monotonic) -> dict:
    """Follows the job until it has ended or `wait` seconds are over (None: to the end). `events`: "console" prints the
    progress lines, "jsonl" the event lines, None nothing. `own`: this client started the job, so Ctrl-C stops it
    (first press: stop safely; a second one: `--now`); else Ctrl-C leaves it running."""
    reader = EventReader(files.dir, from_end=from_end)
    printer = ConsolePrinter(verbose=flags.verbose, out=sys.stderr if flags.json else None) if events == "console" else None
    end = None if wait is None else now() + wait
    handled, shown_steps = 0, None
    if events == "jsonl":
        print(_job_line(files.id, "started", command=command), flush=True)

    def show() -> None:
        for line in reader.read():
            if events == "jsonl":
                print(line, flush=True)
            elif printer is not None:
                event = revive(json.loads(line)) if line.startswith("{") else None
                if event is not None:
                    printer(event)

    with Interrupts() as interrupts:
        while True:
            rec = files.state()
            show()
            if rec.get("status") in ("done", "lost"):
                break
            if printer is not None and live_steps(rec) != shown_steps:
                shown_steps = live_steps(rec)
                for step in shown_steps:
                    print(f"Your turn: {step.get('say')}", file=sys.stderr, flush=True)
            if len(interrupts.presses) > handled:
                handled = len(interrupts.presses)
                if not own:
                    return running_envelope(command, rec)
                if handled == 1:
                    files.request_stop()
                    print("\nStopping safely after the current step... (press Ctrl-C again to stop immediately)",
                          file=sys.stderr, flush=True)
                else:
                    print("\nStopping at once...", file=sys.stderr, flush=True)
                    stop(command, files, now=True)
            if end is not None and now() >= end:
                return running_envelope(command, rec, wait=wait)
            time.sleep(POLL_S)
    show()  # what the job wrote last (its events file is closed before `result.json`)
    result = ended_envelope(command, files, rec)
    if events == "jsonl":
        print(_job_line(files.id, "ended", outcome=result["outcome"], reason=result["reason"]), flush=True)
    return result


def first_answer(files: registry.JobFiles, command: str, wait_busy: float) -> dict:
    """`--detach`: waits (bounded) until the worker has left `queued` or ended; `ok` with the job's id while it runs,
    or the job's own envelope when it ended first (a `busy` included)."""
    end = time.monotonic() + START_WAIT_S + wait_busy
    rec = files.state()
    while rec.get("status") == "queued" and time.monotonic() < end:
        time.sleep(POLL_S)
        rec = files.state()
    if rec.get("status") in ("done", "lost"):
        return ended_envelope(command, files, rec)
    return started_envelope(command, rec)


def attach(files: registry.JobFiles, command: str, flags: Flags) -> dict:
    """What a client that started a job answers (design §6.5): `--detach` the start; `--wait S` the end or `running`;
    no flag a terminal follows to the end and anything else waits 90 s."""
    if flags.detach:
        return first_answer(files, command, flags.wait_busy or 0)
    follows = stdout_is_terminal()
    wait = flags.wait if flags.wait is not None else None if follows else default_wait()
    return drive(files, command, flags, wait=wait, events=_events_for(flags, follows), own=True)


def _events_for(flags: Flags, terminal: bool) -> str | None:
    if flags.jsonl:
        return "jsonl"
    return "console" if terminal and not flags.json else None


# --- the `job` words ---

def _registry() -> tuple[registry.Registry, str | None]:
    here = bind.resolved()
    music = str(here.paths.root) if here.paths is not None else str(here.music_folder) if here.music_folder else None
    return registry.Registry(here.support), music


def _is_write(rec: dict) -> bool:
    found = catalog.by_method(rec.get("method") or "")
    return not found or found[0].kind == "J"


def _rank(rows: list[dict]) -> list[dict]:
    """Running first, then newest (the registry already lists newest first; the sort is stable)."""
    return sorted(rows, key=lambda r: r.get("status") not in registry.ACTIVE)


def _pick(command: str, text: str, reg: registry.Registry, music: str | None, *, running_only: bool) -> tuple[registry.JobFiles | None, dict | None]:
    """The job a word names, or the envelope of why not. `current` is the one running write job of this music folder;
    for the words that only look, with none running, the newest job."""
    if text != "current":
        try:
            return reg.get(text), None
        except registry.NoSuchJob as e:
            return None, envelope.problem(command, "bad_args", e.reason or "unknown_id", str(e))
    rows = reg.list(music)
    running = [r for r in rows if r.get("status") in registry.ACTIVE and _is_write(r)]
    chosen = running[0] if running else None if running_only else rows[0] if rows else None
    if chosen is None:
        return None, envelope.problem(command, "refused", "not_running", NO_JOB if running_only else NO_JOB_YET)
    return reg.get(chosen["id"]), None


def _last_events(files: registry.JobFiles) -> list[dict]:
    lines = EventReader(files.dir).read()[-SHOWN_EVENTS:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _list(command: str, parsed: Parsed) -> dict:
    reg, music = _registry()
    rows = _rank(reg.list(music, all=bool(parsed.args.get("all"))))
    return envelope.envelope(command, "ok", data={"jobs": rows},
                             message=f"{len(rows)} job{'s' if len(rows) != 1 else ''}." if rows else "No jobs yet.")


def _show(command: str, parsed: Parsed) -> dict:
    reg, music = _registry()
    files, failed = _pick(command, parsed.args["job"], reg, music, running_only=False)
    if failed is not None:
        return failed
    rec = files.state()
    data = {"state": rec, "events": _last_events(files), "result": files.result() if rec.get("status") in ("done", "lost") else None}
    if parsed.args.get("log"):
        try:
            data["log"] = (files.dir / "log.txt").read_text(encoding="utf-8", errors="replace")
        except OSError:
            data["log"] = ""
    return envelope.envelope(command, "ok", data=data, job=files.id, person_steps=live_steps(rec))


def _wait(command: str, parsed: Parsed) -> dict:
    reg, music = _registry()
    files, failed = _pick(command, parsed.args["job"], reg, music, running_only=False)
    if failed is not None:
        return failed
    flags, follow = parsed.flags, parsed.command == JOB_FOLLOW
    terminal = stdout_is_terminal()
    wait = flags.wait if flags.wait is not None else None if follow or terminal else default_wait()
    events = "console" if follow and not flags.json and not flags.jsonl else _events_for(flags, terminal) if not follow else (
        "jsonl" if flags.jsonl else None)
    return drive(files, command, flags, wait=wait, events=events, own=False,
                 from_end=bool(parsed.args.get("from_end")))


def _stop(command: str, parsed: Parsed) -> dict:
    reg, music = _registry()
    files, failed = _pick(command, parsed.args["job"], reg, music, running_only=True)
    if failed is not None:
        return failed
    return stop(command, files, now=bool(parsed.args.get("now")))


def run(parsed: Parsed) -> dict:
    """The answer of a `job` word."""
    command = " ".join(parsed.command)
    handler = {JOB_LIST: _list, JOB_SHOW: _show, JOB_FOLLOW: _wait, JOB_WAIT: _wait, JOB_STOP: _stop}[parsed.command]
    return handler(command, parsed)
