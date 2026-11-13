"""One rekordbox file step, the parts Convert (`convert.py`) and Give it its clean name (`rename.py`) share (issue 33
stage D, D4c; a behaviour-preserving move out of `convert.py`): a step that changes a file's place and points rekordbox's
tracks at it (design rekordbox-repoint §5.8). Neither of them imports the other's step: both build on this.

- the refusal: `Skipped` and `skipped(reason)`, with the words of design §8 (`REFUSED`) and of Convert's and Rename's
  own refusals (`CONVERT_REFUSED`); `raise_refusal` turns the backup's or the write's refusal into it
- the journal entry's rekordbox part: `op_rekordbox`, `plan_splices` (the `PPTH` splices), `backup_tracks`,
  `journal_record` (the undo record, inside rekordbox's transaction), `with_audio`, `finished_at`, `abs_path`
- the commit point and recovery: `side_of` and `tracks_at` (which side of the commit a step is on), `anlz_back` and
  `anlz_undo_back` (analysis files to put back), `clear_leftovers`, `rekordbox_lock` (the writer lock), `stop_batch`,
  `ours` (is the file Discjockey's, by SHA-256), and the words a recovery or an undo says
Every caller reaches these as `rbstep.name`, so a test's `monkeypatch.setattr(rbstep, ...)` takes effect in every use.
"""
from __future__ import annotations

import os
import unicodedata
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import astuple
from pathlib import Path

from . import db, rekordbox
from .rekordbox import anlz, master, process
from .rekordbox import write as rbwrite
from .library import Paths, file_sha256, mark_op
from .models import FILE_AUDIO_KEYS, FileAudio
from .rekordbox.lock import Busy, writer_lock
from .rekordbox.session import Session
from .rekordbox.write import RekordboxOpened, WriteRefused
from .upgrades import UpgradeProblem

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
    "rename_blocked": "Discjockey can only give this file its new name while it can point your rekordbox track at "
                      "it, and it can't right now ({reason}). Nothing was changed.",
}

# What a step on the user's own file (Convert, Give it its clean name) says where Same track's words of `REFUSED` don't
# fit: it has no New track and no better version (`skipped(..., own_file=True)`, `raise_refusal` for a step of source
# `file` or `rename`). Nothing was changed.
OWN_FILE_REFUSED = {
    "rekordbox_unreadable": "Discjockey can't open this rekordbox version's library yet, so it can't point your "
                            "rekordbox track at the file. Nothing was changed.",
}

# Convert's own refusals (plan stage D §3, design §8 for the shared ones above); nothing was changed in every case
CONVERT_REFUSED = {
    "downloaded": "Discjockey downloaded this file: it is a clean AIFF already. Nothing was changed.",
    "no_name": "This song has no artist or title yet, so Discjockey can't give its file a clean name. Nothing was "
               "changed.",
    "upgrade_waits": "A better version is waiting: Same track makes it an AIFF.",
    # `clean_aiff`: the file is a clean AIFF, only its name is left (Convert's answer, which `aiff_action` turns into
    # Rename's); `named_already`: nothing is left to do
    "clean_aiff": "This file is a clean AIFF already: Give it its clean name.",
    "named_already": "A clean AIFF with its clean name already.",
    "needs_convert": "This file isn't a clean AIFF yet: Convert to AIFF gives it its clean name too. Nothing was "
                     "changed.",
    "away": "The file's drive isn't connected, so nothing was changed.",
    "file_missing": "Discjockey can't find the file where it expects it. Run a sync first, so it can find the file "
                    "again. Nothing was changed.",
}

NO_TRACK_NOTE = "This file isn't in your rekordbox collection, so there was nothing to keep there."

# Recovery and undo words (design §5.8; Convert's and Rename's recovery both say them)
WAIT_BUSY = ("Another window is changing rekordbox, so Discjockey can't finish an interrupted {what} for {name} yet; "
             "it tries again at the next start.")
UNDO_WAIT_REKORDBOX = "Quit rekordbox so Discjockey can finish an interrupted undo for {name}."
COULD_NOT_FINISH_UNDO = "Could not finish an interrupted undo for {name} yet: {err}"
UNDO_UNREADABLE_WAIT = ("Couldn't finish an interrupted undo for {name} yet: Discjockey can't read your rekordbox "
                        "library to tell how far it got.")
UNDO_UNCLEAN_WAIT = ("Couldn't finish an interrupted undo for {name} yet: rekordbox didn't close normally. Open "
                     "rekordbox, quit it, and Discjockey finishes the undo.")


