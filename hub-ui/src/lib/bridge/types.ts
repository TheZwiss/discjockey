// Every JSON shape of docs/hub-bridge-contract.md, field by field. Source of truth: discjockey/hub/{api,views,jobs}.py.

export type ProblemKind = 'busy' | 'console' | 'sync_running' | 'not_set_up' | 'login_expired' | 'offline'
  | 'playlist_unreadable' | 'config_invalid' | 'qobuz_login_failed' | 'login_failed' | 'changed' | 'refused'
  | 'failed' | 'stopped' | 'protected' | 'crashed' | 'no_library';
export const PROBLEM_KINDS: readonly ProblemKind[] = ['busy', 'console', 'sync_running', 'not_set_up',
  'login_expired', 'offline', 'playlist_unreadable', 'config_invalid', 'qobuz_login_failed', 'login_failed',
  'changed', 'refused', 'failed', 'stopped', 'protected', 'crashed', 'no_library'];
export type Quality = 'lossless' | 'good_lossy' | 'weak' | 'fake' | 'missing';
export const QUALITIES: readonly Quality[] = ['lossless', 'good_lossy', 'weak', 'fake', 'missing'];
export type EmptyKind = 'no_playlists' | 'not_set_up' | 'empty_library' | 'no_preview' | 'up_to_date' | 'no_match'
  | 'all_lossless' | 'all_hidden' | 'nothing_here';
export type Fail = { ok: false; kind: ProblemKind; message: string };
export type Res<T> = ({ ok: true } & T) | Fail;
export type JobStart = Res<{ job_id: number }>;
export type ActionKey = [string, string, string];          // sent back unchanged to start_sync
export type LibraryFilter = 'all' | 'lossless' | 'good_lossy' | 'weak' | 'fake' | 'upgrade_ready';
export type LibrarySort = `${'' | '-'}${'title' | 'artist' | 'length' | 'source' | 'quality' | 'added' | 'folder'}`;
// The contract adds `rekordbox_check` (the plan's list predates it).
export type TodoFilter = 'all' | 'rekordbox_check' | 'upgrade_ready' | 'not_found' | 'weak' | 'good_lossy' | 'fake'
  | 'other';
export type Which = 'current' | 'upgrade';
export type PlaylistLine = { folder: string; link: string; enabled: boolean };
export const NOT_IN_PLAYLIST = '__not_in_playlist__';

export type Status = 'lossless' | 'not_lossless' | 'fake_lossless' | 'missing';
export type Source = 'qobuz' | 'youtube_music' | 'soundcloud' | 'youtube' | 'manual';
export type ByQuality = Record<Quality, number>;

export type TrackRow = {
  track_id: string; artist: string; title: string; folder: string; duration_s: number;
  status: Status; quality: Quality; quality_label: string; cutoff_hz: number | null;
  source: Source | null; source_name: string | null; in_playlists: boolean; hidden: boolean;
  upgrade_ready: boolean; path: string | null; added: string | null; cover_url: string | null;
};
export type TodoGroupKey = Exclude<TodoFilter, 'all'>;
/** `free`: the artist gives it away (see TrackDetail.free_downloads). */
export type TodoItem = TrackRow & { group: TodoGroupKey; detail: string; free: boolean };
export type MoveRow = TrackRow & { from: string; to: string; to_not_lossless: boolean };

export type SpotifyStatus = {
  read_at: string | null; minutes_ago: number | null; problem: ProblemKind | null; message: string;
  stale: boolean; reading: boolean; offline: boolean;
  /** the hub's one automatic read of this session has started (kept in Python, so also after a window reload) */
  auto_read: boolean;
};
export type Budget = { used: number; allowance: number; limit: number; carry_over: number; extra: number;
  remaining: number };
