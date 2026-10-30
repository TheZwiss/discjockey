import { describe, expect, it } from 'vitest';
import type { Sidebar } from '../bridge/types';
import { NOT_IN_PLAYLIST } from '../bridge/types';
import { parseHash } from '../router';
import {
  EDGE_TIP, HANDOFF, browserList, currentKey, edgeValueText, filterText, fold, highlightOf, matchName, moveHighlight,
  playlistTip, rowByKey, rowId, searchTracksHref, sortTip, toggleClosed,
} from './browserModel';

const side: Sidebar = {
  todo: 3, all_tracks: 120, not_in_playlist: 4, limits_warning: false,
  playlists: [
    { name: 'Peak_Time', ref: 'a', service: 'spotify', enabled: true, tracks: 10 },
    { name: 'Hard_Bounce', ref: 'b', service: 'qobuz', enabled: true, tracks: 7 },
    { name: 'acid_Nights', ref: 'c', service: 'spotify', enabled: false, tracks: 2 },
    { name: 'Bouncy', ref: 'd', service: null, enabled: true, tracks: 0 },
  ],
  library_folders: [{ folder: 'Old_Sets', tracks: 5 }, { folder: 'Bounce_Dumps', tracks: 3 }],
};
const list = (o: Partial<{ query: string; az: boolean; closed: string[] }> = {}) =>
  browserList({ side, query: '', az: false, closed: [], ...o });

describe('browserList without a filter', () => {
  it('lists the views, then Playlists in playlists.txt order, then Folders', () => {
    const l = list();
    expect(l.views.map((v) => v.name)).toEqual(['All tracks', 'Not in a playlist']);
    expect(l.views.map((v) => v.href)).toEqual(['#/library', '#/library/not-in-playlist']);
    expect(l.sections.map((s) => [s.key, s.label, s.count])).toEqual([['playlists', 'Playlists', 4], ['folders', 'Folders', null]]);
    expect(l.sections[0].rows.map((r) => r.name)).toEqual(['Peak_Time', 'Hard_Bounce', 'acid_Nights', 'Bouncy']);
    expect(l.sections[1].rows.map((r) => r.name)).toEqual(['Old_Sets', 'Bounce_Dumps']);
    expect(l.handoff).toBeNull();
    expect(l.targets).toEqual([]);
  });

  it('keeps a switched-off playlist in place, with its words in the tooltip', () => {
    const off = list().sections[0].rows[2];
    expect(off).toMatchObject({ kind: 'playlist', enabled: false });
    expect(off.tip).toBe('acid_Nights\nSpotify playlist · 2 tracks\nSwitched off: its files stay, nothing new downloads');
    expect(playlistTip(side.playlists[3])).toBe('Bouncy\n0 tracks');
  });

  it('hides Not in a playlist at 0 and sections with no rows', () => {
    const l = browserList({ side: { ...side, not_in_playlist: 0, library_folders: [] }, query: '', az: false, closed: [] });
    expect(l.views.map((v) => v.key)).toEqual(['view:all']);
    expect(l.sections.map((s) => s.key)).toEqual(['playlists']);
  });

  it('orders Playlists A–Z on request, ignoring case', () => {
    expect(list({ az: true }).sections[0].rows.map((r) => r.name)).toEqual(['acid_Nights', 'Bouncy', 'Hard_Bounce', 'Peak_Time']);
  });

  it('folds a section by its key, still with its head', () => {
    const s = list({ closed: ['playlists'] }).sections[0];
    expect(s).toMatchObject({ key: 'playlists', open: false, foldable: true, count: 4 });
    expect(toggleClosed(['playlists'], 'playlists')).toEqual([]);
    expect(toggleClosed([], 'folders')).toEqual(['folders']);
  });

  it('gives a repeated ref its own key', () => {
    const twice = { ...side, playlists: [side.playlists[0], { ...side.playlists[0], name: 'Peak_Time_2' }] };
    const keys = browserList({ side: twice, query: '', az: false, closed: [] }).sections[0].rows.map((r) => r.key);
    expect(new Set(keys).size).toBe(2);
  });

  it('lists nothing before the sidebar is there, but the hand-off still works', () => {
    expect(browserList({ side: null, query: '', az: false, closed: [] }).sections).toEqual([]);
    expect(browserList({ side: null, query: 'x', az: false, closed: [] }).handoff?.text).toBe('x');
  });
});

