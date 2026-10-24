"""Owns library.db: the schema, the migration from state.json, every query. Nothing else writes SQL (spec
library-and-sources §5.5).

One connection per call: `with connect(path) as conn:` opens it with the binding settings and closes it at the end
of the block (plan library stage 1, "Global constraints"). Transactions are explicit (`BEGIN IMMEDIATE`); outside
one, every statement commits by itself."""
from __future__ import annotations

import json
import sqlite3
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from . import library as disk  # "library" is the Library/ path argument everywhere here
from .planner import ENTRY_KEYS

SCHEMA_VERSION = 1

# version n -> the step that turns a version-n database into version n+1, run inside the open transaction. Stage 2
# adds move_batches/moves as step 1 -> 2.
UPGRADES: dict[int, Callable[[sqlite3.Connection], None]] = {}

NEWER = ("This music folder was last used by a newer Discjockey. Update Discjockey, then try again. "
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
    conn = sqlite3.connect(str(path), isolation_level=None, factory=_Connection)
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = FULL")
        conn.execute("PRAGMA fullfsync = ON")
        conn.execute("PRAGMA checkpoint_fullfsync = ON")
        conn.execute("PRAGMA journal_mode = WAL").fetchone()
    except sqlite3.DatabaseError:
        conn.close()
        raise disk.StateError(UNREADABLE.format(reason=DAMAGED)) from None
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """One write transaction: all of it or nothing. IMMEDIATE takes the write lock at the start, so a second writer
    waits (busy_timeout) instead of failing halfway."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _stored_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.DatabaseError:
        raise disk.StateError(UNREADABLE.format(reason=DAMAGED)) from None
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


def check(conn: sqlite3.Connection) -> None:
    """The version check every open does: a database from a newer Discjockey, or a file that isn't one, is
    StateError (nothing changed); an older one is brought up to SCHEMA_VERSION in one transaction (a failing step
    leaves it at its old version)."""
    version = _stored_version(conn)
    if version > SCHEMA_VERSION:
        raise disk.StateError(NEWER)
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
READ_ONLY = frozenset({"online", "placed_by"})  # entry keys the snapshot adds and save ignores
SNAPSHOT_ONLY = frozenset({"version", "ambiguous", "files"})  # top-level keys the snapshot adds and save ignores
NOT_EXTRA = frozenset(SONG_COLUMNS) | frozenset(FILE_FIELDS) | READ_ONLY | {"aliases"}
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
            v = 1 if v else 0
        elif v is None and (col == "artist" or col == "title"):
            v = ""
        out.append(v)
    extra = {k: v for k, v in entry.items() if k not in NOT_EXTRA}
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
    if values[-1] is not None:
        e.update(json.loads(values[-1]))
    e["aliases"] = aliases
    if file is None:
        e.update(path=None, status="missing", source=None, source_id=None, source_format=None, cutoff_hz=None,
                 source_kbps=None, online=False, placed_by=None)
    else:
        e.update({k: file[k] for k in QUALITY}, path=path, online=bool(file["online"]), placed_by=file["placed_by"])
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


def _sync_library_path(conn: sqlite3.Connection, library: Path) -> int:
    """Library/ always belongs to the music folder the user chose now: a moved music folder or a renamed drive would
    otherwise leave the row pointing at a stale path (and offline). Returns rows changed."""
    return conn.execute("UPDATE watched_folders SET path = ? WHERE kind = 'library' AND path <> ?",
                        (library.as_posix(), library.as_posix())).rowcount


def _insert_song(conn: sqlite3.Connection, key: str, entry: dict) -> int:
    cols = ", ".join(SONG_COLUMNS)
    marks = ", ".join("?" * (len(SONG_COLUMNS) + 2))
    song = conn.execute(f"INSERT INTO songs (key, {cols}, extra) VALUES ({marks})",
                        (key, *_song_values(entry))).lastrowid
    # the song's own key always points at it; an alias another song already has stays with that song
    conn.execute("INSERT OR REPLACE INTO song_ids (service, id, song) VALUES (?, ?, ?)", (SPOTIFY, key, song))
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


def _insert_file(conn, song: int, folder: int, rel: str, entry: dict, facts: Facts, path: str, now: str) -> int:
    return conn.execute(
        "INSERT INTO files (song, folder, path, size, mtime_ns, content_key, placed_by, online, first_seen, "
        "last_seen, status, source, source_id, source_format, cutoff_hz, source_kbps) "
        "VALUES (?, ?, ?, ?, ?, ?, 'app', 1, ?, ?, ?, ?, ?, ?, ?, ?)",
        (song, folder, rel, *_fact_values(facts, path), now, now, *(entry.get(k) for k in QUALITY))).rowcount


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
                    raise ValueError(f"{entry['path']!r} belongs to both {taken[folder, rel]} and {key}")
                taken[folder, rel] = key
                _insert_file(conn, ids[key], folder, rel, entry, facts, entry["path"], stamp)
        conn.executemany("INSERT INTO pending (op) VALUES (?)", [(_dumps(op),) for op in state.get("pending") or []])
        conn.executemany("INSERT INTO never (song_key, data) VALUES (?, ?)",
                         [(k, _dumps(v)) for k, v in (state.get("never") or {}).items()])
        conn.executemany("INSERT INTO usage (service, data) VALUES (?, ?)", list(_usage_rows(state).items()))
        conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", list(_extra_rows(state).items()))


_FILE_COLUMNS = ("id", "song", "folder", "path", "online", "placed_by", "ambiguous") + QUALITY


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
    top-level records, and the read-only `ambiguous` and `files` (sorted online indexed files)."""
    _sync_library_path(conn, library)
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
    out["files"] = sorted(folders.path(f["folder"], f["path"]) for f in files if f["online"])
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
                folders: _Folders, facts: Facts, stamp: str) -> int:
    """Writes the linked file rows whose entry file fields changed (plan task 1.3). Rows are matched by place: the
    row already at an entry's new path is linked to it (a bought file a scan found), else the song's own row moves
    there (files.id stays with a renamed file), else a new row. A row no song keeps is unlinked when its file is
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
        raise ValueError(f"{folders.path(folder, rel)!r} belongs to both {keys[0]} and {keys[1]}")

    released = {old["id"]: old for _, _, old, new in changed if old is not None and new != (old["folder"], old["path"])}
    released.update({f["id"]: f for song in removed if (f := linked.get(song)) is not None})
    n = 0
    common = "size = ?, mtime_ns = ?, content_key = ?, " + ", ".join(f"{k} = ?" for k in QUALITY)
    for song, e, old, new in changed:
        if new is None:
            continue
        values = (*_fact_values(facts, e["path"]), *(e.get(k) for k in QUALITY))
        row = by_place.get(new)
        if row is not None:  # the song's own row (new audio, same path) or one found there (a bought file)
            placed = row["placed_by"] if old is not None and row["id"] == old["id"] else "app"
            n += conn.execute(f"UPDATE files SET song = ?, {common}, placed_by = ?, online = 1, last_seen = ?, "
                              "ambiguous = NULL WHERE id = ?", (song, *values, placed, stamp, row["id"])).rowcount
            released.pop(row["id"], None)
            row["song"] = song
        elif old is not None and old["id"] in released:  # renamed by the app: the same file, a new place
            n += conn.execute(f"UPDATE files SET folder = ?, path = ?, {common}, placed_by = 'app', online = 1, "
                              "last_seen = ?, ambiguous = NULL WHERE id = ?",
                              (*new, *values, stamp, old["id"])).rowcount
            released.pop(old["id"])
            by_place.pop((old["folder"], old["path"]), None)
            by_place[new] = old
        else:
            n += _insert_file(conn, song, *new, e, facts, e["path"], stamp)
    for f in released.values():
        if facts(folders.path(f["folder"], f["path"])) is not None:
            n += conn.execute("UPDATE files SET song = NULL, ambiguous = NULL WHERE id = ?", (f["id"],)).rowcount
        else:
            n += conn.execute("DELETE FROM files WHERE id = ?", (f["id"],)).rowcount
    return n


def save(conn: sqlite3.Connection, state: dict, *, library: Path, facts: Facts, now: datetime) -> int:
    """Writes an I2 snapshot back in one transaction, only what differs from the rows: changed, new and removed
    songs; the file rows of entries whose file fields changed (re-keyed through `facts`, since a swap writes new
    audio under the same path); pending (replaced whole when it differs, it is short); never; usage. ✱ keys are
    ignored. Returns the number of rows written. A v1 dict is StateError; a path in no watched folder, or one two
    entries share, is ValueError (and nothing is written)."""
    if state.get("version") != 2:
        raise disk.StateError(OLD_COPY.format(version=state.get("version")))
    stamp = now.isoformat(timespec="seconds")
    tracks = state.get("tracks") or {}
    with transaction(conn):
        n = _sync_library_path(conn, library)
        folders = _Folders(conn)
        songs = _songs(conn)
        ids, written = _save_songs(conn, tracks, songs, _aliases(conn))
        n += written
        removed = [song for key, (song, _) in songs.items() if key not in tracks]
        n += _save_files(conn, tracks, ids, removed, folders, facts, stamp)
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
