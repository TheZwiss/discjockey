"""The one runner (issue 39, plan v2 §3.1): `run(entry, args, flags)` runs a catalogue entry and answers its envelope.
Kinds R (read) and B (brief save) call the `HubApi` method directly; J and RJ come with the job client (groups 1.5
and 1.6) and answer "not built yet" until then. Nothing here computes a fact: it resolves what the person typed
through `HubApi.resolve`, calls the method the entry names and wraps the answer. `run_method` is `call <method>`: it
picks the entry the method's arguments name and runs it through `run`, so `call` is never a way around an entry's
refusals (`needs_yes`, `--dry-run`, the locks)."""
from __future__ import annotations

import sys
from collections.abc import Mapping

from ..hub import catalog
from ..hub.catalog import Entry
from . import bind, envelope
from .parser import Flags, parameters_of, signature_of

NOT_BUILT = "{command} is not built yet."
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
    if flags.dry_run and not entry.dry_run:
        return envelope.usage(command, f"{command} has no --dry-run: it does not change anything or it cannot be tried first.")
    if entry.needs_yes and not flags.yes and not flags.dry_run:
        return envelope.problem(command, "refused", "needs_yes")
    method = entry.dry_run if flags.dry_run else entry.method
    if method == entry.method and entry.kind not in ("R", "B"):
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
    answer = getattr(api, method)(**kwargs)
    return envelope.from_answer(command, answer, as_of=_as_of(api) if entry.kind in ("R", "RJ") else None)


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

