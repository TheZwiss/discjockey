// The browser column's rows (plan library stage 5, D4, D8 and I7; notes N2–N4, N9, N10, N13): what BrowserColumn.svelte
// shows, pure. On top without a head All tracks and Not in a playlist, then the sections: Favourites (the user's own
// order, a dashed landing row while empty), Playlists in playlists.txt order (download priority, switched-off ones in
// place and dimmed) or A–Z, and Folders: each watched import folder with its crates (a chevron folds them; hidden crates
// and those of a folder with too many have no row), then the Library folders no playlist uses. Each row one line.
//
// Every collection has one identity, its target: `view:all`, `view:unlisted`, `playlist:<ref>` or `folder:<path>` (the
// keys `set_favourites` stores, D3). A collection can have two rows (a favourite is a shortcut to a row that is also in
// Playlists or Folders), so a row's `key` names the row and its `target` the collection; the pill for the collection
// on screen goes on its topmost row.
//
// The filter (N9): a substring of the names as shown, with case and accents folded ("motley" finds "Mötley"). While
// filtering, the views and Favourites step aside, folded sections open, every match is listed once in its own
// section (a crate, hidden ones and every album of a folder with too many included, under its watched folder, which
// stands there as context when its own name doesn't match: never a target), and exactly one row carries the highlight
// (the first match; ↑ ↓ move it, down to the hand-off row). The hand-off row ("Search tracks for “…”") is the last
// row whenever there is text, and the only one, with the highlight, when no name matches (N3).
import type { Crate, Favourite, FolderState, LibraryView, PlaylistService, Sidebar, WatchedEntry } from '../bridge/types';
import { NOT_IN_PLAYLIST } from '../bridge/types';
import { PLAYLIST_SERVICE_NAMES } from '../copy';
import { count } from '../format';
import { buildHash, libraryHref } from '../router';

export const HANDOFF = 'handoff';
export const ALL = 'view:all';
export const UNLISTED = 'view:unlisted';
/** Favourites' landing row while it is empty (I7). */
export const LANDING_TEXT = 'Drag a playlist or folder here';

/** The matched letters of a name, as [start, end) in the name (null: nothing to mark, no filter). */
export type Match = [number, number] | null;

/** What a folder row stands for: a watched import folder, a crate under one, or a Library folder no playlist uses. */
export type FolderKind = 'watched' | 'crate' | 'library';
/** The 14 px lead of a row: the service's logo, a folder outline, the yellow "!" of an away folder, or nothing (a
 *  crate under its watched folder indents instead). */
export type Lead = 'service' | 'folder' | 'warn' | 'none';
export type Place = 'favourites' | 'playlists' | 'folders';

export type ViewRow = { kind: 'view'; key: string; target: string; name: string; count: number; href: string };
type RowBase = {
  key: string; target: string; name: string; count: number | null; href: string; tip: string; match: Match;
  lead: Lead; place: Place;
  /** a crate under its watched folder: no lead, indented to the names */
  indent: boolean;
};
export type PlaylistRow = RowBase & { kind: 'playlist'; service: PlaylistService | null; enabled: boolean };
export type FolderRow = RowBase & {
  kind: 'folder'; folder: FolderKind; path: string; state: FolderState;
  /** a watched folder whose crates show: its chevron (`key` is what `browserClosed` holds) */
  fold: { key: string; open: boolean } | null;
  /** while filtering: a watched folder listed only for its matching crates (never the highlighted row) */
  context: boolean;
  /** a crate: out of the sidebar (shown only while filtering) and whether its folder has too many to show */
  crate: { hidden: boolean; tooMany: boolean } | null;
};
export type CollectionRow = PlaylistRow | FolderRow;
export type HandoffRow = { kind: 'handoff'; key: typeof HANDOFF; text: string; href: string; tip: string };
export type BrowserRow = ViewRow | CollectionRow | HandoffRow;

export type Section = {
  key: 'favourites' | 'playlists' | 'folders'; label: string;
  /** the head's count (Playlists: every line; none while filtering, where only matches are listed) */
  count: number | null;
  /** its rows show: unfolded, or filtering (a filter opens folded sections) */
  open: boolean;
  /** the head folds it (not while filtering) */
  foldable: boolean;
  rows: CollectionRow[];
};

