"""The command line's own words (issue 39 group 1.3; design §2.3): `help`, `where`, `app open` and `call`. They run
no catalogue entry and have no `HubApi` method; `catalog.HOUSEKEEPING` lists them, and T2/T3 count them.

- `help` is the way in. Without words (from a shell, also what the app binary prints for no argument) it is the short
  list: the first line says what an agent runs first, then every word with one line. `help --json` is the machine
  index: every built command with its arguments, flags, whether it writes, its job kind, the bridge methods it runs, the
  reasons it may answer with and its example (CONTRIBUTING.md > "Terminal version" has the layout). `help <noun> [<verb>]` is the same
  for one noun or one command; `help where`, `help call` and `help app open` describe these words. A command
  that is not built yet (`planned`) is in no answer.
- `where` prints the folders the way the window finds them (`library.resolve_paths`), the absolute path of this
  program and its version, and `jobs_running` (the jobs of this music folder the registry says run now), so an agent can check it works on the intended library before any write.
- `app open` opens the window (the one thing here that is not an answer): the same as the app started from the Finder.
- `call <method> [--args <json|->] [--password-stdin]` (plan v2 D4) sends the window's exact payload to a bridge method
  through the entry it names (`call.run_method`)."""
from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

from .. import REPO, __version__, tools
from .. import words as engine_words
from ..hub import catalog, ids, registry
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
                            "type": "str", "id": None}]),
    WHERE: ("Say where Discjockey's folders and this program are, before anything is changed.", "where --json", []),
    APP_OPEN: ("Open the Discjockey window (the same as starting the app).", "app open", []),
    CALL: ("Send a bridge method the window's exact payload; it changes things only as the method's own command does.", "call rekordbox_status --json",
           [{"name": "method", "word": "METHOD", "positional": True, "many": False, "required": True, "type": "str",
             "id": None},
            {"name": "args", "word": "--args", "positional": False, "many": False, "required": False, "type": "str",
             "id": None},
            {"name": "password", "word": "--password-stdin", "positional": False, "many": False, "required": False,
             "type": "bool", "id": None}]),
}
_JOB = {"name": "job", "word": ids.FORMS["job"], "positional": True, "many": False, "required": True, "type": "str",
        "id": "job"}


def _switch(name: str) -> dict:
    return {"name": name, "word": "--" + name.replace("_", "-"), "positional": False, "many": False, "required": False,
            "type": "bool", "id": None}


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
    return catalog.primary(entries)


LOCK_REASONS = {"library": ("library_lock",), "support": ("support_lock",), "rekordbox_w": ("rekordbox_lock", "rekordbox_open"),
                "rekordbox_r": ()}  # the reasons a lock of the catalogue's `locks` column answers with
LINE_REASONS = ("usage", "crashed", "conflicting_flags")  # every line can get these
JOB_REASONS = ("still_running", "stop", "stop_now", "worker_lost")  # a command that runs as a job
PLAN_REASONS = ("changed", "plan_expired", "unknown_id")  # a command that takes `--plan`
_JOB_ID_REASONS = ("unknown_id", "bad_id_kind", "not_running")
# the reasons of the command line's own words (no catalogue entry): `job stop` adds the window's jobs and a lost worker
OWN_REASONS = {
    parser.JOB_SHOW: (*LINE_REASONS, *_JOB_ID_REASONS),
    parser.JOB_FOLLOW: (*LINE_REASONS, *_JOB_ID_REASONS, "still_running"),
    parser.JOB_WAIT: (*LINE_REASONS, *_JOB_ID_REASONS, "still_running"),
    parser.JOB_STOP: (*LINE_REASONS, *_JOB_ID_REASONS, "window_job", "worker_lost"),
    CALL: (*LINE_REASONS, "failed", "unknown_id", "bad_id_kind", "needs_yes", "refused"),
}


def reasons_of(entries: list[Entry]) -> list[str]:
    """The reasons a command may answer with besides what an engine rule says of its own: what every line can get
    wrong, the ids it resolves, the confirmation it asks for, the missing music folder, the locks its entries take,
    what a job answers and what a plan does."""
    found = {*LINE_REASONS, "failed"}
    for e in entries:
        signature = parser.signature_of(e.method)
        if any(a.resolve for a in catalog.effective_params(e, signature).values()):
            found |= {"unknown_id", "bad_id_kind"}
        if e.needs_yes:
            found.add("needs_yes")
        if e.method not in catalog.NEEDS_NO_LIBRARY:
            found.add("no_library")
        if e.kind in ("J", "RJ"):
            found |= set(JOB_REASONS)
        if "plan_id" in signature.parameters:
            found |= set(PLAN_REASONS)
        for lock in e.locks:
            found |= set(LOCK_REASONS[lock])
    return sorted(found)


