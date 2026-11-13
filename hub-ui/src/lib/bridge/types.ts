// Every JSON shape of docs/hub-bridge-contract.md, field by field. Source of truth: discjockey/hub/{api,views,jobs}.py.

export type ProblemKind = 'busy' | 'console' | 'sync_running' | 'not_set_up' | 'login_expired' | 'offline'
  | 'playlist_unreadable' | 'config_invalid' | 'qobuz_login_failed' | 'login_failed' | 'changed' | 'refused'
  | 'failed' | 'stopped' | 'protected' | 'crashed' | 'no_library' | 'setting_off' | 'exists' | 'rekordbox_open';
export const PROBLEM_KINDS: readonly ProblemKind[] = ['busy', 'console', 'sync_running', 'not_set_up',
  'login_expired', 'offline', 'playlist_unreadable', 'config_invalid', 'qobuz_login_failed', 'login_failed',
  'changed', 'refused', 'failed', 'stopped', 'protected', 'crashed', 'no_library', 'setting_off', 'exists', 'rekordbox_open'];
export type Quality = 'lossless' | 'good_lossy' | 'weak' | 'fake' | 'missing';
export const QUALITIES: readonly Quality[] = ['lossless', 'good_lossy', 'weak', 'fake', 'missing'];
export type EmptyKind = 'no_playlists' | 'not_set_up' | 'empty_library' | 'no_preview' | 'up_to_date' | 'no_match'
  | 'all_lossless' | 'all_hidden' | 'nothing_here' | 'gone';
/** A playlist service (`sources.py`): the one a playlist row, a link or a problem belongs to. */
export type PlaylistService = 'spotify' | 'qobuz' | 'soundcloud' | 'youtube_music';
/** A choice in Settings that a read needs (its key in settings.json): `setting_off` names it in `setting`. */
export type SettingKey = 'read_liked_music';
/** `service`: set when a playlist service caused the problem (a `SourceError`), absent for every other. `setting`:
 *  only with kind `setting_off` (add_playlist for a link that needs a Settings choice that is off). */
export type Fail = { ok: false; kind: ProblemKind; message: string; service?: PlaylistService; setting?: SettingKey };
export type Res<T> = ({ ok: true } & T) | Fail;
export type JobStart = Res<{ job_id: number }>;
export type ActionKey = [string, string, string];          // sent back unchanged to start_sync
export type LibraryFilter = 'all' | 'lossless' | 'good_lossy' | 'weak' | 'fake' | 'upgrade_ready';
/** `order` is a playlist's own order (its read record's); the engine's default there, and `artist` elsewhere. */
export type LibrarySort = `${'' | '-'}${'title' | 'artist' | 'length' | 'source' | 'quality' | 'added' | 'folder' | 'order'}`;
// The contract adds `rekordbox_check` (the plan's list predates it) and the import's `same_song` and `duplicate`.
export type TodoFilter = 'all' | 'rekordbox_check' | 'same_song' | 'duplicate' | 'upgrade_ready' | 'cdj' | 'not_found'
  | 'weak' | 'good_lossy' | 'fake' | 'other';
export type Which = 'current' | 'upgrade';
export type PlaylistLine = { folder: string; link: string; enabled: boolean };
export const NOT_IN_PLAYLIST = '__not_in_playlist__';

export type Status = 'lossless' | 'not_lossless' | 'fake_lossless' | 'missing';
export type Source = 'qobuz' | 'youtube_music' | 'soundcloud' | 'youtube' | 'manual';
/** How a download's source was found (the engine's `source_how`): the exact Qobuz track, its ISRC, a name search, the
 *  playlist's own upload, the fallback search, or picked by the user. */
export type SourceHow = 'exact' | 'isrc' | 'name' | 'upload' | 'fallback' | 'chosen';
export type ByQuality = Record<Quality, number>;

export type TrackRow = {
  track_id: string; artist: string; title: string; folder: string; duration_s: number;
  status: Status; quality: Quality; quality_label: string; cutoff_hz: number | null;
  source: Source | null; source_name: string | null; in_playlists: boolean;
  /** a file of the user's own that the import found (no playlist holds it): the table never dims it */
  own: boolean; hidden: boolean;
  upgrade_ready: boolean; path: string | null; added: string | null; cover_url: string | null;
};
export type TodoGroupKey = Exclude<TodoFilter, 'all'>;
/** `free`: the artist gives it away (see TrackDetail.free_downloads). `pair`: only the import's two groups
 *  (`same_song`, `duplicate`) have one; narrow with `isQuestion` / `isDuplicate`. `can_undo`: only `rekordbox_check`
 *  items have it; true when the check belongs to a swap or an added file `undo_upgrade` can still put back. */
/** `file_state` (as a Library row's): whether the item's file is there now, decided per watched folder; `no_file`: the
 *  song has none (Not found). A same-song item is about the user's own file, a duplicate group is only listed while
 *  every file of it is there. */
export type TodoItem = TrackRow & { group: TodoGroupKey; detail: string; free: boolean;
  file_state: Exclude<FileState, 'file_missing'> | 'no_file';
  pair?: QuestionPair | DuplicatePair; can_undo?: boolean; check?: RekordboxCheckView;
  /** `upgrade_ready` items: why Same track can't run now (an `EligibleReason` key), null when it can */
  same_track?: string | null;
  /** `cdj` items (issue 33 stage D): what the CDJs refuse in the file, and `aiff`: why Convert can't run now (an
   *  `EligibleReason` key from the stored facts), null when it can */
  cdj?: CdjWhy; aiff?: string | null;
  /** a batch's open checks (two or more) are one item: `key` and `track_id` are `batch:<id>` (narrow with `isBatch`) */
  key?: string; batch?: BatchCheck };
/** Why the CDJ-3000 or the CDJ-2000NXS2 refuses or stutters on a file (`cdj.cdj_problem`): `reason` format | bitrate |
 *  bits | rate_high | rate_low, `short` To-do's one line, `words` the sentence for the panels. */
export type CdjWhy = { reason: 'format' | 'bitrate' | 'bits' | 'rate_high' | 'rate_low'; short: string; words: string };
/** The `cdj` of `track().aiff` and of an `AiffPlanItem`: the same words without the reason key. */
export type CdjWords = { short: string; words: string };
/** A `BatchCheckItem`'s batch: `size` open checks, `started` the earliest check's date, `tracks` them as single items. */
export type BatchCheck = { id: number; size: number; started: string | null;
  /** who started the batch (`aiff_batches.started_by`): `auto_upgrade` is the sync's Auto-upgrade phase (its item says
   *  "Upgraded during your sync" and its foot "Undo all from this sync"); null when unknown */
  started_by: 'user' | 'upgrade_all' | 'make_aiff' | 'cdj_all' | 'auto_upgrade' | (string & {}) | null;
  /** the batch's own kind (`aiff_batches.kind`): a Convert batch says "Made AIFF"; null when unknown */
  kind: 'upgrade' | 'convert' | 'mixed' | null;
  tracks: TodoItem[] };
