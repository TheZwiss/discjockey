"""Same track for a file that isn't AIFF (issue 33; design rekordbox-repoint §3, §4, §5.8; plan stage B §1.8, §1.9):
the parked upgrade becomes a new 16-bit/44.1 kHz AIFF with the download's name, lined up with rekordbox's timeline of
the old file, and every rekordbox track of the old file is pointed at it, so cues, playlists and history stay.

`same_track(paths, state, track_id, upgrade, session=…)` is one track's step (a batch's item, `batches.run`; the
caller holds the library lock and the batch's `rekordbox.Session`). Before anything is written it measures the two
versions again (`compare`: not the same edit → `needs_choice`), asks rekordbox's timeline (`timeline_offset` on the
session's open library: `not_analysed`, `timing`, `cloud`, an unreadable library refuse) and the free space (§1.9:
`space`). Each refusal is `Skipped(reason)` with the design's words and nothing written; rekordbox open (or opened
since the batch began) is `rekordbox.RekordboxOpened`, which stops the batch. Then the journaled op `convert`
(library.db `pending`) runs design §5.8's steps, each marked:

1. render `build_staged(parked, .tmp/<track>/convert.aiff, L − d)` (the download's tags), hash it, plan the rekordbox
   rows (`write.row_change`: the text columns against the old file's tags) and the `PPTH` splices;
2. journal; 3. the batch's backup (`backed_up`, with each analysis file's copy); 4. `move_path(staged → new)`
   (`placed`); 5. `Writer.repoint`, the undo record journaled just before its `COMMIT` (`committed`); 6.
   `move_path(old → Superseded/)` under the old name (`superseded`); 7. the entry (`upgrades.upgraded_entry`), the
   file row (`placed_by = 'app'`), the batch item and the check (`repointed`, its undo record) in one library.db
   transaction, the parked download kept in .discjockey/undo/ (`upgrades.hold_parked`).
No rekordbox track (or no rekordbox at all): steps 3 and 5 are skipped. Every file move goes through `move_path`
(another drive: a staged copy recorded in the op's `crossing`).

**Recovery** (`recover_convert`, from `library.recover_pending`): the commit point is the `master.db` transaction, so a
step with rekordbox rows is decided by the rows' `FolderPath` now: still the old path → rolled back (analysis files
that hold the new bytes come back from the backup, which needs rekordbox closed: until then the step waits, as for a
drive; the placed file goes back to .tmp/ and is dropped); the new path → steps 6 and 7 finished; neither (rekordbox
changed the track since) → rekordbox left alone, the files rolled back, "needs your help". Another rekordbox library
(or none) on this Mac → only the files, by the `committed` mark. A step without rekordbox rows is decided by whether
the new file is in place. The batch the crash interrupted is marked `stopped` (`crash`).
"""
from __future__ import annotations

import math
import os
import shutil
import unicodedata
from collections.abc import Callable, Collection
from datetime import datetime
from pathlib import Path, PurePosixPath

from mutagen.aiff import AIFF

from . import align, audio, db, library, quality, rekordbox
from .events import Result
from .library import (
    DRIVE_GONE, NameReserver, Paths, _Recovered, _recover_renames, _remove_staged, _Waits, deferred_interrupt,
    drive_away, end_op, file_sha256, journal_crossings, journal_op, mark_op, move_path, short_path, waits_offline,
    watched_root, watched_roots,
)
from .names import expected_stem, split_name, strip_id_suffix
from .planner import replacement_dir, superseded_dir
from .rekordbox import eligible, master, process
from .rekordbox import write as rbwrite
from .rekordbox.eligible import Skip
from .rekordbox.session import Session
from .rekordbox.write import RekordboxOpened, WriteRefused
from .upgrades import (
    Compare, UpgradeProblem, build_staged, fields_before, hold_parked, held_place, precondition, swap_possible,
    undo_keys, upgraded_entry,
)

STAGED_NAME = "convert.aiff"
TEXT_NAMES = {"title": "title", "artist": "artist", "album": "album", "label": "label", "isrc": "ISRC",
              "comment": "comment"}

