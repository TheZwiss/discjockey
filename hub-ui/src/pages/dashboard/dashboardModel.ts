// Pure text/logic for the dashboard and the run history (Task 66). The Svelte files only lay it out.
import { EMPTY } from '$lib/copy';
import type { Dashboard, EmptyKind, RunSummary } from '$lib/bridge/types';
import type { DayBarInput } from '$lib/components/dayBarModel';
import { daysToLoad } from '$lib/days';
import { runCount, runTime } from '../sync/planModel';
import { buildHash } from '$lib/router';
import { minutesLong, percent, plural, runWhen } from '$lib/format';

type Tiles = Dashboard['tiles'];
type Ready = NonNullable<Dashboard['ready']>;

/** " · 3 not found" when playlist tracks have no file: these are counted here (tracks in playlists) but not in the sidebar (files). */
const notFound = (n: number): string => (n > 0 ? ` · ${n} not found` : '');

// ---------- the library's health (the list's first card) ----------
export function healthCard(t: Tiles['lossless'], empty: EmptyKind | null): { value: string | null; unit?: string; label: string } {
  if (empty === 'empty_library' || t.share === null || !t.total) return { value: null, unit: undefined, label: 'lossless · no tracks yet' };
  return { value: String(Math.round(t.share * 100)), unit: '%',
    label: `lossless · ${t.lossless} of ${plural(t.total, 'track')}${notFound(t.by_quality.missing)}` };
}

// ---------- the next sync (the panel) ----------
/** The panel's state (spec "design system" §8, Dashboard): the hub's own sync running; Spotify not read yet (`line`
 *  points up to the header's Read Spotify, its one place, spec §11; null while it can't read); nothing to do; or
 *  ready, counted like Sync's panel counts its run: what runs today (`runCount`), its time, and the whole day of the
 *  service that counts as a day-mode DayBar (used today · this sync · left, or later when it needs more). */
export type NextSync =
  | { state: 'running' }
  | { state: 'unread'; line: string | null }
  | { state: 'up_to_date'; day: DayBarInput | null; limits: Limits; checks: number }
  | { state: 'ready'; count: number; time: { value: string; unit: string };
      day: DayBarInput; limits: Limits; limitReached: boolean };
type Limits = { text: string; full: string } | null;

/** The service whose daily limit counts (the engine's gate: Qobuz when it is set up, else the first account), and
 *  what it used today. */
function gate(t: Tiles): { name: string; used: number; carry: number } {
  const a = t.account_today;
  if (a && a.service !== 'qobuz') return { name: a.name, used: a.used, carry: 0 };
  return { name: 'Qobuz', used: t.qobuz_today.used, carry: t.qobuz_today.carry_over };
}

/** The day card's line: the service and what it allows today, the total the bar's segments add up to (`text`),
 *  and how that total comes about for the tooltip (`full`); null without a daily limit (the DayBar says "No daily
 *  limit"). The short form fits the 320 px panel beside "Download limits →". */
function limitsLine(t: Tiles, r: Ready): { text: string; full: string } | null {
  if (r.left === null) return null;
  const g = gate(t);
  return { text: `${g.name} · ${g.used + Math.max(r.left, 0)} today`,
    full: `${g.name}: ${r.limit} a day${g.carry ? ` + ${g.carry} carried over` : ''}` };
}

/** The whole day: what earlier runs used, then this sync's downloads, then what is left (`used + left` is the day's
 *  allowance, so the segments add up with the engine's `left`) or what waits for later days. */
function dayInput(t: Tiles, r: Ready): DayBarInput {
  const limited = r.left !== null;
  const after = r.qobuz_needed - r.qobuz_uses;
  const left = Math.max(r.left ?? 0, 0);
  const used = gate(t).used;
  return { today: r.qobuz_uses, later: limited ? after : 0, limited,
    laterDays: limited && after > 0 ? daysToLoad(after, left - r.qobuz_uses, r.limit) : 0,
    day: limited ? { used, allowance: used + left } : undefined };
}

export function nextSync(d: Pick<Dashboard, 'ready' | 'tiles' | 'next_checks'>, running: boolean, canRead: boolean): NextSync {
  if (running) return { state: 'running' };
  const r = d.ready;
  if (!r) return { state: 'unread', line: canRead ? EMPTY.no_preview.body ?? null : null };
  if (!r.actions) return { state: 'up_to_date', checks: d.next_checks, limits: limitsLine(d.tiles, r),
    day: r.left === null ? null : dayInput(d.tiles, r) };
  const count = runCount(r.actions, r.qobuz_needed, r.qobuz_uses);
  return { state: 'ready', count, time: runTime(r.duration_min, count), day: dayInput(d.tiles, r),
    limits: limitsLine(d.tiles, r), limitReached: r.left === 0 && r.qobuz_needed > 0 };
}

