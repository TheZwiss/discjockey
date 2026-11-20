"""The shapes of To-do and of one song's details (issue 39, phase 2, E7b): `todo`, `track`, the Missing files preview,
the upgrade and undo previews, the rekordbox preview, the song finder and the selection of a listing, and the results of
the jobs that act on a song (`hide`, `never_download`, the bought file, a candidate, a link, the rekordbox check, Missing
files, the upgrade batches and their undo). The meanings are those of `docs/hub-bridge-contract.md` ("Reads", "Upgrades
and batches", "Auto-upgrade", "Missing files").

`ANSWERS` maps a method to the shape of its answer without `ok` (a J method: the shape of its job's result); `RESULTS`
maps a job kind to the shape of its `JobFinished.result`."""
from typing import Annotated, Literal, NotRequired, TypedDict

from .common import EmptyKind, FailNext, FailPersonStep, PlaylistService, Quality, Result, SourceHow, TrackRow
from .kernel import F, alias, shape

TodoGroupKey = alias(
    "TodoGroupKey",
    Literal["rekordbox_check", "missing_file", "same_song", "duplicate", "upgrade_ready", "cdj", "not_found", "weak",
            "good_lossy", "fake", "other"],
    doc="A To-do group: a `TodoFilter` without `all`. The groups always come in this order.")
FileState = alias(
    "FileState", Literal["here", "offline", "folder_missing", "file_missing"],
    doc="Whether a file is there now: `here`; `offline` (its drive is not connected); `folder_missing` (its watched "
        "folder is not found); `file_missing` (the folder is there, the file's path is not: it went since the last "
        "scan, or its row waits as missing).")
MissingAction = alias(
    "MissingAction", Literal["download_again", "remove"],
    doc="What the user can do for a song whose file waits as missing: Download again for a song in a playlist, Remove "
        "from library for any other (the song decides, `missing.action_for`).")
MissingReason = alias(
    "MissingReason",
    Literal["not_missing", "away", "wrong_action", "found_twice", "never", "check_open", "place_refused", "asked"],
    doc="Why the Missing files action can't run for a song now (`missing.why_not`), the first that applies.")


# --- a song's details: `track` ---

@shape
class Alignment(TypedDict):
    """How well a parked version lines up with the current file (the measurement behind \"the cues stay\")."""
    drift_ms: Annotated[float | None, F("Drift over the file in milliseconds, or null when not measured.",
                                        shown=False)]
    offset_ms: Annotated[float | None, F("Offset between the two files in milliseconds, or null when not measured.",
                                         shown=False)]
    offset_samples: Annotated[int | None, F("The offset in samples, or null when not measured.", shown=False)]
    result: Annotated[str, F("What the two files measured as: exact, shifted, different or unknown.")]
    text: Annotated[str, F("The measurement in words (\"matches exactly\").")]


@shape
class AutoRefused(TypedDict):
    """The refusal the sync's Auto-upgrade phase recorded on a parked upgrade; shown whatever the switch says."""
    reason: Annotated[Literal["timing", "not_analysed", "cloud", "space", "needs_choice"],
                      F("Why the phase left it alone.")]
    message: Annotated[str, F("The refusal in words.")]
    at: Annotated[str | None, F("When it was recorded, an ISO time.")]


@shape
class UpgradeRekordbox(TypedDict):
    """rekordbox's cached state on this Mac."""
    state: Annotated[Literal["ready", "none", "unreadable"],
                     F("`ready`: a library Discjockey can open; `none`: no rekordbox library; `unreadable`: one it "
                       "cannot open.")]
    running: Annotated[bool, F("Whether rekordbox is open.")]


@shape
class Upgrade(TypedDict):
    """The better version parked for a song (`track().upgrade`); null on the song when none waits. Swap only when
    `swap_safe` and `swap_possible`; `cue_text` is the line to show."""
    file: Annotated[str, F("The parked file's path, under Upgrades ready/.", shown=False)]
    source: Annotated[str, F("Where it came from: one of `Source`'s values or another word the engine reports.")]
    source_name: Annotated[str, F("The source in short words (Qobuz, YT Music, SoundCloud).")]
    source_id: Annotated[str, F("The source's own id for it.", shown=False)]
    found: Annotated[str, F("The day it was found, an ISO date.")]
    what: Annotated[str, F("What it is (\"lossless version\", or e.g. \"256 kbps version\").")]
    quality_line: Annotated[str, F("The new version's quality, as the current file's `format_line` says it "
                                   "(\"FLAC · lossless\").")]
    format_line: Annotated[str, F("The parked version's quality in the words of the current file's "
                                  "`source_format_line` (\"FLAC · lossless\", \"AAC · 256 kbps\").")]
    alignment: Annotated[Alignment, F("How it lines up with the current file.")]
    cue_text: Annotated[str, F("The line about the cues: the measurement combined with `swap_possible`.")]
    swap_safe: Annotated[bool, F("The two files measured as the same edit (exact or shifted).")]
    swap_possible: Annotated[bool, F("Same track can run now (any format); `why_not` says why not otherwise.")]
    why_not: Annotated[str | None, F("The eligibility reason key that blocks Same track, null when it can run.")]
    swap_how: Annotated[Literal["in_place", "new_aiff"],
                        F("`in_place`: an AIFF takes the audio; `new_aiff`: a new AIFF with a clean name, rekordbox's "
                          "track pointed at it.")]
    rekordbox: Annotated[UpgradeRekordbox, F("rekordbox's cached state on this Mac.")]
    auto_refused: Annotated[AutoRefused | None, F("The refusal the sync's Auto-upgrade phase recorded, or null.")]
    auto_waits: Annotated[bool, F("The sync met rekordbox open for this upgrade: true only while the switch is on and "
                                  "Same track could run.")]
    audio_url: Annotated[str | None, F("The media URL of the parked file, or null.", shown=False)]


@shape
class FreeDownload(TypedDict):
    """The artist's free download of a SoundCloud version: a gate page (follow, like or e-mail) or SoundCloud's own
    download button."""
    url: Annotated[str, F("The page to open (SoundCloud's own page when `direct`).", shown=False)]
    host: Annotated[str, F("The gate page's host (hypeddit.com).")]
    direct: Annotated[bool, F("SoundCloud's own download button, not a gate page.")]
    title: Annotated[str, F("The title of the upload.")]
    uploader: Annotated[str, F("Who uploaded it.")]


