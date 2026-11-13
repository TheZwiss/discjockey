"""Give it its clean name (issue 33; design rekordbox-repoint §7.1, §5.5, §5.8; plan stage D §0.10, §1.2): an own AIFF
of the library format (16-bit/44.1 kHz) with the right tags gets its clean name, `Artist - Title.aiff`, in the same
folder, and every rekordbox track of the file is pointed at the new name in the same step. The audio, the tags and
the file's facts stay as they are.

`rename_file(paths, state, track_id, *, session=…)` is one track's step (a batch's item, `batches.run`; the caller
holds the library lock and the batch's `rekordbox.Session`). Before anything is written it asks `eligible.rename`
with the file's fresh facts (`clean_aiff` must hold: not an AIFF 16/44.1 with the right tags is `needs_convert`; a
file with its clean name is `named_already`, a case-only difference included), looks the file up in rekordbox's
library (one read: no decoding, the audio doesn't change) and refuses with `Skipped("rename_blocked")` (design §8's
words, nothing moved) when the file has a rekordbox track and rekordbox can't follow: its library can't be opened or
a track is in Cloud Library Sync. rekordbox running with the file in its library is `RekordboxOpened`, as for
Convert (nothing written; the batch stops, which is why it isn't a per-track skip). A file no rekordbox track holds is
only moved. Then the journaled op `rename` (library.db `pending`), each step marked:

1. journal; 2. the batch's backup (`backed_up`; only with rekordbox rows); 3. `move_path(old → new)` (`placed`);
4. `Writer.repoint` (`committed`, its undo record journaled just before the `COMMIT`): `FolderPath`, `FileNameL`
(`OrgFolderPath` only where it equalled the old path), the analysis files' `PPTH` and their `contentFile` rows, one
transaction, `write.rename_change`; 5. the entry (`path` only), the file row (the same row, its facts written
again), the batch item and the check (`renamed`, its undo record) in one library.db transaction.

The new name is the clean one, or with the song's ID when another file holds it (`clean_path`: the file's own name
counts as free, and so do the names the track's own undo record reserves, which the new check replaces). A file that
already holds the ID name because the clean one is taken is `named_already`. The convert→rename chain (an AIFF whose
old file held the clean name: Convert lands on the ID name, then this step takes the clean one) calls `rename_file`
after `convert_file`; the old file sits in Superseded/ by then, so nothing holds the clean name.

**Recovery** (`recover_rename`, from `library.recover_pending`): the commit point is the `master.db` transaction, so
a step with rekordbox rows is decided by the rows' `FolderPath` now (`rbstep.side_of`): the old path → the file goes
back to its old name (an analysis file that holds the new `PPTH` comes back from the backup first, which needs
rekordbox closed: only then does the step wait, as for a drive; a crash before the repoint wrote anything never waits
for rekordbox); the new path → finished; neither (rekordbox changed the track since) → rekordbox left alone, the file
back at its old name, "needs your help". Another rekordbox library (or none) on this Mac → by the `committed` mark. A
step without rekordbox rows is decided by whether the file is at its new name. The batch the crash interrupted is
marked `stopped` (`crash`). Every file move goes through `move_path`; a music file is never deleted or overwritten
(`safe_rename` refuses a taken name).

**The convert→rename chain**: `convert.convert_file` on an AIFF whose old file held the clean name lands on the ID name
(both files exist until rekordbox's commit), and then calls `rename_file` with `after` = its result. The rename keeps
the Convert's check, with its undo, in its `before` (`fields_before(keep_undo=True)`): undoing the rename brings the
"converted" check back, and a second undo returns the original file. From the user's side the file kept its name and
became an AIFF, so the chain's result, its check (`reason` "converted", the Convert's kept edits) and its item say
Convert's words; the rename is an internal second step with an undo of its own (kind `rename`). A standalone rename
later says "renamed" and is "one step back only".

**Undo** (`undo_rename`, from `upgrades.undo`; design §5.9): the same file back to its old name (refused when another
file took it), rekordbox's identity columns and `PPTH` back where they still hold what the step wrote (else
`upgrades.UndoRefused("relocated")`, nothing changed); the journaled op `rename_undo`, decided after a crash by the
tracks' `FolderPath` (`recover_rename_undo`, dispatched in `library.recover_pending`).
"""
from __future__ import annotations