export type BrowserList = {
  views: ViewRow[];
  sections: Section[];
  handoff: HandoffRow | null;
  /** the rows Enter can open, in screen order (filtering only; empty otherwise) */
  targets: string[];
  /** the key of the row that carries the pill: the topmost shown row of the collection on screen */
  on: string | null;
  /** the widest count among the watched folders with a chevron, in digits: their counts take that width, so the
   *  chevrons line up */
  countCh: number;
};

export type BrowserInput = {
  side: Sidebar | null; query: string; az: boolean; closed: readonly string[];
  /** the collection on screen (`currentTarget`), null: none */
  current?: string | null;
  /** crate switches saved a moment ago and not read back yet (path → shown), so a hidden crate goes at once */
  shown?: Readonly<Record<string, boolean>>;
};

const AWAY_WORDS: Record<Exclude<FolderState, 'here'>, string> = {
  offline: 'Offline: connect the drive', folder_missing: 'Folder not found',
};
/** More than this many crates under a watched folder: it is one row, its crates out of the sidebar (D8). */
export const TOO_MANY = 25;

/** One character folded for matching: its base letters without accents (NFD, the combining marks dropped), lower
 *  case. A combining mark on its own folds to nothing. */
const foldChar = (c: string): string => c.normalize('NFD').replace(/\p{M}/gu, '').toLocaleLowerCase();

/** A name folded for matching, with where each folded letter came from in the name (`from[i]`: the name's index of
 *  folded letter i; one more entry, the name's length, closes it). Folded one character at a time, so the text
 *  typed and the names fold the same way and every match maps back to whole characters of the name. */
export function foldMap(name: string): { folded: string; from: number[] } {
  let folded = '';
  const from: number[] = [];
  let at = 0;
  for (const c of name) {
    const f = foldChar(c);
    for (let k = 0; k < f.length; k++) from.push(at);
    folded += f;
    at += c.length;
  }
  from.push(name.length);
  return { folded, from };
}
/** Folded for matching: case and accents ("Mötley" → "motley", "Über" → "uber"). */
export const fold = (s: string): string => foldMap(s).folded;

/** Where the folded text sits in the name, as the name's own characters (a decomposed accent after the last matched
 *  letter included); false: no match; null: no text. */
export function matchName(name: string, q: string): Match | false {
  if (!q) return null;
  const { folded, from } = foldMap(name);
  const i = folded.indexOf(q);
  if (i < 0) return false;
  return [from[i], from[i + q.length]];
}

/** The text the filter filters by: trimmed, folded (blank: no filter). */
export const filterText = (raw: string): string => fold(raw.trim());

/** `#/library?q=…`: All tracks with the text in its track search (the hand-off). */
export const searchTracksHref = (text: string): string => buildHash('/library', {}, { q: text });

/** A piece of a row's name: a crate's separator (" › ", " · ") is quiet, the matched letters are bold. */
export type NamePart = { text: string; sep?: true; hl?: true };
const SEPARATORS = / (?:›|·) /g;
/** A name in pieces for drawing: the separators of a crate's label quiet (only they: the parent "Hardtechno ›" and
 *  the qualifier "· Old Sets" keep the row's colour, D16 rule 9), the match bold. */
export function nameParts(text: string, m: Match): NamePart[] {
  const cuts = new Set<number>([0, text.length]);
  const seps: [number, number][] = [];
  for (const s of text.matchAll(SEPARATORS)) {
    seps.push([s.index, s.index + s[0].length]);
    cuts.add(s.index).add(s.index + s[0].length);
  }
  if (m) cuts.add(m[0]).add(m[1]);
  const at = [...cuts].sort((a, b) => a - b);
  const out: NamePart[] = [];
  for (let i = 0; i < at.length - 1; i++) {
    const [a, b] = [at[i], at[i + 1]];
    if (a === b) continue;
    const part: NamePart = { text: text.slice(a, b) };
    if (seps.some(([s, e]) => a >= s && b <= e)) part.sep = true;
    if (m && a >= m[0] && b <= m[1]) part.hl = true;
    out.push(part);
  }
  return out;
}

