"""One sync run, independent of how it is shown. The console (now) and the hub (later) both use these steps:

    prep = prepare(paths, ...)        load, recover, fetch Spotify, plan      (raises SetupProblem -> exit 2)
    ... the front end shows prep.plan and asks for confirmation ...
    qobuz = open_qobuz(prep)          only if the plan downloads anything     (raises SetupProblem -> exit 2)
    code, report = execute(prep, qobuz, emit=..., token=...)

execute() is safe to run in a worker thread; it never touches signals or the terminal.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from . import config, library, planner, quality, report as rep, spotify
from .accounts import ACCOUNTS
from .acquire import Acquirer, make_ready
from .events import Cancelled, CancelToken, Emit, Message, ReadingPlaylist, Result, RunFinished, no_emit
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
    config_invalid | qobuz_login_failed."""

    def __init__(self, message: str, kind: str = "config_invalid"):
        super().__init__(message)
        self.kind = kind


@dataclass
class Prepared:
    paths: Paths
    state: dict  # the planned state: aliases, playlist flags and retargets already applied
    settings: Settings
    plan: Plan
    log: rep.RunLog
    lines: list[PlaylistLine] = field(default_factory=list)
    fetched: list[FetchedPlaylist] = field(default_factory=list)  # as read from Spotify (the playlist page uses it)

    @property
    def needs_qobuz(self) -> bool:
        return not self.settings.qobuz_skipped and any(a.kind in ("acquire", "upgrade") for a in self.plan.actions)


def prepare(paths: Paths, *, dry_run: bool = False, extra: int | None = None, emit: Emit = no_emit,
            token: CancelToken | None = None) -> Prepared:
    """`token`: Stop while reading Spotify (also while waiting out a rate limit) raises events.Cancelled."""
    token = token or CancelToken()
    log = rep.RunLog(datetime.now())
    try:
        lines = config.load_playlists(paths.playlists_file)
        state = library.load_state(paths.state_file)
        settings = load_settings(paths.settings_file)
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

    if not dry_run:
        for message, ok in library.recover_pending(paths, state):
            log.add_text("recovered" if ok else "errors", message)
            emit(Message("info" if ok else "warning", message))
        library.clear_tmp(paths, state)  # keeps what a step that could not be finished yet still needs

    emit(Message("info", "Reading your Spotify playlists..."))
    try:
        session = spotify.load_session(paths)
        session.check, session.sleep = token.check, token.sleep
        fetched = []
        for i, line in enumerate(lines, 1):
            token.check()
            emit(ReadingPlaylist(i, len(lines), line.folder))
            fetched.append(spotify.fetch_playlist(session, line))
    except spotify.SpotifyError as e:
        raise SetupProblem(str(e), e.kind) from None
    for fp in fetched:
        for item in fp.skipped:
            log.add_text("skipped", f"[{fp.line.folder}] {item}")

    plan = planner.plan(fetched, state, library.list_files(paths), date.today())
    for key in plan.dropped:
        e = plan.state["tracks"][key]
        log.add(Result("dropped", e["folder"], e["artist"], e["title"], key))
    for track, folder, files in plan.ambiguous:
        log.add(Result("ambiguous", folder, track.first_artist, track.title, track.id, "; ".join(files)))
    return Prepared(paths, plan.state, settings, plan, log, lines, fetched)


def replan(prep: Prepared) -> Prepared:
    """The plan worked out again after a run, read-only: the run's own Spotify read (`prep.fetched`) against the
    state.json and the files the run left behind. What the hub's Sync page shows once a sync ends, so a finished
    run is not offered again and nothing needs another Spotify read (issue 20). Raises StateError or SettingsError
    when those files can't be read."""
    state = library.load_state(prep.paths.state_file)
    plan = planner.plan(prep.fetched, state, library.list_files(prep.paths), date.today())
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
        on_disk = library.load_state(prep.paths.state_file)  # record the warning sign, nothing else
        record_signal(on_disk, "login_failed", str(e), datetime.now())
        library.save_state(prep.paths.state_file, on_disk)
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
    library.save_state(prep.paths.state_file, prep.state)
    rep.write_not_lossless(prep.paths, prep.state)
    code = 1 if prep.log.section("errors") else 0
    return code, rep.write_run(prep.paths, prep.log, datetime.now(), code, prep.state)


def execute(prep: Prepared, qobuz, *, emit: Emit = no_emit, token: CancelToken | None = None,
            limit: int | None = None, verbose: bool = False) -> tuple[int, Path]:
    """Runs the plan. Returns (exit code, report path); 130 when stopped through the token (or a KeyboardInterrupt).
    State, not_lossless.md and the report are always written, whatever happens."""
    token = token or CancelToken()
    paths, state = prep.paths, prep.state

    def save() -> None:
        library.save_state(paths.state_file, state)

    save()
    if qobuz:
        qobuz.check = token.check  # a stalled Qobuz request still reacts to Stop
    budget = Budget(state, save, prep.settings)
    accounts = account_budgets(state, save, prep.settings)
    fallback = FallbackSource(verbose=verbose, emit=emit, check=token.check,
                              logins={s: (a.browser, a.profile) for s, a in prep.settings.accounts.items()})
    acquirer = Acquirer(qobuz, fallback, budget, Pacer(emit, token), make_ready, emit=emit, accounts=accounts)
    executor = Executor(paths, state, prep.log, acquirer, quality.inspect, emit=emit, token=token, limit=limit)
    code = 0
    try:
        if fill_kbps(state, fallback, emit):
            save()
        executor.run(prep.plan.actions)
    except (Cancelled, KeyboardInterrupt):
        code = 130
    finally:
        if qobuz:
            qobuz.close()
        save()
        rep.write_not_lossless(paths, state)
        if code == 0 and prep.log.section("errors"):
            code = 1
        path = rep.write_run(paths, prep.log, datetime.now(), code, state)
        emit(RunFinished(code, str(path)))
    return code, path
