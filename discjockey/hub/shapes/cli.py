"""The shapes of the command line's own reads and jobs (issue 39, phase 2, E7e): `settings show`, the rekordbox
backups and their restore, the batch list and one batch, the history, an AIFF batch's undo preview, the stored audio facts and the
sync's Auto-upgrade phase alone. Most are methods of `CliApi` the window does not call (`@cli_first`), so no window file
uses them; the exception is `Opened`, the answer of the six openers the window calls too. The meanings are those of
`docs/hub-bridge-contract.md` and of the commands' own help.

`resolve` and `result_words` have no shape: they are the command line's lookups, no command prints them as `data`.

`ANSWERS` maps a method to the shape of its answer without `ok` (a J method: the shape of its job's result); `RESULTS`
maps a job kind to the shape of its `JobFinished.result`. `CLI_DATA` maps a method (`"<method>"`), or the method a
command's `--dry-run` runs (`"<method>:dry_run"`), to the shape of the `data` the command line prints where that is the
answer plus what the command line adds (a dry run's `plan_id`, a batch's `batch_id`, the counts of `check done`); a
method not in it prints its `ANSWERS` shape. `help --json` gives `data_schema` and `dry_run_schema` from it."""
from typing import Annotated, Literal, NotRequired, TypedDict

from .common import FailNext, FailPersonStep
from .kernel import F, alias, shape
from .library import Browser, Dashboard, SyncResult
from .setup import AiffPlanAnswer, LastCheck
from .todo import (AiffBatchResult, AutoUpgradeBlock, AutoUpgradePreviewAnswer, CheckedResult, ItemResult,
                   RekordboxPreviewAnswer, UndoUpgradePreviewAnswer, UpgradePreviewAnswer)


# --- settings show ---

@shape
class ExtraDay(TypedDict):
    """A one-time extra for one day (settings.json `extra_today`)."""
    date: Annotated[str, F("The day, an ISO date.")]
    amount: Annotated[int, F("How many extra downloads that day.")]


@shape
class SettingsAccount(TypedDict):
    """A YouTube or SoundCloud login that is set up."""
    browser: Annotated[Browser, F("The browser the login is read from.", shown=False)]
    browser_name: Annotated[str, F("The browser's name.")]
    profile: Annotated[str | None, F("The browser profile's folder; null: the default one.", shown=False)]
    profile_name: Annotated[str | None, F("The profile's display name; null for the default profile.")]
    daily_limit: Annotated[int, F("How many downloads a day the account may make.")]
    extra: Annotated[ExtraDay | None, F("The one-time extra, null when none is set.")]
    last_check: Annotated[LastCheck | None, F("The last login check; null when never checked since it was saved.")]
    liked_only: Annotated[bool, F("A free YouTube login: used only for Liked music.")]


@shape
class SettingsLabels(TypedDict):
    """The page's names of the two switches."""
    auto_upgrade: Annotated[str, F("The Auto-upgrade switch's name.")]
    read_liked_music: Annotated[str, F("The Liked music switch's name.")]


@shape
class SettingsView(TypedDict):
    """`settings show`: what Settings holds, in the window's words where it has them. It needs no music folder (the
    settings file is the support folder's). A file that cannot be read is `config_invalid`."""
    music_folder: Annotated[str | None, F("The chosen music folder; null when none is chosen yet.")]
    auto_upgrade: Annotated[bool, F("\"Upgrade automatically when I sync\".")]
    read_liked_music: Annotated[bool, F("The Liked music switch as the page shows it (on only with a YouTube login).")]
    daily_qobuz_limit: Annotated[int, F("How many downloads a day Qobuz may make.")]
    qobuz_skipped: Annotated[bool, F("\"I don't have Qobuz\" was chosen.")]
    spotify_skipped: Annotated[bool, F("\"I don't use Spotify\" was chosen.")]
    import_skipped: Annotated[bool, F("Skip was pressed on \"Your existing music\".")]
    qobuz_last_check: Annotated[LastCheck | None, F("The last Qobuz login check, null when none.")]
    extra: Annotated[ExtraDay | None, F("Qobuz's one-time extra, null when none is set.")]
    warnings_seen: Annotated[dict[str, str], F("Per service, the time its warning signs were last seen (\"Got it\"), "
                                               "an ISO time.")]
    accounts: Annotated[dict[str, SettingsAccount], F("The YouTube and SoundCloud logins that are set up, by service; "
                                                      "a service without one is absent.")]
    labels: Annotated[SettingsLabels, F("The page's names of the two switches.")]


