// To-do page logic (Task 67, spec §5.3; design system mockup design-system/todo.html): navigation order, selection
// across re-fetches, the filter strip, the list's sections, actions per track and the panel's main action.
import type { SegOption } from '$lib/components/segmentedModel';
import type {
  FileSide, FreeDownload, Quality, QuestionPair, QuestionWhy, Todo, TodoFilter, TodoGroupKey, TodoItem, TrackDetail,
} from '$lib/bridge/types';
import { isDuplicate, isQuestion } from '$lib/bridge/types';
import type { QueueItem } from '$lib/stores/queueModel';
import type { PlayerState } from '$lib/stores/player';
import { duration } from '$lib/format';

/** Filter order = the contract's group order (= the list's section order), All first. The import's two groups come
 *  right after rekordbox: they hold downloads back until they are answered (plan library stage 4 D4), and the strip
 *  reads in the order the sections do. With every group present, the later ones go under More (FILTER_MAX). */
export const FILTER_ORDER: TodoFilter[] = ['all', 'rekordbox_check', 'same_song', 'duplicate', 'upgrade_ready',
  'not_found', 'weak', 'good_lossy', 'fake', 'other'];
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
/** A track can be in two groups, so an item is "group/track_id". The import's items are named by what they are
 *  about: a question by its playlist song and the file of the user's own (one song can be asked about more than one
 *  file), a duplicate group by its id. */
export function itemKey(i: Pick<TodoItem, 'group' | 'track_id' | 'pair'>): string {
  const p = i.pair;
  if (i.group === 'same_song' && p && 'own_key' in p) return `same_song/${p.song_key}/${p.own_key}`;
  if (i.group === 'duplicate' && p && 'group_id' in p) return `duplicate/${p.group_id}`;
  return `${i.group}/${i.track_id}`;
}
const find = (items: TodoItem[], key: string) => items.find((i) => itemKey(i) === key);
/** The file ids of a duplicate group's item (none for every other item). */
const fileIds = (i: TodoItem | undefined): number[] => (i && isDuplicate(i) ? i.pair.files.map((f) => f.file_id) : []);

/** Every item in navigation order (the groups come in the contract's order). */
export function flatten(t: Todo | null): TodoItem[] {
  return t ? t.groups.flatMap((g) => g.items) : [];
}

/**
 * The selection after a re-fetch: the same item, else the same track (now in another group), else the item now at
 * the old position, else the previous one. Without a selection: the first item.
 * The import's items: an answered question or duplicate group is done, so the selection goes on to the item now in
 * its place (the next question) rather than following the song into another group; a duplicate group that lost a
 * file to Superseded/ (its id names its files, so the id changes) stays selected as the group of the files left;
 * one that is gone altogether (Keep all) goes to the next item of its own kind, else to the item in its place.
 */
