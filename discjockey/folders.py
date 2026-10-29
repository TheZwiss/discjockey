"""Watched folders and the answers to the import's To-do questions (spec library-and-sources §10, plan library
stage 4 D10-D12, I9): checking and adding an import folder, removing one, "Is this the same song?", and the
Duplicates question's "Keep both" and "Move to Superseded".

Writers (add, remove, the answers, supersede) run while the caller holds the library lock. Every file change is
`library.move_files` (journaled, crash-safe, across drives); nothing here deletes or overwrites a music file.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Callable

from . import db, identify, library, ops, report as rep
from .events import Emit, Message, no_emit
from .library import FolderCheck, NameReserver, Paths
from .models import AddedFolder, DupFile, RemovalCounts, is_own
from .names import split_name, strip_id_suffix
from .ops import OpProblem
from .planner import superseded_dir
from .tidy import failed_detail

# W5 (plan library stage 4 I12) and the other reasons a folder can't be watched; the rest of a check's problems are
# library.FOLDER_PROBLEMS'
IN_MUSIC = "This is inside your music folder, which Discjockey watches already."
HOLDS_MUSIC = "This folder holds your music folder. Choose a folder inside it instead."
IN_WATCHED = "This is inside {other}, which Discjockey watches already."  # {other}: the folder's name
MERGES = "{other} is inside it and becomes part of it."
ALREADY = "Discjockey watches this folder already."
NOT_FOUND = "That folder isn't there. If it is on a drive, connect the drive first."
NOT_READABLE = "macOS doesn't let Discjockey read that folder."
IMPORT_PROBLEMS = {**library.FOLDER_PROBLEMS, "music": IN_MUSIC, "holds_music": HOLDS_MUSIC, "watched": IN_WATCHED,
                   "already": ALREADY, "not_found": NOT_FOUND, "not_readable": NOT_READABLE}

SUPERSEDE = "move_to_superseded"  # the operation's name in reports/operations.jsonl
MOVED = "Moved to {dst}."
NOT_MOVED = "Nothing was moved: {detail}."
NOT_RECORDED = "Moved to {dst}, but Discjockey's records couldn't follow. The next sync catches up."
NOT_A_PLAYLIST_SONG = "That song isn't in your playlists any more, so there is nothing to answer."
STATUS_RANK = {"lossless": 0, "fake_lossless": 1, "not_lossless": 2}  # which own file takes over a playlist song


def check_import_folder(path: Path | str, *, paths: Paths, support: Path, program: Path, home: Path) -> FolderCheck:
    """Whether `path` can be watched, changing nothing: library.check_music_folder's checks of the place (a system
    folder, inside the app, the support folder), then it must be a folder that is there and can be read, and D11's
    rules (W5): not in the music folder or a watched folder, not holding the music folder. A usable one's `merges`
    are the watched folders inside it that it takes over; a refused one inside a watched folder names it in
    `other`. `kind` is "import" when usable. IMPORT_PROBLEMS words each problem (problem_words)."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        return FolderCheck(p, False, False, "not_absolute", None)
    p = p.resolve()
    exists = p.exists()

    def refuse(problem: str, other: str | None = None) -> FolderCheck:
        return FolderCheck(p, exists, False, problem, None, other)

    if not exists:
        return refuse("not_found")
    if not p.is_dir():
        return refuse("not_a_folder")
    if problem := library.place_problem(p, support=support, program=program, home=home):
        return refuse(problem)
    if not os.access(p, os.R_OK | os.X_OK):
        return refuse("not_readable")
    try:
        if paths.db_file.exists():
            with db.connect(paths.db_file) as conn:
                merges = db.check_watched_folder(conn, p, paths.library)
        else:
            merges = db.check_watched_folder(None, p, paths.library)
    except db.FolderRefused as r:
        return refuse(r.reason, r.other)
    return FolderCheck(p, True, True, None, "import", merges=tuple(merges))


def problem_words(check: FolderCheck) -> str | None:
    """The words for a refused check (None when it is usable)."""
    if check.problem is None:
        return None
    return IMPORT_PROBLEMS[check.problem].format(other=PurePosixPath(check.other).name if check.other else "")


def refused_words(refused: db.FolderRefused) -> str:
    """The words (W5) for a folder the records refused when it was added (it changed since the check)."""
    other = PurePosixPath(refused.other).name if refused.other else ""
    return IMPORT_PROBLEMS[refused.reason].format(other=other)


