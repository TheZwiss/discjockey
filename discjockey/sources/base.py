"""What every playlist source shares: its error, its login check and the reader it hands out."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from ..models import FetchedPlaylist, PlaylistInfo, PlaylistLine


class SourceError(Exception):
    """A problem with a playlist service that the user has to fix; the run stops with exit code 2.

    kind (for the hub's cards): not_set_up | login_expired | offline | playlist_unreadable | login_failed |
    qobuz_login_failed | setting_off (the playlist needs a choice in Settings that is off; `setting` names it). `service` names the service the problem is with (a key of models.SERVICE_NAMES), or None."""

    def __init__(self, message: str, kind: str = "offline", service: str | None = None, setting: str | None = None):
        super().__init__(message)
        self.kind = kind
        self.service = service
        self.setting = setting  # kind setting_off: the Settings choice (a key of settings.json) that is off


class LineSkipped(SourceError):
    """A line that was not read this time and that is no problem with the playlist or the service's login (the Liked
    music read met YouTube's bot check): `sources.read` goes on with the other lines and the line's files stay. Any
    other caller sees an ordinary SourceError (kind `offline`)."""


@dataclass(frozen=True)
class LoginState:
    """The answer of a source's local login check (never a network call): `ok`, `missing` (with the words to show)
    or `not_needed` (the service is read without a login: SoundCloud and YouTube Music playlists)."""
    state: str  # "ok" | "missing" | "not_needed"
    message: str = ""

    @property
    def connected(self) -> bool:
        """Whether a read can start: anything but `missing`."""
        return self.state != "missing"


class Reader(Protocol):
    """A logged-in session of one service, opened once per read. A context manager: `close()` runs on exit."""

    def __enter__(self) -> "Reader": ...

    def __exit__(self, *exc) -> None: ...

    def close(self) -> None: ...

    # Set before `fetch` by a reader of the hub: fill `FetchedPlaylist.info` too when the tracks' own answer holds the
    # playlist's name, owner and cover (Qobuz), so the page needs no second login. A source that can't may ignore it.
    want_info: bool
    # Set before `fetch` by a sync: `on_signal(account service, kind, message)` is called when a read made with an
    # account's login meets one of that account's warning signs (accounts.SIGNALS), so the sync records it as a
    # download would. A source that reads without a login may ignore it.
    on_signal: "Callable[[str, str, str], None] | None"

    def fetch(self, line: PlaylistLine) -> FetchedPlaylist: ...

    def info(self, playlist_id: str) -> PlaylistInfo: ...
