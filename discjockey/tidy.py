"""The tidy-up (spec library-and-sources §8; plan library stage 2, group 3): files move to where the playlist order
puts them only when the user asks, one move batch at a time, every move through library.run_op; a folder renamed on
disk as one move; undo; what a Playlists save does with the files it retargets; closing batches a crash left open.

The entry points (tidy_up, rename_folder, undo, after_save) are writers: the caller holds the library lock. Each
first finishes interrupted steps (recover_pending, which closes open batches), empties .tmp/ and scans, so a file
moved by hand since the preview is found where it is, not moved from a stale place. undo_preview and rename_offer
only read. A tidy-up never renames a file and never retries a refused move onto another name: it is skipped."""
from __future__ import annotations

import errno
import sqlite3
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import datetime
from pathlib import PurePosixPath

from . import config, db, library, playlists_file as pf
from .events import Cancelled, CancelToken, Emit, Message, MovesProgress, no_emit
from .library import Paths
from .models import BatchResult, MoveRow, PlannedMove, SaveChoice
from .names import fold
from .planner import tidy_rows

Now = Callable[[], datetime]

FOLDER_LABEL = "the folder rename {old} → {new}"  # run_op's label of a folder move (I6)
# The recovery message of a batch a crash left open, by its kind and whether it moved anything (I6's tidy-up text)
RECOVERED = ("A tidy-up was stopped before it finished: {moved} moved, {left} not moved. You can undo it or tidy up "
             "the rest on the Playlists page.")
RECOVERED_NONE = "A tidy-up was stopped before it moved anything. You can tidy up on the Playlists page."
RECOVERED_RENAME = ("A folder rename was stopped before it finished, but the folder has its new name {new} now. You "
                    "can undo it on the Playlists page.")
RECOVERED_RENAME_NONE = "A folder rename was stopped before it started: the folder keeps its name {old}."
RECOVERED_UNDO = ("An undo was stopped before it finished: {moved} moved back, {left} not moved. Undo the same moves "
                  "again on the Playlists page to move the rest back.")
RECOVERED_UNDO_NONE = ("An undo was stopped before it moved anything back. You can undo again on the Playlists "
                       "page.")
NOT_RENAMED_BACK = ("The folder is called {to} again, but Discjockey couldn't change the playlist's name back. "
                    "Change it on the Playlists page.")
# finish_move refused (I4) after the file moved on disk: the move is recorded `failed`, in words that say so
MOVED_NOT_RECORDED = ("it did move, but another song is listed in its new place, so Discjockey couldn't note where "
                      "it went")
# `place_taken` of an undone folder rename, told apart in the detail (the views word the codes, I6)
FOLDER_THERE = "folder_there"  # a folder called {old} is in the Library again
NAME_USED = "name_used"  # another playlist is called {old} now
FAILED_DETAIL = {errno.EACCES: "Discjockey isn't allowed to change that folder",
                 errno.EPERM: "Discjockey isn't allowed to change that folder",
                 errno.ENOSPC: "the drive is full", errno.EROFS: "the drive is read-only",
                 errno.ENOENT: "it isn't there any more"}
# A folder rename refused at run time is one skipped move: rename_offer's code goes into the detail, with the
# nearest skip reason (the views word the code).
OFFER_SKIP = {"folder_taken": "name_taken", "no_folder": "not_found", "folder_in_use": "changed"}


class Stopped(Cancelled):
    """Stop between two moves: the batch is closed (the moves not made are `stopped`). Still a Cancelled, so a job
    reports it as stopped; `result` is the batch as far as it went, `results` every batch of the call so far
    (after_save runs several), `result` last."""

    def __init__(self, result: BatchResult, earlier: Sequence[BatchResult] = ()):
        super().__init__()
        self.result = result
        self.results = (*earlier, result)


def failed_detail(e: OSError) -> str:
    """The words for a move the system refused (I6 `failed`)."""
    return FAILED_DETAIL.get(e.errno) or (e.strerror or str(e) or type(e).__name__).lower()


# --- pure helpers ---

def _folder_of(path: str) -> str:
    """`F` of `Library/F` (a folder move's src or dst)."""
    return PurePosixPath(path).parts[1]


def _same_folder(a: str | None, b: str) -> bool:
    return a is not None and fold(a) == fold(b)