def _args_of(entries: list[Entry]) -> list[dict]:
    """The arguments of a command as a person types them: `word` is the form of a positional (`aiff:N`, `on|off`) or the
    flag, `id` the id kind a typed value is read as (a key of `ids.FORMS`, else None), `type` what is typed (`str` for
    anything that is resolved)."""
    primary = choose(entries)
    signature = parser.signature_of(primary.method)
    selecting = parser.selects(primary)
    out = []
    for name, arg in catalog.effective_params(primary, signature).items():
        if not (arg.positional or arg.flag):
            continue  # built by `resolve` from another argument: the person never types it
        required = arg.positional and signature.parameters[name].default is signature.parameters[name].empty
        kind = arg.resolve.split(":")[0] if arg.resolve else None
        out.append({"name": name, "word": parser.form_of(name, arg) if arg.positional else arg.flag,
                    "positional": arg.positional, "many": arg.many,
                    "required": required and not (selecting and name == "track_ids"),  # `-`, `--all`, `--rows` stand in
                    "type": "str" if arg.resolve else arg.type, "id": kind if kind in ids.FORMS else None})
    return out


def _flag_values(entries: list[Entry], args: list[dict], flags: list[str]) -> dict[str, str]:
    """The word of the value of every flag of the row that takes one (`--batch aiff:N`, `--in COLLECTION`, `--limit N`)."""
    primary = choose(entries)
    params = catalog.effective_params(primary, parser.signature_of(primary.method))
    out = {a["word"]: parser.form_of(a["name"], params[a["name"]]) for a in args
           if not a["positional"] and a["type"] != "bool"}
    for flag in flags:
        word = parser.VALUE_FLAGS.get(flag) or (parser.SELECTION_FLAGS.get(flag) or (None, None, None))[2]
        if word:
            out[flag] = word
    return out


def _songs(entries: list[Entry], args: list[dict], flags: list[str]) -> list[str]:
    """The ways a selecting command says which songs, each only where the command has it."""
    if not parser.selects(choose(entries)):
        return []
    forms = [f"{ids.FORMS['track']}...", "-"]
    forms += [f for f in ("--all", "--rows") if f in flags or any(a["word"] == f for a in args)]
    return forms + [a["word"] for a in args if a["word"] == "--batch"]


def usage_of(command: tuple[str, ...], args: list[dict], flags: list[str], flag_values: dict[str, str] | None = None,
             songs: list[str] | None = None, required_flags: list[str] | None = None) -> str:
    """The command as it is typed. A command that selects songs writes `(TRACK... | - | --all | --rows)` for them; a
    flag with a value prints it (`[--in COLLECTION]`); a flag the command cannot run without prints no brackets."""
    values, songs, required = flag_values or {}, songs or [], required_flags or []

    def flag(word: str, name: str = "") -> str:
        return f"{word} {values.get(word) or name.upper()}" if word in values or name else word

    words = [" ".join(command)]
    for a in args:
        if a["positional"]:
            if songs and a["name"] == "track_ids":
                words.append("(" + " | ".join(flag(f) if f == "--batch" else f for f in songs) + ")")
                continue
            word = a["word"] + ("..." if a["many"] else "")
            words.append(word if a["required"] else f"[{word}]")
        elif a["word"] not in songs:
            words.append(f"[{a['word']}]" if a["type"] == "bool" else f"[{flag(a['word'], a['name'])}]")
    for f in flags:
        if f in songs:
            continue
        words.append(flag(f) if f in required else f"[{flag(f)}]")
    return " ".join(words)


