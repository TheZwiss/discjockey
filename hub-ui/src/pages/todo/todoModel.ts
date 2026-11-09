// To-do page logic (Task 67, spec §5.3; design system mockup design-system/todo.html): navigation order, selection
// across re-fetches, the filter strip, the list's sections, actions per track and the panel's main action.
import type { SegOption } from '$lib/components/segmentedModel';
import type {
  FileSide, FreeDownload, Quality, QuestionPair, QuestionWhy, Todo, TodoFilter,
  TodoGroupKey, TodoItem, TrackDetail,
} from '$lib/bridge/types';
import { isBatch, isDuplicate, isQuestion } from '$lib/bridge/types';
import { dayMonth, duration, fileAway, rowAway } from '$lib/format';
import { canSwap, defaultWay, fileName } from '$lib/decisions/decisionModel';
import { heldRow, putAt } from '$lib/decisions/hold';
import { fitPath } from '$lib/components/watchedFoldersModel';
import { keep as keepSelected, type Selection } from '$lib/components/selectionModel';

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

/** The page's second line, as `PageHeader` parts in order of importance (issue 30): one line beside the title at every
 *  width, so the header keeps its height between the filters (as one string it wrapped under the title at 1100). The
 *  first part never drops; the others drop whole where they don't fit (the strip's counts say them too) and stay in the
 *  tooltip. Every number counts tracks, as its words say (F5):
 *  - "not lossless yet" is the groups of tracks whose file is below lossless: Upgrade ready (the engine parks an
 *    upgrade only for a lossy file, so its current file is not lossless yet), Not found, Weak, Good lossy, Fake lossless
 *    and Other. It is the sum of those chips, not `chips.all` minus the rest: `chips.all` counts a track once however
 *    many groups it is in, so a track with a check that is also Weak would be taken off twice.
 *  - the questions (Same song, Duplicates) are about the user's own files, often lossless ones.
 *  - the checks are tracks just upgraded and lossless: `check_tracks`, because `chips.rekordbox_check` counts items
 *    and a batch of checks is one item there.
 *  Nothing left in any of them: "Nothing to do". */
