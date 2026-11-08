"""`discjockey upgrades`: the console front end of upgrades.py. Goes through the parked better versions one by one."""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import align, batches, config, library, report as rep, upgrades
from .events import Result
from .library import Paths, StateError
from .models import SOURCE_NAMES
from .quality import quality_line
from .upgrades import UpgradeProblem

TIP = ("Tip: quit rekordbox first: for a file that isn't AIFF, Discjockey points your rekordbox track at the new "
       "file.")
CHOICES = {"s": "same track", "a": "add as new file", "d": "discard", "f": "show in Finder", "l": "later (default)",
           "q": "quit"}
DONE = {"s": "Replaced", "a": "Added as a new file", "d": "Discarded"}
WHAT = {"s": "replace it", "a": "add it as a new file", "d": "discard it"}


def show_in_finder(path: Path) -> None:
    subprocess.run(["open", "-R", str(path)], check=False)


def _quality(source: str | None, fmt: str | None, status: str, cutoff: int | None, kbps: int | None = None) -> str:
    return quality_line(source, fmt or "?", status, cutoff, kbps) if source else status.replace("_", " ")


def _track_result(section: str, track_id: str, e: dict, note: str) -> Result:
    return Result(section, e["folder"], e["artist"], e["title"], track_id, note)


def _failed(log: rep.RunLog, track_id: str, entry: dict, what: str, err: Exception) -> None:
    """Something nobody expected (a full disk, a name clash): one plain line and an error in the report; the
    next track still comes. A file operation left half-done is finished or undone at the next start."""
    text = f"Could not {what} ({type(err).__name__}: {err})."
    print(f"  ! {text}")
    log.add(_track_result("errors", track_id, entry, text))


def _show(paths: Paths, entry: dict) -> None:
    up = entry["upgrade"]
    now = _quality(entry.get("source"), entry.get("source_format"), entry["status"], entry.get("cutoff_hz"),
                   entry.get("source_kbps"))
    new = _quality(up["source"], up["source_format"], up.get("status", "lossless"), up.get("cutoff_hz"), up.get("kbps"))
    width = max(len(now), len(new)) + 3
    print(f"\n[{entry['folder']}] {entry['artist']} - {entry['title']} · {upgrades.upgrade_name(up)} from "
          f"{SOURCE_NAMES.get(up['source'], up['source'])}")
    print(f"  now:  {now.ljust(width)}{entry.get('path') or '(no file)'}")
    print(f"  new:  {new.ljust(width)}{up['file']}")


def _choices(paths: Paths, state: dict, track_id: str, entry: dict, compare) -> str:
    """Measures the alignment afresh and says what it means. Returns the letters the user may type."""
    if not upgrades.current_on_disk(paths, entry):
        print("  Your current file is not where Discjockey expects it. Run a sync first, so it can find the file "
              "again.")
        return "dflq"
    print("  Comparing the two versions...", end="", flush=True)
    alignment = upgrades.check(paths, state, track_id, compare)
    if alignment.swap_safe and upgrades.swap_possible(entry):
        print(f" {alignment.text}. Same track keeps your cue points.")
        return "sadflq"
    if alignment.swap_safe:
        print(f" {alignment.text}. Same track keeps your cue points: the better audio becomes a new AIFF file and "
              "your rekordbox track is pointed at it.")
        return "sadflq"
    print(f" {alignment.text}. Add it as a new file, or discard it.")
    return "adflq"


def _same_track(paths: Paths, state: dict, track_id: str, compare, now: Callable[[], datetime]) -> Result:
    """Same track as a batch of one (batches.run: the same session, backup and journal as a bigger batch)."""
    batch = batches.start(paths, [(track_id, "same_track")], now=now)
    try:
        outcome = batches.run(paths, batch, compare=compare, now=now, state=state)
    except batches.Refused as err:
        raise UpgradeProblem(str(err)) from None
    except (batches.RekordboxOpen, batches.Busy) as err:  # nothing ran: no resumable batch of one is left
        batches.close_unrun(paths, batch, "busy" if isinstance(err, batches.Busy) else "rekordbox_open", str(err),
                            now=now)
        raise UpgradeProblem(str(err)) from None
    item = outcome.results[0]
    if item.state != "done":
        raise UpgradeProblem(item.message or "Nothing was changed.")
    e = state["tracks"][track_id]
    return Result("swapped", e["folder"], e["artist"], e["title"], track_id, item.message or "",
                  status=e["status"], source=e["source"], path=e["path"])


