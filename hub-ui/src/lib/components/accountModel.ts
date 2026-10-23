// The account panel's model (spec settings-setup §5, §7.1, §10, §13): what a login gives, the state line Settings'
// rows and the panel share, where the sign-in stands (its phase), the browser menu and the Qobuz password steps.
// Pure: the panel and its controller (accountFlow.svelte.ts) pass in what the bridge answered and the time.
// Credentials never pass through here except in `takeSecret`, which empties the element it reads.
import type {
  AccountCheck, Browser, DownloadsAccount, DownloadsView, FindLogins, JobSnap, LastCheck, LoginBrowser, Service,
} from '../bridge/types';
import { WRITE_BLOCKED } from '../copy';
import { dayMonth } from '../format';

export type AccountService = Exclude<Service, 'qobuz'>;

/** A service's name where the panel and the rows name it. */
export const SERVICE_TITLES: Record<Service, string> = {
  qobuz: 'Qobuz', youtube: 'YouTube Premium', soundcloud: 'SoundCloud Go+',
};
/** The site, where a sentence talks about its login ("your YouTube login"). */
const SITE: Record<AccountService, string> = { youtube: 'YouTube', soundcloud: 'SoundCloud' };
/** The plan's name ("with Premium"). */
const PLAN: Record<AccountService, string> = { youtube: 'Premium', soundcloud: 'Go+' };
/** What it gives, in a few words (Setup's compact card while it isn't set up). */
export const WHAT_IT_GIVES: Record<Service, string> = {
  qobuz: 'lossless for most songs', youtube: 'about 256 kbps instead of 130', soundcloud: 'about 256 kbps instead of 130',
};
/** The stream quality with an account and without one (spec §1: about 256 against about 130 kbps). */
export const GAIN_KBPS = { with: 256, without: 130 } as const;

/** The risk notes behind the ⓘ beside the name (spec §5 item 5). */
export const RISK_NOTE: Record<Service, string> = {
  qobuz: "Downloading with streamrip is against Qobuz's terms. Discjockey keeps the risk low (pauses, daily limit, "
    + "automatic stop), but can't remove it.",
  youtube: "Downloading breaks YouTube's terms. YouTube is known to block accounts with unusual traffic, and for most "
    + 'people that is their Google account, with Gmail. The daily limit and the pauses lower the risk but don’t '
    + 'remove it.',
  soundcloud: "Downloading breaks SoundCloud's terms. The daily limit and the pauses lower the risk but don’t remove "
    + 'it. Discjockey never works around copy protection: Go+ tracks that are protected are skipped.',
};

/** Reads a secret out of its input element and empties the element at once. */
export function takeSecret(el: { value: string } | null | undefined): string {
  if (!el) return '';
  const v = el.value;
  el.value = '';
  return v;
}

// ---- the state line (Settings' rows and the panel say the same thing) ----

export type Tone = 'good' | 'warn' | 'problem' | 'none' | null;
export type RowLine = { tone: Tone; text: string };
/** The panel's form of the same state: a headline with its mark, and a quieter second line. */
export type PanelLine = { tone: Exclude<Tone, null>; title: string; sub: string | null };

const join = (...parts: (string | null | undefined | false)[]) => parts.filter(Boolean).join(' · ');
const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** "checked today" / "checked 21 Oct" for a saved check; '' without one. */
export function checkedWhen(check: LastCheck | null | undefined, now: Date): string {
  if (!check?.at) return '';
  const day = check.at.slice(0, 10);
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  return day === today ? 'checked today' : `checked ${dayMonth(check.at)}`;
}

/** "Chrome (DJ)": the browser, with the profile's name when there is one to tell apart. */
export function browserLabel(browserName: string, profileName: string | null | undefined): string {
  return profileName ? `${browserName} (${profileName})` : browserName;
}

type Said = { tone: Exclude<Tone, null>; row: string; title: string; sub: string | null };