# --- rekordbox backups and the restore ---

@shape
class RekordboxBackup(TypedDict):
    """One copy of rekordbox's library Discjockey made."""
    id: Annotated[str, F("The name `rekordbox restore` takes.")]
    created: Annotated[str, F("When it was made, an ISO time; empty when the copy does not say.")]
    batches: Annotated[list[int], F("The AIFF batches (ids) that wrote under it.")]
    tracks: Annotated[int, F("How many tracks' analysis files it holds.")]
    size: Annotated[int, F("Its size in bytes.")]


@shape
class RekordboxBackups(TypedDict):
    """The copies of rekordbox's library Discjockey made, newest first (each batch that wrote rekordbox keeps one; a
    restore saves the library it replaced as one). Reads only the backups' own folders: rekordbox's library is never
    opened."""
    backups: Annotated[list[RekordboxBackup], F("The copies, newest first.")]


@shape
class RestoredTrack(TypedDict):
    """A track that would point (or now points) at a file that is not there."""
    id: Annotated[str, F("The track's id in rekordbox's library.", shown=False)]
    path: Annotated[str, F("What the track points at after the restore.")]
    was: Annotated[str, F("What it pointed at before.")]


@shape
class RestorePreviewRekordbox(TypedDict):
    """rekordbox's state for a restore preview."""
    running: Annotated[bool, F("Whether rekordbox is open.")]
    needs_rekordbox_closed: Annotated[bool, F("A restore only runs with rekordbox quit.")]
    writing: NotRequired[Annotated[bool, F("Another Discjockey process is writing rekordbox's library: it was not "
                                           "opened, `missing_after` is null.")]]
    unreadable: NotRequired[Annotated[bool, F("The current library can't be read (it is what a restore can repair): "
                                              "`missing_after` is null.")]]


@shape
class RestorePreview(TypedDict):
    """What `rekordbox restore` of a backup would leave behind, before it runs. Nothing is saved or changed."""
    backup: Annotated[str, F("The backup asked for.")]
    missing_after: Annotated[list[RestoredTrack] | None, F(
        "The tracks that would point at a file that is not there; null when that is not known (see `rekordbox`).")]
    rekordbox: Annotated[RestorePreviewRekordbox, F("rekordbox's state.")]


@shape
class RestoreResult(TypedDict):
    """The result of `rekordbox_restore`: rekordbox's whole library is back as the backup holds it."""
    restored: Annotated[str, F("The backup put back.")]
    saved_current: Annotated[str, F("The id of the backup that holds the library the restore replaced.")]
    missing_after: Annotated[list[RestoredTrack], F("The tracks that now point at a file that is not there "
                                                    "(Discjockey moved it to `Superseded/` since).")]
    recovered: Annotated[list[tuple[str, bool]], F("What a recovery of an earlier crash put right, `[what, ok]` per "
                                                   "line.")]


# --- batches ---

@shape
class BatchRow(TypedDict):
    """One batch Discjockey made, an AIFF batch (Same track, Convert, Rename) or a move batch (a tidy-up, a save, a
    folder rename, an undo); `batches` lists them in one list, newest first."""
    id: Annotated[str, F("The typed id every other command takes: `aiff:12` or `moves:12`.")]
    kind: Annotated[Literal["aiff", "moves"], F("Which kind of batch.")]
    batch: Annotated[int, F("The id inside its kind.", shown=False)]
    what: Annotated[str, F("An AIFF batch's `upgrade`, `convert` or `mixed`; a move batch's title.")]
    started_by: Annotated[str, F("Who started it (an AIFF batch: `user`, `upgrade_all`, `make_aiff`, `cdj_all`, "
                                 "`auto_upgrade`, `download_again`; a move batch: `tidy`, `save`, `rename`, `undo`).")]
    state: Annotated[Literal["running", "stopped", "done"], F("How far it got.")]
    stop_reason: Annotated[Literal["stop", "rekordbox_open", "busy", "crash"] | None,
                           F("Why it stopped; null when it did not (always null for a move batch).")]
    started: Annotated[str, F("When it started, an ISO time.")]
    ended: Annotated[str | None, F("When it ended; null while it runs or never did.")]
    total: Annotated[int, F("How many items it holds.")]
    done: Annotated[int, F("Items done (for a move batch: the files moved).")]
    skipped: Annotated[int, F("Items skipped.")]
    failed: Annotated[int, F("Items that failed (always 0 for a move batch).")]
    planned: Annotated[int, F("Items still planned.")]
    undone: Annotated[int, F("Items undone (always 0 for a move batch: an undo is a batch of its own).")]
    backup: Annotated[str | None, F("The rekordbox backup an AIFF batch made; null for a move batch.")]
    undone_by: Annotated[str | None, F("For a move batch the typed id of the batch that undid it; null otherwise.")]
    via: Annotated[Literal["window", "terminal"], F("Where it started.")]
    scope: Annotated[str | None, F("What was picked for an AIFF batch (`selection`, `library:<view>[:<key>]`, "
                                   "`todo:cdj`, ...); null for a move batch.")]


