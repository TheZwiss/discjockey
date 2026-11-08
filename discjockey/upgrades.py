"""Parked upgrades: what the user can do with a better version an upgrade check found (spec "Upgrades"): a lossless
one, or a clearly better ~256 kbps stream of a lossy file (spec §4).

Front-end independent: `discjockey upgrades` (console) and the hub's "Upgrade ready" group use it.
Callers hold the run lock and have recovered pending operations first. Every action re-checks its
precondition and returns one events.Result; problems the user should read raise UpgradeProblem.

New track (`add_new`) lines the new file up with rekordbox's timeline of the old one when it can (design
rekordbox-repoint §3.1, §7.2; plan stage A §1.9): for the same edit, measured again now (`L`), and a known offset `d`
of rekordbox's timeline for the old file (`rekordbox.timeline_offset`), it renders the download shifted by
`k = L − d` (`audio.render_aiff`), so rekordbox's cues and grid of the old track fit the new file to the sample; the
parked download is kept for the undo, as a swap's is. `k == 0` keeps the download as it is (a rename). A different or
unknown edit, or an unknown `d`, is renamed as before and its check says so (`aligned: false`).

Undo: Swap and Add as new file leave a rekordbox check whose `undo` record (library.upgrade_undo) says how to put
everything back: the fields the step changed as they were (`before`, the parked upgrade included), where the new and
the old file are now (`file`, `old`) with their content keys (`file_key`, `old_key`), and for a swap or a rendered
New track (`rendered: true`) the kept parked download (`held`, in .discjockey/undo/). `undo` puts it all back while
the check stands (a render goes into .discjockey/undo/, cleaned up later: its audio is the download's); "Done,
checked in rekordbox" ends it (library.forget_undo). It is refused when either file changed since the step.
"""
from __future__ import annotations

import hashlib
import itertools
import os
import shutil
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable

from . import align, rekordbox
from .align import Alignment
from .audio import ConversionError, copy_tags, render_aiff
from .content_key import content_key
from .events import Result
from .library import (
    NameReserver, Paths, deferred_interrupt, delete_parked, end_op, forget_undo, fsync_dir, full_fsync, journal_op,
    mark_op, op_paths, run_op, safe_rename, save_state, upgrade_undo, watched_root,
)
from .models import SOURCE_NAMES
from .names import expected_stem, fold, split_name, strip_id_suffix
from .planner import declined, own_key, replacement_dir, superseded_dir

Compare = Callable[..., Alignment]  # (current file, new file) -> Alignment
Offset = Callable[[Path], rekordbox.TimelineOffset]  # (old file) -> where rekordbox's timeline sits for it
SWAP_EXTS = (".aiff", ".aif")  # the new audio is AIFF; a WAV file cannot take it under its own name
CHUNK = 1 << 20


class UpgradeProblem(Exception):
    """An action could not be done; the message is for the user. `forgotten`: the parked file was gone, so the
    record was cleared (the only change)."""

    def __init__(self, message: str, forgotten: bool = False):
        super().__init__(message)
        self.forgotten = forgotten


def upgrade_name(upgrade: dict) -> str:
    """"lossless version", or "256 kbps version" for a better lossy stream from an account (spec §4)."""
    if upgrade.get("status", "lossless") == "lossless":
        return "lossless version"
    return f"{upgrade.get('kbps') or '?'} kbps version"


def ready(state: dict, folder_order: list[str]) -> list[tuple[str, dict]]:
    """Every parked upgrade, in playlists.txt folder order (folders not listed there last), then artist and title."""
    rank = {fold(f): i for i, f in enumerate(folder_order)}
    items = [(k, e) for k, e in state["tracks"].items() if e.get("upgrade")]
    return sorted(items, key=lambda kv: (rank.get(fold(kv[1]["folder"]), len(rank)), fold(kv[1]["folder"]),
                                         kv[1]["artist"].casefold(), kv[1]["title"].casefold()))


def current_on_disk(paths: Paths, entry: dict) -> bool:
    return bool(entry.get("path")) and (paths.root / entry["path"]).is_file()


def drop_parked(paths: Paths, entry: dict) -> dict:
    """Stale cleanup: deletes the parked file (if still there) and returns the entry without its upgrade."""
    delete_parked(paths, (entry.get("upgrade") or {}).get("file"))
    return {**entry, "upgrade": None}


def _same(a: dict | None, b: dict | None) -> bool:
    keys = ("file", "source", "source_id")
    return bool(a and b) and all(a.get(k) == b.get(k) for k in keys)


