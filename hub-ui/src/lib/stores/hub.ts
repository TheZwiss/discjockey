// Shared hub state (plan 64.5). Pages only read these stores.
import { derived, get, writable, type Readable } from 'svelte/store';
import { onEvent } from '../bridge/events';
import { api, onNoLibrary } from '../bridge/client';
import type { AppUpdate, CrateSaved, FavouritesSaved, JobSnap, PlaylistService, SetupStatus, Sidebar, ReadStatus, Res } from '../bridge/types';
import { WRITE_BLOCKED } from '../copy';

export type HubState = {
  booted: boolean; fake: boolean;
  job: JobSnap | null;            // current/last write job (from job_status, JobStarted, JobFinished)
  /** a sign-in waiting for the browser: its own slot beside the write jobs, so it never blocks a write (plan R3) */
  sign_in: JobSnap | null;
  refresh_running: boolean; console_running: boolean;
  read_status: ReadStatus | null;  setup: SetupStatus | null;  sidebar: Sidebar | null;
  /** while Spotify is read (a refresh or a sync's start): which playlist, from ReadingPlaylist */
  read_progress: ReadProgress | null;
  /** the last playlist read was stopped (until the next one starts): ReadStatus says so */
  read_stopped: boolean;
  /** the update check's last answer (app_update / AppUpdate; spec public-release §8) */
  app_update: AppUpdate | null;
  /** counts the AppUpdate events reduced so far, so refreshHub can tell an answer that an event has overtaken */
  app_update_seq: number;
};
export type ReadProgress = { index: number; total: number; folder: string };
export const EMPTY_HUB: HubState = { booted: false, fake: false, job: null, sign_in: null, refresh_running: false,
  console_running: false, read_status: null, setup: null, sidebar: null, read_progress: null, read_stopped: false, app_update: null,
  app_update_seq: 0 };

const state = writable<HubState>({ ...EMPTY_HUB });
const version = writable(0);
const drives = writable(0);

export const hub: Readable<HubState> = { subscribe: state.subscribe };
export const writeBusy = derived(state, (s) => !!s.job?.running || s.console_running);
export const syncRunning = derived(state, (s) => (s.job?.kind === 'sync' && !!s.job.running) || s.console_running);
export const hubSyncRunning = derived(state, (s) => s.job?.kind === 'sync' && !!s.job.running);
export const networkReadsAllowed = derived(syncRunning, (r) => !r);
export const writeBlockedReason = derived(state, (s): string | null =>
  s.job?.running ? WRITE_BLOCKED.busy : s.console_running ? WRITE_BLOCKED.console : null);
/** Why the playlists can't be read until the user logs in (again), and to which service: a service playlists.txt
 *  uses isn't connected, or a read found its login missing or expired. Only the services playlists.txt uses count
 *  (`services`): a Spotify left out in Setup is no problem until a Spotify line is there (plan stage 3, D1). The
 *  shell's banner says it (with its Connect link) and the header slot turns Read playlists off, so the state is said
 *  once (design system §5a/§11). Offline is not a block: a read fixes it. */
export type ReadBlock = { kind: 'login_expired' | 'not_set_up'; service: PlaylistService };
export function readBlockIn(sp: ReadStatus | null): ReadBlock | null {
  if (!sp) return null;
  if (sp.problem === 'login_expired') return { kind: 'login_expired', service: sp.problem_service ?? 'spotify' };
  const off = sp.services?.find((x) => !x.connected);
  if (off) return { kind: 'not_set_up', service: off.service };
  // a read that found a login missing (the poll's `services` may not show it yet); without a service the engine's
  // not_set_up is a missing playlists.txt, which no login fixes. Once `services` lists that service as connected the
  // user has logged in since: the stored problem is stale and must not block the next read (a login_expired can't be
  // judged here, a connected account may still hold an expired login, so that branch stays above)
  if (sp.problem === 'not_set_up' && sp.problem_service
      && !sp.services?.some((x) => x.service === sp.problem_service && x.connected)) {
    return { kind: 'not_set_up', service: sp.problem_service };
  }
  return null;
}
/** The engine's not_set_up without a service: playlists.txt is missing, so setup isn't finished. No login fixes it and
 *  the first-run page and the setup flow say it, so the header slot neither repeats it as a problem card nor lets
 *  Read playlists run (it would find nothing). A login block takes precedence (`readBlockIn` names it). The stored
 *  problem only clears after a successful read, so the live setup state decides too: once playlists.txt exists
 *  (`setup.playlists`) the problem is stale and Read must stay enabled so a read can clear it. Setup not known yet
 *  keeps the block. */