function accountSaid(service: AccountService, a: DownloadsAccount, now: Date): Said {
  const where = a.browser_name ? browserLabel(a.browser_name, a.profile_name) : null;
  const via = where ? `via ${where}` : null;
  const kbps = a.last_check?.kbps ? `${a.last_check.kbps} kbps` : null;
  const checked = checkedWhen(a.last_check, now);
  switch (a.state) {
    case 'on':
      return { tone: 'good', row: join(via, kbps, checked), title: via ? `Signed in ${via}` : 'Signed in',
        sub: join(kbps, checked) || null };
    case 'no_premium':
      return service === 'youtube'
        ? { tone: 'warn', row: 'signed in, but no Premium', title: 'Signed in, but no Premium',
          sub: join(a.last_check?.kbps ? `YouTube gives this account ${a.last_check.kbps} kbps` : null, checked) || null }
        : { tone: 'warn', row: 'signed in · Go+ not confirmed', title: 'Signed in · Go+ not confirmed',
          sub: join('Discjockey still downloads with it', checked) };
    case 'unreadable': {
      const text = `can't read the login in ${a.browser_name ?? 'the browser'}`;
      return { tone: 'problem', row: text, title: capital(text), sub: checked || null };
    }
    case 'paused': return { tone: 'warn', row: 'paused today', title: 'Paused today', sub: via ? `Signed in ${via}` : null };
    case 'used_up':
      return { tone: 'warn', row: "today's downloads used up", title: "Today's downloads used up",
        sub: via ? `Signed in ${via}` : null };
    default: {
      if (!a.browser) return { tone: 'none', row: 'not set up', title: 'Not set up yet', sub: null };
      const text = `not signed in any more${a.browser_name ? ` in ${a.browser_name}` : ''}`;
      return { tone: 'problem', row: text, title: capital(text), sub: checked || null };
    }
  }
}

function qobuzSaid(d: DownloadsView, now: Date): Said {
  const q = d.qobuz;
  const checked = checkedWhen(q.last_check, now);
  switch (q.state) {
    case 'on': return { tone: 'good', row: join('signed in', checked), title: 'Signed in', sub: checked || null };
    case 'skipped': return { tone: 'none', row: 'left out', title: 'Left out', sub: 'Discjockey starts at the other sources' };
    case 'paused': return { tone: 'warn', row: 'paused today', title: 'Paused today', sub: 'Signed in' };
    case 'used_up': return { tone: 'warn', row: "today's downloads used up", title: "Today's downloads used up", sub: 'Signed in' };
    default:
      return q.last_check && !q.last_check.ok
        ? { tone: 'problem', row: "Qobuz didn't accept the login", title: "Qobuz didn't accept the login", sub: checked || null }
        : { tone: 'none', row: 'not set up', title: 'Not set up yet', sub: null };
  }
}

function said(service: Service, d: DownloadsView, now: Date): Said {
  return service === 'qobuz' ? qobuzSaid(d, now) : accountSaid(service, d[service], now);
}

/** The state line of a download source, as Settings' row says it ("via Chrome (DJ) · 256 kbps · checked today"). */
export function stateLine(service: Service, d: DownloadsView, now: Date): RowLine {
  const s = said(service, d, now);
  return { tone: s.tone, text: s.row };
}
/** The same state in the panel: "Signed in via Chrome (DJ)" over "256 kbps · checked today". */
export function panelLine(service: Service, d: DownloadsView, now: Date): PanelLine {
  const s = said(service, d, now);
  return { tone: s.tone, title: s.title, sub: s.sub };
}

/** Setup's compact card head: the state when there is one, else what the login gives. */
export function compactLine(service: Service, d: DownloadsView, now: Date): RowLine {
  const s = said(service, d, now);
  return s.tone === 'none' && s.row === 'not set up' ? { tone: 'none', text: WHAT_IT_GIVES[service] } : { tone: s.tone, text: s.row };
}

/** The account counts as set up (Setup's card shows only its head, Settings offers Check again and Sign out). */
export function isWorking(service: Service, d: DownloadsView): boolean {
  const state = service === 'qobuz' ? d.qobuz.state : d[service].state;
  return state === 'on' || state === 'paused' || state === 'used_up';
}

// ---- what it gives (spec §5 item 1) ----