@shape
class Batches(TypedDict):
    """The batches Discjockey made, newest first."""
    batches: Annotated[list[BatchRow], F("The batches, newest first.")]
    total: Annotated[int, F("How many batches there are of the kind and from the time asked for: as many as the list "
                            "holds, and the `page`'s total.")]


# --- history ---

@shape
class HistoryEntry(TypedDict):
    """One thing that changed: a run of the sync, a batch (AIFF or moves) or a single step Discjockey logged. Exactly
    one of `undo` and `cant_text` is set."""
    kind: Annotated[Literal["run", "batch", "operation"], F("A run, a batch or a single logged step.", shown=False)]
    id: Annotated[str | None, F("The id the commands take: `report:<stamp>`, `aiff:12` or `moves:12`; null for a single "
                                "step.")]
    at: Annotated[str, F("When it happened, an ISO time: a run's or batch's start, a step's time.")]
    text: Annotated[str, F("What happened, in words.")]
    undo: Annotated[str | None, F("The command that undoes it (run its `--dry-run` first); null when nothing does or the "
                                  "command is not there yet.")]
    cant_text: Annotated[str | None, F("Why `undo` is null, in words; null when there is an `undo`.")]
    track_id: Annotated[str | None, F("The song a single step was done to; null for a run or a batch.", shown=False)]
    artist: Annotated[str | None, F("The song's artist, for a single step.")]
    title: Annotated[str | None, F("The song's title, for a single step.")]


@shape
class History(TypedDict):
    """What changed and what can be undone: runs, batches and single steps, newest first."""
    entries: Annotated[list[HistoryEntry], F("The entries, newest first.")]
    since: Annotated[str | None, F("The time the list starts at, an ISO time; null when it was not limited.")]


# --- rekordbox match, library superseded ---

@shape
class MatchRekordbox(TypedDict):
    """What state rekordbox's library was in for the read, in words. `unreadable` answers "was it read just now"; it is
    not the library's health: `rekordbox status` says that (`ready` with `problem: busy` is a healthy library that was
    busy)."""
    state: Annotated[Literal["ready", "none", "unreadable"], F("`ready`: it was read; `none`: no rekordbox library on "
                                                               "this Mac; `unreadable`: it could not be read now (a "
                                                               "writer holds it, or its problem).")]
    state_text: Annotated[str, F("The state in words.")]
    writing: Annotated[bool, F("Discjockey is changing rekordbox's library in another window or the Terminal, so it "
                               "was not opened.")]


@shape
class MatchRow(TypedDict):
    """One thing that does not match: a rekordbox track, or a file of your library rekordbox lacks."""
    kind: Annotated[Literal["missing", "superseded", "away", "not_in_library", "not_in_rekordbox"],
                    F("What does not match.", shown=False)]
    kind_text: Annotated[str, F("What does not match, in words.")]
    path: Annotated[str, F("The file's absolute path, as rekordbox holds it (for a file rekordbox lacks: where it is).")]
    rel_path: Annotated[str | None, F("The path relative to the music folder; null for a file outside it.")]
    track_id: Annotated[str | None, F("The library song whose current file it is; null when none.", shown=False)]
    rekordbox_id: Annotated[str | None, F("The rekordbox track's id; null for a file rekordbox lacks.", shown=False)]
    artist: Annotated[str | None, F("The artist: rekordbox's for its track, the library's for a file it lacks.")]
    title: Annotated[str | None, F("The title: rekordbox's for its track, the library's for a file it lacks.")]


