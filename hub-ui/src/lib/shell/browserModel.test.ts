import { describe, expect, it } from 'vitest';
import type { Sidebar } from '../bridge/types';
import { NOT_IN_PLAYLIST } from '../bridge/types';
import { parseHash } from '../router';
import {
  EDGE_TIP, HANDOFF, browserList, currentTarget, edgeValueText, filterText, fold, highlightOf, matchName, moveHighlight,
  playlistTip, rowByKey, rowId, searchTracksHref, sortTip, toggleClosed,
  LANDING_TEXT, crateShownValue, dropIndex, dropSpring, favouriteOf, favouriteRow, favouritesIn, folderHref, menuFor,
  moveKey, nameParts, playCall, revealPath, watchedFoldKey, type CollectionRow, type FolderRow,
} from './browserModel';
import type { Crate, WatchedEntry } from '../bridge/types';

const side: Sidebar = {
  todo: 3, all_tracks: 120, not_in_playlist: 4, limits_warning: false, favourites: [], watched: [],
  playlists: [
    { name: 'Peak_Time', ref: 'a', service: 'spotify', enabled: true, songs: 10 },
    { name: 'Hard_Bounce', ref: 'b', service: 'qobuz', enabled: true, songs: 7 },
    { name: 'acid_Nights', ref: 'c', service: 'spotify', enabled: false, songs: 2 },
    { name: 'Bouncy', ref: 'd', service: null, enabled: true, songs: 0 },
  ],
  library_folders: [{ path: 'Library/Old_Sets', name: 'Old_Sets', files: 5 },
    { path: 'Library/Bounce_Dumps', name: 'Bounce_Dumps', files: 3 }],
};
const list = (o: Partial<{ query: string; az: boolean; closed: string[] }> = {}) =>
  browserList({ side, query: '', az: false, closed: [], ...o });

describe('browserList with a corrupt stored fold list', () => {
  it('treats a stored object or string as no folded sections', () => {
    for (const bad of [{ playlists: true }, 'playlists', 7, null]) {
      const l = list({ closed: bad as never });
      expect(l.sections.map((s) => s.open)).toEqual([true, true, true]);
    }
  });
});

describe('browserList without a filter', () => {
  it('lists the views, then Favourites, Playlists in playlists.txt order, then Folders', () => {
    const l = list();
    expect(l.views.map((v) => v.name)).toEqual(['All tracks', 'Not in a playlist']);
    expect(l.views.map((v) => v.href)).toEqual(['#/library', '#/library/not-in-playlist']);
    expect(l.sections.map((s) => [s.key, s.label, s.count])).toEqual([['favourites', 'Favourites', null],
      ['playlists', 'Playlists', 4], ['folders', 'Folders', null]]);
    expect(l.sections[0].rows).toEqual([]);   // empty: the column draws its landing row
    expect(l.sections[1].rows.map((r) => r.name)).toEqual(['Peak_Time', 'Hard_Bounce', 'acid_Nights', 'Bouncy']);
    expect(l.sections[2].rows.map((r) => r.name)).toEqual(['Old_Sets', 'Bounce_Dumps']);
    expect(l.handoff).toBeNull();
    expect(l.targets).toEqual([]);
  });

  it('keeps a switched-off playlist in place, with its words in the tooltip', () => {
    const off = list().sections[1].rows[2];
    expect(off).toMatchObject({ kind: 'playlist', enabled: false });
    expect(off.tip).toBe('acid_Nights\nSpotify playlist · 2 songs\nSwitched off: its files stay, nothing new downloads');
    expect(playlistTip(side.playlists[3])).toBe('Bouncy\n0 songs');
    expect(playlistTip({ ...side.playlists[1], songs: 1 })).toBe('Hard_Bounce\nQobuz playlist · 1 song');
  });

  it('gives a playlist never read no count, and says so', () => {
    const never = { ...side.playlists[0], songs: null };
    const r = browserList({ side: { ...side, playlists: [never] }, query: '', az: false, closed: [] }).sections[1].rows[0];
    expect(r.count).toBeNull();
    expect(r.tip).toBe('Peak_Time\nSpotify playlist · not read yet');
  });

  it('hides Not in a playlist at 0 and sections with no rows', () => {
    const l = browserList({ side: { ...side, not_in_playlist: 0, library_folders: [] }, query: '', az: false, closed: [] });
    expect(l.views.map((v) => v.key)).toEqual(['view:all']);
    expect(l.sections.map((s) => s.key)).toEqual(['favourites', 'playlists']);
  });

  it('orders Playlists A–Z on request, ignoring case', () => {
    expect(list({ az: true }).sections[1].rows.map((r) => r.name)).toEqual(['acid_Nights', 'Bouncy', 'Hard_Bounce', 'Peak_Time']);
  });

  it('folds a section by its key, still with its head', () => {
    const s = list({ closed: ['playlists'] }).sections[1];
    expect(s).toMatchObject({ key: 'playlists', open: false, foldable: true, count: 4 });
    expect(toggleClosed(['playlists'], 'playlists')).toEqual([]);
    expect(toggleClosed([], 'folders')).toEqual(['folders']);
  });

  it('gives a repeated ref its own key', () => {
    const twice = { ...side, playlists: [side.playlists[0], { ...side.playlists[0], name: 'Peak_Time_2' }] };
    const keys = browserList({ side: twice, query: '', az: false, closed: [] }).sections[1].rows.map((r) => r.key);
    expect(new Set(keys).size).toBe(2);
  });

  it('lists nothing before the sidebar is there, but the hand-off still works', () => {
    expect(browserList({ side: null, query: '', az: false, closed: [] }).sections).toEqual([]);
    expect(browserList({ side: null, query: 'x', az: false, closed: [] }).handoff?.text).toBe('x');
  });
});

