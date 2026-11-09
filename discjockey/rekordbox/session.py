"""The rekordbox side of one batch (design rekordbox-repoint §5.3 guard 6, §5.6, §5.7; plan stage B §0.3, §0.7, §1.6).

`Session.open(paths, items_need_write=…)` is a context manager around a whole batch (and its undo):
1. takes `<support>/rekordbox.lock` (`lock.writer_lock`: flock, non-blocking) for its whole life, else `Busy`
   (another Discjockey window
   or the Terminal is changing rekordbox's library);
2. asks once whether rekordbox runs, opens the library once for reading (`master.open_read`: immutable while
   rekordbox is closed) and builds the path index; `state` is the library's `Status` (`none` and `unreadable` are
   answers, not errors: the items decide);
3. if rekordbox runs and `items_need_write(view)` says some item needs a rekordbox write, raises `RekordboxOpen`
   before anything changed. `view` is None when the library couldn't be read while rekordbox runs: the callback then
   answers as if every item that isn't an AIFF needed one.

`view()` hands out the open library, its index and status for `offset.timeline_offset(view=…)`. `writer(tracks)`
closes the read connection (two connections to one file never overlap: the read one is immutable), ensures the
batch's backup holds `tracks`' analysis folders (`ensure_backup`; made before the first write) and yields
`write.open_write`'s `Writer`. A `view()` after a write opens the library again with a fresh index (the paths
changed). `rekordbox_opened()` tells a batch started with rekordbox closed that it has opened since (it then stops,
plan §0.7). On leaving, the read connection closes and the backup's manifest records the library's hash
(`Backup.close`), so the next batch can reuse it.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from . import master, process
from .backup import Backup
from .lock import BUSY, Busy, writer_lock
from .locate import Place, locate
from .master import RekordboxView, Status, Unreadable
from .write import WriteRefused, Writer, open_write

__all__ = ["BUSY", "Busy", "RekordboxOpen", "RekordboxView", "Session", "writer_lock"]

_LOCATE = object()


class RekordboxOpen(Exception):
    """rekordbox runs and an item of the batch needs a rekordbox write: nothing was changed."""


class Session:
    """One batch's rekordbox: use `Session.open`."""

    def __init__(self, paths, place: Place | None, running: Callable[[], bool], batch_id: int | None):
        self.paths = paths
        self.place = place
        self._running = running
        self.batch_id = batch_id
        self.running_at_start = False
        self.state: Status = Status("none", False, None, None, None, None, None)
        self.dbid: str | None = None
        self.backup: Backup | None = None
        self.opens = 0          # keyed read opens so far (tests pin one per session without writes)
        self._read: ExitStack | None = None
        self._view: RekordboxView | None = None
        self._unreadable = False

    @classmethod
    @contextmanager
    def open(cls, paths, *, place=_LOCATE, running: Callable[[], bool] | None = None,
             items_need_write: Callable[[RekordboxView | None], bool], batch_id: int | None = None
             ) -> Iterator[Session]:
        place = locate() if place is _LOCATE else place
        running = process.running if running is None else running  # looked up now: tests replace it
        with writer_lock(paths.support):
            s = cls(paths, place, running, batch_id)
            try:
                s._start(items_need_write)
                yield s
            finally:
                s._close_read()
                if s.backup is not None and s.place is not None:
                    s.backup.close(s.place, batch_id=batch_id)

    def _start(self, items_need_write: Callable[[RekordboxView | None], bool]) -> None:
        self.running_at_start = is_running = self._running()
        if self.place is None or not self.place.db.is_file():
            self.state = Status("none", is_running, None, None, None, None, None)
            return
        self._open_read()
        if is_running and items_need_write(self._view):
            self._close_read()
            raise RekordboxOpen()

    def _open_read(self) -> None:
        assert self.place is not None
        is_running = self._running()
        stack = ExitStack()
        try:
            m = stack.enter_context(master.open_read(self.place, is_running))
            self.opens += 1
            self.state = master.status_of(m, is_running)
            self.dbid = m.dbid
            self._view = RekordboxView(m, m.index(), self.state)
            self._read = stack
        except Unreadable as e:
            stack.close()
            self.opens += 1
            state = "ready" if e.problem == "busy" else "unreadable"
            self.state = Status(state, is_running, self.place.app_version, str(self.place.db), e.problem,
                                e.db_version, e.dbid)
            self.dbid = e.dbid
            self._view = None
            self._unreadable = True
        except BaseException:
            stack.close()
            raise

    def _close_read(self) -> None:
        if self._read is not None:
            self._read.close()
        self._read = None
        self._view = None

    def view(self) -> RekordboxView | None:
        """The open library, its index and status; None without a readable library. Opens it again after a write."""
        if self._view is None and self._read is None and not self._unreadable and self.state.state == "ready":
            self._open_read()
        return self._view

    def rekordbox_opened(self) -> bool:
        """Whether rekordbox runs now although it was closed when the batch started."""
        return not self.running_at_start and self._running()

    def ensure_backup(self, tracks: Iterable[tuple[str, list[Path]]]) -> Backup:
        """The batch's backup, made before its first rekordbox write, with `tracks`' analysis folders in it."""
        if self.place is None or self.state.state != "ready":
            raise WriteRefused("rekordbox_unreadable")
        if self._running():
            raise WriteRefused("rekordbox_open")
        tracks = list(tracks)
        if self.backup is None:
            self.backup = Backup.ensure(self.paths, self.place, dbid=self.dbid, batch_id=self.batch_id,
                                        tracks=tracks, db_version=self.state.db_version)
        elif tracks:
            self.backup.add_tracks(self.place, self.batch_id, tracks)
        return self.backup

    @contextmanager
    def writer(self, tracks: Iterable[tuple[str, list[Path]]] = ()) -> Iterator[Writer]:
        """`write.open_write` on this batch's library, after the read connection closed and the backup holds
        `tracks`. Raises `WriteRefused` (nothing written)."""
        if self.place is None or self.state.state != "ready":
            raise WriteRefused("rekordbox_unreadable")
        self._close_read()
        self.ensure_backup(tracks)
        with open_write(self.place, dbid=self.dbid, running=self._running) as w:
            yield w