export type RunCounts = { lossless: number; lossy: number; problems: number; moved: number };
export type RunSummary = {
  run_id: string; started: string; finished: string | null; duration_s: number | null; exit_code: number;
  counts: RunCounts; stopped_after: number | null;
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

export type PlanCounts = { new: number; retries: number; redownloads: number; moves: number; adopts: number;
  bought: number; weekly_checks: number };
/** duration_min counts only the downloads that fit today (the rest wait for the next sync at once). */
/** left null: no daily limit (only free sources are set up). accounts: the expected split between the services. */
export type Estimate = { duration_min: number; qobuz_limit: number; qobuz_needed: number; qobuz_left: number;
  qobuz_uses: number; accounts: EstimateAccount[]; left: number | null; limit: number };
/** The Sync page's estimate: also `minutes_by_downloads[n]`, the minutes for n downloads (n = 0 … `qobuz_uses`, the
 *  most any ticked subset can run today). The page looks its subset's count up here; the formula lives in the engine. */
export type SyncEstimate = Estimate & { minutes_by_downloads: number[] };
export type Dashboard = {
  greeting: string; spotify: SpotifyStatus;
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
export type Sidebar = {
  todo: number; all_tracks: number;
  folders: { folder: string; tracks: number; in_playlists_txt: boolean }[];
  not_in_playlist: number;
  limits_warning: boolean;
};
export type PreviewGroupKey = 'acquire:new' | 'acquire:retry' | 'acquire:redownload' | 'move' | 'adopt'
  | 'adopt_bought' | 'upgrade';
export type PreviewAction = {
  key: ActionKey; kind: string; reason: string | null; track_id: string; artist: string; title: string;
  folder: string; from_folder: string | null; to_dir: string; to_not_lossless: boolean; src: string | null;
  cover_url: string | null;
  /** the order the sync works through the actions (kind, then playlist order); not on `never` rows */
  run?: number;
};
export type SyncPreview = {
  spotify: SpotifyStatus; counts: PlanCounts | null;
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
  spotify: SpotifyStatus;
  /** a sign-in waiting for the browser (its own slot beside the write jobs; Settings restores its phase from it) */
  sign_in?: JobSnap | null };

export type Library = {
  /** the folder at a glance, unaffected by the search and the filter; to_do: what the to-do list shows of it */
  title: string; folder: string | null; summary: { tracks: number; lossless_share: number | null;
    by_quality: ByQuality; upgrades_ready: number; to_do: number };
  chips: Record<LibraryFilter, number>; rows: TrackRow[]; empty: EmptyKind | null;
};
export type Alignment = { drift_ms: number | null; offset_ms: number | null; offset_samples: number | null;
  result: string; text: string };
export type Upgrade = {
  file: string; source: Source | string; source_name: string; source_id: string; found: string; what: string;
  quality_line: string; alignment: Alignment; cue_text: string; swap_safe: boolean; swap_possible: boolean;
  audio_url: string | null;
};
/** The artist's free download of a SoundCloud version: a gate page (follow, like or e-mail; `host` e.g.
 *  hypeddit.com) or SoundCloud's own download button (`direct`). */
export type FreeDownload = { url: string; host: string; direct: boolean; title: string; uploader: string };
export type TrackDetail = TrackRow & {
  isrc: string | null; playlists: string[] | null; in_playlist_count: number; quality_line: string;
  /** "Opus · 135 kbps", "FLAC"; source_full: "YouTube Music", "bought" (both null without a file) */
  format_line: string | null; source_full: string | null;
  source_url: string | null; spotify_url: string | null; next_qobuz_check: string | null;
  rejected_sources: string[]; buy_links: { beatport: string; bandcamp: string }; free_downloads: FreeDownload[];
  bought_name: string; audio_url: string | null; upgrade: Upgrade | null;
};
export type Todo = {
  chips: Record<TodoFilter, number>; hidden_count: number; show_hidden: boolean;
  groups: { key: TodoGroupKey; label: string; hint: string; items: TodoItem[] }[]; empty: EmptyKind | null;
};

export type PlaylistInfo = { name: string; owner_name: string; yours: boolean; collaborative: boolean;
  readable: boolean; image_url: string | null; track_count: number };
export type PlaylistRow = { index: number; folder: string; link: string; playlist_id: string | null;
  enabled: boolean; info: PlaylistInfo | null; tracks: number | null; quality: ByQuality };
/** A track of a Spotify playlist on the playlists page; `downloaded`: it has a file yet. */
export type PlaylistTrack = { track_id: string; artist: string; title: string; cover_url: string | null;
  downloaded: boolean; quality: Quality; quality_label: string | null;
  /** "never download" (the user left it out of the sync) */
  never?: boolean };
export type Playlists = {
  version: string; problem: string | null; rows: PlaylistRow[];
  overlaps: (PlaylistTrack & { folders: string[]; lands_in: string })[];
  empty: EmptyKind | null;
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
  qobuz_last_check?: LastCheck | null;
  /** the Spotify account's display name, saved at login (null: not connected or not known) */
  spotify_user?: string | null;
  accounts: { youtube: AccountStatus | null; soundcloud: AccountStatus | null };
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
export type Candidates = { track_id: string; spotify_duration_s: number; current_quality_label: string;
  candidates: Candidate[]; notes: string[] };
export type AddedPlaylist = { playlist_id: string; link: string; info: PlaylistInfo | null; tracks: number | null;
  readable: boolean; suggested_folder: string; hint: string | null };
export type ChangeKind = 'moves' | 'rename' | 'reroute' | 'add' | 'switch_off' | 'unknown' | 'none';
export type ChangePreview = {
  kind: ChangeKind; headline: string; folders: { folder: string; before: number; after: number }[];
  moves: MoveRow[]; reroutes: (PlaylistTrack & { from: string; to: string })[]; new_downloads: number; days: number; stopped: number; unknown: string[];
  checklist: string[]; problem: string | null;
};
export type OpResult = { track_id: string; result: Result; recovered: [string, boolean][] };

// JobFinished.result per job kind (a crashed sync carries its SyncResult too: exit_code 1, report = the crash note)
export type SyncResult = { exit_code: number; report: string; actions: number; new_since_preview: number };
export type JobResults = {
  refresh: { actions: number }; sync: SyncResult; save_playlists: { version: string };
  save_limits: { service: Service; limit: number; extra_today: number };
  mark_warnings_seen: { service: Service; seen_until: string };
  setup_skip_qobuz: Record<string, never>;
  setup_account: { service: Service; browser: Browser; profile: string | null; saved: boolean; check: AccountCheck };
  account_sign_in: { service: Service; browser: Browser; profile: string | null; saved: boolean; check: AccountCheck };
  qobuz_check_login: Record<string, never>; spotify_sign_out: Record<string, never>;
  setup_forget_account: { service: Service };
  never_download: { track_id: string; never: boolean };
  hide: OpResult; unhide: OpResult; add_bought_file: OpResult; use_candidate: OpResult; use_link: OpResult;
  reject_current: OpResult; rekordbox_checked: OpResult; upgrade_swap: OpResult; upgrade_add_new: OpResult;
  upgrade_discard: OpResult; setup_save_client_id: Record<string, never>; setup_spotify_login: { user: string };
  setup_qobuz_login: Record<string, never>;
  update_tools: ToolsChange; rollback_tools: ToolsChange;
};
