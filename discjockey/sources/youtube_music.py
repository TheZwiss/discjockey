"""The YouTube Music playlist source (sources/__init__.py): public and unlisted playlists, read without a login.

Reading a playlist is not a download: it uses none of the download protection (no pacing, no budget, no usage row, no
auto-stop), and a read error never counts as a failed download. Reads are anonymous: no browser cookies, no login,
no `extractor_args`. The Premium downloads use the YouTube login, so a read must never carry cookies or any state
into them (see "State" below), and "Liked videos" (`LL`) and "Watch later" (`WL`) are refused (W17) because reading
them would need that login.

The one exception is "Liked music" (`LM`, sources-round D5-D7), the user's choice in Settings (`Settings.
read_liked_music`, off by default; it needs a YouTube account). While the choice is off, `left_out` says the line is
not read at all (the sync treats it as a switched-off line, no problem) and a direct read answers
`SourceError(.., "setting_off")`. While it is on, the LM line is read through a second `YoutubeDL` of the reader's
own, created on the first LM read, carrying `accounts.ytdlp_login("youtube", ..)` and closed with the reader: the
anonymous `YoutubeDL`, every other playlist's read and the download path never see those options. It obeys the
account's waits (D6): `left_out` also says so while the YouTube account is paused today (`pacing.account_paused`),
and a bot check or "too many requests" met by the LM read itself is handed to `reader.on_signal` (the sync records
it as the account's warning sign, the one a download would) and ends that line with `LineSkipped`, not the run.

The reader asks yt-dlp's `youtube:tab` extractor through its own `YoutubeDL`, with `extract_flat` and
`process=False`: the extractor returns the playlist's facts (title, owner, count, thumbnails) on the outer dict after
one page request, and `entries` as a lazy generator of flat entries (`id`, `title`, `duration`, `channel`,
`thumbnails`, no artist or album) that fetches the next page only when it is asked for one. yt-dlp is imported inside
the functions that need it, never at module level: `sources` is imported by `config` and `playlists_file`, before
`tools.activate()` has put the newer yt-dlp first.

State: yt-dlp keeps some state at class level (SoundCloud's login header is one: sources/soundcloud.py). The YouTube
tab extractor keeps only constants there (reserved names, language codes, ignored warnings, a time-unit table) that
nothing writes, plus a memo of its compiled link pattern (`_VALID_URL_RE`, the same for everyone); its cookies,
preferences and consent live on the `YoutubeDL` instance this module creates for one read and closes. So nothing
here writes a class attribute; a test snapshots the extractor classes around a read to keep it so."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Callable
from urllib.parse import parse_qs, urlsplit

from ..accounts import BROWSERS, signal_of, ytdlp_login
from ..events import CancelToken, no_emit
from ..library import SupportPaths
from ..models import FetchedPlaylist, PlaylistInfo, PlaylistLine, SourceTrack
from ..titles import clean_uploader, split_title
from .base import LineSkipped, LoginState, SourceError

if TYPE_CHECKING:
    from ..settings import Settings

SERVICE = "youtube_music"
SETTING = "read_liked_music"  # the settings.json key of the Liked music choice
ACCOUNT = "youtube"  # the download account whose login the Liked music read uses (accounts.ACCOUNT_OF)

UNREADABLE_HINT = "Set it to public or unlisted in YouTube Music."
UNREADABLE_INFO = "YouTube Music doesn't show this playlist. It must be public or unlisted. Check the link."
SLOW_DOWN = "YouTube Music asked Discjockey to slow down. Try again in an hour."
PERSONAL = ("Discjockey can't read your liked videos or Watch later. Add the songs to a playlist, set it to public or "
            "unlisted, and paste that link.")
SETTING_OFF = "Reading your Liked music is off. Turn it on in Settings."
LIKED_UNREADABLE = ("YouTube Music doesn't show your Liked music. Check that you are signed in to YouTube in your "
                    "browser (Settings, YouTube Premium) and try again.")
LIKED_PAUSED = "YouTube asked Discjockey to slow down, so your Liked music was not read this time."
LIKED_LOGIN = ("Discjockey couldn't read your YouTube login to read your Liked music. Check it in Settings, "
               "YouTube Premium.")
LIKED_RESTING = "Your YouTube account is resting after a warning sign today. Try reading your Liked music tomorrow."
MIX = ("This is a YouTube mix, which changes every time it plays. Save its songs to a playlist and paste that link.")

LIKED_MUSIC = "LM"  # "Liked music": read only while Settings' choice is on (see the docstring)
LIKED_MUSIC_FOLDER = "Liked_music"  # the folder name "Add Liked music to Playlists" suggests (D8)
PERSONAL_IDS = frozenset({"LL", "WL"})  # liked videos and Watch later: never read
CURATED_MIX_PREFIX = "RDCLAK5uy_"  # YouTube Music's curated playlists are named like mixes but stay put
REMOVED_TITLES = frozenset({"[deleted video]", "[private video]"})
TOPIC_SUFFIX = " - Topic"  # YouTube's auto-generated artist channels
ALBUM_PREFIX = "Album - "  # yt-dlp names an album's playlist so

_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"})
_LIST_ID = re.compile(r"[A-Za-z0-9_-]+")

# What YouTube answers for a playlist it won't show, as yt-dlp words it. A removed, private or never-there playlist
# reads "YouTube said: The playlist does not exist." (YouTube's own alert) or, when the page falls back to the home
# page, "The channel/playlist does not exist and the URL redirected to youtube.com home page" (extractor/youtube/
# _tab.py, `_extract_data`); a malformed id answers HTTP 400. Deliberately absent: the "YouTube said" prefix (it opens
# every alert, including "Something went wrong"), HTTP 404 (YouTube answers some at random) and "Unable to recognize
# tab page" (a layout failure of the extractor): those are YouTube not answering (W15), not the playlist's fault.
_UNREADABLE_SIGNS = ("does not exist", "failed to resolve", "unviewable", "redirected to youtube.com home page",
                     "http error 400")


def recognise(link: str) -> str | None:
    """The playlist id (D5: the `list=` id, case kept) when `link` is a YouTube Music or YouTube playlist link, else
    None. Accepted: `music.youtube.com/playlist?list=ID`, `music.youtube.com/browse/VL<ID>`, and on `youtube.com`
    (also `www.`, `m.`, `music.`) `playlist?list=ID` and `watch?v=…&list=ID`; other query keys (`si=`) are ignored.
    A watch link without `list`, a channel, a video and `youtu.be` are not playlists here. Ids of personal lists
    and mixes are recognised too; reading them is refused with words (`_refusal`)."""
    try:
        parts = urlsplit(link.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if parts.scheme.lower() not in ("http", "https") or host not in _HOSTS:
        return None
    path = parts.path.rstrip("/")
    if path == "/browse" or path.startswith("/browse/"):
        item = path[len("/browse/"):]
        if host == "music.youtube.com" and item.startswith("VL") and "/" not in item:
            return _list_id(item[2:])
        return None
    if path not in ("/playlist", "/watch"):
        return None
    query = parse_qs(parts.query)
    if path == "/watch" and not query.get("v"):
        return None
    ids = query.get("list")
    return _list_id(ids[0]) if ids else None


def _list_id(text: str) -> str | None:
    return text if _LIST_ID.fullmatch(text) else None


def canonical_link(playlist_id: str) -> str:
    return f"https://music.youtube.com/playlist?list={playlist_id}"


def login_state(paths: SupportPaths) -> LoginState:
    """YouTube Music playlists are read without a login."""
    return LoginState("not_needed")


def _liked_music_settings(paths: SupportPaths) -> "Settings | None":
    """The settings when Liked music is on and can be read (the choice is on, a YouTube account is set up), else None
    (also for a settings.json that cannot be read: the line then reads as off). The only place this module looks at
    the settings, and only for the Liked music line: any other read never does."""
    from ..settings import SettingsError, load_settings  # lazily, so a playlist read has no settings in reach
    try:
        settings = load_settings(paths.settings_file)
    except SettingsError:
        return None
    return settings if settings.reads_liked_music else None


def left_out(paths: SupportPaths, line: PlaylistLine, paused: frozenset[str] = frozenset()) -> bool:
    """Whether the sync leaves this line unread this time, before any request (D6, D7): the Liked music line while the
    choice is off (or no YouTube account is set up), or while the YouTube account is paused (`paused`: the account
    services paused today, `pacing.paused_accounts`). Its files stay; the line is no problem."""
    return (line.playlist_id == LIKED_MUSIC
            and (_liked_music_settings(paths) is None or ACCOUNT in paused))


def _refusal(playlist_id: str) -> SourceError | None:
    """Why a recognised id is never read (W17, W18), or None. Decided before any request. (Liked music is not here:
    whether it is read depends on the setting, which the reader checks.)"""
    if playlist_id in PERSONAL_IDS:
        return SourceError(PERSONAL, "playlist_unreadable", SERVICE)
    if playlist_id.startswith("RD") and not playlist_id.startswith(CURATED_MIX_PREFIX):
        return SourceError(MIX, "playlist_unreadable", SERVICE)
    return None


def _problem(e: Exception) -> str:
    """What to say YouTube did when a request failed: "refused" for a 401/403, else only the kind of error (a
    library's text may hold a link)."""
    return "refused" if signal_of(e) == "refused" else type(e).__name__


def _failure(e: Exception, unreadable: SourceError | None) -> SourceError:
    """The words for a failed request. The bot check and too many requests come first (W16); then, when the
    playlist's own page was being asked for (`unreadable` given), YouTube's "does not exist" family is the playlist's
    fault (W13/W14); everything else says YouTube isn't answering (W15)."""
    if signal_of(e) in ("bot_check", "rate_limited"):
        return SourceError(SLOW_DOWN, "offline", SERVICE)
    text = str(e).lower()
    if unreadable is not None and any(sign in text for sign in _UNREADABLE_SIGNS):
        return unreadable
    return SourceError(f"YouTube Music is not responding ({_problem(e)}). Try again later.", "offline", SERVICE)


def _largest(thumbnails: object) -> str | None:
    """The address of the largest thumbnail (by pixels; without sizes, the last one listed), or None."""
    best, best_area = None, -1
    for t in thumbnails if isinstance(thumbnails, list) else []:
        url = t.get("url") if isinstance(t, dict) else None
        if not isinstance(url, str) or not url:
            continue
        w, h = t.get("width"), t.get("height")
        area = w * h if isinstance(w, (int, float)) and isinstance(h, (int, float)) else 0
        if area >= best_area:
            best, best_area = url, area
    return best


def skipped_text(title: object) -> str:
    return f"{title if isinstance(title, str) and title.strip() else 'A track'} (removed from YouTube)"


def parse_entry(entry: object) -> SourceTrack | str:
    """One flat playlist entry as a SourceTrack, or the words for why it is skipped (W19): a deleted or private
    video, or an entry without an id or a length. A flat entry has no artist: a song (album playlists, songs added
    from YouTube Music) is the bare title with the artist as channel, a video is "Artist - Title (Official Video)";
    the splitter's own rule tells them apart (a dash splits, no dash takes the channel)."""
    if not isinstance(entry, dict):
        return skipped_text(None)
    title = entry.get("title")
    duration = entry.get("duration")
    if (not entry.get("id") or not isinstance(title, str) or not title.strip()
            or title.strip().lower() in REMOVED_TITLES
            or isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0):
        return skipped_text(title)
    video_id = str(entry["id"])
    channel = entry.get("channel") or entry.get("uploader") or ""
    if str(channel).strip().lower().endswith(TOPIC_SUFFIX.lower()):
        # an auto-generated "<Artist> - Topic" channel: titles are the song only, so the channel is the known artist
        artists, name = split_title(title, str(channel), clean_uploader(str(channel)))
    else:
        artists, name = split_title(title, str(channel))
    return SourceTrack(
        id=video_id,
        title=name,
        artists=tuple(artists),
        album="",
        image_url=_largest(entry.get("thumbnails")) or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        duration_ms=int(duration) * 1000,
        isrc=None,
        service=SERVICE,
    )


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _info_of(outer: dict, playlist_id: str, count: int | None = None) -> PlaylistInfo:
    """The page's facts from the playlist dict yt-dlp returns before any entry is read."""
    title = str(outer.get("title") or "")
    if title.startswith(ALBUM_PREFIX):
        title = title[len(ALBUM_PREFIX):]
    owner_name = str(outer.get("channel") or outer.get("uploader") or "")
    listed = _count(outer.get("playlist_count"))
    return PlaylistInfo(SERVICE, playlist_id, title, str(outer.get("channel_id") or ""), owner_name, False,
                        _largest(outer.get("thumbnails")), listed if listed is not None else count, False, True)


class YouTubeMusicReader:
    """One anonymous `YoutubeDL` for a whole read. Every page request goes through it; Stop is checked before the
    playlist's page and before each entry (so before each further page). The Liked music line alone is asked through
    a second `YoutubeDL` with the YouTube login (`_liked_music_ydl`).

    `on_signal(service, kind, message)`: set by the sync; called with the account service ("youtube") when the Liked
    music read meets a bot check or "too many requests", so the sync can record the warning sign."""

    def __init__(self, ydl, token: CancelToken, paths: SupportPaths | None = None, make_login_ydl=None):
        self._ydl, self.token = ydl, token
        self._paths, self._make_login_ydl, self._login_ydl = paths, make_login_ydl, None
        self.want_info = False
        self.on_signal: Callable[[str, str, str], None] | None = None

    def __enter__(self) -> "YouTubeMusicReader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        for name in ("_ydl", "_login_ydl"):
            ydl = getattr(self, name)
            if ydl is not None:
                try:
                    ydl.close()
                except Exception:
                    pass
            setattr(self, name, None)

    def _liked_music_ydl(self):
        """The `YoutubeDL` with the YouTube login for the Liked music line, made on the first such read and closed with
        the reader. SourceError(setting_off) while the choice is off or no account is set up."""
        settings = _liked_music_settings(self._paths) if self._paths is not None else None
        if settings is None:
            raise SourceError(SETTING_OFF, "setting_off", SERVICE, SETTING)
        if self._login_ydl is None:
            account = settings.accounts[ACCOUNT]
            if account.browser not in BROWSERS or self._make_login_ydl is None:
                raise SourceError(LIKED_LOGIN, "login_failed", SERVICE)
            try:
                self._login_ydl = self._make_login_ydl(ytdlp_login(ACCOUNT, account.browser, account.profile))
            except Exception as e:  # yt-dlp reads the browser's cookies when the YoutubeDL is made
                if signal_of(e) == "cookies_unreadable":
                    raise SourceError(LIKED_LOGIN, "login_failed", SERVICE) from None
                raise SourceError(f"YouTube Music is not responding ({_problem(e)}). Try again later.", "offline",
                                  SERVICE) from None
        return self._login_ydl

    def _failed(self, e: Exception, unreadable: SourceError | None, playlist_id: str) -> SourceError:
        """The error for a failed request. The Liked music read, which signs in, differs in two ways: a bot check or
        "too many requests" is passed to `on_signal` and ends the line (`LineSkipped`), not the run; an unreadable
        login says so."""
        error = _failure(e, unreadable)
        if playlist_id != LIKED_MUSIC:
            return error
        kind = signal_of(e)
        if kind in ("bot_check", "rate_limited"):
            if self.on_signal is not None:
                what = "YouTube's bot check" if kind == "bot_check" else "YouTube's \"too many requests\""
                self.on_signal(ACCOUNT, kind, f"{what} came up while reading your Liked music.")
            return LineSkipped(LIKED_PAUSED, "offline", SERVICE)
        if kind == "cookies_unreadable":
            return SourceError(LIKED_LOGIN, "login_failed", SERVICE)
        return error

    def _playlist(self, playlist_id: str, unreadable: SourceError) -> dict:
        """The playlist dict (its facts; `entries` still unread) from the playlist's first page."""
        refusal = _refusal(playlist_id)
        if refusal is not None:
            raise refusal
        ydl = self._liked_music_ydl() if playlist_id == LIKED_MUSIC else self._ydl
        self.token.check()
        try:
            outer = ydl.extract_info(canonical_link(playlist_id), download=False, process=False)
        except Exception as e:
            raise self._failed(e, unreadable, playlist_id) from None
        if not isinstance(outer, dict) or outer.get("_type") not in (None, "playlist") or "entries" not in outer:
            raise unreadable  # a redirect to a single video or a page that is no playlist
        return outer

    def fetch(self, line: PlaylistLine) -> FetchedPlaylist:
        if line.playlist_id == LIKED_MUSIC:
            unreadable = SourceError(LIKED_UNREADABLE, "playlist_unreadable", SERVICE)
        else:
            unreadable = SourceError(
                f"playlists.txt line {line.line_no} ({line.folder}): YouTube Music doesn't show this playlist. It "
                "must be public or unlisted. Check the link, or put # in front of the line.",
                "playlist_unreadable", SERVICE)
        outer = self._playlist(line.playlist_id, unreadable)
        tracks: list[SourceTrack] = []
        skipped: list[str] = []
        entries = outer.get("entries")
        entries = iter(entries) if entries is not None else iter(())
        while True:
            self.token.check()  # before each entry, so before the page that holds the next ones
            try:
                entry = next(entries)
            except StopIteration:
                break
            except Exception as e:  # a later page: the playlist was found, so this is never "private"
                raise self._failed(e, None, line.playlist_id) from None
            r = parse_entry(entry)
            (tracks if isinstance(r, SourceTrack) else skipped).append(r)
        info = _info_of(outer, line.playlist_id, len(tracks) + len(skipped)) if self.want_info else None
        return FetchedPlaylist(line, tracks, skipped, info)

    def info(self, playlist_id: str) -> PlaylistInfo:
        """The playlist's facts from its first page alone: the entries are never iterated."""
        unreadable = LIKED_UNREADABLE if playlist_id == LIKED_MUSIC else UNREADABLE_INFO
        outer = self._playlist(playlist_id, SourceError(unreadable, "playlist_unreadable", SERVICE))
        return _info_of(outer, playlist_id)


def open(paths: SupportPaths, token: CancelToken) -> YouTubeMusicReader:  # noqa: A001 (the source interface's name)
    """A reader with its own `YoutubeDL`: the quiet options and the debug-only logger of `fallback.FallbackSource`,
    flat playlists, and nothing else (no cookies, no login, no `extractor_args`). The Liked music line, while it is
    on, gets a second `YoutubeDL` with the same options plus the YouTube login, made when that line is read."""
    token.check()
    try:
        import yt_dlp
        from ..fallback import _Logger
        options = {"quiet": True, "no_warnings": True, "noprogress": True, "logger": _Logger(no_emit),
                   "skip_download": True, "extract_flat": "in_playlist", "socket_timeout": 30}
        ydl = yt_dlp.YoutubeDL(dict(options))
    except Exception as e:
        raise SourceError(f"YouTube Music is not responding ({_problem(e)}). Try again later.", "offline",
                          SERVICE) from None
    return YouTubeMusicReader(ydl, token, paths, lambda login: yt_dlp.YoutubeDL({**options, **login}))
