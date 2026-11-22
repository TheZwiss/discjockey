"""The shapes of the dashboard, the sidebar, the Library, the Sync page's preview and the job snapshot, the playlists
page, Download limits, the run reports and the spectrum (issue 39, phase 2, E7c), and the results of the jobs that
read the playlists, start a sync, save a limit or scan the library. The meanings are those of
`docs/hub-bridge-contract.md` ("Read, any time").

`ANSWERS` maps a method to the shape of its answer without `ok` (a J method: the shape of its job's result); `RESULTS`
maps a job kind to the shape of its `JobFinished.result`."""
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from .common import (ByQuality, EmptyKind, ErrorKind, LibraryFilter, PlaylistService, ProblemKind, Quality,
                     Result, SettingKey, TrackRow, Which)
from .kernel import F, alias, shape
from .todo import AutoUpgradeBlock, FileState, TrackLink

Service = alias("Service", Literal["qobuz", "youtube", "soundcloud"],
                doc="A download service with a daily limit (Download limits): Qobuz, a YouTube Premium account or a "
                    "SoundCloud Go+ account.")
Browser = alias("Browser", Literal["safari", "chrome", "firefox", "brave", "edge"],
                doc="A browser whose login an account uses.")
FolderState = alias(
    "FolderState", Literal["here", "offline", "folder_missing"],
    doc="Where a folder is now: `here`, `offline` (its drive is not connected) or `folder_missing` (not found: moved, "
        "renamed, deleted); the innermost watched folder that is away decides, for its crates too.")
PreviewGroupKey = alias(
    "PreviewGroupKey", Literal["acquire:new", "acquire:retry", "acquire:redownload", "adopt_bought", "upgrade"],
    doc="A group of the Sync page's preview, in the order the page lists them: Download (new), Try again, Download "
        "again, Add a bought file, Look for a better version.")
LibraryView = alias("LibraryView", Literal["all", "unlisted", "playlist", "folder"],
                    doc="Which view of the Library: All tracks, Not in a playlist, a playlist or a folder.")
LibraryFileState = alias(
    "LibraryFileState", Literal["here", "offline", "folder_missing", "file_missing", "no_file"],
    doc="A row's file as the Library says it: a `FileState`, or `no_file` for a playlist song that has no file yet "
        "(only in a playlist view).")
SignalKind = alias(
    "SignalKind", Literal["login_failed", "search_failed", "download_rejected", "preview_only", "duration_mismatch",
                          "auto_stop"],
    doc="A kind of warning sign of Qobuz.")
AccountSignalKind = alias(
    "AccountSignalKind",
    Literal["cookies_unreadable", "bot_check", "rate_limited", "refused", "premium_missing", "download_rejected",
            "auto_stop"],
    doc="A kind of warning sign of a YouTube or SoundCloud account (SoundCloud has no `bot_check`).")
AnySignalKind = alias(
    "AnySignalKind",
    Literal["login_failed", "search_failed", "download_rejected", "preview_only", "duration_mismatch", "auto_stop",
            "cookies_unreadable", "bot_check", "rate_limited", "refused", "premium_missing"],
    doc="A kind of warning sign of any service: a `SignalKind` or an `AccountSignalKind`.")


# --- the read status, the plan's counts and the estimate ---

@shape
class ReadStatusService(TypedDict):
    """One playlist service the switched-on lines of playlists.txt use."""
    service: Annotated[PlaylistService, F("The service.")]
    name: Annotated[str, F("Its name for the page (Spotify, Qobuz, SoundCloud, YouTube Music).")]
    connected: Annotated[bool, F("Whether its login files exist.")]


@shape
class ReadStatus(TypedDict):
    """"Playlists read 2 min ago": how the last playlists read went (the wire field is `read_status`)."""
    read_at: Annotated[str | None, F("When the playlists were last read, an ISO time; null when none was.")]
    minutes_ago: Annotated[int | None, F("Whole minutes since `read_at`; null when none was read.", shown=False)]
    problem: Annotated[ProblemKind | None, F("The last read's problem kind (`offline`: the data shown is older); null "
                                             "when it went well.")]
    message: Annotated[str, F("The problem in words; empty when there is none.")]
    problem_service: Annotated[PlaylistService | None, F("The playlist service `problem` is about; null when no "
                                                         "service's problem. A good read clears it, and so does a "
                                                         "login made for that service (a good Setup or Settings "
                                                         "login, or a good Check again): the page never waits for "
                                                         "a restart.")]
    services: Annotated[list[ReadStatusService], F("The services the switched-on lines of playlists.txt use, in line "
                                                   "order.")]
    lines_changed: Annotated[bool, F("playlists.txt changed since this read: the plan below is from the old lines.")]
    reading: Annotated[bool, F("A read is running now.")]
    offline: Annotated[bool, F("The last read found no network (`problem` is `offline`).")]
    auto_read: Annotated[bool, F("The hub's one automatic read of this session has started (kept in Python, so also "
                                 "after a window reload).")]


@shape
class Budget(TypedDict):
    """One service's daily allowance today."""
    used: Annotated[int, F("Downloads that counted today.")]
    allowance: Annotated[int, F("What may be downloaded today: the limit, the carried-over days and the extra.")]
    limit: Annotated[int, F("The daily limit setting.")]
    carry_over: Annotated[int, F("What earlier days left unused.")]
    extra: Annotated[int, F("The one-time extra for today.")]
    remaining: Annotated[int, F("What is left of the allowance today.")]


@shape
class RunCounts(TypedDict):
    """What a run did, in four counts."""
    lossless: Annotated[int, F("Lossless songs it got.")]
    lossy: Annotated[int, F("Lossy songs it got.")]
    problems: Annotated[int, F("Rows that need the user.")]
    moved: Annotated[int, F("Files it moved.")]


@shape
class RunAutoUpgrade(AutoUpgradeBlock):
    """A run's Auto-upgrade block with its one-line account."""
    line: Annotated[str | None, F("The block's one line (\"Upgraded 2 tracks; your cues stayed. 1 waits for rekordbox "
                                  "to be closed.\"); null when nothing happened.")]


@shape
class RunSummary(TypedDict):
    """One run of the sync as the history lists it (`reports/<run_id>.json`)."""
    run_id: Annotated[str, F("The run's id, the report's stamp.", shown=False)]
    id: Annotated[str, F("The typed id the command line takes, `report:<run_id>` (the window ignores it).",
                         shown=False)]
    started: Annotated[str, F("When the run started, an ISO time.")]
    finished: Annotated[str | None, F("When it finished; null while it never did.")]
    duration_s: Annotated[int | None, F("How long it ran, in seconds; null when start or finish is not known.")]
    exit_code: Annotated[int, F("How it ended: 0 well, 1 some failed, 130 stopped.")]
    counts: Annotated[RunCounts, F("What it did.")]
    stopped_after: Annotated[int | None, F("For a stopped run: how many songs it had done; null otherwise.")]
    kind: Annotated[Literal["sync", "auto_upgrade_only"], F(
        "What the run was: a whole sync, or only its Auto-upgrade phase (`sync run --auto-upgrade-only`, the command "
        "line's; a run from before it is a sync); the window never starts the second.")]
    auto_upgrade: Annotated[RunAutoUpgrade | None, F(
        "The run's Auto-upgrade phase and its one-line account; null when the switch was off for the run.")]


