"""Same track for a file that isn't AIFF, and Convert to AIFF (issue 33; design rekordbox-repoint §3, §4, §5.8; plan
stage B §1.8, §1.9, stage D §1.2): the parked upgrade (`same_track`) or the user's own file itself (`convert_file`)
becomes a new 16-bit/44.1 kHz AIFF with the download's name, lined up with rekordbox's timeline of the old file, and
every rekordbox track of the old file is pointed at it, so cues, playlists and history stay.
What Convert and `rename.py` share (the refusal, the journal entry's rekordbox part, the commit point's side and the
lock) lives in `rbstep.py`; both reach it as `rbstep.name`.

`same_track(paths, state, track_id, upgrade, session=…)` is one track's step (a batch's item, `batches.run`; the
caller holds the library lock and the batch's `rekordbox.Session`). Before anything is written it measures the two
versions again (`compare`: not the same edit → `needs_choice`), asks rekordbox's timeline (`timeline_offset` on the
session's open library: `not_analysed`, `timing`, `cloud`, an unreadable library refuse) and the free space (§1.9:
`space`). Each refusal is `Skipped(reason)` with the design's words and nothing written; rekordbox open (or opened
since the batch began) is `rekordbox.RekordboxOpened`, which stops the batch. Then the journaled op `convert`
(library.db `pending`) runs design §5.8's steps, each marked:

1. render `build_staged(parked, .tmp/<track>/convert.aiff, L − d)` (the download's tags), hash it, plan the rekordbox
   rows (`write.row_change`: the text columns against the old file's tags) and the `PPTH` splices;
2. journal; 3. the batch's backup (`backed_up`, with each analysis file's copy); 4. `move_path(staged → new)`
   (`placed`); 5. `Writer.repoint`, the undo record journaled just before its `COMMIT` (`committed`); 6.
   `move_path(old → Superseded/)` under the old name (`superseded`); 7. the entry (`upgrades.upgraded_entry`), the
   file row (`placed_by = 'app'`), the batch item and the check (`repointed`, its undo record) in one library.db
   transaction, the parked download kept in .discjockey/undo/ (`upgrades.hold_parked`).
`convert_file(paths, state, track_id, *, session=…)` is the same step with the current file as the source
(`op["source"]` is `"file"`, `"upgrade"` for `same_track`): it asks `eligible.convert` with the file's fresh facts and the
session's timeline (nothing to hold: no parked download), renders `render_aiff(old, staged, −d)` (a 16-bit/44.1 kHz
input keeps its samples; the shift is rekordbox's offset only), tags it with `eligible.expected_tags` (the song
record's names, the old file's own comment, genre and year kept; the cover the record's `image_url` or else the old
file's picture, both through `audio.cdj_cover`) and ends with the entry's `path` changed and nothing else (`status`,
`source`, `source_format`, `source_kbps`, `cutoff_hz` stay), a check `reason: "converted"` and the new file's facts
(`files.file_*`, one transaction with the entry). Its name is the clean one, or with the song's ID when the old file
holds that name itself (an AIFF with wrong tags: both files coexist until the commit, so the new one can't take it):
the same call then runs `rename.rename_file` (`_then_rename`), the old file sits in Superseded/ by then, and the file
ends at the clean name; each step is journaled and crash-safe on its own, and the rename keeps the Convert's check and
undo in its `before` (two undos return the original file). The result and the check say "converted": the user's file
kept its name and became an AIFF.
Nothing is held for the undo, which hands nothing back to Upgrades ready/.
A Convert's recovery and undo words say "conversion" where Same track's say "replace" or "upgrade" (`_say`, plan
stage D §3).
No rekordbox track (or no rekordbox at all): steps 3 and 5 are skipped. Every file move goes through `move_path`
(another drive: a staged copy recorded in the op's `crossing`).

**Recovery** (`recover_convert`, from `library.recover_pending`): the commit point is the `master.db` transaction, so a
step with rekordbox rows is decided by the rows' `FolderPath` now: still the old path → rolled back (analysis files
that hold the new bytes come back from the backup, which needs rekordbox closed: until then the step waits, as for a
drive; the placed file goes back to .tmp/ and is dropped); the new path → steps 6 and 7 finished; neither (rekordbox
changed the track since) → rekordbox left alone, the files rolled back, "needs your help". Another rekordbox library
(or none) on this Mac → only the files, by the `committed` mark. A step without rekordbox rows is decided by whether
the new file is in place. The batch the crash interrupted is marked `stopped` (`crash`).

**Undo** (`undo_convert`, from `upgrades.undo`; design §5.9): needs rekordbox closed when the step wrote it and every
track still playing the new file exactly as written (else `upgrades.UndoRefused`, nothing changed); the new file must
be Discjockey's render (SHA-256). The journaled op `convert_undo`: the old file back from Superseded/, rekordbox put
back in one transaction (`Writer.undo_repoint`, the commit point), the new AIFF into .discjockey/undo/ (deleted at the
clean-up), the kept download back to Upgrades ready/, the entry as it was. `recover_convert_undo` decides by the
tracks' `FolderPath` as the step's recovery does: put back → finished; not → rolled back (analysis files the cut-off
write left with the old path get the new one again, waiting for rekordbox to quit).
"""
from __future__ import annotations

import math
import shutil
from collections.abc import Callable, Collection
from contextlib import ExitStack
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path, PurePosixPath

from mutagen.aiff import AIFF

from . import align, audio, library, quality, rbstep, rekordbox
from .events import Result
from .models import FileAudio
from .library import (
    DRIVE_GONE, NameReserver, Paths, Recovered, Waits, deferred_interrupt, drive_away, end_op, file_sha256,
    journal_crossings, journal_op, mark_op, move_path, recover_renames, remove_staged, short_path, waits_offline,
    watched_root, watched_roots,
)
from .names import expected_stem, fold, split_name, strip_id_suffix
from .planner import replacement_dir, superseded_dir
from .rekordbox import eligible, master, process
from .rekordbox import write as rbwrite
from .rekordbox.eligible import Skip
from .rekordbox.lock import Busy
from .rekordbox.session import Session
from .rekordbox.write import RekordboxOpened, WriteRefused
from .rekordbox.offset import TimelineOffset
from .upgrades import (
    COULD_NOT_COMPARE, Compare, UpgradeProblem, build_staged, conversion_words, fields_before, hold_parked,
    held_place, keep_comment, keep_measurement, precondition, swap_possible, undo_keys, upgraded_entry,
)

