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

Callers: the hub's jobs and `discjockey upgrade …` / `batch …` (stage B), Upgrade all and Auto-upgrade (stage C) and
Convert / Rename (stage D: their items are `convert` / `rename`; `RUNNABLE` grows with them).
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime

from . import align, convert, db, library, ops, report as rep, upgrades
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
           "UndoResult", "UndoStopped", "checked", "close_unrun", "recover", "result_of", "resume", "run", "start",
           "tracks_of", "undo"]

RUNNABLE = ("same_track",)  # the actions a batch can run today
OPERATION = "upgrade_same_track"  # operations.log's name for an item
NOTHING_ELIGIBLE = "None of these can be upgraded right now."
STOPPED_BY_REKORDBOX = ("rekordbox was opened, so Discjockey stopped after {done} of {total}. Quit rekordbox and "
                        "press Resume.")
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
    return f"{e.get('artist', '?')} - {e.get('title', track_id)}" if e else track_id


def _words(reason: str) -> str:
    text = REASON_WORDS.get(reason, reason)
    return f"{text[:1].upper()}{text[1:]}. Nothing was changed."


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
    `running`. Returns its id. ValueError for no items, an action no batch runs yet or an unknown starter."""
    if not items:
        raise ValueError("a batch needs at least one track")
    for _, action in items:
        if action not in RUNNABLE:
            raise ValueError(f"{action!r} is not an action a batch runs")
    with db.connect(paths.db_file) as conn:
        return db.start_aiff_batch(conn, "upgrade", started_by, scope, list(items), now())


def _present(paths, e: dict) -> eligible.Present:
    if not e.get("path"):
        return "missing"
    file = paths.root / e["path"]
    if file.is_file():
        return "here"
    return "missing" if library.online(file, library.watched_roots(paths)) else "away"


def _needs_write(paths, state: dict, tracks: Sequence[str]) -> Callable:
    """Session's start question: whether any of `tracks` needs a rekordbox write (plan §0.7): a file that isn't an
    AIFF and is in rekordbox's library (any such file, when the library can't be read while rekordbox runs)."""
    def needs(view) -> bool:
        for track in tracks:
            e = state["tracks"].get(track)
            if not e or not e.get("upgrade") or not e.get("path") or upgrades.swap_possible(e):
                continue
            if view is None or view.master.entries_for(paths.root / e["path"], view.index):
                return True
        return False
    return needs


def _session(paths, *, batch_id: int | None, tracks: Sequence[str], state: dict, running, place):
    options = {} if place is _DEFAULT else {"place": place}
    need = _needs_write(paths, state, tracks) if tracks else (lambda view: False)
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


def _item(paths, state: dict, session: Session, batch_id: int, item: AiffItemRow, compare, now, log) -> str | None:
    """One item. Returns "rekordbox_open" when rekordbox opened under it (the item is `planned` still), else None."""
    track = item.track
    e = state["tracks"].get(track)

    def skip(reason: str, message: str, detail: dict | None = None) -> None:
        _record(paths, batch_id, item, "skipped", reason, message, detail)
        log(track, e, reason, message)

    verdict = eligible.same_track_quick(e, session.state, _present(paths, e)) if e else Skip("no_upgrade")
    if isinstance(verdict, Skip):
        skip(verdict.reason, _words(verdict.reason))
        return None
    upgrade = dict(e["upgrade"])
    try:
        if upgrades.swap_possible(e):
            result = upgrades.swap(paths, state, track, upgrade, compare, now, session=session,
                                   batch=(batch_id, item.seq))
        else:
            result = convert.same_track(paths, state, track, upgrade, session=session, compare=compare, now=now,
                                        batch=(batch_id, item.seq))
    except convert.Skipped as err:
        skip(err.reason, str(err), err.detail)
    except NeedsChoice as err:
        skip("needs_choice", str(err))
    except RekordboxOpened:
        return "rekordbox_open"
    except UpgradeProblem as err:
        _record(paths, batch_id, item, "failed", None, str(err))
        log(track, e, "failed", str(err))
    except Exception as err:  # noqa: BLE001 - one track's surprise must not stop the batch
        message = f"Could not upgrade {_name(e, track)} ({type(err).__name__}: {err}). Nothing more was changed."
        _record(paths, batch_id, item, "failed", None, message)
        log(track, e, "failed", message)
    else:
        log(track, e, "done", result.note)
    return None


def run(paths, batch_id: int, *, emit: Emit = no_emit, token: CancelToken | None = None,
        compare: upgrades.Compare = align.compare_files, now: Callable[[], datetime] = datetime.now,
        running: Callable[[], bool] | None = None, place=_DEFAULT, state: dict | None = None) -> BatchResult:
    """Works off the `planned` items of the `running` batch `batch_id` (see the module docstring). The caller holds
    the library lock and has already run `library.recover_pending` (which calls `recover`, marking every `running`
    batch `stopped`/`crash`): `start` must come after that, or this batch would be stopped before it runs. `state` is
    the caller's snapshot, kept current as the steps write (loaded when None); `running` / `place` are rekordbox's
    process check and library (tests; the real ones when omitted)."""
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

    def log(track: str, entry: dict | None, result: str, message: str) -> None:
        ops.log_operation(paths, now(), track, entry, OPERATION, result, message)

    try:
        if planned:
            with _session(paths, batch_id=batch_id, tracks=[i.track for i in planned], state=state, running=running,
                          place=place) as session:
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
    (then it ends); stopped batches with nothing left end too. Returns the ids that wait for Resume because of the
    crash. Items are never touched: a step's own recovery (`library.recover_pending`) decides them."""
    crashed = []
    with db.connect(paths.db_file) as conn:
        for batch_id in db.running_aiff_batches(conn):
            db.set_aiff_batch(conn, batch_id, state="stopped", stop_reason="crash")
            crashed.append(batch_id)
    _close_finished(paths, now)
    with db.connect(paths.db_file) as conn:
        return [i for i in crashed if db.aiff_batch(conn, i).state == "stopped"]


def _newest_first(paths, tracks: Sequence[str]) -> list[str]:
    with db.connect(paths.db_file) as conn:
        order = {t: db.aiff_item_of(conn, t) or (-1, -1) for t in tracks}
    return sorted(tracks, key=order.__getitem__, reverse=True)


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
    another window holds `rekordbox.lock` (nothing changed)."""
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
                try:
                    done = upgrades.undo(paths, state, track, session=session)
                except UndoRefused as err:
                    results.append(UndoItem(track, "refused", err.reason, str(err)))
                except UpgradeProblem as err:
                    results.append(UndoItem(track, "refused", None, str(err)))
                except Exception as err:  # noqa: BLE001 - one track's surprise must not stop the others
                    results.append(UndoItem(track, "failed", None,
                                            f"Could not undo {_name(e, track)} ({type(err).__name__}: {err})."))
                else:
                    results.append(UndoItem(track, "undone", None, done.note))
                    with db.connect(paths.db_file) as conn:
                        found = db.aiff_item_of(conn, track, batch)
                        if found is not None:
                            db.set_aiff_item(conn, found[0], found[1], "undone")
                    ops.log_operation(paths, now(), track, e, "undo_upgrade", "done", done.note)
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
