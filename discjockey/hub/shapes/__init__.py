"""The payloads of the bridge as shapes (issue 39, phase 2, design §8.2): `kernel.py` is the machinery (`F`, `shape`,
`alias`, the JSON Schema, the TypeScript, the checker), `common.py` the shapes every area uses, and each area has its
module. `python -m discjockey.hub.shapes --export` writes the generated files the window and the reference use
(`hub-ui/src/lib/bridge/types.gen.ts`, `schemas.gen.json`); a test fails while they are stale.

`ANSWERS` maps a method to the shape of its answer without `ok` (for a J method, the shape of the job's result, which
`RESULTS` also maps by job kind). Each area module has its own `ANSWERS` and `RESULTS`, merged here; a key in two
modules is a `ShapeError`.

Test mode (`DISCJOCKEY_CHECK_SHAPES=1`, set by tests/conftest.py): `note_answer` and `note_result` check what the engine
really answers against its shape and keep the mismatches in `MISMATCHES`. They never raise and do nothing otherwise."""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import common
from .kernel import (ALIASES, DEFAULT, SHAPES, F, Registry, ShapeError, alias, json_schema, shape, typescript,
                     validate)

AREAS = (common,)


def _merged(which: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for area in AREAS:
        for key, name in getattr(area, which).items():
            if key in out:
                raise ShapeError(f"{which}: {key!r} is mapped in two modules")
            if name not in SHAPES:
                raise ShapeError(f"{which}: {key!r} names {name!r}, which is no shape")
            out[key] = name
    return out


ANSWERS: dict[str, str] = _merged("ANSWERS")
RESULTS: dict[str, str] = _merged("RESULTS")

BRIDGE = Path(__file__).resolve().parents[3] / "hub-ui" / "src" / "lib" / "bridge"
FILES = {"types": BRIDGE / "types.gen.ts", "schemas": BRIDGE / "schemas.gen.json"}


def schemas_text() -> str:
    """`schemas.gen.json`: every shape and alias, and which shape answers which method and job."""
    body = {"$defs": DEFAULT.definitions(), "answers": ANSWERS, "results": RESULTS}
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
        if isinstance(answer, dict) and set(answer) == {"job_id"}:
            return
        _note(f"answer of {method}", ANSWERS.get(method), answer)
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
    found = [f"{where}: " + "; ".join(problems) for where, problems in MISMATCHES]
    MISMATCHES.clear()
    return found
