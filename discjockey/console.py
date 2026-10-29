"""The console front end: turns core events into terminal lines."""
from __future__ import annotations

import sys

from .events import ActionFinished, ActionStarted, Message, Progress, StepChanged, Waiting
from .report import folder_label

VERBS = {"adopt_bought": "Adding bought file", "acquire": "Downloading", "upgrade": "Looking for a better version"}
STEP_TEXT = {"search": "searching", "download": "downloading", "check": "checking length",
             "convert": "converting", "analyse": "analysing", "compare": "comparing with your file"}
SHORT = {"new_lossless": "lossless", "new_not_lossless": "not lossless", "fake": "fake lossless",
         "upgrade_ready": "better version found, waiting for you", "checked": "no better version yet",
         "bought": "bought file added",
         "moved": "moved", "adopted": "picked up", "redownloaded": "downloaded again", "missing": "not found",
         "queued": "waiting for the next run", "conflicts": "not moved, a file is in the way", "errors": "error"}


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
            note = f" ({r.note})" if r.note and r.section in ("errors", "queued", "conflicts", "fake",
                                                                 "new_not_lossless", "new_lossless",
                                                                 "upgrade_ready") else ""
            self._line(f"    -> {SHORT.get(r.section, r.section)}{note}")
