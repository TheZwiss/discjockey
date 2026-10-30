// Pure helpers for the Library page (sorting, windowing, selection, the filter segments, the columns, the row signals,
// the words of the header and the empty states, the inspector). Tested in libraryModel.test.ts.
import type { Library, LibraryFilter, LibraryRow, LibrarySort, LibraryView, Quality, Sidebar, TrackDetail,
  TrackRow } from '$lib/bridge/types';
import { NOT_IN_PLAYLIST } from '$lib/bridge/types';
import type { SegOption } from '$lib/components/segmentedModel';
import { dayMonth } from '$lib/format';
import { EMPTY } from '$lib/copy';

// ---------- what kind of collection the table shows ----------
/** The table's kind: the four views, with a folder view told apart by what the folder is (plan library stage 5 D10:
 *  each has its own column set). A folder whose kind isn't known (gone) is drawn as a Library folder. */
export type TableKind = 'all' | 'unlisted' | 'playlist' | 'library' | 'watched' | 'crate';
export function tableKind(lib: Pick<Library, 'view' | 'folder_kind'>): TableKind {
  if (lib.view !== 'folder') return lib.view;
  return lib.folder_kind ?? 'library';
}

// ---------- sorting (a saved sort per view kind) ----------
/** The columns a header click sorts by (the engine's sorts, views.SORTS). Source and Added left the table (D10: the
 *  inspector shows both), and the engine has no sort by Subfolder or Playlist, so those heads don't sort. `order` is a
 *  playlist's own (the `#` column), `folder` the two views' Folder column. */
export type SortColumn = 'order' | 'title' | 'artist' | 'folder' | 'length' | 'quality';
const COMMON: SortColumn[] = ['title', 'artist', 'length', 'quality'];
export function sortColumns(view: LibraryView): SortColumn[] {
  if (view === 'playlist') return ['order', ...COMMON];
  if (view === 'folder') return COMMON;
  return [...COMMON, 'folder'];
}
/** A playlist starts in its own order (D9), every other view by Artist ↑ (the mockup). */
export function defaultSort(view: LibraryView): LibrarySort {
  return view === 'playlist' ? 'order' : 'artist';
}
/** Each view kind remembers its own sort: a playlist sorted by Length doesn't turn All tracks round, and `order` (a
 *  playlist's) never reaches a view that has no order. */
export function sortKey(view: LibraryView): string {
  return `library.sort.${view}`;
}
/** The sort every view shared before (step A); a view kind with no sort of its own yet starts from it. */
export const LEGACY_SORT_KEY = 'library.sort';
export function isSort(v: unknown, view: LibraryView): v is LibrarySort {
  if (typeof v !== 'string') return false;
  const c = v.startsWith('-') ? v.slice(1) : v;
  return (sortColumns(view) as string[]).includes(c);
}
/** The sort a view kind opens with: its own saved one, else the shared one from before (when this view has that
 *  column), else its default. */
export function viewSort(view: LibraryView, saved: unknown, legacy: unknown = null): LibrarySort {
  if (isSort(saved, view)) return saved;
  if (isSort(legacy, view)) return legacy;
  return defaultSort(view);
}

/** Header click: same column → flips direction; another column → ascending. */
export function nextSort(current: LibrarySort, column: SortColumn): LibrarySort {
  if (current === column) return `-${column}`;
  return column;
}

/** The column a sort value belongs to and its direction (for the header arrow). */
export function sortState(sort: LibrarySort): { column: string; desc: boolean } {
  return sort.startsWith('-') ? { column: sort.slice(1), desc: true } : { column: sort, desc: false };
}

// ---------- windowing and selection ----------
/** Above this many rows only the visible rows (plus overscan) are rendered. */
export const WINDOW_FROM = 300;
export const OVERSCAN = 10;

/** Rows to render: all of them up to WINDOW_FROM, else the visible ones plus OVERSCAN on each side. */
export function windowSlice(scrollTop: number, viewport: number, rowH: number, count: number,
  overscan = OVERSCAN, from = WINDOW_FROM): { start: number; end: number } {
  if (count <= from || rowH <= 0) return { start: 0, end: count };
  const first = Math.floor(Math.max(0, scrollTop) / rowH);
  const last = Math.ceil((Math.max(0, scrollTop) + Math.max(0, viewport)) / rowH);
  return { start: Math.max(0, first - overscan), end: Math.min(count, last + overscan) };
}