export type BatchCheckItem = TodoItem & { group: 'rekordbox_check'; key: string; batch: BatchCheck };
export const isBatch = (i: TodoItem): i is BatchCheckItem => i.group === 'rekordbox_check' && !!i.batch;
/** A `rekordbox_check` item's check (views.check_view): the step that left it, what the two files measured as
 *  (`match`: exact/shifted/different/unknown, null in records from before it), `aligned` (an added file that
 *  Discjockey rendered lined up with rekordbox's timeline of the old one: the old track's cues fit it to the sample;
 *  false for a swap and in records from before it), `text` the whole instruction and
 *  `old_path` where the old file (added) or the copy of the old audio (swap) is now (null without an undo record).
 *  The item's `detail` is the row's short line. */
export type RekordboxCheckView = { reason: 'wrong_song' | 'added_as_new' | 'swapped' | 'repointed' | 'converted' | 'renamed' | string;
  since: string | null;
  match: string | null; offset_ms: number | null; moved: boolean; aligned: boolean; text: string; old_path: string | null;
  /** false when Discjockey wrote rekordbox's text itself (no Reload Tag step); true for older records */
  reload_tag: boolean;
  /** the AIFF batch that left the check and how many of its checks are still open (null: no batch) */
  batch: { id: number; size: number } | null;
  /** what was written in rekordbox: how many tracks, and the fields kept as the user edited them (null: nothing) */
  rekordbox: { entries: number; kept: string[] } | null;
  /** stage D: a `renamed` check's old base name ("Artist - Title [FREE DL].aiff"), null for every other check; a
   *  `converted` check's `old_path` is where the old file is now (Superseded/), a `renamed` one has none */
  old_name: string | null };

// --- the import of the user's own music (plan library stage 4, I11; contract "Watched folders and the import") ---
/** One file of a question or a duplicate group. `path` is absolute for an import folder's file; `audio_url` is null
 *  only for a file that is offline or can't be played (an import folder's file plays through `file/<file_id>`). */
export type FileSide = { file_id: number; song_key: string | null; path: string; artist: string; title: string;
  duration_s: number; quality: Quality; quality_label: string; online: boolean; audio_url: string | null;
  in_playlist: boolean };
export type QuestionWhy = 'artist' | 'no_artist' | 'length' | 'no_length';
/** "Is this the same song?": a playlist song a file of the user's own might be. `delta_s`: the file's length minus the
 *  song's in whole seconds (null with `no_length`). */
export type QuestionPair = { song_key: string; own_key: string; why: QuestionWhy; delta_s: number | null;
  track: { artist: string; title: string; duration_s: number; folder: string; link: string | null };
  file: FileSide };
export type DuplicateWhy = 'same_audio' | 'same_song';
/** A group of files that are the same audio or the same song: two or more, by file id. */
/** `recommended`: the file the panel picks to keep (views.recommend: the better sound, then AIFF), null when there is no
 *  clear winner; `recommended_why` its one line ("Recommended: best quality"). */
export type DuplicatePair = { group_id: string; why: DuplicateWhy; files: FileSide[]; recommended: number | null;
  recommended_why: string | null };
export type QuestionItem = TodoItem & { group: 'same_song'; pair: QuestionPair };
export type DuplicateItem = TodoItem & { group: 'duplicate'; pair: DuplicatePair };
export const isQuestion = (i: TodoItem): i is QuestionItem => i.group === 'same_song' && !!i.pair;
export const isDuplicate = (i: TodoItem): i is DuplicateItem => i.group === 'duplicate' && !!i.pair;

export type ImportPhase = 'scan' | 'facts' | 'tags' | 'sound' | 'link';
/** A watched folder (watched_folders()): the Library (always `online`, `scanning` while an import looks for files)
 *  or an import folder; `offline`: its drive isn't connected, `missing`: the folder isn't found (moved, renamed,
 *  deleted). `files`: the tracks the folder lists, the same number the sidebar shows for it; `waiting`: files the
 *  import still works through (not read yet, or not sound-checked: not in `files` until read). */
export type WatchedFolderRow = { id: number; path: string; name: string; kind: 'library' | 'import';
  state: 'online' | 'offline' | 'missing' | 'scanning' | 'importing'; files: number; waiting: number; unreadable: number;
  /** all the folder's crates in label order (Settings' switches); `too_many`: more than 25, so they start hidden.
   *  The Library row has none ([], false). */
  crates: Crate[]; too_many: boolean };
export type UnreadableFile = { folder_id: number | null; path: string; reason: string };
export type WatchedFolders = { folders: WatchedFolderRow[]; unreadable: UnreadableFile[];
  /** the files an import would work through now (offline drives' left out) */
  waiting: number;
  /** the user stopped an import this session: offer Continue import */
  stopped: boolean };
export type ImportFolderProblem = FolderProblem | 'not_readable' | 'not_found' | 'music' | 'holds_music' | 'watched'
  | 'already';
/** check_import_folder(path): `message` is the refusal's words; `merges` the watched folders (paths) a usable folder
 *  takes over, `merge_hints` their lines ("{name} is inside it and becomes part of it."). */
export type ImportFolderCheck = Omit<FolderCheck, 'problem' | 'kind'> & { problem: ImportFolderProblem | null;
  kind: 'import' | null; merges: string[]; merge_hints: string[] };
export type RemovalPreview = { name: string; files: number; redownload: number };
/** `import` job result (also the `result` of a stopped one, with `stopped` true). */
export type ImportResult = { files: number; own_songs: number; sound_checked: number; unreadable: number; left: number;
  stopped: boolean; link_note: string | null };

// --- tidy-up and the move log (plan library stage 2, I5; contract "Tidy-up and the move log") ---
/** Why a file can't be moved: the code and the plain words to show. */
export type TidySkip = { reason: 'offline' | 'not_found' | 'name_taken'; text: string };
/** One file a tidy-up could move. `from` / `to` are folders relative to `Library/` (`""` = Library itself, shown
 *  "Library"); `from_path` is what the page sends back to `tidy_up` / `save_playlists`. */
