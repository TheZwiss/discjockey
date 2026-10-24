"""Owns library.db: the schema, the migration from state.json, every query. Nothing else writes SQL (spec
library-and-sources §5.5).

One connection per call: `with connect(path) as conn:` opens it with the binding settings and closes it at the end
of the block (plan library stage 1, "Global constraints"). Transactions are explicit (`BEGIN IMMEDIATE`); outside
one, every statement commits by itself."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import unicodedata
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from . import library as disk  # "library" is the Library/ path argument everywhere here
from .events import Emit, Message
from .models import BatchRow, KnownFile, MoveRow, PlannedMove, ScanResult, SeenFile, WatchedFolder
from .names import expected_stem
from .planner import ENTRY_KEYS

SCHEMA_VERSION = 2

NEWER = ("This music folder was last used by a newer Discjockey. Update Discjockey, then try again. "
         "Nothing was changed.")
OLDER = ("Discjockey's records of this music folder are from an older version. Run a sync once to update them. "
         "Nothing was changed.")
UNREADABLE = "Discjockey can't read its records of this music folder (.discjockey/library.db): {reason}. Nothing was changed."
DAMAGED = "the file is damaged or isn't one of Discjockey's"

# schema version 1 (plan library stage 1, I1), one statement per item: executescript would commit mid-transaction
SCHEMA_V1 = (
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE songs (
      id INTEGER PRIMARY KEY,
      key TEXT NOT NULL UNIQUE,
      artist TEXT NOT NULL, title TEXT NOT NULL,
      artists TEXT, album TEXT, image_url TEXT,
      duration_ms INTEGER, isrc TEXT,
      folder TEXT,
      in_playlists INTEGER NOT NULL DEFAULT 1, added TEXT,
      last_attempt TEXT, last_upgrade_check TEXT, upgrade TEXT, rejected_sources TEXT, declined_streams TEXT,
      free_downloads TEXT, originals_searched TEXT, qobuz_searched TEXT,
      file_gone TEXT,
      extra TEXT)""",
    "CREATE INDEX songs_isrc ON songs (isrc)",
    """CREATE TABLE song_ids (service TEXT NOT NULL, id TEXT NOT NULL,
      song INTEGER NOT NULL REFERENCES songs (id) ON DELETE CASCADE, PRIMARY KEY (service, id))""",
    # a song's ids by song: rewriting its aliases and the cascade of deleting it would otherwise scan the table
    "CREATE INDEX song_ids_song ON song_ids (song)",
    """CREATE TABLE watched_folders (id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE,
      kind TEXT NOT NULL CHECK (kind IN ('library', 'import')), added TEXT NOT NULL, last_scan TEXT)""",
    """CREATE TABLE files (
      id INTEGER PRIMARY KEY,
      song INTEGER REFERENCES songs (id) ON DELETE SET NULL,
      folder INTEGER NOT NULL REFERENCES watched_folders (id),
      path TEXT NOT NULL,
      size INTEGER, mtime_ns INTEGER, content_key TEXT,
      placed_by TEXT NOT NULL CHECK (placed_by IN ('app', 'user', 'import')),
      online INTEGER NOT NULL DEFAULT 1,
      -- 1: missing at the last scan, but it couldn't rule out a move (ScanResult.held); decided on a later scan
      held INTEGER NOT NULL DEFAULT 0,
      -- last_seen: when a scan or a save last recorded the file's facts (an unchanged file's row is never
      -- rewritten); when its folder was last looked at is watched_folders.last_scan
      first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
      status TEXT, source TEXT, source_id TEXT, source_format TEXT, cutoff_hz INTEGER, source_kbps INTEGER,
      ambiguous TEXT,
      UNIQUE (folder, path))""",
    "CREATE INDEX files_key ON files (content_key)",
    "CREATE INDEX files_song ON files (song)",
    "CREATE TABLE never (song_key TEXT PRIMARY KEY, data TEXT NOT NULL)",
    # one row per service ("qobuz", "youtube", "soundcloud"): pacing.usage keeps a `<service>_usage` per service
    "CREATE TABLE usage (service TEXT PRIMARY KEY, data TEXT NOT NULL)",
    "CREATE TABLE pending (id INTEGER PRIMARY KEY, op TEXT NOT NULL)",
)

# step 1 -> 2 (plan library stage 2, I1): the move log of the tidy-up. Batches are never deleted (spec §8.4); a
# files row may go, and its moves keep their label
SCHEMA_V2_STEP = (
    """CREATE TABLE move_batches (
      id INTEGER PRIMARY KEY,
      started TEXT NOT NULL, finished TEXT,       -- ISO seconds; finished NULL = still running or stopped by a crash
      started_by TEXT NOT NULL CHECK (started_by IN ('tidy', 'save', 'rename', 'undo')),
      about TEXT,                                 -- JSON {"from": old, "to": new} for 'rename', else NULL
      undoes INTEGER REFERENCES move_batches (id))""",
    """CREATE TABLE moves (
      id INTEGER PRIMARY KEY,
      batch INTEGER NOT NULL REFERENCES move_batches (id),
      seq INTEGER NOT NULL,                       -- order in the batch; an undo goes in reverse
      kind TEXT NOT NULL CHECK (kind IN ('file', 'folder')),
      file INTEGER REFERENCES files (id) ON DELETE SET NULL,   -- NULL for a folder move or a file row since gone
      label TEXT NOT NULL,                        -- "Artist - Title" of a file, the folder name of a folder move
      src TEXT NOT NULL, dst TEXT NOT NULL,       -- snapshot paths: Library/<...>
      content_key TEXT,                           -- the file's key when planned; undo needs it unchanged
      placed_before TEXT, placed_after TEXT,      -- placed_by before / after this move (folder moves: NULL)
      state TEXT NOT NULL CHECK (state IN ('planned', 'done', 'skipped')),
      reason TEXT, detail TEXT,                   -- skip reason code and its detail (the failure's words)
      UNIQUE (batch, seq))""",
    "CREATE INDEX moves_file ON moves (file)",
    "CREATE INDEX moves_batch ON moves (batch)",
)


def _statements(statements: tuple[str, ...]) -> Callable[[sqlite3.Connection], None]:
    def step(conn: sqlite3.Connection) -> None:
        for statement in statements:  # one execute each: executescript would commit mid-transaction
            conn.execute(statement)
    return step


# version n -> the step that turns a version-n database into version n+1, run inside the open transaction. `create`
# builds SCHEMA_V1 and then runs every step, so a fresh database and an upgraded one are the same
UPGRADES: dict[int, Callable[[sqlite3.Connection], None]] = {1: _statements(SCHEMA_V2_STEP)}


class _Connection(sqlite3.Connection):
    """A connection whose `with` block also closes it (sqlite3's own only commits)."""

    def __exit__(self, *exc):
        try:
            return super().__exit__(*exc)
        finally:
            self.close()


def connect(path: Path) -> sqlite3.Connection:
    """Opens library.db with the binding settings: WAL (if the volume can't do WAL, the default journal: correctness
    doesn't depend on it), synchronous=FULL, foreign keys, F_FULLFSYNC for commits and checkpoints (the SQLite form
    of library.full_fsync), a 5 s wait for another writer. A file that isn't a database is StateError."""
    conn = None
    try:
        conn = sqlite3.connect(str(path), isolation_level=None, factory=_Connection)
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = FULL")
        conn.execute("PRAGMA fullfsync = ON")
        conn.execute("PRAGMA checkpoint_fullfsync = ON")
        conn.execute("PRAGMA journal_mode = WAL").fetchone()
    except sqlite3.Error as e:
        if conn is not None:
            conn.close()
        raise unreadable(e) from None
    return conn