STAGED_NAME = "convert.aiff"

REKORDBOX_OPEN = ("rekordbox is open. Quit rekordbox, then try again. Discjockey changes your rekordbox tracks only "
                  "while rekordbox is closed.")
KEPT_NOTE = "Kept your own {fields} in rekordbox."
# Recovery (design §5.8, plan §3)
WAIT_REKORDBOX = "Quit rekordbox so Discjockey can finish an interrupted replace for {name}."
NOT_FINISHED = "The replace for {name} was not finished; your file and your rekordbox track are as they were."
FINISHED = "Finished an interrupted replace for {name}."
NEEDS_HELP = ("An interrupted replace for {name} needs your help: your rekordbox track was changed since and points "
              "at neither {old} nor {new}. Discjockey left rekordbox alone; your file stays at {old}.")
OTHER_MAC_DONE = ("Finished an interrupted replace for {name} on this Mac's side. Its rekordbox step was made in "
                  "another rekordbox library than this Mac's: open that one to check the track plays {new}.")
OTHER_MAC_UNDONE = ("The replace for {name} was not finished; your file is as it was. Its rekordbox step was made "
                    "in another rekordbox library than this Mac's: check there that the track plays {old}.")
UNREADABLE_WAIT = ("Couldn't finish an interrupted replace for {name} yet: Discjockey can't read your rekordbox "
                   "library to tell how far it got.")
UNCLEAN_WAIT = ("Couldn't finish an interrupted replace for {name} yet: rekordbox didn't close normally. Open "
                "rekordbox, quit it, and Discjockey finishes the replace.")
FINISHED_MOST = "Finished most of an interrupted replace for {name}, but {problem}."
COULD_NOT_FINISH = "Could not finish an interrupted replace for {name} yet: {err}"
STEP_FAILED = "The replace did not work ({err}). {message}"
STEP_NOT_FINISHED = "The replace did not finish ({err}). {message}"
ANLZ_LOST = (" The analysis files of the track couldn't be put back from the backup; analyse the track again in "
             "rekordbox.")


def _say(op: dict, text: str) -> str:
    """`text` (a Same track's words, design §8) as the journal entry `op`'s step says it: a Convert (`source` "file")
    says "conversion" where Same track says "replace" or "upgrade". Applied to a template, before the names are put in."""
    return conversion_words(text) if op.get("source") == "file" else text


def free_space(path: Path) -> int:
    """Free bytes on the drive of `path` (or of its nearest folder that exists). Tests replace it."""
    while not path.exists() and path.parent != path:
        path = path.parent
    return shutil.disk_usage(path).free


def size_text(n: int) -> str:
    """A size for the user's eyes: "1.2 GB", "35 MB"."""
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{max(1, round(n / 1e6))} MB"


def needed_bytes(duration_s: float, channels: int) -> int:
    """The size of a 16-bit/44.1 kHz AIFF of `duration_s` (plan §1.9)."""
    return math.ceil(duration_s * 44100) * 2 * channels + 4096


def space_places(paths: Paths, new: str) -> list[Path]:
    """The folders whose drives a render that ends at `new` (relative to the music folder) needs room on:
    .discjockey/.tmp's, and once more the new file's when the move crosses drives (`move_path` stages a copy there)."""
    target = (paths.root / new).parent
    places = [paths.tmp]
    if library.device(paths.tmp) != library.device(target):
        places.append(target)
    return places


def space_needed(paths: Paths, source: Path, new: str) -> list[tuple[Path, int]]:
    """Where the render needs room and how much, without decoding: .discjockey/.tmp's drive, and once more the new
    file's drive when the move crosses drives (move_path stages a copy there). One `(a folder on the drive, bytes)`
    per drive; `free_space(folder)` is what the drive has. ffprobe reads `source`, the file the render is made from (the
    parked download, or the file itself for Convert; RuntimeError when it can't)."""
    info = quality.probe(source)
    need = needed_bytes(info.duration_s, info.channels or 2)
    return [(place, need) for place in space_places(paths, new)]


def check_space(paths: Paths, source: Path, new: str) -> None:
    """Room for the render of `source` (`space_needed`). Raises Skipped("space")."""
    for place, need in space_needed(paths, source, new):
        free = free_space(place)
        if free < need:
            raise rbstep.Skipped("space", rbstep.REFUSED["space"].format(size=size_text(need), free=size_text(free)),
                          {"needed": need, "free": free})


def plan_names(paths: Paths, state: dict, track_id: str, e: dict, upgrade: dict) -> tuple[str, str]:
    """The names Same track gives a track whose current file isn't an AIFF, without writing anything: the new AIFF
    (next to the old file or in its playlist folder, `replacement_dir`) and where the old file goes to (Superseded/).
    Both relative to the music folder, free names at this moment (what `same_track` would reserve)."""
    names = NameReserver(paths.root, state)
    old_rel = e["path"]
    new = names.choose(replacement_dir(e, upgrade.get("status", "lossless")), expected_stem(e["artist"], e["title"]),
                       ".aiff", track_id)
    return new, _superseded_name(paths, names, track_id, old_rel)


def plan_file_names(paths: Paths, state: dict, track_id: str, e: dict, names: NameReserver | None = None
                    ) -> tuple[str, str]:
    """The names Convert gives a track's own file, without writing anything: the new AIFF with the clean name (in the
    old file's folder, or its playlist folder by `replacement_dir`; the song's status stays, so a lossy file's AIFF
    stays in `not_lossless/`) and where the old file goes (Superseded/). An old file that holds the clean name itself
    (an AIFF with wrong tags) is taken: the new file gets the song's ID until the old one is gone (plan stage D §1.2)."""
    names = names or NameReserver(paths.root, state)  # a plan over many files shares one, so its names stay apart
    new = names.choose(replacement_dir(e, e.get("status") or "lossless"), expected_stem(e["artist"], e["title"]),
                       ".aiff", track_id)
    return new, _superseded_name(paths, names, track_id, e["path"])


def _superseded_name(paths: Paths, names: NameReserver, track_id: str, old_rel: str) -> str:
    stem, ext = split_name(strip_id_suffix(PurePosixPath(old_rel).name, track_id))
    return names.choose(superseded_dir(old_rel, watched_root(paths, old_rel)), stem, ext, track_id)


# --- the timeline and the plan ---

Judge = Callable[[TimelineOffset, master.Status], eligible.Verdict]  # what an action says about rekordbox's timeline