const songsWord = (n: number): string => (n === 1 ? '1 song' : `${count(n)} songs`);
const tracksWord = (n: number): string => (n === 1 ? '1 track' : `${count(n)} tracks`);
const awayLine = (state: FolderState): string => (state === 'here' ? '' : `\n${AWAY_WORDS[state]}`);

export function playlistTip(p: { name: string; service: PlaylistService | null; enabled: boolean; songs: number | null }): string {
  const kind = p.service ? `${PLAYLIST_SERVICE_NAMES[p.service]} playlist` : '';
  const songs = p.songs === null ? 'not read yet' : songsWord(p.songs);
  return `${p.name}\n${kind ? `${kind} · ` : ''}${songs}${p.enabled ? '' : '\nSwitched off: its files stay, nothing new downloads'}`;
}
export const libraryFolderTip = (f: { name: string; files: number }): string =>
  `Library › ${f.name}\n${tracksWord(f.files)} · no playlist uses it`;
export function watchedTip(w: WatchedEntry): string {
  const shown = w.crates.filter((c) => !c.hidden).length;
  let line = tracksWord(w.files);
  if (!w.too_many && shown < w.crates.length) line += ` · ${shown} of ${w.crates.length} folders shown`;
  const many = w.too_many ? `\n${w.crate_count} folders with music: choose which to show in Settings → Watched folders` : '';
  return `${w.place}\n${line}${awayLine(w.state)}${many}`;
}
export function crateTip(c: Crate, w: WatchedEntry): string {
  const out = w.too_many && c.hidden ? `\nNot in the sidebar: ${w.name} has ${w.crate_count} folders with music`
    : c.hidden ? '\nHidden from the sidebar: Settings brings it back' : '';
  return `${c.tip}\n${tracksWord(c.files)}${awayLine(w.state)}${out}`;
}
export const handoffTip = (text: string): string =>
  `Search every track’s title and artist for “${text}” (All tracks)`;
export const sortTip = (az: boolean): string => (az ? 'Order: A–Z · click for download priority'
  : 'Order: download priority (change it on the Playlists page) · click for A–Z');
export const foldWatchedTip = (open: boolean, name: string): string => `${open ? 'Hide' : 'Show'} the folders in ${name}`;
export const EDGE_TIP = 'Drag to resize · double-click to reset';
/** The edge's width for a screen reader. */
export const edgeValueText = (w: number): string => `${w} px`;

/** A row's element id (`aria-activedescendant` names the highlighted one): `bc-` and its key, every character that
 *  can't stand in an id spelled out, so two keys never share an id. */
export const rowId = (key: string): string =>
  `bc-${key.replace(/[^A-Za-z0-9_-]/g, (c) => `.${c.codePointAt(0)!.toString(16)}.`)}`;

const byName = (a: { name: string }, b: { name: string }) =>
  a.name.localeCompare(b.name, undefined, { sensitivity: 'base', numeric: true });

export const playlistTarget = (ref: string): string => `playlist:${ref}`;
export const folderTarget = (path: string): string => `folder:${path}`;
const LIBRARY_PREFIX = 'Library/';
/** A folder's link: a Library folder by its name (the step A route the Dashboard links too), any other by its path. */
export const folderHref = (path: string): string =>
  libraryHref(path.startsWith(LIBRARY_PREFIX) ? path.slice(LIBRARY_PREFIX.length) : path);
/** Where Show in Finder can point (`api.reveal` opens places inside the music folder only): a playlist's folder, a
 *  Library folder; null for an import folder and its crates. */
export function revealPath(row: CollectionRow): string | null {
  if (row.kind === 'playlist') return `${LIBRARY_PREFIX}${row.name}`;
  return row.path.startsWith(LIBRARY_PREFIX) ? row.path : null;
}

/** Every crate of the sidebar with its watched folder, by path. */
function cratesByPath(side: Sidebar): Map<string, { c: Crate; w: WatchedEntry }> {
  const m = new Map<string, { c: Crate; w: WatchedEntry }>();
  for (const w of side.watched) for (const c of w.crates) m.set(c.path, { c, w });
  return m;
}