@shape
class RunDetailForRekordbox(TypedDict):
    """What a run changed for rekordbox."""
    new_files: Annotated[int, F("New files the run put in the library.")]
    folders: Annotated[list[str], F("The folders they are in.")]


@shape
class RunPartLabels(TypedDict):
    """The titles of the Auto-upgrade parts that hold rows of more than one section (`report.PART_LABELS`)."""
    upgraded: Annotated[str, F("The title of the upgraded part.")]
    waiting: Annotated[str, F("The title of the waiting part.")]
    refused: Annotated[str, F("The title of the refused part.")]


@shape
class RunDetail(RunSummary):
    """The end screen of a run: its summary, and the rows by section, what needs the user, what changed for rekordbox
    and the upgrades waiting. Every row with a `track_id` except those of `queued` carries `cover_url`."""
    sections: Annotated[dict[str, list[Result]], F("The report's rows by section (`report.SECTIONS`).")]
    needs_you: Annotated[list[Result], F("The rows that need the user.")]
    for_rekordbox: Annotated[RunDetailForRekordbox, F("What changed for rekordbox.")]
    upgrades_ready: Annotated[int, F("Upgrades waiting now.")]
    report_md: Annotated[str, F("The report's file, relative to the support folder.", shown=False)]
    queued: Annotated[int, F("How many tracks wait for the next sync (stopped before, left out, over the limit).")]
    folder_order: Annotated[list[str], F("The playlist folders in playlists.txt order, for grouping the rows.")]
    section_labels: Annotated[dict[str, str], F(
        "The report's own title of every section (`report.SECTIONS`; the end part of the placements reads "
        "`placed_missing`): the window prints them as they are.")]
    part_labels: Annotated[RunPartLabels, F("The titles of the Auto-upgrade parts: the window prints them as they "
                                            "are.")]


@shape
class PlanCounts(TypedDict):
    """What the plan holds, by kind."""
    new: Annotated[int, F("New downloads.")]
    retries: Annotated[int, F("Songs tried again.")]
    redownloads: Annotated[int, F("Songs downloaded again because their file is missing.")]
    bought: Annotated[int, F("Bought files to add.")]
    weekly_checks: Annotated[int, F("Weekly checks for a better version.")]


@shape
class EstimateAccount(TypedDict):
    """Which service the downloads are expected to use: one entry per set-up service, in quality order."""
    service: Annotated[Service, F("The service.")]
    name: Annotated[str, F("Its name for the page.")]
    uses: Annotated[int | None, F("How many downloads it is expected to do; null for an account behind Qobuz, which "
                                  "only gets the tracks Qobuz lacks.")]
    left: Annotated[int, F("What is left of its allowance today.")]
    limit: Annotated[int, F("Its daily limit.")]
    about: Annotated[bool, F("True for every service but Qobuz: an estimate.")]


@shape
class EstimateBase(TypedDict):
    """The plan's estimate without its accounts. `duration_min` counts only the downloads that fit today (the rest
    wait for the next sync at once)."""
    duration_min: Annotated[int, F("How long the downloads that fit today take, in minutes (70 s a download, rounded "
                                   "to 5 minutes).")]
    qobuz_limit: Annotated[int, F("The daily limit setting of Qobuz (kept for one release).", shown=False)]
    qobuz_needed: Annotated[int, F("The downloads the plan needs from Qobuz (kept for one release).", shown=False)]
    qobuz_left: Annotated[int, F("What is left of Qobuz's allowance today (kept for one release).", shown=False)]
    qobuz_uses: Annotated[int, F("The downloads expected from Qobuz today (kept for one release).", shown=False)]
    left: Annotated[int | None, F("Today's remaining allowance; null: no daily limit (only free sources are set "
                                  "up).")]
    limit: Annotated[int, F("The daily limit.")]


@shape
class Estimate(EstimateBase):
    """The estimate of the dashboard's ready plan."""
    accounts: Annotated[list[EstimateAccount], F("The expected split between the services.")]


@shape
class SyncAccount(EstimateAccount):
    """One service of the Sync page's estimate."""
    uses_by_downloads: Annotated[list[int] | None, F(
        "Its `uses` for `n` downloads, `n` = 0 … `qobuz_uses` (the engine's `views.split`); null for a backup behind "
        "Qobuz. The page looks its ticked count up (a larger count takes the last entry) and never repeats the "
        "split.")]


@shape
class SyncEstimate(EstimateBase):
    """The Sync page's estimate: the formula and the split live in the engine, the page looks its subset's count up."""
    accounts: Annotated[list[SyncAccount], F("The expected split between the services.")]
    minutes_by_downloads: Annotated[list[int], F("The minutes for `n` downloads, `n` = 0 … `qobuz_uses` (the most "
                                                 "any ticked subset can run today).")]


# --- the dashboard ---

@shape
class DashboardLossless(TypedDict):
    """The lossless tile."""
    share: Annotated[float | None, F("The share of the checked files that are lossless, 0 to 1; null when none is "
                                     "checked.")]
    lossless: Annotated[int, F("Songs that are lossless.")]
    total: Annotated[int, F("Songs counted.")]
    by_quality: Annotated[ByQuality, F("The songs by quality class.")]


@shape
class StillToLoad(TypedDict):
    """How long the rest of the downloads takes at the daily limit. All three are null before the playlists were read,
    and for an account behind Qobuz (Qobuz decides)."""
    count: Annotated[int | None, F("Downloads still to do.")]
    days: Annotated[int | None, F("Days they take at the allowance.")]
    fits_today: Annotated[bool | None, F("Whether they all fit into today's allowance.")]


@shape
class LimitCard(TypedDict):
    """One service's card on Download limits (always all three, in quality order); a service that is not set up has
    zeros."""
    service: Annotated[Service, F("The service.")]
    name: Annotated[str, F("Its name for the page (Qobuz, YouTube Premium, SoundCloud Go+).")]
    set_up: Annotated[bool, F("Whether the service is set up.")]
    used: Annotated[int, F("Downloads that counted today.")]
    allowance: Annotated[int, F("Today's allowance.")]
    warnings: Annotated[int, F("Warning signs of the last 14 days.")]
    new_warnings: Annotated[int, F("Those after the last \"Got it\".")]
    paused: Annotated[bool, F("Paused by the auto-stop: stored as stopped until the next sync starts. An account also counts an "
                                 "`auto_stop` signal of today.")]


