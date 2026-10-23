"""Background work for the hub window, and how the engine's events reach the window (spec "hub" 6.2-6.4).

Events: `HubEvents.emit` only puts the event on a queue; it never blocks and never raises, because the engine calls
`emit` inside download callbacks and error handlers. A dispatcher thread sends them to the window.
"""
from __future__ import annotations

import fcntl
import itertools
import json
import os
import threading
import traceback
from collections import deque
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .. import config, events as ev, library, playlists_file, qobuz, report as rep, run, settings, spotify, upgrades
from ..events import Cancelled, CancelToken, Emit
from ..library import LockHeld, Paths
from ..models import Protected
from ..ops import OpProblem


@dataclass(frozen=True)
class JobStarted:
    job_id: int
    kind: str  # see Jobs.start
    track_id: str | None


@dataclass(frozen=True)
class JobFinished:
    job_id: int
    kind: str
    ok: bool
    problem: str | None  # None when ok; else a problem kind (bridge contract)
    message: str  # plain English, never a traceback
    result: dict | None  # what the job returned (per kind, see the bridge contract)


@dataclass(frozen=True)
class ConsoleBusy:
    """A Discjockey run in the terminal holds the lock (the window goes read-only), or has finished."""
    running: bool


@dataclass(frozen=True)
class FileDropped:
    """A file was dropped on the window. readable: Discjockey may read it (then add_bought_file can use it)."""
    track_id: str | None  # the to-do item selected when it was dropped
    name: str
    readable: bool
    message: str  # why it can't be used, else ""


@dataclass(frozen=True)
class SignInPhase:
    """Where a sign-in through the browser is (Settings, Setup): waiting for the login, then checking it."""
    service: str  # youtube | soundcloud
    phase: str  # waiting | checking
    browser: str
    browser_name: str


@dataclass(frozen=True)
class AppUpdate:
    """The update check's answer changed (spec public-release §8): the sidebar line, Settings -> This Mac."""
    state: str  # available | up_to_date | unknown
    current: str  # discjockey.__version__
    latest: str | None  # "1.1.0" when available
    url: str | None  # its release page when available


EVENT_TYPES = (ev.RunStarted, ev.ActionStarted, ev.StepChanged, ev.Progress, ev.Waiting, ev.SourceChosen, ev.Checked,
               ev.AccountUsage, ev.ActionFinished, ev.RunFinished, ev.Message, ev.ReadingPlaylist, JobStarted, JobFinished, ConsoleBusy,
               FileDropped, SignInPhase, AppUpdate)


def event_dict(event: object) -> dict:
    return {"type": type(event).__name__, **asdict(event)}


def event_json(event: object) -> str:
    """JSON that can be put into JavaScript source as it is (ASCII only, no "</")."""
    return json.dumps(event_dict(event), ensure_ascii=True).replace("</", "<\\/")


def _same_slot(a: object, b: object) -> bool:
    """Two updates of which only the newer one is worth showing (a page that lags gets the latest only)."""
    if isinstance(a, ev.Progress) and isinstance(b, ev.Progress):
        return (a.track_id, a.step, a.unit) == (b.track_id, b.step, b.unit)
    return isinstance(a, ev.Waiting) and isinstance(b, ev.Waiting) and a.kind == b.kind


