"""The console front end of issue 33's stage B: `discjockey upgrade …`, `discjockey batch …` and
`discjockey rekordbox checked | backups | restore` (plan rekordbox stage B §2; design rekordbox-repoint §10). The
interactive `discjockey upgrades` stays in `upgrades_cmd.py`; `rekordbox status` / `preview` are `rekordbox_cmd.py`.

Every command runs without prompts and with `--json` prints one object at the end (progress lines go to stderr). A
command that changes anything takes the library lock as the hub does, finishes interrupted steps first
(`library.recover_pending`, before a batch starts) and counts as the user starting it: Same track runs as one AIFF
batch (`batches`: one `rekordbox.lock`, one backup, Stop between tracks), New track and Discard run the tracks one
after the other (no batch record, no Resume: each is quick and has its own undo).

Exit codes: 0 done for every track, or a dry run, or a read; 1 refused or failed, or some tracks skipped or failed
(each result says why); 2 no music folder or no setup; 3 busy (the library lock or `rekordbox.lock` is held); 4
rekordbox is open (nothing done, or the batch stopped there: quit it, then `batch resume`); 5 stopped (Ctrl-C between
tracks: `batch resume <id>`). JSON: `{"ok": true, …}` when the command ran to its end (a dry run, or a batch whose
tracks are listed, skipped ones included: then the exit code is 1), `{"ok": false, "kind": "refused" | "failed" |
"busy" | "rekordbox_open" | "stopped", "reason"?, "message", …}` for a problem; a batch problem carries the batch's
fields too (`batch`, `state`, `results`, …), so the id to resume is always there.
"""
from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath

from . import align, batches, convert, db, library, ops, rekordbox, report as rep, upgrades
from .events import BatchProgress, Cancelled, CancelToken, Result
from .library import LockHeld, NameReserver, NoLibrary, Paths, StateError
from .hub import views
from .rekordbox import backup as rbbackup, eligible
from .rekordbox.eligible import Skip
from .rekordbox.preview import REASON_WORDS
from .rekordbox_cmd import failed, no_library, say
from .settings import SettingsError, load_settings
from .upgrades import UpgradeProblem

OK, FAILED, NO_LIBRARY, BUSY, REKORDBOX_OPEN, STOPPED = 0, 1, 2, 3, 4, 5
CTRL_C_REPEAT_S = 1.0  # as the sync's: uv and caffeinate forward one Ctrl-C a second time
LOCK_HELD = "Another Discjockey run is still going. Wait until it has finished."
NOTHING = "None of these can be upgraded right now."
AUTO_WAITS = "Waited for rekordbox to be closed at your last sync; it is upgraded at your next sync."
WAYS = {"same-track": "same_track", "new-track": "add_new"}
RESTORE_WORDS = {
    "no_rekordbox": "There is no rekordbox library on this Mac, so nothing was changed.",
    "not_found": "There is no backup with that name; `discjockey rekordbox backups` lists them. Nothing was changed.",
    "damaged": "This backup is damaged (its copy of rekordbox's library is not the one its notes name), so nothing "
               "was changed.",
    "other_library": "This backup was made from another rekordbox library than this Mac's, so nothing was changed.",
    "rekordbox_open": convert.REKORDBOX_OPEN,
    "unclean": convert.REFUSED["unclean"],
}
NEEDS_YES = ("This puts rekordbox's whole library back as it was in the backup, and drops every change made in "
             "rekordbox since. Run it again with --yes to do it. Nothing was changed.")
MISSING_AFTER = ("{n} of your rekordbox tracks now point at files that Discjockey has since moved to Superseded/. "
                 "Undo those batches first (`discjockey batch undo`), or Relocate them in rekordbox.")


