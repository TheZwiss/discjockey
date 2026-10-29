"""The import of the user's own music (spec library-and-sources §10, plan library stage 4 D1, D6, I8): the files of
the watched folders, read where they are (never copied, moved, renamed or re-tagged) and given songs of their own.

`run_import` is a write job (the caller holds the library lock). It works through the rows the scan made for new
files of import folders, recording each file's progress on its own row (`files.import_state`), so a stopped import
resumes by construction:

  scan   finish interrupted steps, empty .tmp/, scan the watched folders (new files become `new` rows);
  tags   pass 1, every waiting file: its tags, its name (identify.own_name), its codec and length (probe), then a
         song of its own with the quality the codec gives for now (lossless codec → lossless, else not_lossless);
  sound  pass 2, every file read so far: the sound check (inspect → quality.verdict);
  link   the playlists planned again on the records as they are now and only the songs' links saved (run.link_only),
         so a playlist song the user already has is linked rather than downloaded.

Pass 1 runs over every file before pass 2 because the sound check decodes the whole file (hours for a big folder)
while tags take milliseconds: a sync after a stopped import already knows which songs the user has (D1).
"""
from __future__ import annotations

import errno
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import mutagen
from mutagen.id3 import ID3

from . import db, identify, library, quality
from .events import Cancelled, CancelToken, Emit, ImportProgress, Message, no_emit
from .library import Paths, StateError
from .models import ImportRow, OwnFacts

if TYPE_CHECKING:
    from .run import Prepared

TAG_NAMES = ("artist", "title", "album", "isrc")
ID3_FRAMES = {"artist": "TPE1", "title": "TIT2", "album": "TALB", "isrc": "TSRC"}  # AIFF/WAV: ID3 without easy keys
PROGRESS_EVERY = 25  # files
PROGRESS_SECONDS = 0.5

# W6 / W11 (plan library stage 4 I12): the words the window shows
SCANNING = "Looking for music files"
READING_TAGS = "Reading tags · {done} of {total}"
CHECKING_SOUND = "Checking the sound · {done} of {total}"
LINKING = "Linking to your playlists"
STOPPED = "Import stopped with {left} files to go. It carries on where it stopped."
STOPPED_ONE = "Import stopped with 1 file to go. It carries on where it stopped."
DONE = "Imported {files} files."
DONE_ONE = "Imported 1 file."
LINK_LATER = "Your playlists couldn't be read, so the imported files are linked to them at the next sync."
LINK_FAILED = "Your playlists couldn't be linked yet: {reason}."  # playlists.txt or the settings need fixing
# why a file couldn't be read: "{path}: {reason}"
NO_ACCESS = "macOS doesn't let Discjockey read it"
NO_SOUND = "Discjockey can't find sound it can read in it"


@dataclass(frozen=True)
class ImportResult:
    """What one import did. `files`: the files it imported (read in either pass, and not unreadable now);
    `own_songs`: songs of the user's own it made; `sound_checked`: files whose sound it judged; `unreadable`: files
    it couldn't read; `left`: the files the next import still works through (db.import_left: waiting or not judged
    yet, on drives that are there); `link_note`: LINK_LATER or LINK_FAILED's words when the playlists weren't
    linked, else None."""
    files: int
    own_songs: int
    sound_checked: int
    unreadable: int
    left: int
    stopped: bool
    link_note: str | None


def result_words(result: ImportResult) -> str:
    """W6's line for the end of an import: stopped with the files to go, or the files imported (1 is singular)."""
    if result.stopped:
        return STOPPED_ONE if result.left == 1 else STOPPED.format(left=result.left)
    return DONE_ONE if result.files == 1 else DONE.format(files=result.files)


class ImportStopped(Cancelled):
    """Stop between two files: what is done is written, the rest waits for the next import. Still a Cancelled, so a
    job reports it as stopped; `result` is the import as far as it went."""

    def __init__(self, result: ImportResult):
        super().__init__()
        self.result = result


