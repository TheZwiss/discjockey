// Fake mode only: the Download limits numbers per service, from the fake state (as discjockey/hub/views.py does it).
import type {
  AnySignalKind, Budget, EstimateAccount, SyncAccount, LimitCard, Limits, Service, ServiceUsage, WhatIf,
} from '../types';
import { daysToLoad } from '../../days';
import type { FakeService, FakeState } from './data';

export const SERVICES: Service[] = ['qobuz', 'youtube', 'soundcloud'];
export const NAMES: Record<Service, string> = { qobuz: 'Qobuz', youtube: 'YouTube Premium', soundcloud: 'SoundCloud Go+' };
export const RECOMMENDED: Record<Service, number> = { qobuz: 60, youtube: 30, soundcloud: 60 };
const ZONE_TOPS: Record<Service, number[]> = { qobuz: [40, 60, 79, 100], youtube: [20, 30, 45, 60], soundcloud: [40, 60, 79, 100] };
const ASSESS_TOPS: Record<Service, number[]> = { qobuz: [40, 60, 80, 100], youtube: [20, 30, 45, 60], soundcloud: [40, 60, 80, 100] };
const ZONE_NAMES = ['careful', 'normal', 'faster', 'fast', 'risky'];
const ACCOUNT_SIGNALS: AnySignalKind[] = ['cookies_unreadable', 'bot_check', 'rate_limited', 'refused',
  'premium_missing', 'download_rejected', 'auto_stop'];
export const SIGNAL_KINDS: Record<Service, AnySignalKind[]> = {
  qobuz: ['login_failed', 'search_failed', 'download_rejected', 'preview_only', 'duration_mismatch', 'auto_stop'],
  youtube: ACCOUNT_SIGNALS,
  soundcloud: ACCOUNT_SIGNALS.filter((k) => k !== 'bot_check'),
};

export function serviceOf(s: FakeState, service: Service): FakeService | null {
  if (service === 'qobuz') return s.qobuzSkipped ? null : s.qobuz;
  return s.accounts[service] ?? null;
}
export const setUp = (s: FakeState): Service[] => SERVICES.filter((k) => serviceOf(s, k));