def add_commands(commands, box_commands) -> dict[str, argparse.ArgumentParser]:
    """Adds `upgrade` and `batch` to the top-level sub-commands and `checked`, `backups` and `restore` to
    `rekordbox`'s. Returns the parsers that need a check after parsing (`apply`, `checked`)."""
    def json_flag(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--json", action="store_true", help="print one JSON object")
        return p

    upgrade = commands.add_parser("upgrade", description="The better versions Discjockey found, without prompts. "
                                  "(`upgrades` goes through them by hand.)")
    steps = upgrade.add_subparsers(dest="upgrade_command", metavar="command", required=True)
    json_flag(steps.add_parser("list", help="the parked upgrades and whether Same track can run",
                               description="Read only: every better version waiting, and why Same track can't run "
                                           "for it yet."))
    apply = json_flag(steps.add_parser(
        "apply", help="replace tracks with their better versions",
        description="Replace the given tracks, or --all of them. same-track: one batch (a file that isn't AIFF "
                    "becomes a new AIFF and rekordbox's track is pointed at it, while rekordbox is closed). "
                    "new-track: each track on its own."))
    apply.add_argument("tracks", nargs="*", help="song keys, as `upgrade list` prints them")
    apply.add_argument("--all", action="store_true", help="every track Same track can run for (Upgrade all)")
    apply.add_argument("--way", required=True, choices=sorted(WAYS), help="Same track or New track")
    apply.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS,
                       help="only show what would happen")
    for name, text in (("discard", "throw away the better versions"), ("undo", "undo the replace of tracks")):
        json_flag(steps.add_parser(name, help=text, description=text.capitalize() + ".")).add_argument(
            "tracks", nargs="+", help="song keys")

    batch = commands.add_parser("batch", description="Same track batches: look at them, resume, undo.")
    batch_steps = batch.add_subparsers(dest="batch_command", metavar="command", required=True)
    json_flag(batch_steps.add_parser("list", help="the newest batches"))
    for name, text in (("show", "one batch with its tracks"), ("resume", "carry on a stopped batch"),
                       ("undo", "undo every track a batch did")):
        json_flag(batch_steps.add_parser(name, help=text, description=text.capitalize() + ".")).add_argument(
            "batch_id", type=int, metavar="id", help="the batch's number")

    checked = json_flag(box_commands.add_parser(
        "checked", help='"Done, checked in rekordbox" for tracks',
        description="The reminder to check tracks in rekordbox goes away, and with it their undo."))
    checked.add_argument("tracks", nargs="*", help="song keys")
    checked.add_argument("--batch", type=int, metavar="ID", help="every track of this batch")
    json_flag(box_commands.add_parser("backups", help="the copies of rekordbox's library Discjockey made"))
    restore = json_flag(box_commands.add_parser(
        "restore", help="put rekordbox's whole library back from a backup",
        description="The last resort: rekordbox's library as the backup holds it. Refuses while rekordbox is open."))
    restore.add_argument("backup", help="the backup's name, as `rekordbox backups` prints it")
    restore.add_argument("--yes", action="store_true", default=argparse.SUPPRESS,
                         help="do it (without it nothing is changed)")
    return {"apply": apply, "checked": checked}


def check_args(args: argparse.Namespace, parsers: dict[str, argparse.ArgumentParser]) -> None:
    """The argument rules argparse can't state."""
    if args.command == "upgrade" and args.upgrade_command == "apply" and bool(args.tracks) == args.all:
        parsers["apply"].error("give song keys, or --all")
    if args.command == "rekordbox" and args.rekordbox_command == "checked" \
            and bool(args.tracks) == (args.batch is not None):
        parsers["checked"].error("give song keys, or --batch ID")


# --- shared ---

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


def _progress(event) -> None:
    if isinstance(event, BatchProgress) and event.track_id:
        print(f"{event.done + 1} of {event.total}: {event.name}", file=sys.stderr, flush=True)


def _rekordbox_status() -> rekordbox.Status:
    try:
        return rekordbox.status(rekordbox.locate())
    except Exception:  # noqa: BLE001 - a library that can't be looked at is "unreadable" for the quick check
        return rekordbox.Status("unreadable", False, None, None, None, None, None)


# --- results ---

