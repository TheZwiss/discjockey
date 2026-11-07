"""rekordbox's side of Discjockey (issue 33; design `docs/2026-11-07-rekordbox-repoint-design.md`).

Finds rekordbox's library on this Mac (`locate`), opens its encrypted `master.db` and checks it (`master`: the key,
the guards, finding the tracks that hold a file), and tells whether rekordbox runs (`process`). Each module's
docstring says what it owns.

**Read only in stage A:** nothing here writes `master.db` or an analysis file; every open is read-only and leaves no
file beside the library. Stage B adds the write beside the read (`master.open_write`), never in place of it.

The format knowledge (the key, the tables and columns, the analysis files) follows what pyrekordbox (MIT) and
rekordbox-edit publish; credit to both. No code is copied from either.
"""
from __future__ import annotations

from .locate import Place, locate
from .master import KEYS, Entry, Master, Status, Unreadable, open_read, status

__all__ = ["KEYS", "Entry", "Master", "Place", "Status", "Unreadable", "locate", "open_read", "status"]