# Design §8 (binding): what a refusal says. Nothing was changed in every case.
REFUSED = {
    "needs_choice": "The new version isn't the same edit ({what}), so nothing was changed. Choose New track, or "
                    "discard it.",
    "rekordbox_unreadable": "Discjockey can't open this rekordbox version's library yet, so nothing was changed. "
                            "Choose New track, or update Discjockey.",
    "not_analysed": "rekordbox hasn't analysed this track yet, so Discjockey can't tell exactly where your cues sit. "
                    "Nothing was changed. Analyse it in rekordbox, quit rekordbox, and try again.",
    "timing": "Discjockey couldn't line the new file up with your rekordbox track exactly, so nothing was changed. "
              "Analyse the track again in rekordbox and try again.",
    "cloud": "This track is in rekordbox's Cloud Library Sync, which Discjockey doesn't change yet. Nothing was "
             "changed.",
    "unclean": "rekordbox didn't close normally last time. Open rekordbox, quit it, and try again. Nothing was "
               "changed.",
    "changed": "Your rekordbox track changed while Discjockey was working on it, so nothing was changed. Try again.",
    "other_library": "Your rekordbox library changed while Discjockey was working on it, so nothing was changed. Try "
                     "again.",
    "space": "There isn't enough free space for the new AIFF files ({size} needed, {free} free). Nothing was changed.",
}
REKORDBOX_OPEN = ("rekordbox is open. Quit rekordbox, then try again. Discjockey changes your rekordbox tracks only "
                  "while rekordbox is closed.")
NO_TRACK_NOTE = "This file isn't in your rekordbox collection, so there was nothing to keep there."
KEPT_NOTE = "Kept your own {fields} in rekordbox."
# Recovery (design §5.8, plan §3)
WAIT_REKORDBOX = "Quit rekordbox so Discjockey can finish an interrupted replace for {name}."
NOT_FINISHED = "The replace for {name} was not finished; your file and your rekordbox track are as they were."
FINISHED = "Finished an interrupted replace for {name}."
NEEDS_HELP = ("An interrupted replace for {name} needs your help: your rekordbox track was changed since and points "
              "at neither {old} nor {new}. Discjockey left rekordbox alone; your file stays at {old}.")
OTHER_MAC_DONE = ("Finished an interrupted replace for {name} on this Mac's side. Its rekordbox step was made in "
                  "another rekordbox library than this Mac's: open that one to check the track plays {new}.")
OTHER_MAC_UNDONE = ("The replace for {name} was not finished; your file is as it was. Its rekordbox step was made "
                    "in another rekordbox library than this Mac's: check there that the track plays {old}.")
UNREADABLE_WAIT = ("Couldn't finish an interrupted replace for {name} yet: Discjockey can't read your rekordbox "
                   "library to tell how far it got.")
UNCLEAN_WAIT = ("Couldn't finish an interrupted replace for {name} yet: rekordbox didn't close normally. Open "
                "rekordbox, quit it, and Discjockey finishes the replace.")
ANLZ_LOST = (" The analysis files of the track couldn't be put back from the backup; analyse the track again in "
             "rekordbox.")