def _timeline(session: Session, old_file: Path, judge: Judge, *, own_file: bool = False
              ) -> tuple[list[rekordbox.Entry], int]:
    """rekordbox's tracks of the old file and `d` (44.1 kHz samples); `judge` is the action's own rule
    (`eligible.same_track` or `eligible.convert`) applied to what the timeline found; `own_file`: Convert's, so a
    refusal says the words of the user's own file (`rbstep.OWN_FILE_REFUSED`). Raises Skipped, or RekordboxOpened."""
    view = session.view()
    if view is None:
        if session.state.state == "none":
            return [], 0  # no rekordbox on this Mac: d = 0, nothing to repoint (design §3.4)
        if session.state.running:
            raise RekordboxOpened()
        raise rbstep.skipped("rekordbox_unreadable", own_file=own_file)
    try:
        t = rekordbox.timeline_offset(old_file, view=view)
    except Exception as err:  # ffmpeg can't read the old file: a failure of this track, nothing written
        raise UpgradeProblem(f"Discjockey couldn't read your file to line the new one up ({err}). Nothing was "
                             "changed.") from err
    verdict = judge(t, view.status)
    if isinstance(verdict, Skip):
        raise rbstep.skipped(verdict.reason, own_file=own_file) \
            if verdict.reason in rbstep.REFUSED or verdict.reason in rbstep.CONVERT_REFUSED \
            else rbstep.Skipped(verdict.reason, verdict.reason)
    entries = [x.entry for x in t.entries]
    if entries:
        if session.running_at_start or session.rekordbox_opened():
            raise RekordboxOpened()
        if view.status.problem == "unclean":
            raise rbstep.skipped("unclean")
    return entries, t.samples or 0


def _plan_rekordbox(session: Session, entries: list[rekordbox.Entry], old_file: Path, staged: Path, new_abs: str
                    ) -> tuple[list[rbwrite.RowChange], list[rbwrite.AnlzChange]]:
    """The rows to repoint (identity, file facts, text columns against the old file's tags) and the `PPTH` splices."""
    if not entries:
        return [], []
    old_tags = audio.file_facts(old_file).tags
    clean = audio.file_facts(staged).tags
    info = AIFF(str(staged)).info
    frames = round(info.length * info.sample_rate)
    size = staged.stat().st_size
    changes = [rbwrite.row_change(entry, new_abs, file_size=size, channels=info.channels, frames=frames,
                                  old_tags=old_tags, clean=clean) for entry in entries]
    return changes, rbstep.plan_splices(session, entries, new_abs)


# --- the step ---

def same_track(paths: Paths, state: dict, track_id: str, upgrade: dict, *, session: Session,
               compare: Compare = align.compare_files, now: Callable[[], datetime] = datetime.now,
               batch: tuple[int, int] | None = None) -> Result:
    """One track's Same track for a current file that isn't AIFF (see the module docstring). `batch` = (AIFF batch,
    seq): its item is marked done with the step. Raises Skipped (nothing written), RekordboxOpened (nothing written;
    the batch stops) or UpgradeProblem (a failure, nothing written, or the words of what recovery did)."""
    e = precondition(paths, state, track_id, upgrade, need_current=True)
    if swap_possible(e):
        raise UpgradeProblem(f"{PurePosixPath(e['path']).name} is an AIFF file: its audio is swapped in place.")
    old_rel = e["path"]
    old_file, parked = paths.root / old_rel, paths.root / upgrade["file"]
    alignment = compare(old_file, parked)
    if not alignment.swap_safe:
        keep_measurement(paths, state, track_id, e, alignment)
        if alignment.result == "unknown":  # not "a different edit": the files could not be compared at all
            raise rbstep.Skipped("needs_choice", COULD_NOT_COMPARE)
        raise rbstep.skipped("needs_choice", what=alignment.text or alignment.result)
    measured = {**e, "upgrade": {**upgrade, "alignment": alignment.to_dict()}}
    entries, d = _timeline(session, old_file, lambda t, status: eligible.same_track(measured, None, status, t))

    new, superseded = plan_names(paths, state, track_id, e, upgrade)
    try:
        check_space(paths, parked, new)
    except RuntimeError as err:  # ffprobe can't read the download
        raise UpgradeProblem(f"Could not prepare the new version ({err}). Nothing was changed.") from err

    workdir = paths.tmp / track_id
    staged = workdir / STAGED_NAME
    new_abs = rbstep.abs_path(paths, new)
    try:  # step 1: the render and the plan; a failure leaves nothing
        workdir.mkdir(parents=True, exist_ok=True)
        staged.unlink(missing_ok=True)
        build_staged(parked, staged, alignment.offset_samples - d)
        keep_comment(old_file, staged)
        changes, splices = _plan_rekordbox(session, entries, old_file, staged, new_abs)
        op = _op(paths, track_id, e, upgrade, alignment, now, batch, old_rel, new, superseded, staged, session,
                 changes, splices)
    except BaseException as err:
        shutil.rmtree(workdir, ignore_errors=True)
        if not isinstance(err, Exception) or isinstance(err, UpgradeProblem):
            raise
        raise UpgradeProblem(f"Could not prepare the new version ({err}). Nothing was changed; the upgrade is "
                             "still waiting.") from err
    return _execute(paths, state, op, session, entries, changes, splices, e)


