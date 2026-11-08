"""rekordbox's library `master.db`, read only (design rekordbox-repoint §5.2–§5.4, plan stage A §1.2, §1.4, §1.5; stage
B plan §1.2). Stage B's write is `write.py`; this module stays the read side.

`master.db` is SQLCipher 4 with one fixed key (`KEYS`, tried in order; the value pyrekordbox publishes), sent as a
passphrase (`PRAGMA key = '<hex>'`) as the connection's first statement; a read of `sqlite_master` proves it. This
module is the only place that touches rekordbox's database.

**Reading never leaves a file beside `master.db`** (plan §0.1). rekordbox keeps it in WAL mode: `-wal` and `-shm`
exist only while a connection is open. Every open here is read-only (`mode=ro`, so a write fails in SQLite itself),
and it is `immutable=1` (no locks, no `-wal`/`-shm` made) unless rekordbox is running *and* both files are there,
in which case the open shares them to see rekordbox's latest commits. A plain `mode=ro` open on a closed library
would make both files and trip guard 4 the next time.

Guards of stage A (read side), each an `Unreadable(problem)` from `open_read`:
1. no key opens it: `key` (when rekordbox runs, any failed open or read is `busy` instead: it may hold a lock);
2. `djmdProperty.DBVersion` not in `DB_VERSIONS`: `db_version`; a column of `READ_COLUMNS` missing: `schema`.
4. A `-wal` or `-shm` beside `master.db` while rekordbox is closed: `status()` says `ready` with problem `unclean`
   (stage B refuses to write on it; reading still works, from the main file).
`status()` folds all of it into one answer: `ready`, `none` or `unreadable`.

Finding a track (`Master.entries_for`): the `djmdContent` rows not deleted (`rb_local_deleted = 0`) and not
streaming (`FileType` 25) whose `FolderPath` (the file's whole path), NFC-normalised and case-folded, equals the
file's; also a row with the same file name whose path is the same file on disk (`os.path.samefile`: a folder
reached through a link). `rb_LocalFolderPath` and `OrgFolderPath` stay out of the match: NULL and `''` on every row
of a rekordbox 7 library checked 2026-11-07.
"""
from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import sqlcipher3

from . import process
from .locate import Place

KEYS: tuple[str, ...] = ("402fd482c38817c35ffa8ffb8c7d93143b749e7d315df7a81732a1ff43608497",)
DB_VERSIONS = frozenset({"6000"})
STREAMING = 25  # FileType of a streaming service's track (its FolderPath is a link, not a file)

# Every column stage A reads plus every column stage B reads or writes (plan stage B §0.2: one guard list, design §5.3
# guard 2). A table that lacks one is "schema". djmdLabel has no SearchStr in rekordbox 7 (nor in pyrekordbox's table
# definitions); djmdArtist and djmdAlbum do.
_LOOKUP = ("ID", "Name", "UUID", "rb_local_usn", "rb_local_deleted", "created_at", "updated_at")
READ_COLUMNS: dict[str, tuple[str, ...]] = {
    "djmdContent": ("ID", "UUID", "FolderPath", "FileNameL", "OrgFolderPath", "rb_LocalFolderPath", "FileType",
                    "FileSize", "BitDepth", "SampleRate", "BitRate", "Length", "AnalysisDataPath", "Title", "ArtistID",
                    "AlbumID", "LabelID", "ISRC", "Commnt", "usn", "rb_local_synced", "rb_local_deleted",
                    "rb_local_usn", "created_at", "updated_at"),
    "djmdArtist": (*_LOOKUP, "SearchStr"),
    "djmdAlbum": (*_LOOKUP, "SearchStr"),
    "djmdLabel": _LOOKUP,
    "djmdCue": ("ContentID", "rb_local_deleted"),
    "djmdProperty": ("DBID", "DBVersion"),
    "contentFile": ("ID", "ContentID", "Path", "Hash", "Size", "rb_local_usn", "updated_at"),
    "agentRegistry": ("registry_id", "int_1", "updated_at"),
}

Problem = Literal["unclean", "busy", "key", "db_version", "schema"]
State = Literal["ready", "none", "unreadable"]
_HEX_KEY = re.compile(r"[0-9a-fA-F]{64}")
_CHUNK = 500  # ids per IN (...) list, well under SQLite's variable limit


@dataclass(frozen=True)
class Status:
    state: State
    running: bool
    version: str | None
    library: str | None
    problem: Problem | None
    db_version: str | None
    dbid: str | None


@dataclass(frozen=True)
class Entry:
    id: str
    folder_path: str
    file_name: str
    file_type: int
    analysis_path: str | None
    title: str
    artist: str
    album: str
    label: str
    isrc: str
    comment: str
    cloud: bool
    created_at: str | None
    artist_id: str | None  # the lookup rows this track points at (text columns are written through them)
    album_id: str | None
    label_id: str | None
    org_folder_path: str  # '' when NULL
    local_folder_path: str | None  # rb_LocalFolderPath
    file_size: int | None
    uuid: str | None


