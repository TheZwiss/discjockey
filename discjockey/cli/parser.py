"""The parser, generated from the catalogue (issue 39, design §2.2): one command per built entry of
`discjockey.hub.catalog.ENTRIES`, its flags made from the `HubApi` method's signature (`catalog.effective_params`),
plus `call`. Global flags stand anywhere on the line and are read once (`split_globals`); a flag a command does not
take is a usage error, never ignored. `route` decides whether a line belongs to the new commands or to the old ones in
`legacy.py`, which keep their words until their replacements are built. The command line's own words (`help`, `where`,
`app open`, `call`) are parsed here too but run no entry.

Not offered in phase 1: `--sandbox`, `--if-rev`, `--if-version`; `--jsonl`, `--wait`, `--detach` and `--wait-busy` are
read but only job commands act on them."""
from __future__ import annotations

import argparse
import inspect
from collections.abc import Collection
from dataclasses import dataclass, field

from ..hub import catalog
from ..hub.api import CliApi
from ..hub.catalog import Entry

LEGACY_WORDS = frozenset(("setup", "update", "upgrades", "upgrade", "batch", "convert", "rename", "rekordbox",
                          "settings"))
GLOBAL_BOOL = {"--json": "json", "--jsonl": "jsonl", "--detach": "detach", "--verbose": "verbose",
               "--no-color": "no_color"}
GLOBAL_VALUE = {"--wait": "wait", "--wait-busy": "wait_busy"}
DEFAULT_LIMIT = 200
CALL = ("call",)
HELP, WHERE, APP_OPEN = ("help",), ("where",), ("app", "open")
# The command line's own words (`catalog.HOUSEKEEPING`): they run no catalogue entry (`housekeeping.py`; the `job`
# words are the job client's, `follow.py`).
JOB_LIST, JOB_SHOW, JOB_FOLLOW, JOB_WAIT, JOB_STOP = (("job", w) for w in ("list", "show", "follow", "wait", "stop"))
JOB_WORDS = (JOB_LIST, JOB_SHOW, JOB_FOLLOW, JOB_WAIT, JOB_STOP)
HOUSEKEEPING = (HELP, WHERE, APP_OPEN, CALL, *JOB_WORDS)
# what the `job` words take, by the name it gets in `Parsed.args`: a positional job id (flag None: `job:…` or `current`)
# and their own switches
JOB_ARGS = {JOB_LIST: {"all": "--all"}, JOB_SHOW: {"job": None, "log": "--log"},
            JOB_FOLLOW: {"job": None, "from_end": "--from-end"}, JOB_WAIT: {"job": None},
            JOB_STOP: {"job": None, "now": "--now"}}


SELECTION_WORDS = "Say which songs: their ids, `-` (ids on standard input), --all or --rows."
BATCH_SELECTION_WORDS = "Say which songs: their ids, `-` (ids on standard input), --all, --rows or --batch <aiff:n>."


def _selection_words(batchable: bool) -> str:
    """What a write on songs says when none were named (`--batch` too where the command takes a batch's songs)."""
    return BATCH_SELECTION_WORDS if batchable else SELECTION_WORDS


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
    all: bool = False  # the selection forms of a bulk write (design §7.3): --all, --rows with --in / --todo / --search / --quality
    rows: bool = False
    where: str | None = None
    todo: str | None = None
    search: str | None = None
    quality: str | None = None


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


SELECTION_FLAGS = {"--rows": ("rows", True), "--in": ("where", False), "--todo": ("todo", False),
                   "--search": ("search", False), "--quality": ("quality", False)}  # flag -> (Flags field, switch?)


def selects(entry: Entry) -> bool:
    """Whether a command takes the selection forms (design §7.3): a write whose method works on a list of songs
    (`track_ids`). They stand beside its own words, so `<ids>`, `-`, `--all` and `--rows` are the four ways to say
    which songs."""
    return entry.kind != "R" and "track_ids" in parameters_of(entry.method)


def _selection_flags(entries: list[Entry], taken: Collection[str]) -> list[str]:
    """The selection flags of a command: `--rows` and its narrowing words always, `--all` only where the catalogue names
    the verb's own "all" (`catalog.ALL_OF`) and the method has no `--all` of its own."""
    if not any(selects(e) for e in entries):
        return []
    command = " ".join(entries[0].command)
    flags = [f for f in SELECTION_FLAGS if f not in taken]
    return (["--all"] if command in catalog.ALL_OF and "--all" not in taken else []) + flags


