"""The console front end of issue 33's stage D: `discjockey convert` and `discjockey rename` (plan rekordbox stage D §2;
design §10). They run the same batches as the window's Convert to AIFF, Give it its clean name, Make all lossless files
AIFF and the CDJ group's Convert all, through what `aiff_plan`, `batches`, `convert` and `rename` do; this module only
finds the files, asks the plan, starts the batch and prints the way it ended. It adds no file logic.

  convert <track>…            Each named song: a clean AIFF (`eligible.aiff_action` decides between Convert and "only
                              the name"); `user`.
  convert --all lossless      Every lossless file of the library, or of `--in`'s view (`playlist:<name>`,
                              `folder:<path>`, `unlisted`): Make all lossless files AIFF; `make_aiff`.
  convert --all cdj           The group "Won't play well on CDJs": Convert all; `cdj_all`; `--in` is `bad_args`.
  rename <track>… | --all     Rename's answer alone: the file's clean name for an own clean AIFF (`--all`: every one
                              whose name isn't clean, `--in` as above); `user`.

`--dry-run` prints the plan (human lines, or `{"ok": true, "dry_run": true, "plan": AiffPlan.to_dict()}`) and starts
nothing. A run takes the library lock, finishes interrupted steps (`library.recover_pending`), plans and starts one
AIFF batch (`batches.start`, `via` terminal, scope as `_batch_scope` says) that `_finish` runs. Exit codes: 0 done for
every file, or a dry run; 1 refused or failed, or some files skipped or failed (each result says why); 2 no music folder;
3 busy (the library lock or `rekordbox.lock` is held); 4 rekordbox is open (quit it, then `batch resume`); 5 stopped
(Ctrl-C between files: `batch resume aiff:<n>`). A plan with nothing in it is exit 1,
`{"ok": false, "kind": "refused", "reason": "nothing_to_do", "message", "batch": null, "results": [], "plan"}`;
`bad_args` (exit 1) is a combination of arguments that means nothing, or an `--in` playlist or folder that doesn't exist
("No playlist called “X”."; an existing empty one is "Nothing to change"). `batch list | show | resume | undo` and
`check done --batch` work for these batches as for any other.

A library whose own files come from before schema 8 has no stored audio facts until an import ran, and the plan reads
them. So both commands, a dry run included, first fill the missing facts (`importer.fill_facts`: it only reads the
files) under the library lock, with a progress line on stderr; a dry run that finds none takes no lock and writes
nothing. A file ffprobe can't read is marked once (`db.set_facts_failed`) and no longer counts as missing facts. `batches.run` does the rest: one rekordbox session, one backup, Stop between files.
"""
from __future__ import annotations

import argparse
import os
import signal
import sqlite3
import sys
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import aiff_plan, batches, convert, db, importer, library, rbstep, rekordbox, report as rep, scanner
from .events import CTRL_C_REPEAT_S, BatchProgress, Cancelled, CancelToken, ImportProgress
from .hub import views
from .library import LockHeld, NoLibrary, Paths, StateError
from .rekordbox import process
from .rekordbox.preview import REASON_WORDS
from .words import NO_FOLDER, NO_PLAYLIST
from .cli.legacy_out import failed, no_library, say

OK, FAILED, NO_LIBRARY, BUSY, REKORDBOX_OPEN, STOPPED = 0, 1, 2, 3, 4, 5
LOCK_HELD = "Another Discjockey run is still going. Wait until it has finished."
GROUPS = ("lossless", "cdj")
NOTHING_TO_DO = aiff_plan.NOTHING_TO_CHANGE
STOPPED_WORDS = "Stopped. Everything finished so far is saved."
READING = "Reading what your files are: {done} of {total}"
VERBS = {"convert": "Converting", "rename": "Renaming"}
LOSSY_NOTE = "{n} of these {are} lossy: an AIFF made from them sounds the same and takes 5–10 times the space."
BAD_IN_FORM = "--in is playlist:<name>, folder:<path> or unlisted."
BAD_IN_WITH_TRACKS = "--in narrows --all; it means nothing with named songs."
BAD_IN_WITH_CDJ = "--all cdj is the whole group of files CDJs won't play well; --in can't narrow it."


# --- the batch run's console output and exit codes, shared by `convert` and `rename` (moved here from the deleted
# old console module for `upgrade`, `batch` and `rekordbox`; those words are the new command line's) ---

