// To-do page logic (Task 67, spec §5.3; design system mockup design-system/todo.html): navigation order, selection
// across re-fetches, the filter strip, the list's sections, actions per track and the panel's main action.
import type { SegOption } from '$lib/components/segmentedModel';
import type { FreeDownload, Quality, Todo, TodoFilter, TodoGroupKey, TodoItem, TrackDetail } from '$lib/bridge/types';

/** Filter order = the contract's group order, All first. */
export const FILTER_ORDER: TodoFilter[] = ['all', 'rekordbox_check', 'upgrade_ready', 'not_found', 'weak', 'good_lossy',
  'fake', 'other'];
/** Short, so the strip holds five and More on one line at 1100 (the section heads carry the full names). */
const FILTER_LABEL: Record<TodoFilter, string> = {
  all: 'All', rekordbox_check: 'rekordbox', same_song: 'Same song?', duplicate: 'Duplicates', upgrade_ready: 'Upgrades',
  not_found: 'Not found', weak: 'Weak', good_lossy: 'Good lossy', fake: 'Fake lossless', other: 'Other',
};
const FILTER_DOT: Partial<Record<TodoFilter, Quality>> = {
  upgrade_ready: 'lossless', not_found: 'missing', weak: 'weak', good_lossy: 'good_lossy', fake: 'fake',
};
/** On the strip before More: All and four groups. */
export const FILTER_MAX = 5;

/** The Segmented's options in contract order; groups at zero are left out, except All and the chosen one. */
export function segOptions(chips: Record<TodoFilter, number>, value: TodoFilter): SegOption<TodoFilter>[] {
  return FILTER_ORDER.filter((k) => k === 'all' || k === value || (chips[k] ?? 0) > 0)
    .map((k) => ({ key: k, label: FILTER_LABEL[k], count: chips[k] ?? 0, dot: FILTER_DOT[k] ?? null }));
}

export function isFilter(v: unknown): v is TodoFilter {
  return typeof v === 'string' && (FILTER_ORDER as string[]).includes(v);
}
/** `?filter=` wins over the remembered filter. */
export function filterFrom(query: string | null, saved: string): TodoFilter {
  return isFilter(query) ? query : isFilter(saved) ? saved : 'all';
}

export function headerSub(n: number): string {
  if (!n) return 'Nothing to do';
  return n === 1 ? '1 track is not lossless yet' : `${n} tracks are not lossless yet`;
}

// ---------- navigation ----------
/** A track can be in two groups, so an item is "group/track_id". */
export function itemKey(i: Pick<TodoItem, 'group' | 'track_id'>): string {
  return `${i.group}/${i.track_id}`;
}
const trackOf = (key: string) => key.slice(key.indexOf('/') + 1);

/** Every item in navigation order (the groups come in the contract's order). */
export function flatten(t: Todo | null): TodoItem[] {
  return t ? t.groups.flatMap((g) => g.items) : [];
}

/**
 * The selection after a re-fetch: the same item, else the same track (now in another group), else the item now at
 * the old position, else the previous one. Without a selection: the first item.
 */
export function keepSelection(key: string | null, before: TodoItem[], after: TodoItem[]): string | null {
  if (!after.length) return null;
  if (key === null) return itemKey(after[0]);
  if (after.some((i) => itemKey(i) === key)) return key;
  const same = after.find((i) => i.track_id === trackOf(key));
  if (same) return itemKey(same);
  const pos = before.findIndex((i) => itemKey(i) === key);
  if (pos < 0) return itemKey(after[0]);
  return itemKey(after[Math.min(pos, after.length - 1)]);
}

/** ↑ (-1) / ↓ (+1); stays at the ends. */
export function moveSelection(items: TodoItem[], key: string | null, delta: number): string | null {
  if (!items.length) return null;
  const pos = items.findIndex((i) => itemKey(i) === key);
  if (pos < 0) return itemKey(items[0]);
  return itemKey(items[Math.max(0, Math.min(items.length - 1, pos + delta))]);
}

/** `?track=`: the first item of that track. */
export function selectFromTrack(items: TodoItem[], track_id: string | null): string | null {
  const i = track_id ? items.find((x) => x.track_id === track_id) : undefined;
  return i ? itemKey(i) : null;
}