/** The scrollTop that keeps a line (its top and height in px) in view, unchanged when it already is; `clear`: the
 *  height at the top it must stay below (a stuck section head over the rows of its section). */
export function keepLine(scrollTop: number, viewport: number, top: number, height: number, clear = 0): number {
  if (top - clear < scrollTop) return Math.max(0, top - clear);
  if (top + height > scrollTop + viewport) return Math.max(0, top + height - viewport);
  return scrollTop;
}

/** The scrollTop that puts a line in the middle of the view (first load with ?track=). */
export function centerLine(viewport: number, top: number, height: number): number {
  return Math.max(0, top - (viewport - height) / 2);
}

/** The table's lines in order: the main rows, then (a playlist whose folder holds files it doesn't) the main part's
 *  empty line when it has no rows, the `Also in this folder` head and those files. One table, one column grid (D9). */
export type TableLine = { kind: 'row'; row: LibraryRow; also: boolean } | { kind: 'empty'; text: string } | { kind: 'section' };
export function tableLines(rows: LibraryRow[], also: LibraryRow[] | null, emptyLine: string | null): TableLine[] {
  const out: TableLine[] = rows.map((row) => ({ kind: 'row', row, also: false }));
  if (also?.length) {
    if (!rows.length && emptyLine) out.push({ kind: 'empty', text: emptyLine });
    out.push({ kind: 'section' });
    for (const row of also) out.push({ kind: 'row', row, also: true });
  }
  return out;
}
/** The top of line `index` when rows are `rowH` high and the other lines (the empty line, the section head) `otherH`. */
export function lineTop(lines: TableLine[], index: number, rowH: number, otherH: number): number {
  let top = 0;
  for (let i = 0; i < Math.min(index, lines.length); i++) top += lines[i].kind === 'row' ? rowH : otherH;
  return top;
}

/** Selection survives a re-fetch by track id; the index is -1 when the track is not in the new rows. */
export function selectedIndex(rows: Pick<TrackRow, 'track_id'>[], id: string | null): number {
  return id === null ? -1 : rows.findIndex((r) => r.track_id === id);
}

/** The rows the table shows, main ones then a playlist's `also` (what ↑ ↓ walk, what a selection is found in). */
export function allRows(lib: Pick<Library, 'rows' | 'also'>): LibraryRow[] {
  return lib.also?.length ? [...lib.rows, ...lib.also] : lib.rows;
}
/** The row of the selected track on the table, if it is there. */
export function rowOf(lib: Pick<Library, 'rows' | 'also'> | null, id: string | null): LibraryRow | null {
  if (!lib || id === null) return null;
  return allRows(lib).find((r) => r.track_id === id) ?? null;
}

/** Whether the selected track is known to be off the table (its details then don't stand, stores/chrome.ts
 *  `detailsStand`): not among the rows shown (a playlist's `also` count), filtered or searched away, gone from the
 *  library, or no rows at all (an empty library or folder, nothing matches). Not known (false) before the first
 *  answer, or while the answer on screen is still another folder's (a link into a new folder with a track): the
 *  selection came from a table. `answeredFor` is the route's folder param the answer on screen was asked for; the
 *  answer's own `key` is not compared, since the engine echoes its spelling of it (`Library/Old_Sets` for the route's
 *  `Old_Sets`). */
export function offTable(lib: Pick<Library, 'rows' | 'also'> | null, answeredFor: string | null | undefined,
  folder: string | null, track: string | null): boolean {
  if (!lib || track === null || answeredFor !== folder) return false;
  return rowOf(lib, track) === null;
}

/** ↑/↓: the next selected id (stays at the ends; nothing selected → first/last row). */
export function moveSelection(rows: Pick<TrackRow, 'track_id'>[], id: string | null, delta: 1 | -1): string | null {
  if (!rows.length) return null;
  const i = selectedIndex(rows, id);
  if (i < 0) return rows[delta > 0 ? 0 : rows.length - 1].track_id;
  return rows[Math.min(rows.length - 1, Math.max(0, i + delta))].track_id;
}

// ---------- to-do ----------
/** "Open in to-do" only for tracks the to-do list shows: in a playlist, not hidden, and not lossless or with an upgrade
 *  ready (views.todo; a track in no playlist or a hidden one isn't there, so the link would find nothing). */