export function readNeedsSetupIn(sp: ReadStatus | null, setup: SetupStatus | null): boolean {
  return !!sp && sp.problem === 'not_set_up' && !sp.problem_service && readBlockIn(sp) === null
    && setup?.playlists !== true;
}
/** The one source for the banner, the header slot and Sync's card (spec §5a/§11). */
export const readBlock = derived(state, (s) => readBlockIn(s.read_status));
export const readBlocked = derived(readBlock, (b) => b !== null);
/** +1 on every JobFinished (any kind), ConsoleBusy {running:false} and a finished refresh. Pages re-fetch on change. */
export const dataVersion: Readable<number> = { subscribe: version.subscribe };
/** dataVersion plus 1 on every DrivesChanged (a drive plugged in or ejected, a watched folder gone or back while the
 *  window is open). What shows a file's or a watched folder's state re-reads on it: the Library list and its panel,
 *  To-do, the watched folders (Settings, Setup). A plain bump of dataVersion would also re-read pages a drive can't
 *  change (Sync's plan, Playlists). */
export const filesVersion: Readable<number> = derived([version, drives], ([v, d]) => v + d);

/** The job kind of a sign-in (engine `Jobs.start_sign_in`). */
const SIGN_IN_KIND = 'account_sign_in';
/** The job kind of the music-folder check (`rescan_library`): only its finish matters, as a data bump (see below). */
const SCAN_KIND = 'scan';

/** Applies an event to the shared state (exported for tests). */
export function reduceHub(s: HubState, e: Parameters<Parameters<typeof onEvent>[0]>[0]): HubState {
  switch (e.type) {
    case 'ReadingPlaylist':
      return { ...s, read_progress: { index: e.index, total: e.total, folder: e.folder } };
    case 'JobStarted':
      if (e.kind === 'refresh') {
        return { ...s, refresh_running: true, read_progress: null, read_stopped: false,
          read_status: s.read_status ? { ...s.read_status, reading: true } : s.read_status };
      }
      {
        const snap: JobSnap = { id: e.job_id, kind: e.kind, track_id: e.track_id, started: new Date().toISOString(),
          running: true, stopping: false, last: {}, results: [], finished: null, actions: [] };
        if (e.kind === SIGN_IN_KIND) return { ...s, sign_in: snap };
        if (e.kind === SCAN_KIND) return s;   // the quiet background check is no activity: it never takes the job slot
        return { ...s, read_progress: e.kind === 'sync' ? null : s.read_progress, job: snap };
      }
    case 'JobFinished':
      if (e.kind === 'refresh') {
        return { ...s, refresh_running: false, read_progress: null, read_stopped: e.problem === 'stopped',
          read_status: s.read_status ? { ...s.read_status, reading: false } : s.read_status };
      }
      if (e.kind === SIGN_IN_KIND) {
        return s.sign_in?.id === e.job_id ? { ...s, sign_in: { ...s.sign_in, running: false, finished: e } } : s;
      }
      if (s.job && s.job.id === e.job_id) {
        return { ...s, read_progress: e.kind === 'sync' ? null : s.read_progress,
          job: { ...s.job, running: false, stopping: false, finished: e } };
      }
      return s;
    case 'ImportProgress':
      // the running import's live counts (Settings' row and the import card read `job.last.ImportProgress`, as
      // job_status' snapshot carries it after a reload)
      return s.job?.running && s.job.kind === 'import'
        ? { ...s, job: { ...s.job, last: { ...s.job.last, ImportProgress: e } } } : s;
    case 'RunStarted':
      return s.job?.running ? { ...s, read_progress: null, job: { ...s.job, actions: e.actions ?? [] } } : s;
    case 'ConsoleBusy':
      return { ...s, console_running: e.running };
    case 'AppUpdate':
      return { ...s, app_update: { state: e.state, current: e.current, latest: e.latest, url: e.url },
        app_update_seq: s.app_update_seq + 1 };
    default:
      return s;
  }
}

