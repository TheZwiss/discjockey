"""What every playlist source shares: its error, its login check and the reader it hands out."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models import FetchedPlaylist, PlaylistInfo, PlaylistLine


class SourceError(Exception):
    """A problem with a playlist service that the user has to fix; the run stops with exit code 2.

    kind (for the hub's cards): not_set_up | login_expired | offline | playlist_unreadable | login_failed |
    qobuz_login_failed. `service` names the service the problem is with (a key of models.SERVICE_NAMES), or None."""

    def __init__(self, message: str, kind: str = "offline", service: str | None = None):
        super().__init__(message)
        self.kind = kind
        self.service = service


@dataclass(frozen=True)
class LoginState:
    """The answer of a source's local login check (never a network call): `ok` or `missing`, and the words to
    show when it is missing."""
    state: str  # "ok" | "missing"
    message: str = ""


class Reader(Protocol):
    """A logged-in session of one service, opened once per read. A context manager: `close()` runs on exit."""

    def __enter__(self) -> "Reader": ...

    def __exit__(self, *exc) -> None: ...

    def close(self) -> None: ...

    # Set before `fetch` by a reader of the hub: fill `FetchedPlaylist.info` too when the tracks' own answer holds the
    # playlist's name, owner and cover (Qobuz), so the page needs no second login. A source that can't may ignore it.
    want_info: bool

    def fetch(self, line: PlaylistLine) -> FetchedPlaylist: ...

    def info(self, playlist_id: str) -> PlaylistInfo: ...
