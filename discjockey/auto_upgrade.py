"""Auto-upgrade, the sync's last phase (issue 33 stage C; design rekordbox-repoint §2.5; plan stage C §0, §1.2).

With Settings' `auto_upgrade` on (the default), a sync ends with one AIFF batch that does Same track for exactly the
set Upgrade all would do, while rekordbox is closed. This module holds what decides that set and what keeps a
refusal from being decoded again at every sync; the phase itself (`run_phase`, the records, the run's block) is the
next task group's.

- `plan` says what the phase would do now (`Planned`): the tracks it runs, the ones that wait for rekordbox, the ones
  it leaves alone because a recorded refusal still holds. The set is `views.upgrade_ready_keys(state, held)` (To-do's
  Upgrade ready list, hidden ones left out; `held` are the plan's question keys) filtered by
  `eligible.same_track_quick` with `batches.present` and rekordbox's `Status`: the same test `HubApi.upgrade_all`
  counts with (`same_track is None`), so the Sync line, To-do's count and the phase can't differ. The library is
  asked for its `Status` only when a track of the set isn't an AIFF (an AIFF swap needs nothing from it), running or
  not, so a library Discjockey can't open keeps its tracks out of the set even while rekordbox runs. rekordbox
  running then means everything in the set waits, and nothing else of its library is read (no stamps).
- `auto_refused` (on the parked upgrade, `e["upgrade"]["auto_refused"]`): `{"reason", "message", "at", "anlz":
  {path: mtime_ns} | None, "free": int | None}` for the four refusals the phase records (`timing`, `not_analysed`,
  `cloud`, `space`). `refusal_holds` (pure) says whether one still holds: for the first three, while the analysis
  files of every rekordbox track of the file are the same set with the same mtimes as recorded (rekordbox analysing
  the track again changes them, a first analysis adds them; `stamps` reads them with one read open of the library);
  for `space`, while the drive's free space is not larger than recorded (`free_now`). A record whose `anlz` is None
  (it could not be read) never holds. The record steers only this phase: Upgrade all, a selection and a single
  Replace are the user acting and run the track again.
- `Outcome` is the run's block (the report, `--json`, the end screen); its keys are plan stage C §1.6.
"""
from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath

import sqlcipher3

from . import batches, convert
from .hub import views
from .rekordbox import eligible, master
from .rekordbox.eligible import Skip
from .rekordbox.locate import Place
from .rekordbox.offset import analysis_folder_files
from .settings import Settings

__all__ = ["ANLZ_REFUSALS", "REFUSALS", "Outcome", "Planned", "free_now", "plan", "refusal_holds", "stamps"]

ANLZ_REFUSALS = ("timing", "not_analysed", "cloud")  # recorded with the analysis files' stamps
REFUSALS = (*ANLZ_REFUSALS, "space")                 # the refusals the phase records on the upgrade


@dataclass(frozen=True)
class Planned:
    """What the phase would do now. `run`: song keys in To-do's order; `waiting`: (key, "rekordbox_open" | "busy");
    `refused`: (key, its `auto_refused` record), held and not tried; `rekordbox_running`: what `running()` said."""
    run: list[str]
    waiting: list[tuple[str, str]]
    refused: list[tuple[str, dict]]
    rekordbox_running: bool


@dataclass(frozen=True)
class Outcome:
    """The run's Auto-upgrade block. `results`: one dict per track, `{"track", "name", "state": "done" | "would" |
    "waiting" | "refused" | "failed", "reason", "message", "how"}` (`how`: `in_place` | `new_aiff` | None)."""
    batch: int | None
    backup: str | None
    done: int
    waiting: int
    refused: int
    failed: int
    stopped: bool
    dry_run: bool
    results: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


def _is_aiff(e: dict) -> bool:
    return PurePosixPath(e.get("path") or "").suffix.lower() in eligible.AIFF_EXTS


def _record(e: dict) -> dict | None:
    found = (e.get("upgrade") or {}).get("auto_refused")
    return found if isinstance(found, dict) else None


def free_now(paths, e: dict) -> int | None:
    """Free bytes on the drive of the track's folder, the measure of a `space` record (None when it can't be read)."""
    try:
        return convert.free_space((paths.root / e["path"]).parent)
    except OSError:
        return None


