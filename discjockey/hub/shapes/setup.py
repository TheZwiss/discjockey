"""The shapes of Setup, Settings, the music folder, the watched folders and the import, tidy-up and the move log, the
reads with network and the AIFF plan (issue 39, phase 2, E7d), and the results of the jobs they start. The meanings are
those of `docs/hub-bridge-contract.md` ("Tidy-up and the move log", "Read with network", "Setup wizard", "Settings",
"The music folder", "Watched folders and the import", "Convert and clean names").

`ANSWERS` maps a method to the shape of its answer without `ok` (a J method: the shape of its job's result); `RESULTS`
maps a job kind to the shape of its `JobFinished.result`."""
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from .common import Empty, PlaylistService, Result, TrackRow
from .kernel import F, alias, shape
from .library import Browser, Crate, LibraryView, PlaylistInfo, PlaylistTrack, Service
from .todo import AiffBatchResult, CdjWords, UndoResult


def _extend(base: type, name: str, doc: str, fields: dict):
    """A shape that extends `base` with fields one of which is a Python keyword (`from`): `class X(Base)` cannot spell
    it, so the class is made through `base`'s own metaclass. The generated TypeScript is `Base & { ... }` as for any
    subclass."""
    return shape(type(base)(name, (base,), {"__annotations__": fields, "__module__": __name__, "__doc__": doc}))


def _record(name: str, doc: str, fields: dict):
    """A shape with a field whose name is no Python name (`from`, `yt-dlp`): the functional `TypedDict` form."""
    cls = TypedDict(name, fields)
    cls.__doc__ = doc
    return shape(cls)


# --- the music folder, the app update, the setup status ---

MusicState = alias(
    "MusicState", Literal["ok", "not_chosen", "missing"],
    doc="Where the music folder stands: `ok` (bound), `not_chosen` (Setup's first step) or `missing` (config.json "
        "names a folder that is not there, e.g. an unplugged drive).")
FolderKind = alias(
    "FolderKind", Literal["new", "empty", "discjockey_library", "other_files"],
    doc="What a usable folder holds: `new` (not there yet, made on the user's choice), `empty`, "
        "`discjockey_library` (a Discjockey library already) or `other_files` (the page asks before using it).")
FolderProblem = alias(
    "FolderProblem",
    Literal["not_absolute", "not_a_folder", "system_folder", "inside_app", "is_support_dir", "not_writable"],
    doc="Why a folder can't be the music folder.")
SetupStep = alias(
    "SetupStep", Literal["music", "tools", "spotify", "downloads", "playlists"],
    doc="The required step `setup_status` names next; `downloads` is Qobuz signed in or left out.")


@shape
class MusicStatus(TypedDict):
    """The music folder (spec public-release §4)."""
    state: Annotated[MusicState, F("Where the folder stands.")]
    path: Annotated[str | None, F("The bound or missing folder; null while none is chosen.")]
    suggested: Annotated[str, F("The default to offer (`~/Music/Discjockey`).")]


@shape
class FolderCheck(TypedDict):
    """What `check_music_folder(path)` found; it changes nothing."""
    path: Annotated[str, F("The resolved folder.")]
    exists: Annotated[bool, F("Whether the folder is there.")]
    usable: Annotated[bool, F("Whether it can be the music folder; false: `problem` names why.")]
    problem: Annotated[FolderProblem | None, F("Why it is not usable, else null.")]
    kind: Annotated[FolderKind | None, F("What a usable folder holds; null when it is not usable.")]
    message: Annotated[str | None, F("The refusal in plain words; null when usable.")]


@shape
class MusicFolderAnswer(TypedDict):
    """The answer of `retry_music_folder`: the status after the try."""
    music: Annotated[MusicStatus, F("Where the music folder stands now.")]


@shape
class MusicFolderSet(TypedDict):
    """The answer of `set_music_folder(path)`: it answers at once, no job."""
    music: Annotated[MusicStatus, F("Where the music folder stands now.")]
    restart: Annotated[bool, F("True when the choice is saved but the open window keeps its library: ask to reopen, "
                               "then `quit()`.")]


@shape
class AppUpdate(TypedDict):
    """The update check's last answer (event `AppUpdate`); it never touches the network."""
    state: Annotated[Literal["available", "up_to_date", "unknown"], F(
        "`unknown`: no answer yet (offline, rate limit, or a version that is not plain); the page shows nothing.")]
    current: Annotated[str, F("This app's version.")]
    latest: Annotated[str | None, F("The newest version; only for `available`.")]
    url: Annotated[str | None, F("The release page; only for `available`.", shown=False)]


@shape
class LastCheck(TypedDict):
    """A saved login check (settings.json): when it ran and what it found."""
    ok: Annotated[bool, F("Whether the login worked.")]
    problem: Annotated[str | None, F("What was wrong, else null.")]
    kbps: Annotated[int | None, F("The stream quality found, else null.")]
    at: Annotated[str, F("When the check ran, an ISO time.")]


@shape
class AccountStatus(TypedDict):
    """A YouTube or SoundCloud account that is set up."""
    browser: Annotated[Browser, F("The browser the login is read from.", shown=False)]
    browser_name: Annotated[str, F("The browser's name.")]
    daily_limit: Annotated[int, F("How many downloads a day the account may make.")]
    profile: Annotated[str | None, F("The browser profile's folder; null: the default one, or Safari's only one.",
                                     shown=False)]
    profile_name: Annotated[str | None, F("The profile's display name; null when it can't be read.")]
    last_check: Annotated[LastCheck | None, F("The last login check; null when never checked since it was saved.")]


@shape
class SetupStatusTools(TypedDict):
    """Which tools are found."""
    ffmpeg: Annotated[bool, F("ffmpeg is found.")]
    ffprobe: Annotated[bool, F("ffprobe is found.")]
    deno: Annotated[bool, F("deno is found.")]


