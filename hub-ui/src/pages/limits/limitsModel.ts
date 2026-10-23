// Download limits page: pure helpers for texts and decisions, tested in limitsModel.test.ts. The page answers three
// questions in order (mockup design-system/limits.html): are my accounts okay (cards, warning signs), how far am I
// (today, the backlog, the 14 days), and what would another limit do (the panel).
import type { AnySignalKind, LimitCard, Service, ServiceUsage, Signal } from '$lib/bridge/types';
import { estimate, estimateText, plural } from '$lib/format';

export type Zone = { name: string; from: number; to: number };
export type Draft = { limit: number; extra: number };

/** The risk scale's track ends here; the number field takes values up to `setting.max`. */
export const SLIDER_MAX = 150;
export const WHAT_IF_THROTTLE_MS = 150;

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Index of the zone a value falls in (0 careful … 4 risky). */
export function zoneIndex(value: number, zones: Zone[]): number {
  const i = zones.findIndex((x) => value >= x.from && value <= x.to);
  return i >= 0 ? i : value < (zones[0]?.from ?? 1) ? 0 : zones.length - 1;
}
/** The risk tone of a zone (design language §2, risk colours): careful and normal safe, faster and fast easier to
 * notice, risky high. */
export type Risk = 'safe' | 'notice' | 'high';
export const RISK: Risk[] = ['safe', 'safe', 'notice', 'notice', 'high'];
export const riskOf = (value: number, zones: Zone[]): Risk => RISK[zoneIndex(value, zones)] ?? 'high';
export const RISK_TONE: Record<Risk, 'good' | 'warn' | 'problem'> = { safe: 'good', notice: 'warn', high: 'problem' };

/** The verdict per assessment level, in plain words: a title and what it means. */
export const VERDICT: Record<number, { title: string; sub: string }> = {
  1: { title: 'Slow and very careful', sub: 'The safest pace; the backlog takes longer.' },
  2: { title: 'The recommended pace', sub: 'Steady, like someone who listens a lot.' },
  3: { title: 'A bit faster, a bit easier to notice', sub: 'Fine now and then; keep an eye on warning signs.' },
  4: { title: 'Faster, but easier to notice', sub: 'More likely to trigger checks or refused downloads.' },
  5: { title: 'Risky: this many a day stands out', sub: 'Accounts get blocked for traffic like this.' },
};
export function verdict(level: number): { title: string; sub: string } {
  return VERDICT[Math.min(5, Math.max(1, Math.round(level)))];
}

/** A value and how it compares with the saved setting: null when equal, else "instead of …" and whether it's better
 * (fewer days, a shorter run: shown in green). */
export type Compare = { value: string; unit: string; was: string | null; better: boolean };
export function compareDays(next: number, saved: number): Compare {
  return { value: String(next), unit: next === 1 ? 'day' : 'days',
    was: next === saved ? null : `instead of ${plural(saved, 'day')}`, better: next < saved };
}
export function compareRun(nextMin: number, savedMin: number): Compare {
  const e = estimate(nextMin), now = estimateText(nextMin), was = estimateText(savedMin);
  return { value: e.value, unit: e.unit, was: now === was ? null : `instead of ${was}`, better: nextMin < savedMin };
}

/** Back / Save are always in the foot, off until the draft differs from the saved setting. */
export function isChanged(d: Draft, saved: { limit: number; extra_today: number }): boolean {
  return d.limit !== saved.limit || d.extra !== saved.extra_today;
}
export function footerLabels(d: Draft, saved: { limit: number; extra_today: number }): { back: string; save: string } {
  if (d.limit !== saved.limit) return { back: `Back to ${saved.limit}`, save: `Save ${d.limit} a day` };
  if (d.extra !== saved.extra_today) return { back: 'Undo', save: d.extra ? `Save +${d.extra} for today` : 'Save' };
  return { back: 'Undo', save: 'Save' };
}

export function clampLimit(v: number, max: number): number {
  return Math.min(max, Math.max(1, Math.round(v)));
}
/** The extra-for-today choices: None, +5, +10, +20, +40 (up to the max), plus the saved amount when it is another
 * one (set from the console with --extra), so the strip always shows what is set. */
export function extraOptions(saved: number, max: number): { key: string; label: string }[] {
  const amounts = [...new Set([0, 5, 10, 20, 40, saved])].filter((n) => n <= max).sort((a, b) => a - b);
  return amounts.map((n) => ({ key: String(n), label: n ? `+${n}` : 'None' }));
}

