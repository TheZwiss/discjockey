"""The job worker (issue 39, design §6.3): `Discjockey job _worker <id>`, the hidden command a write job runs in. It
outlives the client that started it; the client only follows `<support>/jobs/<id>/` (`hub/registry.py`).

What it does, in this order:
1. Takes the job's `alive` lock: the descriptor the spawner handed over (`ALIVE_FD_ENV`; see the handoff in the
   registry's words), else it takes the lock itself (a worker started by hand).
2. Reads `state.json` and works only from it: the music and support folders and rekordbox's folder are the ones the
   client saw (`roots`), the method and its arguments are the stored ones, `wait_busy` is the stored wait. Nothing comes
   from the worker's own environment (it is overwritten from `roots` for the engine code that still reads it); the
   one thing the environment tells it is where the registry is, which the spawner sets itself.
3. Builds the headless `HubApi` (`bind.headless`) whose `Jobs` runs inline (`Jobs.adopt`): the work runs on this
   main thread, the only one that gets signals, and takes the library lock there. A write job runs under its own
   `caffeinate -i -w <pid>`.
4. A held library lock: the `busy` envelope, naming the holder when the registry knows it, and the end; with
   `wait_busy` it asks again every 2 s until that many seconds have passed.
5. SIGINT: the first one cancels the job's token (stop safely); a second one at least `CTRL_C_REPEAT_S` later raises
   `KeyboardInterrupt` (stop at once; `deferred_interrupt` still holds it back inside a step); a sooner one is ignored.
   The job's `stop` file cancels the same token.
6. The end, in this order: the events file is closed, `result.json`, `status: done`, then the `alive` lock is let go.

`state.json`'s `progress` is the events reduced to `{step, done, total, item, message, line}` (`registry.ProgressReducer`,
the window's jobs use it too): written at every status change and at most once a second otherwise (`JobFiles.update`)."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime

from .. import events as ev
from ..events import CTRL_C_REPEAT_S
from ..hub import catalog, jobs, outcomes, registry
from . import bind, envelope

ALIVE_FD_ENV = "DISCJOCKEY_ALIVE_FD"  # the descriptor of the spawner's claim on `alive`, set by `call.spawn_worker`
RETRY_BUSY_S = 2.0  # how often `--wait-busy` asks for the library again
TICK_S = 0.5  # how often the worker looks whether it was asked to stop, and writes a held-back state
BUSY_PROBLEMS = ("console", "busy")  # the kinds of problem a held library lock makes


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Sink:
    """What the engine's events go to: the job's `events.jsonl` writer, the progress reducer, and (for the end) the
    job's own `JobFinished`."""

    def __init__(self, writer: registry.EventsWriter, reducer: registry.ProgressReducer):
        self.writer, self.reducer = writer, reducer
        self.finished: jobs.JobFinished | None = None

    def emit(self, event: object) -> None:
        if isinstance(event, jobs.JobFinished):
            self.finished = event
        self.writer.emit(event)
        try:
            self.reducer(event)
        except Exception:  # noqa: BLE001  the engine calls this inside download callbacks: it never raises
            pass


class Ticker(threading.Thread):
    """Notices a stop request (Ctrl-C or the `stop` file) and writes `stopping`; writes what `update` held back. It
    never touches the files inside a signal handler (the handler only sets the token). `interrupt` (a read job): the
    stop request also reaches the main thread as SIGINT, once, because a read has nothing to finish safely."""

    def __init__(self, files: registry.JobFiles, token, interrupt: bool = False):
        super().__init__(name="job-ticker", daemon=True)
        self.files, self.token = files, token
        self.interrupt, self._sent = interrupt, False
        self._end = threading.Event()

    def run(self) -> None:
        while not self._end.wait(TICK_S):
            try:
                if self.token.cancelled and self.files.state().get("status") == "running":
                    self.files.update(status="stopping")
                if self.interrupt and self.token.cancelled and not self._sent:
                    self._sent = True
                    os.kill(os.getpid(), signal.SIGINT)  # the handler runs on the main thread, which runs the read
                self.files.flush()
            except Exception:  # noqa: BLE001
                pass

    def end(self) -> None:
        self._end.set()
        self.join(5)