@shape
class DashboardTiles(TypedDict):
    """The dashboard's tiles."""
    lossless: Annotated[DashboardLossless, F("The lossless tile.")]
    qobuz_today: Annotated[Budget, F("Qobuz's allowance today.")]
    still_to_load: Annotated[StillToLoad, F("The downloads still to do.")]
    account_today: Annotated[LimitCard | None, F("The first set-up card of `limits()` (Qobuz first, then YouTube "
                                                 "Premium, then SoundCloud Go+); null when no service is set up.")]


@shape
class DashboardReady(Estimate):
    """The plan that is ready: the estimate fields of the preview (without `minutes_by_downloads`) and the counts."""
    counts: Annotated[PlanCounts, F("What the plan holds.")]
    actions: Annotated[int, F("How many actions the plan has.")]


@shape
class DashboardNeedsYou(TypedDict):
    """What waits for the user."""
    upgrades: Annotated[int, F("Better versions waiting.")]
    swappable: Annotated[int, F("Of them, those a swap keeps the cues for.")]
    not_found: Annotated[int, F("Songs nobody has.")]
    weak: Annotated[int, F("Songs of weak quality.")]


@shape
class DashboardFolder(TypedDict):
    """One playlist folder's bar."""
    folder: Annotated[str, F("The playlist's folder name.")]
    tracks: Annotated[int, F("Songs the playlist holds.")]
    lossless_share: Annotated[float | None, F("The share of its checked files that are lossless; null when none is "
                                              "checked.")]
    by_quality: Annotated[ByQuality, F("Its songs by quality class.")]


@shape
class Dashboard(TypedDict):
    """The start page. `ready` is null until the playlists were read; `empty` says why the page has nothing to show."""
    greeting: Annotated[str, F("Good morning, afternoon or evening.")]
    read_status: Annotated[ReadStatus, F("How the last playlists read went.")]
    tiles: Annotated[DashboardTiles, F("The tiles.")]
    ready: Annotated[DashboardReady | None, F("What the next sync would do; null until the playlists were read.")]
    needs_you: Annotated[DashboardNeedsYou, F("What waits for the user.")]
    folders: Annotated[list[DashboardFolder], F("One bar per playlist folder, in playlists.txt order.")]
    last_runs: Annotated[list[RunSummary], F("The newest runs.")]
    has_more_runs: Annotated[bool, F("There are more runs than `last_runs` lists.")]
    next_checks: Annotated[int | None, F("Weekly checks in the preview; null until the playlists were read.")]
    empty: Annotated[EmptyKind | None, F("Why the page has nothing to show, or null.")]


# --- the sidebar ---

@shape
class Crate(TypedDict):
    """A crate: a folder below a watched import folder that holds music itself (wrapper folders get no row)."""
    path: Annotated[str, F("The folder's path.", shown=False)]
    label: Annotated[str, F("Its short name in the browser (\"Hardtechno › 2019\", \"Bounce · Old Sets\" when another "
                            "crate has the name).")]
    name: Annotated[str, F("The folder's own name.")]
    tip: Annotated[str, F("The whole way from the watched folder (\"Rekordbox Library › Hardtechno › 2019\").")]
    files: Annotated[int, F("The files at or below it.")]
    hidden: Annotated[bool, F("Out of the sidebar: the user's switch, else the default (shown, but hidden under a "
                              "folder with `too_many` crates).")]
    has_crates: Annotated[bool, F("Another crate lies below it.")]


@shape
class WatchedEntry(TypedDict):
    """A watched import folder in the sidebar, by name."""
    path: Annotated[str, F("The folder as the snapshot spells it.", shown=False)]
    name: Annotated[str, F("The folder's name.")]
    place: Annotated[str, F("Its path in words (\"~/Music/Old\", \"Example Drive › Music\").")]
    files: Annotated[int, F("The imported files at or below it, leaving out those an import still has to work "
                            "through.")]
    state: Annotated[FolderState, F("Where the folder is now, checked live.")]
    too_many: Annotated[bool, F("It has more than 25 crates: the folder is then one row.")]
    crate_count: Annotated[int, F("How many crates it has.")]
    crates: Annotated[list[Crate], F("All its crates in label order, hidden ones too.")]


@shape
class Favourite(TypedDict):
    """A Favourite, resolved. Keys whose playlist or folder is gone are left out of the answer (the engine keeps them
    stored, also through a `set_favourites` that does not name them)."""
    key: Annotated[str, F("`playlist:<ref>` or `folder:<path>`: what `set_favourites` takes.", shown=False)]
    kind: Annotated[Literal["playlist", "folder"], F("A playlist or a folder.")]
    name: Annotated[str, F("The playlist's folder name, or a crate's `label`.")]
    service: Annotated[PlaylistService | None, F("A playlist's service; null for a folder.")]
    enabled: Annotated[bool, F("A playlist's switch; true for a folder.")]
    count: Annotated[int | None, F("A playlist's songs (null: never read) or a folder's files.")]
    path: Annotated[str | None, F("The folder's path; null for a playlist.", shown=False)]
    state: Annotated[FolderState, F("A playlist is `here`; a crate has its watched folder's.")]


@shape
class SidebarPlaylist(TypedDict):
    """One line of playlists.txt in the sidebar."""
    name: Annotated[str, F("The playlist's folder name.")]
    ref: Annotated[str, F("The playlist's token: a Spotify id stays bare, any other service is `service:id`.",
                          shown=False)]
    service: Annotated[PlaylistService | None, F("Its service.")]
    enabled: Annotated[bool, F("Whether the line is switched on.")]
    songs: Annotated[int | None, F("The distinct songs of its read record; null: never read. A read that found no "
                                   "song is 0.")]


@shape
class SidebarLibraryFolder(TypedDict):
    """A `Library/` folder with files that no playlist line uses."""
    path: Annotated[str, F("`Library/<name>`, what `library(\"folder\", …)` takes.", shown=False)]
    name: Annotated[str, F("The folder's name.")]
    files: Annotated[int, F("The files at or below it.")]


@shape
class Sidebar(TypedDict):
    """Counts and lists for the sidebar. Every `files` count is the length of the `rows` of the view it opens, as are
    `all_tracks`, `not_in_playlist` and a playlist's `songs`."""
    todo: Annotated[int, F("The to-do badge.")]
    all_tracks: Annotated[int, F("All tracks.")]
    not_in_playlist: Annotated[int, F("Songs in no playlist.")]
    limits_warning: Annotated[bool, F("A set-up service has a warning sign the user has not marked as seen (\"Got "
                                      "it\"), or is paused today: the dot on Download limits.")]
    favourites: Annotated[list[Favourite], F("The Favourites in their stored order.")]
    playlists: Annotated[list[SidebarPlaylist], F("Every line of playlists.txt in file order, switched-off ones "
                                                  "too.")]
    watched: Annotated[list[WatchedEntry], F("The watched import folders (not the Library) by name.")]
    library_folders: Annotated[list[SidebarLibraryFolder], F("The Library folders with files that no playlist line "
                                                             "uses, by name (case and accents ignored).")]