import os
from collections.abc import Callable, Collection
from contextlib import ExitStack
from dataclasses import asdict
from datetime import datetime
from pathlib import Path, PurePosixPath

import sqlcipher3

from . import audio, library, quality, rbstep, rekordbox
from .content_key import content_key
from .library import (
    DRIVE_GONE, NameReserver, Paths, Recovered, Waits, deferred_interrupt, drive_away, end_op, file_sha256,
    journal_op, mark_op, move_path, recover_renames, short_path, undo_paths, upgrade_undo, waits_offline,
    watched_roots,
)
from .events import Result
from .models import FileAudio
from .names import expected_stem, fold, id_tags
from .rekordbox import eligible, master, process
from .rekordbox import write as rbwrite
from .rekordbox.eligible import Skip
from .rekordbox.lock import Busy
from .rekordbox.session import Session
from .rekordbox.write import RekordboxOpened, WriteRefused
from .upgrades import UpgradeProblem, fields_before

# Design §8 (binding): the `{reason}` of "Refused, rename blocked"; "open" is what a screen says when it asks without
# running the step (rekordbox running, the file in its library: the step itself raises `RekordboxOpened`)
BLOCKED_WHY = {"open": "rekordbox is open", "unreadable": "rekordbox's library can't be opened",
               "cloud": "the track is in Cloud Library Sync"}

# Recovery (design §5.8, plan stage D §3): this step's words
WAIT_REKORDBOX = "Quit rekordbox so Discjockey can finish an interrupted clean-name change for {name}."
NOT_FINISHED = ("Giving {name} its clean name was not finished; your file and your rekordbox track are as they "
                "were.")
FINISHED = "Finished giving {name} its clean name."
NEEDS_HELP = ("An interrupted clean-name change for {name} needs your help: your rekordbox track was changed since "
              "and points at neither {old} nor {new}. Discjockey left rekordbox alone; your file stays at {old}.")
OTHER_MAC_DONE = ("Finished giving {name} its clean name on this Mac's side. Its rekordbox step was made in another "
                  "rekordbox library than this Mac's: open that one to check the track plays {new}.")
OTHER_MAC_UNDONE = ("Giving {name} its clean name was not finished; your file is as it was. Its rekordbox step was "
                    "made in another rekordbox library than this Mac's: check there that the track plays {old}.")
UNREADABLE_WAIT = ("Couldn't finish an interrupted clean-name change for {name} yet: Discjockey can't read your "
                   "rekordbox library to tell how far it got.")
UNCLEAN_WAIT = ("Couldn't finish an interrupted clean-name change for {name} yet: rekordbox didn't close normally. "
                "Open rekordbox, quit it, and Discjockey finishes the change.")
COULD_NOT_FINISH = "Could not finish an interrupted clean-name change for {name} yet: {err}"
STEP_FAILED = "Giving the file its clean name did not work ({err}). {message}"
STEP_NOT_FINISHED = "Giving the file its clean name did not finish ({err}). {message}"
ANLZ_LOST = (" The analysis files of the track couldn't be put back from the backup; analyse the track again in "
             "rekordbox.")


# Undo (design §5.9, plan stage D §3 has no sentence of its own): Same track's undo words with "the clean name" in the
# place of "the upgrade"; the sentences that say no step reuse rbstep's (UNDO_WAIT_REKORDBOX, UNDO_UNREADABLE_WAIT, …)
UNDO_FINISHED = "Finished undoing the clean name for {name}."
UNDO_NOT_FINISHED = ("Undoing the clean name for {name} was not finished: the clean name stands as it was, and you "
                     "can undo it again.")
UNDO_NEEDS_HELP = ("An interrupted undo for {name} needs your help: your rekordbox track was changed since and points "
                   "at neither {old} nor {new}. Discjockey left rekordbox alone; the clean name stands, with your "
                   "file at {new}.")
UNDO_OTHER_MAC_DONE = ("Finished undoing the clean name for {name} on this Mac's side. Its rekordbox step was made in "
                       "another rekordbox library than this Mac's: open that one to check the track plays {old}.")
