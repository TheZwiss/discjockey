"""The shapes of the command line's own reads and jobs (issue 39, phase 2, E7e): `settings show`, the rekordbox
backups and their restore, the batch list and one batch, an AIFF batch's undo preview, the stored audio facts and the
sync's Auto-upgrade phase alone, and the six bridge methods that answer `{}` and belong to no area. They are methods of
`CliApi` the window does not call (`@cli_first`), so no window file uses these shapes. The meanings are those of
`docs/hub-bridge-contract.md` and of the commands' own help.

`resolve` and `result_words` have no shape: they are the command line's lookups, no command prints them as `data`.

`ANSWERS` maps a method to the shape of its answer without `ok` (a J method: the shape of its job's result); `RESULTS`
maps a job kind to the shape of its `JobFinished.result`. `CLI_DATA` maps a method (`"<method>"`), or the method a
command's `--dry-run` runs (`"<method>:dry_run"`), to the shape of the `data` the command line prints where that is the
answer plus what the command line adds (a dry run's `plan_id`, a batch's `batch_id`, the counts of `check done`); a
method not in it prints its `ANSWERS` shape. `help --json` gives `data_schema` and `dry_run_schema` from it."""
from typing import Annotated, Literal, NotRequired, TypedDict

from .common import FailPersonStep
from .kernel import F, shape
from .library import Browser
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
    batches: Annotated[list[BatchRow], F("The newest batches (`--limit`).")]
    total: Annotated[int, F("How many batches there are of the kinds asked for.")]


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


ANSWERS: dict[str, str] = {
    "settings_view": "SettingsView", "rekordbox_backups": "RekordboxBackups",
    "rekordbox_restore_preview": "RestorePreview", "batches": "Batches", "batch_detail": "BatchDetail",
    "batch_undo_preview": "BatchUndoPreview", "facts_preview": "FactsPreview",
    # the bridge reads that answer `{}` and belong to no area
    "show_in_finder": "Empty", "reveal": "Empty", "open_report": "Empty", "open_licenses": "Empty",
    "open_external": "Empty", "open_privacy_settings": "Empty",
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
    "rekordbox_checked": "CheckDoneData", "auto_upgrade_run": "AutoUpgradeRunData",
    "rekordbox_preview": "RekordboxPreviewData",
}
