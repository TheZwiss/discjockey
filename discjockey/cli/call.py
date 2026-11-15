"""The one runner (issue 39, plan v2 §3.1): `run(entry, args, flags)` runs a catalogue entry and answers its envelope.
Kinds R (read) and B (brief save) call the `HubApi` method directly; J (a write job) and RJ (a read that can take
minutes: no locks) create a registry job and start its worker process (`start_job`), and the client that follows it
(`follow.attach`: `--detach`, `--wait`, the default wait) answers. Nothing here computes a fact: it resolves what the person typed
through `HubApi.resolve`, calls the method the entry names and wraps the answer. `run_method` is `call <method>`: it
picks the entry the method's arguments name and runs it through `run`, so `call` is never a way around an entry's
refusals (`needs_yes`, `--dry-run`, the locks)."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from datetime import datetime

from .. import tools
from ..hub import catalog, registry
from ..hub.catalog import Entry
from ..rekordbox.locate import locate
from . import bind, envelope, follow, worker
from .parser import Flags, parameters_of, signature_of

NOT_BUILT = "{command} is not built yet."
START_WAIT_S = 15.0  # how long the client waits for a worker to leave `queued` (with --wait-busy: that much more)
FOLLOW_POLL_S = 0.05
_children: list[subprocess.Popen] = []  # workers this process started and has not seen end (reaped at the next start)
WINDOW_WORDS = {"native_dialog": "it opens a macOS dialog, which only the window can show",
                "closes_window": "it closes the window, which only the window has"}


def command_of(entry: Entry) -> str:
    return " ".join(entry.command) or entry.method


def _stdin_lines() -> list[str]:
    return [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]


def _resolved(api, command: str, arg: catalog.Arg, value: object) -> tuple[object, dict | None]:
    """What `HubApi.resolve` makes of the typed `value`, or the envelope of why not."""
    values = list(value) if isinstance(value, (list, tuple)) else [value]
    if values == ["-"] and arg.many:
        values = _stdin_lines()  # "-" reads the ids from stdin
    answer = api.resolve(arg.resolve, [str(v) for v in values])
    if not answer.get("ok"):
        return None, envelope.from_answer(command, answer)
    resolved = answer["resolved"]
    return (resolved if arg.many else resolved[0]), None


def run(entry: Entry, args: Mapping, flags: Flags, *, api=None, exact: bool = False) -> dict:
    """Runs one entry. `args` are the method's parameters by name as the person gave them (what the command line
    typed; `resolve` turns them into arguments), or, with `exact` (`call`), already the bridge's own arguments."""
    command = command_of(entry)
    if entry.kind in ("W", "dropped"):
        return envelope.usage(command, f"{entry.method} is not a command of the command line.")
    if entry.planned:
        return envelope.usage(command, NOT_BUILT.format(command=command))
    if entry.kind == "J-control":
        return envelope.usage(command, f"{entry.method} only reaches a job of the process that runs it: "
                                       "use `job stop <job>`.")
    if flags.dry_run and not entry.dry_run:
        return envelope.usage(command, f"{command} has no --dry-run: it does not change anything or it cannot be tried first.")
    if entry.needs_yes and not flags.yes and not flags.dry_run:
        return envelope.problem(command, "refused", "needs_yes")
    method = entry.dry_run if flags.dry_run else entry.method
    if method == entry.method and entry.kind not in ("R", "B", "J", "RJ"):
        return envelope.usage(command, NOT_BUILT.format(command=command))
    api = api or bind.default()
    kwargs = dict(args)
    if not exact:
        for name, arg in catalog.effective_params(entry, signature_of(entry.method)).items():
            if arg.resolve and name in kwargs:
                value, failed = _resolved(api, command, arg, kwargs[name])
                if failed is not None:
                    return failed
                kwargs[name] = value
    kwargs.update(entry.fixed)
    if method != entry.method:
        kwargs = {k: v for k, v in kwargs.items() if k in parameters_of(method)}
    if method == entry.method and entry.kind in ("J", "RJ"):
        return start_job(entry, kwargs, command, flags)
    answer = getattr(api, method)(**kwargs)
    return envelope.from_answer(command, answer, as_of=_as_of(api) if entry.kind in ("R", "RJ") else None)


def worker_argv(job_id: str) -> list[str]:
    """The command that starts the worker of `job_id`: the checkout's Python with `-m discjockey`, or, in the built
    app, the app's own program (`sys.executable`; the `-m` form does not exist in a frozen app, and `app_main` sends
    every argument it does not know to the command line)."""
    if tools.is_frozen():
        return [sys.executable, "job", "_worker", job_id]
    return [sys.executable, "-m", "discjockey", "job", "_worker", job_id]


def spawn_worker(files: registry.JobFiles, argv: list[str] | None = None) -> subprocess.Popen:
    """Starts the worker of a created job, detached: a new session (nothing the client's terminal does reaches it),
    stdin and stdout to /dev/null, stderr to the job's `log.txt`. The worker gets the descriptor of the creator's
    `alive` claim, so the job is never without the lock (the registry's handoff), and finds the registry through
    `DISCJOCKEY_SUPPORT`, which the spawner sets to the folder the job lives in (everything else it reads from
    `state.json`). The caller lets go of its own claim afterwards (`files.release_claim()`)."""
    fd = files.claim()
    env = {**os.environ, worker.ALIVE_FD_ENV: str(fd), bind.SUPPORT_ENV: str(files.dir.parent.parent)}
    with open(files.dir / "log.txt", "ab") as log:
        process = subprocess.Popen(argv or worker_argv(files.id), start_new_session=True, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=log, pass_fds=(fd,), env=env,
                                   cwd=None if tools.is_frozen() else str(tools.program_dir()))
    _children[:] = [c for c in _children if c.poll() is None]
    _children.append(process)
    return process


