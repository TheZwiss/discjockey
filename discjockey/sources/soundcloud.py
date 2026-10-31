"""The SoundCloud playlist source (sources/__init__.py): sets, likes and the short links that stand for them.

Reading a playlist is not a download: it uses none of the download protection (no pacing, no budget, no usage row, no
auto-stop), and a read error never counts as a failed download. Reads are anonymous: no browser cookies, with one
exception, the `soundcloud.com/you/likes` link, which names no user until the SoundCloud login says who "you" is.

The reader asks SoundCloud's API itself through yt-dlp's SoundCloud extractor (as `fallback._soundcloud_track` does),
which keeps the client id current. yt-dlp is imported inside the functions that need it, never at module level:
`sources` is imported by `config` and `playlists_file`, before `tools.activate()` has put the newer yt-dlp first.

yt-dlp's `_HEADERS` is one dict shared by every SoundCloud extractor of the process, and a login writes its OAuth
header into it. So every anonymous request here passes `headers={}` itself and stays anonymous whatever else ran."""
from __future__ import annotations

import re
import urllib.error
import urllib.request

from ..accounts import BROWSERS, signal_of, ytdlp_login
from ..events import CancelToken
from ..library import SupportPaths
from ..models import FetchedPlaylist, PlaylistInfo, PlaylistLine, SourceTrack
from ..titles import split_title
from .base import LoginState, SourceError

SERVICE = "soundcloud"

UNREADABLE_HINT = "Make it public in SoundCloud, or use its private share link."
UNREADABLE_SET = ("SoundCloud doesn't show this playlist. It may be private or removed; for a private set, use its "
                  "private share link.")
SLOW_DOWN = "SoundCloud asked Discjockey to slow down. Try again in an hour."
LIKES_HINT = ("To read your own likes, use your profile's likes link: on SoundCloud, open your profile, click Likes "
              "and copy the address (soundcloud.com/your-name/likes).")

BATCH_SIZE = 50      # track ids per `tracks?ids=` request
LIKES_PAGE = 200     # SoundCloud's largest page for a linked-partitioning query
REDIRECT_TIMEOUT = 10  # seconds for the one request that follows a short link
USER_AGENT = "Discjockey (playlist link check)"
YOU = "you/likes"

_HOST = r"https?://(?:(?:www|m)\.)?soundcloud\.com"
_TAIL = r"/?(?:[?#].*)?"
_SET = re.compile(rf"{_HOST}/([\w-]+)/sets/([:\w-]+)(?:/([^?/#]+))?{_TAIL}", re.I)
_LIKES = re.compile(rf"{_HOST}/([\w-]+)/likes{_TAIL}", re.I)
_SHORT = re.compile(r"https?://on\.soundcloud\.com/[\w-]+" + _TAIL, re.I)
_NOT_USERS = frozenset({"discover"})  # discover sets change daily: never a playlist of a person


def recognise(link: str) -> str | None:
    """The playlist id (D3: the link's path, lowercased except a private set's secret token) when `link` is a
    SoundCloud set, a set's private share link or a likes list, else None. Tracks, albums, reposts, user pages and
    short links are not playlists here (a short link is `expand`'s)."""
    m = _SET.fullmatch(link)
    if m:
        user = m.group(1).lower()
        if user in _NOT_USERS:
            return None
        pid = f"{user}/sets/{m.group(2).lower()}"
        return f"{pid}/{m.group(3)}" if m.group(3) else pid
    m = _LIKES.fullmatch(link)
    if m and m.group(1).lower() not in _NOT_USERS:
        return f"{m.group(1).lower()}/likes"
    return None


def canonical_link(playlist_id: str) -> str:
    return f"https://soundcloud.com/{playlist_id}"


def login_state(paths: SupportPaths) -> LoginState:
    """SoundCloud playlists are read without a login."""
    return LoginState("not_needed")


def _problem(e: Exception) -> str:
    """What to say SoundCloud did when a request failed: only the kind of error (a library's text may hold a link)."""
    return type(e).__name__


def _status(e: Exception) -> int | None:
    """The HTTP status of a failed yt-dlp request (its ExtractorError holds the HTTPError as `cause`), else None."""
    status = getattr(getattr(e, "cause", None), "status", None)
    if isinstance(status, int):
        return status
    m = re.search(r"HTTP Error (\d{3})", str(e))
    return int(m.group(1)) if m else None


def _offline(e: Exception) -> SourceError:
    if _status(e) == 429:
        return SourceError(SLOW_DOWN, "offline", SERVICE)
    return SourceError(f"SoundCloud is not responding ({_problem(e)}). Try again later.", "offline", SERVICE)