UNDO_OTHER_MAC_UNDONE = ("Undoing the clean name for {name} was not finished: the clean name stands as it was. Its "
                         "rekordbox step was made in another rekordbox library than this Mac's: check there that the "
                         "track plays {new}.")


def blocked(why: str) -> rbstep.Skipped:
    """`Skipped("rename_blocked")` for `why`, a `BLOCKED_WHY` key (nothing was moved or written)."""
    return rbstep.skipped("rename_blocked", reason=BLOCKED_WHY[why])


def clean_path(paths: Paths, state: dict, track_id: str, e: dict, names: NameReserver | None = None) -> str | None:
    """The path Give it its clean name gives the track's file (relative to the music folder), without writing
    anything: `<its folder>/<Artist - Title>.aiff`, or with the song's ID when another file holds that name. The
    file's own name counts as free (it moves away first), and so do the names the track's own undo record reserves
    (the check this step writes replaces that record: a Convert that landed on the ID name because its old file held
    the clean one leaves that name reserved for its undo). The path the file has already when that is the answer
    (`eligible.rename` then says `named_already`, a case-only difference included). None for a song with no artist
    or title. FileExistsError when no name is free. `names`: a reserver to ask instead of a fresh one (the caller marks
    what it hands out as taken)."""
    if not (e.get("artist") or "").strip() or not (e.get("title") or "").strip():
        return None
    old = e["path"]
    names = names or NameReserver(paths.root, state)  # a plan over many files shares one (the names it hands out stay)
    names.release(old)
    if (u := upgrade_undo(e)) is not None:
        for p in undo_paths(u):
            names.release(p)
    folder = str(PurePosixPath(old).parent)
    stem = expected_stem(e["artist"], e["title"])
    for name in (stem, *(f"{stem} {tag}" for tag in id_tags(track_id))):
        rel = f"{folder}/{name}.aiff"
        if fold(rel) == fold(old):
            return old
        if not names.is_taken(rel):
            return rel
    raise FileExistsError(f"no free file name for {stem}.aiff in {folder}")


def _entries(session: Session, old_file: Path) -> list[rekordbox.Entry]:
    """The rekordbox tracks that hold `old_file` (none: nothing to point anywhere). Raises RekordboxOpened (rekordbox
    runs and holds the file, or its library can't be read because it is open), `Skipped` (`rename_blocked`: the
    library can't be opened, a track is in Cloud Library Sync; `unclean`)."""
    view = session.view()
    if view is None:
        if session.state.state == "none":
            return []  # no rekordbox on this Mac: the file is only moved
        if session.state.running:
            raise RekordboxOpened()
        raise blocked("unreadable")
    try:
        entries = view.master.entries_for(Path(os.path.abspath(old_file)), view.index)
    except (master.Unreadable, sqlcipher3.DatabaseError):
        raise blocked("unreadable") from None
    if entries:
        if session.running_at_start or session.rekordbox_opened():
            raise RekordboxOpened()
        if any(x.cloud for x in entries):
            raise blocked("cloud")
        if view.status.problem == "unclean":
            raise rbstep.skipped("unclean")
    return entries