def _item_lines(state: dict, item: batches.ItemResult) -> list[str]:
    name = _name(state, item.track)
    if item.state == "done":
        where = f" → {PurePosixPath(item.path).name}" if item.path else ""
        lines = [f"{'Upgraded' if item.action == 'same_track' else 'Done'}: {name}{where}"]
        rb = item.rekordbox
        if item.action == "same_track" and rb is None:
            lines.append("  " + convert.NO_TRACK_NOTE)
        elif kept := convert.kept_note((rb or {}).get("kept") or []):
            lines.append("  " + kept)
        return lines
    if item.state == "skipped":
        return [f"Skipped: {name} ({_words(item.reason)})"]
    if item.state == "failed":
        return [f"Failed: {name} ({item.message})"]
    return [f"Waiting: {name}"]


def _batch_lines(state: dict, result: dict, label: str = "upgraded") -> list[str]:
    """The human text of a batch-shaped dict (`BatchResult.to_dict()` or `_each`'s)."""
    items = [batches.ItemResult(**i) for i in result["results"]]
    lines = [line for item in items for line in _item_lines(state, item)]
    if result["done"]:
        lines.append(f"{result['done']} {label}, your cues stayed." if label == "upgraded"
                     else f"{result['done']} {label}.")
    not_done = result["skipped"] + result["failed"]
    if not_done:
        lines.append(f"{not_done} not {label}.")
    if any(i.state == "done" and (i.rekordbox or {}).get("entries") for i in items):
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
    return f"Resume it with: discjockey batch resume {result['batch']}" if result.get("batch") else None


def _finish(args: argparse.Namespace, paths: Paths, state: dict, recovered: Sequence, batch_id: int,
            call: Callable[[CancelToken], batches.BatchResult], alone: bool = False) -> int:
    """Runs `call(token)` (batches.run or resume) and turns every way a batch can end into the output and exit code.
    `alone`: a batch of one track the user named (as the window's single Replace). When it meets rekordbox open or
    `Busy` before anything ran it is closed (`batches.close_unrun`) instead of left `stopped`: the track simply stays
    in Upgrade ready, there is nothing to resume."""
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
                        "After you quit rekordbox: discjockey batch resume " + str(d["batch"]))
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
    _say(args, {"ok": True, **d}, _batch_lines(state, d), recovered)
    return _code_of(d)


# --- upgrade list ---

def _listed(state: dict, order: list[str]) -> list[tuple[str, dict]]:
    """The parked upgrades the To-do page lists (`views.upgrade_ready_keys`, the same answer as the window's Upgrade
    all), in playlists.txt folder order."""
    keys = set(views.upgrade_ready_keys(state))
    return [(k, e) for k, e in upgrades.ready(state, order) if k in keys]


def _folder_order(paths: Paths) -> list[str]:
    from . import config
    try:
        return [line.folder for line in config.load_playlists(paths.playlists_file)]
    except config.ConfigError:
        return []


def _quality(e: dict, which: str) -> str:
    from .upgrades_cmd import quality_text
    if which == "now":
        return quality_text(e.get("source"), e.get("source_format"), e["status"], e.get("cutoff_hz"),
                            e.get("source_kbps"))
    up = e["upgrade"]
    return quality_text(up["source"], up.get("source_format"), up.get("status", "lossless"), up.get("cutoff_hz"),
                        up.get("kbps"))


def _quick(paths: Paths, e: dict | None, rb: rekordbox.Status) -> str | None:
    """Same track's quick answer for an entry: None when it can run, else the reason."""
    verdict = Skip("no_upgrade") if e is None else eligible.same_track_quick(e, rb, batches.present(paths, e))
    return verdict.reason if isinstance(verdict, Skip) else None