def precondition(paths: Paths, state: dict, track_id: str, upgrade: dict, *, need_current: bool) -> dict:
    """The entry, if `upgrade` can still be acted on. A parked file that is gone clears the record."""
    e = state["tracks"].get(track_id)
    if e is None or not _same(e.get("upgrade"), upgrade):
        raise UpgradeProblem(f"This {upgrade_name(upgrade)} has changed since it was shown, so nothing was done.")
    if not (paths.root / upgrade["file"]).is_file():
        state["tracks"][track_id] = drop_parked(paths, e)
        save_state(paths, state)
        raise UpgradeProblem(f"The {upgrade_name(upgrade)} is no longer in {upgrade['file']} (deleted by hand?), so "
                             "Discjockey has forgotten it. A later check can find it again.", forgotten=True)
    if need_current and not current_on_disk(paths, e):
        raise UpgradeProblem("Your current file is not where Discjockey expects it. Run a sync first, so it can "
                             "find the file again.")
    return e


def check(paths: Paths, state: dict, track_id: str, compare: Compare = align.compare_files) -> Alignment:
    """Precondition plus a fresh measurement of how the two versions line up."""
    e = state["tracks"].get(track_id) or {}
    if not e.get("upgrade"):
        raise UpgradeProblem("No better version is waiting for this track.")
    precondition(paths, state, track_id, e["upgrade"], need_current=True)
    return compare(paths.root / e["path"], paths.root / e["upgrade"]["file"])


def upgraded_entry(entry: dict, upgrade: dict, path: str) -> dict:
    status = upgrade.get("status", "lossless")
    lossless = status == "lossless"
    return {**entry, "status": status, "source": upgrade["source"], "source_id": upgrade["source_id"],
            "source_format": upgrade["source_format"], "cutoff_hz": None if lossless else upgrade.get("cutoff_hz"),
            "source_kbps": None if lossless else upgrade.get("kbps"), "source_how": upgrade.get("how"),
            "path": path, "upgrade": None}


def _result(section: str, track_id: str, e: dict, note: str, **fields) -> Result:
    return Result(section, e["folder"], e["artist"], e["title"], track_id, note, **fields)


UNDO_FIELDS = ("status", "source", "source_id", "source_format", "cutoff_hz", "source_kbps", "source_how", "path",
               "upgrade", "rekordbox_check")


def fields_before(e: dict) -> dict:
    """The fields an upgrade changes, as they were: its undo puts them back. A check that stood before keeps its
    words but not its own undo: one step back only (its kept copy goes at the next clean-up, library._prune_undo)."""
    b = {k: e.get(k) for k in UNDO_FIELDS}
    if b["rekordbox_check"]:
        b["rekordbox_check"] = {k: v for k, v in b["rekordbox_check"].items() if k != "undo"}
    return b


def undo_keys(paths: Paths, new: str, old: str) -> dict | None:
    """The content keys of the two files an undo checks, or None (no undo) if one can't be read."""
    try:
        return {"file": new, "file_key": content_key(paths.root / new), "old": old,
                "old_key": content_key(paths.root / old)}
    except OSError:
        return None