@shape
class SetupStatusAccounts(TypedDict):
    """The two accounts of the download logins."""
    youtube: Annotated[AccountStatus | None, F("The YouTube account, or null when none is set up.")]
    soundcloud: Annotated[AccountStatus | None, F("The SoundCloud account, or null when none is set up.")]


@shape
class SetupStatusYoutubeMusic(TypedDict):
    """YouTube Music's Liked music."""
    liked_music: Annotated[bool, F("Settings' \"Read my Liked music\" is on (it only counts with a YouTube account: "
                                   "forgetting that login turns it off for good).")]
    can_turn_on: Annotated[bool, F("A YouTube account is set up.")]
    listed: Annotated[bool, F("A Liked music line is in playlists.txt, switched on or off.")]


@shape
class SetupStatus(TypedDict):
    """What is set up (`setup_status()`): open the wizard while `complete` is false. It never carries a secret, only
    whether it is there. Setup's \"Your existing music\" step is not among the required ones: `existing` never changes
    `next_step` or `complete` and never blocks Continue."""
    music: Annotated[MusicStatus, F("The music folder; unbound, `playlists` and `complete` are false.")]
    tools: Annotated[SetupStatusTools, F("Which tools are found.")]
    spotify_app: Annotated[bool, F("The Spotify Client ID is saved.")]
    spotify_login: Annotated[bool, F("The Spotify login is there.")]
    qobuz: Annotated[bool, F("The Qobuz login is saved (stays false when Qobuz was left out).")]
    playlists: Annotated[bool, F("playlists.txt has playlists.")]
    complete: Annotated[bool, F("Every required step is done.")]
    next_step: Annotated[SetupStep | None, F("The first required step not done, null when none.")]
    version: Annotated[str, F("`discjockey.__version__` (Settings → About shows it).")]
    qobuz_skipped: Annotated[bool, F("\"I don't have Qobuz\": the Downloads step counts as done.")]
    spotify_skipped: Annotated[bool, F("\"I don't use Spotify\": the Spotify step counts as done; connecting Spotify "
                                       "clears it.")]
    youtube_music: Annotated[SetupStatusYoutubeMusic, F("YouTube Music's Liked music.")]
    auto_upgrade: Annotated[bool, F("\"Upgrade automatically when I sync\" (Settings, Setup's Downloads step): on by "
                                    "default; false too when settings.json can't be read.")]
    existing: Annotated[bool, F("Setup's \"Your existing music\" step is done: an import folder is watched or it was "
                                "skipped.")]
    import_folders: Annotated[int, F("The import folders watched.")]
    import_skipped: Annotated[bool, F("Skip was pressed on \"Your existing music\" (`setup_skip_import`).")]
    qobuz_last_check: Annotated[LastCheck | None, F("The saved Qobuz login check, null when none.")]
    spotify_user: Annotated[str | None, F("The Spotify account's display name saved at login; null when not "
                                          "connected or not known.")]
    accounts: Annotated[SetupStatusAccounts, F("The YouTube and SoundCloud accounts.")]


@shape
class RekordboxStatus(TypedDict):
    """rekordbox on this Mac now: its library's state and whether it runs; the window's pair."""
    state: Annotated[Literal["ready", "none", "unreadable"], F("What rekordbox's library is like.")]
    running: Annotated[bool, F("Whether rekordbox runs.")]


@shape
class RekordboxStatusAnswer(RekordboxStatus):
    """What `rekordbox_status()` answers: the window's pair plus the command line's richer answer (the window reads
    `state` and `running` only). It works without a music folder and answers from a cache while a writer holds
    `rekordbox.lock`."""
    state_text: Annotated[str, F("The state in words.")]
    problem: Annotated[Literal["unclean", "busy", "key", "db_version", "schema"] | None,
                       F("What is wrong with the library, else null.")]
    problem_text: Annotated[str | None, F("The problem in words, else null.")]
    version: Annotated[str | None, F("rekordbox's version, null where unknown.")]
    library: Annotated[str | None, F("master.db's path, null where unknown.", shown=False)]
    db_version: Annotated[str | None, F("master.db's DB version, null where unknown.")]
    modified_at: Annotated[str | None, F("master.db's modified time (local ISO, to the second), null where unknown.")]
    size: Annotated[int | None, F("master.db's size in bytes, null where unknown.")]
    writing: NotRequired[Annotated[bool, F("Present (true) while a Discjockey writer holds `rekordbox.lock`: `state` "
                                           "is then the last value read.")]]
    as_of: NotRequired[Annotated[str | None, F("With `writing`: when that value was read (an ISO time), null when "
                                                "none was read yet.")]]


# --- logins, the download sources, the tools ---

@shape
class LoginBrowserProfile(TypedDict):
    """One browser profile and whether it holds a login."""
    id: Annotated[str | None, F("The profile's folder; null is Safari's only profile.", shown=False)]
    name: Annotated[str, F("The profile's display name.")]
    signed_in: Annotated[bool, F("Whether the profile holds a login of the service.")]


@shape
class LoginBrowser(TypedDict):
    """An installed browser."""
    id: Annotated[Browser, F("The browser.", shown=False)]
    name: Annotated[str, F("Its name.")]
    default: Annotated[bool, F("The Mac's default browser.")]
    readable: Annotated[bool, F("Whether its login files can be read.")]
    problem: Annotated[Literal["no_access", "locked"] | None, F(
        "Why it can't be read: `no_access` (Safari without Full Disk Access) or `locked`; else null.")]
    profiles: Annotated[list[LoginBrowserProfile], F("Its profiles and which hold a login.")]


@shape
class FindLogins(TypedDict):
    """`find_logins(service)`: the installed browsers, the default first, and which profiles hold a login."""
    browsers: Annotated[list[LoginBrowser], F("The installed browsers, the default one first.")]


@shape
class DownloadsViewQobuz(TypedDict):
    """The Qobuz rung of the ladder."""
    state: Annotated[Literal["on", "off", "skipped", "paused", "used_up"], F(
        "`on`; `off` (not signed in, or its last login check failed); `skipped` (\"I don't have Qobuz\"); `paused` "
        "(stopped itself today); `used_up` (today's allowance used).")]
    last_check: Annotated[LastCheck | None, F("The last login check; null when never checked since it was saved.")]
    tracks: Annotated[int, F("Live tracks from Qobuz.")]