export type TidyRow = TrackRow & {
  file_id: number; from: string; to: string; from_path: string; placed_by: 'app' | 'user' | 'import';
  /** moves by default: no skip and placed by the app */
  ticked: boolean;
  /** placed by the user or an import: marked "You put this here", listed apart */
  yours: boolean;
  skip: TidySkip | null;
  /** save preview only: the old folder name whose rename on disk would put this file at its target */
  by_rename: string | null;
};
/** The "You put these here" group (null when no row is `yours`). */
export type TidyYours = { count: number; movable: number; mark: string; header: string; control: string };
export type TidyPreview = {
  rows: TidyRow[]; ticked: number; rekordbox: string[]; undo_note: string;
  /** null, or the text shown instead of the list (nothing out of place, or only `yours` rows left) */
  empty: string | null; yours: TidyYours | null;
};
export type MoveBatch = { id: number; at: string; title: string; moved: number; skipped: number;
  /** 0: the Undo button reads "Nothing left to undo" */
  undoable: number; undone_by: number | null; summary: string };
export type MoveBatches = { batches: MoveBatch[]; total: number };
export type UndoSkip = { reason: string; text: string };
/** `kind` "folder": a folder rename going back, `files` how many files are in it (null for a file row). */
export type UndoRow = { label: string; kind: 'file' | 'folder'; files: number | null; from: string; to: string;
  skip: UndoSkip | null };
export type UndoPreview = {
  batch_id: number; title: string; rows: UndoRow[];
  moving: number; warning: string[]; nothing_left: boolean;
};
export type SkippedMove = { label: string; from: string; to: string; reason: string; text: string };
/** What a move batch tells the page: `tidy_up`, `undo_moves` and each item of `save_playlists`' `batches` finish with it
 *  (also with problem `stopped`, then `stopped` is true). `batch_id` is null when nothing was asked to move. */
export type BatchResult = { batch_id: number | null; title: string; moved: number; headline: string;
  skipped: SkippedMove[]; stopped: boolean };
/** `save_playlists`' third argument: the answer to the save question. */
export type SaveFiles = { choice: 'leave' | 'move'; renames: [string, string][]; moves: [number, string][] };

export type ReadStatus = {
  read_at: string | null; minutes_ago: number | null; problem: ProblemKind | null; message: string;
  /** the playlist service `problem` is about (null: no service's problem; a good read clears it) */
  problem_service: PlaylistService | null;
  /** the services the switched-on lines of playlists.txt use, in line order; `connected`: its login files exist */
  services: { service: PlaylistService; name: string; connected: boolean }[];
  stale: boolean; reading: boolean; offline: boolean;
  /** the hub's one automatic read of this session has started (kept in Python, so also after a window reload) */
  auto_read: boolean;
};
export type Budget = { used: number; allowance: number; limit: number; carry_over: number; extra: number;
  remaining: number };
export type RunCounts = { lossless: number; lossy: number; problems: number; moved: number };
/** One track of the sync's Auto-upgrade phase (auto_upgrade.py). `state` `would` only in a dry run; `reason` a waiting
 *  row's `rekordbox_open` | `busy` | `not_reached`, a refused row's `EligibleReason` key; `how` the way Same track goes. */
export type AutoUpgradeResult = { track: string; name: string; state: 'done' | 'would' | 'waiting' | 'refused' | 'failed';
  reason: string | null; message: string | null; how: 'in_place' | 'new_aiff' | null };
/** A run's Auto-upgrade block (the report's `.json` key `auto_upgrade`, contract "Auto-upgrade"): `batch` null when no
 *  batch ran, `waiting` = rekordbox open + busy + not reached. */
export type AutoUpgradeBlock = { batch: number | null; backup: string | null; done: number; waiting: number;
  refused: number; failed: number; stopped: boolean; dry_run: boolean; results: AutoUpgradeResult[] };
export type RunSummary = {
  run_id: string; started: string; finished: string | null; duration_s: number | null; exit_code: number;
  counts: RunCounts; stopped_after: number | null;
  /** the run's Auto-upgrade phase and its one-line account (`line`: "Upgraded 2 tracks; your cues stayed. 1 waits for
   *  rekordbox to be closed."; null when nothing happened); null when the switch was off for the run */
  auto_upgrade: (AutoUpgradeBlock & { line: string | null }) | null;
};
export type ErrorKind = 'network' | 'qobuz' | 'other' | 'not_found';
export type Result = {
  section: string; folder: string; artist: string; title: string; track_id: string | null; note: string;
  status: Status | null; source: Source | string | null; cutoff_hz: number | null; path: string | null;
  error_kind: ErrorKind | null;
  found_status?: Status | null;   // upgrade_ready: the found file's status (status is the current file's); missing in old runs
  cover_url?: string | null;   // run(run_id) only: rows shown one by one
};
export type RunDetail = RunSummary & {
  sections: Record<string, Result[]>; needs_you: Result[];
  for_rekordbox: { new_files: number; folders: string[] }; upgrades_ready: number; report_md: string;
  queued: number; folder_order: string[];   // tracks waiting for the next sync; playlist folders in their order
};

export type PlanCounts = { new: number; retries: number; redownloads: number; bought: number; weekly_checks: number };
/** duration_min counts only the downloads that fit today (the rest wait for the next sync at once). */
/** left null: no daily limit (only free sources are set up). accounts: the expected split between the services. */
export type Estimate = { duration_min: number; qobuz_limit: number; qobuz_needed: number; qobuz_left: number;
  qobuz_uses: number; accounts: EstimateAccount[]; left: number | null; limit: number };
/** The Sync page's estimate: also `minutes_by_downloads[n]`, the minutes for n downloads (n = 0 … `qobuz_uses`, the
 *  most any ticked subset can run today), and per account `uses_by_downloads[n]`, its `uses` for n downloads (null for
 *  a backup behind Qobuz). The page looks its subset's count up here (a larger count takes the last entry); the
 *  formula and the split live in the engine. */