def run_upgrade_list(args: argparse.Namespace) -> int:
    resolved = library.resolve_paths()
    if resolved.paths is None:
        return no_library(args, resolved)
    paths = resolved.paths
    try:
        state = library.load_state(paths)
    except StateError as e:
        return failed(args, str(e))
    try:
        auto_on = load_settings(paths.settings_file).auto_upgrade
    except SettingsError as e:
        return failed(args, str(e), "refused", "settings_invalid")
    rb = _rekordbox_status()
    rows = []
    for key, e in _listed(state, _folder_order(paths)):
        found = e["upgrade"].get("auto_refused")  # the sync's Auto-upgrade record (plan stage C §0.6)
        record = found if isinstance(found, dict) else None
        rows.append({"track": key, "artist": e["artist"], "title": e["title"], "folder": e["folder"],
                     "file": e.get("path"), "parked": e["upgrade"]["file"], "now": _quality(e, "now"),
                     "new": _quality(e, "new"),
                     "alignment": (e["upgrade"].get("alignment") or {}).get("result") or "unknown",
                     "same_track": _quick(paths, e, rb),
                     "auto_refused": {k: record.get(k) for k in ("reason", "message", "at")} if record else None,
                     "auto_waits": auto_on and bool(e["upgrade"].get("auto_waits"))})
    lines = []
    for r in rows:
        lines.append(f"{r['track']}  [{r['folder']}] {r['artist']} - {r['title']}")
        why = "possible" if r["same_track"] is None else f"not now ({_words(r['same_track'])})"
        lines.append(f"    now {r['now']} · new {r['new']} · same edit: {r['alignment']} · Same track: {why}")
        if r["auto_waits"]:
            lines.append("    " + AUTO_WAITS)
        if r["auto_refused"]:
            lines.append(f"    Not upgraded at your sync: {r['auto_refused']['message']}")
    if not rows:
        lines.append("No better versions are waiting.")
    say(args, {"ok": True, "upgrades": rows, "count": len(rows)}, lines)
    return OK


# --- upgrade apply ---

def _plan_row(paths: Paths, state: dict, key: str, e: dict | None, way: str, reason: str | None) -> dict:
    """One track of a dry run: `planned` or `skipped`, with the files it would make."""
    row = {"track": key, "action": WAYS[way], "state": "skipped" if reason else "planned", "reason": reason,
           "file": str(paths.root / e["path"]) if e and e.get("path") else None, "new_file": None, "superseded": None}
    if reason or e is None:
        return row
    try:
        if way == "new-track":
            new, old = upgrades.add_new_names(paths, state, key, e, e["upgrade"].get("status", "lossless"))
        elif upgrades.swap_possible(e):
            new = e["path"]
            old = upgrades.swap_backup_name(paths, NameReserver(paths.root, state), key, e["path"])
        else:
            new, old = convert.plan_names(paths, state, key, e, e["upgrade"])
    except (FileExistsError, KeyError, ValueError):  # no free name now: the run finds out
        return row
    row["new_file"], row["superseded"] = str(paths.root / new), str(paths.root / old)
    return row


def _space(paths: Paths, state: dict, planned: list[dict]) -> list[dict]:
    """What the new AIFF files need, per drive: the sum over the tracks that become a new file (a swap writes into
    the file it replaces and renders in .discjockey/.tmp)."""
    need: dict[int, list] = {}
    for row in planned:
        e = state["tracks"][row["track"]]
        if row["action"] == "same_track" and upgrades.swap_possible(e) or not row["new_file"]:
            continue
        try:
            places = convert.space_needed(paths, paths.root / e["upgrade"]["file"],
                                          Path(row["new_file"]).relative_to(paths.root).as_posix())
        except (RuntimeError, OSError):  # the download can't be probed: the run says so for that track
            continue
        for folder, nbytes in places:
            entry = need.setdefault(library.device(folder), [folder, 0])
            entry[1] += nbytes
    return [{"drive": str(folder), "needed": n, "free": (free := convert.free_space(folder)), "enough": free >= n}
            for folder, n in need.values()]