def refusal_holds(record: dict, anlz_now: Mapping[str, int] | None, free_now: int | None) -> bool:
    """Whether a recorded refusal still holds (plan stage C §0.7): `anlz_now` are the track's analysis files now
    (`stamps`' value for it), `free_now` the free bytes on its drive now (`free_now`). An unreadable stamp (None, on
    either side), an unknown reason or a record without its fact never holds, so the track is tried again."""
    reason = record.get("reason")
    if reason in ANLZ_REFUSALS:
        then = record.get("anlz")
        return isinstance(then, Mapping) and anlz_now is not None and dict(then) == dict(anlz_now)
    if reason == "space":
        then = record.get("free")
        return (isinstance(then, int) and not isinstance(then, bool) and free_now is not None
                and free_now <= then)
    return False


def _stamp(place: Place, entries) -> dict[str, int] | None:
    """The analysis files of `entries` with their mtimes; None when a folder or file can't be read (it vanished, or
    isn't ours to read), so the record made from it never holds."""
    found: dict[str, int] = {}
    try:
        for entry in entries:
            for file in analysis_folder_files(place, entry):
                found[file.relative_to(place.share).as_posix()] = file.stat().st_mtime_ns
    except OSError:
        return None
    return found


def stamps(paths, keys: Sequence[str], state: dict, *, running: Callable[[], bool], place: Place | None
           ) -> dict[str, dict[str, int] | None]:
    """The analysis files of each song's rekordbox tracks, `{path under share: mtime_ns}`, with one read open of
    rekordbox's library for all `keys` (nothing is opened for no keys). `{}` is a track with no analysis (or no
    rekordbox track); None means it could not be read: no rekordbox library, one that can't be opened, a song
    without a file, or an analysis file that vanished under the read."""
    out: dict[str, dict[str, int] | None] = dict.fromkeys(keys)
    if not keys or place is None or not place.db.is_file():
        return out
    try:
        with master.open_read(place, bool(running())) as m:
            index = m.index()
            for key in keys:
                e = state["tracks"].get(key)
                if not e or not e.get("path"):
                    continue
                out[key] = _stamp(place, m.entries_for(paths.root / e["path"], index))
    except (master.Unreadable, sqlcipher3.DatabaseError):
        return dict.fromkeys(keys)
    return out


def plan(paths, state: dict, held: Collection[str], settings: Settings, *, running: Callable[[], bool],
         place: Place | None, status: master.Status | None = None) -> Planned | None:
    """What the phase would do now, or None when the switch is off. `running` / `place` are rekordbox's process check
    and library (the real ones are `process.running` and `locate()`); `held` the plan's question keys. `status` is a
    rekordbox `Status` the caller already has (the hub's cached one): used as it is, nothing is opened for it.

    rekordbox running: every track of the set waits (`rekordbox_open`); of its library only the `Status` is read, and
    only for a set with a file that isn't an AIFF (the same set Upgrade all counts, plan stage C §0.3). Otherwise
    the set runs, minus the tracks a still-holding refusal leaves alone (`refused`); the records of the analysis
    kind are checked with one read open for all of them."""
    if not settings.auto_upgrade:
        return None
    is_running = bool(running())
    keys = views.upgrade_ready_keys(state, held)
    present = {k: batches.present(paths, state["tracks"][k]) for k in keys}

    def eligible_keys(rb: master.Status) -> list[str]:
        return [k for k in keys if not isinstance(eligible.same_track_quick(state["tracks"][k], rb, present[k]),
                                                  Skip)]

    rb = status
    if rb is None:
        rb = views.UNKNOWN_REKORDBOX
        if any(not _is_aiff(state["tracks"][k]) for k in eligible_keys(rb)):
            rb = master.status(place, lambda: is_running)  # one keyed open, only for a file that isn't an AIFF
    ready = eligible_keys(rb)
    if is_running:
        return Planned([], [(k, "rekordbox_open") for k in ready], [], True)

    records = {k: r for k in ready if (r := _record(state["tracks"][k])) is not None}
    now = stamps(paths, [k for k, r in records.items() if r.get("reason") in ANLZ_REFUSALS], state,
                 running=lambda: is_running, place=place)
    run: list[str] = []
    refused: list[tuple[str, dict]] = []
    for k in ready:
        record = records.get(k)
        if record is not None and refusal_holds(
                record, now.get(k), free_now(paths, state["tracks"][k]) if record.get("reason") == "space" else None):
            refused.append((k, record))
        else:
            run.append(k)
    return Planned(run, [], refused, False)