export function inTodo(t: Pick<TrackRow, 'status' | 'upgrade_ready' | 'in_playlists' | 'hidden'>): boolean {
  return t.in_playlists && !t.hidden && (t.status !== 'lossless' || t.upgrade_ready);
}
/** The same for a table row: a song without a file is on the to-do list only when it was not found (its group there);
 *  one still waiting for the next sync isn't. */
export function rowInTodo(r: Pick<LibraryRow, 'status' | 'upgrade_ready' | 'in_playlists' | 'hidden' | 'file_state' | 'wait'>): boolean {
  return r.file_state === 'no_file' ? r.wait === 'not_found' : inTodo(r);
}

export function todoHref(id: string): string {
  return `/todo?track=${encodeURIComponent(id)}`;
}

// ---------- the quality filter ----------
/** Remembered filter per folder. */
export function filterKey(folder: string | null): string {
  return `library.filter.${folder === null ? '__all__' : folder === NOT_IN_PLAYLIST ? '__not_in_playlist__' : folder}`;
}

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

// ---------- columns (D10) ----------
/** The table's optional columns (D10, notes N6, the mockup's `columns()`): Track, Artist, Quality and the upgrade slot
 *  are always there; these come in as the table's own width allows, in this order, and go in the reverse one (Length
 *  first, Subfolder or Folder last). A column that would say the same on every row isn't one: a playlist has Length
 *  only (its order and its "in …" notes carry the rest), a Library folder too (its files hold no crates and no
 *  playlist of their own beyond the one the folder is named for, or none); a watched folder or a crate has Subfolder
 *  only when crates sit inside it (`subfolders`). All tracks and Not in a playlist name the Folder (where the file
 *  sits, D12); Not in a playlist has no Playlist column (every row is in none). */
export type OptionalColumn = 'folder' | 'subfolder' | 'playlist' | 'length';
export function optionalColumns(kind: TableKind, subfolders = false): OptionalColumn[] {
  if (kind === 'all') return ['folder', 'playlist', 'length'];
  if (kind === 'unlisted') return ['folder', 'length'];
  if (kind === 'playlist' || kind === 'library') return ['length'];
  return [...(subfolders ? ['subfolder' as const] : []), 'playlist', 'length'];
}
/** The width (px) the table needs for Track and Artist beside Quality and the upgrade slot, and what each optional
 *  column adds to it (D10, the mockup's numbers): a column shows from the sum of its own and those before it. A
 *  playlist's `#` column comes on top of the base. */
export const BASE_WIDTH = 380;
export const ORDER_WIDTH = 40;
export const COLUMN_WIDTH: Record<OptionalColumn, number> = { folder: 140, subfolder: 140, playlist: 180, length: 200 };
/** The table's own width from which each of the kind's optional columns shows (All tracks: Folder 520, Playlist 700,
 *  Length 900). */
export function columnThresholds(kind: TableKind, subfolders = false): { column: OptionalColumn; from: number }[] {
  let need = BASE_WIDTH + (kind === 'playlist' ? ORDER_WIDTH : 0);
  return optionalColumns(kind, subfolders).map((column) => ({ column, from: (need += COLUMN_WIDTH[column]) }));
}
/** The optional columns a table this wide shows. */
export function columnsAt(kind: TableKind, width: number, subfolders = false): OptionalColumn[] {
  return columnThresholds(kind, subfolders).filter((t) => width >= t.from).map((t) => t.column);
}
/** The grid's tracks for those columns: the names share what is left (Track a little more than Artist, a place less:
 *  with the details open at 1280 a wider Folder cut the artists while "Hard_Bounce" had room to spare; the mockup's
 *  116 px / .95fr), a place never below a playlist folder's name ("Hard_Bounce"), the Playlist badge a little more
 *  than the Artist (a playlist's name and its +n), Length fits "12:34", Quality the widest badge (FAKE · 16.0 kHz), so
 *  every badge starts at one x, and the slot fits UPGRADE. A playlist's `#` comes first and fits "999". */