def read_tags(path: Path) -> dict[str, str | None]:
    """The artist, title, album and ISRC tags of an audio file of any AUDIO_EXTS format (mutagen's easy tags; AIFF
    and WAV carry plain ID3), each None when missing or empty. Tags mutagen can't make sense of count as missing:
    the file's name still names the song. A file that can't be opened raises its OSError."""
    with open(path, "rb"):  # no access, gone: the caller words it (mutagen would hide the reason)
        pass
    out: dict[str, str | None] = dict.fromkeys(TAG_NAMES)
    try:
        f = mutagen.File(path, easy=True)
    except mutagen.MutagenError:
        return out
    tags = getattr(f, "tags", None)
    if tags is None:
        return out
    for name in TAG_NAMES:
        if isinstance(tags, ID3):
            frame = tags.get(ID3_FRAMES[name])
            values = list(frame.text) if frame is not None else []
        else:
            try:
                values = tags.get(name) or []
            except (KeyError, ValueError):  # a key this format's easy tags don't have
                values = []
        text = next((str(v).strip() for v in values if str(v).strip()), None)
        out[name] = text
    return out


def files_waiting(paths: Paths) -> int:
    """The files an import would work through now (db.import_left): the window's start condition (D14). An offline
    drive's files are left out: they wait until it is back, so they never start an import."""
    if not paths.db_file.exists():
        return 0
    with db.connect(paths.db_file) as conn:
        return db.import_left(conn)


def link_playlists(paths: Paths, prep: Prepared | None = None, *, emit: Emit = no_emit, token: CancelToken | None = None) -> str | None:
    """The import's last phase (D6), as `run_import`'s `link`: plans from `prep` (the window's last read of the
    playlists, run.Prepared) or else reads them, then run.link_only. LINK_LATER when they couldn't be read (W11),
    LINK_FAILED with the reason when playlists.txt or the settings stand in the way: either way the files are
    imported, and the next sync links them. The caller holds the library lock."""
    from . import run
    from .settings import SettingsError
    try:
        if prep is None:
            prep = run.prepare(paths, emit=emit, token=token)
        run.link_only(paths, prep, emit)
    except run.SetupProblem as e:
        return _link_failed(e) if e.kind == "config_invalid" else LINK_LATER
    except (StateError, SettingsError) as e:
        return _link_failed(e)
    return None


def _link_failed(e: Exception) -> str:
    return LINK_FAILED.format(reason=(str(e).strip().rstrip(".") or type(e).__name__))


class _Pacer:
    """ImportProgress at most every PROGRESS_EVERY files or PROGRESS_SECONDS, and always at a phase's start and end."""

    def __init__(self, emit: Emit, phase: str, total: int, unreadable: int):
        self.emit, self.phase, self.total = emit, phase, total
        self.last_done, self.last_at = 0, time.monotonic()
        emit(ImportProgress(phase, 0, total, unreadable))

    def step(self, done: int, unreadable: int) -> None:
        now = time.monotonic()
        if done == self.total or done - self.last_done >= PROGRESS_EVERY or now - self.last_at >= PROGRESS_SECONDS:
            self.last_done, self.last_at = done, now
            self.emit(ImportProgress(self.phase, done, self.total, unreadable))


def _reason(e: BaseException) -> str:
    """Plain words for why a file couldn't be read, never a traceback."""
    if isinstance(e, PermissionError) or (isinstance(e, OSError) and e.errno in (errno.EACCES, errno.EPERM)):
        return NO_ACCESS
    if isinstance(e, OSError) and not isinstance(e, FileNotFoundError) and e.strerror:
        return e.strerror.lower()
    return NO_SOUND


def _gone(row: ImportRow) -> bool:
    """The file isn't at its path (removed, moved or its drive unplugged since the scan): the row is left for the
    next scan, which knows what happened to it, and never marked unreadable."""
    return not os.path.lexists(row.path)