@shape
class TrackLink(TypedDict):
    """The track's page on the service it was read from."""
    url: Annotated[str, F("The page to open.", shown=False)]
    label: Annotated[str, F("\"Open in Spotify\", \"Open in Qobuz\", \"Open in SoundCloud\" or \"Open in YouTube "
                            "Music\".")]
    service: Annotated[PlaylistService, F("The service the page belongs to (the logo beside \"Open in …\").")]


@shape
class TrackBuyLinks(TypedDict):
    """Where to buy the song."""
    beatport: Annotated[str, F("A Beatport search for it.", shown=False)]
    bandcamp: Annotated[str, F("A Bandcamp search for it.", shown=False)]


@shape
class CdjWords(TypedDict):
    """What the CDJs refuse in a file, in words (the `cdj` of `track().aiff` and of an AIFF plan item)."""
    short: Annotated[str, F("To-do's one line.")]
    words: Annotated[str, F("The sentence for the panels.")]


# `from` is a Python keyword, so the shape is written in the functional form
TrackAiff = TypedDict("TrackAiff", {
    "action": Annotated[Literal["convert", "rename"] | None, F("What can run, or null when nothing can.")],
    "why_not": Annotated[str | None, F("An `EligibleReason` key when the action is blocked, else null.")],
    "kind": Annotated[str | None, F("The kind of item (an `AiffKind`: flac, wav, alac, aiff_hires, tags, name, ...); "
                                    "null when `action` is.")],
    "from": Annotated[str | None, F("The file's format line (\"FLAC · 24-bit · 96 kHz\").")],
    "to": Annotated[str | None, F("What a Convert makes (\"AIFF · 16-bit · 44.1 kHz\"); null for a rename.")],
    "name_now": Annotated[str, F("The file's name now.")],
    "new_name": Annotated[str | None, F("The file's name when done (equal to `name_now` for a Convert whose AIFF ends "
                                        "where the old file was).")],
    "bytes": Annotated[int, F("The room the render needs.")],
    "lossy": Annotated[bool, F("Whether the file is lossy.")],
    "cdj": Annotated[CdjWords | None, F("What the CDJs refuse in the file, or null.")],
})
TrackAiff.__doc__ = (
    "What Convert and \"Give it its clean name\" can do for a file (issue 33 stage D); null on the song: no file, a "
    "download or a parked upgrade (the upgrade decision stands). `why_not` set means the action is blocked: for "
    "`rekordbox_unreadable`, `cloud` and `rename_blocked` the `action` and its `kind` / `to` / `new_name` / `bytes` are "
    "still the step's own (judged as if rekordbox were not in the way; no free name is a rename with `new_name` null), "
    "so the card shows Becomes, Name and Space and says why it waits. For any other reason (an `EligibleReason` key "
    "such as `named_already`, `away`) `action` is null, `kind` / `to` / `new_name` null, `bytes` 0. `from`, `lossy` and "
    "`cdj` always say what the file is.")
shape(TrackAiff)


@shape
class MissingView(TypedDict):
    """What the user can do for a song whose file waits as missing (`missing.view`): the single song's button, why it
    can't run, and what it does."""
    since: Annotated[str, F("The ISO day of the first scan that missed the file.")]
    place: Annotated[str, F("Where the file was (the Folder column's words); empty without a path.")]
    action: Annotated[MissingAction, F("The action the song gets (the song decides, not a choice).")]
    label: Annotated[str, F("The single song's button: \"Download again\" or \"Remove from library…\".")]
    tone: Annotated[Literal["filled", "danger"], F("The button's tone: `filled` for Download again, `danger` for "
                                                   "Remove (it asks first).")]
    why_not: Annotated[MissingReason | None, F("Why the action can't run now, null when it can.")]
    words: Annotated[str | None, F("The reason's sentence, null when `why_not` is null.")]
    foot_note: Annotated[str | None, F("The words to show under a disabled button: `words`, null when nothing holds "
                                       "the action back or the note above says them already (found in several "
                                       "places, its drive away).")]
    will: Annotated[str, F("What the action does for this song (\"Downloads again at your next sync\", \"Gets the "
                           "better version already waiting for it at your next sync; nothing is downloaded\", "
                           "\"Removed from your library\").")]
    upgrade_waiting: Annotated[bool, F("A parked better version waits (Download again puts it in, Remove deletes "
                                       "it).")]
    in_missing_files: Annotated[bool, F("To-do's Missing files group lists the song: true unless Download again was "
                                        "asked and no held refusal keeps it there.")]


@shape
class MissingDetail(MissingView):
    """`track().missing`: the song's `MissingView` plus the words of the details panel. Null on the song when its file
    isn't marked missing (a file gone since the last scan shows `file_state` `file_missing` without it)."""
    line: Annotated[str, F("\"Missing since 12 Nov. It was in Techno 2019.\"; in several places \"Found in 2 places: "
                           "Techno 2019 and Old crates.\"")]
    hint: Annotated[str, F("What can be done, by `why_not` first and then by action: the To-do panel's, with its "
                           "buttons.")]
    hint_library: Annotated[str, F("The same for the Library, whose foot only opens To-do; the same text when the song "
                                   "was found in several places or was asked for already.")]