def _reap(process: subprocess.Popen, reader: registry.JobFiles) -> None:
    """A worker whose job has ended is just exiting: wait for it, so nothing of it is left behind. One that still runs
    is left alone."""
    if reader.state().get("status") in ("done", "lost"):
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            pass


def start_job(entry: Entry, kwargs: Mapping, command: str, flags: Flags, *,
              argv: Callable[[str], list[str]] | None = None) -> dict:
    """A write job from the terminal (design §6.3): the roots as this process sees them, the job in the registry
    (`queued`, claimed), the worker started and handed the claim, then the first answer: the job's own envelope when
    it has ended, else `running` (exit 8) with its id (or, with --detach, `ok`). The first stderr line names the job. Killing this process afterwards never touches the worker."""
    here = bind.resolved()
    place = locate()
    roots = {"music": str(here.paths.root) if here.paths is not None else str(here.music_folder) if here.music_folder else None,
             "support": str(here.support), "rekordbox": str(place.db.parent) if place is not None else None,
             "sandbox": None}
    reg = registry.Registry(here.support)
    reg.prune(datetime.now())
    files = reg.create(entry.method, command, dict(kwargs), "terminal", roots)
    files.update(method=entry.method, wait_busy=flags.wait_busy)
    files.flush()
    print(follow.first_line(files.id), file=sys.stderr, flush=True)  # before anything else: a killed call keeps the id
    try:
        process = spawn_worker(files, argv(files.id) if argv else None)
    except OSError as e:
        files.write_result(envelope.problem(command, "failed", "crashed", f"The job could not be started: {e}.",
                                            job=files.id))
        files.update(status="done", ended=datetime.now().astimezone().isoformat(timespec="seconds"))
        files.release_claim()
        return files.result()
    finally:
        files.release_claim()
    reader = reg.get(files.id)
    answer = follow.attach(reader, command, flags)
    _reap(process, reader)
    return answer


def _as_of(api) -> dict | None:
    """How fresh the index and the playlist read are (`HubApi.freshness`, from the stored records), for the envelope of
    a read. A freshness that cannot be had (a damaged library.db) leaves both null: it never fails the answer."""
    fresh = api.freshness()
    return {key: fresh[key] for key in ("scanned_at", "read_at")} if fresh.get("ok") else None


def choose(entries: list[Entry], flags: Flags) -> Entry:
    """The entry of a noun-verb command that runs: the write when there is one (its `--dry-run` runs the entry's
    `dry_run` method), else the read."""
    return next((e for e in entries if e.kind != "R"), entries[0])


def _pick(entries: list[Entry], args: Mapping) -> Entry | None:
    """The entry of a method that the arguments name: every fixed value present and equal; the one with the most fixed
    values, else the first without any (`upgrade` with `mode: discard` is `upgrade discard`, else `upgrade apply`).
    None when every entry fixes a value the arguments leave out or differ in (`never_download` without `never`)."""
    matching = [e for e in entries if e.fixed and all(k in args and args[k] == v for k, v in e.fixed.items())]
    if matching:
        return max(matching, key=lambda e: len(e.fixed))
    return next((e for e in entries if not e.fixed), None)


def run_method(method: str, args: object, flags: Flags, *, password: str | None = None, api=None) -> dict:
    """`call <method>`: the bridge's method name and arguments (`docs/hub-bridge-contract.md`), run through the entry
    they name. `password` is what came on stdin with `--password-stdin`; it goes to the method's secret parameter."""
    entries = catalog.by_method(method)
    if not entries:
        return envelope.usage("call", f"There is no method called {method}.")
    if method in catalog.WINDOW_ONLY:
        return envelope.usage("call", f"{method} is not offered: {WINDOW_WORDS[catalog.WINDOW_ONLY[method]]}.")
    if method in catalog.DROPPED:
        return envelope.usage("call", f"{method} is not offered: the command line does not have it.")
    if not isinstance(args, Mapping):
        return envelope.usage("call", "--args must be a JSON object of the method's arguments.")
    secret_names = {name for e in entries for name, a in e.params.items() if a.secret}
    if given := sorted(secret_names & set(args)):
        return envelope.problem("call", "refused", "refused",
                                f"{given[0]} is never taken from --args. Send it on stdin with --password-stdin.")
    if password is not None and not secret_names:
        return envelope.usage("call", f"{method} takes no password.")
    secrets = {name: password for name in secret_names} if password is not None else {}
    entry = _pick(entries, args)
    if entry is None:
        fixed = sorted({k for e in entries for k in e.fixed})
        return envelope.usage("call", f"{method} needs {', '.join(fixed)} with one of the values it takes.")
    command = command_of(entry)
    if entry.planned:
        return envelope.usage(command, NOT_BUILT.format(command=command))
    parameters = parameters_of(method)
    if unknown := sorted(set(args) - set(parameters)):
        return envelope.usage(command, f"{method} has no argument {unknown[0]}: its arguments are "
                                       f"{', '.join(parameters) or 'none'}.")
    needed = [n for n, p in parameters.items() if p.default is p.empty and n not in entry.fixed
              and n not in args and n not in secrets]
    if needed:
        return envelope.usage(command, f"{method} needs {', '.join(needed)}.")
    kwargs = {**args, **secrets}
    return run(entry, kwargs, flags, api=api, exact=True)

