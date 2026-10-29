// Setup, the first-run guide (spec settings-setup §8). Pure helpers; nothing here talks to the backend on its own.
// Credentials (the Spotify Client ID, the Qobuz password) are never kept here: `takeSecret` reads the value straight
// out of the input element and empties it; the page only holds booleans about fields.
import type { SetupStatus, SetupTools, WatchedFolders } from '$lib/bridge/types';
import type { StripStep } from '$lib/components';
// one copy of takeSecret for Settings and Setup (the account panel's model); Spotify's Client ID uses it here
export { takeSecret } from '$lib/components/accountModel';

export type WizardStep = 'music' | 'existing' | 'tools' | 'spotify' | 'downloads' | 'playlists';
export const STEPS: WizardStep[] = ['music', 'existing', 'tools', 'spotify', 'downloads', 'playlists'];
export const STEP_LABELS: Record<WizardStep, string> = {
  music: 'Music folder', existing: 'Your existing music', tools: 'Programs', spotify: 'Spotify', downloads: 'Downloads',
  playlists: 'First playlist',
};
/** Steps that don't have to be done to go on (plan library stage 4, I11): "Your existing music" never blocks
 *  Continue, never locks a later step and is never the engine's next step. */
export const OPTIONAL_STEPS: readonly WizardStep[] = ['existing'];

export type ClientIdCheck = 'empty' | 'ok' | 'bad';
/** A Spotify Client ID: 32 hex characters, any case; spaces around it are ignored. */
export function checkClientId(raw: string): ClientIdCheck {
  const v = (raw ?? '').trim();
  if (!v) return 'empty';
  return /^[0-9a-f]{32}$/i.test(v) ? 'ok' : 'bad';
}
export const CLIENT_ID_BAD = 'A Client ID has 32 letters and digits.';

/** Which steps are done, as setup_status() says. Your existing music: a folder watched, or skipped. Spotify:
 *  connected, or "I don't use Spotify". Downloads: Qobuz signed in, or "I don't have Qobuz". */
export function stepsDone(s: SetupStatus): Record<WizardStep, boolean> {
  return {
    music: s.music?.state === 'ok',
    existing: !!s.existing,
    tools: s.tools.ffmpeg && s.tools.ffprobe && s.tools.deno,
    spotify: (s.spotify_app && s.spotify_login) || s.spotify_skipped,
    downloads: s.qobuz || s.qobuz_skipped,
    playlists: s.playlists,
  };
}

/** Continue on Your existing music skips the step only when nothing is watched: the status says so, and so do the
 *  folders the page has read (a folder added a moment ago may not be in the status yet). */
export function skipsExisting(s: SetupStatus, folders: WatchedFolders | null): boolean {
  return !s.existing && !folders?.folders.some((f) => f.kind === 'import');
}

/** No music folder is bound yet: the music step is the only one Setup shows (every later step may read the library,
 *  which isn't there), whatever the address asks for. */
export function mustChooseMusic(s: SetupStatus): boolean {
  return s.music?.state !== 'ok';
}

/** The step Setup opens at without a step in the address: the music folder while none is bound, else the engine's
 *  next step; with everything done, Spotify (Programs only when a program is missing). */
export function firstStep(s: SetupStatus): WizardStep {
  if (mustChooseMusic(s)) return 'music';
  if (s.next_step) return s.next_step;
  return stepsDone(s).tools ? 'spotify' : 'tools';
}

export function isStep(v: string | undefined): v is WizardStep {
  return !!v && (STEPS as string[]).includes(v);
}

/** Steps the strip lets you open: the done ones and the first open required one (later ones wait until it is
 *  done); an optional step waits for nothing but the music folder. */
export function reachable(step: WizardStep, s: SetupStatus): boolean {
  const done = stepsDone(s);
  if (!done.music) return step === 'music';
  if (OPTIONAL_STEPS.includes(step)) return true;
  const firstOpen = STEPS.findIndex((k) => !done[k] && !OPTIONAL_STEPS.includes(k));
  return done[step] || firstOpen === -1 || STEPS.indexOf(step) <= firstOpen;
}