export function keepSelection(key: string | null, before: TodoItem[], after: TodoItem[]): string | null {
  if (!after.length) return null;
  if (key === null) return itemKey(after[0]);
  if (after.some((i) => itemKey(i) === key)) return key;
  const old = find(before, key);
  const ids = fileIds(old);
  const rest = ids.length ? after.find((i) => fileIds(i).some((id) => ids.includes(id))) : undefined;
  if (rest) return itemKey(rest);
  // an import item that is gone (answered, or kept) hands the selection to the next item of its own kind, so a
  // duplicate stays on a duplicate and a question on a question; only without one does the position decide
  if (old?.pair) {
    const kind = (list: TodoItem[]) => list.filter((i) => i.group === old.group);
    const at = kind(before).findIndex((i) => itemKey(i) === key);
    const peers = kind(after);
    if (peers.length) return itemKey(peers[Math.min(Math.max(at, 0), peers.length - 1)]);
  }
  const same = old && !old.pair ? after.find((i) => !i.pair && i.track_id === old.track_id) : undefined;
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

/** `?track=`: the first item of that track; `file:<id>` (a file of the import's items, playing in the foot: its
 *  link back) selects the question or duplicate group that file is in. */
export function selectFromTrack(items: TodoItem[], track_id: string | null): string | null {
  const m = track_id ? /^file:(\d+)$/.exec(track_id) : null;
  const i = m ? items.find((x) => filesOf(x).some((f) => f.file_id === Number(m[1])))
    : track_id ? items.find((x) => x.track_id === track_id) : undefined;
  return i ? itemKey(i) : null;
}

/** After "Good enough, hide": the next item that is not this track (the previous one at the end). */
export function selectAfterHide(items: TodoItem[], key: string): string | null {
  const pos = items.findIndex((i) => itemKey(i) === key);
  const id = items[pos]?.track_id;
  const next = items.slice(pos + 1).find((i) => i.track_id !== id)
    ?? items.slice(0, Math.max(0, pos)).reverse().find((i) => i.track_id !== id);
  return next ? itemKey(next) : null;
}

/** Whether a row is dimmed ("not in your playlists", for the older kinds). A same-song question and a duplicate
 *  group are never dimmed: they are about the user's own files, which no playlist holds. */
export const rowOff = (i: TodoItem): boolean => !i.pair && !i.in_playlists;

/** The rows ▶ in a track's details plays through as the to-do queue. The import's items are left out: a question's
 *  song has no file yet and a duplicate group is several files, so neither is a track the queue could ask for. */
export function queueRows(items: TodoItem[]): TodoItem[] {
  return items.filter((i) => !i.pair);
}

/** The badge a row shows: a question shows the quality of the user's file it asks about (the playlist song waits
 *  for the answer and has no file); every other row its track's. */
export function rowBadge(i: TodoItem): { quality: Quality; label: string } {
  return isQuestion(i) ? { quality: i.pair.file.quality, label: i.pair.file.quality_label }
    : { quality: i.quality, label: i.quality_label };
}

// ---------- the import's details (plan library stage 4, W8) ----------
/** The files of an import item: a question's one file, a duplicate group's files; none for any other item. */
export function filesOf(i: TodoItem): FileSide[] {
  return isQuestion(i) ? [i.pair.file] : isDuplicate(i) ? i.pair.files : [];
}

/** A file's id in the player's queue (the foot's link back selects its item through selectFromTrack). */
export const fileQueueId = (f: Pick<FileSide, 'file_id'>): string => `file:${f.file_id}`;

/** ▶ on a file: the files of the item that can play, as a queue starting at that file, so ⏭ goes on to the next copy
 *  and copies are compared one after the other. Null when that file can't play (offline, or no address). */
export function fileQueue(files: FileSide[], file_id: number, cover_url: string | null = null):
  { items: QueueItem[]; start: number; urls: Map<string, string> } | null {
  const playable = files.filter((f) => f.online && f.audio_url);
  const start = playable.findIndex((f) => f.file_id === file_id);
  if (start < 0) return null;
  return {
    items: playable.map((f) => ({ track_id: fileQueueId(f), artist: f.artist, title: f.title || fileName(f.path),
      cover_url, duration_s: f.duration_s || null })),
    start,
    urls: new Map(playable.map((f) => [fileQueueId(f), f.audio_url as string])),
  };
}

/** A file's ▶ as the player has it: its own sound loading or playing, else paused. */
export function fileState(p: Pick<PlayerState, 'track_id' | 'playing' | 'loading'>, f: Pick<FileSide, 'file_id'>):
  'playing' | 'paused' | 'loading' {
  if (p.track_id !== fileQueueId(f)) return 'paused';
  return p.loading ? 'loading' : p.playing ? 'playing' : 'paused';
}

/** The last part of a path ("Neon Riot - Neonfieber.aiff"). */
export function fileName(path: string): string {
  return path.split('/').filter(Boolean).at(-1) ?? path;
}
/** The folder a file is in, home as "~" ("/Volumes/Example Drive/Music/Old", "Library/Hard_Bounce"). */
export function fileFolder(path: string): string {
  const dir = path.replace(/\/+$/, '').split('/').slice(0, -1).join('/');
  return dir.replace(/^\/Users\/[^/]+(?=\/|$)/, '~') || '/';
}

/** One line of "Is this the same song?": the playlist song's value beside the file's; `differs` marks the line the
 *  why is about (the artist for `artist` / `no_artist`, the length for `length` / `no_length`). */
export type CompareLine = { key: 'title' | 'artist' | 'length' | 'where'; song: string; file: string;
  differs: boolean; fileTitle?: string };
/** Stands for a value that isn't there (no artist in the file, a length that couldn't be read). */
export const NO_VALUE = '—';
const DIFFERS: Record<QuestionWhy, CompareLine['key']> = {
  artist: 'artist', no_artist: 'artist', length: 'length', no_length: 'length' };

export function compareLines(p: QuestionPair): CompareLine[] {
  const d = DIFFERS[p.why];
  const len = (s: number) => (s > 0 ? duration(s) : NO_VALUE);
  return [
    { key: 'title', song: p.track.title, file: p.file.title || fileName(p.file.path), differs: false },
    { key: 'artist', song: p.track.artist || NO_VALUE, file: p.file.artist || NO_VALUE, differs: d === 'artist' },
    { key: 'length', song: len(p.track.duration_s), file: p.why === 'no_length' ? NO_VALUE : len(p.file.duration_s),
      differs: d === 'length' },
    { key: 'where', song: p.track.folder, file: fileFolder(p.file.path), differs: false, fileTitle: p.file.path },
  ];
}

/** "Keep both" for two files, "Keep all" for more (W8). */
export function keepLabel(n: number): string {
  return n > 2 ? 'Keep all' : 'Keep both';
}

/** The playlist service a song's link opens ("Open in Spotify"); null for a link of no known service. */
export function linkService(link: string | null): string | null {
  if (!link) return null;
  if (/^https:\/\/open\.spotify\.com\//.test(link)) return 'Spotify';
  if (/^https:\/\/([a-z]+\.)?qobuz\.com\//.test(link)) return 'Qobuz';
  return null;
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
