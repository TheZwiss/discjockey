"""`discjockey call <method> [--args <json|->] [--password-stdin]` (issue 39, plan v2 D4): the command line's way to
send the window's exact payload to a bridge method. A housekeeping module: it only reads its own words and hands them
to `call.run_method`, which picks the catalogue entry and runs it like the noun-verb form."""
from __future__ import annotations

import json
import sys

from . import call, envelope
from .parser import Parsed


def run(parsed: Parsed) -> dict:
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
