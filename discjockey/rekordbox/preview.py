"""`preview`: what Same track, Convert to AIFF and Give it its clean name would do for one file, answered read-only
(plan stage A §2; design rekordbox-repoint §10). The body of `discjockey rekordbox preview` and of the bridge method
that comes later (it decodes the file, 1–3 s: callers run it where the spectrum read runs).

It reads the library's snapshot (`library.load_state`: no lock, nothing written), the file's facts and rekordbox's
answer for the file (`timeline_offset`, which only reads), and puts them through the pure rules of `eligible`. It
changes nothing: no file is made, moved or tagged, no name is reserved (the names come from a fresh `NameReserver`
that is thrown away), and nothing is left beside rekordbox's library.

A file the library doesn't know (`path` for any file) still gets the rekordbox part; its `eligible` values are all
`not_in_library`. Raises `PreviewRefused` (an unknown key, a file that isn't there) or `PreviewFailed` (the file can't
be read, the records can't be read).
"""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from .. import audio, library, rekordbox
from ..library import NameReserver, Paths, StateError, watched_root
from ..names import expected_stem, fold, split_name, strip_id_suffix
from ..planner import replacement_dir, superseded_dir
from ..upgrades import swap_possible
from . import eligible
from .eligible import Eligible, Skip

# What a reason says in a sentence (the console's words; the window brings its own from design §8)
REASON_WORDS = {
    "no_upgrade": "no better version is waiting",
    "needs_choice": "it's a different edit, so you choose",
    "file_missing": "the file isn't where Discjockey expects it",
    "away": "its drive isn't connected",
    "rekordbox_unreadable": "Same track needs a rekordbox library Discjockey can open",
    "timing": "Discjockey couldn't line the new file up with your rekordbox track exactly; analyse the track again "
              "in rekordbox and try again",
    "not_analysed": "rekordbox hasn't analysed this track yet, so Discjockey can't tell exactly where your cues "
                    "sit; analyse it in rekordbox, quit rekordbox, and try again",
    "cloud": "this track is in rekordbox's Cloud Library Sync, which Discjockey doesn't change yet",
    "downloaded": "a file Discjockey downloaded is clean already",
    "clean_aiff": "already a clean AIFF",
    "named_already": "already has its clean name",
    "needs_convert": "needs Convert to AIFF first",
    "no_name": "no artist or title known",
    "not_in_library": "not a file of your library",
    "auto_refused": "an automatic upgrade was refused for it before",
}


