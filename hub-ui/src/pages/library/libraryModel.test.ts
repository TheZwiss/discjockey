import { describe, expect, it } from 'vitest';
import type { TrackRow } from '$lib/bridge/types';
import { NOT_IN_PLAYLIST } from '$lib/bridge/types';
import {
  centerLine, columnThresholds, columnsAt, defaultSort, fileName, folderCell, footAction, gridColumns, hasSubfolders, inTodo,
  isSort, keepLine, lineTop, moveSelection, noFileCount, noFileNote, pageEmpty, placeLine, playQueue, playable,
  playlistCell, playlistsLine, libraryCalls, nextSort, offTable, optionalColumns, rowAway, rowDim, rowInTodo, rowOf, rowOff,
  rowTitleTip, segOptions, selectedIndex, shortUrl, sortKey, sortState, subfolderCell, subtitleParts, tableKind, tableLines,
  titleNote, viewSort, waitWords, windowSlice, alsoHint,
} from './libraryModel';
import type { LibraryRow, TrackDetail } from '$lib/bridge/types';

const row = (id: string, extra: Partial<TrackRow> = {}): TrackRow => ({
  track_id: id, artist: 'A', title: id, folder: 'Hard_Bounce', duration_s: 200, status: 'lossless', quality: 'lossless',
  quality_label: 'LOSSLESS', cutoff_hz: null, source: 'qobuz', source_name: 'Qobuz', in_playlists: true, own: false, hidden: false,
  upgrade_ready: false, path: `Library/Hard_Bounce/A - ${id}.aiff`, added: null, cover_url: null, ...extra,
} as TrackRow);

describe('header click → next sort', () => {
  it('flips the same column: artist → -artist → artist', () => {
    expect(nextSort('artist', 'artist')).toBe('-artist');
    expect(nextSort('-artist', 'artist')).toBe('artist');
  });
  it('another column starts ascending', () => {
    expect(nextSort('artist', 'quality')).toBe('quality');
    expect(nextSort('-artist', 'length')).toBe('length');
    expect(nextSort('-quality', 'title')).toBe('title');
  });
  it('reads the arrow state', () => {
    expect(sortState('-quality')).toEqual({ column: 'quality', desc: true });
    expect(sortState('artist')).toEqual({ column: 'artist', desc: false });
  });
});

describe('windowing slice', () => {
  it('renders every row up to 300', () => {
    expect(windowSlice(5000, 400, 36, 300)).toEqual({ start: 0, end: 300 });
  });
  it('top of a long list: visible rows plus 10 below', () => {
    expect(windowSlice(0, 360, 36, 1500)).toEqual({ start: 0, end: 20 });
  });
  it('middle of a long list: 10 overscan on each side', () => {
    // rows 750..760 visible
    expect(windowSlice(750 * 36, 360, 36, 1500)).toEqual({ start: 740, end: 770 });
  });
  it('end of a long list stops at the count', () => {
    expect(windowSlice(1500 * 36, 360, 36, 1500)).toEqual({ start: 1490, end: 1500 });
  });
  it('keeps the selected line in view, clear of a stuck section head', () => {
    expect(keepLine(0, 360, 3 * 36, 36)).toBe(0);
    expect(keepLine(0, 360, 12 * 36, 36)).toBe(13 * 36 - 360);
    expect(keepLine(500, 360, 2 * 36, 36)).toBe(72);
    // a row of the Also section under a 32 px stuck head stops below it, not half under it
    expect(keepLine(500, 360, 510, 36, 32)).toBe(478);
    expect(keepLine(500, 360, 540, 36, 32)).toBe(500);
    expect(centerLine(360, 20 * 36, 36)).toBe(20 * 36 - 162);
    expect(centerLine(360, 36, 36)).toBe(0);
  });
});

describe('selection after a re-fetch', () => {
  it('follows the track id to its new position', () => {
    const before = [row('t1'), row('t2'), row('t3')];
    const after = [row('t3'), row('t1'), row('t2')];
    expect(selectedIndex(before, 't2')).toBe(1);
    expect(selectedIndex(after, 't2')).toBe(2);
  });
  it('is -1 when the track is gone, and null stays null', () => {
    expect(selectedIndex([row('t1')], 't9')).toBe(-1);
    expect(selectedIndex([row('t1')], null)).toBe(-1);
  });
  it('↑/↓ moves and stops at the ends', () => {
    const rows = [row('t1'), row('t2')];
    expect(moveSelection(rows, null, 1)).toBe('t1');
    expect(moveSelection(rows, 't1', 1)).toBe('t2');
    expect(moveSelection(rows, 't2', 1)).toBe('t2');
    expect(moveSelection(rows, 't1', -1)).toBe('t1');
    expect(moveSelection([], 't1', 1)).toBeNull();
  });
});