describe('browserList while filtering', () => {
  it('matches a case-folded substring, each match once, views aside, folded sections open', () => {
    const l = list({ query: 'BOU', closed: ['playlists', 'folders'] });
    expect(l.views).toEqual([]);
    expect(l.sections.map((s) => [s.key, s.open, s.foldable, s.count])).toEqual([['playlists', true, false, null], ['folders', true, false, null]]);
    expect(l.sections[0].rows.map((r) => r.name)).toEqual(['Hard_Bounce', 'Bouncy']);
    expect(l.sections[1].rows.map((r) => r.name)).toEqual(['Bounce_Dumps']);
    expect(l.targets).toEqual(['pl:b', 'pl:d', 'fo:Bounce_Dumps', HANDOFF]);
  });

  it('marks the matched letters', () => {
    const rows = list({ query: 'bou' }).sections[0].rows;
    expect(rows.map((r) => r.match)).toEqual([[5, 8], [0, 3]]);
    expect(matchName('Hard_Bounce', 'zzz')).toBe(false);
    expect(matchName('Hard_Bounce', '')).toBeNull();
  });

  it('trims the text and matches composed and decomposed letters alike', () => {
    expect(filterText('  Peak ')).toBe('peak');
    const nfd = 'Cafe\u0301';   // "Café" with a combining accent
    const l = browserList({ side: { ...side, playlists: [{ ...side.playlists[0], name: nfd }] }, query: 'café', az: false, closed: [] });
    expect(l.sections[0].rows).toHaveLength(1);
    expect(l.sections[0].rows[0].match).toEqual([0, 5]);   // the accent after the last letter is marked with it
  });

  it('folds accents as well as case, and marks the name\'s own letters', () => {
    expect(fold('Mötley Crüe')).toBe('motley crue');
    expect(fold('ÜBER')).toBe('uber');
    expect(matchName('Mötley_Edits', 'motley')).toEqual([0, 6]);
    expect(matchName('Das Über-Set', filterText('UBER'))).toEqual([4, 8]);
    expect(matchName('Über', filterText('ü'))).toEqual([0, 1]);
    const names = { ...side, playlists: [{ ...side.playlists[0], name: 'Mötley_Edits' }, { ...side.playlists[1], name: 'Über_Trax' }] };
    const found = (query: string) => browserList({ side: names, query, az: false, closed: [] }).sections[0]?.rows.map((r) => r.name);
    expect(found('motley')).toEqual(['Mötley_Edits']);
    expect(found('uber')).toEqual(['Über_Trax']);
  });

  it('takes text of spaces only as no filter: no hand-off, no targets', () => {
    const l = list({ query: '   ' });
    expect(l.handoff).toBeNull();
    expect(l.targets).toEqual([]);
    expect(l.views).toHaveLength(2);
  });

  it('lists the matches A–Z when Playlists is in A–Z order', () => {
    expect(list({ query: 'a' }).sections[0].rows.map((r) => r.name)).toEqual(['Peak_Time', 'Hard_Bounce', 'acid_Nights']);
    const l = list({ query: 'a', az: true });
    expect(l.sections[0].rows.map((r) => r.name)).toEqual(['acid_Nights', 'Hard_Bounce', 'Peak_Time']);
    expect(l.targets.slice(0, 3)).toEqual(['pl:c', 'pl:b', 'pl:a']);
  });

  it('puts the hand-off last, with the text as typed (trimmed)', () => {
    const l = list({ query: ' Bou ' });
    expect(l.handoff).toMatchObject({ kind: 'handoff', text: 'Bou', href: '#/library?q=Bou',
      tip: 'Search every track’s title and artist for “Bou” (All tracks)' });
  });

  it('with no match leaves only the hand-off, which carries the highlight', () => {
    const l = list({ query: 'kaltf' });
    expect(l.sections).toEqual([]);
    expect(l.targets).toEqual([HANDOFF]);
    expect(highlightOf(l.targets, null)).toBe(HANDOFF);
  });
});

