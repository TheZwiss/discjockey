// The only bridge to Python. Only this file touches window.pywebview (plan 64.4).
import type {
  AddedPlaylist, Empty, Stopped, Runs, RunAnswer, SpectrumAnswer, AppUpdate, Candidate, Candidates, ChangePreview, Dashboard, Fail, JobStart, JobStatus, Library,
  Limits, LibraryFilter, MoveBatches, SaveFiles, TidyPreview, UndoPreview, LibrarySort, PlaylistLine, Playlists, ProblemKind, QobuzUsage, Res,
  SetupStatus, SetupTools, Sidebar, SyncPreview, Todo, TodoFilter, TrackAnswer, WhatIf, Which,
  Browser, DownloadsView, FindLogins, OpResult, Service, FolderCheck, MusicStatus, ImportFolderCheck,
  RemovalPreview, MissingAction, MissingPreview, WatchedFolders, LibraryView, FavouritesSaved, CrateSaved, CratesSaved, RekordboxStatus, RekordboxStatusAnswer, SyncScope, AiffPlan, AiffScope,
  AiffPlanAnswer, PreviewAnswer, DownloadsViewAnswer, MusicFolderSet, MusicFolderAnswer,
} from './types';
import { CONTRACT_METHODS } from './contract';
import { waitForJob } from '../stores/jobs';
import { toasts } from '../stores/toasts';
import { CRASHED_MESSAGE, RECOVERED_TITLE, problemCopy, successCopy } from '../copy';