describe('browserList while filtering', () => {
  it('matches a case-folded substring, each match once, views and Favourites aside, folded sections open', () => {
    const l = list({ query: 'BOU', closed: ['playlists', 'folders'] });
    expect(l.views).toEqual([]);
    expect(l.sections.map((s) => [s.key, s.open, s.foldable, s.count])).toEqual([['playlists', true, false, null], ['folders', true, false, null]]);
    expect(l.sections[0].rows.map((r) => r.name)).toEqual(['Hard_Bounce', 'Bouncy']);
    expect(l.sections[1].rows.map((r) => r.name)).toEqual(['Bounce_Dumps']);
    expect(l.targets).toEqual(['playlist:b', 'playlist:d', 'folder:Library/Bounce_Dumps', HANDOFF]);
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
    expect(l.targets.slice(0, 3)).toEqual(['playlist:c', 'playlist:b', 'playlist:a']);
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
  const t = ['playlist:b', 'playlist:d', 'folder:x', HANDOFF];
  it('is the first match, or the current one while it still is a target', () => {
    expect(highlightOf(t, null)).toBe('playlist:b');
    expect(highlightOf(t, 'folder:x')).toBe('folder:x');
    expect(highlightOf(t, 'playlist:gone')).toBe('playlist:b');
    expect(highlightOf([], 'playlist:b')).toBeNull();
  });
  it('moves down to the hand-off and up to the first, held at both ends', () => {
    expect(moveHighlight(t, null, 1)).toBe('playlist:d');
    expect(moveHighlight(t, 'folder:x', 1)).toBe(HANDOFF);
    expect(moveHighlight(t, HANDOFF, 1)).toBe(HANDOFF);
    expect(moveHighlight(t, 'playlist:b', -1)).toBe('playlist:b');
    expect(moveHighlight([], null, 1)).toBeNull();
  });
  it('finds the row to open by its key', () => {
    const l = list({ query: 'bou' });
    expect(rowByKey(l, 'playlist:d')?.href).toBe('#/library/folder/Bouncy');
    expect(rowByKey(l, HANDOFF)?.href).toBe('#/library?q=bou');
    expect(rowByKey(list(), 'view:all')?.href).toBe('#/library');
    expect(rowByKey(l, 'nope')).toBeNull();
  });
});

describe('the current row', () => {
  it('follows the library route', () => {
    expect(currentTarget(side, undefined)).toBeNull();
    expect(currentTarget(side, null)).toBe('view:all');
    expect(currentTarget(side, NOT_IN_PLAYLIST)).toBe('view:unlisted');
    expect(currentTarget(side, 'Hard_Bounce')).toBe('playlist:b');
    expect(currentTarget(side, 'Old_Sets')).toBe('folder:Library/Old_Sets');
    expect(currentTarget(side, '/Volumes/Drive/Sets')).toBe('folder:/Volumes/Drive/Sets');
    expect(currentTarget(side, 'Gone')).toBeNull();
    expect(currentTarget(null, 'Hard_Bounce')).toBeNull();
  });
  it('picks the playlist when a Library folder has the same name', () => {
    const both = { ...side, library_folders: [{ path: 'Library/Hard_Bounce', name: 'Hard_Bounce', files: 1 }] };
    expect(currentTarget(both, 'Hard_Bounce')).toBe('playlist:b');
  });
  it('puts the pill on the first line of a repeated ref, whose row has the plain key', () => {
    const twice = { ...side, playlists: [side.playlists[0], { ...side.playlists[0], name: 'Peak_Time_2' }] };
    const l = browserList({ side: twice, query: '', az: false, closed: [], current: currentTarget(twice, 'Peak_Time') });
    const rows = l.sections[1].rows;
    expect(l.on).toBe(rows[0].key);
    expect(rows[1].key).not.toBe(rows[0].key);
  });
  it('puts the pill on the topmost shown row: the favourite, else its own row below', () => {
    const fav = { ...side, favourites: [{ key: 'playlist:b', kind: 'playlist' as const, name: 'Hard_Bounce',
      service: 'qobuz' as const, enabled: true, count: 7, path: null, state: 'here' as const }] };
    const at = (closed: string[]) => browserList({ side: fav, query: '', az: false, closed, current: 'playlist:b' }).on;
    expect(at([])).toBe('fav:playlist:b');
    expect(at(['favourites'])).toBe('playlist:b');
    expect(at(['favourites', 'playlists'])).toBeNull();
    expect(browserList({ side: fav, query: '', az: false, closed: [], current: 'view:all' }).on).toBe('view:all');
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

// ---------- step B: watched folders with crates, Favourites, the menu, the drag ----------
const RB = '/Users/you/Music/Rekordbox Library';
const crate = (path: string, label: string, files: number, o: Partial<Crate> = {}): Crate => ({
  path: `${RB}/${path}`, label, name: path.split('/').pop()!, tip: `Rekordbox Library › ${path.split('/').join(' › ')}`,
  files, hidden: false, has_crates: false, ...o });
const rekordbox: WatchedEntry = { path: RB, name: 'Rekordbox Library', place: '~/Music/Rekordbox Library', files: 1240,
  state: 'here', too_many: false, crate_count: 4, crates: [
    crate('Old Sets/Bounce', 'Bounce · Old Sets', 4), crate('Edits', 'Edits', 3, { hidden: true }),
    crate('DJ/Hardtechno', 'Hardtechno', 9, { has_crates: true }), crate('DJ/Hardtechno/2019', 'Hardtechno › 2019', 4)] };
const albums: WatchedEntry = { path: '/Volumes/Example Drive/Albums', name: 'Albums', place: 'Example Drive › Albums',
  files: 312, state: 'here', too_many: true, crate_count: 30, crates: Array.from({ length: 30 }, (_, i) => ({
    path: `/Volumes/Example Drive/Albums/A/Album ${i + 1}`, label: `Album ${i + 1}`, name: `Album ${i + 1}`,
    tip: `Albums › A › Album ${i + 1}`, files: 1, hidden: true, has_crates: false })) };
const vinyl: WatchedEntry = { path: '/Volumes/Vinyl Drive/Vinyl Rips', name: 'Vinyl Rips', place: 'Vinyl Drive › Vinyl Rips',
  files: 6, state: 'offline', too_many: false, crate_count: 0, crates: [] };
const full = { ...side, watched: [albums, rekordbox, vinyl] };
const folders = (o: Partial<{ query: string; closed: string[]; shown: Record<string, boolean> }> = {}) => {
  const l = browserList({ side: full, query: '', az: false, closed: [], ...o });
  return l.sections.find((x) => x.key === 'folders')!.rows as FolderRow[];
};

describe('watched folders and their crates', () => {
  it('lists each watched folder, its shown crates indented under it, then the Library folders', () => {
    expect(folders().map((r) => [r.name, r.folder, r.indent, r.lead])).toEqual([
      ['Albums', 'watched', false, 'folder'],
      ['Rekordbox Library', 'watched', false, 'folder'],
      ['Bounce · Old Sets', 'crate', true, 'none'], ['Hardtechno', 'crate', true, 'none'],
      ['Hardtechno › 2019', 'crate', true, 'none'],
      ['Vinyl Rips', 'watched', false, 'warn'],
      ['Old_Sets', 'library', false, 'folder'], ['Bounce_Dumps', 'library', false, 'folder']]);
  });
  it('gives a chevron only to a folder whose crates show; too many is one row without one', () => {
    const rows = folders();
    expect(rows.find((r) => r.name === 'Rekordbox Library')!.fold).toEqual({ key: watchedFoldKey(RB), open: true });
    expect(rows.find((r) => r.name === 'Albums')!.fold).toBeNull();
    expect(rows.find((r) => r.name === 'Vinyl Rips')!.fold).toBeNull();
  });
  it('shows a crate switched on under a folder with too many', () => {
    const on = { ...albums, crates: albums.crates.map((c, i) => (i === 3 ? { ...c, hidden: false } : c)) };
    const l = browserList({ side: { ...side, watched: [on] }, query: '', az: false, closed: [] });
    const rows = l.sections.find((x) => x.key === 'folders')!.rows as FolderRow[];
    expect(rows.slice(0, 2).map((r) => r.name)).toEqual(['Albums', 'Album 4']);
    expect(rows[0].fold?.open).toBe(true);
  });
  it('folds a watched folder by its chevron: its crates go, it stays', () => {
    const rows = folders({ closed: [watchedFoldKey(RB)] });
    expect(rows.filter((r) => r.indent)).toEqual([]);
    expect(rows.find((r) => r.name === 'Rekordbox Library')!.fold?.open).toBe(false);
  });
  it('hides a crate at once while its switch is being saved', () => {
    const rows = folders({ shown: { [`${RB}/DJ/Hardtechno`]: false, [`${RB}/Edits`]: true } });
    expect(rows.filter((r) => r.indent).map((r) => r.name)).toEqual(['Bounce · Old Sets', 'Edits', 'Hardtechno › 2019']);
  });
  it('aligns the chevrons: the widest count of a folder with one, in digits', () => {
    expect(browserList({ side: full, query: '', az: false, closed: [] }).countCh).toBe('1,240'.length);
  });
  it('links an import folder and a crate by path, a Library folder by name', () => {
    const rows = folders();
    expect(rows.find((r) => r.name === 'Hardtechno')!.href).toBe(`#/library/folder/${encodeURIComponent(`${RB}/DJ/Hardtechno`)}`);
    expect(rows.find((r) => r.name === 'Old_Sets')!.href).toBe('#/library/folder/Old_Sets');
    expect(folderHref('Library/Old_Sets')).toBe('#/library/folder/Old_Sets');
    expect(parseHash(folderHref(`${RB}/DJ/Hardtechno`)).params.folder).toBe(`${RB}/DJ/Hardtechno`);
  });
  it('words each folder row (I7): place and count, what is hidden, an away drive, too many', () => {
    const rows = folders();
    expect(rows.find((r) => r.name === 'Rekordbox Library')!.tip).toBe('~/Music/Rekordbox Library\n1,240 tracks · 3 of 4 folders shown');
    expect(rows.find((r) => r.name === 'Vinyl Rips')!.tip).toBe('Vinyl Drive › Vinyl Rips\n6 tracks\nOffline: connect the drive');
    expect(rows.find((r) => r.name === 'Albums')!.tip).toBe('Example Drive › Albums\n312 tracks\n30 folders with music: choose which to show in Settings → Watched folders');
    expect(rows.find((r) => r.name === 'Hardtechno › 2019')!.tip).toBe('Rekordbox Library › DJ › Hardtechno › 2019\n4 tracks');
    expect(rows.find((r) => r.name === 'Old_Sets')!.tip).toBe('Library › Old_Sets\n5 tracks · no playlist uses it');
  });
});

describe('the filter over crates', () => {
  it('finds hidden crates and those of a folder with too many, under their watched folder as context', () => {
    const rows = folders({ query: 'album 1' });
    expect(rows.slice(0, 3).map((r) => [r.name, r.context])).toEqual([['Albums', true], ['Album 1', false], ['Album 10', false]]);
    expect(rows[1].tip).toBe('Albums › A › Album 1\n1 track\nNot in the sidebar: Albums has 30 folders with music');
    const edits = folders({ query: 'edits' });
    expect(edits.map((r) => [r.name, r.context, r.crate?.hidden ?? null])).toEqual([['Rekordbox Library', true, null], ['Edits', false, true]]);
    expect(edits[1].tip).toContain('\nHidden from the sidebar: Settings brings it back');
  });
  it('never makes a context row a target; a watched folder whose own name matches is one', () => {
    const l = browserList({ side: full, query: 'edits', az: false, closed: [] });
    expect(l.targets).toEqual([`folder:${RB}/Edits`, HANDOFF]);
    const own = browserList({ side: full, query: 'rekordbox', az: false, closed: [watchedFoldKey(RB)] });
    expect(own.targets).toEqual([`folder:${RB}`, HANDOFF]);
  });
  it('matches the label as shown and marks it there', () => {
    const rows = folders({ query: 'old sets' });
    expect(rows.map((r) => [r.name, r.match])).toEqual([['Rekordbox Library', null], ['Bounce · Old Sets', [9, 17]]]);
  });
});

describe('a name in pieces', () => {
  it('makes only the separators quiet, and the match bold', () => {
    expect(nameParts('Hardtechno › 2019', null)).toEqual([{ text: 'Hardtechno' }, { text: ' › ', sep: true }, { text: '2019' }]);
    expect(nameParts('Bounce · Old Sets', [0, 3])).toEqual([{ text: 'Bou', hl: true }, { text: 'nce' },
      { text: ' · ', sep: true }, { text: 'Old Sets' }]);
    expect(nameParts('Peak_Time', null)).toEqual([{ text: 'Peak_Time' }]);
    expect(nameParts('a › b', [0, 5]).map((p) => [p.text, !!p.sep, !!p.hl])).toEqual([['a', false, true], [' › ', true, true], ['b', false, true]]);
  });
});

describe('Favourites', () => {
  const favs = { ...full, favourites: [
    { key: 'playlist:b', kind: 'playlist' as const, name: 'Hard_Bounce', service: 'qobuz' as const, enabled: true, count: 7,
      path: null, state: 'here' as const },
    { key: `folder:${RB}/DJ/Hardtechno`, kind: 'folder' as const, name: 'Hardtechno', service: null, enabled: true,
      count: 9, path: `${RB}/DJ/Hardtechno`, state: 'here' as const },
    { key: 'folder:/Volumes/Vinyl Drive/Vinyl Rips', kind: 'folder' as const, name: 'Vinyl Rips', service: null,
      enabled: true, count: 6, path: '/Volumes/Vinyl Drive/Vinyl Rips', state: 'offline' as const }] };
  it('lists them in the stored order, a pinned crate with the folder outline, an away one with the "!"', () => {
    const rows = browserList({ side: favs, query: '', az: false, closed: [] }).sections[0].rows;
    expect(rows.map((r) => [r.key, r.target, r.lead, r.indent, r.count])).toEqual([
      ['fav:playlist:b', 'playlist:b', 'service', false, 7],
      [`fav:folder:${RB}/DJ/Hardtechno`, `folder:${RB}/DJ/Hardtechno`, 'folder', false, 9],
      ['fav:folder:/Volumes/Vinyl Drive/Vinyl Rips', 'folder:/Volumes/Vinyl Drive/Vinyl Rips', 'warn', false, 6]]);
    expect(rows[1].tip).toBe('Rekordbox Library › DJ › Hardtechno\n9 tracks');
    expect(rows[2].tip).toContain('Offline: connect the drive');
    expect(rows[0].href).toBe('#/library/folder/Hard_Bounce');
  });
  it('steps aside while filtering', () => {
    expect(browserList({ side: favs, query: 'hard', az: false, closed: [] }).sections.map((x) => x.key))
      .toEqual(['playlists', 'folders']);
  });
  it('shows a saved order at once, made from the sidebar\'s rows where it has no favourite yet', () => {
    const keys = [`folder:${RB}/DJ/Hardtechno/2019`, 'playlist:b', 'playlist:a', 'folder:Library/Old_Sets', 'folder:/gone'];
    expect(favouritesIn(favs, keys).map((f) => [f.key, f.name, f.count, f.state])).toEqual([
      [`folder:${RB}/DJ/Hardtechno/2019`, 'Hardtechno › 2019', 4, 'here'], ['playlist:b', 'Hard_Bounce', 7, 'here'],
      ['playlist:a', 'Peak_Time', 10, 'here'], ['folder:Library/Old_Sets', 'Old_Sets', 5, 'here']]);
    expect(favouritesIn(favs, null)).toBe(favs.favourites);
    expect(favouriteOf(full, 'folder:/Volumes/Vinyl Drive/Vinyl Rips')).toMatchObject({ name: 'Vinyl Rips', state: 'offline' });
    expect(favouriteOf(full, 'view:all')).toBeNull();
  });
  it('makes the full sidebar\'s shortcuts from the same rows', () => {
    const r = favouriteRow(favs.favourites[0], favs);
    expect(r).toMatchObject({ name: 'Hard_Bounce', href: '#/library/folder/Hard_Bounce', lead: 'service' });
  });
  it('has its landing row\'s words', () => {
    expect(LANDING_TEXT).toBe('Drag a playlist or folder here');
  });
});

describe('the drag', () => {
  it('moves a key to its new place, or puts a new one in, held to the ends', () => {
    expect(moveKey(['a', 'b', 'c', 'd'], 'c', 1)).toEqual(['a', 'c', 'b', 'd']);
    expect(moveKey(['a', 'b', 'c'], 'a', 9)).toEqual(['b', 'c', 'a']);
    expect(moveKey(['a', 'b'], 'x', 1)).toEqual(['a', 'x', 'b']);
    expect(moveKey([], 'x', -3)).toEqual(['x']);
  });
  it('lands below every row whose middle is above the pointer', () => {
    expect(dropIndex([15, 47, 79], 10)).toBe(0);
    expect(dropIndex([15, 47, 79], 50)).toBe(2);
    expect(dropIndex([15, 47, 79], 200)).toBe(3);
  });
  it('settles on a critically damped spring: no overshoot, about 0.4 s for a row', () => {
    const s = dropSpring(32);
    const pts = s.easing.replace(/^linear\(|\)$/g, '').split(', ').map(Number);
    expect(pts[0]).toBe(0);
    expect(pts.at(-1)).toBe(1);
    expect(pts.every((p, i) => i === 0 || p >= pts[i - 1])).toBe(true);
    expect(pts.every((p) => p <= 1)).toBe(true);
    expect(s.duration).toBeGreaterThan(250);
    expect(s.duration).toBeLessThan(500);
    expect(dropSpring(0).duration).toBeGreaterThanOrEqual(120);
  });
});

describe('the right-click menu', () => {
  const l = browserList({ side: full, query: '', az: false, closed: [] });
  const fo = l.sections.find((x) => x.key === 'folders')!.rows;
  const byName = (n: string) => fo.find((r) => r.name === n)! as CollectionRow;
  const pl = l.sections.find((x) => x.key === 'playlists')!.rows[1];
  const words = (r: CollectionRow, favs: string[] = []) => menuFor(r, new Set(favs)).map((m) => m.label);
  it('offers Open, Play, the favourite, Hide on a crate and Show in Finder where it can', () => {
    expect(words(pl)).toEqual(['Open', 'Play', 'Add to favourites', 'Show in Finder']);
    expect(words(pl, ['playlist:b'])).toEqual(['Open', 'Play', 'Remove from favourites', 'Show in Finder']);
    expect(words(byName('Hardtechno'))).toEqual(['Open', 'Play', 'Add to favourites', 'Hide from sidebar']);
    expect(menuFor(byName('Hardtechno'), new Set()).find((m) => m.action === 'hide')!.note).toBe('Settings brings it back');
    expect(words(byName('Rekordbox Library'))).toEqual(['Open', 'Play', 'Add to favourites']);
    expect(words(byName('Old_Sets'))).toEqual(['Open', 'Play', 'Add to favourites', 'Show in Finder']);
    expect(menuFor(l.views[0], new Set()).map((m) => m.label)).toEqual(['Open', 'Play']);
  });
  it('offers Show in sidebar on a hidden crate the filter found, and no Hide on a favourite', () => {
    const edits = folders({ query: 'edits' })[1];
    expect(words(edits)).toEqual(['Open', 'Play', 'Add to favourites', 'Show in sidebar']);
    const fav = favouriteRow({ key: `folder:${RB}/DJ/Hardtechno`, kind: 'folder', name: 'Hardtechno', service: null,
      enabled: true, count: 9, path: `${RB}/DJ/Hardtechno`, state: 'here' }, full);
    expect(words(fav, [fav.target])).toEqual(['Open', 'Play', 'Remove from favourites']);
  });
  it('saves only an override that differs from the default', () => {
    expect(crateShownValue(false, false)).toBe(false);
    expect(crateShownValue(false, true)).toBeNull();
    expect(crateShownValue(true, true)).toBe(true);
    expect(crateShownValue(true, false)).toBeNull();
  });
  it('plays a row\'s own view and shows in Finder only inside the music folder', () => {
    expect(playCall(pl)).toEqual({ view: 'playlist', key: 'Hard_Bounce' });
    expect(playCall(byName('Hardtechno'))).toEqual({ view: 'folder', key: `${RB}/DJ/Hardtechno` });
    expect(playCall(l.views[1])).toEqual({ view: 'unlisted', key: null });
    expect(revealPath(pl)).toBe('Library/Hard_Bounce');
    expect(revealPath(byName('Old_Sets'))).toBe('Library/Old_Sets');
    expect(revealPath(byName('Hardtechno'))).toBeNull();
  });
});