def _name(state: dict, track: str) -> str:
    e = state["tracks"].get(track)
    return f"{e['artist']} - {e['title']}" if e else track


def _words(reason: str | None) -> str:
    return REASON_WORDS.get(reason or "", reason or "")


def _say(args: argparse.Namespace, data: dict, lines: list[str], recovered: Sequence = ()) -> None:
    if recovered:
        data = {**data, "recovered": [[m, ok] for m, ok in recovered]}
    say(args, data, lines)


def _in_library(args: argparse.Namespace, work: Callable[[Paths, dict, list], int]) -> int:
    """Runs `work(paths, state, recovered)` with the library lock held, after interrupted steps were finished
    (recovery comes before a batch is recorded, or the new batch would be marked crashed)."""
    resolved = library.resolve_paths()
    if resolved.paths is None:
        return no_library(args, resolved)
    paths = resolved.paths
    try:
        with library.run_lock(paths.lock):
            state = library.open_state(paths)
            recovered = library.recover_pending(paths, state)
            library.clear_tmp(paths, state)
            if not args.json:
                for message, _ok in recovered:
                    print(message)
            return work(paths, state, recovered)
    except NoLibrary as e:
        return failed(args, str(e), "refused", "no_library", code=NO_LIBRARY)
    except LockHeld:
        return failed(args, LOCK_HELD, "busy", code=BUSY)
    except StateError as e:
        return failed(args, str(e))
    except KeyboardInterrupt:  # outside a batch's own handling (recovery, reading): nothing is half done
        return failed(args, "Stopped. Everything finished so far is saved.", "stopped", code=STOPPED)


@contextmanager
def _interruptible(token: CancelToken):
    """Ctrl-C once stops between tracks (the track in work finishes or rolls back); a second one, a second later,
    raises KeyboardInterrupt, which the batch turns into the same stop."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    first: list[float] = []

    def on_ctrl_c(signum, frame):
        now = time.monotonic()
        if not first:
            first.append(now)
            token.cancel()
            print("\nStopping safely after the current track... (press Ctrl-C again to stop immediately)",
                  file=sys.stderr)
        elif now - first[0] >= CTRL_C_REPEAT_S:
            raise KeyboardInterrupt

    previous = signal.signal(signal.SIGINT, on_ctrl_c)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


def _item_lines(state: dict, item: batches.ItemResult) -> list[str]:
    name = _name(state, item.track)
    if item.state == "done":
        where = f" → {PurePosixPath(item.path).name}" if item.path else ""
        lines = [f"{'Upgraded' if item.action == 'same_track' else 'Done'}: {name}{where}"]
        rb = item.rekordbox
        if item.action == "same_track" and rb is None:
            lines.append("  " + rbstep.NO_TRACK_NOTE)
        elif kept := convert.kept_note((rb or {}).get("kept") or []):
            lines.append("  " + kept)
        return lines
    if item.state == "skipped":  # a Convert or Rename item says its own words (no "upgrade"); Same track the preview's
        why = item.message if item.action != "same_track" and item.message else _words(item.reason)
        return [f"Skipped: {name} ({why})"]
    if item.state == "failed":
        return [f"Failed: {name} ({item.message})"]
    if item.state == "undone":
        return [f"Undone: {name}"]
    return [f"Waiting: {name}"]


def _done_line(items: Sequence[batches.ItemResult], done: int, label: str | None) -> str:
    """The summary line of the finished items: a batch with a Same track item (or `label`, "done" for New track and
    Discard) as always, a Convert / Rename batch in plan stage D's §3 words."""
    if label == "done":
        return f"{done} done."
    if label is None and any(i.action == "same_track" for i in items):
        return f"{done} upgraded, your cues stayed."
    made = sum(1 for i in items if i.state == "done" and i.action == "convert")
    named = sum(1 for i in items if i.state == "done" and i.action == "rename")
    plural = lambda n: f"{n} file{'s' if n != 1 else ''}"  # noqa: E731
    parts = ([f"made {plural(made)} AIFF"] if made else []) + (
        [f"gave {plural(named)} {'its' if named == 1 else 'their'} clean name"] if named else [])
    return f"{parts[0][:1].upper()}{parts[0][1:]}{''.join(', ' + p for p in parts[1:])}."