export type SyncAccount = EstimateAccount & { uses_by_downloads: number[] | null };
export type SyncEstimate = Omit<Estimate, 'accounts'> & { accounts: SyncAccount[]; minutes_by_downloads: number[] };
export type Dashboard = {
  greeting: string; read_status: ReadStatus;
  tiles: {
    lossless: { share: number | null; lossless: number; total: number; by_quality: ByQuality };
    qobuz_today: Budget;
    still_to_load: { count: number; days: number; fits_today: boolean };
    account_today: LimitCard | null;
  };
  ready: (Estimate & { counts: PlanCounts; actions: number }) | null;
  needs_you: { upgrades: number; swappable: number; not_found: number; weak: number };
  folders: { folder: string; tracks: number; lossless_share: number | null; by_quality: ByQuality }[];
  last_runs: RunSummary[]; has_more_runs: boolean; next_checks: number; empty: EmptyKind | null;
};
/** Where a folder is now: `here`, `offline` (its drive isn't connected) or `folder_missing` (not found: moved, renamed,
 *  deleted); the innermost watched folder that is away decides, for its crates too. */
export type FolderState = 'here' | 'offline' | 'folder_missing';
/** A crate: a folder below a watched import folder that holds music itself (wrapper folders get no row). `label` is
 *  its short name in the browser ("Hardtechno › 2019", "Bounce · Old Sets" when another crate has the name), `name` the
 *  folder's own, `tip` the whole way from the watched folder ("Rekordbox Library › Hardtechno › 2019"), `files` the
 *  files at or below it. `hidden`: out of the sidebar (the user's switch, else the default: shown, but hidden under a
 *  folder with `too_many` crates); `has_crates`: another crate lies below it. */
export type Crate = { path: string; label: string; name: string; tip: string; files: number; hidden: boolean;
  has_crates: boolean };
/** A watched import folder in the sidebar, by name. `place` is the folder's path in words ("~/Music/Old", "Example
 *  Drive › Music"); `files` leaves out those an import still has to work through; `crates`: all of them, label
 *  order; `crate_count` and `too_many` (more than 25 crates) as in `Crate`. */
export type WatchedEntry = { path: string; name: string; place: string; files: number; state: FolderState;
  too_many: boolean; crate_count: number; crates: Crate[] };
/** A Favourite, resolved: `key` is `playlist:<ref>` or `folder:<path>` (what `set_favourites` takes). Keys whose
 *  playlist or folder is gone are left out of the answer (the engine keeps them stored, also through a
 *  `set_favourites` that does not name them). `count`: a playlist's songs
 *  (null: never read) or a folder's files. `path`: the folder's, null for a playlist. */
export type Favourite = { key: string; kind: 'playlist' | 'folder'; name: string; service: PlaylistService | null;
  enabled: boolean; count: number | null; path: string | null; state: FolderState };
export type Sidebar = {
  todo: number; all_tracks: number; not_in_playlist: number; limits_warning: boolean;
  /** in the stored order */
  favourites: Favourite[];
  /** every line of playlists.txt in file order, switched-off ones too; `ref` the playlist's token, `songs` the
   *  distinct songs of its read (null: never read) */
  playlists: { name: string; ref: string; service: PlaylistService | null; enabled: boolean; songs: number | null }[];
  /** the import folders by name */
  watched: WatchedEntry[];
  /** the Library/ folders with files that no playlist line uses, by name; `path` is `Library/<name>` */
  library_folders: { path: string; name: string; files: number }[];
};
/** What `set_favourites` and `set_crate_shown` answer: brief saves that start no job (plan library stage 5, D15). */
export type FavouritesSaved = { favourites: string[] };
export type CrateSaved = { path: string; shown: boolean | null };
export type CratesSaved = { paths: string[]; shown: boolean | null };
export type PreviewGroupKey = 'acquire:new' | 'acquire:retry' | 'acquire:redownload' | 'adopt_bought' | 'upgrade';
export type PreviewAction = {
  key: ActionKey; kind: string; reason: string | null; track_id: string; artist: string; title: string;
  folder: string; to_dir: string; to_not_lossless: boolean; src: string | null;
  cover_url: string | null;
  /** the collections of the browser column the song belongs to (issue 37), by their targets: every playlist whose
   *  read holds it (`playlist:<ref>`, playlists.txt order), then the folders its file sits in, outer to inner
   *  (`folder:<path>`: a watched folder, its crates shown in the sidebar, a Library folder no playlist uses). Sync
   *  leaves the row out only when every one of them is switched off */
  in: string[];
  /** the order the sync works through the actions (kind, then playlist order); not on `never` rows */
  run?: number;
};
export type SyncPreview = {
  read_status: ReadStatus; counts: PlanCounts | null;
  /** songs held back until the user answers "Is this the same song?" (not downloaded meanwhile) */
  waiting_answers: number;
  /** first upgrade checks of imported music that the per-run cap left for later runs */
  deferred_checks: number;
  groups: { key: PreviewGroupKey | string; label: string; actions: PreviewAction[] }[];
  estimate: SyncEstimate | null;
  /** downloads left out because the user said "never download" */
  never: PreviewAction[];
  /** playlists.txt order */
  folders: string[];
  /** unique Spotify tracks read */
  in_playlists: number | null;
  ambiguous: { track_id: string; artist: string; title: string; folder: string; files: string[] }[];
  dropped: { track_id: string; artist: string; title: string; folder: string }[];
  notes: string[]; empty: EmptyKind | null;
  /** every collection a row is `in`, by its target -> its name as the plan's sections name it ("Techno",
   *  "Techno › 2019"); {} before the first read */
  collections: Record<string, string>;
  /** Auto-upgrade before a start: `ready` = the upgrades the sync's last phase would put in place (those that would wait
   *  for rekordbox included; nothing of rekordbox's library is opened for it). null: the switch is off, or no preview */
  auto_upgrade: { on: boolean; ready: number } | null;
};

export type PlannedAction = { kind: string; track_id: string; title: string; artist: string; image_url?: string | null };
export type JobSnap = {
  id: number; kind: string; track_id: string | null; started: string; running: boolean; stopping: boolean;
  // last event of each type (see events.ts); typed loosely here to avoid a cycle
  last: Partial<Record<string, any>>;
  // newest AccountUsage event of each service (`last` keeps only the newest one overall); absent in older bridges
  usage?: any[];
  results: any[];             // ActionFinished events
  finished: any | null;       // JobFinished event
  actions: PlannedAction[];
};
export type JobStatus = { job: JobSnap | null; refresh_running: boolean; console_running: boolean;
  read_status: ReadStatus;
  /** a sign-in waiting for the browser (its own slot beside the write jobs; Settings restores its phase from it) */
  sign_in?: JobSnap | null };

