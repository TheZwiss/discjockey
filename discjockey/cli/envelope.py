"""The envelope (issue 39, design §4.1): the one object `--json` prints for every command, a usage error and a crash
too, and the exit code of every outcome. `from_answer` turns a `HubApi` answer (`{ok, ...}` or `{ok: false, kind,
message, outcome, reason, next, person_steps, data}`) into it, so the command line says what the window's bridge
says."""
from __future__ import annotations

from collections.abc import Mapping

from ..hub import shapes
from ..hub.outcomes import EXIT, NO_AS_OF, REASONS, VERSION, envelope  # noqa: F401  (the envelope itself lives with the table of outcomes: the window's jobs write it too)

YOUR_TURN = "Your turn: "  # what starts each line of `person_steps` on stderr (`cli/__init__.py` notices, `follow.py`)


def noted(env: dict, method: str, dry: bool = False) -> dict:
    """`env` as it is, after the check of an ok envelope's final `data` against the shape `help --json` prints for it
    (`shapes.note_cli_data`; test mode only)."""
    if env.get("outcome") == "ok" and isinstance(env.get("data"), dict):
        shapes.note_cli_data(env["command"], shapes.cli_data_name(method, dry), env["data"])
    return env


def problem(command: str, outcome: str, reason: str, message: str | None = None, **fields) -> dict:
    """An envelope for a problem of the command line itself: `message` defaults to the reason's own words."""
    return envelope(command, outcome, reason=reason, message=message or REASONS[reason].text, **fields)


def usage(command: str, message: str, reason: str = "usage") -> dict:
    """`bad_args` (exit 2): the line was not right, nothing was looked at."""
    return problem(command, "bad_args", reason, message)


def crashed(command: str) -> dict:
    return problem(command, "failed", "crashed")


def from_answer(command: str, answer: Mapping, **fields) -> dict:
    """The envelope of one `HubApi` answer: the answer minus `ok` is `data` when it worked (an answer that says what to
    run next, a search with no hit, carries it as `next`: that is the envelope's, not `data`'s); a problem keeps its
    `outcome`, `reason`, `message`, `next`, `person_steps` and `data`."""
    if answer.get("ok"):
        return envelope(command, "ok", data={k: v for k, v in answer.items() if k not in ("ok", "next")},
                        next=answer.get("next") or (), **fields)
    outcome = answer.get("outcome") or "failed"
    reason = answer.get("reason")
    return envelope(command, outcome, reason=reason if reason in REASONS else None, message=answer.get("message"),
                    data=answer.get("data"), next=answer.get("next") or (), person_steps=answer.get("person_steps") or (),
                    **fields)


def exit_code(env: Mapping) -> int:
    return EXIT[env["outcome"]]
