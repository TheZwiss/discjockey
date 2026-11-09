"""rekordbox's library written: a track pointed at a new file, its text columns, and the way back (design
rekordbox-repoint §5.3–§5.5, §5.8 step 5, §5.9, §5.11; plan stage B §0.1, §0.12, §1.3). `master.py` stays the read
side; this module is the only place that writes `master.db` or an analysis file.

`open_write(place, dbid=…)` checks the guards with nothing opened for writing and refuses with `WriteRefused(reason)`
(a `REASONS` key): rekordbox running (`rekordbox_open`, guard 3), `-wal`/`-shm` beside the closed library (`unclean`,
guard 4), the key, `DBVersion` or a column of `READ_COLUMNS` (`rekordbox_unreadable`, guards 1–2), another library
(`other_library`, guard 7). The `Writer` it yields runs one transaction per call (`BEGIN IMMEDIATE`) and checks
guard 3 again just before `COMMIT`: rekordbox appeared → rollback, every analysis file back byte for byte, and
`RekordboxOpened`. rekordbox keeps the library in WAL mode; a keyed read-write connection makes `-wal`/`-shm` while it
is open and removes both on a clean close (checked on a copy 2026-11-08), so guard 4 still holds after our write.

- `repoint`: per track `FolderPath` (the new whole path, NFC) and `FileNameL`; `OrgFolderPath` and
  `rb_LocalFolderPath` only where each equalled the old `FolderPath` (`''` and NULL on every row of a rekordbox 7
  library); the file facts (`FileType` 12, `FileSize`, `BitDepth`, `SampleRate`, `BitRate`, `Length`); the text
  columns where `TextChange.write` says so; the analysis files' `PPTH` (spliced bytes written as `<name>.dj-new` and
  renamed over) and their `contentFile` rows (`Hash` = MD5 of the new bytes, `Size`). Refused with nothing written
  when a track's `FolderPath`/`FileNameL` no longer hold the planned before values or an analysis file changed
  (`changed`), or a track is cloud-synced (`cloud`, guard 5).
- `write_text`: the in-place AIFF swap's write, text columns and `FileSize` only.
- `undo_repoint`: identity back only while it holds exactly what we wrote (else `relocated`, nothing changed), file
  facts back whatever they hold, each text column back only where it still holds what we wrote, `PPTH` back only where
  the file still names our path. `check_undo` answers the same refusals first, without a transaction, so the caller
  moves no file before it knows; a swap's record (`identity=False`) never checks or writes the path.

Text columns (design §5.11): `Title`, `ISRC`, `Commnt` are written in place; artist, album and label are ids into
`djmdArtist`/`djmdAlbum`/`djmdLabel`, found (an active row whose `Name` equals the value, NFC exact, lowest id) or
created with rekordbox's own scheme, read on a copy of a rekordbox 7 library 2026-11-08: `ID` a random unused 32-bit
number as decimal text (rekordbox's own ids reach 4.29e9; pyrekordbox's 28-bit ids fit in that), `UUID` a random
lowercase UUID, `SearchStr` NULL (rekordbox 7 leaves it NULL on every artist and album row), the sync flags 0, `usn`
NULL, `created_at` = `updated_at` = the stamp. Existing lookup rows are never changed.

The stamp (plan §0.12, corrected by the facts): rekordbox gives **every changed or created row its own number**
(`localUpdateCount + 1`, `+ 2`, … consecutive within one change, e.g. a new artist, album and label) and leaves
`agentRegistry.localUpdateCount` at the last; it does not refresh that row's `updated_at` with each count (its
`updated_at` was older than rows with lower numbers). pyrekordbox's `autoincrement_local_update_count` also numbers
each change on its own. So per transaction: created lookup rows first (in the order made), then the tracks in id
order, then their `contentFile` rows in id order, each `rb_local_usn` the next number; `int_1` the last; every changed
row's `updated_at` is `now` as `YYYY-MM-DD HH:MM:SS.fff +00:00` (UTC).
"""
from __future__ import annotations

import hashlib
import os
import secrets
import unicodedata
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import sqlcipher3

from . import anlz, eligible, master, process
from .locate import Place
from .master import Entry