function playlistRow(p: Sidebar['playlists'][number], key: string, place: Place): PlaylistRow {
  return { kind: 'playlist', key, target: playlistTarget(p.ref), name: p.name, service: p.service, enabled: p.enabled,
    count: p.songs, href: libraryHref(p.name), tip: playlistTip(p), match: null, lead: p.service ? 'service' : 'none',
    place, indent: false };
}
const folderBase = { kind: 'folder' as const, match: null, indent: false, fold: null, context: false, crate: null };
function watchedRow(w: WatchedEntry, open: boolean | null, place: Place): FolderRow {
  return { ...folderBase, key: folderTarget(w.path), target: folderTarget(w.path), name: w.name, count: w.files,
    href: folderHref(w.path), tip: watchedTip(w), lead: w.state === 'here' ? 'folder' : 'warn', place,
    folder: 'watched', path: w.path, state: w.state, fold: open === null ? null : { key: watchedFoldKey(w.path), open } };
}
function crateRow(c: Crate, w: WatchedEntry, hidden: boolean, place: Place): FolderRow {
  return { ...folderBase, key: folderTarget(c.path), target: folderTarget(c.path), name: c.label, count: c.files,
    href: folderHref(c.path), tip: crateTip({ ...c, hidden }, w), lead: 'none', place, folder: 'crate', path: c.path,
    state: w.state, indent: true, crate: { hidden, tooMany: w.too_many } };
}
function libraryFolderRow(f: Sidebar['library_folders'][number], place: Place): FolderRow {
  return { ...folderBase, key: folderTarget(f.path), target: folderTarget(f.path), name: f.name, count: f.files,
    href: folderHref(f.path), tip: libraryFolderTip(f), lead: 'folder', place, folder: 'library', path: f.path,
    state: 'here' };
}
/** The key `browserClosed` holds for a folded watched folder. */
export const watchedFoldKey = (path: string): string => `watched:${path}`;

/** A favourite as a row (the browser's Favourites and the full sidebar's shortcuts): a playlist with its logo, a
 *  folder with the folder outline (a pinned crate stands on its own now), or the "!" while its drive is away. */
export function favouriteRow(f: Favourite, side: Sidebar, crates = cratesByPath(side)): CollectionRow {
  const key = `fav:${f.key}`;
  if (f.kind === 'playlist') {
    const p = { name: f.name, ref: f.key.slice('playlist:'.length), service: f.service, enabled: f.enabled, songs: f.count };
    return { ...playlistRow(p, key, 'favourites'), target: f.key };
  }
  const path = f.path ?? f.key.slice('folder:'.length);
  const cr = crates.get(path);
  const w = side.watched.find((x) => x.path === path);
  const lib = side.library_folders.find((x) => x.path === path);
  const tip = cr ? crateTip({ ...cr.c, hidden: false }, cr.w) : w ? watchedTip(w)
    : lib ? libraryFolderTip(lib) : `${f.name}${awayLine(f.state)}`;
  return { ...folderBase, key, target: f.key, name: f.name, count: f.count, href: folderHref(path), tip,
    lead: f.state === 'here' ? 'folder' : 'warn', place: 'favourites', path, state: f.state,
    folder: cr ? 'crate' : w ? 'watched' : 'library' };
}

/** The favourite a target would be, made from the sidebar's own rows (a pin saved a moment ago and not read back
 *  yet); null when the sidebar doesn't list it. */
export function favouriteOf(side: Sidebar, target: string, crates = cratesByPath(side)): Favourite | null {
  if (target.startsWith('playlist:')) {
    const ref = target.slice('playlist:'.length);
    const p = side.playlists.find((x) => x.ref === ref);
    return p ? { key: target, kind: 'playlist', name: p.name, service: p.service, enabled: p.enabled, count: p.songs,
      path: null, state: 'here' } : null;
  }
  if (!target.startsWith('folder:')) return null;
  const path = target.slice('folder:'.length);
  const base = { key: target, kind: 'folder' as const, service: null, enabled: true, path };
  const w = side.watched.find((x) => x.path === path);
  if (w) return { ...base, name: w.name, count: w.files, state: w.state };
  const cr = crates.get(path);
  if (cr) return { ...base, name: cr.c.label, count: cr.c.files, state: cr.w.state };
  const lib = side.library_folders.find((x) => x.path === path);
  return lib ? { ...base, name: lib.name, count: lib.files, state: 'here' } : null;
}

