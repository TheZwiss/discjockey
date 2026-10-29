import { describe, expect, it } from 'vitest';
import type { TrackRow } from '$lib/bridge/types';
import {
  fileName, folderCell, footAction, inTodo, isSort, moveSelection, nextSort, optionalColumns, overview, placeLine,
  rowOff, scrollToKeep, segOptions, selectedIndex, shortUrl, sortState, windowSlice,
} from './libraryModel';
import type { Library, TrackDetail } from '$lib/bridge/types';

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
  it('overview: the share as a number, nothing known without tracks', () => {
    const s = (tracks: number, lossless: number): Library['summary'] => ({ tracks, lossless_share: tracks ? lossless / tracks : null,
      by_quality: { lossless, good_lossy: 0, weak: tracks - lossless, fake: 0, missing: 0 }, upgrades_ready: 0, to_do: 0 });
    expect(overview(s(10, 6))).toEqual({ value: '60', unit: '%', label: 'lossless · 6 of 10 tracks' });
    expect(overview(s(1, 1)).label).toBe('lossless · 1 of 1 track');
    expect(overview(s(0, 0))).toEqual({ value: null, label: 'lossless · no tracks yet' });
    // two files not sound-checked yet: left out of by_quality and of the share, still in `tracks`
    const part: Library['summary'] = { tracks: 10, lossless_share: 0.5, upgrades_ready: 0, to_do: 0,
      by_quality: { lossless: 4, good_lossy: 0, weak: 4, fake: 0, missing: 0 } };
    expect(overview(part)).toEqual({ value: '50', unit: '%', label: 'lossless · 4 of 8 checked tracks' });
    expect(overview({ ...part, lossless_share: null, by_quality: { lossless: 0, good_lossy: 0, weak: 0, fake: 0, missing: 0 } }))
      .toEqual({ value: null, label: 'lossless · none checked yet' });
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
  it('optional columns: All tracks shows the folder first', () => {
    expect(optionalColumns(true)).toEqual(['folder', 'source', 'added']);
    expect(optionalColumns(false)).toEqual(['source', 'added']);
  });
  it('folder cell and sorts', () => {
    expect(folderCell(row('a'))).toBe('Hard_Bounce');
    expect(folderCell(row('a', { in_playlists: false }))).toBe('Not in a playlist');
    expect(isSort('-folder')).toBe(true);
    expect(isSort('added')).toBe(true);
    expect(isSort('bpm')).toBe(false);
  });
});

describe('a dimmed row', () => {
  it('is a downloaded song that left every playlist', () => {
    expect(rowOff(row('a'))).toBe(false);
    expect(rowOff(row('a', { in_playlists: false }))).toBe(true);
  });
  it('is never one of the users own files, which no playlist holds', () => {
    expect(rowOff(row('a', { in_playlists: false, own: true, source_name: 'own file' }))).toBe(false);
    expect(rowOff(row('a', { in_playlists: true, own: true }))).toBe(false);
  });
});

describe('copy helpers', () => {
  it('short source link and place line', () => {
    expect(shortUrl('https://www.youtube.com/watch?v=abcdefghijk')).toBe('youtube.com/watch?v=…');
    expect(shortUrl('https://soundcloud.com/a')).toBe('soundcloud.com/a');
    expect(placeLine('Hard_Bounce', 2)).toBe('Hard_Bounce · in 2 playlists');
    expect(placeLine('Hard_Bounce', 1)).toBe('Hard_Bounce · in 1 playlist');
    expect(placeLine('Hard_Bounce', null)).toBe('Hard_Bounce');
    expect(placeLine('Old_Sets', 0, false)).toBe('Not in a playlist');
  });
});