describe('"Open in to-do" availability', () => {
  it('only for tracks the to-do list shows', () => {
    expect(inTodo(row('a'))).toBe(false);
    expect(inTodo(row('b', { status: 'not_lossless' }))).toBe(true);
    expect(inTodo(row('c', { status: 'fake_lossless' }))).toBe(true);
    expect(inTodo(row('d', { status: 'lossless', upgrade_ready: true }))).toBe(true);
  });
  it('not for a track in no playlist or a hidden one: To-do leaves them out', () => {
    expect(inTodo(row('e', { status: 'not_lossless', in_playlists: false }))).toBe(false);
    expect(inTodo(row('f', { status: 'not_lossless', hidden: true }))).toBe(false);
  });
});

describe('the panel', () => {
  const up = (swap_safe: boolean, swap_possible = true) => ({ swap_safe, swap_possible }) as TrackDetail['upgrade'];
  const t = (extra: Partial<TrackDetail>) => ({ ...row('x'), upgrade: null, ...extra }) as TrackDetail;
  it('foot: Swap when the upgrade matches, Open in to-do for other to-dos, nothing for lossless', () => {
    expect(footAction(t({ status: 'not_lossless', upgrade_ready: true, upgrade: up(true) }))).toBe('swap');
    expect(footAction(t({ status: 'not_lossless', upgrade_ready: true, upgrade: up(false) }))).toBe('todo');
    expect(footAction(t({ status: 'not_lossless', upgrade_ready: true, upgrade: up(true, false) }))).toBe('todo');
    expect(footAction(t({ status: 'not_lossless' }))).toBe('todo');
    expect(footAction(t({}))).toBeNull();
    expect(footAction(t({ status: 'not_lossless', in_playlists: false }))).toBeNull();
  });
  it('file name without the folders', () => {
    expect(fileName('Library/Hard_Bounce/not_lossless/Armin Hermann - Get Naughty.aiff')).toBe('Armin Hermann - Get Naughty.aiff');
    expect(fileName('x.aiff')).toBe('x.aiff');
    expect(fileName(null)).toBe('');
  });
});

