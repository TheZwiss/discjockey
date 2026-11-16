"""Backups of rekordbox's library, one per batch (design rekordbox-repoint §5.7; plan stage B §1.5, §0.14).

A backup is a folder `<music folder>/.discjockey/rekordbox/backups/<UTC YYYYMMDDTHHMMSSZ>[-n]/` holding:
- `master.db`: a plain file copy, made only while no `-wal`/`-shm` lies beside the library (guard 4: then the file
  alone is the whole library) and checked by SHA-256 against the source before and after the copy;
- `share/<the analysis folder>/`: every file of each backed-up track's analysis folder, the first copy (what goes
  with this `master.db`). A folder that a later batch adds to a reused backup and that is already there with other
  bytes is copied again under `later/<batch id>/…`, so a crash's rollback (`anlz_copy`) always finds the bytes from
  just before its own batch;
- `manifest.json`: `app_version`, `dbid`, `db_version`, `created`, `master_sha256_before`, `master_sha256_after`
  (null until `close`), `batches`, `tracks` (`[{"track", "folders": [share-relative]}]`).

`Backup.ensure` reuses the newest backup whose `master_sha256_after` equals `master.db`'s current SHA-256 (nothing has
changed the library since that batch ended), else makes a new one. `prune` keeps the backups an undo record or an
unfinished batch names plus the newest 3. `restore` is the last resort (`discjockey rekordbox restore`): it first saves
the current library as a backup of its own, then puts the backup's `master.db` and analysis files back, each through
`<name>.dj-new` and a rename, and lists the tracks that now point at a file that isn't there (repointed since that
backup: their old files are in `Superseded/`).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .. import __version__
from . import master, process
from .lock import writer_lock
from .locate import Place
from .write import NEW_SUFFIX, WriteRefused, remove_leftover, replace_bytes

KEEP_NEWEST = 3
MANIFEST = "manifest.json"
_CHUNK = 1 << 20


def backups_dir(paths) -> Path:
    return paths.data / "rekordbox" / "backups"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _write_json(path: Path, data: dict) -> None:
    replace_bytes(path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def _copy_checked(src: Path, dst: Path) -> str:
    """`src` copied to `dst` through `<name>.dj-new`, flushed and renamed; its SHA-256 the same before, after and in
    the copy (else `WriteRefused("changed")`: something wrote the file meanwhile). Answers the SHA-256."""
    before = sha256_file(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + NEW_SUFFIX)
    shutil.copyfile(src, tmp)
    with open(tmp, "rb+") as f:
        os.fsync(f.fileno())
    if sha256_file(tmp) != before or sha256_file(src) != before:
        tmp.unlink(missing_ok=True)
        raise WriteRefused("changed")
    os.replace(tmp, dst)
    return before


@dataclass(frozen=True)
class BackupInfo:
    id: str
    created: str
    batches: list
    size: int
    tracks: int


@dataclass(frozen=True)
class RestoreResult:
    saved_current: str
    missing_after: list[dict]   # [{"id", "path": what the track points at now, "was": what it pointed at before}]


class RestoreRefused(Exception):
    """`reason`: `rekordbox_open`, `unclean`, `not_found`, `damaged` (the backup's master.db isn't the one its manifest
    names), `other_library` (made from another rekordbox library), `no_rekordbox`."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Backup:
    """One backup folder and its manifest."""

    def __init__(self, folder: Path, manifest: dict):
        self.folder = folder
        self.manifest = manifest

    @property
    def id(self) -> str:
        return self.folder.name

    @classmethod
    def load(cls, folder: Path) -> Backup | None:
        try:
            data = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return cls(folder, data) if isinstance(data, dict) else None

    def _save(self) -> None:
        _write_json(self.folder / MANIFEST, self.manifest)

    # -- making and reusing --

    @classmethod
    def ensure(cls, paths, place: Place, *, dbid: str | None, batch_id: int | None,
               tracks: Iterable[tuple[str, list[Path]]], db_version: str | None = None,
               now: Callable[[], datetime] = _now) -> Backup:
        """The backup a batch writes under (before its first rekordbox write): the newest one whose
        `master_sha256_after` equals `master.db`'s SHA-256 now, with this batch's id and tracks added, else a new one.
        `tracks`: (track id, its analysis folders under `place.share`). Raises `WriteRefused("unclean")` while
        `-wal`/`-shm` lie beside the library."""
        if master.leftovers(place.db):
            raise WriteRefused("unclean")
        current = sha256_file(place.db)
        for b in _all(paths):
            if b.manifest.get("master_sha256_after") == current and b.manifest.get("dbid") == dbid:
                b.manifest["master_sha256_after"] = None  # open again until this batch closes it
                b._add(place, batch_id, tracks)
                return b
        return cls._new(paths, place, dbid=dbid, batch_id=batch_id, tracks=tracks, db_version=db_version, now=now)

    @classmethod
    def _new(cls, paths, place: Place, *, dbid, batch_id, tracks, db_version, now) -> Backup:
        root = backups_dir(paths)
        root.mkdir(parents=True, exist_ok=True)
        stem = now().strftime("%Y%m%dT%H%M%SZ")
        folder, n = root / stem, 1
        while True:
            try:
                folder.mkdir()
                break
            except FileExistsError:
                n += 1
                folder = root / f"{stem}-{n}"
        sha = _copy_checked(place.db, folder / "master.db")
        b = cls(folder, {"app_version": __version__, "dbid": dbid, "db_version": db_version,
                         "created": now().isoformat(timespec="seconds"), "master_sha256_before": sha,
                         "master_sha256_after": None, "batches": [], "tracks": []})
        b._add(place, batch_id, tracks)
        return b

    def add_tracks(self, place: Place, batch_id: int | None, tracks: Iterable[tuple[str, list[Path]]]) -> None:
        """More of the batch's tracks (their analysis folders copied in before their write)."""
        self._add(place, batch_id, tracks)

    def _add(self, place: Place, batch_id: int | None, tracks: Iterable[tuple[str, list[Path]]]) -> None:
        if batch_id is not None and batch_id not in self.manifest["batches"]:
            self.manifest["batches"].append(batch_id)
        known = {(t["track"], tuple(t["folders"])) for t in self.manifest["tracks"]}
        for track, folders in tracks:
            rels = []
            for folder in folders:
                rel = _share_rel(place, folder)
                if rel is None or not folder.is_dir():
                    continue
                rels.append(rel)
                self._copy_folder(folder, rel, batch_id)
            if (track, tuple(rels)) not in known:
                self.manifest["tracks"].append({"track": track, "folders": rels})
                known.add((track, tuple(rels)))
        self._save()

    def _copy_folder(self, folder: Path, rel: str, batch_id: int | None) -> None:
        first = self.folder / "share" / rel
        for src in sorted(p for p in folder.iterdir() if p.is_file() and not p.name.endswith(NEW_SUFFIX)):
            kept = first / src.name
            if not kept.exists():
                _copy_checked(src, kept)
            elif sha256_file(kept) != sha256_file(src):
                later = self.folder / "later" / str(batch_id) / rel / src.name
                if not later.exists() or sha256_file(later) != sha256_file(src):  # not a stale copy of an earlier undo
                    _copy_checked(src, later)

    def anlz_copy(self, place: Place, path: Path, batch_id: int | None) -> Path | None:
        """The copy of the analysis file `path` as it was before batch `batch_id` wrote it, or None."""
        rel = _share_rel(place, path.parent)
        if rel is None:
            return None
        for candidate in (self.folder / "later" / str(batch_id) / rel / path.name,
                          self.folder / "share" / rel / path.name):
            if candidate.is_file():
                return candidate
        return None

    def close(self, place: Place, *, batch_id: int | None = None) -> None:
        """At the batch's end (also when stopped): `master_sha256_after` = the library's SHA-256 now, so the next batch
        can reuse this backup while nothing else changes the library."""
        if batch_id is not None and batch_id not in self.manifest["batches"]:
            self.manifest["batches"].append(batch_id)
        if place.db.is_file() and not master.leftovers(place.db):
            self.manifest["master_sha256_after"] = sha256_file(place.db)
        self._save()

    def info(self) -> BackupInfo:
        size = sum(p.stat().st_size for p in self.folder.rglob("*") if p.is_file())
        return BackupInfo(self.id, str(self.manifest.get("created") or ""), list(self.manifest.get("batches") or []),
                          size, len(self.manifest.get("tracks") or []))


