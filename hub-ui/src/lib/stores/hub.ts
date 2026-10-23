// Shared hub state (plan 64.5). Pages only read these stores.
import { derived, get, writable, type Readable } from 'svelte/store';
import { onEvent } from '../bridge/events';
import { api, onNoLibrary } from '../bridge/client';
import type { AppUpdate, JobSnap, SetupStatus, Sidebar, SpotifyStatus } from '../bridge/types';
import { WRITE_BLOCKED } from '../copy';

export type HubState = {
  booted: boolean; fake: boolean;
  job: JobSnap | null;            // current/last write job (from job_status, JobStarted, JobFinished)
  /** a sign-in waiting for the browser: its own slot beside the write jobs, so it never blocks a write (plan R3) */
  sign_in: JobSnap | null;
  refresh_running: boolean; console_running: boolean;
  spotify: SpotifyStatus | null;  setup: SetupStatus | null;  sidebar: Sidebar | null;
  /** while Spotify is read (a refresh or a sync's start): which playlist, from ReadingPlaylist */
  read_progress: ReadProgress | null;
  /** the last Spotify read was stopped (until the next one starts): SpotifyStatus says so */
  read_stopped: boolean;
  /** the update check's last answer (app_update / AppUpdate; spec public-release §8) */
  app_update: AppUpdate | null;
  /** counts the AppUpdate events reduced so far, so refreshHub can tell an answer that an event has overtaken */
  app_update_seq: number;
};
export type ReadProgress = { index: number; total: number; folder: string };
export const EMPTY_HUB: HubState = { booted: false, fake: false, job: null, sign_in: null, refresh_running: false,
  console_running: false, spotify: null, setup: null, sidebar: null, read_progress: null, read_stopped: false, app_update: null,
  app_update_seq: 0 };

const state = writable<HubState>({ ...EMPTY_HUB });
const version = writable(0);

export const hub: Readable<HubState> = { subscribe: state.subscribe };
export const writeBusy = derived(state, (s) => !!s.job?.running || s.console_running);
export const syncRunning = derived(state, (s) => (s.job?.kind === 'sync' && !!s.job.running) || s.console_running);
export const hubSyncRunning = derived(state, (s) => s.job?.kind === 'sync' && !!s.job.running);
export const networkReadsAllowed = derived(syncRunning, (r) => !r);
export const writeBlockedReason = derived(state, (s): string | null =>
  s.job?.running ? WRITE_BLOCKED.busy : s.console_running ? WRITE_BLOCKED.console : null);
/** Spotify can't be read until the user logs in (again): no login, not set up, or the login expired. The shell's
 *  banner says it (with its Set up link) and the header slot disables Read Spotify, so the state is said once
 *  (design system §5a/§11). Offline is not "missing": a read fixes it. */
export function spotifyMissingIn(setup: SetupStatus | null, spotify: SpotifyStatus | null): boolean {
  return spotifyMissingKindIn(setup, spotify) !== null;
}
/** Which one, for the words: the expired login, else "not set up" (no login, or a read that found none). */
export function spotifyMissingKindIn(setup: SetupStatus | null, spotify: SpotifyStatus | null):
  'login_expired' | 'not_set_up' | null {
  if (spotify?.problem === 'login_expired') return 'login_expired';
  return setup?.spotify_login === false || spotify?.problem === 'not_set_up' ? 'not_set_up' : null;
}
export const spotifyMissing = derived(state, (s) => spotifyMissingIn(s.setup, s.spotify));
/** The one source for the banner, the header slot and Sync's card (spec §5a/§11). */
export const spotifyMissingKind = derived(state, (s) => spotifyMissingKindIn(s.setup, s.spotify));
/** +1 on every JobFinished (any kind), ConsoleBusy {running:false} and a finished refresh. Pages re-fetch on change. */
export const dataVersion: Readable<number> = { subscribe: version.subscribe };

/** The job kind of a sign-in (engine `Jobs.start_sign_in`). */
const SIGN_IN_KIND = 'account_sign_in';

/** Applies an event to the shared state (exported for tests). */
export function reduceHub(s: HubState, e: Parameters<Parameters<typeof onEvent>[0]>[0]): HubState {
  switch (e.type) {
    case 'ReadingPlaylist':
      return { ...s, read_progress: { index: e.index, total: e.total, folder: e.folder } };
    case 'JobStarted':
      if (e.kind === 'refresh') {
        return { ...s, refresh_running: true, read_progress: null, read_stopped: false,
          spotify: s.spotify ? { ...s.spotify, reading: true } : s.spotify };
      }
      {
        const snap: JobSnap = { id: e.job_id, kind: e.kind, track_id: e.track_id, started: new Date().toISOString(),
          running: true, stopping: false, last: {}, results: [], finished: null, actions: [] };
        if (e.kind === SIGN_IN_KIND) return { ...s, sign_in: snap };
        return { ...s, read_progress: e.kind === 'sync' ? null : s.read_progress, job: snap };
      }
    case 'JobFinished':
      if (e.kind === 'refresh') {
        return { ...s, refresh_running: false, read_progress: null, read_stopped: e.problem === 'stopped',
          spotify: s.spotify ? { ...s.spotify, reading: false } : s.spotify };
      }
      if (e.kind === SIGN_IN_KIND) {
        return s.sign_in?.id === e.job_id ? { ...s, sign_in: { ...s.sign_in, running: false, finished: e } } : s;
      }
      if (s.job && s.job.id === e.job_id) {
        return { ...s, read_progress: null, job: { ...s.job, running: false, stopping: false, finished: e } };
      }
      return s;
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

onEvent((e) => {
  state.update((s) => reduceHub(s, e));
  if (e.type === 'JobFinished' || (e.type === 'ConsoleBusy' && !e.running)) {
    version.update((v) => v + 1);
    void refreshHub();
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
        ...(js.ok ? { job: js.job ?? (s.job && !s.job.running ? s.job : null), refresh_running: js.refresh_running,
          console_running: js.console_running, spotify: js.spotify,
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

/** Boot (main.ts). */
export function markBooted(fake: boolean): void {
  state.update((s) => ({ ...s, booted: true, fake }));
}
/** Pages that changed Spotify's state through their own call (e.g. SpotifyStatus Stop) can poke the hub. */
export function bumpData(): void {
  version.update((v) => v + 1);
  void refreshHub();
}
export function hubNow(): HubState {
  return get(state);
}
