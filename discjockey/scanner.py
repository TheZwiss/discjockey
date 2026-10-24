"""Walks the watched folders and sorts every audio file against the index (spec library-and-sources
§6.1, §6.3, §6.4). Reads only; returns a ScanResult that db.apply_scan writes.

Works on plain data: the watched folders and the index's file rows come in, a ScanResult goes out, no SQL here.
A file whose path, size and mtime match its row is not read (one `lstat` per file). A folder that can't be seen is
offline and its rows appear in no list; a subfolder that can't be listed or a file that can't be read leaves its
rows as they are, and a row that would be gone is held instead when its file could be in a place the walk
couldn't read (spec §12). So nothing is ever reported gone because something couldn't be read.
"""
from __future__ import annotations

import os
import stat
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .content_key import AUDIO_EXTS, content_key
from .models import KnownFile, ScanResult, SeenFile, WatchedFolder
from .names import fold


def scan(folders: list[WatchedFolder], known: list[KnownFile], *, exclude: list[Path],
         snapshot_path: Callable[[int, str], str], key_of: Callable[[Path], str] = content_key,
         mounted: Callable[[Path], bool] = os.path.ismount) -> ScanResult:
    """Sort every audio file of `folders` against `known`. `exclude` are folders never walked (the music folder's
    `Superseded/`, `Upgrades ready/`, `.discjockey/`); `snapshot_path(folder_id, rel)` names an ambiguous row's
    candidates as views and reports show them; `key_of` and `mounted` are replaceable for tests."""
    excluded = {_fkey(p) for p in exclude}
    tops = _tops(folders, excluded)
    rows_at: dict[tuple[int, str], KnownFile] = {}
    for row in known:
        if row.folder in tops:
            top, prefix = tops[row.folder]
            rows_at[(top.id, prefix + row.rel)] = row

    result = ScanResult()
    sorting = _Sorting()
    for top in folders:
        if tops[top.id][0] is not top:
            continue  # scanned as part of the folder it sits in
        members = [top] + [f for f in folders if f is not top and tops[f.id][0] is top]
        rows = {rel: row for (tid, rel), row in rows_at.items() if tid == top.id}
        if _offline(top.path, mounted):
            _go_offline(result, sorting, members, rows.values())
            continue
        walked = _walk(top.path, excluded)
        if walked.failed:
            _go_offline(result, sorting, members, rows.values())
            continue
        local = _sort_folder(top, rows, walked, key_of)
        if _offline(top.path, mounted):  # it went away while it was read
            _go_offline(result, sorting, members, rows.values())
            continue
        for member in members[1:]:
            if _offline(member.path, mounted):  # an inner watched folder that isn't there is offline, not gone
                prefix = tops[member.id][1]
                # its files: rows of the inner folder and rows a scan recorded under the outer one
                gone_inner = [row for rel, row in rows.items() if rel.startswith(prefix)]
                _go_offline(result, sorting, [member], gone_inner)
                local.drop(prefix, {row.id for row in gone_inner})
        sorting.add(local)

    _reconcile(result, sorting, snapshot_path)
    return result


# --- which folders are walked -------------------------------------------------------------------------------------

def _fkey(p: Path | str) -> str:
    return fold(os.path.normpath(str(p)))


def _skipped_dir(path: Path, excluded: set[str]) -> bool:
    return path.name.startswith(".") or _fkey(path) in excluded


def _tops(folders: list[WatchedFolder], excluded: set[str]) -> dict[int, tuple[WatchedFolder, str]]:
    """Folder id -> (the folder it is scanned as part of, the rel prefix of its files there). A folder inside
    another is scanned as the outer one, unless the outer one's walk would skip it (hidden or excluded)."""
    out: dict[int, tuple[WatchedFolder, str]] = {}
    for f in folders:
        best: WatchedFolder | None = None
        for o in folders:
            if o is f or o.path == f.path or not f.path.is_relative_to(o.path):
                continue
            inside = f.path.relative_to(o.path)
            walked = all(not _skipped_dir(o.path.joinpath(*inside.parts[:i + 1]), excluded)
                         for i in range(len(inside.parts)))
            if walked and (best is None or len(o.path.parts) < len(best.path.parts)):
                best = o
        if best is None:
            out[f.id] = (f, "")
        else:
            out[f.id] = (best, _nfc(f.path.relative_to(best.path).as_posix()) + "/")
    return out


def _offline(path: Path, mounted: Callable[[Path], bool]) -> bool:
    parts = path.parts
    if len(parts) >= 3 and parts[0] == "/" and parts[1] == "Volumes" and not mounted(Path("/Volumes", parts[2])):
        return True
    return not path.is_dir()