@shape
class TrackDetail(TrackRow):
    """One song's details (`track`): the row plus everything the details panel shows. `audio_url` is null for every
    `file_state` but `here`."""
    sound_checked: Annotated[bool, F("False: an imported file whose sound isn't judged yet; `quality_line` then ends "
                                     "\"sound not checked yet\".")]
    file_state: Annotated[FileState, F("Whether the file is there now, decided per watched folder and, for a song whose "
                                       "file waits as missing, by the stored mark (`offline` wins when its drive is "
                                       "away).")]
    place: Annotated[str | None, F("Where the file sits, as the Folder column says it; null without a file.")]
    cutoff_text: Annotated[str | None, F("The cutoff in words, as the stat card says it (\"16.0 kHz · where the highs "
                                         "end · lossless reaches about 22 kHz\"); null for a lossless or missing file "
                                         "and for a sound not checked yet.")]
    isrc: Annotated[str | None, F("The song's ISRC, or null.")]
    playlists: Annotated[list[str] | None, F("The playlist folders holding the song, null until the playlists were "
                                             "read.")]
    in_playlist_count: Annotated[int | None, F("How many playlists hold the song; null until the playlists were "
                                               "read.")]
    quality_line: Annotated[str | None, F("The file's source and quality (\"YouTube OPUS · cutoff 16.0 kHz\"); null "
                                           "without a file.")]
    format_line: Annotated[str | None, F("The file itself (\"AIFF · 16-bit\", \"WAV · 24-bit\", \"FLAC\"); null "
                                         "without a file.")]
    source_full: Annotated[str | None, F("The source in full words (\"YouTube Music\", \"bought\", \"your own "
                                         "file\"); null without a file.")]
    source_format_line: Annotated[str | None, F("What the download was made from (\"Opus · 135 kbps\", \"FLAC\"); "
                                                "null without a file and for an own or bought file.")]
    source_how: Annotated[SourceHow | None, F("How the source was found; null for an own or bought file and for a "
                                              "file from before this was stored.")]
    source_url: Annotated[str | None, F("The source's page; null when it is the song's own page (`track_link`).",
                                        shown=False)]
    track_link: Annotated[TrackLink | None, F("The track's page on the service it was read from, or null.")]
    next_qobuz_check: Annotated[str | None, F("An ISO date, `next_sync`, or null.")]
    rejected_sources: Annotated[list[str], F("The sources the user rejected for this song.")]
    buy_links: Annotated[TrackBuyLinks, F("Search links to buy the song.")]
    free_downloads: Annotated[list[FreeDownload], F("The artists' free downloads found on SoundCloud while the track "
                                                    "is not lossless.")]
    bought_name: Annotated[str, F("The path a bought file would be dropped at.", shown=False)]
    audio_url: Annotated[str | None, F("The media URL of the file; null for every `file_state` but `here`.",
                                       shown=False)]
    upgrade: Annotated[Upgrade | None, F("The parked better version, or null.")]
    aiff: Annotated[TrackAiff | None, F("What Convert and the clean name can do for this file, or null.")]
    missing: Annotated[MissingDetail | None, F("The song's file waits as missing (issue 43), or null.")]


@shape
class TrackAnswer(TypedDict):
    """The answer of `track`."""
    track: Annotated[TrackDetail, F("The song's details.")]


# --- To-do ---

@shape
class CdjWhy(CdjWords):
    """Why the CDJ-3000 or the CDJ-2000NXS2 refuses or stutters on a file (`cdj.cdj_problem`)."""
    reason: Annotated[Literal["format", "bitrate", "bits", "rate_high", "rate_low"], F("The problem's key.")]


@shape
class RekordboxCheckBatch(TypedDict):
    """The AIFF batch that left a check."""
    id: Annotated[int, F("The batch's id.", shown=False)]
    size: Annotated[int, F("How many of its checks are still open.")]


@shape
class RekordboxCheckWritten(TypedDict):
    """What was written in rekordbox."""
    entries: Annotated[int, F("How many tracks.")]
    kept: Annotated[list[str], F("The fields kept as the user edited them.")]


@shape
class RekordboxCheckView(TypedDict):
    """A `rekordbox_check` item's check (`views.check_view`): the step that left it, what the two files measured as and
    what to do in rekordbox. The item's `detail` is the row's short line."""
    reason: Annotated[str, F("The step that left the check: wrong_song, added_as_new, swapped, repointed, converted, "
                             "renamed or placed_missing.")]
    since: Annotated[str | None, F("When the check was left, an ISO time, or null.")]
    match: Annotated[str | None, F("What the two files measured as (exact, shifted, different, unknown); null in "
                                   "records from before it.")]
    offset_ms: Annotated[float | None, F("The measured offset in milliseconds, or null.", shown=False)]
    moved: Annotated[bool, F("Whether the audio moved against rekordbox's timeline.")]
    aligned: Annotated[bool, F("An added file that Discjockey rendered lined up with rekordbox's timeline of the old "
                               "one: the old track's cues fit it to the sample; false for a swap and in records from "
                               "before it.")]
    text: Annotated[str, F("The whole instruction for the person.")]
    old_path: Annotated[str | None, F("Where the old file (added) or the copy of the old audio (swap) is now; null "
                                      "without an undo record.")]
    relocate: Annotated[bool, F("An added file whose old file is an AIFF, so rekordbox's Relocate takes the new file; "
                                "false for any other old file and for records from before it.")]
    reload_tag: Annotated[bool, F("False when Discjockey wrote rekordbox's text itself (no Reload Tag step); true for "
                                  "older records.")]
    batch: Annotated[RekordboxCheckBatch | None, F("The AIFF batch that left the check, null when none.")]
    rekordbox: Annotated[RekordboxCheckWritten | None, F("What was written in rekordbox, null when nothing.")]
    old_name: Annotated[str | None, F("A `renamed` check's old base name (\"Artist - Title [FREE DL].aiff\"), null for "
                                      "every other check.")]
    person_steps: Annotated[list[FailPersonStep], F("The steps only the person can do in rekordbox (the command "
                                                    "line's; the window words its own); empty for a check that "
                                                    "leaves nothing to do.")]


@shape
class TodoItemBase(TrackRow):
    """One song of a To-do group: the row plus the group's own words. `pair`, `can_undo` and the others are set only on
    the groups that use them. `free` and `own` are NotRequired because the engine leaves them off some items (findings,
    the window's types call both always there); the generated TypeScript still says `TrackRow & {...}`, where `own` is
    required."""
    group: Annotated[TodoGroupKey, F("The group the item is in.")]
    detail: Annotated[str, F("The row's short line (what to do, or why it is here).")]
    free: NotRequired[Annotated[bool, F("The artist gives it away: a not found, weak, good lossy or fake track with a "
                                        "free download (the row's FREE tag). Not sent by the engine on a "
                                        "`rekordbox_check` item (finding).")]]
    own: NotRequired[Annotated[bool, F("A file of the user's own that the import found (no playlist holds it). Not sent "
                                       "by the engine on a duplicate group's item (finding); a `TrackRow` has it "
                                       "always.")]]
    file_state: Annotated[Literal["here", "offline", "folder_missing", "file_missing", "no_file"],
                          F("Whether the item's file is there now (`FileState`), or `no_file`: the song has none "
                            "(Not found).")]
    missing: NotRequired[Annotated[MissingView, F("`missing_file` items (issue 43): the song's waiting file, with its "
                                                  "action and the engine's words.")]]
    can_undo: NotRequired[Annotated[bool, F("`rekordbox_check` items: the check belongs to a swap or an added file "
                                            "`undo_upgrade` can still put back.", shown=False)]]
    check: NotRequired[Annotated[RekordboxCheckView, F("`rekordbox_check` items: the check.")]]
    same_track: NotRequired[Annotated[str | None, F("`upgrade_ready` items: why Same track can't run now (an "
                                                    "`EligibleReason` key), null when it can.")]]
    cdj: NotRequired[Annotated[CdjWhy, F("`cdj` items: what the CDJs refuse in the file.")]]
    aiff: NotRequired[Annotated[str | None, F("`cdj` items: why Convert can't run now (an `EligibleReason` key), null "
                                              "when it can.")]]