@shape
class FavouritesSaved(TypedDict):
    """What `set_favourites` answers: a brief save that starts no job."""
    favourites: Annotated[list[str], F("The keys now stored, in order.")]


@shape
class CrateSaved(TypedDict):
    """What `set_crate_shown` answers: a brief save that starts no job."""
    path: Annotated[str, F("The crate's path.", shown=False)]
    shown: Annotated[bool | None, F("The user's switch now; null: back to the default.")]


@shape
class CratesSaved(TypedDict):
    """What `set_crates_shown` answers: a brief save that starts no job."""
    paths: Annotated[list[str], F("The crates' paths (a path given twice counts once).", shown=False)]
    shown: Annotated[bool | None, F("The user's switch now; null: back to the default.")]


# --- the Sync page's preview and the job snapshot ---

PreviewAction = TypedDict("PreviewAction", {
    "id": Annotated[str, F("The action's id in this plan (`act:<kind>:<track>:<n>`); sent back ticked to `start_sync`.",
                           shown=False)],
    "kind": Annotated[str, F("What the action does (acquire, adopt_bought, upgrade).")],
    "reason": Annotated[str | None, F("Why: new, retry or redownload for a download; null for the others.")],
    "track_id": Annotated[str, F("The song's id.", shown=False)],
    "artist": Annotated[str, F("The artist.")],
    "title": Annotated[str, F("The title.")],
    "folder": Annotated[str, F("The playlist folder it goes to.")],
    "to_dir": Annotated[str, F("The folder it lands in (`Library/<folder>`).")],
    "to_not_lossless": Annotated[bool, F("It would land in the folder's `not_lossless` folder.")],
    "src": Annotated[str | None, F("The file it starts from; null when none.", shown=False)],
    "cover_url": Annotated[str | None, F("The cover's media URL, else the Spotify image URL, else null.",
                                         shown=False)],
    "in": Annotated[list[str], F(
        "The collections of the browser column the song belongs to (issue 37), by their targets: every playlist "
        "whose read holds it (`playlist:<ref>`, playlists.txt order), then the folders its file sits in, outer to "
        "inner (`folder:<path>`). Sync leaves the row out only when every one of them is switched off; empty: nothing "
        "can switch it off.", shown=False)],
    "run": NotRequired[Annotated[int, F("The order the sync works through the actions (kind, then playlist order); "
                                        "not on `never` rows.")]],
})
shape(PreviewAction)


@shape
class SyncPreset(TypedDict):
    """One of the "how many" choices of a plan."""
    key: Annotated[Literal["5", "10", "25", "50", "fits", "all"], F("The choice.", shown=False)]
    label: Annotated[str, F("Its words (\"10\", \"7 · fits today\", \"All 12\").")]
    downloads: Annotated[int, F("How many downloads it ticks.")]
    selected: Annotated[list[str], F("The ids of the actions it ticks: every action in the Sync scope that is no download "
                                     "and the first downloads in scope, in the order the sync works.", shown=False)]


@shape
class PreviewGroup(TypedDict):
    """One group of the preview's actions."""
    key: Annotated[PreviewGroupKey, F("The group.", shown=False)]
    label: Annotated[str, F("The group's title (Download (new), Try again, Download again, Add a bought file, Look "
                            "for a better version).")]
    actions: Annotated[list[PreviewAction], F("Its actions.")]


@shape
class SyncPreviewAmbiguous(TypedDict):
    """A song whose files the sync cannot tell apart."""
    track_id: Annotated[str, F("The song's id.", shown=False)]
    artist: Annotated[str, F("The artist.")]
    title: Annotated[str, F("The title.")]
    folder: Annotated[str, F("The playlist folder.")]
    files: Annotated[list[str], F("The files that could be it.")]


@shape
class SyncPreviewDropped(TypedDict):
    """A song the plan dropped."""
    track_id: Annotated[str, F("The song's id.", shown=False)]
    artist: Annotated[str, F("The artist.")]
    title: Annotated[str, F("The title.")]
    folder: Annotated[str, F("The playlist folder.")]


@shape
class PlaceNotes(TypedDict):
    """The engine's sentence for the placements of parked better versions."""
    closed: Annotated[str, F("The sentence while rekordbox is closed.")]
    open: Annotated[str, F("The sentence while rekordbox is open.")]


@shape
class SyncPreviewAutoUpgrade(TypedDict):
    """Auto-upgrade before a start. Null in the preview when the switch is off and nothing is to be placed."""
    on: Annotated[bool, F("The Auto-upgrade switch.")]
    ready: Annotated[int, F("The upgrades the sync's last phase would put in place (those that would wait for "
                            "rekordbox included; nothing of rekordbox's library is opened for it).")]
    places: Annotated[int, F("The missing songs it would put their parked better version in (with the switch off "
                             "too).")]
    place_notes: Annotated[PlaceNotes | None, F("The engine's sentence for them (rekordbox closed / open); null with "
                                                "none.")]


@shape
class SyncPreview(TypedDict):
    """The check before Start. Each action's `id` is sent back ticked to `start_sync`. Before the first read the
    counts are 0, `counts` and `estimate` null and `collections` empty."""
    read_status: Annotated[ReadStatus, F("How the last playlists read went.")]
    counts: Annotated[PlanCounts | None, F("What the plan holds; null before a read.")]
    waiting_answers: Annotated[int, F("Songs held back until the user answers \"Is this the same song?\" (not "
                                      "downloaded meanwhile).")]
    deferred_checks: Annotated[int, F("First upgrade checks of imported music that the per-run cap left for later "
                                      "runs.")]
    groups: Annotated[list[PreviewGroup], F("The actions by group, in the order the page lists them.")]
    estimate: Annotated[SyncEstimate | None, F("How long it takes and which service does the downloads; null before "
                                               "a read.")]
    never: Annotated[list[PreviewAction], F("Downloads left out because the user said \"never download\" (rows "
                                            "without `run`).")]
    folders: Annotated[list[str], F("The playlist folders in playlists.txt order.")]
    in_playlists: Annotated[int | None, F("The unique Spotify tracks read; null before a read.")]
    ambiguous: Annotated[list[SyncPreviewAmbiguous], F("Songs whose files the sync cannot tell apart.")]
    dropped: Annotated[list[SyncPreviewDropped], F("Songs the plan dropped.")]
    notes: Annotated[list[str], F("Notes of the plan, in words.")]
    empty: Annotated[EmptyKind | None, F("Why the page has nothing to show, or null.")]
    collections: Annotated[dict[str, str], F(
        "Every collection a row is `in`, by its target, to its name as the plan's sections name it (\"Techno\", "
        "\"Techno › 2019\"); empty before the first read.")]
    auto_upgrade: Annotated[SyncPreviewAutoUpgrade | None, F(
        "Auto-upgrade before a start; null: the switch is off and nothing is to be placed (or settings.json cannot "
        "be read, or there is no preview).")]
    read_id: Annotated[str | None, F("The stored read the plan is derived from (`read:<n>`); null before the first "
                                     "read.", shown=False)]
    plan_id: Annotated[str | None, F("The id this plan is stored under (`plan:<12 hex>`, 24 h); Start and `sync run "
                                     "--plan` run only its actions. Null before the first read.")]
    presets: Annotated[list[SyncPreset], F("The \"how many\" choices, by downloads; empty when no action is in the "
                                           "Sync scope.")]
    default_how_many: Annotated[str | None, F("The choice to start from (a preset's `key`): `fits` when it is offered, "
                                              "else `all`; null when there are no choices.")]
    search: Annotated[str | None, F("The words the actions of `groups` were narrowed to (the command line's "
                                    "`--search`); null for the whole plan. Everything else is the whole plan's.")]


