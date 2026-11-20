// The hand-written part of the bridge's types. Every other shape is generated into types.gen.ts from
// discjockey/hub/shapes/ (`uv run python -m discjockey.hub.shapes --export`); edit the Python shapes, never the
// generated file. This file re-exports it, so the window imports every type from here, and keeps only what is
// generic: Res, JobStart, NOT_IN_PLAYLIST and the guards. The other types below are still to move into the shapes.
export * from './types.gen';
import type { Crate, Browser, PlaylistInfo, PlaylistTrack, LibraryView, RefreshResult, SyncResult, SaveLimitsResult, WarningsSeenResult, Service, ScanResult, Fail, ProblemKind, Quality, EmptyKind, PlaylistService, SettingKey, ActionKey, LibraryFilter, TodoFilter, Which, Source, SourceHow, ByQuality, TrackRow, Result, TodoItem, BatchCheckItem, QuestionItem, DuplicateItem, AutoUpgradeBlock, FileState, TrackLink, CdjWords, MissingResult, OpResult, CheckedResult, AiffBatchResult, UndoResult } from './types.gen';

export type Res<T> = ({ ok: true } & T) | Fail;
export type JobStart = Res<{ job_id: string }>;
export const NOT_IN_PLAYLIST = '__not_in_playlist__';

export const isBatch = (i: TodoItem): i is BatchCheckItem => i.group === 'rekordbox_check' && !!i.batch;

// --- the import of the user's own music (plan library stage 4, I11; contract "Watched folders and the import") ---
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
/** rekordbox on this Mac now (`rekordbox_status()`): its library's state and whether it runs; the window's pair. */
export type RekordboxStatus = {
  state: 'ready' | 'none' | 'unreadable';
  running: boolean;
};
/** What `rekordbox_status()` answers: the window's pair plus the command line's richer answer (the window reads `state`
 *  and `running` only): the words for the state and the problem, what is wrong with the library, rekordbox's version,
 *  master.db's path, DB version, modified time (local ISO, to the second) and size; each null where unknown. */
export type RekordboxStatusAnswer = RekordboxStatus & {
  state_text: string;
  problem: 'unclean' | 'busy' | 'key' | 'db_version' | 'schema' | null;
  problem_text: string | null;
  version: string | null;
  library: string | null;
  db_version: string | null;
  modified_at: string | null;
  size: number | null;
  /** Present (true) while a Discjockey writer holds `rekordbox.lock`: `state` is then the last value read. */
  writing?: boolean;
  /** With `writing`: when that value was read (ISO time), null when none was read yet. */
  as_of?: string | null;
};
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

// --- AIFF batches (Same track, Upgrade all, issue 33 stage B; contract "Upgrades and batches") ---
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
  /** `writing` (only then present): a writer held rekordbox.lock, so the plan took the cached state and no lookup */
  rekordbox: { state: 'ready' | 'none' | 'unreadable'; running: boolean; needs_closed: boolean; writing?: boolean } };

// JobFinished.result per job kind (SyncResult, ScanResult and the others of the reads are in types.gen.ts)
export type JobResults = {
  import: ImportResult; folders: { name: string; files: number; redownload: number };
  answer: Record<string, never>; supersede: { result: Result; recovered: [string, boolean][] };
  refresh: RefreshResult; sync: SyncResult; save_playlists: { version: string; batches: BatchResult[] };
  tidy: BatchResult; undo_moves: BatchResult;
  save_limits: SaveLimitsResult;
  mark_warnings_seen: WarningsSeenResult;
  setup_skip_qobuz: Record<string, never>; setup_skip_spotify: Record<string, never>;
  set_read_liked_music: Record<string, never>; add_liked_music: { folder: string };
  set_auto_upgrade: { auto_upgrade: boolean };
  setup_account: { service: Service; browser: Browser; profile: string | null; saved: boolean; check: AccountCheck };
  account_sign_in: { service: Service; browser: Browser; profile: string | null; saved: boolean; check: AccountCheck };
  qobuz_check_login: Record<string, never>; spotify_sign_out: Record<string, never>;
  setup_forget_account: { service: Service };
  never_download: { track_id: string; never: boolean };
  scan: ScanResult; missing_files: MissingResult;
  hide: OpResult; unhide: OpResult; add_bought_file: OpResult; use_candidate: OpResult; use_link: OpResult;
  reject_current: OpResult; rekordbox_checked: CheckedResult; upgrade_batch: AiffBatchResult; aiff_batch: AiffBatchResult; batch_resume: AiffBatchResult;
  upgrade_add_new: AiffBatchResult; upgrade_discard: AiffBatchResult; batch_undo: UndoResult; undo_upgrade: UndoResult; setup_save_client_id: Record<string, never>; setup_spotify_login: { user: string };
  setup_qobuz_login: Record<string, never>;
  update_tools: ToolsChange; rollback_tools: ToolsChange;
};