# --- the import's two groups: a question and a duplicate group ---

@shape
class FileSide(TypedDict):
    """One file of a question or of a duplicate group. `path` is absolute for an import folder's file."""
    file_id: Annotated[int, F("The file's id.", shown=False)]
    song_key: Annotated[str | None, F("The song the file is linked to, or null.", shown=False)]
    path: Annotated[str, F("The file's path.")]
    artist: Annotated[str, F("The artist.")]
    title: Annotated[str, F("The title.")]
    duration_s: Annotated[float, F("The length in seconds.")]
    quality: Annotated[Quality, F("The colour class.")]
    quality_label: Annotated[str, F("The words next to the colour.")]
    online: Annotated[bool, F("The file is there by the folder rule only (`here`), not offline.")]
    audio_url: Annotated[str | None, F("The media URL to play; null only for a file that is offline or can't be "
                                       "played (an import folder's file plays through `file/<file_id>`).",
                                       shown=False)]
    in_playlist: Annotated[bool, F("Whether the file is the library's file of a playlist song.")]


@shape
class QuestionPairTrack(TypedDict):
    """The playlist song a question is about."""
    artist: Annotated[str, F("The artist.")]
    title: Annotated[str, F("The title.")]
    duration_s: Annotated[float, F("The length in seconds.")]
    folder: Annotated[str, F("The playlist folder.")]
    link: Annotated[str | None, F("The song's link, or null.", shown=False)]


QuestionWhy = alias("QuestionWhy", Literal["artist", "no_artist", "length", "no_length"],
                    doc="Why a question is asked: the artist matched, the file has no artist, the lengths differ, or one "
                        "has none.")
DuplicateWhy = alias("DuplicateWhy", Literal["same_audio", "same_song"], doc="Why the files of a group are one group.")


@shape
class QuestionPair(TypedDict):
    """\"Is this the same song?\": a playlist song a file of the user's own might be."""
    song_key: Annotated[str, F("The playlist song's key.", shown=False)]
    own_key: Annotated[str, F("The user's own song's key.", shown=False)]
    why: Annotated[QuestionWhy, F("Why it is asked.")]
    delta_s: Annotated[int | None, F("The file's length minus the song's in whole seconds; null with `no_length`.")]
    track: Annotated[QuestionPairTrack, F("The playlist song.")]
    file: Annotated[FileSide, F("The user's own file.")]


@shape
class DuplicatePair(TypedDict):
    """A group of files that are the same audio or the same song: two or more, by file id."""
    group_id: Annotated[str, F("The group's id.", shown=False)]
    why: Annotated[DuplicateWhy, F("Why the files are one group.")]
    files: Annotated[list[FileSide], F("The files of the group.")]
    recommended: Annotated[int | None, F("The `file_id` the panel picks to keep (the better sound, then AIFF), null "
                                         "when there is no clear winner.", shown=False)]
    recommended_why: Annotated[str | None, F("The recommendation's one line (\"Recommended: best quality\").")]


@shape
class TodoPlainItem(TodoItemBase):
    """An item that is not a batch: one of a batch's checks, or any other single item."""
    pair: NotRequired[Annotated[QuestionPair | DuplicatePair, F("Only the import's two groups (`same_song`, "
                                                                "`duplicate`) have one.")]]
    key: NotRequired[Annotated[str, F("A batch item's key, `batch:<id>`.", shown=False)]]


@shape
class BatchCheck(TypedDict):
    """A `BatchCheckItem`'s batch: the open checks of one AIFF batch, as one item. The engine words the batch, the
    window prints the words as they are."""
    id: Annotated[int, F("The batch's id.", shown=False)]
    size: Annotated[int, F("How many open checks the batch has.")]
    started: Annotated[str | None, F("The earliest check's date.")]
    aiff_id: NotRequired[Annotated[str, F("`aiff:<id>`, the id the command line takes for this batch (the window "
                                          "ignores it).", shown=False)]]
    started_by: Annotated[str | None, F("Who started the batch (`aiff_batches.started_by`): user, upgrade_all, "
                                        "make_aiff, cdj_all, auto_upgrade (the sync's Auto-upgrade phase), "
                                        "download_again (the same phase with the switch off, putting in the parked "
                                        "better version of a missing song); null when unknown.")]
    from_sync: Annotated[bool, F("The sync's last phase made the batch: it reads as \"Upgraded during your sync\".")]
    kind: Annotated[Literal["upgrade", "convert", "mixed"] | None,
                    F("The batch's own kind (`aiff_batches.kind`): a Convert batch says \"Made AIFF\"; null when "
                      "unknown.")]
    row_name: Annotated[str, F("The To-do row's name (\"3 tracks upgraded\", \"3 better versions put in\", \"3 tracks "
                               "changed\").")]
    row_sub: Annotated[str, F("The row's sub line (\"today · Same track\").")]
    list_title: Annotated[str, F("The title of the batch's list.")]
    card_summary: Annotated[str | None, F("The summary of the \"In rekordbox\" card (\"same track(s), cues kept\", "
                                          "\"better versions in\"); null when the card has no steps.")]
    placed_summary: Annotated[str | None, F("\"better versions in\" when the batch holds a placement, else null.")]
    tracks: Annotated[list[TodoPlainItem], F("The batch's checks as single items.")]


@shape
class TodoItem(TodoPlainItem):
    """A To-do item as a group lists it: any of the optional keys of the groups' items."""
    batch: NotRequired[Annotated[BatchCheck, F("A batch's open checks (two or more) are one item.")]]


@shape
class QuestionItem(TodoItemBase):
    """An item of the `same_song` group."""
    pair: Annotated[QuestionPair, F("The question.")]


@shape
class DuplicateItem(TodoItemBase):
    """An item of the `duplicate` group."""
    pair: Annotated[DuplicatePair, F("The group of files.")]


@shape
class BatchCheckItem(TodoItemBase):
    """An item of the `rekordbox_check` group that stands for an AIFF batch (`group` `rekordbox_check`; the first
    track's row fields)."""
    key: Annotated[str, F("`batch:<id>`, also the item's `track_id`.", shown=False)]
    batch: Annotated[BatchCheck, F("The batch.")]


# --- the groups and the page ---