/** After "Good enough, hide": the next item that is not this track (the previous one at the end). */
export function selectAfterHide(items: TodoItem[], key: string): string | null {
  const pos = items.findIndex((i) => itemKey(i) === key);
  const id = trackOf(key);
  const next = items.slice(pos + 1).find((i) => i.track_id !== id)
    ?? items.slice(0, Math.max(0, pos)).reverse().find((i) => i.track_id !== id);
  return next ? itemKey(next) : null;
}

// ---------- details panel ----------
export type Actions = {
  listen: boolean;                          // ▶ Listen (MiniPlayer), only with a file
  versions: 'find' | 'wrong_song';          // "Find a version" (missing) / "Wrong song?" → candidates dialog
  noneOfThese: boolean;                     // "None of these" in the dialog: not for missing tracks
  buy: boolean;                             // Beatport / Bandcamp links
  dropZone: boolean;                        // bought file: missing, not lossless, fake lossless
  hide: 'hide' | 'unhide' | null;
  upgrade: { swap: boolean; primary: 'swap' | 'add_new' } | null;
  showInFinder: boolean;                    // "Other" items
  rekordboxDone: boolean;                   // "Check in rekordbox" items
  /** the panel foot's one filled button: the to-do's own action; null when it has none in the app (a lossy file
   *  is bought and dropped: its buy links and drop zone are its actions) */
  main: 'swap' | 'add_new' | 'rekordbox' | 'find' | 'finder' | null;
};

const IMPROVABLE = ['missing', 'not_lossless', 'fake_lossless'];

/** What the details panel offers for this track, seen from the selected item's group. */
export function actionsFor(track: TrackDetail, group: TodoGroupKey | null = null): Actions {
  const missing = track.status === 'missing';
  const improvable = IMPROVABLE.includes(track.status);
  const up = track.upgrade;
  const swap = !!up && up.swap_safe && up.swap_possible;
  const check = group === 'rekordbox_check';
  const upgrade = up ? { swap, primary: swap ? 'swap' as const : 'add_new' as const } : null;
  const finder = group === 'other' && !!track.path;
  return {
    listen: !!track.audio_url,
    versions: missing ? 'find' : 'wrong_song',
    noneOfThese: !missing,
    buy: improvable,
    dropZone: improvable,
    hide: track.hidden ? 'unhide' : check ? null : improvable || group === 'other' ? 'hide' : null,
    upgrade,
    showInFinder: finder,
    rekordboxDone: check,
    main: check ? 'rekordbox' : upgrade ? upgrade.primary : missing ? 'find' : finder ? 'finder' : null,
  };
}

/** Under an artist's free download: what the user does there and what they usually get. */
export function freeHint(fs: FreeDownload[]): string {
  return fs.every((f) => f.direct) ? 'The artist\'s own file · usually WAV or 320 kbps MP3'
    : 'For a follow, a like or an e-mail · usually WAV or 320 kbps MP3';
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
/** The "Qobuz" fact from `next_qobuz_check`: ISO date → "not there yet · looks again on 20 Oct", null → nothing. */
export function qobuzText(next: string | null): string | null {
  if (!next) return null;
  if (next === 'next_sync') return 'not there yet · looks again at the next sync';
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(next);
  if (!m) return null;
  return `not there yet · looks again on ${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}`;
}

export { cueTone, cutoffStat, foundText } from '$lib/format';

/** "will be filed as Library/Hard_Bounce/Armin Hermann – Get Naughty" (bought_name without the extension). */
export function filedAs(bought_name: string): string {
  const slash = bought_name.lastIndexOf('/');
  const dir = bought_name.slice(0, slash + 1);
  const name = bought_name.slice(slash + 1).replace(/\.[^.]+$/, '').replace(' - ', ' – ');
  return `${dir}${name}`;
}

// ---------- bought file (part B) ----------
/** The FileDropped event as the page sees it. */
export type DroppedFile = { track_id: string | null; name: string; readable: boolean; message: string };
export type DropDecision = { do: 'add' } | { do: 'message'; text: string } | { do: 'toast' } | { do: 'ignore' };

/** What the drop zone of `selectedId` does with a FileDropped event (plan Task 67, §6.6).
 *  'toast' = nothing selected: the shell (App.svelte) already shows the event's message as a toast. */
export function dropDecision(e: DroppedFile, selectedId: string | null): DropDecision {
  if (e.track_id === null) return { do: 'toast' };
  if (e.track_id !== selectedId) return { do: 'ignore' };
  if (!e.readable) return { do: 'message', text: e.message };
  return { do: 'add' };
}