@shape
class DownloadsAccount(TypedDict):
    """A YouTube or SoundCloud rung of the ladder and its account panel."""
    state: Annotated[Literal["on", "off", "no_premium", "unreadable", "paused", "used_up"], F(
        "`on`; `off` (not set up, or its last check found no login / failed); `no_premium` (YouTube: a free login, "
        "used only for Liked music); `unreadable` (macOS did not let Discjockey read the browser's login); `paused`; "
        "`used_up`.")]
    browser: Annotated[Browser | None, F("The browser the login is read from, null when not set up.", shown=False)]
    browser_name: Annotated[str | None, F("The browser's name, null when not set up.")]
    profile: Annotated[str | None, F("The browser profile's folder; null: the default one.", shown=False)]
    profile_name: Annotated[str | None, F("The profile's display name; null when it can't be read.")]
    last_check: Annotated[LastCheck | None, F("The last login check; null when never checked since it was saved.")]
    tracks: Annotated[int, F("The library's live lossy tracks this account brought in at about 256 kbps.")]


@shape
class DownloadsViewLibrary(TypedDict):
    """The library's live tracks (in a playlist, not hidden) counted by rung."""
    lossless: Annotated[int, F("Lossless tracks (an artist's lossless original counts here).")]
    account: Annotated[int, F("Lossy stream downloads at 200 kbps or more.")]
    free: Annotated[int, F("The lower or unknown ones.")]


@shape
class DownloadsView(TypedDict):
    """The source ladder and the account panels of Settings and Setup (spec settings-setup §6.4): each download
    source's state and the library counted by rung. Without a music folder the library counts are zero."""
    qobuz: Annotated[DownloadsViewQobuz, F("The Qobuz rung.")]
    youtube: Annotated[DownloadsAccount, F("The YouTube account.")]
    soundcloud: Annotated[DownloadsAccount, F("The SoundCloud account.")]
    library: Annotated[DownloadsViewLibrary, F("The library counted by rung.")]


@shape
class DownloadsViewAnswer(TypedDict):
    """The answer of `downloads_view()`."""
    downloads: Annotated[DownloadsView, F("The ladder and the panels.")]


@shape
class AccountCheck(TypedDict):
    """A login checked again."""
    ok: Annotated[bool, F("Whether the login is usable.")]
    problem: Annotated[Literal["cookies_unreadable", "not_logged_in", "no_premium", "failed"] | None,
                       F("What is wrong, else null.")]
    kbps: Annotated[int | None, F("The stream quality found, else null.")]
    message: Annotated[str, F("The sentence to show.")]


@shape
class DownloadTool(TypedDict):
    """One download tool in Settings → This Mac."""
    version: Annotated[str | None, F("What this window runs; null: not installed.")]
    source: Annotated[Literal["built_in", "updated"], F("`built_in` came with Discjockey, `updated` was brought by "
                                                         "Update download tools.")]
    waiting: Annotated[str | None, F("The version the next start uses, when it differs: an update or a step back "
                                     "waits for a reopen.")]
    previous: Annotated[str | None, F("What Go back would use; null: nothing to go back to.")]


# `yt-dlp` is no Python name, so the shape is written in the functional form
DownloadTools = alias(
    "DownloadTools", dict[str, DownloadTool],
    doc="The two download tools by name: `yt-dlp`, and `streamrip` (always `built_in` with null `waiting` and "
        "`previous`). Keyed by name because `yt-dlp` is no identifier.")


@shape
class SetupToolsTools(TypedDict):
    """Which tools are found."""
    ffmpeg: Annotated[bool, F("ffmpeg is found.")]
    ffprobe: Annotated[bool, F("ffprobe is found.")]
    deno: Annotated[bool, F("deno is found.")]


@shape
class SetupTools(TypedDict):
    """What `setup_check_tools()` found, and the download tools of Settings → This Mac."""
    tools: Annotated[SetupToolsTools, F("Which tools are found.")]
    missing: Annotated[list[str], F("The tools not found.")]
    hints: Annotated[dict[str, str], F("For each missing tool, how to get it.")]
    redirect_uri: Annotated[str, F("The Spotify redirect address to enter in the Spotify app.", shown=False)]
    download_tools: Annotated[DownloadTools | None, F(
        "The download tools; null when reading them failed unexpectedly (`download_tools_problem` says so).")]
    download_tools_problem: Annotated[str | None, F("A plain sentence when `download_tools` is null, else null.")]


@shape
class ToolsChange(TypedDict):
    """The result of `update_tools` and `rollback_tools`: the version the next start uses before and after."""
    before: Annotated[dict[str, str | None], F("The version the next start uses before, per tool.")]
    after: Annotated[dict[str, str | None], F("The version the next start uses after, per tool.")]
    restart: Annotated[bool, F("True when that is not the version this window runs: ask to reopen, then `quit()`.")]


@shape
class AccountSaved(TypedDict):
    """The result of `setup_account` and `account_sign_in`: the login checked and saved (a login without Premium or
    Go+ is saved too)."""
    service: Annotated[Service, F("The service.")]
    browser: Annotated[Browser, F("The browser.", shown=False)]
    profile: Annotated[str | None, F("The profile whose login was found; null: the default one.", shown=False)]
    saved: Annotated[bool, F("Whether the login was saved.")]
    check: Annotated[AccountCheck, F("What the check found.")]


@shape
class AccountForgotten(TypedDict):
    """The result of `setup_forget_account`."""
    service: Annotated[Service, F("The service whose saved browser was removed.")]


@shape
class SpotifyLogin(TypedDict):
    """The result of `setup_spotify_login`."""
    user: Annotated[str, F("The Spotify account's display name.")]


@shape
class LikedMusicAdded(TypedDict):
    """The result of `add_liked_music`."""
    folder: Annotated[str, F("The folder the Liked music line got (`Liked_music`, or `Liked_music_2`, ... when taken).")]