def _share_rel(place: Place, folder: Path) -> str | None:
    try:
        return Path(folder).relative_to(place.share).as_posix()
    except ValueError:
        return None


def _all(paths) -> list[Backup]:
    """Every readable backup, newest first."""
    root = backups_dir(paths)
    if not root.is_dir():
        return []
    found = [b for b in (Backup.load(f) for f in root.iterdir() if f.is_dir()) if b is not None]
    return sorted(found, key=lambda b: (str(b.manifest.get("created") or ""), b.id), reverse=True)


def backups(paths) -> list[BackupInfo]:
    """The backups of this music folder, newest first."""
    return [b.info() for b in _all(paths)]


def find(paths, backup_id: str) -> Backup | None:
    return next((b for b in _all(paths) if b.id == backup_id), None)


def prune(paths, keep_ids: set[str]) -> list[str]:
    """Deletes every backup except `keep_ids` (named by an undo record or an unfinished batch) and the newest 3.
    Answers the ids deleted. A backup holds Discjockey's own copies, never a music file."""
    removed = []
    for i, b in enumerate(_all(paths)):
        if i < KEEP_NEWEST or b.id in keep_ids:
            continue
        shutil.rmtree(b.folder)
        removed.append(b.id)
    return removed


def restore(paths, place: Place | None, backup_id: str, *, running: Callable[[], bool] | None = None,
            now: Callable[[], datetime] = _now) -> RestoreResult:
    """Puts rekordbox's library back as backup `backup_id` holds it. Refuses (`RestoreRefused`) with nothing changed
    while rekordbox runs, with `-wal`/`-shm` beside the library, for an unknown or damaged backup, or one made from
    another library; raises `Busy` (nothing changed) while another Discjockey writer holds `rekordbox.lock`, which
    the whole restore holds. Saves the current library first (`saved_current`). `running` is looked up at call time
    when left out."""
    with writer_lock(paths.support):
        return _restore(paths, place, backup_id, running or process.running, now)


