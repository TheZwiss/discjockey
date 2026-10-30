import { describe, expect, it } from 'vitest';
import type { TrackRow } from '$lib/bridge/types';
import { NOT_IN_PLAYLIST } from '$lib/bridge/types';
import {
  columnThresholds, columnsAt, fileName, folderCell, footAction, gridColumns, inTodo, isSort, libraryView, moveSelection,
  nextSort, offTable, optionalColumns, placeLine, playable, rowAway, rowOff, rowTitleTip, scrollToKeep, segOptions, selectedIndex, shortUrl, sortState, windowSlice,
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
  it('keeps the selected row in view', () => {
    expect(scrollToKeep(0, 360, 36, 3)).toBe(0);
    expect(scrollToKeep(0, 360, 36, 12)).toBe(13 * 36 - 360);
    expect(scrollToKeep(500, 360, 36, 2)).toBe(72);
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
  it('optional columns (D10): Folder in the two views, Length everywhere, no Source or Added', () => {
    expect(optionalColumns('all')).toEqual(['folder', 'length']);
    expect(optionalColumns('unlisted')).toEqual(['folder', 'length']);
    expect(optionalColumns('folder')).toEqual(['length']);
  });
  it('thresholds add up from Track + Artist (380): Folder +140, Length +200', () => {
    expect(columnThresholds('all')).toEqual([{ column: 'folder', from: 520 }, { column: 'length', from: 720 }]);
    expect(columnThresholds('folder')).toEqual([{ column: 'length', from: 580 }]);
  });
  it("columns by the table's own width: Length goes first, Folder last (the widths table)", () => {
    // 1280 · Library (rail + browser), details closed: 946
    expect(columnsAt('all', 946)).toEqual(['folder', 'length']);
    // 1100 · Library, details closed: 766
    expect(columnsAt('all', 766)).toEqual(['folder', 'length']);
    // 1100 · details open (the browser stepped back): 685; 1280 · details open: 586
    expect(columnsAt('all', 685)).toEqual(['folder']);
    expect(columnsAt('unlisted', 586)).toEqual(['folder']);
    expect(columnsAt('folder', 586)).toEqual(['length']);
    expect(columnsAt('folder', 579)).toEqual([]);
    expect(columnsAt('all', 519)).toEqual([]);
    expect(columnsAt('all', 520)).toEqual(['folder']);
    // Length's edges: All tracks at 720, a playlist at 580
    expect(columnsAt('all', 719)).toEqual(['folder']);
    expect(columnsAt('all', 720)).toEqual(['folder', 'length']);
    expect(columnsAt('unlisted', 720)).toEqual(['folder', 'length']);
    expect(columnsAt('folder', 580)).toEqual(['length']);
  });
  it('grid: the names share the rest, fixed Length, Quality and slot', () => {
    expect(gridColumns([])).toBe('minmax(0, 1.45fr) minmax(0, 1fr) 116px var(--w-row-action)');
    expect(gridColumns(['folder', 'length']))
      .toBe('minmax(0, 1.45fr) minmax(0, 1fr) minmax(96px, .8fr) 52px 116px var(--w-row-action)');
  });
  it('tells the three lists apart', () => {
    expect(libraryView(null)).toBe('all');
    expect(libraryView(NOT_IN_PLAYLIST)).toBe('unlisted');
    expect(libraryView('Hard_Bounce')).toBe('folder');
  });
  it('folder cell and sorts', () => {
    expect(folderCell(row('a'))).toBe('Hard_Bounce');
    expect(folderCell(row('a', { in_playlists: false }))).toBe('Not in a playlist');
    // Not in a playlist: every row is in none, so the cell says where the file sits; "–" (null) without a folder
    expect(folderCell(row('a', { in_playlists: false }), 'unlisted')).toBe('Hard_Bounce');
    expect(folderCell(row('a', { in_playlists: false, folder: '' }), 'unlisted')).toBeNull();
    expect(isSort('-folder')).toBe(true);
    // Source and Added left the table: a sort by them saved before falls back to the default
    expect(isSort('added')).toBe(false);
    expect(isSort('-source')).toBe(false);
    expect(isSort('length')).toBe(true);
    expect(isSort('bpm')).toBe(false);
  });
});

const here = (r: TrackRow, file_state: LibraryRow['file_state'] = 'here'): LibraryRow => ({ ...r, sound_checked: true, file_state });

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
  it('short source link and place line', () => {
    expect(shortUrl('https://www.youtube.com/watch?v=abcdefghijk')).toBe('youtube.com/watch?v=…');
    expect(shortUrl('https://soundcloud.com/a')).toBe('soundcloud.com/a');
    expect(placeLine('Hard_Bounce')).toBe('Hard_Bounce');
    expect(placeLine('Old_Sets', false)).toBe('Not in a playlist');
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
  const lib = (folder: string | null, ids: string[]) => ({ folder, rows: ids.map((id) => row(id)) as unknown as LibraryRow[] });
  it('a track among the rows shown is on the table', () => {
    expect(offTable(lib('Hard_Bounce', ['t1', 't2']), 'Hard_Bounce', 't2')).toBe(false);
  });
  it('filtered or searched away, or gone from the library: off', () => {
    expect(offTable(lib('Hard_Bounce', ['t1']), 'Hard_Bounce', 't2')).toBe(true);
  });
  it('no rows at all (an empty library or folder, nothing matches): off', () => {
    expect(offTable(lib('Hard_Bounce', []), 'Hard_Bounce', 't2')).toBe(true);
    expect(offTable(lib(NOT_IN_PLAYLIST, []), NOT_IN_PLAYLIST, 'local:1')).toBe(true);
  });
  it('not known yet: before the first answer, or while the answer is still another folder\'s', () => {
    expect(offTable(null, 'Hard_Bounce', 't2')).toBe(false);
    expect(offTable(lib('Qobuz_Picks', ['t9']), 'Hard_Bounce', 't2')).toBe(false);
  });
  it('nothing selected: nothing to be off', () => {
    expect(offTable(lib('Hard_Bounce', []), 'Hard_Bounce', null)).toBe(false);
  });
});
