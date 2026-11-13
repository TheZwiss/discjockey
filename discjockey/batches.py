"""AIFF batches: Same track over a list of tracks, as one job (issue 33; design rekordbox-repoint §2.2, §5.6, §5.9,
§5.12; plan stage B §1.10).

A batch is a row in library.db (`db.start_aiff_batch`: the planned items, outside the move log) that `run` works off
in order. The caller holds the library lock and has recovered pending steps; `run` takes `rekordbox.lock` and opens
one `rekordbox.Session` for the whole batch (one read open and index, one backup before the first rekordbox write).
Per item, in order:

1. Stop (`token`) or rekordbox opening since the batch began (plan §0.7: a batch started with rekordbox closed
   stops at the next item, an AIFF swap included) ends the batch; the rest stays `planned`.
2. The item's eligibility is asked again (`eligible.same_track_quick`: an upgrade still parked, the file there, an
   alignment that is the same edit, a readable library for a file that isn't AIFF). What only the step can find out
   (the edit measured again, no waveform, a timing disagreement, a cloud track, too little space, an unclean library)
   comes back as its own refusal. A refused item is `skipped` with its reason (an `eligible.REASONS` key) and the
   batch goes on; any other failure is `failed` with its plain words and the batch goes on too.
3. An AIFF becomes an in-place swap (`upgrades.swap`: audio swapped, rekordbox's text written while rekordbox is
   closed), any other format `convert.same_track` (a new AIFF, rekordbox's track pointed at it). Both mark their item
   `done` in the transaction that ends their step, so a crash never leaves a finished step beside a `planned` item.

rekordbox opening during an item rolls that item back (it stays `planned`), and the batch stops with
`rekordbox_open`. The batch ends in one of these ways: it returns a `BatchResult` (state `done`; refusals and failures
are in its items), or raises `Stopped` (Stop; state `stopped`/`stop`), `RekordboxOpen` (`stopped`/`rekordbox_open`;
nothing changed when it came at the start), `Busy` (another window or the Terminal holds `rekordbox.lock`; nothing
changed, the batch is `stopped`/`busy`) or `Refused` (nothing in it could be done; state `done`). Each carries the
`BatchResult` as it stands. `resume` runs the `planned` items of a stopped batch again, `undo` puts a batch's (or any
tracks') done items back, newest first, in one session, `checked` ends the undo for tracks ("Done, checked in
rekordbox"), `recover` closes what a crash left (`library.recover_pending` calls it).

Stage C (Auto-upgrade, plan stage C §0.4, §0.5, §1.3): the sync's last phase starts a batch with
`started_by="auto_upgrade"` and runs it with `require_closed=True` (rekordbox running at the start refuses the whole
batch, an AIFF swap included: a track may be loaded on a deck). An auto batch is never resumed: when Stop,
rekordbox opening or `Busy` ends it, the phase calls `end_auto`, which skips its `planned` items and ends it `done`
with its backup kept (its done items keep their undo and check cards); `recover` does the same for one a crash left
`running`, so the next sync plans afresh and To-do never offers Resume for it.

Callers: the hub's jobs and `discjockey upgrade …` / `batch …` (stage B), Upgrade all and Auto-upgrade (stage C) and
Convert / Rename (stage D).

Stage D (plan §0.13, §1.6): an item's action is `same_track`, `convert` (`convert.convert_file`) or `rename`
(`rename.rename_file`); the batch's kind follows (`upgrade`, `convert`, or `mixed` with a `same_track` item). A Convert
or Rename item asks `eligible.aiff_action` with the file's fresh facts first: an item whose answer changed (a Convert
whose file is a clean AIFF now, a Rename whose file needs converting) is `skipped` with the new answer's reason and
words, never switched to the other action. The steps ask again and refuse what only they can find out. A Convert that
lands on the song's ID because its old file held the clean name goes on to give the file its clean name in the same
item (`convert._then_rename`): one item, the final result. A batch's session counts a Convert or Rename item as a
rekordbox write when its file is in rekordbox's library, whatever its format; operations.log names the steps
`aiff_convert` / `aiff_rename` (a Same track item stays `upgrade_same_track`).
"""
from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime

from . import align, audio, convert, db, library, ops, rbstep, rename, report as rep, upgrades
from .events import BatchProgress, Cancelled, CancelToken, Emit, Result, no_emit
from .models import AiffBatchRow, AiffItemRow
from .rekordbox import Session, eligible
from .rekordbox import session as rbsession
from .rekordbox.eligible import Skip
from .rekordbox.preview import REASON_WORDS
from .rekordbox.session import BUSY, Busy
from .rekordbox.write import RekordboxOpened
from .upgrades import NeedsChoice, UndoRefused, UpgradeProblem