def _batch_lines(state: dict, result: dict, label: str | None = None) -> list[str]:
    """The human text of a batch-shaped dict (`BatchResult.to_dict()` or `_each`'s). `label` "done" is `_each`'s."""
    items = [batches.ItemResult(**i) for i in result["results"]]
    lines = [line for item in items for line in _item_lines(state, item)]
    if result["done"]:
        lines.append(_done_line(items, result["done"], label))
    not_done = result["skipped"] + result["failed"]
    if not_done:
        convert_only = label is None and not any(i.action == "same_track" for i in items)
        lines.append(f"{not_done} left as they are." if convert_only else
                     f"{not_done} not {'done' if label == 'done' else 'upgraded'}.")
    if any(i.state == "done" and i.action != "rename" and (i.rekordbox or {}).get("entries") for i in items):
        # (a clean name keeps the file itself: the USB step is for a file rekordbox's tracks were pointed away from)
        lines.append(rep.USB_STEP)
    return lines


def _code_of(result: dict) -> int:
    return OK if not result["skipped"] and not result["failed"] else FAILED


def _problem(args: argparse.Namespace, state: dict, kind: str, message: str, code: int, result: dict,
             recovered: Sequence, reason: str | None = None, hint: str | None = None, items: bool = True) -> int:
    """A batch ended without finishing: its fields stay in the JSON, the human text is its tracks (`items`) and the
    way on."""
    data = {"ok": False, "kind": kind, **({"reason": reason} if reason else {}), "message": message, **result}
    lines = (_batch_lines(state, result) if items else []) + [message] + ([hint] if hint else [])
    _say(args, data, lines, recovered)
    return code


def _resume_hint(result: dict) -> str | None:
    return f"Resume it with: discjockey batch resume aiff:{result['batch']}" if result.get("batch") else None


def _finish(args: argparse.Namespace, paths: Paths, state: dict, recovered: Sequence, batch_id: int,
            call: Callable[[CancelToken], batches.BatchResult], alone: bool = False,
            left: Sequence[batches.ItemResult] = ()) -> int:
    """Runs `call(token)` (batches.run or resume) and turns every way a batch can end into the output and exit code.
    `alone`: a batch of one track the user named (as the window's single Replace). When it meets rekordbox open or
    `Busy` before anything ran it is closed (`batches.close_unrun`) instead of left `stopped`: the track simply stays
    in Upgrade ready, there is nothing to resume. `left`: tracks the caller named that never became a batch item
    (`convert` / `rename`'s plan left them as they are): a batch that ends normally lists them as skipped, so the exit
    code is 1 as for any skipped track."""
    def unrun(kind: str, error: Exception, d: dict, code: int) -> int | None:
        if not alone or d["total"] != 1 or d["done"]:
            return None
        closed = batches.close_unrun(paths, batch_id, kind, str(error)).to_dict()
        return _problem(args, state, kind, str(error), code, closed, recovered,
                        "rekordbox_open" if kind == "rekordbox_open" else None, items=False)

    token = CancelToken()
    try:
        with _interruptible(token):
            result = call(token)
    except batches.Stopped as e:
        d = e.result.to_dict()
        left = sum(1 for i in d["results"] if i["state"] == "planned")
        return _problem(args, state, "stopped", f"Stopped after {d['total'] - left} of {d['total']}.", STOPPED, d,
                        recovered, hint=_resume_hint(d))
    except KeyboardInterrupt:  # the second Ctrl-C: the batch is `stopped` already (batches.run)
        d = batches.result_of(paths, batch_id).to_dict()
        return _problem(args, state, "stopped", "Stopped. Everything finished so far is saved.", STOPPED, d,
                        recovered, hint=_resume_hint(d))
    except batches.RekordboxOpen as e:
        d = e.result.to_dict()
        if (closed := unrun("rekordbox_open", e, d, REKORDBOX_OPEN)) is not None:
            return closed
        done = d["total"] - sum(1 for i in d["results"] if i["state"] == "planned")
        if done:
            message = batches.STOPPED_BY_REKORDBOX_CONSOLE.format(done=done, total=d["total"], batch=d["batch"])
            return _problem(args, state, "rekordbox_open", message, REKORDBOX_OPEN, d, recovered, "rekordbox_open")
        return _problem(args, state, "rekordbox_open", str(e), REKORDBOX_OPEN, d, recovered, "rekordbox_open",
                        "After you quit rekordbox: discjockey batch resume aiff:" + str(d["batch"]))
    except batches.Busy as e:
        d = batches.result_of(paths, batch_id).to_dict()
        if (closed := unrun("busy", e, d, BUSY)) is not None:
            return closed
        return _problem(args, state, "busy", str(e), BUSY, d, recovered, hint=_resume_hint(d))
    except batches.Refused as e:
        d = e.result.to_dict()
        only = d["results"][0]["reason"] if len(d["results"]) == 1 else None
        return _problem(args, state, "refused", str(e), FAILED, d, recovered, only)
    d = result.to_dict()
    if left:
        d = {**d, "total": d["total"] + len(left), "skipped": d["skipped"] + len(left),
             "results": [*d["results"], *(r.to_dict() for r in left)]}
    _say(args, {"ok": True, **d}, _batch_lines(state, d), recovered)
    return _code_of(d)


