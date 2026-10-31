// What To-do and the Library share of "the track just acted on stays in view" (a Replace, Discard, Done, Undo or Keep
// in the details): which row of a fresh answer is the held one, and putting it back where it stood. Each page keeps
// its own hold (what it is held under: the view, the search, the filter) and its own answer type.

/** The held row among `rows`: the track itself, else (a duplicate's Keep) the one whose file stayed. `keep`: the paths
 *  of the files that stay, null for every other action. */
export function heldRow<R extends { track_id: string; path: string | null }>(rows: R[],
  h: { id: string; keep: string[] | null }): R | null {
  const own = rows.find((r) => r.track_id === h.id);
  if (own) return own;
  const keep = h.keep;
  return keep ? rows.find((r) => !!r.path && keep.includes(r.path)) ?? null : null;
}

/** `list` with `item` put in at `at` (past the end: last). */
export function putAt<T>(list: T[], item: T, at: number): T[] {
  const i = Math.max(0, Math.min(at, list.length));
  return [...list.slice(0, i), item, ...list.slice(i)];
}
