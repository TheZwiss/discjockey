"""The shapes every area uses (issue 39, phase 2): the words of a problem, the quality classes, a song's row, a report
line, a failed answer. The meanings are those of `docs/hub-bridge-contract.md`, "Shared shapes". The area modules
declare their own shapes on top of these.

`ANSWERS` maps a bridge or command-line method to the shape of its answer without `ok`; `RESULTS` maps a job kind to
the shape of its `JobFinished.result` (a J method is mapped to that result shape). Here only `freshness`."""
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from .kernel import F, alias, shape

ProblemKind = alias(
    "ProblemKind",
    Literal["busy", "console", "sync_running", "not_set_up", "login_expired", "offline", "playlist_unreadable",
            "config_invalid", "qobuz_login_failed", "login_failed", "changed", "refused", "failed", "stopped",
            "protected", "crashed", "no_library", "setting_off", "exists", "rekordbox_open"],
    const="PROBLEM_KINDS",
    doc="Why an answer is not ok. The window reads `kind` and shows `message`; the command line maps each kind to an "
        "outcome (`outcomes.KIND_OUTCOME`). The command line's own `bad_args` is sent only to it.")
FailKind = alias(
    "FailKind",
    Literal["busy", "console", "sync_running", "not_set_up", "login_expired", "offline", "playlist_unreadable",
            "config_invalid", "qobuz_login_failed", "login_failed", "changed", "refused", "failed", "stopped",
            "protected", "crashed", "no_library", "setting_off", "exists", "rekordbox_open", "bad_args"],
    doc="The `kind` of a failed answer: a `ProblemKind`, or `bad_args` for what only the command line sends (a typed "
        "id or word that names nothing; the window never sends one and shows it as `crashed`).")
Quality = alias(
    "Quality", Literal["lossless", "good_lossy", "weak", "fake", "missing"], const="QUALITIES",
    doc="A song's colour class: lossless green, good_lossy yellow, weak red (cutoff 17 kHz or less), fake purple, "
        "missing red.")
EmptyKind = alias(
    "EmptyKind",
    Literal["no_playlists", "not_set_up", "empty_library", "no_preview", "up_to_date", "no_match", "all_lossless",
            "all_hidden", "nothing_here", "gone"],
    doc="Why a page has nothing to show (a first-run or empty state), or null when it has something.")
PlaylistService = alias(
    "PlaylistService", Literal["spotify", "qobuz", "soundcloud", "youtube_music"],
    doc="A playlist service (`sources.py`): the one a playlist row, a link or a problem belongs to.")
SettingKey = alias(
    "SettingKey", Literal["read_liked_music"],
    doc="A choice in Settings that a read needs (its key in settings.json): `setting_off` names it in `setting`.")
FailOutcome = alias(
    "FailOutcome", Literal["failed", "bad_args", "busy", "needs_person", "stopped", "refused"],
    doc="The command line's outcome of a problem (`outcomes.KIND_OUTCOME`).")
LibraryFilter = alias(
    "LibraryFilter", Literal["all", "lossless", "good_lossy", "weak", "fake", "upgrade_ready"],
    doc="Which songs the Library lists.")
LibrarySort = alias(
    "LibrarySort",
    Literal["title", "-title", "artist", "-artist", "length", "-length", "source", "-source", "quality", "-quality",
            "added", "-added", "folder", "-folder", "order", "-order"],
    doc="The Library's order: a column name, `-` in front for descending. `order` is a playlist's own order (its read "
        "record's); the engine's default there, and `artist` elsewhere.")
TodoFilter = alias(
    "TodoFilter",
    Literal["all", "rekordbox_check", "missing_file", "same_song", "duplicate", "upgrade_ready", "cdj", "not_found",
            "weak", "good_lossy", "fake", "other"],
    doc="A To-do group, or `all`.")
Which = alias("Which", Literal["current", "upgrade"],
              doc="Which file of a song: the one in the library now, or the parked better version.")
Status = alias(
    "Status", Literal["lossless", "not_lossless", "fake_lossless", "missing"],
    doc="What the sound check made of a file.")
Source = alias(
    "Source", Literal["qobuz", "youtube_music", "soundcloud", "youtube", "manual"],
    doc="Where a file came from; `manual` is a file the user bought or owns.")