def _in_folder(path: str, folder: str) -> bool:
    parts = PurePosixPath(path).parts
    return len(parts) > 2 and parts[0] == "Library" and fold(parts[1]) == fold(folder)


def _repath(path: str, new: str) -> str:
    parts = PurePosixPath(path).parts
    return "/".join(("Library", new, *parts[2:]))


def _label(entry: dict) -> str:
    return f"{entry.get('artist') or '?'} - {entry.get('title') or '?'}"


def rename_offer(old: str, new: str, rows: list[pf.Row], library_dirs: Collection[str], *,
                 pairs: Collection[tuple[str, str]] = ()) -> str | None:
    """Pure: None when renaming `Library/<old>` to `Library/<new>` on disk can be offered, else why not:
    `no_folder` (there is no such folder: nothing to offer), `folder_taken` (`new` is already a folder in
    Library/), `folder_in_use` (a row of the new lines, switched off or not, still uses `old`: renaming would take
    its files away; chains of renames always end up here). `pairs`: every rename of the same change; an old folder
    that two of them rename (two playlists come from one folder) is `folder_in_use` too. Names compare by fold."""
    dirs = {fold(d) for d in library_dirs}
    if fold(old) not in dirs:
        return "no_folder"
    if fold(new) in dirs:
        return "folder_taken"
    if any(fold(r.folder) == fold(old) for r in rows):
        return "folder_in_use"
    if sum(fold(o) == fold(old) for o, _ in pairs) > 1:
        return "folder_in_use"
    return None


# --- the entry steps and the runner ---

def _begin(paths: Paths, emit: Emit) -> dict:
    """A writer's start: records opened, interrupted steps finished (messages emitted), .tmp/ emptied, the Library
    scanned; then the fresh snapshot the batch is planned on."""
    state = library.open_state(paths, emit)
    for message, ok in library.recover_pending(paths, state):
        emit(Message("info" if ok else "warning", message))
    library.clear_tmp(paths, state)
    library.scan_library(paths, emit)
    return library.open_state(paths, emit)


def library_dirs(paths: Paths) -> list[str]:
    """The folders directly under `Library/` (the names rename_offer checks)."""
    if not paths.library.is_dir():
        return []
    return [c.name for c in paths.library.iterdir() if c.is_dir() and not c.name.startswith(".")]


def _keys_by_file(state: dict) -> dict[int, str]:
    return {e["file_id"]: k for k, e in state["tracks"].items() if e.get("file_id") is not None}


def _content_keys(paths: Paths) -> dict[int, str | None]:
    with db.connect(paths.db_file) as conn:
        return {f.id: f.content_key for f in db.known_files(conn)}


def _start(paths: Paths, started_by: str, moves: Sequence[PlannedMove], now: Now, *, about: dict | None = None,
           undoes: int | None = None) -> int:
    with db.connect(paths.db_file) as conn:
        return db.start_batch(conn, started_by=started_by, about=about, undoes=undoes, moves=moves, now=now())


def _rename_playlist(paths: Paths, frm: str, to: str) -> bool:
    """The playlists.txt line whose folder is `frm` (fold) gets `to` (the atomic writer). False, writing nothing,
    when no line says `frm` (renamed again or removed since, or already written): so it is safe to do again."""
    loaded = pf.load(paths.playlists_file)
    if not any(fold(r.folder) == fold(frm) for r in loaded.rows):
        return False
    rows = [pf.Row(to, r.link, r.enabled) if fold(r.folder) == fold(frm) else r for r in loaded.rows]
    pf.save(paths.playlists_file, rows, loaded.version)
    return True


def _playlist_follows(paths: Paths, m: MoveRow) -> str | None:
    """After a folder move: the playlist named like the folder's old name takes its new one (an undo of a rename
    names the playlist back, P2; for a rename the save already wrote, no line has the old name and nothing is
    written). Returns a warning when playlists.txt couldn't be written."""
    frm, to = _folder_of(m.src), _folder_of(m.dst)
    try:
        _rename_playlist(paths, frm, to)
    except (OSError, UnicodeError, config.ConfigError, pf.PlaylistsChanged):
        return NOT_RENAMED_BACK.format(to=to)
    return None


