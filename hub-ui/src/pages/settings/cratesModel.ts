// Settings → Watched folders: an import folder's crates as switches (plan library stage 5, B7; D8, D15). Pure, so it
// is tested; FoldersPanel and CrateSwitches render it. A switch says whether the crate is a row in the sidebar's
// Folders; the save is brief (`set_crate_shown`), so the rows show the new state at once (`pending`) and are put back
// when the save is refused.
import type { WatchedFolderRow } from '$lib/bridge/types';
import type { ToggleItem } from '$lib/components/toggleModel';
import { count } from '$lib/components/watchedFoldersModel';
import { crateShownValue } from '$lib/shell/browserModel';

/** More crates than this and All needs a search first (D8's limit: past it the sidebar shows the folder as one row). */
export const ALL_MAX = 25;

const samePath = (p: string): string => p.normalize('NFC').replace(/\/+$/, '');
const hasCrates = (f: WatchedFolderRow) => f.kind === 'import' && f.crates.length > 0;

/** The folder whose crates show: the route's (`#/settings/folders/<path>`, Library's "Show some in the sidebar…"),
 *  matched as a path (NFC, no trailing slash), else the first import folder with crates; null when none has any. */
export function pickedFolder(folders: WatchedFolderRow[] | null | undefined, path: string | undefined): WatchedFolderRow | null {
  const all = (folders ?? []).filter(hasCrates);
  if (path) {
    const want = samePath(path);
    const hit = all.find((f) => samePath(f.path) === want);
    if (hit) return hit;
  }
  return all[0] ?? null;
}

/** The switch rows: label and files as the sidebar shows them, on = in the sidebar (a save under way wins), the full
 *  way from the watched folder as the tooltip, and the folders it sits in as more words to find it by (an album by
 *  its artist's folder, when the label is the album's name alone). */
export function crateItems(f: WatchedFolderRow, pending: Record<string, boolean> = {}): ToggleItem[] {
  return f.crates.map((c) => ({
    key: c.path, label: c.label, count: c.files, on: pending[c.path] ?? !c.hidden, tip: c.tip,
    find: c.tip.split(' › ').slice(1, -1).join(' '),
  }));
}

/** What a switch (or All · None over `keys`) saves: only the crates whose state changes, each with the value
 *  `set_crate_shown` stores (null where the folder's default already gives it, as the browser column saves). */
export function crateChanges(f: WatchedFolderRow, keys: string[], on: boolean, pending: Record<string, boolean> = {}):
  { path: string; shown: boolean | null }[] {
  const now = new Map(crateItems(f, pending).map((i) => [i.key, i.on]));
  return keys.filter((k) => now.has(k) && now.get(k) !== on).map((path) => ({ path, shown: crateShownValue(f.too_many, on) }));
}

/** The note over a folder with too many crates for the sidebar. */
export const tooManyText = (f: Pick<WatchedFolderRow, 'crates'>): string =>
  `${count(f.crates.length)} folders with music, too many for the sidebar: switch on the ones you want to see.`;