/** The user's own number: how many tracks came in at about 130 kbps (accounts) or from Qobuz; null when 0. */
export function gainLine(service: Service, d: DownloadsView): string | null {
  if (service === 'qobuz') return d.qobuz.tracks > 0 ? `${d.qobuz.tracks} of your tracks came from Qobuz.` : null;
  return d.library.free > 0
    ? `${d.library.free} of your tracks came from free streams at about ${GAIN_KBPS.without} kbps.` : null;
}
/** The gain card's caption under the number ("with Premium · about 130 without"). */
export function gainCaption(service: AccountService): string {
  return `with ${PLAN[service]} · about ${GAIN_KBPS.without} without`;
}
/** Qobuz's share of the library (the bar under its count); null without a library. */
export function qobuzShare(d: DownloadsView): { tracks: number; total: number; share: number | null } {
  const total = d.library.lossless + d.library.account + d.library.free;
  return { tracks: d.qobuz.tracks, total, share: total > 0 ? Math.min(1, d.qobuz.tracks / total) : null };
}

// ---- Chromium's keychain prompt ----

const CHROMIUM: Partial<Record<Browser, string>> = { chrome: 'Chrome', brave: 'Brave', edge: 'Microsoft Edge' };
/** The one-line warning before the first check of a Chromium browser; null for Safari and Firefox, and once that
 *  browser has been checked before (plan R25). */
export function chromiumHint(browser: Browser | null | undefined, everChecked: boolean): string | null {
  const name = browser ? CHROMIUM[browser] : undefined;
  if (!name || everChecked) return null;
  return `macOS will ask about “${name} Safe Storage” once. Click Always Allow.`;
}
/** Has any saved account been checked with this browser (so macOS already asked)? */
export function checkedBefore(browser: Browser | null | undefined, d: DownloadsView | null): boolean {
  if (!browser || !d) return false;
  return [d.youtube, d.soundcloud].some((a) => a.browser === browser && a.last_check != null);
}

// ---- the panel's phase ----

/** A browser profile the panel offers: found with a login, none found (Sign in), or one macOS doesn't let us read. */
export type Offer =
  | { kind: 'found'; browser: Browser; browserName: string; profile: string | null; profileName: string | null;
    picked?: boolean }
  | { kind: 'none'; browser: Browser | null; browserName: string | null; profile: string | null;
    profileName: string | null; searched: string[]; picked?: boolean }
  | { kind: 'unreadable'; browser: Browser; browserName: string; profile: string | null; picked?: boolean };

/** Where the panel stands. `picked`: chosen in "Use another browser" (Cancel goes back to the account's state). */
export type PanelPhase =
  | { kind: 'looking' }
  | { kind: 'error'; message: string }
  | Offer
  | { kind: 'waiting'; browser: Browser; browserName: string }
  | { kind: 'checking'; browserName: string | null }
  | { kind: 'result'; message: string; tone: 'warn' | 'problem'; retry: Offer | { kind: 'form' } | null }
  | { kind: 'working' }
  | { kind: 'no_premium' }
  | { kind: 'form'; editing?: boolean };

const byDefaultThenName = (a: LoginBrowser, b: LoginBrowser) =>
  Number(b.default) - Number(a.default) || a.name.localeCompare(b.name);

/** "Chrome", "Chrome or Firefox", "Chrome, Firefox or Brave". */
export function orList(names: string[]): string {
  if (names.length <= 1) return names[0] ?? '';
  return `${names.slice(0, -1).join(', ')} or ${names[names.length - 1]}`;
}

/** find_logins' answer as the first offer (spec §7.1): the default browser first, then by name; its first signed-in
 *  profile → found. None → Sign in with the default browser, or the first one that can be read. A browser macOS
 *  doesn't let us read is never offered for Sign in; when it is the only one, the panel says why (unreadable). */
export function firstFound(f: FindLogins): Offer {
  const order = [...f.browsers].sort(byDefaultThenName);
  const readable = order.filter((b) => b.problem !== 'no_access');
  for (const b of readable) {
    const p = b.profiles.find((x) => x.signed_in);
    if (p) return { kind: 'found', browser: b.id, browserName: b.name, profile: p.id,
      profileName: b.profiles.length > 1 ? p.name : null };
  }
  const offer = readable[0];
  if (offer) return { kind: 'none', browser: offer.id, browserName: offer.name, profile: null, profileName: null,
    searched: readable.map((b) => b.name) };
  const shut = order[0];
  if (shut) return { kind: 'unreadable', browser: shut.id, browserName: shut.name, profile: null };
  return { kind: 'none', browser: null, browserName: null, profile: null, profileName: null, searched: [] };
}

