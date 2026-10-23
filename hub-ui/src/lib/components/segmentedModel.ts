// One choice of a few (design system §4): Segmented shows up to `max` options on one line and puts the rest in its
// "More" menu. The chosen option is always on the strip, so the user can see what is picked. Pure, so it is tested.
import type { Quality } from '../bridge/types';

export type SegOption<K extends string> = { key: K; label: string; count?: number | null; dot?: Quality | null };

/** Splits the options into the strip (`shown`, in order) and the "More" menu. When the chosen `value` would land in
 * the menu it takes the strip's last slot, and the option it displaces leads the menu. The input is not changed. */
export function splitOptions<K extends string>(opts: SegOption<K>[], value: K, max = 6):
    { shown: SegOption<K>[]; more: SegOption<K>[] } {
  const n = Math.max(1, Math.floor(max));
  if (opts.length <= n) return { shown: opts, more: [] };
  const shown = opts.slice(0, n);
  const more = opts.slice(n);
  const i = more.findIndex((x) => x.key === value);
  if (i >= 0) {
    const [chosen] = more.splice(i, 1);
    more.unshift(shown[n - 1]);
    shown[n - 1] = chosen;
  }
  return { shown, more };
}

/** The segment that Tab reaches (radio-group rule): the chosen one, or the first when the value matches none of the
 * shown options (e.g. Sync's "custom" amount after ticking rows by hand), so the strip never drops out of the Tab
 * order. null without options. */
export function tabStop<K extends string>(shown: SegOption<K>[], value: K | string): K | null {
  return shown.find((o) => o.key === value)?.key ?? shown[0]?.key ?? null;
}

/** Whether a strip is tight: its segments at their full labels (`natural`, px) need more than its width
 * (`available`). A tight strip lets its unchosen segments shorten, so the chosen one never leaves it. 1 px covers
 * sub-pixel rounding; no segments or no width yet (not laid out) is never tight. */
export function isTight(natural: number[], available: number): boolean {
  if (!natural.length || available <= 0) return false;
  return natural.reduce((a, b) => a + b, 0) > available + 1;
}