@shape
class AutoUpgradeSet(TypedDict):
    """The result of `set_auto_upgrade`."""
    auto_upgrade: Annotated[bool, F("The value saved (the window ignores it, the command line says it).")]


# --- reads with network ---

@shape
class Candidate(TypedDict):
    """One version of a song a source offers; send it back unchanged to `preview` and `use_candidate`."""
    source: Annotated[str, F("The source (`Source`'s values, or another word the engine reports).")]
    id: Annotated[str, F("The source's id of the version.", shown=False)]
    title: Annotated[str, F("The title.")]
    artist: Annotated[str, F("The artist.")]
    duration_s: Annotated[float | None, F("The length in seconds, else null.")]
    url: Annotated[str | None, F("Where the version is, else null.", shown=False)]
    isrc: Annotated[str | None, F("The ISRC, else null.", shown=False)]
    album: Annotated[str | None, F("The album, else null.")]
    label: Annotated[str | None, F("The label, else null.")]
    image_url: Annotated[str | None, F("The cover's address, else null.", shown=False)]
    key: Annotated[str, F("The version's key.", shown=False)]
    source_name: Annotated[str, F("The source in short words.")]
    length_diff_s: Annotated[float | None, F("The length against the song's, in seconds (green within 3 s); null when "
                                             "one is unknown.")]
    can_preview: Annotated[bool, F("Whether `preview` can play it (not a Qobuz version).")]
    score: Annotated[float | None, F("How well it matches, 0 to 100; null when not scored.")]
    matches: Annotated[bool, F("Whether it matches the song.")]
    length_ok: Annotated[bool, F("Whether its length is close enough.")]
    current: Annotated[bool, F("The version in the library now (listed first).")]
    rejected: Annotated[bool, F("The user marked it as wrong.")]


@shape
class Candidates(TypedDict):
    """`search_candidates(track_id)`: the versions the sources offer, the current one first."""
    track_id: Annotated[str, F("The song's id.", shown=False)]
    track_duration_s: Annotated[float, F("The song's length in seconds.")]
    current_quality_label: Annotated[str, F("The words of the current file's quality.")]
    candidates: Annotated[list[Candidate], F("The versions.")]
    notes: Annotated[list[str], F("Lines about the search.")]


@shape
class PreviewAnswer(TypedDict):
    """`preview(track_id, candidate)`: 30 seconds of a version (youtube_music, soundcloud, youtube only)."""
    url: Annotated[str, F("A media address `<audio>` plays.", shown=False)]


@shape
class AddedPlaylist(TypedDict):
    """`add_playlist(url)`: a pasted link read through its service's reader. Add the row with `link` and
    `suggested_folder`."""
    playlist_id: Annotated[str, F("The playlist's ref (see `playlists()`).", shown=False)]
    service: Annotated[PlaylistService, F("The service.")]
    service_name: Annotated[str, F("The service's name.")]
    link: Annotated[str, F("The link to store.", shown=False)]
    info: Annotated[PlaylistInfo | None, F("What the service says of the playlist, null when not readable.")]
    tracks: Annotated[int | None, F("How many tracks, null when neither the tracks nor the count were read.")]
    readable: Annotated[bool, F("Whether the service shows the playlist.")]
    suggested_folder: Annotated[str, F("The folder name to offer (editable).")]
    hint: Annotated[str | None, F("When not readable: the service's words, the same as `info.hint`; else null.")]


ChangeKind = alias(
    "ChangeKind", Literal["moves", "rename", "reroute", "add", "switch_off", "unknown", "none"],
    doc="What a playlist edit would do: `moves` or `rename` (files would sit in another folder), `reroute` (only "
        "tracks without a file change folder), `add`, `switch_off` (a playlist is left out of the sync and nothing "
        "else changes), `unknown` or `none`.")


@shape
class ChangePreviewFolder(TypedDict):
    """A folder whose file count a change alters."""
    folder: Annotated[str, F("The folder.")]
    before: Annotated[int, F("Its files before the change.")]
    after: Annotated[int, F("Its files after (0 for a switched-off playlist's folder).")]




RenameOffer = _record(
    "RenameOffer",
    "A folder rename on disk a save could do: one per playlist whose folder name changes other than in case and whose "
    "old folder is in `Library/`.",
    {
        "from": Annotated[str, F("The playlist folder's old name.")],
        "to": Annotated[str, F("The new folder name.")],
        "files": Annotated[int, F("How many files are in the folder.")],
        "offered": Annotated[bool, F("False: show `why_not` instead of the choice.")],
        "why_not": Annotated[str | None, F("Why the rename is not offered (\"A folder called {new} is already in your "
                                           "Library.\"); else null.")],
        "option": Annotated[str, F("The choice's label (\"Rename the folder on disk too\").")],
        "detail": Annotated[str, F("The choice's detail (\"One folder move instead of {n} file moves.\").")],
    })


# --- the move log and the tidy-up (the ones the tidy preview and the playlist-change preview share) ---

@shape
class TidySkip(TypedDict):
    """Why a file can't be moved."""
    reason: Annotated[Literal["offline", "not_found", "name_taken"], F("The code.")]
    text: Annotated[str, F("The plain words to show (\"Offline, skipped\", \"Not where Discjockey last saw it\", \"A "
                           "file with this name is already in {to}\"); such a row can't be ticked.")]