def _dry_run(args: argparse.Namespace, paths: Paths, tracks: list[str] | None) -> int:
    way = args.way
    try:
        state = library.load_state(paths)
    except StateError as e:
        return failed(args, str(e))
    rb = _rekordbox_status()
    if tracks is None:
        tracks = [k for k, e in _listed(state, _folder_order(paths)) if _quick(paths, e, rb) is None]
    rows = []
    for key in dict.fromkeys(tracks):
        e = state["tracks"].get(key)
        if way == "same-track":
            reason = _quick(paths, e, rb)
        else:
            reason = "no_upgrade" if not e or not e.get("upgrade") else \
                {"away": "away", "missing": "file_missing"}.get(batches.present(paths, e))
        rows.append(_plan_row(paths, state, key, e, way, reason))
    planned = [r for r in rows if r["state"] == "planned"]
    space = _space(paths, state, planned)
    needs_closed = rb.running and way == "same-track" and any(
        not upgrades.swap_possible(state["tracks"][r["track"]]) for r in planned)
    lines = []
    for r in rows:
        name = _name(state, r["track"])
        if r["state"] == "planned":
            target = PurePosixPath(r["new_file"]).name if r["new_file"] else "a new AIFF"
            lines.append(f"Would upgrade: {name} → {target}")
        else:
            lines.append(f"Skipped: {name} ({_words(r['reason'])})")
    lines.append(f"{len(planned)} would be upgraded, {len(rows) - len(planned)} skipped." if rows else NOTHING)
    lines += [f"Not enough free space on {s['drive']}: {convert.size_text(s['needed'])} needed, "
              f"{convert.size_text(s['free'])} free." for s in space if not s["enough"]]
    if needs_closed:
        lines.append(convert.REKORDBOX_OPEN)
    lines.append("Dry run: nothing was changed. The real run checks each track again.")
    say(args, {"ok": True, "dry_run": True, "way": way, "total": len(rows), "planned": len(planned),
               "skipped": len(rows) - len(planned), "results": rows, "space": space,
               "rekordbox": {"state": rb.state, "running": rb.running, "needs_rekordbox_closed": needs_closed}},
        lines)
    return OK


def _each_dict(results: list[batches.ItemResult], stopped: bool) -> dict:
    count = lambda s: sum(1 for r in results if r.state == s)  # noqa: E731
    return {"batch": None, "state": "stopped" if stopped else "done", "stop_reason": "stop" if stopped else None,
            "total": len(results), "done": count("done"), "skipped": count("skipped"), "failed": count("failed"),
            "results": [r.to_dict() for r in results], "backup": None}


def _each(args: argparse.Namespace, paths: Paths, state: dict, recovered: Sequence, tracks: list[str], action: str,
          step: Callable[[str, dict, dict], Result], verb: str) -> int:
    """New track and Discard: the tracks one after the other, as one job (Stop between them, per-track results, no
    batch record). `step(track, entry, upgrade)` does one track and returns its `Result`; `verb` is for the words
    of a failure."""
    token = CancelToken()
    results: list[batches.ItemResult] = []
    stopped = False

    def waiting(left: Sequence[str]) -> None:
        results.extend(batches.ItemResult(t, action, "planned", None, None, None, None) for t in left)

    with _interruptible(token):
        for n, key in enumerate(tracks):
            try:
                token.check()
            except Cancelled:
                stopped = True
                waiting(tracks[n:])
                break
            e = state["tracks"].get(key)
            if not e or not e.get("upgrade"):
                results.append(batches.ItemResult(key, action, "skipped", "no_upgrade", None, None, None))
                continue
            print(f"{n + 1} of {len(tracks)}: {_name(state, key)}", file=sys.stderr, flush=True)
            finished = None
            try:
                with library.deferred_interrupt():  # a Ctrl-C waits until the step is complete
                    finished = step(key, e, dict(e["upgrade"]))
            except KeyboardInterrupt:  # the second Ctrl-C, or the first one handed on after the step
                stopped = True
                if finished is not None:
                    results.append(batches.ItemResult(key, action, "done", None, finished.note, finished.path, None))
                    ops.log_operation(paths, datetime.now(), key, e, f"upgrade_{action}", "done", finished.note)
                    waiting(tracks[n + 1:])
                else:
                    waiting(tracks[n:])
                break
            except UpgradeProblem as err:
                results.append(batches.ItemResult(key, action, "failed", None, str(err), None, None))
                ops.log_operation(paths, datetime.now(), key, e, f"upgrade_{action}", "failed", str(err))
            except Exception as err:  # noqa: BLE001 - one track's surprise must not stop the others
                message = f"Could not {verb} {_name(state, key)} ({type(err).__name__}: {err})."
                results.append(batches.ItemResult(key, action, "failed", None, message, None, None))
                ops.log_operation(paths, datetime.now(), key, e, f"upgrade_{action}", "failed", message)
            else:
                results.append(batches.ItemResult(key, action, "done", None, finished.note, finished.path, None))
                ops.log_operation(paths, datetime.now(), key, e, f"upgrade_{action}", "done", finished.note)
    d = _each_dict(results, stopped)
    if d["done"]:
        rep.write_not_lossless(paths, state)
    lines = _batch_lines(state, d, label="done")
    if stopped:
        left = sum(1 for r in results if r.state == "planned")
        message = f"Stopped after {d['total'] - left} of {d['total']}."
        _say(args, {"ok": False, "kind": "stopped", "message": message, **d}, lines + [message], recovered)
        return STOPPED
    _say(args, {"ok": True, **d}, lines, recovered)
    return _code_of(d)


