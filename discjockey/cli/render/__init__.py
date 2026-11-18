"""The command line's text pages (issue 39, design §4.2): `layout.py` is the page framework, `generic.py` prints any
payload as a page, and hand pages (library, to-do, sync, track, verdict and spectrum, runs) join it in later groups.
`page_for(command)` is the printer of a command: its hand page when it has one, else the generic one."""
from __future__ import annotations

from collections.abc import Callable

from . import generic, report, todo, track

HAND_PAGES: dict[str, Callable] = {"todo list": todo.page, "upgrade list": todo.page, "check list": todo.page,
                                   "missing list": todo.page,
                                   "track show": track.page, "report show": report.page}


def page_for(command: str | None) -> Callable:
    """The function that makes the page of `command` (an envelope's `command`): `page(payload, *, message, verbose,
    limit, offset)`."""
    return HAND_PAGES.get(command or "", generic.page)