# --- walking one folder -------------------------------------------------------------------------------------------

def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _reason(e: OSError) -> str:
    return e.strerror or type(e).__name__


@dataclass
class _Walked:
    files: list[tuple[str, Path, os.stat_result]] = field(default_factory=list)  # rel, path on disk, lstat
    unlisted: list[str] = field(default_factory=list)  # rels of subfolders that couldn't be listed
    unreadable: list[tuple[str, str]] = field(default_factory=list)  # rel, reason
    failed: bool = False  # the folder itself couldn't be listed


def _walk(top: Path, excluded: set[str]) -> _Walked:
    out = _Walked()
    errors: list[OSError] = []
    base = str(top)
    for dirpath, dirnames, filenames in os.walk(base, onerror=errors.append):  # never follows linked folders
        dirnames[:] = sorted(d for d in dirnames if not _skipped_dir(Path(dirpath, d), excluded))
        for name in sorted(filenames):
            if name.startswith(".") or os.path.splitext(name)[1].lower() not in AUDIO_EXTS:
                continue
            path = Path(dirpath, name)
            rel = _nfc(path.relative_to(base).as_posix())
            try:
                st = os.lstat(path)
            except FileNotFoundError:
                continue  # removed since the folder was listed
            except OSError as e:
                out.unreadable.append((rel, _reason(e)))
                continue
            if stat.S_ISREG(st.st_mode):  # a linked file can point outside the folder: skipped
                out.files.append((rel, path, st))
    for e in errors:
        if e.filename is None or os.path.normpath(os.fsdecode(e.filename)) == os.path.normpath(base):
            out.failed = True
        else:
            out.unlisted.append(_nfc(Path(os.fsdecode(e.filename)).relative_to(base).as_posix()))
    return out


@dataclass
class _Sorting:
    """What the folders' walks found, before files are matched across folders."""
    unchanged: list[int] = field(default_factory=list)  # row ids
    retagged: list[tuple[int, SeenFile]] = field(default_factory=list)
    replaced: list[tuple[int, SeenFile]] = field(default_factory=list)
    unreadable: list[tuple[int, str, str]] = field(default_factory=list)
    present: list[tuple[KnownFile, SeenFile]] = field(default_factory=list)  # rows whose file is at its path
    kept: list[KnownFile] = field(default_factory=list)  # rows left as they are (offline, unlisted, unreadable)
    hold_if_gone: set[int] = field(default_factory=set)  # missing rows of a folder whose walk couldn't see it all
    unreadable_sizes: set[int] = field(default_factory=set)  # sizes of files that couldn't be read (lstat worked)
    missing: list[KnownFile] = field(default_factory=list)  # rows whose path is gone
    new: list[SeenFile] = field(default_factory=list)  # files no row has at their path

    def add(self, other: _Sorting) -> None:
        self.hold_if_gone |= other.hold_if_gone
        self.unreadable_sizes |= other.unreadable_sizes
        for name in ("unchanged", "retagged", "replaced", "unreadable", "present", "kept", "missing", "new"):
            getattr(self, name).extend(getattr(other, name))

    def drop(self, prefix: str, row_ids: set[int]) -> None:
        """Forget what was found under `prefix` (an inner folder that went offline) and those rows."""
        def under(rel: str) -> bool:
            return rel.startswith(prefix)
        self.unchanged = [i for i in self.unchanged if i not in row_ids]
        self.retagged = [(i, s) for i, s in self.retagged if i not in row_ids]
        self.replaced = [(i, s) for i, s in self.replaced if i not in row_ids]
        self.present = [(row, s) for row, s in self.present if row.id not in row_ids]
        self.unreadable = [u for u in self.unreadable if not under(u[1])]
        self.kept = [row for row in self.kept if row.id not in row_ids]
        self.missing = [row for row in self.missing if row.id not in row_ids]
        self.hold_if_gone -= row_ids
        self.new = [s for s in self.new if not under(s.rel)]


