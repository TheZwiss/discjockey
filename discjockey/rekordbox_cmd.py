"""`discjockey rekordbox status` and `discjockey rekordbox preview`: what rekordbox's library is like and what
Same track, Convert and Rename would do for one file (plan rekordbox stage A §2; design rekordbox-repoint §10).

Both are read-only and take no library lock (they don't change Discjockey's records either). `status` needs no music
folder. Exit codes: 0 the command answered (a library that isn't there, or can't be opened, is an answer), 1 it
refused or failed (an unknown track, a missing file, a file ffmpeg can't read), 2 there is no music folder to look a
track up in. `--json` prints one object: `{"ok": true, …}`, or `{"ok": false, "kind", "message"}` with a `reason` for
a refusal.
"""
from __future__ import annotations

import argparse
import json

from . import library, rekordbox
from .library import StateError
from .rekordbox import preview as previewing
from .rekordbox.eligible import ACTIONS

ACTION_NAMES = {"same_track": "Same track", "convert": "Convert to AIFF", "rename": "Give it its clean name"}
TIMING_WORDS = {
    "no_rekordbox": "no rekordbox library on this Mac, so nothing to line up with",
    "not_in_rekordbox": "not in your rekordbox collection",
    "format": "this format has no delay",
    "no_cues": "no cues or beat grid in rekordbox to keep in place",
    "measured": "measured",
    "not_analysed": "rekordbox hasn't analysed it yet",
    "timing": "couldn't be measured exactly",
    "unreadable": "rekordbox's library can't be read",
}
FIELD_WORDS = {"title": "title", "artist": "artist", "album": "album", "label": "label", "isrc": "ISRC",
               "comment": "comment"}


def _say(args: argparse.Namespace, data: dict, lines: list[str]) -> None:
    if args.json:
        print(json.dumps(data))
    else:
        print("\n".join(lines))


def _failed(args: argparse.Namespace, message: str, kind: str = "failed", reason: str | None = None,
            code: int = 1) -> int:
    data = {"ok": False, "kind": kind, "message": message}
    if reason:
        data["reason"] = reason
    _say(args, data, [message])
    return code


# --- status ---

def status_lines(st: rekordbox.Status) -> list[str]:
    if st.state == "none":
        return ["No rekordbox library on this Mac."]
    if st.state == "unreadable":
        return ["Discjockey can't open this rekordbox version's library yet."]
    lines = [f"rekordbox library found: {st.library}"]
    lines.append(f"rekordbox {st.version} is open." if st.running and st.version else
                 "rekordbox is open." if st.running else "rekordbox is closed.")
    if st.problem == "unclean":
        lines.append("rekordbox didn't close normally last time. Open rekordbox and quit it before Discjockey "
                     "changes anything there.")
    elif st.problem == "busy":
        lines.append("rekordbox is holding its library right now, so Discjockey can't read it until rekordbox is "
                     "closed.")
    return lines


def run_status(args: argparse.Namespace) -> int:
    try:
        st = rekordbox.status(rekordbox.locate())
    except Exception as e:  # an unexpected failure is the one thing that is not an answer
        return _failed(args, f"Discjockey couldn't look at rekordbox ({type(e).__name__}: {e}).")
    data = {"ok": True, "state": st.state, "running": st.running, "version": st.version, "library": st.library,
            "problem": st.problem, "db_version": st.db_version}
    _say(args, data, status_lines(st))
    return 0


# --- preview ---

def _ms(value: float | None) -> str:
    return "?" if value is None else f"{value:.1f} ms"


def preview_lines(p: dict) -> list[str]:
    rb = p["rekordbox"]
    lines = [f"File: {p['file']}"]
    bits = f", {p['bits']}-bit" if p["bits"] else ""
    lines.append(f"Format: {p['codec']}, {p['sample_rate'] / 1000:g} kHz{bits}")
    rb_state = {"none": "no library on this Mac", "unreadable": "library can't be opened",
                "ready": "library found"}[rb["state"]]
    lines.append(f"rekordbox: {rb_state}" + (", open" if rb["running"] else ", closed") + (
        " (didn't close normally last time)" if rb["problem"] == "unclean" else ""))
    t = p["timing"]
    samples = "" if t["offset_samples"] is None else f" ({t['offset_samples']} samples)"
    lines.append(f"Timing: {TIMING_WORDS[t['result']]}{samples}")
    for e in p["entries"]:
        bits = [f"{e['cues']} cue{'s' if e['cues'] != 1 else ''}", "beat grid" if e["grid"] else "no beat grid"]
        if e["offset_ms"] is not None:
            bits.append(f"offset {_ms(e['offset_ms'])}, expected {_ms(e['expected_ms'])}, score {e['score']:.2f}")
        elif e["pwv3"]:
            bits.append("waveform not measured")
        if e["cloud"]:
            bits.append("in Cloud Library Sync")
        if e["fields_kept"]:
            bits.append("keeps your own " + ", ".join(FIELD_WORDS[f] for f in e["fields_kept"]))
        lines.append(f"  rekordbox track {e['id']}: " + "; ".join(bits))
    for action in ACTIONS:
        reason = p["eligible"][action]
        lines.append(f"{ACTION_NAMES[action]}: " + ("possible" if reason is None else
                                                    f"not now ({previewing.REASON_WORDS[reason]})"))
    if p["new_file"]:
        lines.append(f"New file: {p['new_file']}")
    if p["superseded"]:
        lines.append(f"The old file would go to: {p['superseded']}")
    return lines


def run_preview(args: argparse.Namespace) -> int:
    resolved = library.resolve_paths()
    if args.track and resolved.paths is None:
        message = (f"Your music folder isn't there: {resolved.music_folder}" if resolved.problem == "missing" else
                   "Discjockey doesn't know your music folder yet. Open the Discjockey window and follow Setup, "
                   "or run: discjockey setup")
        return _failed(args, message, "refused", "no_library", code=2)
    try:
        p = previewing.preview(resolved.paths, track=args.track, path=args.path)
    except previewing.PreviewRefused as e:
        return _failed(args, str(e), "refused", e.reason)
    except (previewing.PreviewFailed, StateError) as e:
        return _failed(args, str(e))
    except Exception as e:
        return _failed(args, f"Discjockey couldn't preview this file ({type(e).__name__}: {e}).")
    _say(args, p, preview_lines(p))
    return 0


def run(args: argparse.Namespace) -> int:
    return run_status(args) if args.rekordbox_command == "status" else run_preview(args)