export function budgetOf(f: FakeService, limit = f.limit, extra = f.extra_today): Budget {
  const carry = Math.min(Math.floor(limit / 3), f.carry_over);
  const allowance = limit + carry + extra;
  return { used: f.used_today, allowance, limit, carry_over: carry, extra,
    remaining: Math.max(0, allowance - f.used_today) };
}
export function zones(service: Service) {
  let from = 1;
  return [...ZONE_TOPS[service], 500].map((to, i) => { const z = { name: ZONE_NAMES[i], from, to }; from = to + 1; return z; });
}
export function assessment(service: Service, limit: number) {
  const i = ASSESS_TOPS[service].findIndex((top) => limit <= top);
  return i < 0 ? { level: 5, label: 'risky' } : { level: i + 1, label: ZONE_NAMES[i] };
}
/** What every download counts against: Qobuz when set up, else the accounts together; null = no limit. */
export function gate(s: FakeState): { remaining: number; limit: number } | null {
  const up = setUp(s);
  if (!up.length) return null;
  const pick = up.includes('qobuz') ? ['qobuz' as Service] : up;
  const b = pick.map((k) => budgetOf(serviceOf(s, k)!));
  return { remaining: b.reduce((a, x) => a + x.remaining, 0), limit: b.reduce((a, x) => a + x.limit, 0) };
}
export function split(s: FakeState, needed: number): EstimateAccount[] {
  const up = setUp(s);
  let rest = needed;
  return up.map((service) => {
    const b = budgetOf(serviceOf(s, service)!);
    const behind = up.includes('qobuz') && service !== 'qobuz';
    const uses = behind ? null : Math.min(rest, b.remaining);
    rest -= uses ?? 0;
    return { service, name: NAMES[service], uses, left: b.remaining, limit: b.limit, about: service !== 'qobuz' };
  });
}
/** views.sync_estimate's accounts: split() plus each account's `uses` for every count 0 … `most`. */
export function syncSplit(s: FakeState, needed: number, most: number): SyncAccount[] {
  const tables = Array.from({ length: most + 1 }, (_, n) => split(s, n));
  return split(s, needed).map((a, i) => ({ ...a,
    uses_by_downloads: a.uses === null ? null : tables.map((t) => t[i].uses as number) }));
}
/** The warning signs with `new` (after the last "Got it") and `clears_in` (days until they leave the 14 days). */
export function signalsOf(s: FakeState, f: FakeService): ServiceUsage['signals'] {
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  return f.signals.map((g) => ({ ...g, new: !f.seen || g.time > f.seen,
    clears_in: 14 - Math.round((day(s.now) - day(new Date(g.time))) / 864e5) }));
}
export function cards(s: FakeState): LimitCard[] {
  const today = s.now.toISOString().slice(0, 10);
  return SERVICES.map((service) => {
    const f = serviceOf(s, service);
    if (!f) return { service, name: NAMES[service], set_up: false, used: 0, allowance: 0, warnings: 0, new_warnings: 0, paused: false };
    const b = budgetOf(f);
    return { service, name: NAMES[service], set_up: true, used: b.used, allowance: b.allowance,
      warnings: f.signals.length, new_warnings: signalsOf(s, f).filter((g) => g.new).length, paused: f.signals.some((g) => g.kind === 'auto_stop' && g.time.startsWith(today)) };
  });
}
export function whatIf(s: FakeState, service: Service, limit: number, extra: number, count: number): WhatIf {
  const f = serviceOf(s, service)!;
  const b = budgetOf(f, limit, extra);
  const behind = setUp(s).includes('qobuz') && service !== 'qobuz';
  const g = gate(s)!;
  const own = budgetOf(f);
  const remaining = g.remaining - own.remaining + b.remaining, total = g.limit - own.limit + limit;
  return { limit, extra_today: extra, assessment: assessment(service, limit), allowance_today: b.allowance,
    remaining_today: b.remaining, days_to_load: behind ? null : daysToLoad(count, remaining, total),
    run_minutes: Math.max(1, Math.round(Math.min(count, b.remaining) * 0.75)) };
}
export function limits(s: FakeState, service: Service, count: number): Limits {
  const f = serviceOf(s, service);
  if (!f) return { service, cards: cards(s), usage: null };
  const today = new Date(s.now);
  const days = f.days.map((used, i) => {
    const d = new Date(today); d.setDate(d.getDate() - (13 - i));
    return { date: d.toISOString().slice(0, 10), used: i === 13 ? f.used_today : used };
  });
  const summary: Partial<Record<AnySignalKind, number>> = Object.fromEntries(SIGNAL_KINDS[service].map((k) => [k, 0]));
  for (const g of f.signals) if (g.kind in summary) summary[g.kind] = (summary[g.kind] ?? 0) + 1;
  const behind = setUp(s).includes('qobuz') && service !== 'qobuz' ? 'Qobuz' : null;
  const g = gate(s)!;
  const usage: ServiceUsage = {
    service, name: NAMES[service], behind, today: budgetOf(f), days,
    still_to_load: behind ? { count: null, days: null, fits_today: null }
      : { count, days: daysToLoad(count, g.remaining, g.limit), fits_today: count <= g.remaining },
    setting: { limit: f.limit, extra_today: f.extra_today, recommended: RECOMMENDED[service], zones: zones(service),
      min: 1, max: 500, extra_max: 200 },
    assessment: assessment(service, f.limit), what_if: whatIf(s, service, f.limit, f.extra_today, count),
    signals: signalsOf(s, f), signal_summary: summary, last_download: f.last_download,
  };
  return { service, cards: cards(s), usage };
}