describe('table and strip', () => {
  it('filter strip: Fake only when there are fake files or it is chosen; dots and counts', () => {
    const c = { all: 3, lossless: 1, good_lossy: 1, weak: 1, fake: 0, upgrade_ready: 1 };
    expect(segOptions(c, 'all').map((o) => o.label)).toEqual(['All', 'Lossless', 'Good lossy', 'Weak', 'Upgrade ready']);
    expect(segOptions({ ...c, fake: 2 }, 'all').map((o) => o.key)).toContain('fake');
    expect(segOptions(c, 'fake').map((o) => o.key)).toContain('fake');
    expect(segOptions(c, 'all')[1]).toEqual({ key: 'lossless', label: 'Lossless', count: 1, dot: 'lossless' });
    expect(segOptions(null, 'all')[0].count).toBe(0);
  });
  it('optional columns (D10): per kind, a column that would say the same on every row left out', () => {
    expect(optionalColumns('all')).toEqual(['folder', 'playlist', 'length']);
    expect(optionalColumns('unlisted')).toEqual(['folder', 'length']);
    expect(optionalColumns('playlist')).toEqual(['length']);
    expect(optionalColumns('library')).toEqual(['length']);
    expect(optionalColumns('watched', true)).toEqual(['subfolder', 'playlist', 'length']);
    expect(optionalColumns('watched', false)).toEqual(['playlist', 'length']);
    expect(optionalColumns('crate', true)).toEqual(['subfolder', 'playlist', 'length']);
    expect(optionalColumns('crate')).toEqual(['playlist', 'length']);
  });
  it('thresholds add up from Track + Artist (380): Folder or Subfolder +140, Playlist +180, Length +200; a playlist\'s # +40', () => {
    expect(columnThresholds('all')).toEqual([{ column: 'folder', from: 520 }, { column: 'playlist', from: 700 },
      { column: 'length', from: 900 }]);
    expect(columnThresholds('watched', true)).toEqual([{ column: 'subfolder', from: 520 }, { column: 'playlist', from: 700 },
      { column: 'length', from: 900 }]);
    expect(columnThresholds('playlist')).toEqual([{ column: 'length', from: 620 }]);
    expect(columnThresholds('library')).toEqual([{ column: 'length', from: 580 }]);
  });
  it("columns by the table's own width: Length goes first, then Playlist, Subfolder or Folder last (the widths table)", () => {
    // 1280 · Library (rail + browser), details closed: 946
    expect(columnsAt('watched', 946, true)).toEqual(['subfolder', 'playlist', 'length']);
    expect(columnsAt('all', 946)).toEqual(['folder', 'playlist', 'length']);
    // 1280 · the browser dragged to 320: 866 (Length goes first)
    expect(columnsAt('watched', 866, true)).toEqual(['subfolder', 'playlist']);
    // 1100 · Library, details closed: 766 (today's 1280 set)
    expect(columnsAt('watched', 766, true)).toEqual(['subfolder', 'playlist']);
    // 1100 · details open (the browser stepped back): 685; 1280 · details open: 586 (today's 1100 set)
    expect(columnsAt('watched', 685, true)).toEqual(['subfolder']);
    expect(columnsAt('watched', 586, true)).toEqual(['subfolder']);
    expect(columnsAt('crate', 586)).toEqual(['playlist']);   // no crates inside: Playlist from 560
    expect(columnsAt('crate', 559)).toEqual([]);
    expect(columnsAt('unlisted', 586)).toEqual(['folder']);
    expect(columnsAt('playlist', 619)).toEqual([]);
    expect(columnsAt('playlist', 620)).toEqual(['length']);
    expect(columnsAt('library', 580)).toEqual(['length']);
    expect(columnsAt('all', 519)).toEqual([]);
    expect(columnsAt('all', 699)).toEqual(['folder']);
    expect(columnsAt('unlisted', 720)).toEqual(['folder', 'length']);
  });
  it('grid: the names share the rest, fixed #, Length, Quality and slot', () => {
    expect(gridColumns([])).toBe('minmax(0, 1.45fr) minmax(0, 1fr) 116px var(--w-row-action)');
    expect(gridColumns(['folder', 'playlist', 'length']))
      .toBe('minmax(0, 1.45fr) minmax(0, 1fr) minmax(96px, .8fr) minmax(0, 1.1fr) 52px 116px var(--w-row-action)');
    expect(gridColumns(['length'], true)).toBe('24px minmax(0, 1.45fr) minmax(0, 1fr) 52px 116px var(--w-row-action)');
  });
  it('tells the kinds apart: the views, and a folder view by what the folder is', () => {
    expect(tableKind({ view: 'all', folder_kind: null })).toBe('all');
    expect(tableKind({ view: 'unlisted', folder_kind: null })).toBe('unlisted');
    expect(tableKind({ view: 'playlist', folder_kind: null })).toBe('playlist');
    expect(tableKind({ view: 'folder', folder_kind: 'watched' })).toBe('watched');
    expect(tableKind({ view: 'folder', folder_kind: 'crate' })).toBe('crate');
    expect(tableKind({ view: 'folder', folder_kind: 'library' })).toBe('library');
    expect(tableKind({ view: 'folder', folder_kind: null })).toBe('library');
  });
});

