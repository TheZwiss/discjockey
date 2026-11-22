"""`history` (issue 39, design §5.3, §7.4): what changed and what can be undone, as one list. Runs, batches (AIFF and
moves) and the single steps of the operations log are put in one order, newest first, and each carries the command that
undoes it or the words that say why none does. Pure: `CliApi.history` gathers the records and gives them here.

A single step that an AIFF batch made is part of that batch (its record holds the track, the line's time lies between
the batch's start and end, and the operation is one an AIFF batch writes): the batch is listed, the step is not. A move
batch folds nothing: `tidy.py` writes no operations-log line.

An undo is offered as a command only when the catalogue has built it (`built`): one that is still planned says so
(`words.UNDO_NOT_YET`), so a later phase's verb appears in `history` by itself when it lands."""
from __future__ import annotations

import shlex
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import UTC, datetime

from .. import batches as batch_rule, folders, words
from ..upgrades import can_undo
from . import since as since_mod, views

# The operations `track undo` puts back: one step of a song that `can_undo` still allows, when it is the song's latest.
_TRACK_UNDO = frozenset(("upgrade_same_track", "upgrade_add_new", "upgrade_place", "aiff_convert", "aiff_rename"))
# The steps whose undo is the opposite switch: `operation -> (method, command)` of the command that does it.
_SWITCHES = {"never download": ("never_download", "track download"), "download allowed": ("never_download", "track never"),
             "hide": ("hide", "track unhide"), "unhide": ("hide", "track hide")}
# The steps nothing undoes, with the words that say why.
_CANT = {
    "upgrade_discard": words.DISCARD_CANT,
    "undo_upgrade": words.WAS_UNDO, "undo_convert": words.WAS_UNDO, "undo_rename": words.WAS_UNDO,
    "rekordbox_checked": words.CHECKED_CANT,
    folders.SUPERSEDE: words.SUPERSEDED_CANT,
    "download again": words.DOWNLOAD_CANT,
    "removed from library": words.REMOVED_CANT,
    "add_bought_file": words.NEW_VERSION_CANT, "use_candidate": words.NEW_VERSION_CANT, "use_link": words.NEW_VERSION_CANT,
    "reject_current": words.UNKNOWN_CANT,
}
# Every operation name the code writes to the log (tests/test_hub_history.py pins this against the writers).
OPERATIONS = _TRACK_UNDO | _SWITCHES.keys() | _CANT.keys()
# What an AIFF batch writes to the log: its steps are folded into the batch.
_BATCH_STEPS = frozenset((*batch_rule.OPERATIONS.values(), *batch_rule.UNDO_OPERATIONS.values()))
_EPOCH = datetime.fromtimestamp(0, UTC)

Built = Callable[[str, str], bool]


def entries(runs: Sequence[Mapping], batches: Sequence[Mapping], operations: Sequence[tuple[int, Mapping]], *,
            tracks: Mapping[str, Mapping], batch_tracks: Mapping[int, Collection[str]],
            finished_order: Mapping[str, int], built: Built, now: datetime, since: str | None) -> list[dict]:
    """Every run, batch and single step from `since` on, newest first (equal times: runs, then batches, then steps, a
    step of a later log line first). `runs`: `views.runs` rows; `batches`: `batches` rows of both kinds; `operations`:
    `(line number, line)` of the operations log, the numbering of `finished_order` (track -> the line of its latest
    finished upgrade step); `tracks`: the library's records; `batch_tracks`: each AIFF batch's songs, by its number;
    `built(method, command)`: whether the catalogue has that command (not planned); `since`: an ISO time or None."""
    out = [_run(r) for r in runs if since_mod.after(r["started"], since)]
    out += [_batch(b, built) for b in batches if since_mod.after(b["started"], since)]
    spans = _spans(batches, batch_tracks, now)
    for n, op in sorted(operations, key=lambda numbered: numbered[0], reverse=True):
        if op.get("result") == "done" and since_mod.after(op.get("time"), since) and not _folded(op, spans):
            out.append(_step(n, op, tracks, finished_order, built))
    return sorted(out, key=lambda e: _moment(e["at"]), reverse=True)


def _moment(at: str | None) -> datetime:
    """`at` as an aware time (no zone is local); a stamp that cannot be read comes first in time."""
    try:
        return datetime.fromisoformat(at).astimezone()
    except (TypeError, ValueError):
        return _EPOCH