@shape
class MissingAll(TypedDict):
    """The `missing_file` group's `all`: what the head link and the commands' `--all` act on."""
    download_again: Annotated[int, F("Items not hidden whose action is Download again and can run now.")]
    remove: Annotated[int, F("Items not hidden whose action is Remove and can run now.")]
    label: Annotated[str | None, F("The head link's words, \"Select all · {k}\" over the group's items that are not "
                                   "hidden; null under two.")]


@shape
class TodoGroupStopped(TypedDict):
    """The newest stopped batch with items left."""
    batch_id: Annotated[int, F("The batch's id.", shown=False)]
    left: Annotated[int, F("How many items are left.")]


@shape
class TodoGroupHead(TypedDict):
    """What every To-do group has."""
    label: Annotated[str, F("The group's name.")]
    hint: Annotated[str, F("The group's one line.")]
    items: Annotated[list[TodoItem], F("The items of the group.")]
    stopped: NotRequired[Annotated[TodoGroupStopped | None, F("The newest stopped batch with items left "
                                                              "(`upgrade_ready`, `cdj`).")]]


@shape
class MissingGroup(TodoGroupHead):
    """The `missing_file` group (issue 43)."""
    key: Annotated[Literal["missing_file"], F("The group's key.")]
    all: NotRequired[Annotated[MissingAll, F("Counts by action what the head link and the commands' `--all` act "
                                             "on.")]]


@shape
class CountedGroupAll(TypedDict):
    """`all` of a counted group. `upgrade_ready`: Upgrade all's counts (Same track can run `n` / the edit needs a
    choice `m` / waits for something else `k`). `cdj`: what Convert all can do now `n` and what waits `k`, no `m`."""
    n: Annotated[int, F("What can run now.")]
    m: NotRequired[Annotated[int, F("`upgrade_ready` only: what needs a choice.")]]
    k: Annotated[int, F("What waits for something else.")]


@shape
class CountedGroup(TodoGroupHead):
    """Every group but `missing_file`. `upgrade_ready` and `cdj` carry `all` and `stopped`."""
    key: Annotated[Literal["rekordbox_check", "same_song", "duplicate", "upgrade_ready", "cdj", "not_found", "weak",
                           "good_lossy", "fake", "other"], F("The group's key.")]
    all: NotRequired[Annotated[CountedGroupAll, F("What the group's bulk button acts on.")]]


TodoGroup = alias("TodoGroup", MissingGroup | CountedGroup, doc="One group of the To-do page.")


@shape
class Todo(TypedDict):
    """The To-do page (`todo`): the groups always in the order of `TodoFilter` (the import adds `same_song` and
    `duplicate` after the first; issue 43 `missing_file` second). `chips` counts exclude hidden items."""
    chips: Annotated[dict[str, int], F("How many items each filter holds, a key for every `TodoFilter` (hidden ones "
                                       "left out; `chips.all` counts each song once; `rekordbox_check` counts items, "
                                       "a batch is one).")]
    check_tracks: Annotated[int, F("The tracks with an open check in rekordbox whatever the filter (a batch counts "
                                   "its `size`): the page header's number.")]
    hidden_count: Annotated[int, F("How many hidden items there are, for \"Show hidden (N)\".")]
    show_hidden: Annotated[bool, F("Whether hidden items are listed.")]
    sub: Annotated[list[str], F("The page header's second line as parts in order of importance (\"3 tracks are not "
                                "lossless yet\", \"2 songs are missing their file\"; [\"Nothing to do\"] when "
                                "none).")]
    groups: Annotated[list[TodoGroup], F("The groups with items, in order.")]
    empty: Annotated[EmptyKind | None, F("Why the page has nothing to show, or null.")]
    empty_text: Annotated[str | None, F("`empty`'s words for the command line (\"Everything is lossless.\"), null for "
                                        "no state or one the engine has no words for.")]


# --- Missing files ---

@shape
class MissingPreviewItem(TypedDict):
    """One song of `missing_files_preview` (`missing.preview`)."""
    track_id: Annotated[str, F("The song's key.", shown=False)]
    artist: Annotated[str, F("The artist.")]
    title: Annotated[str, F("The title.")]
    place: Annotated[str, F("Where its file was.")]
    since: Annotated[str | None, F("The ISO day its file was first missed; null when it is not missing.")]
    will: Annotated[bool, F("Whether the action runs for it now.")]
    reason: Annotated[MissingReason | None, F("Why not, null when `will`.")]
    words: Annotated[str, F("The action's `will` sentence when it does, else the reason's sentence.")]
    upgrade_waiting: Annotated[bool, F("A parked better version waits (Download again puts it in, Remove deletes "
                                       "it).")]


@shape
class MissingConfirm(TypedDict):
    """Remove's question as the engine words it (`missing.confirm_for`): the plural for several songs."""
    title: Annotated[str, F("The question (\"Remove from your library?\").")]
    body: Annotated[str, F("What removing does.")]
    confirm_label: Annotated[str, F("The button's words, \"Remove\".")]
    tone: Annotated[Literal["danger"], F("The button's tone.")]


@shape
class MissingPreview(TypedDict):
    """`missing_files_preview`: what Download again or Remove would do for these songs, one item per song in the order
    asked (a key that is no song is an item with `reason` `not_missing`)."""
    action: Annotated[MissingAction, F("The action asked.")]
    items: Annotated[list[MissingPreviewItem], F("One item per song.")]
    n: Annotated[int, F("How many will run.")]
    skipped: Annotated[int, F("How many will not.")]
    words: Annotated[str, F("The one line (\"2 songs download again at your next sync; 1 is skipped.\").")]
    button: Annotated[str | None, F("The selection panel's button over the `n` (\"Download again · 2\", \"Remove from "
                                    "library · 2…\"); null when none runs.")]
    confirm: Annotated[MissingConfirm | None, F("Remove's question for them; null for Download again and for none.")]


@shape
class MissingItemResult(TypedDict):
    """One song of a finished `missing_files` job."""
    track_id: Annotated[str, F("The song's key.", shown=False)]
    action: Annotated[MissingAction, F("The action asked.")]
    state: Annotated[Literal["done", "skipped"], F("What became of it.")]
    reason: Annotated[MissingReason | None, F("Why it was skipped, null when done.")]
    words: Annotated[str | None, F("A done song's `will` sentence or a skipped song's reason sentence.")]