class HubEvents:
    """Queue + dispatcher thread between the engine and the window (spec 6.4)."""

    def __init__(self, window: Callable[[], object | None]):
        self.window = window  # the pywebview window, or None once it is gone
        self._queue: deque = deque()
        self._cond = threading.Condition()
        self._stopped = False
        self._thread = threading.Thread(target=self._loop, name="hub-events", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify_all()
        if self._thread.is_alive():
            self._thread.join(timeout)

    def pending(self) -> int:
        with self._cond:
            return len(self._queue)

    def emit(self, event: object) -> None:
        """Never blocks (beyond a very short lock) and never raises."""
        try:
            with self._cond:
                if self._stopped:
                    return
                if self._queue and _same_slot(self._queue[-1], event):
                    self._queue[-1] = event
                else:
                    self._queue.append(event)
                self._cond.notify()
        except Exception:
            pass

    def _loop(self) -> None:
        while True:
            with self._cond:
                while not self._queue and not self._stopped:
                    self._cond.wait()
                if self._stopped:
                    return
                event = self._queue.popleft()
            self._send(event)

    def _send(self, event: object) -> None:
        try:
            script = f"window.dj && window.dj.onEvent({event_json(event)})"
            window = self.window()
            if window is not None:
                window.evaluate_js(script)
        except Exception:  # the page is not ready, is reloading, or the window is closing: drop it
            pass


# --- jobs: one file-changing job at a time, each holding the engine lock for its duration only (spec 6.2) ---

CONSOLE_TEXT = "A sync is running in the terminal. Wait until it has finished."
BUSY_TEXT = "Discjockey is still busy with the last change. Wait until it has finished."
ACTIVITY_OPTIONS = 0x00FFFFFF | (1 << 20)  # NSActivityUserInitiated, idle system sleep disabled


class Busy(Exception):
    """A job could not start. kind: busy (the hub's own job runs) | console (a terminal run holds the lock)."""

    def __init__(self, message: str, kind: str):
        super().__init__(message)
        self.kind = kind


@contextmanager
def keep_awake(reason: str):
    """Keeps App Nap and idle sleep from slowing or pausing a long job (the console has caffeinate)."""
    info = activity = None
    try:
        from Foundation import NSProcessInfo
        info = NSProcessInfo.processInfo()
        activity = info.beginActivityWithOptions_reason_(ACTIVITY_OPTIONS, reason)
    except Exception:
        activity = None
    try:
        yield
    finally:
        if activity is not None:
            try:
                info.endActivity_(activity)
            except Exception:
                pass


def lock_free(path) -> bool:
    """True if nobody holds the engine lock right now (a non-blocking try, released at once)."""
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        return True
    with library.LOCK_PROBE:  # never at the same moment as this process's own run_lock (library.try_flock)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        finally:
            os.close(fd)  # closing also releases the lock
    return True


def problem_of(e: BaseException) -> tuple[str, str]:
    """(problem kind, plain message) for anything a job raised. Never a traceback."""
    if isinstance(e, run.RunCrashed):  # whatever it was, it stopped a running sync
        return "crashed", rep.plain_error(e.error)
    if isinstance(e, (Cancelled, KeyboardInterrupt)):
        return "stopped", "Stopped. Nothing was left half-done."
    if isinstance(e, library.NoLibrary):
        return "no_library", str(e)
    if isinstance(e, LockHeld):
        return "console", CONSOLE_TEXT
    if isinstance(e, (run.SetupProblem, OpProblem, spotify.SpotifyError)):
        return e.kind, str(e)
    if isinstance(e, config.ConfigError):
        return ("not_set_up" if e.kind == "not_set_up" else "refused"), str(e)
    if isinstance(e, upgrades.UpgradeProblem):
        return ("changed" if e.forgotten else "refused"), str(e)
    if isinstance(e, playlists_file.PlaylistsChanged):
        return "changed", str(e)
    if isinstance(e, settings.SettingsError):
        return "config_invalid", str(e)
    if isinstance(e, qobuz.QobuzError):
        return "failed", qobuz.login_problem(e)
    if isinstance(e, Protected):
        return "protected", str(e)
    if isinstance(e, ValueError):
        return "refused", str(e)
    return "crashed", rep.plain_error(e)


@dataclass
class JobContext:
    job_id: int
    kind: str
    token: CancelToken
    emit: Emit  # records into the snapshot and sends to the window
    failed_result: dict | None = None  # JobFinished.result if the work raises (a crashed sync: its report)


@dataclass
class Job:
    id: int
    kind: str
    track_id: str | None
    token: CancelToken
    started: str
    done: threading.Event = field(default_factory=threading.Event)
    last: dict = field(default_factory=dict)  # event type -> the newest event of that type (as JSON data)
    usage: dict = field(default_factory=dict)  # service -> its newest AccountUsage event, in first-seen order
    results: list = field(default_factory=list)  # every ActionFinished so far (as JSON data)
    finished: dict | None = None  # the JobFinished event
    finishing: threading.Lock = field(default_factory=threading.Lock)  # the worker and Stop never both finish it

    def record(self, event: object) -> None:
        data = event_dict(event)
        self.last[data["type"]] = data
        if isinstance(event, ev.AccountUsage):
            self.usage[event.service] = data
        if isinstance(event, ev.ActionFinished):
            self.results.append(data)

    def snapshot(self) -> dict:
        return {"id": self.id, "kind": self.kind, "track_id": self.track_id, "started": self.started,
                "running": not self.done.is_set(), "stopping": self.token.cancelled and not self.done.is_set(),
                "last": dict(self.last), "usage": list(self.usage.values()), "results": list(self.results), "finished": self.finished,
                "actions": list(self.last.get("RunStarted", {}).get("actions", []))}


class Jobs:
    def __init__(self, lock: Path | None, emit: Emit, *, keep_awake=keep_awake,
                 now: Callable[[], datetime] = datetime.now):
        """`lock`: the library's .lock; None while no music folder is bound (Setup's first steps): then a write job
        only waits for the hub's other jobs, as there is no library to share with a terminal run."""
        self.lock, self.emit, self.keep_awake, self.now = lock, emit, keep_awake, now
        self._mutex = threading.Lock()
        self._ids = itertools.count(1)
        self.current: Job | None = None  # the running (or last) write job
        self.refresh: Job | None = None
        self.sign_in: Job | None = None  # a sign-in waiting for the browser (its own slot: it changes no library)
        self._watch: threading.Thread | None = None
        self._closed = threading.Event()
        self._holder = threading.local()  # .on: this thread is a write job's and holds the engine lock
        self._brief = False  # lock_briefly holds (or is about to take) the engine lock: that is no terminal run
        self._briefs = 0  # how many times lock_briefly has taken it (a probe that overlapped one doesn't count)

    def bind(self, lock: Path) -> None:
        """The library's lock, once a music folder is bound (at start or when it is first chosen)."""
        with self._mutex:
            self.lock = lock

    def running(self) -> Job | None:
        job = self.current
        return job if job is not None and not job.done.is_set() else None

    def console_running(self) -> bool:
        """A terminal run holds the lock (our own job, or our own brief save, holding it does not count)."""
        if self.running() is not None or self._brief:
            return False
        briefs = self._briefs
        lock = self.lock
        return lock is not None and not lock_free(lock) and not self._brief and briefs == self._briefs

    @contextmanager
    def lock_briefly(self):
        """The engine lock for one short change made outside a write job: a sign-in's or a page check's settings save
        (spec settings-setup §13, one writer at a time). In a write job's own thread the lock is held already, so
        nothing is taken. Raises Busy (busy: the hub's write job; console: a terminal run) instead of waiting."""
        if getattr(self._holder, "on", False):
            yield
            return
        with self._mutex, ExitStack() as stack:  # no write job can start meanwhile (start takes the mutex)
            if self.running() is not None:
                raise Busy(BUSY_TEXT, "busy")
            self._brief, self._briefs = True, self._briefs + 1
            stack.callback(setattr, self, "_brief", False)
            try:
                if self.lock is not None:
                    stack.enter_context(library.run_lock(self.lock))
            except LockHeld:
                raise Busy(CONSOLE_TEXT, "console") from None
            yield

    def _new(self, kind: str, track_id: str | None) -> Job:
        return Job(next(self._ids), kind, track_id, CancelToken(), self.now().isoformat(timespec="seconds"))

    def start(self, kind: str, work: Callable[[JobContext], dict | None], track_id: str | None = None) -> Job:
        """A write job: `work(ctx)` runs in a worker thread while holding the engine lock and keeping the Mac awake.
        Raises Busy at once if another write job runs or the console holds the lock."""
        with self._mutex:
            if self.running() is not None:
                raise Busy(BUSY_TEXT, "busy")
            if self.console_running():
                raise Busy(CONSOLE_TEXT, "console")
            job = self.current = self._new(kind, track_id)
            threading.Thread(target=self._run, args=(job, work, True), name=f"hub-job-{job.id}", daemon=True).start()
        return job

    def start_refresh(self, work: Callable[[JobContext], dict | None]) -> Job:
        """Read-only work (the Spotify read for the preview): no lock, its own Stop. Not while the hub's sync runs."""
        with self._mutex:
            if self.refresh is not None and not self.refresh.done.is_set():
                raise Busy("Spotify is being read already.", "busy")
            if (job := self.running()) is not None and job.kind == "sync":
                raise Busy("A sync is running; it reads Spotify itself.", "busy")
            job = self.refresh = self._new("refresh", None)
            threading.Thread(target=self._run, args=(job, work, False), name=f"hub-refresh-{job.id}",
                             daemon=True).start()
        return job

    def start_sign_in(self, kind: str, work: Callable[[JobContext], dict | None]) -> Job:
        """A sign-in through the browser (spec settings-setup §13): it waits up to minutes for the user, so it runs
        beside the write jobs, without the engine lock and without keeping the Mac awake. One at a time; its settings
        save takes the lock for a moment (lock_briefly)."""
        with self._mutex:
            if self.sign_in is not None and not self.sign_in.done.is_set():
                raise Busy("A sign-in is already waiting for the browser.", "busy")
            job = self.sign_in = self._new(kind, None)
            threading.Thread(target=self._run, args=(job, work, False), name=f"hub-sign-in-{job.id}",
                             daemon=True).start()
        return job

    def stop_sign_in(self) -> bool:
        job = self.sign_in
        if job is None or job.done.is_set():
            return False
        job.token.cancel()
        return True

    def stop(self) -> bool:
        job = self.running()
        if job is None:
            return False
        job.token.cancel()
        return True

    def stop_refresh(self) -> bool:
        """Ends the read at once, even while its thread still waits for one slow Spotify request: the job counts as
        stopped right away, and whatever that thread sends or returns later is dropped (refresh_work stores nothing
        once the token is cancelled). Write jobs are never let go like this: they hold the lock until they end."""
        job = self.refresh
        if job is None or job.done.is_set():
            return False
        job.token.cancel()
        self._finish(job, False, *problem_of(Cancelled()), None)
        return True

    def wait(self, timeout: float | None = None) -> bool:
        job = self.current
        return job is None or job.done.wait(timeout)

    def status(self) -> dict:
        job, refresh, sign_in = self.current, self.refresh, self.sign_in
        return {"job": job.snapshot() if job else None,
                "sign_in": sign_in.snapshot() if sign_in else None,
                "refresh_running": refresh is not None and not refresh.done.is_set(),
                "console_running": self.console_running()}

    def _job_emit(self, job: Job) -> Emit:
        def emit(event: object) -> None:  # like HubEvents.emit: never raises into the engine
            if job.done.is_set():  # a stopped read whose thread is still finishing a request
                return
            try:
                job.record(event)
            except Exception:
                return
            self.emit(event)
        return emit

    def _run(self, job: Job, work, write: bool) -> None:
        emit = self._job_emit(job)
        emit(JobStarted(job.id, job.kind, job.track_id))
        ok, problem, message, result = True, None, "", None
        ctx = JobContext(job.id, job.kind, job.token, emit)
        try:
            if write:
                lock = library.run_lock(self.lock) if self.lock is not None else nullcontext()
                with lock, self.keep_awake("Discjockey is changing your library"):
                    self._holder.on = True
                    try:
                        result = work(ctx)
                    finally:
                        self._holder.on = False
            else:
                result = work(ctx)
        except BaseException as e:  # noqa: BLE001 - every outcome becomes a JobFinished for the window
            ok = False
            problem, message = problem_of(e)
            result = ctx.failed_result
            if problem == "crashed":
                traceback.print_exc()  # for whoever looks at the terminal; the window gets the plain message
        self._finish(job, ok, problem, message, result)

    def _finish(self, job: Job, ok: bool, problem: str | None, message: str, result: dict | None) -> bool:
        """The job's one JobFinished. False if it had finished already (a refresh that Stop let go)."""
        with job.finishing:
            if job.done.is_set():
                return False
            finished = JobFinished(job.id, job.kind, ok, problem, message, result)
            try:
                job.finished = event_dict(finished)
            except Exception:
                finished = JobFinished(job.id, job.kind, ok, problem, message, None)
                job.finished = event_dict(finished)
            job.done.set()
        self.emit(finished)
        return True

    # --- console detection (spec 6.2): poll the lock every few seconds ---

    def watch_console(self, interval: float = 3.0) -> None:
        def loop() -> None:
            last = False
            while not self._closed.wait(interval):
                now = self.console_running()
                if now != last:
                    last = now
                    self.emit(ConsoleBusy(now))

        self._watch = threading.Thread(target=loop, name="hub-console-watch", daemon=True)
        self._watch.start()

    @property
    def closed(self) -> threading.Event:
        """Set once the window is gone (watchers stop)."""
        return self._closed

    def close(self) -> None:
        self._closed.set()
        if self._watch is not None:
            self._watch.join(2)


# --- the preview and the sync (spec 6.3) ---

class PreviewStore:
    """The last read-only plan (what the Sync screen shows and the user ticks). Keeps the last good one when a later
    read fails (e.g. offline), with the problem next to it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.prep: run.Prepared | None = None
        self.read_at: datetime | None = None
        self.problem: str | None = None
        self.message = ""
        self.stale = False  # a sync ran since: the plan is out of date
        self.auto_read = False  # the hub has started its one automatic read of this session (claim_auto_read)

    def ready(self, prep: run.Prepared, at: datetime, token: CancelToken | None = None) -> None:
        """`token`: a read that was stopped meanwhile (its request answered late) stores nothing."""
        with self._lock:
            if token is not None and token.cancelled:
                return
            self.prep, self.read_at, self.problem, self.message, self.stale = prep, at, None, "", False

    def failed(self, problem: str, message: str, token: CancelToken | None = None) -> None:
        with self._lock:
            if token is not None and token.cancelled:
                return
            self.problem, self.message = problem, message

    def mark_stale(self) -> None:
        with self._lock:
            self.stale = True

    def keys(self) -> set[tuple[str, str, str]]:
        with self._lock:
            return {run.action_key(a) for a in self.prep.plan.actions} if self.prep else set()


def refresh_work(paths: Paths, store: PreviewStore, now: Callable[[], datetime] = datetime.now,
                 infos: dict | None = None):
    """Read-only: run.prepare(dry_run=True). Never writes state.json, reports or the library. With `infos`, also
    reads each playlist's name, owner and cover for the playlist page (a failure there is not a problem)."""
    def work(ctx: JobContext) -> dict:
        try:
            prep = run.prepare(paths, dry_run=True, emit=ctx.emit, token=ctx.token)
        except run.SetupProblem as e:
            store.failed(e.kind, str(e), ctx.token)
            raise
        store.ready(prep, now(), ctx.token)
        ctx.token.check()
        if infos is not None:
            read_infos(paths, [line.playlist_id for line in prep.lines], infos, ctx.token)
        return {"actions": len(prep.plan.actions)}
    return work


def read_infos(paths: Paths, playlist_ids: list[str], infos: dict, token: CancelToken) -> None:
    try:
        session = spotify.load_session(paths)
        session.check, session.sleep = token.check, token.sleep
        me, _ = spotify.current_user(session)
        for pid in playlist_ids:
            token.check()
            try:
                infos[pid] = spotify.playlist_info(session, pid, me)
            except spotify.SpotifyError:
                infos.pop(pid, None)
    except spotify.SpotifyError:
        pass


def sync_work(paths: Paths, store: PreviewStore, ticked: set[tuple[str, str, str]],
              now: Callable[[], datetime] = datetime.now):
    """A sync from the preview: a fresh plan (recovery, .tmp cleanup, new Spotify read), only the actions the user saw
    and left ticked, filtered before open_qobuz; nothing left -> finish_quietly. Afterwards the preview is the plan
    worked out again from that read and the library as the run left it (run.replan), so the Sync page shows what is
    really left without reading Spotify again."""
    def work(ctx: JobContext) -> dict:
        previewed = store.keys()
        if not previewed and store.prep is None:
            raise ValueError("Read your Spotify playlists first (↻), so you can check the plan before it starts.")
        started = now()
        prep, read_at, new_since = None, started, 0
        step = "reading your Spotify playlists and working out the plan"

        def outcome(code: int, report: Path) -> dict:
            return {"exit_code": code, "report": str(report), "actions": len(prep.plan.actions) if prep else 0,
                    "new_since_preview": new_since}

        try:
            prep = run.prepare(paths, emit=ctx.emit, token=ctx.token)
            read_at = now()
            new_since = sum(1 for a in prep.plan.actions if run.action_key(a) not in previewed)
            run.select_actions(prep, previewed, ticked)
            if not prep.plan.actions:
                step = "saving the results"
                code, report = run.finish_quietly(prep, emit=ctx.emit)
                ctx.emit(ev.RunFinished(code, str(report)))
            else:
                step = "signing in to Qobuz"
                qobuz_source = run.open_qobuz(prep)
                code, report = run.execute(prep, qobuz_source, emit=ctx.emit, token=ctx.token)
        except run.RunCrashed as e:  # execute filed the run with its crash note and sent RunFinished
            ctx.failed_result = outcome(1, e.report)
            raise
        except Exception as e:
            if problem_of(e)[0] != "crashed":  # a setup problem, offline, ...: not a crash, nothing to file
                raise
            try:
                report = rep.write_crash(paths, prep.log if prep else rep.RunLog(started), now(), step, e)
            except OSError:  # reports/ can't be written: the crash itself is what the window shows
                raise e from None
            ctx.emit(ev.RunFinished(1, str(report)))
            ctx.failed_result = outcome(1, report)
            raise
        finally:
            if prep is not None:
                preview_after_run(store, prep, read_at)
        return outcome(code, report)
    return work


def preview_after_run(store: PreviewStore, prep: run.Prepared, read_at: datetime) -> None:
    """The preview once a sync has ended (finished, stopped or not): the run's Spotify read planned again against
    the library it left. If state.json or settings.json can't be read now, the old preview stays, marked stale."""
    try:
        store.ready(run.replan(prep), read_at)
    except (library.StateError, settings.SettingsError):
        store.mark_stale()