@shape
class MatchCounts(TypedDict):
    """How many of each kind there are in the narrowed view."""
    matched: Annotated[int, F("Rekordbox tracks whose file is a song's current file.")]
    missing: Annotated[int, F("Rekordbox tracks whose file is not there.")]
    superseded: Annotated[int, F("Rekordbox tracks that point at a file in Superseded/.")]
    away: Annotated[int, F("Rekordbox tracks on a watched drive that is not connected now.")]
    not_in_library: Annotated[int, F("Rekordbox tracks whose file is in your music folder or a watched folder but is "
                                     "no song's file.")]
    not_in_rekordbox: Annotated[int, F("Files of your library that no rekordbox track holds.")]
    outside: Annotated[int, F("Rekordbox tracks whose file is there but elsewhere: your own files, never a problem.")]


@shape
class RekordboxMatch(TypedDict):
    """`rekordbox match`: what in rekordbox does not match your files, and which of your files rekordbox lacks."""
    entries: Annotated[list[MatchRow], F("The findings, missing first, then Superseded/, away, not in the library and "
                                         "not in rekordbox; each kind by path. Empty when rekordbox was not read.")]
    counts: Annotated[MatchCounts, F("How many of each kind (all 0 when rekordbox was not read).")]
    rekordbox: Annotated[MatchRekordbox, F("rekordbox's state for this read.")]
    text: Annotated[str, F("The answer in one sentence.")]


@shape
class SupersededFile(TypedDict):
    """One file in `Superseded/`."""
    path: Annotated[str, F("The file's absolute path.")]
    rel_path: Annotated[str, F("The path relative to the music folder.")]
    size: Annotated[int, F("The size in bytes.", shown=False)]
    size_text: Annotated[str, F("The size in words.")]
    rekordbox: Annotated[int, F("How many rekordbox tracks hold this file; 0 when rekordbox could not be read.")]


@shape
class Superseded(TypedDict):
    """`library superseded`: the files of `Superseded/`, their size and which of them rekordbox still points at."""
    files: Annotated[list[SupersededFile], F("The files, by path.")]
    total: Annotated[int, F("How many files.")]
    size: Annotated[int, F("Their size together, in bytes.", shown=False)]
    size_text: Annotated[str, F("Their size together, in words.")]
    held: Annotated[int, F("How many files rekordbox still points at.")]
    rekordbox: Annotated[MatchRekordbox, F("rekordbox's state for this read.")]
    text: Annotated[str, F("The answer in one sentence.")]
    note: Annotated[str, F("Discjockey never deletes music: the files can be deleted in the Finder.")]
    next: NotRequired[Annotated[list[FailNext], F("When there are files: how to show them in the Finder, and, when "
                                                  "rekordbox still uses some, which tracks.")]]


# --- doctor ---

DoctorCheckKey = alias(
    "DoctorCheckKey",
    Literal["music_folder", "tools", "logins", "folder_access", "rekordbox", "stale_lock", "lost_jobs", "records",
            "pending_steps", "drives_away", "downloads_paused", "out_of_place", "superseded", "rekordbox_files", "stopped_batches",
            "open_checks", "cdj", "songs_without_file", "upgrades_waiting"],
    doc="One check of `doctor` (`discjockey/hub/doctor.py`, `CHECKS`).")


@shape
class DoctorProblem(TypedDict):
    """One thing `doctor` found, with what to do about it."""
    check: Annotated[DoctorCheckKey, F("The check that found it.", shown=False)]
    level: Annotated[Literal["problem", "note"], F("`problem`: something to fix. `note`: worth knowing, nothing to fix.")]
    gig: Annotated[bool, F("Whether the next gig depends on it (`status --ready` lists these).", shown=False)]
    text: Annotated[str, F("What is wrong, in words.")]
    count: Annotated[int | None, F("The number the text counts (jobs, folders, files, tracks); null when it counts nothing.")]
    next: Annotated[list[FailNext], F("Commands that look further or move on.")]
    person_steps: Annotated[list[FailPersonStep], F("The steps only a person can do.")]