__all__ = ["BUSY", "Busy", "BatchResult", "ItemResult", "RekordboxOpen", "Refused", "Stopped", "UndoItem",
           "UndoResult", "UndoStopped", "checked", "close_unrun", "end_auto", "present", "recover", "result_of",
           "resume", "run", "start", "tracks_of", "undo"]

RUNNABLE = ("same_track", "convert", "rename")  # the actions a batch can run
AUTO = "auto_upgrade"  # `started_by` of the sync's Auto-upgrade batch
OPERATION = "upgrade_same_track"  # operations.log's name for a Same track item
OPERATIONS = {"same_track": OPERATION, "convert": "aiff_convert", "rename": "aiff_rename"}  # ... for each action
UNDO_OPERATIONS = {"upgrade": "undo_upgrade", "convert": "undo_convert", "rename": "undo_rename"}
LOG_PREFIXES = ("upgrade_", "aiff_")  # the log's names of a finished step (`_finished_order`)
NOTHING_ELIGIBLE = "None of these can be upgraded right now."
NOTHING_UNDONE = "None of these could be undone."
STOPPED_BY_REKORDBOX = ("rekordbox was opened, so Discjockey stopped after {done} of {total}. Quit rekordbox and "
                        "press Resume.")
# the console's variant of the line above: there is no Resume button to press
STOPPED_BY_REKORDBOX_CONSOLE = ("rekordbox was opened, so Discjockey stopped after {done} of {total}. Quit rekordbox "
                                "and run: discjockey batch resume {batch}.")
STOPPED_UNDO_BY_REKORDBOX = ("rekordbox was opened, so Discjockey stopped the undo after {done} of {total}. Quit "
                             "rekordbox and undo the rest.")
_DEFAULT = object()


@dataclass(frozen=True)
class ItemResult:
    """One item of a batch as it stands. `state`: planned | done | skipped | failed | undone; `reason` an
    `eligible.REASONS` key (skipped items only); `message` the words (a done item's note, a skip's or failure's
    reason in words); `path` the track's file after a done item; `rekordbox` what was written there
    (`{"entries": [ids], "kept": [fields]}`) or None."""
    track: str
    action: str
    state: str
    reason: str | None
    message: str | None
    path: str | None
    rekordbox: dict | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class BatchResult:
    """A batch's state and every item (the console's and the bridge's one shape, design §10)."""
    batch: int
    state: str  # running | stopped | done
    stop_reason: str | None  # stop | rekordbox_open | crash
    total: int
    done: int
    skipped: int
    failed: int
    results: list[ItemResult]
    backup: str | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class UndoItem:
    """One track of an undo. `state`: undone | refused (nothing changed; `reason` is the refusal key of
    `UndoRefused`, or None for a record that no longer applies) | failed | waiting (not reached: Stop or rekordbox
    opening ended the undo first; `reason` is `rekordbox_open` or None for Stop; nothing changed)."""
    track: str
    state: str
    reason: str | None
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class UndoResult:
    batch: int | None  # the batch undone as a whole, None for a list of tracks
    total: int
    undone: int
    refused: int
    failed: int
    results: list[UndoItem]

    def to_dict(self) -> dict:
        return asdict(self)


class UndoStopped(Cancelled):
    """Stop during an undo: the tracks done stay undone, the rest is `waiting`; `result` is the undo as far as it
    went (what `Stopped` is for a batch)."""

    def __init__(self, result: UndoResult):
        super().__init__()
        self.result = result


class Stopped(Cancelled):
    """Stop between two items: the batch is `stopped` (`stop`), its `planned` items wait for `resume`. Still a
    Cancelled, so a job reports it as stopped; `result` is the batch as far as it went."""

    def __init__(self, result: BatchResult):
        super().__init__()
        self.result = result


class RekordboxOpen(rbsession.RekordboxOpen):
    """rekordbox runs and the batch needs a rekordbox write (at the start: nothing was changed), or it opened
    during the batch (the item in work was rolled back). The batch is `stopped` (`rekordbox_open`); `resume` after
    rekordbox is quit. `result` is the batch as it stands; the message is for the user. An undo raises it too
    (`undo`): `result` is then its `UndoResult`, the tracks not reached listed as `waiting`."""

    def __init__(self, result: BatchResult | UndoResult):
        if isinstance(result, UndoResult):
            done = sum(1 for i in result.results if i.state != "waiting")
            super().__init__(upgrades.UNDO_REFUSED["rekordbox_open"] if not done else
                             STOPPED_UNDO_BY_REKORDBOX.format(done=done, total=result.total))
        else:
            done = result.total - sum(1 for i in result.results if i.state == "planned")
            super().__init__(convert.REKORDBOX_OPEN if not done else
                             STOPPED_BY_REKORDBOX.format(done=done, total=result.total))
        self.result = result