def rename_file(paths: Paths, state: dict, track_id: str, *, session: Session,
                now: Callable[[], datetime] = datetime.now, batch: tuple[int, int] | None = None,
                after: Result | None = None) -> Result:
    """Give it its clean name for one track's own file (see the module docstring). `batch` = (AIFF batch, seq): its
    item is marked done with the step. `after`: the Convert's result when this is the convert→rename chain's second
    half (`convert.convert_file`): the new check keeps the Convert's check and undo in its `before`, and the result and
    the item say the Convert's words ("converted", the file now at its final name; the check's `reason` is "converted"
    too). Raises `Skipped` (nothing written:
    `eligible.rename`'s reasons, `rename_blocked`, `unclean`), `RekordboxOpened` (nothing written; the batch stops) or
    `UpgradeProblem` (a failure, nothing written, or the words of what recovery did)."""
    e = state["tracks"].get(track_id)
    if e is None or not e.get("path"):
        raise UpgradeProblem("This track has no file to rename. Nothing was changed.")
    old = e["path"]
    old_file = paths.root / old
    if not old_file.is_file():
        raise rbstep.skipped("file_missing" if library.online(old_file, watched_roots(paths)) else "away")
    try:
        info = quality.probe(old_file)
        facts = audio.file_facts(old_file)
    except (RuntimeError, OSError) as err:
        raise UpgradeProblem(f"Discjockey couldn't read {PurePosixPath(old).name} ({err}). Nothing was "
                             "changed.") from err
    try:
        new = clean_path(paths, state, track_id, e)
    except FileExistsError as err:
        raise UpgradeProblem(f"Discjockey found no free name for this file ({err}). Nothing was changed.") from err
    verdict = eligible.rename(e, facts, session.state, None, clean_path=new)
    if isinstance(verdict, Skip):
        if verdict.reason == "rekordbox_unreadable":  # the library can't be read, so the file's tracks are unknown
            if session.state.running:
                raise RekordboxOpened()
            raise blocked("unreadable")
        raise rbstep.skipped(verdict.reason)
    entries = _entries(session, old_file)
    new_abs = rbstep.abs_path(paths, new)
    changes = [rbwrite.rename_change(x, new_abs) for x in entries]
    splices = rbstep.plan_splices(session, entries, new_abs)
    file_audio = quality.file_audio(info)
    sha = file_sha256(old_file)
    op = {"kind": "rename", "source": "rename", "track_id": track_id, "batch": list(batch) if batch else None,
          "old": old, "new": new, "new_sha256": sha, "file_key": content_key(old_file),
          "entry": rbstep.with_audio({**e, "path": new}, file_audio),
          "before": fields_before(e, keep_undo=after is not None),
          "chain": None if after is None else {"note": after.note.replace(after.path, new, 1),
                                               "kept": list(((e.get("rekordbox_check") or {}).get("rekordbox")
                                                             or {}).get("kept") or [])},
          "audio": asdict(file_audio), "rekordbox": rbstep.op_rekordbox(session, changes, splices),
          "check": {"reason": "renamed" if after is None else "converted", "since": now().date().isoformat(),
                    "batch": batch[0] if batch else None},
          "marks": {"backed_up": False, "placed": False, "committed": False}}
    return _execute(paths, state, op, session, entries, changes, splices)


# --- the step ---

def _execute(paths: Paths, state: dict, op: dict, session: Session, entries: list[rekordbox.Entry],
             changes: list[rbwrite.RowChange], splices: list[rbwrite.AnlzChange]) -> Result:
    """Steps 1–5 of the module docstring for the journal entry `op`."""
    track_id, old, new = op["track_id"], op["old"], op["new"]
    roots = watched_roots(paths)
    with deferred_interrupt():  # a Ctrl-C waits until the step is at a safe point
        journal_op(paths, state, op)  # step 1
        rb = op["rekordbox"]
        if rb is not None:  # step 2
            try:
                rbstep.backup_tracks(session, track_id, entries, rb)
                op["marks"]["backed_up"] = True
                mark_op(paths, state, op)
            except BaseException as err:
                _drop(paths, state, op)
                rbstep.raise_refusal(err, op)
        try:  # step 3
            move_path(paths.root, old, new, None, roots)
        except BaseException as err:
            _drop(paths, state, op)
            if not isinstance(err, Exception):
                raise
            raise UpgradeProblem(f"Could not give the file its clean name ({err}). Nothing was changed.") from err
        op["marks"]["placed"] = True
        mark_op(paths, state, op)
        if rb is not None:  # step 4: the commit point
            try:
                with session.writer() as w:
                    w.repoint(changes, splices, prepared=lambda c: rbstep.journal_record(paths, state, op, c))
            except (WriteRefused, RekordboxOpened) as err:  # rolled back, analysis files as they were
                _roll_back(paths, state, op, roots)
                rbstep.raise_refusal(err, op)
            except Exception as err:  # decided by the track's path now, as after a crash
                message = _settle(paths, state, op, roots)
                if rbstep.finished_at(state, op, track_id, new):  # it failed after the commit; recovery finished it
                    return _result(op)
                raise UpgradeProblem(STEP_FAILED.format(err=err, message=message)) from err
            op["marks"]["committed"] = True
            mark_op(paths, state, op)
        try:  # step 5
            result = _finish(paths, state, op)
        except Exception as err:  # finish right now if the disk allows, else at the next start
            message = _settle(paths, state, op, roots)
            if rbstep.finished_at(state, op, track_id, new):
                return _result(op)
            raise UpgradeProblem(STEP_NOT_FINISHED.format(err=err, message=message)) from err
    return result