@dataclass(frozen=True)
class PathIndex:
    """One pass over `djmdContent` (not deleted, not streaming) for many lookups: `by_path` maps a track's folded
    `FolderPath` (NFC, case-folded) to the ids that hold it, `by_name` the folded file name to (id, `FolderPath`) for
    every row of that name, in the database's order. `Master.entries_for(path, index)` answers from it."""
    by_path: dict[str, list[str]]
    by_name: dict[str, list[tuple[str, str]]]


class Unreadable(Exception):
    """The library can't be read: `problem` says why (`busy` when rekordbox runs and the open or a read failed)."""

    def __init__(self, problem: Problem, db_version: str | None = None, dbid: str | None = None):
        super().__init__(problem)
        self.problem = problem
        self.db_version = db_version
        self.dbid = dbid


def connect(db: Path, key: str | None, *, immutable: bool = True,
            driver: Callable | None = None):
    """A read-only connection to `db`, unlocked with `key` (64 hex characters, passphrase form, SQLCipher 4 defaults;
    None sends no key) and proven by a read of `sqlite_master`. `immutable` opens without locks and without making
    `-wal`/`-shm`. Raises the driver's error when the file doesn't open or the key doesn't fit. `driver` is the
    module's `connect` (the self-test passes its own)."""
    if key is not None and not _HEX_KEY.fullmatch(key):
        raise ValueError("a SQLCipher key here is 64 hex characters")
    uri = Path(db).absolute().as_uri() + ("?mode=ro&immutable=1" if immutable else "?mode=ro")
    con = (driver or sqlcipher3.connect)(uri, uri=True)
    try:
        if key is not None:
            con.execute(f"PRAGMA key = '{key}'")
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except BaseException:
        con.close()
        raise
    return con


