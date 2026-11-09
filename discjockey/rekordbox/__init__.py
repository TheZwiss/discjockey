"""rekordbox's side of Discjockey (issue 33; design `docs/2026-11-07-rekordbox-repoint-design.md`).

Finds rekordbox's library on this Mac (`locate`), opens its encrypted `master.db` and checks it (`master`: the key,
the guards, finding the tracks that hold a file), and tells whether rekordbox runs (`process`). It reads rekordbox's
analysis files (`anlz`) and measures where rekordbox's timeline sits for a file (`timing`, pure; `probe`, the ffmpeg
side; `offset.timeline_offset`, one answer per file). `eligible` (pure) says per track what Same track, Convert and
Rename can do and why not, and `preview` is the read-only answer the `rekordbox preview` command prints (import them
from their modules: `preview` pulls in `upgrades`, which imports this package). Each module's docstring says what it
owns.

**Reads, and in stage B writes:** `master` only reads (every open is read-only and leaves no file beside the
library); the write is its own module, `write` (`open_write`, the `Writer`: a track pointed at a new file, its text
columns, the way back), with `anlz.splice_ppth` for the analysis files. `backup` keeps a copy of the library per batch
(and restores one), `session` is a batch's rekordbox side (`rekordbox.lock`, the start check, one read open and
index, the backup before the first write).

The format knowledge (the key, the tables and columns, the analysis files) follows what pyrekordbox (MIT) and
rekordbox-edit publish; credit to both. No code is copied from either.
"""
from __future__ import annotations

from .locate import Place, locate
from .master import KEYS, Entry, Master, PathIndex, RekordboxView, Status, Unreadable, open_read, status
from .offset import EntryTiming, TimelineOffset, timeline_offset
from .session import Busy, RekordboxOpen, Session
from .write import RekordboxOpened, WriteRefused, Writer, open_write

__all__ = ["KEYS", "Busy", "Entry", "EntryTiming", "Master", "PathIndex", "Place", "RekordboxOpen", "RekordboxOpened",
           "RekordboxView", "Session", "Status", "WriteRefused", "Writer", "open_write",
           "TimelineOffset", "Unreadable", "locate", "open_read", "status", "timeline_offset"]