TidyRow = _extend(TrackRow, "TidyRow", "One file a tidy-up could move: a track row plus where it goes.", {
    "file_id": Annotated[int, F("The file's id.", shown=False)],
    "from": Annotated[str, F("The folder it is in, relative to `Library/` (`\"\"` is `Library` itself, shown "
                             "\"Library\").")],
    "to": Annotated[str, F("The folder the playlist order puts it in, relative to `Library/`.")],
    "from_path": Annotated[str, F("The snapshot path the page sends back to `tidy_up` and `save_playlists`.",
                                  shown=False)],
    "placed_by": Annotated[Literal["app", "user", "import"], F("Who put the file where it is.")],
    "ticked": Annotated[bool, F("Moves by default: no `skip` and placed by the app.")],
    "yours": Annotated[bool, F("Placed by the user or an import: the page marks it \"You put this here\" and lists "
                               "it apart.")],
    "skip": Annotated[TidySkip | None, F("Why it can't be moved, else null.")],
    "by_rename": Annotated[str | None, F("Save preview only: the old folder name whose rename on disk would put the "
                                         "file at its target; null in `tidy_preview`.")],
})


@shape
class TidyYours(TypedDict):
    """The \"You put these here\" group of the list, with its one control."""
    count: Annotated[int, F("How many rows are yours.")]
    movable: Annotated[int, F("How many of them can be moved.")]
    mark: Annotated[str, F("The mark on each row (\"You put this here\").")]
    header: Annotated[str, F("The group's header.")]
    control: Annotated[str, F("The control's label (\"Put these in playlist order too\"): it ticks every movable row "
                              "of the group.")]


@shape
class TidyPreview(TypedDict):
    """`tidy_preview()`: every file the playlist order puts somewhere else (\"Tidy up files\")."""
    rows: Annotated[list[TidyRow], F("The files a tidy-up could move.")]
    ticked: Annotated[int, F("How many rows are ticked by default.")]
    rekordbox: Annotated[list[str], F("Two lines for the confirmation.")]
    undo_note: Annotated[str, F("\"You can undo this on this page.\"")]
    empty: Annotated[str | None, F("Null, or the text shown instead of the list (nothing out of place, or only `yours` "
                                   "rows left: the button then stays usable).")]
    yours: Annotated[TidyYours | None, F("The \"You put these here\" group; null when no row is `yours`.")]


@shape
class MoveBatch(TypedDict):
    """One batch of moves in the log."""
    id: Annotated[int, F("The batch's id.", shown=False)]
    at: Annotated[str, F("When it started, an ISO time.")]
    title: Annotated[str, F("\"Tidy-up\", \"Saved playlists\", \"Renamed {old} to {new}\" or \"Undo of: {title}\".")]
    moved: Annotated[int, F("The files moved (a folder rename counts the files it carried).")]
    skipped: Annotated[int, F("The moves not made.")]
    undoable: Annotated[int, F("How many moves an undo could still make today; 0: the Undo button reads \"Nothing left "
                               "to undo\".")]
    undone_by: Annotated[int | None, F("The id of the latest undo of it, else null.", shown=False)]
    summary: Annotated[str, F("\"{n} files moved\" / \"1 file moved\", plus \" · {k} not moved\".")]


@shape
class MoveBatches(TypedDict):
    """`move_batches()`: the 20 newest move batches, newest first; empty while nothing was ever moved."""
    batches: Annotated[list[MoveBatch], F("The newest batches.")]
    total: Annotated[int, F("How many batches there are in all.")]


@shape
class UndoSkip(TypedDict):
    """Why a move can't go back."""
    reason: Annotated[str, F("The code: `offline`, `not_found`, `name_taken` as for a tidy-up, or `moved_on`, "
                             "`place_taken`, `playlist_renamed`.")]
    text: Annotated[str, F("The plain words to show.")]


UndoRow = _record("UndoRow", "One move an undo would make.", {
    "label": Annotated[str, F("The file's or folder's name.")],
    "kind": Annotated[Literal["file", "folder"], F("`folder`: a folder rename going back.")],
    "files": Annotated[int | None, F("For a folder row how many files are in it now, else the count the rename "
                                     "carried; null for a file row.")],
    "from": Annotated[str, F("Where it is now.")],
    "to": Annotated[str, F("Where it goes back to.")],
    "skip": Annotated[UndoSkip | None, F("Why it can't go back, else null.")],
})


@shape
class UndoPreview(TypedDict):
    """`undo_preview(batch_id)`: what undoing a batch would do, move by move."""
    batch_id: Annotated[int, F("The batch.", shown=False)]
    title: Annotated[str, F("The batch's title.")]
    rows: Annotated[list[UndoRow], F("One row per move.")]
    moving: Annotated[int, F("How many files go back.")]
    warning: Annotated[list[str], F("Lines for the confirmation (rekordbox; for a folder rename also that the folder "
                                    "and the playlist get their old name back).")]
    nothing_left: Annotated[bool, F("No row can go back: the page offers no Undo.")]


SkippedMove = _record("SkippedMove", "A move that was not made.", {
    "label": Annotated[str, F("The file's or folder's name.")],
    "from": Annotated[str, F("Where it is.")],
    "to": Annotated[str, F("Where it would have gone.")],
    "reason": Annotated[str, F("The code.")],
    "text": Annotated[str, F("The plain words: those of `tidy_preview`'s and `undo_preview`'s `skip`, plus `changed` "
                             "\"Changed since the list was shown\", `failed` \"Couldn't move it: {why}\" and `stopped` "
                             "\"Not moved: the moves were stopped first\".")],
})


@shape
class BatchResult(TypedDict):
    """What a move batch tells the page: `tidy_up`, `undo_moves` and each item of `save_playlists`' `batches` finish
    with it (also with problem `stopped`, then `stopped` is true). Files never change their names in a move batch: only
    their folder changes."""
    batch_id: Annotated[int | None, F("The batch's id; null when nothing was asked to move.", shown=False)]
    title: Annotated[str, F("The batch's title.")]
    moved: Annotated[int, F("How many files moved (a folder rename counts the files it carried).")]
    headline: Annotated[str, F("The sentence to show: \"Moved {n} files.\" / \"Moved 1 file.\" (an undo: \"... back.\"), "
                               "plus \" {k} not moved:\" when some were skipped.")]
    skipped: Annotated[list[SkippedMove], F("The moves not made.")]
    stopped: Annotated[bool, F("The user stopped it.")]


