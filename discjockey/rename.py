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
a step with rekordbox rows is decided by the rows' `FolderPath` now (`convert.side_of`): the old path → the file goes
back to its old name (an analysis file that holds the new `PPTH` comes back from the backup first, which needs
rekordbox closed: only then does the step wait, as for a drive; a crash before the repoint wrote anything never waits
for rekordbox); the new path → finished; neither (rekordbox changed the track since) → rekordbox left alone, the file
back at its old name, "needs your help". Another rekordbox library (or none) on this Mac → by the `committed` mark. A
step without rekordbox rows is decided by whether the file is at its new name. The batch the crash interrupted is
marked `stopped` (`crash`). Every file move goes through `move_path`; a music file is never deleted or overwritten
(`safe_rename` refuses a taken name).
"""
from __future__ import annotations

import os
from collections.abc import Callable, Collection
from dataclasses import asdict
from datetime import datetime
from pathlib import Path, PurePosixPath

import sqlcipher3

from . import audio, convert, library, quality, rekordbox
from .content_key import content_key
from .convert import Skipped, skipped, track_name
from .library import (
    DRIVE_GONE, NameReserver, Paths, _Recovered, _Waits, deferred_interrupt, drive_away, end_op, file_sha256,
    journal_op, mark_op, move_path, short_path, undo_paths, upgrade_undo, waits_offline, watched_roots,
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


def blocked(why: str) -> Skipped:
    """`Skipped("rename_blocked")` for `why`, a `BLOCKED_WHY` key (nothing was moved or written)."""
    return skipped("rename_blocked", reason=BLOCKED_WHY[why])


def clean_path(paths: Paths, state: dict, track_id: str, e: dict) -> str | None:
    """The path Give it its clean name gives the track's file (relative to the music folder), without writing
    anything: `<its folder>/<Artist - Title>.aiff`, or with the song's ID when another file holds that name. The
    file's own name counts as free (it moves away first), and so do the names the track's own undo record reserves
    (the check this step writes replaces that record: a Convert that landed on the ID name because its old file held
    the clean one leaves that name reserved for its undo). The path the file has already when that is the answer
    (`eligible.rename` then says `named_already`, a case-only difference included). None for a song with no artist
    or title. FileExistsError when no name is free."""
    if not (e.get("artist") or "").strip() or not (e.get("title") or "").strip():
        return None
    old = e["path"]
    names = NameReserver(paths.root, state)
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
            raise skipped("unclean")
    return entries


def rename_file(paths: Paths, state: dict, track_id: str, *, session: Session,
                now: Callable[[], datetime] = datetime.now, batch: tuple[int, int] | None = None) -> Result:
    """Give it its clean name for one track's own file (see the module docstring). `batch` = (AIFF batch, seq): its
    item is marked done with the step. Raises `Skipped` (nothing written: `eligible.rename`'s reasons,
    `rename_blocked`, `unclean`), `RekordboxOpened` (nothing written; the batch stops) or `UpgradeProblem` (a failure,
    nothing written, or the words of what recovery did)."""
    e = state["tracks"].get(track_id)
    if e is None or not e.get("path"):
        raise UpgradeProblem("This track has no file to rename. Nothing was changed.")
    old = e["path"]
    old_file = paths.root / old
    if not old_file.is_file():
        raise skipped("file_missing" if library.online(old_file, watched_roots(paths)) else "away")
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
        raise skipped(verdict.reason)
    entries = _entries(session, old_file)
    new_abs = convert.abs_path(paths, new)
    changes = [rbwrite.rename_change(x, new_abs) for x in entries]
    splices = convert.plan_splices(session, entries, new_abs)
    file_audio = quality.file_audio(info)
    sha = file_sha256(old_file)
    op = {"kind": "rename", "source": "rename", "track_id": track_id, "batch": list(batch) if batch else None,
          "old": old, "new": new, "new_sha256": sha, "file_key": content_key(old_file),
          "entry": convert.with_audio({**e, "path": new}, file_audio), "before": fields_before(e),
          "audio": asdict(file_audio), "rekordbox": convert.op_rekordbox(session, changes, splices),
          "check": {"reason": "renamed", "since": now().date().isoformat(), "batch": batch[0] if batch else None},
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
                convert.backup_tracks(session, track_id, entries, rb)
                op["marks"]["backed_up"] = True
                mark_op(paths, state, op)
            except BaseException as err:
                _drop(paths, state, op)
                convert.raise_refusal(err, op)
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
                    w.repoint(changes, splices, prepared=lambda c: convert.journal_record(paths, state, op, c))
            except (WriteRefused, RekordboxOpened) as err:  # rolled back, analysis files as they were
                _roll_back(paths, state, op, roots)
                convert.raise_refusal(err, op)
            except Exception as err:  # decided by the track's path now, as after a crash
                message = _settle(paths, state, op, roots)
                if convert.finished_at(state, op, track_id, new):  # it failed after the commit; recovery finished it
                    return _result(op)
                raise UpgradeProblem(STEP_FAILED.format(err=err, message=message)) from err
            op["marks"]["committed"] = True
            mark_op(paths, state, op)
        try:  # step 5
            result = _finish(paths, state, op)
        except Exception as err:  # finish right now if the disk allows, else at the next start
            message = _settle(paths, state, op, roots)
            if convert.finished_at(state, op, track_id, new):
                return _result(op)
            raise UpgradeProblem(STEP_NOT_FINISHED.format(err=err, message=message)) from err
    return result


def _result(op: dict) -> Result:
    e, rb = op["entry"], op["rekordbox"]
    note = f"now named {PurePosixPath(op['new']).name}"
    if rb is None:
        note += f". {convert.NO_TRACK_NOTE}"
    return Result("renamed", e["folder"], e["artist"], e["title"], op["track_id"], note, status=e.get("status"),
                  source=e.get("source"), path=op["new"])


def _finish(paths: Paths, state: dict, op: dict) -> Result:
    """Step 5: the entry (its path), the file row (the same row, the file's facts written again), the batch item and
    the check with its undo record, with the end of the journal entry."""
    track_id = op["track_id"]
    rb = op["rekordbox"]
    check = {**op["check"], "rekordbox": None if rb is None else {"entries": [r["id"] for r in rb["rows"]],
                                                                   "kept": []}}
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
    if (paths.root / op["old"]).exists() or not convert.ours(paths.root / op["new"], op["new_sha256"]):
        return
    move_path(paths.root, op["new"], op["old"], None, roots)


def _roll_back(paths: Paths, state: dict, op: dict, roots: Collection[Path]) -> None:
    """The file as it was before the step (rekordbox untouched or already rolled back): the step ends."""
    _put_back(paths, op, roots)
    _drop(paths, state, op)


def _settle(paths: Paths, state: dict, op: dict, roots: Collection[Path]) -> str:
    """recover_rename right after a failure in the step, as words (the batch runs on: it is not stopped)."""
    outcome = recover_rename(paths, state, op, roots, crashed=False)
    if isinstance(outcome, _Waits):
        return library._waiting(outcome, True)[0]
    return outcome[0]


# --- recovery ---

def _forward(paths: Paths, state: dict, op: dict, roots: Collection[Path]) -> None:
    """Steps 3 and 5 after the commit (or, without rekordbox, once the file is at its new name): a file still at its
    old name (the commit is rekordbox's, so the move is what is left) goes to the new one, then the step ends."""
    if not (paths.root / op["new"]).exists() and (paths.root / op["old"]).exists():
        move_path(paths.root, op["old"], op["new"], None, roots)
    _finish(paths, state, op)


def recover_rename(paths: Paths, state: dict, op: dict, roots: Collection[Path] | None = None, *,
                   crashed: bool = True) -> tuple[str, bool] | _Waits:
    """Finishes or rolls back a rename step an earlier run was interrupted in (see the module docstring). Returns
    (message, finished), or a `library._Waits` for a step that stays pending (a drive away, rekordbox open while an
    analysis file must come back, a library that can't be read). `crashed`: the step's batch is marked `stopped`
    (False right after a failure inside a running batch)."""
    roots = watched_roots(paths) if roots is None else roots
    name = track_name(op.get("entry") or {}, op["track_id"])
    try:
        away = drive_away(op, paths.root, roots)
        if away is not None:
            short = short_path(away)
            return _Waits(name, _Recovered(DRIVE_GONE.format(path=short), False, True, drive=short),
                          not waits_offline(op, paths.root, roots))
        if crashed:
            convert.stop_batch(paths, op)
        side = convert.side_of(paths, op)
        if side == "unreadable":
            return _Waits(name, _Recovered("", False, True), True, UNREADABLE_WAIT.format(name=name))
        if side == "unclean":
            return _Waits(name, _Recovered("", False, True), True, UNCLEAN_WAIT.format(name=name))
        convert.clear_leftovers(paths, (a["path"] for a in (op["rekordbox"] or {}).get("anlz", [])), not crashed)
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
        back, lost = convert.anlz_back(op)  # side "old": not committed
        if back and process.running():
            return _Waits(name, _Recovered("", False, True), True, WAIT_REKORDBOX.format(name=name))
        try:
            with convert.rekordbox_lock(paths, not crashed or not back):
                for path, copy in back:
                    rbwrite.replace_bytes(path, copy.read_bytes())
        except Busy:
            return _Waits(name, _Recovered("", False, True), True,
                          convert.WAIT_BUSY.format(what="clean-name change", name=name))
        _roll_back(paths, state, op, roots)
        return NOT_FINISHED.format(name=name) + (ANLZ_LOST if lost else ""), False
    except Exception as err:  # e.g. permissions: the step stays and is tried again at the next start
        return COULD_NOT_FINISH.format(name=name, err=err), False