def _move_one(paths: Paths, state: dict, keys: Mapping[int, str], m: MoveRow,
              undo: bool) -> tuple[str, str | None] | None:
    """One move through run_op; None when it happened, else (reason, detail). A refused or failed rename leaves the
    file where it was (run_op drops a step that renamed nothing)."""
    try:
        if m.kind == "folder":
            # the songs in the folder go with it; the playlist's songs take its new name (wherever their files
            # are), so targets stay where the files are: an undo's playlist is called {old} again (P2)
            old, new = _folder_of(m.src), _folder_of(m.dst)
            entries = {}
            for k, e in state["tracks"].items():
                moved = bool(e.get("path")) and _in_folder(e["path"], old)
                if moved or _same_folder(e.get("folder"), old):
                    entries[k] = {**e, **({"path": _repath(e["path"], new)} if moved else {}),
                                  **({"folder": new} if _same_folder(e.get("folder"), old) else {})}
            library.run_op(paths, state, "", [(m.src, m.dst)], None, entries=entries,
                           label=FOLDER_LABEL.format(old=old, new=new))
        else:
            key = keys.get(m.file_id) if m.file_id is not None else None
            if key is None:  # its song is gone since it was planned
                return ("moved_on" if undo else "not_found", None)
            library.run_op(paths, state, key, [(m.src, m.dst)], {**state["tracks"][key], "path": m.dst})
    except FileExistsError:
        return ("place_taken", FOLDER_THERE if m.kind == "folder" else None) if undo else ("name_taken", None)
    except FileNotFoundError:
        return ("moved_on" if undo else "not_found", None)
    except OSError as e:
        return ("failed", failed_detail(e))
    return None


def _close(paths: Paths, batch_id: int, started_by: str, now: Now, *, stopped: bool) -> BatchResult:
    with db.connect(paths.db_file) as conn:
        db.close_batch(conn, batch_id, now())
        moves = db.batch_moves(conn, batch_id)
    return BatchResult(batch_id=batch_id, started_by=started_by, moved=sum(m.state == "done" for m in moves),
                       skipped=tuple(m for m in moves if m.state == "skipped"), stopped=stopped)


def _run(paths: Paths, state: dict, batch_id: int, started_by: str, *, emit: Emit, token: CancelToken,
         now: Now) -> BatchResult:
    """Every planned move of the batch, in order: Stop is checked before each; each one is done (finish_move) or
    skipped with its reason, and the batch goes on (spec §12); then the batch is closed."""
    with db.connect(paths.db_file) as conn:
        planned = [m for m in db.batch_moves(conn, batch_id) if m.state == "planned"]
    keys = _keys_by_file(state)
    try:
        for n, m in enumerate(planned, 1):
            token.check()
            skip = _move_one(paths, state, keys, m, started_by == "undo")
            with db.connect(paths.db_file) as conn:
                if skip is None:
                    try:
                        db.finish_move(conn, m.id)
                    except sqlite3.IntegrityError:
                        db.skip_move(conn, m.id, "failed", MOVED_NOT_RECORDED)
                        skip = ("failed", MOVED_NOT_RECORDED)
                else:
                    db.skip_move(conn, m.id, *skip)
            if skip is None and m.kind == "folder" and (warning := _playlist_follows(paths, m)):
                emit(Message("warning", warning))
            emit(MovesProgress(batch_id, n, len(planned)))
    except Cancelled:
        raise Stopped(_close(paths, batch_id, started_by, now, stopped=True)) from None
    return _close(paths, batch_id, started_by, now, stopped=False)


# --- tidy-up and folder rename ---

def tidy_up(paths: Paths, moves: Sequence[tuple[int, str]], *, started_by: str = "tidy", emit: Emit = no_emit,
            token: CancelToken | None = None, now: Now = datetime.now) -> BatchResult:
    """Moves the files the page sent ((file_id, src as the page showed it)), each only if it still looks as shown:
    a file whose path isn't the sent one is `changed`, one with no row any more `not_found`, one the preview can't
    move its skip (offline, not_found, name_taken). Every sent move goes into the batch, skipped ones too, so the log
    shows them. Moved files become placed by the app. Stop between files: Stopped, carrying the closed batch."""
    state = _begin(paths, emit)
    return _tidy(paths, state, moves, started_by, emit=emit, token=token or CancelToken(), now=now)