class Caffeinate:
    """`caffeinate -i -w <own pid>` for a write job (`J`) and a read job (`RJ`: an agent's minute-long read must not sleep
    under it either): the Mac does not go to sleep under it, and the process ends by itself when the worker does.
    Nothing if the program is not there. The launcher (`bin/discjockey`) wraps nothing: each worker keeps the Mac awake."""

    def __init__(self, wanted: bool):
        self.process = None
        if wanted:
            try:
                self.process = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())], stdin=subprocess.DEVNULL,
                                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                self.process = None

    def end(self) -> None:
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()


class StopSignals:
    """SIGINT as `design §6.3` step 4 says. `hard` is whether the second press came (the envelope says `stop_now`).
    `at_once` (a read job): the first press ends the job (a read leaves nothing half-done, so `hard` stays False)."""

    def __init__(self, token, at_once: bool = False):
        self.token, self.hard, self.first, self.at_once = token, False, None, at_once
        self.previous = None

    def __enter__(self):
        self.previous = signal.signal(signal.SIGINT, self._on_sigint)
        return self

    def __exit__(self, *exc):
        signal.signal(signal.SIGINT, signal.SIG_IGN)  # the end is written whatever arrives now
        return False

    def _on_sigint(self, signum, frame) -> None:
        now = time.monotonic()
        if self.first is None:
            self.first = now
            self.token.cancel()
            if self.at_once:
                raise KeyboardInterrupt
        elif now - self.first >= CTRL_C_REPEAT_S:
            self.hard = True
            raise KeyboardInterrupt


def _holder(files: registry.JobFiles, roots: dict) -> dict | None:
    """The job that holds the library now, from the registry (`{job, via, kind, line, text, where}`), else None. Only a running job
    that holds the library lock counts (`Jobs._holder_of`: its own `library_lock`, else the catalogue's `locks` column):
    a queued job still waits for it and a running read job holds nothing."""
    return jobs.Jobs._holder_of(s for s in registry.Registry(files.dir.parent.parent).list(roots.get("music"))
                                if s.get("id") != files.id)


def _busy(command: str, files: registry.JobFiles, roots: dict, job=None) -> dict:
    """The `busy` envelope. A job that ended busy by a lock of its own (the support lock a save inside it met) says
    that reason; otherwise the library is held: by the job the registry names, else by a terminal run."""
    own = getattr(getattr(job, "error", None), "reason", None)
    if own in outcomes.REASONS and outcomes.REASONS[own].outcome == "busy":
        return envelope.problem(command, "busy", own, data=getattr(job.error, "data", None), job=files.id)
    holder = _holder(files, roots)
    reason = "library_lock" if holder else "console"
    return envelope.problem(command, "busy", reason, data={"holder": holder or {"via": "unknown"}}, job=files.id)


def _is_busy(answer: dict, job) -> bool:
    if not answer.get("ok"):
        return answer.get("outcome") == "busy"
    return bool(job is not None and job.finished and job.finished.get("problem") in BUSY_PROBLEMS)


def _left_batch(job) -> bool:
    """Whether a job that ended busy left an AIFF batch behind (stopped, with its planned items): its answer names the
    batch and `batch resume`, which is what the person or agent does next, not the same command again."""
    return bool(job is not None and ((job.finished or {}).get("result") or {}).get("batch"))


def _stopped_reason(env: dict, signals: StopSignals) -> dict:
    if env["outcome"] == "stopped" and signals.hard:
        return {**env, "reason": "stop_now", "message": outcomes.REASONS["stop_now"].text}
    return env


def _call(api, method: str, args: dict) -> dict:
    return getattr(api, method)(**args)


