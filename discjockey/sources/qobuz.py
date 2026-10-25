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
UNREADABLE_HINT = "Make it public in Qobuz, or use one of your own playlists."
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


def parse_item(item: object) -> SourceTrack | str:
    """One entry of a playlist's `tracks.items` as a SourceTrack, or the words for why it is skipped. A track Qobuz
    lists but won't stream (`streamable` false: a preview or a region lock) stays in the list, marked."""
    if not isinstance(item, dict):
        return "Unknown track (unreadable entry)"
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


def _total(listing: dict) -> int | None:
    """The `total` of a track listing when it is a positive whole number, else None (missing, zero or not a number)."""
    total = listing.get("total")
    if isinstance(total, str) and total.strip().isdigit():
        total = int(total)
    return total if isinstance(total, int) and not isinstance(total, bool) and total > 0 else None


def _problem(e: Exception) -> str:
    """What to say Qobuz did when a request failed: our own words for QobuzError, else only the kind of error
    (the text of a library's exception may hold a link)."""
    return str(e) if isinstance(e, qobuz.QobuzError) else type(e).__name__


class QobuzReader:
    """One Qobuz login for a whole read. Every request goes through `QobuzSource._call`: Stop reaches it and it gives
    up after 30 seconds."""

    def __init__(self, source: qobuz.QobuzSource):
        self.source = source
        self.want_info = False  # set by sources.read: fill FetchedPlaylist.info from the first page (see fetch)
        self._user_asked = False  # the logged-in user's id is asked for once per reader
        self._user_id: str | None = None

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
        info: PlaylistInfo | None = None
        offset = 0
        while True:
            page = self._playlist(line.playlist_id, unreadable, extra="tracks", limit=PAGE_SIZE, offset=offset)
            if offset == 0 and self.want_info:  # the first page names the playlist too: no second playlist request,
                info = self._info_of(page, line.playlist_id)  # and the hub's page needs no second login
            listing = page.get("tracks")
            listing = listing if isinstance(listing, dict) else {}
            items = listing.get("items")
            items = items if isinstance(items, list) else []
            for item in items:
                r = parse_item(item)
                (tracks if isinstance(r, SourceTrack) else skipped).append(r)
            offset += PAGE_SIZE
            total = _total(listing)
            # without a usable total, a full page means there may be more
            more = offset < total if total else len(items) == PAGE_SIZE
            if not items or not more:
                return FetchedPlaylist(line, tracks, skipped, info)

    def _logged_in_user(self) -> str | None:
        """The id of the logged-in Qobuz user, from `playlist/getUserPlaylists` (its answer names the user next to
        the playlists). Asked for on the first call only; None when the request fails or the answer has no user id.
        Stop (events.Cancelled) passes through."""
        if not self._user_asked:
            self._user_asked = True
            self.source.check()
            params = {"app_id": str(self.source.client.config.session.qobuz.app_id), "limit": 1}
            try:
                status, body = self.source._call(self.source.client._api_request("playlist/getUserPlaylists", params))
                user = body.get("user") if status == 200 and isinstance(body, dict) else None
                uid = user.get("id") if isinstance(user, dict) else None
                self._user_id = str(uid) if uid not in (None, "") else None
            except Exception:
                self._user_id = None
        return self._user_id

    def info(self, playlist_id: str) -> PlaylistInfo:
        data = self._playlist(playlist_id, "Qobuz doesn't show this playlist. It must be public or one of yours. "
                                           "Check the link.")
        return self._info_of(data, playlist_id)

    def _info_of(self, data: dict, playlist_id: str) -> PlaylistInfo:
        """The page's facts from a `playlist/get` answer (the user's own id is asked for once per reader)."""
        owner = data.get("owner") or {}
        count = data.get("tracks_count")
        owner_id = str(owner.get("id") or "")
        user_id = self._logged_in_user()
        return PlaylistInfo(SERVICE, str(data.get("id") or playlist_id), data.get("name") or "",
                            owner_id, owner.get("name") or "",
                            bool(data.get("is_collaborative")), _cover(data),
                            count if isinstance(count, int) else None,
                            bool(owner_id) and owner_id == user_id, True)


def open(paths: SupportPaths, token: CancelToken) -> QobuzReader:  # noqa: A001 (the source interface's name)
    try:
        source = qobuz.QobuzSource.open(paths)
    except qobuz.QobuzNotSetUp:
        raise SourceError(NOT_SET_UP, "not_set_up", SERVICE) from None
    except Exception as e:
        raise SourceError(qobuz.login_problem(e), "qobuz_login_failed", SERVICE) from None
    source.check = token.check
    return QobuzReader(source)