@shape
class DoctorCheck(TypedDict):
    """One line of `doctor`'s checks."""
    check: Annotated[DoctorCheckKey, F("The check.", shown=False)]
    label: Annotated[str, F("What the check looks at, in words.")]
    state: Annotated[Literal["ok", "problem", "note", "skipped"],
                     F("`ok`: nothing found. `problem` / `note`: it found something of that level (a problem wins). "
                       "`skipped`: it was not run: it needs a music folder and none is chosen, or it reads the library's "
                       "records and those cannot be read (the `records` check says so).")]


@shape
class Doctor(TypedDict):
    """`doctor`: everything that is wrong, each problem with what to do next, and every check that ran."""
    text: Annotated[str, F("The answer in one sentence: how many problems and notes, or that nothing is wrong.")]
    problems: Annotated[list[DoctorProblem], F("What was found: problems first, then notes, each in check order.")]
    checks: Annotated[list[DoctorCheck], F("Every check, in order, with its state.")]


# --- status ---

@shape
class StatusNav(TypedDict):
    """The numbers the window's navigation shows."""
    todo: Annotated[int, F("The to-do badge: what needs you.")]
    all_tracks: Annotated[int, F("All tracks.")]
    not_in_playlist: Annotated[int, F("Songs in no playlist.")]
    limits_warning: Annotated[bool, F("A set-up service has a warning sign you have not marked as seen, or is paused "
                                      "today: the dot on Download limits.")]


@shape
class StatusJob(TypedDict):
    """A job of this music folder that has not ended."""
    id: Annotated[str, F("The job's id (`job:…`), what `job show` and `job wait` take.")]
    command: Annotated[str, F("The command that started it.")]
    via: Annotated[Literal["window", "terminal"], F("Where it was started.")]
    status: Annotated[Literal["queued", "running", "stopping"], F("Where it is.")]
    line: Annotated[str | None, F("Its progress in one line; null before it has any.")]
    started: Annotated[str, F("When it started, an ISO time.")]


@shape
class StatusData(TypedDict):
    """What `status` prints as `data`: what the window's Dashboard and navigation show, the jobs that run now and,
    with `--ready`, the problems a gig depends on."""
    dashboard: Annotated[Dashboard, F("What the window's Dashboard shows.")]
    nav: Annotated[StatusNav, F("The numbers of the window's navigation.")]
    jobs: Annotated[list[StatusJob], F("The jobs of this music folder that have not ended, newest first.")]
    ready: Annotated[list[DoctorProblem] | None, F("With `--ready`: the problems of `doctor` that a gig depends on, "
                                                   "none when the library is ready; null without it.")]
    ready_text: NotRequired[Annotated[str, F("With `--ready`: whether the library is ready for a gig, or how many "
                                             "things to look at first, in one sentence; left out without it.")]]


@shape
class StatusView(StatusData):
    """`status`: the answer of the engine. The command line moves `person_steps` out of `data` into the envelope."""
    person_steps: NotRequired[Annotated[list[FailPersonStep], F("The steps only a person can do for the running jobs "
                                                               "(\"Your turn\" lines); left out when none.")]]


@shape
class BatchItem(ItemResult):
    """One track of an AIFF batch, with its name."""
    name: Annotated[str, F("The song as `Artist - Title`; its key when it is not in the library any more.")]


@shape
class BatchMove(TypedDict):
    """One move of a move batch as the records keep it."""
    seq: Annotated[int, F("Its place in the batch; an undo goes in reverse.", shown=False)]
    kind: Annotated[Literal["file", "folder"], F("A file or a folder rename.")]
    label: Annotated[str, F("The file's or folder's name.")]
    src: Annotated[str, F("Where it was.")]
    dst: Annotated[str, F("Where it went, or would have gone.")]
    state: Annotated[Literal["planned", "done", "skipped"], F("What became of it.")]
    reason: Annotated[str | None, F("A skip's reason code.")]
    detail: Annotated[str | None, F("A skip's own detail (a failure's words).")]
    files: Annotated[int | None, F("For a folder move how many files it carried; null otherwise.")]
    text: Annotated[str | None, F("Why a move that was not made was not, in plain words; null for the others.")]


@shape
class BatchDetail(BatchRow):
    """One batch by its typed id: its row as `batches` lists it, and by kind its items or its moves."""
    results: NotRequired[Annotated[list[BatchItem], F("An AIFF batch's items, one per track.")]]
    moves: NotRequired[Annotated[list[BatchMove], F("A move batch's moves, in order.")]]