SourceHow = alias(
    "SourceHow", Literal["exact", "isrc", "name", "upload", "fallback", "chosen"],
    doc="How a download's source was found (the engine's `source_how`): the exact Qobuz track, its ISRC, a name "
        "search, the playlist's own upload, the fallback search, or picked by the user.")
ErrorKind = alias(
    "ErrorKind", Literal["network", "qobuz", "other", "not_found"],
    doc="What kind of error a report line holds (errors: network, qobuz or other; a song nobody has: not_found).")
ActionKey = alias(
    "ActionKey", tuple[str, str, str],
    doc="The key of one planned action, three words; sent back unchanged to start_sync.")


@shape
class PlaylistLine(TypedDict):
    """One line of playlists.txt as the window edits it."""
    folder: Annotated[str, F("The playlist's folder name in the library.")]
    link: Annotated[str, F("The playlist's link.")]
    enabled: Annotated[bool, F("Whether the line is switched on; a switched-off line is left out of the sync.")]


@shape
class ByQuality(TypedDict):
    """A count for each quality class."""
    lossless: Annotated[int, F("Songs that are lossless.")]
    good_lossy: Annotated[int, F("Songs that are lossy but good.")]
    weak: Annotated[int, F("Songs whose cutoff is 17 kHz or less.")]
    fake: Annotated[int, F("Songs that claim to be lossless and are not.")]
    missing: Annotated[int, F("Songs with no file found.")]


@shape
class TrackRow(TypedDict):
    """One song as a list shows it: a Library row, a to-do item, a change move (to-do items add `group` and `detail`,
    moves add `from`, `to`, `to_not_lossless`)."""
    track_id: Annotated[str, F("The song's id.", shown=False)]
    artist: Annotated[str, F("The artist.")]
    title: Annotated[str, F("The title.")]
    folder: Annotated[str, F("The playlist folder the file is in; empty for the user's own songs from the import, "
                             "which belong to no playlist folder.")]
    duration_s: Annotated[float, F("The length in seconds.")]
    status: Annotated[Status, F("What the sound check made of the file.")]
    quality: Annotated[Quality, F("The colour class: lossless green, good_lossy yellow, weak red, fake purple, "
                                  "missing red.")]
    quality_label: Annotated[str, F("The words next to the colour: LOSSLESS, 20.0 kHz, LOSSY, FAKE · 16.0 kHz, "
                                    "NOT FOUND.")]
    cutoff_hz: Annotated[int | None, F("The measured cutoff in Hz, if measured; `quality_label` is its words.",
                                       shown=False)]
    source: Annotated[Source | None, F("Where the file came from, or null.")]
    source_name: Annotated[str | None, F("The source in short words: Qobuz, YT Music, SoundCloud, YouTube, bought; "
                                         "`own file` for a file the import found.")]
    in_playlists: Annotated[bool, F("Whether a playlist still holds the song.")]
    own: Annotated[bool, F("A file of the user's own that the import found (no playlist holds it): the table never "
                           "dims it. False for a downloaded or bought one.")]
    hidden: Annotated[bool, F("Whether the user hid the song.")]
    upgrade_ready: Annotated[bool, F("Whether a better version is waiting.")]
    path: Annotated[str | None, F("The file's path (absolute for the user's own songs), or null when there is none.")]
    added: Annotated[str | None, F("The playlist day (an ISO time); for an own file the day Discjockey first saw it.")]
    cover_url: Annotated[str | None, F("The media URL of the embedded cover, else the Spotify image URL, else null "
                                       "(show a placeholder).", shown=False)]
    rev: Annotated[str | None, F("The record's revision (10 hex): send it back as `expect` / `--if-rev` so the write "
                                 "refuses if the song changed since this read.", shown=False)]