class _Run:
    def __init__(self, paths: Paths, emit: Emit, token: CancelToken, read_tags, probe, inspect):
        self.paths, self.emit, self.token = paths, emit, token
        self.read_tags, self.probe, self.inspect = read_tags, probe, inspect
        self.read: set[int] = set()  # file ids read in either pass
        self.failed: set[int] = set()  # file ids this import couldn't read
        self.own_songs = self.sound_checked = 0
        self.link_note: str | None = None

    def result(self, stopped: bool) -> ImportResult:
        with db.connect(self.paths.db_file) as conn:
            left = db.import_left(conn)
        return ImportResult(len(self.read - self.failed), self.own_songs, self.sound_checked, len(self.failed), left, stopped,
                            self.link_note)

    def unreadable(self, conn, row: ImportRow, e: BaseException) -> None:
        if _gone(row):
            return
        db.set_unreadable(conn, row.file_id, _reason(e))
        self.read.add(row.file_id)
        self.failed.add(row.file_id)

    def tags(self) -> None:
        with db.connect(self.paths.db_file) as conn:
            # a file the sound check couldn't read has its own song already: only the sound check is tried again
            judged_later = {r.file_id for r in db.import_unjudged(conn)}
            rows = [r for r in db.import_waiting(conn) if r.file_id not in judged_later]
            pacer = _Pacer(self.emit, "tags", len(rows), len(self.failed))
            for done, row in enumerate(rows, 1):
                self.token.check()
                if not _gone(row):
                    try:
                        tags = self.read_tags(row.path)
                        artist, title = identify.own_name(tags, row.path.name)
                        info = self.probe(row.path)
                        status = "lossless" if quality.is_lossless_codec(info.codec) else "not_lossless"
                        facts = OwnFacts(artist, title, tags.get("album"), tags.get("isrc"),
                                         round(info.duration_s * 1000) if info.duration_s else None, info.codec, status)
                    except Exception as e:  # an unreadable file is listed, never the end of the import
                        self.unreadable(conn, row, e)
                    else:  # import_waiting's rows have no song yet (judged_later's have): a new own song
                        if not self.own_songs:  # linked at the end, or by the next import after a stop
                            db.set_import_link_pending(conn, True)
                        db.add_own_song(conn, row.file_id, facts)
                        self.own_songs += 1
                        self.read.add(row.file_id)
                pacer.step(done, len(self.failed))

    def sound(self) -> None:
        with db.connect(self.paths.db_file) as conn:
            rows = [r for r in db.import_unjudged(conn) if r.file_id not in self.failed]
            pacer = _Pacer(self.emit, "sound", len(rows), len(self.failed))
            for done, row in enumerate(rows, 1):
                self.token.check()
                if not _gone(row):
                    try:
                        codec, cutoff = self.inspect(row.path)
                        status = quality.verdict(quality.is_lossless_codec(codec), cutoff)
                    except Exception as e:
                        self.unreadable(conn, row, e)
                    else:
                        db.set_sound(conn, row.file_id, status, cutoff, None)
                        self.sound_checked += 1
                        self.read.add(row.file_id)
                pacer.step(done, len(self.failed))


def run_import(paths: Paths, *, emit: Emit = no_emit, token: CancelToken, link: Callable[[], str | None],
               read_tags: Callable[[Path], dict[str, str | None]] = read_tags,
               probe: Callable[[Path], quality.AudioInfo] = quality.probe,
               inspect: Callable[[Path], tuple[str, int | None]] = quality.inspect) -> ImportResult:
    """The import, as the module docstring says. The caller holds the library lock. `link`: the last phase
    (link_playlists bound to the window's last read), returning words for a link that didn't happen, or None; it
    runs while own songs wait for it (db.import_link_pending: made by this import, or by one stopped before its
    link phase ended). Stop (`token`) is checked before each file and before linking: ImportStopped, carrying the result,
    after the current file is written. Files that couldn't be read before are tried again (this import's scan is
    spec §12's "next scan"); files on a drive that isn't there wait for it."""
    run = _Run(paths, emit, token, read_tags, probe, inspect)
    emit(ImportProgress("scan", 0, 0, 0))
    state = library.open_state(paths, emit)
    for message, ok in library.recover_pending(paths, state):  # as every writer's start (tidy._begin)
        emit(Message("info" if ok else "warning", message))
    library.clear_tmp(paths, state)
    library.scan_library(paths, emit, analyze=inspect, after_recovery=True)
    try:
        token.check()
        run.tags()
        run.sound()
        token.check()
        with db.connect(paths.db_file) as conn:
            pending = db.import_link_pending(conn)
        if pending:
            emit(ImportProgress("link", 0, 0, len(run.failed)))
            run.link_note = link()
            with db.connect(paths.db_file) as conn:  # linked, or left to the next sync (its plan links them too)
                db.set_import_link_pending(conn, False)
    except Cancelled:
        raise ImportStopped(run.result(stopped=True)) from None
    return run.result(stopped=False)