@shape
class SavePlaylistsResult(TypedDict):
    """The result of `save_playlists`."""
    version: Annotated[str, F("The playlists' new version.", shown=False)]
    batches: Annotated[list[BatchResult], F("The move batches the save made, if any.")]


SaveFiles = _record("SaveFiles", "`save_playlists`' third argument: the answer to the save question.", {
    "choice": Annotated[Literal["leave", "move"], F("The answer to the save question.")],
    "renames": Annotated[list[tuple[str, str]], F("The folder renames to do on disk, `[old, new]`.", shown=False)],
    "moves": Annotated[list[tuple[int, str]], F("The files to move, `[file_id, from_path]`.", shown=False)],
})


@shape
class KeepFileResult(TypedDict):
    """The result of `keep_file`, also of a job that stopped after some moves (then `kept_track` is null)."""
    results: Annotated[list[Result], F("One report line per file that went to Superseded/, in the order they moved: "
                                       "`section` `replaced`, `path` where the file went (relative to the music "
                                       "folder). Fewer than the group's other files when a move stopped the job.")]
    recovered: Annotated[list[tuple[str, bool]], F("What a recovery of an earlier crash put right, `[what, ok]` per "
                                                   "line.")]
    kept_track: Annotated[str | None, F("The key of the song the kept file belongs to afterwards (a playlist song may "
                                        "have taken the file over from an own song); null when the file is linked to "
                                        "no song, or the job stopped before the end.")]


# --- the change a playlist edit would make ---

ChangeReroute = _extend(PlaylistTrack, "ChangeReroute", "A track without a file yet that will land in another folder.", {
    "from": Annotated[str, F("The folder it would have gone to.")],
    "to": Annotated[str, F("The folder it will go to.")],
})


@shape
class ChangePreviewTidy(TypedDict):
    """The files this change would put in another folder."""
    headline: Annotated[str, F("\"{n} files would sit in a different folder\".")]
    rows: Annotated[list[TidyRow], F("The files, each with `by_rename` set when a rename on disk would move it.")]


@shape
class ChangePreview(TypedDict):
    """`preview_playlist_change(lines)`: what saving the playlist lines would do. A switched-on line not read yet is
    read once through its service's reader; a service that is not connected, or a playlist its service won't show, is
    skipped without an error."""
    kind: Annotated[ChangeKind, F("What the edit does.")]
    headline: Annotated[str, F("Ready to show.")]
    folders: Annotated[list[ChangePreviewFolder], F("The folders whose file count changes (a switched-off playlist's "
                                                    "folder has `after` 0 and is not shown as a change).")]
    tidy: Annotated[ChangePreviewTidy | None, F("The files this change would put in another folder, null when none.")]
    renames: Annotated[list[RenameOffer], F("The folder renames on disk the save could do.")]
    reroutes: Annotated[list[ChangeReroute], F("Tracks without a file yet that will land in another folder.")]
    new_downloads: Annotated[int, F("How many tracks are new to download.")]
    days: Annotated[int, F("How many days of downloads that is.")]
    stopped: Annotated[int, F("How many songs a switched-off playlist stops syncing.")]
    unknown: Annotated[list[str], F("The lines whose playlist is not known.")]
    checklist: Annotated[list[str], F("Three or four lines for the confirmation.")]
    problem: Annotated[str | None, F("What is wrong with the lines (Save would be refused), else null.")]


# --- watched folders and the import ---

ImportPhase = alias("ImportPhase", Literal["scan", "facts", "tags", "sound", "link"],
                    doc="A phase of the import (`ImportProgress` events).")
ImportFolderProblem = alias(
    "ImportFolderProblem",
    Literal["not_absolute", "not_a_folder", "system_folder", "inside_app", "is_support_dir", "not_writable",
            "not_readable", "not_found", "music", "holds_music", "watched", "already"],
    doc="Why a folder can't be watched: a `FolderProblem`, or `not_readable`, `not_found`, `music` (inside the music "
        "folder), `holds_music` (holds it), `watched` (inside a watched folder) or `already`.")


@shape
class WatchedFolderRow(TypedDict):
    """A watched folder: the Library (always `online`, `scanning` while an import looks for files) or an import
    folder."""
    id: Annotated[int, F("The folder's id.", shown=False)]
    path: Annotated[str, F("The folder's path.")]
    name: Annotated[str, F("Its name (\"Library\" for the Library).")]
    kind: Annotated[Literal["library", "import"], F("The Library or an import folder.")]
    state: Annotated[Literal["online", "offline", "missing", "scanning", "importing"], F(
        "`offline`: its drive is not connected; `missing`: the folder is not a folder now (moved, renamed or "
        "deleted); `scanning`: an import is looking for files; `importing`: one runs and this folder has files it "
        "has not finished.")]
    files: Annotated[int, F("The tracks the folder lists, the same number the sidebar shows for it.")]
    waiting: Annotated[int, F("Files the import still works through (not read yet, or not sound-checked).")]
    unreadable: Annotated[int, F("Files it could not read.")]
    crates: Annotated[list[Crate], F("All the folder's crates in label order, hidden ones too, with the user's "
                                     "switches applied (Settings' switches); the Library row has none.")]
    too_many: Annotated[bool, F("More than 25 crates, so they start hidden.")]


@shape
class UnreadableFile(TypedDict):
    """A file the import could not read."""
    folder_id: Annotated[int | None, F("The id of its folder.", shown=False)]
    path: Annotated[str, F("The file's path.")]
    reason: Annotated[str, F("Why, in words (\"macOS doesn't let Discjockey read it\", \"Discjockey can't find sound "
                             "it can read in it\", \"The file is empty\").")]


@shape
class WatchedFolders(TypedDict):
    """`watched_folders()`: the Library first, then the import folders by id. The live phase and counts of an import
    come from the `ImportProgress` event, not from here."""
    folders: Annotated[list[WatchedFolderRow], F("The watched folders.")]
    unreadable: Annotated[list[UnreadableFile], F("The files it could not read, in the Library and every import "
                                                  "folder.")]
    waiting: Annotated[int, F("The files an import would work through now (offline drives' left out).")]
    stopped: Annotated[bool, F("The user stopped an import (kept in library.db until Continue import): offer Continue import.")]


