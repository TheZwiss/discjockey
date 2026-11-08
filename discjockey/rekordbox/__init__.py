"""rekordbox's side of Discjockey (issue 33; design `docs/2026-11-07-rekordbox-repoint-design.md`).

Finds rekordbox's library on this Mac (`locate`), opens its encrypted `master.db` and checks it (`master`: the key,
the guards, finding the tracks that hold a file), and tells whether rekordbox runs (`process`). It reads rekordbox's
analysis files (`anlz`) and measures where rekordbox's timeline sits for a file (`timing`, pure; `probe`, the ffmpeg
side; `offset.timeline_offset`, one answer per file). `eligible` (pure) says per track what Same track, Convert and
Rename can do and why not, and `preview` is the read-only answer the `rekordbox preview` command prints (import them
from their modules: `preview` pulls in `upgrades`, which imports this package). Each module's docstring says what it
owns.

**Read only in stage A:** nothing here writes `master.db` or an analysis file; every open is read-only and leaves no
file beside the library. Stage B adds the write beside the read (`master.open_write`), never in place of it.

The format knowledge (the key, the tables and columns, the analysis files) follows what pyrekordbox (MIT) and
rekordbox-edit publish; credit to both. No code is copied from either.
"""
from __future__ import annotations

from .locate import Place, locate
from .master import KEYS, Entry, Master, PathIndex, RekordboxView, Status, Unreadable, open_read, status
from .offset import EntryTiming, TimelineOffset, timeline_offset

__all__ = ["KEYS", "Entry", "EntryTiming", "Master", "PathIndex", "Place", "RekordboxView", "Status",
           "TimelineOffset", "Unreadable", "locate", "open_read", "status", "timeline_offset"]