/** `sound_checked` false: an imported file whose sound isn't judged yet, its quality is the codec's guess for now.
 *  `file_state`: whether the row's file is there now, decided per watched folder (never `file_missing`, which only
 *  `track()` checks); a row that isn't `here` doesn't play. `no_file`: a playlist song that has no file yet (only in a
 *  playlist view): `wait` says why, `path` is null.
 *  `place`: the folder the file sits in, in the Folder column's words (null: no file, or the playlist view's rows inside
 *  the playlist's own Library folder). `subfolder`: folder views only: a watched folder's rows carry their crate's label
 *  ("" for a file directly in it), a crate's the folders below it ("2019" or "A › B"); null elsewhere. `position`: the
 *  place in the playlist's read (playlist view only). `playlists`: the playlists whose read holds the song, in
 *  playlists.txt order. */
export type LibraryRow = TrackRow & { sound_checked: boolean; file_state: Exclude<FileState, 'file_missing'> | 'no_file';
  wait: 'waiting' | 'not_found' | null;
  /** a `not_found` row: the day the sync looks again (ISO; due on and after it) or 'next_sync' (never looked yet);
   *  null on every other row (views.next_due) */
  next_try: string | null; position: number | null; place: string | null; subfolder: string | null;
  playlists: string[];
  /** the song's page on its service, for the row menu's "Open in {Service}" (null: no page known; the item is absent) */
  track_link: TrackLink | null };
export type LibraryView = 'all' | 'unlisted' | 'playlist' | 'folder';
export type Library = {
  /** the folder at a glance, unaffected by the search and the filter; to_do: what the to-do list shows of it;
   *  not_lossless: the checked files that aren't lossless (good lossy + weak + fake). Only the rows with a file count. */
  title: string; summary: { tracks: number; lossless_share: number | null;
    by_quality: ByQuality; upgrades_ready: number; to_do: number; not_lossless: number };
  /** the old `folder` argument: null (All tracks), NOT_IN_PLAYLIST, a playlist's folder name or a folder's key */
  folder: string | null;
  /** what the request asked for; `key`: the playlist's folder name as playlists.txt spells it, or the folder's path
   *  (null for All tracks and Not in a playlist) */
  view: LibraryView; key: string | null;
  /** folder views: what the folder is. `library`: a Library/ folder; null: none of these (`empty` is `gone`) */
  folder_kind: 'watched' | 'crate' | 'library' | null;
  /** the header's second line as parts in order of importance (the page drops the last parts first); empty when `gone` */
  subtitle: string[];
  chips: Record<LibraryFilter, number>; rows: LibraryRow[];
  /** a playlist view: the files in the playlist's own Library folder whose song the playlist doesn't hold; null elsewhere */
  also: LibraryRow[] | null;
  /** a read playlist's songs: how many it lists (distinct, what the sidebar's `songs` counts) and how many of them have
   *  a file, before any search or filter; null elsewhere and while never read. The page words "13 of 18 downloaded". */
  songs: { listed: number; with_file: number } | null;
  /** a playlist view: when its read was made (null: never read), whether its line is switched on, its service */
  read_at: string | null; enabled: boolean | null; service: PlaylistService | null;
  /** the newest stopped `library:*` AIFF batch (Make all, a selection's Convert) with items left: the header's
   *  "Resume · {left} left"; null when none (issue 33 stage D) */
  aiff_stopped: { batch_id: number; left: number } | null;
  empty: EmptyKind | null;
};
export type Alignment = { drift_ms: number | null; offset_ms: number | null; offset_samples: number | null;
  result: string; text: string };
export type AutoRefused = { reason: 'timing' | 'not_analysed' | 'cloud' | 'space' | 'needs_choice'; message: string;
  at: string | null };
export type Upgrade = {
  file: string; source: Source | string; source_name: string; source_id: string; found: string; what: string;
  quality_line: string; /** "FLAC · lossless": the new version's quality, as the current file's `format_line` */
  format_line: string; alignment: Alignment; cue_text: string; swap_safe: boolean;
  /** Same track can run now (any format); `why_not` is the reason key when it can't (null when it can) */
  swap_possible: boolean; why_not: string | null;
  /** `in_place`: an AIFF takes the audio; `new_aiff`: a new AIFF with a clean name, rekordbox's track pointed at it */
  swap_how: 'in_place' | 'new_aiff';
  /** rekordbox's cached state on this Mac */
  rekordbox: { state: 'ready' | 'none' | 'unreadable'; running: boolean };
  /** the refusal the sync's Auto-upgrade phase recorded (`reason`: timing | not_analysed | cloud | space | needs_choice;
   *  `message` its words, `at` an ISO time); shown whatever the switch says */
  auto_refused: AutoRefused | null;
  /** the sync met rekordbox open for this upgrade: only while the switch is on and Same track could run */
  auto_waits: boolean;
  audio_url: string | null;
};
/** The artist's free download of a SoundCloud version: a gate page (follow, like or e-mail; `host` e.g.
 *  hypeddit.com) or SoundCloud's own download button (`direct`). */
export type FreeDownload = { url: string; host: string; direct: boolean; title: string; uploader: string };
/** The track's page on the service it was read from; `label` "Open in Spotify" / "Open in Qobuz"; `service` the
 *  playlist service the page belongs to (the logo beside "Open in …"). */
export type TrackLink = { url: string; label: string; service: PlaylistService };
export type FileState = 'here' | 'offline' | 'folder_missing' | 'file_missing';
export type TrackDetail = TrackRow & {
  /** false: an imported file whose sound isn't judged yet (see LibraryRow); `quality_line` then ends "sound not checked yet" */
  sound_checked: boolean;
  /** why the file is or isn't there: `offline` (its drive isn't connected), `folder_missing` (its watched folder isn't
   *  found), `file_missing` (the folder is there, the file's path isn't: it went since the last scan); `audio_url` is
   *  null for all but `here` */
  file_state: FileState;
  /** where the file sits, as the Folder column says it (null without a file) */
  place: string | null;
  isrc: string | null; playlists: string[] | null; in_playlist_count: number; quality_line: string;
  /** "Opus · 135 kbps", "FLAC"; source_full: "YouTube Music", "bought", "your own file" for a file the import
   *  found (both null without a file) */
  format_line: string | null; source_full: string | null;
  /** "Opus · 135 kbps", "FLAC": what the download was made from; null without a file and for an own or bought file.
   *  `format_line` is the file itself ("AIFF · 16-bit", "WAV · 24-bit", "FLAC") */
  source_format_line: string | null;
  /** how the source was found; null for an own or bought file and for a file from before this was stored */
  source_how: SourceHow | null;
  /** the source's page; null when it is the song's own page (`track_link`) */
  source_url: string | null; track_link: TrackLink | null; next_qobuz_check: string | null;
  rejected_sources: string[]; buy_links: { beatport: string; bandcamp: string }; free_downloads: FreeDownload[];
  bought_name: string; audio_url: string | null; upgrade: Upgrade | null;
  /** what Convert and "Give it its clean name" can do for this file (issue 33 stage D); null: no file, a download
   *  or a parked upgrade (the upgrade decision stands) */
  aiff: TrackAiff | null;
};
/** `track().aiff`. With an `action`: `kind` (an `AiffKind`), `from` the file's format line ("FLAC · 24-bit · 96 kHz"),
 *  `to` what a Convert makes ("AIFF · 16-bit · 44.1 kHz"; null for a rename), `new_name` the file's name when done
 *  (equal to `name_now` for a Convert whose AIFF ends where the old file was), `bytes` the room the render needs.
 *  Without: `why_not` is the reason (an `EligibleReason` key such as `named_already`, `away`, `rekordbox_unreadable`),
 *  `from`, `lossy` and `cdj` still say what the file is, `kind` / `to` / `new_name` null, `bytes` 0. */
