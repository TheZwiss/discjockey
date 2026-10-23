// Pure helpers for the Library page (sorting, windowing, selection, the filter strip, the panel). Tested in
// libraryModel.test.ts.
import type { Library, LibraryFilter, LibrarySort, Quality, TrackDetail, TrackRow } from '$lib/bridge/types';
import { NOT_IN_PLAYLIST } from '$lib/bridge/types';
import type { SegOption } from '$lib/components/segmentedModel';

export type SortColumn = 'title' | 'artist' | 'folder' | 'source' | 'added' | 'length' | 'quality';
export const DEFAULT_SORT: LibrarySort = 'artist';
export const SORT_COLUMNS: SortColumn[] = ['title', 'artist', 'folder', 'source', 'added', 'length', 'quality'];
/** Above this many rows only the visible rows (plus overscan) are rendered. */
export const WINDOW_FROM = 300;
export const OVERSCAN = 10;

/** Header click: same column → flips direction; another column → ascending. */
export function nextSort(current: LibrarySort, column: SortColumn): LibrarySort {
  if (current === column) return `-${column}`;
  return column;
}

/** The column a sort value belongs to and its direction (for the header arrow). */
export function sortState(sort: LibrarySort): { column: string; desc: boolean } {
  return sort.startsWith('-') ? { column: sort.slice(1), desc: true } : { column: sort, desc: false };
}

export function isSort(v: unknown): v is LibrarySort {
  if (typeof v !== 'string') return false;
  const c = v.startsWith('-') ? v.slice(1) : v;
  return (SORT_COLUMNS as string[]).includes(c);
}

/** Rows to render: all of them up to WINDOW_FROM, else the visible ones plus OVERSCAN on each side. */
export function windowSlice(scrollTop: number, viewport: number, rowH: number, count: number,
  overscan = OVERSCAN, from = WINDOW_FROM): { start: number; end: number } {
  if (count <= from || rowH <= 0) return { start: 0, end: count };
  const first = Math.floor(Math.max(0, scrollTop) / rowH);
  const last = Math.ceil((Math.max(0, scrollTop) + Math.max(0, viewport)) / rowH);
  return { start: Math.max(0, first - overscan), end: Math.min(count, last + overscan) };
}

/** The scrollTop that keeps row `index` in view (unchanged when it already is). */
export function scrollToKeep(scrollTop: number, viewport: number, rowH: number, index: number): number {
  if (index < 0) return scrollTop;
  const top = index * rowH;
  if (top < scrollTop) return top;
  if (top + rowH > scrollTop + viewport) return Math.max(0, top + rowH - viewport);
  return scrollTop;
}

/** scrollTop that puts row `index` in the middle of the view (first load with ?track=). */
export function scrollToCenter(viewport: number, rowH: number, index: number): number {
  return index < 0 ? 0 : Math.max(0, index * rowH - (viewport - rowH) / 2);
}

/** Selection survives a re-fetch by track id; the index is -1 when the track is not in the new rows. */
export function selectedIndex(rows: TrackRow[], id: string | null): number {
  return id === null ? -1 : rows.findIndex((r) => r.track_id === id);
}

/** ↑/↓: the next selected id (stays at the ends; nothing selected → first/last row). */
export function moveSelection(rows: TrackRow[], id: string | null, delta: 1 | -1): string | null {
  if (!rows.length) return null;
  const i = selectedIndex(rows, id);
  if (i < 0) return rows[delta > 0 ? 0 : rows.length - 1].track_id;
  return rows[Math.min(rows.length - 1, Math.max(0, i + delta))].track_id;
}

/** "Open in to-do" only for tracks the to-do list shows: in a playlist, not hidden, and not lossless or with an upgrade
 *  ready (views.todo; a track in no playlist or a hidden one isn't there, so the link would find nothing). */
export function inTodo(t: Pick<TrackRow, 'status' | 'upgrade_ready' | 'in_playlists' | 'hidden'>): boolean {
  return t.in_playlists && !t.hidden && (t.status !== 'lossless' || t.upgrade_ready);
}

export function todoHref(id: string): string {
  return `/todo?track=${encodeURIComponent(id)}`;
}

