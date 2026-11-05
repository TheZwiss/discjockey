// QualityBar's segments (sources round I4, notes problem 8). Pure, so every share is pinned.
// The bar spans what it is given: the counts by quality and, for a playlist, its songs that have no file yet
// (`waiting`), which end the bar as a dashed segment (the house shape for "waiting to be filled", as `Cover empty`).
import type { ByQuality, Quality } from '../bridge/types';
import { QUALITIES } from '../bridge/types';

export const QUALITY_NAMES: Record<Quality, string> = { lossless: 'lossless', good_lossy: 'good lossy', weak: 'weak',
  fake: 'fake', missing: 'missing' };

export type BarPart = { key: Quality | 'waiting'; n: number; pct: number };

/** The segments in the bar's order, the waiting songs last, each with its width in % of everything the bar spans;
 *  only the parts that have songs. Empty: nothing at all (the bar is its empty track). */
export function barParts(byQuality: ByQuality, waiting = 0): BarPart[] {
  const w = Number.isFinite(waiting) && waiting > 0 ? Math.round(waiting) : 0;
  const counts: [BarPart['key'], number][] = [...QUALITIES.map((q): [Quality, number] => [q, byQuality[q] ?? 0]),
    ['waiting', w]];
  const total = counts.reduce((a, [, n]) => a + n, 0);
  if (!total) return [];
  return counts.filter(([, n]) => n > 0).map(([key, n]) => ({ key, n, pct: (n / total) * 100 }));
}

/** The bar's tooltip and VoiceOver words: "9 lossless · 2 weak · 5 waiting"; '' with nothing. */
export function barTitle(parts: BarPart[]): string {
  return parts.map((p) => `${p.n} ${p.key === 'waiting' ? 'waiting' : QUALITY_NAMES[p.key]}`).join(' · ');
}