class Refused(Exception):
    """Nothing in the batch could be done and nothing failed: every item was skipped. The message is the one item's
    own reason, or the general sentence for several."""

    def __init__(self, result: BatchResult):
        skipped = [i for i in result.results if i.state == "skipped"]
        super().__init__(skipped[0].message if len(result.results) == 1 and skipped and skipped[0].message
                         else NOTHING_ELIGIBLE)
        self.result = result


def _name(e: dict | None, track_id: str) -> str:
    return f"{e.get('artist', '?')} – {e.get('title', track_id)}" if e else track_id


# What a Convert or Rename item says where the Same track's words don't fit (plan stage D §3, "Skipped list": the words
# of `rbstep.CONVERT_REFUSED`, whole sentences, are used as they stand)
FILE_WORDS = {
    "rekordbox_unreadable": "Discjockey can't open this rekordbox version's library yet, so it can't point your "
                            "rekordbox track at the file. Nothing was changed.",
    # a Convert item meets `clean_aiff` only when its answer became Rename: the file is a clean AIFF, its name isn't
    "clean_aiff": "This file is a clean AIFF already: Give it its clean name.",
}
SWITCHED = {"convert": "clean_aiff", "rename": "needs_convert"}  # the reason of an item whose answer changed


def words(reason: str, action: str = "same_track", why: str | None = None) -> str:
    """The words of a skip (`reason` an `eligible.REASONS` key) for an item of `action`. A Convert or Rename item says
    `rbstep.CONVERT_REFUSED`'s sentences (rekordbox lower case, no "upgrade"); `why` (a `rename.BLOCKED_WHY` text)
    fills `rename_blocked`'s `{reason}`."""
    if action != "same_track":
        if reason == "rename_blocked":
            return rbstep.REFUSED[reason].format(reason=why or rename.BLOCKED_WHY["unreadable"])
        if text := FILE_WORDS.get(reason) or rbstep.CONVERT_REFUSED.get(reason):
            return text
    text = REASON_WORDS.get(reason, reason)
    if not text.startswith("rekordbox"):  # rekordbox is written in lower case, a sentence's start included
        text = f"{text[:1].upper()}{text[1:]}"
    return f"{text}. Nothing was changed."


def _item_result(item: AiffItemRow) -> ItemResult:
    found = item.result if isinstance(item.result, dict) else {}
    message = found.get("note") or found.get("message") or (item.reason if item.state == "failed" else None)
    return ItemResult(item.track, item.action, item.state, item.reason if item.state == "skipped" else None,
                      message, found.get("path"), found.get("rekordbox"))


def _batch_result(row: AiffBatchRow) -> BatchResult:
    counts = row.counts
    return BatchResult(row.id, row.state, row.stop_reason, len(row.items), counts["done"], counts["skipped"],
                       counts["failed"], [_item_result(i) for i in row.items], row.backup)


def _row(paths, batch_id: int) -> AiffBatchRow:
    with db.connect(paths.db_file) as conn:
        row = db.aiff_batch(conn, batch_id)
    if row is None:
        raise ValueError(f"there is no AIFF batch {batch_id}")
    return row


def result_of(paths, batch_id: int) -> BatchResult:
    """A stored batch as `run` returns it (`batch show`, the To-do page). ValueError when there is no such batch."""
    return _batch_result(_row(paths, batch_id))


def tracks_of(paths, batch_id: int) -> list[str]:
    """The songs a batch did (its `done` items), in the order it did them."""
    return [i.track for i in _row(paths, batch_id).items if i.state == "done"]


def start(paths, items: Sequence[tuple[str, str]], *, started_by: str = "user", scope: str | None = None,
          now: Callable[[], datetime] = datetime.now) -> int:
    """Records a batch of `items` ((song key, action) pairs, all `planned`) before anything runs; it starts
    `running`. Returns its id. The batch's kind follows its actions (plan stage D §0.13): `same_track` only →
    `upgrade`, `convert` / `rename` only → `convert`, both → `mixed`. ValueError for no items, an action no batch
    runs or an unknown starter."""
    if not items:
        raise ValueError("a batch needs at least one track")
    for _, action in items:
        if action not in RUNNABLE:
            raise ValueError(f"{action!r} is not an action a batch runs")
    actions = {action for _, action in items}
    kind = "upgrade" if actions == {"same_track"} else "convert" if "same_track" not in actions else "mixed"
    _close_planned_elsewhere(paths, {track for track, _ in items}, now)
    with db.connect(paths.db_file) as conn:
        return db.start_aiff_batch(conn, kind, started_by, scope, list(items), now())