def _tidy(paths: Paths, state: dict, moves: Sequence[tuple[int, str]], started_by: str, *, emit: Emit,
          token: CancelToken, now: Now) -> BatchResult:
    keys = _keys_by_file(state)
    sent: list[tuple[int, str]] = []
    for file_id, path in moves:  # each file once: the first time it is sent counts
        if all(file_id != i for i, _ in sent):
            sent.append((int(file_id), path))
    rows = {r.file_id: r for r in tidy_rows(state, only={keys[i] for i, _ in sent if i in keys})}
    content = _content_keys(paths)
    planned = []
    for file_id, path in sent:
        e = state["tracks"][keys[file_id]] if file_id in keys else None
        if e is None or not e.get("path"):
            if PurePosixPath(path).parts[:1] != ("Library",) or len(PurePosixPath(path).parts) < 3:
                continue  # nothing on record to log it against
            planned.append(PlannedMove("file", None if e is None else file_id,
                                       PurePosixPath(path).stem if e is None else _label(e), path, path, None,
                                       None, None, skip=("not_found", None)))
            continue
        row = rows.get(file_id)
        if fold(e["path"]) != fold(path):
            skip, dst = "changed", row.dst if row else e["path"]
        elif row is None:
            skip, dst = "not_found", e["path"]
        else:
            skip, dst = row.skip, row.dst
        planned.append(PlannedMove("file", file_id, _label(e), e["path"], dst, content.get(file_id),
                                   e.get("placed_by"), "app", skip=None if skip is None else (skip, None)))
    if not planned:
        return BatchResult(None, started_by, 0, (), False)
    batch = _start(paths, started_by, planned, now)
    return _run(paths, state, batch, started_by, emit=emit, token=token, now=now)


def check_folder_names(*names: str) -> None:
    """ValueError unless every name could be a playlist's folder (one name, not a path, not hidden)."""
    for name in names:
        if not name and isinstance(name, str):
            raise ValueError("A folder name can't be empty.")
        if (not isinstance(name, str) or not name or "/" in name or "\\" in name or name.startswith(".")
                or name != name.strip()):
            raise ValueError(f"\u201c{name}\u201d can't be used as a folder name.")


def rename_folder(paths: Paths, old: str, new: str, *, pairs: Collection[tuple[str, str]] = (),
                  emit: Emit = no_emit, token: CancelToken | None = None, now: Now = datetime.now) -> BatchResult:
    """Renames `Library/<old>` to `Library/<new>` as one folder move (a batch `rename`): every linked song under it
    gets its new path in the same step, the other rows of files in it follow in finish_move; placed_by stays (the
    files keep their place inside the folder). Only when rename_offer, asked again now against playlists.txt and
    the disk, is None; else the batch holds the one move, skipped. `pairs` as rename_offer."""
    state = _begin(paths, emit)
    return _rename(paths, state, old, new, pairs, emit=emit, token=token or CancelToken(), now=now)


def _rename(paths: Paths, state: dict, old: str, new: str, pairs: Collection[tuple[str, str]], *, emit: Emit,
            token: CancelToken, now: Now) -> BatchResult:
    check_folder_names(old, new)
    dirs = library_dirs(paths)
    why = rename_offer(old, new, pf.load(paths.playlists_file).rows, dirs, pairs=pairs)
    on_disk = next((d for d in dirs if fold(d) == fold(old)), old)  # the folder's own spelling
    move = PlannedMove("folder", None, on_disk, f"Library/{on_disk}", f"Library/{new}", None, None, None,
                       skip=None if why is None else (OFFER_SKIP[why], why))
    batch = _start(paths, "rename", [move], now, about={"from": old, "to": new})
    return _run(paths, state, batch, "rename", emit=emit, token=token, now=now)


# --- undo ---

def _file_undo_skip(paths: Paths, m: MoveRow, e: dict | None, taken: set[str]) -> str | None:
    if e is None or m.now_path is None:  # the file row is gone, or no song's file any more
        return "moved_on"
    if not e.get("online", True):
        return "offline"
    if fold(m.now_path) != fold(m.dst) or m.now_key != m.content_key or e.get("held"):
        return "moved_on"
    if fold(m.src) in taken or (paths.root / m.src).exists():
        return "place_taken"
    return None