export type TrackAiff = { action: 'convert' | 'rename' | null; why_not: string | null; kind: string | null;
  from: string | null; to: string | null; name_now: string; new_name: string | null; bytes: number; lossy: boolean;
  cdj: CdjWords | null };
export type Todo = {
  chips: Record<TodoFilter, number>;
  /** the tracks with an open check in rekordbox, whatever the filter: `chips.rekordbox_check` counts items (a batch is
   *  one), this counts tracks (a batch counts its `size`), the page header's number */
  check_tracks: number; hidden_count: number; show_hidden: boolean;
  groups: { key: TodoGroupKey; label: string; hint: string; items: TodoItem[];
    /** `upgrade_ready`: Upgrade all's counts (Same track can run / the edit needs a choice / waits for something
     *  else) and the newest stopped Same track batch with items left. `cdj` (stage D): `all` is `{n, k}` (what Convert
     *  all can do now / what waits; no `m`) and `stopped` the newest stopped `todo:*` batch with items left */
    all?: { n: number; m?: number; k: number }; stopped?: { batch_id: number; left: number } | null }[];
  empty: EmptyKind | null;
};

/** `owner_name` is "" when the name already says it (a SoundCloud likes list, "{username}'s likes"). */
export type PlaylistInfo = { name: string; owner_name: string; yours: boolean; collaborative: boolean;
  readable: boolean; image_url: string | null;
  /** null: the service gave no count (a SoundCloud likes list) */
  track_count: number | null;
  /** the words of the row's service for a playlist it won't show (always set once info is) */
  hint: string };
/** `playlist_id` is the playlist's ref: a Spotify id stays bare, every other service's is `<service>:<id>`
 *  (`qobuz:<id>`, `soundcloud:user/sets/slug`, `youtube_music:<list id>`). */
export type PlaylistRow = { index: number; folder: string; link: string; playlist_id: string | null;
  service: PlaylistService; service_name: string; enabled: boolean; info: PlaylistInfo | null;
  tracks: number | null; quality: ByQuality;
  /** a listed Liked music line while Settings' choice is off (or no YouTube login): the choice it needs, else null */
  needs_setting: SettingKey | null };
/** A track of a Spotify playlist on the playlists page; `downloaded`: it has a file yet. */
export type PlaylistTrack = { track_id: string; artist: string; title: string; cover_url: string | null;
  downloaded: boolean; quality: Quality; quality_label: string | null;
  /** "never download" (the user left it out of the sync) */
  never?: boolean };
export type Playlists = {
  version: string; problem: string | null; rows: PlaylistRow[];
  overlaps: (PlaylistTrack & { folders: string[]; lands_in: string })[];
  empty: EmptyKind | null;
  /** `waiting`: files a tidy-up ticks by default (the "Tidy up files" badge) */
  tidy: { waiting: number };
};

export type Assessment = { level: number; label: string };
export type WhatIf = { limit: number; extra_today: number; assessment: Assessment; allowance_today: number;
  remaining_today: number; days_to_load: number | null; run_minutes: number };
export type SignalKind = 'login_failed' | 'search_failed' | 'download_rejected' | 'preview_only'
  | 'duration_mismatch' | 'auto_stop';
export type QobuzUsage = {
  today: Budget; days: { date: string; used: number }[];
  still_to_load: { count: number; days: number; fits_today: boolean };
  setting: { limit: number; extra_today: number; recommended: number;
    zones: { name: string; from: number; to: number }[]; min: number; max: number; extra_max: number };
  assessment: Assessment; what_if: WhatIf;
  signals: Signal<SignalKind>[];
  signal_summary: Record<SignalKind, number>; last_download: string | null;
};
export type Browser = 'safari' | 'chrome' | 'firefox' | 'brave' | 'edge';
export type Service = 'qobuz' | 'youtube' | 'soundcloud';
export type AccountSignalKind = 'cookies_unreadable' | 'bot_check' | 'rate_limited' | 'refused' | 'premium_missing'
  | 'download_rejected' | 'auto_stop';
export type AnySignalKind = SignalKind | AccountSignalKind;
export type LimitCard = { service: Service; name: string; set_up: boolean; used: number; allowance: number;
  /** warning signs of the last 14 days; `new_warnings`: those after the last "Got it" */
  warnings: number; new_warnings: number; paused: boolean };
/** A warning sign: `new` = after the last "Got it", `clears_in` = days until it leaves the 14 days (1 = tomorrow). */
export type Signal<K extends string = AnySignalKind> = { time: string; kind: K; message: string; new: boolean; clears_in: number };
export type ServiceUsage = Omit<QobuzUsage, 'signals' | 'signal_summary' | 'still_to_load'> & {
  service: Service; name: string;
  /** "Qobuz" for an account behind Qobuz (it only gets the tracks Qobuz lacks), else null */
  behind: string | null;
  still_to_load: { count: number | null; days: number | null; fits_today: boolean | null };
  signals: Signal[];
  signal_summary: Partial<Record<AnySignalKind, number>>;
};
export type Limits = { service: Service; cards: LimitCard[]; usage: ServiceUsage | null };
export type EstimateAccount = { service: Service; name: string; uses: number | null; left: number; limit: number;
  about: boolean };

/** `waveform`: base64 of `cols` bytes, the peak of each column's stretch of the track (0 = silence, 255 = the
 *  loudest column), for the mini player's bars. */
export type Spectrum = { cols: number; bands: number; max_hz: number; duration_s: number; floor_db: number;
  data: string; waveform: string; which: Which; cutoff_hz: number | null };