def _close_planned_elsewhere(paths, tracks: set[str], now: Callable[[], datetime]) -> None:
    """A track is planned in one batch only: the unrun (`planned`) items of earlier stopped batches for `tracks`
    are skipped (`later_batch`), so repeated tries (Upgrade all meeting an open rekordbox again and again) leave no
    dead Resume behind. Their done items and Undo stay; a stopped batch with nothing left ends."""
    with db.connect(paths.db_file) as conn:
        touched = False
        for batch_id in db.unfinished_aiff_batches(conn):
            row = db.aiff_batch(conn, batch_id)
            if row.state != "stopped":
                continue
            for item in row.items:
                if item.state == "planned" and item.track in tracks:
                    db.set_aiff_item(conn, batch_id, item.seq, "skipped", "later_batch",
                                     {"message": words("later_batch")})
                    touched = True
    if touched:
        _close_finished(paths, now)


def present(paths, e: dict) -> eligible.Present:
    """Whether the track's file is `here`, `away` (its drive is not connected) or `missing` (`eligible.Present`)."""
    if not e.get("path"):
        return "missing"
    file = paths.root / e["path"]
    if file.is_file():
        return "here"
    return "missing" if library.online(file, library.watched_roots(paths)) else "away"


def _needs_write(paths, state: dict, items: Sequence[tuple[str, str]]) -> Callable:
    """Session's start question: whether any of `items` ((track, action) pairs) needs a rekordbox write (plan §0.7,
    §1.6): a Same track item whose file isn't an AIFF and is in rekordbox's library, a Convert or Rename item whose
    file is in it, whatever its format (any such file, when the library can't be read while rekordbox runs)."""
    def needs(view) -> bool:
        for track, action in items:
            e = state["tracks"].get(track)
            if not e or not e.get("path"):
                continue
            if action == "same_track" and (not e.get("upgrade") or upgrades.swap_possible(e)):
                continue
            if view is None or view.master.entries_for(paths.root / e["path"], view.index):
                return True
        return False
    return needs


def _session(paths, *, batch_id: int | None, items: Sequence[tuple[str, str]], state: dict, running, place,
             require_closed: bool = False):
    options = {} if place is _DEFAULT else {"place": place}
    if require_closed:  # every item counts as a rekordbox write: rekordbox running at the start refuses the batch
        need = lambda view: True  # noqa: E731
    else:
        need = _needs_write(paths, state, items) if items else (lambda view: False)
    return Session.open(paths, running=running, items_need_write=need, batch_id=batch_id, **options)


def _stop(paths, batch_id: int, reason: str) -> BatchResult:
    with db.connect(paths.db_file) as conn:
        db.set_aiff_batch(conn, batch_id, state="stopped", stop_reason=reason)
        return _batch_result(db.aiff_batch(conn, batch_id))


def _record(paths, batch_id: int, item: AiffItemRow, state: str, reason: str | None, message: str,
            detail: dict | None = None) -> None:
    """A skipped or failed item: its state, reason (a skipped item's key; a failure's words) and what to show."""
    with db.connect(paths.db_file) as conn:
        db.set_aiff_item(conn, batch_id, item.seq, state, reason if state == "skipped" else message,
                         {"message": message, **({"detail": detail} if detail else {})})


def _file_answer(paths, state: dict, session: Session, track: str, e: dict | None, action: str
                 ) -> tuple[str, str | None] | None:
    """What a Convert or Rename item's file says now (plan §1.6: fresh facts, `eligible.aiff_action`): None when the
    item's own action can run (the step asks again and may still refuse), else (reason, message or None) of its skip.
    An item whose answer changed (a Convert whose file is a clean AIFF now, a Rename whose file isn't one any more) is
    skipped with the new answer's reason, never switched. A library rekordbox can't be read (`rekordbox_unreadable`)
    is left to the step: it knows whether rekordbox runs (the batch stops) or Rename is blocked."""
    where = present(paths, e) if e else "missing"
    if where != "here":
        return ("away" if where == "away" else "file_missing"), None
    try:
        facts = audio.file_facts(paths.root / e["path"])
    except (RuntimeError, OSError):
        return None  # the step reads it again and says what is wrong with it
    try:
        clean = rename.clean_path(paths, state, track, e)
    except FileExistsError:
        clean = None  # the step says there is no free name
    name, verdict = eligible.aiff_action(e, facts, session.state, None, where, clean)
    if isinstance(verdict, Skip):
        return None if verdict.reason == "rekordbox_unreadable" else (verdict.reason, None)
    if name == action:
        return None
    reason = SWITCHED[action]
    return reason, words(reason, action)