def unreadable(e: sqlite3.Error) -> disk.StateError:
    """The StateError for a database SQLite refused, in words for what went wrong."""
    text = str(e).lower()
    if "locked" in text or "busy" in text:
        reason = "another program is using it right now; try again in a moment"
    elif "readonly" in text or "read-only" in text or "unable to open" in text:
        reason = "it can't be opened for writing (the drive may be read-only or disconnected)"
    else:
        reason = DAMAGED
    return disk.StateError(UNREADABLE.format(reason=reason))


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """One write transaction: all of it or nothing (also when COMMIT itself fails). IMMEDIATE takes the write lock
    at the start, so a second writer waits (busy_timeout) instead of failing halfway."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def _stored_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.Error as e:
        raise unreadable(e) from None
    if row is None or not str(row[0]).isdigit():
        raise disk.StateError(UNREADABLE.format(reason="it has no version number"))
    return int(row[0])


def _upgrade(conn: sqlite3.Connection, version: int) -> None:
    """Runs the steps from `version` up to SCHEMA_VERSION inside the caller's transaction."""
    while version < SCHEMA_VERSION:
        step = UPGRADES.get(version)
        if step is None:
            raise disk.StateError(UNREADABLE.format(
                reason=f"it has version {version}, which this Discjockey can't update"))
        step(conn)
        version += 1
    conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(version),))


def check(conn: sqlite3.Connection, *, upgrade: bool = False) -> None:
    """The version check every open does: a database from a newer Discjockey, or a file that isn't one, is
    StateError (nothing changed). An older one is brought up to SCHEMA_VERSION in one transaction (a failing step
    leaves it at its old version) only with `upgrade`, which only a writer holding the library lock passes
    (migrate); a reader refuses it (OLDER), as it takes no lock."""
    version = _stored_version(conn)
    if version > SCHEMA_VERSION:
        raise disk.StateError(NEWER)
    if version < SCHEMA_VERSION and not upgrade:
        raise disk.StateError(OLDER)
    if version < SCHEMA_VERSION:
        with transaction(conn):
            version = _stored_version(conn)  # another process may have upgraded it meanwhile
            if version < SCHEMA_VERSION:
                _upgrade(conn, version)


# --- the entry <-> rows mapping (plan library stage 1, I2) ---

class FileFacts(NamedTuple):
    """What `facts(snapshot path)` reports about a file on disk; `facts` returns None when no file is there."""
    size: int
    mtime_ns: int
    content_key: str


Facts = Callable[[str], "FileFacts | None"]

# songs columns, in table order; JSON columns hold a list/dict, in_playlists a bool
SONG_COLUMNS = ("artist", "title", "artists", "album", "image_url", "duration_ms", "isrc", "folder", "in_playlists",
                "added", "last_attempt", "last_upgrade_check", "upgrade", "rejected_sources", "declined_streams",
                "free_downloads", "originals_searched", "qobuz_searched", "file_gone")
JSON_COLUMNS = frozenset({"artists", "upgrade", "rejected_sources", "declined_streams", "free_downloads"})
# not in planner.ENTRY_KEYS: only in an entry while set (None and absent read the same with .get)
OPTIONAL_COLUMNS = frozenset({"artists", "album", "image_url", "declined_streams"})
# the linked file's fields; QUALITY are the ones copied onto the files row
FILE_FIELDS = ("path", "status", "source", "source_id", "source_format", "cutoff_hz", "source_kbps")
QUALITY = FILE_FIELDS[1:]
READ_ONLY = frozenset({"online", "placed_by", "held"})  # entry keys the snapshot adds and save ignores
SNAPSHOT_ONLY = frozenset({"version", "ambiguous", "files"})  # top-level keys the snapshot adds and save ignores
NOT_EXTRA = frozenset(SONG_COLUMNS) | frozenset(FILE_FIELDS) | READ_ONLY | {"aliases"}
# the keys every snapshot entry has unless the stored entry lacked them; `extra[ABSENT]` lists the ones it lacked
# (an entry written before free_downloads existed is a different case for rule 5 than free_downloads: None)
TRACKED = tuple(dict.fromkeys((*ENTRY_KEYS, *FILE_FIELDS)))
ABSENT = "_absent"
USAGE_SUFFIX = "_usage"  # `<service>_usage` -> the usage table
STATE_EXTRA = "state."  # meta key prefix for any other top-level key, so none is lost
SPOTIFY = "spotify"


def _dumps(value) -> str:
    return _ENCODER.encode(value)


# one encoder for every value: json.dumps with arguments builds a new one per call, which a save does per entry
_ENCODER = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _song_values(entry: dict) -> tuple:
    """The songs columns (SONG_COLUMNS order) and `extra` for an entry, encoded as stored, so equal entries give
    equal tuples."""
    out = []
    for col in SONG_COLUMNS:  # a save compares every entry: the common values skip json.dumps
        v = entry.get(col)
        if col in JSON_COLUMNS:
            v = None if v is None else "[]" if v == [] else _dumps(v)
        elif col == "in_playlists":
            v = 1 if entry.get(col, True) else 0  # rule 1 reads an absent in_playlists as True
        elif v is None and (col == "artist" or col == "title"):
            v = ""
        out.append(v)
    extra = {k: v for k, v in entry.items() if k not in NOT_EXTRA}
    absent = [k for k in TRACKED if k not in entry]
    if absent:
        extra[ABSENT] = absent
    out.append(_dumps(extra) if extra else None)
    return tuple(out)


def _entry(values: tuple, aliases: list[str], file: dict | None, path: str | None) -> dict:
    """An I2 entry from its songs columns (as _song_values gives them), its aliases and its linked file row."""
    e = dict.fromkeys(ENTRY_KEYS)
    for col, v in zip(SONG_COLUMNS, values):
        if col in OPTIONAL_COLUMNS and v is None:
            continue
        if col in JSON_COLUMNS and v is not None:
            v = json.loads(v)
        elif col == "in_playlists":
            v = bool(v)
        e[col] = v
    extra = {} if values[-1] is None else json.loads(values[-1])
    absent = extra.pop(ABSENT, [])
    e.update(extra)
    e["aliases"] = aliases
    if file is None:
        e.update(path=None, status="missing", source=None, source_id=None, source_format=None, cutoff_hz=None,
                 source_kbps=None, online=False, placed_by=None, held=False)
    else:
        e.update({k: file[k] for k in QUALITY}, path=path, online=bool(file["online"]), placed_by=file["placed_by"],
                 held=bool(file["held"]))
    for k in absent:  # keys the entry didn't have stay absent: the planner tells "absent" from None (rule 5)
        e.pop(k, None)
    return e


def snapshot_path(kind: str, folder: str, rel: str) -> str:
    """I2's path of a file: `Library/<rel>` in the library watched folder, else the absolute POSIX path."""
    return f"Library/{rel}" if kind == "library" else str(PurePosixPath(folder) / rel)