class Skipped(UpgradeProblem):
    """The track's step can't run now and nothing was changed: `reason` is an `eligible.REASONS` key, the message the
    design's words; `detail` adds what the item's result shows (the sizes of a `space` refusal)."""

    def __init__(self, reason: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.reason = reason
        self.detail = detail or {}


def skipped(reason: str, /, *, own_file: bool = False, **words) -> Skipped:
    """`Skipped(reason)` with the design's words for it (`REFUSED`, `CONVERT_REFUSED`), `words` put into their
    placeholders; Convert's and Rename's steps raise their refusals through it. `own_file`: the step works on the
    user's own file, so a reason in `OWN_FILE_REFUSED` says that sentence instead of Same track's."""
    text = (own_file and OWN_FILE_REFUSED.get(reason)) or REFUSED.get(reason) or CONVERT_REFUSED[reason]
    return Skipped(reason, text.format(**words), words or None)


def abs_path(paths: Paths, rel: str) -> str:
    """The file's whole path as rekordbox keeps it (NFC)."""
    return unicodedata.normalize("NFC", os.path.abspath(paths.root / rel))


def track_name(e: dict, track_id: str) -> str:
    return f"{e.get('artist', '?')} - {e.get('title', track_id)}"


# --- the journal entry and the rekordbox part of the step ---

def op_rekordbox(session: Session, changes: list[rbwrite.RowChange], splices: list[rbwrite.AnlzChange]) -> dict | None:
    """The `rekordbox` part of a step's journal entry: the library's DBID, per row the before and after values, per
    analysis file its hashes, and the slots the step fills (`backup`, `record`, `kept`); None for a file no rekordbox
    track holds."""
    if not changes:
        return None
    return {"dbid": session.dbid, "backup": None,
            "rows": [{"id": c.id, "before": dict(c.before), "after": dict(c.after)} for c in changes],
            "anlz": [{"path": str(a.path), "old_sha256": a.old_sha256,
                      "new_sha256": rbwrite.sha256_of(a.new_bytes), "backup": None} for a in splices],
            "record": None, "kept": []}


def plan_splices(session: Session, entries: list[rekordbox.Entry], new_abs: str) -> list[rbwrite.AnlzChange]:
    """The `PPTH` splices of the analysis files of `entries` (one per file, however many tracks share it) for the new
    file at `new_abs`; Convert's and Rename's step plan them the same way."""
    splices: list[rbwrite.AnlzChange] = []
    seen: set[str] = set()
    for entry in entries:
        found, _others = rbwrite.anlz_changes(session.place, entry, new_abs)
        for a in found:
            if str(a.path) not in seen:
                seen.add(str(a.path))
                splices.append(a)
    return splices


def with_audio(entry: dict, audio_facts: FileAudio | None) -> dict:
    """`entry` with its read-only `file_*` keys (what the snapshot shows of the file at `path`) set to `audio_facts`,
    so the caller's snapshot is right until it reads another; a save never writes them."""
    if audio_facts is None:
        return entry
    return {**entry, **dict(zip(FILE_AUDIO_KEYS, astuple(audio_facts)))}


def backup_tracks(session: Session, track_id: str, entries: list[rekordbox.Entry], rb: dict) -> None:
    """Step 3: the batch's backup holds the analysis folders of `entries` (the track's rekordbox rows) and each
    analysis file's copy; its id and the copies' paths go into the journal entry's `rekordbox` part `rb` (the caller
    marks `backed_up`). Raises `WriteRefused` (nothing written) or the backup's own error."""
    folders = [f for x in entries if (f := rbwrite.analysis_folder(session.place, x)) is not None]
    b = session.ensure_backup([(track_id, folders)])
    rb["backup"] = b.id
    for a in rb["anlz"]:
        copy = b.anlz_copy(session.place, Path(a["path"]), session.batch_id)
        a["backup"] = None if copy is None else str(copy)


def journal_record(paths: Paths, state: dict, op: dict, c: rbwrite.Committed) -> None:
    """Inside the rekordbox transaction, before its COMMIT: the undo record and the fields kept go into the journal,
    so a crash after the commit finishes the step with them."""
    rb = op["rekordbox"]
    rb["record"] = c.record().to_dict()
    kept = {f for r in c.rows for f in r.kept}
    rb["kept"] = [f for f in TEXT_NAMES if f in kept]
    mark_op(paths, state, op)


# what a refusal says about the step's source (the journal entry's `source`)
WAITING = {"upgrade": "; the upgrade is still waiting.", "file": ".", "rename": "."}


def raise_refusal(err: BaseException, op: dict) -> None:
    """A refusal of the backup or the write (nothing changed) as this step's answer (`op`: the step's journal entry)."""
    if isinstance(err, RekordboxOpened):
        raise err
    if isinstance(err, WriteRefused):
        if err.reason == "rekordbox_open":
            raise RekordboxOpened() from err
        if err.reason in REFUSED and err.reason not in ("needs_choice", "space"):
            raise skipped(err.reason, own_file=op.get("source") in ("file", "rename")) from err
        raise Skipped(err.reason, REFUSED["changed"]) from err
    if not isinstance(err, Exception):
        raise err
    raise UpgradeProblem(f"Could not make the rekordbox backup ({err}). Nothing was changed"
                         f"{WAITING[op.get('source', 'upgrade')]}") from err


def finished_at(state: dict, op: dict, track_id: str, path: str) -> bool:
    """Whether the step is over (no longer pending) and the track's file is `path` now."""
    return (not any(o.get("op_id") == op["op_id"] for o in state.get("pending", []))
            and state["tracks"][track_id].get("path") == path)


# --- the lock, the commit point and recovery ---

def ours(path: Path, sha256: str) -> bool:
    try:
        return path.is_file() and file_sha256(path) == sha256
    except OSError:
        return False


@contextmanager
def rekordbox_lock(paths: Paths, held: bool) -> Iterator[None]:
    """`rekordbox.lock` for a write into rekordbox's analysis files (raises `Busy`); `held`: the caller's batch or
    undo session already has it."""
    if held:
        yield
        return
    with writer_lock(paths.support):
        yield


def clear_leftovers(paths: Paths, files: Iterable[object], held: bool) -> None:
    """Deletes the `<name>.dj-new` a crash left beside rekordbox's analysis files `files` (under the lock; while
    another writer holds it they stay for the next start)."""
    found = [Path(str(f)) for f in files if Path(str(f)).with_name(Path(str(f)).name + rbwrite.NEW_SUFFIX).exists()]
    if not found:
        return
    try:
        with rekordbox_lock(paths, held):
            for f in found:
                rbwrite.remove_leftover(f)
    except Busy:
        pass


def stop_batch(paths: Paths, op: dict) -> None:
    """The batch the crash interrupted: `stopped` (`crash`), so it offers Resume."""
    batch = op.get("batch")
    if not batch:
        return
    with db.connect(paths.db_file) as conn:
        row = db.aiff_batch(conn, batch[0])
        if row is not None and row.state == "running":
            db.set_aiff_batch(conn, batch[0], state="stopped", stop_reason="crash")


def side_of(paths: Paths, op: dict) -> str:
    """Which side of the commit the step is on: "new" (rekordbox's tracks play the new file), "old", "neither"
    (rekordbox changed a track since), "other" (another rekordbox library, or none, on this Mac: decided by the
    marks), "unreadable", "unclean"."""
    rb = op["rekordbox"]
    if rb is None:  # no rekordbox step: by whether the new file is in place
        return "new" if ours(paths.root / op["new"], op["new_sha256"]) else "old"
    return tracks_at(rb["dbid"], {r["id"]: (r["after"]["FolderPath"], r["before"]["FolderPath"])
                                  for r in rb["rows"]})


def tracks_at(dbid: str, paths_of: dict[str, tuple[str, str]]) -> str:
    """Where rekordbox's tracks `paths_of` (id -> (new path, old path)) point now: "new" when every one holds its new
    path, "old" when every one holds its old path, else "neither"; "other" for another rekordbox library (or none) on
    this Mac, "unreadable", "unclean" (a `-wal` or `-shm` alone beside the library while rekordbox is closed)."""
    place = rekordbox.locate()
    if place is None or not place.db.is_file():
        return "other"
    running = process.running()
    left = master.leftovers(place.db)
    if left and not running and len(left) != 2:
        return "unclean"
    try:  # with -wal and -shm there (a crash with the write open), a shared open sees what was committed
        with master.open_read(place, running or len(left) == 2) as m:
            if m.dbid != dbid:
                return "other"
            ids = list(paths_of)
            marks = ",".join("?" * len(ids))
            now = {str(i): p for i, p in m.con.execute(
                f"SELECT ID, FolderPath FROM djmdContent WHERE ID IN ({marks}) AND IFNULL(rb_local_deleted, 0) = 0",
                ids)}
    except master.Unreadable:
        return "unreadable"
    if all(now.get(i) == new for i, (new, _old) in paths_of.items()):
        return "new"
    if all(now.get(i) == old for i, (_new, old) in paths_of.items()):
        return "old"
    return "neither"


def anlz_back(op: dict) -> tuple[list[tuple[Path, Path]], bool]:
    """The analysis files that hold the step's new bytes, each with its backup copy; and whether any of them has no
    good copy (it is then left as it is)."""
    out, lost = [], False
    for a in (op["rekordbox"] or {}).get("anlz", []):
        path = Path(a["path"])
        if not ours(path, a["new_sha256"]):
            continue  # as it was (the write rolled back), or rekordbox's own since
        copy = Path(a["backup"]) if a.get("backup") else None
        if copy is None or not ours(copy, a["old_sha256"]):
            lost = True
            continue
        out.append((path, copy))
    return out, lost


def anlz_undo_back(op: dict) -> list[tuple[Path, bytes]]:
    """The analysis files an undo that didn't commit left with the old file's `PPTH` (cut off between writing them
    and the commit), each with its bytes as the upgrade left them (the new path spliced in again)."""
    out = []
    for a in op["rekordbox"]["record"].get("anlz", []):
        if not a.get("old_ppth") or a.get("old_ppth") == a.get("new_ppth"):
            continue
        path = Path(str(a["path"]))
        parsed = anlz.read(path)
        if parsed is not None and anlz.ppth(parsed) == a["old_ppth"]:
            out.append((path, anlz.splice_ppth(parsed, str(a["new_ppth"]))))
    return out
