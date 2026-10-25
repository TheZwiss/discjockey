"""One sync run, independent of how it is shown. The console (now) and the hub (later) both use these steps:

    prep = prepare(paths, ...)        load, recover, read the playlists, plan      (raises SetupProblem -> exit 2)
    ... the front end shows prep.plan and asks for confirmation ...
    qobuz = open_qobuz(prep)          only if the plan downloads anything     (raises SetupProblem -> exit 2)
    code, report = execute(prep, qobuz, emit=..., token=...)

execute() is safe to run in a worker thread; it never touches signals or the terminal.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from . import config, library, planner, quality, report as rep, sources
from .accounts import ACCOUNTS
from .acquire import Acquirer, make_ready
from .events import ActionStarted, Cancelled, CancelToken, Emit, Message, Result, RunFinished, no_emit
from .execute import Executor
from .fallback import FallbackSource, stream_url
from .library import Paths, StateError
from .models import Action, FetchedPlaylist, Plan, PlaylistLine
from .pacing import Budget, Pacer, record_signal
from .qobuz import QobuzError, QobuzNotSetUp, QobuzSource
from .settings import MAX_EXTRA, Settings, SettingsError, load_settings, save_settings


class SetupProblem(Exception):
    """Something the user has to fix (exit code 2). Nothing in the library was changed.

    kind (the hub picks its card by it): not_set_up | login_expired | offline | playlist_unreadable |
    config_invalid | qobuz_login_failed. `service` names the playlist service a SourceError came from (else None)."""

    def __init__(self, message: str, kind: str = "config_invalid", service: str | None = None):
        super().__init__(message)
        self.kind = kind
        self.service = service


class RunCrashed(Exception):
    """execute() stopped on an unexpected error (`error`, chained as the cause). The run is filed anyway: state saved,
    `report` holds the crash note, and RunFinished (exit code 1) was sent."""

    def __init__(self, error: Exception, report: Path):
        super().__init__(str(error))
        self.error, self.report = error, report


@dataclass
class Prepared:
    paths: Paths
    state: dict  # the planned state: aliases, playlist flags and retargets already applied
    settings: Settings
    plan: Plan
    log: rep.RunLog
    lines: list[PlaylistLine] = field(default_factory=list)
    fetched: list[FetchedPlaylist] = field(default_factory=list)  # as read from the playlist services (the playlist page uses it)

    @property
    def needs_qobuz(self) -> bool:
        return not self.settings.qobuz_skipped and any(a.kind in ("acquire", "upgrade") for a in self.plan.actions)


@contextmanager
def lock_held():
    """The default for `prepare(lock=...)`: the caller holds the library lock already."""
    yield True


def prepare(paths: Paths, *, dry_run: bool = False, extra: int | None = None, emit: Emit = no_emit,
            token: CancelToken | None = None, want_info: bool = False,
            lock: Callable[[], AbstractContextManager[bool]] = lock_held) -> Prepared:
    """`token`: Stop while reading the playlists (also while waiting out a rate limit) raises events.Cancelled.
    Before the playlists are read, the library's records are opened for writing (migrated if needed), interrupted steps
    are finished (not in a dry run) and Library/ is scanned (also in a dry run, spec library-and-sources §6.4), so
    the plan works on the files as they are. `lock()` yields whether the library lock is held for that: a reader
    (the window's preview) that can't get it (a terminal run, a hub job) plans on the records as the last scan
    left them and writes nothing. `want_info`: the hub's read also takes the playlists' names, owners and covers from
    what reading the tracks told (FetchedPlaylist.info), so it needs no second login to ask."""
    token = token or CancelToken()
    log = rep.RunLog(datetime.now())
    try:
        lines = config.load_playlists(paths.playlists_file)
        settings = load_settings(paths.settings_file)
        with lock() as held:
            state = _open(paths, log, emit, dry_run=dry_run) if held else library.load_state(paths)
    except config.ConfigError as e:
        raise SetupProblem(str(e), e.kind) from None
    except (StateError, SettingsError) as e:
        raise SetupProblem(str(e), "config_invalid") from None
    if extra is not None:
        if not 1 <= extra <= MAX_EXTRA:
            raise SetupProblem(f"The extra amount must be between 1 and {MAX_EXTRA}.", "config_invalid")
        settings = replace(settings, extra_date=date.today().isoformat(), extra_amount=extra)
        save_settings(paths.settings_file, settings)
        emit(Message("info", f"Allowing {extra} extra Qobuz downloads today."))

    emit(Message("info", "Reading your playlists..."))
    try:
        fetched = sources.read(paths, lines, emit=emit, token=token, want_info=want_info)
    except sources.SourceError as e:
        raise SetupProblem(str(e), e.kind, e.service) from None
    for fp in fetched:
        for item in fp.skipped:
            log.add_text("skipped", f"[{fp.line.folder}] {item}")

    plan = planner.plan(fetched, state, state["files"], date.today())
    for key in plan.dropped:
        e = plan.state["tracks"][key]
        log.add(Result("dropped", e["folder"], e["artist"], e["title"], key))
    for key, track, folder, files in plan.ambiguous:
        log.add(Result("ambiguous", folder, track.first_artist, track.title, key, "; ".join(files)))
    return Prepared(paths, plan.state, settings, plan, log, lines, fetched)


def _open(paths: Paths, log: rep.RunLog, emit: Emit, *, dry_run: bool) -> dict:
    """The writer's part of prepare (the lock is held): open (and migrate), recover (not in a dry run), scan, then
    the snapshot the plan works on. A dry run needs no snapshot before the scan (scan_library opens the records
    itself, and leaves a pending step's files alone). A dry run changes no music file: a library not yet moved into
    library.db whose state.json has steps pending is neither migrated (that finishes them) nor scanned; it plans
    from state.json as it is."""
    if not dry_run:
        state = library.open_state(paths, emit)
        for message, ok in library.recover_pending(paths, state):
            log.add_text("recovered" if ok else "errors", message)
            emit(Message("info" if ok else "warning", message))
        library.clear_tmp(paths, state)  # keeps what a step that could not be finished yet still needs
    library.scan_library(paths, emit, recover=not dry_run)
    return library.load_state(paths)


def replan(prep: Prepared) -> Prepared:
    """The plan worked out again after a run, read-only: the run's own Spotify read (`prep.fetched`) against the
    state.json and the files the run left behind. What the hub's Sync page shows once a sync ends, so a finished
    run is not offered again and nothing needs another Spotify read (issue 20). Raises StateError or SettingsError
    when those files can't be read."""
    state = library.load_state(prep.paths)
    plan = planner.plan(prep.fetched, state, state["files"], date.today())
    return Prepared(prep.paths, plan.state, load_settings(prep.paths.settings_file), plan, rep.RunLog(datetime.now()),
                    prep.lines, prep.fetched)


LEFT_OUT = "left out of this run by you"
NEW_SINCE_PREVIEW = "new since the preview, next run"


def action_key(a: Action) -> tuple[str, str, str]:
    """How the hub recognises an action of its preview in the fresh plan: a move whose target changed meanwhile is
    a different action, so it is never run unseen."""
    return a.kind, a.track_id, a.dest_dir or f"Library/{a.folder}"


def select_actions(prep: Prepared, previewed: set[tuple[str, str, str]], ticked: set[tuple[str, str, str]]) -> None:
    """Partial plans (the hub's checkboxes): keeps only actions the user saw and left ticked. Call before
    open_qobuz, which decides from the kept actions whether Qobuz is needed. The others get a "queued" result."""
    kept = []
    for a in prep.plan.actions:
        key = action_key(a)
        if key in ticked and key in previewed:
            kept.append(a)
            continue
        e = prep.state["tracks"].get(a.track_id)
        artist, title = (e["artist"], e["title"]) if e else (a.track.first_artist, a.track.title)
        prep.log.add(Result("queued", a.folder, artist, title, a.track_id,
                            LEFT_OUT if key in previewed else NEW_SINCE_PREVIEW))
    prep.plan.actions = kept


def account_budgets(state: dict, save: Callable[[], None], settings: Settings) -> dict[str, Budget]:
    """A Budget for each account service that is set up (YouTube Premium, SoundCloud Go+), in quality order."""
    return {s: Budget(state, save, settings, service=s) for s in ACCOUNTS if s in settings.accounts}


def budget_text(prep: Prepared) -> str:
    lines = [] if prep.settings.qobuz_skipped else [Budget(prep.state, lambda: None, prep.settings).describe()]
    lines += [b.describe() for b in account_budgets(prep.state, lambda: None, prep.settings).values()]
    return "\n".join(lines)


def open_qobuz(prep: Prepared) -> QobuzSource | None:
    if not prep.needs_qobuz:
        return None
    try:
        return QobuzSource.open(prep.paths)
    except QobuzNotSetUp as e:  # not a warning sign from Qobuz, so nothing is recorded
        raise SetupProblem(str(e), "not_set_up") from None
    except QobuzError as e:
        on_disk = library.open_state(prep.paths)  # record the warning sign, nothing else
        record_signal(on_disk, "login_failed", str(e), datetime.now())
        library.save_state(prep.paths, on_disk)
        raise SetupProblem(str(e), "qobuz_login_failed") from None


def fill_kbps(state: dict, fallback: FallbackSource, emit: Emit = no_emit) -> int:
    """Lossy files downloaded before Discjockey kept their bitrate get it from the stream they were made from (read
    only, nothing is downloaded). A failed lookup stays empty and is tried again next sync. Returns how many got one."""
    todo = [e for e in state["tracks"].values() if e.get("status") == "not_lossless" and e.get("path")
            and not e.get("source_kbps") and stream_url(e.get("source") or "", e.get("source_id"))]
    if not todo:
        return 0
    emit(Message("info", f"Looking up the bitrate of {len(todo)} older download{'s' if len(todo) != 1 else ''}..."))

    def one(e: dict) -> int | None:
        try:
            return fallback.stream_kbps(e["source"], e["source_id"])
        except Cancelled:
            raise
        except Exception as ex:  # gone or offline: the next sync tries again
            emit(Message("debug", f"Bitrate of {e['artist']} - {e['title']} not found: {str(ex)[:200]}"))
            return None

    with ThreadPoolExecutor(max_workers=min(8, len(todo))) as pool:
        rates = list(pool.map(one, todo))
    for e, kbps in zip(todo, rates):
        if kbps:
            e["source_kbps"] = kbps
    return sum(1 for k in rates if k)


def finish_quietly(prep: Prepared, emit: Emit = no_emit) -> tuple[int, Path]:
    """For a plan without actions: save flags and aliases, refresh not_lossless.md, write the report."""
    fill_kbps(prep.state, FallbackSource(emit=emit), emit)
    library.save_state(prep.paths, prep.state)
    rep.write_not_lossless(prep.paths, prep.state)
    code = 1 if prep.log.section("errors") else 0
    return code, rep.write_run(prep.paths, prep.log, datetime.now(), code, prep.state)


STEP_VERBS = {"acquire": "downloading", "upgrade": "looking for a better version of",
              "adopt_bought": "adding the bought file of"}


def action_step(event: ActionStarted) -> str:
    """The step a crash note names while an action runs: "downloading Artist - Title (track 2 of 9)"."""
    a = event.action
    return (f"{STEP_VERBS.get(a.kind, 'working on')} {a.track.first_artist} - {a.track.title} "
            f"(track {event.index} of {event.total})")


def execute(prep: Prepared, qobuz, *, emit: Emit = no_emit, token: CancelToken | None = None,
            limit: int | None = None, verbose: bool = False) -> tuple[int, Path]:
    """Runs the plan. Returns (exit code, report path); 130 when stopped through the token (or a KeyboardInterrupt).
    State, not_lossless.md and the report are always written, whatever happens. An unexpected error files the run
    with a crash note as its report (exit code 1, RunFinished sent) and raises RunCrashed."""
    token = token or CancelToken()
    paths, state = prep.paths, prep.state
    step = "getting ready"

    def tracking(event: object) -> None:
        nonlocal step
        if isinstance(event, ActionStarted):
            step = action_step(event)
        emit(event)

    def save() -> None:
        library.save_state(paths, state)

    save()
    if qobuz:
        qobuz.check = token.check  # a stalled Qobuz request still reacts to Stop
    budget = Budget(state, save, prep.settings)
    accounts = account_budgets(state, save, prep.settings)
    fallback = FallbackSource(verbose=verbose, emit=emit, check=token.check,
                              logins={s: (a.browser, a.profile) for s, a in prep.settings.accounts.items()})
    acquirer = Acquirer(qobuz, fallback, budget, Pacer(emit, token), make_ready, emit=emit, accounts=accounts)
    executor = Executor(paths, state, prep.log, acquirer, quality.inspect, emit=tracking, token=token, limit=limit)
    code, crash = 0, None
    try:
        step = "looking up the bitrate of older downloads"
        if fill_kbps(state, fallback, emit):
            save()
        executor.run(prep.plan.actions)
        step = "saving the results"
    except (Cancelled, KeyboardInterrupt):
        code = 130
    except Exception as e:  # noqa: BLE001 - filed with a crash note below, then raised as RunCrashed
        code, crash = 1, e
    finally:
        if qobuz:
            qobuz.close()
        save()
        rep.write_not_lossless(paths, state)
        if code == 0 and prep.log.section("errors"):
            code = 1
        if crash is None:
            path = rep.write_run(paths, prep.log, datetime.now(), code, state)
        else:
            path = rep.write_crash(paths, prep.log, datetime.now(), step, crash, state)
        emit(RunFinished(code, str(path)))
    if crash is not None:
        raise RunCrashed(crash, path) from crash
    return code, path