def add_new(paths: Paths, state: dict, track_id: str, upgrade: dict, compare: Compare = align.compare_files,
            offset: Offset | None = None, now: Callable[[], datetime] = datetime.now) -> Result:
    """The new file takes the correct name in the current file's folder (`<folder>/<Artist - Title>.aiff`, ID suffix
    only if another file has it; a playlist folder's root unless it stays lossy, spec §7: `replacement_dir`); the
    current file moves to Superseded/ (mirroring its folder) first, so the new one can also take the name the old one
    had. One pending operation (run_op). rekordbox gets a new file; the user relocates the old track to it.

    The two files are measured again now (`compare`). For the same edit with a known offset of rekordbox's timeline
    (`offset`, default rekordbox.timeline_offset), the new file is the parked download rendered shifted by
    `k = L − d`, so the old track's cues fit to the sample, and the download is kept in .discjockey/undo/ (renames:
    old → Superseded/, render → the new name, download → kept); `k == 0` renames the download itself. Otherwise the
    download is renamed as it is. The check (added_as_new) keeps the measurement (`match`, `offset_ms`; the parked
    one when it can't be measured now) and whether the new file is lined up (`aligned`). A failure before the files
    move leaves nothing behind (UpgradeProblem)."""
    e = precondition(paths, state, track_id, upgrade, need_current=True)
    names = NameReserver(paths.root, state)
    stem, ext = split_name(strip_id_suffix(PurePosixPath(e["path"]).name, track_id))
    old = names.choose(superseded_dir(e["path"], watched_root(paths, e["path"])), stem, ext, track_id)
    status = upgrade.get("status", "lossless")
    folder = replacement_dir(e, status)  # a 256 kbps version stays in a playlist folder's not_lossless/
    target = f"{folder}/{expected_stem(e['artist'], e['title'])}.aiff"
    if fold(e["path"]) == fold(target):  # the old file has the name: it moves away (first rename), then the new one
        new = target
    else:
        new = names.choose(folder, expected_stem(e["artist"], e["title"]), ".aiff", track_id)
    alignment = compare(paths.root / e["path"], paths.root / upgrade["file"])
    measured = alignment.to_dict() if alignment.result != "unknown" else (upgrade.get("alignment") or {})
    shift = _lined_up_shift(paths.root / e["path"], alignment, offset)
    check = {"reason": "added_as_new", "since": now().date().isoformat(), "match": measured.get("result") or "unknown",
             "offset_ms": measured.get("offset_ms") or 0.0, "aligned": shift is not None}
    if not shift:  # nothing to render: the download itself becomes the new file
        keys = undo_keys(paths, upgrade["file"], e["path"])  # read before the move; the move keeps the content
        if keys is not None:
            check["undo"] = {"kind": "add_new", "before": fields_before(e), **keys, "file": new, "old": old}
        entry = {**upgraded_entry(e, upgrade, new), "rekordbox_check": check}
        run_op(paths, state, track_id, [(e["path"], old), (upgrade["file"], new)], entry)
        return _result("added_new", track_id, e, f"new file {new}; the old one moved to {old}", status=status,
                       source=upgrade["source"], path=new)

    workdir = paths.tmp / track_id
    staged = workdir / "new.aiff"
    try:
        workdir.mkdir(parents=True, exist_ok=True)
        build_staged(paths.root / upgrade["file"], staged, shift)
        rendered = staged.relative_to(paths.root).as_posix()
        keys = undo_keys(paths, rendered, e["path"])
        held = held_place(paths, track_id, upgrade["file"])
    except BaseException as err:
        shutil.rmtree(workdir, ignore_errors=True)
        if not isinstance(err, Exception):  # Ctrl-C: nothing was changed
            raise
        detail = str(err) if isinstance(err, UpgradeProblem) else f"Could not prepare the new version ({err})"
        raise UpgradeProblem(f"{detail.rstrip('. ')}. Nothing was changed; the {upgrade_name(upgrade)} is still "
                             "waiting.") from err
    if keys is not None:
        check["undo"] = {"kind": "add_new", "before": fields_before(e), **keys, "file": new, "old": old, "held": held,
                         "rendered": True}
    entry = {**upgraded_entry(e, upgrade, new), "rekordbox_check": check}
    try:
        run_op(paths, state, track_id, [(e["path"], old), (rendered, new), (upgrade["file"], held)], entry)
    except BaseException:
        if not any(fold(p) == fold(rendered) for op in state.get("pending", []) for p in op_paths(op)):
            shutil.rmtree(workdir, ignore_errors=True)  # the step was dropped: the render is nobody's
        raise
    shutil.rmtree(workdir, ignore_errors=True)
    if keys is None:  # no undo (a file couldn't be read): the kept download has no use
        forget_undo(paths, {"held": held})
    return _result("added_new", track_id, e, f"new file {new}, lined up with the old one; the old one moved to {old}",
                   status=status, source=upgrade["source"], path=new)


def _lined_up_shift(old_file: Path, alignment: Alignment, offset: Offset | None) -> int | None:
    """The shift (44.1 kHz samples) that lines the new file up with rekordbox's timeline of `old_file`: `L − d`; None
    when the files aren't the same edit or `d` is unknown (rekordbox can't tell, or anything in that look fails: New
    track never refuses, plan §0.4)."""
    if not alignment.swap_safe:
        return None
    try:
        d = (offset or rekordbox.timeline_offset)(old_file).samples
    except Exception:  # whatever goes wrong in the look at rekordbox (ffmpeg, its library): New track still renames
        return None
    return None if d is None else alignment.offset_samples - d