@shape
class MissingResult(TypedDict):
    """`JobFinished.result` of `missing_files`. Every song skipped ends the job `changed` with this result kept."""
    action: Annotated[MissingAction, F("The action run.")]
    results: Annotated[list[MissingItemResult], F("One row per song.")]
    done: Annotated[list[str], F("The keys of the songs done.", shown=False)]
    skipped: Annotated[list[str], F("The keys of the songs skipped.", shown=False)]
    words: Annotated[str, F("The one line in the past (\"Removed 2 songs from your library; 1 is skipped.\").")]
    recovered: Annotated[list[tuple[str, bool]], F("What a recovery of an earlier crash put right, `[what, ok]` per "
                                                   "line.")]


# --- the results of the jobs that act on a song ---

@shape
class OpResult(TypedDict):
    """The result of `hide`, `unhide`, `add_bought_file`, `use_candidate`, `use_link` and `reject_current`."""
    track_id: Annotated[str, F("The song's key.", shown=False)]
    result: Annotated[Result, F("The report line of what was done.")]
    recovered: Annotated[list[tuple[str, bool]], F("What a recovery of an earlier crash put right, `[what, ok]` per "
                                                   "line.")]


@shape
class NeverDownloadResult(TypedDict):
    """The result of `never_download`."""
    track_id: Annotated[str, F("The song's key.", shown=False)]
    never: Annotated[bool, F("Whether the song is now left out of the sync.")]


@shape
class ItemResultRekordbox(TypedDict):
    """What was written in rekordbox for one track."""
    entries: Annotated[list[str], F("The rekordbox tracks written.", shown=False)]
    kept: Annotated[list[str], F("The fields kept as the user edited them.")]


@shape
class ItemResult(TypedDict):
    """One track of a batch."""
    track: Annotated[str, F("The song's key.", shown=False)]
    action: Annotated[str, F("What was done: same_track, add_new, convert, rename, ...")]
    state: Annotated[Literal["planned", "done", "skipped", "failed", "undone"], F("What became of it.")]
    reason: Annotated[str | None, F("An `EligibleReason` key (skipped only).")]
    message: Annotated[str | None, F("The words.")]
    path: Annotated[str | None, F("The file's path.")]
    rekordbox: Annotated[ItemResultRekordbox | None, F("What was written in rekordbox, or null.")]


@shape
class AiffBatchResult(TypedDict):
    """The result of `upgrade` (Same track, New track, Discard), `upgrade_all`, `batch_resume` and, in stage D,
    `convert`, `rename` and `make_aiff`. New track and Discard lists have the same shape with `batch` null; a job also
    carries it when it ends `stopped`, `rekordbox_open`, `busy` or `refused`."""
    batch: Annotated[int | None, F("The batch's id, null for a New track or Discard list.", shown=False)]
    state: Annotated[Literal["running", "stopped", "done"], F("How the batch ended.")]
    stop_reason: Annotated[Literal["stop", "rekordbox_open", "busy", "crash"] | None,
                           F("Why it stopped, null when it did not.")]
    total: Annotated[int, F("How many tracks it holds.")]
    done: Annotated[int, F("How many were done.")]
    skipped: Annotated[int, F("How many were skipped.")]
    failed: Annotated[int, F("How many failed.")]
    results: Annotated[list[ItemResult], F("One row per track.")]
    backup: Annotated[str | None, F("The id of the copy of rekordbox's library made for it, or null.")]
    recovered: Annotated[list[tuple[str, bool]], F("What a recovery of an earlier crash put right, `[what, ok]` per "
                                                   "line.")]
    new_since_plan: NotRequired[Annotated[list[str], F("A run with a plan (`--plan`): the songs named that the plan "
                                                       "did not have, left out.", shown=False)]]


@shape
class UndoItem(TypedDict):
    """One track of an undo."""
    track: Annotated[str, F("The song's key.", shown=False)]
    state: Annotated[Literal["undone", "refused", "failed", "waiting"], F("What became of it.")]
    reason: Annotated[str | None, F("Why it was refused.")]
    message: Annotated[str, F("The words.")]


@shape
class UndoResult(TypedDict):
    """The result of `undo_upgrade` (and of `batch_undo`)."""
    batch: Annotated[int | None, F("The batch undone, null for single songs.", shown=False)]
    total: Annotated[int, F("How many tracks.")]
    undone: Annotated[int, F("How many were undone.")]
    refused: Annotated[int, F("How many were refused.")]
    failed: Annotated[int, F("How many failed.")]
    results: Annotated[list[UndoItem], F("One row per track.")]
    recovered: Annotated[list[tuple[str, bool]], F("What a recovery of an earlier crash put right, `[what, ok]` per "
                                                   "line.")]
    words: NotRequired[Annotated[str, F("What the undo says when it worked (\"Conversion undone. Your old file is "
                                        "back.\"); only on success.")]]


@shape
class CheckedResult(TypedDict):
    """The result of `rekordbox_checked`."""
    results: Annotated[list[Result], F("One report line per track checked.")]
    checked: Annotated[list[str], F("The keys of the checks cleared.", shown=False)]
    not_checked: Annotated[list[str], F("The keys that had no open check.", shown=False)]
    recovered: Annotated[list[tuple[str, bool]], F("What a recovery of an earlier crash put right, `[what, ok]` per "
                                                   "line.")]
    batch: NotRequired[Annotated[int, F("Only when `rekordbox_checked` was sent a `batch_id` (the command line's "
                                        "`--batch`).", shown=False)]]
    newer: NotRequired[Annotated[dict[str, str | None], F(
        "Only with `batch`: the songs of the batch whose check a later batch took, each with that batch's id "
        "(`aiff:<n>`), or null when it is not an AIFF batch.", shown=False)]]


# --- the command line's reads (cli-first) ---

@shape
class FoundTrack(TypedDict):
    """One song `find_tracks` found."""
    track_id: Annotated[str, F("The song's key.", shown=False)]
    artist: Annotated[str, F("The artist.")]
    title: Annotated[str, F("The title.")]
    rel_path: Annotated[str | None, F("The file's path relative to the music folder; null without a file and for a "
                                      "file of an import folder.")]
    path: Annotated[str | None, F("The file's absolute path; null without a file.")]


@shape
class FindTracksAnswer(TypedDict):
    """The songs that match, in artist then title order. With no hit and playlists read long ago, `next` says to
    read them."""
    rows: Annotated[list[FoundTrack], F("The songs found.")]
    total: Annotated[int, F("How many.")]
    next: NotRequired[Annotated[list[FailNext], F("`sync read`, when there is no hit and the playlists were read before "
                                                  "their last change or more than a day ago.")]]


