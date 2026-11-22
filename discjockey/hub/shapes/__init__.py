"""The payloads of the bridge as shapes (issue 39, phase 2, design §8.2): `kernel.py` is the machinery (`F`, `shape`,
`alias`, the JSON Schema, the TypeScript, the checker), `common.py` the shapes every area uses, and each area has its
module. `python -m discjockey.hub.shapes --export` writes the generated files the window and the reference use
(`hub-ui/src/lib/bridge/types.gen.ts`, `schemas.gen.json`); a test fails while they are stale.

`ANSWERS` maps a method to the shape of its answer without `ok` (for a J method, the shape of the job's result, which
`RESULTS` also maps by job kind). Each area module has its own `ANSWERS` and `RESULTS`, merged here; a key in two
modules is a `ShapeError`. `CLI_DATA` (only `cli.py` has one) maps a method, or `"<method>:dry_run"`, to the shape of the
`data` the command line prints where it adds to the answer; `cli_data_name` is the one lookup.

Test mode (`DISCJOCKEY_CHECK_SHAPES=1`, set by tests/conftest.py): `note_answer`, `note_fail`, `note_result` and `note_cli_data` check what the engine
really answers against its shape and keep the mismatches in `MISMATCHES`. They never raise and do nothing otherwise."""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import cli, common, library, setup, todo
from .kernel import (ALIASES, DEFAULT, SHAPES, F, Registry, ShapeError, alias, json_schema, shape, typescript,
                     validate, values)

AREAS = (common, todo, library, setup, cli)


def _merged(which: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for area in AREAS:
        for key, name in getattr(area, which, {}).items():
            if key in out:
                raise ShapeError(f"{which}: {key!r} is mapped in two modules")
            if name not in SHAPES:
                raise ShapeError(f"{which}: {key!r} names {name!r}, which is no shape")
            out[key] = name
    return out


ANSWERS: dict[str, str] = _merged("ANSWERS")
RESULTS: dict[str, str] = _merged("RESULTS")
CLI_DATA: dict[str, str] = _merged("CLI_DATA")


def cli_data_name(method: str | None, dry: bool = False) -> str | None:
    """The shape of the `data` the command line prints for `method` (`dry`: the method a command's `--dry-run` runs):
    its own `CLI_DATA` entry, else the shape of the answer (`ANSWERS`). None when none is mapped."""
    if not method:
        return None
    return CLI_DATA.get(f"{method}:dry_run" if dry else method) or ANSWERS.get(method)


BRIDGE = Path(__file__).resolve().parents[3] / "hub-ui" / "src" / "lib" / "bridge"
FILES = {"types": BRIDGE / "types.gen.ts", "schemas": BRIDGE / "schemas.gen.json"}


def schemas_text() -> str:
    """`schemas.gen.json`: every shape and alias, and which shape answers which method and job."""
    body = {"$defs": DEFAULT.definitions(), "answers": ANSWERS, "results": RESULTS,
            "cli_data": CLI_DATA}
    return json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def generated() -> dict[Path, str]:
    """Each generated file and what it must hold."""
    return {FILES["types"]: typescript(), FILES["schemas"]: schemas_text()}


# --- test mode ---

CHECKING = os.environ.get("DISCJOCKEY_CHECK_SHAPES") == "1"
MISMATCHES: list[tuple[str, list[str]]] = []


def _note(where: str, name: str | None, value) -> None:
    if name is None:
        return
    try:
        problems = validate(value, name)
    except Exception as e:  # noqa: BLE001 - a check never breaks the product
        problems = [f"the check itself failed: {e!r}"]
    if problems:
        MISMATCHES.append((where, problems))


def note_answer(method: str, answer) -> None:
    """Check what `method` answered (without `ok`) against its shape. The start of a J method (`{job_id}`) is skipped:
    its result is checked by `note_result`."""
    if not CHECKING:
        return
    try:
        if isinstance(answer, dict) and answer.get("ok") is False:
            _note(f"failure handed back by {method}", "CliFail", answer)  # a failure a method handed back whole
            return
        if isinstance(answer, dict) and set(answer) == {"job_id"}:
            return  # a job start
        _note(f"answer of {method}", ANSWERS.get(method), answer)
    except Exception:  # noqa: BLE001
        pass


def note_fail(method: str, answer) -> None:
    """Check a failed answer (`{ok: false, kind, message, ...}`) that `method` ended with against `CliFail`."""
    if not CHECKING:
        return
    try:
        _note(f"failure handed back by {method}", "CliFail", answer)
    except Exception:  # noqa: BLE001
        pass


def note_cli_data(command: str, name: str | None, data) -> None:
    """Check the `data` an ok envelope of `command` prints against `name`, the shape `help --json` says it has
    (`cli_data_name`). None: no shape is mapped, nothing is checked."""
    if not CHECKING or name is None:
        return
    try:
        _note(f"data of command {command}", name, data)
    except Exception:  # noqa: BLE001
        pass


def note_result(kind: str, result) -> None:
    """Check the result of a finished job of `kind` against its shape; no result is not checked."""
    if not CHECKING or result is None:
        return
    try:
        _note(f"result of job {kind}", RESULTS.get(kind), result)
    except Exception:  # noqa: BLE001
        pass


def take_mismatches() -> list[str]:
    """What the checks found since the last call, one line per mismatch (`where: problem; problem`), and forget it."""
    taken = MISMATCHES[:]
    del MISMATCHES[:len(taken)]  # an append from a job thread between the copy and here stays for the next call
    return [f"{where}: " + "; ".join(problems) for where, problems in taken]