def leftovers(db: Path) -> list[Path]:
    """The `-wal` and `-shm` files beside `db`."""
    return [p for p in (db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")) if p.exists()]


def _immutable(db: Path, running: bool) -> bool:
    return not (running and len(leftovers(db)) == 2)


def missing_columns_of(con, table: str) -> list[str]:
    """The columns of `READ_COLUMNS[table]` the table lacks (all of them when the table is missing)."""
    have = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
    return [c for c in READ_COLUMNS[table] if c not in have]


def missing_columns(con) -> list[str]:
    """`table.column` for every `READ_COLUMNS` entry the database lacks."""
    return [f"{table}.{c}" for table in READ_COLUMNS for c in missing_columns_of(con, table)]


def _fold(path: str) -> str:
    return unicodedata.normalize("NFC", path).casefold()


def _text(value) -> str:
    return "" if value is None else str(value)


def _id(value) -> str | None:
    return None if value is None or value == "" else str(value)


class Master:
    """An open, read-only `master.db`. It has no method that writes, and its connection refuses writes."""

    def __init__(self, con, place: Place, db_version: str, dbid: str | None):
        self.con = con
        self.place = place
        self.db_version = db_version
        self.dbid = dbid

    def index(self) -> PathIndex:
        """The path index of this library: one query, for a batch that looks up many files."""
        by_path: dict[str, list[str]] = {}
        by_name: dict[str, list[tuple[str, str]]] = {}
        for row_id, folder_path in self._candidates():
            folded = _fold(folder_path)
            by_path.setdefault(folded, []).append(row_id)
            by_name.setdefault(folded.rsplit("/", 1)[-1], []).append((row_id, folder_path))
        return PathIndex(by_path, by_name)

    def _candidates(self) -> list[tuple[str, str]]:
        return self.con.execute(
            "SELECT ID, FolderPath FROM djmdContent WHERE IFNULL(rb_local_deleted, 0) = 0 "
            "AND IFNULL(FileType, 0) <> ? AND FolderPath IS NOT NULL", (STREAMING,)).fetchall()

    def entries_for(self, path: Path, index: PathIndex | None = None) -> list[Entry]:
        """The rekordbox tracks that hold the file at `path`, in the database's order (none, one, or several). With
        `index` (this library's, from `index()`) the same answer comes without a scan of the table."""
        target = os.path.abspath(path)
        folded, name = _fold(target), _fold(os.path.basename(target))
        if index is None:
            rows = [(i, p) for i, p in self._candidates() if _fold(p).rsplit("/", 1)[-1] == name]
        else:  # a folded path ends in the folded name, so the name's rows hold every possible match
            rows = index.by_name.get(name, [])
        ids = [row_id for row_id, folder_path in rows
               if _fold(folder_path) == folded or _same_file(folder_path, target)]
        return self._entries(ids)

    def _entries(self, ids: list[str]) -> list[Entry]:
        if not ids:
            return []
        found = {}
        for chunk in _chunks(ids):
            marks = ",".join("?" * len(chunk))
            for row in self.con.execute(
                    "SELECT c.ID, c.FolderPath, c.FileNameL, c.FileType, c.AnalysisDataPath, c.Title, a.Name, "
                    "al.Name, l.Name, c.ISRC, c.Commnt, "
                    "(c.usn IS NOT NULL OR IFNULL(c.rb_local_synced, 0) <> 0), c.created_at, "
                    "c.ArtistID, c.AlbumID, c.LabelID, c.OrgFolderPath, c.rb_LocalFolderPath, c.FileSize, c.UUID "
                    "FROM djmdContent c LEFT JOIN djmdArtist a ON a.ID = c.ArtistID "
                    "LEFT JOIN djmdAlbum al ON al.ID = c.AlbumID LEFT JOIN djmdLabel l ON l.ID = c.LabelID "
                    f"WHERE c.ID IN ({marks})", chunk):
                (row_id, folder_path, file_name, file_type, analysis, title, artist, album, label, isrc, comment,
                 cloud, created_at, artist_id, album_id, label_id, org_path, local_path, file_size, uuid) = row
                found[row_id] = Entry(
                    id=_text(row_id), folder_path=_text(folder_path), file_name=_text(file_name),
                    file_type=int(file_type or 0), analysis_path=analysis or None, title=_text(title),
                    artist=_text(artist), album=_text(album), label=_text(label), isrc=_text(isrc),
                    comment=_text(comment), cloud=bool(cloud),
                    created_at=None if created_at is None else str(created_at),
                    artist_id=_id(artist_id), album_id=_id(album_id), label_id=_id(label_id),
                    org_folder_path=_text(org_path), local_folder_path=None if local_path is None else str(local_path),
                    file_size=None if file_size is None else int(file_size), uuid=_id(uuid))
        return [found[i] for i in ids if i in found]

    def cue_counts(self, ids: list[str]) -> dict[str, int]:
        """How many cues (memory and hot, not deleted) each track has; 0 for one without."""
        counts = dict.fromkeys(ids, 0)
        for chunk in _chunks(list(counts)):
            marks = ",".join("?" * len(chunk))
            for content_id, n in self.con.execute(
                    "SELECT ContentID, count(*) FROM djmdCue WHERE IFNULL(rb_local_deleted, 0) = 0 "
                    f"AND ContentID IN ({marks}) GROUP BY ContentID", chunk):
                counts[content_id] = n
        return counts


@dataclass(frozen=True)
class RekordboxView:
    """What one batch reads of rekordbox: the open library, its path index and its status, taken once (plan stage B
    §0.4, §1.6; `session.Session.view()` hands it out). `offset.timeline_offset(view=…)` answers from it without
    opening the library again."""
    master: Master
    index: PathIndex
    status: Status


def _chunks(items: list) -> Iterator[list]:
    for i in range(0, len(items), _CHUNK):
        yield items[i:i + _CHUNK]


def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except (OSError, ValueError):
        return False


def _open_keyed(db: Path, running: bool):
    immutable = _immutable(db, running)
    for key in KEYS:
        try:
            return connect(db, key, immutable=immutable)
        except sqlcipher3.DatabaseError:
            continue
    raise Unreadable("busy" if running else "key")


@contextmanager
def open_read(place: Place, running: bool) -> Iterator[Master]:
    """`place`'s library opened read-only and checked (guards 1 and 2), closed on leaving. Raises `Unreadable`.
    `running`: whether rekordbox runs now (decides the kind of open and turns failures into `busy`)."""
    con = _open_keyed(place.db, running)
    try:
        try:
            if missing_columns_of(con, "djmdProperty"):
                raise Unreadable("schema")
            row = con.execute("SELECT DBVersion, DBID FROM djmdProperty").fetchone()
            db_version, dbid = (None, None) if row is None else (_text(row[0]) or None, _text(row[1]) or None)
            if db_version not in DB_VERSIONS:
                raise Unreadable("db_version", db_version, dbid)
            if missing_columns(con):
                raise Unreadable("schema", db_version, dbid)
        except sqlcipher3.DatabaseError:
            raise Unreadable("busy" if running else "schema") from None
        yield Master(con, place, db_version, dbid)
    finally:
        con.close()


def status_of(master: Master, running: bool) -> Status:
    """The `ready` answer for a library that `open_read` has just opened: `status()` without a second keyed open."""
    problem: Problem | None = "unclean" if not running and leftovers(master.place.db) else None
    return Status("ready", running, master.place.app_version, str(master.place.db), problem, master.db_version,
                  master.dbid)


def status(place: Place | None, running: Callable[[], bool] | None = None) -> Status:
    """What Discjockey can do with rekordbox's library now. Never raises for a library it can't read."""
    is_running = (running or process.running)()
    if place is None or not place.db.is_file():  # gone since locate(): no library, not a wrong key
        return Status("none", is_running, None, None, None, None, None)
    try:
        with open_read(place, is_running) as master:
            return status_of(master, is_running)
    except Unreadable as e:
        state: State = "ready" if e.problem == "busy" else "unreadable"
        return Status(state, is_running, place.app_version, str(place.db), e.problem, e.db_version, e.dbid)