// ---------- needs you ----------
/** One row of Needs you: the label and its count apart (the count sits in the list's number column, as in Sync's
 *  Could be better), the detail under it, and the To-do filter it opens. At most these three, so the list never
 *  grows past them. `tone` colours the icon: good news (an upgrade) or a problem. */
export type NeedRow = { key: 'upgrades' | 'not_found' | 'weak'; label: string; n: number; sub: string; href: string;
  tone: 'good' | 'problem' };

const todo = (filter: string) => buildHash('/todo', {}, { filter });

export function needsRows(n: Dashboard['needs_you']): NeedRow[] {
  const rows: NeedRow[] = [];
  if (n.upgrades) rows.push({ key: 'upgrades', label: n.upgrades === 1 ? 'Upgrade ready' : 'Upgrades ready', n: n.upgrades,
    sub: n.swappable ? `${n.swappable} can be swapped, cues stay` : 'listen and decide', href: todo('upgrade_ready'),
    tone: 'good' });
  if (n.not_found) rows.push({ key: 'not_found', label: 'Not found', n: n.not_found, sub: 'buy links ready',
    href: todo('not_found'), tone: 'problem' });
  if (n.weak) rows.push({ key: 'weak', label: n.weak === 1 ? 'Weak version' : 'Weak versions', n: n.weak,
    sub: 'audibly lossy (≤ 17 kHz)', href: todo('weak'), tone: 'problem' });
  return rows;
}

// ---------- folders ----------
/** `short` for the folder row's number column, `full` (with the not found, which the short form leaves to the
 *  quality bar) for its tooltip. */
export function folderLine(f: Dashboard['folders'][number]): { short: string; full: string } {
  if (!f.tracks) return { short: 'empty', full: `${f.folder} · empty` };
  const share = percent(f.lossless_share);
  return { short: `${f.tracks} · ${share}`,
    full: `${f.folder} · ${plural(f.tracks, 'track')} · ${share} lossless${notFound(f.by_quality.missing)}` };
}

// ---------- runs ----------
export type RunPart = { text: string; tone: 'ok' | 'warn' | 'bad' | null };
/** `status` is the run's mark: finished (`ok`), some tracks failed (exit 1, `failed`), stopped by the user (exit 130 or
 *  `stopped_after`, `stopped`: not a problem, so not red). */
export type RunLine = { title: string; parts: RunPart[]; note: string | null; href: string; status: 'ok' | 'failed' | 'stopped' };

export function runHref(run_id: string): string {
  return buildHash('/sync/run/:run_id', { run_id });
}

export function runLine(r: RunSummary, now: Date | number = new Date()): RunLine {
  const length = r.duration_s === null ? null : minutesLong(r.duration_s / 60);
  const c = r.counts;
  const parts: RunPart[] = [];
  if (c.lossless) parts.push({ text: `${c.lossless} lossless`, tone: 'ok' });
  if (c.lossy) parts.push({ text: `${c.lossy} lossy`, tone: 'warn' });
  if (c.problems) parts.push({ text: plural(c.problems, 'problem'), tone: 'bad' });
  if (c.moved) parts.push({ text: `${c.moved} moved`, tone: null });
  if (!parts.length) parts.push({ text: 'nothing changed', tone: null });
  const note = r.stopped_after !== null ? `stopped by you after ${plural(r.stopped_after, 'track')}`
    : r.exit_code === 130 ? 'stopped by you' : null;
  const status = r.stopped_after !== null || r.exit_code === 130 ? 'stopped' : r.exit_code === 0 ? 'ok' : 'failed';
  return { title: [runWhen(r.started, now), length].filter(Boolean).join(' · '), parts, note, href: runHref(r.run_id),
    status };
}

/** All runs' panel: the runs and what they did, added up (added = lossless + lossy, as the end screen counts it). */
export function runTotals(runs: RunSummary[]): { runs: number; added: number; moved: number; problems: number } {
  return runs.reduce((t, r) => ({ runs: t.runs + 1, added: t.added + r.counts.lossless + r.counts.lossy,
    moved: t.moved + r.counts.moved, problems: t.problems + r.counts.problems }), { runs: 0, added: 0, moved: 0, problems: 0 });
}

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
  'November', 'December'];
export const GROUP_FROM = 10;

/** Runs as they come (newest first); more than GROUP_FROM → one group per month with a label. */
export function groupByMonth(runs: RunSummary[]): { label: string | null; runs: RunSummary[] }[] {
  if (runs.length <= GROUP_FROM) return [{ label: null, runs }];
  const out: { label: string; runs: RunSummary[] }[] = [];
  for (const r of runs) {
    const d = new Date(r.started);
    const label = Number.isNaN(d.getTime()) ? 'Earlier' : `${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
    const last = out.at(-1);
    if (last?.label === label) last.runs.push(r);
    else out.push({ label, runs: [r] });
  }
  return out;
}
