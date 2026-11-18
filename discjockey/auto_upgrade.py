"""Auto-upgrade, the sync's last phase (issue 33 stage C; design rekordbox-repoint §2.5; plan stage C §0, §1.2).

With Settings' `auto_upgrade` on (the default), a sync ends with one AIFF batch that does Same track for exactly the
set Upgrade all would do, while rekordbox is closed. This module holds what decides that set, what keeps a refusal
from being decoded again at every sync, and the phase itself (`run_phase`), which `run.execute` and
`run.finish_quietly` call once the run reached its end.

- `plan` says what the phase would do now (`Planned`): the tracks it runs, the ones that wait for rekordbox, the ones
  it leaves alone because a recorded refusal still holds. The set is `views.upgrade_ready_keys(state, held)` (To-do's
  Upgrade ready list, hidden ones left out; `held` are the plan's question keys) filtered by
  `eligible.same_track_quick` with `batches.present` and rekordbox's `Status`: the same test `HubApi.upgrade_all`
  counts with (`same_track is None`), so the Sync line, To-do's count and the phase can't differ. The library is
  asked for its `Status` only when a track of the set isn't an AIFF (an AIFF swap needs nothing from it), running or
  not, so a library Discjockey can't open keeps its tracks out of the set even while rekordbox runs. rekordbox
  running then means everything in the set waits, except the tracks a recorded refusal still holds (sorted as the
  Sync page's count sorts them, so the two always agree: an analysis record counts as holding, `space` and
  `needs_choice` are checked against the drive and the two files), and nothing else of its library is read (no
  stamps).
- `auto_refused` (on the parked upgrade, `e["upgrade"]["auto_refused"]`): `{"reason", "message", "at", "anlz":
  {path: mtime_ns} | None, "free": int | None, "files": {path: mtime_ns} | None}` for the refusals the phase records
  (`timing`, `not_analysed`, `cloud`, `space`, and `needs_choice` when the two files could not be compared at all).
  `refusal_holds` (pure) says whether one still holds: for the first three, while the analysis
  files of every rekordbox track of the file are the same set with the same mtimes as recorded (rekordbox analysing
  the track again changes them, a first analysis adds them; `stamps` reads them with one read open of the library);
  for `space`, while the drive's free space is not larger than recorded (`free_now`); for `needs_choice`, while the
  current file and the parked one have the mtimes recorded (`file_stamps`: a comparison that failed is not repeated
  at every sync, and a measurement that says "a different edit" is stored on the upgrade by the step instead). A
  record whose stamp is None (it could not be read) never holds. The record steers only this phase: Upgrade all, a selection and a single
  Replace are the user acting and run the track again.
- Placements (issue 43, D9, plan §4.5.4): the phase also puts the parked better version in for each song the user asked to
  download again whose file is missing (`missing.place_keys`, `eligible.place_quick`; `convert.place_parked`, the batch
  action `place`), whatever the switch says: Download again is the user's go for that song. They run first, in the same
  batch and the same rules (rekordbox closed, `auto_waits`, `auto_refused` for `space` and `cloud`). With the switch off
  ONLY placements run (`plan` is None when there is nothing to place, before anything of rekordbox is looked at). The
  phase runs after the planner has saved the song's current playlist folder (`convert.place_names` reads the stored
  entry's `folder`): `run.execute` and `run.finish_quietly` plan first, `auto_upgrade_only` has no plan to wait for.
- `run_phase` (plan §1.2): `plan`, then, with rekordbox closed, one batch (`batches.start(started_by="auto_upgrade",
  scope="sync")`, or `download_again` with the switch off, `batches.run(require_closed=True)`). rekordbox running when the phase starts: no batch row at all,
  every track of the set waits (its `auto_waits` mark is set), except those a held refusal leaves alone (listed as
  refused). Stop, rekordbox opening, `Busy` or Ctrl-C end the batch
  through `batches.end_auto` (its `planned` items are skipped, so To-do never offers Resume); the results and the
  records are filed from the batch as it ended. A Ctrl-C is re-raised once they are in the state. A dry run lists
  what would happen and writes nothing (no record, no log entry). Anything else that escapes is the run's crash.
- The records on the parked upgrade (plan §0.6): `auto_refused` for a refusal of those kinds (taken from the
  batch's item, with the stamps and the free space measured after the batch) and `auto_waits` (the ISO time
  of the sync that met rekordbox open for it). The phase clears both from every track it tries, and `auto_waits` from
  every track it reaches with rekordbox closed; both are saved with the run's state. An upgrade's undo brings the parked
  upgrade back without `auto_waits` (`upgrades.fields_before`): the song is no longer waiting for rekordbox. rekordbox open at the end of a
  sync is said as `waiting_line` (what happened), never as `before_start_line` (the Sync page's line before a start). Nothing else is recorded: other
  skips (`changed`, `unclean`, `busy`, ...) are in this run's results only, so the next sync simply tries again.
- `Outcome` is the run's block (the report, `--json`, the end screen); its keys are plan stage C §1.6. The results go
  into the run's log: `upgraded` (done; `placed_missing` for a placement), `upgrade_waits` (waiting, refused, not
  reached), `errors` (failed).
"""
from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import PurePosixPath

