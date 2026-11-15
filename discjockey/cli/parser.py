"""The parser, generated from the catalogue (issue 39, design §2.2): one command per built entry of
`discjockey.hub.catalog.ENTRIES`, its flags made from the `HubApi` method's signature (`catalog.effective_params`),
plus `call`. Global flags stand anywhere on the line and are read once (`split_globals`); a flag a command does not
take is a usage error, never ignored. `route` decides whether a line belongs to the new commands or to the old ones in
`legacy.py`, which keep their words until their replacements are built.

Not offered in phase 1: `--sandbox`, `--if-rev`, `--if-version`; `--jsonl`, `--wait`, `--detach` and `--wait-busy` are
read but only job commands act on them."""
from __future__ import annotations

import argparse
import inspect
from dataclasses import dataclass, field

from ..hub import catalog
from ..hub.api import CliApi
from ..hub.catalog import Entry

LEGACY_WORDS = frozenset(("setup", "update", "upgrades", "upgrade", "batch", "convert", "rename", "rekordbox",
                          "settings", "hub"))
GLOBAL_BOOL = {"--json": "json", "--jsonl": "jsonl", "--detach": "detach", "--verbose": "verbose",
               "--no-color": "no_color"}
GLOBAL_VALUE = {"--wait": "wait", "--wait-busy": "wait_busy"}
DEFAULT_LIMIT = 200
CALL = ("call",)


class UsageError(Exception):
    """The line is not right (`bad_args`, exit 2): `reason` is `usage` or `conflicting_flags`."""

    def __init__(self, message: str, reason: str = "usage"):
        super().__init__(message)
        self.message = message
        self.reason = reason


@dataclass
class Flags:
    """The global flags, and the per-command ones the runner reads (`--dry-run`, `--yes`, `--limit`, `--offset`)."""
    json: bool = False
    jsonl: bool = False
    wait: float | None = None
    detach: bool = False
    wait_busy: float | None = None
    verbose: bool = False
    no_color: bool = False
    dry_run: bool = False
    yes: bool = False
    limit: int = DEFAULT_LIMIT
    offset: int = 0


@dataclass
class Parsed:
    """One line understood. `entries` are the built entries of the command (empty for `call`); `args` the values the
    person gave, by the method's parameter names (for `call`: `method`, `args_text`, `password_stdin`)."""
    command: tuple[str, ...]
    entries: list[Entry]
    args: dict
    flags: Flags
    words: list[str] = field(default_factory=list)


def split_globals(argv: list[str]) -> tuple[Flags, list[str]]:
    """The global flags wherever they stand, and the line without them."""
    flags, rest = Flags(), []
    i = 0
    while i < len(argv):
        token = argv[i]
        name, eq, inline = token.partition("=")
        if token in GLOBAL_BOOL:
            setattr(flags, GLOBAL_BOOL[token], True)
        elif name in GLOBAL_VALUE:
            if eq:
                text = inline
            elif i + 1 < len(argv):
                i += 1
                text = argv[i]
            else:
                raise UsageError(f"{name} needs a number of seconds.")
            try:
                seconds = float(text)
            except ValueError:
                raise UsageError(f"{name} needs a number of seconds, not {text!r}.") from None
            if seconds < 0:
                raise UsageError(f"{name} cannot be negative.")
            setattr(flags, GLOBAL_VALUE[name], seconds)
        else:
            rest.append(token)
        i += 1
    if flags.json and flags.jsonl:
        raise UsageError("--json and --jsonl say opposite things: choose one.", "conflicting_flags")
    if flags.detach and flags.wait is not None:
        raise UsageError("--detach and --wait say opposite things: choose one.", "conflicting_flags")
    return flags, rest


def built() -> list[Entry]:
    """The entries whose command is built: the parser and `help --json` offer exactly these."""
    return [e for e in catalog.ENTRIES if e.command and not e.planned and e.kind not in ("W", "dropped")]


def commands() -> dict[tuple[str, ...], list[Entry]]:
    out: dict[tuple[str, ...], list[Entry]] = {}
    for e in built():
        out.setdefault(e.command, []).append(e)
    return out


def words_of(argv: list[str]) -> tuple[list[str], bool]:
    """The command words at the front of `argv` (global flags skipped) and whether a flag came before any word."""
    words, i = [], 0
    while i < len(argv):
        token = argv[i]
        name = token.partition("=")[0]
        if token in GLOBAL_BOOL:
            i += 1
        elif name in GLOBAL_VALUE:
            i += 1 if "=" in token else 2
        elif token.startswith("-"):
            return words, not words
        else:
            words.append(token)
            i += 1
    return words, False


def route(argv: list[str]) -> str:
    """`legacy` for a line the old parser still owns (a bare sync, a leading sync flag, a word whose replacement is not
    built), else `new`. The line goes to the old parser unchanged."""
    words, flag_first = words_of(argv)
    if not words or flag_first:
        return "legacy"
    if tuple(words[:1]) == CALL or any(cmd[:2] == tuple(words[:2]) for cmd in commands() if len(words) > 1):
        return "new"
    return "legacy" if words[0] in LEGACY_WORDS else "new"


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise UsageError(message)


def signature_of(method: str) -> inspect.Signature:
    return inspect.signature(getattr(CliApi, method).__wrapped__)