describe('sorts: a default and a saved sort per view kind', () => {
  it('a playlist opens in its own order, every other view by Artist', () => {
    expect(defaultSort('playlist')).toBe('order');
    expect(defaultSort('all')).toBe('artist');
    expect(defaultSort('folder')).toBe('artist');
  });
  it('each kind has its own key', () => {
    expect(sortKey('playlist')).toBe('library.sort.playlist');
    expect(sortKey('folder')).not.toBe(sortKey('all'));
  });
  it('a sort a view has no column for is not one of its sorts', () => {
    expect(isSort('-order', 'playlist')).toBe(true);
    expect(isSort('order', 'all')).toBe(false);
    expect(isSort('folder', 'playlist')).toBe(false);
    expect(isSort('-folder', 'all')).toBe(true);
    expect(isSort('folder', 'folder')).toBe(false);
    expect(isSort('length', 'folder')).toBe(true);
    // Source and Added left the table: a sort by them saved before falls back to the default
    expect(isSort('added', 'all')).toBe(false);
    expect(isSort('-source', 'all')).toBe(false);
    expect(isSort('bpm', 'all')).toBe(false);
    expect(isSort(3, 'all')).toBe(false);
  });
  it('opens with its own saved sort, else the shared one from before when it fits, else its default', () => {
    expect(viewSort('playlist', '-length', 'artist')).toBe('-length');
    expect(viewSort('playlist', null, '-title')).toBe('-title');
    expect(viewSort('folder', null, 'folder')).toBe('artist');
    expect(viewSort('playlist', 'folder', null)).toBe('order');
    expect(viewSort('all', null, null)).toBe('artist');
  });
});

describe('the cells', () => {
  const lr = (over: Partial<LibraryRow> = {}): LibraryRow => ({ ...here(row('a')), ...over });
  it('Folder says where the file sits (D12), "–" without a place', () => {
    expect(folderCell(lr({ place: 'Rekordbox Library › Hardtechno › 2019' }))).toBe('Rekordbox Library › Hardtechno › 2019');
    expect(folderCell(lr({ place: null }))).toBeNull();
  });
  it('Subfolder: the crate or the folders below; "–" for a file in the folder itself', () => {
    expect(subfolderCell(lr({ subfolder: '2019' }))).toBe('2019');
    expect(subfolderCell(lr({ subfolder: '' }))).toBeNull();
    expect(subfolderCell(lr({ subfolder: null }))).toBeNull();
  });
  it('Playlist: the first playlist, +n for the others, all of them by name as the tooltip', () => {
    expect(playlistCell(lr({ playlists: ['Hard_Bounce', 'Powertrance', 'Bouncy'] })))
      .toEqual({ name: 'Hard_Bounce', more: 2, tip: 'In Hard_Bounce, Powertrance, Bouncy' });
    expect(playlistCell(lr({ playlists: ['Hard_Bounce'] }))).toEqual({ name: 'Hard_Bounce', more: 0, tip: 'In Hard_Bounce' });
    expect(playlistCell(lr({ playlists: [] }))).toBeNull();
  });
  it('a playlist row whose file sits elsewhere says where after its title; nowhere else', () => {
    expect(titleNote(lr({ place: 'Techno 2019' }), 'playlist')).toBe('in Techno 2019');
    expect(titleNote(lr({ place: null }), 'playlist')).toBeNull();
    expect(titleNote(lr({ place: 'Techno 2019' }), 'all')).toBeNull();
    expect(titleNote(lr({ place: 'Techno 2019', file_state: 'no_file' }), 'playlist')).toBeNull();
  });
});

const here = (r: TrackRow, file_state: LibraryRow['file_state'] = 'here'): LibraryRow => ({ ...r, sound_checked: true, file_state,
  wait: null, position: null, place: null, subfolder: null, playlists: [] });

describe('a dimmed row', () => {
  it('is a downloaded song that left every playlist', () => {
    expect(rowOff(row('a'))).toBe(false);
    expect(rowOff(row('a', { in_playlists: false }))).toBe(true);
  });
  it('is never one of the users own files, which no playlist holds', () => {
    expect(rowOff(row('a', { in_playlists: false, own: true, source_name: 'own file' }))).toBe(false);
    expect(rowOff(row('a', { in_playlists: true, own: true }))).toBe(false);
  });
  it('says why in its title tooltip, under the name, at every width', () => {
    expect(rowTitleTip(here(row('a', { in_playlists: false })), 'Artist - Title')).toBe('Artist - Title\nNot in any playlist any more');
  });
  it('has the name alone in the tooltip when it is in a playlist or the users own file', () => {
    expect(rowTitleTip(here(row('a')), 'Artist - Title')).toBe('Artist - Title');
    expect(rowTitleTip(here(row('a', { in_playlists: false, own: true, source_name: 'own file' })), 'Artist - Title')).toBe('Artist - Title');
  });
  it('leaves an away row to its own tag: the name alone', () => {
    expect(rowTitleTip(here(row('a', { in_playlists: false }), 'offline'), 'Artist - Title')).toBe('Artist - Title');
    expect(rowTitleTip(here(row('a', { in_playlists: false }), 'folder_missing'), 'Artist - Title')).toBe('Artist - Title');
  });
});