import sqlcipher3

from . import align, batches, convert, library, missing, report as rep, upgrades, words
from .events import CancelToken, Emit, Message, Result, no_emit
from .hub import views
from .hub.outcomes import REASONS
from .rekordbox import eligible, master
from .rekordbox import lock as rb_lock
from .rekordbox.eligible import Skip
from .rekordbox.locate import Place
from .rekordbox.offset import analysis_folder_files
from .settings import Settings
from .words import before_start_line, waiting_line  # the engine's words (`words.py`); console.py and the tests name them here

__all__ = ["ANLZ_REFUSALS", "FILE_REFUSALS", "PLACE_WAITS", "REFUSALS", "STEP", "WAITS", "Outcome", "Planned", "before_start_line",
           "file_stamps", "free_now", "plan", "refusal_holds", "run_phase", "stamps", "start_note", "waiting_line"]

ANLZ_REFUSALS = ("timing", "not_analysed", "cloud")  # recorded with the analysis files' stamps
FILE_REFUSALS = ("needs_choice",)                    # the two files could not be compared: recorded with their stamps
REFUSALS = (*ANLZ_REFUSALS, "space", *FILE_REFUSALS)  # the refusals the phase records on the upgrade
STEP = "upgrading at the end of the sync"            # what a crash note says the run was doing
# plan stage C §3 (binding): the waiting rows of the results, by the reason the track did not run
WAITS = {
    "rekordbox_open": "Waits for rekordbox to be closed: it is upgraded at your next sync, or press Upgrade all.",
    "not_reached": "The sync stopped before this one; it is upgraded at your next sync.",
    "busy": "Another Discjockey window or the Terminal was changing your rekordbox library; it is upgraded at your "
            "next sync.",
}
# the same rows for a placement (plan §5.4): what waits is the song's better version, put in at the next sync
PLACE_WAITS = {
    "rekordbox_open": "Waits for rekordbox to be closed: its better version goes in at your next sync.",
    "not_reached": "The sync stopped before this one; its better version goes in at your next sync.",
    "busy": "Another Discjockey window or the Terminal was changing your rekordbox library; its better version goes in "
            "at your next sync.",
    # rekordbox's library can't be read: the song is not dropped, it waits (the words of `batches.words`, its ending changed)
    "rekordbox_unreadable": batches.words("rekordbox_unreadable", "place").removesuffix(". Nothing was changed.")
                            + "; its better version goes in once it can.",
}
PLAN_CHANGED = REASONS["changed"].text  # a track of a plan's run whose answer is another now (`upgrade apply --plan` says it too)