def _item(paths, state: dict, session: Session, batch_id: int, item: AiffItemRow, compare, now, log) -> str | None:
    """One item. Returns "rekordbox_open" when rekordbox opened under it (the item is `planned` still), else None."""
    track = item.track
    action = item.action
    e = state["tracks"].get(track)
    operation = OPERATIONS[action]

    def skip(reason: str, message: str, detail: dict | None = None) -> None:
        _record(paths, batch_id, item, "skipped", reason, message, detail)
        log(track, e, reason, message, operation)

    if action == "same_track":
        verdict = eligible.same_track_quick(e, session.state, present(paths, e)) if e else Skip("no_upgrade")
        answer = (verdict.reason, None) if isinstance(verdict, Skip) else None
    else:
        answer = _file_answer(paths, state, session, track, e, action)
    if answer is not None:
        skip(answer[0], answer[1] or words(answer[0], action))
        return None
    try:
        if action == "convert":
            result = convert.convert_file(paths, state, track, session=session, now=now, batch=(batch_id, item.seq))
        elif action == "rename":
            result = rename.rename_file(paths, state, track, session=session, now=now, batch=(batch_id, item.seq))
        elif upgrades.swap_possible(e):
            result = upgrades.swap(paths, state, track, dict(e["upgrade"]), compare, now, session=session,
                                   batch=(batch_id, item.seq))
        else:
            result = convert.same_track(paths, state, track, dict(e["upgrade"]), session=session, compare=compare,
                                        now=now, batch=(batch_id, item.seq))
    except rbstep.Skipped as err:
        # Convert's own library refusal says "Choose New track" (Same track's words): this item says its own
        skip(err.reason, words(err.reason, action) if err.reason == "rekordbox_unreadable" and action == "convert"
             else str(err), err.detail)
    except NeedsChoice as err:
        skip("needs_choice", str(err))
    except RekordboxOpened:
        return "rekordbox_open"
    except UpgradeProblem as err:
        _record(paths, batch_id, item, "failed", None, str(err))
        log(track, e, "failed", str(err), operation)
    except Exception as err:  # noqa: BLE001 - one track's surprise must not stop the batch
        what = {"convert": "convert {name}", "rename": "give {name} its clean name"}.get(action, "upgrade {name}")
        message = f"Could not {what.format(name=_name(e, track))} ({type(err).__name__}: {err}). " \
                  "Nothing more was changed."
        _record(paths, batch_id, item, "failed", None, message)
        log(track, e, "failed", message, operation)
    else:
        log(track, e, "done", result.note, operation)
    return None


def run(paths, batch_id: int, *, emit: Emit = no_emit, token: CancelToken | None = None,
        compare: upgrades.Compare = align.compare_files, now: Callable[[], datetime] = datetime.now,
        running: Callable[[], bool] | None = None, place=_DEFAULT, state: dict | None = None,
        require_closed: bool = False) -> BatchResult:
    """Works off the `planned` items of the `running` batch `batch_id` (see the module docstring). The caller holds
    the library lock and has already run `library.recover_pending` (which calls `recover`, ending every `running`
    batch): `start` must come after that, or this batch would be ended before it runs. `state` is
    the caller's snapshot, kept current as the steps write (loaded when None); `running` / `place` are rekordbox's
    process check and library (tests; the real ones when omitted). `require_closed` (Auto-upgrade): the session's
    start check treats every item as needing a rekordbox write, so rekordbox running when the batch begins raises
    `RekordboxOpen` with nothing changed and no backup made, whatever the files are (an AIFF swap included). The
    session makes that check only when there is a rekordbox library to open; with none there is nothing to protect."""
    token = token or CancelToken()
    row = _row(paths, batch_id)
    if row.state != "running":
        raise ValueError(f"AIFF batch {batch_id} is {row.state}, not running")
    state = library.load_state(paths) if state is None else state
    planned = [i for i in row.items if i.state == "planned"]
    total = len(row.items)
    handled = total - len(planned)
    stop = None
    backup = row.backup

    def log(track: str, entry: dict | None, result: str, message: str, operation: str = OPERATION) -> None:
        ops.log_operation(paths, now(), track, entry, operation, result, message)

    try:
        if planned:
            with _session(paths, batch_id=batch_id, items=[(i.track, i.action) for i in planned], state=state,
                          running=running, place=place, require_closed=require_closed) as session:
                for item in planned:
                    try:
                        token.check()
                    except Cancelled:
                        stop = "stop"
                        break
                    if session.rekordbox_opened():
                        stop = "rekordbox_open"
                        break
                    emit(BatchProgress(batch_id, handled, total, item.track,
                                       _name(state["tracks"].get(item.track), item.track)))
                    stop = _item(paths, state, session, batch_id, item, compare, now, log)
                    if stop:
                        break
                    handled += 1
                    if session.backup is not None and session.backup.id != backup:
                        backup = session.backup.id
                        with db.connect(paths.db_file) as conn:
                            db.set_aiff_batch(conn, batch_id, state="running", backup=backup)
                if session.backup is not None:
                    backup = session.backup.id
    except Busy:  # another window or the Terminal changes rekordbox's library: nothing was done by this call
        _stop(paths, batch_id, "busy")
        raise
    except rbsession.RekordboxOpen:  # at the start: nothing was changed
        raise RekordboxOpen(_stop(paths, batch_id, "rekordbox_open")) from None
    except KeyboardInterrupt:  # Ctrl-C: the step in work finished (deferred_interrupt); the rest waits
        _stop(paths, batch_id, "stop")
        raise
    with db.connect(paths.db_file) as conn:
        if stop:
            db.set_aiff_batch(conn, batch_id, state="stopped", stop_reason=stop, backup=backup)
        else:
            db.set_aiff_batch(conn, batch_id, state="done", backup=backup, ended=now())
        result = _batch_result(db.aiff_batch(conn, batch_id))
    if result.done:
        rep.write_not_lossless(paths, state)  # the not-lossless list follows what the batch changed
    if stop == "stop":
        raise Stopped(result)
    if stop == "rekordbox_open":
        raise RekordboxOpen(result)
    emit(BatchProgress(batch_id, total, total, None, None))
    if not result.done and not result.failed and result.skipped:
        raise Refused(result)
    return result