def extra_flags(entries: list[Entry], taken: Collection[str] = ()) -> list[str]:
    """The flags a command has beside its method's own: the selection words of a bulk write, `--dry-run` when an entry
    answers it, `--yes` when an entry needs it, `--limit` and `--offset` on a read (unless the method's own flags took
    the word). The parser and `help --json` both read this."""
    flags = _selection_flags(entries, taken)
    if any(e.dry_run for e in entries):
        flags.append("--dry-run")
    if any(e.needs_yes for e in entries):
        flags.append("--yes")
    if all(e.kind == "R" for e in entries):
        flags += [f"--{word}" for word in ("limit", "offset") if f"--{word}" not in taken]
    return flags


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
    for flag in extra_flags(entries, taken):
        if flag == "--all":
            leaf.add_argument(flag, dest="_sel_all", action="store_true", default=argparse.SUPPRESS)
        elif flag in SELECTION_FLAGS:
            field_name, switch = SELECTION_FLAGS[flag]
            leaf.add_argument(flag, dest=f"_sel_{field_name}", action="store_true" if switch else "store",
                              default=argparse.SUPPRESS)
        elif flag in ("--dry-run", "--yes"):
            leaf.add_argument(flag, dest=f"_{flag[2:].replace('-', '_')}", action="store_true", default=argparse.SUPPRESS)
        else:
            leaf.add_argument(flag, dest=f"_{flag[2:]}", type=int, default=argparse.SUPPRESS)


def build() -> _Parser:
    """The parser of every built command and of `call`."""
    root = _Parser(prog="discjockey", add_help=False, allow_abbrev=False)
    nouns = root.add_subparsers(dest="_noun", parser_class=_Parser, required=True)
    nodes: dict[tuple[str, ...], argparse.ArgumentParser] = {}
    levels: dict[tuple[str, ...], argparse._SubParsersAction] = {(): nouns}
    own = {cmd: [] for cmd in HOUSEKEEPING if cmd != CALL}
    for cmd, entries in {**commands(), **own}.items():
        for depth in range(1, len(cmd)):
            path = cmd[:depth]
            if path not in nodes:
                nodes[path] = levels[path[:-1]].add_parser(path[-1], add_help=False, allow_abbrev=False)
                levels[path] = nodes[path].add_subparsers(dest=f"_word{depth}", parser_class=_Parser, required=True)
        leaf = levels[cmd[:-1]].add_parser(cmd[-1], add_help=False, allow_abbrev=False)
        if entries:
            _add_arguments(leaf, entries)
        elif cmd == HELP:
            leaf.add_argument("topic", nargs="*", metavar="WORD", default=argparse.SUPPRESS)
        elif cmd in JOB_ARGS:
            for name, flag in JOB_ARGS[cmd].items():
                if flag is None:
                    leaf.add_argument(name, metavar=name.upper(), default=argparse.SUPPRESS)
                else:
                    leaf.add_argument(flag, dest=name, action="store_true", default=argparse.SUPPRESS)
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
    known = [*commands(), *HOUSEKEEPING]
    nouns = sorted({c[0] for c in known})
    if not words:
        raise UsageError("Say what to do: " + ", ".join(nouns) + ".")
    if words[0] not in nouns:
        raise UsageError(f"{words[0]} is not a command. The commands so far: {', '.join(nouns)}.")
    verbs = sorted({" ".join(c[1:2]) for c in known if c[0] == words[0]} - {""})
    if (words[0],) not in known and (len(words) < 2 or words[1] not in verbs):
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
    selected = ns.get("batch_id") is not None  # `--batch` says which songs: the batch's
    for key, attr in (("_sel_all", "all"), ("_sel_rows", "rows"), ("_sel_where", "where"), ("_sel_todo", "todo"),
                      ("_sel_search", "search"), ("_sel_quality", "quality")):
        if (value := ns.pop(key, None)):
            setattr(flags, attr, value)
            selected = True
    for key in ("limit", "offset"):
        if (value := ns.pop(f"_{key}", None)) is not None:
            if value < 0:
                raise UsageError(f"--{key} cannot be negative.")
            setattr(flags, key, value)
    if command in HOUSEKEEPING:
        return Parsed(command, [], ns, flags, words)
    entries = commands()[command]
    primary = next((e for e in entries if e.kind != "R"), entries[0])
    signature = signature_of(primary.method)
    for name, arg in catalog.effective_params(primary, signature).items():
        if arg.positional and arg.many:
            if name in ns and not ns[name]:
                del ns[name]
        if (arg.positional and name not in ns and signature.parameters[name].default is inspect.Parameter.empty
                and not (selected and name == "track_ids")):  # --all / --rows say which songs instead
            raise UsageError(_selection_words("batch_id" in signature.parameters) if name == "track_ids"
                             else f"{name.replace('_', ' ')} is missing.")
        if (arg.flag and name not in ns and signature.parameters[name].default is inspect.Parameter.empty
                and not flags.all):  # a flag the method cannot do without; the verb's own --all has its meaning without it
            raise UsageError(f"{arg.flag} is missing.")
    return Parsed(command, entries, ns, flags, words)
