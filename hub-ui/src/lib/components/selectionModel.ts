// Multi-select in a list (issue 33 stage B plan §6.1; To-do now, the Library table later): pure, keyed by the list's
// own keys. A selection is its keys in the order they were picked and an anchor, the key the next ⇧-click ranges from
// and ↑ ↓ move from. Several keys can be selected only inside one scope (To-do: an item's group): `scopeOf(key)` names
// it, null for a key that never takes part in a multi-selection (a plain click selects it alone).
//   click            selects one
//   ⌘-click          toggles the key within the anchor's scope (another scope: starts over with that key)
//   ⇧-click          the range anchor…key within the scope, in list order (the anchor stays)
//   ⌘A               every key of the anchor's scope
//   Escape           back to the anchor alone
//   ↑ / ↓            a single selection moves (a multi-selection ends at the anchor's neighbour)
export type Selection = { keys: string[]; anchor: string | null };
export type Mods = { meta?: boolean; shift?: boolean };
export type ScopeOf = (key: string) => string | null;

export const NONE: Selection = { keys: [], anchor: null };
/** One key selected (null: nothing). */
export function single(key: string | null): Selection {
  return key === null ? NONE : { keys: [key], anchor: key };
}
/** The one key when exactly one is selected, else null. */
export function only(sel: Selection): string | null {
  return sel.keys.length === 1 ? sel.keys[0] : null;
}
export const isSelected = (sel: Selection, key: string): boolean => sel.keys.includes(key);
/** The scope a multi-selection can grow in: the anchor's, null when the anchor can't take part in one. */
export function scopeOfSel(sel: Selection, scopeOf: ScopeOf): string | null {
  return sel.anchor === null ? null : scopeOf(sel.anchor);
}

export function click(sel: Selection, key: string, mods: Mods, order: string[], scopeOf: ScopeOf): Selection {
  const scope = scopeOf(key);
  const same = scope !== null && sel.anchor !== null && scopeOf(sel.anchor) === scope && sel.keys.length > 0;
  if (!same || (!mods.meta && !mods.shift)) return single(key);
  if (mods.shift) {
    const a = order.indexOf(sel.anchor as string);
    const b = order.indexOf(key);
    if (a < 0 || b < 0) return single(key);
    const [lo, hi] = a <= b ? [a, b] : [b, a];
    const keys = order.slice(lo, hi + 1).filter((k) => scopeOf(k) === scope);
    return { keys, anchor: sel.anchor };
  }
  // ⌘: toggle; a key going out that was the anchor hands it to the last key picked before it
  if (sel.keys.includes(key)) {
    const keys = sel.keys.filter((k) => k !== key);
    return { keys, anchor: sel.anchor === key ? keys.at(-1) ?? null : sel.anchor };
  }
  return { keys: [...sel.keys, key], anchor: key };
}

/** ⌘A: every key of the anchor's scope, in list order; unchanged when the anchor takes part in none. */
export function selectAll(sel: Selection, order: string[], scopeOf: ScopeOf): Selection {
  const scope = scopeOfSel(sel, scopeOf);
  if (scope === null) return sel;
  return { keys: order.filter((k) => scopeOf(k) === scope), anchor: sel.anchor };
}
/** Every key of one scope, the first one the anchor ("Upgrade all · n" selects its group). */
export function selectScope(scope: string, order: string[], scopeOf: ScopeOf): Selection {
  const keys = order.filter((k) => scopeOf(k) === scope);
  return keys.length ? { keys, anchor: keys[0] } : NONE;
}
/** Escape: back to the anchor alone. */
export function escape(sel: Selection): Selection {
  return sel.keys.length > 1 && sel.anchor !== null ? single(sel.anchor) : sel;
}
/** ↑ (-1) / ↓ (+1) from the anchor, one key selected; stays at the ends; with nothing selected the first key. */
export function move(sel: Selection, order: string[], delta: number): Selection {
  if (!order.length) return NONE;
  const pos = sel.anchor === null ? -1 : order.indexOf(sel.anchor);
  if (pos < 0) return single(order[0]);
  return single(order[Math.max(0, Math.min(order.length - 1, pos + delta))]);
}
/** One key out of the selection (the selection panel's ✕); the anchor goes to the last key left. */
export function drop(sel: Selection, key: string): Selection {
  if (!sel.keys.includes(key)) return sel;
  const keys = sel.keys.filter((k) => k !== key);
  return { keys, anchor: sel.anchor === key ? keys.at(-1) ?? null : sel.anchor };
}

/** The selection after the list changed (`after`: its keys now). Keys that left drop out; an anchor that left goes to
 *  the nearest key still selected. When none is left, `fallback(anchor)` decides the one key (To-do: its
 *  keepSelection, the item now in its place); by default the key now at the anchor's old place in `before`, else the
 *  one before it, else nothing. */
export function keep(sel: Selection, before: string[], after: string[],
  fallback: (anchor: string | null) => string | null = (a) => near(a, before, after)): Selection {
  const here = new Set(after);
  const keys = sel.keys.filter((k) => here.has(k));
  if (!keys.length) return single(fallback(sel.anchor));
  if (sel.anchor !== null && here.has(sel.anchor)) return { keys, anchor: sel.anchor };
  // the anchor left: the selected key nearest to its old place (the next one down, else the last above)
  const pos = sel.anchor === null ? -1 : before.indexOf(sel.anchor);
  const rank = (k: string) => before.indexOf(k);
  const below = keys.filter((k) => rank(k) > pos).sort((a, b) => rank(a) - rank(b));
  const above = keys.filter((k) => rank(k) <= pos).sort((a, b) => rank(b) - rank(a));
  return { keys, anchor: below[0] ?? above[0] ?? keys[0] };
}
function near(anchor: string | null, before: string[], after: string[]): string | null {
  if (!after.length) return null;
  const pos = anchor === null ? -1 : before.indexOf(anchor);
  if (pos < 0) return null;
  return after[Math.min(pos, after.length - 1)];
}
