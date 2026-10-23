// Fake mode only: downloads_view() from the fake state, the way views.downloads computes it (spec settings-setup §6.4).
import type { DownloadsAccount, DownloadsView, LimitCard } from '../types';
import type { FakeState } from './data';
import { cards } from './limits';
import { BROWSER_NAMES } from './browsers';

const PREMIUM_MIN_KBPS = 200;
const STREAMS = ['youtube_music', 'soundcloud', 'youtube'];
const SOURCE_OF = { youtube: 'youtube_music', soundcloud: 'soundcloud' } as const;

function cardState(c: LimitCard | undefined): 'paused' | 'used_up' | null {
  if (!c) return null;
  if (c.paused) return 'paused';
  return c.allowance && c.used >= c.allowance ? 'used_up' : null;
}

export function downloads(s: FakeState): DownloadsView {
  const byService = new Map(cards(s).map((c) => [c.service, c]));
  const live = s.tracks.filter((t) => t.in_playlists && !t.hidden);
  const lossy = live.filter((t) => t.status === 'not_lossless' && t.source && STREAMS.includes(t.source));
  const premium = (t: { kbps?: number }) => (t.kbps ?? 0) >= PREMIUM_MIN_KBPS;
  const q = s.qobuzLastCheck ?? null;
  const qstate = s.qobuzSkipped ? 'skipped' : !s.setup.qobuz || (q && !q.ok) ? 'off'
    : cardState(byService.get('qobuz')) ?? 'on';
  const account = (service: 'youtube' | 'soundcloud'): DownloadsAccount => {
    const a = s.accounts[service];
    const check = a?.lastCheck ?? null;
    const state: DownloadsAccount['state'] = !a ? 'off'
      : check && !check.ok ? (check.problem === 'no_premium' ? 'no_premium' : check.problem === 'cookies_unreadable' ? 'unreadable' : 'off')
      : cardState(byService.get(service)) ?? 'on';
    return { state, browser: a?.browser ?? null, browser_name: a ? BROWSER_NAMES[a.browser] : null,
      profile: a?.profile ?? null, profile_name: a ? a.profileName ?? null : null, last_check: check,
      tracks: lossy.filter((t) => t.source === SOURCE_OF[service] && premium(t)).length };
  };
  return {
    qobuz: { state: qstate, last_check: q, tracks: live.filter((t) => t.source === 'qobuz').length },
    youtube: account('youtube'), soundcloud: account('soundcloud'),
    library: { lossless: live.filter((t) => t.status === 'lossless').length,
      account: lossy.filter(premium).length, free: lossy.filter((t) => !premium(t)).length },
  };
}