export function headerSub(t: { chips: Record<TodoFilter, number>; check_tracks: number }): string[] {
  const { chips } = t;
  const questions = chips.same_song + chips.duplicate;
  const tracks = chips.upgrade_ready + chips.not_found + chips.weak + chips.good_lossy + chips.fake + chips.other;
  const checks = t.check_tracks;
  const parts = [
    tracks ? (tracks === 1 ? '1 track is not lossless yet' : `${tracks} tracks are not lossless yet`) : null,
    questions ? `${questions} ${questions === 1 ? 'question' : 'questions'} about your files` : null,
    checks ? `${checks} ${checks === 1 ? 'track' : 'tracks'} to check in rekordbox` : null,
  ].filter((p): p is string => p !== null);
  return parts.length ? parts : ['Nothing to do'];
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

// ---------- multi-select (issue 33 stage B §6.1) ----------
/** The groups whose items can be selected several at once (their actions run on a selection): Upgrade ready and
 *  Check in rekordbox (a batch item among single checks: Done and Undo for all their tracks, stage B §6.4); the
 *  other groups' actions are one track's. */
export const MULTI_GROUPS: TodoGroupKey[] = ['upgrade_ready', 'rekordbox_check'];
/** Two or more items selected, all checks: the checks' selection panel (BatchCheckCards). */
export function multiChecks(selected: TodoItem[]): boolean {
  return selected.length > 1 && selected.every((i) => i.group === 'rekordbox_check');
}
/** selectionModel's scope of a key: its item's group where that group allows several, else null. */
export function multiScope(items: TodoItem[]): (key: string) => string | null {
  const groups = new Map(items.map((i) => [itemKey(i), i.group]));
  return (key) => {
    const g = groups.get(key);
    return g && MULTI_GROUPS.includes(g) ? g : null;
  };
}
/** The checks a batch card or a selection of checks acted on (Done, Undo all, Undo this one): the page keeps them in
 *  its panel until the next pick, whatever shape the list gives them now. `batch`: the panel was that batch's card. */
export type CheckHold = { ids: string[]; batch: { id: number; started: string | null } | null };
/** The open checks of a hold in `items` (a batch item gives its tracks), in the list's order, with the keys of the
 *  rows that hold them; null when none is left (all done or undone). */
export function heldChecks(items: TodoItem[], h: CheckHold): { keys: string[]; tracks: TodoItem[] } | null {
  const keys: string[] = [];
  const tracks: TodoItem[] = [];
  for (const i of items) {
    if (i.group !== 'rekordbox_check') continue;
    const mine = (isBatch(i) ? i.batch.tracks : [i]).filter((t) => h.ids.includes(t.track_id));
    if (!mine.length) continue;
    keys.push(itemKey(i));
    tracks.push(...mine);
  }
  return tracks.length ? { keys, tracks } : null;
}
/** The Upgrade ready group of an answer (its `all` and `stopped` drive the head's link), null when it has none. */
export function upgradeGroup(t: Todo | null): Todo['groups'][number] | null {
  return t?.groups.find((g) => g.key === 'upgrade_ready') ?? null;
}

/** "Upgrade all · n": the group's items that Upgrade all can reach. A hidden item is left out (the hub's `upgrade_all`
 *  leaves it out, and the head's n doesn't count it), also with Show hidden on. */
export function upgradeAllKeys(group: { items: TodoItem[] } | null): string[] {
  return group ? group.items.filter((i) => !i.hidden).map(itemKey) : [];
}
/** Whether the selection is the whole group as Upgrade all means it: every item it can reach, and no hidden one (that
 *  would be a choice of its own, sent as a list). */
export function wholeUpgradeGroup(group: { items: TodoItem[] } | null, selected: TodoItem[]): boolean {
  const keys = upgradeAllKeys(group);
  const picked = new Set(selected.map(itemKey));
  return keys.length > 0 && keys.every((k) => picked.has(k)) && selected.every((i) => !i.hidden);
}
/** A batch's panel stays until the next pick of the user's own: while it is pinned, a re-fetch keeps only the rows
 *  still in the list selected (the batch's tracks leave it one by one) and never moves the pick to a neighbour, which
 *  could be the new check row of the batch just done. */
export function keepPinned(sel: Selection, before: string[], after: string[]): Selection {
  return keepSelected(sel, before, after, () => null);
}
/** The checks panel gives way to a pinned batch's result: its rows may have become the checks' (the batch's own check
 *  row appears in another group when it is done). */
export const checksPanelShows = (pinnedBatch: boolean, hasChecks: boolean): boolean => hasChecks && !pinnedBatch;
/** The list follows a running batch: one fresh answer per track done. `prev`: the count seen last (-1: no batch ran);
 *  returns whether to ask again and the count to remember. */
export function batchListStep(prev: number, v: { phase: 'running' | 'ended'; done: number } | null): { reload: boolean; seen: number } {
  if (!v || v.phase !== 'running') return { reload: false, seen: -1 };
  return { reload: prev >= 0 && v.done > prev, seen: v.done };
}
/** One run at a time, a call during a run asks for exactly one more after it (the list's fresh answers during a batch:
 *  a burst of progress events is not a burst of requests). */
export function coalesce(run: () => Promise<void>): () => void {
  let busy = false;
  let again = false;
  const go = async (): Promise<void> => {
    if (busy) { again = true; return; }
    busy = true;
    try {
      do { again = false; await run(); } while (again);
    } finally { busy = false; }
  };
  return () => { void go(); };
}

// ---------- the item just acted on ----------
/** The item the user just acted on in the details (a Replace, Discard, Done, Undo or a duplicate's Keep). It stays in
 *  the list where it stood and stays selected, its result and Undo in the details, until the user picks another item
 *  or changes the filter or Show hidden: "Upgrades" shows only upgrades, and a replace takes the track to "Check in
 *  rekordbox", so without it the rekordbox steps and "Undo the replace" would go out of sight with the row (the
 *  Library keeps the track it acted on the same way, libraryModel Hold). `keep`: a duplicate's Keep, the paths of the
 *  files that stay (the hold follows the song that has a kept file now). `put`: the item was put into the list after
 *  an answer dropped it, so the list asks again when the hold ends. `ghost`: no to-do is left of it (Done, Discard on a
 *  lossless track): its row stays as it was, and its details are the track's, without a decision. */
export type TodoHold = { key: string; id: string; keep: string[] | null; filter: TodoFilter; showHidden: boolean;
  put: boolean; ghost: boolean };
export function holdApplies(h: TodoHold | null, key: string | null, filter: TodoFilter, showHidden: boolean): boolean {
  return !!h && h.key === key && h.filter === filter && h.showHidden === showHidden;
}
/** The held item among `items`: the same item, else the same track (now in another group), else (a duplicate's Keep)
 *  the song whose file stayed. The import's items are never "the same track". */
export function findHeld(items: TodoItem[], h: Pick<TodoHold, 'key' | 'id' | 'keep'>): TodoItem | null {
  return find(items, h.key) ?? heldRow(items.filter((i) => !i.pair), h);
}
/** A held item with no to-do left: the row as it was, minus what only a to-do has. */
export function ghostOf(old: TodoItem): TodoItem {
  return { ...old, upgrade_ready: false, can_undo: false, check: undefined, detail: '' };
}
/** How many of a section's `items` are open to-dos: the item a load put back into the list (`extraKey`, the answer
 *  didn't list it) stays in view but is not one, so it is in neither the section's count nor the chip's. */
export function openCount(items: TodoItem[], extraKey: string | null): number {
  return extraKey === null ? items.length : items.filter((i) => itemKey(i) !== extraKey).length;
}
/** The answer with the held item put back where its place stood in `before` (the answer on screen; `was`: the held
 *  key there): in the section it stood in, at its position there; the section is made again when the answer has none
 *  left. An answer that lists the item already comes back as it is. */
export function withHeldItem(view: Todo, item: TodoItem, before: Todo | null, was: string): Todo {
  if (flatten(view).some((i) => itemKey(i) === itemKey(item))) return view;
  const home = before?.groups.find((g) => g.items.some((i) => itemKey(i) === was));
  const key = home?.key ?? item.group;
  const at = home ? home.items.findIndex((i) => itemKey(i) === was) : -1;
  const there = view.groups.find((g) => g.key === key);
  if (there) {
    const groups = view.groups.map((g) => (g === there ? { ...g, items: putAt(g.items, item, at < 0 ? g.items.length : at) } : g));
    return { ...view, groups, empty: null };
  }
  if (!home) return view;
  const rank = (k: TodoGroupKey) => FILTER_ORDER.indexOf(k);
  const next = view.groups.findIndex((g) => rank(g.key) > rank(key));
  const made = { key, label: home.label, hint: home.hint, items: [item] };
  return { ...view, groups: putAt(view.groups, made, next < 0 ? view.groups.length : next), empty: null };
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
    : track_id ? items.find((x) => x.track_id === track_id)
      // a track a batch upgraded is its batch's row (Sync's "Fix →", the Library's link)
      ?? items.find((x) => isBatch(x) && x.batch.tracks.some((t) => t.track_id === track_id)) : undefined;
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
/** The row's lead is dimmed: a track no playlist holds (`rowOff`) or a file that is away (`rowAway`: offline, its
 *  folder not found), as in Library's table. The trailing column tells the two apart: the quality badge, or the
 *  `AwayTag` in its place, which says why the file can't play. */
export const rowDim = (i: TodoItem): boolean => !isBatch(i) && (rowOff(i) || rowAway(i) !== null);

/** The rows ▶ in a track's details plays through as the to-do queue. The import's items are left out: a question's
 *  song has no file yet and a duplicate group is several files, so neither is a track the queue could ask for. */
export function queueRows(items: TodoItem[]): TodoItem[] {
  // a batch's row is its tracks, each one in the queue in the batch's order
  return items.filter((i) => !i.pair).flatMap((i) => (isBatch(i) ? i.batch.tracks : [i]));
}

/** The badge a row shows: a question shows the quality of the user's file it asks about (the playlist song waits
 *  for the answer and has no file); every other row its track's. */
export function rowBadge(i: TodoItem): { quality: Quality | 'muted'; label: string } {
  // a batch's row: its tracks' quality when they share one (a Same track batch of lossless versions), else MIXED
  if (isBatch(i)) {
    const q = new Set(i.batch.tracks.map((t) => `${t.quality}|${t.quality_label}`));
    return q.size === 1 ? { quality: i.batch.tracks[0].quality, label: i.batch.tracks[0].quality_label }
      : { quality: 'muted', label: 'MIXED' };
  }
  return isQuestion(i) ? { quality: i.pair.file.quality, label: i.pair.file.quality_label }
    : { quality: i.quality, label: i.quality_label };
}

// ---------- the import's details (plan library stage 4, W8) ----------
/** The files of an import item: a question's one file, a duplicate group's files; none for any other item. */
export function filesOf(i: TodoItem): FileSide[] {
  return isQuestion(i) ? [i.pair.file] : isDuplicate(i) ? i.pair.files : [];
}

/** The folder a file is in, home as "~" ("/Volumes/Example Drive/Music/Old", "Library/Hard_Bounce"). */
export function fileFolder(path: string): string {
  const dir = path.replace(/\/+$/, '').split('/').slice(0, -1).join('/');
  return dir.replace(/^\/Users\/[^/]+(?=\/|$)/, '~') || '/';
}
/** `fileFolder` as the watched folders read in Settings: a folder on another drive is "Example Drive › Music/Old" (the
 *  drive's name first, as it is what tells which one to connect), any other stays as `fileFolder` has it. Whole, for
 *  a place that wraps (nothing is cut). */
export function filePlace(path: string): string {
  const { head, tail } = fitPath(fileFolder(path), () => true);
  // the blank after "›" is a plain one: a line may break after the "›", never before it (fitPath keeps that one tight)
  return head.replace(/\u00A0$/, ' ') + tail;
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
    { key: 'where', song: p.track.folder, file: filePlace(p.file.path), differs: false, fileTitle: p.file.path },
  ];
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
  const swap = canSwap(up);
  const check = group === 'rekordbox_check';
  const upgrade = up ? { swap, primary: defaultWay(up, swap) } : null;
  const finder = group === 'other' && !!track.path && !fileAway(track);   // nothing to show when the file isn't there
  // a lossless version is ready: the upgrade decision is the way to it, so no "Get a lossless file" (buy, drop) under it
  const getBetter = improvable && !(up && up.what === 'lossless version');
  return {
    listen: !!track.audio_url || fileAway(track),   // away: the player stays, switched off, as in the Library
    versions: missing ? 'find' : 'wrong_song',
    noneOfThese: !missing,
    buy: getBetter,
    dropZone: getBetter,
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

/** The "Qobuz" fact from `next_qobuz_check`: ISO date → "not there yet · looks again on 20 Oct", null → nothing. */
export function qobuzText(next: string | null): string | null {
  if (!next) return null;
  if (next === 'next_sync') return 'not there yet · looks again at the next sync';
  const day = dayMonth(next);
  return day ? `not there yet · looks again on ${day}` : null;
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

// ---------- the decisions (shared with the Library, lib/decisions) ----------
export {
  KEPT_FILE, QUIT_REKORDBOX, SUPERSEDED_NOT_DELETED, canSwap, checkCard, editLine, fileFormat, fileName, fileQueue,
  fileQueueId, fileState, fileWords, groupIdOf, keepLabel, keepWords, lastFolder, localDay, replaceLabel, replacedCard,
  sinceText, upgradeWays,
} from '$lib/decisions/decisionModel';
export type {
  CheckCard, CheckStep, DuplicatePick, ReplacedCard, ReplacedRow, UpgradeWays, Way, WayOption,
} from '$lib/decisions/decisionModel';