/** The Favourites as `keys` orders them (a save not read back yet): the sidebar's own favourites where it has them,
 *  else made from its rows; a key the sidebar knows nothing of is left out. */
export function favouritesIn(side: Sidebar, keys: readonly string[] | null): Favourite[] {
  if (!keys) return side.favourites;
  const crates = cratesByPath(side);
  const known = new Map(side.favourites.map((f) => [f.key, f]));
  return keys.flatMap((k) => {
    const f = known.get(k) ?? favouriteOf(side, k, crates);
    return f ? [f] : [];
  });
}

/** the rows with each key once, the first kept: the lists are keyed by it */
function once<T extends { key: string }>(rows: T[]): T[] {
  const seen = new Set<string>();
  return rows.filter((r) => !seen.has(r.key) && !!seen.add(r.key));
}

export function browserList({ side, query, az, closed: storedClosed, current = null, shown = {} }: BrowserInput): BrowserList {
  // a stored value is only checked for its type (getPref), so an object or a string can stand here
  const closed = Array.isArray(storedClosed) ? storedClosed : [];
  const q = filterText(query);
  const filtering = q !== '';
  if (!side) {
    return { views: [], sections: [], targets: [], handoff: filtering ? handoff(query) : null, on: null, countCh: 1 };
  }
  const views: ViewRow[] = filtering ? [] : [
    { kind: 'view', key: ALL, target: ALL, name: 'All tracks', count: side.all_tracks, href: libraryHref(null) },
    ...(side.not_in_playlist > 0 ? [{ kind: 'view' as const, key: UNLISTED, target: UNLISTED, name: 'Not in a playlist',
      count: side.not_in_playlist, href: libraryHref(NOT_IN_PLAYLIST) }] : []),
  ];
  const keep = <T extends CollectionRow>(r: T): T | null => {
    if (!filtering) return r;
    const m = matchName(r.name, q);
    return m === false ? null : { ...r, match: m };
  };
  const kept = <T extends CollectionRow>(rows: T[]): T[] => rows.flatMap((r) => { const k = keep(r); return k ? [k] : []; });

  // a ref twice in playlists.txt still gets two rows, each with its own key
  const seen = new Set<string>();
  let playlists: PlaylistRow[] = side.playlists.map((p) => {
    let key = playlistTarget(p.ref);
    for (let n = 2; seen.has(key); n++) key = `${playlistTarget(p.ref)}#${n}`;
    seen.add(key);
    return playlistRow(p, key, 'playlists');
  });
  if (az) playlists = [...playlists].sort(byName);
  playlists = kept(playlists);

  const isHidden = (c: Crate) => (c.path in shown ? !shown[c.path] : c.hidden);
  const folders: FolderRow[] = [];
  let countCh = 1;
  for (const w of side.watched) {
    const visible = w.crates.filter((c) => !isHidden(c));
    const open = filtering || !closed.includes(watchedFoldKey(w.path));
    if (!filtering) {
      folders.push(watchedRow(w, visible.length ? open : null, 'folders'));
      if (visible.length) countCh = Math.max(countCh, count(w.files).length);
      if (open) folders.push(...visible.map((c) => crateRow(c, w, false, 'folders')));
      continue;
    }
    // filtering: every crate that matches, hidden ones too, under its watched folder (context when only they match)
    const crates = kept(w.crates.map((c) => crateRow(c, w, isHidden(c), 'folders')));
    const own = keep(watchedRow(w, null, 'folders'));
    if (!own && !crates.length) continue;
    folders.push(own ?? { ...watchedRow(w, null, 'folders'), context: true }, ...crates);
  }
  folders.push(...kept(side.library_folders.map((f) => libraryFolderRow(f, 'folders'))));
  // one folder is one row: a watched folder or crate that sits at the path of a Library folder (or twice) is drawn once,
  // the first (a keyed list can't hold a key twice)
  const onceFolders = once(folders);

  const section = (key: Section['key'], label: string, rows: CollectionRow[], count: number | null): Section => ({
    key, label, rows, count: filtering ? null : count, foldable: !filtering, open: filtering || !closed.includes(key) });
  const sections: Section[] = [];
  // Favourites steps aside while filtering: each match once, in its own section, one highlight (N9)
  if (!filtering) {
    const crates = cratesByPath(side);
    sections.push(section('favourites', 'Favourites', once(side.favourites.map((f) => favouriteRow(f, side, crates))), null));
  }
  if (playlists.length) sections.push(section('playlists', 'Playlists', playlists, side.playlists.length));
  if (onceFolders.length) sections.push(section('folders', 'Folders', onceFolders, null));

  const ho = filtering ? handoff(query) : null;
  const targets = filtering
    ? [...sections.flatMap((s) => s.rows.filter((r) => !(r.kind === 'folder' && r.context)).map((r) => r.key)), HANDOFF]
    : [];
  return { views, sections, handoff: ho, targets, on: topmostRow(views, sections, current), countCh };
}

