// On/off groups (design system §4 "on/off, several items"): the header's "N of M on" and the search that a group gets
// from seven rows. Pure, so it is tested; ToggleGroup and ToggleRow render it.
import { foldText } from '../format';

export type ToggleItem = { key: string; label: string; count?: number | null; on: boolean;
  /** the row's tooltip (a crate's whole way from its watched folder) */
  tip?: string;
  /** more words the search finds the row by besides its label (a crate's parent folders: an album by its artist) */
  find?: string };

/** A group gets a search field from this many rows. */
export const SEARCH_FROM = 7;

/** "6 of 7 on" — also when all or none are on, so the header never changes shape. */
export const groupSummary = (items: ToggleItem[]) => `${items.filter((i) => i.on).length} of ${items.length} on`;

/** The rows whose name (or `find`) contains the query, ignoring case and accents; all rows for an empty query. */
export function filterItems(items: ToggleItem[], query: string): ToggleItem[] {
  const q = foldText(query.trim());
  return q ? items.filter((i) => foldText(i.label).includes(q) || (!!i.find && foldText(i.find).includes(q))) : items;
}

/** The keys All · None act on: the rows the search shows (all rows for an empty query). */
export const visibleKeys = (items: ToggleItem[], query: string) => filterItems(items, query).map((i) => i.key);

/** The items with the given keys switched on or off, the others unchanged; a new list (the input is not changed). */
export function setOn(items: ToggleItem[], keys: string[], on: boolean): ToggleItem[] {
  const pick = new Set(keys);
  return items.map((i) => (pick.has(i.key) && i.on !== on ? { ...i, on } : i));
}

/** A grow group's sizes (px) as it measures them; `given` is the space the layout gives it, not its own result. */
export type GrowSizes = {
  /** the group's box plus the spare it handed away: the same before and after the spare is applied */
  given: number;
  /** the group's box minus its rows' area: head, its rule, the search, the borders */
  chrome: number;
  /** all rows' height (the scroller's scrollHeight) */
  content: number;
  /** one row plus the rule between two rows (0 with fewer than 2 rows) */
  pitch: number;
  rule: number;
  /** the box's min-height (`--min-rows` whole rows plus the peek, set in CSS): the one source of the peek, so a cut
   *  at the minimum is the min-height's own and a measured half row that rounds apart from it can't leave px over */
  floor: number;
  minRows: number;
  /** each row's top in the rows' area (px from its start), when the rows differ in height (a wrapping sub-line, a
   *  section head): the cut then lands the peek into the row it crosses, measured, not counted in pitches */
  tops?: number[];
};

/**
 * The px a cut grow group hands to the space above the foot so that its cut lands a `peek` into a row, never on a
 * row's edge (spec §11, issue 10): the rows' area rounds down to whole rows plus the peek. 0 when the rows fit, at
 * or under the 3-row minimum (its min-height already ends on a peek) and without a row pitch. Less than one row.
 * With `tops` (rows of different heights) the cut is measured: it lands inside the last row whose peek fits, at least
 * a peek into it and half a peek short of its end.
 * The peek is what the min-height holds beyond its whole rows: measured as half a row it once rounded 2 px apart
 * from the CSS, and the group held those 2 px at its minimum (final review M3).
 */
export function growSpare(s: GrowSizes): number {
  const area = s.given - s.chrome;
  if (s.pitch <= 0 || s.content <= area + 0.5) return 0;
  // k whole rows with the k − 1 rules between them, then the peek (which starts with the next row's rule)
  const peek = Math.max(0, s.floor - s.chrome - (s.minRows * s.pitch - s.rule));
  if (s.tops && s.tops.length > s.minRows) {
    // the last row whose peek still fits; the rows above it show whole
    let cut = -1;
    s.tops.forEach((top, i) => { if (top + peek <= area + 1e-6) cut = i; });
    if (cut < s.minRows) return 0;
    // anywhere inside that row: at least the peek shown and at least half a peek still hidden (never on its edge)
    const bottom = cut + 1 < s.tops.length ? s.tops[cut + 1] : s.content;
    const end = Math.max(s.tops[cut] + peek, Math.min(area, bottom - peek / 2));
    return Math.max(0, Math.floor(area - end + 1e-6));
  }
  const rows = Math.floor((area + s.rule - peek) / s.pitch + 1e-6);
  if (rows < s.minRows) return 0;
  return Math.max(0, Math.floor(area - (rows * s.pitch - s.rule + peek) + 1e-6));
}

/** Context key of the host that takes a grow group's spare height (Panel, below its `after`). */
export const GROW_SPARE = Symbol('grow-spare');
/** `set` the px to hold above the foot; `height` is what the spacer really holds now (it gives way first). One grow
 *  group per host: `join` registers it (the host warns in dev about a second one, whose spare would overwrite the
 *  first's) and returns its leave. */
export type GrowSpareHost = { set: (px: number) => void; height: () => number; join: () => () => void };