class BadArgs(Exception):
    """A combination of arguments that means nothing (exit 1, reason `bad_args`)."""


@dataclass(frozen=True)
class Job:
    """What the command asked for: the plan's `scope`, the `started_by` of its batch, `only` ("rename": Rename's answer
    alone) and the `action` named for songs the plan leaves as they are."""
    scope: dict
    started_by: str
    only: str | None
    action: str

    @property
    def named(self) -> list[str]:
        return self.scope.get("tracks", [])


# --- arguments ---

def add_commands(commands) -> dict[str, argparse.ArgumentParser]:
    """Adds `convert` and `rename` to the top-level sub-commands. Returns their parsers for `check_args`."""
    def common(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("tracks", nargs="*", help="song keys, as the library's JSON prints them")
        p.add_argument("--in", dest="where", metavar="VIEW", default=None,
                       help="with --all: only the files of playlist:<name>, folder:<path> or unlisted")
        p.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS, help="only show the plan")
        p.add_argument("--json", action="store_true", help="print one JSON object")
        return p

    convert_parser = common(commands.add_parser(
        "convert", description="Make files clean AIFFs (16-bit, 44.1 kHz, clean tags and name) and point rekordbox's "
                               "tracks at them while rekordbox is closed; your originals go to Superseded/. Names "
                               "songs, or --all lossless (every lossless file, or --in's view) or --all cdj (the files "
                               "CDJs won't play well)."))
    convert_parser.add_argument("--all", choices=GROUPS, metavar="{lossless,cdj}", default=None,
                                help="every lossless file (Make all lossless files AIFF), or the CDJ group")
    rename_parser = common(commands.add_parser(
        "rename", description="Give clean AIFFs their clean name `Artist - Title.aiff` and point rekordbox's tracks at "
                              "it while rekordbox is closed. The file itself stays."))
    rename_parser.add_argument("--all", action="store_true", help="every clean AIFF whose name isn't clean")
    return {"convert": convert_parser, "rename": rename_parser}


def check_args(args: argparse.Namespace, parsers: dict[str, argparse.ArgumentParser]) -> None:
    """The argument rule argparse can't state."""
    if args.command in parsers and bool(args.tracks) == bool(args.all):
        parsers[args.command].error("give song keys, or --all" + (" lossless | cdj" if args.command == "convert"
                                                                    else ""))


def _view(text: str | None) -> tuple[str, str | None]:
    """`--in`'s text as the plan's (view, key)."""
    if text is None:
        return "all", None
    if text == "unlisted":
        return "unlisted", None
    kind, _, key = text.partition(":")
    if kind in ("playlist", "folder") and key.strip():
        return kind, key
    raise BadArgs(BAD_IN_FORM)


def _job(args: argparse.Namespace) -> Job:
    rename = args.command == "rename"
    group = "lossless" if rename and args.all else (None if rename else args.all)
    if args.where is not None:
        if group is None:
            raise BadArgs(BAD_IN_WITH_TRACKS)
        if group == "cdj":
            raise BadArgs(BAD_IN_WITH_CDJ)
    only = "rename" if rename else None
    if group is None:
        return Job({"kind": "tracks", "tracks": list(dict.fromkeys(args.tracks))}, "user", only, args.command)
    if group == "cdj":
        return Job({"kind": "cdj"}, "cdj_all", only, args.command)
    view, key = _view(args.where)
    return Job({"kind": "lossless", "view": view, "key": key}, "user" if rename else "make_aiff", only, args.command)


# --- the facts fill and the plan ---

def _facts_progress(event) -> None:
    if isinstance(event, ImportProgress) and event.total:
        print(READING.format(done=event.done, total=event.total), file=sys.stderr, flush=True)