const TRACK: Record<OptionalColumn | 'order' | 'title' | 'artist' | 'end', string> = {
  order: '24px', title: 'minmax(0, 1.45fr)', artist: 'minmax(0, 1fr)', folder: 'minmax(96px, .8fr)',
  subfolder: 'minmax(96px, .8fr)', playlist: 'minmax(0, 1.1fr)', length: '52px', end: '116px var(--w-row-action)',
};
export function gridColumns(cols: OptionalColumn[], order = false): string {
  return [...(order ? [TRACK.order] : []), TRACK.title, TRACK.artist, ...cols.map((c) => TRACK[c]), TRACK.end].join(' ');
}
/** Whether a watched folder or a crate has crates inside it (its Subfolder column, D10): the sidebar says (a watched
 *  folder's crate count, a crate's `has_crates`); before it is there, the rows do (a row in a crate below). */
export function hasSubfolders(lib: Pick<Library, 'view' | 'folder_kind' | 'key' | 'rows'>,
  side: Pick<Sidebar, 'watched'> | null | undefined): boolean {
  if (lib.view !== 'folder' || (lib.folder_kind !== 'watched' && lib.folder_kind !== 'crate')) return false;
  const key = lib.key === null ? null : samePath(lib.key);
  const w = side?.watched.find((x) => samePath(x.path) === key);
  if (w) return w.crate_count > 0 || w.too_many;
  const c = side?.watched.flatMap((x) => x.crates).find((x) => samePath(x.path) === key);
  if (c) return c.has_crates;
  return lib.rows.some((r) => !!r.subfolder);
}
const samePath = (p: string): string => p.normalize('NFC').replace(/\/+$/, '');

// ---------- the cells ----------
/** The two views' Folder cell: where the file sits (D12, `place`); null → "–". Being in no playlist is told by the
 *  dim and the title's tooltip, not here. */
export function folderCell(r: Pick<LibraryRow, 'place'>): string | null {
  return r.place || null;
}
/** A folder view's Subfolder cell: the crate (a watched folder) or the folders below (a crate); null ("–") for a file
 *  in the folder itself. */
export function subfolderCell(r: Pick<LibraryRow, 'subfolder'>): string | null {
  return r.subfolder || null;
}
/** The Playlist cell: the first playlist holding the song (playlists.txt order) as a neutral badge, "+n" for the
 *  others, and every one of them by name as its tooltip; null ("–") for a song in none. */
export function playlistCell(r: Pick<LibraryRow, 'playlists'>): { name: string; more: number; tip: string } | null {
  if (!r.playlists.length) return null;
  return { name: r.playlists[0], more: r.playlists.length - 1, tip: `In ${r.playlists.join(', ')}` };
}
/** A playlist's row whose file sits outside the playlist's own folder says where, after its title ("in Techno 2019",
 *  D9); it gives way before the title. Null inside the folder (the engine's `place` is null there) and elsewhere. */
export function titleNote(r: Pick<LibraryRow, 'place' | 'file_state'>, kind: TableKind): string | null {
  return kind === 'playlist' && r.place && r.file_state !== 'no_file' ? `in ${r.place}` : null;
}

// ---------- row signals (D6) ----------
/** A row reads dimmed when its song left every playlist (a downloaded file nothing holds any more). A file of the
 *  user's own is in no playlist by nature, so it is never dimmed: dimming it would say "gone" about a file that is
 *  exactly where its owner put it. */
export function rowOff(r: Pick<TrackRow, 'in_playlists' | 'own'>): boolean {
  return !r.in_playlists && !r.own;
}
/** Why a dimmed leftover row is dimmed: the title cell's tooltip says it at every width. */
export const ROW_OFF_REASON = 'Not in any playlist any more';
/** The title cell's tooltip: the full name (the cell cuts a long one), and under it, for a dimmed leftover row, why it
 *  is dimmed. An away row (drive or folder not there) and a song without a file keep the name alone: the quality
 *  column says why. */
export function rowTitleTip(r: Pick<LibraryRow, 'in_playlists' | 'own' | 'file_state'>, name: string): string {
  return rowOff(r) && rowAway(r) === null && r.file_state !== 'no_file' ? `${name}\n${ROW_OFF_REASON}` : name;
}
/** Whether a row's file is there to play: not when its drive is offline or its watched folder isn't found
 *  (`file_state`, decided per folder by the engine), nor for a song with no file yet (`no_file`). Enter, double-click
 *  and the cover play only such a row, and the player's queue holds only these. */
