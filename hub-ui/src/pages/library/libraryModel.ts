// Pure helpers for the Library page (sorting, windowing, selection, the filter segments, the columns, the row signals,
// the words of the header and the empty states, the inspector). Tested in libraryModel.test.ts.
import type { Decision } from '$lib/decisions/decisionModel';
import type { Library, LibraryFilter, LibraryRow, LibrarySort, LibraryView, Quality, Sidebar, TrackDetail,
  TrackRow } from '$lib/bridge/types';
import { resolveTarget, type LibraryTarget } from '$lib/router';
import type { SegOption } from '$lib/components/segmentedModel';
import { dayMonth, rowAway } from '$lib/format';
import { EMPTY } from '$lib/copy';
import { heldRow, putAt } from '$lib/decisions/hold';
import {
  keep as keepSelected, only, selectAll, single, type ScopeOf, type Selection,
} from '$lib/components/selectionModel';

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

/** The track the user just acted on in the details (a replace, Discard, Done, Undo, Keep): it stays on the table and
 *  selected, its result and Undo in the details, until the user picks another track or changes the view, the search or
 *  the filter, so a replace under "Upgrade ready" doesn't take the row (and with it the rekordbox steps) away, as To-do
 *  keeps the item it acted on. `keep`: a duplicate's Keep, the paths of the files that stay; when the track's own file
 *  went (or its row took another name, the engine's heir), the hold follows the track that has a kept file now. */
export type Hold = { id: string; keep: string[] | null; folder: string | null; q: string; filter: LibraryFilter };
export function holdApplies(h: Hold | null, folder: string | null, q: string, filter: LibraryFilter): h is Hold {
  return !!h && h.folder === folder && h.q === q && h.filter === filter;
}
/** The held track's row among `rows` (lib/decisions/hold). */
export { heldRow };
/** The answer with the held row put back where it stood before (`before`: the answer on screen, the held track's
 *  place in it), when the new answer no longer lists it: in the playlist's `also` part when it stood there, else among
 *  the rows (at their end when it stood nowhere). An answer that lists it already comes back as it is. */