def _folder_undo_skip(paths: Paths, m: MoveRow, rows: list[pf.Row]) -> tuple[str, str | None] | None:
    old, new = _folder_of(m.src), _folder_of(m.dst)
    if not (paths.root / m.dst).is_dir():
        return "moved_on", None
    if (paths.root / m.src).exists():
        return "place_taken", FOLDER_THERE
    if any(fold(r.folder) == fold(old) for r in rows):
        return "place_taken", NAME_USED
    if not any(fold(r.folder) == fold(new) for r in rows):
        return "playlist_renamed", None  # P2: folder and playlist name go back together, or not at all
    return None


def undo_preview(paths: Paths, state: dict, batch_id: int) -> list[PlannedMove]:
    """Read only: the batch's done moves in reverse order, each back from `dst` to `src`, the file's placed_by
    back to what it was. A move that can't go back carries its skip: `offline`; `moved_on` (the file isn't at `dst`
    with the key it had, or its song is gone; a folder: `Library/<new>` isn't there); `place_taken` (something is
    at `src`; a folder: `Library/<old>` exists, detail `folder_there`, or another playlist is called {old}, detail
    `name_used`); a folder: `playlist_renamed`
    when no playlists.txt line says {new} (P2). Moves the batch skipped aren't listed."""
    if not paths.db_file.exists():  # no records yet, so no batch either
        return []
    with db.connect(paths.db_file) as conn:
        done = [m for m in db.batch_moves(conn, batch_id) if m.state == "done"]
    by_file = {e["file_id"]: e for e in state["tracks"].values() if e.get("file_id") is not None}
    taken = {fold(e["path"]) for e in state["tracks"].values() if e.get("path")}
    rows = pf.load(paths.playlists_file).rows if any(m.kind == "folder" for m in done) else []
    out = []
    for m in reversed(done):
        if m.kind == "folder":
            skip, placed = _folder_undo_skip(paths, m, rows), None
        else:
            e = by_file.get(m.file_id) if m.file_id is not None else None
            reason = _file_undo_skip(paths, m, e, taken)
            skip, placed = None if reason is None else (reason, None), (e or {}).get("placed_by", m.placed_after)
        out.append(PlannedMove(m.kind, m.file_id, m.label, m.dst, m.src, m.content_key,
                               placed, m.placed_before, skip=skip))
    return out


def undo(paths: Paths, batch_id: int, *, emit: Emit = no_emit, token: CancelToken | None = None,
         now: Now = datetime.now) -> BatchResult:
    """Undoes a batch (spec §8.4) as a batch of its own (`undo`, `undoes` = it): undo_preview again on the fresh
    state, then each move back, only while its file is still where the batch put it and the old place is free;
    every other one is recorded skipped with its reason. An undone folder rename names the playlist back in
    playlists.txt too (P2). A batch with no done moves gives no batch (batch_id None)."""
    state = _begin(paths, emit)
    planned = undo_preview(paths, state, batch_id)
    if not planned:
        return BatchResult(None, "undo", 0, (), False)
    batch = _start(paths, "undo", planned, now, undoes=batch_id)
    return _run(paths, state, batch, "undo", emit=emit, token=token or CancelToken(), now=now)


# --- the save's choice ---

def after_save(paths: Paths, retargeted: Mapping[str, str], choice: SaveChoice, *, emit: Emit = no_emit,
               token: CancelToken | None = None, now: Now = datetime.now) -> list[BatchResult]:
    """After a Playlists save (playlists.txt already written): the retargeted songs get their new folder (one save),
    so targets are current without waiting for a sync. `leave`: their files that the app placed become placed by
    the user (P1), no batch. `move`: each rename on disk (a batch each), then the moves (a batch `save`); the
    results in that order."""
    if choice.files not in ("leave", "move"):
        raise ValueError(f"{choice.files!r} is not a choice for the files")
    token = token or CancelToken()
    state = _begin(paths, emit)
    changed = False
    for key, folder in retargeted.items():
        e = state["tracks"].get(key)
        if e is not None and e.get("folder") != folder:
            e["folder"], changed = folder, True
    if changed:
        library.save_state(paths, state)
    if choice.files == "leave":
        ids = [r.file_id for r in tidy_rows(state, only=retargeted.keys()) if r.placed_by == "app"]
        with db.connect(paths.db_file) as conn:
            db.set_placed_by(conn, ids, "user")
        return []
    results: list[BatchResult] = []
    try:
        for old, new in choice.renames:
            results.append(_rename(paths, state, old, new, choice.renames, emit=emit, token=token, now=now))
            state = library.load_state(paths)  # paths and the files on disk changed
        moves = _through_renames(state, choice.moves, choice.renames)
        results.append(_tidy(paths, state, moves, "save", emit=emit, token=token, now=now))
    except Stopped as stopped:
        raise Stopped(stopped.result, results) from None
    return results


