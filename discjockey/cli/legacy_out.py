"""The old command line's output helpers (`say`, `failed`, `no_library`), moved unchanged out of `rekordbox_cmd.py` when
`rekordbox preview` became the new command line's (issue 39, group 1.9). `batch_cmd.py`, `convert_cmd.py` and
`settings_cmd.py` still print through them; this module goes with the last of those (groups 1.12 to 1.14)."""
from __future__ import annotations

import argparse
import json

from .. import library


def say(args: argparse.Namespace, data: dict, lines: list[str]) -> None:
    if args.json:
        print(json.dumps(data))
    else:
        print("\n".join(lines))


def failed(args: argparse.Namespace, message: str, kind: str = "failed", reason: str | None = None,
           code: int = 1, extra: dict | None = None, lines: list[str] | None = None) -> int:
    """The failure shape `{"ok": false, "kind", "message", "reason"?}` (+ `extra`'s keys), printed as JSON or as
    `lines` (the message alone by default); returns the exit code."""
    data = {"ok": False, "kind": kind, "message": message}
    if reason:
        data["reason"] = reason
    data.update(extra or {})
    say(args, data, [message] if lines is None else lines)
    return code


def no_library(args: argparse.Namespace, resolved: library.Resolved) -> int:
    """Exit 2: there is no music folder to work in (not chosen yet, or its drive isn't there)."""
    message = (f"Your music folder isn't there: {resolved.music_folder}" if resolved.problem == "missing" else
               "Discjockey doesn't know your music folder yet. Open the Discjockey window and follow Setup, "
               "or run: discjockey setup")
    return failed(args, message, "refused", "no_library", code=2)