def _result(op: dict) -> Result:
    e, rb = op["entry"], op["rekordbox"]
    if op.get("chain"):  # the second half of a Convert: it says what the Convert said
        return Result("converted", e["folder"], e["artist"], e["title"], op["track_id"], op["chain"]["note"],
                      status=e.get("status"), source=e.get("source"), path=op["new"])
    note = f"now named {PurePosixPath(op['new']).name}"
    if rb is None:
        note += f". {rbstep.NO_TRACK_NOTE}"
    return Result("renamed", e["folder"], e["artist"], e["title"], op["track_id"], note, status=e.get("status"),
                  source=e.get("source"), path=op["new"])


def _finish(paths: Paths, state: dict, op: dict) -> Result:
    """Step 5: the entry (its path), the file row (the same row, the file's facts written again), the batch item and
    the check with its undo record, with the end of the journal entry."""
    track_id = op["track_id"]
    rb = op["rekordbox"]
    kept = list((op.get("chain") or {}).get("kept") or [])  # the Convert's kept edits, in a chain
    check = {**op["check"], "rekordbox": None if rb is None else {"entries": [r["id"] for r in rb["rows"]],
                                                                   "kept": kept}}
    check["undo"] = {"kind": "rename", "before": op["before"], "old": op["old"], "file": op["new"],
                     "file_key": op["file_key"], "file_sha256": op["new_sha256"], "audio": op["audio"],
                     "repoint": None if rb is None else rb.get("record"),
                     "backup": None if rb is None else rb.get("backup")}
    entry = {**op["entry"], "rekordbox_check": check}
    result = _result(op)
    item = None
    if op.get("batch"):
        item = (op["batch"][0], op["batch"][1], {"path": op["new"], "note": result.note,
                                                 "rekordbox": check["rekordbox"]})
    end_op(paths, state, op, {track_id: entry}, rekeyed=[op["new"]], item=item,
           audio={op["new"]: FileAudio(**op["audio"])})
    return result


def _drop(paths: Paths, state: dict, op: dict) -> None:
    """Ends a step that changed nothing (or was rolled back)."""
    end_op(paths, state, op, {})


def _put_back(paths: Paths, op: dict, roots: Collection[Path]) -> None:
    """The file back at its old name, when it is at the new one (by its SHA-256: another file at the new name is
    left alone) and nothing is at the old one."""
    if (paths.root / op["old"]).exists() or not rbstep.ours(paths.root / op["new"], op["new_sha256"]):
        return
    move_path(paths.root, op["new"], op["old"], None, roots)


def _roll_back(paths: Paths, state: dict, op: dict, roots: Collection[Path]) -> None:
    """The file as it was before the step (rekordbox untouched or already rolled back): the step ends."""
    _put_back(paths, op, roots)
    _drop(paths, state, op)


def _settle(paths: Paths, state: dict, op: dict, roots: Collection[Path]) -> str:
    """recover_rename right after a failure in the step, as words (the batch runs on: it is not stopped)."""
    outcome = recover_rename(paths, state, op, roots, crashed=False)
    if isinstance(outcome, Waits):
        return library.waiting(outcome, True)[0]
    return outcome[0]


# --- recovery ---

def _forward(paths: Paths, state: dict, op: dict, roots: Collection[Path]) -> None:
    """Steps 3 and 5 after the commit (or, without rekordbox, once the file is at its new name): a file still at its
    old name (the commit is rekordbox's, so the move is what is left) goes to the new one, then the step ends."""
    if not (paths.root / op["new"]).exists() and (paths.root / op["old"]).exists():
        move_path(paths.root, op["old"], op["new"], None, roots)
    _finish(paths, state, op)


