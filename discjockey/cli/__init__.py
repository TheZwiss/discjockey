"""Discjockey's command line (issue 39): `main(argv)` is the one entry (`discjockey/__main__.py` and
`discjockey/app_main.py` call it). The parser is generated from the catalogue (`parser.py`); every built command runs
through `call.run`, which calls a `HubApi` method (`bind.py`, headless) and wraps its answer in the envelope
(`envelope.py`): with `--json` stdout holds exactly that object, also for a usage error and a crash, and the exit code
is the outcome's (`hub/outcomes.py` `EXIT`). Without `--json` the answer is a text page (`render/`), notices and
problems go to stderr. A line whose command is not built yet (a bare sync, a leading sync flag, a legacy word) goes
unchanged to the old parser in `legacy.py`. Imports yt-dlp through the engine: only after `tools.activate()`."""
from __future__ import annotations

import json
import sys
import traceback

from ..hub.outcomes import REASONS
from . import call, envelope, housekeeping, parser
from .legacy import parse_args  # noqa: F401 - the old parser's entry, for the callers that pin its words
from .parser import APP_OPEN, HOUSEKEEPING, Flags, UsageError
from . import render
from .render import layout


def render_text(env: dict, flags: Flags, *, color: bool = False) -> str:
    """The text of an answer: its `data` as the command's page (a hand page, else the generic one), under the message
    when it worked (a problem's message goes to stderr)."""
    page = render.page_for(env["command"])(env["data"] or {}, message=env["message"] if env["outcome"] == "ok" else None,
                                           verbose=flags.verbose, limit=flags.limit, offset=flags.offset)
    return layout.render(page, color=color)


def notices(env: dict) -> list[str]:
    """What goes to stderr besides the page: a problem's message, the steps only the person can do, what to run next."""
    lines = []
    if env["outcome"] != "ok":
        lines.append(env["message"] or (REASONS[env["reason"]].text if env["reason"] else env["outcome"]))
    lines += [f"Your turn: {step['say']}" + (f" Then: {step['then']}" if step.get("then") else "")
              for step in env["person_steps"]]
    lines += [f"Next: {n['run']}" + (f"  ({n['why']})" if n.get("why") else "") for n in env["next"]]
    return lines


def emit(env: dict, flags: Flags) -> int:
    """Prints the answer (one JSON object with `--json`, else the page and the notices) and returns the exit code."""
    if flags.json or flags.jsonl:  # `--jsonl`: the events came before, the envelope is the last line
        print(json.dumps(env, ensure_ascii=False), flush=True)
        return envelope.exit_code(env)
    if env["outcome"] == "ok" or env["data"]:
        text = render_text(env, flags, color=layout.use_color(sys.stdout, no_color=flags.no_color))
        if text:
            print(text)
    for line in notices(env):
        print(line, file=sys.stderr)
    return envelope.exit_code(env)


def _run(argv: list[str]) -> int:
    flags = Flags(json="--json" in argv, jsonl="--jsonl" in argv)  # what a usage error needs before the line is read
    words = parser.words_of(argv)[0]
    command = " ".join(words[:2])
    try:
        parsed = parser.parse(argv)
        flags, command = parsed.flags, " ".join(parsed.command)
        if parsed.command == APP_OPEN:
            return housekeeping.open_app()  # the window is the answer; nothing is printed
        if parsed.command in HOUSEKEEPING:
            env = housekeeping.run(parsed)
        else:
            env = call.run(call.choose(parsed.entries, flags), parsed.args, flags)
    except UsageError as e:
        env = envelope.usage(command, e.message, e.reason)
    except Exception:  # noqa: BLE001 - `--json` always ends with one object; a bug is a failed answer
        if flags.verbose:
            traceback.print_exc()
        env = envelope.crashed(command)
    return emit(env, flags)


WORKER = ["job", "_worker"]  # the hidden command a job's worker process runs (cli/worker.py); not in `help`, not parsed


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:2] == WORKER:
        from . import worker
        return worker.main(argv[2:])
    if [a for a in argv if a != "--json"] in (["--help"], ["-h"]):  # the usual first probe: the short list
        argv = ["help", *(a for a in argv if a == "--json")]
    elif {"--help", "-h"} & set(argv):  # `upgrade --help`, `upgrade apply -h`: the help of that word or command
        rest = [a for a in argv if a not in ("--help", "-h")]
        if parser.route(rest) == "new":
            argv = ["help", *parser.words_of(rest)[0], *(["--json"] if "--json" in argv else [])]
    if parser.route(argv) == "legacy":
        from . import legacy
        return legacy.main(argv)
    return _run(argv)