AIFF_TYPE = 12
IDENTITY = ("FolderPath", "FileNameL", "OrgFolderPath", "rb_LocalFolderPath")
FACTS = ("FileType", "FileSize", "BitDepth", "SampleRate", "BitRate", "Length")
TEXT_COLUMNS = {"title": "Title", "artist": "ArtistID", "album": "AlbumID", "label": "LabelID", "isrc": "ISRC",
                "comment": "Commnt"}
LOOKUP_TABLES = {"artist": "djmdArtist", "album": "djmdAlbum", "label": "djmdLabel"}
ANLZ_EXTS = (".DAT", ".EXT", ".2EX")  # the PMAI files that carry PPTH (.3EX is no PMAI file)
NEW_SUFFIX = ".dj-new"
BUSY_MS = 2000
_ZEROS = ("rb_data_status", "rb_local_data_status", "rb_local_deleted", "rb_local_synced", "Compilation")


class WriteRefused(Exception):
    """Nothing was written: `reason` is a `eligible.REASONS` key (`rekordbox_open`, `unclean`, `rekordbox_unreadable`,
    `changed`, `cloud`, `relocated`) or `other_library`."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class RekordboxOpened(Exception):
    """rekordbox started while a transaction was open: it was rolled back and every analysis file is as it was."""


@dataclass(frozen=True)
class TextChange:
    field: str               # one of audio.TEXT_FIELDS
    before_shown: str        # what rekordbox showed when the change was planned (the name for artist/album/label)
    write: str | None        # the clean value to write, None to leave the column
    kept: bool               # the user's own edit (text_plan said "kept")


@dataclass(frozen=True)
class RowChange:
    id: str
    before: dict[str, object]   # FolderPath and FileNameL as planned: the row must still hold them
    after: dict[str, object]    # FolderPath, FileNameL and the FACTS for a repoint; FileSize only for write_text
    text: dict[str, TextChange] = field(default_factory=dict)


@dataclass(frozen=True)
class AnlzChange:
    path: Path
    old_sha256: str
    new_bytes: bytes
    backup: Path | None = None   # the batch backup's copy (crash recovery; the writer restores from memory)
    old_ppth: str = ""
    new_ppth: str = ""


@dataclass
class RepointRow:
    id: str
    identity_before: dict[str, object]
    identity_after: dict[str, object]
    facts_before: dict[str, object]
    text: dict[str, dict[str, object]]          # field -> {"before": column value, "wrote": column value}
    kept: list[str]
    contentfile_before: list[dict[str, object]]  # [{"id", "hash", "size"}] of the rows this write changed


@dataclass
class RepointRecord:
    dbid: str
    rows: list[RepointRow]
    anlz: list[dict[str, object]]  # [{"path", "old_sha256", "new_sha256", "backup", "old_ppth", "new_ppth"}]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> RepointRecord:
        return cls(d["dbid"], [RepointRow(**r) for r in d["rows"]], [dict(a) for a in d["anlz"]])


@dataclass
class Committed:
    usn: int                          # localUpdateCount after the write
    stamp: str
    created: dict[str, list[str]]     # lookup rows made: table -> ids
    rows: list[RepointRow]
    anlz: list[dict[str, object]]
    dbid: str = ""

    def record(self) -> RepointRecord:
        """What undo needs (stored in the check's undo record and the journal)."""
        return RepointRecord(self.dbid, self.rows, self.anlz)


@dataclass
class UndoOutcome:
    usn: int
    stamp: str
    restored: dict[str, list[str]]   # row id -> text fields put back
    kept: dict[str, list[str]]       # row id -> text fields left (the user changed them since)
    anlz: dict[str, str]             # analysis file -> "restored" | "left"


# --- planning (pure, from what the read side found) ---

def _norm(text: object) -> str:
    return unicodedata.normalize("NFC", "" if text is None else str(text)).strip()


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def plan_text(entry: Entry, old_tags: dict[str, str], clean: dict[str, str]) -> dict[str, TextChange]:
    """Per text field what a write does (design §5.11, `eligible.text_plan`): the clean value where rekordbox still
    shows the old file's tag and the value differs, nothing where it already shows the clean value, and the user's
    own edit kept. A clean value that is empty never blanks what rekordbox shows (the download lacks that tag)."""
    plan = eligible.text_plan(entry, old_tags, clean)
    out = {}
    for f, what in plan.items():
        shown = getattr(entry, f)
        value = clean.get(f) or ""
        write = value if what == "write" and _norm(value) and _norm(shown) != _norm(value) else None
        out[f] = TextChange(f, shown, write, what == "kept")
    return out


def bit_rate(channels: int) -> int:
    return 44100 * 16 * channels // 1000


def row_change(entry: Entry, new_path: str, *, file_size: int, channels: int, frames: int,
               old_tags: dict[str, str], clean: dict[str, str]) -> RowChange:
    """The repoint of `entry` to the 16-bit 44.1 kHz AIFF at `new_path` (`frames` samples per channel): identity,
    file facts (`Length` whole seconds rounded down, plan §0.13) and the text plan."""
    new_path = nfc(new_path)
    return RowChange(
        entry.id, {"FolderPath": entry.folder_path, "FileNameL": entry.file_name},
        {"FolderPath": new_path, "FileNameL": new_path.rsplit("/", 1)[-1], "FileType": AIFF_TYPE,
         "FileSize": file_size, "BitDepth": 16, "SampleRate": 44100, "BitRate": bit_rate(channels),
         "Length": frames // 44100},
        plan_text(entry, old_tags, clean))


def text_change(entry: Entry, *, file_size: int, old_tags: dict[str, str], clean: dict[str, str]) -> RowChange:
    """The in-place swap's write for `entry`: its text plan and the new `FileSize` (plan §0.6)."""
    return RowChange(entry.id, {"FolderPath": entry.folder_path, "FileNameL": entry.file_name},
                     {"FileSize": file_size}, plan_text(entry, old_tags, clean))


def analysis_folder(place: Place, entry: Entry) -> Path | None:
    """The folder of `entry`'s analysis files under the library's `share` folder, or None without analysis."""
    if not entry.analysis_path:
        return None
    return (place.share / entry.analysis_path.lstrip("/")).parent


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def anlz_changes(place: Place, entry: Entry, new_path: str,
                 backup_of: Callable[[Path], Path] | None = None) -> tuple[list[AnlzChange], list[str]]:
    """The `PPTH` splices for `entry`'s analysis files, and the files left alone because their `PPTH` names something
    other than the track's old file (`ppth: "other"`). `backup_of` maps a file to its copy in the batch backup."""
    folder = analysis_folder(place, entry)
    changes: list[AnlzChange] = []
    others: list[str] = []
    if folder is None or not folder.is_dir():
        return changes, others
    for path in sorted(folder.iterdir()):
        if path.suffix.upper() not in ANLZ_EXTS or not path.is_file():
            continue
        a = anlz.read(path)
        if a is None:
            continue
        current = anlz.ppth(a)
        target = anlz.ppth_after(current, entry.folder_path, new_path)
        if target is None:
            others.append(str(path))
            continue
        changes.append(AnlzChange(path, sha256_of(a.data), anlz.splice_ppth(a, target),
                                  backup_of(path) if backup_of else None, current or "", target))
    return changes, others


# --- the write ---

def stamp_of(now: datetime) -> str:
    """rekordbox's timestamp: `YYYY-MM-DD HH:MM:SS.fff +00:00`, UTC."""
    now = now.astimezone(UTC)
    return now.strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d} +00:00"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _id_key(value: object) -> tuple[int, int, str]:
    text = str(value)
    return (0, int(text), "") if text.isdigit() else (1, 0, text)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def replace_bytes(path: Path, data: bytes) -> None:
    """`data` into `path` through `<name>.dj-new`, flushed and renamed over: never a half-written file."""
    tmp = path.with_name(path.name + NEW_SUFFIX)
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def remove_leftover(path: Path) -> None:
    """Deletes `<name>.dj-new` beside `path`: what a crash between `replace_bytes`' write and its rename leaves."""
    path.with_name(path.name + NEW_SUFFIX).unlink(missing_ok=True)


@contextmanager
def open_write(place: Place, *, dbid: str | None, running: Callable[[], bool] | None = None,
               clock: Callable[[], datetime] = _utcnow) -> Iterator[Writer]:
    """`place`'s library opened for writing after guards 1–4 and 7, closed on leaving. Raises `WriteRefused` with
    nothing opened for writing. `dbid`: the library the batch read (None skips the compare). `running` is looked up
    at call time when left out."""
    running = running or process.running
    if running():
        raise WriteRefused("rekordbox_open")
    if master.leftovers(place.db):
        raise WriteRefused("unclean")
    try:  # guards 1 and 2 on a read-only open first: a wrong key or schema never gets a read-write connection
        with master.open_read(place, False) as m:
            found = m.dbid
    except master.Unreadable:
        raise WriteRefused("rekordbox_unreadable") from None
    if dbid is not None and found != dbid:
        raise WriteRefused("other_library")
    con = _open_rw(place.db)
    try:
        yield Writer(con, place, found or "", running, clock)
    finally:
        con.close()


def _open_rw(db: Path):
    for key in master.KEYS:
        con = sqlcipher3.connect(Path(db).absolute().as_uri(), uri=True, isolation_level=None)
        try:
            con.execute(f"PRAGMA key = '{key}'")
            con.execute("SELECT count(*) FROM sqlite_master").fetchone()
            con.execute(f"PRAGMA busy_timeout = {BUSY_MS}")
            return con
        except sqlcipher3.DatabaseError:
            con.close()
    raise WriteRefused("rekordbox_unreadable")


class _Usn:
    """The transaction's numbers: each changed or created row takes the next one; `int_1` ends at the last."""

    def __init__(self, con):
        row = con.execute("SELECT int_1 FROM agentRegistry WHERE registry_id = 'localUpdateCount'").fetchone()
        if row is None:
            raise WriteRefused("rekordbox_unreadable")
        self.value = int(row[0] or 0)

    def next(self) -> int:
        self.value += 1
        return self.value

    def save(self, con) -> None:
        con.execute("UPDATE agentRegistry SET int_1 = ? WHERE registry_id = 'localUpdateCount'", (self.value,))


class Writer:
    """An open read-write `master.db` (from `open_write`). Every method is one transaction."""

    def __init__(self, con, place: Place, dbid: str, running: Callable[[], bool], clock: Callable[[], datetime]):
        self.con = con
        self.place = place
        self.dbid = dbid
        self._running = running
        self._clock = clock

    # -- transaction frame --

    @contextmanager
    def _transaction(self, running: Callable[[], bool] | None) -> Iterator[list[tuple[Path, bytes]]]:
        """BEGIN IMMEDIATE … guard 3 … COMMIT. Yields the list the body appends (path, original bytes) to before it
        overwrites an analysis file; on any failure those files get their bytes back."""
        written: list[tuple[Path, bytes]] = []
        try:
            self.con.execute("BEGIN IMMEDIATE")
        except sqlcipher3.OperationalError:  # another program holds the library
            raise WriteRefused("rekordbox_open") from None
        try:
            yield written
            if (running or self._running)():
                raise RekordboxOpened()
            self.con.execute("COMMIT")
        except BaseException:
            try:
                self.con.execute("ROLLBACK")
            except sqlcipher3.Error:
                pass
            for path, original in reversed(written):
                replace_bytes(path, original)
            raise

    def _rows(self, ids: list[str]) -> dict[str, dict[str, object]]:
        cols = ("ID", *IDENTITY, *FACTS, "Title", "ArtistID", "AlbumID", "LabelID", "ISRC", "Commnt", "usn",
                "rb_local_synced", "rb_local_deleted", "AnalysisDataPath")
        out = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            for row in self.con.execute(f"SELECT {', '.join(cols)} FROM djmdContent "
                                        f"WHERE ID IN ({','.join('?' * len(chunk))})", chunk):
                out[str(row[0])] = dict(zip(cols, row))
        return out

    def _shown(self, field_name: str, row: dict[str, object]) -> str:
        column = TEXT_COLUMNS[field_name]
        if field_name not in LOOKUP_TABLES:
            return "" if row[column] is None else str(row[column])
        if row[column] in (None, ""):
            return ""
        found = self.con.execute(f"SELECT Name FROM {LOOKUP_TABLES[field_name]} WHERE ID = ?",
                                 (row[column],)).fetchone()
        return "" if found is None or found[0] is None else str(found[0])

    def _lookup(self, table: str, name: str, usn: _Usn, stamp: str, created: dict[str, list[str]]) -> str:
        """The id of the active `table` row named `name` (NFC exact, lowest id), else of a new one."""
        target = nfc(name)
        found = [r[0] for r in self.con.execute(
            f"SELECT ID, Name FROM {table} WHERE IFNULL(rb_local_deleted, 0) = 0") if nfc(r[1] or "") == target]
        if found:
            return str(min(found, key=_id_key))
        columns = [r[1] for r in self.con.execute(f"PRAGMA table_info({table})")]
        new_id = self._unused_id(table)
        values: dict[str, object] = {"ID": new_id, "Name": target, "UUID": str(uuid.uuid4()),
                                     "rb_local_usn": usn.next(), "created_at": stamp, "updated_at": stamp}
        values.update({c: 0 for c in _ZEROS if c in columns})
        values = {k: v for k, v in values.items() if k in columns}
        self.con.execute(f"INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
                         list(values.values()))
        created.setdefault(table, []).append(new_id)
        return new_id

    def _unused_id(self, table: str) -> str:
        while True:
            candidate = str(secrets.randbelow(2 ** 32))
            if int(candidate) >= 100 and self.con.execute(
                    f"SELECT 1 FROM {table} WHERE ID = ?", (candidate,)).fetchone() is None:
                return candidate

    def _check_rows(self, changes: list[RowChange]) -> dict[str, dict[str, object]]:
        rows = self._rows([c.id for c in changes])
        for c in changes:
            row = rows.get(c.id)
            if row is None or int(row["rb_local_deleted"] or 0):
                raise WriteRefused("changed")
            if any(row[k] != v for k, v in c.before.items()):
                raise WriteRefused("changed")
            if row["usn"] is not None or int(row["rb_local_synced"] or 0):
                raise WriteRefused("cloud")
        return rows

    def _texts(self, changes: list[RowChange], rows: dict[str, dict[str, object]], usn: _Usn, stamp: str,
               created: dict[str, list[str]]) -> dict[str, tuple[dict[str, object], dict[str, dict], list[str]]]:
        """Per row the text columns to set, what undo needs, and the fields kept. Lookup rows are made here, before
        any track takes a number."""
        out = {}
        for c in changes:
            row = rows[c.id]
            sets: dict[str, object] = {}
            record: dict[str, dict] = {}
            kept: list[str] = []
            for f, tc in c.text.items():
                if tc.kept:
                    kept.append(f)
                    continue
                if tc.write is None:
                    continue
                shown = self._shown(f, row)
                if _norm(shown) != _norm(tc.before_shown):  # changed since it was planned: the user's now
                    kept.append(f)
                    continue
                column = TEXT_COLUMNS[f]
                if f in LOOKUP_TABLES:
                    value = self._lookup(LOOKUP_TABLES[f], tc.write, usn, stamp, created) if tc.write else None
                else:
                    value = nfc(tc.write)
                if value != row[column]:
                    sets[column] = value
                    record[f] = {"before": row[column], "wrote": value}
            out[c.id] = (sets, record, kept)
        return out

    def _content_files(self, row_id: str, paths: list[str]) -> list[tuple]:
        if not paths:
            return []
        return self.con.execute(
            f"SELECT ID, Path, Hash, Size FROM contentFile WHERE ContentID = ? AND Path IN "
            f"({','.join('?' * len(paths))}) ORDER BY ID", (row_id, *paths)).fetchall()

    def _rel(self, path: Path) -> str | None:
        try:
            return "/" + Path(path).relative_to(self.place.share).as_posix()
        except ValueError:
            return None

    def _rows_of_files(self, files: list[Path], ids: list[str]) -> dict[str, list[str]]:
        """Which tracks' `contentFile` rows name each analysis file (by `Path`)."""
        by_row: dict[str, list[str]] = {i: [] for i in ids}
        rels = [r for r in (self._rel(p) for p in files) if r]
        for i in ids:
            by_row[i] = [str(r[1]) for r in self._content_files(i, rels)]
        return by_row

    def _set(self, table: str, key: str, key_value: object, values: dict[str, object]) -> None:
        if values:
            self.con.execute(f"UPDATE {table} SET {', '.join(f'{k} = ?' for k in values)} WHERE {key} = ?",
                             (*values.values(), key_value))

    # -- repoint --

    def repoint(self, changes: list[RowChange], anlz_changes: list[AnlzChange], *,
                running: Callable[[], bool] | None = None,
                prepared: Callable[[Committed], None] | None = None) -> Committed:
        """Points each track of `changes` at its new file and splices `anlz_changes`, in one transaction.
        `prepared` gets the outcome after every change is made and before guard 3 and `COMMIT`: a caller journals
        the undo record there, so a crash right after the commit still finds it (an exception rolls back)."""
        stamp = stamp_of(self._clock())
        with self._transaction(running) as written:
            rows = self._check_rows(changes)
            originals = []
            for ac in anlz_changes:
                data = Path(ac.path).read_bytes()
                if sha256_of(data) != ac.old_sha256:
                    raise WriteRefused("changed")
                originals.append((Path(ac.path), data))
            usn = _Usn(self.con)
            created: dict[str, list[str]] = {}
            texts = self._texts(changes, rows, usn, stamp, created)
            files = self._rows_of_files([Path(a.path) for a in anlz_changes], [c.id for c in changes])
            out_rows = []
            for c in sorted(changes, key=lambda c: _id_key(c.id)):
                row = rows[c.id]
                old_path = row["FolderPath"]
                sets = {k: v for k, v in c.after.items() if k in FACTS or k in ("FolderPath", "FileNameL")}
                if "FolderPath" in c.after:
                    for col in ("OrgFolderPath", "rb_LocalFolderPath"):
                        if row[col] is not None and row[col] == old_path:
                            sets[col] = c.after["FolderPath"]
                text_sets, text_record, kept = texts[c.id]
                sets.update(text_sets)
                sets.update(rb_local_usn=usn.next(), updated_at=stamp)
                self._set("djmdContent", "ID", c.id, sets)
                identity_before = {k: row[k] for k in IDENTITY}
                identity_after = {k: sets.get(k, row[k]) for k in IDENTITY}
                facts_before = {k: row[k] for k in FACTS if k in c.after}
                out_rows.append(RepointRow(c.id, identity_before, identity_after, facts_before, text_record, kept, []))
            by_id = {r.id: r for r in out_rows}
            new_by_rel = {self._rel(Path(a.path)): a for a in anlz_changes}
            for r in out_rows:
                for cf_id, path, old_hash, old_size in self._content_files(r.id, files[r.id]):
                    ac = new_by_rel[path]
                    by_id[r.id].contentfile_before.append({"id": cf_id, "hash": old_hash, "size": old_size})
                    self._set("contentFile", "ID", cf_id,
                              {"Hash": hashlib.md5(ac.new_bytes).hexdigest(),  # noqa: S324 (rekordbox's checksum)
                               "Size": len(ac.new_bytes), "rb_local_usn": usn.next(), "updated_at": stamp})
            usn.save(self.con)
            for path, data in originals:
                written.append((path, data))
                replace_bytes(path, next(a.new_bytes for a in anlz_changes if Path(a.path) == path))
            anlz_record = [{"path": str(a.path), "old_sha256": a.old_sha256, "new_sha256": sha256_of(a.new_bytes),
                            "backup": None if a.backup is None else str(a.backup), "old_ppth": a.old_ppth,
                            "new_ppth": a.new_ppth} for a in anlz_changes]
            committed = Committed(usn.value, stamp, created, out_rows, anlz_record, self.dbid)
            if prepared is not None:
                prepared(committed)
        return committed

    def write_text(self, changes: list[RowChange], *, running: Callable[[], bool] | None = None,
                   prepared: Callable[[Committed], None] | None = None) -> Committed:
        """The in-place swap's write: text columns and `FileSize` only (no path, no analysis file). Its record is
        undone with `undo_repoint(..., identity=False)`."""
        for c in changes:
            extra = set(c.after) - {"FileSize"}
            if extra:
                raise ValueError(f"write_text changes only FileSize and text, not {sorted(extra)}")
        return self.repoint(changes, [], running=running, prepared=prepared)

    # -- undo --

    def check_undo(self, record: RepointRecord, *, identity: bool = True) -> None:
        """Design §5.9 step 1 without a transaction: refuses (`WriteRefused`) as `undo_repoint` would, so the caller
        changes nothing on disk before it knows the undo can run (rekordbox is closed: nothing changes in between,
        and `undo_repoint` checks again)."""
        if record.dbid and self.dbid and record.dbid != self.dbid:
            raise WriteRefused("other_library")
        self._undoable(record, self._rows([r.id for r in record.rows]), identity)

    @staticmethod
    def _undoable(record: RepointRecord, rows: dict[str, dict[str, object]], identity: bool) -> None:
        for r in record.rows:
            row = rows.get(r.id)
            if row is None or int(row["rb_local_deleted"] or 0):
                if not identity:
                    continue  # a swap's track removed from rekordbox since: nothing to put back there
                raise WriteRefused("relocated")
            if identity and any(row[k] != v for k, v in r.identity_after.items()):
                raise WriteRefused("relocated")
            if row["usn"] is not None or int(row["rb_local_synced"] or 0):
                raise WriteRefused("cloud")

    def undo_repoint(self, record: RepointRecord, *, running: Callable[[], bool] | None = None,
                     identity: bool = True, prepared: Callable[[UndoOutcome], None] | None = None) -> UndoOutcome:
        """Puts back what `record` wrote (design §5.9 steps 1 and 3). Refuses (`relocated`) with nothing changed when
        a track's identity no longer holds exactly what was written, or the track is gone. `identity=False` is the
        in-place swap's record (`write_text`: no path was written): its identity is neither checked nor written, so a
        track the user relocated since still gets its text back. `prepared` gets the outcome after every change and
        before guard 3 and `COMMIT`, as `repoint`'s."""
        if record.dbid and self.dbid and record.dbid != self.dbid:
            raise WriteRefused("other_library")
        stamp = stamp_of(self._clock())
        restored: dict[str, list[str]] = {}
        kept: dict[str, list[str]] = {}
        anlz_state: dict[str, str] = {}
        with self._transaction(running) as written:
            rows = self._rows([r.id for r in record.rows])
            self._undoable(record, rows, identity)
            back: list[tuple[Path, bytes, bytes, dict]] = []  # path, now, put back, record entry
            for a in record.anlz:
                path = Path(str(a["path"]))
                parsed = anlz.read(path)
                if parsed is None or anlz.ppth(parsed) != a["new_ppth"] or not a["old_ppth"]:
                    anlz_state[str(path)] = "left"  # re-analysed (or gone) since: rekordbox's own file now
                    continue
                back.append((path, parsed.data, anlz.splice_ppth(parsed, str(a["old_ppth"])), a))
            usn = _Usn(self.con)
            present = [r for r in record.rows if r.id in rows and not int(rows[r.id]["rb_local_deleted"] or 0)]
            for r in sorted(present, key=lambda r: _id_key(r.id)):
                row = rows[r.id]
                sets: dict[str, object] = {}
                if identity:
                    sets.update({k: v for k, v in r.identity_before.items() if row[k] != v})
                sets.update(r.facts_before)
                restored[r.id], kept[r.id] = [], []
                for f, t in r.text.items():
                    column = TEXT_COLUMNS[f]
                    if row[column] == t["wrote"]:
                        sets[column] = t["before"]
                        restored[r.id].append(f)
                    else:
                        kept[r.id].append(f)
                sets.update(rb_local_usn=usn.next(), updated_at=stamp)
                self._set("djmdContent", "ID", r.id, sets)
            back_rels = {self._rel(p): (p, data, entry) for p, _now, data, entry in back}
            for r in sorted(present, key=lambda r: _id_key(r.id)):
                before = {c["id"]: c for c in r.contentfile_before}
                for cf_id, path, _hash, _size in self._content_files(r.id, [k for k in back_rels if k]):
                    _p, data, entry = back_rels[path]
                    old = before.get(cf_id)
                    if old is not None and sha256_of(data) == entry["old_sha256"]:
                        values = {"Hash": old["hash"], "Size": old["size"]}
                    else:
                        values = {"Hash": hashlib.md5(data).hexdigest(), "Size": len(data)}  # noqa: S324
                    self._set("contentFile", "ID", cf_id, {**values, "rb_local_usn": usn.next(), "updated_at": stamp})
            usn.save(self.con)
            for path, now_bytes, data, _entry in back:
                written.append((path, now_bytes))
                replace_bytes(path, data)
                anlz_state[str(path)] = "restored"
            outcome = UndoOutcome(usn.value, stamp, restored, kept, anlz_state)
            if prepared is not None:
                prepared(outcome)
        return outcome