describe('the highlight', () => {
  const t = ['pl:b', 'pl:d', 'fo:x', HANDOFF];
  it('is the first match, or the current one while it still is a target', () => {
    expect(highlightOf(t, null)).toBe('pl:b');
    expect(highlightOf(t, 'fo:x')).toBe('fo:x');
    expect(highlightOf(t, 'pl:gone')).toBe('pl:b');
    expect(highlightOf([], 'pl:b')).toBeNull();
  });
  it('moves down to the hand-off and up to the first, held at both ends', () => {
    expect(moveHighlight(t, null, 1)).toBe('pl:d');
    expect(moveHighlight(t, 'fo:x', 1)).toBe(HANDOFF);
    expect(moveHighlight(t, HANDOFF, 1)).toBe(HANDOFF);
    expect(moveHighlight(t, 'pl:b', -1)).toBe('pl:b');
    expect(moveHighlight([], null, 1)).toBeNull();
  });
  it('finds the row to open by its key', () => {
    const l = list({ query: 'bou' });
    expect(rowByKey(l, 'pl:d')?.href).toBe('#/library/folder/Bouncy');
    expect(rowByKey(l, HANDOFF)?.href).toBe('#/library?q=bou');
    expect(rowByKey(list(), 'view:all')?.href).toBe('#/library');
    expect(rowByKey(l, 'nope')).toBeNull();
  });
});

describe('the current row', () => {
  it('follows the library route', () => {
    expect(currentKey(side, undefined)).toBeNull();
    expect(currentKey(side, null)).toBe('view:all');
    expect(currentKey(side, NOT_IN_PLAYLIST)).toBe('view:unlisted');
    expect(currentKey(side, 'Hard_Bounce')).toBe('pl:b');
    expect(currentKey(side, 'Old_Sets')).toBe('fo:Old_Sets');
    expect(currentKey(side, 'Gone')).toBeNull();
    expect(currentKey(null, 'Hard_Bounce')).toBeNull();
  });
  it('picks the playlist when a Library folder has the same name', () => {
    const both = { ...side, library_folders: [{ folder: 'Hard_Bounce', tracks: 1 }] };
    expect(currentKey(both, 'Hard_Bounce')).toBe('pl:b');
  });
  it('picks the first line of a repeated ref, whose row has the plain key', () => {
    const twice = { ...side, playlists: [side.playlists[0], { ...side.playlists[0], name: 'Peak_Time_2' }] };
    const rows = browserList({ side: twice, query: '', az: false, closed: [] }).sections[0].rows;
    expect(currentKey(twice, 'Peak_Time')).toBe(rows[0].key);
    expect(rows[1].key).not.toBe(rows[0].key);
  });
});

describe('ids and words', () => {
  it('gives each row an id of its own, whatever its key holds', () => {
    expect(rowId('pl:abc')).toBe('bc-pl.3a.abc');
    expect(rowId('fo:Old Sets')).toBe('bc-fo.3a.Old.20.Sets');
    expect(rowId('handoff')).toBe('bc-handoff');
    expect(new Set(['fo:a b', 'fo:a_b', 'fo:a.b', 'fo:a.20.b'].map(rowId)).size).toBe(4);
  });
  it('the edge names no number and says its width', () => {
    expect(EDGE_TIP).toBe('Drag to resize · double-click to reset');
    expect(edgeValueText(312)).toBe('312 px');
  });
  it('the sort toggle names the order and the click', () => {
    expect(sortTip(false)).toBe('Order: download priority (change it on the Playlists page) · click for A–Z');
    expect(sortTip(true)).toBe('Order: A–Z · click for download priority');
  });
  it('the hand-off link round-trips odd text through the route', () => {
    const text = 'a&b ?=#% “x”';
    expect(parseHash(searchTracksHref(text))).toMatchObject({ name: 'library', params: {} });
    expect(parseHash(searchTracksHref(text)).query.get('q')).toBe(text);
  });
});
