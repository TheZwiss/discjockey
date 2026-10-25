// Part B pure logic: the result list below the live card (filter segments, Problems / Done, message line, covers).
import type { Result } from '$lib/bridge/types';
import type { SegOption } from '$lib/components/segmentedModel';
import { foundLossless, sourceName, verdict } from './cardState';

export type ListChip = 'all' | 'lossless' | 'lossy' | 'problems';
export const PROBLEM_SECTIONS = new Set(['missing', 'errors', 'conflicts', 'ambiguous']);

export const isProblem = (r: Result) => PROBLEM_SECTIONS.has(r.section);
// An upgrade check's result.status is the current file's: the quality it counts and is badged by is the found file's.
export const isLossless = (r: Result) =>
  !isProblem(r) && (r.section === 'upgrade_ready' ? foundLossless(r) : r.status === 'lossless');
export const isLossy = (r: Result) => !isProblem(r)
  && (r.section === 'upgrade_ready' ? !foundLossless(r) : r.status === 'not_lossless' || r.status === 'fake_lossless');

const MATCH: Record<ListChip, (r: Result) => boolean> = {
  all: () => true, lossless: isLossless, lossy: isLossy, problems: isProblem,
};

export function chipCounts(results: Result[]): Record<ListChip, number> {
  return { all: results.length, lossless: results.filter(isLossless).length, lossy: results.filter(isLossy).length,
    problems: results.filter(isProblem).length };
}

/** The filter strip's segments (spec §8): All · Lossless · Lossy · Problems with their counts; each but All carries
 * the dot of the quality it shows (green, yellow, red: colour plus shape, §4). */
export function segOptions(results: Result[]): SegOption<ListChip>[] {
  const c = chipCounts(results);
  return [
    { key: 'all', label: 'All', count: c.all },
    { key: 'lossless', label: 'Lossless', count: c.lossless, dot: 'lossless' },
    { key: 'lossy', label: 'Lossy', count: c.lossy, dot: 'good_lossy' },
    { key: 'problems', label: 'Problems', count: c.problems, dot: 'weak' },
  ];
}

/** The message line: the last message until a track starts or finishes after it ("Reading your playlists…"
 * goes once the first track starts). */
export function liveMessage(r: { messages: { text: string; at: number }[]; last_started_at: number | null;
  last_finished_at: number | null }): string | null {
  const last = r.messages.at(-1);
  if (!last) return null;
  return Math.max(r.last_started_at ?? 0, r.last_finished_at ?? 0) > last.at ? null : last.text;
}

/** Cover links by track id for the rows: the saved selection's first (the same as in the plan), then the engine's. */
export function coverMap(selection: { track_id: string; cover_url?: string | null }[],
  planned: { track_id: string; image_url?: string | null }[]): Map<string, string> {
  const m = new Map<string, string>();
  for (const a of planned) if (a.image_url) m.set(a.track_id, a.image_url);
  for (const a of selection) if (a.cover_url) m.set(a.track_id, a.cover_url);
  return m;
}

/** The results a chip shows, split into "Problems first" and "Done", each in run order. */
export function listFor(results: Result[], chip: ListChip): { problems: Result[]; done: Result[] } {
  const shown = results.filter(MATCH[chip]);
  return { problems: shown.filter(isProblem), done: shown.filter((r) => !isProblem(r)) };
}

/** The badge of one result row: "NOT FOUND", "NO INTERNET · retried next run", "20.0 kHz · YT Music", "MOVED → X". */
export function rowBadge(r: Result): { tone: ReturnType<typeof verdict>['tone']; text: string } {
  const v = verdict(r);
  if (isProblem(r) && r.error_kind === 'network') return { tone: v.tone, text: 'NO INTERNET · retried next run' };
  const src = sourceName(r.source);
  if (isLossy(r) && src) return { tone: v.tone, text: `${v.label} · ${src}` };
  return { tone: v.tone, text: v.label };
}

/** The to-do link of a problem row (null when the result names no track). */
export const fixHref = (r: Result) => (r.track_id ? `#/todo?track=${encodeURIComponent(r.track_id)}` : null);