def run_upgrade_apply(args: argparse.Namespace) -> int:
    if args.all and args.way != "same-track":
        return failed(args, "--all works only with --way same-track (Upgrade all); name the tracks for new-track.",
                      "refused", "all_needs_same_track")
    resolved = library.resolve_paths()
    if resolved.paths is None:
        return no_library(args, resolved)
    if getattr(args, "dry_run", False):
        return _dry_run(args, resolved.paths, None if args.all else list(dict.fromkeys(args.tracks)))

    def work(paths: Paths, state: dict, recovered: list) -> int:
        tracks = list(dict.fromkeys(args.tracks))
        if args.all:
            rb = _rekordbox_status()
            tracks = [k for k, e in _listed(state, _folder_order(paths)) if _quick(paths, e, rb) is None]
            if not tracks:
                return failed(args, NOTHING, "refused", extra={"batch": None, "results": []})
        if args.way == "new-track":
            return _each(args, paths, state, recovered, tracks, "add_new",
                         lambda key, e, up: upgrades.add_new(paths, state, key, up, align.compare_files,
                                                             now=datetime.now), "add")
        batch_id = batches.start(paths, [(t, "same_track") for t in tracks],
                                 started_by="upgrade_all" if args.all else "user")
        return _finish(args, paths, state, recovered, batch_id, lambda token: batches.run(
            paths, batch_id, emit=_progress, token=token, compare=align.compare_files, state=state),
            alone=not args.all and len(tracks) == 1)
    return _in_library(args, work)


def run_upgrade_discard(args: argparse.Namespace) -> int:
    def work(paths: Paths, state: dict, recovered: list) -> int:
        return _each(args, paths, state, recovered, list(dict.fromkeys(args.tracks)), "discard",
                     lambda key, e, up: upgrades.discard(paths, state, key, up), "discard")
    return _in_library(args, work)


# --- undo ---

def _undo_lines(state: dict, d: dict) -> list[str]:
    lines = []
    for i in d["results"]:
        name = _name(state, i["track"])
        lines.append(f"Undone: {name}" if i["state"] == "undone" else
                     f"Not undone yet: {name}" if i["state"] == "waiting" else
                     f"Not undone: {name} ({i['message']})")
    if d["undone"]:
        lines.append(f"{d['undone']} undone.")
    return lines


def _undo(args: argparse.Namespace, paths: Paths, state: dict, recovered: Sequence, target) -> int:
    token = CancelToken()

    def problem(kind: str, message: str, code: int, result: batches.UndoResult) -> int:
        d = result.to_dict()
        _say(args, {"ok": False, "kind": kind, "message": message, **d}, _undo_lines(state, d) + [message], recovered)
        return code

    try:
        with _interruptible(token):
            result = batches.undo(paths, target, emit=_progress, token=token, state=state)
    except batches.RekordboxOpen as e:
        return problem("rekordbox_open", str(e), REKORDBOX_OPEN, e.result)
    except batches.UndoStopped as e:
        return problem("stopped", "Stopped. The tracks undone so far stay undone.", STOPPED, e.result)
    except batches.Busy as e:
        return failed(args, str(e), "busy", code=BUSY)
    d = result.to_dict()
    if d["total"] and not d["undone"]:  # as the window: nothing at all was undone is a refusal, the results still there
        message = result.results[0].message if d["total"] == 1 else batches.NOTHING_UNDONE
        _say(args, {"ok": False, "kind": "refused", "message": message, **d}, _undo_lines(state, d) + [message],
             recovered)
        return FAILED
    _say(args, {"ok": True, **d}, _undo_lines(state, d), recovered)
    return OK if not d["refused"] and not d["failed"] else FAILED