export interface Bridge {
  // read, any time
  dashboard(): Promise<Res<Dashboard>>;           sidebar(): Promise<Res<Sidebar>>;
  sync_preview(): Promise<Res<SyncPreview>>;      refresh(auto?: boolean): Promise<JobStart>;
  stop_refresh(): Promise<Res<Stopped>>;   job_status(): Promise<Res<JobStatus>>;
  library(view: LibraryView, key: string | null, query: string, filter: LibraryFilter, sort: LibrarySort | null): Promise<Res<Library>>;
  track(track_id: string): Promise<Res<TrackAnswer>>;
  todo(filter: TodoFilter, show_hidden: boolean): Promise<Res<Todo>>;
  playlists(): Promise<Res<Playlists>>;
  tidy_preview(): Promise<Res<TidyPreview>>;
  move_batches(): Promise<Res<MoveBatches>>;
  undo_preview(batch_id: number): Promise<Res<UndoPreview>>;
  // watched folders and the import (library stage 4)
  watched_folders(): Promise<Res<WatchedFolders>>;
  check_import_folder(path: string): Promise<Res<ImportFolderCheck>>;
  removal_preview(folder_id: number): Promise<Res<RemovalPreview>>;
  /** What Download again (`download_again`) or Remove from library (`remove`) would do for songs whose file is missing
   *  (issue 43): one item per song, `will` and the sentence; reads only. An unknown action is `bad_args` */
  missing_files_preview(track_ids: string[], action: MissingAction): Promise<Res<MissingPreview>>;
  // Favourites and crate switches: brief saves in library.db, no job and no engine lock (D15); `busy` when a running
  // job's write holds the file for too long
  set_favourites(keys: string[]): Promise<Res<FavouritesSaved>>;
  set_crate_shown(path: string, shown: boolean | null): Promise<Res<CrateSaved>>;
  /** several crates in one save (Settings' All / None): all or none; every path must be a crate of a watched folder */
  set_crates_shown(paths: string[], shown: boolean | null): Promise<Res<CratesSaved>>;
  limits(service: Service): Promise<Res<Limits>>;
  limits_what_if(service: Service, limit: number, extra_today: number): Promise<Res<WhatIf>>;
  runs(): Promise<Res<Runs>>;   run(run_id: string): Promise<Res<RunAnswer>>;
  spectrum(track_id: string, which: Which): Promise<Res<SpectrumAnswer>>;
  setup_status(): Promise<Res<SetupStatus>>;
  /** rekordbox on this Mac now; works without a music folder. The Sync page reads it when it opens and on window focus */
  rekordbox_status(): Promise<Res<RekordboxStatusAnswer>>;
  /** What Make all lossless files AIFF, a selection's Convert or the CDJ group's Convert all would do now (issue 33
   *  stage D): a read of the files' stored facts, no decoding; own files whose facts are not stored yet (at most 50) are
   *  probed in memory and never stored, as the run fills them first. `refused` for a scope that is none of the three */
  aiff_plan(scope: AiffScope): Promise<Res<AiffPlanAnswer>>;
  // read with network (refused with sync_running during any sync)
  search_candidates(track_id: string): Promise<Res<Candidates>>;
  preview(track_id: string, candidate: Candidate): Promise<Res<PreviewAnswer>>;
  add_playlist(url: string): Promise<Res<AddedPlaylist>>;
  preview_playlist_change(lines: PlaylistLine[]): Promise<Res<ChangePreview>>;
  // write jobs (outcome = JobFinished with the same job_id)
  start_sync(plan_id: string | null, selected: string[]): Promise<JobStart>;   stop(): Promise<Res<Stopped>>;
  save_playlists(lines: PlaylistLine[], loaded_version: string, files?: SaveFiles | null): Promise<JobStart>;
  tidy_up(moves: [number, string][]): Promise<JobStart>;   undo_moves(batch_id: number): Promise<JobStart>;
  add_watched_folder(path: string): Promise<JobStart>;   remove_watched_folder(folder_id: number): Promise<JobStart>;
  start_import(): Promise<JobStart>;
  answer_same_song(song_key: string, own_key: string, same: boolean): Promise<JobStart>;
  keep_duplicates(group_id: string, paths: string[]): Promise<JobStart>;
  /** "Keep this file" of a duplicate group: every other file goes to Superseded/ in one job (`paths`: the files as the card showed them) */
  keep_file(group_id: string, file_id: number, paths: string[]): Promise<JobStart>;
  save_limits(service: Service, limit: number, extra_today: number): Promise<JobStart>;
  mark_warnings_seen(service: Service): Promise<JobStart>;
  hide(track_id: string, hidden: boolean, expect?: string | null): Promise<JobStart>;
  never_download(track_id: string, never: boolean): Promise<JobStart>;
  /** `path`: an absolute path of a file Discjockey can read, the `path` of a `FileDropped` event */
  add_bought_file(track_id: string, path: string, expect?: string | null): Promise<JobStart>;
  use_candidate(track_id: string, candidate: Candidate, expect?: string | null): Promise<JobStart>;
  use_link(track_id: string, url: string, expect?: string | null): Promise<JobStart>;
  reject_current(track_id: string, expect?: string | null): Promise<JobStart>;
  /** "Done, checked in rekordbox" for tracks (a batch card sends its done tracks) */
  rekordbox_checked(track_ids: string[]): Promise<JobStart>;
  /** `expect` (hide, add_bought_file, use_candidate, use_link, reject_current, upgrade of one song): the `rev` of the
   *  row acted on; the write is refused `changed` when the song's record is not at that rev any more.
   *  Replace tracks with their better versions; one track is a list of one. `same_track` (any format) is one AIFF
   *  batch (job `upgrade_batch`); `new_track` / `discard` run the list one after the other (jobs `upgrade_add_new` /
   *  `upgrade_discard`) */
  upgrade(track_ids: string[], mode: 'same_track' | 'new_track' | 'discard', plan_id: string | null, expect?: string | null): Promise<JobStart>;
  /** Upgrade all: Same track for every parked upgrade the list counts as possible (job `upgrade_batch`) */
  upgrade_all(): Promise<JobStart>;
  /** Convert to AIFF for songs, or only the name for a clean AIFF (each file's own answer decides): one batch, job
   *  `aiff_batch`, progress BatchProgress, result `AiffBatchResult`; `origin` is the page that asked (the batch's scope
   *  says so). The songs the plan leaves out come back as `skipped` results. One id is a batch of one */
  convert(track_ids: string[], origin?: 'library' | 'todo'): Promise<JobStart>;
  /** Give it its clean name for songs (a file that needs a Convert is left as it is): as `convert`, from the Library */
  rename(track_ids: string[]): Promise<JobStart>;
  /** Make all lossless files AIFF (`lossless`) or the CDJ group's Convert all (`cdj`): plans again, one batch (job
   *  `aiff_batch`); nothing to change ends it `refused` */
  make_aiff(scope: Extract<AiffScope, { kind: 'lossless' | 'cdj' }>): Promise<JobStart>;
  /** carries on a stopped batch (job `batch_resume`) */
  batch_resume(batch_id: number): Promise<JobStart>;
  /** "Undo all": every track a batch did, newest first (job `batch_undo`) */
  batch_undo(batch_id: number): Promise<JobStart>;
  /** "Undo" on "Check in rekordbox" items with `can_undo`: puts swaps, added files and Same tracks back, newest first */
  undo_upgrade(track_ids: string[]): Promise<JobStart>;
  rescan_library(): Promise<JobStart>;
  /** Download again or Remove from library for songs whose file is missing (job `missing_files`, result `MissingResult`):
   *  each song is asked again when the job runs and a changed one is `skipped` with its reason; every song skipped ends
   *  the job `changed`. Remove is final: no undo, no music file deleted. The plan is made again, so the Sync page shows
   *  the planned download at once */
  missing_files(track_ids: string[], action: MissingAction): Promise<JobStart>;
  // other
  show_in_finder(track_id: string, which: Which): Promise<Res<Empty>>;   reveal(rel_path: string): Promise<Res<Empty>>;
  open_report(run_id: string): Promise<Res<Empty>>;   open_external(url: string): Promise<Res<Empty>>;
  app_update(): Promise<Res<AppUpdate>>;
  quit(): Promise<Res<Empty>>;
  // setup
  setup_check_tools(): Promise<Res<SetupTools>>;  setup_save_client_id(client_id: string): Promise<JobStart>;
  setup_spotify_login(): Promise<JobStart>;       setup_qobuz_login(email: string, password: string): Promise<JobStart>;
  open_licenses(): Promise<Res<Empty>>;
  update_tools(): Promise<JobStart>;
  rollback_tools(): Promise<JobStart>;
  setup_skip_qobuz(): Promise<JobStart>;
  setup_skip_spotify(): Promise<JobStart>;
  set_read_liked_music(on: boolean): Promise<JobStart>;
  /** "Upgrade automatically when I sync" (job `set_auto_upgrade`); on by default */
  set_auto_upgrade(on: boolean): Promise<JobStart>;
  add_liked_music(): Promise<JobStart>;
  /** The Sync scope (settings.json `sync_scope`): the playlists and folders left out and the weekly kinds switched off.
   *  Works without a music folder */
  sync_scope(): Promise<Res<SyncScope>>;
  /** Switches collections (`playlist:<ref>` / `folder:<path>`) and weekly kinds (`kind:retry` / `kind:weekly`) out of
   *  the sync (`off`) or back in (`on`): a settings job (`set_sync_scope`, result: the scope as saved). The last write
   *  wins; an item that is none of those, or in both lists, is `refused` before a job starts */
  set_sync_scope(on: string[], off: string[]): Promise<JobStart>;
  setup_skip_import(): Promise<Res<Empty>>;
  setup_account(service: 'youtube' | 'soundcloud', browser: Browser, profile?: string | null): Promise<JobStart>;
  downloads_view(): Promise<Res<DownloadsViewAnswer>>;
  find_logins(service: 'youtube' | 'soundcloud'): Promise<Res<FindLogins>>;
  account_sign_in(service: 'youtube' | 'soundcloud', browser: Browser, profile?: string | null): Promise<JobStart>;
  stop_sign_in(): Promise<Res<Stopped>>;
  open_privacy_settings(): Promise<Res<Empty>>;
  qobuz_check_login(): Promise<JobStart>;
  spotify_sign_out(): Promise<JobStart>;
  // the music folder
  pick_folder(start?: string | null): Promise<Res<{ path: string | null }>>;
  check_music_folder(path: string): Promise<Res<FolderCheck>>;
  set_music_folder(path: string): Promise<Res<MusicFolderSet>>;
  retry_music_folder(): Promise<Res<MusicFolderAnswer>>;
  setup_forget_account(service: 'youtube' | 'soundcloud'): Promise<JobStart>;
}