@shape
class ImportFolderCheck(TypedDict):
    """What `check_import_folder(path)` found; it changes nothing."""
    path: Annotated[str, F("The resolved folder.")]
    exists: Annotated[bool, F("Whether the folder is there.")]
    usable: Annotated[bool, F("Whether it can be watched; false: `problem` names why.")]
    problem: Annotated[ImportFolderProblem | None, F("Why it can't be watched, else null.")]
    kind: Annotated[Literal["import"] | None, F("`import` for a usable folder, else null.")]
    message: Annotated[str | None, F("The refusal's words, else null.")]
    merges: Annotated[list[str], F("The paths of the watched folders inside it that it would take over (their files "
                                   "and links are kept).")]
    merge_hints: Annotated[list[str], F("One line each (\"{name} is inside it and becomes part of it.\").")]


@shape
class RemovalPreview(TypedDict):
    """`removal_preview(folder_id)`, and the result of `remove_watched_folder` (job `folders`)."""
    name: Annotated[str, F("The folder's name.")]
    files: Annotated[int, F("The folder's file count.")]
    redownload: Annotated[int, F("The playlist songs whose only file is there (they download again at the next "
                                 "sync).")]


@shape
class ImportResult(TypedDict):
    """The result of the `import` job (`add_watched_folder`, `start_import`), also of a stopped one (`stopped` true)."""
    files: Annotated[int, F("The files imported (read in either pass, not unreadable now).")]
    own_songs: Annotated[int, F("The user's own songs found.")]
    sound_checked: Annotated[int, F("The files whose sound was checked.")]
    unreadable: Annotated[int, F("The files it could not read.")]
    left: Annotated[int, F("The files the next import still works through.")]
    stopped: Annotated[bool, F("The user stopped it.")]
    link_note: Annotated[str | None, F("The words of a link that did not happen, else null.")]


# --- the AIFF plan ---

AiffKind = alias(
    "AiffKind", str,
    doc="The kind of an item in the panel's order: `flac`, `wav`, `alac`, `aiff_hires` (an AIFF that is not 16-bit / "
        "44.1 kHz), `tags` (a 16/44.1 AIFF whose tags are not the download's), `name` (a rename), `wavpack`, `ape`, "
        "`tta`, `mp3`, `aac`, `opus`, `vorbis`, then any other codec by its own name.")


@shape
class AiffScopeTracks(TypedDict):
    """A selection of songs."""
    kind: Annotated[Literal["tracks"], F("The selection.", shown=False)]
    tracks: Annotated[list[str], F("The songs' keys, each song once.", shown=False)]


@shape
class AiffScopeLossless(TypedDict):
    """A view's own lossless files, as `library()` lists them without filter or search."""
    kind: Annotated[Literal["lossless"], F("A view's lossless files.", shown=False)]
    view: Annotated[LibraryView, F("Which view.", shown=False)]
    key: Annotated[str | None, F("The playlist or folder; null for `all` and `unlisted`.", shown=False)]


@shape
class AiffScopeCdj(TypedDict):
    """To-do's \"Won't play well on CDJs\" group."""
    kind: Annotated[Literal["cdj"], F("The CDJ group.", shown=False)]


AiffScope = alias(
    "AiffScope", AiffScopeTracks | AiffScopeLossless | AiffScopeCdj,
    doc="What `aiff_plan`, `convert`, `rename` and `make_aiff` take: a selection, a view's lossless files, or the CDJ "
        "group.")


@shape
class AiffPlanScopeTracks(AiffScopeTracks):
    """The plan's scope for a selection."""
    label: Annotated[str, F("\"Selection\".")]


@shape
class AiffPlanScopeLossless(AiffScopeLossless):
    """The plan's scope for a view."""
    label: Annotated[str, F("The view's title.")]


@shape
class AiffPlanScopeCdj(AiffScopeCdj):
    """The plan's scope for the CDJ group."""
    label: Annotated[str, F("\"Won't play well on CDJs\".")]


AiffPlanScope = alias("AiffPlanScope", AiffPlanScopeTracks | AiffPlanScopeLossless | AiffPlanScopeCdj,
                      doc="The scope as asked plus its `label`.")

AiffPlanItem = _record(
    "AiffPlanItem",
    "One file the run would change. `path`, `new_path` and `superseded` are relative to the music folder (an own file "
    "in a watched folder: absolute).",
    {
        "track": Annotated[str, F("The song's key.", shown=False)],
        "name": Annotated[str, F("The song's name.")],
        "action": Annotated[Literal["convert", "rename"], F("What the run does.")],
        "kind": Annotated[AiffKind, F("The kind of item.")],
        "from": Annotated[str, F("The format line (\"FLAC · 24-bit · 96 kHz\", \"MP3 · 44.1 kHz · 320 kbps\").")],
        "path": Annotated[str, F("The file now.")],
        "new_path": Annotated[str, F("Where it will be (a Convert whose AIFF takes the name the old file held ends at "
                                     "the old path).")],
        "superseded": Annotated[str | None, F("Where the old file goes (Convert only); null for a rename.")],
        "bytes": Annotated[int, F("The room the render needs; a rename needs none.")],
        "cdj": Annotated[CdjWords | None, F("What the CDJs refuse in the file, or null.")],
    })


@shape
class AiffLeft(TypedDict):
    """A file of a `tracks` scope that is left as it is."""
    track: Annotated[str, F("The song's key.", shown=False)]
    name: Annotated[str, F("The song's name.")]
    reason: Annotated[str, F("An `EligibleReason` key (`named_already`, `downloaded`, `needs_convert`, `away`, ...).")]
    message: Annotated[str, F("Its words.")]


@shape
class AiffPlanWaiting(TypedDict):
    """Files that can't run now but may later."""
    reason: Annotated[str, F("Why they wait.")]
    message: Annotated[str, F("Its words.")]
    n: Annotated[int, F("How many files.")]