def _extractor(options: dict):
    """(YoutubeDL, initialised SoundCloud extractor). The user extractor is a SoundCloud extractor that also knows
    yt-dlp's impersonation target for paged answers; it shares the API calls of the others."""
    import yt_dlp
    ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noprogress": True, "socket_timeout": 30, **options})
    try:
        ie = ydl.get_info_extractor("SoundcloudUser")
        ie.initialize()
    except BaseException:
        ydl.close()
        raise
    return ydl, ie


def _api(ie, token: CancelToken, url: str, *, headers: dict, query: dict | None = None,
         refused: SourceError | None = None, **kwargs):
    """One API answer. Stop is checked before the request. 404/401/403 raise `refused` when given; 429 and every
    other failure say SoundCloud isn't answering."""
    token.check()
    try:
        return ie._call_api(url, None, query=dict(query or {}), headers=headers, **kwargs)
    except Exception as e:
        if refused is not None and _status(e) in (401, 403, 404):
            raise refused from None
        raise _offline(e) from None


def _account(paths: SupportPaths):
    """The SoundCloud account of Settings, or None."""
    from ..settings import SettingsError, load_settings
    try:
        return load_settings(paths.settings_file).accounts.get(SERVICE)
    except (SettingsError, OSError, ValueError, KeyError, TypeError):
        return None


def _login_session(paths: SupportPaths, token: CancelToken):
    """(YoutubeDL, extractor, headers, `me`) through the SoundCloud login of Settings: the one place a read uses
    cookies. W8 without the account, W9 when the browser's login can't be read or SoundCloud doesn't accept it."""
    account = _account(paths)
    if account is None:
        raise SourceError(LIKES_HINT, "playlist_unreadable", SERVICE)
    browser = BROWSERS.get(account.browser, account.browser)
    expired = SourceError(
        f"SoundCloud didn't accept the login from {browser}. Log in to SoundCloud there, or use your profile's "
        "likes link (soundcloud.com/your-name/likes).", "login_expired", SERVICE)
    token.check()
    try:
        ydl, ie = _extractor(ytdlp_login(SERVICE, account.browser, account.profile))
    except Exception as e:
        if signal_of(e) in ("cookies_unreadable", "refused"):
            raise expired from None
        raise _offline(e) from None
    try:
        headers = dict(ie._HEADERS)
        if "Authorization" not in headers:  # yt-dlp found no accepted token in the browser's cookies
            raise expired
        me = _api(ie, token, ie._API_V2_BASE + "me", headers=headers, refused=expired)
        if not isinstance(me, dict) or not me.get("id"):
            raise expired
    except BaseException:
        ydl.close()
        raise
    return ydl, ie, headers, me


def _redirect_target(url: str) -> str | None:
    """Where a short link sends the browser first (its `Location`), or None when it sends nowhere. One request, no
    cookies, our own User-Agent. A network failure raises URLError/OSError; 429 raises HTTPError."""
    class _Stay(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None  # keep the first answer: its Location is all we want

    opener = urllib.request.build_opener(_Stay)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=REDIRECT_TIMEOUT) as answer:
            return answer.headers.get("Location")
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400:
            return e.headers.get("Location")
        raise


def expand(link: str, paths: SupportPaths, token: CancelToken) -> str:
    """The link a pasted SoundCloud link stands for. `on.soundcloud.com/<code>` follows its redirect once; the target
    must be a set or likes list we read, else the link comes back unchanged (and is refused as any other link).
    `soundcloud.com/you/likes` becomes `<your permalink>/likes` through the login of Settings, so the stored line
    needs no login later. Every other link comes back as it is."""
    link = link.strip()
    if _SHORT.fullmatch(link):
        token.check()
        try:
            target = _redirect_target(link)
        except Exception as e:  # URLError, a timeout, or the HTTPError of a 429
            raise _offline(e) from None
        playlist_id = recognise(target) if target else None
        return canonical_link(playlist_id) if playlist_id else link
    if recognise(link) == YOU:
        ydl, _ie, _headers, me = _login_session(paths, token)
        ydl.close()
        permalink = str(me.get("permalink") or "").strip().lower()
        if not re.fullmatch(r"[\w-]+", permalink):
            raise SourceError(LIKES_HINT, "playlist_unreadable", SERVICE)
        return canonical_link(f"{permalink}/likes")
    return link


def _image(url: object) -> str | None:
    """A cover address at 500 px: SoundCloud's `-large` (100 px) becomes `-t500x500`."""
    if not isinstance(url, str) or not url:
        return None
    return url.replace("-large.", "-t500x500.")