def _work(files: registry.JobFiles, record: dict, sink: Sink, api, signals: StopSignals) -> dict:
    """Asks the method to start the job until it ran or the wait for the library is over; the envelope of the end."""
    command, method, args = record["command"], record["method"], record.get("args") or {}
    roots = record.get("roots") or {}
    deadline = time.monotonic() + float(record.get("wait_busy") or 0)
    token = bind.job_token(api)
    entries = catalog.by_method(method)
    try:
        if entries and entries[0].kind == "RJ":  # a read that takes long: no library lock, no `Jobs` job
            return _stopped_reason(_read_job(files, command, method, args, api), signals)
        while True:
            sink.finished = None
            answer = _call(api, method, args)
            job = bind.last_job(api)
            if _is_busy(answer, job) and not _left_batch(job) and time.monotonic() < deadline:
                token.sleep(min(RETRY_BUSY_S, deadline - time.monotonic()))
                continue  # (a busy end that left a batch is not retried: the same command would meet `not_stopped`)
            break
        if _is_busy(answer, job):
            if _left_batch(job):
                return _stopped_reason(api._job_envelope(command, method, job, files.id), signals)
            return _busy(command, files, roots, job)
        if not answer.get("ok"):
            return _stopped_reason(envelope.from_answer(command, answer, job=files.id), signals)
        if job is None or job.finished is None:  # the job ended without its JobFinished (a stop in the very first moment)
            return envelope.problem(command, "failed", "worker_lost", job=files.id)
        env = api._job_envelope(command, method, job, files.id)
        if env["outcome"] == "ok" and entries and "scan" in entries[0].locks:
            env["as_of"] = {**env["as_of"], **(envelope.as_of(api) or {})}  # a read that scans: as a read says how fresh it is now
        return _stopped_reason(envelope.noted(env, method), signals)
    except (ev.Cancelled, KeyboardInterrupt):
        return _stopped_reason(envelope.problem(command, "stopped", "stop", job=files.id), signals)


def _read_job(files: registry.JobFiles, command: str, method: str, args: dict, api) -> dict:
    """An RJ entry (design §5.2): the method answers when it is done, and `status: running` is written by hand (no
    `Jobs` job does it). A stop request (the stop file, `--now` or Ctrl-C) ends it at once, as SIGINT on this thread:
    a read has nothing to finish safely, and its plan is saved only after the method returns."""
    files.update(status="running")
    answer = _call(api, method, args)
    env = envelope.from_answer(command, answer, job=files.id, as_of=envelope.as_of(api) if answer.get("ok") else None)
    entry = catalog.entry_of(method, command)
    if env["outcome"] == "ok" and entry is not None and entry.dry_run == method:
        # the read is a command's `--dry-run` (`aiff_plan`): its plan is saved like any dry run's (call._dry_run)
        if (plan_id := api.save_plan(command, answer, command)) is not None:
            env["data"]["plan_id"] = plan_id
        words = api.result_words(method, answer)
        env["message"] = words.get("message") if words.get("ok") else None
        env["next"] += [n for n in api.scan_next() if n not in env["next"]]
    return envelope.noted(env, method, dry=entry is not None and entry.dry_run == method)


def _run(files: registry.JobFiles) -> int:
    record = files.state()
    roots = record.get("roots") or {}
    command = record.get("command") or "job"
    writer = files.events()
    env = None
    signals = None
    ticker = caffeinate = None
    try:
        bind.adopt_environment(roots)
        sink = Sink(writer, registry.ProgressReducer(files))
        api = bind.headless(bind.from_roots(roots), events=sink, job=files)
        entries = catalog.by_method(record["method"])
        kind = entries[0].kind if entries else None
        caffeinate = Caffeinate(kind in ("J", "RJ"))
        read = kind == "RJ"
        ticker = Ticker(files, bind.job_token(api), interrupt=read)
        ticker.start()
        with StopSignals(bind.job_token(api), at_once=read) as signals:
            env = _work(files, record, sink, api, signals)
    except BaseException:  # noqa: BLE001 - whatever happened, the job ends with an envelope
        traceback.print_exc()  # log.txt
        env = envelope.crashed(command)
        env["job"] = files.id
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if ticker is not None:
            ticker.end()
        writer.close()
        files.write_result(env if env is not None else envelope.crashed(command))
        files.update(status="done", ended=_now())
        if caffeinate is not None:
            caffeinate.end()
    return envelope.exit_code(env)


def _inherited_fd() -> int | None:
    text = os.environ.pop(ALIVE_FD_ENV, None)
    try:
        return int(text) if text else None
    except ValueError:
        return None


def main(argv: list[str]) -> int:
    """`job _worker <id>`: runs the job the registry holds under that id, to its end. The exit code is the outcome's."""
    if len(argv) != 1:
        print("job _worker takes one job id.", file=sys.stderr)
        return 2
    fd = _inherited_fd()
    try:
        files = registry.Registry(bind.resolved().support).get(argv[0])
        with files.alive(fd=fd):
            return _run(files)
    except (registry.NoSuchJob, RuntimeError) as e:
        print(e, file=sys.stderr)
        return 2