// The sidebar is read again (refreshHub) after every JobFinished (a refresh, a sync and an import change what it
// counts and lists, so do a tidy-up or a folder change), after ConsoleBusy {running: false} and after DrivesChanged
// (a folder's state: here, offline, not found). No event was added for the sidebar (plan library stage 5, B2.4).
onEvent((e) => {
  state.update((s) => reduceHub(s, e));
  if (e.type === 'JobFinished' || (e.type === 'ConsoleBusy' && !e.running)) {
    version.update((v) => v + 1);
    void refreshHub();
  } else if (e.type === 'DrivesChanged') {
    drives.update((v) => v + 1);
    void refreshHub();  // the sidebar's To-do count leaves out a duplicate whose file just went away
  }
});

let inflight: Promise<void> | null = null;
let again = false;

/** `no_library` from any call means the music folder is gone (or not chosen). The shell's gate reads it from
 *  setup_status, so read it again here, once for every page. Not while a refresh runs (its own sidebar call answers
 *  no_library too) and not once the gate already knows. */
export function refreshOnNoLibrary(): void {
  if (inflight) return;
  const music = get(state).setup?.music?.state;
  if (music && music !== 'ok') return;
  void refreshHub();
}
onNoLibrary(refreshOnNoLibrary);
/** job_status + setup_status + sidebar + app_update. Calls made while one runs are merged into one more. */
export function refreshHub(): Promise<void> {
  if (inflight) { again = true; return inflight; }
  inflight = (async () => {
    do {
      again = false;
      const updateSeq = get(state).app_update_seq;  // an event during the calls beats app_update()'s older answer
      const [js, setup, side, upd] = await Promise.all([api.job_status(), api.setup_status(), api.sidebar(), api.app_update()]);
      state.update((s) => ({
        ...s,
        ...(js.ok ? { job: (js.job && js.job.kind !== SCAN_KIND ? js.job : null) ?? (s.job && !s.job.running ? s.job : null), refresh_running: js.refresh_running,
          console_running: js.console_running, read_status: js.read_status,
          sign_in: js.sign_in ?? (s.sign_in && !s.sign_in.running ? s.sign_in : null) } : {}),
        setup: setup.ok ? stripOk(setup) : s.setup,
        sidebar: side.ok ? stripOk(side) : s.sidebar,
        app_update: upd.ok && s.app_update_seq === updateSeq ? stripOk(upd) : s.app_update,
      }));
    } while (again);
  })().finally(() => { inflight = null; });
  return inflight;
}
function stripOk<T extends { ok: true }>(r: T): Omit<T, 'ok'> {
  const { ok: _ok, ...rest } = r;
  return rest;
}

/** Saves the Favourites (the stored order of `keys`) and reads the sidebar again. A brief save, not a job (D15): the
 *  answer is `{favourites}` or `busy` when a running job's write held the file too long. The sidebar is read after a
 *  refusal too, so the list the page showed while saving is put back by what is stored. */
export async function saveFavourites(keys: string[]): Promise<Res<FavouritesSaved>> {
  const r = await api.set_favourites(keys);
  await refreshHub();
  return r;
}
/** Shows (true), hides (false) or resets (null: the default) a crate in the sidebar, then reads the sidebar again,
 *  as `saveFavourites` does. */
export async function saveCrateShown(path: string, shown: boolean | null): Promise<Res<CrateSaved>> {
  const r = await api.set_crate_shown(path, shown);
  await refreshHub();
  return r;
}

/** Boot (main.ts). */
export function markBooted(fake: boolean): void {
  state.update((s) => ({ ...s, booted: true, fake }));
}
/** Pages that changed Spotify's state through their own call (e.g. ReadStatus Stop) can poke the hub. */
export function bumpData(): void {
  version.update((v) => v + 1);
  void refreshHub();
}
export function hubNow(): HubState {
  return get(state);
}