def _entry(kind: str, id_: str | None, at: str, text: str, undo: str | None, cant_text: str | None, *,
           track_id: str | None = None, artist: str | None = None, title: str | None = None) -> dict:
    return {"kind": kind, "id": id_, "at": at, "text": text, "undo": undo, "cant_text": cant_text, "track_id": track_id,
            "artist": artist, "title": title}


def _command(built: Built, method: str, command: str, argument: str) -> tuple[str | None, str | None]:
    """`(undo, cant_text)` of a command that undoes something: the line to type when the catalogue has it, else the
    words that say it comes later."""
    line = f"{command} {shlex.quote(argument)}"
    if built(method, command):
        return line, None
    return None, words.UNDO_NOT_YET.format(command=line)


def _run(r: Mapping) -> dict:
    counts = r["counts"]
    line = (r.get("auto_upgrade") or {}).get("line") or words.HISTORY_RUN_NOTHING
    text = words.HISTORY_RUN[r["kind"]].format(line=line, **counts)
    return _entry("run", r["id"], r["started"] or "", text, None, words.RUN_CANT)


def _batch(b: Mapping, built: Built) -> dict:
    if b["kind"] == "aiff":
        what = (words.AUTO_BATCH_DETAIL if b["started_by"] in views.SYNC_STARTERS
                else words.HISTORY_AIFF.get(b["what"], b["what"]))
        text = words.HISTORY_AIFF_DONE.format(what=what, done=b["done"], total=b["total"])
        method = "batch_undo"
    else:
        text = f"{b['what']} · {views.moves_summary(b['done'], b['skipped'])}"
        method = "undo_moves"
    undo, cant = _batch_undo(b, method, built)
    return _entry("batch", b["id"], b["started"], text, undo, cant)


def _batch_undo(b: Mapping, method: str, built: Built) -> tuple[str | None, str | None]:
    """The undo of a batch, or why it has none. Its `done` counts the items still done: a batch that is all undone
    has none left."""
    if b["state"] == "running":
        return None, words.STILL_RUNNING
    if b["started_by"] == "undo":
        return None, words.WAS_UNDO
    if b["undone_by"] is not None:
        return None, words.UNDONE_BY.format(id=b["undone_by"])
    if not b["done"]:
        return None, words.UNDONE if b["undone"] else words.NOTHING_DONE
    return _command(built, method, "batch undo", b["id"])


def _spans(batches: Sequence[Mapping], batch_tracks: Mapping[int, Collection[str]],
           now: datetime) -> list[tuple[datetime, datetime, Collection[str]]]:
    """Each AIFF batch's time from its start (to the second, as the log's lines are) to its end (a batch that has none:
    now), with its songs."""
    return [(_moment(b["started"]).replace(microsecond=0), _moment(b["ended"]) if b["ended"] else now.astimezone(),
             batch_tracks.get(b["batch"], ())) for b in batches if b["kind"] == "aiff"]


def _folded(op: Mapping, spans: Sequence[tuple[datetime, datetime, Collection[str]]]) -> bool:
    """Whether an AIFF batch made this step: one of its songs, an operation a batch writes, inside its time."""
    if op.get("operation") not in _BATCH_STEPS or not op.get("track_id"):
        return False
    when = _moment(op.get("time"))
    return any(start <= when <= end and op["track_id"] in held for start, end, held in spans)


def _step(n: int, op: Mapping, tracks: Mapping[str, Mapping], finished_order: Mapping[str, int],
          built: Built) -> dict:
    name = op.get("operation", "")
    artist, title = op.get("artist"), op.get("title")
    said = words.OPERATION_WORDS.get(name, name)
    text = f"{artist} - {title}: {said}" if artist and title else said
    track_id = op.get("track_id") or None
    undo, cant = _step_undo(name, n, track_id, tracks, finished_order, built)
    return _entry("operation", None, op.get("time") or "", text, undo, cant, track_id=track_id, artist=artist, title=title)


def _step_undo(name: str, n: int, track_id: str | None, tracks: Mapping[str, Mapping],
               finished_order: Mapping[str, int], built: Built) -> tuple[str | None, str | None]:
    if name in _TRACK_UNDO:
        record = tracks.get(track_id) if track_id else None
        if record is None:
            return None, words.SONG_GONE
        if finished_order.get(track_id) != n:
            return None, words.LATER_STEP
        if not can_undo(record):
            return None, words.CANT_UNDO_NOW
        return _command(built, "undo_upgrade", "track undo", track_id)
    if name in _SWITCHES:
        method, command = _SWITCHES[name]
        return _command(built, method, command, track_id) if track_id else (None, words.UNKNOWN_CANT)
    return None, _CANT.get(name, words.UNKNOWN_CANT)