def _fill_facts(paths: Paths) -> bool:
    """Stores the audio facts of own files that have none (library lock held); False when Ctrl-C stopped it, what was
    read stays stored."""
    token = CancelToken()
    try:
        with _interruptible(token):
            importer.fill_facts(paths, emit=_facts_progress, token=token)
    except (Cancelled, KeyboardInterrupt):
        return False
    return True


def _needs_fill(paths: Paths) -> bool:
    """Whether a dry run must fill facts first (and so take the lock): own files without facts, or records older than
    schema 8 (a library.db before it has no facts at all; a state.json not yet moved into library.db the same)."""
    if not paths.db_file.exists():
        return paths.state_file.exists()
    try:
        with db.connect(paths.db_file, read_only=True) as conn:
            return db.facts_missing(conn) > 0
    except sqlite3.OperationalError:  # no such column: a writer's open upgrades the schema
        return True


def _check_view(paths: Paths, state: dict, job: Job) -> None:
    """`--in` names a playlist or folder that exists: one that doesn't is BadArgs with its name (an existing empty one
    is "Nothing to change")."""
    view, key = job.scope.get("view"), job.scope.get("key")
    if view not in ("playlist", "folder"):
        return
    lines, _, watched = aiff_plan.view_inputs(paths, view, None, None, None)
    if view == "folder" and (paths.root / key).is_dir():  # a folder on disk that holds no file yet is empty, not wrong
        return
    if not views.view_known(state, view, key, lines=lines, watched=watched):
        raise BadArgs(NO_PLAYLIST.format(name=key) if view == "playlist" else NO_FOLDER.format(path=key))


def _held(paths: Paths, state: dict, job: Job) -> set[str]:
    """The songs the CDJ group leaves out because To-do shows their decision first: a duplicate group listed now
    (`views.decided_songs`, which the hub's `HubApi._decided_now` asks too, so console and hub name the same files).
    Only the `cdj` scope has any. An open "Is this the same song?" question isn't one of them here: those come from the
    import's last plan, which lives in a running window and is on no disk, so a console run can't see them (its files
    stay in the group; Convert all there is still the user's own command)."""
    if job.scope.get("kind") != "cdj" or not paths.db_file.exists():
        return set()
    with db.connect(paths.db_file) as conn:
        groups = db.duplicate_groups(conn)
        files = {g.id: db.group_files(conn, g.id) for g in groups}
        folders = db.watched_folders(conn)
    away = {str(f.path): why for f in folders
            if f.kind == "import" and (why := scanner.away_reason(f.path, os.path.ismount)) is not None}
    return views.decided_songs(state, (), groups, files, (), away, {})


def _plan(paths: Paths, state: dict, job: Job) -> aiff_plan.AiffPlan:
    """`aiff_plan.read_plan` for the job: one read open of rekordbox's library for the lookup of its tracks."""
    return aiff_plan.read_plan(paths, state, job.scope, place=rekordbox.locate(), running=process.running(),
                               only=job.only, held=_held(paths, state, job))


# --- output ---

def _plan_lines(plan: aiff_plan.AiffPlan, job: Job) -> list[str]:
    lines = [f"{i.label}  {i.name}  →  {PurePosixPath(i.new_path).name}" for i in plan.items]
    lines += [f"Left as it is: {s.name} ({s.message})" for s in plan.skipped]
    lines += [f"Waiting ({w['n']}): {w['message']}" for w in plan.waiting]
    if not plan.total:
        return lines + [_nothing_message(plan, job)]
    lines.append(f"{plan.total} file{'s' if plan.total != 1 else ''} would be changed: "
                 + " · ".join(f"{k['label']} {k['n']}" for k in plan.kinds) + ".")
    if plan.lossy:
        lines.append(LOSSY_NOTE.format(n=plan.lossy, are="is" if plan.lossy == 1 else "are"))
    for s in plan.space:
        lines.append(f"Needs {convert.size_text(s['needed'])} on {s['drive']} · {convert.size_text(s['free'])} free"
                     + ("" if s["enough"] else f". Not enough space on {s['drive']}: {convert.size_text(s['needed'])} "
                                               f"needed, {convert.size_text(s['free'])} free"))
    if plan.superseded_bytes:
        lines.append(f"Your originals ({convert.size_text(plan.superseded_bytes)}) go to Superseded/ on the same "
                     "drive.")
    if plan.rekordbox["needs_closed"] and plan.rekordbox["running"]:
        lines.append(convert.REKORDBOX_OPEN)
    return lines + ["Dry run: nothing was changed. The real run checks each file again."]