/** The music folder (spec public-release §4): ok (bound) · not_chosen (Setup's first step) · missing (config.json
 *  names a folder that isn't there, e.g. an unplugged drive). `path`: the bound or missing folder. */
export type MusicState = 'ok' | 'not_chosen' | 'missing';
export type MusicStatus = { state: MusicState; path: string | null; suggested: string };
export type FolderKind = 'new' | 'empty' | 'discjockey_library' | 'other_files';
export type FolderProblem = 'not_absolute' | 'not_a_folder' | 'system_folder' | 'inside_app' | 'is_support_dir'
  | 'not_writable';
export type FolderCheck = { path: string; exists: boolean; usable: boolean; problem: FolderProblem | null;
  kind: FolderKind | null; message: string | null };

/** The update check's last answer (app_update(), event AppUpdate); `latest` and `url` only when `available`. */
export type AppUpdate = { state: 'available' | 'up_to_date' | 'unknown'; current: string; latest: string | null;
  url: string | null };

/** The required step setup_status() names next; `downloads` = Qobuz signed in or left out. */
export type SetupStep = 'music' | 'tools' | 'spotify' | 'downloads' | 'playlists';
export type SetupStatus = {
  music: MusicStatus;
  tools: { ffmpeg: boolean; ffprobe: boolean; deno: boolean }; spotify_app: boolean; spotify_login: boolean;
  qobuz: boolean; playlists: boolean; complete: boolean; next_step: SetupStep | null;
  /** discjockey.__version__ */
  version: string;
  /** "I don't have Qobuz": the Downloads step counts as done */
  qobuz_skipped: boolean;
  /** "I don't use Spotify": the Spotify step counts as done (connecting Spotify clears it) */
  spotify_skipped: boolean;
  qobuz_last_check?: LastCheck | null;
  /** the Spotify account's display name, saved at login (null: not connected or not known) */
  spotify_user?: string | null;
  /** Setup's "Your existing music" step: done once an import folder is watched or it was skipped. Not a required
   *  step: it never changes `next_step` or `complete`, and never blocks Continue */
  existing: boolean;
  /** the import folders watched */
  import_folders: number;
  /** Skip was pressed (`setup_skip_import`) */
  import_skipped: boolean;
  accounts: { youtube: AccountStatus | null; soundcloud: AccountStatus | null };
  /** YouTube Music's Liked music: the choice, whether it can be turned on (a YouTube account is set up) and whether
   *  a Liked music line is in playlists.txt (on or off) */
  youtube_music: { liked_music: boolean; can_turn_on: boolean; listed: boolean };
  /** "Upgrade automatically when I sync" (Settings, Setup's Downloads step): on by default */
  auto_upgrade: boolean;
};
/** rekordbox on this Mac now (`rekordbox_status()`): its library's state and whether it runs. */
export type RekordboxStatus = { state: 'ready' | 'none' | 'unreadable'; running: boolean };
export type AccountStatus = { browser: Browser; browser_name: string; daily_limit: number; profile?: string | null;
  profile_name?: string | null; last_check?: LastCheck | null };
/** find_logins(service): the installed browsers, the default first, and which profiles hold a login. */
export type LoginBrowser = { id: Browser; name: string; default: boolean; readable: boolean;
  problem: 'no_access' | 'locked' | null; profiles: { id: string | null; name: string; signed_in: boolean }[] };
export type FindLogins = { browsers: LoginBrowser[] };
/** A saved login check (settings.json): when it ran and what it found. */
export type LastCheck = { ok: boolean; problem: string | null; kbps: number | null; at: string };
/** downloads_view(): the source ladder and the account panels (spec settings-setup §6.4). */
export type DownloadsView = {
  qobuz: { state: 'on' | 'off' | 'skipped' | 'paused' | 'used_up'; last_check: LastCheck | null; tracks: number };
  youtube: DownloadsAccount; soundcloud: DownloadsAccount;
  library: { lossless: number; account: number; free: number };
};
export type DownloadsAccount = {
  state: 'on' | 'off' | 'no_premium' | 'unreadable' | 'paused' | 'used_up';
  browser: Browser | null; browser_name: string | null; profile: string | null; profile_name: string | null;
  last_check: LastCheck | null;
  /** the library's tracks this account brought in at about 256 kbps */
  tracks: number;
};
export type AccountCheck = { ok: boolean; problem: 'cookies_unreadable' | 'not_logged_in' | 'no_premium' | 'failed' | null;
  kbps: number | null; message: string };
/** One download tool in Settings → This Mac (setup_check_tools' download_tools). */
export type DownloadTool = {
  /** what this window runs (null: not installed) */
  version: string | null;
  /** came with Discjockey, or brought by Update download tools */
  source: 'built_in' | 'updated';
  /** the version the next start uses, when it differs: an update or a step back waits for a reopen */
  waiting: string | null;
  /** what Go back would use (null: nothing to go back to) */
  previous: string | null;
};
export type DownloadTools = { 'yt-dlp': DownloadTool; streamrip: DownloadTool };
export type SetupTools = { tools: { ffmpeg: boolean; ffprobe: boolean; deno: boolean }; missing: string[];
  hints: Record<string, string>; redirect_uri: string;
  /** null when reading them failed unexpectedly: download_tools_problem then says so in a plain sentence */
  download_tools: DownloadTools | null; download_tools_problem: string | null };
/** update_tools / rollback_tools: the version the next start uses before and after; restart: reopen to use it */
export type ToolsChange = { before: Record<string, string | null>; after: Record<string, string | null>;
  restart: boolean };

export type Candidate = {
  source: Source | string; id: string; title: string; artist: string; duration_s: number | null;
  url: string | null; isrc: string | null; album: string | null; label: string | null; image_url: string | null;
  key: string; source_name: string; length_diff_s: number | null; can_preview: boolean; score: number | null;
  matches: boolean; length_ok: boolean; current: boolean; rejected: boolean;
};
export type Candidates = { track_id: string; track_duration_s: number; current_quality_label: string;
  candidates: Candidate[]; notes: string[] };
export type AddedPlaylist = { playlist_id: string; service: PlaylistService; service_name: string; link: string;
  info: PlaylistInfo | null; tracks: number | null;
  readable: boolean; suggested_folder: string; hint: string | null };
export type ChangeKind = 'moves' | 'rename' | 'reroute' | 'add' | 'switch_off' | 'unknown' | 'none';
/** A folder rename on disk this save could do; `offered` false: show `why_not` instead of the choice. */
export type RenameOffer = { from: string; to: string; files: number; offered: boolean; why_not: string | null;
  option: string; detail: string };
