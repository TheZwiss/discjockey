"""Plans (issue 39, design §7.1): what a dry run saw, kept for the write that follows it.

A dry run answers its items (each with a key) and its command line saves them here, `<support>/plans/<12 hex>.json`:
the plan file a dry run writes (beside `cache/` and, for a read job, its record under `jobs/`).
`<write> --plan plan:<12 hex>` then runs only those items, each asked again as it
runs (the engine's own per-item checks stay): `bind` is the rule that tells an item that still stands from one whose
answer changed (skipped, `changed`) and one that is new since the plan (left out, listed under `new_since_plan`).
It is the window's sync rule (`run.select_actions` with `new_since_preview`) made general, so the write jobs of the
command line and the window's Start use one decision.

The id is the hash of the plan's kind, its music folder and its sorted item keys: the same dry run twice is the same
plan. A plan is good for 24 hours and for the music folder it was made in. An older one, or one of another folder, is
`PlanExpired` (it carries the dry run to repeat as its `next`); a plan that was never made or has been pruned is
`UnknownPlan`. Plans are pruned at every save (a week after they were made, so that a plan that ran out says so
rather than "unknown")."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from ..problem import Problem

PLANS_DIR = "plans"
LIFETIME = timedelta(hours=24)  # how long a plan can be run
KEPT = timedelta(days=7)        # how long its file stays (so that "expired" can be told from "unknown")
ID_FORMAT = re.compile(r"plan:([0-9a-f]{12})")
EXPIRED = "That plan is {why}. Make a new one."


class UnknownPlan(Problem):
    """There is no plan with that id (never made, pruned, or not an id at all): `bad_args`, `unknown_id`."""

    def __init__(self, plan_id: str):
        super().__init__(f"There is no plan {plan_id}. A dry run makes one: its answer says its id.",
                         reason="unknown_id")


class PlanExpired(Problem):
    """The plan is more than 24 hours old, or was made for another music folder: `refused`, `plan_expired`, with the
    dry run to repeat as `next`."""

    def __init__(self, why: str, command: str | None):
        next = [{"run": f"{command} --dry-run", "why": "makes a new plan"}] if command else []
        super().__init__(EXPIRED.format(why=why), reason="plan_expired", next=next)


@dataclass(frozen=True)
class Plan:
    id: str
    kind: str
    root: str | None
    created: datetime
    items: Mapping[str, object]  # item key -> the answer the dry run gave for it
    extra: Mapping[str, object] = field(default_factory=dict)

    @property
    def command(self) -> str | None:
        """The command line of the dry run that made the plan, when it said (`extra["command"]`)."""
        command = self.extra.get("command")
        return command if isinstance(command, str) else None


@dataclass(frozen=True)
class Binding:
    """What a run with a plan does with the items it finds now (`Plan.bind`). `run` are the plan's keys that still
    stand, in the plan's order; `changed` are the plan's keys whose answer is another now or that are gone; `new` are
    the keys the plan has not seen. The run does `run`, answers `changed` as `skipped` with `reason: "changed"` and
    lists `new` under `new_since_plan`."""
    run: tuple[str, ...]
    changed: tuple[str, ...]
    new: tuple[str, ...]


def items_of(answer: Mapping) -> dict[str, object] | None:
    """The items of a dry run's answer: `answer["items"]` is a list of rows, each with its own `key` (a string, unique:
    the id the person addresses the item by). None when the answer has no such list, so it makes no plan. The one rule
    every dry run of the command line follows; the key is the item's identity, the row its answer."""
    rows = answer.get("items")
    if not isinstance(rows, list) or not all(isinstance(r, Mapping) and isinstance(r.get("key"), str) for r in rows):
        return None
    keys = [r["key"] for r in rows]
    return {r["key"]: dict(r) for r in rows} if len(set(keys)) == len(keys) else None


def _dir(support: Path) -> Path:
    return Path(support) / PLANS_DIR


def plan_id(kind: str, root: str | None, keys: list[str] | tuple[str, ...]) -> str:
    """`plan:<12 hex>`: the hash of the kind, the music folder and the sorted item keys."""
    text = json.dumps([kind, root, sorted(keys)], ensure_ascii=False, separators=(",", ":"))
    return "plan:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _file(support: Path, identifier: str) -> Path | None:
    """The plan's file, or None when `identifier` is not a plan id (it is typed by a person: never made into a path
    unchecked)."""
    found = ID_FORMAT.fullmatch(identifier) if isinstance(identifier, str) else None
    return _dir(support) / f"{found.group(1)}.json" if found else None


def _prune(support: Path, now: datetime) -> None:
    for file in _dir(support).glob("*.json"):
        try:
            if now - datetime.fromtimestamp(file.stat().st_mtime) > KEPT:
                file.unlink()
        except OSError:
            continue  # gone already, or not ours to remove: the next save tries again


def save(support: Path, kind: str, root: str | None, items: Mapping[str, object], extra: Mapping[str, object] | None = None,
         *, now: datetime | None = None) -> str:
    """Stores a dry run's plan and returns its id. `items` maps each item's key to the answer the dry run gave for it
    (anything JSON can hold); `extra` is what else the run needs to know (a sync's read id and records generation,
    the dry run's own `command`). The same dry run again is the same id and replaces the file (the 24 hours start
    over). Old plans are pruned first."""
    now = now or datetime.now()
    identifier = plan_id(kind, root, list(items))
    folder = _dir(support)
    folder.mkdir(parents=True, exist_ok=True)
    _prune(support, now)
    body = {"v": 1, "id": identifier, "kind": kind, "root": root, "created": now.isoformat(timespec="seconds"),
            "items": dict(items), "extra": dict(extra or {})}
    handle, tmp = tempfile.mkstemp(dir=folder, prefix=".plan-", suffix=".tmp")  # inside plans/: nothing else is written
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _file(support, identifier))
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return identifier


def load(support: Path, identifier: str, root: str | None, *, now: datetime | None = None) -> Plan:
    """The plan `identifier`, to run in the music folder `root`. `UnknownPlan` when there is no such plan (an id that
    is none, no file, or a file that is not a plan); `PlanExpired` when it is older than 24 hours or was made for
    another music folder."""
    file = _file(support, identifier)
    if file is None:
        raise UnknownPlan(str(identifier))
    try:
        body = json.loads(file.read_text(encoding="utf-8"))
        plan = Plan(body["id"], body["kind"], body["root"], datetime.fromisoformat(body["created"]),
                    dict(body["items"]), dict(body.get("extra") or {}))
        if body["v"] != 1 or plan.id != identifier:
            raise ValueError(identifier)
    except (OSError, ValueError, KeyError, TypeError):
        raise UnknownPlan(identifier) from None
    if plan.root != root:
        raise PlanExpired("for another music folder", plan.command)
    if (now or datetime.now()) - plan.created > LIFETIME:
        raise PlanExpired("more than a day old", plan.command)
    return plan


def bind(plan: Plan, now: Mapping[str, object]) -> Binding:
    """The plan against the items a run finds now (`now`: item key -> the answer the engine gives today). An item
    stands when it is in both with the same answer; one whose answer is another, or that is gone, is `changed`; one
    only `now` has is `new`."""
    run, changed = [], []
    for key, then in plan.items.items():
        (run if key in now and now[key] == then else changed).append(key)
    return Binding(tuple(run), tuple(changed), tuple(k for k in now if k not in plan.items))
