// The only bridge to Python. Only this file touches window.pywebview (plan 64.4).
import type {
  ActionKey, AddedPlaylist, AppUpdate, Candidate, Candidates, ChangePreview, Dashboard, Fail, JobStart, JobStatus, Library,
  Limits, LibraryFilter, MoveBatches, SaveFiles, TidyPreview, UndoPreview, LibrarySort, PlaylistLine, Playlists, ProblemKind, QobuzUsage, Res, RunDetail,
  RunSummary, SetupStatus, SetupTools, Sidebar, Spectrum, SyncPreview, Todo, TodoFilter, TrackDetail, WhatIf, Which,
  AccountCheck, Browser, DownloadsView, FindLogins, OpResult, Service, FolderCheck, MusicStatus,
} from './types';
import { CONTRACT_METHODS } from './contract';
import { waitForJob } from '../stores/jobs';
import { toasts } from '../stores/toasts';
import { CRASHED_MESSAGE, RECOVERED_TITLE, problemCopy, successCopy } from '../copy';

export interface Bridge {
  // read, any time
  dashboard(): Promise<Res<Dashboard>>;           sidebar(): Promise<Res<Sidebar>>;
  sync_preview(): Promise<Res<SyncPreview>>;      refresh(auto?: boolean): Promise<JobStart>;
  stop_refresh(): Promise<Res<{ stopped: boolean }>>;   job_status(): Promise<Res<JobStatus>>;
  library(folder: string | null, query: string, filter: LibraryFilter, sort: LibrarySort): Promise<Res<Library>>;
  track(track_id: string): Promise<Res<{ track: TrackDetail }>>;
  todo(filter: TodoFilter, show_hidden: boolean): Promise<Res<Todo>>;
  playlists(): Promise<Res<Playlists>>;
  tidy_preview(): Promise<Res<TidyPreview>>;
  move_batches(): Promise<Res<MoveBatches>>;
  undo_preview(batch_id: number): Promise<Res<UndoPreview>>;
  limits(service: Service): Promise<Res<Limits>>;
  limits_what_if(service: Service, limit: number, extra_today: number): Promise<Res<WhatIf>>;
  runs(): Promise<Res<{ runs: RunSummary[] }>>;   run(run_id: string): Promise<Res<{ run: RunDetail }>>;
  spectrum(track_id: string, which: Which): Promise<Res<{ spectrum: Spectrum }>>;
  media_url(track_id: string, which: Which): Promise<Res<{ url: string }>>;
  setup_status(): Promise<Res<SetupStatus>>;      select(track_id: string | null): Promise<Res<{}>>;
  // read with network (refused with sync_running during any sync)
  search_candidates(track_id: string): Promise<Res<Candidates>>;
  preview(track_id: string, candidate: Candidate): Promise<Res<{ url: string }>>;
  add_playlist(url: string): Promise<Res<AddedPlaylist>>;
  preview_playlist_change(lines: PlaylistLine[]): Promise<Res<ChangePreview>>;
  // write jobs (outcome = JobFinished with the same job_id)
  start_sync(selected: ActionKey[]): Promise<JobStart>;   stop(): Promise<Res<{ stopped: boolean }>>;
  save_playlists(lines: PlaylistLine[], loaded_version: string, files?: SaveFiles | null): Promise<JobStart>;
  tidy_up(moves: [number, string][]): Promise<JobStart>;   undo_moves(batch_id: number): Promise<JobStart>;
  save_limits(service: Service, limit: number, extra_today: number): Promise<JobStart>;
  mark_warnings_seen(service: Service): Promise<JobStart>;
  hide(track_id: string, hidden: boolean): Promise<JobStart>;
  never_download(track_id: string, never: boolean): Promise<JobStart>;
  add_bought_file(track_id: string): Promise<JobStart>;
  use_candidate(track_id: string, candidate: Candidate): Promise<JobStart>;
  use_link(track_id: string, url: string): Promise<JobStart>;
  reject_current(track_id: string): Promise<JobStart>;
  rekordbox_checked(track_id: string): Promise<JobStart>;
  upgrade(track_id: string, mode: 'swap' | 'add_new' | 'discard'): Promise<JobStart>;
  rescan_library(): Promise<JobStart>;
  // other
  show_in_finder(track_id: string, which: Which): Promise<Res<{}>>;   reveal(rel_path: string): Promise<Res<{}>>;
  open_report(run_id: string): Promise<Res<{}>>;   open_external(url: string): Promise<Res<{}>>;
  app_update(): Promise<Res<AppUpdate>>;
  quit(): Promise<Res<{}>>;
  // setup
  setup_check_tools(): Promise<Res<SetupTools>>;  setup_save_client_id(client_id: string): Promise<JobStart>;
  setup_spotify_login(): Promise<JobStart>;       setup_qobuz_login(email: string, password: string): Promise<JobStart>;
  open_licenses(): Promise<Res<{}>>;
  update_tools(): Promise<JobStart>;
  rollback_tools(): Promise<JobStart>;
  setup_skip_qobuz(): Promise<JobStart>;
  setup_account(service: 'youtube' | 'soundcloud', browser: Browser, profile?: string | null): Promise<JobStart>;
  setup_check_account(service: 'youtube' | 'soundcloud'): Promise<Res<{ service: Service; check: AccountCheck }>>;
  downloads_view(): Promise<Res<{ downloads: DownloadsView }>>;
  find_logins(service: 'youtube' | 'soundcloud'): Promise<Res<FindLogins>>;
  account_sign_in(service: 'youtube' | 'soundcloud', browser: Browser, profile?: string | null): Promise<JobStart>;
  stop_sign_in(): Promise<Res<{ stopped: boolean }>>;
  open_privacy_settings(): Promise<Res<{}>>;
  qobuz_check_login(): Promise<JobStart>;
  spotify_sign_out(): Promise<JobStart>;
  // the music folder
  pick_folder(start?: string | null): Promise<Res<{ path: string | null }>>;
  check_music_folder(path: string): Promise<Res<FolderCheck>>;
  set_music_folder(path: string): Promise<Res<{ music: MusicStatus; restart: boolean }>>;
  retry_music_folder(): Promise<Res<{ music: MusicStatus }>>;
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
  | { ok: true; job_id: number; result: R }
  /** `result`: what a job that ended with a problem still carries (a stopped move batch: the moves it made), else null */
  | { ok: false; job_id: number | null; kind: ProblemKind; message: string; result?: R | null };

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
  return { ok: true, job_id, result: fin.result as R };
}
