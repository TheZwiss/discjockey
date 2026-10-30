// The browser column's rows (plan library stage 5, D4 and I7; notes N2–N4, N9, N13): what BrowserColumn.svelte shows,
// pure. On top without a head All tracks and Not in a playlist, then the sections (Favourites from step B, above
// Playlists), Playlists in playlists.txt order (download priority, switched-off ones in place and dimmed) or A–Z, and
// Folders (step A: the Library folders no playlist uses). Each row one line.
//
// The filter (N9): a substring of the names, with case and accents folded ("motley" finds "Mötley"). While filtering, the views step aside, folded sections open,
// every match is listed once in its own section, and exactly one row carries the highlight (the first match; ↑ ↓ move
// it, down to the hand-off row). The hand-off row ("Search tracks for “…”") is the last row whenever there is text,
// and the only one, with the highlight, when no name matches (N3).
import type { PlaylistService, Sidebar } from '../bridge/types';
import { NOT_IN_PLAYLIST } from '../bridge/types';
import { buildHash, libraryHref } from '../router';

export const HANDOFF = 'handoff';

/** The matched letters of a name, as [start, end) in the name (null: nothing to mark, no filter). */
export type Match = [number, number] | null;

export type ViewRow = { kind: 'view'; key: string; name: string; count: number; href: string };
export type PlaylistRow = { kind: 'playlist'; key: string; name: string; service: PlaylistService | null;
  enabled: boolean; count: number; href: string; tip: string; match: Match };
export type FolderRow = { kind: 'folder'; key: string; name: string; count: number; href: string; tip: string;
  match: Match };
export type HandoffRow = { kind: 'handoff'; key: typeof HANDOFF; text: string; href: string; tip: string };
export type BrowserRow = ViewRow | PlaylistRow | FolderRow | HandoffRow;

export type Section = {
  key: 'playlists' | 'folders'; label: string;
  /** the head's count (Playlists: every line; none while filtering, where only matches are listed) */
  count: number | null;
  /** its rows show: unfolded, or filtering (a filter opens folded sections) */
  open: boolean;
  /** the head folds it (not while filtering) */
  foldable: boolean;
  rows: (PlaylistRow | FolderRow)[];
};

export type BrowserList = {
  views: ViewRow[];
  sections: Section[];
  handoff: HandoffRow | null;
  /** the rows Enter can open, in screen order (filtering only; empty otherwise) */
  targets: string[];
};

export type BrowserInput = { side: Sidebar | null; query: string; az: boolean; closed: readonly string[] };

const SERVICE_NAME: Record<PlaylistService, string> = { spotify: 'Spotify', qobuz: 'Qobuz' };

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

export function playlistTip(p: { name: string; service: PlaylistService | null; enabled: boolean; songs: number | null }): string {
  const kind = p.service ? `${SERVICE_NAME[p.service]} playlist · ` : '';
  return `${p.name}\n${kind}${p.songs ?? 0} tracks${p.enabled ? '' : '\nSwitched off: its files stay, nothing new downloads'}`;
}
export const folderTip = (f: { name: string; files: number }): string =>
  `Library › ${f.name}\n${f.files} tracks · no playlist uses it`;
export const handoffTip = (text: string): string =>
  `Search every track’s title and artist for “${text}” (All tracks)`;
export const sortTip = (az: boolean): string => (az ? 'Order: A–Z · click for download priority'
  : 'Order: download priority (change it on the Playlists page) · click for A–Z');
export const EDGE_TIP = 'Drag to resize · double-click to reset';
/** The edge's width for a screen reader. */
export const edgeValueText = (w: number): string => `${w} px`;

/** A row's element id (`aria-activedescendant` names the highlighted one): `bc-` and its key, every character that
 *  can't stand in an id spelled out, so two keys never share an id. */
export const rowId = (key: string): string =>
  `bc-${key.replace(/[^A-Za-z0-9_-]/g, (c) => `.${c.codePointAt(0)!.toString(16)}.`)}`;