class Skipped(UpgradeProblem):
    """The track's step can't run now and nothing was changed: `reason` is an `eligible.REASONS` key, the message the
    design's words; `detail` adds what the item's result shows (the sizes of a `space` refusal)."""

    def __init__(self, reason: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.reason = reason
        self.detail = detail or {}


def _skipped(reason: str, **words) -> Skipped:
    return Skipped(reason, REFUSED[reason].format(**words), words or None)


def free_space(path: Path) -> int:
    """Free bytes on the drive of `path` (or of its nearest folder that exists). Tests replace it."""
    while not path.exists() and path.parent != path:
        path = path.parent
    return shutil.disk_usage(path).free


def size_text(n: int) -> str:
    """A size for the user's eyes: "1.2 GB", "35 MB"."""
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{max(1, round(n / 1e6))} MB"


def needed_bytes(duration_s: float, channels: int) -> int:
    """The size of a 16-bit/44.1 kHz AIFF of `duration_s` (plan §1.9)."""
    return math.ceil(duration_s * 44100) * 2 * channels + 4096


def check_space(paths: Paths, parked: Path, new: str) -> None:
    """Room for the render on .discjockey/.tmp's drive, and once more on the new file's drive when the move crosses
    drives (move_path stages a copy there). Raises Skipped("space")."""
    info = quality.probe(parked)
    need = needed_bytes(info.duration_s, info.channels or 2)
    target = (paths.root / new).parent
    places = [paths.tmp]
    if library.device(paths.tmp) != library.device(target):
        places.append(target)
    for place in places:
        free = free_space(place)
        if free < need:
            raise Skipped("space", REFUSED["space"].format(size=size_text(need), free=size_text(free)),
                          {"needed": need, "free": free})


def _abs(paths: Paths, rel: str) -> str:
    """The file's whole path as rekordbox keeps it (NFC)."""
    return unicodedata.normalize("NFC", os.path.abspath(paths.root / rel))


def _name(e: dict, track_id: str) -> str:
    return f"{e.get('artist', '?')} - {e.get('title', track_id)}"


# --- the timeline and the plan ---

def _timeline(session: Session, e: dict, upgrade: dict, alignment: align.Alignment, old_file: Path
              ) -> tuple[list[rekordbox.Entry], int]:
    """rekordbox's tracks of the old file and `d` (44.1 kHz samples). Raises Skipped, or RekordboxOpened."""
    view = session.view()
    if view is None:
        if session.state.state == "none":
            return [], 0  # no rekordbox on this Mac: d = 0, nothing to repoint (design §3.4)
        if session.state.running:
            raise RekordboxOpened()
        raise _skipped("rekordbox_unreadable")
    try:
        t = rekordbox.timeline_offset(old_file, view=view)
    except Exception as err:  # ffmpeg can't read the old file: a failure of this track, nothing written
        raise UpgradeProblem(f"Discjockey couldn't read your file to line the new one up ({err}). Nothing was "
                             "changed.") from err
    measured = {**e, "upgrade": {**upgrade, "alignment": alignment.to_dict()}}
    verdict = eligible.same_track(measured, None, view.status, t)
    if isinstance(verdict, Skip):
        raise _skipped(verdict.reason) if verdict.reason in REFUSED else Skipped(verdict.reason, verdict.reason)
    entries = [x.entry for x in t.entries]
    if entries:
        if session.running_at_start or session.rekordbox_opened():
            raise RekordboxOpened()
        if view.status.problem == "unclean":
            raise _skipped("unclean")
    return entries, t.samples or 0


def _plan_rekordbox(session: Session, entries: list[rekordbox.Entry], old_file: Path, staged: Path, new_abs: str
                    ) -> tuple[list[rbwrite.RowChange], list[rbwrite.AnlzChange]]:
    """The rows to repoint (identity, file facts, text columns against the old file's tags) and the `PPTH` splices."""
    if not entries:
        return [], []
    old_tags = audio.file_facts(old_file).tags
    clean = audio.file_facts(staged).tags
    info = AIFF(str(staged)).info
    frames = round(info.length * info.sample_rate)
    size = staged.stat().st_size
    changes = [rbwrite.row_change(entry, new_abs, file_size=size, channels=info.channels, frames=frames,
                                  old_tags=old_tags, clean=clean) for entry in entries]
    splices: list[rbwrite.AnlzChange] = []
    seen: set[str] = set()
    for entry in entries:
        found, _others = rbwrite.anlz_changes(session.place, entry, new_abs)
        for a in found:
            if str(a.path) not in seen:
                seen.add(str(a.path))
                splices.append(a)
    return changes, splices


# --- the step ---

def same_track(paths: Paths, state: dict, track_id: str, upgrade: dict, *, session: Session,
               compare: Compare = align.compare_files, now: Callable[[], datetime] = datetime.now,
               batch: tuple[int, int] | None = None) -> Result:
    """One track's Same track for a current file that isn't AIFF (see the module docstring). `batch` = (AIFF batch,
    seq): its item is marked done with the step. Raises Skipped (nothing written), RekordboxOpened (nothing written;
    the batch stops) or UpgradeProblem (a failure, nothing written, or the words of what recovery did)."""
    e = precondition(paths, state, track_id, upgrade, need_current=True)
    if swap_possible(e):
        raise UpgradeProblem(f"{PurePosixPath(e['path']).name} is an AIFF file: its audio is swapped in place.")
    old_rel = e["path"]
    old_file, parked = paths.root / old_rel, paths.root / upgrade["file"]
    alignment = compare(old_file, parked)
    if not alignment.swap_safe:
        raise _skipped("needs_choice", what=alignment.text or alignment.result)
    entries, d = _timeline(session, e, upgrade, alignment, old_file)

    status = upgrade.get("status", "lossless")
    names = NameReserver(paths.root, state)
    new = names.choose(replacement_dir(e, status), expected_stem(e["artist"], e["title"]), ".aiff", track_id)
    stem, ext = split_name(strip_id_suffix(PurePosixPath(old_rel).name, track_id))
    superseded = names.choose(superseded_dir(old_rel, watched_root(paths, old_rel)), stem, ext, track_id)
    try:
        check_space(paths, parked, new)
    except RuntimeError as err:  # ffprobe can't read the download
        raise UpgradeProblem(f"Could not prepare the new version ({err}). Nothing was changed.") from err

    workdir = paths.tmp / track_id
    staged = workdir / STAGED_NAME
    new_abs = _abs(paths, new)
    try:  # step 1: the render and the plan; a failure leaves nothing
        workdir.mkdir(parents=True, exist_ok=True)
        staged.unlink(missing_ok=True)
        build_staged(parked, staged, alignment.offset_samples - d)
        changes, splices = _plan_rekordbox(session, entries, old_file, staged, new_abs)
        op = _op(paths, track_id, e, upgrade, alignment, now, batch, old_rel, new, superseded, staged, session,
                 changes, splices)
    except BaseException as err:
        shutil.rmtree(workdir, ignore_errors=True)
        if not isinstance(err, Exception) or isinstance(err, UpgradeProblem):
            raise
        raise UpgradeProblem(f"Could not prepare the new version ({err}). Nothing was changed; the upgrade is "
                             "still waiting.") from err

    roots = watched_roots(paths)
    with deferred_interrupt():  # a Ctrl-C waits until the step is at a safe point
        journal_op(paths, state, op)  # step 2
        rb = op["rekordbox"]
        if rb is not None:  # step 3: the batch's backup holds this track's analysis folders
            try:
                folders = [f for x in entries if (f := rbwrite.analysis_folder(session.place, x)) is not None]
                b = session.ensure_backup([(track_id, folders)])
                rb["backup"] = b.id
                for a in rb["anlz"]:
                    copy = b.anlz_copy(session.place, Path(a["path"]), session.batch_id)
                    a["backup"] = None if copy is None else str(copy)
                op["marks"]["backed_up"] = True
                mark_op(paths, state, op)
            except BaseException as err:
                _drop(paths, state, op)
                _raise_refusal(err)
        try:  # step 4
            move_path(paths.root, op["staged"], new, op["crossing"].get("0"), roots)
        except BaseException as err:
            _drop(paths, state, op)
            if not isinstance(err, Exception):
                raise
            raise UpgradeProblem(f"Could not put the new file in place ({err}). Nothing was changed; the upgrade is "
                                 "still waiting.") from err
        op["marks"]["placed"] = True
        mark_op(paths, state, op)
        if rb is not None:  # step 5: the commit point
            try:
                with session.writer() as w:
                    w.repoint(changes, splices, prepared=lambda c: _journal_record(paths, state, op, c))
            except (WriteRefused, RekordboxOpened) as err:  # rolled back, analysis files as they were
                _roll_back(paths, state, op, roots)
                _raise_refusal(err)
            except Exception as err:  # decided by the track's path now, as after a crash
                message = _settle(paths, state, op, roots)
                raise UpgradeProblem(f"The replace did not work ({err}). {message}") from err
            op["marks"]["committed"] = True
            mark_op(paths, state, op)
        try:  # step 6
            move_path(paths.root, old_rel, superseded, op["crossing"].get("1"), roots)
            op["marks"]["superseded"] = True
            mark_op(paths, state, op)
            result = _finish(paths, state, op)  # step 7
        except Exception as err:  # finish right now if the disk allows, else at the next start
            message = _settle(paths, state, op, roots)
            finished = not any(o.get("op_id") == op["op_id"] for o in state.get("pending", []))
            if finished and state["tracks"][track_id].get("path") == new:
                return _result(track_id, e, op)
            raise UpgradeProblem(f"The replace did not finish ({err}). {message}") from err
    return result


def _op(paths: Paths, track_id: str, e: dict, upgrade: dict, alignment: align.Alignment,
        now: Callable[[], datetime], batch: tuple[int, int] | None, old: str, new: str, superseded: str,
        staged: Path, session: Session, changes: list[rbwrite.RowChange], splices: list[rbwrite.AnlzChange]) -> dict:
    """The journal entry of the step (plan §1.8)."""
    staged_rel = staged.relative_to(paths.root).as_posix()
    crossing, size = journal_crossings(paths.root, [(staged_rel, new), (old, superseded)])
    rb = None
    if changes:
        rb = {"dbid": session.dbid, "backup": None,
              "rows": [{"id": c.id, "before": dict(c.before), "after": dict(c.after)} for c in changes],
              "anlz": [{"path": str(a.path), "old_sha256": a.old_sha256,
                        "new_sha256": rbwrite.sha256_of(a.new_bytes), "backup": None} for a in splices],
              "record": None, "kept": []}
    return {"kind": "convert", "track_id": track_id, "batch": list(batch) if batch else None, "source": "upgrade",
            "old": old, "new": new, "superseded": superseded, "staged": staged_rel, "crossing": crossing,
            "size": size, "old_sha256": file_sha256(paths.root / old), "new_sha256": file_sha256(staged),
            "parked": upgrade["file"], "held": held_place(paths, track_id, upgrade["file"]),
            "entry": upgraded_entry(e, upgrade, new), "before": fields_before(e),
            "check": {"reason": "repointed", "since": now().date().isoformat(), "match": alignment.result,
                      "offset_ms": alignment.offset_ms, "aligned": True, "batch": batch[0] if batch else None},
            "rekordbox": rb,
            "marks": {"backed_up": False, "placed": False, "committed": False, "superseded": False}}


def _journal_record(paths: Paths, state: dict, op: dict, c: rbwrite.Committed) -> None:
    """Inside the rekordbox transaction, before its COMMIT: the undo record and the fields kept go into the journal,
    so a crash after the commit finishes the step with them."""
    rb = op["rekordbox"]
    rb["record"] = c.record().to_dict()
    kept = {f for r in c.rows for f in r.kept}
    rb["kept"] = [f for f in TEXT_NAMES if f in kept]
    mark_op(paths, state, op)


def _raise_refusal(err: BaseException) -> None:
    """A refusal of the backup or the write (nothing changed) as this step's answer."""
    if isinstance(err, RekordboxOpened):
        raise err
    if isinstance(err, WriteRefused):
        if err.reason == "rekordbox_open":
            raise RekordboxOpened() from err
        if err.reason in REFUSED and err.reason not in ("needs_choice", "space"):
            raise _skipped(err.reason) from err
        raise Skipped(err.reason, REFUSED["changed"]) from err
    if not isinstance(err, Exception):
        raise err
    raise UpgradeProblem(f"Could not make the rekordbox backup ({err}). Nothing was changed; the upgrade is still "
                         "waiting.") from err


def _kept_note(kept: list[str]) -> str:
    return KEPT_NOTE.format(fields=" / ".join(TEXT_NAMES[f] for f in kept)) if kept else ""


def _result(track_id: str, e: dict, op: dict) -> Result:
    rb = op["rekordbox"]
    note = f"new file {op['new']}, lined up with rekordbox; the old one moved to {op['superseded']}"
    extra = NO_TRACK_NOTE if rb is None else _kept_note(rb.get("kept") or [])
    if extra:
        note += f". {extra}"
    return Result("swapped", e["folder"], e["artist"], e["title"], track_id, note,
                  status=op["entry"].get("status"), source=op["entry"].get("source"), path=op["new"])


def _finish(paths: Paths, state: dict, op: dict) -> Result:
    """Step 7: the parked download kept for the undo, then the entry, its file row, the batch item and the check
    with its undo record, with the end of the journal entry."""
    track_id = op["track_id"]
    held = hold_parked(paths, op)
    keys = undo_keys(paths, op["new"], op["superseded"]) if held else None
    rb = op["rekordbox"]
    check = {**op["check"], "rekordbox": None if rb is None else {"entries": [r["id"] for r in rb["rows"]],
                                                                   "kept": list(rb.get("kept") or [])}}
    if keys is not None:
        check["undo"] = {"kind": "convert", "before": op["before"], **keys, "held": held,
                         "repoint": None if rb is None else rb.get("record")}
    entry = {**op["entry"], "rekordbox_check": check}
    before = state["tracks"].get(track_id) or op["entry"]
    result = _result(track_id, before, op)
    item = None
    if op.get("batch"):
        item = (op["batch"][0], op["batch"][1], {"path": op["new"], "note": result.note,
                                                 "rekordbox": check["rekordbox"]})
    shutil.rmtree(paths.root / PurePosixPath(op["staged"]).parent, ignore_errors=True)
    end_op(paths, state, op, {track_id: entry}, rekeyed=[op["new"]], item=item, app_placed=[op["new"]])
    return result


def _drop(paths: Paths, state: dict, op: dict) -> None:
    """Ends a step that changed nothing (or was rolled back); the parked upgrade stays for another try."""
    shutil.rmtree(paths.root / PurePosixPath(op["staged"]).parent, ignore_errors=True)
    end_op(paths, state, op, {})


def _ours(path: Path, sha256: str) -> bool:
    try:
        return path.is_file() and file_sha256(path) == sha256
    except OSError:
        return False


def _take_back(paths: Paths, op: dict, roots: Collection[Path]) -> None:
    """The placed new file (Discjockey's own render, by its SHA-256) back to .tmp/, where `_drop` removes it; a
    staged copy a move to another drive left beside it goes too. Another file at that name is left alone."""
    new, staged = paths.root / op["new"], paths.root / op["staged"]
    copy = op["crossing"].get("0")
    if copy:
        _remove_staged(paths.root / copy)
    if not _ours(new, op["new_sha256"]):
        return
    if _ours(staged, op["new_sha256"]):  # a move to another drive that only had the source's removal left
        new.unlink()
        return
    back = library.staging_path(op["staged"]) if library.crosses(paths.root, op["new"], op["staged"]) else None
    move_path(paths.root, op["new"], op["staged"], back, roots)


def _roll_back(paths: Paths, state: dict, op: dict, roots: Collection[Path]) -> None:
    """The files as they were before the step (rekordbox untouched or already rolled back): the step ends."""
    _take_back(paths, op, roots)
    _drop(paths, state, op)


def _settle(paths: Paths, state: dict, op: dict, roots: Collection[Path]) -> str:
    """recover_convert right after a failure in the step, as words (the batch runs on: it is not stopped)."""
    outcome = recover_convert(paths, state, op, roots, crashed=False)
    if isinstance(outcome, _Waits):
        return library._waiting(outcome, True)[0]
    return outcome[0]


# --- recovery ---

def _stop_batch(paths: Paths, op: dict) -> None:
    """The batch the crash interrupted: `stopped` (`crash`), so it offers Resume."""
    batch = op.get("batch")
    if not batch:
        return
    with db.connect(paths.db_file) as conn:
        row = db.aiff_batch(conn, batch[0])
        if row is not None and row.state == "running":
            db.set_aiff_batch(conn, batch[0], state="stopped", stop_reason="crash")


def _side(paths: Paths, op: dict) -> str:
    """Which side of the commit the step is on: "new" (rekordbox's tracks play the new file), "old", "neither"
    (rekordbox changed a track since), "other" (another rekordbox library, or none, on this Mac: decided by the
    marks), "unreadable", "unclean"."""
    rb = op["rekordbox"]
    if rb is None:  # no rekordbox step: by whether the new file is in place
        return "new" if _ours(paths.root / op["new"], op["new_sha256"]) else "old"
    place = rekordbox.locate()
    if place is None or not place.db.is_file():
        return "other"
    running = process.running()
    left = master.leftovers(place.db)
    if left and not running and len(left) != 2:
        return "unclean"
    try:  # with -wal and -shm there (a crash with the write open), a shared open sees what was committed
        with master.open_read(place, running or len(left) == 2) as m:
            if m.dbid != rb["dbid"]:
                return "other"
            ids = [r["id"] for r in rb["rows"]]
            marks = ",".join("?" * len(ids))
            now = {str(i): p for i, p in m.con.execute(
                f"SELECT ID, FolderPath FROM djmdContent WHERE ID IN ({marks}) AND IFNULL(rb_local_deleted, 0) = 0",
                ids)}
    except master.Unreadable:
        return "unreadable"
    if all(now.get(r["id"]) == r["after"]["FolderPath"] for r in rb["rows"]):
        return "new"
    if all(now.get(r["id"]) == r["before"]["FolderPath"] for r in rb["rows"]):
        return "old"
    return "neither"


def _anlz_back(op: dict) -> tuple[list[tuple[Path, Path]], bool]:
    """The analysis files that hold the step's new bytes, each with its backup copy; and whether any of them has no
    good copy (it is then left as it is)."""
    out, lost = [], False
    for a in (op["rekordbox"] or {}).get("anlz", []):
        path = Path(a["path"])
        if not _ours(path, a["new_sha256"]):
            continue  # as it was (the write rolled back), or rekordbox's own since
        copy = Path(a["backup"]) if a.get("backup") else None
        if copy is None or not _ours(copy, a["old_sha256"]):
            lost = True
            continue
        out.append((path, copy))
    return out, lost


def _finish_forward(paths: Paths, state: dict, op: dict, roots: Collection[Path]) -> tuple[str, bool] | _Waits:
    """Steps 6 and 7 after the commit (or the placement, without rekordbox)."""
    name = _name(op.get("entry") or {}, op["track_id"])
    step = {"renames": [[op["old"], op["superseded"]]], "size": {"0": (op.get("size") or {}).get("1")},
            "staged": {"0": op["crossing"]["1"]} if op["crossing"].get("1") else {}}
    r = _recover_renames(paths.root, step, roots)
    if r.wait:
        return _Waits(name, r, not waits_offline(op, paths.root, roots))
    _finish(paths, state, op)
    if r.problem and not r.done_any and not (paths.root / op["old"]).exists():
        return FINISHED.format(name=name), True  # the old file was gone already (moved by hand)
    if r.problem:
        return f"Finished most of an interrupted replace for {name}, but {r.problem}.", False
    return FINISHED.format(name=name), True


def recover_convert(paths: Paths, state: dict, op: dict, roots: Collection[Path] | None = None, *,
                    crashed: bool = True) -> tuple[str, bool] | _Waits:
    """Finishes or rolls back a convert step an earlier run was interrupted in (see the module docstring). Returns
    (message, finished), or a `library._Waits` for a step that stays pending (a drive away, rekordbox open while
    analysis files must come back, a library that can't be read). `crashed`: the step's batch is marked `stopped`
    (False right after a failure inside a running batch)."""
    roots = watched_roots(paths) if roots is None else roots
    name = _name(op.get("entry") or {}, op["track_id"])
    try:
        away = drive_away(op, paths.root, roots)
        if away is not None:
            short = short_path(away)
            return _Waits(name, _Recovered(DRIVE_GONE.format(path=short), False, True, drive=short),
                          not waits_offline(op, paths.root, roots))
        if crashed:
            _stop_batch(paths, op)
        side = _side(paths, op)
        if side == "unreadable":
            return _Waits(name, _Recovered("", False, True), True, UNREADABLE_WAIT.format(name=name))
        if side == "unclean":
            return _Waits(name, _Recovered("", False, True), True, UNCLEAN_WAIT.format(name=name))
        if side == "other":
            if op["marks"].get("committed"):
                outcome = _finish_forward(paths, state, op, roots)
                if isinstance(outcome, _Waits) or not outcome[1]:
                    return outcome
                return OTHER_MAC_DONE.format(name=name, new=op["new"]), True
            _roll_back(paths, state, op, roots)
            return OTHER_MAC_UNDONE.format(name=name, old=op["old"]), False
        if side == "new":
            return _finish_forward(paths, state, op, roots)
        if side == "neither":
            _roll_back(paths, state, op, roots)
            return NEEDS_HELP.format(name=name, old=op["old"], new=op["new"]), False
        back, lost = _anlz_back(op)  # side "old": not committed
        if back and process.running():
            return _Waits(name, _Recovered("", False, True), True, WAIT_REKORDBOX.format(name=name))
        for path, copy in back:
            rbwrite.replace_bytes(path, copy.read_bytes())
        _roll_back(paths, state, op, roots)
        return NOT_FINISHED.format(name=name) + (ANLZ_LOST if lost else ""), False
    except Exception as err:  # e.g. permissions: the step stays and is tried again at the next start
        return f"Could not finish an interrupted replace for {name} yet: {err}", False