@dataclass(frozen=True)
class Planned:
    """What the phase would do now. `run`: song keys in To-do's order; `waiting`: (key, "rekordbox_open" | "busy" | "rekordbox_unreadable");
    `refused`: (key, its `auto_refused` record), held and not tried; `rekordbox_running`: what `running()` said.
    `place`: which keys of `run`, `waiting` and `refused` are placements (Download again for a missing file with a
    parked better version, D9); `run` lists them first."""
    run: list[str]
    waiting: list[tuple[str, str]]
    refused: list[tuple[str, dict]]
    rekordbox_running: bool
    place: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Outcome:
    """The run's Auto-upgrade block. `results`: one dict per track, `{"track", "name", "state": "done" | "would" |
    "waiting" | "refused" | "failed", "reason", "message", "how", "action"}` (`action`: `same_track` | `place`, the
    placement for a missing file; `how`: `in_place` | `new_aiff` | `placed`).
    `refused` (state and count) is only a reason in `REFUSALS`, the ones To-do shows and the next sync leaves alone;
    a skip nothing is recorded for (`changed`, `unclean`, `other_library`, ...) is `waiting` for the next sync with
    its own reason and words."""
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


def refusal_holds(record: dict, anlz_now: Mapping[str, int] | None, free_now: int | None,
                  files_now: Mapping[str, int] | None = None) -> bool:
    """Whether a recorded refusal still holds (plan stage C §0.7): `anlz_now` are the track's analysis files now
    (`stamps`' value for it), `free_now` the free bytes on its drive now (`free_now`), `files_now` the stamps of its
    two files now (`file_stamps`). `needs_choice` is recorded when the two files could not be compared at all (a
    measurement that says "a different edit" is stored on the upgrade instead and takes the track out of the set): it
    holds while neither file has been touched. An unreadable stamp (None, on either side), an unknown reason or a
    record without its fact never holds, so the track is tried again."""
    reason = record.get("reason")
    if reason in ANLZ_REFUSALS:
        then = record.get("anlz")
        return isinstance(then, Mapping) and anlz_now is not None and dict(then) == dict(anlz_now)
    if reason in FILE_REFUSALS:
        then = record.get("files")
        return isinstance(then, Mapping) and bool(then) and files_now is not None and dict(then) == dict(files_now)
    if reason == "space":
        then = record.get("free")
        return (isinstance(then, int) and not isinstance(then, bool) and free_now is not None
                and free_now <= then)
    return False