def _backup_of(paths, place: Place | None, backup_id: str) -> Backup:
    """The backup `backup_id` names, or `RestoreRefused` (`no_rekordbox`, `not_found`)."""
    if place is None or not place.db.is_file():
        raise RestoreRefused("no_rekordbox")
    b = find(paths, backup_id)
    if b is None or not (b.folder / "master.db").is_file():
        raise RestoreRefused("not_found")
    return b


def _verified(b: Backup, place: Place, running: bool) -> tuple[str | None, str | None]:
    """What a restore of `b` checks of the two libraries, in this order: `-wal`/`-shm` beside the current one (`unclean`;
    with rekordbox running they are normal and not looked at), the backup's own `master.db` against its manifest
    (`damaged`), the library it was made from against this Mac's (`other_library`: also when the current library can be
    read and the backup's manifest names no library). A current library that can't be read is not compared: restore is
    the repair for it, and the backup's own checksum was checked. Answers (dbid, db_version) of the current library,
    None where it can't be read."""
    if not running and master.leftovers(place.db):
        raise RestoreRefused("unclean")
    if sha256_file(b.folder / "master.db") != b.manifest.get("master_sha256_before"):
        raise RestoreRefused("damaged")
    try:
        with master.open_read(place, running) as m:
            dbid, db_version = m.dbid, m.db_version
    except master.Unreadable:
        dbid, db_version = None, None
    if dbid and b.manifest.get("dbid") != dbid:  # a backup that names no library can't be shown to be this one's
        raise RestoreRefused("other_library")
    return dbid, db_version