def convert_file(paths: Paths, state: dict, track_id: str, *, session: Session,
                 now: Callable[[], datetime] = datetime.now, batch: tuple[int, int] | None = None) -> Result:
    """Convert to AIFF for one track's own file (plan stage D §1.2; the module docstring): the file itself, lined up
    with rekordbox's timeline, becomes a clean 16-bit/44.1 kHz AIFF and every rekordbox track of it is pointed at the
    new file. `batch` = (AIFF batch, seq): its item is marked done with the step. Raises Skipped (nothing written:
    `eligible.convert`'s reasons, the timeline's, `space`), RekordboxOpened (nothing written; the batch stops) or
    UpgradeProblem (a failure, nothing written, or the words of what recovery did)."""
    e = state["tracks"].get(track_id)
    if e is None or not e.get("path"):
        raise UpgradeProblem("This track has no file to convert. Nothing was changed.")
    old_rel = e["path"]
    old_file = paths.root / old_rel
    if not old_file.is_file():
        raise rbstep.skipped("file_missing" if library.online(old_file, watched_roots(paths)) else "away")
    try:
        info = quality.probe(old_file)
        facts = audio.file_facts(old_file)
    except (RuntimeError, OSError) as err:
        raise UpgradeProblem(f"Discjockey couldn't read {PurePosixPath(old_rel).name} ({err}). Nothing was "
                             "changed.") from err
    verdict = eligible.convert(e, facts, session.state, None)
    if isinstance(verdict, Skip):
        if verdict.reason == "rekordbox_unreadable" and session.state.running:
            raise RekordboxOpened()  # the library can't be read while rekordbox holds it: rekordbox open stops the batch
        raise rbstep.skipped(verdict.reason, own_file=True)
    entries, d = _timeline(session, old_file, lambda t, status: eligible.convert(e, facts, status, t), own_file=True)

    new, superseded = plan_file_names(paths, state, track_id, e)
    try:
        check_space(paths, old_file, new)
    except RuntimeError as err:  # ffprobe can't read the file
        raise UpgradeProblem(f"Could not prepare the new file ({err}). Nothing was changed.") from err

    workdir = paths.tmp / track_id
    staged = workdir / STAGED_NAME
    new_abs = rbstep.abs_path(paths, new)
    try:  # step 1: the render, its tags and the plan; a failure leaves nothing
        workdir.mkdir(parents=True, exist_ok=True)
        staged.unlink(missing_ok=True)
        try:
            audio.render_aiff(old_file, staged, -d)  # rekordbox's timeline: k = −d (design §3.1)
        except audio.ConversionError as err:
            raise UpgradeProblem(f"Could not prepare the new file: {err}") from None
        _tag_file(e, old_file, staged, facts)
        changes, splices = _plan_rekordbox(session, entries, old_file, staged, new_abs)
        op = _file_op(paths, track_id, e, now, batch, new, superseded, staged, session, changes, splices,
                      quality.file_audio(info), quality.file_audio(quality.probe(staged)))
    except BaseException as err:
        shutil.rmtree(workdir, ignore_errors=True)
        if not isinstance(err, Exception) or isinstance(err, UpgradeProblem):
            raise
        raise UpgradeProblem(f"Could not prepare the new file ({err}). Nothing was changed.") from err
    result = _execute(paths, state, op, session, entries, changes, splices, e)
    if fold(f"{PurePosixPath(new).parent}/{expected_stem(e['artist'], e['title'])}.aiff") == fold(old_rel):
        return _then_rename(paths, state, track_id, result, session, now, batch)  # the old file held the clean name
    return result


def _then_rename(paths: Paths, state: dict, track_id: str, converted: Result, session: Session,
                 now: Callable[[], datetime], batch: tuple[int, int] | None) -> Result:
    """The second half of a Convert whose old file held the clean name (so the new AIFF took the song's ID, the old
    file went to Superseded/): Give it its clean name, its own journaled and crash-safe step (`rename.rename_file`,
    `after` = the Convert's result: the check it writes keeps the Convert's check and undo in its `before`, so the
    first undo brings the "converted" check back and the second returns the original file). A crash between leaves a
    valid AIFF with the ID name, which Give it its clean name renames later. When the rename can't run now (rekordbox
    opened meanwhile, a refusal), the Convert stands: its result says the file keeps the ID name for now."""
    from . import rename  # rename builds on this module
    try:
        return rename.rename_file(paths, state, track_id, session=session, now=now, batch=batch, after=converted)
    except (UpgradeProblem, RekordboxOpened) as err:
        name = PurePosixPath(converted.path).name
        why = str(err) or "rekordbox was opened meanwhile."
        return replace(converted, note=f"{converted.note}. The file keeps the name {name} for now: {why}")


def _tag_file(e: dict, old_file: Path, staged: Path, facts: audio.FileFacts) -> None:
    """The new file's tags (design §3.5, "from the file itself"): exactly the frames `write_tags` writes for a
    download, from `eligible.expected_tags` (the song record's names, the old file's own comment kept) and the cover
    (the record's, else the old file's picture), plus the genre and year the old file has."""
    expected = eligible.expected_tags(e, facts.tags)
    audio.write_tags(staged, title=expected["title"], artists=(expected["artist"],), album=expected["album"],
                     isrc=expected["isrc"] or None, label=expected["label"] or None, cover=_cover(e, old_file),
                     comment=expected["comment"])
    audio.set_genre_year(staged, *audio.genre_year(old_file))


def _cover(e: dict, old_file: Path) -> bytes | None:
    """The record's picture (a playlist song's `image_url`, fetched as downloads fetch it), else, or when the fetch
    fails, the old file's own; the caller's `write_tags` makes either CDJ-safe."""
    try:
        fetched = audio.fetch_cover(e.get("image_url"))
    except Exception:  # a cover must never fail a batch
        fetched = None
    return fetched or audio.embedded_cover(old_file)


def _execute(paths: Paths, state: dict, op: dict, session: Session, entries: list[rekordbox.Entry],
             changes: list[rbwrite.RowChange], splices: list[rbwrite.AnlzChange], e: dict) -> Result:
    """Steps 2–7 of design §5.8 for the journal entry `op` (the module docstring), the same for both sources: journal,
    backup, place the new file, rekordbox's commit, the old file to Superseded/, the end."""
    track_id, new, old_rel = op["track_id"], op["new"], op["old"]
    roots = watched_roots(paths)
    with deferred_interrupt():  # a Ctrl-C waits until the step is at a safe point
        journal_op(paths, state, op)  # step 2
        rb = op["rekordbox"]
        if rb is not None:  # step 3: the batch's backup holds this track's analysis folders
            try:
                rbstep.backup_tracks(session, track_id, entries, rb)
                op["marks"]["backed_up"] = True
                mark_op(paths, state, op)
            except BaseException as err:
                _drop(paths, state, op)
                rbstep.raise_refusal(err, op)
        try:  # step 4
            move_path(paths.root, op["staged"], new, op["crossing"].get("0"), roots)
        except BaseException as err:
            _drop(paths, state, op)
            if not isinstance(err, Exception):
                raise
            raise UpgradeProblem(f"Could not put the new file in place ({err}). Nothing was changed"
                                 f"{rbstep.WAITING[op.get('source', 'upgrade')]}") from err
        op["marks"]["placed"] = True
        mark_op(paths, state, op)
        if rb is not None:  # step 5: the commit point
            try:
                with session.writer() as w:
                    w.repoint(changes, splices, prepared=lambda c: rbstep.journal_record(paths, state, op, c))
            except (WriteRefused, RekordboxOpened) as err:  # rolled back, analysis files as they were
                _roll_back(paths, state, op, roots)
                rbstep.raise_refusal(err, op)
            except Exception as err:  # decided by the track's path now, as after a crash
                message = _settle(paths, state, op, roots)
                if rbstep.finished_at(state, op, track_id, new):  # it failed after the commit and recovery finished it
                    return _result(track_id, e, op)
                raise UpgradeProblem(_say(op, STEP_FAILED).format(err=err, message=message)) from err
            op["marks"]["committed"] = True
            mark_op(paths, state, op)
        try:  # step 6
            move_path(paths.root, old_rel, op["superseded"], op["crossing"].get("1"), roots)
            op["marks"]["superseded"] = True
            mark_op(paths, state, op)
            result = _finish(paths, state, op)  # step 7
        except Exception as err:  # finish right now if the disk allows, else at the next start
            message = _settle(paths, state, op, roots)
            if rbstep.finished_at(state, op, track_id, new):
                return _result(track_id, e, op)
            raise UpgradeProblem(_say(op, STEP_NOT_FINISHED).format(err=err, message=message)) from err
    return result