// ---------- today, the backlog and the 14 days ----------

export function dayMonth(iso: string): string {
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
}
function hhmm(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}
function sameDay(iso: string, now: Date): boolean {
  const d = new Date(iso);
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
}

/** The line under today's bar: where today's allowance comes from (when it resets sits behind its ⓘ). */
export function todayLine(u: ServiceUsage): string {
  const t = u.today;
  const adds = [t.carry_over ? `${t.carry_over} carried over` : '', t.extra ? `${t.extra} extra` : ''].filter(Boolean);
  return adds.length ? [String(t.limit), ...adds].join(' + ') : `${t.limit} a day`;
}
/** "last download 21:47" (today) or "last download 18 Oct"; null before the first. */
export function lastDownload(u: ServiceUsage, now: Date = new Date()): string | null {
  if (!u.last_download) return null;
  return `last download ${sameDay(u.last_download, now) ? hhmm(u.last_download) : dayMonth(u.last_download)}`;
}

/** The backlog beside today: the tracks still to load and when they're done at the saved limit. */
export type Backlog = { value: string; unit: string; line: string; done: boolean };
export function backlog(u: ServiceUsage): Backlog {
  const s = u.still_to_load;
  if (u.behind) return { value: '—', unit: '', line: `${u.behind} sets the pace`, done: false };
  const count = s.count ?? 0;
  const unit = count === 1 ? 'track' : 'tracks';
  if (!count) return { value: '0', unit, line: 'Nothing waiting to download', done: true };
  if (s.fits_today) return { value: String(count), unit, line: 'done today', done: true };
  return { value: String(count), unit, line: `about ${plural(s.days ?? 0, 'day')} at ${u.setting.limit} a day`, done: false };
}

export function dayLabel(date: string, last: boolean): string {
  return last ? 'today' : String(new Date(`${date}T12:00:00`).getDate());
}
export function barTooltip(date: string, used: number, zone: string): string {
  return `${dayMonth(date)} · ${plural(used, 'download')}${used ? ` · ${zone}` : ''}`;
}

// ---------- the service cards ----------

export const pageTitle = 'Download limits';
export const SERVICES: Service[] = ['qobuz', 'youtube', 'soundcloud'];
export const isService = (v: string | undefined): v is Service => !!v && (SERVICES as string[]).includes(v);
export function defaultService(cards: LimitCard[]): Service {
  return cards.find((c) => c.set_up)?.service ?? 'qobuz';
}
/** A card's status, colour plus shape: paused today (red ▪), new warnings (yellow !), else all good (green ✓);
 * warnings already seen ("Got it") keep it green and say how many. */
export function serviceStatus(c: LimitCard): { tone: 'good' | 'warn' | 'problem'; text: string } | null {
  if (!c.set_up) return null;
  if (c.paused) return { tone: 'problem', text: 'Paused today' };
  if (c.new_warnings) return { tone: 'warn', text: plural(c.new_warnings, 'new warning') };
  if (c.warnings) return { tone: 'good', text: `All good · ${c.warnings} seen` };
  return { tone: 'good', text: 'All good' };
}

export const HONEST_NOTE: Record<Service, string> = {
  qobuz: "Qobuz doesn't publish limits, so these levels are cautious estimates, not knowledge. Many downloads on one "
    + 'day after a long break look worse than a steady daily amount, so only part of an unused day carries over.',
  youtube: 'YouTube publishes no limits and is known to block accounts with unusual traffic. For most people this is '
    + "their Google account, with Gmail. Downloading breaks YouTube's terms. Keep the limit low; the pauses and the "
    + "automatic stop lower the risk but don't remove it.",
  soundcloud: "SoundCloud doesn't publish limits either, so these levels are cautious estimates. Downloading breaks "
    + "SoundCloud's terms; the pauses and the automatic stop lower the risk but don't remove it.",
};

// ---------- warning signs ----------