@shape
class Result(TypedDict):
    """One report line (also `ActionFinished.result`, run sections and op results): the payload copy of
    `events.Result`."""
    section: Annotated[str, F("The report section the line belongs to (`report.SECTIONS`). `moved`, `adopted` and "
                                      "`conflicts` are no longer written by new runs; they stay in the list because "
                                      "past runs' reports have them.")]
    folder: Annotated[str, F("The playlist folder.")]
    artist: Annotated[str, F("The artist.")]
    title: Annotated[str, F("The title.")]
    track_id: Annotated[str | None, F("The song's id, or null.", shown=False)]
    note: Annotated[str, F("What happened, in words.")]
    status: Annotated[Status | None, F("What the sound check made of the file, or null.")]
    source: Annotated[str | None, F("Where the file came from: one of `Source`'s values, or another word the engine "
                                    "reports; null when there is none.")]
    cutoff_hz: Annotated[int | None, F("The measured cutoff in Hz, or null.", shown=False)]
    path: Annotated[str | None, F("The file's path, or null.")]
    error_kind: Annotated[ErrorKind | None, F("For an error line: what kind; null elsewhere.")]
    found_status: NotRequired[Annotated[Status | None, F(
        "upgrade_ready: the found file's status (`status` stays the current file's; a SoundCloud original can be "
        "lossless). Missing in runs saved before it.")]]
    cover_url: NotRequired[Annotated[str | None, F("`run(run_id)` only: the cover of rows shown one by one.",
                                                   shown=False)]]


@shape
class FailNext(TypedDict):
    """One command that moves on after a problem."""
    run: Annotated[str, F("The command line to run.")]
    why: Annotated[str, F("What it is for.")]


@shape
class FailPersonStep(TypedDict):
    """One step only a person can do."""
    id: Annotated[str, F("The step's id (`step:relocate_new`, `step:reload_tag`, ...).", shown=False)]
    say: Annotated[str, F("What the person does, in words.")]
    then: Annotated[str | None, F("The command that goes on afterwards, or null.")]


@shape
class Fail(TypedDict):
    """A problem answer: `{ok: false, kind, message}` and, from the bridge decorator, the command line's view of it
    (issue 39, `discjockey/hub/outcomes.py`); the window ignores the latter. `outcome`, `reason`, `next`,
    `person_steps` and `data` are always present on an answer of the engine, optional here so the fake bridge needs
    no change. The window never sends what makes a `bad_args`: a failure the command line gets is a `CliFail`."""
    ok: Annotated[Literal[False], F("Always false on a problem.", shown=False)]
    kind: Annotated[ProblemKind, F("Why it failed; the window reads this.")]
    message: Annotated[str, F("Plain words for the person.")]
    service: NotRequired[Annotated[PlaylistService, F(
        "Set when a playlist service caused the problem (a SourceError); absent for every other.")]]
    setting: NotRequired[Annotated[SettingKey, F(
        "Only with kind `setting_off` (add_playlist for a link that needs a Settings choice that is off).")]]
    outcome: NotRequired[Annotated[FailOutcome, F("The command line's outcome of the problem.", shown=False)]]
    reason: NotRequired[Annotated[str, F("The closed reason of the problem (`outcomes.REASONS`).", shown=False)]]
    next: NotRequired[Annotated[list[FailNext], F("The commands that move on.")]]
    person_steps: NotRequired[Annotated[list[FailPersonStep], F("The steps only a person can do.")]]
    data: NotRequired[Annotated[dict[str, Any] | None, F(
        "Facts that belong to the reason, a different object per reason (`outcomes.REASONS`); null or absent when "
        "there are none.")]]


@shape
class CliFail(Fail):
    """A failed answer as any caller can get it: a `Fail` whose `kind` can also be `bad_args` (a typed id or word that
    names nothing: `BadId`, an unknown `--plan`). Every failure the engine answers is checked against this shape."""
    kind: Annotated[FailKind, F("Why it failed; `bad_args` only for the command line.")]


@shape
class Empty(TypedDict):
    """An answer or a job result with nothing in it (`{}`)."""


@shape
class Freshness(TypedDict):
    """How fresh the answers are, from the stored records alone: never a scan or a fetch."""
    scanned_at: Annotated[str | None, F("When the index was last scanned (a watched folder's last scan), an ISO "
                                        "time; null while there is no music folder, no library.db or nothing was "
                                        "scanned.")]
    read_at: Annotated[str | None, F("When the playlists were last read, an ISO time; null when none was.")]


ANSWERS: dict[str, str] = {"freshness": "Freshness"}
RESULTS: dict[str, str] = {}
