"""The command line's own words (issue 39 group 1.3; design §2.3): `help`, `where`, `app open` and `call`. They run
no catalogue entry and have no `HubApi` method; `catalog.HOUSEKEEPING` lists them, and T2/T3 count them.

- `help` is the way in. Without words (from a shell, also what the app binary prints for no argument) it is the short
  list: the first line says what an agent runs first, then every word with one line. `help --json` is the machine
  index: every built command with its arguments, flags, whether it writes, its job kind, the reasons it may answer
  with and its example (CONTRIBUTING.md > "Terminal version" has the layout). `help <noun> [<verb>]` is the same
  for one noun or one command; `help where`, `help call` and `help app open` describe these words. A command
  that is not built yet (`planned`) is in no answer.
- `where` prints the folders the way the window finds them (`library.resolve_paths`), the absolute path of this
  program and its version, and `jobs_running` (the jobs of this music folder the registry says run now), so an agent can check it works on the intended library before any write.
- `app open` opens the window (the one thing here that is not an answer): the same as the app started from the Finder.
- `call <method> [--args <json|->] [--password-stdin]` (plan v2 D4) sends the window's exact payload to a bridge method
  through the entry it names (`call.run_method`)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import REPO, __version__, tools
from ..hub import catalog, registry
from ..hub.api import LIBRARY_METHODS
from ..hub.catalog import Entry
from ..hub.outcomes import REASONS
from ..rekordbox.locate import locate
from . import bind, call, envelope, follow, parser
from .parser import APP_OPEN, CALL, HELP, JOB_WORDS, WHERE, Flags, Parsed

FIRST_LINE = "AI agents: run `{path} help --json` first."
GLOBAL_FLAGS = [
    {"flag": "--json", "says": "print exactly one JSON object (the envelope) on stdout"},
    {"flag": "--jsonl", "says": "print one JSON object per line (job commands)"},
    {"flag": "--wait", "says": "seconds to wait for a job to finish before answering (job commands)"},
    {"flag": "--detach", "says": "start a job and answer at once (job commands)"},
    {"flag": "--wait-busy", "says": "seconds to wait while another Discjockey process holds the library (job commands)"},
    {"flag": "--verbose", "says": "show the raw facts and the details too"},
    {"flag": "--no-color", "says": "no colour in the text pages"},
]
# the command line's own words: what each does, and how it is written. `kind` is "words" (no catalogue entry).
OWN_WORDS = {
    HELP: ("Say how to use Discjockey: the short list, the machine index with --json, or one command.",
           "help --json", [{"name": "topic", "word": "WORD", "positional": True, "many": True, "required": False,
                            "type": "str"}]),
    WHERE: ("Say where Discjockey's folders and this program are, before anything is changed.", "where --json", []),
    APP_OPEN: ("Open the Discjockey window (the same as starting the app).", "app open", []),
    CALL: ("Send a bridge method the window's exact payload; it changes things only as the method's own command does.", "call rekordbox_status --json",
           [{"name": "method", "word": "METHOD", "positional": True, "many": False, "required": True, "type": "str"},
            {"name": "args", "word": "--args", "positional": False, "many": False, "required": False, "type": "str"},
            {"name": "password", "word": "--password-stdin", "positional": False, "many": False, "required": False,
             "type": "bool"}]),
}
_JOB = {"name": "job", "word": "JOB", "positional": True, "many": False, "required": True, "type": "str"}


def _switch(name: str) -> dict:
    return {"name": name, "word": "--" + name.replace("_", "-"), "positional": False, "many": False, "required": False,
            "type": "bool"}


OWN_WORDS.update({
    parser.JOB_LIST: ("List the jobs of this music folder: running first, then the newest.", "job list", [_switch("all")]),
    parser.JOB_SHOW: ("Show one job: its state, its last events, its result when it ended (`job:<id>` or `current`).",
                      "job show current", [_JOB, _switch("log")]),
    parser.JOB_FOLLOW: ("Follow a job's events to its end, then print its answer.", "job follow current",
                        [_JOB, _switch("from_end")]),
    parser.JOB_WAIT: ("Wait for a job to end (at most --wait seconds) and print its own answer; running (exit 8) if "
                      "it goes on.", "job wait current --wait 90", [_JOB]),
    parser.JOB_STOP: ("Ask a job to stop safely after its current step; --now stops it at once (terminal jobs).",
                      "job stop current", [_JOB, _switch("now")]),
})
WRITES = ("J", "J-control", "B")
JOBS = ("J", "J-control", "RJ")


def command_path() -> str:
    """The absolute path of this program: the app's own binary, or the checkout's `bin/discjockey`."""
    if tools.is_frozen():
        return str(Path(sys.executable).resolve())
    launcher = REPO / "bin" / "discjockey"
    return str(launcher if launcher.is_file() else Path(sys.executable).resolve())


# --- help ---

def choose(entries: list[Entry]) -> Entry:
    """The entry the command runs (`call.choose`'s rule): the write when there is one, else the read."""
    return next((e for e in entries if e.kind != "R"), entries[0])


def reasons_of(entries: list[Entry]) -> list[str]:
    """The reasons a command may answer with besides a plain failure: what the line itself can get wrong, the ids it
    resolves, the confirmation it asks for, the missing music folder, and the locks its entries take."""
    found = {"usage", "crashed"}
    for e in entries:
        signature = parser.signature_of(e.method)
        if any(a.resolve for a in catalog.effective_params(e, signature).values()):
            found |= {"unknown_id", "bad_id_kind"}
        if e.needs_yes:
            found.add("needs_yes")
        if e.method in LIBRARY_METHODS:
            found.add("no_library")
        found |= {f"{lock}_lock" for lock in e.locks if f"{lock}_lock" in REASONS}
    return sorted(found)


def _args_of(entries: list[Entry]) -> list[dict]:
    primary = choose(entries)
    signature = parser.signature_of(primary.method)
    out = []
    for name, arg in catalog.effective_params(primary, signature).items():
        if not (arg.positional or arg.flag):
            continue  # built by `resolve` from another argument: the person never types it
        required = arg.positional and signature.parameters[name].default is signature.parameters[name].empty
        out.append({"name": name, "word": name.upper() if arg.positional else arg.flag, "positional": arg.positional,
                    "many": arg.many, "required": required, "type": arg.type})
    return out


def usage_of(command: tuple[str, ...], args: list[dict], flags: list[str]) -> str:
    words = [" ".join(command)]
    for a in args:
        if a["positional"]:
            word = a["word"] + ("..." if a["many"] else "")
            words.append(word if a["required"] else f"[{word}]")
        else:
            words.append(f"[{a['word']}]" if a["type"] == "bool" else f"[{a['word']} {a['name'].upper()}]")
    words += [f"[{f}{' N' if f in ('--limit', '--offset') else ''}]" for f in flags]
    return " ".join(words)


def index_entry(command: tuple[str, ...], entries: list[Entry]) -> dict:
    """One built command as `help --json` lists it. `kind` is the catalogue's (R read, RJ read that may run as a job,
    J write job, J-control stops a job, B brief save, `words` the command line's own word); `writes` is whether it
    changes anything, `job` whether it runs as a job; `dry_run` whether `--dry-run` shows what it would do."""
    primary = choose(entries)
    args = _args_of(entries)
    taken = {a["word"] for a in args if not a["positional"]}
    flags = parser.extra_flags(entries, taken)
    return {"command": " ".join(command), "kind": primary.kind, "writes": primary.kind in WRITES,
            "job": primary.kind in JOBS, "args": args, "flags": flags, "needs_yes": any(e.needs_yes for e in entries),
            "dry_run": any(e.dry_run for e in entries), "locks": sorted({lock for e in entries for lock in e.locks}),
            "reasons": reasons_of(entries), "example": next((e.example for e in entries if e.example), ""),
            "usage": usage_of(command, args, flags)}


def own_entry(command: tuple[str, ...]) -> dict:
    says, example, args = OWN_WORDS[command]
    flags = [] if command != CALL else ["--dry-run", "--yes"]
    return {"command": " ".join(command), "kind": "words", "writes": command in (CALL, parser.JOB_STOP), "job": False, "args": args,
            "flags": flags, "needs_yes": False, "dry_run": False, "locks": [],
            "reasons": ["usage", "crashed"], "example": example, "usage": usage_of(command, args, flags),
            "says": says}


def index() -> list[dict]:
    """Every built command, the command line's own words first."""
    own = [own_entry(c) for c in parser.HOUSEKEEPING]
    return own + [index_entry(c, e) for c, e in sorted(parser.commands().items())]


def _short(found: dict) -> dict:
    """What the text page of one command shows: its usage and whether it changes anything."""
    return {"command": found["command"], "usage": found["usage"], "writes": found["writes"],
            "example": found["example"]}


def _list_page() -> list[dict]:
    """The short list: one line per noun (the verbs it has), then the command line's own words."""
    nouns: dict[str, list[str]] = {}
    for cmd in sorted(parser.commands()):
        nouns.setdefault(cmd[0], []).append(" ".join(cmd[1:]))
    rows = [{"word": noun, "does": ", ".join(v for v in verbs if v) or "(see help " + noun + ")"}
            for noun, verbs in nouns.items()]
    rows += [{"word": " ".join(cmd), "does": OWN_WORDS[cmd][0]} for cmd in parser.HOUSEKEEPING]
    return rows


def run_help(parsed: Parsed) -> dict:
    topic = parsed.args.get("topic") or []
    flags: Flags = parsed.flags
    path = command_path()
    if not topic:
        if flags.json:
            return envelope.envelope("help", "ok", message=FIRST_LINE.format(path=path), data={
                "command": path, "version": __version__, "global_flags": GLOBAL_FLAGS, "commands": index()})
        return envelope.envelope(
            "help", "ok", message=FIRST_LINE.format(path=path), data={"commands": _list_page()},
            next=[{"run": f"{path} help <word> [<verb>]", "why": "one word or command in detail"}])
    found = [c for c in index() if c["command"].split()[:len(topic)] == topic]
    if not found:
        words = sorted({c["command"].split()[0] for c in index()})
        return envelope.usage("help", f"There is no command called {' '.join(topic)}. The words so far: "
                                      f"{', '.join(words)}.")
    return envelope.envelope("help", "ok", data={"commands": found if flags.json else [_short(c) for c in found]})


# --- where ---

def run_where(parsed: Parsed) -> dict:
    here = bind.resolved()
    paths = here.paths
    place = locate()
    music = {"path": str(paths.root) if paths is not None else str(here.music_folder) if here.music_folder else None,
             "state": here.problem or "ok"}
    buy_list = paths.not_lossless_md if paths is not None else None
    return envelope.envelope("where", "ok", message="Where Discjockey keeps its things.", data={
        "music": music, "not_lossless": str(buy_list) if buy_list is not None and buy_list.is_file() else None,
        "support": str(here.support), "rekordbox": str(place.db) if place is not None else None,
        "command": command_path(), "version": __version__, "sandbox": None,
        "jobs_running": registry.Registry(here.support).running(music["path"])})


# --- app open ---

def open_app() -> int:
    """Opens the window (no caffeinate: the window keeps the Mac awake itself while it changes the library). It opens
    without a music folder too: Setup, or the missing-folder screen, takes over. Imports the hub (and so yt-dlp) here,
    after `tools.activate()`."""
    from ..hub import app
    return app.main(bind.resolved())


# --- call ---

def run_call(parsed: Parsed) -> dict:
    method, text = parsed.args["method"], parsed.args.get("args_text")
    password_stdin = parsed.args.get("password_stdin", False)
    if text == "-" and password_stdin:
        return envelope.usage("call", "--args - and --password-stdin both read stdin: send the arguments in --args.")
    args: object = {}
    if text is not None:
        try:
            args = json.loads(sys.stdin.read() if text == "-" else text)
        except ValueError as e:
            return envelope.usage("call", f"--args is not JSON: {e}.")
    password = sys.stdin.read().rstrip("\r\n") if password_stdin else None
    return call.run_method(method, args, parsed.flags, password=password)


def run(parsed: Parsed) -> dict:
    """The answer of `help`, `where` or `call` (`app open` is `open_app`)."""
    if parsed.command in JOB_WORDS:
        return follow.run(parsed)
    return {HELP: run_help, WHERE: run_where, CALL: run_call}[parsed.command](parsed)