describe('copy helpers', () => {
  it('short source link, the place line (D11) and the Playlists row', () => {
    expect(shortUrl('https://www.youtube.com/watch?v=abcdefghijk')).toBe('youtube.com/watch?v=…');
    expect(shortUrl('https://soundcloud.com/a')).toBe('soundcloud.com/a');
    expect(placeLine('Hardtechno › 2019')).toBe('in Hardtechno › 2019');
    expect(placeLine(null)).toBe('');
    expect(playlistsLine({ in_playlists: true, playlists: ['Hard_Bounce', 'Bouncy'] })).toBe('Hard_Bounce, Bouncy');
    expect(playlistsLine({ in_playlists: false, playlists: [] })).toBe('–');
    expect(playlistsLine({ in_playlists: true, playlists: null })).toBeNull();
  });
});

describe('an away row (library stage 4 fix K)', () => {
  it('plays only when its file is there, and names why it is not', () => {
    expect(playable({ file_state: 'here' })).toBe(true);
    expect(playable({ file_state: 'offline' })).toBe(false);
    expect(playable({ file_state: 'folder_missing' })).toBe(false);
    expect(rowAway({ file_state: 'here' })).toBeNull();
    expect(rowAway({ file_state: 'offline' })).toBe('offline');
    expect(rowAway({ file_state: 'folder_missing' })).toBe('folder_missing');
  });
});

describe('offTable: the selected track known to be off the table (the details then never stand empty)', () => {
  // the answer's own `folder`/`key` is the engine's spelling; offTable goes by the route param the answer was asked for
  const lib = (ids: string[], also: string[] | null = null) => ({ folder: 'Library/Old_Sets', key: 'Library/Old_Sets',
    rows: ids.map((id) => row(id)) as unknown as LibraryRow[], also: also && (also.map((id) => row(id)) as unknown as LibraryRow[]) });
  it('a track among the rows shown is on the table', () => {
    expect(offTable(lib(['t1', 't2']), 'Hard_Bounce', 'Hard_Bounce', 't2')).toBe(false);
  });
  it('filtered or searched away, or gone from the library: off', () => {
    expect(offTable(lib(['t1']), 'Hard_Bounce', 'Hard_Bounce', 't2')).toBe(true);
  });
  it('the engine echoing another spelling of the folder (Library/Old_Sets for the route Old_Sets) changes nothing', () => {
    expect(offTable(lib(['t1']), 'Old_Sets', 'Old_Sets', 't2')).toBe(true);
    expect(offTable(lib(['t1', 't2']), 'Old_Sets', 'Old_Sets', 't2')).toBe(false);
  });
  it('no rows at all (an empty library or folder, nothing matches): off', () => {
    expect(offTable(lib([]), 'Hard_Bounce', 'Hard_Bounce', 't2')).toBe(true);
    expect(offTable(lib([]), NOT_IN_PLAYLIST, NOT_IN_PLAYLIST, 'local:1')).toBe(true);
    expect(offTable(lib([]), null, null, 't2')).toBe(true);
  });
  it('not known yet: before the first answer, or while the answer is still another folder\'s', () => {
    expect(offTable(null, null, 'Hard_Bounce', 't2')).toBe(false);
    expect(offTable(lib(['t9']), 'Qobuz_Picks', 'Hard_Bounce', 't2')).toBe(false);
  });
  it('a playlist\'s other files of its folder (`also`) are on the table too', () => {
    expect(offTable(lib(['t1'], ['left']), 'Hard_Bounce', 'Hard_Bounce', 'left')).toBe(false);
    expect(rowOf(lib(['t1'], ['left']), 'left')?.track_id).toBe('left');
    expect(rowOf(lib(['t1']), 'x')).toBeNull();
  });
  it('nothing selected: nothing to be off', () => {
    expect(offTable(lib([]), 'Hard_Bounce', 'Hard_Bounce', null)).toBe(false);
  });
});