@shape
class SelectListingAnswer(TypedDict):
    """The songs a listing selects."""
    ids: Annotated[list[str], F("Every song the screen of the listing shows, each once, in the order shown.",
                                shown=False)]
    message: NotRequired[Annotated[str, F("A verb's \"all\" that selects none: the words the window says then.")]]


@shape
class UpgradePreviewRekordbox(TypedDict):
    """rekordbox's state for a batch preview."""
    state: Annotated[Literal["ready", "none", "unreadable"], F("rekordbox's cached state on this Mac.")]
    running: Annotated[bool, F("Whether rekordbox is open.")]
    needs_rekordbox_closed: Annotated[bool, F("A Same track that is not a swap must wait for rekordbox to be quit.")]


@shape
class UpgradePreviewItem(TypedDict):
    """One song of an upgrade preview (`batches.preview_row`)."""
    key: Annotated[str, F("The song's key.", shown=False)]
    action: Annotated[str, F("What the plan names: same_track or add_new.")]
    state: Annotated[Literal["planned", "skipped"], F("Whether it would run.")]
    reason: Annotated[str | None, F("Why not, an `EligibleReason` key.")]
    file: Annotated[str | None, F("The current file's absolute path.")]
    new_file: Annotated[str | None, F("The file it would make, an absolute path; null when none.")]
    superseded: Annotated[str | None, F("Where the old file would go, an absolute path; null when none.")]


@shape
class DiscardPreviewItem(TypedDict):
    """One song of a Discard preview."""
    key: Annotated[str, F("The song's key.", shown=False)]
    action: Annotated[Literal["discard"], F("Always discard.")]
    state: Annotated[Literal["planned", "skipped"], F("Whether it would run.")]
    reason: Annotated[str | None, F("Why not (`no_upgrade`).")]
    file: Annotated[str | None, F("The current file (it stays), an absolute path.")]
    parked: Annotated[str | None, F("The parked better version that is deleted for good, an absolute path.")]


@shape
class UpgradePreviewSpace(TypedDict):
    """What the new files need on one drive."""
    drive: Annotated[str, F("The folder that decides the drive.")]
    needed: Annotated[int, F("Bytes needed.")]
    free: Annotated[int, F("Bytes free.")]
    enough: Annotated[bool, F("Whether it fits.")]


@shape
class UpgradePreviewAnswer(TypedDict):
    """What an upgrade would do, answered before it runs (the dry run of `upgrade apply`; Upgrade all). Discard's items
    are the current file that stays and the parked download that is deleted, and it has no `space` or `rekordbox`.
    Reads only."""
    mode: Annotated[Literal["same_track", "new_track", "discard"], F("The mode asked.")]
    total: Annotated[int, F("How many songs.")]
    planned: Annotated[int, F("How many would run.")]
    skipped: Annotated[int, F("How many would not.")]
    items: Annotated[list[UpgradePreviewItem | DiscardPreviewItem], F("One item per song.")]
    space: NotRequired[Annotated[list[UpgradePreviewSpace], F("What the new files need per drive (not for Discard).")]]
    rekordbox: NotRequired[Annotated[UpgradePreviewRekordbox, F("rekordbox's state (not for Discard).")]]


@shape
class UndoPreviewItem(TypedDict):
    """One song of an undo preview."""
    key: Annotated[str, F("The song's key.", shown=False)]
    action: Annotated[Literal["undo"], F("Always undo.")]
    state: Annotated[Literal["planned", "skipped"], F("Whether it would run.")]
    reason: Annotated[str | None, F("Why it can't be undone.")]
    message: Annotated[str | None, F("The reason's words.")]
    file: Annotated[str | None, F("The song's file, an absolute path.")]
    step: Annotated[str | None, F("The kind of file step an undo would put back (swap, add_new, convert, rename).")]


@shape
class UndoPreviewRekordbox(TypedDict):
    """rekordbox's state for an undo preview."""
    running: Annotated[bool, F("Whether rekordbox is open.")]
    needs_rekordbox_closed: Annotated[bool, F("A step that wrote rekordbox can only be undone with rekordbox quit.")]


@shape
class UndoUpgradePreviewAnswer(TypedDict):
    """What `undo_upgrade` of these songs would do, before it runs. Whether the files changed since is only known when
    the undo runs."""
    total: Annotated[int, F("How many songs.")]
    planned: Annotated[int, F("How many would be undone.")]
    skipped: Annotated[int, F("How many would not.")]
    items: Annotated[list[UndoPreviewItem], F("One item per song.")]
    rekordbox: Annotated[UndoPreviewRekordbox, F("rekordbox's state.")]


@shape
class AutoUpgradeResult(TypedDict):
    """One track of the sync's Auto-upgrade phase (`auto_upgrade.py`)."""
    track: Annotated[str, F("The song's key.", shown=False)]
    name: Annotated[str, F("The song's name.")]
    state: Annotated[Literal["done", "would", "waiting", "refused", "failed"],
                     F("What became of it; `would` only in a dry run.")]
    reason: Annotated[str | None, F("A waiting row's `rekordbox_open`, `busy` or `not_reached`, a refused row's "
                                    "`EligibleReason` key.")]
    message: Annotated[str | None, F("The words.")]
    how: Annotated[Literal["in_place", "new_aiff", "placed"] | None,
                   F("The way Same track goes, or `placed` for a placement (Download again put the parked better "
                     "version in for a song whose file is missing).")]
    action: NotRequired[Annotated[Literal["same_track", "place"], F("What the row does; absent in a report from before "
                                                                    "issue 43 (read it as `same_track`).")]]


@shape
class AutoUpgradeBlock(TypedDict):
    """A run's Auto-upgrade block (the report's `.json` key `auto_upgrade`). Placements are rows like the others and
    count in `done` / `waiting` / `refused`. With the switch off the block is there only when a placement is coming or
    was done."""
    batch: Annotated[int | None, F("The batch's id, null when no batch ran.", shown=False)]
    backup: Annotated[str | None, F("The copy of rekordbox's library made for it, or null.")]
    done: Annotated[int, F("How many were done.")]
    waiting: Annotated[int, F("How many wait (rekordbox open + busy + not reached).")]
    refused: Annotated[int, F("How many the phase refuses and To-do shows.")]
    failed: Annotated[int, F("How many failed.")]
    stopped: Annotated[bool, F("The run was stopped.")]
    dry_run: Annotated[bool, F("Nothing was written: this is the plan.")]
    results: Annotated[list[AutoUpgradeResult], F("One row per track.")]