def preview(paths, place: Place | None, backup_id: str, running: bool) -> list[dict] | None:
    """What `restore` would leave missing, before it runs (the dry run): the tracks whose path the backup changes and
    whose path in the backup names no file, `[{"id", "path", "was"}]` as `RestoreResult.missing_after`; None when
    the current library can't be read, so what it holds is unknown. The same refusals
    as `restore` except `rekordbox_open` (`running` says rekordbox runs: the caller says so beside the list). Reads only:
    no lock, nothing is saved or written; the caller holds `rekordbox.lock` shared while master.db is read (opened
    shared, not immutable, while rekordbox runs with `-wal` and `-shm` there)."""
    b = _backup_of(paths, place, backup_id)
    _verified(b, place, running)
    return _missing_after(place.db, b.folder / "master.db", running)


def _restore(paths, place: Place | None, backup_id: str, running: Callable[[], bool],
             now: Callable[[], datetime]) -> RestoreResult:
    b = _backup_of(paths, place, backup_id)
    if running():
        raise RestoreRefused("rekordbox_open")
    dbid, db_version = _verified(b, place, False)
    folders = [(t["track"], [place.share / rel for rel in t["folders"]]) for t in b.manifest.get("tracks") or []]
    saved = Backup._new(paths, place, dbid=dbid, batch_id=None, tracks=folders, db_version=db_version, now=now)
    saved.close(place)
    share = b.folder / "share"
    targets = [(src, place.share / src.relative_to(share))
               for src in sorted(p for p in share.rglob("*") if p.is_file())] if share.is_dir() else []
    for path in (place.db, *(dst for _src, dst in targets)):
        remove_leftover(path)  # a crash between a write and its rename leaves `<name>.dj-new` behind
    replace_bytes(place.db, (b.folder / "master.db").read_bytes())
    for src, dst in targets:
        dst.parent.mkdir(parents=True, exist_ok=True)
        replace_bytes(dst, src.read_bytes())
    return RestoreResult(saved.id, _missing_after(saved.folder / "master.db", place.db) or [])


def _paths_of(db: Path, running: bool = False) -> dict[str, str] | None:
    """{track id: file path} of the tracks `db` holds; None when `db` can't be read (no key fits, or a query fails).
    `running`: rekordbox runs now, so a library with `-wal` and `-shm` is opened shared, not immutable."""
    immutable = master.immutable_for(db, running)
    for key in master.KEYS:
        try:
            con = master.connect(db, key, immutable=immutable)
        except master.sqlcipher3.DatabaseError:
            continue
        try:
            return {str(i): str(p) for i, p in con.execute(
                "SELECT ID, FolderPath FROM djmdContent WHERE IFNULL(rb_local_deleted, 0) = 0 "
                "AND IFNULL(FileType, 0) <> ? AND FolderPath IS NOT NULL", (master.STREAMING,))}
        except master.sqlcipher3.DatabaseError:
            return None
        finally:
            con.close()
    return None


def _missing_after(saved: Path, restored: Path, running: bool = False) -> list[dict] | None:
    """The tracks whose path the restore changed and whose restored path names no file; None when either library
    can't be read. `running`: rekordbox runs now (it applies to a library with `-wal` and `-shm` beside it)."""
    before, after = _paths_of(saved, running), _paths_of(restored, running)
    if before is None or after is None:
        return None
    return [{"id": i, "path": p, "was": before[i]} for i, p in sorted(after.items())
            if i in before and before[i] != p and not os.path.exists(p)]