def _review(paths: Paths, state: dict, track_id: str, log: rep.RunLog, ask: Callable[[str], str],
            opener: Callable[[Path], None], compare, now: Callable[[], datetime]) -> bool:
    """One parked upgrade. Returns False when the user wants to quit."""
    entry = state["tracks"][track_id]
    up = entry["upgrade"]
    _show(paths, entry)
    try:
        upgrades.precondition(paths, state, track_id, up, need_current=False)
        offer = _choices(paths, state, track_id, entry, compare)
    except UpgradeProblem as p:
        print(f"\n  {p}" if p.forgotten else f"  {p}")
        log.add(_track_result("discarded" if p.forgotten else "errors", track_id, entry, str(p)))
        return True
    except Exception as err:
        print()
        _failed(log, track_id, entry, "compare the two versions", err)
        return True
    while True:
        print("  " + "  ".join(f"[{k}] {CHOICES[k]}" for k in offer))
        answer = ask("  > ").strip().lower() or "l"
        if answer not in offer:
            print(f"  Please type one of: {', '.join(offer)}.")
            continue
        if answer == "f":
            opener(paths.root / up["file"])
            continue
        if answer in "lq":
            return answer == "l"
        try:
            with library.deferred_interrupt():  # a Ctrl-C waits until the step is done and in the report
                if answer == "s":
                    result = _same_track(paths, state, track_id, compare, now)
                elif answer == "a":
                    result = upgrades.add_new(paths, state, track_id, up, compare, now=now)
                else:
                    result = upgrades.discard(paths, state, track_id, up)
                log.add(result)
        except UpgradeProblem as p:
            print(f"  ! {p}")
            log.add(_track_result("discarded" if p.forgotten else "errors", track_id, entry, str(p)))
            return True
        except Exception as err:
            _failed(log, track_id, entry, WHAT[answer], err)
            return True
        print(f"  {DONE[answer]}." + (f" ({result.note})" if answer != "d" else ""))
        check = state["tracks"][track_id].get("rekordbox_check")
        if answer != "d" and check:  # the same words as the To-do's "Check in rekordbox", from the measurement
            print(f"  {rep.check_text(check)}")
        return True


def run_upgrades(paths: Paths, *, ask: Callable[[str], str] | None = None,
                 opener: Callable[[Path], None] = show_in_finder,
                 compare=align.compare_files, now: Callable[[], datetime] = datetime.now) -> int:
    """Expects the run lock to be held. Exit code 0, 1 (a step failed), 2 (state unreadable) or 130 (Ctrl-C).
    `ask` defaults to input(), looked up when called."""
    ask = ask or input
    try:
        state = library.open_state(paths)
    except StateError as e:
        print(e)
        return 2
    try:
        order = [line.folder for line in config.load_playlists(paths.playlists_file)]
    except config.ConfigError:
        order = []  # works offline and without playlists.txt; folders then follow their names
    log = rep.RunLog(now())
    code = 0
    try:
        for message, ok in library.recover_pending(paths, state):
            log.add_text("recovered" if ok else "errors", message)
            print(message)
        library.clear_tmp(paths, state)
        items = upgrades.ready(state, order)
        if not items:
            print("No better versions are waiting.")
        else:
            print(TIP)
            for track_id, _ in items:
                if not _review(paths, state, track_id, log, ask, opener, compare, now):
                    break
    except KeyboardInterrupt:
        print("\nStopped. Everything finished so far is saved.")
        code = 130
    finally:
        if code == 0 and log.section("errors"):
            code = 1
        if not log.is_empty():  # something changed: report and not_lossless.md, also after a Ctrl-C
            rep.write_not_lossless(paths, state)
            print(rep.summary(log, rep.write_run(paths, log, now(), code, state)))
    return code
