"""Parked upgrades: what the user can do with a better version an upgrade check found (spec "Upgrades"): a lossless
one, or a clearly better ~256 kbps stream of a lossy file (spec §4).

Front-end independent: `discjockey upgrades` (console) uses it now, the hub's "Upgrade ready" group later.
Callers hold the run lock and have recovered pending operations first. Every action re-checks its
precondition and returns one events.Result; problems the user should read raise UpgradeProblem.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable

from . import align
from .align import Alignment
from .audio import copy_tags
from .events import Result
from .library import (
    NameReserver, Paths, deferred_interrupt, delete_parked, fsync_dir, full_fsync, run_op, safe_rename, save_state,
)
from .models import SOURCE_NAMES
from .names import expected_stem, fold, split_name, strip_id_suffix
from .planner import declined, folder_dir, own_key

Compare = Callable[..., Alignment]  # (current file, new file) -> Alignment
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
        save_state(paths.state_file, state)
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


def _upgraded(entry: dict, upgrade: dict, path: str) -> dict:
    status = upgrade.get("status", "lossless")
    lossless = status == "lossless"
    return {**entry, "status": status, "source": upgrade["source"], "source_id": upgrade["source_id"],
            "source_format": upgrade["source_format"], "cutoff_hz": None if lossless else upgrade.get("cutoff_hz"),
            "source_kbps": None if lossless else upgrade.get("kbps"), "path": path, "upgrade": None}


def _result(section: str, track_id: str, e: dict, note: str, **fields) -> Result:
    return Result(section, e["folder"], e["artist"], e["title"], track_id, note, **fields)


def add_new(paths: Paths, state: dict, track_id: str, upgrade: dict,
            now: Callable[[], datetime] = datetime.now) -> Result:
    """The parked file takes the correct name in the folder root (`Library/<Folder>/<Artist - Title>.aiff`, ID suffix
    only if another file has it); the current file moves to Superseded/ first, so the new one can also take the name
    the old one had. One pending operation with two renames. rekordbox's Auto Relocate then links the old entry to the
    new file by its name, but its cues fit the old edit: the entry asks for a rekordbox check (added_as_new)."""
    e = precondition(paths, state, track_id, upgrade, need_current=True)
    names = NameReserver(paths.root, state)
    stem, ext = split_name(strip_id_suffix(PurePosixPath(e["path"]).name, track_id))
    old = names.choose(f"Superseded/{e['folder']}", stem, ext, track_id)
    status = upgrade.get("status", "lossless")
    folder = folder_dir(e["folder"], status)  # a 256 kbps version stays in not_lossless/
    target = f"{folder}/{expected_stem(e['artist'], e['title'])}.aiff"
    if fold(e["path"]) == fold(target):  # the old file has the name: it moves away (first rename), then the new one
        new = target
    else:
        new = names.choose(folder, expected_stem(e["artist"], e["title"]), ".aiff", track_id)
    entry = {**_upgraded(e, upgrade, new), "rekordbox_check": {"reason": "added_as_new",
                                                               "since": now().date().isoformat()}}
    run_op(paths, state, track_id, [(e["path"], old), (upgrade["file"], new)], entry)
    return _result("added_new", track_id, e, f"new file {new}; the old one moved to {old}", status=status,
                   source=upgrade["source"], path=new)


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
    save_state(paths.state_file, state)
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
    """The parked audio shifted to line up with the current file (PCM to PCM, no resampling), with its tags.
    A positive offset trims that many samples at the start, a negative one puts silence in front."""
    if offset_samples == 0:
        shutil.copyfile(parked, staged)
        return
    if offset_samples > 0:
        shift = f"atrim=start_sample={offset_samples},asetpts=PTS-STARTPTS"
    else:
        shift = f"adelay=delays={-offset_samples}S:all=1"
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(parked), "-map", "0:a:0", "-map_metadata", "-1",
         "-af", shift, "-c:a", "pcm_s16be", "-f", "aiff", str(staged)],
        capture_output=True, start_new_session=True,
    )
    if r.returncode != 0:
        raise UpgradeProblem("Could not prepare the new version for the swap: "
                             f"{r.stderr.decode(errors='replace').strip()[-300:]}")
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
        save_state(paths.state_file, state)
    _back_up(paths, op)
    op["backed_up"] = True
    save_state(paths.state_file, state)


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
    state["tracks"][op["track_id"]] = {**op["entry"], "path": path}
    delete_parked(paths, op["parked"])
    shutil.rmtree(paths.root / PurePosixPath(op["staged"]).parent, ignore_errors=True)
    state["pending"].remove(op)
    save_state(paths.state_file, state)
    return path


def _drop(paths: Paths, state: dict, op: dict) -> None:
    """Ends an operation that changed nothing (or was undone); the parked version stays for another try."""
    shutil.rmtree(paths.root / PurePosixPath(op["staged"]).parent, ignore_errors=True)
    state["pending"].remove(op)
    save_state(paths.state_file, state)


def swap(paths: Paths, state: dict, track_id: str, upgrade: dict, compare: Compare = align.compare_files) -> Result:
    """Swap (spec "Upgrades", steps 1-6). Refused unless the versions line up, measured again now."""
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
    backup = names.choose(f"Superseded/{e['folder']}", f"{stem} (lossy)", ext, track_id)
    renames = []
    if (upgrade.get("status", "lossless") == "lossless" and fold(p.parent.name) == "not_lossless"
            and not names.is_taken(f"{p.parent.parent}/{p.name}")):
        renames = [[target, f"{p.parent.parent}/{p.name}"]]
    op = {"kind": "swap", "track_id": track_id, "target": target,
          "staged": staged.relative_to(paths.root).as_posix(), "backup": backup,
          "old_sha256": _sha256(paths.root / target), "new_sha256": _sha256(staged), "renames": renames,
          "parked": upgrade["file"], "entry": _upgraded(e, upgrade, target)}
    with deferred_interrupt():  # a Ctrl-C waits until the file is complete again
        state["pending"].append(op)  # step 2
        save_state(paths.state_file, state)
        try:
            _back_up(paths, op)  # step 3
        except Exception as err:  # e.g. the name was taken meanwhile: your file was not touched
            _drop(paths, state, op)
            raise UpgradeProblem(f"The swap did not work ({err}). Nothing was changed; the "
                                 f"{upgrade_name(upgrade)} is still waiting.") from err
        op["backed_up"] = True  # from here on, recovery knows that Discjockey may have written to the file
        save_state(paths.state_file, state)
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