describe('which library(view, key, …) call answers the route', () => {
  const side = { playlists: [{ name: 'Hard_Bounce' }, { name: 'Peak_Time' }], library_folders: [{ name: 'Old_Sets', path: 'Library/Old_Sets' }] } as never;
  it('All tracks and Not in a playlist are views of their own', () => {
    expect(libraryCalls(null, side)).toEqual([{ view: 'all', key: null }]);
    expect(libraryCalls(NOT_IN_PLAYLIST, side)).toEqual([{ view: 'unlisted', key: null }]);
    // an import folder or a crate by its path (the browser column's rows)
    expect(libraryCalls('/Users/you/Music/Rekordbox Library/Hardtechno', side))
      .toEqual([{ view: 'folder', key: '/Users/you/Music/Rekordbox Library/Hardtechno' }]);
  });
  it('a name the sidebar lists as a playlist is a playlist (case ignored), a Library folder asks by its path', () => {
    expect(libraryCalls('hard_bounce', side)).toEqual([{ view: 'playlist', key: 'hard_bounce' }]);
    expect(libraryCalls('Old_Sets', side)).toEqual([{ view: 'folder', key: 'Library/Old_Sets' }]);
  });
  it('a name nothing lists is asked as a playlist, which the engine answers as gone', () => {
    expect(libraryCalls('Nowhere', side)).toEqual([{ view: 'playlist', key: 'Nowhere' }]);
  });
  it('without the sidebar yet the playlist is tried first, then the Library folder', () => {
    expect(libraryCalls('Old_Sets', null)).toEqual([{ view: 'playlist', key: 'Old_Sets' }, { view: 'folder', key: 'Library/Old_Sets' }]);
  });
});