def _through_renames(state: dict, moves: Sequence[tuple[int, str]],
                     renames: Sequence[tuple[str, str]]) -> list[tuple[int, str]]:
    """The sent moves with each path under a renamed folder taken in either spelling, before or after the rename
    (the page may send either, and the rename may have been refused): a sent path that is the file's path today
    in the other spelling becomes it. Anything else stays as sent (and is `changed` when it doesn't match)."""
    keys = _keys_by_file(state)
    out = []
    for file_id, path in moves:
        now = state["tracks"][keys[file_id]].get("path") if file_id in keys else None
        if now and fold(now) != fold(path):
            for old, new in renames:
                for a, b in ((old, new), (new, old)):
                    if _in_folder(path, a) and fold(_repath(path, b)) == fold(now):
                        path = now
        out.append((file_id, path))
    return out


# --- recovery (P3) ---

def _happened(paths: Paths, m: MoveRow) -> bool:
    """A planned move of a batch a crash left open was made: a file move when its row is at `dst` (only run_op's
    finished step, or recover_pending finishing it, puts it there; a step run_op rolled back never does), a folder
    move when `Library/<new>` is there and `Library/<old>` isn't."""
    if m.kind == "folder":
        return (paths.root / m.dst).is_dir() and not (paths.root / m.src).exists()
    return m.now_path is not None and fold(m.now_path) == fold(m.dst)


def recover(paths: Paths, state: dict) -> list[tuple[str, bool]]:
    """Closes the batches a crash (or power cut) left open, once the interrupted steps are finished
    (library.recover_pending calls it last): each planned move is done when it happened, else `stopped` (P3: the
    files not started are not moved now; the Tidy up button offers them again). A done folder move's playlist name
    is written when that was still to do (idempotent). One message per batch. Nothing while a step is still
    pending (it decides where its file is; the next start finishes it first)."""
    messages: list[tuple[str, bool]] = []
    with db.connect(paths.db_file) as conn:
        if db.has_pending(conn):
            return messages
        for batch_id in db.open_batches(conn):
            moves = db.batch_moves(conn, batch_id)
            for m in moves:
                if m.state != "planned":
                    continue
                if not _happened(paths, m):
                    db.skip_move(conn, m.id, "stopped")
                    continue
                try:
                    db.finish_move(conn, m.id)
                except sqlite3.IntegrityError:
                    db.skip_move(conn, m.id, "failed", MOVED_NOT_RECORDED)
            moves = db.batch_moves(conn, batch_id)
            for m in moves:
                if m.kind == "folder" and m.state == "done" and (warning := _playlist_follows(paths, m)):
                    messages.append((warning, False))
            db.close_batch(conn, batch_id, datetime.now())
            messages.append((_recovered(_started_by(conn, batch_id), moves), True))
    return messages


def _started_by(conn, batch_id: int) -> str:
    """The kind of a batch (db.batches lists them newest first; ids count up from 1 and batches are never
    deleted, so the open ones are among the newest)."""
    _, total = db.batches(conn, 0)
    rows, _ = db.batches(conn, max(1, total - batch_id + 1))
    return next((r.started_by for r in rows if r.id == batch_id), "tidy")


def _recovered(started_by: str, moves: list[MoveRow]) -> str:
    moved = sum(m.state == "done" for m in moves)
    left = len(moves) - moved
    if started_by == "rename":
        m = moves[0]
        return (RECOVERED_RENAME.format(new=_folder_of(m.dst)) if moved
                else RECOVERED_RENAME_NONE.format(old=_folder_of(m.src)))
    if started_by == "undo":
        return RECOVERED_UNDO.format(moved=moved, left=left) if moved else RECOVERED_UNDO_NONE
    return RECOVERED.format(moved=moved, left=left) if moved else RECOVERED_NONE