def discard(paths: Paths, state: dict, track_id: str, upgrade: dict) -> Result:
    """Never offer this file again; the parked copy is deleted. A ~256 kbps stream of the current file's own upload
    is only declined (declined_streams): rejected_sources means the wrong song, and that is the version kept."""
    e = precondition(paths, state, track_id, upgrade, need_current=False)
    key = f"{upgrade['source']}:{upgrade['source_id']}"
    delete_parked(paths, upgrade["file"])  # first: a crash before saving leaves a record whose file is gone (handled)
    if key == own_key(e):
        state["tracks"][track_id] = {**declined(e, {key}), "upgrade": None}
    else:
        state["tracks"][track_id] = {**e, "rejected_sources": sorted(set(e.get("rejected_sources") or []) | {key}),
                                     "upgrade": None}
    save_state(paths, state)
    name = SOURCE_NAMES.get(upgrade["source"], upgrade["source"])
    return _result("discarded", track_id, e, f"this {name} file won't be offered again", status=e["status"])


# --- Swap: the lossless audio goes into the current file, which keeps its path, name and rekordbox entry ---

def swap_possible(entry: dict) -> bool:
    return PurePosixPath(entry.get("path") or "").suffix.lower() in SWAP_EXTS


def _sha256(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _verified(path: Path, sha256: str) -> bool:
    return path.is_file() and _sha256(path) == sha256


def build_staged(parked: Path, staged: Path, offset_samples: int) -> None:
    """The parked audio shifted to line up (audio.render_aiff: 16-bit/44.1 kHz PCM keeps its samples), with its
    tags. A positive offset trims that many samples at the start, a negative one puts silence in front; 0 copies
    the file as it is."""
    if offset_samples == 0:
        shutil.copyfile(parked, staged)
        return
    try:
        render_aiff(parked, staged, offset_samples)
    except ConversionError as err:
        raise UpgradeProblem(f"Could not prepare the new version: {err}") from None
    copy_tags(parked, staged)


def _copy_synced(src: Path, dst: Path) -> None:
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        shutil.copyfileobj(fin, fout, CHUNK)
        fout.flush()
        full_fsync(fout.fileno())


def _write_in_place(target: Path, source: Path, sha256: str) -> None:
    """Replaces the content of `target` but keeps the file itself (same inode), so rekordbox keeps its entry."""
    with open(source, "rb") as fin, open(target, "r+b") as fout:
        shutil.copyfileobj(fin, fout, CHUNK)
        fout.truncate()
        fout.flush()
        full_fsync(fout.fileno())
    if _sha256(target) != sha256:
        raise OSError(f"{target.name} does not have the expected content after writing")


def _backup_copy(op: dict) -> str:
    return str(PurePosixPath(op["staged"]).with_name("backup.aiff"))


def _back_up(paths: Paths, op: dict) -> None:
    """Step 3: a verified copy of the current file goes to Superseded/ before anything is overwritten.
    Raises (and changes nothing in Library/) if the reserved name was taken meanwhile."""
    copy = paths.root / _backup_copy(op)
    _copy_synced(paths.root / op["target"], copy)
    if _sha256(copy) != op["old_sha256"]:
        raise OSError("the backup copy does not match your file")
    safe_rename(paths.root, _backup_copy(op), op["backup"])
    fsync_dir((paths.root / op["backup"]).parent)  # the backup's new name is on the drive, too


def _back_up_again(paths: Paths, state: dict, op: dict) -> None:
    """Step 3 during recovery. If another file took the reserved name meanwhile, a new name is reserved first."""
    if (paths.root / op["backup"]).exists():
        p = PurePosixPath(op["backup"])
        stem, ext = split_name(strip_id_suffix(p.name, op["track_id"]))
        op["backup"] = NameReserver(paths.root, state).choose(str(p.parent), stem, ext, op["track_id"])
        mark_op(paths, state, op)
    _back_up(paths, op)
    op["backed_up"] = True
    mark_op(paths, state, op)


def _finish(paths: Paths, state: dict, op: dict) -> str:
    """Steps 5 and 6: out of not_lossless/ when the name is free there, entry, clean up. Returns the final path."""
    path = op["target"]
    for src, dst in op["renames"]:
        if (paths.root / dst).exists() and not (paths.root / src).exists():  # done before an interruption
            path = dst
            continue
        try:
            safe_rename(paths.root, src, dst)
            path = dst
        except OSError:  # the name was taken meanwhile: the file stays where it is
            pass
    entry = {**op["entry"], "path": path}
    if "check" in op:  # a swap from before undo existed has neither a check nor a kept copy
        held = hold_parked(paths, op)
        check = {**op["check"], "moved": path != op["target"]}
        keys = undo_keys(paths, path, op["backup"]) if held else None
        if keys is not None:
            check["undo"] = {"kind": "swap", "before": op["before"], **keys, "held": held}
        entry["rekordbox_check"] = check
    else:
        delete_parked(paths, op["parked"])
    shutil.rmtree(paths.root / PurePosixPath(op["staged"]).parent, ignore_errors=True)
    end_op(paths, state, op, {op["track_id"]: entry}, rekeyed=[path])  # the new audio is in it, entry changed or not
    return path


def hold_parked(paths: Paths, op: dict) -> str | None:
    """Step 6: the parked download moves to .discjockey/undo/ (kept for the undo) instead of being deleted.
    Returns where it is, or None (no undo) when it can't be kept there: then it is deleted as before."""
    held = op["held"]
    if (paths.root / held).is_file() and not (paths.root / op["parked"]).exists():  # done before an interruption
        return held
    try:
        safe_rename(paths.root, op["parked"], held)
        return held
    except OSError:
        delete_parked(paths, op["parked"])
        return None


def held_place(paths: Paths, track_id: str, parked: str) -> str:
    """A free place for a swap's kept download: .discjockey/undo/<track>/<its name>, another folder if taken."""
    name = PurePosixPath(parked).name
    for n in itertools.count(1):
        folder = paths.undo / (track_id if n == 1 else f"{track_id}-{n}")
        if not (folder / name).exists():
            return (folder / name).relative_to(paths.root).as_posix()
    raise AssertionError("unreachable")


def _drop(paths: Paths, state: dict, op: dict) -> None:
    """Ends an operation that changed nothing (or was undone); the parked version stays for another try."""
    shutil.rmtree(paths.root / PurePosixPath(op["staged"]).parent, ignore_errors=True)
    end_op(paths, state, op, {}, rekeyed=[op["target"]])  # an undo may have written the old audio back into it


def swap(paths: Paths, state: dict, track_id: str, upgrade: dict, compare: Compare = align.compare_files,
         now: Callable[[], datetime] = datetime.now) -> Result:
    """Swap (spec "Upgrades", steps 1-6). Refused unless the versions line up, measured again now. The entry asks
    for a rekordbox check (swapped: Reload Tag and analyse again; Auto Relocate when the file moved up), which holds
    the undo; the parked download is kept for it."""
    e = precondition(paths, state, track_id, upgrade, need_current=True)
    target = e["path"]
    if not swap_possible(e):
        raise UpgradeProblem(f"A swap only works for AIFF files, and {PurePosixPath(target).name} is not one. "
                             f"Add the {upgrade_name(upgrade)} as a new file instead.")
    alignment = compare(paths.root / target, paths.root / upgrade["file"])
    if not alignment.swap_safe:
        raise UpgradeProblem(f"Not swapped: {alignment.text}. Add the {upgrade_name(upgrade)} as a new file instead, "
                             "or discard it.")
    workdir = paths.tmp / track_id
    workdir.mkdir(parents=True, exist_ok=True)
    staged = workdir / "swap.aiff"
    build_staged(paths.root / upgrade["file"], staged, alignment.offset_samples)  # step 1

    names = NameReserver(paths.root, state)
    p = PurePosixPath(target)
    stem, ext = split_name(strip_id_suffix(p.name, track_id))
    backup = names.choose(superseded_dir(target, watched_root(paths, target)), f"{stem} (lossy)", ext, track_id)
    renames = []
    # out of not_lossless/ only for a file in a playlist folder's not_lossless/ (spec §7); anywhere else it stays
    home = replacement_dir(e, "lossless")
    if (upgrade.get("status", "lossless") == "lossless" and fold(home) != fold(str(p.parent))
            and not names.is_taken(f"{home}/{p.name}")):
        renames = [[target, f"{home}/{p.name}"]]
    op = {"kind": "swap", "track_id": track_id, "target": target,
          "staged": staged.relative_to(paths.root).as_posix(), "backup": backup,
          "old_sha256": _sha256(paths.root / target), "new_sha256": _sha256(staged), "renames": renames,
          "parked": upgrade["file"], "entry": upgraded_entry(e, upgrade, target),
          "held": held_place(paths, track_id, upgrade["file"]), "before": fields_before(e),
          "check": {"reason": "swapped", "since": now().date().isoformat(), "match": alignment.result,
                    "offset_ms": alignment.offset_ms}}
    with deferred_interrupt():  # a Ctrl-C waits until the file is complete again
        journal_op(paths, state, op)  # step 2
        try:
            _back_up(paths, op)  # step 3
        except Exception as err:  # e.g. the name was taken meanwhile: your file was not touched
            _drop(paths, state, op)
            raise UpgradeProblem(f"The swap did not work ({err}). Nothing was changed; the "
                                 f"{upgrade_name(upgrade)} is still waiting.") from err
        op["backed_up"] = True  # from here on, recovery knows that Discjockey may have written to the file
        mark_op(paths, state, op)
        try:
            _write_in_place(paths.root / target, staged, op["new_sha256"])  # step 4
            final = _finish(paths, state, op)  # steps 5 and 6
        except Exception as err:  # e.g. the disk is full: finish or undo right now, not at the next start
            message, _ = recover_swap(paths, state, op, retry=False)
            raise UpgradeProblem(f"The swap did not work ({err}). {message}") from err
    note = f"{alignment.text}; the lossy file is kept as {backup}"
    if final != target:
        note += f"; moved to {final}"
    return _result("swapped", track_id, e, note, status=upgrade.get("status", "lossless"),
                   source=upgrade["source"], path=final)


def _where(paths: Paths, op: dict) -> str | None:
    """Where the swapped file is now: its old place, or the folder root if step 5 already moved it."""
    for rel in [op["target"]] + [dst for _, dst in op["renames"]]:
        if (paths.root / rel).is_file():
            return rel
    return None


def recover_swap(paths: Paths, state: dict, op: dict, retry: bool = True) -> tuple[str, bool]:
    """Finish or undo a swap that was interrupted (spec "Crash safety"). Returns (message, finished).
    retry=False (right after a failure) undoes instead of trying the same steps again. The file is only ever
    written while a backup with its old content (checked by SHA-256) is in Superseded/."""
    e = op.get("entry") or {}
    name = f"{e.get('artist', '?')} - {e.get('title', op['track_id'])}"
    what = upgrade_name({"status": e.get("status", "lossless"), "kbps": e.get("source_kbps")})
    try:
        where = _where(paths, op)
        if where is None:
            _drop(paths, state, op)
            return f"Could not finish an interrupted swap for {name}: {op['target']} is gone.", False
        now = _sha256(paths.root / where)
        backup_ok = _verified(paths.root / op["backup"], op["old_sha256"])
        staged_ok = _verified(paths.root / op["staged"], op["new_sha256"])
        if where != op["target"] and now != op["new_sha256"]:  # the move to the root comes after the write, so
            # this is not the swapped file but someone else's: never write into it
            if op.get("backed_up") and not backup_ok:
                return (f"An interrupted swap for {name} needs your help: {op['target']} is gone and its backup "
                        f"{op['backup']} is missing or changed. Nothing more was changed.", False)
            _drop(paths, state, op)
            return (f"{op['target']} is gone and {where} is another file, so Discjockey left it alone. The swap for "
                    f"{name} was not done; the {what} is still waiting.", False)
        if now == op["new_sha256"]:  # the new audio is in place: only steps 5 and 6 are left
            _finish(paths, state, op)
            if backup_ok:
                return f"Finished an interrupted swap for {name}", True
            return f"Finished an interrupted swap for {name}, but its backup {op['backup']} is missing", False
        if now == op["old_sha256"]:  # your file is as it was
            if retry and staged_ok:
                if not backup_ok:
                    _back_up_again(paths, state, op)
                _write_in_place(paths.root / where, paths.root / op["staged"], op["new_sha256"])
                _finish(paths, state, op)
                return f"Finished an interrupted swap for {name}", True
            _drop(paths, state, op)
            kept = f" (a copy of it is in {op['backup']})" if backup_ok else ""
            return (f"The swap for {name} was not done, and your file is as it was{kept}. The {what} is "
                    "still waiting.", False)
        if not backup_ok:  # the file is neither old nor new, and there is no good backup
            if not op.get("backed_up"):  # Discjockey never wrote to it: someone else changed it
                _drop(paths, state, op)
                return (f"{where} changed while the swap for {name} was waiting (edited by another program?), so "
                        f"Discjockey left it alone. The swap was not done; the {what} is still waiting.", False)
            return (f"An interrupted swap for {name} needs your help: {where} may be damaged and its backup "
                    f"{op['backup']} is missing or changed. Nothing more was changed.", False)
        if retry and staged_ok:
            _write_in_place(paths.root / where, paths.root / op["staged"], op["new_sha256"])
            _finish(paths, state, op)
            return f"Finished an interrupted swap for {name}", True
        _write_in_place(paths.root / where, paths.root / op["backup"], op["old_sha256"])
        _drop(paths, state, op)
        return (f"The swap for {name} was undone: your file is as it was before (a copy stays in "
                f"{op['backup']}). The {what} is still waiting.", False)
    except Exception as err:  # e.g. permissions: keep the operation and try again at the next start
        return f"Could not finish an interrupted swap for {name} yet: {err}", False


# --- Undo: a swap or an added file put back as it was, while its rekordbox check stands ---

NOTHING_TO_UNDO = "There is no upgrade to undo for this track."


def can_undo(entry: dict) -> bool:
    """Pure: whether the entry's rekordbox check holds an undo that may still apply (the track still has the step's
    file and no newer version waits). Whether the files changed is checked only when the undo runs."""
    u = upgrade_undo(entry)
    return bool(u) and entry.get("path") == u.get("file") and not entry.get("upgrade")


class _UndoStuck(Exception):
    """An undo of a swap can't go on; the message is for the user (the step was dropped or waits for help)."""


def _track_name(e: dict, track_id: str) -> str:
    return f"{e.get('artist', '?')} - {e.get('title', track_id)}"


def _unchanged(paths: Paths, rel: str, key: str) -> None:
    """Refuses the undo unless the file at `rel` still has the content key it had right after the step."""
    try:
        now = content_key(paths.root / rel)
    except OSError:
        raise UpgradeProblem(f"{rel} is gone, so the upgrade can't be undone. Nothing was changed.") from None
    if now != key:
        raise UpgradeProblem(f"{rel} changed since the upgrade (edited by another program?), so it can't be undone. "
                             "Nothing was changed.")


def _in_the_way(paths: Paths, state: dict, track_id: str, rel: str, own: str) -> bool:
    """Whether another file (on disk or another track's) holds `rel`; `own` (the track's own file, which moves out
    of the way first) does not count."""
    if fold(rel) == fold(own):
        return False
    if (paths.root / rel).exists():
        return True
    return any(k != track_id and fold(rel) in (fold(x.get("path") or ""), fold((x.get("upgrade") or {}).get("file")
                                                                              or ""))
               for k, x in state["tracks"].items())


def undo(paths: Paths, state: dict, track_id: str) -> Result:
    """Puts a swap or an added file back as it was: the old file at its old path, the entry's fields as they were
    (the parked upgrade waits again, its file back in Upgrades ready/), the new file out of the folder. Refused when
    either file changed since the step, the track's file is another one now, a newer version is waiting, or a file
    is in the way of a place something goes back to. A rendered New track also needs its kept download, which goes
    back to Upgrades ready/; the render goes into .discjockey/undo/. Crash-safe: Add as new goes back through run_op,
    a swap through a pending `swap_undo` step (recover_swap_undo)."""
    e = state["tracks"].get(track_id)
    u = upgrade_undo(e)
    if not u:
        raise UpgradeProblem(NOTHING_TO_UNDO)
    if e.get("path") != u["file"]:
        raise UpgradeProblem("This track has another file now, so the upgrade can't be undone. Nothing was changed.")
    if e.get("upgrade"):
        raise UpgradeProblem("Another better version is waiting for this track now, so the upgrade can't be undone. "
                             "Nothing was changed.")
    before = u["before"]
    parked = before["upgrade"]["file"]
    _unchanged(paths, u["file"], u["file_key"])
    _unchanged(paths, u["old"], u["old_key"])
    if (u["kind"] == "swap" or u.get("rendered")) and not (paths.root / u["held"]).is_file():
        step = "swap" if u["kind"] == "swap" else "upgrade"
        raise UpgradeProblem(f"The copy of the new version Discjockey kept for the undo is gone, so the {step} can't "
                             "be undone. Nothing was changed.")
    for rel in (before["path"], parked):
        if _in_the_way(paths, state, track_id, rel, u["file"]):
            raise UpgradeProblem(f"Another file is at {rel} now, so the upgrade can't be undone. Nothing was changed.")
    entry = {**e, **before}
    what = upgrade_name(before["upgrade"])
    if u["kind"] == "add_new" and u.get("rendered"):
        # the render first (it may have the old file's name) into .discjockey/undo/, where the clean-up takes it
        # (library._prune_undo: its audio is the download's), then the kept download and the old file back
        renames = [(u["file"], held_place(paths, track_id, u["file"])), (u["held"], parked),
                   (u["old"], before["path"])]
        run_op(paths, state, track_id, renames, entry, label=_track_name(e, track_id))
        note = f"the old file is back at {before['path']}; the {what} waits in {parked} again"
    elif u["kind"] == "add_new":
        # the new file first: it may have the old file's name (the old one moved away first in add_new)
        run_op(paths, state, track_id, [(u["file"], parked), (u["old"], before["path"])], entry,
               label=_track_name(e, track_id))
        note = f"the old file is back at {before['path']}; the {what} waits in {parked} again"
    else:
        _undo_swap(paths, state, track_id, u, entry)
        note = f"your old audio is back in {before['path']}; the {what} waits in {parked} again"
    return _result("upgrade_undone", track_id, e, note, status=before["status"], source=before["source"],
                   path=before["path"])


def _undo_swap(paths: Paths, state: dict, track_id: str, u: dict, entry: dict) -> None:
    """The backup's audio goes back into the file (same inode, so rekordbox keeps its entry), the file back to its
    old place, the kept download back to Upgrades ready/, then the entry; the backup, now the same as the file,
    is deleted last. One pending step; the file is only ever written while the backup (checked by SHA-256) is there."""
    before = u["before"]
    op = {"kind": "swap_undo", "track_id": track_id, "target": u["file"], "home": before["path"],
          "backup": u["old"], "held": u["held"], "parked": before["upgrade"]["file"],
          "old_sha256": _sha256(paths.root / u["old"]), "new_sha256": _sha256(paths.root / u["file"]),
          "entry": entry}
    with deferred_interrupt():  # a Ctrl-C waits until the file is complete again
        journal_op(paths, state, op)
        try:
            _finish_undo(paths, state, op)
        except _UndoStuck as stuck:
            raise UpgradeProblem(str(stuck)) from None
        except Exception as err:  # e.g. the disk is full: one more try right now, else at the next start
            message, ok = recover_swap_undo(paths, state, op)
            if not ok:
                raise UpgradeProblem(f"The undo did not work ({err}). {message}") from err


def _finish_undo(paths: Paths, state: dict, op: dict) -> None:
    """Every step of a swap's undo that is still to do; each one sees whether it was done before an interruption."""
    e = op.get("entry") or {}
    name = _track_name(e, op["track_id"])
    where = next((rel for rel in (op["target"], op["home"]) if (paths.root / rel).is_file()), None)
    if where is None:
        end_op(paths, state, op, {})
        raise _UndoStuck(f"Could not undo the swap for {name}: {op['target']} is gone. Nothing more was changed.")
    now = _sha256(paths.root / where)
    if now != op["old_sha256"]:  # not written back yet, or only half
        if not _verified(paths.root / op["backup"], op["old_sha256"]):
            if now == op["new_sha256"]:  # nothing was changed: the swap stays
                end_op(paths, state, op, {})
                raise _UndoStuck(f"The swap for {name} was not undone: its backup {op['backup']} is missing or "
                                 "changed. Nothing was changed.")
            raise _UndoStuck(f"Undoing the swap for {name} needs your help: {where} may be damaged and its backup "
                             f"{op['backup']} is missing or changed. Nothing more was changed.")
        _write_in_place(paths.root / where, paths.root / op["backup"], op["old_sha256"])
    if where != op["home"]:
        safe_rename(paths.root, where, op["home"])
    if (paths.root / op["held"]).is_file():
        safe_rename(paths.root, op["held"], op["parked"])
        try:
            (paths.root / op["held"]).parent.rmdir()
        except OSError:  # not empty
            pass
    (paths.root / op["backup"]).unlink(missing_ok=True)  # its audio is in the file again (checked above)
    end_op(paths, state, op, {op["track_id"]: op["entry"]}, rekeyed=[op["home"]])


def recover_swap_undo(paths: Paths, state: dict, op: dict) -> tuple[str, bool]:
    """Finish an undo of a swap that was interrupted. Returns (message, finished)."""
    name = _track_name(op.get("entry") or {}, op["track_id"])
    try:
        _finish_undo(paths, state, op)
        return f"Finished undoing the swap for {name}", True
    except _UndoStuck as stuck:
        return str(stuck), False
    except Exception as err:  # e.g. permissions: keep the step and try again at the next start
        return f"Could not finish undoing the swap for {name} yet: {err}", False