def _base_op(paths: Paths, track_id: str, batch: tuple[int, int] | None, old: str, new: str, superseded: str,
             staged: Path, session: Session, changes: list[rbwrite.RowChange],
             splices: list[rbwrite.AnlzChange]) -> dict:
    """What the journal entry of both sources has (plan §1.8): the files, their hashes, the rekordbox rows and analysis
    files; the caller adds `source`, `parked`, `held`, `entry`, `before`, `check` and the marks."""
    staged_rel = staged.relative_to(paths.root).as_posix()
    crossing, size = journal_crossings(paths.root, [(staged_rel, new), (old, superseded)])
    rb = rbstep.op_rekordbox(session, changes, splices)
    return {"kind": "convert", "track_id": track_id, "batch": list(batch) if batch else None,
            "old": old, "new": new, "superseded": superseded, "staged": staged_rel, "crossing": crossing,
            "size": size, "old_sha256": file_sha256(paths.root / old), "new_sha256": file_sha256(staged),
            "rekordbox": rb, "marks": {"backed_up": False, "placed": False, "committed": False, "superseded": False}}


def _op(paths: Paths, track_id: str, e: dict, upgrade: dict, alignment: align.Alignment,
        now: Callable[[], datetime], batch: tuple[int, int] | None, old: str, new: str, superseded: str,
        staged: Path, session: Session, changes: list[rbwrite.RowChange], splices: list[rbwrite.AnlzChange]) -> dict:
    """The journal entry of Same track's step (plan §1.8)."""
    return {**_base_op(paths, track_id, batch, old, new, superseded, staged, session, changes, splices),
            "source": "upgrade", "parked": upgrade["file"], "held": held_place(paths, track_id, upgrade["file"]),
            "entry": upgraded_entry(e, upgrade, new), "before": fields_before(e),
            "check": {"reason": "repointed", "since": now().date().isoformat(), "match": alignment.result,
                      "offset_ms": alignment.offset_ms, "aligned": True, "batch": batch[0] if batch else None}}


def _file_op(paths: Paths, track_id: str, e: dict, now: Callable[[], datetime], batch: tuple[int, int] | None,
             new: str, superseded: str, staged: Path, session: Session, changes: list[rbwrite.RowChange],
             splices: list[rbwrite.AnlzChange], old_audio: FileAudio, new_audio: FileAudio) -> dict:
    """The journal entry of Convert's step (plan stage D §1.2): no parked download (`parked` and `held` None), the song
    entry changes only its path, and the files' facts (`audio` the new file's, `old_audio` the old file's, which its
    undo puts back) are written with the end."""
    return {**_base_op(paths, track_id, batch, e["path"], new, superseded, staged, session, changes, splices),
            "source": "file", "parked": None, "held": None, "entry": rbstep.with_audio({**e, "path": new, "placed_by": "app"}, new_audio),
            "before": fields_before(e), "audio": asdict(new_audio), "old_audio": asdict(old_audio),
            "old_placed_by": e.get("placed_by"),
            "check": {"reason": "converted", "since": now().date().isoformat(), "batch": batch[0] if batch else None}}


def kept_note(kept: list[str]) -> str:
    return KEPT_NOTE.format(fields=" / ".join(rbstep.TEXT_NAMES[f] for f in kept)) if kept else ""


def _result(track_id: str, e: dict, op: dict) -> Result:
    rb = op["rekordbox"]
    note = f"new file {op['new']}, lined up with rekordbox; the old one moved to {op['superseded']}"
    extra = rbstep.NO_TRACK_NOTE if rb is None else kept_note(rb.get("kept") or [])
    if extra:
        note += f". {extra}"
    return Result("converted" if op.get("source") == "file" else "swapped", e["folder"], e["artist"], e["title"],
                  track_id, note, status=op["entry"].get("status"), source=op["entry"].get("source"),
                  path=op["new"])


def _finish(paths: Paths, state: dict, op: dict) -> Result:
    """Step 7: the parked download kept for the undo (Same track; Convert has none), then the entry, its file row (with
    the new file's facts, Convert), the batch item and the check with its undo record, with the end of the journal
    entry."""
    track_id = op["track_id"]
    from_file = op.get("source") == "file"
    held = None if from_file else hold_parked(paths, op)
    keys = undo_keys(paths, op["new"], op["superseded"]) if held or from_file else None
    rb = op["rekordbox"]
    check = {**op["check"], "rekordbox": None if rb is None else {"entries": [r["id"] for r in rb["rows"]],
                                                                   "kept": list(rb.get("kept") or [])}}
    if keys is not None:
        check["undo"] = {"kind": "convert", "source": op["source"], "before": op["before"], **keys, "held": held,
                         "file_sha256": op["new_sha256"], "repoint": None if rb is None else rb.get("record"),
                         "backup": None if rb is None else rb.get("backup"), "audio": op.get("old_audio"),
                         "placed_by": op.get("old_placed_by")}
    entry = {**op["entry"], "rekordbox_check": check}
    before = state["tracks"].get(track_id) or op["entry"]
    result = _result(track_id, before, op)
    item = None
    if op.get("batch"):
        item = (op["batch"][0], op["batch"][1], {"path": op["new"], "note": result.note,
                                                 "rekordbox": check["rekordbox"]})
    shutil.rmtree(paths.root / PurePosixPath(op["staged"]).parent, ignore_errors=True)
    audio = {op["new"]: FileAudio(**op["audio"])} if op.get("audio") else None
    end_op(paths, state, op, {track_id: entry}, rekeyed=[op["new"]], item=item, app_placed=[op["new"]], audio=audio)
    return result