describe('a playlist view (D6, D9; issues #29 "For B6")', () => {
  const lr = (id: string, over: Partial<LibraryRow> = {}): LibraryRow => ({ ...here(row(id, { title: id })), ...over });
  const waiting = (id: string, wait: LibraryRow['wait'] = 'waiting'): LibraryRow =>
    ({ ...here(row(id, { path: null, quality: 'missing', status: 'missing' }), 'no_file'), wait });
  const summary = (tracks: number) => ({ tracks, lossless_share: null, by_quality: { lossless: 0, good_lossy: 0, weak: 0, fake: 0, missing: 0 },
    upgrades_ready: 0, to_do: 0, not_lossless: 0 });
  const view = (over: object): never => ({ view: 'playlist', key: 'Hard_Bounce', title: 'Hard_Bounce', folder: 'Hard_Bounce',
    folder_kind: null, empty: null, subtitle: ['9 tracks', 'Spotify playlist', 'Library › Hard_Bounce'], summary: summary(9),
    chips: { all: 9, lossless: 0, good_lossy: 0, weak: 0, fake: 0, upgrade_ready: 0 }, rows: [], also: null,
    read_at: '2026-10-01', enabled: true, service: 'spotify', ...over }) as never;

  it('a song without a file is dimmed, never plays, and is in To-do only when it was not found', () => {
    expect(rowDim(waiting('w'))).toBe(true);
    expect(rowDim(lr('a', { file_state: 'offline' }))).toBe(true);
    expect(rowDim(lr('a', { in_playlists: false }))).toBe(true);
    expect(rowDim(lr('a'))).toBe(false);
    expect(rowDim(lr('a', { in_playlists: false, own: true }))).toBe(false);
    expect(playable(waiting('w'))).toBe(false);
    expect(rowAway(waiting('w'))).toBeNull();
    expect(rowInTodo(waiting('w'))).toBe(false);
    expect(rowInTodo(waiting('w', 'not_found'))).toBe(true);
    expect(rowInTodo(lr('a', { status: 'not_lossless' }))).toBe(true);
    expect(rowTitleTip({ ...waiting('w'), in_playlists: false }, 'A - w')).toBe('A - w');
  });
  it('the table lists the songs, then the folder\'s other files under their head; an empty line only beside them', () => {
    const kinds = (l: ReturnType<typeof tableLines>) => l.map((x) => (x.kind === 'row' ? `${x.also ? '+' : ''}${x.row.track_id}` : x.kind));
    expect(kinds(tableLines([lr('a'), waiting('w')], [lr('left')], 'x'))).toEqual(['a', 'w', 'section', '+left']);
    expect(kinds(tableLines([], [lr('left')], 'This playlist is empty.'))).toEqual(['empty', 'section', '+left']);
    expect(kinds(tableLines([lr('a')], [], null))).toEqual(['a']);
    expect(kinds(tableLines([lr('a')], null, null))).toEqual(['a']);
    const lines = tableLines([lr('a'), lr('b')], [lr('left')], null);
    expect(lineTop(lines, 3, 38, 32)).toBe(2 * 38 + 32);
    expect(lineTop(lines, 99, 38, 32)).toBe(3 * 38 + 32);
  });
  it('the queue (the browser\'s Play too) is the table\'s order: songs, then the other files, only files that are there', () => {
    const away = lr('away', { file_state: 'offline' });
    expect(playQueue(view({ rows: [lr('b'), waiting('w'), away], also: [lr('a', { in_playlists: false })] })).map((r) => r.track_id))
      .toEqual(['b', 'a']);
    expect(playQueue(view({ rows: [lr('x'), away], also: null, view: 'folder' })).map((r) => r.track_id)).toEqual(['x']);
  });
  it('the songs without a file: the sidebar\'s songs less the ones with a file, so 9 + 3 make its 12', () => {
    const side = { playlists: [{ name: 'hard_bounce', songs: 12 }] } as never;
    const lib = view({ rows: [lr('a'), waiting('w')] });
    expect(noFileCount(lib, side, false)).toBe(3);
    // no sidebar yet: the rows, when they are the whole list
    expect(noFileCount(lib, null, true)).toBe(1);
    expect(noFileCount(lib, null, false)).toBeNull();
    expect(noFileCount(view({ read_at: null }), side, true)).toBeNull();
    expect(noFileCount(view({ view: 'folder' }), side, true)).toBeNull();
    expect(noFileCount(view({}), { playlists: [{ name: 'Hard_Bounce', songs: null }] } as never, false)).toBeNull();
  });
  it('the subtitle counts them with the songs in one part, so the count and the rows add up at every width', () => {
    expect(subtitleParts(view({}), 3)).toEqual(['9 of 12 downloaded', 'Spotify playlist', 'Library › Hard_Bounce']);
    expect(subtitleParts(view({}), 0)).toEqual(['9 tracks', 'Spotify playlist', 'Library › Hard_Bounce']);
    expect(subtitleParts(view({}), null)).toEqual(['9 tracks', 'Spotify playlist', 'Library › Hard_Bounce']);
    expect(subtitleParts(view({ subtitle: [] }), 3)).toEqual([]);
  });
  it('a song not found says what To-do offers; a waiting one when it comes', () => {
    expect(noFileNote('waiting')).toMatch(/^It downloads at the next sync/);
    expect(noFileNote('not_found', '2026-10-20'))
      .toBe('No source had a usable copy when the sync looked. Qobuz looks again on 20\u00a0Oct. To-do has links to buy it or get it another way.');
    expect(noFileNote('not_found', 'next_sync')).toMatch(/Qobuz looks again at the next sync\./);
    expect(noFileNote('not_found')).not.toMatch(/Qobuz/);
    // a switched-off playlist downloads nothing new: its waiting song says how to get it, not "at the next sync"
    expect(noFileNote('waiting', null, true)).toMatch(/switched off.*Switch it on in Playlists/);
    expect(noFileNote('not_found', null, true)).toMatch(/^No source/);
    expect(waitWords(false)).toEqual({ word: 'Waiting', tip: 'Downloads at the next sync' });
    expect(waitWords(true)).toEqual({ word: 'Switched off', tip: 'Switched off: its files stay, nothing new downloads' });
  });
});