def merge_hints(check: FolderCheck) -> list[str]:
    """W5's merge Hint, one per watched folder the new one takes over (named by its folder name)."""
    return [MERGES.format(other=PurePosixPath(m).name) for m in check.merges]


def add(paths: Paths, path: Path | str, now: datetime | None = None) -> AddedFolder:
    """Watches `path` (check it first with check_import_folder; db.add_watched_folder enforces D11 again and raises
    db.FolderRefused). The library's records are opened first, so a library with no library.db yet gets one. The
    next scan finds its files; the import works through them."""
    library.open_records(paths)
    with db.connect(paths.db_file) as conn:
        return db.add_watched_folder(conn, Path(path).expanduser(), now or datetime.now())


def removal(paths: Paths, folder_id: int) -> RemovalCounts:
    """What removing the folder takes away (W4): its files, and the playlist songs that download again."""
    with db.connect(paths.db_file) as conn:
        return db.removal_counts(conn, folder_id)


def remove(paths: Paths, folder_id: int, today: date | None = None) -> RemovalCounts:
    """Stops watching an import folder (D12); its files stay where they are. ValueError for the Library folder or an
    unknown id."""
    with db.connect(paths.db_file) as conn:
        return db.remove_watched_folder(conn, folder_id, today or date.today())


def answer_same_song(paths: Paths, song_key: str, own_key: str, same: bool, now: datetime | None = None) -> None:
    """"Is this the same song?" answered: the next plan links the own song's file to the playlist song (same), or
    keeps them apart and lets the playlist song download (not same). ValueError when `own_key` isn't an own song's
    key; OpProblem(changed) when `song_key` isn't a playlist song's: an own song's, or a song the records know that
    no playlist has any more. A token the records don't know yet is a playlist song still to be downloaded (the
    question comes from the plan, which knows the playlists)."""
    if not is_own(own_key):
        raise ValueError(f"{own_key!r} is not a song of the user's own")
    entry = library.load_state(paths)["tracks"].get(song_key)
    if is_own(song_key) or (entry is not None and not entry.get("in_playlists", True)):
        raise OpProblem(NOT_A_PLAYLIST_SONG, "changed")
    with db.connect(paths.db_file) as conn:
        db.set_decision(conn, "same_song", song_key, own_key, "same" if same else "not_same", now or datetime.now())


def keep_both(paths: Paths, group_id: str, now: datetime | None = None) -> None:
    """Duplicates' "Keep both": the group is not asked again (a new copy makes it another group)."""
    with db.connect(paths.db_file) as conn:
        db.set_decision(conn, "keep_both", group_id, "", "keep", now or datetime.now())


def _current(conn, state: dict, group_id: str, file_id: int) -> list[DupFile]:
    """The group's files as they are now, or OpProblem(CHANGED): a file of it gone, offline, held or ambiguous (as
    duplicate_groups leaves them out), the group answered "Keep both", `file_id` not in it, or (a same-audio group)
    its files no longer share one audio. A group that isn't a same-audio one is a same-song group (I4, from the
    plan) only while it still is one: one playlist song's file, and the rest own songs' files that identify.compare
    finds certainly that song. File ids can be given out again after a row is deleted, so the shape alone could
    name a file the window never showed."""
    try:
        ids = db.group_ids(group_id)
        files = db.group_files(conn, group_id)
    except ValueError:
        raise OpProblem(ops.CHANGED, "changed") from None
    if (file_id not in ids or len(files) != len(ids) or not all(f.online and f.usable for f in files)
            or group_id in db.decisions(conn)["keep_both"]):
        raise OpProblem(ops.CHANGED, "changed")
    if group_id not in {g.id for g in db.duplicate_groups(conn)} and not _same_song(state, files):
        raise OpProblem(ops.CHANGED, "changed")
    return files


def _same_song(state: dict, files: list[DupFile]) -> bool:
    playlist = [f for f in files if f.song_key is not None and not is_own(f.song_key)]
    own = [f for f in files if f.song_key is not None and is_own(f.song_key)]
    if len(playlist) != 1 or len(own) != len(files) - 1:
        return False
    tracks = state["tracks"]
    e = tracks.get(playlist[0].song_key)
    if e is None or e.get("file_id") != playlist[0].file_id:
        return False
    for f in own:
        o = tracks.get(f.song_key)
        if o is None or o.get("file_id") != f.file_id:
            return False
        match = identify.compare(e.get("artist") or "", e.get("title") or "", e.get("duration_ms"), e.get("isrc"), o)
        if match is None or match[0] != "certain":
            return False
    return True