class _Folders:
    """The watched folders, for turning snapshot paths into (folder id, rel) and back."""

    def __init__(self, conn: sqlite3.Connection):
        self.rows = {i: (p, k) for i, p, k in conn.execute("SELECT id, path, kind FROM watched_folders")}
        self.library = next(i for i, (_, k) in self.rows.items() if k == "library")

    def path(self, folder: int, rel: str) -> str:
        p, k = self.rows[folder]
        return snapshot_path(k, p, rel)

    def locate(self, path: str) -> tuple[int, str]:
        """(folder id, rel) of a snapshot path; ValueError when it is in no watched folder."""
        path = unicodedata.normalize("NFC", path)
        if path.startswith("Library/") and len(path) > len("Library/"):
            return self.library, path[len("Library/"):]
        if path.startswith("/"):
            p = PurePosixPath(path)
            best = None
            for i, (root, _) in self.rows.items():
                r = PurePosixPath(unicodedata.normalize("NFC", root))
                if p != r and p.is_relative_to(r) and (best is None or len(r.parts) > len(best[1].parts)):
                    best = (i, r)
            if best is not None:
                return best[0], p.relative_to(best[1]).as_posix()
        raise ValueError(f"{path!r} is not a file in a watched folder (Library/... or an absolute path)")


def sync_library_path(conn: sqlite3.Connection, library: Path) -> int:
    """Library/ always belongs to the music folder the user chose now: a moved music folder or a renamed drive would
    otherwise leave the row pointing at a stale path (and offline). Writers only (save, migrate on open): it reads
    first and writes only when the path really differs, so it takes no write lock otherwise. Returns rows changed."""
    row = conn.execute("SELECT id, path FROM watched_folders WHERE kind = 'library'").fetchone()
    if row is None or row[1] == library.as_posix():
        return 0
    return conn.execute("UPDATE watched_folders SET path = ? WHERE id = ?", (library.as_posix(), row[0])).rowcount


SHARED = ("Two songs in Discjockey's records point at the same file, {path} ({a} and {b}). "
          "Nothing was changed.")


def _name(e: dict) -> str:
    return f"{e.get('artist') or '?'} - {e.get('title') or '?'}"


def _shared(path: str, a: dict, b: dict) -> disk.StateError:
    return disk.StateError(SHARED.format(path=path, a=_name(a), b=_name(b)))


def _insert_song(conn: sqlite3.Connection, key: str, entry: dict) -> int:
    cols = ", ".join(SONG_COLUMNS)
    marks = ", ".join("?" * (len(SONG_COLUMNS) + 2))
    song = conn.execute(f"INSERT INTO songs (key, {cols}, extra) VALUES ({marks})",
                        (key, *_song_values(entry))).lastrowid
    # an id another song already has (as its key or an alias) stays with that song; create inserts every song's own
    # key before any alias, so there a song's key always points at it
    conn.execute("INSERT OR IGNORE INTO song_ids (service, id, song) VALUES (?, ?, ?)", (SPOTIFY, key, song))
    return song


def _write_aliases(conn: sqlite3.Connection, song: int, key: str, aliases, *, new: bool = False) -> int:
    """Replaces the song's alias rows (insertion order is the aliases' order); a `new` song has none yet. Returns
    rows written."""
    n = 0 if new else conn.execute("DELETE FROM song_ids WHERE song = ? AND NOT (service = ? AND id = ?)",
                                   (song, SPOTIFY, key)).rowcount
    for a in aliases or []:
        if a != key:
            n += conn.execute("INSERT OR IGNORE INTO song_ids (service, id, song) VALUES (?, ?, ?)",
                              (SPOTIFY, a, song)).rowcount
    return n


def _fact_values(facts: Facts, path: str) -> tuple:
    f = facts(path)
    return (None, None, None) if f is None else (f.size, f.mtime_ns, f.content_key)


def _insert_file(conn, song: int, folder: int, rel: str, entry: dict, facts: Facts, path: str, now: str,
                 placed_by: str = "app") -> int:
    return conn.execute(
        "INSERT INTO files (song, folder, path, size, mtime_ns, content_key, placed_by, online, first_seen, "
        "last_seen, status, source, source_id, source_format, cutoff_hz, source_kbps) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)",
        (song, folder, rel, *_fact_values(facts, path), placed_by, now, now,
         *(entry.get(k) for k in QUALITY))).rowcount


def _usage_rows(state: dict) -> dict[str, str]:
    return {k[:-len(USAGE_SUFFIX)]: _dumps(v) for k, v in state.items()
            if k.endswith(USAGE_SUFFIX) and v is not None}


def _extra_rows(state: dict) -> dict[str, str]:
    """Top-level keys with no table of their own (none today), kept in meta so a save never drops one."""
    known = {"tracks", "pending", "never"} | SNAPSHOT_ONLY
    return {STATE_EXTRA + k: _dumps(v) for k, v in state.items() if k not in known and not k.endswith(USAGE_SUFFIX)}


def create(path: Path, state: dict, *, library: Path, facts: Facts, now: datetime) -> None:
    """A fresh library.db at `path` from a snapshot-shaped dict (a v1 state.json or an I2 snapshot; ✱ keys are
    ignored), in one transaction: the `library` watched folder, one song per entry, one file row per entry with a
    path (placed by the app, size/mtime/key from `facts`, NULL where it finds no file), pending/never/usage.
    Raises FileExistsError if `path` is there, ValueError for a path in no watched folder or one two entries share."""
    if path.exists():
        raise FileExistsError(path)
    stamp = now.isoformat(timespec="seconds")
    with connect(path) as conn, transaction(conn):
        for statement in SCHEMA_V1:
            conn.execute(statement)
        conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)",
                         [("schema_version", "1"), ("created", stamp)])
        _upgrade(conn, 1)
        conn.execute("INSERT INTO watched_folders (path, kind, added) VALUES (?, 'library', ?)",
                     (library.as_posix(), stamp))
        folders = _Folders(conn)
        tracks = state.get("tracks") or {}
        ids = {key: _insert_song(conn, key, entry) for key, entry in tracks.items()}
        taken: dict[tuple[int, str], str] = {}
        for key, entry in tracks.items():
            _write_aliases(conn, ids[key], key, entry.get("aliases"), new=True)
            if entry.get("path"):
                folder, rel = folders.locate(entry["path"])
                if (folder, rel) in taken:
                    raise _shared(entry["path"], tracks[taken[folder, rel]], entry)
                taken[folder, rel] = key
                _insert_file(conn, ids[key], folder, rel, entry, facts, entry["path"], stamp)
        conn.executemany("INSERT INTO pending (op) VALUES (?)", [(_dumps(op),) for op in state.get("pending") or []])
        conn.executemany("INSERT INTO never (song_key, data) VALUES (?, ?)",
                         [(k, _dumps(v)) for k, v in (state.get("never") or {}).items()])
        conn.executemany("INSERT INTO usage (service, data) VALUES (?, ?)", list(_usage_rows(state).items()))
        conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", list(_extra_rows(state).items()))


_FILE_COLUMNS = ("id", "song", "folder", "path", "online", "held", "placed_by", "ambiguous") + QUALITY


def _files(conn: sqlite3.Connection) -> list[dict]:
    return [dict(zip(_FILE_COLUMNS, row))
            for row in conn.execute(f"SELECT {', '.join(_FILE_COLUMNS)} FROM files ORDER BY id")]