describe('the empty states, worded by the view (I7; the engine says no_match even without search)', () => {
  const lr = (id: string): LibraryRow => here(row(id));
  const lib = (over: object) => ({ view: 'playlist', title: 'Hard_Bounce', empty: 'no_match', read_at: '2026-10-01', rows: [],
    also: null, ...over }) as never;
  it('an empty playlist, an empty folder, Not in a playlist with nothing', () => {
    expect(pageEmpty(lib({}), '', 'all').page).toMatchObject({ kind: 'empty', title: 'This playlist is empty.' });
    expect(pageEmpty(lib({ view: 'folder' }), '', 'all').page).toMatchObject({ kind: 'empty', title: 'No music in this folder.' });
    expect(pageEmpty(lib({ view: 'unlisted' }), '', 'all').page?.title).toBe('Every track is in a playlist.');
  });
  it('a playlist never read', () => {
    expect(pageEmpty(lib({ read_at: null }), '', 'all').page)
      .toEqual({ kind: 'never_read', title: "This playlist hasn't been read yet.", body: 'Read your playlists above to see its songs.' });
    expect(pageEmpty(lib({ read_at: null }), 'neon', 'all').page?.kind).toBe('never_read');
  });
  it('gone, by the view', () => {
    expect(pageEmpty(lib({ empty: 'gone' }), '', 'all').page?.title).toBe("This playlist isn't in your list any more.");
    expect(pageEmpty(lib({ empty: 'gone', view: 'folder' }), '', 'all').page?.title).toBe("This folder isn't in your library any more.");
  });
  it('a search or a filter that matches nothing; an empty library', () => {
    expect(pageEmpty(lib({}), ' neon ', 'all').page).toEqual({ kind: 'search', title: 'Nothing in Hard_Bounce matches “neon”.' });
    expect(pageEmpty(lib({}), '', 'weak').page).toEqual({ kind: 'filter', title: 'No tracks with this quality here.' });
    expect(pageEmpty(lib({ empty: 'empty_library', view: 'all' }), '', 'all').page?.kind).toBe('library');
  });
  it('rows on the table: nothing to say', () => {
    expect(pageEmpty(lib({ rows: [lr('a')], empty: null }), '', 'all')).toEqual({ page: null, line: null });
  });
  it('the playlist\'s own part empty beside its folder\'s other files: one line in the table, no empty page', () => {
    const also = [lr('left')];
    expect(pageEmpty(lib({ also }), '', 'all')).toEqual({ page: null, line: 'This playlist is empty.' });
    expect(pageEmpty(lib({ also, read_at: null }), '', 'all').line).toBe("This playlist hasn't been read yet.");
    expect(pageEmpty(lib({ also }), 'neon', 'all').line).toBe("None of the playlist's songs match “neon”.");
    expect(pageEmpty(lib({ also }), '', 'weak').line).toBe("None of the playlist's songs have this quality.");
  });
});

describe('the Also section\'s hint', () => {
  it('says the files aren\'t in the playlist only once it was read', () => {
    expect(alsoHint('Hard_Bounce')).toBe("files in Hard_Bounce that aren't in this playlist");
    expect(alsoHint('Hard_Bounce', true)).toBe('files in Hard_Bounce, until the playlist is read');
  });
});

describe('a folder view\'s Subfolder column: only with crates inside', () => {
  const lib = (over: object) => ({ view: 'folder', folder_kind: 'watched', key: '/Users/you/Music/Rekordbox Library', rows: [], ...over }) as never;
  const crate = (path: string, has_crates: boolean) => ({ path, has_crates });
  const side = { watched: [{ path: '/Users/you/Music/Rekordbox Library/', crate_count: 4, too_many: false,
    crates: [crate('/Users/you/Music/Rekordbox Library/Hardtechno', true), crate('/Users/you/Music/Rekordbox Library/Edits', false)] },
  { path: '/Volumes/Example Drive/Albums', crate_count: 312, too_many: true, crates: [] },
  { path: '/Users/you/Music/Plain', crate_count: 0, too_many: false, crates: [] }] } as never;
  it('the sidebar says: a watched folder by its crates, a crate by the crates inside it', () => {
    expect(hasSubfolders(lib({}), side)).toBe(true);
    expect(hasSubfolders(lib({ key: '/Volumes/Example Drive/Albums' }), side)).toBe(true);
    expect(hasSubfolders(lib({ key: '/Users/you/Music/Plain' }), side)).toBe(false);
    expect(hasSubfolders(lib({ folder_kind: 'crate', key: '/Users/you/Music/Rekordbox Library/Hardtechno' }), side)).toBe(true);
    expect(hasSubfolders(lib({ folder_kind: 'crate', key: '/Users/you/Music/Rekordbox Library/Edits' }), side)).toBe(false);
  });
  it('before the sidebar, the rows do; a Library folder and the views never', () => {
    expect(hasSubfolders(lib({ rows: [{ subfolder: '2019' }] }), null)).toBe(true);
    expect(hasSubfolders(lib({ rows: [{ subfolder: '' }] }), null)).toBe(false);
    expect(hasSubfolders(lib({ folder_kind: 'library', rows: [{ subfolder: 'x' }] }), side)).toBe(false);
    expect(hasSubfolders(lib({ view: 'all' }), side)).toBe(false);
  });
});