def skipped_text(track_id: object) -> str:
    return f"A track SoundCloud no longer shows (ID {track_id})" if track_id else "A track SoundCloud no longer shows"


def parse_track(obj: object) -> SourceTrack | str:
    """One SoundCloud track object as a SourceTrack, or the words for why it is skipped. SoundCloud's own metadata
    wins where it exists (D9): a label-distributed upload names its artist, album and ISRC; `policy` BLOCK is not
    playable here, SNIP is a 30 s preview unless the Go+ account plays it."""
    if not isinstance(obj, dict) or not obj.get("id"):
        return skipped_text(obj.get("id") if isinstance(obj, dict) else None)
    user = obj.get("user") if isinstance(obj.get("user"), dict) else {}
    meta = obj.get("publisher_metadata") if isinstance(obj.get("publisher_metadata"), dict) else {}
    artists, title = split_title(str(obj.get("title") or ""), str(user.get("username") or ""),
                                 meta.get("artist") or None)
    policy = str(obj.get("policy") or "").upper()
    length = obj.get("full_duration") or obj.get("duration") or 0
    isrc = meta.get("isrc")
    return SourceTrack(
        id=str(obj["id"]),
        title=title,
        artists=tuple(artists),
        album=meta.get("album_title") or "",
        image_url=_image(obj.get("artwork_url") or user.get("avatar_url")),
        duration_ms=int(length) if isinstance(length, (int, float)) else 0,
        isrc=isrc.strip().upper() if isinstance(isrc, str) and isrc.strip() else None,
        service=SERVICE,
        link=obj.get("permalink_url") or None,
        streamable=policy != "BLOCK",
        account_only=policy == "SNIP",
    )


def _is_stub(track: object) -> bool:
    """A track the set lists by id only (SoundCloud fills in the first few of a set)."""
    return isinstance(track, dict) and bool(track.get("id")) and not track.get("title")