export function playable(r: Pick<LibraryRow, 'file_state'>): boolean {
  return r.file_state === 'here';
}
/** An away row: dimmed like a leftover one (it can't play), and its `AwayTag` says why. */
export function rowAway(r: Pick<LibraryRow, 'file_state'>): Exclude<LibraryRow['file_state'], 'here' | 'no_file'> | null {
  return r.file_state === 'here' || r.file_state === 'no_file' ? null : r.file_state;
}
/** The row's lead (cover and title) is dimmed: a song that left every playlist, a file that is away, or a playlist
 *  song with no file yet (D6). The quality column tells the three apart: nothing, an `AwayTag`, Waiting / NOT FOUND. */
export function rowDim(r: Pick<LibraryRow, 'in_playlists' | 'own' | 'file_state'>): boolean {
  return rowOff(r) || r.file_state !== 'here';
}
/** A playlist song without a file, in the quality column (D6, I7): "Waiting" in muted words while the next sync will
 *  download it; the red NOT FOUND badge when the sync looked and found nothing usable (To-do's not-found group). */
export const WAITING_WORD = 'Waiting';
export const WAITING_TIP = 'Downloads at the next sync';
/** In a switched-off playlist nothing new downloads, so its songs without a file aren't waiting for anything: they say
 *  so, in the same muted words (I7's line for a switched-off playlist as the tooltip). */
export const OFF_WORD = 'Switched off';
export const OFF_TIP = 'Switched off: its files stay, nothing new downloads';
export function waitWords(off: boolean): { word: string; tip: string } {
  return off ? { word: OFF_WORD, tip: OFF_TIP } : { word: WAITING_WORD, tip: WAITING_TIP };
}
export const NOT_FOUND_WORD = 'NOT FOUND';
/** The row has no next-try date (only the track's details do), so its tooltip says what To-do offers instead. */
export const NOT_FOUND_TIP = 'Nothing usable found yet: To-do has other ways to get it';

// ---------- the header ----------
/** A playlist's songs that have no file yet (waiting or not found): the sidebar's song count (every song the view
 *  lists, D5) less the ones with a file (`summary.tracks`); without the sidebar, the rows themselves when they are
 *  the whole list (no search, no filter). Null when it can't be told. */
export function noFileCount(lib: Pick<Library, 'view' | 'key' | 'read_at' | 'summary' | 'rows'>,
  side: Pick<Sidebar, 'playlists'> | null | undefined, whole: boolean): number | null {
  if (lib.view !== 'playlist' || lib.read_at === null) return null;
  const fold = (x: string) => x.normalize('NFC').toLowerCase();
  const line = side?.playlists.find((p) => lib.key !== null && fold(p.name) === fold(lib.key));
  if (line && line.songs !== null) return Math.max(0, line.songs - lib.summary.tracks);
  return whole ? lib.rows.filter((r) => r.file_state === 'no_file').length : null;
}
/** The header's second line (I7, the engine's parts). A read playlist's count is its songs with a file, which is what
 *  the strip and the filter count, while the table also lists the songs still without one and the sidebar counts every
 *  song (issues #29 "For B6": 13 tracks beside 18 rows and "18 songs" read as a disagreement). So when some have no
 *  file the count names both in one part, "13 of 18 downloaded" (the inspector's "not downloaded yet" for such a
 *  song): one part, so the parts dropping at a narrow width never leave half of it. */
export function subtitleParts(lib: Pick<Library, 'subtitle' | 'summary'>, missing: number | null): string[] {
  if (!missing || !lib.subtitle.length) return lib.subtitle;
  const [, ...rest] = lib.subtitle;
  return [`${lib.summary.tracks} of ${lib.summary.tracks + missing} downloaded`, ...rest];
}

// ---------- the empty states (I7; issues #29 "For B6") ----------
export type PageEmpty = { kind: 'library' | 'gone' | 'never_read' | 'empty' | 'search' | 'filter'; title: string;
  body?: string };
/** What the list area says when the table has nothing to show, or (`line`) when a playlist's own part is empty but its
 *  folder holds files it doesn't (`also`): then the table stays, with this line above the `Also in this folder`
 *  section. The engine answers an empty folder and a read playlist with no songs as `no_match` even without search
 *  text, so the words come from the view, the folder's kind, the read and the search, not from `empty`. */