def parameters_of(method: str) -> dict[str, inspect.Parameter]:
    """The method's parameters by name, without `self`."""
    return {n: p for n, p in signature_of(method).parameters.items() if n != "self"}


def _option_type(arg: catalog.Arg):
    return {"int": int, "float": float}.get(arg.type, str)


def _add_arguments(leaf: argparse.ArgumentParser, entries: list[Entry]) -> None:
    primary = next((e for e in entries if e.kind != "R"), entries[0])
    signature = signature_of(primary.method)
    taken = set()
    for name, arg in catalog.effective_params(primary, signature).items():
        optional = signature.parameters[name].default is not inspect.Parameter.empty
        if arg.positional:
            leaf.add_argument(name, nargs="*" if arg.many else "?" if optional else None, metavar=name.upper(),
                              default=argparse.SUPPRESS)
        elif arg.flag:
            taken.add(arg.flag)
            if arg.type == "bool":
                leaf.add_argument(arg.flag, dest=name, action="store_true", default=argparse.SUPPRESS)
            else:
                leaf.add_argument(arg.flag, dest=name, type=_option_type(arg), default=argparse.SUPPRESS,
                                  action="append" if arg.many else "store")
    if any(e.dry_run for e in entries):
        leaf.add_argument("--dry-run", dest="_dry_run", action="store_true", default=argparse.SUPPRESS)
    if any(e.needs_yes for e in entries):
        leaf.add_argument("--yes", dest="_yes", action="store_true", default=argparse.SUPPRESS)
    if all(e.kind == "R" for e in entries):
        for word in ("limit", "offset"):
            if f"--{word}" not in taken:
                leaf.add_argument(f"--{word}", dest=f"_{word}", type=int, default=argparse.SUPPRESS)


def build() -> _Parser:
    """The parser of every built command and of `call`."""
    root = _Parser(prog="discjockey", add_help=False, allow_abbrev=False)
    nouns = root.add_subparsers(dest="_noun", parser_class=_Parser, required=True)
    nodes: dict[tuple[str, ...], argparse.ArgumentParser] = {}
    levels: dict[tuple[str, ...], argparse._SubParsersAction] = {(): nouns}
    for cmd, entries in commands().items():
        for depth in range(1, len(cmd)):
            path = cmd[:depth]
            if path not in nodes:
                nodes[path] = levels[path[:-1]].add_parser(path[-1], add_help=False, allow_abbrev=False)
                levels[path] = nodes[path].add_subparsers(dest=f"_word{depth}", parser_class=_Parser, required=True)
        leaf = levels[cmd[:-1]].add_parser(cmd[-1], add_help=False, allow_abbrev=False)
        _add_arguments(leaf, entries)
        leaf.set_defaults(_command=cmd)
    call = nouns.add_parser(CALL[0], add_help=False, allow_abbrev=False)
    call.add_argument("method")
    call.add_argument("--args", dest="args_text", default=None, metavar="JSON|-")
    call.add_argument("--password-stdin", dest="password_stdin", action="store_true")
    call.add_argument("--dry-run", dest="_dry_run", action="store_true", default=argparse.SUPPRESS)
    call.add_argument("--yes", dest="_yes", action="store_true", default=argparse.SUPPRESS)
    call.set_defaults(_command=CALL)
    return root


def _check_words(words: list[str]) -> None:
    """A friendly usage error for a word that is not a command (argparse's own would list its internals)."""
    known = commands()
    nouns = sorted({c[0] for c in known} | {CALL[0]})
    if not words:
        raise UsageError("Say what to do: " + ", ".join(nouns) + ".")
    if words[0] not in nouns:
        raise UsageError(f"{words[0]} is not a command. The commands so far: {', '.join(nouns)}.")
    verbs = sorted({" ".join(c[1:2]) for c in known if c[0] == words[0]} - {""})
    if words[0] != CALL[0] and (len(words) < 2 or words[1] not in verbs):
        raise UsageError(f"Say what to do with {words[0]}: {', '.join(verbs)}.")


def parse(argv: list[str]) -> Parsed:
    """Reads one line of the new commands. Raises `UsageError`."""
    flags, rest = split_globals(argv)
    words, _ = words_of(rest)
    _check_words(words)
    ns = vars(build().parse_args(rest))
    command = tuple(ns.pop("_command"))
    for key in [k for k in ns if k.startswith(("_noun", "_word"))]:
        del ns[key]
    for key, attr in (("_dry_run", "dry_run"), ("_yes", "yes")):
        if ns.pop(key, False):
            setattr(flags, attr, True)
    for key in ("limit", "offset"):
        if (value := ns.pop(f"_{key}", None)) is not None:
            if value < 0:
                raise UsageError(f"--{key} cannot be negative.")
            setattr(flags, key, value)
    if command == CALL:
        return Parsed(command, [], ns, flags, words)
    entries = commands()[command]
    primary = next((e for e in entries if e.kind != "R"), entries[0])
    signature = signature_of(primary.method)
    for name, arg in catalog.effective_params(primary, signature).items():
        if arg.positional and arg.many:
            if name in ns and not ns[name]:
                del ns[name]
        if arg.positional and name not in ns and signature.parameters[name].default is inspect.Parameter.empty:
            raise UsageError(f"{name.replace('_', ' ')} is missing.")
    return Parsed(command, entries, ns, flags, words)
