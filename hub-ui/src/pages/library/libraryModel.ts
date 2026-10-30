// Pure helpers for the Library page (sorting, windowing, selection, the filter segments, the columns, the inspector).
// Tested in libraryModel.test.ts.
import type { Library, LibraryFilter, LibraryRow, LibrarySort, LibraryView as WireView, Quality, Sidebar, TrackDetail,
  TrackRow } from '$lib/bridge/types';
import { NOT_IN_PLAYLIST, QUALITIES } from '$lib/bridge/types';
import type { SegOption } from '$lib/components/segmentedModel';

/** The columns a header click sorts by. Source and Added left the table (plan library stage 5 D10: the inspector shows
 *  both), so a sort by them saved before isn't one any more (isSort): it falls back to the default, rather than sort
 *  the rows by a column nobody can see. */
export type SortColumn = 'title' | 'artist' | 'folder' | 'length' | 'quality';
export const DEFAULT_SORT: LibrarySort = 'artist';
export const SORT_COLUMNS: SortColumn[] = ['title', 'artist', 'folder', 'length', 'quality'];
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

/** Whether the selected track is known to be off the table (its details then don't stand, stores/chrome.ts
 *  `detailsStand`): not among the rows shown, filtered or searched away, gone from the library, or no rows at all (an
 *  empty library or folder, nothing matches). Not known (false) before the first answer, or while the answer on
 *  screen is still another folder's (a link into a new folder with a track): the selection came from a table.
 *  `answeredFor` is the route's folder param the answer on screen was asked for; the answer's own `key` is not
 *  compared, since the engine echoes its spelling of it (`Library/Old_Sets` for the route's `Old_Sets`). */