def recover_rename(paths: Paths, state: dict, op: dict, roots: Collection[Path] | None = None, *,
                   crashed: bool = True) -> tuple[str, bool] | Waits:
    """Finishes or rolls back a rename step an earlier run was interrupted in (see the module docstring). Returns
    (message, finished), or a `library.Waits` for a step that stays pending (a drive away, rekordbox open while an
    analysis file must come back, a library that can't be read). `crashed`: the step's batch is marked `stopped`
    (False right after a failure inside a running batch)."""
    roots = watched_roots(paths) if roots is None else roots
    name = rbstep.track_name(op.get("entry") or {}, op["track_id"])
    try:
        away = drive_away(op, paths.root, roots)
        if away is not None:
            short = short_path(away)
            return Waits(name, Recovered(DRIVE_GONE.format(path=short), False, True, drive=short),
                          not waits_offline(op, paths.root, roots))
        if crashed:
            rbstep.stop_batch(paths, op)
        side = rbstep.side_of(paths, op)
        if side == "unreadable":
            return Waits(name, Recovered("", False, True), True, UNREADABLE_WAIT.format(name=name))
        if side == "unclean":
            return Waits(name, Recovered("", False, True), True, UNCLEAN_WAIT.format(name=name))
        rbstep.clear_leftovers(paths, (a["path"] for a in (op["rekordbox"] or {}).get("anlz", [])), not crashed)
        if side == "other":
            if op["marks"].get("committed"):
                _forward(paths, state, op, roots)
                return OTHER_MAC_DONE.format(name=name, new=op["new"]), True
            _roll_back(paths, state, op, roots)
            return OTHER_MAC_UNDONE.format(name=name, old=op["old"]), False
        if side == "new":
            _forward(paths, state, op, roots)
            return FINISHED.format(name=name), True
        if side == "neither":
            _roll_back(paths, state, op, roots)
            return NEEDS_HELP.format(name=name, old=op["old"], new=op["new"]), False
        back, lost = rbstep.anlz_back(op)  # side "old": not committed
        if back and process.running():
            return Waits(name, Recovered("", False, True), True, WAIT_REKORDBOX.format(name=name))
        try:
            with rbstep.rekordbox_lock(paths, not crashed or not back):
                for path, copy in back:
                    rbwrite.replace_bytes(path, copy.read_bytes())
        except Busy:
            return Waits(name, Recovered("", False, True), True,
                          rbstep.WAIT_BUSY.format(what="clean-name change", name=name))
        _roll_back(paths, state, op, roots)
        return NOT_FINISHED.format(name=name) + (ANLZ_LOST if lost else ""), False
    except Exception as err:  # e.g. permissions: the step stays and is tried again at the next start
        return COULD_NOT_FINISH.format(name=name, err=err), False


# --- undo (design §5.9; plan stage D §1.2) ---