declare global {
  interface Window { pywebview?: { api?: Partial<Record<string, (...args: unknown[]) => Promise<unknown>>> } }
}

const CRASHED: Fail = { ok: false, kind: 'crashed', message: CRASHED_MESSAGE };

let ready: Promise<void> | null = null;
/** Resolves when window.pywebview.api exists (pywebview injects it after load and fires 'pywebviewready'). */
export function bridgeReady(): Promise<void> {
  if (ready) return ready;
  ready = new Promise<void>((resolve) => {
    if (typeof window === 'undefined') return;
    if (window.pywebview?.api) return resolve();
    const done = () => {
      if (!window.pywebview?.api) return;
      window.removeEventListener('pywebviewready', done);
      clearInterval(poll);
      resolve();
    };
    window.addEventListener('pywebviewready', done);
    const poll = setInterval(done, 100); // safety net if the event fired before this listener
  });
  return ready;
}

const noLibraryHandlers = new Set<() => void>();
/** Runs `fn` whenever any bridge call answers `no_library` (the music folder is not there). The shell's hub store uses
 *  it to read the setup state again, so the missing-folder screen appears whatever page asked. Returns the remover. */
export function onNoLibrary(fn: () => void): () => void {
  noLibraryHandlers.add(fn);
  return () => { noLibraryHandlers.delete(fn); };
}