@shape
class PlannedAction(TypedDict):
    """One planned action of a running job, copied from `RunStarted.actions`."""
    kind: Annotated[str, F("What the action does.")]
    track_id: Annotated[str, F("The song's id.", shown=False)]
    title: Annotated[str, F("The title.")]
    artist: Annotated[str, F("The artist.")]
    image_url: NotRequired[Annotated[str | None, F("The cover.", shown=False)]]


@shape
class JobSnap(TypedDict):
    """A job's snapshot after a window reload (the events are not shapes: `tests/fixtures/hub_events.schema.json` pins
    them)."""
    id: Annotated[str, F("The job's id.", shown=False)]
    kind: Annotated[str, F("The job kind (`sync`, `refresh`, `tidy`, ...).")]
    track_id: Annotated[str | None, F("The song the job works on; null for a job on none.", shown=False)]
    started: Annotated[str, F("When it started, an ISO time.")]
    running: Annotated[bool, F("It is running.")]
    stopping: Annotated[bool, F("A stop was asked and the job ends after its current step.")]
    batch_kind: NotRequired[Annotated[Literal["upgrade", "convert", "mixed"] | None, F(
        "An AIFF batch job's (`upgrade_batch`, `aiff_batch`, `batch_resume`, `upgrade_add_new`, `upgrade_discard`) "
        "batch kind, else null: `upgrade` for Same track, `convert` for what Convert, Give it its clean name, Make "
        "all and the CDJ group's Convert all start; for `batch_resume` the stopped batch's own kind. After a reload it "
        "says whose batch runs; the live `JobStarted` event carries the same.")]]
    last: Annotated[Any, F("The newest event of each type, as events.ts `HubEvent`, by the event's type name.")]
    usage: NotRequired[Annotated[list[Any], F(
        "The newest `AccountUsage` event of each service, in the order the services first reported (`last` keeps only "
        "the newest one overall); empty until a download counted.")]]
    results: Annotated[Any, F("The `ActionFinished` events so far, as events.ts `HubEvent`s, in a list.")]
    finished: Annotated[Any, F("The `JobFinished` event as events.ts `HubEvent`, null while the job runs.")]
    actions: Annotated[list[PlannedAction], F("The run's planned actions in the order the run does them; empty until "
                                              "a run started and for jobs without a run.")]


@shape
class SyncArgs(TypedDict):
    """What a sync was started with."""
    plan_id: Annotated[str | None, F("The plan it ran (`plan:<12 hex>`); null when the record has none.")]
    selected: Annotated[list[str], F("The ids of the actions ticked, in the plan.", shown=False)]


@shape
class LastSync(TypedDict):
    """The newest sync of this music folder, from the job registry."""
    job: Annotated[str, F("Its job id.")]
    args: Annotated[SyncArgs, F("What it was started with.")]
    ended: Annotated[str | None, F("When it ended, an ISO time; null while it runs.")]


@shape
class ConsoleHolder(TypedDict):
    """Another process that holds the library lock: what the window's banner says and the job it names (`ConsoleBusy`
    carries the same fields)."""
    job: Annotated[str | None, F("The holder's job id in the registry; null for a holder with no registry entry.",
                                 shown=False)]
    via: Annotated[Literal["terminal", "window"] | None, F(
        "Where the holder runs: the Terminal or another window; null for a holder with no registry entry.")]
    kind: Annotated[str | None, F("The holder's job kind (`sync`, `tidy`, ...); null for a holder with no registry "
                                  "entry.")]
    line: Annotated[str | None, F("How far the holder is (\"4 of 60\"); null before it says.")]
    text: Annotated[str, F("What the window says while it holds the library: the job, where it runs, how far it is.")]
    where: Annotated[str | None, F(
        "Where it runs as the Sync page's live view says it (\"In the Terminal\", \"In another window\"); null for a "
        "holder with no registry entry.")]


@shape
class JobStatus(TypedDict):
    """The snapshot after a window reload."""
    job: Annotated[JobSnap | None, F("The running write job; null when none runs.")]
    refresh_running: Annotated[bool, F("A playlists read is running.")]
    console_running: Annotated[bool, F("A console command is running.")]
    console: Annotated[ConsoleHolder | None, F("Who holds the library lock besides this window, the Terminal's job or "
                                               "another window's; null when nothing does. After a reload the banner "
                                               "names the job from it at once.")]
    read_status: Annotated[ReadStatus, F("How the last playlists read went.")]
    last_sync: Annotated[LastSync | None, F("The newest sync of this music folder, the window's or the terminal's: what "
                                            "was ticked, and when it ended; null with none.")]
    sign_in: NotRequired[Annotated[JobSnap | None, F(
        "A sign-in waiting for the browser (its own slot beside the write jobs; Settings restores its phase from "
        "it); null when none.")]]


@shape
class JobEvents(TypedDict):
    """What `job_events` answers: a job's events from a position on (the window's follow of a job another process runs)."""
    events: Annotated[list[Any], F("The job's events from `after` on, as events.ts `HubEvent` objects (`{type, …fields}`), "
                                   "at most 500.")]
    next: Annotated[int, F("The position to ask from next: `after` plus the lines of the files delivered (a line that "
                           "is no event has its place but is not in `events`).", shown=False)]
    done: Annotated[bool, F("The job has ended and these were its last events.", shown=False)]
    status: Annotated[Literal["queued", "running", "stopping", "done", "lost"], F(
        "The job's status when it was read.", shown=False)]
    finished: Annotated[Any, F("The job's end, from its result.json, as the watch sends it (a `JobFinished` "
                                       "event object; `worker_lost` when it left no result); null until `done`.",
                                       shown=False)]


@shape
class Stopped(TypedDict):
    """What `stop`, `stop_refresh` and `stop_sign_in` answer."""
    stopped: Annotated[bool, F("Whether a job was running to stop.")]


# --- the Library ---