def index_entry(command: tuple[str, ...], entries: list[Entry]) -> dict:
    """One built command as `help --json` lists it. `kind` is the catalogue's (R read, RJ read that may run as a job,
    J write job, J-control stops a job, B brief save, `words` the command line's own word); `writes` is whether it
    changes anything, `job` whether it runs as a job; `dry_run` whether `--dry-run` shows what it would do. `methods`
    are the bridge methods it runs (`call` takes their names), `dry_run_method` the one `--dry-run` runs; `songs` the
    ways to say which songs; `flag_values` the word of each flag's value; `required_flags` the flags it cannot run
    without."""
    primary = choose(entries)
    args = _args_of(entries)
    taken = {a["word"] for a in args if not a["positional"]}
    flags = parser.extra_flags(entries, taken)
    values = _flag_values(entries, args, flags)
    songs = _songs(entries, args, flags)
    required = [f for f in flags if f in catalog.PHASE_ONLY.values()]
    return {"command": " ".join(command), "kind": primary.kind, "writes": primary.kind in WRITES,
            "job": primary.kind in JOBS, "args": args, "flags": flags, "needs_yes": any(e.needs_yes for e in entries),
            "dry_run": any(e.dry_run for e in entries), "locks": sorted({lock for e in entries for lock in e.locks}),
            "methods": list(dict.fromkeys(e.method for e in entries)),
            "dry_run_method": next((e.dry_run for e in entries if e.dry_run), None), "songs": songs,
            "flag_values": values, "required_flags": required,
            "reasons": reasons_of(entries), "example": next((e.example for e in entries if e.example), ""),
            "usage": usage_of(command, args, flags, values, songs, required)}


def own_entry(command: tuple[str, ...]) -> dict:
    says, example, args = OWN_WORDS[command]
    flags = [] if command != CALL else ["--dry-run", "--yes"]
    values = {"--args": "JSON|-"} if command == CALL else {}
    return {"command": " ".join(command), "kind": "words", "writes": command in (CALL, parser.JOB_STOP), "job": False, "args": args,
            "flags": flags, "needs_yes": False, "dry_run": False, "locks": [], "methods": [], "dry_run_method": None,
            "songs": [], "flag_values": values, "required_flags": [],
            "reasons": sorted(OWN_REASONS.get(command, LINE_REASONS)), "example": example,
            "usage": usage_of(command, args, flags, values), "says": says}


def index() -> list[dict]:
    """Every built command, the command line's own words first."""
    own = [own_entry(c) for c in parser.HOUSEKEEPING]
    return own + [index_entry(c, e) for c, e in sorted(parser.commands().items())]


def call_methods() -> list[str]:
    """The bridge methods `call` accepts: every method of a built or cli-first entry, except the window's own, the
    dropped and the ones that only stop a job."""
    return sorted({e.method for e in catalog.ENTRIES if not e.planned and e.kind not in ("W", "dropped", "J-control")})


def _short(found: dict) -> dict:
    """What the text page of one command shows: its usage and whether it changes anything (and what it does, where the
    row has a sentence)."""
    short = {"command": found["command"], "usage": found["usage"], "writes": found["writes"], "example": found["example"]}
    return {**short, "says": found["says"]} if found.get("says") else short


def _list_page() -> list[dict]:
    """The short list: one line per noun (the verbs it has), then the command line's own words."""
    nouns: dict[str, list[str]] = {}
    for cmd in sorted(parser.commands()):
        nouns.setdefault(cmd[0], []).append(" ".join(cmd[1:]))
    rows = [{"word": noun, "does": f"{engine_words.NOUN_WORDS[noun]} ({', '.join(v for v in verbs if v)})"
             if any(verbs) else engine_words.NOUN_WORDS[noun]} for noun, verbs in nouns.items()]
    rows += [{"word": " ".join(cmd), "does": OWN_WORDS[cmd][0]} for cmd in parser.HOUSEKEEPING]
    return rows


def run_help(parsed: Parsed) -> dict:
    topic = parsed.args.get("topic") or []
    flags: Flags = parsed.flags
    path = shlex.quote(command_path())  # a line a shell can take, also where the path holds a space
    if not topic:
        if flags.json:
            return envelope.envelope("help", "ok", message=FIRST_LINE.format(path=path), data={
                "command": command_path(), "version": __version__, "global_flags": GLOBAL_FLAGS, "commands": index(), "call_methods": call_methods()})
        return envelope.envelope(
            "help", "ok", message=FIRST_LINE.format(path=path), data={"commands": _list_page()},
            next=[{"run": f"{path} help <word> [<verb>]", "why": "one word or command in detail"}])
    every = index()
    found = []
    for length in range(len(topic), 0, -1):  # `upgrade apply x --help` shows `upgrade apply`: words from the end drop off
        found = [c for c in every if c["command"].split()[:length] == topic[:length]]
        if found:
            break
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