def close_unrun(paths, batch_id: int, reason: str, message: str, *, now: Callable[[], datetime] = datetime.now
                ) -> BatchResult:
    """Ends a batch that did not run (the console's batch of one meeting rekordbox open or `Busy`): its `planned`
    items are `skipped` with `reason` (an `eligible.REASONS` key) and `message`, the batch is `done`. Leaves nothing
    for To-do to offer as Resume."""
    with db.connect(paths.db_file) as conn:
        row = db.aiff_batch(conn, batch_id)
        for item in row.items:
            if item.state == "planned":
                db.set_aiff_item(conn, batch_id, item.seq, "skipped", reason, {"message": message})
        db.set_aiff_batch(conn, batch_id, state="done", backup=None, ended=now())
        return _batch_result(db.aiff_batch(conn, batch_id))


def end_auto(paths, batch_id: int, reason: str, *, now: Callable[[], datetime] = datetime.now) -> BatchResult:
    """Ends an Auto-upgrade batch that Stop, rekordbox opening, `Busy` or a crash cut short (plan stage C §0.5): every
    `planned` item is `skipped` with `reason` (an `eligible.REASONS` key: `rekordbox_open`, `not_reached`, `busy`)
    and its words, and the batch is `done` with its backup id kept (unlike `close_unrun`: the done items still need
    it for their undo). No stop reason is stored; the items carry it. The done items are not touched. A batch that
    is `done` already comes back as it is. ValueError for a batch not started by `auto_upgrade` or one that isn't
    there; `reason` must be an `eligible.REASONS` key."""
    if reason not in eligible.REASONS:
        raise ValueError(f"{reason!r} is not a reason an item is skipped for")
    with db.connect(paths.db_file) as conn:
        row = db.aiff_batch(conn, batch_id)
        if row is None:
            raise ValueError(f"there is no AIFF batch {batch_id}")
        if row.started_by != AUTO:
            raise ValueError(f"AIFF batch {batch_id} was not started by Auto-upgrade")
        if row.state != "done":
            for item in row.items:
                if item.state == "planned":
                    db.set_aiff_item(conn, batch_id, item.seq, "skipped", reason, {"message": words(reason)})
            db.set_aiff_batch(conn, batch_id, state="done", ended=now())
        return _batch_result(db.aiff_batch(conn, batch_id))


def resume(paths, batch_id: int, **options) -> BatchResult:
    """Runs the `planned` items of a stopped batch again (their eligibility is asked again, as at the start). A
    stopped batch with nothing left is closed (`done`). ValueError unless the batch is `stopped`. `options` as
    `run`'s."""
    row = _row(paths, batch_id)
    if row.state != "stopped":
        raise ValueError(f"AIFF batch {batch_id} is {row.state}, not stopped")
    with db.connect(paths.db_file) as conn:
        if row.counts["planned"]:
            db.set_aiff_batch(conn, batch_id, state="running", stop_reason=None)
        else:
            db.set_aiff_batch(conn, batch_id, state="done", ended=options.get("now", datetime.now)())
            return _batch_result(db.aiff_batch(conn, batch_id))
    return run(paths, batch_id, **options)