export const SIGNAL_ORDER: Record<Service, AnySignalKind[]> = {
  qobuz: ['login_failed', 'search_failed', 'download_rejected', 'preview_only', 'duration_mismatch', 'auto_stop'],
  youtube: ['cookies_unreadable', 'bot_check', 'rate_limited', 'refused', 'premium_missing', 'download_rejected',
    'auto_stop'],
  soundcloud: ['cookies_unreadable', 'rate_limited', 'refused', 'premium_missing', 'download_rejected', 'auto_stop'],
};
const SIGNAL_OK: Record<AnySignalKind, string> = {
  login_failed: 'Login always worked',
  search_failed: 'No failed searches',
  download_rejected: 'No refused downloads',
  preview_only: 'No preview-only files',
  duration_mismatch: 'Lengths always matched',
  auto_stop: 'Never paused',
  cookies_unreadable: 'Browser login always readable',
  bot_check: 'No “not a bot” checks',
  rate_limited: 'Never asked to slow down',
  refused: 'No refused requests',
  premium_missing: 'Premium formats always there',
};
const SIGNAL_BAD: Record<AnySignalKind, string> = {
  login_failed: 'Login failed',
  search_failed: 'Search failed',
  download_rejected: 'Download refused',
  preview_only: 'Preview-only file',
  duration_mismatch: 'Length didn’t match',
  auto_stop: 'Paused',
  cookies_unreadable: 'Browser login not readable',
  bot_check: '“Not a bot” check',
  rate_limited: 'Asked to slow down',
  refused: 'Request refused',
  premium_missing: 'Premium formats missing',
};

/** One row per kind of this service. A kind that happened: its name, the count, the latest time and message,
 * whether any is new (after "Got it") and when the kind clears (its newest sign leaves the 14 days). Kinds that
 * happened come first (newest first), then the quiet ones in the service's order. */
export type WarningRow = { kind: AnySignalKind; ok: false; title: string; count: number; latest: string;
  isNew: boolean; clearsIn: number; time: string } | { kind: AnySignalKind; ok: true; title: string };
export function warningRows(service: Service, signals: Signal[]): WarningRow[] {
  const bad: WarningRow[] = [], ok: WarningRow[] = [];
  for (const kind of SIGNAL_ORDER[service]) {
    const of = signals.filter((g) => g.kind === kind).sort((a, b) => (a.time < b.time ? 1 : -1));
    if (!of.length) { ok.push({ kind, ok: true, title: SIGNAL_OK[kind] }); continue; }
    const last = of[0];
    bad.push({ kind, ok: false, title: SIGNAL_BAD[kind], count: of.length,
      latest: `${dayMonth(last.time)} ${hhmm(last.time)} · ${last.message}`, isNew: of.some((g) => g.new),
      clearsIn: Math.max(...of.map((g) => g.clears_in)), time: last.time });
  }
  bad.sort((a, b) => ((a as { time: string }).time < (b as { time: string }).time ? 1 : -1));
  return [...bad, ...ok];
}
export const clearsText = (days: number): string => (days <= 1 ? 'clears tomorrow' : `clears in ${days} days`);

/** Signs that say "too fast", with how the suggestion line names them. A failed login or an unreadable browser
 * login is an account problem, not a pace one: no suggestion for those. */
const PACE: Partial<Record<AnySignalKind, (n: number) => string>> = {
  download_rejected: (n) => `refused ${plural(n, 'download')}`,
  search_failed: (n) => `failed ${plural(n, 'search', 'searches')}`,
  preview_only: (n) => `sent ${plural(n, 'preview-only file')}`,
  bot_check: (n) => `asked ${n === 1 ? 'once' : `${n} times`} whether you're a bot`,
  rate_limited: (n) => `asked ${n === 1 ? 'once' : `${n} times`} to slow down`,
  refused: (n) => `refused ${plural(n, 'request')}`,
  auto_stop: (n) => `made Discjockey pause ${n === 1 ? 'once' : `${n} times`}`,
};
export const SUGGESTION_WHY = 'A slower pace makes that less likely.';
/** A slower limit to try when at least two new signs from the last 7 days point at going too fast (one failed
 * search is noise) and the limit is above the careful zone: "Qobuz refused 3 downloads this week." (+ SUGGESTION_WHY) and "Try 40 a day" (the top of careful).
 * Null otherwise. */
export function suggestion(u: ServiceUsage, current: number): { text: string; limit: number } | null {
  const careful = u.setting.zones[0]?.to ?? 1;
  if (current <= careful) return null;
  const recent = u.signals.filter((g) => g.new && g.clears_in >= 8 && PACE[g.kind]);
  if (recent.length < 2) return null;
  const counts = new Map<AnySignalKind, number>();
  for (const g of recent) counts.set(g.kind, (counts.get(g.kind) ?? 0) + 1);
  const [kind, n] = [...counts].sort((a, b) => b[1] - a[1] || (a[0] === 'auto_stop' ? 1 : -1))[0];
  return { text: `${u.name} ${PACE[kind]!(n)} this week.`, limit: careful };
}