def _drop(paths: Paths, state: dict, op: dict) -> None:
    """Ends a step that changed nothing (or was rolled back); the parked upgrade stays for another try."""
    shutil.rmtree(paths.root / PurePosixPath(op["staged"]).parent, ignore_errors=True)
    end_op(paths, state, op, {})


def _take_back(paths: Paths, op: dict, roots: Collection[Path]) -> None:
    """The placed new file (Discjockey's own render, by its SHA-256) back to .tmp/, where `_drop` removes it; a
    staged copy a move to another drive left beside it goes too. Another file at that name is left alone."""
    new, staged = paths.root / op["new"], paths.root / op["staged"]
    copy = op["crossing"].get("0")
    if copy:
        remove_staged(paths.root / copy)
    if not rbstep.ours(new, op["new_sha256"]):
        return
    if rbstep.ours(staged, op["new_sha256"]):  # a move to another drive that only had the source's removal left
        new.unlink()
        return
    back = library.staging_path(op["staged"]) if library.crosses(paths.root, op["new"], op["staged"]) else None
    move_path(paths.root, op["new"], op["staged"], back, roots)


def _roll_back(paths: Paths, state: dict, op: dict, roots: Collection[Path]) -> None:
    """The files as they were before the step (rekordbox untouched or already rolled back): the step ends."""
    _take_back(paths, op, roots)
    _drop(paths, state, op)


def _settle(paths: Paths, state: dict, op: dict, roots: Collection[Path]) -> str:
    """recover_convert right after a failure in the step, as words (the batch runs on: it is not stopped)."""
    outcome = recover_convert(paths, state, op, roots, crashed=False)
    if isinstance(outcome, Waits):
        return library.waiting(outcome, True)[0]
    return outcome[0]


# --- recovery ---


def _finish_forward(paths: Paths, state: dict, op: dict, roots: Collection[Path]) -> tuple[str, bool] | Waits:
    """Steps 6 and 7 after the commit (or the placement, without rekordbox)."""
    name = rbstep.track_name(op.get("entry") or {}, op["track_id"])
    step = {"renames": [[op["old"], op["superseded"]]], "size": {"0": (op.get("size") or {}).get("1")},
            "staged": {"0": op["crossing"]["1"]} if op["crossing"].get("1") else {}}
    r = recover_renames(paths.root, step, roots)
    if r.wait:
        return Waits(name, r, not waits_offline(op, paths.root, roots))
    _finish(paths, state, op)
    if r.problem and not r.done_any and not (paths.root / op["old"]).exists():
        return _say(op, FINISHED).format(name=name), True  # the old file was gone already (moved by hand)
    if r.problem:
        return _say(op, FINISHED_MOST).format(name=name, problem=r.problem), False
    return _say(op, FINISHED).format(name=name), True


def recover_convert(paths: Paths, state: dict, op: dict, roots: Collection[Path] | None = None, *,
                    crashed: bool = True) -> tuple[str, bool] | Waits:
    """Finishes or rolls back a convert step an earlier run was interrupted in (see the module docstring). Returns
    (message, finished), or a `library.Waits` for a step that stays pending (a drive away, rekordbox open while
    analysis files must come back, a library that can't be read). `crashed`: the step's batch is marked `stopped`
    (False right after a failure inside a running batch)."""
    roots = watched_roots(paths) if roots is None else roots
    name = rbstep.track_name(op.get("entry") or {}, op["track_id"])
    try:
        away = drive_away(op, paths.root, roots)
        if away is not None:
            short = short_path(away)
            return Waits(name, Recovered(DRIVE_GONE.format(path=short), False, True, drive=short),
                          not waits_offline(op, paths.root, roots))
        if crashed:
            rbstep.stop_batch(paths, op)
        side = rbstep.side_of(paths, op)
        if side == "unreadable":
            return Waits(name, Recovered("", False, True), True, _say(op, UNREADABLE_WAIT).format(name=name))
        if side == "unclean":
            return Waits(name, Recovered("", False, True), True, _say(op, UNCLEAN_WAIT).format(name=name))
        rbstep.clear_leftovers(paths, (a["path"] for a in (op["rekordbox"] or {}).get("anlz", [])), not crashed)
        if side == "other":
            if op["marks"].get("committed"):
                outcome = _finish_forward(paths, state, op, roots)
                if isinstance(outcome, Waits) or not outcome[1]:
                    return outcome
                return _say(op, OTHER_MAC_DONE).format(name=name, new=op["new"]), True
            _roll_back(paths, state, op, roots)
            return _say(op, OTHER_MAC_UNDONE).format(name=name, old=op["old"]), False
        if side == "new":
            return _finish_forward(paths, state, op, roots)
        if side == "neither":
            _roll_back(paths, state, op, roots)
            return _say(op, NEEDS_HELP).format(name=name, old=op["old"], new=op["new"]), False
        back, lost = rbstep.anlz_back(op)  # side "old": not committed
        if back and process.running():
            return Waits(name, Recovered("", False, True), True, _say(op, WAIT_REKORDBOX).format(name=name))
        try:
            with rbstep.rekordbox_lock(paths, not crashed or not back):
                for path, copy in back:
                    rbwrite.replace_bytes(path, copy.read_bytes())
        except Busy:
            return Waits(name, Recovered("", False, True), True, rbstep.WAIT_BUSY.format(what=_say(op, "replace"), name=name))
        _roll_back(paths, state, op, roots)
        return _say(op, NOT_FINISHED).format(name=name) + (ANLZ_LOST if lost else ""), False
    except Exception as err:  # e.g. permissions: the step stays and is tried again at the next start
        return _say(op, COULD_NOT_FINISH).format(name=name, err=err), False


# --- undo (design §5.9; plan stage B §1.8) ---

UNDO_FINISHED = "Finished undoing the upgrade for {name}."
UNDO_NOT_FINISHED = ("Undoing the upgrade for {name} was not finished: the upgrade stands as it was, and you can undo "
                     "it again.")
UNDO_NEEDS_HELP = ("An interrupted undo for {name} needs your help: your rekordbox track was changed since and points "
                   "at neither {old} nor {new}. Discjockey left rekordbox alone; the upgrade stands, with your file "
                   "at {new}.")
UNDO_OTHER_MAC_DONE = ("Finished undoing the upgrade for {name} on this Mac's side. Its rekordbox step was made in "
                       "another rekordbox library than this Mac's: open that one to check the track plays {old}.")
