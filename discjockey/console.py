"""The console front end: turns core events into terminal lines."""
from __future__ import annotations

import sys
from collections.abc import Callable

from .auto_upgrade import before_start_line
from .events import ActionFinished, ActionStarted, BatchProgress, Message, Progress, StepChanged, Waiting
from .report import folder_label

VERBS = {"adopt_bought": "Adding bought file", "acquire": "Downloading", "upgrade": "Looking for a better version"}
STEP_TEXT = {"search": "searching", "download": "downloading", "check": "checking length",
             "convert": "converting", "analyse": "analysing", "compare": "comparing with your file"}
SHORT = {"new_lossless": "lossless", "new_not_lossless": "not lossless", "fake": "fake lossless",
         "upgrade_ready": "better version found, waiting for you", "checked": "no better version yet",
         "bought": "bought file added",
         "redownloaded": "downloaded again", "missing": "not found",
         "queued": "waiting for the next run", "errors": "error"}


# what only the window does (plan library stage 4, D13, W10): the console never imports nor asks
IMPORT_WAITING = ("{n} files in your watched folders wait to be imported. Open the window to import them.",
                  "1 file in your watched folders waits to be imported. Open the window to import it.")
QUESTIONS_WAITING = ("{n} songs wait for your answer in the window (Is this the same song?).",
                     "1 song waits for your answer in the window (Is this the same song?).")


def waiting_lines(import_waiting: int, questions: int) -> list[str]:
    """The console's lines for files waiting to be imported and songs held for "Is this the same song?" (run.Prepared
    has both counts); none at 0."""
    lines = []
    for n, (many, one) in ((import_waiting, IMPORT_WAITING), (questions, QUESTIONS_WAITING)):
        if n > 0:
            lines.append(one if n == 1 else many.format(n=n))
    return lines


# Auto-upgrade in the printed plan (plan stage C §2, §3): what the sync's last phase will do
UPGRADE_PLAN = ("At the end, {n} upgrades go in place of your files; your cues stay.",
                "At the end, 1 upgrade goes in place of your files; your cues stay.")
UPGRADE_HOW = {"in_place": "in place", "new_aiff": "new AIFF"}
UPGRADE_HELD = "Not tried this sync (refused before, and nothing changed since):"


def upgrade_lines(block: dict | None, name_of: Callable[[str], str], *, full: bool) -> list[str]:
    """The console's Auto-upgrade lines for the plan, from the dry-run block (`auto_upgrade.run_phase(...,
    dry_run=True).to_dict()`, None with the switch off): how many upgrades go in at the end, the Sync page's
    before-start line when rekordbox is open, and with `full` (the dry run) each upgrade with its way and the held
    refusals with their reason. `name_of(song key)` is "Artist - Title". None or nothing to do: no lines."""
    rows = (block or {}).get("results") or []
    coming = [r for r in rows if r["state"] in ("would", "waiting")]
    held = [r for r in rows if r["state"] == "refused"]
    lines: list[str] = []
    if coming:
        n = len(coming)
        lines.append(UPGRADE_PLAN[1] if n == 1 else UPGRADE_PLAN[0].format(n=n))
        if any(r["state"] == "waiting" and r["reason"] == "rekordbox_open" for r in coming):
            lines.append(before_start_line(n))
        if full:
            lines += [f"  {name_of(r['track'])} ({UPGRADE_HOW.get(r['how'], r['how'])})" for r in coming]
    if full and held:
        lines.append(UPGRADE_HELD)
        lines += [f"  {name_of(r['track'])}: {r['message']}" for r in held]
    return lines


def _size(n: float) -> str:
    return f"{n / 1_000_000:.1f} MB"


class ConsolePrinter:
    """Call it with every event. Progress and pauses share one line that is overwritten in place."""

    def __init__(self, verbose: bool = False, out=None):
        self.verbose, self._out = verbose, out  # None: whatever sys.stdout is at the time of writing
        self.status_len = 0
        self.header = ""  # the "[3/12] Downloading ..." line, printed once the track shows any work
        self.waiting_notes: set[str] = set()  # reasons already announced for tracks that only wait

    @property
    def out(self):
        return self._out or sys.stdout

    def _status(self, text: str) -> None:
        pad = max(0, self.status_len - len(text))
        self.out.write("\r" + text + " " * pad)
        self.out.flush()
        self.status_len = len(text)

    def _clear(self) -> None:
        if self.status_len:
            self.out.write("\r" + " " * self.status_len + "\r")
            self.status_len = 0

    def _line(self, text: str) -> None:
        self._clear()
        self.out.write(text + "\n")
        self.out.flush()

    def _show_header(self) -> None:
        if self.header:
            header, self.header = self.header, ""
            self._line(header)

    def __call__(self, event: object) -> None:
        if isinstance(event, ActionStarted):
            a = event.action
            self.header = (f"[{event.index}/{event.total}] {VERBS[a.kind]} [{folder_label(a.folder)}] "
                           f"{a.track.first_artist} - {a.track.title}")
        elif isinstance(event, ActionFinished) and event.result.section == "queued" and self.header:
            # nothing was tried for this track (e.g. --limit reached): one line for all of them, not one each
            self.header = ""
            if event.result.note not in self.waiting_notes:
                self.waiting_notes.add(event.result.note)
                self._line(f"  Further downloads wait for the next run ({event.result.note}).")
        elif isinstance(event, (StepChanged, Progress, ActionFinished)) or (
                isinstance(event, Waiting) and event.remaining > 0):
            self._show_header()
            self._show_progress(event)
        elif isinstance(event, Waiting):
            self._clear()
        elif isinstance(event, BatchProgress):  # the sync's Auto-upgrade phase: one line per track
            if event.track_id:
                self._line(f"Upgrading {event.done + 1} of {event.total}: {event.name}")
        elif isinstance(event, Message):
            if event.level == "info":
                self._line(event.text)
            elif event.level == "warning":
                self._line(f"  ! {event.text}")
            elif self.verbose:
                self._show_header()
                self._line(f"    {event.text}")

    def _show_progress(self, event: object) -> None:
        if isinstance(event, StepChanged):
            self._status(f"    {STEP_TEXT.get(event.step, event.step)}...")
        elif isinstance(event, Progress):
            if event.unit == "bytes":
                total = f" of {_size(event.total)}" if event.total else ""
                self._status(f"    {STEP_TEXT.get(event.step, event.step)} {_size(event.done)}{total}")
            else:
                total = f" of {event.total:.0f} s" if event.total else ""
                self._status(f"    {STEP_TEXT.get(event.step, event.step)} {event.done:.0f} s{total}")
        elif isinstance(event, Waiting):
            self._status(f"    {event.label}: {event.remaining:.0f} s")
        elif isinstance(event, ActionFinished):
            r = event.result
            note = f" ({r.note})" if r.note and r.section in ("errors", "queued", "fake",
                                                                 "new_not_lossless", "new_lossless",
                                                                 "upgrade_ready") else ""
            self._line(f"    -> {SHORT.get(r.section, r.section)}{note}")