def undo_rename(paths: Paths, state: dict, track_id: str, u: dict, entry: dict, *,
                session: Session | None = None) -> str:
    """Undoes one Give it its clean name (`u`: the check's undo record, kind `rename`; `entry`: the song as it was;
    `upgrades.undo` checked the rest first: the track still has the file, the file's audio is as it was, no other file
    holds the old name). Design §5.9, as the journaled op `rename_undo`; there is no old file to bring back and no
    new file to put away: it is the same file.

    1. decide, nothing changed yet: when the step wrote rekordbox, rekordbox is closed (else
       `UndoRefused("rekordbox_open")`) and every track still plays the file exactly as written (identity columns as
       the step wrote them, else `relocated`; `cloud`, `other_library`, …);
    2. the file back to its old name (`restored`; `move_path` refuses a name another file took);
    3. rekordbox in one transaction (`Writer.undo_repoint`, the commit point): `FolderPath`, `FileNameL` and
       `OrgFolderPath` back, `PPTH` back where the file still names the new path, `contentFile` for the files
       spliced (`committed`); refused or rolled back there → the file goes back to its new name, nothing changed;
    4. the entry as it was (its check: the one before the step, with its own undo when the step was the second half
       of a Convert), the file row at the old name with its facts.
    Returns the result's note. `recover_rename_undo` finishes or rolls back a step a crash cut off."""
    from .upgrades import UndoRefused, undo_session, undo_writer  # upgrades imports this module lazily
    record = u.get("repoint")
    audio_facts = FileAudio(**u["audio"]) if u.get("audio") else None
    with ExitStack() as stack:
        rb, rec = None, None
        if record:  # step 1; the read-write connection is closed again before any file moves (it leaves -wal/-shm)
            rb = undo_session(paths, session, stack, renamed=True)
            rec = rbwrite.RepointRecord.from_dict(record)
            with ExitStack() as check:
                try:
                    undo_writer(rb, check, renamed=True).check_undo(rec)
                except WriteRefused as err:
                    raise UndoRefused(err.reason, renamed=True) from None
        op = {"kind": "rename_undo", "source": "rename", "track_id": track_id, "old": u["before"]["path"],
              "new": u["file"], "audio": u.get("audio"), "entry": rbstep.with_audio(entry, audio_facts),
              "rekordbox": None if not record else {"dbid": record["dbid"], "record": record, "outcome": None},
              "marks": {"restored": False, "committed": False}}
        roots = watched_roots(paths)
        with deferred_interrupt():  # a Ctrl-C waits until the step is at a safe point
            journal_op(paths, state, op)
            try:  # step 2
                move_path(paths.root, op["new"], op["old"], None, roots)
            except BaseException as err:
                end_op(paths, state, op, {})
                if not isinstance(err, Exception):
                    raise
                raise UpgradeProblem(f"Could not put your file back at its old name ({err}). Nothing was "
                                     "changed.") from err
            op["marks"]["restored"] = True
            mark_op(paths, state, op)
            if rb is not None:  # step 3: the commit point
                try:
                    with ExitStack() as write:
                        undo_writer(rb, write, renamed=True).undo_repoint(
                            rec, prepared=lambda o: _undo_outcome(paths, state, op, o))
                except UndoRefused:  # the library could not be opened for the write: nothing changed there
                    _undo_back(paths, state, op, roots)
                    raise
                except (WriteRefused, RekordboxOpened) as err:  # rolled back, analysis files as they were
                    _undo_back(paths, state, op, roots)
                    reason = "rekordbox_open" if isinstance(err, RekordboxOpened) else err.reason
                    raise UndoRefused(reason, renamed=True) from None
                except Exception as err:  # decided by the track's path now, as after a crash
                    message = _settle_undo(paths, state, op, roots)
                    raise UpgradeProblem(f"The undo did not work ({err}). {message}") from err
                op["marks"]["committed"] = True
                mark_op(paths, state, op)
            try:  # step 4
                if _undo_forward(paths, state, op, roots).wait:
                    raise OSError("a drive is away")
            except Exception as err:  # finish right now if the disk allows, else at the next start
                message = _settle_undo(paths, state, op, roots)
                if not any(o.get("op_id") == op["op_id"] for o in state.get("pending", [])) and \
                        state["tracks"][track_id].get("path") == op["old"]:
                    return f"the file is named {PurePosixPath(op['old']).name} again"
                raise UpgradeProblem(f"The undo did not finish ({err}). {message}") from err
    return f"the file is named {PurePosixPath(op['old']).name} again"


def _undo_outcome(paths: Paths, state: dict, op: dict, outcome: rbwrite.UndoOutcome) -> None:
    """Inside the undo's transaction, before its COMMIT: what it put back, into the journal."""
    op["rekordbox"]["outcome"] = {"restored": outcome.restored, "kept": outcome.kept, "anlz": outcome.anlz}
    mark_op(paths, state, op)


def _end_undo(paths: Paths, state: dict, op: dict) -> None:
    """The undo's end: the song as it was, the file row at the old name with its facts (the same row), the end of the
    journal entry."""
    audio_facts = FileAudio(**op["audio"]) if op.get("audio") else None
    end_op(paths, state, op, {op["track_id"]: op["entry"]}, rekeyed=[op["old"]],
           audio={op["old"]: audio_facts} if audio_facts else None)


def _undo_back(paths: Paths, state: dict, op: dict, roots: Collection[Path]) -> Recovered:
    """An undo that didn't reach rekordbox's commit: the file back at its new name, the step ends with nothing
    changed."""
    r = recover_renames(paths.root, {"renames": [[op["old"], op["new"]]], "staged": {}, "size": {}}, roots)
    if not r.wait:
        end_op(paths, state, op, {})
    return r