@shape
class AutoUpgradePreviewAnswer(TypedDict):
    """What the sync's last phase would do now (`sync run --auto-upgrade-only --dry-run`)."""
    auto_upgrade: Annotated[AutoUpgradeBlock | None, F("The phase's block, null when Settings' switch is off and no "
                                                       "placement is coming.")]
    start_note: Annotated[str | None, F("The Sync page's before-start line for it; null when nothing is coming.")]


@shape
class RekordboxPreviewState(TypedDict):
    """What rekordbox's library is like for a preview."""
    state: Annotated[Literal["ready", "none", "unreadable"], F("The library's state.")]
    running: Annotated[bool, F("Whether rekordbox is open.")]
    problem: Annotated[Literal["unclean", "busy", "key", "db_version", "schema"] | None,
                       F("What is wrong with the library, or null.")]
    state_text: Annotated[str, F("`state` in words.")]
    problem_text: Annotated[str | None, F("`problem` in words.")]
    writing: NotRequired[Annotated[bool, F("True while a writer of any Discjockey process holds the lock: master.db "
                                           "was not opened and the timing is `unreadable`.")]]
    writing_text: NotRequired[Annotated[str, F("`writing` in words.")]]


@shape
class RekordboxPreviewTiming(TypedDict):
    """How the timing of the file against rekordbox came out."""
    result: Annotated[str, F("The outcome: no_rekordbox, not_in_rekordbox, format, no_cues, measured, not_analysed, "
                             "timing, unreadable or missing_file.")]
    offset_samples: Annotated[int | None, F("The measured offset in samples, null when not measured.", shown=False)]
    result_text: Annotated[str, F("`result` in words.")]


@shape
class RekordboxContentFile(TypedDict):
    """An analysis file rekordbox keeps for a track."""
    path: Annotated[str, F("Its path relative to rekordbox's share folder.", shown=False)]
    hash: Annotated[str | None, F("The hash rekordbox noted when it was made.", shown=False)]
    size: Annotated[int | None, F("The size rekordbox noted.", shown=False)]
    updated_at: Annotated[str | None, F("When its row was last changed.", shown=False)]


@shape
class RekordboxPreviewEntry(TypedDict):
    """One rekordbox track that holds the file."""
    id: Annotated[str, F("The rekordbox track's id.", shown=False)]
    cues: Annotated[int, F("How many cues the analysis holds.")]
    grid: Annotated[bool, F("The analysis holds a beat grid.")]
    pwv3: Annotated[bool, F("The analysis holds a waveform to measure.")]
    offset_ms: Annotated[float | None, F("The measured offset in milliseconds.", shown=False)]
    expected_ms: Annotated[float | None, F("The expected value it snapped to, in milliseconds.", shown=False)]
    score: Annotated[float | None, F("How well the match scored.", shown=False)]
    cloud: Annotated[bool, F("The track is in rekordbox's Cloud Library Sync.")]
    fields_kept: Annotated[list[str], F("The text fields that would stay as the user edited them.")]
    folder_path: Annotated[str, F("The path rekordbox has for the file.", shown=False)]
    content_file: Annotated[list[RekordboxContentFile], F("The analysis files rekordbox keeps for it.")]
    updated_at: Annotated[str | None, F("When the track row was last changed.", shown=False)]


@shape
class RekordboxPreviewEligible(TypedDict):
    """What each action would do for the file: the reason key (null when it can run) and its words."""
    same_track: Annotated[str | None, F("Why Same track can't run (an `EligibleReason` key), null when it can; "
                                        "`not_in_library` for a file the library does not know.")]
    same_track_text: Annotated[str, F("`same_track` in words (\"possible\" when it can run).")]
    convert: Annotated[str | None, F("The same for Convert to AIFF.")]
    convert_text: Annotated[str, F("`convert` in words.")]
    rename: Annotated[str | None, F("The same for Give it its clean name.")]
    rename_text: Annotated[str, F("`rename` in words.")]


@shape
class RekordboxPreviewAnswer(TypedDict):
    """What Same track, Convert and Rename would do for one file, and what rekordbox holds for it (read only: it
    decodes the file). The engine's own `ok` is part of it (it answers `ok` once: this is the same key)."""
    ok: Annotated[Literal[True], F("Always true.", shown=False)]
    track: Annotated[str | None, F("The song's key, null for a file the library does not know.", shown=False)]
    file: Annotated[str, F("The file's absolute path.")]
    codec: Annotated[str, F("The file's codec.")]
    sample_rate: Annotated[int | None, F("The sample rate in Hz.")]
    bits: Annotated[int | None, F("The bit depth.")]
    new_file: Annotated[str | None, F("The file the first action that can run would make, an absolute path; null when "
                                      "none can.")]
    superseded: Annotated[str | None, F("Where the old file would go, an absolute path; null when none.")]
    rekordbox: Annotated[RekordboxPreviewState, F("rekordbox's library.")]
    timing: Annotated[RekordboxPreviewTiming, F("How the file's timing against rekordbox came out.")]
    entries: Annotated[list[RekordboxPreviewEntry], F("The rekordbox tracks that hold the file.")]
    eligible: Annotated[RekordboxPreviewEligible, F("What each action would do.")]


ANSWERS: dict[str, str] = {
    "todo": "Todo", "track": "TrackAnswer", "missing_files_preview": "MissingPreview",
    "find_tracks": "FindTracksAnswer", "rekordbox_preview": "RekordboxPreviewAnswer",
    "upgrade_preview": "UpgradePreviewAnswer", "undo_upgrade_preview": "UndoUpgradePreviewAnswer",
    "auto_upgrade_preview": "AutoUpgradePreviewAnswer", "select_listing": "SelectListingAnswer",
    "hide": "OpResult", "add_bought_file": "OpResult", "use_candidate": "OpResult", "use_link": "OpResult",
    "reject_current": "OpResult", "rekordbox_checked": "CheckedResult", "never_download": "NeverDownloadResult",
    "missing_files": "MissingResult", "upgrade": "AiffBatchResult", "upgrade_all": "AiffBatchResult",
    "undo_upgrade": "UndoResult",
}
RESULTS: dict[str, str] = {
    "hide": "OpResult", "unhide": "OpResult", "add_bought_file": "OpResult", "use_candidate": "OpResult",
    "use_link": "OpResult", "reject_current": "OpResult", "rekordbox_checked": "CheckedResult",
    "never_download": "NeverDownloadResult", "missing_files": "MissingResult", "upgrade_batch": "AiffBatchResult",
    "upgrade_add_new": "AiffBatchResult", "upgrade_discard": "AiffBatchResult", "undo_upgrade": "UndoResult",
}