class PreviewRefused(Exception):
    """Nothing to preview: `reason` is "unknown_track", "file_missing" or "away"."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


class PreviewFailed(Exception):
    """The answer couldn't be read: the file (ffmpeg, permissions) or the library's records."""


def _under_missing_volume(path: str) -> bool:
    parts = Path(path).parts
    return len(parts) >= 3 and parts[:2] == ("/", "Volumes") and not os.path.ismount(os.path.join("/", "Volumes", parts[2]))


def _absolute(paths: Paths | None, rel: str) -> Path:
    return (paths.root / rel) if paths is not None else Path(rel)


def _find(state: dict | None, paths: Paths | None, file: Path) -> str | None:
    """The key of the song whose current file is `file`, else None."""
    if state is None or paths is None:
        return None
    wanted = fold(os.path.abspath(file))
    for key, entry in state["tracks"].items():
        if entry.get("path") and fold(os.path.abspath(paths.root / entry["path"])) == wanted:
            return key
    return None


def _fresh(paths: Paths, state: dict, free: str | None = None) -> NameReserver:
    """A throw-away reserver over the records; `free`, a path the step would vacate, is released."""
    names = NameReserver(paths.root, state)
    if free:
        names.release(free)
    return names


def _clean_name(paths: Paths, state: dict, key: str, entry: dict, folder: str) -> str | None:
    """The path `<folder>/<Artist - Title>.aiff` would get, the file's own name counted as free (it moves away first,
    as in `upgrades.add_new`)."""
    if not (entry.get("artist") or "").strip() or not (entry.get("title") or "").strip():
        return None
    stem = expected_stem(entry["artist"], entry["title"])
    if fold(entry["path"]) == fold(f"{folder}/{stem}.aiff"):
        return entry["path"]
    try:
        return _fresh(paths, state, entry["path"]).choose(folder, stem, ".aiff", key)
    except FileExistsError:
        return None


def _superseded(paths: Paths, state: dict, key: str, entry: dict) -> str:
    stem, ext = split_name(strip_id_suffix(PurePosixPath(entry["path"]).name, key))
    return _fresh(paths, state).choose(superseded_dir(entry["path"], watched_root(paths, entry["path"])), stem, ext, key)


def _places(paths: Paths, state: dict, key: str, entry: dict, same: eligible.Verdict, conv: eligible.Verdict,
            ren_path: str | None, ren: eligible.Verdict) -> tuple[str | None, str | None]:
    """(new file, where the old one goes) as absolute paths, for the first action that can run; (None, None) when
    none can. A rename moves nothing to Superseded/."""
    if isinstance(same, Eligible):
        if swap_possible(entry):
            new = entry["path"]
        else:
            status = entry["upgrade"].get("status", "lossless")
            new = _clean_name(paths, state, key, entry, replacement_dir(entry, status))
    elif isinstance(conv, Eligible):
        new = _clean_name(paths, state, key, entry, replacement_dir(entry, entry["status"]))
    elif isinstance(ren, Eligible):
        return (str(paths.root / ren_path) if ren_path else None), None
    else:
        return None, None
    old = _superseded(paths, state, key, entry)
    return (str(paths.root / new) if new else None), str(paths.root / old)


def _clean_tags(paths: Paths | None, entry: dict | None, facts: audio.FileFacts, from_upgrade: bool) -> dict[str, str]:
    """The text the new file would carry. Same track's new file takes the parked download's tags (design §3.5, "From an
    upgrade"), read as they are; any other action writes the record's (`eligible.expected_tags`)."""
    if entry is None:
        return facts.tags
    if from_upgrade and paths is not None:
        try:
            return audio.file_facts(paths.root / entry["upgrade"]["file"]).tags
        except (RuntimeError, OSError):  # the parked file can't be read: the record's text is the best guess
            pass
    return eligible.expected_tags(entry, facts.tags)


def preview(paths: Paths | None, *, track: str | None = None, path: Path | str | None = None,
            offset: Callable[[Path], rekordbox.TimelineOffset] | None = None) -> dict:
    """The command's JSON for the song `track` (its key) or the file `path`. `paths` is the music folder's, None
    when there is none (then only `path` works, and the library knows nothing)."""
    if (track is None) == (path is None):
        raise ValueError("preview takes a track or a path")
    state = None
    if paths is not None and (track is not None or paths.db_file.exists() or paths.state_file.exists()):
        try:
            state = library.load_state(paths)
        except StateError as e:
            if track is not None:
                raise PreviewFailed(str(e)) from None
    if track is not None:
        entry = (state or {"tracks": {}})["tracks"].get(track)
        if entry is None:
            raise PreviewRefused("unknown_track", f"Discjockey doesn't know a track {track}.")
        key = track
        if not entry.get("path"):
            raise PreviewRefused("file_missing", "This track has no file.")
        file = paths.root / entry["path"]
    else:
        file = Path(path).expanduser()
        key = _find(state, paths, file)
        entry = state["tracks"][key] if key else None
    if not file.is_file():
        if _under_missing_volume(os.path.abspath(file)):
            raise PreviewRefused("away", f"The drive with {file} isn't connected.")
        raise PreviewRefused("file_missing", f"There is no file at {file}.")
    try:
        facts = audio.file_facts(file)
        timeline = (offset or rekordbox.timeline_offset)(file)
    except (RuntimeError, OSError) as e:  # ProbeError is a RuntimeError
        raise PreviewFailed(f"Discjockey couldn't read {file.name}: {e}") from None

    rb = timeline.rekordbox
    same = eligible.same_track(entry, facts, rb, timeline) if entry else None
    clean = _clean_tags(paths, entry, facts, isinstance(same, Eligible)) if timeline.entries else facts.tags
    rows = [{"id": t.entry.id, "cues": t.cues, "grid": t.grid, "pwv3": t.pwv3, "offset_ms": t.offset_ms,
             "expected_ms": t.expected_ms, "score": t.score, "cloud": t.entry.cloud,
             "fields_kept": eligible.fields_kept(t.entry, facts.tags, clean)} for t in timeline.entries]
    out = {"ok": True, "track": key if entry else None, "file": str(file.absolute()), "codec": facts.codec,
           "sample_rate": facts.sample_rate, "bits": facts.bits, "new_file": None, "superseded": None,
           "rekordbox": {"state": rb.state, "running": rb.running, "problem": rb.problem},
           "timing": {"result": timeline.why, "offset_samples": timeline.samples}, "entries": rows,
           "eligible": dict.fromkeys(eligible.ACTIONS, "not_in_library")}
    if entry is None:
        return out
    conv = eligible.convert(entry, facts, rb, timeline)
    ren_path = _clean_name(paths, state, key, entry, str(PurePosixPath(entry["path"]).parent))
    ren = eligible.rename(entry, facts, rb, timeline, clean_path=ren_path)
    out["eligible"] = {"same_track": eligible.reason_of(same), "convert": eligible.reason_of(conv),
                       "rename": eligible.reason_of(ren)}
    out["new_file"], out["superseded"] = _places(paths, state, key, entry, same, conv, ren_path, ren)
    return out
