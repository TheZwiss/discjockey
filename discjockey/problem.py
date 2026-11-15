"""What every problem the engine raises carries besides its message (issue 39, design §4.3): the `reason` (one key of
`hub.outcomes.REASONS`), the commands that move on (`next`: `{"run", "why"}`), the steps only a person can do
(`person_steps`: `{"id", "say", "then"}`) and `data` (what else the answer should say, such as the holder of a lock).
`OpProblem`, `jobs.Busy`, `rekordbox.lock.Busy` and `library.LockHeld` all stand on it; the bridge and the command
line read the four fields off whatever was raised (absent on any other exception)."""
from __future__ import annotations

from collections.abc import Iterable, Mapping


class Problem(Exception):
    """An exception with a message for the user and the four answer fields; the fields default to "none"."""

    reason: str | None
    next: list[dict]
    person_steps: list[dict]
    data: Mapping | None

    def __init__(self, message: str = "", *, reason: str | None = None, next: Iterable[Mapping] = (),
                 person_steps: Iterable[Mapping] = (), data: Mapping | None = None):
        super().__init__(message)
        self.reason = reason
        self.next = [dict(n) for n in next]
        self.person_steps = [dict(s) for s in person_steps]
        self.data = data