export function offTable(lib: Pick<Library, 'rows'> | null, answeredFor: string | null | undefined, folder: string | null,
  track: string | null): boolean {
  if (!lib || track === null || answeredFor !== folder) return false;
  return !lib.rows.some((r) => r.track_id === track);
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

/** Which list the table shows: one playlist's folder, All tracks (rows of every folder), or Not in a playlist (rows
 *  that no folder holds, so a Folder column would say the same on every row). */
export type LibraryView = 'folder' | 'all' | 'unlisted';
export function libraryView(folder: string | null): LibraryView {
  return folder === null ? 'all' : folder === NOT_IN_PLAYLIST ? 'unlisted' : 'folder';
}
/** The table's optional columns (plan library stage 5 D10, notes N6, the mockup's `columns()`): Track, Artist, Quality
 *  and the upgrade slot are always there; these come in as the table's own width allows, in this order, and go in the
 *  reverse one (Length first, Folder last). A column that would say the same on every row isn't one: a playlist's
 *  rows all sit in its folder, so it has Length only (its order carries the rest). All tracks and Not in a playlist
 *  name the Folder. *Playlist* (the playlists holding the song, +180 px, between Folder and Length) joins in step B,
 *  when the rows carry them; today a track's folder is its playlist's, so the column would repeat Folder. */
export type OptionalColumn = 'folder' | 'length';
export function optionalColumns(view: LibraryView): OptionalColumn[] {
  return view === 'folder' ? ['length'] : ['folder', 'length'];
}
/** The width (px) the table needs for Track and Artist beside Quality and the upgrade slot, and what each optional
 *  column adds to it (D10, the mockup's numbers): a column shows from the sum of its own and those before it. */
export const BASE_WIDTH = 380;
export const COLUMN_WIDTH: Record<OptionalColumn, number> = { folder: 140, length: 200 };
/** The table's own width from which each of the view's optional columns shows (All tracks: Folder 520, Length 720). */
export function columnThresholds(view: LibraryView): { column: OptionalColumn; from: number }[] {
  let need = BASE_WIDTH;
  return optionalColumns(view).map((column) => ({ column, from: (need += COLUMN_WIDTH[column]) }));
}
/** The optional columns a table this wide shows. */
export function columnsAt(view: LibraryView, width: number): OptionalColumn[] {
  return columnThresholds(view).filter((t) => width >= t.from).map((t) => t.column);
}
/** The grid's tracks for those columns: the names share what is left (Track a little more than Artist, Folder less:
 *  with the details open at 1280 a wider Folder cut the artists while "Hard_Bounce" had room to spare; the mockup's
 *  116 px / .95fr), Folder never below a playlist folder's name ("Hard_Bounce"), Length fits "12:34", Quality the widest badge (FAKE · 16.0 kHz), so
 *  every badge starts at one x, and the slot fits UPGRADE. */
const TRACK: Record<OptionalColumn | 'title' | 'artist' | 'end', string> = {
  title: 'minmax(0, 1.45fr)', artist: 'minmax(0, 1fr)', folder: 'minmax(96px, .8fr)', length: '52px',
  end: '116px var(--w-row-action)',
};
export function gridColumns(cols: OptionalColumn[]): string {
  return [TRACK.title, TRACK.artist, ...cols.map((c) => TRACK[c]), TRACK.end].join(' ');
}
/** A row reads dimmed when its song left every playlist (a downloaded file nothing holds any more). A file of the
 *  user's own is in no playlist by nature, so it is never dimmed: dimming it would say "gone" about a file that is
 *  exactly where its owner put it. */
export function rowOff(r: Pick<TrackRow, 'in_playlists' | 'own'>): boolean {
  return !r.in_playlists && !r.own;
}
/** Why a dimmed leftover row is dimmed. The Folder column says it too ("Not in a playlist"), but only at the widths
 *  that show that column; this is the same word on the title cell at every width. */
export const ROW_OFF_REASON = 'Not in any playlist any more';
/** The title cell's tooltip: the full name (the cell cuts a long one), and under it, for a dimmed leftover row, why it
 *  is dimmed. An away row (drive or folder not there) keeps the name alone: its `AwayTag` says why it can't play. */
export function rowTitleTip(r: Pick<LibraryRow, 'in_playlists' | 'own' | 'file_state'>, name: string): string {
  return rowOff(r) && rowAway(r) === null ? `${name}\n${ROW_OFF_REASON}` : name;
}
/** Whether a row's file is there to play: not when its drive is offline or its watched folder isn't found
 *  (`file_state`, decided per folder by the engine). Enter, double-click and the cover play only such a row, and the
 *  player's queue holds only these. */
export function playable(r: Pick<LibraryRow, 'file_state'>): boolean {
  return r.file_state === 'here';
}
/** An away row: dimmed like a leftover one (it can't play), and its `AwayTag` says why. */
export function rowAway(r: Pick<LibraryRow, 'file_state'>): Exclude<LibraryRow['file_state'], 'here' | 'no_file'> | null {
  return r.file_state === 'here' || r.file_state === 'no_file' ? null : r.file_state;
}
/** A row's Folder cell. All tracks: the folder of its playlist, or "Not in a playlist" for a track in none. Not in a
 *  playlist (every row in none): the folder the file sits in, which is what tells its rows apart. Null: nothing there
 *  (the cell shows "–"). */
export function folderCell(r: Pick<TrackRow, 'folder' | 'in_playlists'>, view: LibraryView = 'all'): string | null {
  if (view !== 'unlisted' && !r.in_playlists) return 'Not in a playlist';
  return r.folder || null;
}

/** The panel's foot: Swap when the upgrade matches exactly; Open in to-do for any other to-do; nothing for a
 *  lossless track (or one the to-do list doesn't show). */
export function footAction(t: Pick<TrackDetail, 'upgrade' | 'status' | 'upgrade_ready' | 'in_playlists' | 'hidden'>):
    'swap' | 'todo' | null {
  if (t.upgrade?.swap_safe && t.upgrade.swap_possible) return 'swap';
  return inTodo(t) ? 'todo' : null;
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

/** The panel head's place: the folder the file sits in; a track in no playlist says so. (Which playlists it is in is
 *  the Playlists row, by name: a count here was cut at 1100 and named none of them.) */
export function placeLine(folder: string, inPlaylists = true): string {
  return inPlaylists ? folder : 'Not in a playlist';
}

/** One `library(view, key, …)` call (the engine answers one view of the library per call). */
export type LibraryCall = { view: WireView; key: string | null };
const same = (a: string, b: string): boolean => a.normalize('NFC').toLowerCase() === b.normalize('NFC').toLowerCase();
/** The calls that answer the page's `folder` (the route's param: null = All tracks, NOT_IN_PLAYLIST, a path, or a name; the
 *  new routes of plan library stage 5 I5 replace this). A name is a playlist's folder when the sidebar lists one of
 *  that name, else a Library folder no playlist uses (`Library/<name>`); a name nothing lists is asked as a playlist,
 *  which the engine answers with `empty: 'gone'`. Without the sidebar yet (the window just opened) both are tried in
 *  that order: the second only when the first came back gone. */
export function libraryCalls(folder: string | null, side: Pick<Sidebar, 'playlists' | 'library_folders'> | null): LibraryCall[] {
  if (folder === null) return [{ view: 'all', key: null }];
  if (folder === NOT_IN_PLAYLIST) return [{ view: 'unlisted', key: null }];
  // an import folder or a crate (the browser column links them by their path, plan library stage 5 I5)
  if (folder.startsWith('/')) return [{ view: 'folder', key: folder }];
  const asPlaylist: LibraryCall = { view: 'playlist', key: folder };
  const asFolder: LibraryCall = { view: 'folder', key: `Library/${folder}` };
  if (!side) return [asPlaylist, asFolder];
  if (side.playlists.some((p) => same(p.name, folder))) return [asPlaylist];
  const lib = side.library_folders.find((f) => same(f.name, folder));
  return lib ? [{ view: 'folder', key: lib.path }] : [asPlaylist];
}
// --- today's playlist screen, until the playlist views are drawn (plan library stage 5, B6) ---
const fold = (x: string): string => x.normalize('NFC').toLowerCase();
const SORT_KEYS: Record<string, (r: LibraryRow) => string | number | (string | number | boolean)[]> = {
  title: (r) => fold(r.title),
  artist: (r) => [fold(r.artist), fold(r.title)],
  length: (r) => r.duration_s,
  source: (r) => r.source_name ?? '',
  quality: (r) => (r.sound_checked ? QUALITIES.indexOf(r.quality) : QUALITIES.length),
  added: (r) => r.added ?? '',
  order: (r) => [r.position === null, r.position ?? 0],
  folder: (r) => [!r.in_playlists, fold(r.folder), fold(r.artist), fold(r.title)],
};
function compareKeys(a: unknown, b: unknown): number {
  if (Array.isArray(a) && Array.isArray(b)) {
    for (let i = 0; i < Math.min(a.length, b.length); i++) {
      const c = compareKeys(a[i], b[i]);
      if (c) return c;
    }
    return a.length - b.length;
  }
  return (a as number) < (b as number) ? -1 : (a as number) > (b as number) ? 1 : 0;
}
/** A filter chip never holds a file whose sound isn't checked yet; only All does (views._matches). */
const inFilter = (r: LibraryRow, f: LibraryFilter): boolean =>
  f === 'all' || (f === 'upgrade_ready' ? r.upgrade_ready : r.sound_checked && r.quality === f);
/** The playlist's own summary (it counts the songs it holds that have a file) with the leftover files added, counted
 *  as views._group counts a row's to-do state. */
function summaryWith(base: Library['summary'], extra: LibraryRow[]): Library['summary'] {
  const by = { ...base.by_quality };
  for (const r of extra) if (r.sound_checked) by[r.quality]++;
  const counted = Object.values(by).reduce((n, c) => n + c, 0);
  return { tracks: base.tracks + extra.length, lossless_share: counted ? Math.round((by.lossless / counted) * 10000) / 10000 : null,
    by_quality: by, upgrades_ready: base.upgrades_ready + extra.filter((r) => r.upgrade_ready).length,
    not_lossless: by.good_lossy + by.weak + by.fake,
    to_do: base.to_do + extra.filter((r) => r.in_playlists && !r.hidden && r.sound_checked
      && (r.upgrade_ready || r.quality === 'weak' || r.quality === 'good_lossy' || r.quality === 'fake')).length };
}
const tracksWord = (n: number): string => (n === 1 ? '1 track' : `${n} tracks`);
/** What ▶ queues for a collection asked whole (no search, no filter) in `sort`: the page's own list (a playlist's
 *  leftover files merged in by `asToday`) and, of it, the rows whose file is there. The browser's Play uses it, so
 *  both start the same queue. */
export function playQueue<L extends Library>(lib: L, sort: LibrarySort): LibraryRow[] {
  return asToday(lib, '', 'all', sort).rows.filter(playable);
}
/** A playlist view as the page drew a folder before the playlist views: the playlist's songs with a file and the files
 *  of its own Library folder it does not hold (`also`, the leftovers, dimmed by their own row fields) are one list,
 *  with the counts of that list; the songs still waiting for a file are left out. `lib` must be asked for without
 *  search and filter (the summary and the chips count the whole list; the search and the filter are applied here, as
 *  the engine applies them to a folder). Any other view, and a playlist that is gone, comes back as it is.
 *  B6 draws the waiting rows and the `also` section itself and removes this. */
export function asToday<L extends Library>(lib: L, query: string, filter: LibraryFilter, sort: LibrarySort): L {
  if (lib.view !== 'playlist' || lib.empty === 'gone') return lib;
  const files = [...lib.rows.filter((r) => r.file_state !== 'no_file'), ...(lib.also ?? [])];
  const q = fold(query ?? '').trim();
  const found = q ? files.filter((r) => fold(`${r.artist} ${r.title}`).includes(q)) : files;
  const chips = Object.fromEntries(LIBRARY_FILTERS.map((f) => [f, found.filter((r) => inFilter(r, f)).length])) as Library['chips'];
  const key = SORT_KEYS[sort.replace(/^-/, '')] ?? SORT_KEYS.artist;
  const sign = sort.startsWith('-') ? -1 : 1;
  const rows = found.filter((r) => inFilter(r, filter)).sort((a, b) => sign * compareKeys(key(a), key(b)));
  // the engine counts only the songs with a file that the playlist holds: the count part is this list's
  const [first, ...rest] = lib.subtitle;
  const subtitle = lib.read_at === null
    ? (files.length ? [tracksWord(files.length), first, ...(lib.enabled === false ? ['switched off'] : []), `Library › ${lib.title}`]
      : lib.subtitle)
    : [tracksWord(files.length), ...rest];
  return { ...lib, rows, also: null, chips, summary: summaryWith(lib.summary, lib.also ?? []), subtitle,
    empty: lib.empty === 'empty_library' ? lib.empty : null };
}