function devWarn(...args: unknown[]): void {
  if (import.meta.env.DEV || import.meta.env.VITE_FAKE === '1') console.warn(...args);
}

async function call(method: string, args: unknown[]): Promise<unknown> {
  await bridgeReady();
  const fn = window.pywebview?.api?.[method];
  if (typeof fn !== 'function') {
    devWarn(`bridge method missing: ${method}`);
    return CRASHED;
  }
  try {
    const r = await fn(...args);
    if (!r || typeof r !== 'object' || typeof (r as { ok?: unknown }).ok !== 'boolean') {
      devWarn(`bridge ${method}: unexpected answer`);
      return CRASHED;
    }
    const f = r as { ok: boolean; kind?: unknown };
    if (!f.ok && f.kind === 'no_library') noLibraryHandlers.forEach((fn) => fn());
    return r;
  } catch (err) {
    devWarn(`bridge ${method} failed`, err);
    return CRASHED;
  }
}

export const api = Object.fromEntries(
  CONTRACT_METHODS.map((m) => [m, (...args: unknown[]) => call(m, args)]),
) as unknown as Bridge;

/** rekordbox on this Mac now, or null when the bridge could not say (the Sync page's before-start Hint then stays out). */
export async function rekordboxStatus(): Promise<RekordboxStatus | null> {
  const r = await api.rekordbox_status();
  return r.ok ? { state: r.state, running: r.running } : null;
}

/** Fake mode: installs an object as window.pywebview.api and fires 'pywebviewready' (as pywebview does). */
export function installBridge(impl: object): void {
  window.pywebview = { api: impl as never };
  window.dispatchEvent(new Event('pywebviewready'));
}

/** Tests only: forget a resolved bridgeReady (a new fake window). */
export function _resetBridge(): void {
  ready = null;
}

export type JobOutcome<R> =
  /** `message`: the engine's own line for a job that ends well (a duplicate's "Moved 2 files to Superseded/."), "" for most */
  | { ok: true; job_id: string; result: R; message?: string }
  /** `result`: what a job that ended with a problem still carries (a stopped move batch: the moves it made), else null */
  | { ok: false; job_id: string | null; kind: ProblemKind; message: string; result?: R | null };

function problemToast(kind: ProblemKind, message: string): void {
  toasts.show({ tone: 'problem', title: problemCopy(kind).title, body: message || undefined });
}

/**
 * Starts a write job and waits for its JobFinished. An immediate refusal resolves at once with job_id null.
 * Shows a problem toast unless `quiet`, a success toast for the job kind unless `success === false`
 * (a string replaces the default), and the `recovered` lines of an OpResult as an info toast.
 */
export async function runJob<R = unknown>(start: Promise<JobStart>,
  opts: { quiet?: boolean; success?: string | false } = {}): Promise<JobOutcome<R>> {
  let started: JobStart;
  try {
    started = await start;
  } catch {
    started = CRASHED;
  }
  if (!started || started.ok !== true) {
    const f = (started as Fail) ?? CRASHED;
    if (!opts.quiet) problemToast(f.kind, f.message);
    return { ok: false, job_id: null, kind: f.kind, message: f.message };
  }
  const job_id = started.job_id;
  const fin = await waitForJob(job_id);
  const recovered = (fin.result as OpResult | null)?.recovered;
  if (Array.isArray(recovered) && recovered.length) {
    toasts.show({ tone: 'info', title: RECOVERED_TITLE, body: recovered.map((r) => r[0]).join(' · ') });
  }
  if (!fin.ok) {
    const kind = (fin.problem ?? 'crashed') as ProblemKind;
    if (!opts.quiet) problemToast(kind, fin.message);
    return { ok: false, job_id, kind, message: fin.message, result: (fin.result ?? null) as R | null };
  }
  if (opts.success !== false) {
    const text = typeof opts.success === 'string' ? opts.success : successCopy(fin.kind);
    if (text) toasts.show({ tone: 'success', title: text });
  }
  return { ok: true, job_id, result: fin.result as R, message: fin.message };
}