def _undo_forward(paths: Paths, state: dict, op: dict, roots: Collection[Path]) -> Recovered:
    """The file at its old name (the move still to do, if any), then the undo's end."""
    r = recover_renames(paths.root, {"renames": [[op["new"], op["old"]]], "staged": {}, "size": {}}, roots)
    if not r.wait:
        _end_undo(paths, state, op)
    return r


def _settle_undo(paths: Paths, state: dict, op: dict, roots: Collection[Path]) -> str:
    """recover_rename_undo right after a failure inside the undo (its own session holds `rekordbox.lock`)."""
    outcome = recover_rename_undo(paths, state, op, roots, held=True)
    if isinstance(outcome, Waits):
        return library.waiting(outcome, True)[0]
    return outcome[0]


def recover_rename_undo(paths: Paths, state: dict, op: dict, roots: Collection[Path] | None = None, *,
                        held: bool = False) -> tuple[str, bool] | Waits:
    """Finishes or rolls back an undo an earlier run was interrupted in. Its commit point is rekordbox's transaction,
    so a step with a rekordbox record is decided by the tracks' `FolderPath` now: the old name's → finished (step 4);
    still the new name's → rolled back (analysis files the cut-off write left with the old `PPTH` get the new one
    again, which needs rekordbox closed: until then the step waits; the file back at its new name); neither →
    rekordbox left alone, rolled back, "needs your help". Another rekordbox library (or none): by the `committed`
    mark. A step without rekordbox is finished. Analysis files are only written under `rekordbox.lock` (`held`: the
    undo's own session has it); another holder makes the step wait."""
    roots = watched_roots(paths) if roots is None else roots
    name = rbstep.track_name(op.get("entry") or {}, op["track_id"])
    try:
        away = drive_away(op, paths.root, roots)
        if away is not None:
            short = short_path(away)
            return Waits(name, Recovered(DRIVE_GONE.format(path=short), False, True, drive=short),
                          not waits_offline(op, paths.root, roots))
        rb = op.get("rekordbox")
        side = "done"
        if rb is not None:
            rows = rb["record"]["rows"]
            side = rbstep.tracks_at(rb["dbid"], {r["id"]: (r["identity_before"]["FolderPath"],
                                                            r["identity_after"]["FolderPath"]) for r in rows})
        if side == "unreadable":
            return Waits(name, Recovered("", False, True), True, rbstep.UNDO_UNREADABLE_WAIT.format(name=name))
        if side == "unclean":
            return Waits(name, Recovered("", False, True), True, rbstep.UNDO_UNCLEAN_WAIT.format(name=name))
        if rb is not None:
            rbstep.clear_leftovers(paths, (a["path"] for a in rb["record"].get("anlz", [])), held)
        if side == "other":
            side = "done" if op["marks"].get("committed") else "back"
            words = UNDO_OTHER_MAC_DONE if side == "done" else UNDO_OTHER_MAC_UNDONE
        elif side == "neither":
            words = UNDO_NEEDS_HELP
        else:
            words = UNDO_FINISHED if side in ("done", "new") else UNDO_NOT_FINISHED
        if side in ("done", "new"):
            r = _undo_forward(paths, state, op, roots)
            ok = not r.problem
        else:
            if side == "old":
                back = rbstep.anlz_undo_back(op)
                if back and process.running():
                    return Waits(name, Recovered("", False, True), True,
                                  rbstep.UNDO_WAIT_REKORDBOX.format(name=name))
                try:
                    with rbstep.rekordbox_lock(paths, held or not back):
                        for path, data in back:
                            rbwrite.replace_bytes(path, data)
                except Busy:
                    return Waits(name, Recovered("", False, True), True,
                                  rbstep.WAIT_BUSY.format(what="undo", name=name))
            r = _undo_back(paths, state, op, roots)
            ok = False
        if r.wait:
            return Waits(name, r, not waits_offline(op, paths.root, roots))
        message = words.format(name=name, old=op["old"], new=op["new"])
        if r.problem:
            message += f" ({r.problem})"
        return message, ok
    except Exception as err:  # e.g. permissions: the step stays and is tried again at the next start
        return rbstep.COULD_NOT_FINISH_UNDO.format(name=name, err=err), False
