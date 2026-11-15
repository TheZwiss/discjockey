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

`state.json`'s `progress` is the events reduced to `{step, done, total, item, message}` (`Progress`): written at every
status change and at most once a second otherwise (`JobFiles.update`)."""
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


class Reducer:
    """The events of the job reduced to `state.json`'s `progress`: the step now running, how many of how many are done,
    the item in work and the last message. Only what changed is handed to `JobFiles.update`, which rate-limits the
    write."""

    def __init__(self, files: registry.JobFiles):
        self.files = files
        self.fields: dict = {"step": None, "done": None, "total": None, "item": None, "message": None}
        self._lock = threading.Lock()

    def __call__(self, event: object) -> None:
        with self._lock:
            before = dict(self.fields)
            self._take(event)
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


class Sink:
    """What the engine's events go to: the job's `events.jsonl` writer, the progress reducer, and (for the end) the
    job's own `JobFinished`."""

    def __init__(self, writer: registry.EventsWriter, reducer: Reducer):
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
    never touches the files inside a signal handler (the handler only sets the token)."""

    def __init__(self, files: registry.JobFiles, token):
        super().__init__(name="job-ticker", daemon=True)
        self.files, self.token = files, token
        self._end = threading.Event()

    def run(self) -> None:
        while not self._end.wait(TICK_S):
            try:
                if self.token.cancelled and self.files.state().get("status") == "running":
                    self.files.update(status="stopping")
                self.files.flush()
            except Exception:  # noqa: BLE001
                pass

    def end(self) -> None:
        self._end.set()
        self.join(5)


class Caffeinate:
    """`caffeinate -i -w <own pid>` for a write job: the Mac does not go to sleep under it, and the process ends by
    itself when the worker does. Nothing if the program is not there."""

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
    """SIGINT as `design §6.3` step 4 says. `hard` is whether the second press came (the envelope says `stop_now`)."""

    def __init__(self, token):
        self.token, self.hard, self.first = token, False, None
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
        elif now - self.first >= CTRL_C_REPEAT_S:
            self.hard = True
            raise KeyboardInterrupt


def _holder(files: registry.JobFiles, roots: dict) -> dict | None:
    """The job that holds the library now, from the registry (`{job, via, kind}`), else None."""
    for other in registry.Registry(files.dir.parent.parent).list(roots.get("music")):
        if other.get("id") != files.id and other.get("status") in ("running", "stopping"):
            return {"job": other["id"], "via": other.get("via"), "kind": other.get("kind")}
    return None


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


def _stopped_reason(env: dict, signals: StopSignals) -> dict:
    if env["outcome"] == "stopped" and signals.hard:
        return {**env, "reason": "stop_now", "message": outcomes.REASONS["stop_now"].text}
    return env


def _finished_envelope(command: str, files: registry.JobFiles, job, api=None, method: str | None = None) -> dict:
    """The envelope of a job that ran (`JobFinished`): `result` is the data of a success, or what a failed job left. A run
    whose items end in a state its entry counts (`Entry.partial`) is `partial`; the engine's words beside the result
    (`CliApi.result_words`: the batch's id, the steps for the person, what to run next) are added."""
    done = job.finished or {}
    result = done.get("result") or {}
    words = api.result_words(method, result) if api is not None and method and result else {}
    words = words if words.get("ok") else {}  # words are an extra: a failure to find them leaves the answer as it is
    entry = catalog.entry_of(method, command) if method else None
    if done.get("ok"):
        outcome = outcomes.run_outcome(result.get("results"), entry.partial if entry else ())
        return envelope.envelope(command, outcome, message=done.get("message") or words.get("message") or None,
                                 data={**result, **(words.get("data") or {})}, next=words.get("next") or (),
                                 person_steps=words.get("person_steps") or (), job=files.id)
    fields = outcomes.problem_fields(done.get("problem") or "crashed", job.error)
    data = {**result, **(words.get("data") or {}), **(fields["data"] or {})} or None
    return envelope.envelope(command, fields["outcome"], reason=fields["reason"], message=done.get("message"),
                             data=data, next=[*fields["next"], *(words.get("next") or ())],
                             person_steps=[*fields["person_steps"], *(words.get("person_steps") or ())], job=files.id)


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
            if _is_busy(answer, job) and time.monotonic() < deadline:
                token.sleep(min(RETRY_BUSY_S, deadline - time.monotonic()))
                continue
            break
        if _is_busy(answer, job):
            return _busy(command, files, roots, job)
        if not answer.get("ok"):
            return _stopped_reason(envelope.from_answer(command, answer, job=files.id), signals)
        if job is None or job.finished is None:  # the job ended without its JobFinished (a stop in the very first moment)
            return envelope.problem(command, "failed", "worker_lost", job=files.id)
        return _stopped_reason(_finished_envelope(command, files, job, api, method), signals)
    except (ev.Cancelled, KeyboardInterrupt):
        return _stopped_reason(envelope.problem(command, "stopped", "stop", job=files.id), signals)


def _read_job(files: registry.JobFiles, command: str, method: str, args: dict, api) -> dict:
    """An RJ entry (design §5.2): the method answers when it is done, and `status: running` is written by hand (no
    `Jobs` job does it). Stop at once (`--now`) reaches it as SIGINT on this thread; the stop file only ends it where
    the method itself looks at its token."""
    files.update(status="running")
    answer = _call(api, method, args)
    fresh = api.freshness()
    as_of = {key: fresh[key] for key in ("scanned_at", "read_at")} if fresh.get("ok") else None
    return envelope.from_answer(command, answer, job=files.id, as_of=as_of if answer.get("ok") else None)


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
        sink = Sink(writer, Reducer(files))
        api = bind.headless(bind.from_roots(roots), events=sink, job=files)
        entries = catalog.by_method(record["method"])
        caffeinate = Caffeinate(bool(entries) and entries[0].kind == "J")
        ticker = Ticker(files, bind.job_token(api))
        ticker.start()
        with StopSignals(bind.job_token(api)) as signals:
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