UNDO_OTHER_MAC_UNDONE = ("Undoing the upgrade for {name} was not finished: the upgrade stands as it was. Its rekordbox "
                         "step was made in another rekordbox library than this Mac's: check there that the track "
                         "plays {new}.")


def undo_convert(paths: Paths, state: dict, track_id: str, u: dict, entry: dict, *,
                 session: Session | None = None) -> str:
    """Undoes one Same track that made a new AIFF (`u`: the check's undo record, kind `convert`; `entry`: the song
    as it was; `upgrades.undo` checked the rest first). Design §5.9, as the journaled op `convert_undo`:

    A Convert's undo (`u["source"]` is "file") has no kept download to hand back: the old file comes back and the
    new AIFF goes to .discjockey/undo/ (the old file still holds the audio), and the old file's facts go back to its
    row.

    1. decide, nothing changed yet: the new file's audio is still the render's (`upgrades.undo` checked its content
       key: a tag edit, say by rekordbox, doesn't stop an undo), and when the step wrote rekordbox, rekordbox is
       closed (else `UndoRefused("rekordbox_open")`) and every track still plays the new file exactly as written
       (else `relocated`, `cloud`, `other_library`, …);
    2. the old file back from Superseded/ (`restored`);
    3. rekordbox in one transaction (`Writer.undo_repoint`: the path back, the file facts back, each text column
       back where it still holds what the step wrote, `PPTH` back where the file still names the new path),
       `committed`; refused or rolled back there → the old file goes back to Superseded/ and nothing changed;
    4. the new AIFF into .discjockey/undo/ (the clean-up deletes it: its audio is the download's, or the old file's),
       the kept download back to Upgrades ready/, the entry as it was.
    Returns the result's note. `recover_convert_undo` finishes or rolls back a step a crash cut off."""
    from .upgrades import UndoRefused, undo_session, undo_writer, upgrade_name  # upgrades imports this module lazily
    before = u["before"]
    record = u.get("repoint")
    converted = u.get("source") == "file"
    note = f"the old file is back at {before['path']}"
    if before.get("upgrade"):  # Same track: the better version waits again (Convert has none to hand back)
        note += f"; the {upgrade_name(before['upgrade'])} waits in {before['upgrade']['file']} again"
    with ExitStack() as stack:
        rb, rec = None, None
        if record:  # step 1; the read-write connection is closed again before any file moves (it leaves -wal/-shm)
            rb = undo_session(paths, session, stack, converted)
            rec = rbwrite.RepointRecord.from_dict(record)
            with ExitStack() as check:
                try:
                    undo_writer(rb, check, converted).check_undo(rec)
                except WriteRefused as err:
                    raise UndoRefused(err.reason, converted) from None
        op = _undo_op(paths, track_id, u, entry, record)
        roots = watched_roots(paths)
        with deferred_interrupt():  # a Ctrl-C waits until the step is at a safe point
            journal_op(paths, state, op)
            try:  # step 2
                move_path(paths.root, op["superseded"], op["old"], op["crossing"].get("0"), roots)
            except BaseException as err:
                end_op(paths, state, op, {})
                if not isinstance(err, Exception):
                    raise
                raise UpgradeProblem(f"Could not put your old file back ({err}). Nothing was changed.") from err
            op["marks"]["restored"] = True
            mark_op(paths, state, op)
            if rb is not None:  # step 3: the commit point
                try:
                    with ExitStack() as write:
                        writer = undo_writer(rb, write, converted)
                        outcome = writer.undo_repoint(rec, prepared=lambda o: _undo_outcome(paths, state, op, o))
                except UndoRefused:  # the library could not be opened for the write: nothing changed there
                    _undo_back(paths, state, op, roots)
                    raise
                except (WriteRefused, RekordboxOpened) as err:  # rolled back, analysis files as they were
                    _undo_back(paths, state, op, roots)
                    reason = "rekordbox_open" if isinstance(err, RekordboxOpened) else err.reason
                    raise UndoRefused(reason, converted) from None
                except Exception as err:  # decided by the track's path now, as after a crash
                    message = _settle_undo(paths, state, op, roots)
                    raise UpgradeProblem(f"The undo did not work ({err}). {message}") from err
                op["marks"]["committed"] = True
                mark_op(paths, state, op)
                kept = sorted({f for fields in outcome.kept.values() for f in fields}, key=list(rbstep.TEXT_NAMES).index)
                if kept:
                    note += f". {KEPT_NOTE.format(fields=' / '.join(rbstep.TEXT_NAMES[f] for f in kept))}"
            try:  # step 4
                move_path(paths.root, op["new"], op["staged"], op["crossing"].get("1"), roots)
                if op["held"]:
                    move_path(paths.root, op["held"], op["parked"], op["crossing"].get("2"), roots)
                _end_undo(paths, state, op)
            except Exception as err:  # finish right now if the disk allows, else at the next start
                message = _settle_undo(paths, state, op, roots)
                if not any(o.get("op_id") == op["op_id"] for o in state.get("pending", [])) and \
                        state["tracks"][track_id].get("path") == op["old"]:
                    return note
                raise UpgradeProblem(f"The undo did not finish ({err}). {message}") from err
    return note


def _undo_op(paths: Paths, track_id: str, u: dict, entry: dict, record: dict | None) -> dict:
    """The journal entry of an undo: `old` where the old file goes back to, `superseded` where it is now, `new` the
    AIFF, `staged` where the AIFF goes (.discjockey/undo/), `held` the kept download, `parked` its place in Upgrades
    ready/ (library.CONVERT_PATH_KEYS: every name stays reserved while it runs)."""
    before = u["before"]
    trash = held_place(paths, track_id, u["file"])
    renames = [(u["old"], before["path"]), (u["file"], trash)]
    parked = (before.get("upgrade") or {}).get("file")
    if u.get("held"):  # Same track's kept download goes back to Upgrades ready/; a Convert holds none
        renames.append((u["held"], parked))
    crossing, size = journal_crossings(paths.root, renames)
    return {"kind": "convert_undo", "track_id": track_id, "source": u.get("source", "upgrade"),
            "old": before["path"], "superseded": u["old"],
            "new": u["file"], "staged": trash, "held": u.get("held"), "parked": parked, "audio": u.get("audio"), "placed_by": u.get("placed_by"),
            "crossing": crossing, "size": size, "entry": rbstep.with_audio(_placed_again(entry, u), _audio_of(u.get("audio"))),
            "rekordbox": None if not record else {"dbid": record["dbid"], "record": record, "outcome": None},
            "marks": {"restored": False, "committed": False}}