def _close_finished(paths, now: Callable[[], datetime]) -> None:
    """A stopped batch with no `planned` item left has nothing to resume: it ends (`done`), and its backup is free
    for the prune."""
    with db.connect(paths.db_file) as conn:
        for batch_id in db.unfinished_aiff_batches(conn):
            row = db.aiff_batch(conn, batch_id)
            if row.state == "stopped" and not row.counts["planned"]:
                db.set_aiff_batch(conn, batch_id, state="done", backup=None, ended=now())


def recover(paths, *, now: Callable[[], datetime] = datetime.now) -> list[int]:
    """After a crash: every `running` batch is `stopped` (`crash`) and offers Resume, unless nothing is left in it
    (then it ends); stopped batches with nothing left end too. An Auto-upgrade batch is never resumed, running or
    stopped (the crash may have come between `run` ending it and the phase's `end_auto`): it ends through `end_auto`
    (`not_reached`). Returns the ids that wait for Resume because of the crash. Items are never touched, except an
    auto batch's `planned` ones: a step's own recovery (`library.recover_pending`, which runs first) decides what
    the item in work became."""
    crashed, auto = [], []
    with db.connect(paths.db_file) as conn:
        for batch_id in db.unfinished_aiff_batches(conn):
            row = db.aiff_batch(conn, batch_id)
            if row.started_by == AUTO:
                auto.append(batch_id)
            elif row.state == "running":
                db.set_aiff_batch(conn, batch_id, state="stopped", stop_reason="crash")
                crashed.append(batch_id)
    for batch_id in auto:
        end_auto(paths, batch_id, "not_reached", now=now)
    _close_finished(paths, now)
    with db.connect(paths.db_file) as conn:
        return [i for i in crashed if db.aiff_batch(conn, i).state == "stopped"]


def _finished_order(paths) -> dict[str, int]:
    """Track -> the line of operations.log where its latest finished upgrade step stands. The log is appended in the
    order steps finish, so the line number tells which came later even when two steps share a timestamp (they are
    written to the second)."""
    order: dict[str, int] = {}
    try:
        lines = paths.operations_log.read_text(encoding="utf-8").splitlines()
    except OSError:
        return order
    for n, line in enumerate(lines):
        try:
            op = json.loads(line)
        except ValueError:
            continue
        if isinstance(op, dict) and str(op.get("operation", "")).startswith(LOG_PREFIXES) \
                and op.get("result") == "done":
            order[op.get("track_id")] = n
    return order


def _newest_first(paths, tracks: Sequence[str]) -> list[str]:
    """`tracks`, the one whose step finished last first: by the log line of its latest finished upgrade (ties of the
    timestamps can't confuse it), then by its newest batch item (batch, seq: row ids). A track with neither (a record
    from before the log) comes last, in the order it was given."""
    finished = _finished_order(paths)
    with db.connect(paths.db_file) as conn:
        item = {t: db.aiff_item_of(conn, t) or (-1, -1) for t in tracks}
    return sorted(tracks, key=lambda t: (finished.get(t, -1), item[t]), reverse=True)


def _undo_kind(e: dict | None) -> str:
    """What the track's undo puts back: `rename` (Give it its clean name, or a Convert→Rename chain's second half),
    `convert` (Convert to AIFF) or `upgrade` (anything else)."""
    u = upgrades.upgrade_undo(e) if e else None
    if u and u.get("kind") == "rename":
        return "rename"
    return "convert" if u and u.get("kind") == "convert" and u.get("source") == "file" else "upgrade"