@shape
class LibraryRow(TrackRow):
    """One row of the Library: a song's row with what the table needs. The user's own songs (the import) are in no
    folder: `folder` is empty and `in_playlists` false."""
    sound_checked: Annotated[bool, F(
        "False for an imported file whose sound is not judged yet (its quality is the codec's guess for now: the page "
        "says \"sound not checked yet\").")]
    file_state: Annotated[LibraryFileState, F(
        "Whether the row's file is there now, decided per watched folder (`file_missing` is the stored mark of a file "
        "that waits as missing, issue 43); a row that is not `here` does not play. `no_file`: a playlist song that "
        "has no file yet.")]
    wait: Annotated[Literal["waiting", "not_found"] | None, F(
        "A song without a file: `waiting` (the sync has yet to get it) or `not_found` (the sync found nothing "
        "usable); null for a row with a file.")]
    next_try: Annotated[str | None, F(
        "A `not_found` row: the day the sync looks again (ISO; due on and after it) or `next_sync` (never looked "
        "yet); null on every other row.")]
    position: Annotated[int | None, F("The place in the playlist's read (playlist view only).")]
    place: Annotated[str | None, F(
        "The folder the file sits in, in the Folder column's words (a Library file says its playlist line or "
        "folder, a watched folder's file the folder and its crate); null: no file, or a playlist view's rows inside "
        "the playlist's own Library folder.")]
    subfolder: Annotated[str | None, F(
        "Folder views only: a watched folder's rows carry their crate's label (\"\" for a file directly in it), a "
        "crate's the folders below it (\"2019\" or \"A › B\"); null elsewhere.")]
    playlists: Annotated[list[str], F("The playlists whose read holds the song, in playlists.txt order; empty for a "
                                      "song only a file holds.")]
    in_missing_files: Annotated[bool, F(
        "To-do's Missing files group lists the song: true only for a row whose file waits as missing and that the "
        "group lists; false for every other row, and for a song whose Download again is asked.")]
    track_link: Annotated[TrackLink | None, F(
        "The song's page on its service, for the row menu's \"Open in {Service}\"; null: no page known.")]


@shape
class LibrarySummary(TypedDict):
    """The folder at a glance, unaffected by the search and the filter. Only the rows with a file count."""
    tracks: Annotated[int, F("The songs with a file.")]
    lossless_share: Annotated[float | None, F("The share of the checked files that are lossless; null when none is "
                                              "checked.")]
    by_quality: Annotated[ByQuality, F("The checked files by quality class.")]
    upgrades_ready: Annotated[int, F("Better versions waiting.")]
    to_do: Annotated[int, F("What the to-do list shows of the view (in a playlist, not hidden).")]
    not_lossless: Annotated[int, F("The checked files that are not lossless (good lossy + weak + fake).")]


@shape
class LibrarySongs(TypedDict):
    """A read playlist's songs, before any search or filter."""
    listed: Annotated[int, F("How many distinct songs it lists (what the sidebar's `songs` counts).")]
    with_file: Annotated[int, F("How many of them have a file.")]


@shape
class LibraryAiffStopped(TypedDict):
    """The newest stopped `library:*` AIFF batch (Make all, a selection's Convert) with items left."""
    batch_id: Annotated[int, F("The batch's id.", shown=False)]
    left: Annotated[int, F("How many items are left (\"Resume · {left} left\").")]


@shape
class Library(TypedDict):
    """One view of the library. A playlist or folder that is not there any more is no error: `empty` is `gone`, `rows`
    and `subtitle` are empty. An empty folder, and a playlist that was read and holds nothing, both have `empty`
    `no_match` even without search text."""
    title: Annotated[str, F("The view's name.")]
    summary: Annotated[LibrarySummary, F("The folder at a glance.")]
    folder: Annotated[str | None, F("The old `folder` argument: null (All tracks), `__not_in_playlist__`, a "
                                    "playlist's folder name or a folder's key.", shown=False)]
    view: Annotated[LibraryView, F("What the request asked for.")]
    key: Annotated[str | None, F("The playlist's folder name as playlists.txt spells it, or the folder's path; null "
                                 "for All tracks and Not in a playlist.", shown=False)]
    folder_kind: Annotated[Literal["watched", "crate", "library"] | None, F(
        "Folder views: what the folder is (`library`: a Library/ folder); null: none of these (`empty` is `gone`).")]
    subtitle: Annotated[list[str], F("The header's second line as parts in order of importance (the page drops the "
                                     "last parts first); empty when `gone`.")]
    chips: Annotated[dict[str, int], F("The row count of each `LibraryFilter` (`all` counts every row the table "
                                       "lists, a read playlist's songs without a file too, never `also`).")]
    rows: Annotated[list[LibraryRow], F("The rows of the view, searched and filtered.")]
    also: Annotated[list[LibraryRow] | None, F("A playlist view: the files in the playlist's own Library folder whose "
                                               "song the playlist does not hold, by artist then title; null "
                                               "elsewhere.")]
    songs: Annotated[LibrarySongs | None, F(
        "A read playlist's songs: how many it lists and how many have a file; null elsewhere and while never read. "
        "The page words \"13 of 18 downloaded\".")]
    read_at: Annotated[str | None, F("A playlist view: when its read was made; null: never read, and in other "
                                     "views.")]
    enabled: Annotated[bool | None, F("A playlist view: whether its line is switched on; null elsewhere.")]
    service: Annotated[PlaylistService | None, F("A playlist view: its service; null elsewhere.")]
    aiff_stopped: Annotated[LibraryAiffStopped | None, F(
        "The newest stopped `library:*` AIFF batch with items left: the header's \"Resume · {left} left\"; null "
        "when none (issue 33 stage D).")]
    empty: Annotated[EmptyKind | None, F("Why the page has nothing to show (`gone` adds to the usual words), or "
                                         "null.")]


# --- the playlists page ---

@shape
class PlaylistInfo(TypedDict):
    """What the service says of a playlist; null on the row until it was read (refresh or add_playlist)."""
    name: Annotated[str, F("The playlist's name.")]
    owner_name: Annotated[str, F("Its owner; empty when the name already says it (a SoundCloud likes list is named "
                                 "\"{username}'s likes\").")]
    yours: Annotated[bool, F("Whether it is the user's own.")]
    collaborative: Annotated[bool, F("Whether it is collaborative.")]
    readable: Annotated[bool, F("Whether the service shows its tracks.")]
    image_url: Annotated[str | None, F("Its picture; null when none.", shown=False)]
    track_count: Annotated[int | None, F("How many tracks it has; null when the service gives no count (a SoundCloud "
                                         "likes list: the row's `tracks` is then what the read found).")]
    hint: Annotated[str, F("The words of the row's service for a playlist it will not show (always set once info "
                           "is).")]