def file_stamps(paths, e: dict) -> dict[str, int] | None:
    """The mtimes of the song's current file and of its parked upgrade, `{path: mtime_ns}`: what a `needs_choice`
    record holds on. None when either can't be read."""
    try:
        return {rel: (paths.root / rel).stat().st_mtime_ns for rel in (e["path"], e["upgrade"]["file"])}
    except (OSError, KeyError, TypeError):
        return None


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
        with rb_lock.reader_lock(paths.support) as free:  # shared, only while master.db is open (design §6.1)
            if not free:  # another Discjockey is changing rekordbox's library: not read now, so no record holds
                return dict.fromkeys(keys)
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
         place: Place | None, status: master.Status | None = None, quick: bool = False) -> Planned | None:
    """What the phase would do now, or None when there is nothing it may do: the switch is off and no song is waiting
    to be placed (`missing.place_keys`: Download again was asked, its file is missing, a better version is parked).
    With the switch off the set is the placements alone (Download again is the user's go for that song); nothing of
    rekordbox is looked at when there are none. `running` / `place` are rekordbox's process check and library (the real
    ones are `process.running` and `locate()`); `held` the plan's question keys. `status` is a rekordbox `Status` the
    caller already has (the hub's cached one): used as it is, nothing is opened for it.

    rekordbox running: the tracks of the set wait (`rekordbox_open`) except those a recorded refusal still holds
    (`refused`: the library is never read for them, so a record of the analysis kind counts as holding); of its
    library only the `Status` is read, and only for a set with a placement or a file that isn't an AIFF (the same set
    Upgrade all counts, plus the placements, plan stage C §0.3). Otherwise the set runs, minus the tracks a
    still-holding refusal leaves alone (`refused`); the records of the analysis kind are checked with one read open for
    all of them. Placements come first in `run`, `waiting` and `refused` order, and are named by `Planned.place`.

    `quick` is the Sync page's count before a start (plan §4): rekordbox's library is never opened, so a record of the
    analysis kind can't be checked and counts as holding (the track is `refused`, not counted as ready). A phase that
    meets rekordbox running sorts the records the same way, so its waiting count equals that page's `ready`."""
    keys = views.upgrade_ready_keys(state, held) if settings.auto_upgrade else []
    candidates = missing.place_keys(state)
    present = {k: batches.present(paths, state["tracks"][k]) for k in (*candidates, *keys)}
    # the file back on disk, or its drive away, leaves a song out whatever rekordbox says (`place_quick` asks the rest again)
    placing = [k for k in candidates
               if not isinstance(eligible.place_quick(state["tracks"][k], views.UNKNOWN_REKORDBOX, present[k]), Skip)]
    if not settings.auto_upgrade and not placing:
        return None
    is_running = bool(running())

    def eligible_keys(rb: master.Status) -> list[str]:
        return [k for k in keys if not isinstance(eligible.same_track_quick(state["tracks"][k], rb, present[k]),
                                                  Skip)]

    rb = status
    if rb is None:
        rb = views.UNKNOWN_REKORDBOX
        if placing or any(not _is_aiff(state["tracks"][k]) for k in eligible_keys(rb)):
            with rb_lock.reader_lock(paths.support) as free:  # shared, only while master.db is open (design §6.1)
                # one keyed open, only for a placement or a file that isn't an AIFF; a library another Discjockey is
                # changing is not opened: it is taken as readable, and the batch asks again under its own lock
                rb = master.status(place, lambda: is_running) if free else views.UNKNOWN_REKORDBOX
    verdicts = {k: eligible.place_quick(state["tracks"][k], rb, present[k]) for k in placing}
    # a library rekordbox can't read keeps the placement: it waits (`rekordbox_unreadable`), it is not dropped
    unreadable = [k for k, v in verdicts.items() if isinstance(v, Skip) and v.reason == "rekordbox_unreadable"]
    placed = [k for k, v in verdicts.items() if not isinstance(v, Skip)]
    ready = [*placed, *eligible_keys(rb)]
    unchecked = quick or is_running  # rekordbox's library is not read for the stamps: analysis records count as holding

    records = {k: r for k in ready if (r := _record(state["tracks"][k])) is not None}
    now = {} if unchecked else stamps(paths, [k for k, r in records.items() if r.get("reason") in ANLZ_REFUSALS],
                                      state, running=lambda: is_running, place=place)
    run: list[str] = []
    refused: list[tuple[str, dict]] = []
    for k in ready:
        record, e = records.get(k), state["tracks"][k]
        if record is not None and (
                (unchecked and record.get("reason") in ANLZ_REFUSALS)
                or refusal_holds(record, now.get(k), free_now(paths, e) if record.get("reason") == "space" else None,
                                 file_stamps(paths, e) if record.get("reason") in FILE_REFUSALS else None)):
            refused.append((k, record))
        else:
            run.append(k)
    waiting = [(k, "rekordbox_unreadable") for k in unreadable]
    place_keys = frozenset((*placed, *unreadable))
    if is_running:
        return Planned([], [(k, "rekordbox_open") for k in run] + waiting, refused, True, place_keys)
    return Planned(run, waiting, refused, False, place_keys)


def start_note(block: dict | None) -> str | None:
    """The Sync page's before-start line for the phase, from its dry-run block (`Outcome.to_dict()`; None: nothing may
    run: the switch is off and no song waits to be placed): `words.before_start_line` when rekordbox is open (an
    upgrade of the set waits for it), `words.auto_plan_line` when it is closed, nothing when no upgrade is coming. The
    count is the one the page's `auto_upgrade.ready` has: the upgrades that would run plus those that would wait, a held
    refusal not among them. The placements for missing files (D9) are another clause (`words.place_plan_line`, with the
    switch off too), after the upgrades' line."""
    rows = (block or {}).get("results") or []
    coming = [r for r in rows if r["state"] in ("would", "waiting")]
    placing = [r for r in coming if r.get("action") == "place"]
    upgrading = [r for r in coming if r.get("action") != "place"]
    lines = []
    if upgrading:
        waits = any(r["state"] == "waiting" and r["reason"] == "rekordbox_open" for r in upgrading)
        lines.append(words.before_start_line(len(upgrading)) if waits else words.auto_plan_line(len(upgrading)))
    if placing:
        waits = any(r["state"] == "waiting" and r["reason"] in ("rekordbox_open", "rekordbox_unreadable")
                    for r in placing)  # a library that can't be read waits like an open rekordbox
        lines.append(words.place_plan_line(len(placing), waits))
    return " ".join(lines) or None