/** Remembered filter per folder. */
export function filterKey(folder: string | null): string {
  return `library.filter.${folder === null ? '__all__' : folder === NOT_IN_PLAYLIST ? '__not_in_playlist__' : folder}`;
}
export const SORT_KEY = 'library.sort';

const FILTERS: { key: LibraryFilter; label: string; dot: Quality | null }[] = [
  { key: 'all', label: 'All', dot: null }, { key: 'lossless', label: 'Lossless', dot: 'lossless' },
  { key: 'good_lossy', label: 'Good lossy', dot: 'good_lossy' }, { key: 'weak', label: 'Weak', dot: 'weak' },
  { key: 'fake', label: 'Fake', dot: 'fake' }, { key: 'upgrade_ready', label: 'Upgrade ready', dot: 'lossless' },
];
export const LIBRARY_FILTERS = FILTERS.map((f) => f.key);
/** The quality filter as one Segmented strip, in this order; Fake only when there are fake files (or it is chosen). */
export function segOptions(chips: Library['chips'] | null | undefined, value: LibraryFilter): SegOption<LibraryFilter>[] {
  const c = chips ?? { all: 0, lossless: 0, good_lossy: 0, weak: 0, fake: 0, upgrade_ready: 0 };
  return FILTERS.filter((f) => f.key !== 'fake' || c.fake > 0 || value === 'fake')
    .map((f) => ({ key: f.key, label: f.label, count: c[f.key], dot: f.dot }));
}

/** The table's optional columns, in the order they appear as the table gets wider (spec §3: more space shows more).
 *  All tracks spans every folder, so its first one is Folder. */
export function optionalColumns(allTracks: boolean): ('folder' | 'source' | 'added')[] {
  return allTracks ? ['folder', 'source', 'added'] : ['source', 'added'];
}
/** A row's folder cell: a track in no playlist reads so instead of the folder it sits in on disk. */
export function folderCell(r: Pick<TrackRow, 'folder' | 'in_playlists'>): string {
  return r.in_playlists ? r.folder : 'Not in a playlist';
}

/** The panel's foot: Swap when the upgrade matches exactly; Open in to-do for any other to-do; nothing for a
 *  lossless track (or one the to-do list doesn't show). */
export function footAction(t: Pick<TrackDetail, 'upgrade' | 'status' | 'upgrade_ready' | 'in_playlists' | 'hidden'>):
    'swap' | 'todo' | null {
  if (t.upgrade?.swap_safe && t.upgrade.swap_possible) return 'swap';
  return inTodo(t) ? 'todo' : null;
}

/** The panel with nothing picked: the folder's lossless share (a StatCard over the quality bar). */
export function overview(s: Library['summary']): { value: string | null; unit?: string; label: string } {
  if (!s.tracks || s.lossless_share === null) return { value: null, label: 'lossless · no tracks yet' };
  return { value: String(Math.round(s.lossless_share * 100)), unit: '%',
    label: `lossless · ${s.by_quality.lossless} of ${s.tracks} ${s.tracks === 1 ? 'track' : 'tracks'}` };
}

/** The file's name from its path; the folder is in the track card already. */
export function fileName(path: string | null | undefined): string {
  if (!path) return '';
  return path.slice(path.lastIndexOf('/') + 1);
}

/** "youtube.com/watch?v=…" from a source URL: host without www, path shortened. */
export function shortUrl(url: string | null | undefined, max = 9): string {
  if (!url) return '';
  try {
    const u = new URL(url);
    const host = u.hostname.replace(/^www\./, '');
    const rest = `${u.pathname === '/' ? '' : u.pathname}${u.search}`;
    if (!rest) return host;
    return rest.length > max ? `${host}${rest.slice(0, max)}…` : `${host}${rest}`;
  } catch {
    return url;
  }
}

/** "Hard_Bounce · in 2 playlists" (null count → just the folder); a track in no playlist says so. */
export function placeLine(folder: string, count: number | null | undefined, inPlaylists = true): string {
  if (!inPlaylists) return 'Not in a playlist';
  if (count === null || count === undefined) return folder;
  return `${folder} · in ${count} ${count === 1 ? 'playlist' : 'playlists'}`;
}