@shape
class PlaylistRow(TypedDict):
    """One line of playlists.txt on the playlists page (top = highest priority)."""
    index: Annotated[int, F("The line's place.", shown=False)]
    folder: Annotated[str, F("The playlist's folder name.")]
    link: Annotated[str, F("The playlist's link.")]
    playlist_id: Annotated[str | None, F(
        "The playlist's ref (a Spotify id stays bare, every other service's is `<service>:<id>`); the page keys rows "
        "by it.", shown=False)]
    service: Annotated[PlaylistService, F("The row's service.")]
    service_name: Annotated[str, F("Its name (Spotify, Qobuz, SoundCloud, YouTube Music).")]
    enabled: Annotated[bool, F("Whether the line is switched on.")]
    info: Annotated[PlaylistInfo | None, F("What the service says; null until it was read.")]
    tracks: Annotated[int | None, F("The tracks found; null when neither the tracks nor the playlist's count were "
                                    "read (the row then shows no count).")]
    quality: Annotated[ByQuality, F("Its songs by quality class: always the five counts, all 0 while the tracks were "
                                    "not read (a switched-off playlist is never read).")]
    needs_setting: Annotated[SettingKey | None, F(
        "A listed Liked music line while Settings' choice is off (or no YouTube login): the choice it needs, else "
        "null.")]


@shape
class PlaylistTrack(TypedDict):
    """A track on the playlists page."""
    track_id: Annotated[str, F("The song's id.", shown=False)]
    artist: Annotated[str, F("The artist.")]
    title: Annotated[str, F("The title.")]
    cover_url: Annotated[str | None, F("The cover.", shown=False)]
    downloaded: Annotated[bool, F("Whether it has a file yet.")]
    quality: Annotated[Quality, F("The colour class.")]
    quality_label: Annotated[str | None, F("The words next to the colour; null without a state entry.")]
    never: NotRequired[Annotated[bool, F("The user left it out of the sync (\"never download\").")]]


@shape
class PlaylistOverlap(PlaylistTrack):
    """A track that is in several switched-on playlists."""
    folders: Annotated[list[str], F("The playlists' folders, in list order.")]
    lands_in: Annotated[str, F("The first of them: where the file goes.")]


@shape
class PlaylistsTidy(TypedDict):
    """The tidy-up's badge."""
    waiting: Annotated[int, F("Files a tidy-up ticks by default (`planner.out_of_place`: files the playlist order "
                              "puts elsewhere, not placed by the user): the \"Tidy up files\" badge.")]


@shape
class Playlists(TypedDict):
    """The playlists page."""
    version: Annotated[str, F("The playlists file's version: must be sent to `save_playlists`.", shown=False)]
    problem: Annotated[str | None, F("What the sync would say about the file; null when nothing.")]
    rows: Annotated[list[PlaylistRow], F("Every line, top = highest priority.")]
    overlaps: Annotated[list[PlaylistOverlap], F("For the panel when nothing is unsaved: each track that is in "
                                                 "several switched-on playlists.")]
    empty: Annotated[EmptyKind | None, F("Why the page has nothing to show, or null.")]
    tidy: Annotated[PlaylistsTidy, F("The tidy-up's badge.")]


# --- Download limits ---

@shape
class Assessment(TypedDict):
    """What a daily limit means."""
    level: Annotated[int, F("The zone's place, 1 (careful) to 5 (risky).")]
    label: Annotated[str, F("The zone's name (careful, normal, faster, fast, risky).")]


@shape
class WhatIf(TypedDict):
    """\"What N per day means\" while the slider moves (no write). For an account behind Qobuz `days_to_load` is
    null."""
    limit: Annotated[int, F("The daily limit asked, 1 to 500.")]
    extra_today: Annotated[int, F("The one-time extra for today, 0 to 200.")]
    assessment: Annotated[Assessment, F("What the limit means.")]
    allowance_today: Annotated[int, F("Today's allowance at this limit.")]
    remaining_today: Annotated[int, F("What would be left of it today.")]
    days_to_load: Annotated[int | None, F("Days the rest of the downloads takes; null for an account behind Qobuz or "
                                          "before a read.")]
    run_minutes: Annotated[int, F("How long a run takes, in minutes.")]


@shape
class SignalBase(TypedDict):
    """A warning sign without its kind: `new` is after the last \"Got it\"."""
    time: Annotated[str, F("When it happened, an ISO time.")]
    message: Annotated[str, F("What happened, in words.")]
    new: Annotated[bool, F("After the time in settings.json `warnings_seen[service]`, or never marked.")]
    clears_in: Annotated[int, F("Days until it leaves the 14 days (1 = tomorrow).")]


@shape
class Signal(SignalBase):
    """A warning sign of a YouTube or SoundCloud account (or any service)."""
    kind: Annotated[AnySignalKind, F("What kind of sign it is.")]


@shape
class QobuzSignal(SignalBase):
    """A warning sign of Qobuz."""
    kind: Annotated[SignalKind, F("What kind of sign it is.")]


@shape
class UsageDay(TypedDict):
    """One day of a service's use."""
    date: Annotated[str, F("The day, an ISO date.")]
    used: Annotated[int, F("Downloads that counted that day.")]


UsageZone = TypedDict("UsageZone", {
    "name": Annotated[str, F("The zone's name (careful, normal, faster, fast, risky).")],
    "from": Annotated[int, F("Its first limit.")],
    "to": Annotated[int, F("Its last limit.")],
})
shape(UsageZone)


@shape
class UsageSetting(TypedDict):
    """The setting and what the slider offers."""
    limit: Annotated[int, F("The daily limit.")]
    extra_today: Annotated[int, F("The one-time extra for today.")]
    recommended: Annotated[int, F("The recommended limit (60 Qobuz, 30 YouTube, 60 SoundCloud).")]
    zones: Annotated[list[UsageZone], F("The five zones (Qobuz and SoundCloud: careful 1–40, normal 41–60, faster "
                                        "61–79, fast 80–100, risky 101–500; YouTube: careful 1–20, normal 21–30, "
                                        "faster 31–45, fast 46–60, risky 61–500).")]
    min: Annotated[int, F("The smallest limit.")]
    max: Annotated[int, F("The largest limit.")]
    extra_max: Annotated[int, F("The largest extra for today.")]


@shape
class UsageBase(TypedDict):
    """What every service's page has: today, the last 14 days, the setting, its meaning and the last download."""
    today: Annotated[Budget, F("Today's numbers.")]
    days: Annotated[list[UsageDay], F("The last 14 days, oldest first.")]
    setting: Annotated[UsageSetting, F("The setting and what the slider offers.")]
    assessment: Annotated[Assessment, F("What the limit means.")]
    what_if: Annotated[WhatIf, F("What the saved limit means, in the answer of `limits_what_if`.")]
    last_download: Annotated[str | None, F("When the last download that counted toward the limit was, an ISO time "
                                           "(any day); null if none yet.")]


@shape
class QobuzUsage(UsageBase):
    """Qobuz's page of Download limits."""
    still_to_load: Annotated[StillToLoad, F("The downloads still to do.")]
    signals: Annotated[list[QobuzSignal], F("The warning signs of the last 14 days.")]
    signal_summary: Annotated[dict[str, int], F("A count for every `SignalKind`.")]