# --- the phase ---

def _name(e: dict) -> str:
    return f"{e.get('artist') or '?'} – {e.get('title') or '?'}"


def _how(e: dict, placed: bool = False) -> str:
    return "placed" if placed else "in_place" if upgrades.swap_possible(e) else "new_aiff"


def _folder(e: dict, where: Callable[[str], str] | None) -> str:
    """The folder a result is filed under: the song's playlist folder, else (an own song) the folder its file sits in,
    named as Sync names it."""
    return e.get("folder") or ((where(e["path"]) if where and e.get("path") else "") or "")


def _row(e: dict, key: str, state: str, reason: str | None, message: str | None, placed: bool = False) -> dict:
    return {"track": key, "name": _name(e), "state": state, "reason": reason, "message": message,
            "how": _how(e, placed), "action": "place" if placed else "same_track"}


def _waits(placed: bool) -> dict[str, str]:
    return PLACE_WAITS if placed else WAITS


def _rows(planned: Planned, before: Mapping[str, dict]) -> list[dict]:
    """The rows of the tracks the phase does not run: held refusals (their recorded words), then the ones that wait."""
    return ([_row(before[k], k, "refused", r.get("reason"), r.get("message"), k in planned.place)
             for k, r in planned.refused]
            + [_row(before[k], k, "waiting", why, _waits(k in planned.place)[why], k in planned.place)
               for k, why in planned.waiting])


def _change(state: dict, key: str, *, drop: Sequence[str] = (), add: Mapping[str, object] | None = None) -> bool:
    """Edits the keys of the parked upgrade's own records; False when the song has none or nothing changes."""
    e = state["tracks"].get(key)
    if not e or not e.get("upgrade"):
        return False
    up = {k: v for k, v in e["upgrade"].items() if k not in drop}
    up.update(add or {})
    if up == e["upgrade"]:
        return False
    state["tracks"][key] = {**e, "upgrade": up}
    return True


def _batch(paths, state: dict, batch_id: int, *, emit: Emit, token: CancelToken, running, place, compare, now
           ) -> tuple[batches.BatchResult, bool, bool]:
    """Runs the batch and, when Stop, rekordbox opening, `Busy` or Ctrl-C cut it short, ends it (`end_auto`). Returns
    its result as it ended, whether Stop (or Ctrl-C) did it and whether it was Ctrl-C."""
    try:
        return batches.run(paths, batch_id, emit=emit, token=token, compare=compare, now=now, running=running,
                           place=place, state=state, require_closed=True), False, False
    except batches.Refused as e:  # nothing could be done: the batch is done already
        return e.result, False, False
    except batches.Stopped:
        return batches.end_auto(paths, batch_id, "not_reached", now=now), True, False
    except batches.RekordboxOpen:
        return batches.end_auto(paths, batch_id, "rekordbox_open", now=now), False, False
    except batches.Busy:
        return batches.end_auto(paths, batch_id, "busy", now=now), False, False
    except KeyboardInterrupt:  # the step in work finished (deferred_interrupt); the rest waits
        return batches.end_auto(paths, batch_id, "not_reached", now=now), True, True


def _batch_rows(result: batches.BatchResult, before: Mapping[str, dict]) -> list[dict]:
    rows = []
    for item in result.results:
        e, placed = before[item.track], item.action == "place"
        if item.state == "done":
            rows.append(_row(e, item.track, "done", None, item.message, placed))
        elif item.state == "failed":
            rows.append(_row(e, item.track, "failed", None, item.message, placed))
        elif item.reason in _waits(placed):
            rows.append(_row(e, item.track, "waiting", item.reason, _waits(placed)[item.reason], placed))
        elif item.reason in REFUSALS:  # a refusal the phase records: To-do says why
            rows.append(_row(e, item.track, "refused", item.reason, item.message, placed))
        else:  # a skip it only reports (`changed`, `unclean`, ...): nothing is recorded, the next sync tries again
            rows.append(_row(e, item.track, "waiting", item.reason, item.message, placed))
    return rows


