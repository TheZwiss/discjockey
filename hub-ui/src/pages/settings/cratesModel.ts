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
  `${count(f.crates.length)} folders with music, too many for the sidebar: switch on some, or search, then use All.`;

/** The group's head: "<folder> in the sidebar", or just "In the sidebar" when the name is too long for the head. */
export const GROUP_NAME_MAX = 30;
export const groupLabel = (name: string): string => (name.length > GROUP_NAME_MAX ? 'In the sidebar' : `${name} in the sidebar`);

export type CrateChange = { path: string; shown: boolean | null };
/** What a run of saves answers: the paths stored (in order), and the refusal that stopped it (null when none). */
export type CrateSaveResult = { saved: string[]; failed: unknown };
export type CrateSavesIO = {
  folder: () => WatchedFolderRow;
  /** stores the changes one after the other and stops at the first refusal */
  send: (changes: CrateChange[]) => Promise<CrateSaveResult>;
  /** reads the folders again, so the rows then show what is stored */
  reload: () => Promise<void>;
  /** the switches whose save is under way, by path: their value shows instead of the stored one */
  pending: (p: Record<string, boolean>) => void;
  /** a save was refused */
  failed: () => void;
};

/**
 * The saves behind the switches. A click shows its value at once (`pending`) and is sent after every earlier click
 * (one chain, so a later click is always stored after an earlier one, also a second All · None during the first,
 * which is queued; its changes are worked out against what the rows show). Each path remembers which click set it
 * last: an older answer never takes back a newer click. When a run stops at a refusal (`busy` after k of n), the
 * unsaved ones are put back before the folders are read again, the saved ones keep their value until after it, so
 * nothing flickers back and forth. Resolves when that click's save is done.
 */
export function crateSaves(io: CrateSavesIO): (keys: string[], on: boolean) => Promise<void> {
  let pending: Record<string, boolean> = {};
  const owner = new Map<string, number>();
  let seq = 0;
  let tail: Promise<void> = Promise.resolve();
  const release = (paths: string[], mine: number) => {
    const next = { ...pending };
    for (const p of paths) if (owner.get(p) === mine) { owner.delete(p); delete next[p]; }
    pending = next;
    io.pending({ ...pending });
  };
  async function run(changes: CrateChange[], mine: number) {
    let r: CrateSaveResult;
    try { r = await io.send(changes); } catch (e) { r = { saved: [], failed: e ?? true }; }
    const stored = new Set(r.saved);
    release(changes.filter((c) => !stored.has(c.path)).map((c) => c.path), mine);
    if (r.saved.length) { try { await io.reload(); } catch { /* the rows keep what they show */ } }
    release(r.saved, mine);
    if (r.failed) io.failed();
  }
  return (keys, on) => {
    const changes = crateChanges(io.folder(), keys, on, pending);
    if (!changes.length) return Promise.resolve();
    const mine = ++seq;
    for (const c of changes) owner.set(c.path, mine);
    pending = { ...pending, ...Object.fromEntries(changes.map((c) => [c.path, on])) };
    io.pending({ ...pending });
    const done = tail.then(() => run(changes, mine));
    tail = done.catch(() => undefined);
    return done;
  };
}