def undo(paths, target: int | Sequence[str], *, emit: Emit = no_emit, token: CancelToken | None = None,
         running: Callable[[], bool] | None = None, place=_DEFAULT, state: dict | None = None,
         now: Callable[[], datetime] = datetime.now) -> UndoResult:
    """Puts back a batch's `done` items (`target` an id) or the given tracks, newest first, through one
    `Session` (one `rekordbox.lock`, one backup before the first rekordbox write). A track whose undo is refused
    (relocated, a file changed, nothing to undo) stays as it is and is listed with its reason; the others go on.
    Each undone track's batch item becomes `undone`. Like a batch, an undo is one job with one quit: when any
    track's undo has to change rekordbox and rekordbox runs, nothing is undone (`RekordboxOpen`, every track
    `waiting`); when rekordbox opens meanwhile, the undo stops before the next track (`RekordboxOpen`, what was
    undone stays undone, the rest `waiting`). Stop between tracks raises `UndoStopped` the same way. Busy when
    another window holds `rekordbox.lock` (nothing changed).

    A Convert or a Give it its clean name is undone like a Same track (`upgrades.undo` dispatches by the track's undo
    record; the refusals say "conversion" / "clean name" through the step's own `UndoRefused(converted=/renamed=)`).
    A Convert→Rename chain (the old file held the clean name: `convert._then_rename`) is two undos, newest first:
    the rename's, then the Convert's, one `undone` result with the Convert's note and one batch item `undone`. When
    the second is refused the first stands (the clean name is back, the conversion stays) and the track is listed
    `refused` / `failed` with words that say so; its item stays `done`. The result's section stays `upgrade_undone`
    for all three kinds (the UI maps it, D6)."""
    token = token or CancelToken()
    state = library.load_state(paths) if state is None else state
    batch = target if isinstance(target, int) else None
    tracks = [i.track for i in reversed(_row(paths, batch).items) if i.state == "done"] if batch is not None \
        else _newest_first(paths, list(dict.fromkeys(target)))
    results: list[UndoItem] = []

    def result() -> UndoResult:
        count = lambda s: sum(1 for r in results if r.state == s)  # noqa: E731
        return UndoResult(batch, len(tracks), count("undone"), count("refused"), count("failed"), results)

    def waiting(left: Sequence[str], reason: str | None) -> None:
        results.extend(UndoItem(t, "waiting", reason, "Not undone yet. Nothing was changed.") for t in left)

    def needs_rekordbox(view) -> bool:  # a track whose step wrote rekordbox needs it closed (plan §0.7)
        return any((upgrades.upgrade_undo(state["tracks"].get(t)) or {}).get("repoint") for t in tracks)

    stop = None
    try:
        with Session.open(paths, running=running, items_need_write=needs_rekordbox,
                          **({} if place is _DEFAULT else {"place": place})) as session:
            for n, track in enumerate(tracks):
                try:
                    token.check()
                except Cancelled:
                    stop = "stop"
                if stop is None and session.rekordbox_opened():
                    stop = "rekordbox_open"
                if stop:
                    waiting(tracks[n:], "rekordbox_open" if stop == "rekordbox_open" else None)
                    break
                e = state["tracks"].get(track)
                if batch is not None:
                    emit(BatchProgress(batch, n, len(tracks), track, _name(e, track)))
                kind = _undo_kind(e)
                try:
                    done = upgrades.undo(paths, state, track, session=session)
                except UndoRefused as err:
                    results.append(UndoItem(track, "refused", err.reason, str(err)))
                except UpgradeProblem as err:
                    results.append(UndoItem(track, "refused", None, str(err)))
                except Exception as err:  # noqa: BLE001 - one track's surprise must not stop the others
                    results.append(UndoItem(track, "failed", None, f"Could not undo {_name(e, track)} "
                                                                   f"({type(err).__name__}: {err})."))
                else:
                    if kind == "rename" and _undo_kind(state["tracks"].get(track)) == "convert":
                        # the Convert→Rename chain: the clean name is back, the conversion is the second undo
                        kind = "convert"
                        try:
                            done = upgrades.undo(paths, state, track, session=session)
                        except Exception as err:  # noqa: BLE001 - the first half stands; say so, go on
                            half = (f"The clean name is back, but the conversion could not be undone: {err}"
                                    if isinstance(err, UpgradeProblem) else
                                    f"The clean name is back, but the conversion could not be undone for "
                                    f"{_name(e, track)} ({type(err).__name__}: {err}).")
                            results.append(UndoItem(track, "refused" if isinstance(err, UpgradeProblem) else "failed",
                                                    getattr(err, "reason", None), half))
                            continue
                    results.append(UndoItem(track, "undone", None, done.note))
                    with db.connect(paths.db_file) as conn:
                        found = db.aiff_item_of(conn, track, batch)
                        if found is not None:
                            db.set_aiff_item(conn, found[0], found[1], "undone")
                    ops.log_operation(paths, now(), track, e, UNDO_OPERATIONS[kind], "done", done.note)
    except rbsession.RekordboxOpen:  # at the start: nothing was changed
        waiting(tracks, "rekordbox_open")
        raise RekordboxOpen(result()) from None
    _close_finished(paths, now)
    if stop == "rekordbox_open":
        raise RekordboxOpen(result())
    if stop:
        raise UndoStopped(result())
    if batch is not None:
        emit(BatchProgress(batch, len(tracks), len(tracks), None, None))
    return result()


def checked(paths, track_ids: Sequence[str], *, state: dict | None = None,
            now: Callable[[], datetime] = datetime.now) -> list[Result]:
    """"Done, checked in rekordbox" for each track that has a check: the reminder and with it the undo end, the kept
    download goes, and the backups only these undo records named are free for the prune. A track without a check is
    left out of the answer."""
    state = library.load_state(paths) if state is None else state
    out = []
    for track in dict.fromkeys(track_ids):
        e = state["tracks"].get(track)
        if e is not None and e.get("rekordbox_check"):
            out.append(ops.rekordbox_checked(paths, state, track))
    _close_finished(paths, now)
    return out