def run_phase(paths, state: dict, held: Collection[str], settings: Settings, log: rep.RunLog, *,
              emit: Emit = no_emit, token: CancelToken | None = None, running: Callable[[], bool],
              place: Place | None, compare=align.compare_files, now: Callable[[], datetime] = datetime.now,
              where: Callable[[str], str] | None = None, dry_run: bool = False, via: str = "terminal",
              only: Collection[str] | None = None, changed: Collection[str] = ()) -> Outcome | None:
    """The sync's Auto-upgrade phase (see the module docstring). `via`: where the sync started (its batch says so).
    `only` (a run with a plan, `sync run --auto-upgrade-only --plan`): the tracks that still stand as the plan saw them;
    the others of the set do not run: those the plan had and whose answer changed (`changed`) are rows that wait
    (reason `changed`), the ones new since the plan are left out. `state` is the run's snapshot, kept current by the
    batch's steps and saved by the caller; `held` the plan's question keys; `running` / `place` rekordbox's process
    check and library, `where` names an own song's folder for the results. Returns None when `plan` is (the switch is
    off and no song waits to be placed: nothing is read or written), else the run's block, which is also
    `log.auto_upgrade` (not in a dry run, which touches neither the log nor the records). The batch is started by
    `auto_upgrade` with the switch on, by `download_again` with it off."""
    planned = plan(paths, state, held, settings, running=running, place=place)
    if planned is None:
        return None
    token = token or CancelToken()
    before = {k: state["tracks"][k] for k in (*planned.run, *(k for k, _ in planned.refused),
                                               *(k for k, _ in planned.waiting))}
    left_out = [k for k in planned.run if only is not None and k not in only]
    if left_out:
        planned = replace(planned, run=[k for k in planned.run if k not in left_out])
    if dry_run:
        rows = [_row(before[k], k, "would", None, None, k in planned.place) for k in planned.run] + _rows(planned, before)
        return _outcome(None, None, rows, False, True)

    rows = _rows(planned, before)
    shown = {r["track"] for r in rows} | set(planned.run)
    rows += [_row(state["tracks"].get(k) or {}, k, "waiting", "changed", PLAN_CHANGED, k in planned.place)
             for k in changed if k not in shown]  # the plan had it, its answer is another now (or it is gone): the run leaves it as it is
    waiting_places = sum(1 for k, _ in planned.waiting if k in planned.place)
    if len(planned.waiting) > waiting_places:
        emit(Message("info", waiting_line(len(planned.waiting) - waiting_places)))
    if waiting_places:
        emit(Message("info", words.place_waiting_line(waiting_places)))
    batch_id, backup, stopped, interrupted = None, None, False, False
    if planned.run and token.cancelled:  # Stop came while the phase was being worked out: it does not start
        rows = [_row(before[k], k, "waiting", "not_reached", _waits(k in planned.place)["not_reached"],
                     k in planned.place) for k in planned.run] + rows
        stopped = True
    elif planned.run:
        places = sum(1 for k in planned.run if k in planned.place)
        if (n := len(planned.run) - places):
            emit(Message("info", f"Upgrading {n} track{'s' if n != 1 else ''} at the end of the sync..."))
        if places:
            emit(Message("info", words.placing_line(places)))
        items = [(k, "place" if k in planned.place else "same_track") for k in planned.run]  # placements first
        batch_id = batches.start(paths, items, scope="sync", via=via, now=now,
                                 started_by=batches.AUTO if settings.auto_upgrade else batches.DOWNLOAD_AGAIN)
        result, stopped, interrupted = _batch(paths, state, batch_id, emit=emit, token=token, running=running,
                                              place=place, compare=compare, now=now)
        backup = result.backup
        rows = _batch_rows(result, before) + rows

    changed = _write_records(paths, state, planned, rows, running=running, place=place, now=now)
    if changed:
        library.save_state(paths, state)
    _file(log, state, rows, where)
    outcome = _outcome(batch_id, backup, rows, stopped, False)
    log.auto_upgrade = outcome.to_dict()
    if interrupted:
        raise KeyboardInterrupt
    return outcome