def _linked(files: list[dict]) -> dict[int, dict]:
    """song id -> its linked file row (the lowest id: stage 1 links one file per song)."""
    out: dict[int, dict] = {}
    for f in files:
        if f["song"] is not None:
            out.setdefault(f["song"], f)
    return out


def _aliases(conn: sqlite3.Connection) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for song, key, alias in conn.execute(
            "SELECT i.song, s.key, i.id FROM song_ids i JOIN songs s ON s.id = i.song "
            "WHERE i.service = ? ORDER BY i.rowid", (SPOTIFY,)):
        if alias != key:
            out.setdefault(song, []).append(alias)
    return out


def _songs(conn: sqlite3.Connection) -> dict[str, tuple[int, tuple]]:
    """key -> (song id, its columns as _song_values gives them)."""
    rows = conn.execute(f"SELECT id, key, {', '.join(SONG_COLUMNS)}, extra FROM songs ORDER BY id")
    return {r[1]: (r[0], tuple(r[2:])) for r in rows}


def _records(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """The top-level records as stored (JSON text): never, usage, the meta-kept extras."""
    return {"never": dict(conn.execute("SELECT song_key, data FROM never")),
            "usage": dict(conn.execute("SELECT service, data FROM usage")),
            "meta": dict(conn.execute("SELECT key, value FROM meta WHERE key LIKE 'state.%'"))}


def _pending(conn: sqlite3.Connection) -> list[str]:
    return [op for (op,) in conn.execute("SELECT op FROM pending ORDER BY id")]


def snapshot(conn: sqlite3.Connection, library: Path) -> dict:
    """The I2 snapshot the engine and the planner work on: one entry per song (joined with its linked file), the
    top-level records, and the read-only `ambiguous` and `files` (sorted online indexed files a scan didn't hold). Only reads: hub
    threads call it while a writer works, and it works on a read-only volume. `library` is the Library/ folder; the
    snapshot names its files `Library/<rel>` whatever path its row holds (writers keep that path current)."""
    folders = _Folders(conn)
    files = _files(conn)
    linked = _linked(files)
    aliases = _aliases(conn)
    tracks, ambiguous = {}, {}
    for key, (song, values) in _songs(conn).items():
        f = linked.get(song)
        path = None if f is None else folders.path(f["folder"], f["path"])
        tracks[key] = _entry(values, aliases.get(song, []), f, path)
        if f is not None and f["ambiguous"] is not None:
            ambiguous[key] = json.loads(f["ambiguous"])
    records = _records(conn)
    out = {"version": 2, "tracks": tracks, "pending": [json.loads(op) for op in _pending(conn)],
           "never": {k: json.loads(v) for k, v in records["never"].items()},
           "qobuz_usage": {"days": {}, "signals": []}}
    out.update({s + USAGE_SUFFIX: json.loads(v) for s, v in records["usage"].items()})
    out.update({k[len(STATE_EXTRA):]: json.loads(v) for k, v in records["meta"].items()})
    out["ambiguous"] = ambiguous
    out["files"] = sorted(folders.path(f["folder"], f["path"]) for f in files if f["online"] and not f["held"])
    return out


# --- the diffing save (plan library stage 1, task 1.3) ---

OLD_COPY = ("Discjockey tried to save an old copy of its records (version {version}) into library.db. "
            "Nothing was changed.")


def _sync_records(conn: sqlite3.Connection, table: str, key_col: str, value_col: str, old: dict[str, str],
                  new: dict[str, str]) -> int:
    """Makes a key -> JSON table hold `new`, writing only the rows that differ. Returns rows written."""
    n = 0
    for k in old.keys() - new.keys():
        n += conn.execute(f"DELETE FROM {table} WHERE {key_col} = ?", (k,)).rowcount
    for k, v in new.items():
        if old.get(k) != v:
            n += conn.execute(f"INSERT OR REPLACE INTO {table} ({key_col}, {value_col}) VALUES (?, ?)",
                              (k, v)).rowcount
    return n


def _save_songs(conn: sqlite3.Connection, tracks: dict, songs: dict, aliases: dict) -> tuple[dict[str, int], int]:
    """Updates changed songs (columns, extra, aliases) and inserts new ones. Returns key -> song id, rows written."""
    ids, n = {}, 0
    assignments = ", ".join(f"{c} = ?" for c in (*SONG_COLUMNS, "extra"))
    for key, e in tracks.items():
        values = _song_values(e)
        if key not in songs:
            ids[key] = _insert_song(conn, key, e)
            n += 2 + _write_aliases(conn, ids[key], key, e.get("aliases"), new=True)  # the song and its own id
            continue
        song, stored = songs[key]
        ids[key] = song
        if values != stored:
            n += conn.execute(f"UPDATE songs SET {assignments} WHERE id = ?", (*values, song)).rowcount
        if [a for a in e.get("aliases") or [] if a != key] != aliases.get(song, []):
            n += _write_aliases(conn, song, key, e.get("aliases"))
    return ids, n


def _save_files(conn: sqlite3.Connection, tracks: dict, ids: dict[str, int], removed: list[int],
                folders: _Folders, facts: Facts, stamp: str, rekeyed: Collection[str]) -> int:
    """Writes the linked file rows whose entry file fields changed (plan task 1.3). Rows are matched by place: the
    row already at an entry's new path is linked to it (a bought file a scan found), else the song's own row moves
    there (files.id stays with a renamed file), else a new row; each keeps the song's old file's placed_by ('app'
    for a song that had none). A row no song keeps is unlinked when its file is
    still there, deleted when it is gone. Two songs on one file is a ValueError."""
    files = _files(conn)
    linked = _linked(files)
    by_place = {(f["folder"], f["path"]): f for f in files}
    changed, owners = [], {}
    for key, e in tracks.items():
        song = ids[key]
        old = linked.get(song)
        new = folders.locate(e["path"]) if e.get("path") else None
        if new is not None:
            owners.setdefault(new, []).append(key)
        if old is None and new is None:
            continue
        if old is not None and new == (old["folder"], old["path"]) and all(e.get(k) == old[k] for k in QUALITY):
            continue
        changed.append((song, e, old, new))
    shared = {p: keys for p, keys in owners.items() if len(keys) > 1}
    if shared:
        (folder, rel), keys = next(iter(shared.items()))
        raise _shared(folders.path(folder, rel), tracks[keys[0]], tracks[keys[1]])

    released = {old["id"]: old for _, _, old, new in changed if old is not None and new != (old["folder"], old["path"])}
    released.update({f["id"]: f for song in removed if (f := linked.get(song)) is not None})
    n = 0
    common = "size = ?, mtime_ns = ?, content_key = ?, " + ", ".join(f"{k} = ?" for k in QUALITY)
    for song, e, old, new in changed:
        if new is None:
            continue
        values = (*_fact_values(facts, e["path"]), *(e.get(k) for k in QUALITY))
        # a song's file stays the user's when the app replaces or renames it (stage 2's tidy-up leaves those alone);
        # a song that had no file gets one the app placed
        placed = "app" if old is None else old["placed_by"]
        row = by_place.get(new)
        if row is not None:  # the song's own row (new audio, same path) or one found there (a bought file)
            n += conn.execute(f"UPDATE files SET song = ?, {common}, placed_by = ?, online = 1, held = 0, "
                              "last_seen = ?, ambiguous = NULL WHERE id = ?", (song, *values, placed, stamp, row["id"])).rowcount
            released.pop(row["id"], None)
            row["song"] = song
        elif old is not None and old["id"] in released:  # renamed by the app: the same file, a new place
            n += conn.execute(f"UPDATE files SET folder = ?, path = ?, {common}, placed_by = ?, online = 1, "
                              "held = 0, last_seen = ?, ambiguous = NULL WHERE id = ?",
                              (*new, *values, placed, stamp, old["id"])).rowcount
            released.pop(old["id"])
            by_place.pop((old["folder"], old["path"]), None)
            by_place[new] = old
        else:
            n += _insert_file(conn, song, *new, e, facts, e["path"], stamp, placed)
    written = {unicodedata.normalize("NFC", e["path"]) for _, e, _, new in changed if new is not None}
    for path in {unicodedata.normalize("NFC", p) for p in rekeyed} - written:  # new audio under an unchanged entry: only the facts change
        row = by_place.get(folders.locate(path))
        if row is not None and (f := facts(path)) is not None:  # a file gone meanwhile: its row is the scan's
            n += conn.execute("UPDATE files SET size = ?, mtime_ns = ?, content_key = ?, last_seen = ? WHERE id = ?",
                              (f.size, f.mtime_ns, f.content_key, stamp, row["id"])).rowcount
    for f in released.values():
        if facts(folders.path(f["folder"], f["path"])) is not None:
            n += conn.execute("UPDATE files SET song = NULL, ambiguous = NULL WHERE id = ?", (f["id"],)).rowcount
        else:
            n += conn.execute("DELETE FROM files WHERE id = ?", (f["id"],)).rowcount
    return n


def save(conn: sqlite3.Connection, state: dict, *, library: Path, facts: Facts, now: datetime,
         rekeyed: Collection[str] = ()) -> int:
    """Writes an I2 snapshot back in one transaction, only what differs from the rows: changed, new and removed
    songs; the file rows of entries whose file fields changed (re-keyed through `facts`, since a swap writes new
    audio under the same path); pending (replaced whole when it differs, it is short); never; usage. ✱ keys are
    ignored. `rekeyed`: snapshot paths whose audio Discjockey rewrote in place with no entry field changing; their
    rows get size/mtime/key from `facts` again, so a later scan doesn't take them for a file replaced outside
    Discjockey. Returns the number of rows written. A v1 dict, or a file two entries share, is StateError; a path in
    no watched folder is ValueError (nothing is written either way)."""
    if state.get("version") != 2:
        raise disk.StateError(OLD_COPY.format(version=state.get("version")))
    stamp = now.isoformat(timespec="seconds")
    tracks = state.get("tracks") or {}
    with transaction(conn):
        n = sync_library_path(conn, library)
        folders = _Folders(conn)
        songs = _songs(conn)
        ids, written = _save_songs(conn, tracks, songs, _aliases(conn))
        n += written
        removed = [song for key, (song, _) in songs.items() if key not in tracks]
        n += _save_files(conn, tracks, ids, removed, folders, facts, stamp, rekeyed)
        for song in removed:
            n += conn.execute("DELETE FROM songs WHERE id = ?", (song,)).rowcount
        ops = [_dumps(op) for op in state.get("pending") or []]
        if ops != _pending(conn):
            n += conn.execute("DELETE FROM pending").rowcount
            n += sum(conn.execute("INSERT INTO pending (op) VALUES (?)", (op,)).rowcount for op in ops)
        records = _records(conn)
        n += _sync_records(conn, "never", "song_key", "data", records["never"],
                           {k: _dumps(v) for k, v in (state.get("never") or {}).items()})
        n += _sync_records(conn, "usage", "service", "data", records["usage"], _usage_rows(state))
        n += _sync_records(conn, "meta", "key", "value", records["meta"], _extra_rows(state))
    return n


# --- the scan (spec library-and-sources §6, plan task 3.2) ---

def watched_folders(conn: sqlite3.Connection) -> list[WatchedFolder]:
    return [WatchedFolder(i, Path(p), k) for i, p, k in conn.execute(
        "SELECT id, path, kind FROM watched_folders ORDER BY id")]


def known_files(conn: sqlite3.Connection) -> list[KnownFile]:
    """Every file row, as the scanner sees it."""
    return [KnownFile(i, folder, rel, size, mtime, key, song is not None, ambiguous is not None)
            for i, folder, rel, size, mtime, key, song, ambiguous in conn.execute(
                "SELECT id, folder, path, size, mtime_ns, content_key, song, ambiguous FROM files ORDER BY id")]


def _inner(folders: dict[int, PurePosixPath], folder: int) -> list[tuple[int, str]]:
    """(outer folder id, rel prefix) of a watched folder that sits inside others: a scan records the files it finds
    there under the outer folder's id."""
    inner = folders[folder]
    return [(i, inner.relative_to(root).as_posix() + "/") for i, root in folders.items()
            if i != folder and inner != root and inner.is_relative_to(root)]


def has_pending(conn: sqlite3.Connection) -> bool:
    """A step (library.run_op) is still pending: its files are between two places."""
    return conn.execute("SELECT 1 FROM pending LIMIT 1").fetchone() is not None


def apply_scan(conn: sqlite3.Connection, result: ScanResult, now: datetime,
               judged: Mapping[int, tuple[str, int | None, str]] | None = None) -> int:
    """Writes a ScanResult in one transaction (rules: the ScanResult docstring), together with the quality `judged`
    for replaced files (file id -> status, cutoff, source format; set_quality), so a replaced file's new key is never
    recorded without its new quality. Offline folders' rows are marked
    offline and keep everything else; an online folder's rows are online again and the folder's last_scan is now
    (only rows that change are written: an unchanged scan writes one row per folder). Retagged and replaced
    rows get the file's size, mtime and key; a moved row takes its new place (placed by the user), and an unlinked
    row already there gives way to it; ambiguous rows keep their candidates; new files and copies become unlinked
    rows (found there by a scan: placed by 'import'); a gone row is deleted and its song's file marked gone today.
    Held rows keep everything but are marked held (the snapshot's `held`: the planner leaves their songs alone, as
    offline ones); unreadable rows stay as they are. Returns the rows written."""
    stamp, today = now.isoformat(timespec="seconds"), now.date().isoformat()
    n = 0
    with transaction(conn):
        folders = {i: PurePosixPath(unicodedata.normalize("NFC", p))
                   for i, p in conn.execute("SELECT id, path FROM watched_folders")}
        offline = set(result.offline)
        online = [i for i in folders if i not in offline]
        held = set(result.held)
        for i in online:  # back online, and seen by this scan (a held row wasn't); only the rows that change
            n += conn.execute("UPDATE files SET online = 1 WHERE folder = ? AND online = 0", (i,)).rowcount
            n += conn.execute(
                f"UPDATE files SET held = 0 WHERE folder = ? AND held = 1 AND id NOT IN "
                f"({', '.join('?' * len(held))})", (i, *held)).rowcount
            n += conn.execute("UPDATE watched_folders SET last_scan = ? WHERE id = ?", (stamp, i)).rowcount
        for file_id in held:  # left as it is, but known not to be there: the planner leaves its song alone
            n += conn.execute("UPDATE files SET held = 1 WHERE id = ? AND held = 0", (file_id,)).rowcount
        for i in offline:
            n += conn.execute("UPDATE files SET online = 0 WHERE folder = ? AND online = 1", (i,)).rowcount
            for outer, prefix in _inner(folders, i):  # its files a scan recorded under the outer folder
                n += conn.execute("UPDATE files SET online = 0 WHERE folder = ? AND online = 1 "
                                  "AND substr(path, 1, ?) = ?", (outer, len(prefix), prefix)).rowcount
        facts = "size = ?, mtime_ns = ?, content_key = ?, last_seen = ?, ambiguous = NULL"
        for file_id, seen in (*result.retagged, *result.replaced):
            n += conn.execute(f"UPDATE files SET {facts} WHERE id = ?",
                              (seen.size, seen.mtime_ns, seen.content_key, stamp, file_id)).rowcount
        for file_id, seen in result.moved:
            # an earlier scan's candidate at the target (an unlinked row) gives way to the file that moved there
            n += conn.execute("DELETE FROM files WHERE folder = ? AND path = ? AND id != ? AND song IS NULL",
                              (seen.folder, seen.rel, file_id)).rowcount
            n += conn.execute(f"UPDATE files SET folder = ?, path = ?, placed_by = 'user', online = 1, {facts} "
                              "WHERE id = ?", (seen.folder, seen.rel, seen.size, seen.mtime_ns, seen.content_key,
                                               stamp, file_id)).rowcount
        for file_id, candidates in result.ambiguous:
            n += conn.execute("UPDATE files SET ambiguous = ? WHERE id = ?", (_dumps(candidates), file_id)).rowcount
        for seen in (*result.new, *result.copies):
            n += conn.execute(
                "INSERT INTO files (song, folder, path, size, mtime_ns, content_key, placed_by, online, first_seen, "
                "last_seen) VALUES (NULL, ?, ?, ?, ?, ?, 'import', 1, ?, ?) ON CONFLICT (folder, path) DO NOTHING",
                (seen.folder, seen.rel, seen.size, seen.mtime_ns, seen.content_key, stamp, stamp)).rowcount
        for file_id in result.gone:
            n += conn.execute("UPDATE songs SET file_gone = ? WHERE id = (SELECT song FROM files WHERE id = ?)",
                              (today, file_id)).rowcount
            n += conn.execute("DELETE FROM files WHERE id = ?", (file_id,)).rowcount
        for file_id, (status, cutoff_hz, source_format) in (judged or {}).items():
            n += set_quality(conn, file_id, status, cutoff_hz, source_format)
    return n


def set_quality(conn: sqlite3.Connection, file_id: int, status: str, cutoff_hz: int | None,
                source_format: str) -> int:
    """A file judged again after its audio was replaced outside Discjockey: it is no longer the download it was, so
    it counts as the user's own file (source 'manual', as a bought file) with the quality it has now."""
    return conn.execute("UPDATE files SET status = ?, cutoff_hz = ?, source_format = ?, source = 'manual', "
                        "source_id = NULL, source_kbps = NULL WHERE id = ?",
                        (status, cutoff_hz, source_format, file_id)).rowcount


# --- the move log (spec library-and-sources §5.2, §8.4; plan library stage 2, group 1) ---

# the skip reasons a move can carry (plan library stage 2, I6); views word them
SKIP_REASONS = frozenset({"offline", "not_found", "name_taken", "changed", "failed", "stopped", "moved_on",
                          "place_taken"})
_MOVE_COLUMNS = ("id", "batch", "seq", "kind", "file", "label", "src", "dst", "content_key", "placed_before",
                 "placed_after", "state", "reason", "detail")


def _reason_code(reason: str) -> str:
    if reason not in SKIP_REASONS:
        raise ValueError(f"{reason!r} is not a skip reason")
    return reason


def start_batch(conn: sqlite3.Connection, *, started_by: str, about: dict | None, undoes: int | None,
                moves: Sequence[PlannedMove], now: datetime) -> int:
    """Records a batch and every move it plans, in one transaction, before anything moves: each move `planned`, or
    `skipped` with its reason when its `skip` is set; `seq` is its position in `moves`. Paths are stored as snapshot
    paths (NFC); one in no watched folder, a file move that would rename its file, a folder move between two watched
    folders or an unknown skip reason is a ValueError (nothing written). Returns the batch id."""
    folders = _Folders(conn)
    rows = []
    for seq, m in enumerate(moves):
        src, dst = (unicodedata.normalize("NFC", p) for p in (m.src, m.dst))
        (src_folder, _), (dst_folder, _) = folders.locate(src), folders.locate(dst)
        if m.kind == "folder" and src_folder != dst_folder:
            raise ValueError(f"a folder move stays in its watched folder: {src!r} -> {dst!r}")
        if m.kind == "file" and PurePosixPath(src).name != PurePosixPath(dst).name:
            raise ValueError(f"a move never renames a file: {src!r} -> {dst!r}")  # spec §8.3
        state, reason, detail = ("planned", None, None) if m.skip is None else ("skipped", _reason_code(m.skip[0]),
                                                                                  m.skip[1])
        rows.append((seq, m.kind, m.file_id, m.label, src, dst, m.content_key, m.placed_before, m.placed_after, state,
                     reason, detail))
    with transaction(conn):
        batch = conn.execute("INSERT INTO move_batches (started, started_by, about, undoes) VALUES (?, ?, ?, ?)",
                             (now.isoformat(timespec="seconds"), started_by,
                              None if about is None else _dumps(about), undoes)).lastrowid
        conn.executemany(f"INSERT INTO moves (batch, {', '.join(_MOVE_COLUMNS[2:])}) "
                         f"VALUES (?, {', '.join('?' * len(_MOVE_COLUMNS[2:]))})", [(batch, *r) for r in rows])
    return batch


def _move(conn: sqlite3.Connection, move_id: int) -> dict:
    row = conn.execute(f"SELECT {', '.join(_MOVE_COLUMNS)} FROM moves WHERE id = ?", (move_id,)).fetchone()
    if row is None:
        raise ValueError(f"there is no move {move_id}")
    return dict(zip(_MOVE_COLUMNS, row))


def finish_move(conn: sqlite3.Connection, move_id: int) -> None:
    """A move that happened on disk, written in one transaction: the move becomes `done`. A `file` move's file row
    (by id) takes `dst`'s place and `placed_after` (a no-op on the place when run_op's save already wrote it; an
    unlinked row left at `dst`, whose file isn't there, gives way, as in apply_scan); a move whose file row is gone
    is only marked done. A `folder` move gives every row of its watched folder under `src` + "/" the `dst` prefix
    instead, placed_by untouched (the target folder didn't exist, so no place collides). Finishing a done move again
    changes nothing; a skipped move is a ValueError."""
    with transaction(conn):
        m = _move(conn, move_id)
        if m["state"] == "done":
            return
        if m["state"] == "skipped":
            raise ValueError(f"move {move_id} was skipped ({m['reason']}); it can't be finished")
        folders = _Folders(conn)
        folder, rel = folders.locate(m["dst"])
        if m["kind"] == "file" and m["file"] is not None:
            conn.execute("DELETE FROM files WHERE folder = ? AND path = ? AND id != ? AND song IS NULL",
                         (folder, rel, m["file"]))
            conn.execute("UPDATE files SET folder = ?, path = ?, placed_by = COALESCE(?, placed_by) WHERE id = ?",
                         (folder, rel, m["placed_after"], m["file"]))
        elif m["kind"] == "folder":
            src_folder, src_rel = folders.locate(m["src"])
            old, new = src_rel + "/", rel + "/"
            conn.execute("UPDATE files SET path = ? || substr(path, ?) WHERE folder = ? AND substr(path, 1, ?) = ?",
                         (new, len(old) + 1, src_folder, len(old), old))
        conn.execute("UPDATE moves SET state = 'done', reason = NULL, detail = NULL WHERE id = ?", (move_id,))


def skip_move(conn: sqlite3.Connection, move_id: int, reason: str, detail: str | None = None) -> None:
    """A move that didn't happen: `skipped` with its reason code and detail. Skipping a done move is a ValueError."""
    reason = _reason_code(reason)
    with transaction(conn):
        if _move(conn, move_id)["state"] == "done":
            raise ValueError(f"move {move_id} is done; it can't be skipped")
        conn.execute("UPDATE moves SET state = 'skipped', reason = ?, detail = ? WHERE id = ?",
                     (reason, detail, move_id))


def set_placed_by(conn: sqlite3.Connection, file_ids: Collection[int], value: str) -> int:
    """Marks who put these files where they are (plan library stage 2, P1: the save that leaves files where they
    are makes them the user's). Returns the rows that changed."""
    if not file_ids:
        return 0
    with transaction(conn):
        return conn.executemany("UPDATE files SET placed_by = ? WHERE id = ? AND placed_by != ?",
                                [(value, i, value) for i in file_ids]).rowcount


def close_batch(conn: sqlite3.Connection, batch_id: int, now: datetime) -> None:
    """Ends a batch in one transaction: `finished` is now (kept when it is already closed), and every move still
    `planned` becomes skipped as `stopped` (plan library stage 2, P3)."""
    with transaction(conn):
        if conn.execute("SELECT 1 FROM move_batches WHERE id = ?", (batch_id,)).fetchone() is None:
            raise ValueError(f"there is no batch {batch_id}")
        conn.execute("UPDATE moves SET state = 'skipped', reason = 'stopped', detail = NULL "
                     "WHERE batch = ? AND state = 'planned'", (batch_id,))
        conn.execute("UPDATE move_batches SET finished = ? WHERE id = ? AND finished IS NULL",
                     (now.isoformat(timespec="seconds"), batch_id))


def open_batches(conn: sqlite3.Connection) -> list[int]:
    """The batches not closed yet: still running, or stopped by a crash (tidy.recover closes them)."""
    return [i for (i,) in conn.execute("SELECT id FROM move_batches WHERE finished IS NULL ORDER BY id")]


def batch_moves(conn: sqlite3.Connection, batch_id: int) -> list[MoveRow]:
    """A batch's moves in `seq` order, each with its file row's snapshot path and key today."""
    folders = _Folders(conn)
    out = []
    for row in conn.execute(
            f"SELECT {', '.join('m.' + c for c in _MOVE_COLUMNS)}, f.folder, f.path, f.content_key "
            "FROM moves m LEFT JOIN files f ON f.id = m.file WHERE m.batch = ? ORDER BY m.seq", (batch_id,)):
        m = dict(zip(_MOVE_COLUMNS, row))
        folder, rel, key = row[len(_MOVE_COLUMNS):]
        out.append(MoveRow(id=m["id"], batch=m["batch"], seq=m["seq"], kind=m["kind"], file_id=m["file"],
                           label=m["label"], src=m["src"], dst=m["dst"], content_key=m["content_key"],
                           placed_before=m["placed_before"], placed_after=m["placed_after"], state=m["state"],
                           reason=m["reason"], detail=m["detail"],
                           now_path=None if folder is None else folders.path(folder, rel), now_key=key))
    return out


def _undoable(conn: sqlite3.Connection, folders: _Folders, batch_id: int) -> int:
    """The done moves of a batch whose undo could run today, from the rows alone (no disk): a file move whose row
    is at `dst` with its key unchanged and no row at `src`; a folder move while any row sits under `dst` + "/"."""
    n = 0
    for kind, src, dst, key, folder, rel, now_key in conn.execute(
            "SELECT m.kind, m.src, m.dst, m.content_key, f.folder, f.path, f.content_key FROM moves m "
            "LEFT JOIN files f ON f.id = m.file WHERE m.batch = ? AND m.state = 'done'", (batch_id,)):
        if kind == "folder":
            under, prefix = folders.locate(dst)
            prefix += "/"
            n += conn.execute("SELECT 1 FROM files WHERE folder = ? AND substr(path, 1, ?) = ? LIMIT 1",
                              (under, len(prefix), prefix)).fetchone() is not None
        elif folder is not None and (folder, rel) == folders.locate(dst) and now_key == key:
            n += conn.execute("SELECT 1 FROM files WHERE folder = ? AND path = ?",
                              folders.locate(src)).fetchone() is None
    return n


def batches(conn: sqlite3.Connection, limit: int = 20) -> tuple[list[BatchRow], int]:
    """The newest `limit` batches, newest first, with their counts, plus how many batches there are in all."""
    folders = _Folders(conn)
    out = []
    for i, started, finished, started_by, about, undoes, moved, skipped, undone_by in conn.execute(
            "SELECT b.id, b.started, b.finished, b.started_by, b.about, b.undoes, "
            "(SELECT COUNT(*) FROM moves m WHERE m.batch = b.id AND m.state = 'done'), "
            "(SELECT COUNT(*) FROM moves m WHERE m.batch = b.id AND m.state = 'skipped'), "
            "(SELECT MAX(u.id) FROM move_batches u WHERE u.undoes = b.id) "
            "FROM move_batches b ORDER BY b.id DESC LIMIT ?", (limit,)).fetchall():
        out.append(BatchRow(id=i, started=started, finished=finished, started_by=started_by,
                            about=None if about is None else json.loads(about), undoes=undoes, moved=moved,
                            skipped=skipped, undoable=_undoable(conn, folders, i), undone_by=undone_by))
    return out, conn.execute("SELECT COUNT(*) FROM move_batches").fetchone()[0]


# --- the migration from state.json (spec library-and-sources §5.3, plan task 1.4) ---

DB_NAME = "library.db"
BACKUP_NAME = "state.v1.json"
STUB = {"version": 2, "moved_to": DB_NAME}  # an older Discjockey reads it and stops with its version message
MIGRATING = "Updating Discjockey's records of your library (only this once; it can take a minute)..."
MIGRATION_FAILED = ("Discjockey couldn't update its records of your library ({reason}). Nothing was changed; it tries "
                    "again next time.")
SIDE_FILES = ("-wal", "-shm", "-journal")  # SQLite's files beside a database


def db_file(paths: disk.Paths) -> Path:
    return paths.data / DB_NAME


def _tmp(paths: disk.Paths) -> Path:
    return paths.data / (DB_NAME + ".tmp")


def _remove_with_side_files(path: Path) -> None:
    for p in (path, *(path.with_name(path.name + s) for s in SIDE_FILES)):
        p.unlink(missing_ok=True)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# the steps, one function each so a test can crash the migration after any of them
def _read_v1(paths: disk.Paths) -> dict:  # step 1
    return disk._load_v1(paths.state_file)


def _build(paths: disk.Paths, state: dict, raw: bytes | None, facts: Facts, now: datetime) -> None:  # step 3
    tmp = _tmp(paths)
    _remove_with_side_files(tmp)  # left over from a migration that crashed
    create(tmp, state, library=paths.library, facts=facts, now=now)
    with connect(tmp) as conn:
        if raw is not None:
            conn.execute("INSERT INTO meta (key, value) VALUES ('migrated_from', ?)", (_sha256(raw),))
        # folds the WAL into the file, so the rename below moves one complete file
        conn.execute("PRAGMA journal_mode = DELETE").fetchone()


def _place(paths: disk.Paths) -> None:  # step 4
    tmp, target = _tmp(paths), db_file(paths)
    fd = os.open(tmp, os.O_RDONLY)
    try:
        disk.full_fsync(fd)
    finally:
        os.close(fd)
    for s in SIDE_FILES:  # with no library.db these belong to nothing, and SQLite would apply them to the new one
        target.with_name(target.name + s).unlink(missing_ok=True)
    os.replace(tmp, target)
    disk.fsync_dir(paths.data)


def _backup(paths: disk.Paths) -> None:
    """Step 5: state.v1.json becomes a second name for state.json (overwriting an older backup: this is the newest
    copy), so state.json is never missing before the stub replaces it."""
    backup = paths.data / BACKUP_NAME
    tmp = backup.with_name(BACKUP_NAME + ".tmp")
    tmp.unlink(missing_ok=True)
    try:
        os.link(paths.state_file, tmp)
    except OSError:  # a volume without hard links: a copy, written out to the drive
        with open(tmp, "wb") as f:
            f.write(paths.state_file.read_bytes())
            f.flush()
            disk.full_fsync(f.fileno())
    os.replace(tmp, backup)
    disk.fsync_dir(paths.data)


SHARED_SETTLED = ("Two songs pointed at the same file, {path}: it stays with {keep}, and {other} will be "
                  "downloaded again.")
ALIAS_SHARED = "{song} and {other} share a Spotify link; it stays with {other}."
# no automatic restore from state.v1.json (plan stage 1, 3.1): it doesn't know what Discjockey did since, so
# rebuilding from it could download or misplace files; reader and writer both refuse
DB_MISSING = ("Discjockey's records (library.db) are missing from the .discjockey folder. Nothing was changed. Put "
              "the file back, for example from Time Machine, and open Discjockey again.")


def _settle(state: dict, emit: Emit) -> None:
    """Makes a state.json the database can hold, in memory only: a file two entries point at stays with the one
    whose name it has (expected_stem), else the one added first; the other becomes missing (its quality fields
    cleared) so the planner gets it again. An alias another song already has stays with that song (as create
    does). Each case is a warning."""
    tracks = state.get("tracks") or {}
    by_path: dict[str, list[str]] = {}
    for key, e in tracks.items():
        if e.get("path"):
            by_path.setdefault(unicodedata.normalize("NFC", e["path"]), []).append(key)
    for path, keys in by_path.items():
        if len(keys) < 2:
            continue
        stem = unicodedata.normalize("NFC", PurePosixPath(path).stem)

        def rank(k: str) -> tuple:
            e = tracks[k]
            named = unicodedata.normalize("NFC", expected_stem(e.get("artist") or "", e.get("title") or "")) == stem
            return not named, e.get("added") or "￿"

        keep = min(keys, key=rank)  # min keeps the first of equals: the earlier entry
        for k in keys:
            if k != keep:
                tracks[k] = {**tracks[k], "path": None, "status": "missing", **dict.fromkeys(QUALITY[1:])}
                emit(Message("warning", SHARED_SETTLED.format(path=path, keep=_name(tracks[keep]),
                                                              other=_name(tracks[k]))))
    holders = {k: k for k in tracks}
    for key, e in tracks.items():
        for a in e.get("aliases") or []:
            if a != key and (other := holders.setdefault(a, key)) != key:
                emit(Message("warning", ALIAS_SHARED.format(song=_name(e), other=_name(tracks[other]))))


def is_stub(path: Path) -> bool:
    try:
        return json.loads(path.read_bytes()).get("version") == STUB["version"]
    except (OSError, ValueError, AttributeError):
        return False


def _write_stub(paths: disk.Paths) -> None:  # step 6
    disk.write_json_atomic(paths.state_file, STUB, indent=2)


def _migrated_from(paths: disk.Paths) -> str | None:
    with connect(db_file(paths)) as conn:
        check(conn)
        row = conn.execute("SELECT value FROM meta WHERE key = 'migrated_from'").fetchone()
    return None if row is None else row[0]


def _resume(paths: disk.Paths) -> bool:
    """Finishes a migration that got as far as placing library.db. True when nothing is left to do; False when
    state.json changed since (an older Discjockey ran in between): library.db is set aside as library.db.discarded
    and the migration starts again."""
    if not paths.state_file.exists():
        _write_stub(paths)  # crashed after the backup (or a library made new): an older Discjockey must see the stub
        return True
    raw = paths.state_file.read_bytes()
    if json.loads(raw).get("version") == STUB["version"]:
        return True
    disk._load_v1(paths.state_file)  # any version but 1 and 2: its own message
    if _migrated_from(paths) == _sha256(raw):
        _backup(paths)
        _write_stub(paths)
        return True
    target = db_file(paths)
    discarded = target.with_name(DB_NAME + ".discarded")
    for s in ("", *SIDE_FILES):
        if target.with_name(target.name + s).exists():
            os.replace(target.with_name(target.name + s), discarded.with_name(discarded.name + s))
    return False


def _reason(e: Exception) -> str:
    if isinstance(e, OSError) and e.strerror:
        return e.strerror[:1].lower() + e.strerror[1:]
    return str(e) or type(e).__name__


def migrate(paths: disk.Paths, *, facts: Facts, now: datetime, emit: Emit,
            recover: Callable[[dict], None]) -> None:
    """state.json -> library.db (spec §5.3), all or nothing; the caller holds the lock. Safe to call on every open:
    with library.db in place and the stub written it does nothing, and it finishes a migration a crash interrupted.
    Steps: read state.json (v1), `recover` its pending steps (it saves to state.json as today), build
    library.db.tmp with content keys and the SHA-256 of state.json's bytes, write it out and rename it into place,
    rename state.json to state.v1.json, write the stub. Until the rename into place state.json is untouched by the
    migration itself; any failure is StateError (a state.json of another version keeps its own message)."""
    try:
        if db_file(paths).exists():
            with connect(db_file(paths)) as conn:  # every writer's open: the version check, Library/'s path
                check(conn, upgrade=True)
                sync_library_path(conn, paths.library)
            if _resume(paths):
                return
        if is_stub(paths.state_file):  # library.db was made and is gone: never rebuilt (DB_MISSING)
            raise disk.StateError(DB_MISSING)
        state = _read_v1(paths)
        recover(state)
        raw = paths.state_file.read_bytes() if paths.state_file.exists() else None
        emit(Message("info", MIGRATING))
        _settle(state, emit)
        _build(paths, state, raw, facts, now)
        _place(paths)
        if raw is not None:  # a new library has no state.json to keep
            _backup(paths)
        _write_stub(paths)
    except disk.StateError:
        _remove_with_side_files(_tmp(paths))
        raise
    except Exception as e:
        _remove_with_side_files(_tmp(paths))
        raise disk.StateError(MIGRATION_FAILED.format(reason=_reason(e))) from e
