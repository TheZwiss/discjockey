// All shared copy in one place: plain English, short, sentence case, "you" voice (plan Part C "Copy").
import type { EmptyKind, PlanCounts, ProblemKind } from './bridge/types';

export type CopyAction = { label: string; href?: string; retry?: boolean; report?: boolean };
export type ProblemCopy = { title: string; hint?: string; action?: CopyAction };

/** Problem kind → headline (+ hint, + action). The backend's `message` is always shown as the detail line. */
export const PROBLEMS: Record<ProblemKind, ProblemCopy> = {
  busy: { title: 'Wait until the current change is finished.' },
  console: { title: 'A sync is running in the terminal.' },
  sync_running: { title: "Not while a sync runs. Try again when it's finished." },
  not_set_up: { title: "Discjockey isn't set up yet.", action: { label: 'Open setup →', href: '#/setup' } },
  login_expired: { title: 'Your Spotify login has expired.',
    action: { label: 'Connect Spotify →', href: '#/settings/spotify' } },
  offline: { title: "No internet connection. Try again when you're online.", action: { label: 'Retry', retry: true } },
  playlist_unreadable: { title: "A playlist can't be read.", hint: 'Follow ≠ own: make your own copy in Spotify.',
    action: { label: 'Open Playlists', href: '#/playlists' } },
  config_invalid: { title: 'Something in your settings needs fixing.' },
  qobuz_login_failed: { title: "Qobuz didn't accept the login.",
    action: { label: 'Open Qobuz in Settings →', href: '#/settings/qobuz' } },
  login_failed: { title: "The Spotify login didn't work." },
  changed: { title: 'This track changed in the meantime.' },
  refused: { title: "That isn't possible." },
  failed: { title: "That didn't work." },
  protected: { title: 'This version is DRM-protected.' },
  stopped: { title: 'Stopped. Nothing was left half done.' },
  no_library: { title: 'Choose your music folder first.', action: { label: 'Open setup →', href: '#/setup/music' } },
  crashed: { title: 'Something went wrong', action: { label: 'Open report', report: true } },
};
export const SYNC_CRASHED = 'The sync stopped unexpectedly';
export const CRASHED_MESSAGE = 'Something went wrong. Try again.';
export const NOT_WHILE_SYNC = "Not while a sync runs. Try again when it's finished.";

/** Spotify can't be read because its login is missing (`not_set_up` with `spotify`; the engine's not_set_up also
 *  covers a missing playlists.txt, hence the flag). Same link as the expired login: one state, one wording, one link
 *  on every page (spec §11). */
export const SPOTIFY_NOT_CONNECTED: ProblemCopy = { title: "Spotify isn't connected.",
  action: { label: 'Connect Spotify →', href: '#/settings/spotify' } };

export function problemCopy(kind: ProblemKind | string, opts: { sync?: boolean; spotify?: boolean } = {}): ProblemCopy {
  if (kind === 'not_set_up' && opts.spotify) return SPOTIFY_NOT_CONNECTED;
  const c = PROBLEMS[kind as ProblemKind] ?? PROBLEMS.crashed;
  if (kind === 'crashed' && opts.sync) return { ...c, title: SYNC_CRASHED };
  return c;
}

/** Job kind → success toast. Setup kinds have none (the wizard shows its own). */
export const SUCCESS: Record<string, string> = {
  hide: 'Hidden from the to-do list.',
  unhide: 'Back on the to-do list.',
  add_bought_file: 'Bought file added.',
  use_candidate: 'New version placed. The old file is in Superseded.',
  use_link: 'New version placed. The old file is in Superseded.',
  reject_current: 'Moved to Superseded. The next sync searches again.',
  rekordbox_checked: 'Marked as checked in rekordbox.',
  upgrade_swap: 'Swapped. rekordbox keeps the cue points.',
  upgrade_add_new: 'Added as a new file.',
  upgrade_discard: 'Upgrade discarded.',
  save_playlists: 'Playlists saved. Changes happen at the next sync.',
  save_limits: 'Daily limit saved.',
  setup_skip_qobuz: 'Qobuz left out.',
  setup_forget_account: 'Login forgotten.',
  setup_account: '',  // the setup step shows the check's own message
};
export function successCopy(jobKind: string): string | null {
  return SUCCESS[jobKind] ?? null;
}
export const RECOVERED_TITLE = 'First finished an interrupted step:';

/** EmptyKind → default copy for EmptyState. */
export const EMPTY: Record<EmptyKind, { title: string; body?: string; action?: CopyAction }> = {
  no_playlists: { title: 'No playlists yet.', action: { label: 'Add a playlist →', href: '#/playlists' } },
  not_set_up: { title: "Discjockey isn't set up yet.", action: { label: 'Finish setup →', href: '#/setup' } },
  empty_library: { title: 'No tracks yet. Run a sync to fill your library.' },
  // Spotify's state and Read Spotify live in the header slot right above (spec §5a/§11): say what's missing here, point up
  no_preview: { title: 'Nothing to review yet.', body: 'Read Spotify above to see what changed in your playlists.' },
  up_to_date: { title: 'Everything is up to date.' },
  no_match: { title: 'Nothing matches.' },
  all_lossless: { title: 'Everything is lossless.' },
  all_hidden: { title: 'Only hidden tracks are left.' },
  nothing_here: { title: 'Nothing here.' },
};

export const WRITE_BLOCKED = {
  busy: 'Wait until the current change is finished.',
  console: 'A sync is running in the terminal.',
} as const;

export const BANNER = {
  console: "A sync is running in the terminal. You can look around; changes wait until it's finished.",
} as const;

export const DROP_BLOCKED = "macOS didn't let Discjockey read this file. Move it to Downloads, or allow access in "
  + 'System Settings → Privacy & Security → Files and Folders.';

export const STEP_LABEL: Record<string, string> = {
  search: 'Searching', download: 'Downloading', check: 'Checking', convert: 'Converting', analyse: 'Analysing',
  compare: 'Comparing',
};

/** The same plan counts on the Dashboard and in Sync's before-start counters: [key, one, many]. */
export const PLAN_COUNT_WORDS: [keyof PlanCounts, string, string][] = [
  ['new', 'new', 'new'], ['retries', 'retry', 'retries'], ['redownloads', 'download again', 'downloads again'],
  ['moves', 'move', 'moves'], ['adopts', 'found file', 'found files'], ['bought', 'bought file', 'bought files'],
  ['weekly_checks', 'weekly check', 'weekly checks'],
];

/** The backend message as the detail line under a problem headline, without a repeat of the headline
 *  ("Your Spotify login has expired." twice → nothing; "Something went wrong. Try again." → "Try again."). */
export function detailLine(message: string | null | undefined, title: string): string {
  const m = (message ?? '').trim();
  const t = title.trim().replace(/[.…]+$/, '');
  if (!m || !t) return m;
  if (m.toLowerCase().startsWith(t.toLowerCase())) return m.slice(t.length).replace(/^[.…:;,\s–-]+/, '').trim();
  return m;
}