def _pure_own(f: DupFile) -> bool:
    """A file of a song of the user's own that no playlist song was linked to (a "Yes, same song" answer keeps the
    `local:<n>` key but puts the song in a playlist: it is a playlist song's file for what moves)."""
    return f.song_key is not None and is_own(f.song_key) and not f.in_playlists


def _heir(moved: DupFile, others: list[DupFile]) -> int | None:
    """D10: a playlist song's file moved away while only own songs' files stay: the best of them (by quality, then
    the oldest row) takes over the playlist song, so nothing downloads again."""
    if moved.song_key is None or _pure_own(moved):
        return None
    if any(o.song_key is not None and not _pure_own(o) for o in others):
        return None  # another playlist song's file stays: it keeps its own song, the moved one's downloads again
    own = [o for o in others if _pure_own(o)]
    if not own:
        return None
    return min(own, key=lambda o: (STATUS_RANK.get(o.status or "", 3), o.file_id)).file_id


def _target(paths: Paths, state: dict, moved: DupFile, watched: str | None) -> str:
    """The moved file's place in Superseded/, mirroring its folder (spec §7; an import folder's as
    `<its name>/<subfolders>`), its name kept; a name taken there gets the song's ID (a playlist song's) or a
    counter."""
    name = PurePosixPath(moved.path).name
    playlist_key = moved.song_key if moved.song_key and not is_own(moved.song_key) else ""
    stem, ext = split_name(strip_id_suffix(name, playlist_key) if playlist_key else name)
    return NameReserver(paths.root, state).choose(superseded_dir(moved.path, watched), stem, ext, playlist_key)


def supersede(paths: Paths, group_id: str, file_id: int, *, emit: Emit = no_emit,
              now: Callable[[], datetime] = datetime.now) -> str:
    """Duplicates' "Move to Superseded" (D10): like replacing a file, the file `file_id` of the group goes to
    Superseded/ (never deleted), through library.move_files (journaled; across drives a verified copy first), its
    row goes, and when it was a playlist song's while own songs' files stay, one of them takes the playlist song
    over (_heir). No move batch, no undo; a line in reports/operations.jsonl. Interrupted steps are finished first.
    OpProblem(CHANGED) when the group isn't as the window showed it, OpProblem(failed) when the move was refused
    (nothing moved). Returns where the file went."""
    state = library.open_state(paths, emit)
    for message, ok in library.recover_pending(paths, state):  # as every writer's start (tidy._begin)
        emit(Message("info" if ok else "warning", message))
    with db.connect(paths.db_file) as conn:
        try:
            files = _current(conn, state, group_id, file_id)
        except OpProblem as p:
            ops.log_operation(paths, now(), "", None, SUPERSEDE, p.kind, str(p))
            raise
        moved = next(f for f in files if f.file_id == file_id)
        watched = db.watched_root(conn, moved.path)
    key = moved.song_key or ""
    entry = state["tracks"].get(key)
    if not (paths.root / moved.path).is_file():
        ops.log_operation(paths, now(), key, entry, SUPERSEDE, "changed", ops.CHANGED)
        raise OpProblem(ops.CHANGED, "changed")
    heir = _heir(moved, [f for f in files if f.file_id != file_id])
    dst = _target(paths, state, moved, watched)
    try:
        library.move_files(paths, "supersede", [(moved.path, dst)], ref=file_id, heir=heir,
                           label=PurePosixPath(moved.path).name)
    except OSError as e:
        message = NOT_MOVED.format(detail=failed_detail(e))
        ops.log_operation(paths, now(), key, entry, SUPERSEDE, "failed", message)
        raise OpProblem(message, "failed") from None
    except (sqlite3.IntegrityError, ValueError):  # moved, but the records refused the result (move_files)
        message = NOT_RECORDED.format(dst=dst)
        ops.log_operation(paths, now(), key, entry, SUPERSEDE, "failed", message)
        raise OpProblem(message, "failed") from None
    message = MOVED.format(dst=dst)
    ops.log_operation(paths, now(), key, entry, SUPERSEDE, "done", message)
    rep.write_not_lossless(paths, library.load_state(paths))
    emit(Message("info", message))
    return dst