const byName = (a: { name: string }, b: { name: string }) =>
  a.name.localeCompare(b.name, undefined, { sensitivity: 'base', numeric: true });

export function browserList({ side, query, az, closed: storedClosed }: BrowserInput): BrowserList {
  // a stored value is only checked for its type (getPref), so an object or a string can stand here
  const closed = Array.isArray(storedClosed) ? storedClosed : [];
  const q = filterText(query);
  const filtering = q !== '';
  if (!side) {
    return { views: [], sections: [], targets: [], handoff: filtering ? handoff(query) : null };
  }
  const views: ViewRow[] = filtering ? [] : [
    { kind: 'view', key: 'view:all', name: 'All tracks', count: side.all_tracks, href: libraryHref(null) },
    ...(side.not_in_playlist > 0 ? [{ kind: 'view' as const, key: 'view:unlisted', name: 'Not in a playlist',
      count: side.not_in_playlist, href: libraryHref(NOT_IN_PLAYLIST) }] : []),
  ];

  // a ref twice in playlists.txt still gets two rows, each with its own key
  const seen = new Set<string>();
  let playlists: PlaylistRow[] = side.playlists.map((p, i) => {
    let key = `pl:${p.ref}`;
    if (seen.has(key)) key = `${key}#${i}`;
    seen.add(key);
    return { kind: 'playlist', key, name: p.name, service: p.service, enabled: p.enabled, count: p.songs ?? 0,
      href: libraryHref(p.name), tip: playlistTip(p), match: null };
  });
  if (az) playlists = [...playlists].sort(byName);
  let folders: FolderRow[] = side.library_folders.map((f) => ({ kind: 'folder', key: `fo:${f.name}`, name: f.name,
    count: f.files, href: libraryHref(f.name), tip: folderTip(f), match: null }));

  if (filtering) {
    const keep = <T extends PlaylistRow | FolderRow>(rows: T[]): T[] => rows.flatMap((r) => {
      const m = matchName(r.name, q);
      return m === false ? [] : [{ ...r, match: m }];
    });
    playlists = keep(playlists);
    folders = keep(folders);
  }

  const section = (key: Section['key'], label: string, rows: (PlaylistRow | FolderRow)[], count: number | null): Section => ({
    key, label, rows, count: filtering ? null : count, foldable: !filtering, open: filtering || !closed.includes(key) });
  const sections: Section[] = [];
  // step B: Favourites goes here, above Playlists (it steps aside while filtering, N9)
  if (playlists.length) sections.push(section('playlists', 'Playlists', playlists, side.playlists.length));
  if (folders.length) sections.push(section('folders', 'Folders', folders, null));

  const ho = filtering ? handoff(query) : null;
  const targets = filtering ? [...sections.flatMap((s) => s.rows.map((r) => r.key)), HANDOFF] : [];
  return { views, sections, handoff: ho, targets };
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

/** The row of the collection on screen: `folder` is the library route's folder param (undefined: not on Library;
 *  null: All tracks). Step A keys a playlist and a Library folder by name, and no Library folder shares a playlist's
 *  name (it is one no playlist uses), so the first playlist of that name, else the folder. */
export function currentKey(side: Sidebar | null, folder: string | null | undefined): string | null {
  if (folder === undefined) return null;
  if (folder === null) return 'view:all';
  if (folder === NOT_IN_PLAYLIST) return 'view:unlisted';
  if (!side) return null;
  const p = side.playlists.find((x) => x.name === folder);
  if (p) return `pl:${p.ref}`;
  return side.library_folders.some((f) => f.name === folder) ? `fo:${folder}` : null;
}

/** A folded section's key in or out of the remembered list. */
export function toggleClosed(closed: readonly string[], key: string): string[] {
  return closed.includes(key) ? closed.filter((k) => k !== key) : [...closed, key];
}