/** The row the pill goes on: the topmost shown row of the collection on screen. */
function topmostRow(views: ViewRow[], sections: Section[], current: string | null): string | null {
  if (!current) return null;
  for (const v of views) if (v.target === current) return v.key;
  for (const s of sections) if (s.open) for (const r of s.rows) if (r.target === current) return r.key;
  return null;
}

function handoff(raw: string): HandoffRow {
  const text = raw.trim();
  return { kind: 'handoff', key: HANDOFF, text, href: searchTracksHref(text), tip: handoffTip(text) };
}

/** The one highlighted row while filtering: the current one while it is still a target, else the first match (the
 *  hand-off when nothing matches). Null when not filtering. */
export function highlightOf(targets: readonly string[], current: string | null): string | null {
  if (!targets.length) return null;
  return current !== null && targets.includes(current) ? current : targets[0];
}

/** ↑ ↓ in the filter: the highlight one row up or down, held at the first and the last (the hand-off). */
export function moveHighlight(targets: readonly string[], current: string | null, delta: 1 | -1): string | null {
  const at = highlightOf(targets, current);
  if (at === null) return null;
  const i = targets.indexOf(at) + delta;
  return targets[Math.max(0, Math.min(targets.length - 1, i))];
}

/** Every row by its key (to open the highlighted one). */
export function rowByKey(list: BrowserList, key: string): BrowserRow | null {
  if (list.handoff?.key === key) return list.handoff;
  for (const r of list.views) if (r.key === key) return r;
  for (const s of list.sections) for (const r of s.rows) if (r.key === key) return r;
  return null;
}

/** The collection on screen as a target: `folder` is the library route's folder param (undefined: not on Library;
 *  null: All tracks). A path (an import folder or a crate, "/…") is a folder; a name is a playlist's folder when a
 *  playlist has it, else a Library folder no playlist uses (step A's route, which the Dashboard links too). */
export function currentTarget(side: Sidebar | null, folder: string | null | undefined): string | null {
  if (folder === undefined) return null;
  if (folder === null) return ALL;
  if (folder === NOT_IN_PLAYLIST) return UNLISTED;
  if (folder.startsWith('/')) return folderTarget(folder);
  if (!side) return null;
  const p = side.playlists.find((x) => x.name === folder);
  if (p) return playlistTarget(p.ref);
  const lib = side.library_folders.find((f) => f.name === folder);
  return lib ? folderTarget(lib.path) : null;
}

/** A folded section's or watched folder's key in or out of the remembered list. */
export function toggleClosed(closed: readonly string[], key: string): string[] {
  const c = Array.isArray(closed) ? closed : [];
  return c.includes(key) ? c.filter((k) => k !== key) : [...c, key];
}

// ---------- Favourites: order and drag (notes "Motion": lift 120 ms, rows part 200 ms, drop spring) ----------

/** The keys with `key` put at `to` (its index in the list without it; held to the ends). A key not in the list yet
 *  goes in there; one already in moves. */
