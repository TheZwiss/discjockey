// The hand-written part of the bridge's types. Every other shape is generated into types.gen.ts from
// discjockey/hub/shapes/ (`uv run python -m discjockey.hub.shapes --export`); edit the Python shapes, never the
// generated file. This file re-exports it, so the window imports every type from here, and keeps only what is
// generic: Res, JobStart, NOT_IN_PLAYLIST, the guards and JobResults (E7e removes it).
export * from './types.gen';
import type { Fail, TodoItem, BatchCheckItem, QuestionItem, DuplicateItem, Result, RefreshResult, SyncResult, SaveLimitsResult, WarningsSeenResult, ScanResult, MissingResult, OpResult, CheckedResult, AiffBatchResult, UndoResult, ImportResult, BatchResult, Service, Browser, AccountCheck, ToolsChange } from './types.gen';

export type Res<T> = ({ ok: true } & T) | Fail;
export type JobStart = Res<{ job_id: string }>;
export const NOT_IN_PLAYLIST = '__not_in_playlist__';

export const isBatch = (i: TodoItem): i is BatchCheckItem => i.group === 'rekordbox_check' && !!i.batch;
export const isQuestion = (i: TodoItem): i is QuestionItem => i.group === 'same_song' && !!i.pair;
export const isDuplicate = (i: TodoItem): i is DuplicateItem => i.group === 'duplicate' && !!i.pair;

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