def run_upgrade_undo(args: argparse.Namespace) -> int:
    return _in_library(args, lambda paths, state, recovered: _undo(
        args, paths, state, recovered, list(dict.fromkeys(args.tracks))))


# --- batch ---

def _batch_dict(row) -> dict:
    c = row.counts
    return {"batch": row.id, "kind": row.kind, "started_by": row.started_by, "state": row.state,
            "stop_reason": row.stop_reason, "started": row.started, "ended": row.ended, "total": sum(c.values()),
            "done": c["done"], "skipped": c["skipped"], "failed": c["failed"], "planned": c["planned"],
            "undone": c["undone"], "backup": row.backup}


def _batch_line(b: dict) -> str:
    stop = f", {b['stop_reason']}" if b["stop_reason"] else ""
    return (f"#{b['batch']}  {b['started'][:16].replace('T', ' ')}  {b['state']}{stop}  {b['done']} of {b['total']} "
            f"done" + (f", {b['skipped']} skipped" if b["skipped"] else "") +
            (f", {b['failed']} failed" if b["failed"] else "") + (f", {b['undone']} undone" if b["undone"] else "") +
            (f", {b['planned']} left" if b["planned"] else "") + f"  ({b['started_by']})")


def run_batch_list(args: argparse.Namespace) -> int:
    resolved = library.resolve_paths()
    if resolved.paths is None:
        return no_library(args, resolved)
    paths = resolved.paths
    rows: list[dict] = []
    total = 0
    if paths.db_file.exists():
        with db.connect(paths.db_file) as conn:
            found, total = db.aiff_batches(conn)
        rows = [_batch_dict(r) for r in found]
    say(args, {"ok": True, "batches": rows, "count": total}, [_batch_line(b) for b in rows] or ["No batches yet."])
    return OK


def _unknown_batch(args: argparse.Namespace, paths: Paths, batch_id: int) -> int | None:
    """Exit code 1 (`unknown_batch`) when there is no such batch, else None."""
    if paths.db_file.exists():
        with db.connect(paths.db_file) as conn:
            if db.aiff_batch(conn, batch_id) is not None:
                return None
    return failed(args, f"There is no batch {batch_id}.", "refused", "unknown_batch")


def run_batch_show(args: argparse.Namespace) -> int:
    resolved = library.resolve_paths()
    if resolved.paths is None:
        return no_library(args, resolved)
    paths = resolved.paths
    if (code := _unknown_batch(args, paths, args.batch_id)) is not None:
        return code
    try:
        state = library.load_state(paths)
    except StateError as e:
        return failed(args, str(e))
    result = batches.result_of(paths, args.batch_id)
    with db.connect(paths.db_file) as conn:
        info = _batch_dict(db.aiff_batch(conn, args.batch_id))
    d = {**info, **result.to_dict()}
    say(args, {"ok": True, **d}, [_batch_line(info)] + _batch_lines(state, result.to_dict()))
    return OK


def run_batch_resume(args: argparse.Namespace) -> int:
    def work(paths: Paths, state: dict, recovered: list) -> int:
        if (code := _unknown_batch(args, paths, args.batch_id)) is not None:
            return code
        row = batches.result_of(paths, args.batch_id)
        if row.state != "stopped":
            return failed(args, f"Batch {args.batch_id} is {row.state}, not stopped, so there is nothing to resume.",
                          "refused", "not_stopped", extra=row.to_dict())
        return _finish(args, paths, state, recovered, args.batch_id, lambda token: batches.resume(
            paths, args.batch_id, emit=_progress, token=token, compare=align.compare_files, state=state))
    return _in_library(args, work)