/** An account's phase: a running or just-ended flow (`active`) wins; else the saved account's state; else what
 *  find_logins found (looking while it hasn't answered, error when it failed). */
export function accountPhase(a: DownloadsAccount | null, logins: FindLogins | null, loadError: string | null,
  active: PanelPhase | null): PanelPhase {
  if (active) return active;
  if (a && (a.state === 'on' || a.state === 'paused' || a.state === 'used_up')) return { kind: 'working' };
  if (a?.state === 'no_premium') return { kind: 'no_premium' };
  if (a?.state === 'unreadable' && a.browser) {
    return { kind: 'unreadable', browser: a.browser, browserName: a.browser_name ?? a.browser, profile: a.profile };
  }
  if (loadError) return { kind: 'error', message: loadError };
  if (!a || !logins) return { kind: 'looking' };
  return firstFound(logins);
}

/** Qobuz's phase: the flow wins; signed in → working; else the email and password form. */
export function qobuzPhase(q: DownloadsView['qobuz'] | null, active: PanelPhase | null): PanelPhase {
  if (active) return active;
  if (!q) return { kind: 'looking' };
  return q.state === 'on' || q.state === 'paused' || q.state === 'used_up' ? { kind: 'working' } : { kind: 'form' };
}

export type MainAction = { kind: 'use' | 'sign-in' | 'privacy' | 'qobuz-sign-in' | 'look-again'; label: string };
/** The phase's one main action (the Panel foot's filled button; Setup's card button): nothing while it works or
 *  waits. Safari without Full Disk Access → Open System Settings; another unreadable browser is checked again; a
 *  failed look for logins is tried again. */
export function mainAction(phase: PanelPhase): MainAction | null {
  switch (phase.kind) {
    case 'found': return { kind: 'use', label: 'Use this login' };
    case 'none': return phase.browser ? { kind: 'sign-in', label: 'Sign in' } : { kind: 'look-again', label: 'Look again' };
    case 'unreadable': return phase.browser === 'safari' ? { kind: 'privacy', label: 'Open System Settings' }
      : { kind: 'use', label: 'Use this login' };
    case 'result': {
      // a login that answered but without Premium/Go+ (warn) is the right login: using it again is checking again
      const again = phase.retry ? mainAction(phase.retry) : null;
      return again?.kind === 'use' && phase.tone === 'warn' ? { ...again, label: 'Check again' } : again;
    }
    case 'form': return { kind: 'qobuz-sign-in', label: 'Sign in' };
    case 'error': return { kind: 'look-again', label: 'Try again' };
    default: return null;
  }
}

/** A result that offers nothing to do again (a failed sign-out, System Settings that didn't open): the panel gives
 *  it an OK that goes back to the account's own state, so no result is a dead end. */
export function dismissable(phase: PanelPhase): boolean {
  return phase.kind === 'result' && !mainAction(phase) && phase.retry?.kind !== 'form';
}

/** A finished check (setup_account / account_sign_in) as the next phase: null when it works (the state line says
 *  so), Safari's refusal as unreadable, else the check's words with the offer to try again. */
export function checkPhase(check: AccountCheck, retry: Offer): PanelPhase | null {
  if (check.ok) return null;
  if (check.problem === 'cookies_unreadable' && retry.browser === 'safari') {
    return { kind: 'unreadable', browser: 'safari', browserName: retry.browserName ?? 'Safari', profile: retry.profile,
      picked: retry.picked };
  }
  return { kind: 'result', message: check.message, tone: check.problem === 'no_premium' ? 'warn' : 'problem', retry };
}

// ---- "Use another browser ▾" ----

export type MenuChoice = {
  key: string; label: string; note: string | null; good: boolean;
  browser: Browser; browserName: string; profile: string | null; profileName: string | null;
  signedIn: boolean; noAccess: boolean;
};
/** Every installed browser × profile, the default browser first. "<Browser> · <profile>" only for a browser with
 *  more than one profile; marked "signed in", "needs Full Disk Access" or "default browser". Keys are unique. */