@shape
class AiffPlanKind(TypedDict):
    """A kind of item with files."""
    kind: Annotated[AiffKind, F("The kind.", shown=False)]
    label: Annotated[str, F("The panel's line (\"FLAC → AIFF\", \"New tags\", \"Clean name only\").")]
    n: Annotated[int, F("How many items.")]


@shape
class AiffPlanSpace(TypedDict):
    """The room the new files need on one drive."""
    drive: Annotated[str, F("A folder on the drive.")]
    needed: Annotated[int, F("Bytes needed.")]
    free: Annotated[int, F("Bytes free.")]
    enough: Annotated[bool, F("Whether the room is enough.")]


@shape
class AiffPlanRekordbox(TypedDict):
    """rekordbox as the plan found it."""
    state: Annotated[Literal["ready", "none", "unreadable"], F("What rekordbox's library is like.")]
    running: Annotated[bool, F("Whether rekordbox runs.")]
    needs_closed: Annotated[bool, F("True when an item's file is in rekordbox's library: it must be closed.")]
    writing: NotRequired[Annotated[bool, F("Only present (true) when a writer held `rekordbox.lock`: the plan took "
                                           "the cached state and no lookup of rekordbox's tracks.")]]


@shape
class AiffPlan(TypedDict):
    """The read-only plan behind a selection's Convert, Rename, Make all lossless files AIFF and the CDJ group's
    Convert all (`aiff_plan.AiffPlan.to_dict`)."""
    scope: Annotated[AiffPlanScope, F("The scope as asked plus `label`.")]
    items: Annotated[list[AiffPlanItem], F("The files the run would change, in order.")]
    skipped: Annotated[list[AiffLeft], F("A `tracks` scope only: the songs left as they are.")]
    waiting: Annotated[list[AiffPlanWaiting], F("Files that can't run now but may later, each once and never an "
                                                "item, in the order away, file_missing, no_name, "
                                                "rekordbox_unreadable, cloud, rename_blocked, upgrade_waits.")]
    kinds: Annotated[list[AiffPlanKind], F("The kinds with files, in the panel's order.")]
    lossy: Annotated[int, F("How many items have a lossy file now (their AIFF sounds the same, only the format "
                            "changes).")]
    total: Annotated[int, F("How many items.")]
    space: Annotated[list[AiffPlanSpace], F("The room the new files need per drive; a rename needs none.")]
    superseded_bytes: Annotated[int, F("What `Superseded/` takes.")]
    rekordbox: Annotated[AiffPlanRekordbox, F("rekordbox as the plan found it.")]


@shape
class AiffPlanAnswer(TypedDict):
    """The answer of `aiff_plan(scope)`."""
    plan: Annotated[AiffPlan, F("The plan.")]


ANSWERS: dict[str, str] = {
    "setup_status": "SetupStatus", "check_music_folder": "FolderCheck", "retry_music_folder": "MusicFolderAnswer",
    "set_music_folder": "MusicFolderSet", "rekordbox_status": "RekordboxStatusAnswer", "app_update": "AppUpdate",
    "downloads_view": "DownloadsViewAnswer", "find_logins": "FindLogins", "setup_check_tools": "SetupTools",
    "watched_folders": "WatchedFolders", "check_import_folder": "ImportFolderCheck",
    "removal_preview": "RemovalPreview", "tidy_preview": "TidyPreview", "move_batches": "MoveBatches",
    "undo_preview": "UndoPreview", "search_candidates": "Candidates", "preview": "PreviewAnswer",
    "add_playlist": "AddedPlaylist", "preview_playlist_change": "ChangePreview", "aiff_plan": "AiffPlanAnswer",
    "setup_skip_import": "Empty",
    # J methods: the shape of the job's result
    "save_playlists": "SavePlaylistsResult", "tidy_up": "BatchResult", "undo_moves": "BatchResult",
    "add_watched_folder": "ImportResult", "remove_watched_folder": "RemovalPreview", "start_import": "ImportResult",
    "answer_same_song": "Empty", "keep_duplicates": "Empty", "keep_file": "KeepFileResult",
    "set_read_liked_music": "Empty", "add_liked_music": "LikedMusicAdded", "set_auto_upgrade": "AutoUpgradeSet",
    "setup_account": "AccountSaved", "account_sign_in": "AccountSaved", "qobuz_check_login": "Empty",
    "spotify_sign_out": "Empty", "setup_forget_account": "AccountForgotten", "setup_save_client_id": "Empty",
    "setup_spotify_login": "SpotifyLogin", "setup_qobuz_login": "Empty", "setup_skip_qobuz": "Empty",
    "setup_skip_spotify": "Empty", "update_tools": "ToolsChange", "rollback_tools": "ToolsChange",
    "convert": "AiffBatchResult", "rename": "AiffBatchResult", "make_aiff": "AiffBatchResult",
    "batch_resume": "AiffBatchResult", "batch_undo": "UndoResult",
}
RESULTS: dict[str, str] = {
    "import": "ImportResult", "folders": "RemovalPreview", "answer": "Empty", "supersede": "KeepFileResult",
    "save_playlists": "SavePlaylistsResult", "tidy": "BatchResult", "undo_moves": "BatchResult",
    "setup_skip_qobuz": "Empty", "setup_skip_spotify": "Empty", "set_read_liked_music": "Empty",
    "add_liked_music": "LikedMusicAdded", "set_auto_upgrade": "AutoUpgradeSet", "setup_account": "AccountSaved",
    "account_sign_in": "AccountSaved", "qobuz_check_login": "Empty", "spotify_sign_out": "Empty",
    "setup_forget_account": "AccountForgotten", "setup_save_client_id": "Empty",
    "setup_spotify_login": "SpotifyLogin", "setup_qobuz_login": "Empty", "update_tools": "ToolsChange",
    "rollback_tools": "ToolsChange", "aiff_batch": "AiffBatchResult", "batch_resume": "AiffBatchResult",
    "batch_undo": "UndoResult",
}