def _outcome(batch: int | None, backup: str | None, rows: list[dict], stopped: bool, dry_run: bool) -> Outcome:
    count = lambda s: sum(1 for r in rows if r["state"] == s)  # noqa: E731
    return Outcome(batch, backup, count("done"), count("waiting"), count("refused"), count("failed"), stopped,
                   dry_run, rows)


def _still_same_edit(e: dict | None) -> bool:
    """Whether the song's parked upgrade is still stored as the same edit: a `needs_choice` skip that left it so is a
    comparison that failed (an unreadable file); one that measured a different edit has stored that, and the track
    is out of the set anyway."""
    return bool(e and e.get("upgrade") and (e["upgrade"].get("alignment") or {}).get("result") in ("exact", "shifted"))


def _write_records(paths, state: dict, planned: Planned, rows: list[dict], *, running, place, now) -> bool:
    """Writes the records into `state` (plan §0.6). Returns whether anything changed."""
    changed = False
    at = now().isoformat(timespec="seconds")
    waited = {r["track"] for r in rows if r["state"] == "waiting" and r["reason"] in WAITS}  # not tried: kept as they were
    for key in planned.run:  # tried now: what was recorded earlier is out of date
        if key not in waited:
            changed |= _change(state, key, drop=("auto_refused", "auto_waits"))
    for key, _ in planned.refused:  # reached with rekordbox closed
        changed |= _change(state, key, drop=("auto_waits",))
    new = [r for r in rows if r["track"] in planned.run and r["state"] == "refused" and r["reason"] in REFUSALS
           and (r["reason"] not in FILE_REFUSALS or _still_same_edit(state["tracks"].get(r["track"])))]
    now_stamps = stamps(paths, [r["track"] for r in new if r["reason"] in ANLZ_REFUSALS], state, running=running,
                        place=place)
    for r in new:
        key, e = r["track"], state["tracks"].get(r["track"])
        if e is None:
            continue
        record = {"reason": r["reason"], "message": r["message"], "at": at,
                  "anlz": now_stamps.get(key) if r["reason"] in ANLZ_REFUSALS else None,
                  "free": free_now(paths, e) if r["reason"] == "space" else None,
                  "files": file_stamps(paths, e) if r["reason"] in FILE_REFUSALS else None}
        changed |= _change(state, key, add={"auto_refused": record})
    for r in rows:  # met rekordbox open, at the start or mid-phase
        if r["state"] == "waiting" and r["reason"] == "rekordbox_open":
            changed |= _change(state, r["track"], add={"auto_waits": at})
    return changed


def _file(log: rep.RunLog, state: dict, rows: list[dict], where) -> None:
    """The rows as the run's results: `upgraded` (`placed_missing` for a placement), `upgrade_waits` and, for a failure,
    `errors`. A track the sync's
    check parked a moment ago (`upgrade_ready`) is told once, by its row here: the phase's result replaces the old one."""
    filed = {r["track"] for r in rows}
    log.results = [x for x in log.results if not (x.section == "upgrade_ready" and x.track_id in filed)]
    for r in rows:
        key = r["track"]
        e = state["tracks"].get(key) or {}
        artist, title = e.get("artist") or "", e.get("title") or ""
        folder = _folder(e, where)
        if r["state"] == "done":
            section = "placed_missing" if r.get("action") == "place" else "upgraded"
            log.add(Result(section, folder, artist, title, key, r["message"] or "", status=e.get("status"),
                           source=e.get("source"), path=e.get("path")))
        elif r["state"] == "failed":
            log.add(Result("errors", folder, artist, title, key, r["message"] or "", error_kind="other"))
        else:
            log.add(Result("upgrade_waits", folder, artist, title, key, r["message"] or ""))