export function browserMenu(f: FindLogins | null): MenuChoice[] {
  if (!f) return [];
  const out: MenuChoice[] = [];
  for (const b of [...f.browsers].sort(byDefaultThenName)) {
    const noAccess = b.problem === 'no_access';
    const profiles = b.profiles.length ? b.profiles : [{ id: null, name: b.name, signed_in: false }];
    const many = profiles.length > 1;
    profiles.forEach((p, i) => {
      const signedIn = !noAccess && p.signed_in;
      out.push({
        key: `${b.id}:${p.id ?? `#${i}`}`, label: many ? `${b.name} · ${p.name}` : b.name,
        note: noAccess ? 'needs Full Disk Access' : signedIn ? 'signed in' : b.default ? 'default browser' : null,
        good: signedIn, browser: b.id, browserName: b.name, profile: p.id, profileName: many ? p.name : null,
        signedIn, noAccess,
      });
    });
  }
  return out;
}
/** A menu pick as the offer the panel shows (its main action then does it). */
export function pickedPhase(c: MenuChoice): Offer {
  if (c.noAccess) return { kind: 'unreadable', browser: c.browser, browserName: c.browserName, profile: c.profile, picked: true };
  if (c.signedIn) return { kind: 'found', browser: c.browser, browserName: c.browserName, profile: c.profile,
    profileName: c.profileName, picked: true };
  return { kind: 'none', browser: c.browser, browserName: c.browserName, profile: c.profile, profileName: c.profileName,
    searched: [browserLabel(c.browserName, c.profileName)], picked: true };
}

// ---- the sentences of a phase ----

export function foundText(service: AccountService, p: Extract<Offer, { kind: 'found' }>): string {
  return `Found your ${SITE[service]} login in ${browserLabel(p.browserName, p.profileName)}.`;
}
export function noneText(service: AccountService, p: Extract<Offer, { kind: 'none' }>): string {
  if (!p.browser) return 'No browser Discjockey can read is on this Mac.';
  return `No ${SITE[service]} login in ${orList(p.searched.length ? p.searched : [p.browserName ?? ''])}.`;
}
export function signInHint(service: AccountService, p: Extract<Offer, { kind: 'none' }>, defaultName: string | null): string | null {
  if (!p.browser) return 'Install Chrome or Firefox, sign in there, then look again.';
  if (!p.browserName) return null;
  const where = browserLabel(p.browserName, p.profileName);
  return p.browserName === defaultName && !p.profileName
    ? `Sign in opens ${SITE[service]} in ${where}, your default browser.` : `Sign in opens ${SITE[service]} in ${where}.`;
}
export function unreadableText(browserName: string): { text: string; hint: string } {
  return browserName === 'Safari'
    ? { text: "macOS didn't let Discjockey read Safari's logins.", hint: 'Turn on Discjockey under Full Disk Access, then come back.' }
    : { text: `macOS didn't let Discjockey read ${browserName}'s login.`, hint: 'Use this login again and click Always Allow.' };
}
export function waitingText(browserName: string): string {
  return `Waiting for your sign-in in ${browserName}…`;
}

// ---- disabled ----

/** Why the panel's write buttons are off: a terminal run, the hub's sync, another change, another sign-in (the hub
 *  store keeps a waiting sign-in in its own `sign_in` slot, never in `job`). */
export function accountBlocked(s: { job: JobSnap | null; console_running: boolean; sign_in?: JobSnap | null }): string | null {
  if (s.console_running) return WRITE_BLOCKED.console;
  if (s.job?.running) return s.job.kind === 'sync' ? 'Wait until the sync has finished.' : WRITE_BLOCKED.busy;
  if (s.sign_in?.running) return 'Another sign-in is waiting for the browser.';
  return null;
}

// ---- Qobuz with a Google, Apple or Facebook account: give it a password once (spec settings-setup §13) ----

export const QOBUZ_PASSWORD_URL = 'https://www.qobuz.com/signin/forget-password';
export function qobuzPasswordSteps(): string[] {
  return ["Open Qobuz's page and enter your account's e-mail.", 'Open the e-mail from Qobuz and choose a password.',
    'Sign in here with that e-mail and password.'];
}