def _nothing_message(plan: aiff_plan.AiffPlan, job: Job) -> str:
    """"Nothing to change" in general, the one song's own words when the user named just one."""
    if len(job.named) == 1 and len(plan.skipped) == 1:
        return plan.skipped[0].message
    return NOTHING_TO_DO


def _nothing(args: argparse.Namespace, plan: aiff_plan.AiffPlan, job: Job, recovered: Sequence) -> int:
    message = _nothing_message(plan, job)
    lines = [f"Left as it is: {s.name} ({s.message})" for s in plan.skipped if len(job.named) != 1]
    lines += [f"Waiting ({w['n']}): {w['message']}" for w in plan.waiting]
    _say(args, {"ok": False, "kind": "refused", "reason": "nothing_to_do", "message": message,
                          "batch": None, "results": [], "plan": plan.to_dict()}, [message, *lines], recovered)
    return FAILED


def _progress(plan: aiff_plan.AiffPlan) -> Callable:
    """The batch's progress on stderr: "Converting 3 of 52: Artist - Title" / "Renaming …"."""
    verbs = {i.track: VERBS[i.action] for i in plan.items}

    def emit(event) -> None:
        if isinstance(event, BatchProgress) and event.track_id:
            print(f"{verbs.get(event.track_id, 'Converting')} {event.done + 1} of {event.total}: {event.name}",
                  file=sys.stderr, flush=True)
    return emit


# --- the commands ---

def _dry_run(args: argparse.Namespace, paths: Paths, job: Job) -> int:
    try:
        if _needs_fill(paths):
            with library.run_lock(paths.lock):
                if library.open_records(paths, recover=False) and not _fill_facts(paths):
                    return failed(args, STOPPED_WORDS, "stopped", code=STOPPED)
        state = library.load_state(paths)
    except NoLibrary as e:
        return failed(args, str(e), "refused", "no_library", code=NO_LIBRARY)
    except LockHeld:
        return failed(args, LOCK_HELD, "busy", code=BUSY)
    except StateError as e:
        return failed(args, str(e))
    try:
        _check_view(paths, state, job)
    except BadArgs as e:
        return failed(args, str(e), "refused", "bad_args")
    plan = _plan(paths, state, job)
    say(args, {"ok": True, "dry_run": True, "plan": plan.to_dict()}, _plan_lines(plan, job))
    return OK


def _batch_scope(scope: dict) -> str:
    """What the batch records as its scope: `selection` for named songs, `todo:cdj` for the CDJ group, else
    `library:<view>[:<key>]`."""
    if scope["kind"] == "tracks":
        return "selection"
    if scope["kind"] == "cdj":
        return "todo:cdj"
    return "library:" + ":".join(p for p in (scope["view"], scope.get("key")) if p)


def _run(args: argparse.Namespace, paths: Paths, state: dict, recovered: list, job: Job) -> int:
    try:
        _check_view(paths, state, job)  # before the fill: a typo costs no reading
    except BadArgs as e:
        return failed(args, str(e), "refused", "bad_args")
    if not _fill_facts(paths):
        return failed(args, STOPPED_WORDS, "stopped", code=STOPPED)
    state = library.load_state(paths)  # the fill wrote the facts the plan reads
    plan = _plan(paths, state, job)
    if not plan.total:
        return _nothing(args, plan, job, recovered)
    left = [batches.ItemResult(s.track, job.action, "skipped", s.reason, s.message, None, None) for s in plan.skipped]
    batch_id = batches.start(paths, plan.actions(), started_by=job.started_by, scope=_batch_scope(job.scope),
                             via="terminal")
    emit = _progress(plan)
    return _finish(
        args, paths, state, recovered, batch_id,
        lambda token: batches.run(paths, batch_id, emit=emit, token=token, state=state),
        alone=len(job.named) == 1, left=left)


def run(args: argparse.Namespace) -> int:
    """`convert` and `rename`; `cli.main` calls it."""
    try:
        job = _job(args)
    except BadArgs as e:
        return failed(args, str(e), "refused", "bad_args")
    resolved = library.resolve_paths()
    if resolved.paths is None:
        return no_library(args, resolved)
    if getattr(args, "dry_run", False):
        return _dry_run(args, resolved.paths, job)
    return _in_library(args, lambda paths, state, recovered: _run(args, paths, state, recovered, job))