@shape
class BatchUndoPreview(UndoUpgradePreviewAnswer):
    """What `batch undo` of an AIFF batch would do, before it runs: one item per `done` song, newest first (the order
    an undo goes). Whether the files changed since is only known when the undo runs."""
    batch: Annotated[str, F("The batch, `aiff:<n>`.")]


# --- the audio facts, the Auto-upgrade phase alone ---

@shape
class FactsPreview(TypedDict):
    """The dry run of `library facts`: nothing is stored."""
    total: Annotated[int, F("How many own files lack stored facts.")]


@shape
class FactsResult(TypedDict):
    """The result of `fill_facts` (`library facts`): the audio facts read for the files that had none (codec, rate, bit
    depth, bitrate). A second run finds none."""
    total: Annotated[int, F("The files that lacked facts.")]
    filled: Annotated[int, F("The files whose facts were read.")]
    unreadable: Annotated[int, F("The files ffprobe found no sound in: marked and left out until they change.")]


@shape
class AutoUpgradeRunResult(TypedDict):
    """The result of `auto_upgrade_run` (`sync run --auto-upgrade-only`): the sync's last phase alone. A job that is
    stopped or crashed carries it too."""
    exit_code: Annotated[int, F("How it ended: 0 well, 130 stopped, 1 crashed.")]
    report: Annotated[str | None, F("The run's report id (`report:<stamp>`); null when no report was written.")]
    auto_upgrade: Annotated[AutoUpgradeBlock | None, F(
        "The phase's block; null when Settings' switch is off and no placement was coming.")]
    recovered: Annotated[list[tuple[str, bool]], F("What a recovery of an earlier crash put right, `[what, ok]` per "
                                                   "line.")]
    new_since_plan: NotRequired[Annotated[list[str], F(
        "A run with `--plan`: the songs that are new since the plan, left out.", shown=False)]]


# --- what the command line adds to `data` ---

@shape
class AiffPlanDryRun(AiffPlanAnswer):
    """`aiff convert --dry-run` and `aiff rename --dry-run`: the plan, and the id `--plan` runs it by."""
    plan_id: NotRequired[Annotated[str, F("The id the plan is stored under; `--plan <id>` runs it. Missing when the "
                                          "plan lists nothing to run.")]]


@shape
class UpgradePreviewDryRun(UpgradePreviewAnswer):
    """`upgrade apply --dry-run`: what it would do, and the id `--plan` runs it by."""
    plan_id: NotRequired[Annotated[str, F("The id the plan is stored under; `--plan <id>` runs it. Missing for "
                                          "`upgrade discard`, which runs on what is there.")]]


@shape
class AutoUpgradePreviewDryRun(AutoUpgradePreviewAnswer):
    """`sync run --auto-upgrade-only --dry-run`: what the phase would do, and the id `--plan` runs it by."""
    plan_id: NotRequired[Annotated[str, F("The id the plan is stored under; `--plan <id>` runs it. Missing when the "
                                          "phase has nothing to run.")]]


@shape
class UpgradeRunRow(ItemResult):
    """One song of a batch as the command line prints it: with the steps only a person can do for it."""
    person_steps: Annotated[list[FailPersonStep], F("The steps only a person can do in rekordbox for this song; empty "
                                                    "when there are none.")]


@shape
class UpgradeRunData(AiffBatchResult):
    """The `data` of `upgrade apply`, `upgrade all`, `batch resume` and the AIFF commands: the batch's result with
    each row's steps for the person, and the batch's name."""
    results: Annotated[list[UpgradeRunRow], F("One row per track.")]
    batch_id: NotRequired[Annotated[str, F("The batch, `aiff:<n>`; missing when no batch was made (a New track or "
                                           "Discard list).")]]


@shape
class SyncFailed(TypedDict):
    """One song `sync run` could not finish (the report's Errors section)."""
    track_id: Annotated[str | None, F("The song's key; null for an error that is no song's.", shown=False)]
    artist: Annotated[str, F("The artist, empty for an error that is no song's.")]
    title: Annotated[str, F("The title, empty for an error that is no song's.")]
    text: Annotated[str, F("What went wrong, in the report's words.")]


