// The source ladder's state and its words (spec settings-setup §4, plan R26). Pure: SourceLadder renders it.
// Rungs, best first: Qobuz (lossless) · the artist's own file (always) · Premium streams (YouTube Premium or
// SoundCloud Go+, about 256 kbps) · free streams (always, about 130 kbps). The engine treats the two accounts as one
// tier, so either one lights the Premium rung.
import type { DownloadsView, Service } from '../bridge/types';

export type RungState = 'on' | 'off' | 'paused' | 'used_up' | 'skipped' | 'no_premium' | 'unreadable';
export type Ladder = { qobuz: RungState; youtube: RungState; soundcloud: RungState; accounts: boolean };
export type AccountService = 'youtube' | 'soundcloud';
export type ChipTone = 'good' | 'warn' | 'none';

/** The account's full name (its chip shows only the service). */
export const ACCOUNT_NAME: Record<AccountService, string> = { youtube: 'YouTube Premium', soundcloud: 'SoundCloud Go+' };
const SERVICE: Record<AccountService, string> = { youtube: 'YouTube', soundcloud: 'SoundCloud' };
const TIER: Record<AccountService, string> = { youtube: 'Premium', soundcloud: 'Go+' };
const ACCOUNTS: AccountService[] = ['youtube', 'soundcloud'];

/** An account the engine downloads through: signed in, or (SoundCloud only) a login saved without confirmed Go+,
 *  which the engine still uses (R26). */
function working(service: AccountService, s: RungState): boolean {
  return s === 'on' || (service === 'soundcloud' && s === 'no_premium');
}

export function ladderState(d: DownloadsView): Ladder {
  const youtube = d.youtube.state as RungState, soundcloud = d.soundcloud.state as RungState;
  return { qobuz: d.qobuz.state as RungState, youtube, soundcloud,
    accounts: working('youtube', youtube) || working('soundcloud', soundcloud) };
}

/** Qobuz is there when signed in, also while paused or used up for today: it comes back by itself. */
export function qobuzLit(s: RungState): boolean {
  return s === 'on' || s === 'paused' || s === 'used_up';
}

/** The one line under the ladder: what this setup means (spec §4, exactly four sentences). */
export function ladderLine(l: Ladder): string {
  const name = l.youtube === 'on' ? ACCOUNT_NAME.youtube : ACCOUNT_NAME.soundcloud;
  if (qobuzLit(l.qobuz) && l.accounts) return `Songs Qobuz doesn't have come in at about 256 kbps through ${name}.`;
  if (qobuzLit(l.qobuz)) return "Songs Qobuz doesn't have come from free YouTube at about 130 kbps.";
  if (l.accounts) return "Without Qobuz nothing comes in lossless, except the artists' own files.";
  return 'Without Qobuz or an account, most songs come in at about 130 kbps.';
}

/** An account chip's mark: ✓ signed in, ! something to look at (not confirmed, paused, used up), dashed nothing. */
export function chipTone(s: RungState): ChipTone {
  if (s === 'on') return 'good';
  if (s === 'no_premium' || s === 'paused' || s === 'used_up') return 'warn';
  return 'none';
}

/** Paused or used up for today: Download limits explains it and can lift it, so the chip and the account panel go
 *  there (`#/limits/<service>`, the limits page's route); null for every other state. */
export function limitsHref(service: Service, s: string): string | null {
  return s === 'paused' || s === 'used_up' ? `#/limits/${service}` : null;
}

function stateWords(service: AccountService, s: RungState): string {
  switch (s) {
    case 'on': return 'signed in';
    case 'no_premium': return `${TIER[service]} not confirmed`;
    case 'paused': return 'paused today, see Download limits';
    case 'used_up': return 'used up today, see Download limits';
    case 'unreadable': return "the login can't be read";
    default: return 'not set up';
  }
}

/** The chip's state in words, for screen readers and its tooltip ("YouTube Premium: signed in"). */
export function chipLabel(service: AccountService, s: RungState): string {
  return `${ACCOUNT_NAME[service]}: ${stateWords(service, s)}`;
}

/** The Qobuz rung's line under its name. */
export function qobuzWords(s: RungState, compact: boolean): string {
  if (s === 'on') return 'signed in';
  if (s === 'paused') return compact ? 'paused today' : 'signed in · paused today';
  if (s === 'used_up') return compact ? 'used up today' : 'signed in · used up today';
  if (s === 'skipped') return 'not used';
  return 'not signed in';
}

/** The Premium rung's line: through which account when lit, else why not (YouTube's state first). */
export function premiumWords(l: Ladder, compact: boolean): string {
  const on = ACCOUNTS.filter((a) => l[a] === 'on');
  if (on.length === 2) return compact ? 'through Premium and Go+' : `through ${ACCOUNT_NAME.youtube} and ${ACCOUNT_NAME.soundcloud}`;
  if (on.length === 1) return `through ${ACCOUNT_NAME[on[0]]}`;
  if (l.accounts) return compact ? 'Go+ not confirmed' : 'through SoundCloud · Go+ not confirmed';
  for (const a of ACCOUNTS) {
    const s = l[a];
    if (s === 'paused' || s === 'used_up') {
      const what = s === 'paused' ? 'paused today' : 'used up today';
      return `${compact ? SERVICE[a] : ACCOUNT_NAME[a]} ${what}`;
    }
    if (s === 'unreadable') return `can't read the ${SERVICE[a]} login`;
    if (s === 'no_premium') return compact ? `${TIER[a]} not confirmed` : `${ACCOUNT_NAME[a]} not confirmed`;
  }
  return compact ? 'needs Premium or Go+' : `needs ${ACCOUNT_NAME.youtube} or ${ACCOUNT_NAME.soundcloud}`;
}
