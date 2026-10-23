// Fake scenarios of the Download limits page (fake mode only). Open them with ?scenario=limits:<name>.
import type { PageFake } from '$lib/bridge/fake/bridge';
import type { Browser } from '$lib/bridge/types';
import type { FakeAccount, FakeState } from '$lib/bridge/fake/data';

type Mode = 'loading' | 'save-refused';
const mode = new WeakMap<FakeState, Mode>();

function at(s: FakeState, daysAgo: number, h: number, m: number): string {
  const d = new Date(s.now);
  d.setDate(d.getDate() - daysAgo);
  d.setHours(h, m, 0, 0);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(h)}:${p(m)}:00`;
}

const account = (s: FakeState, limit: number, used: number, browser: Browser = 'chrome'): FakeAccount => ({
  limit, extra_today: 0, carry_over: Math.floor(limit / 3), used_today: used, days: Array.from({ length: 14 },
    (_, i) => (i === 13 ? used : [3, 0, 12, 30, 8, 0, 0, 21, 25, 4, 0, 0, 18][i])), signals: [], last_download:
    at(s, 0, 20, 31), browser });

const fake: PageFake = {
  scenarios: {
    // a fresh install: nothing downloaded yet, no carry-over, no warning signs
    fresh(s) {
      s.qobuz = { ...s.qobuz, used_today: 0, carry_over: 0, days: Array(14).fill(0), signals: [], last_download: null };
    },
    // a quiet fortnight: no warning signs at all
    'all-good'(s) { s.qobuz.signals = []; },
    // the warning signs were marked as seen ("Got it") an hour ago
    seen(s) { s.qobuz.seen = new Date(s.now.getTime() - 3600e3).toISOString().slice(0, 19); },
    // a long backlog: 120 tracks, about 3 days at 60 a day
    backlog(s) { s.newTracks = s.newTracks.concat(Array.from({ length: 110 }, (_, i) => ({ ...s.newTracks[i % s.newTracks.length], track_id: `bl${i}` }))); },
    // 20 extra downloads allowed for today
    'extra-today'(s) { s.qobuz.extra_today = 20; },
    // several warning signs in the last 14 days
    warnings(s) {
      s.qobuz.signals = [
        { time: at(s, 2, 21, 47), kind: 'login_failed', message: 'Qobuz did not accept the login' },
        { time: at(s, 5, 20, 3), kind: 'login_failed', message: 'Qobuz did not accept the login' },
        { time: at(s, 2, 21, 52), kind: 'download_rejected', message: 'Qobuz refused the download of “Get Naughty”' },
        { time: at(s, 2, 21, 53), kind: 'download_rejected', message: 'Qobuz refused the download of “Gimme Gimme”' },
        { time: at(s, 2, 21, 54), kind: 'download_rejected', message: 'Qobuz refused the download of “The Weekend”' },
        { time: at(s, 2, 21, 54), kind: 'auto_stop', message: 'Qobuz paused after 3 rejected downloads in a row' },
        { time: at(s, 4, 22, 12), kind: 'preview_only', message: 'Only a 30-second preview came back' },
        ...s.qobuz.signals,
      ];
    },
    // only YouTube Premium (a colleague without Qobuz)
    'only-youtube'(s) { s.qobuzSkipped = true; s.accounts.youtube = account(s, 30, 4); },
    // Qobuz, YouTube Premium and SoundCloud Go+
    'all-three'(s) { s.accounts.youtube = account(s, 30, 4); s.accounts.soundcloud = account(s, 60, 11, 'firefox'); },
    // YouTube Premium paused today after three refusals
    'youtube-paused'(s) {
      s.accounts.youtube = { ...account(s, 30, 9), signals: [
        { time: at(s, 0, 21, 2), kind: 'bot_check', message: 'Sign in to confirm you’re not a bot' },
        { time: at(s, 0, 21, 3), kind: 'refused', message: 'HTTP Error 403: Forbidden' },
        { time: at(s, 0, 21, 4), kind: 'refused', message: 'HTTP Error 403: Forbidden' },
        { time: at(s, 0, 21, 4), kind: 'auto_stop', message: '3 YouTube Premium requests failed in a row' }] };
    },
    // nothing set up: only the free sources
    nothing(s) { s.qobuzSkipped = true; },
    // the page stays on its skeletons
    loading(s) { mode.set(s, 'loading'); },
    // saving is refused
    'save-refused'(s) { mode.set(s, 'save-refused'); },
  },
  overrides: {
    limits: (ctx, base) => (service) => (mode.get(ctx.s) === 'loading' ? new Promise(() => {}) : base(service)),
    save_limits: (ctx, base) => async (service, limit, extra_today) => (mode.get(ctx.s) === 'save-refused'
      ? ctx.fail('refused', 'Not saved: settings.json is open in another app. Close it, then try again.')
      : base(service, limit, extra_today)),
  },
};
export const scenarios = fake.scenarios;
export const overrides = fake.overrides;
export default fake;
