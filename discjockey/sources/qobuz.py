"""The Qobuz playlist source (sources/__init__.py): recognising its links, the local login check and the `Reader`.

Reading a playlist is not a download: it uses none of the download protection (no pacing, no daily limit, no usage
row, no auto-stop), and a read error never counts as a failed download. The reader logs in once with its own
`qobuz.QobuzSource` (not the one `run.open_qobuz` hands to `execute`: streamrip's client is bound to one
`asyncio.Runner`, and a read and a download run in different threads) and closes it when the read ends."""
from __future__ import annotations

import re
import tomllib

from .. import qobuz
from ..events import CancelToken
from ..library import SupportPaths
from ..models import FetchedPlaylist, PlaylistInfo, PlaylistLine, SourceTrack
from .base import LoginState, SourceError

SERVICE = "qobuz"

PAGE_SIZE = 500  # tracks per playlist/get request (streamrip's own get_metadata stops after one page of this size)
NOT_SET_UP = "Your playlists include a Qobuz playlist, but Qobuz isn't set up yet. Run: discjockey setup"
UNREADABLE_STATUSES = (400, 401, 403, 404)  # Qobuz's answers for a playlist that doesn't exist or isn't visible

_PLAYLIST_PAGE = re.compile(r"https?://(?:open|play|listen)\.qobuz\.com/playlist/(\d+)(?:[/?#].*)?", re.I)
_STORE_PAGE = re.compile(r"https?://www\.qobuz\.com/[a-z]{2}-[a-z]{2}/playlists/[^/?#]+/(\d+)(?:[/?#].*)?", re.I)


def recognise(link: str) -> str | None:
    """The playlist id when `link` is a Qobuz playlist link (the player's or the store's), else None."""
    for rx in (_PLAYLIST_PAGE, _STORE_PAGE):
        m = rx.fullmatch(link)
        if m:
            return m.group(1)
    return None


def canonical_link(playlist_id: str) -> str:
    return f"https://open.qobuz.com/playlist/{playlist_id}"


def login_state(paths: SupportPaths) -> LoginState:
    """Whether Setup left a Qobuz login on this Mac: streamrip's config file holds an e-mail (or user id) and the
    password hash (or token) that `QobuzSource.open` logs in with. A local check; the file is only read."""
    try:
        data = tomllib.loads(qobuz.config_file(paths).read_text(encoding="utf-8")).get("qobuz") or {}
    except (OSError, ValueError):  # no file, or one that isn't TOML (tomllib.TOMLDecodeError is a ValueError)
        return LoginState("missing", NOT_SET_UP)
    if data.get("email_or_userid") and data.get("password_or_token"):
        return LoginState("ok")
    return LoginState("missing", NOT_SET_UP)


def parse_item(item: dict) -> SourceTrack | str:
    """One entry of a playlist's `tracks.items` as a SourceTrack, or the words for why it is skipped. A track Qobuz
    lists but won't stream (`streamable` false: a preview or a region lock) stays in the list, marked."""
    title = item.get("title") or ""
    if item.get("version"):
        title = f"{title} ({item['version']})"
    if not item.get("id"):
        return f"{title or 'Unknown track'} (no Qobuz ID)"
    album = item.get("album") or {}
    artist = (item.get("performer") or {}).get("name") or (album.get("artist") or {}).get("name")
    return SourceTrack(
        id=str(item["id"]),
        title=title,
        artists=(artist,) if artist else (),
        album=album.get("title") or "",
        image_url=(album.get("image") or {}).get("large") or None,
        duration_ms=int(item.get("duration") or 0) * 1000,
        isrc=item.get("isrc") or None,
        service=SERVICE,
        streamable=item.get("streamable") is not False,
    )


def _cover(data: dict) -> str | None:
    """The playlist's cover: the first url of the largest list the answer has."""
    for key in ("images300", "image_rectangle", "images150", "images"):
        urls = data.get(key)
        if isinstance(urls, list) and urls and isinstance(urls[0], str):
            return urls[0]
    return None


def _problem(e: Exception) -> str:
    """What to say Qobuz did when a request failed: our own words for QobuzError, else only the kind of error
    (the text of a library's exception may hold a link)."""
    return str(e) if isinstance(e, qobuz.QobuzError) else type(e).__name__


class QobuzReader:
    """One Qobuz login for a whole read. Every request goes through `QobuzSource._call`: Stop reaches it and it gives
    up after 30 seconds."""

    def __init__(self, source: qobuz.QobuzSource):
        self.source = source

    def __enter__(self) -> "QobuzReader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.source.close()

    def _playlist(self, playlist_id: str, unreadable: str, **params) -> dict:
        """One `playlist/get` answer. `unreadable` is the message when Qobuz doesn't show the playlist. Stop
        (events.Cancelled) passes through."""
        self.source.check()
        params = {"app_id": str(self.source.client.config.session.qobuz.app_id), "playlist_id": playlist_id, **params}
        try:
            status, body = self.source._call(self.source.client._api_request("playlist/get", params))
        except Exception as e:
            raise SourceError(f"Qobuz is not responding ({_problem(e)}). Try again later.", "offline",
                              SERVICE) from None
        if status in UNREADABLE_STATUSES:
            raise SourceError(unreadable, "playlist_unreadable", SERVICE)
        if status != 200 or not isinstance(body, dict):
            raise SourceError(f"Qobuz is not responding (HTTP {status}). Try again later.", "offline", SERVICE)
        return body

    def fetch(self, line: PlaylistLine) -> FetchedPlaylist:
        unreadable = (f"playlists.txt line {line.line_no} ({line.folder}): Qobuz doesn't show this playlist. "
                      "It must be public or one of yours. Check the link, or put # in front of the line.")
        tracks: list[SourceTrack] = []
        skipped: list[str] = []
        offset = 0
        while True:
            page = self._playlist(line.playlist_id, unreadable, extra="tracks", limit=PAGE_SIZE, offset=offset)
            listing = page.get("tracks") or {}
            items = listing.get("items") or []
            for item in items:
                r = parse_item(item)
                (tracks if isinstance(r, SourceTrack) else skipped).append(r)
            offset += PAGE_SIZE
            if not items or offset >= int(listing.get("total") or 0):
                return FetchedPlaylist(line, tracks, skipped)

    def info(self, playlist_id: str) -> PlaylistInfo:
        data = self._playlist(playlist_id, "Qobuz doesn't show this playlist. It must be public or one of yours. "
                                           "Check the link.")
        owner = data.get("owner") or {}
        count = data.get("tracks_count")
        # streamrip doesn't keep the logged-in user's id, so a Qobuz playlist is never marked as "yours" here
        return PlaylistInfo(SERVICE, str(data.get("id") or playlist_id), data.get("name") or "",
                            str(owner.get("id") or ""), owner.get("name") or "",
                            bool(data.get("is_collaborative")), _cover(data),
                            count if isinstance(count, int) else None, False, True)


def open(paths: SupportPaths, token: CancelToken) -> QobuzReader:  # noqa: A001 (the source interface's name)
    try:
        source = qobuz.QobuzSource.open(paths)
    except qobuz.QobuzNotSetUp:
        raise SourceError(NOT_SET_UP, "not_set_up", SERVICE) from None
    except Exception as e:
        raise SourceError(qobuz.login_problem(e), "qobuz_login_failed", SERVICE) from None
    source.check = token.check
    return QobuzReader(source)