class SoundCloudReader:
    """One anonymous extractor for a whole read, and a second, logged-in one opened on first need (`you/likes`)."""

    def __init__(self, ydl, ie, paths: SupportPaths, token: CancelToken):
        self._ydl, self._ie = ydl, ie
        self.paths, self.token = paths, token
        self.want_info = False
        self._login: tuple | None = None  # (ydl, ie, headers, me) once opened

    def __enter__(self) -> "SoundCloudReader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        for ydl in (self._ydl, self._login[0] if self._login else None):
            if ydl is not None:
                try:
                    ydl.close()
                except Exception:
                    pass
        self._ydl, self._login = None, None

    # -- requests

    def _get(self, url: str, unreadable: SourceError | None, **kwargs):
        return _api(self._ie, self.token, url, headers={}, refused=unreadable, **kwargs)

    def _login_open(self) -> tuple:
        if self._login is None:
            self._login = _login_session(self.paths, self.token)
        return self._login

    def _resolve(self, path: str, unreadable: SourceError) -> dict:
        data = self._get(self._ie._resolv_url(f"https://soundcloud.com/{path}"), unreadable)
        if not isinstance(data, dict) or "errors" in data:
            raise unreadable
        return data

    def _fill(self, tracks: list, unreadable: SourceError, playlist_id: str | None = None,
              secret: str | None = None) -> list:
        """`tracks` with every stub replaced by its full object: ids fetched 50 at a time, in the original order. An
        id the answer lacks stays a stub (the caller skips it)."""
        stubs = [str(t["id"]) for t in tracks if _is_stub(t)]
        found: dict[str, dict] = {}
        for i in range(0, len(stubs), BATCH_SIZE):
            query = {"ids": ",".join(stubs[i:i + BATCH_SIZE])}
            if playlist_id:
                query["playlistId"] = playlist_id
            if secret:
                query["playlistSecretToken"] = secret
            answer = self._get(self._ie._API_V2_BASE + "tracks", unreadable, query=query)
            for t in answer if isinstance(answer, list) else []:
                if isinstance(t, dict) and t.get("id") and t.get("title"):
                    found[str(t["id"])] = t
        return [found.get(str(t.get("id")), t) if _is_stub(t) else t for t in tracks]

    # -- what a read returns

    @staticmethod
    def _sorted(tracks: list) -> tuple[list[SourceTrack], list[str]]:
        out: list[SourceTrack] = []
        skipped: list[str] = []
        for t in tracks:
            r = parse_track(t) if not _is_stub(t) else skipped_text(t.get("id"))
            (out if isinstance(r, SourceTrack) else skipped).append(r)
        return out, skipped

    def fetch(self, line: PlaylistLine) -> FetchedPlaylist:
        unreadable = SourceError(
            f"playlists.txt line {line.line_no} ({line.folder}): SoundCloud doesn't show this playlist. It may be "
            "private or removed; for a private set, use its private share link. Check the link, or put # in front "
            "of the line.", "playlist_unreadable", SERVICE)
        pid = line.playlist_id
        if pid.endswith("/likes"):
            return self._fetch_likes(line, pid, unreadable)
        playlist = self._set(pid, unreadable)
        secret = pid.split("/")[3] if pid.count("/") >= 3 else None
        items = playlist.get("tracks") or []
        items = self._fill(items if isinstance(items, list) else [], unreadable, str(playlist["id"]), secret)
        tracks, skipped = self._sorted(items)
        info = self._set_info(playlist, pid) if self.want_info else None
        return FetchedPlaylist(line, tracks, skipped, info)

    def _set(self, pid: str, unreadable: SourceError) -> dict:
        playlist = self._resolve(pid, unreadable)
        if playlist.get("kind") != "playlist" or not playlist.get("id"):
            raise unreadable
        return playlist

    def _fetch_likes(self, line: PlaylistLine, pid: str, unreadable: SourceError) -> FetchedPlaylist:
        user, ie, headers = self._likes_user(pid, unreadable)
        base = ie._API_V2_BASE + f"users/{user['id']}/track_likes"
        items: list = []
        url, query = base, {"limit": LIKES_PAGE, "linked_partitioning": "1"}
        while url:
            page = _api(ie, self.token, url, headers=headers, query=query, refused=unreadable,
                        impersonate=ie._browser_impersonate_target)
            if not isinstance(page, dict):
                raise unreadable
            for entry in page.get("collection") or []:
                track = entry.get("track") if isinstance(entry, dict) else None
                items.append(track if isinstance(track, dict) else {})
            url, query = page.get("next_href"), {}  # the next address holds its own cursor
        items = self._fill(items, unreadable)
        tracks, skipped = self._sorted(items)
        info = self._likes_info(user, pid, len(tracks) + len(skipped), items) if self.want_info else None
        return FetchedPlaylist(line, tracks, skipped, info)

    def _likes_user(self, pid: str, unreadable: SourceError) -> tuple[dict, object, dict]:
        """(user, the extractor to ask, its headers): the named user anonymously, or "you" through the login."""
        if pid == YOU:
            _ydl, ie, headers, me = self._login_open()
            return me, ie, headers
        user = self._resolve(pid.split("/")[0], unreadable)
        if user.get("kind") != "user" or not user.get("id"):
            raise unreadable
        return user, self._ie, {}

    # -- the page's facts

    def info(self, playlist_id: str) -> PlaylistInfo:
        unreadable = SourceError(UNREADABLE_SET, "playlist_unreadable", SERVICE)
        if playlist_id.endswith("/likes"):
            user, _ie, _headers = self._likes_user(playlist_id, unreadable)
            return self._likes_info(user, playlist_id, None, [])
        return self._set_info(self._set(playlist_id, unreadable), playlist_id)

    @staticmethod
    def _set_info(playlist: dict, playlist_id: str) -> PlaylistInfo:
        user = playlist.get("user") if isinstance(playlist.get("user"), dict) else {}
        listed = playlist.get("tracks") if isinstance(playlist.get("tracks"), list) else []
        cover = playlist.get("artwork_url") or next(
            (t["artwork_url"] for t in listed if isinstance(t, dict) and t.get("artwork_url")), None)
        count = playlist.get("track_count")
        return PlaylistInfo(SERVICE, playlist_id, str(playlist.get("title") or ""), str(user.get("id") or ""),
                            str(user.get("username") or ""), False, _image(cover),
                            count if isinstance(count, int) and not isinstance(count, bool) else len(listed),
                            False, True)

    @staticmethod
    def _likes_info(user: dict, playlist_id: str, count: int | None, items: list) -> PlaylistInfo:
        name = str(user.get("username") or "")
        cover = next((t["artwork_url"] for t in items if isinstance(t, dict) and t.get("artwork_url")), None)
        return PlaylistInfo(SERVICE, playlist_id, f"{name}'s likes", str(user.get("id") or ""), name, False,
                            _image(cover), count, False, True)


def open(paths: SupportPaths, token: CancelToken) -> SoundCloudReader:  # noqa: A001 (the source interface's name)
    token.check()
    try:
        ydl, ie = _extractor({})
    except Exception as e:
        raise _offline(e) from None
    return SoundCloudReader(ydl, ie, paths, token)