export type ChangePreview = {
  kind: ChangeKind; headline: string; folders: { folder: string; before: number; after: number }[];
  /** the files this change would put in another folder (null: none) */
  tidy: { headline: string; rows: TidyRow[] } | null; renames: RenameOffer[];
  reroutes: (PlaylistTrack & { from: string; to: string })[]; new_downloads: number; days: number; stopped: number; unknown: string[];
  checklist: string[]; problem: string | null;
};
export type OpResult = { track_id: string; result: Result; recovered: [string, boolean][] };

// --- AIFF batches (Same track, Upgrade all, issue 33 stage B; contract "Upgrades and batches") ---
/** One track of a batch: `reason` an `EligibleReason` key (skipped only), `message` the words, `rekordbox` what was
 *  written there. */
export type ItemResult = { track: string; action: string; state: 'planned' | 'done' | 'skipped' | 'failed' | 'undone';
  reason: string | null; message: string | null; path: string | null;
  rekordbox: { entries: string[]; kept: string[] } | null };
/** The result of `upgrade(…, 'swap')`, `upgrade_all`, `batch_resume` and, in stage D, `convert`, `rename` and `make_aiff`
 *  (job `aiff_batch`); New track and Discard lists have the same shape
 *  with `batch` null (and a job also carries it when it ends `stopped`, `rekordbox_open`, `busy` or `refused`). */
export type AiffBatchResult = { batch: number | null; state: 'running' | 'stopped' | 'done';
  stop_reason: 'stop' | 'rekordbox_open' | 'busy' | 'crash' | null; total: number; done: number; skipped: number;
  failed: number; results: ItemResult[]; backup: string | null; recovered: [string, boolean][] };
// --- Convert, clean names, Make all lossless files AIFF (issue 33 stage D; contract "Convert and clean names") ---
/** What `aiff_plan`, `convert`, `rename` and `make_aiff` take: a selection, a view's lossless files, or the CDJ group. */
export type AiffScope =
  | { kind: 'tracks'; tracks: string[] }
  | { kind: 'lossless'; view: LibraryView; key: string | null }
  | { kind: 'cdj' };
/** The kinds of an item in the panel's order: `flac`, `wav`, `alac`, `aiff_hires`, `tags`, `name`, `wavpack`, `ape`,
 *  `tta`, `mp3`, `aac`, `opus`, `vorbis`, then any other codec by its own name. */
export type AiffKind = string;
/** One file the run would change; `path` / `new_path` / `superseded` are relative to the music folder (an own file in
 *  a watched folder: absolute); `superseded` null for a rename. */
export type AiffPlanItem = { track: string; name: string; action: 'convert' | 'rename'; kind: AiffKind; from: string;
  path: string; new_path: string; superseded: string | null; bytes: number; cdj: CdjWords | null };
/** A file of a `tracks` scope that is left as it is: `reason` an `EligibleReason` key, `message` its words. */
export type AiffLeft = { track: string; name: string; reason: string; message: string };
export type AiffPlan = {
  /** the scope as asked plus `label`: "Selection", "Won't play well on CDJs", else the view's title */
  scope: AiffScope & { label: string };
  items: AiffPlanItem[]; skipped: AiffLeft[];
  /** files that can't run now but may later, each once and never an item, in the order away, file_missing, no_name,
   *  rekordbox_unreadable, cloud, rename_blocked, upgrade_waits */
  waiting: { reason: string; message: string; n: number }[];
  kinds: { kind: AiffKind; label: string; n: number }[];
  /** how many items have a lossy file now (their AIFF sounds the same, only the format changes) */
  lossy: number; total: number;
  /** the room the new files need per drive (`drive` a folder on it); a rename needs none */
  space: { drive: string; needed: number; free: number; enough: boolean }[];
  superseded_bytes: number;
  rekordbox: { state: 'ready' | 'none' | 'unreadable'; running: boolean; needs_closed: boolean } };
export type UndoItem = { track: string; state: 'undone' | 'refused' | 'failed' | 'waiting'; reason: string | null;
  message: string };
export type UndoResult = { batch: number | null; total: number; undone: number; refused: number; failed: number;
  results: UndoItem[]; recovered: [string, boolean][];
  /** stage D: what the undo says when it worked ("Conversion undone. Your old file is back."); only on success */
  words?: string };
export type CheckedResult = { results: Result[]; checked: string[]; not_checked: string[]; recovered: [string, boolean][] };

// JobFinished.result per job kind (a crashed sync carries its SyncResult too: exit_code 1, report = the crash note)
export type SyncResult = { exit_code: number; report: string; actions: number; new_since_preview: number };
export type JobResults = {
  import: ImportResult; folders: { files: number; redownload: number };
  answer: Record<string, never>; supersede: { result: Result; recovered: [string, boolean][] };
  refresh: { actions: number }; sync: SyncResult; save_playlists: { version: string; batches: BatchResult[] };
  tidy: BatchResult; undo_moves: BatchResult;
  save_limits: { service: Service; limit: number; extra_today: number };
  mark_warnings_seen: { service: Service; seen_until: string };
  setup_skip_qobuz: Record<string, never>; setup_skip_spotify: Record<string, never>;
  set_read_liked_music: Record<string, never>; add_liked_music: { folder: string };
  set_auto_upgrade: Record<string, never>;
  setup_account: { service: Service; browser: Browser; profile: string | null; saved: boolean; check: AccountCheck };
  account_sign_in: { service: Service; browser: Browser; profile: string | null; saved: boolean; check: AccountCheck };
  qobuz_check_login: Record<string, never>; spotify_sign_out: Record<string, never>;
  setup_forget_account: { service: Service };
  never_download: { track_id: string; never: boolean };
  scan: { moved: number; new: number; gone: number; changed: number; copies: number };
  hide: OpResult; unhide: OpResult; add_bought_file: OpResult; use_candidate: OpResult; use_link: OpResult;
  reject_current: OpResult; rekordbox_checked: CheckedResult; upgrade_batch: AiffBatchResult; aiff_batch: AiffBatchResult; batch_resume: AiffBatchResult;
  upgrade_add_new: AiffBatchResult; upgrade_discard: AiffBatchResult; batch_undo: UndoResult; undo_upgrade: UndoResult; setup_save_client_id: Record<string, never>; setup_spotify_login: { user: string };
  setup_qobuz_login: Record<string, never>;
  update_tools: ToolsChange; rollback_tools: ToolsChange;
};
