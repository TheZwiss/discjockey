"""The envelope (issue 39, design §4.1): the one object `--json` prints for every command, a usage error and a crash
too, and the exit code of every outcome. `from_answer` turns a `HubApi` answer (`{ok, ...}` or `{ok: false, kind,
message, outcome, reason, next, person_steps, data}`) into it, so the command line says what the window's bridge
says."""
from __future__ import annotations

from collections.abc import Iterable, Mapping

from ..hub.outcomes import EXIT, REASONS

VERSION = 1
NO_AS_OF = {"scanned_at": None, "read_at": None}


def envelope(command: str, outcome: str, *, reason: str | None = None, message: str | None = None,
             data: Mapping | None = None, next: Iterable[Mapping] = (), person_steps: Iterable[Mapping] = (),
             recovered: Iterable[Mapping] = (), job: str | None = None, as_of: Mapping | None = None,
             sandbox: str | None = None) -> dict:
    """The envelope, its keys in design order. `recovered` is always a list, `as_of` always has both keys."""
    if outcome not in EXIT:
        raise ValueError(f"no such outcome {outcome!r}")
    if reason is not None and reason not in REASONS:
        raise ValueError(f"no such reason {reason!r}")
    return {"v": VERSION, "command": command, "outcome": outcome, "reason": reason, "message": message,
            "data": dict(data) if data is not None else None, "next": [dict(n) for n in next],
            "person_steps": [dict(s) for s in person_steps], "recovered": [dict(r) for r in recovered], "job": job,
            "as_of": {**NO_AS_OF, **(as_of or {})}, "sandbox": sandbox}


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
