// Fake mode only: the logins page scenarios put on the fake Mac (Settings' and Setup's download accounts), so both
// pages show the same accounts, browsers and checks.
import type { FakeAccount, FakeState } from './data';
import { RECOMMENDED } from './limits';
import type { LastCheck, LoginBrowser } from '../types';

/** today on the fake clock at h:15, as the engine writes a time */
export function at(s: FakeState, h = 9): string {
  const d = new Date(s.now);
  d.setHours(h, 15, 0, 0);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:00`;
}

/** an account's last check: good at 256 kbps unless `over` says otherwise */
export function check(s: FakeState, over: Partial<LastCheck> = {}): LastCheck {
  return { ok: true, problem: null, kbps: 256, at: at(s, 10), ...over };
}

/** a saved YouTube/SoundCloud login, from Chrome's "DJ" profile unless `over` says otherwise */
export function account(s: FakeState, service: 'youtube' | 'soundcloud', over: Partial<FakeAccount> = {}): FakeAccount {
  return { limit: RECOMMENDED[service], extra_today: 0, carry_over: 0, used_today: 0, days: Array(14).fill(0),
    signals: [], last_download: null, browser: 'chrome', profile: 'Profile 2', profileName: 'DJ',
    lastCheck: check(s), ...over };
}

/** Chrome (the default browser) with two profiles; `signedIn` names the profiles that hold the service's login */
export function chrome(signedIn: string[] = []): LoginBrowser {
  return { id: 'chrome', name: 'Chrome', default: true, readable: true, problem: null,
    profiles: [{ id: 'Default', name: 'Person 1', signed_in: signedIn.includes('Default') },
      { id: 'Profile 2', name: 'DJ', signed_in: signedIn.includes('Profile 2') }] };
}

/** Safari without Full Disk Access (its logins can't be read) */
export function safari(): LoginBrowser {
  return { id: 'safari', name: 'Safari', default: false, readable: false, problem: 'no_access',
    profiles: [{ id: null, name: 'Safari', signed_in: false }] };
}

/** Qobuz signed in, checked this morning */
export function signedQobuz(s: FakeState): void {
  s.qobuzLastCheck = { ok: true, problem: null, kbps: null, at: at(s) };
}