def _sort_folder(top: WatchedFolder, rows: dict[str, KnownFile], walked: _Walked,
                 key_of: Callable[[Path], str]) -> _Sorting:
    out = _Sorting()
    seen: set[str] = set()
    for rel, reason in walked.unreadable:
        seen.add(rel)
        out.unreadable.append((top.id, rel, reason))
        if rel in rows:
            out.kept.append(rows[rel])
    for rel, path, st in walked.files:
        seen.add(rel)
        row = rows.get(rel)
        if (row is not None and row.content_key is not None and row.size == st.st_size
                and row.mtime_ns == st.st_mtime_ns):
            found = SeenFile(top.id, rel, st.st_size, st.st_mtime_ns, row.content_key)
            out.present.append((row, found))
            if row.ambiguous:  # back at its own path: written so its candidates are cleared
                out.retagged.append((row.id, found))
            else:
                out.unchanged.append(row.id)
            continue
        try:
            key = key_of(path)
        except OSError as e:
            out.unreadable.append((top.id, rel, _reason(e)))
            out.unreadable_sizes.add(st.st_size)
            if row is not None:
                out.kept.append(row)
            continue
        found = SeenFile(top.id, rel, st.st_size, st.st_mtime_ns, key)
        if row is None:
            out.new.append(found)
        elif row.content_key is None or row.content_key == key:  # None: a migrated file back at its path
            out.present.append((row, found))
            out.retagged.append((row.id, found))
        else:
            out.present.append((row, found))
            out.replaced.append((row.id, found))
    for rel, row in rows.items():
        if rel in seen:
            continue
        if any(rel.startswith(p + "/") for p in walked.unlisted):
            out.kept.append(row)  # its subfolder couldn't be listed: treated as unchanged, never gone
            out.unchanged.append(row.id)
        else:
            out.missing.append(row)
    if walked.unlisted or walked.unreadable:  # a moved file may be where the walk couldn't look
        out.hold_if_gone.update(row.id for row in out.missing)
    return out


def _go_offline(result: ScanResult, sorting: _Sorting, folders: list[WatchedFolder], rows) -> None:
    result.offline.extend(f.id for f in folders)
    sorting.kept.extend(rows)


# --- matching across folders (§6.3) -------------------------------------------------------------------------------

def _name(rel: str) -> str:
    return fold(PurePosixPath(rel).name)


def _reconcile(result: ScanResult, s: _Sorting, snapshot_path: Callable[[int, str], str]) -> None:
    result.unchanged = len(s.unchanged)
    result.retagged = s.retagged
    result.replaced = s.replaced
    result.unreadable = s.unreadable

    still_there = {found.content_key for _, found in s.present}
    still_there.update(row.content_key for row in s.kept if row.content_key is not None)

    new_by_key: dict[str, list[SeenFile]] = {}
    new_by_name: dict[str, list[SeenFile]] = {}
    for f in s.new:
        new_by_key.setdefault(f.content_key, []).append(f)
        new_by_name.setdefault(_name(f.rel), []).append(f)
    # Files a scan already indexed (unlinked rows) are candidates too for a song's missing file: an ambiguous row's
    # were indexed by the scan that found them, and a copy indexed while the original was still there is where the
    # song's file is once the original goes (a copy made before deleting it, or a file put back from the Trash).
    indexed_by_key: dict[str, list[tuple[int, SeenFile]]] = {}
    indexed_by_name: dict[str, list[tuple[int, SeenFile]]] = {}
    for row, found in s.present:
        if not row.linked:
            indexed_by_key.setdefault(found.content_key, []).append((row.id, found))
            indexed_by_name.setdefault(_name(found.rel), []).append((row.id, found))

    used: set[tuple[int, str]] = set()  # (folder, rel) of every moved target

    def decide(row: KnownFile, new: list[SeenFile], indexed: list[tuple[int, SeenFile]]) -> None:
        candidates = list(new)
        # by key only (a name is no proof it's the same audio); an unlinked row that is gone is nobody's file
        if row.ambiguous or (row.linked and row.content_key is not None):
            candidates += [found for rid, found in indexed if rid != row.id]
        candidates = [c for c in candidates if (c.folder, c.rel) not in used]
        if len(candidates) == 1:
            target = candidates[0]
            used.add((target.folder, target.rel))
            still_there.add(target.content_key)
            result.moved.append((row.id, target))
        elif candidates:
            result.ambiguous.append((row.id, sorted(snapshot_path(c.folder, c.rel) for c in candidates)))
        elif row.id in s.hold_if_gone or (row.size is not None and row.size in s.unreadable_sizes):
            result.held.append(row.id)  # could be the file that couldn't be read: decided on a later scan
        else:
            result.gone.append(row.id)

    order = sorted(s.missing, key=lambda row: (not row.linked, row.id))  # a song's file wins a shared target
    for row in order:  # by content key
        if row.content_key is not None:
            decide(row, new_by_key.get(row.content_key, []), indexed_by_key.get(row.content_key, []))
    for row in order:  # a migrated row without a key: by file name (today's rule-3 search, once)
        if row.content_key is None:
            decide(row, new_by_name.get(_name(row.rel), []), indexed_by_name.get(_name(row.rel), []))

    for f in s.new:
        if (f.folder, f.rel) in used:
            continue
        (result.copies if f.content_key in still_there else result.new).append(f)