def _placed_again(entry: dict, u: dict) -> dict:
    """`entry` (the song as it was) with the read-only `placed_by` of the old file back, as its row gets it with the end."""
    return {**entry, "placed_by": u["placed_by"]} if u.get("placed_by") else entry


def _audio_of(record: dict | None) -> FileAudio | None:
    return FileAudio(**record) if record else None


def _undo_outcome(paths: Paths, state: dict, op: dict, outcome: rbwrite.UndoOutcome) -> None:
    """Inside the undo's transaction, before its COMMIT: what it put back and kept, into the journal."""
    op["rekordbox"]["outcome"] = {"restored": outcome.restored, "kept": outcome.kept, "anlz": outcome.anlz}
    mark_op(paths, state, op)


def _end_undo(paths: Paths, state: dict, op: dict) -> None:
    """Step 4's end: the song as it was, its old file's row (with its facts, when the record has them: a Convert's),
    the end of the journal entry."""
    old_audio = _audio_of(op.get("audio"))
    end_op(paths, state, op, {op["track_id"]: op["entry"]}, rekeyed=[op["old"]],
           audio={op["old"]: old_audio} if old_audio else None,
           placed_by={op["old"]: op["placed_by"]} if op.get("placed_by") else None)
    if op.get("held"):
        try:
            (paths.root / op["held"]).parent.rmdir()
        except OSError:  # not empty, or gone
            pass


def _undo_back(paths: Paths, state: dict, op: dict, roots: Collection[Path]) -> Recovered:
    """An undo that didn't reach rekordbox's commit: the old file back to Superseded/, the step ends with nothing
    changed. A staged copy the way back left is removed first."""
    copy = op["crossing"].get("0")
    if copy:
        remove_staged(paths.root / copy)
    staged, size = {}, {}
    if library.crosses(paths.root, op["old"], op["superseded"]):
        staged = {"0": library.staging_path(op["superseded"])}
        size = {"0": (paths.root / op["old"]).stat().st_size}
    r = recover_renames(paths.root, {"renames": [[op["old"], op["superseded"]]], "staged": staged, "size": size},
                         roots)
    if not r.wait:
        end_op(paths, state, op, {})
    return r


def _undo_forward(paths: Paths, state: dict, op: dict, roots: Collection[Path]) -> Recovered:
    """Every move of the undo still to do, then its end."""
    renames = [[op["superseded"], op["old"]], [op["new"], op["staged"]]]
    if op.get("held"):
        renames.append([op["held"], op["parked"]])
    step = {"renames": renames, "staged": op["crossing"], "size": op.get("size") or {}}
    r = recover_renames(paths.root, step, roots)
    if not r.wait:
        _end_undo(paths, state, op)
    return r


def _settle_undo(paths: Paths, state: dict, op: dict, roots: Collection[Path]) -> str:
    outcome = recover_convert_undo(paths, state, op, roots, held=True)
    if isinstance(outcome, Waits):
        return library.waiting(outcome, True)[0]
    return outcome[0]


def recover_convert_undo(paths: Paths, state: dict, op: dict, roots: Collection[Path] | None = None, *,
                         held: bool = False) -> tuple[str, bool] | Waits:
    """Finishes or rolls back an undo an earlier run was interrupted in. Its commit point is rekordbox's transaction,
    so a step with a rekordbox record is decided by the tracks' `FolderPath` now: the old file's → finished (step 4);
    still the new file's → rolled back (analysis files the cut-off write left with the old path get the new one
    again, which needs rekordbox closed: until then the step waits; the old file back to Superseded/); neither →
    rekordbox left alone, rolled back, "needs your help". Another rekordbox library (or none): by the `committed`
    mark. A step without rekordbox is finished. Analysis files are only written under `rekordbox.lock` (`held`: the
    undo's own session has it); another holder makes the step wait."""
    roots = watched_roots(paths) if roots is None else roots
    name = rbstep.track_name(op.get("entry") or {}, op["track_id"])
    try:
        away = drive_away(op, paths.root, roots)
        if away is not None:
            short = short_path(away)
            return Waits(name, Recovered(DRIVE_GONE.format(path=short), False, True, drive=short),
                          not waits_offline(op, paths.root, roots))
        rb = op.get("rekordbox")
        side = "done"
        if rb is not None:
            rows = rb["record"]["rows"]
            side = rbstep.tracks_at(rb["dbid"], {r["id"]: (r["identity_before"]["FolderPath"],
                                                    r["identity_after"]["FolderPath"]) for r in rows})
        if side == "unreadable":
            return Waits(name, Recovered("", False, True), True, _say(op, rbstep.UNDO_UNREADABLE_WAIT).format(name=name))
        if side == "unclean":
            return Waits(name, Recovered("", False, True), True, _say(op, rbstep.UNDO_UNCLEAN_WAIT).format(name=name))
        if rb is not None:
            rbstep.clear_leftovers(paths, (a["path"] for a in rb["record"].get("anlz", [])), held)
        if side == "other":
            side = "done" if op["marks"].get("committed") else "back"
            words = UNDO_OTHER_MAC_DONE if side == "done" else UNDO_OTHER_MAC_UNDONE
        elif side == "neither":
            words = UNDO_NEEDS_HELP
        else:
            words = UNDO_FINISHED if side in ("done", "new") else UNDO_NOT_FINISHED
        words = _say(op, words)
        if side in ("done", "new"):
            r = _undo_forward(paths, state, op, roots)
            ok = not r.problem
        else:
            if side == "old":
                back = rbstep.anlz_undo_back(op)
                if back and process.running():
                    return Waits(name, Recovered("", False, True), True, _say(op, rbstep.UNDO_WAIT_REKORDBOX).format(name=name))
                try:
                    with rbstep.rekordbox_lock(paths, held or not back):
                        for path, data in back:
                            rbwrite.replace_bytes(path, data)
                except Busy:
                    return Waits(name, Recovered("", False, True), True,
                                  rbstep.WAIT_BUSY.format(what="undo", name=name))
            r = _undo_back(paths, state, op, roots)
            ok = False
        if r.wait:
            return Waits(name, r, not waits_offline(op, paths.root, roots))
        message = words.format(name=name, old=op["old"], new=op["new"])
        if r.problem:
            message += f" ({r.problem})"
        return message, ok
    except Exception as err:  # e.g. permissions: the step stays and is tried again at the next start
        return rbstep.COULD_NOT_FINISH_UNDO.format(name=name, err=err), False