@shape
class SyncRunData(SyncResult):
    """The `data` of `sync run`: the result with what the report counted and which songs failed."""
    counts: Annotated[dict[str, int], F("Each report section with at least one result (its key, as `report show` says "
                                        "them): how many.")]
    failed: Annotated[list[SyncFailed], F("The songs that failed, empty when none did.")]


@shape
class CheckDoneRow(TypedDict):
    """One track of `check done`."""
    track: Annotated[str, F("The song's key.", shown=False)]
    action: Annotated[Literal["check"], F("Always `check`.")]
    state: Annotated[Literal["done", "skipped"], F("`done`: its check is cleared; `skipped`: it had nothing to check, "
                                                   "or a later change took its check.")]
    reason: Annotated[Literal["nothing_to_check", "newer_batch"] | None, F("Why it was skipped, null when done.")]
    message: Annotated[str | None, F("The words, where there are some.")]


@shape
class CheckDoneData(CheckedResult):
    """The `data` of `check done`: the result with one row per track named, and how many tracks it counted."""
    results: Annotated[list[CheckDoneRow], F("One row per track, `done` or `skipped`.")]
    total: NotRequired[Annotated[int, F("How many tracks the command looked at.")]]
    done: NotRequired[Annotated[int, F("How many were checked.")]]
    skipped: NotRequired[Annotated[int, F("How many had nothing to check, or belong to a later change.")]]
    failed: NotRequired[Annotated[int, F("How many failed (always 0).")]]


@shape
class AutoUpgradeRunData(AutoUpgradeRunResult):
    """The `data` of `sync run --auto-upgrade-only`: the phase's result and the batch it made."""
    batch_id: NotRequired[Annotated[str, F("The phase's batch, `aiff:<n>`; missing when it made none.")]]


@shape
class RekordboxPreviewData(RekordboxPreviewAnswer):
    """The `data` of `rekordbox preview`: the answer without the `ok` the window's answer carries (`data` never has it)."""
    ok: NotRequired[Annotated[Literal[True], F("Not in the command line's `data`.", shown=False)]]


# --- open ... ---

@shape
class Opened(TypedDict):
    """What `open file|folder|url|report|licences|privacy-settings` answer: the place or web address, and whether it was
    opened (`--print` only says it)."""
    target: Annotated[str, F("The absolute path or the web address.")]
    opened: Annotated[bool, F("It was opened (false with `--print`).")]
    text: Annotated[str, F("What was done, in words: \"Opened <target>.\", or with `--print` that it would open it and "
                           "opened nothing.")]


ANSWERS: dict[str, str] = {
    "settings_view": "SettingsView", "rekordbox_backups": "RekordboxBackups",
    "rekordbox_restore_preview": "RestorePreview", "batches": "Batches", "batch_detail": "BatchDetail",
    "history": "History", "doctor": "Doctor", "status_view": "StatusView", "rekordbox_match": "RekordboxMatch",
    "library_superseded": "Superseded",
    "batch_undo_preview": "BatchUndoPreview", "facts_preview": "FactsPreview",
    "show_in_finder": "Opened", "reveal": "Opened", "open_report": "Opened", "open_licenses": "Opened",
    "open_external": "Opened", "open_privacy_settings": "Opened",
    # J methods: the shape of the job's result
    "rekordbox_restore": "RestoreResult", "fill_facts": "FactsResult", "auto_upgrade_run": "AutoUpgradeRunResult",
}
RESULTS: dict[str, str] = {
    "rekordbox_restore": "RestoreResult", "facts": "FactsResult", "auto_upgrade": "AutoUpgradeRunResult",
}
CLI_DATA: dict[str, str] = {
    "aiff_plan:dry_run": "AiffPlanDryRun", "upgrade_preview:dry_run": "UpgradePreviewDryRun",
    "auto_upgrade_preview:dry_run": "AutoUpgradePreviewDryRun",
    "upgrade": "UpgradeRunData", "upgrade_all": "UpgradeRunData", "batch_resume": "UpgradeRunData",
    "convert": "UpgradeRunData", "rename": "UpgradeRunData", "make_aiff": "UpgradeRunData",
    "rekordbox_checked": "CheckDoneData", "auto_upgrade_run": "AutoUpgradeRunData", "start_sync": "SyncRunData",
    "rekordbox_preview": "RekordboxPreviewData", "status_view": "StatusData",
}