def run_batch_undo(args: argparse.Namespace) -> int:
    def work(paths: Paths, state: dict, recovered: list) -> int:
        if (code := _unknown_batch(args, paths, args.batch_id)) is not None:
            return code
        return _undo(args, paths, state, recovered, args.batch_id)
    return _in_library(args, work)


# --- rekordbox checked / backups / restore ---

def run_checked(args: argparse.Namespace) -> int:
    def work(paths: Paths, state: dict, recovered: list) -> int:
        if args.batch is not None:
            if (code := _unknown_batch(args, paths, args.batch)) is not None:
                return code
            tracks = batches.tracks_of(paths, args.batch)
        else:
            tracks = list(dict.fromkeys(args.tracks))
        before = {t: state["tracks"].get(t) for t in tracks}
        done = [r.track_id for r in batches.checked(paths, tracks, state=state)]
        for t in done:  # operations.log, as the window's "Done, checked in rekordbox"
            ops.log_operation(paths, datetime.now(), t, before[t], "rekordbox_checked", "done", "checked in rekordbox")
        # a batch's tracks checked one by one earlier are not a problem; a key that has nothing to check is
        missing = [] if args.batch is not None else [t for t in tracks if t not in done]
        lines = [f"Checked: {_name(state, t)}" for t in done] + [
            f"Nothing to check: {_name(state, t)}" for t in missing]
        _say(args, {"ok": True, "checked": done, "not_checked": missing}, lines or ["No tracks to check."], recovered)
        return OK if not missing else FAILED
    return _in_library(args, work)


def run_backups(args: argparse.Namespace) -> int:
    resolved = library.resolve_paths()
    if resolved.paths is None:
        return no_library(args, resolved)
    found = rbbackup.backups(resolved.paths)
    rows = [{"id": b.id, "created": b.created, "batches": b.batches, "tracks": b.tracks, "size": b.size}
            for b in found]
    lines = [f"{b['id']}  {convert.size_text(b['size'])}, {b['tracks']} track{'s' if b['tracks'] != 1 else ''}"
             for b in rows]
    say(args, {"ok": True, "backups": rows}, lines or ["No backups yet."])
    return OK


def run_restore(args: argparse.Namespace) -> int:
    if not getattr(args, "yes", False):
        return failed(args, NEEDS_YES, "refused", "needs_yes")

    def work(paths: Paths, state: dict, recovered: list) -> int:
        try:
            done = rbbackup.restore(paths, rekordbox.locate(), args.backup)
        except rbbackup.RestoreRefused as e:
            kind = "rekordbox_open" if e.reason == "rekordbox_open" else "refused"
            return failed(args, RESTORE_WORDS[e.reason], kind, e.reason,
                          code=REKORDBOX_OPEN if kind == "rekordbox_open" else FAILED)
        except batches.Busy as e:
            return failed(args, str(e), "busy", code=BUSY)
        lines = [f"Restored rekordbox's library from {args.backup}. Your library as it was is saved as "
                 f"{done.saved_current}."]
        if done.missing_after:
            lines.append(MISSING_AFTER.format(n=len(done.missing_after)))
        _say(args, {"ok": True, "restored": args.backup, "saved_current": done.saved_current,
                    "missing_after": done.missing_after}, lines, recovered)
        return OK
    return _in_library(args, work)


def run(args: argparse.Namespace) -> int:
    """Dispatches the commands of this module; `cli.main` calls it for `upgrade`, `batch` and `rekordbox checked |
    backups | restore`."""
    if args.command == "upgrade":
        return {"list": run_upgrade_list, "apply": run_upgrade_apply, "discard": run_upgrade_discard,
                "undo": run_upgrade_undo}[args.upgrade_command](args)
    if args.command == "batch":
        return {"list": run_batch_list, "show": run_batch_show, "resume": run_batch_resume,
                "undo": run_batch_undo}[args.batch_command](args)
    return {"checked": run_checked, "backups": run_backups, "restore": run_restore}[args.rekordbox_command](args)