export function pageEmpty(lib: Pick<Library, 'view' | 'title' | 'empty' | 'read_at' | 'rows' | 'also'>, query: string,
  filter: LibraryFilter): { page: PageEmpty | null; line: string | null } {
  if (lib.empty === 'empty_library') return { page: { kind: 'library', title: EMPTY.empty_library.title }, line: null };
  if (lib.empty === 'gone') {
    return { page: { kind: 'gone', title: lib.view === 'playlist' ? "This playlist isn't in your list any more."
      : "This folder isn't in your library any more." }, line: null };
  }
  if (lib.rows.length) return { page: null, line: null };
  const q = query.trim();
  const playlist = lib.view === 'playlist';
  const neverRead = playlist && lib.read_at === null;
  const empty: PageEmpty = neverRead
    ? { kind: 'never_read', title: "This playlist hasn't been read yet.", body: 'Read your playlists above to see its songs.' }
    : q ? { kind: 'search', title: `Nothing in ${lib.title} matches “${q}”.` }
    : filter !== 'all' ? { kind: 'filter', title: 'No tracks with this quality here.' }
    : { kind: 'empty', title: playlist ? 'This playlist is empty.' : lib.view === 'unlisted' ? 'Every track is in a playlist.'
      : lib.view === 'all' ? EMPTY.empty_library.title : 'No music in this folder.' };
  if (!lib.also?.length) return { page: empty, line: null };
  // the folder's other files are there: the playlist's own part says it is empty, in one line of the table
  const line = neverRead ? "This playlist hasn't been read yet."
    : q ? `None of the playlist's songs match “${q}”.`
    : filter !== 'all' ? "None of the playlist's songs have this quality."
    : 'This playlist is empty.';
  return { page: null, line };
}
/** The `Also in this folder` head's hint (I7). Before the playlist was ever read nobody knows which of its folder's
 *  files it holds, so the hint doesn't claim they aren't in it. */
export function alsoHint(folder: string, neverRead = false): string {
  return neverRead ? `files in ${folder}, until the playlist is read` : `files in ${folder} that aren't in this playlist`;
}

// ---------- the inspector ----------
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

/** The panel head's place (D11): where the file sits, in the Folder and Subfolder columns' words ("in Hardtechno ›
 *  2019"); a song with no file yet says so, in the words the header counts it with. (Which playlists it is in is the
 *  Playlists row, by name.) */
export const NO_FILE_PLACE = 'not downloaded yet';
export function placeLine(place: string | null): string {
  return place ? `in ${place}` : '';
}
/** The details of a song without a file say what happens next (one NoteCard): a waiting one downloads at the next
 *  sync, Qobuz first (the order every download takes); a song not found was looked for, Qobuz looks again (`next`, its
 *  details' `next_qobuz_check` when the engine has them: "next_sync" or a date), and To-do has the other ways to get it
 *  (its foot: Open in to-do). In a switched-off playlist (`off`) a song still to come waits for nothing: it says how to
 *  get it. */
export function noFileNote(wait: LibraryRow['wait'], next: string | null = null, off = false): string {
  if (off && wait !== 'not_found') {
    return 'Its playlist is switched off, so nothing new downloads. Switch it on in Playlists to get this song.';
  }
  if (wait !== 'not_found') return 'It downloads at the next sync: from Qobuz when it has it, else from the best other source.';
  const day = next === 'next_sync' ? 'at the next sync' : next && dayMonth(next) ? `on ${dayMonth(next)}` : null;
  return `No source had a usable copy when the sync looked.${day ? ` Qobuz looks again ${day}.` : ''} To-do has links to`
    + ' buy it or get it another way.';
}
/** The details' Playlists row: every playlist holding the song, by name; "–" for a song in none; nothing while the
 *  playlists weren't read yet (`playlists` null). */
export function playlistsLine(t: Pick<TrackDetail, 'in_playlists' | 'playlists'>): string | null {
  if (!t.in_playlists) return '–';
  return t.playlists?.length ? t.playlists.join(', ') : null;
}

// ---------- the calls ----------
/** One `library(view, key, …)` call (the engine answers one view of the library per call). */
export type LibraryCall = { view: LibraryView; key: string | null };
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
/** What ▶ queues for a collection asked whole (no search, no filter): the page's own list as the table shows it (a
 *  playlist's songs, then the other files of its folder) and, of it, the rows whose file is there. The browser's Play
 *  uses it, so both start the same queue. */
export function playQueue(lib: Pick<Library, 'rows' | 'also'>): LibraryRow[] {
  return allRows(lib).filter(playable);
}