@shape
class ServiceUsage(UsageBase):
    """The Download limits page of one set-up service."""
    service: Annotated[Service, F("The service.")]
    name: Annotated[str, F("Its name for the page.")]
    behind: Annotated[str | None, F("\"Qobuz\" for an account behind Qobuz (it only gets the tracks Qobuz lacks), "
                                    "else null.")]
    still_to_load: Annotated[StillToLoad, F("The downloads still to do.")]
    signals: Annotated[list[Signal], F("The warning signs of the last 14 days.")]
    signal_summary: Annotated[dict[str, int], F(
        "A count for every `AnySignalKind` of the service: Qobuz login_failed, search_failed, download_rejected, "
        "preview_only, duration_mismatch, auto_stop; YouTube cookies_unreadable, bot_check, rate_limited, refused, "
        "premium_missing, download_rejected, auto_stop; SoundCloud the same without bot_check.")]


@shape
class Limits(TypedDict):
    """The Download limits page."""
    service: Annotated[Service, F("The service the page is for.")]
    cards: Annotated[list[LimitCard], F("Always all three services in quality order.")]
    usage: Annotated[ServiceUsage | None, F("The page of that service; null when it is not set up.")]


@shape
class Runs(TypedDict):
    """The run history."""
    runs: Annotated[list[RunSummary], F("The runs, newest first.")]


@shape
class RunAnswer(TypedDict):
    """One run's end screen."""
    run: Annotated[RunDetail, F("The run.")]


@shape
class Spectrum(TypedDict):
    """A file's spectrum. `data` is `cols * bands` bytes row by row in time, each row low to high frequency (band width
    `max_hz / bands`): byte v is `floor_db * (1 - v / 255)` dB (0 dB = the loudest cell)."""
    cols: Annotated[int, F("How many columns (time steps).")]
    bands: Annotated[int, F("How many frequency bands.")]
    max_hz: Annotated[int, F("The highest frequency.")]
    duration_s: Annotated[float, F("The file's length in seconds.")]
    floor_db: Annotated[float, F("The quietest dB the bytes show.")]
    data: Annotated[str, F("The matrix, base64.", shown=False)]
    waveform: Annotated[str, F(
        "Base64 of `cols` bytes, one per column (the same columns as the matrix): the largest sample anywhere in that "
        "column's stretch of the track, 0 = silence, 255 = the loudest column, linear; for the mini player's bars.",
        shown=False)]
    which: Annotated[Which, F("Which file it is of.")]
    cutoff_hz: Annotated[int | None, F("The measured cutoff in Hz, where to draw the cutoff line; null: none (always "
                                       "for the parked version).")]


@shape
class SpectrumAnswer(TypedDict):
    """A file's spectrum."""
    spectrum: Annotated[Spectrum, F("The spectrum.")]


# --- results of the jobs ---

@shape
class RefreshResult(TypedDict):
    """The result of the playlists read (`refresh`)."""
    actions: Annotated[int, F("How many actions the new plan has.")]
    read_id: Annotated[str, F("The read this stored (`read:<n>`). A read that could not be stored ends the job "
                              "`failed` instead (the plan is derived from the stored read).")]


@shape
class SyncResult(TypedDict):
    """The result of a sync (`start_sync`); a crashed sync carries one too: `exit_code` 1, `report` its crash note."""
    exit_code: Annotated[int, F("How the run ended: 0 well, 130 stopped.")]
    report: Annotated[str, F("The report's absolute .md path.", shown=False)]
    actions: Annotated[int, F("How many actions it ran; 0 when it crashed before the plan.")]
    new_since_plan: Annotated[list[str], F("The actions the run's fresh plan has that the plan you started from did not, "
                                           "by their ids in the fresh plan; left for the next sync.")]


@shape
class SaveLimitsResult(TypedDict):
    """The result of `save_limits`."""
    service: Annotated[Service, F("The service.")]
    limit: Annotated[int, F("The daily limit saved.")]
    extra_today: Annotated[int, F("The extra for today saved.")]


@shape
class WarningsSeenResult(TypedDict):
    """The result of `mark_warnings_seen` (\"Got it\")."""
    service: Annotated[Service, F("The service.")]
    seen_until: Annotated[str, F("The time saved: its signals up to then are no longer `new`.")]


@shape
class ScanResult(TypedDict):
    """What one library scan found (`rescan_library`, `library scan --json`; issue 43): a file the scan does not see
    waits as missing, never decided by one scan."""
    moved: Annotated[int, F("Files found in another folder.")]
    new: Annotated[int, F("New files.")]
    gone: Annotated[int, F("Index rows of nobody's file, dropped.")]
    missing: Annotated[int, F("Songs whose file was not found at this scan.")]
    back: Annotated[int, F("Missing files seen again.")]
    changed: Annotated[int, F("Audio replaced outside Discjockey.")]
    copies: Annotated[int, F("Copies of a file found.")]


@shape
class ScopeCollection(TypedDict):
    """A playlist or folder left out of the Sync."""
    target: Annotated[str, F("`playlist:<ref>` or `folder:<path>`: what `set_sync_scope` takes.", shown=False)]
    name: Annotated[str, F("Its name: the playlists.txt line's folder name, or the last part of the folder's path; the "
                           "target itself when no line or folder has it any more (a folder on a drive that is away "
                           "comes back).")]


@shape
class ScopeKind(TypedDict):
    """A weekly kind switched off."""
    kind: Annotated[Literal["retry", "weekly"], F("The kind: `retry` (Not found last time) or `weekly` (Weekly checks).",
                                                    shown=False)]
    label: Annotated[str, F("Its words.")]


@shape
class SyncScope(TypedDict):
    """The Sync scope (`sync_scope`; the result of `set_sync_scope`, the scope as saved): what the sync leaves out.
    Nothing listed means everything is on."""
    off: Annotated[list[ScopeCollection], F("The playlists and folders switched off, in the order they were switched.")]
    weekly_off: Annotated[list[ScopeKind], F("The weekly kinds switched off.")]


ANSWERS: dict[str, str] = {
    "sync_scope": "SyncScope", "set_sync_scope": "SyncScope",
    "dashboard": "Dashboard", "sidebar": "Sidebar", "library": "Library", "sync_preview": "SyncPreview",
    "job_status": "JobStatus", "job_events": "JobEvents", "playlists": "Playlists", "limits": "Limits", "limits_what_if": "WhatIf",
    "runs": "Runs", "run": "RunAnswer", "spectrum": "SpectrumAnswer", "stop_refresh": "Stopped", "stop": "Stopped",
    "stop_sign_in": "Stopped", "set_favourites": "FavouritesSaved", "set_crate_shown": "CrateSaved",
    "set_crates_shown": "CratesSaved", "refresh": "RefreshResult", "start_sync": "SyncResult",
    "save_limits": "SaveLimitsResult", "mark_warnings_seen": "WarningsSeenResult", "rescan_library": "ScanResult",
}
RESULTS: dict[str, str] = {
    "set_sync_scope": "SyncScope",
    "refresh": "RefreshResult", "sync": "SyncResult", "save_limits": "SaveLimitsResult",
    "mark_warnings_seen": "WarningsSeenResult", "scan": "ScanResult",
}