export function moveKey(keys: readonly string[], key: string, to: number): string[] {
  const rest = keys.filter((k) => k !== key);
  const at = Math.max(0, Math.min(rest.length, Math.round(to)));
  return [...rest.slice(0, at), key, ...rest.slice(at)];
}
/** Whether the dragged row's middle is over the Favourites' drop zone `[top, bottom]` (its head to its last row): a
 *  row released anywhere else, a favourite included, goes back where it came from. */
export function inDropZone(mid: number, zone: readonly [number, number]): boolean {
  return mid >= zone[0] && mid <= zone[1];
}
/** Where a dragged row lands: how many of the other rows' middles lie above the pointer. */
export function dropIndex(mids: readonly number[], y: number): number {
  let n = 0;
  for (const m of mids) if (m < y) n++;
  return n;
}
/** A critically damped spring (damping 1, no overshoot: a drop has no momentum) with Apple's `response` in seconds,
 *  as a CSS `linear()` easing and the time it takes to settle within half a pixel of a `distance` px move (at least
 *  120 ms, so even a short hop reads as a settle). x(t) = 1 − (1 + ωt)·e^(−ωt), ω = 2π / response. */
export function dropSpring(distance: number, response = 0.3): { duration: number; easing: string } {
  const w = (2 * Math.PI) / response;
  const x = (t: number) => 1 - (1 + w * t) * Math.exp(-w * t);
  const d = Math.max(Math.abs(distance), 1);
  let t = 0;
  while (t < 2 && (1 - x(t)) * d > 0.5) t += 0.005;
  const duration = Math.max(0.12, t);
  const steps = 24;
  const pts = Array.from({ length: steps + 1 }, (_, i) => Math.round(x((duration * i) / steps) * 1000) / 1000);
  pts[steps] = 1;
  return { duration: Math.round(duration * 1000), easing: `linear(${pts.join(', ')})` };
}

// ---------- the right-click menu (I7: Open · Play · Add to favourites / Remove · Hide from sidebar · Show in Finder) ----------

export type MenuAction = 'open' | 'play' | 'fav-add' | 'fav-remove' | 'hide' | 'show' | 'finder';
export type MenuEntry = { action: MenuAction; label: string; note?: string };
export const HIDE_NOTE = 'Settings brings it back';

/** The menu of a row. Hide only on a crate under its watched folder (a favourite stays a favourite; its row there has
 *  no Hide), and on a hidden crate the filter lists, Show in sidebar; Show in Finder only where `api.reveal` can open
 *  the folder (inside the music folder). */
export function menuFor(row: ViewRow | CollectionRow, favourites: ReadonlySet<string>): MenuEntry[] {
  const out: MenuEntry[] = [{ action: 'open', label: 'Open' }, { action: 'play', label: 'Play' }];
  if (row.kind === 'view') return out;
  out.push(favourites.has(row.target) ? { action: 'fav-remove', label: 'Remove from favourites' }
    : { action: 'fav-add', label: 'Add to favourites' });
  if (row.kind === 'folder' && row.crate && row.place === 'folders') {
    out.push(row.crate.hidden ? { action: 'show', label: 'Show in sidebar' }
      : { action: 'hide', label: 'Hide from sidebar', note: HIDE_NOTE });
  }
  if (revealPath(row) !== null) out.push({ action: 'finder', label: 'Show in Finder' });
  return out;
}
/** What `set_crate_shown` gets to hide or show a crate: the override only where it differs from the default (shown,
 *  or hidden under a folder with too many), else null (back to the default). */
export const crateShownValue = (tooMany: boolean, show: boolean): boolean | null =>
  show ? (tooMany ? true : null) : (tooMany ? null : false);

/** The library view a row's Play starts from (its own order, every file there). */
export function playCall(row: ViewRow | CollectionRow): { view: LibraryView; key: string | null } {
  if (row.kind === 'view') return { view: row.target === UNLISTED ? 'unlisted' : 'all', key: null };
  if (row.kind === 'playlist') return { view: 'playlist', key: row.name };
  return { view: 'folder', key: row.path };
}
