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
AIFF batch (`batches.start`, scope `console`) that `batch_cmd._finish` runs: the exit codes 0-5, the `--json` shapes and
Ctrl-C are exactly those of `upgrade apply` (batch_cmd's docstring). A plan with nothing in it is exit 1,
`{"ok": false, "kind": "refused", "reason": "nothing_to_do", "message", "batch": null, "results": [], "plan"}`;
`bad_args` (exit 1) is a combination of arguments that means nothing, or an `--in` playlist or folder that doesn't exist
("No playlist called “X”."; an existing empty one is "Nothing to change"). `batch list | show | resume | undo` and
`rekordbox checked --batch` work for these batches as for any other.

A library whose own files come from before schema 8 has no stored audio facts until an import ran, and the plan reads
them. So both commands, a dry run included, first fill the missing facts (`importer.fill_facts`: it only reads the
files) under the library lock, with a progress line on stderr; a dry run that finds none takes no lock and writes
nothing. A file ffprobe can't read is marked once (`db.set_facts_failed`) and no longer counts as missing facts. `batches.run` does the rest: one rekordbox session, one backup, Stop between files.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import aiff_plan, batch_cmd, batches, convert, db, importer, library, rekordbox
from .batch_cmd import BUSY, FAILED, LOCK_HELD, NO_LIBRARY, OK, STOPPED
from .events import BatchProgress, Cancelled, CancelToken, ImportProgress
from .hub import views
from .library import LockHeld, NoLibrary, Paths, StateError
from .rekordbox import process
from .rekordbox_cmd import failed, no_library, say

GROUPS = ("lossless", "cdj")
NOTHING_TO_DO = aiff_plan.NOTHING_TO_CHANGE
STOPPED_WORDS = "Stopped. Everything finished so far is saved."
READING = "Reading what your files are: {done} of {total}"
VERBS = {"convert": "Converting", "rename": "Renaming"}
LOSSY_NOTE = "{n} of these {are} lossy: an AIFF made from them sounds the same and takes 5–10 times the space."
BAD_IN_FORM = "--in is playlist:<name>, folder:<path> or unlisted."
NO_PLAYLIST = "No playlist called “{name}”."
NO_FOLDER = "No folder at {path}."
BAD_IN_WITH_TRACKS = "--in narrows --all; it means nothing with named songs."
BAD_IN_WITH_CDJ = "--all cdj is the whole group of files CDJs won't play well; --in can't narrow it."


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
        with batch_cmd._interruptible(token):
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
        with db.connect(paths.db_file) as conn:
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


def _plan(paths: Paths, state: dict, job: Job) -> aiff_plan.AiffPlan:
    """`aiff_plan.read_plan` for the job: one read open of rekordbox's library for the lookup of its tracks."""
    return aiff_plan.read_plan(paths, state, job.scope, place=rekordbox.locate(), running=process.running(),
                               only=job.only)


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
    batch_cmd._say(args, {"ok": False, "kind": "refused", "reason": "nothing_to_do", "message": message,
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
    batch_id = batches.start(paths, plan.actions(), started_by=job.started_by, scope="console")
    emit = _progress(plan)
    return batch_cmd._finish(
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
    return batch_cmd._in_library(args, lambda paths, state, recovered: _run(args, paths, state, recovered, job))
