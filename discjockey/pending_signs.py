"""Warning signs that are met where the library lock is not ours and so cannot be written into library.db yet.

A Liked music read made outside a sync (a pasted link, the change preview) can meet YouTube's bot check while a sync,
a scan or a terminal run holds the lock. The sign then waits in `.discjockey/pending_signs.json` (a small file written
whole or not at all, like the other small files beside library.db) until some caller holds the lock: the next job, the
next start, the next paste or preview, a terminal run (`run.record_pending`). Until then the sign already counts for
the pause (`paused`), so no read asks the account again meanwhile. Best-effort like the other side records: a file that
can't be read or written is logged and treated as empty."""
from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime
from typing import Iterable

from .library import Paths, write_json_atomic
from .pacing import PAUSE_SIGNALS

logger = logging.getLogger(__name__)

_MUTEX = threading.Lock()  # this process's threads (the window's calls, the jobs); a terminal run only reads and removes


def _read(paths: Paths) -> list[dict]:
    try:
        data = json.loads(paths.pending_signs.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        logger.warning("couldn't read the waiting warning signs", exc_info=True)
        return []
    return [s for s in data if isinstance(s, dict) and {"service", "kind", "message", "time"} <= s.keys()] \
        if isinstance(data, list) else []


def _write(paths: Paths, signs: list[dict]) -> None:
    if signs:
        write_json_atomic(paths.pending_signs, signs, ensure_ascii=False)
    else:
        paths.pending_signs.unlink(missing_ok=True)


def load(paths: Paths) -> list[dict]:
    """The waiting signs, oldest first: dicts with service, kind, message and time (ISO, when it was met)."""
    with _MUTEX:
        return _read(paths)


def add(paths: Paths, signs: Iterable[tuple[str, str, str]], now: datetime) -> None:
    """Keeps `signs` ((account service, kind, message), as `on_signal` gives them) until they are recorded. Needs no
    library lock; the file is made on the spot, so a sign survives the app closing."""
    new = [{"service": s, "kind": k, "message": m, "time": now.isoformat(timespec="seconds")} for s, k, m in signs]
    if not new:
        return
    with _MUTEX:
        try:
            _write(paths, _read(paths) + new)
        except OSError:
            logger.warning("couldn't keep a warning sign for later", exc_info=True)


def remove(paths: Paths, taken: list[dict]) -> None:
    """Drops signs that were recorded (one waiting sign for each of `taken`); ones added meanwhile stay."""
    with _MUTEX:
        rest = _read(paths)
        for sign in taken:
            if sign in rest:
                rest.remove(sign)
        try:
            _write(paths, rest)
        except OSError:
            logger.warning("couldn't clear the recorded warning signs", exc_info=True)


def paused(paths: Paths, today: date) -> frozenset[str]:
    """The account services a waiting pause sign (pacing.PAUSE_SIGNALS) put on hold today. Pure but for the file."""
    day = today.isoformat()
    return frozenset(s["service"] for s in load(paths)
                     if s["kind"] in PAUSE_SIGNALS and str(s["time"])[:10] == day)
