"""The one runner (issue 39, plan v2 §3.1): `run(entry, args, flags)` runs a catalogue entry and answers its envelope.
Kinds R (read) and B (brief save) call the `HubApi` method directly; J (a write job) and RJ (a read that can take
minutes: no locks) create a registry job and start its worker process (`start_job`), and the client that follows it
(`follow.attach`: `--detach`, `--wait`, the default wait) answers. Nothing here computes a fact: it resolves what the person typed
through `HubApi.resolve`, calls the method the entry names and wraps the answer. `run_method` is `call <method>`: it
picks the entry the method's arguments name and runs it through `run`, so `call` is never a way around an entry's
refusals (`needs_yes`, `--dry-run`, the locks)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from datetime import datetime

from .. import tools
from ..hub import catalog, ids, registry, select
from ..hub.catalog import Entry
from ..rekordbox import lock as rb_lock
from ..rekordbox.locate import locate
from . import bind, envelope, follow, worker
from .parser import (BATCH_SELECTION_WORDS, DRY_RUN_ONLY_WORDS, SELECTION_WORDS, SWITCH_ALONE_WORDS, SYNC_DRY_RUN_WORDS, Flags,
                     UsageError, parameters_of, selects, signature_of)

NOT_BUILT = "{command} is not built yet."
JOB_FLAGS_WORDS = "{command} answers at once: {given} is for a command that runs as a job."
START_WAIT_S = 15.0  # how long the client waits for a worker to leave `queued` (with --wait-busy: that much more)
FOLLOW_POLL_S = 0.05
_children: list[subprocess.Popen] = []  # workers this process started and has not seen end (reaped at the next start)
WINDOW_WORDS = {"native_dialog": "it opens a macOS dialog, which only the window can show",
                "closes_window": "it closes the window, which only the window has",
                "binds_folder": "it connects the music folder and starts watching it, which only the window does (`setup status` says how the folder stands)"}


def command_of(entry: Entry) -> str:
    return " ".join(entry.command) or entry.method


class StdinProblem(Exception):
    """What came on stdin is not a list of ids."""


def _stdin_lines() -> list[str]:
    """The ids `-` stands for: one per line, or one JSON array of texts (`… list --json | jq '[.data.rows[].track_id]'`)."""
    text = sys.stdin.read().strip()
    if text.startswith("["):
        try:
            values = json.loads(text)
        except ValueError:
            raise StdinProblem("Standard input starts like a JSON list but is not one.") from None
        if not isinstance(values, list) or not all(isinstance(v, str) and v.strip() for v in values):
            raise StdinProblem("A JSON list on standard input holds ids, as texts.")
        found = [v.strip() for v in values]
    else:
        found = [line.strip() for line in text.splitlines() if line.strip()]
    if not found:
        raise StdinProblem("Nothing came on standard input: `-` reads the ids from it.")
    return found


def _resolved(api, command: str, arg: catalog.Arg, value: object) -> tuple[object, dict | None]:
    """What `HubApi.resolve` makes of the typed `value`, or the envelope of why not."""
    values = list(value) if isinstance(value, (list, tuple)) else [value]
    if values == ["-"] and arg.many:
        try:
            values = _stdin_lines()  # "-" reads the ids from stdin
        except StdinProblem as e:
            return None, envelope.usage(command, str(e))
    answer = api.resolve(arg.resolve, [str(v) for v in values])
    if not answer.get("ok"):
        return None, envelope.from_answer(command, answer)
    resolved = answer["resolved"]
    return (resolved if arg.many else resolved[0]), None


def _arguments(entry: Entry, args: Mapping, command: str, api, exact: bool,
               chosen: tuple[str, ...] = ()) -> tuple[dict, dict | None]:
    """The method's arguments from what the person typed (resolved through `HubApi.resolve`, the entry's `fixed` values
    added), or the envelope of why not. A resolved value that is a mapping spreads: each other argument of the entry
    that is derived (no word of its own) with the same `resolve` kind takes the key of its name, the argument itself
    the key of its own name. `chosen` names the arguments the engine already answered (the songs a selection
    picked): they are ids and are not resolved again."""
    kwargs = dict(args)
    if not exact:
        params = catalog.effective_params(entry, signature_of(entry.method))
        spread_done: set[str] = set()  # made from another argument's value: not resolved again
        for name, arg in params.items():
            if arg.resolve and name in kwargs and name not in chosen and name not in spread_done:
                value, failed = _resolved(api, command, arg, kwargs[name])
                if failed is not None:
                    return {}, failed
                spread = [other for other, o in params.items() if other != name and o.resolve == arg.resolve
                          and o.flag is None and not o.positional]
                if isinstance(value, Mapping) and spread:  # one typed word several arguments are made of (`--in`: `view`, `key`)
                    kwargs.update({other: value[other] for other in spread})
                    spread_done.update(spread)
                    value = value[name]
                kwargs[name] = value
    kwargs.update(entry.fixed)
    return kwargs, None


NOTHING_LEFT = {"total": 0, "done": 0, "skipped": 0, "failed": 0, "results": []}  # the data of a run of no songs


def _listing(entry: Entry, command: str, flags: Flags) -> tuple[dict | None, dict | None]:
    """The listing `--all` or `--rows` names (`select.parse`'s words), or the envelope of why the flags are wrong."""
    if flags.all:
        verb = catalog.ALL_OF.get(command)
        if verb is None:
            return None, envelope.usage(command, f"{command} has no --all. Name the songs, or use --rows.")
        takes = catalog.ALL_NARROWS.get(command, ())
        if (clash := [w for w, field, v in (("--in", "where", flags.where), ("--todo", "todo", flags.todo),
                                            ("--search", "search", flags.search), ("--quality", "quality", flags.quality))
                      if v and field not in takes]):
            return None, envelope.usage(command, f"{clash[0]} narrows --rows; --all is the verb's own list.",
                                        "conflicting_flags")
        return {"verb_all": verb, **({"in": flags.where} if flags.where else {})}, None
    if flags.todo and flags.where:
        return None, envelope.usage(command, "--in and --todo name two different lists: choose one.", "conflicting_flags")
    listing = {"in": flags.where, "search": flags.search, "quality": flags.quality, "group": flags.todo}
    return {k: v for k, v in listing.items() if v is not None}, None


BAD_IN_WITH_CDJ = ("--all --todo cdj is the whole group of files CDJs won't play well; --in can't narrow it.")
BAD_ALL_TODO = "--all takes --todo cdj, the group of files CDJs won't play well; no other group has a Convert all."


def _all_scope(args: Mapping, flags: Flags, command: str, api) -> tuple[dict, dict | None]:
    """`aiff convert --all [--in C | --todo cdj]` (design §7.3): the scope `make_aiff` takes, `lossless` in a collection
    (`--in`, resolved by `HubApi.resolve`; none is all of them) or the CDJ group. Also the dry run of `aiff rename --all
    [--in C]`: its plan is the collection's, so it says what waits too (the run selects the same songs through
    `select_listing`). Returns the arguments with `scope`, or the envelope of why not."""
    if clash := [w for w, v in (("--search", flags.search), ("--quality", flags.quality),
                                ("--todo", flags.todo if command != "aiff convert" else None)) if v]:
        return {}, envelope.usage(command, f"{clash[0]} narrows --rows; --all is the verb's own list.", "conflicting_flags")
    if flags.todo is not None:
        if flags.where:
            return {}, envelope.usage(command, BAD_IN_WITH_CDJ, "conflicting_flags")
        if flags.todo != "cdj":
            return {}, envelope.usage(command, BAD_ALL_TODO)
        return {**args, "scope": {"kind": "cdj"}}, None
    answer = api.resolve("collection", [flags.where or "all"])
    if not answer.get("ok"):
        return {}, envelope.from_answer(command, answer)
    return {**args, "scope": {"kind": "lossless", **answer["resolved"][0]}}, None


def _selection(entry: Entry, args: Mapping, flags: Flags, command: str, api) -> tuple[dict, dict | None]:
    """The songs of a bulk write (design §7.3): exactly one of the ids typed (or `-`), `--all` and `--rows`, with
    `--rows` narrowed by `--in` / `--todo` and `--search` / `--quality`. `--all` and `--rows` are answered by
    `HubApi.select_listing`, the engine's one rule for which rows a listing shows; the ids go to the method as they
    are. Returns the arguments with `track_ids` filled, or the envelope of why not."""
    typed = bool(args.get("track_ids"))
    batchable = "batch_id" in parameters_of(entry.method)  # `check done --batch aiff:n`: a batch names its own songs
    batch = args.get("batch_id") is not None
    words = BATCH_SELECTION_WORDS if batchable else SELECTION_WORDS
    forms = [name for name, on in (("the song ids", typed), ("--all", flags.all), ("--rows", flags.rows),
                                   ("--batch", batch)) if on]
    narrowing = any((flags.where, flags.todo, flags.search, flags.quality))
    if len(forms) > 1:
        return {}, envelope.usage(command, f"{' and '.join(forms)} say different things: choose one. {words}",
                                  "conflicting_flags")
    if not forms:
        return {}, envelope.usage(command, words)
    if narrowing and not flags.rows and not (flags.all and command in catalog.ALL_NARROWS):
        return {}, envelope.usage(command, "--in, --todo, --search and --quality narrow --rows; they mean nothing "
                                           "without it.", "conflicting_flags")
    if batch:
        return {**args, "track_ids": []}, None
    if typed:
        return dict(args), None
    if flags.all and ((command in catalog.ALL_METHOD and command not in catalog.ALL_OF)  # a scope, not a list of songs
                      or (command == "aiff rename" and flags.dry_run)):
        return _all_scope(args, flags, command, api)
    listing, failed = _listing(entry, command, flags)
    if failed is not None:
        return {}, failed
    if flags.all and command == "aiff rename" and args.get("plan_id"):
        listing = {**listing, "plan": args["plan_id"]}  # the run answers for the plan's songs too (V1.10's plan rule)
    answer = api.select_listing(listing)
    if not answer.get("ok"):
        return {}, envelope.from_answer(command, answer)
    if not answer["ids"] and command in catalog.AIFF:  # no song to convert or rename: done, the dry run says so too
        return {}, envelope.envelope(command, "ok", message=answer.get("message") or select.NO_ROWS, data=NOTHING_LEFT)
    if not answer["ids"] and command in catalog.MISSING:  # no song waits for the action: done, the dry run says so too
        message = answer.get("message") or select.NO_ROWS
        nothing = {"action": entry.fixed["action"], "items": [], "n": 0, "skipped": 0, "words": message,
                   "button": None, "confirm": None}  # a dry run keeps its own shape
        return {}, envelope.envelope(command, "ok", message=message, data=nothing if flags.dry_run else NOTHING_LEFT)
    if not answer["ids"] and answer.get("message") and not flags.dry_run:  # a verb's "all" with nothing left is done (R29)
        return {}, envelope.envelope(command, "ok", message=answer["message"], data=NOTHING_LEFT)
    return {**args, "track_ids": answer["ids"]}, None


def _plan_entry(command: str, kwargs: Mapping) -> tuple[Entry, dict]:
    """The `--dry-run` of an AIFF command: the command's `aiff_plan` entry and its arguments, the scope the write would
    run (`make_aiff`'s own, or the songs of `convert` / `rename`) and the entry's `only` (Rename's answer alone)."""
    entry = catalog.entry_of("aiff_plan", command)
    scope = kwargs.get("scope") or {"kind": "tracks", "tracks": kwargs.get("track_ids") or []}
    return entry, {"scope": scope, **entry.fixed}


def _dry_run(entry: Entry, command: str, kwargs: Mapping, api) -> dict:
    """The entry's `--dry-run` (design §7.1): its `dry_run` method on the last scan, answering `as_of.scanned_at` and,
    when a watched folder changed after that scan, `next: library scan`. An answer that lists its items (each with a
    `key`) is stored as a plan (`plan_store`: the plan file a dry run writes) and its id is `data.plan_id`, which
    `--plan` runs (a switch's entry saves it under the line with its flag: `sync run --auto-upgrade-only`, which an
    expired plan says to repeat; the whole sync's plan is `sync_preview`'s own). A read that stands in for a write nobody has built (`catalog.stands_in`) is its own dry run: it answers
    as a read does (`as_of`, no plan; the scan hint only where the read plans on the last scan's files,
    `catalog.STAND_INS_ON_SCAN`: a limit's what-if or a folder check does not)."""
    method = entry.dry_run or entry.method
    answer = getattr(api, method)(**{k: v for k, v in kwargs.items() if k in parameters_of(method)})
    env = envelope.from_answer(command, answer, as_of=envelope.as_of(api))
    if env["outcome"] == "ok":
        if not catalog.stands_in(entry):
            line = f"{command} {flag}" if (flag := catalog.switch_of(entry)) else command
            if (plan_id := api.save_plan(command, answer, line)) is not None:
                env["data"]["plan_id"] = plan_id
            words = api.result_words(method, answer)  # a dry run that has something to say beside its facts
            if words.get("ok") and words.get("message"):
                env["message"] = words["message"]
        if not catalog.stands_in(entry) or method in catalog.STAND_INS_ON_SCAN:
            env["next"] += [n for n in api.scan_next() if n not in env["next"]]
    return envelope.noted(env, method, dry=True)


def _needs_yes(entry: Entry, command: str, kwargs: Mapping | None = None, api=None) -> dict:
    """`refused`, `needs_yes`: the window asks first and this command never asks. `message` is the window's question
    (`catalog.CONFIRM`), `data` what the dry run shows (as `--dry-run` answers it, its plan id too) for a command that
    has one, so the person sees what `--yes` would do. Without `api` (a command with no dry run) nothing is looked at."""
    dry = _dry_run(entry, command, kwargs, api) if entry.dry_run and api is not None else None
    shown = dry is not None and dry["outcome"] == "ok"
    return envelope.problem(command, "refused", "needs_yes", catalog.confirm_words(entry),
                            data=dry["data"] if shown else None, as_of=dry["as_of"] if shown else None)


def job_flags(flags: Flags, allowed: tuple[str, ...] = ()) -> list[str]:
    """The job flags (`--detach`, `--wait`, `--wait-busy`, `--jsonl`) the line carries, except the ones in `allowed`."""
    given = [word for word, on in (("--detach", flags.detach), ("--wait", flags.wait is not None),
                                   ("--wait-busy", flags.wait_busy is not None), ("--jsonl", flags.jsonl)) if on]
    return [word for word in given if word not in allowed]


def refuse_job_flags(flags: Flags, command: str, allowed: tuple[str, ...] = ()) -> dict | None:
    """The usage error (`bad_args`, exit 2) of a command that answers at once and was given a job flag: a flag a command
    does not take is never ignored (design §2.2). None when the line carries none."""
    given = job_flags(flags, allowed)
    if not given:
        return None
    return envelope.usage(command, JOB_FLAGS_WORDS.format(command=command, given=" and ".join(given)))


def run(entry: Entry, args: Mapping, flags: Flags, *, api=None, exact: bool = False) -> dict:
    """Runs one entry. `args` are the method's parameters by name as the person gave them (what the command line
    typed; `resolve` turns them into arguments), or, with `exact` (`call`), already the bridge's own arguments."""
    command = command_of(entry)
    if entry.kind in ("W", "dropped"):
        return envelope.usage(command, f"{entry.method} is not a command of the command line.")
    if entry.planned:
        return envelope.usage(command, NOT_BUILT.format(command=command))
    if entry.kind == "J-control":
        return envelope.usage(command, f"{entry.method} is the window's Stop safely: use `job stop <job>`.")
    if flags.dry_run and not entry.dry_run and not catalog.stands_in(entry):
        return envelope.usage(command, f"{command} has no --dry-run: it does not change anything or it cannot be tried first.")
    if not flags.dry_run and entry.kind not in ("R", "B", "J", "RJ"):
        return envelope.usage(command, NOT_BUILT.format(command=command))
    if entry.needs_yes and not flags.yes and not flags.dry_run and not entry.dry_run:
        return _needs_yes(entry, command)  # nothing to show: refused before anything is looked up
    api = api or bind.default()
    chosen: tuple[str, ...] = ()
    if not exact and selects(entry):
        args, failed = _selection(entry, args, flags, command, api)
        if failed is not None:
            return failed
        chosen = (("track_ids",) if flags.all or flags.rows or args.get("batch_id") is not None else ()
                  ) + (("scope",) if "scope" in args else ())
    elif any((flags.all, flags.rows, flags.where, flags.todo, flags.search, flags.quality)):
        return envelope.usage(command, f"{command} takes no selection words (--all, --rows, --in, --todo, --search, "
                                       "--quality).")
    kwargs, failed = _arguments(entry, args, command, api, exact, chosen)
    if failed is not None:
        return failed
    if flags.all and not exact and command in catalog.ALL_METHOD:  # the verb's own `--all` (the window's button)
        if kwargs.get("mode") not in (None, "same_track"):
            return envelope.usage(command, select.ALL_IS_SAME_TRACK, "conflicting_flags")
        if not flags.dry_run:
            entry = catalog.entry_of(catalog.ALL_METHOD[command], command)
            kwargs = {k: v for k, v in kwargs.items() if k in parameters_of(entry.method)}
    if flags.dry_run:
        if entry.dry_run == "aiff_plan" and entry.method != "aiff_plan":  # Convert, Rename, Make all: the one `AiffPlan`
            entry, kwargs = _plan_entry(command, kwargs)
        if entry.dry_run == entry.method and entry.kind in ("J", "RJ"):  # the read is the job (`aiff_plan`): a worker runs it
            return start_job(entry, kwargs, command, flags)
        return refuse_job_flags(flags, command) or _dry_run(entry, command, kwargs, api)  # answers at once
    if entry.needs_yes and not flags.yes:
        return _needs_yes(entry, command, kwargs, api)
    if entry.kind in ("J", "RJ"):
        return start_job(entry, kwargs, command, flags)
    if (refused := refuse_job_flags(flags, command)) is not None:  # an R or B method answers at once
        return refused
    answer = getattr(api, entry.method)(**kwargs)
    env = envelope.noted(envelope.from_answer(command, answer, as_of=envelope.as_of(api) if entry.kind in ("R", "RJ") else None),
                         entry.method)
    return paged(entry, env, flags) if flags.json and not exact else env


def paged(entry: Entry, env: dict, flags: Flags) -> dict:
    """`env` with the list `entry.pages` names cut to `--offset` / `--limit` (0 = all) and the envelope's `page` saying
    which slice it is (design §4.2): `total` is the whole list's length, `next_offset` the offset of the next page or
    None on the last. An entry without `pages`, or a problem, is returned as it is (`page` stays null)."""
    if not entry.pages or env["outcome"] != "ok" or not isinstance(env["data"], dict):
        return env
    whole = env["data"][entry.pages]
    end = len(whole) if flags.limit == 0 else flags.offset + flags.limit
    rows = whole[flags.offset:end]
    page = {"list": entry.pages, "offset": flags.offset, "limit": flags.limit, "total": len(whole),
            "next_offset": flags.offset + len(rows) if flags.offset + len(rows) < len(whole) else None}
    return {**env, "data": {**env["data"], entry.pages: rows}, "page": page}


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
    if entry.kind == "J":  # a write: its lock file exists before it starts, so a reader of rekordbox holds something
        rb_lock.ensure(here.support)
    place = locate()
    roots = {"music": str(here.paths.root) if here.paths is not None else str(here.music_folder) if here.music_folder else None,
             "support": str(here.support), "rekordbox": str(place.db.parent) if place is not None else None,
             "rekordbox_share": str(place.share) if place is not None else None, "sandbox": None}
    reg = registry.Registry(here.support)
    reg.prune(datetime.now())
    files = reg.create(entry.method, command, dict(kwargs), "terminal", roots)
    files.update(method=entry.method, wait_busy=flags.wait_busy, library_lock="library" in entry.locks)
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


def choose(entries: list[Entry], flags: Flags, args: Mapping | None = None) -> Entry:
    """The entry of a noun-verb command that runs: the write when there is one (its `--dry-run` runs the entry's
    `dry_run` method), else the read. A command that dispatches by id kind (`catalog.BY_ID_KIND`: `batch undo`) runs the
    entry of the typed id's kind. A command with a switch (`catalog.SWITCHES`) runs the switch's entry with its flag, else
    the command's other write. Raises `UsageError`."""
    command = " ".join(entries[0].command)
    if command in catalog.SWITCHES:
        return _by_switch(entries, command, flags, args or {})
    if command in catalog.BY_ID_KIND and args:
        return _by_id_kind(entries, command, args, flags)
    return catalog.primary(entries)


def _by_switch(entries: list[Entry], command: str, flags: Flags, args: Mapping) -> Entry:
    """The entry of a command with a switch (`sync run`): with the switch its own entry, which takes neither action ids nor
    `--how-many` (a flag is never ignored, design §2.2); without it the whole run, whose `--dry-run` is `sync plan`'s answer
    and so takes none of the words that choose what to run."""
    switch_method = catalog.SWITCHES[command][1]
    if flags.auto_upgrade_only:
        if args.get("selected") or args.get("how_many") is not None:
            raise UsageError(SWITCH_ALONE_WORDS, "conflicting_flags")
        return next(e for e in entries if e.method == switch_method)
    if flags.dry_run and (args.get("selected") or args.get("plan_id") is not None or args.get("how_many") is not None):
        raise UsageError(SYNC_DRY_RUN_WORDS, "conflicting_flags")
    return catalog.primary([e for e in entries if e.method != switch_method])


def _by_id_kind(entries: list[Entry], command: str, args: Mapping, flags: Flags) -> Entry:
    """The entry of `command` whose positional resolves the kind of the id typed (the catalogue's rows, built and planned).
    A kind whose write is not built (`batch undo moves:<n>`) runs its stand-in read with `--dry-run` and is a usage
    error without it; a write that is built is returned itself."""
    name = catalog.BY_ID_KIND[command][0]
    try:
        kind = ids.parse(str(args[name]), ids.BATCH_KINDS).kind
    except ids.BadId as e:  # the same words `resolve` gives a bad batch id
        raise UsageError(e.message, e.reason) from None
    rows = [e for e in catalog.ENTRIES if e.command == entries[0].command and name in e.params
            and e.params[name].resolve == kind]
    write = catalog.primary(rows) if rows else catalog.primary(entries)
    if not write.planned:
        return write
    if not flags.dry_run:
        raise UsageError(DRY_RUN_ONLY_WORDS.format(command=f"{command} {ids.FORMS[kind].replace(':N', ':<n>')}"))
    return next(e for e in rows if catalog.stands_in(e))


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