export function withHeld<L extends Pick<Library, 'rows' | 'also'>>(lib: L, row: LibraryRow, before: Pick<Library, 'rows' | 'also'> | null,
  was: string): L {
  if (rowOf(lib, row.track_id)) return lib;
  const put = (list: LibraryRow[], at: number) => putAt(list, row, at);
  const inAlso = before?.also?.findIndex((r) => r.track_id === was) ?? -1;
  if (inAlso >= 0 && lib.also) return { ...lib, also: put(lib.also, Math.min(inAlso, lib.also.length)) };
  const at = before ? before.rows.findIndex((r) => r.track_id === was) : -1;
  return { ...lib, rows: put(lib.rows, at < 0 ? lib.rows.length : Math.min(at, lib.rows.length)) };
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
/** The same for a table row: a song without a file is on the to-do list only when it was not found (its group there)
 *  and the user didn't hide it there; one still waiting for the next sync isn't. */
export function rowInTodo(r: Pick<LibraryRow, 'status' | 'upgrade_ready' | 'in_playlists' | 'hidden' | 'file_state' | 'wait'>): boolean {
  return r.file_state === 'no_file' ? r.wait === 'not_found' && !r.hidden : inTodo(r);
}

export function todoHref(id: string): string {
  return `/todo?track=${encodeURIComponent(id)}`;
}

// ---------- the quality filter ----------
/** Remembered filter per collection (a playlist and a Library folder keep their step A key, the folder's name). */
export function filterKey(t: LibraryTarget): string {
  const k = t.kind === 'all' ? '__all__' : t.kind === 'unlisted' ? '__not_in_playlist__' : t.kind === 'playlist' ? t.name
    : t.path.startsWith('Library/') ? t.path.slice('Library/'.length) : t.path;
  return `library.filter.${k}`;
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
export function optionalColumns(kind: TableKind, subfolders = false, playlists = true): OptionalColumn[] {
  if (kind === 'all') return ['folder', 'playlist', 'length'];
  if (kind === 'unlisted') return ['folder', 'length'];
  if (kind === 'playlist' || kind === 'library') return ['length'];
  return [...(subfolders ? ['subfolder' as const] : []), ...(playlists ? ['playlist' as const] : []), 'length'];
}
/** Whether a folder view's Playlist column can say anything (`columnsAt`'s `playlists`; D10 amended): false only when
 *  no row of the collection's unfiltered answer is in a playlist (an album drive no playlist uses), where the column
 *  would print "–" on every row and only take room from the cut titles; Length then shows from where Playlist did.
 *  The page asks it of an answer without search or filter and holds that value while one is on, so the columns don't
 *  jump as the user types. Only the watched and crate kinds have the column. */
export function playlistColumnFor(lib: Pick<Library, 'rows' | 'also'>): boolean {
  return allRows(lib).some((r) => r.playlists.length > 0);
}
/** Whether the table's Artist column can say anything: false only when no row of the view has an artist (a crate of
 *  the user's own untagged files, whose titles come from the file names), where the column would be empty on every
 *  row and only take room from the cut titles. Nothing stands in for it: a name is shown as the file gives it. Asked of
 *  an answer without search or filter, held while one is on (like `playlistColumnFor`); an empty view keeps the column. */
export function artistColumnFor(lib: Pick<Library, 'rows' | 'also'>): boolean {
  const rows = allRows(lib);
  return rows.length === 0 || rows.some((r) => r.artist.trim() !== '');
}
/** The sort the table shows: with no Artist column, a sort by Artist reads as the same direction on Track (the
 *  engine's Artist sort breaks ties by title, and with no artist anywhere that is a sort by title). */
export function shownSort(sort: LibrarySort, artist: boolean): LibrarySort {
  if (artist) return sort;
  const { column, desc } = sortState(sort);
  return column === 'artist' ? (desc ? '-title' : 'title') : sort;
}
/** The width (px) the table needs for Track and Artist beside Quality and the upgrade slot, and what each optional
 *  column adds to it (D10, the mockup's numbers): a column shows from the sum of its own and those before it. A
 *  playlist's `#` column comes on top of the base. */
export const BASE_WIDTH = 380;
export const ORDER_WIDTH = 40;
export const COLUMN_WIDTH: Record<OptionalColumn, number> = { folder: 140, subfolder: 140, playlist: 180, length: 200 };
/** The table's own width from which each of the kind's optional columns shows (All tracks: Folder 520, Playlist 700,
 *  Length 900). */
export function columnThresholds(kind: TableKind, subfolders = false, playlists = true): { column: OptionalColumn; from: number }[] {
  let need = BASE_WIDTH + (kind === 'playlist' ? ORDER_WIDTH : 0);
  return optionalColumns(kind, subfolders, playlists).map((column) => ({ column, from: (need += COLUMN_WIDTH[column]) }));
}
/** The optional columns a table this wide shows; `playlists` false leaves the Playlist column out (playlistColumnFor). */
export function columnsAt(kind: TableKind, width: number, subfolders = false, playlists = true): OptionalColumn[] {
  return columnThresholds(kind, subfolders, playlists).filter((t) => width >= t.from).map((t) => t.column);
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
export function gridColumns(cols: OptionalColumn[], order = false, artist = true): string {
  return [...(order ? [TRACK.order] : []), TRACK.title, ...(artist ? [TRACK.artist] : []), ...cols.map((c) => TRACK[c]), TRACK.end].join(' ');
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
/** A watched folder with more crates than the sidebar holds (its header's link to Settings' list of them): the sidebar's
 *  line for it when `too_many`, else null. The folder's key and the sidebar's path match as paths (NFC, no trailing
 *  slash), as `hasSubfolders` matches them. */
export function tooManyFor(lib: Pick<Library, 'view' | 'folder_kind' | 'key'> | null,
  side: Pick<Sidebar, 'watched'> | null | undefined): Sidebar['watched'][number] | null {
  if (!lib || lib.view !== 'folder' || lib.folder_kind !== 'watched' || lib.key === null) return null;
  const key = samePath(lib.key);
  const w = side?.watched.find((x) => samePath(x.path) === key);
  return w?.too_many ? w : null;
}

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
/** An away row: dimmed like a leftover one (it can't play), and its `AwayTag` says why (shared with To-do's rows). */
export { rowAway };
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
/** To-do's next-try line for a `next_try` (views.next_due) on `today` (a local ISO day): null when nothing is
 *  looked for again. */
export function nextTryLine(nextTry: string | null, today: string): string | null {
  if (nextTry === null) return null;
  if (nextTry === 'next_sync' || nextTry <= today) return 'tried again at the next sync';
  const days = Math.round((Date.parse(`${nextTry}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000);
  return `next try in ${days} day${days === 1 ? '' : 's'}`;
}
/** NOT FOUND's tooltip (I7): what happened, when the sync looks again, and where to go meanwhile (To-do, unless the
 *  user hid the song there). */
export function notFoundTip(r: Pick<LibraryRow, 'next_try' | 'hidden'>, today: string): string {
  const line = nextTryLine(r.next_try, today);
  return `Nothing usable found yet${line ? `, ${line}` : ''}. ${r.hidden ? 'You hid it from To-do.' : 'To-do has other ways to get it.'}`;
}
/** A day as the engine spells it (YYYY-MM-DD), in local time. */
export function localDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// ---------- the header ----------
/** The header's second line (I7, the engine's parts). A read playlist's count is its songs with a file, which is what
 *  the strip and the filter count, while the table also lists the songs still without one and the sidebar counts every
 *  song (13 tracks beside 18 rows and "18 songs" would read as a disagreement). So when some have no
 *  file the count names both in one part, "13 of 18 downloaded" (the inspector's "not downloaded yet" for such a
 *  song): one part, so the parts dropping at a narrow width never leave half of it. Both numbers come from the one
 *  answer (`songs`, before any search or filter).
 *  `strip`: the SummaryStrip is shown. A read playlist's count then leaves the header (sources round D10, notes
 *  problem 8): the strip says it at every size ("13 of 18 downloaded", with the bar's dashed end), and a header part
 *  drops first when the panel is open, so the count was the part that went. The header keeps `{Service} playlist`
 *  and its breadcrumb. Without the strip (no file yet) the header keeps the count, so it is never gone. */
export function subtitleParts(lib: Pick<Library, 'subtitle' | 'songs' | 'view' | 'read_at'>, strip = false): string[] {
  const s = lib.songs;
  // a read playlist's count is its second part, after the service (the engine's order); every other view's is its first
  const at = lib.view === 'playlist' ? 1 : 0;
  if (strip && s && lib.view === 'playlist' && lib.read_at !== null && lib.subtitle.length > at) {
    return lib.subtitle.filter((_, i) => i !== at);
  }
  if (!s || s.listed <= s.with_file || (lib.view === 'playlist' && lib.read_at === null) || lib.subtitle.length <= at) {
    return lib.subtitle;
  }
  return lib.subtitle.map((p, i) => (i === at ? `${s.with_file} of ${s.listed} downloaded` : p));
}

// ---------- the empty states (I7) ----------
/** A playlist with no read record (`read_at` null) while the header's read status (every playlist's) may say "read 2 min
 *  ago": it was added since the last read, or that read couldn't open it. Both stay true side by side. */
export const NOT_IN_LAST_READ = "This playlist wasn't in the last read.";
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
    ? { kind: 'never_read', title: NOT_IN_LAST_READ, body: "It was added since, or it couldn't be opened. Read your playlists above to see its songs." }
    : q ? { kind: 'search', title: `Nothing in ${lib.title} matches “${q}”.` }
    : filter !== 'all' ? { kind: 'filter', title: 'No tracks with this quality here.' }
    : { kind: 'empty', title: playlist ? 'This playlist is empty.' : lib.view === 'unlisted' ? 'Every track is in a playlist.'
      : lib.view === 'all' ? EMPTY.empty_library.title : 'No music in this folder.' };
  if (!lib.also?.length) return { page: empty, line: null };
  // the folder's other files are there: the playlist's own part says it is empty, in one line of the table
  const line = neverRead ? NOT_IN_LAST_READ
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
/** What the panel's foot holds: the decision the track waits for (the upgrade, the rekordbox check a replace left, a
 *  duplicate group: decisionFor), decided right here with To-do's own foot; else the AIFF card's button (Convert to
 *  AIFF, Give it its clean name: `aiff`, its look and whether the CDJs refuse the file) and Open in to-do for any other
 *  to-do (a weak file is bought and dropped there); nothing for a lossless track (or one the to-do list doesn't show).
 *  A file the CDJs refuse is To-do's CDJ item, so the AIFF button stands in for Open in to-do; any other file keeps
 *  both, the filled one first (`aiff_todo`: Convert above Open in to-do; `todo_aiff`: the outlined Convert under it). */
export type FootKind = NonNullable<Decision>['kind'] | 'todo' | 'aiff' | 'aiff_todo' | 'todo_aiff';
export function footAction(t: Pick<TrackDetail, 'status' | 'upgrade_ready' | 'in_playlists' | 'hidden'>,
  decision: Decision, aiff: { variant: 'filled' | 'outline'; cdj: boolean } | null = null): FootKind | null {
  if (decision) return decision.kind;
  const todo = inTodo(t);
  if (!aiff) return todo ? 'todo' : null;
  if (!todo || aiff.cdj) return 'aiff';
  return aiff.variant === 'filled' ? 'aiff_todo' : 'todo_aiff';
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
 *  get it. A song not found that the user hid from To-do (`hidden`) is not sent there: To-do doesn't show it. */
export function noFileNote(wait: LibraryRow['wait'], next: string | null = null, off = false, hidden = false): string {
  if (off && wait !== 'not_found') {
    return 'Its playlist is switched off, so nothing new downloads. Switch it on in Playlists to get this song.';
  }
  if (wait !== 'not_found') return 'It downloads at the next sync: from Qobuz when it has it, else from the best other source.';
  const day = next === 'next_sync' ? 'at the next sync' : next && dayMonth(next) ? `on ${dayMonth(next)}` : null;
  return `No source had a usable copy when the sync looked.${day ? ` Qobuz looks again ${day}.` : ''}`
    + (hidden ? ' You hid it from To-do.' : ' To-do has links to buy it or get it another way.');
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
/** The calls that answer the page's target (`router.libraryTarget`). A playlist name the sidebar doesn't list but names
 *  a Library folder of (an old link) is that folder (`resolveTarget`); a name nothing lists is asked as a playlist,
 *  which the engine answers with `empty: 'gone'`. Without the sidebar yet (the window just opened) an old link's name
 *  is tried both ways, in that order: the second only when the first came back gone. */
export function libraryCalls(target: LibraryTarget, side: Pick<Sidebar, 'playlists' | 'library_folders'> | null): LibraryCall[] {
  const t = resolveTarget(target, side);
  if (t.kind === 'all') return [{ view: 'all', key: null }];
  if (t.kind === 'unlisted') return [{ view: 'unlisted', key: null }];
  if (t.kind === 'folder') return [{ view: 'folder', key: t.path }];
  const asPlaylist: LibraryCall = { view: 'playlist', key: t.name };
  return side ? [asPlaylist] : [asPlaylist, { view: 'folder', key: `Library/${t.name}` }];
}
/** The header's title before the engine's answer names the collection. */
export function targetTitle(t: LibraryTarget): string {
  if (t.kind === 'all') return 'All tracks';
  if (t.kind === 'unlisted') return 'Not in a playlist';
  return t.kind === 'playlist' ? t.name : t.path.split('/').filter(Boolean).pop() ?? t.path;
}
/** What ▶ queues for a collection asked whole (no search, no filter): the page's own list as the table shows it (a
 *  playlist's songs, then the other files of its folder) and, of it, the rows whose file is there. The browser's Play
 *  uses it, so both start the same queue. */
export function playQueue(lib: Pick<Library, 'rows' | 'also'>): LibraryRow[] {
  return allRows(lib).filter(playable);
}

// ---------- the row's context menu ----------
/** The row menu's items in their order, worked out from the row alone when the menu opens (`link`: the row's own
 *  `track_link`, so "Open in {Service}" is in the menu from its first frame and nothing joins it later). `todo`: the
 *  row is on the to-do list; `finder`: its file can be shown in Finder. */
export type MenuKind = 'details' | 'finder' | 'open' | 'todo';
export function rowMenu(m: { todo: boolean; finder: boolean; link: LibraryRow['track_link'] }):
  { kind: MenuKind; label: string; test?: string }[] {
  return [{ kind: 'details', label: 'Show details', test: 'menu-details' },
    ...(m.finder ? [{ kind: 'finder' as const, label: 'Show in Finder' }] : []),
    ...(m.link ? [{ kind: 'open' as const, label: m.link.label, test: 'menu-open-in' }] : []),
    ...(m.todo ? [{ kind: 'todo' as const, label: 'Open in to-do', test: 'menu-todo' }] : [])];
}

// ---------- multi-select and the AIFF batch (issue 33 stage D, plan §6.0.1, §6.2) ----------
/** The one scope several rows can be selected in: rows with a file (an `also` row too). A song without a file is null:
 *  a click selects it alone, and ⌘-click, ⇧-click and ⌘A leave it out. Away rows have a file and take part (the
 *  plan leaves them out with their reason). */
export const FILES_SCOPE = 'files';
export function tableScope(rows: Pick<LibraryRow, 'track_id' | 'file_state'>[]): ScopeOf {
  const scopes = new Map(rows.map((r): [string, string | null] => [r.track_id, r.file_state === 'no_file' ? null : FILES_SCOPE]));
  return (key) => scopes.get(key) ?? null;
}
/** ⌘A: every row of the scope on screen (the table's rows after filter and search, in its order). With nothing selected
 *  it starts from the first row that can take part; with only a song without a file selected it does nothing. */
export function selectAllRows(sel: Selection, order: string[], scopeOf: ScopeOf): Selection {
  if (sel.anchor === null) {
    const first = order.find((k) => scopeOf(k) !== null);
    return first === undefined ? sel : selectAll(single(first), order, scopeOf);
  }
  return selectAll(sel, order, scopeOf);
}
/** The selection after a new answer of the table: keys that left drop out, the anchor goes to the nearest one left,
 *  none left: nothing. A single selection is never touched (its track may be off the table on purpose: `offTable`,
 *  Hold); the selection stays on the same tracks when a done file changed its row's format and name. */
export function keepTableSelection(sel: Selection, before: string[], after: string[]): Selection {
  if (sel.keys.length < 2) return sel;
  const next = keepSelected(sel, before, after, () => null);
  const same = next.keys.length === sel.keys.length && next.anchor === sel.anchor;
  return same ? sel : next;
}

/** What the inspector shows: one track's details, a batch panel for two or more rows, the view's plan (the header's
 *  Make AIFF…), or nothing. The view's plan comes before the selection (opening it clears the selection, a pick
 *  closes it). */
export type InspectorSubject = { kind: 'track'; id: string } | { kind: 'tracks'; ids: string[] } | { kind: 'view' } | null;
export function inspectorSubject(sel: Selection, viewOpen: boolean): InspectorSubject {
  if (viewOpen) return { kind: 'view' };
  if (sel.keys.length > 1) return { kind: 'tracks', ids: sel.keys };
  const id = only(sel);
  return id === null ? null : { kind: 'track', id };
}
/** Whether the subject is a batch panel (the chrome's `batchSubject`). */
export const isBatchSubject = (s: InspectorSubject): boolean => s?.kind === 'tracks' || s?.kind === 'view';

export const MAKE_AIFF = 'Make AIFF…';
export const MAKE_AIFF_TIP = 'Make all lossless files AIFF';
/** The header's AIFF button: "Make AIFF…" opens the view's plan; "Resume · {k} left" while a library batch is stopped.
 *  While the flow runs it keeps the label it had when it started (`frozen`) and opens the panel. */
export type AiffHeader = { kind: 'make' | 'resume'; label: string; tip: string | null; batch_id: number | null };
export function aiffHeader(stopped: { batch_id: number; left: number } | null, running: boolean,
  frozen: string | null = null): AiffHeader {
  const resume = !!stopped && !running;
  const base: AiffHeader = resume
    ? { kind: 'resume', label: `Resume · ${stopped.left} left`, tip: 'Carry on with the files this batch left', batch_id: stopped.batch_id }
    : { kind: 'make', label: MAKE_AIFF, tip: MAKE_AIFF_TIP, batch_id: null };
  return running && frozen ? { ...base, label: frozen } : base;
}