/** The step strip: done ✓, the one on screen, the next one you can open, and the ones that wait. */
export function stripSteps(current: WizardStep, s: SetupStatus): StripStep<WizardStep>[] {
  const done = stepsDone(s);
  return STEPS.map((key) => ({
    key, label: STEP_LABELS[key], done: done[key],
    state: key === current ? 'current' : done[key] ? 'done' : reachable(key, s) ? 'open' : 'locked',
  }));
}

export function neighbour(step: WizardStep, delta: -1 | 1): WizardStep | null {
  return STEPS[STEPS.indexOf(step) + delta] ?? null;
}

export type NextRule = { allowed: boolean; why: string | null };
/** May Continue go on from this step? The reason is the Hint beside the disabled button. */
export function nextRule(step: WizardStep, s: SetupStatus, tools: SetupTools | null): NextRule {
  const no = (why: string): NextRule => ({ allowed: false, why });
  const yes: NextRule = { allowed: true, why: null };
  switch (step) {
    case 'music': return stepsDone(s).music ? yes : no('Choose your music folder first.');
    case 'existing': return yes;
    case 'tools':
      if (!tools) return no('Checking the programs…');
      return tools.missing.length ? no('Install the missing programs, then Check again.') : yes;
    case 'spotify': return stepsDone(s).spotify ? yes : no("Connect Spotify, or choose I don't use Spotify.");
    case 'downloads': return stepsDone(s).downloads ? yes : no("Sign in to Qobuz, or choose I don't have Qobuz.");
    case 'playlists': return s.playlists ? yes : no('Add a playlist first.');
  }
}

/** Whether Continue is the screen's filled button: once the step is done. An optional step lets you go on before
 *  that (Continue skips it), but its own main action (Add folder…) stays the filled one until it is done. */
export function continueFilled(step: WizardStep, s: SetupStatus, rule: NextRule): boolean {
  return rule.allowed && (!OPTIONAL_STEPS.includes(step) || stepsDone(s)[step]);
}

/** The Downloads step's one card whose main action is filled (plan R10): Qobuz while it is required (neither signed
 *  in nor left out); afterwards none, and Continue is the filled button. The other cards' actions are `primary`. */
export function filledCard(s: SetupStatus): 'qobuz' | null {
  return stepsDone(s).downloads ? null : 'qobuz';
}

/** A step's row in Settings, where a done setup sends its links (spec §3.3); the first playlist goes to Playlists. */
const DONE_HOME: Record<WizardStep, string> = {
  music: '/settings/music', existing: '/settings/folders', tools: '/settings/programs', spotify: '/settings/spotify', downloads: '/settings/qobuz', playlists: '/playlists',
};
/** Where Setup sends you when you arrive with setup done: a step's own place in Settings, `#/setup` itself goes to
 *  Settings. null: stay in the guide. Only on arrival: a user finishing the guide keeps going to its end. A Spotify
 *  left out stays in the guide's Spotify step: Settings sends a Spotify without an app there to make one. */
export function doneRedirect(s: SetupStatus, step: WizardStep | null): string | null {
  if (!s.complete) return null;
  if (step === 'spotify' && !(s.spotify_app && s.spotify_login)) return null;
  return step ? DONE_HOME[step] : '/settings';
}

// ---- the programs Discjockey needs (Setup's Programs step and Settings' Programs row say the same) ----

export const TOOL_NAMES = ['ffmpeg', 'ffprobe', 'deno'] as const;
export type ToolName = (typeof TOOL_NAMES)[number];
export const TOOL_PURPOSE: Record<ToolName, string> = {
  ffmpeg: 'converts files to AIFF', ffprobe: 'checks length and quality (comes with ffmpeg)',
  deno: 'helps with YouTube downloads',
};
/** The Terminal line under each missing program, once per command: ffprobe comes with ffmpeg, so a missing pair
 *  shows `brew install ffmpeg` only under ffmpeg. The engine's hint is cut to its `brew install …` when it has one. */
export function toolFixes(tools: SetupTools | null): Partial<Record<ToolName, string>> {
  const seen = new Set<string>();
  const out: Partial<Record<ToolName, string>> = {};
  if (!tools) return out;
  for (const n of TOOL_NAMES) {
    const hint = tools.hints[n];
    if (tools.tools[n] || !hint) continue;
    const c = /brew install \S+/.exec(hint)?.[0] ?? hint;
    if (!seen.has(c)) { seen.add(c); out[n] = c; }
  }
  return out;
}
