// The fake's records, crates, Favourites and views must follow the engine's rules (discjockey/hub/views.py,
// api.py; plan library stage 5, I4, D8–D12, D15). The pure rules first, then the scenarios the browser is built on.
import { describe, expect, it } from 'vitest';
import { createFakeBridge } from './bridge';
import { cratesOf, placeWords } from './library';

const fake = (scenario: string) => createFakeBridge(scenario, { speed: 200 });
const must = <T extends { ok: boolean }>(r: T): Extract<T, { ok: true }> => {
  if (!r.ok) throw new Error(JSON.stringify(r));
  return r as Extract<T, { ok: true }>;
};
const REKORDBOX = '/Users/you/Music/Rekordbox Library';
const ALBUMS = '/Volumes/Example Drive/Albums';

describe('crates (views.crates, D8)', () => {
  const W = '/Volumes/Drive/Sets';
  it('a crate is a folder holding a file; wrapper folders and the watched folder itself get none', () => {
    const r = cratesOf([`${W}/loose.wav`, `${W}/Wrap/Inner/a.wav`, `${W}/Wrap/Inner/b.wav`, `${W}/Hard/c.wav`], [W], {});
    expect(r[W].crates.map((c) => [c.label, c.files, c.tip])).toEqual([
      ['Hard', 1, 'Sets › Hard'], ['Inner', 2, 'Sets › Wrap › Inner']]);
    expect(r[W]).toMatchObject({ too_many: false, crate_count: 2 });
  });
  it('a crate in a crate is labelled "Parent › Child", counts files below it and marks its parent', () => {
    const r = cratesOf([`${W}/Hard/a.wav`, `${W}/Hard/2019/b.wav`, `${W}/Hard/2019/c.wav`], [W], {});
    expect(r[W].crates).toMatchObject([
      { label: 'Hard', files: 3, has_crates: true }, { label: 'Hard › 2019', name: '2019', files: 2, has_crates: false }]);
  });
  it('two crates of one name (case ignored) say where they are, hidden or not', () => {
    const r = cratesOf([`${W}/Bounce/a.wav`, `${W}/Old/bounce/b.wav`], [W], { [`${W}/Old/bounce`]: false });
    expect(r[W].crates.map((c) => [c.label, c.hidden])).toEqual([['bounce · Old', true], ['Bounce · Sets', false]]);
  });
  it('numbers sort as numbers', () => {
    const r = cratesOf([`${W}/Set 10/a.wav`, `${W}/Set 2/a.wav`, `${W}/set 1/a.wav`], [W], {});
    expect(r[W].crates.map((c) => c.label)).toEqual(['set 1', 'Set 2', 'Set 10']);
  });
  it('more than 25 crates start hidden; a switch beats the default either way', () => {
    const files = Array.from({ length: 26 }, (_, i) => `${W}/Album ${i}/a.wav`);
    const many = cratesOf(files, [W], { [`${W}/Album 3`]: true })[W];
    expect(many.too_many).toBe(true);
    expect(many.crates.filter((c) => !c.hidden).map((c) => c.label)).toEqual(['Album 3']);
    const few = cratesOf(files.slice(0, 25), [W], { [`${W}/Album 3`]: false })[W];
    expect(few.too_many).toBe(false);
    expect(few.crates.filter((c) => c.hidden).map((c) => c.label)).toEqual(['Album 3']);
  });
  it('a file under two watched folders belongs to the deeper one', () => {
    const r = cratesOf([`${W}/Deep/Crate/a.wav`], [W, `${W}/Deep`], {});
    expect(r[W].crate_count).toBe(0);
    expect(r[`${W}/Deep`].crates.map((c) => c.label)).toEqual(['Crate']);
  });
});

describe('placeWords (views.place)', () => {
  it('says the home folder as ~ and a drive by its name first', () => {
    expect(placeWords('/Users/you')).toBe('~');
    expect(placeWords('/Users/you/Music/Old')).toBe('~/Music/Old');
    expect(placeWords('/Volumes/Example Drive/Music/Old')).toBe('Example Drive › Music/Old');
    expect(placeWords('/Volumes/Example Drive')).toBe('Example Drive');
    expect(placeWords('/opt/music')).toBe('/opt/music');
  });
});

describe('library:crates', () => {
  const f = fake('library:crates');
  it('lists the watched folders by name, each with its place, state and crates', async () => {
    const side = must(await f.sidebar());
    expect(side.watched.map((w) => [w.name, w.place, w.state, w.too_many, w.crate_count])).toEqual([
      ['Albums', 'Example Drive › Albums', 'here', true, 312],
      ['Rekordbox Library', '~/Music/Rekordbox Library', 'here', false, 6],
      ['Vinyl Rips', 'Vinyl Drive › Vinyl Rips', 'offline', false, 2]]);
    const rb = side.watched[1];
    expect(rb.files).toBe(31);
    expect(rb.crates.map((c) => [c.label, c.files, c.hidden, c.has_crates])).toEqual([
      ['Bounce · Old Sets', 4, false, false], ['Bounce · Rekordbox Library', 6, false, false], ['Edits', 3, true, false],
      ['Hardtechno', 9, false, true], ['Hardtechno › 2019', 4, false, false], ['Peak Time', 7, false, false]]);
    expect(rb.crates.find((c) => c.name === '2019')!.tip).toBe('Rekordbox Library › Hardtechno › 2019');
  });
  it('Albums has 312 album folders, all hidden because there are too many', async () => {
    const albums = must(await f.sidebar()).watched[0];
    expect(albums.crates).toHaveLength(312);
    expect(albums.crates.every((c) => c.hidden && c.files === 1)).toBe(true);
    expect(new Set(albums.crates.map((c) => c.label)).size).toBe(312);
  });
  it('Settings gets the same crates and too_many in watched_folders()', async () => {
    const rows = must(await f.watched_folders()).folders;
    expect(rows.map((r) => [r.name, r.state, r.crates.length, r.too_many])).toEqual([
      ['Library', 'online', 0, false], ['Rekordbox Library', 'online', 6, false], ['Albums', 'online', 312, true],
      ['Vinyl Rips', 'offline', 2, false]]);
  });
  it('the Library folder no playlist uses is listed beside Old_Sets', async () => {
    expect(must(await f.sidebar()).library_folders).toEqual([
      { path: 'Library/Old_Hardstyle', name: 'Old_Hardstyle', files: 4 }, { path: 'Library/Old_Sets', name: 'Old_Sets', files: 2 }]);
  });
  it('has four Favourites in the stored order, resolved', async () => {
    const side = must(await f.sidebar());
    expect(side.favourites.map((x) => [x.kind, x.name, x.state])).toEqual([
      ['playlist', 'Hard_Bounce', 'here'], ['folder', 'Hardtechno', 'here'], ['folder', 'Peak Time', 'here'],
      ['folder', 'Bounce · Old Sets', 'here']]);
    expect(side.favourites[1]).toMatchObject({ path: `${REKORDBOX}/Hardtechno`, count: 9, service: null, enabled: true });
    expect(side.favourites[0]).toMatchObject({ path: null, service: 'spotify', enabled: true });
    expect(side.favourites[0].count).toBe(side.playlists.find((p) => p.name === 'Hard_Bounce')!.songs);
  });
  it('a watched folder view lists its files with their crate; the folder says what it is', async () => {
    const v = must(await f.library('folder', REKORDBOX, '', 'all', 'artist'));
    expect(v).toMatchObject({ title: 'Rekordbox Library', view: 'folder', key: REKORDBOX, folder_kind: 'watched', also: null,
      empty: null, subtitle: ['31 tracks', '6 folders with music', '~/Music/Rekordbox Library'] });
    expect(v.summary.tracks).toBe(31);
    const by = (sub: string) => v.rows.filter((r) => r.subfolder === sub).length;
    expect([by(''), by('Bounce · Rekordbox Library'), by('Bounce · Old Sets'), by('Hardtechno › 2019'), by('Edits')]).toEqual([2, 6, 4, 4, 3]);
    expect(v.rows.every((r) => r.place !== null)).toBe(true);
    expect(v.rows.find((r) => r.subfolder === 'Hardtechno › 2019')!.place).toBe('Rekordbox Library › Hardtechno › 2019');
    expect(v.rows.find((r) => r.subfolder === '')!.place).toBe('Rekordbox Library');
  });
  it('a crate view shows the folders below it as the row subfolder', async () => {
    const v = must(await f.library('folder', `${REKORDBOX}/Hardtechno`, '', 'all', 'artist'));
    expect(v).toMatchObject({ title: 'Hardtechno', folder_kind: 'crate', subtitle: ['9 tracks', 'Rekordbox Library › Hardtechno'] });
    expect(v.rows.map((r) => r.subfolder).sort()).toEqual(['', '', '', '', '', '2019', '2019', '2019', '2019']);
    // a path is a folder at its '/', not by its first letters
    expect(must(await f.library('folder', `${REKORDBOX}/Hard`, '', 'all', 'artist')).empty).toBe('gone');
  });
  it('an away folder says so second; its rows read offline', async () => {
    const v = must(await f.library('folder', '/Volumes/Vinyl Drive/Vinyl Rips', '', 'all', 'artist'));
    expect(v.subtitle).toEqual(['6 tracks', 'Offline: connect the drive', '2 folders with music', 'Vinyl Drive › Vinyl Rips']);
    expect(v.rows.every((r) => r.file_state === 'offline')).toBe(true);
    const crate = must(await f.library('folder', '/Volumes/Vinyl Drive/Vinyl Rips/Side A', '', 'all', 'artist'));
    expect(crate.subtitle).toEqual(['3 tracks', 'Offline: connect the drive', 'Vinyl Rips › Side A']);
  });
  it('a row reads its folder\'s state, not its own flag (as the engine does)', async () => {
    const f = fake('library:crates');
    for (const t of f._ctx.s.tracks) t.away = undefined;
    const v = must(await f.library('folder', '/Volumes/Vinyl Drive/Vinyl Rips', '', 'all', 'artist'));
    expect(v.rows.every((r) => r.file_state === 'offline')).toBe(true);
    // a flag on a file in a folder that is there changes nothing in the list
    f._ctx.s.tracks.find((t) => t.folder === 'Hard_Bounce')!.away = 'offline';
    const all = must(await f.library('all', null, '', 'all', 'artist'));
    expect(all.rows.filter((r) => r.file_state === 'offline').length).toBe(v.rows.length);
  });
  it('a Library folder no playlist uses has its own words; a path nothing knows is gone', async () => {
    const v = must(await f.library('folder', 'Library/Old_Hardstyle', '', 'all', 'artist'));
    expect(v).toMatchObject({ folder_kind: 'library', subtitle: ['4 tracks', 'no playlist uses it', 'Library › Old_Hardstyle'] });
    const gone = must(await f.library('folder', '/Nowhere/Else', '', 'all', 'artist'));
    expect(gone).toMatchObject({ empty: 'gone', folder_kind: null, subtitle: [], rows: [] });
  });
  it("track() says where the file sits, in the Folder column's words", async () => {
    const place = async (id: string) => must(await f.track(id)).track.place;
    expect(await place('local:18')).toBe('Rekordbox Library › Hardtechno › 2019');
    expect(await place('local:1')).toBe('Rekordbox Library');
    expect(await place('old-hardstyle-0')).toBe('Old_Hardstyle');
    const t1 = must(await f.track('t1')).track;
    expect(t1.place).toBe(t1.path!.split('/')[1]);   // a playlist's file: its Library folder, as the disk has it
  });
});

describe('Favourites and crate switches are brief saves (D15)', () => {
  it('set_favourites answers the stored list, once per key, in order; the sidebar follows', async () => {
    const f = fake('library:crates');
    const keys = must(await f.sidebar()).favourites.map((x) => x.key);
    const r = must(await f.set_favourites([keys[2], keys[0], keys[2]]));
    expect(r.favourites).toEqual([keys[2], keys[0]]);
    expect(must(await f.sidebar()).favourites.map((x) => x.key)).toEqual([keys[2], keys[0]]);
    expect(must(await f.set_favourites([])).favourites).toEqual([]);
  });
  it('a key whose target is gone is left out of the sidebar, but stays stored', async () => {
    const f = fake('library:crates');
    const ghost = 'folder:/Volumes/Gone/Nothing';
    const keys = must(await f.sidebar()).favourites.map((x) => x.key);
    await f.set_favourites([ghost, ...keys]);
    expect(must(await f.sidebar()).favourites.map((x) => x.key)).toEqual(keys);
    expect(must(await f.set_favourites([ghost])).favourites).toEqual([ghost]);
  });
  it('refuses what is no list of keys', async () => {
    const f = fake('normal');
    expect(await f.set_favourites(['nonsense'])).toMatchObject({ ok: false, kind: 'refused' });
    expect(await f.set_favourites('playlist:x' as never)).toMatchObject({ ok: false, kind: 'refused' });
    expect(await f.set_crate_shown('', true)).toMatchObject({ ok: false, kind: 'refused' });
    expect(await f.set_crate_shown(`${REKORDBOX}/Edits`, 'yes' as never)).toMatchObject({ ok: false, kind: 'refused' });
  });
  it('answers busy and changes nothing when told the file is held', async () => {
    const f = fake('library:crates');
    const before = must(await f.sidebar()).favourites.map((x) => x.key);
    f._ctx.s.briefBusy = true;
    expect(await f.set_favourites([])).toMatchObject({ ok: false, kind: 'busy' });
    expect(await f.set_crate_shown(`${REKORDBOX}/Peak Time`, false)).toMatchObject({ ok: false, kind: 'busy' });
    f._ctx.s.briefBusy = false;
    const side = must(await f.sidebar());
    expect(side.favourites.map((x) => x.key)).toEqual(before);
    expect(side.watched[1].crates.find((c) => c.name === 'Peak Time')!.hidden).toBe(false);
  });
  it('the scenario library:crates_busy starts with the file held, for the page that shoots the busy state', async () => {
    const f = fake('library:crates_busy');
    expect(must(await f.sidebar()).favourites).toHaveLength(4);
    expect(await f.set_favourites([])).toMatchObject({ ok: false, kind: 'busy' });
  });
  it('set_crate_shown switches a crate; null goes back to the default', async () => {
    const f = fake('library:crates');
    const crate = async (root: number, name: string) =>
      must(await f.sidebar()).watched[root].crates.find((c) => c.name === name)!;
    expect(must(await f.set_crate_shown(`${REKORDBOX}/Peak Time`, false))).toMatchObject({ path: `${REKORDBOX}/Peak Time`, shown: false });
    expect((await crate(1, 'Peak Time')).hidden).toBe(true);
    must(await f.set_crate_shown(`${REKORDBOX}/Edits`, true));
    expect((await crate(1, 'Edits')).hidden).toBe(false);
    must(await f.set_crate_shown(`${REKORDBOX}/Edits`, null));
    expect((await crate(1, 'Edits')).hidden).toBe(false);     // the default of a folder with few crates: shown
    must(await f.set_crate_shown(`${ALBUMS}/Neon Nights`, true));
    expect((await crate(0, 'Neon Nights')).hidden).toBe(false);
    expect((await crate(0, 'Harbour Nights')).hidden).toBe(true);
    must(await f.set_crate_shown(`${ALBUMS}/Neon Nights`, null));
    expect((await crate(0, 'Neon Nights')).hidden).toBe(true);
    // Settings reads the same switches
    must(await f.set_crate_shown(`${ALBUMS}/Neon Nights`, true));
    const row = must(await f.watched_folders()).folders.find((r) => r.name === 'Albums')!;
    expect(row.crates.filter((c) => !c.hidden).map((c) => c.name)).toEqual(['Neon Nights']);
  });
  it('the brief saves answer no_library while no music folder is bound, like every library method', async () => {
    const f = fake('no_music');
    expect(await f.set_favourites([])).toMatchObject({ ok: false, kind: 'no_library' });
    expect(await f.set_crate_shown(REKORDBOX, true)).toMatchObject({ ok: false, kind: 'no_library' });
  });
});

describe('library:first_look and library:never_read', () => {
  it('first_look has the folders and crates but no Favourites', async () => {
    const side = must(await fake('library:first_look').sidebar());
    expect(side.favourites).toEqual([]);
    expect(side.watched).toHaveLength(3);
  });
  it('the normal state has no Favourites and no watched folders with music in the sidebar either', async () => {
    const side = must(await fake('normal').sidebar());
    expect(side.favourites).toEqual([]);
    expect(side.watched.map((w) => [w.name, w.crate_count])).toEqual([['Music', 0]]);
  });
  it('never_read: no playlist knows its songs, its view says it was never read', async () => {
    const f = fake('library:never_read');
    const side = must(await f.sidebar());
    expect(side.playlists.every((p) => p.songs === null)).toBe(true);
    const v = must(await f.library('playlist', 'Hard_Bounce', '', 'all', null));
    expect(v).toMatchObject({ read_at: null, enabled: true, service: 'spotify', subtitle: ['Spotify playlist', 'not read yet'] });
    expect(v.rows.every((r) => r.file_state !== 'no_file')).toBe(true);
    expect(v.also!.length).toBeGreaterThan(0);   // the folder's files are all "also": the playlist holds no song
    expect(v.rows).toEqual([]);
  });
});

describe('library views of a playlist (D9)', () => {
  it('lists the read record in its order, the waiting songs among it, and the folder files it does not hold as also', async () => {
    const f = fake('normal');
    const v = must(await f.library('playlist', 'hard_bounce', '', 'all', null));   // any case
    expect(v).toMatchObject({ title: 'Hard_Bounce', folder: 'Hard_Bounce', view: 'playlist', key: 'Hard_Bounce',
      folder_kind: null, enabled: true, service: 'spotify', empty: null });
    expect(v.read_at).not.toBeNull();
    expect(v.rows.map((r) => r.position)).toEqual(v.rows.map((_, i) => i + 1));      // the playlist's own order
    const waiting = v.rows.filter((r) => r.file_state === 'no_file');
    // a song the sync found nothing for is Not found; one it has yet to look at (t4) waits
    expect(waiting.find((r) => r.track_id === 't3')).toMatchObject({ wait: 'not_found', path: null, place: null, quality: 'missing' });
    expect(waiting.find((r) => r.track_id === 't4')).toMatchObject({ wait: 'waiting', path: null, place: null, title: 'AEIOU' });
    expect(waiting.every((r) => r.wait === (r.track_id === 't3' ? 'not_found' : 'waiting'))).toBe(true);
    // rows with a file are the only ones counted; one in the playlist's own folder says no place, any other its folder
    expect(v.summary.tracks).toBe(v.rows.length - waiting.length);
    for (const r of v.rows.filter((x) => x.file_state !== 'no_file')) {
      const folder = r.path!.split('/')[1];
      expect(r.place).toBe(folder === 'Hard_Bounce' ? null : folder);
    }
    expect(v.subtitle).toEqual([`${v.summary.tracks} tracks`, 'Spotify playlist', 'Library › Hard_Bounce']);
    expect(v.also).toEqual([]);
  });
  it('waiting songs of a library with no file at all still list', async () => {
    const f = fake('normal');
    f._ctx.s.tracks = [];
    const v = must(await f.library('playlist', 'Hard_Bounce', '', 'all', null));
    expect(v.rows.length).toBeGreaterThan(0);
    expect(v.rows.every((r) => r.file_state === 'no_file' && r.wait === 'waiting' && r.path === null)).toBe(true);
    expect(v.summary.tracks).toBe(0);
  });
  it('a song held by two playlists names both, in playlists.txt order, and has a place outside its own folder', async () => {
    const f = fake('normal');
    const v = must(await f.library('playlist', 'Powertrance', '', 'all', null));
    const t2 = v.rows.find((r) => r.track_id === 't2')!;
    expect(t2.playlists).toEqual(['Hard_Bounce', 'Powertrance']);
    expect(t2.place).toBe('Hard_Bounce');
  });
  it('search narrows rows and also; chips count rows with a file; the filter applies to both', async () => {
    const f = fake('normal');
    const all = must(await f.library('playlist', 'Hard_Bounce', '', 'all', null));
    const weak = must(await f.library('playlist', 'Hard_Bounce', '', 'weak', null));
    expect(weak.chips).toEqual(all.chips);
    expect(weak.rows.every((r) => r.quality === 'weak' && r.file_state !== 'no_file')).toBe(true);
    const found = must(await f.library('playlist', 'Hard_Bounce', 'zzzz-no-such-song', 'all', null));
    expect(found).toMatchObject({ rows: [], also: [], empty: 'no_match', chips: { all: 0 } });
    expect(found.summary.tracks).toBe(all.summary.tracks);
  });
  it('sorts by the playlist order by default and by a column when asked, either way round', async () => {
    const f = fake('normal');
    const title = must(await f.library('playlist', 'Hard_Bounce', '', 'all', 'title')).rows.map((r) => r.title.toLowerCase());
    expect(title).toEqual([...title].sort());
    const back = must(await f.library('playlist', 'Hard_Bounce', '', 'all', '-title')).rows.map((r) => r.title.toLowerCase());
    expect(back).toEqual([...title].reverse());
    expect(must(await f.library('all', null, '', 'all', 'order')).rows[0].position).toBeNull();   // no order outside a playlist
  });
  it('a playlist that is read and empty is told apart from one never read', async () => {
    const f = fake('normal');
    f._ctx.s.emptyRead = ['Hard_Techno'];
    expect(must(await f.library('playlist', 'Hard_Techno', '', 'all', null))).toMatchObject({
      rows: [], also: [], empty: 'no_match', subtitle: ['0 tracks', 'Spotify playlist', 'Library › Hard_Techno'] });
    expect(must(await f.library('playlist', 'Powertrance', '', 'all', null)).read_at).not.toBeNull();
    expect(must(await f.library('playlist', 'Hard_Techno', '', 'all', null)).read_at).not.toBeNull();
    expect(must(await f.sidebar()).playlists.find((p) => p.name === 'Hard_Techno')!.songs).toBe(0);
  });
  it('a playlist that is not in the list is gone, not an error', async () => {
    const v = must(await fake('normal').library('playlist', 'No_Such_List', '', 'all', null));
    expect(v).toMatchObject({ empty: 'gone', title: 'No_Such_List', subtitle: [], rows: [], also: null });
  });
  it('refuses a request the engine would refuse', async () => {
    const f = fake('normal');
    expect(await f.library('shelf' as never, null, '', 'all', null)).toMatchObject({ ok: false, kind: 'refused' });
    expect(await f.library('playlist', null, '', 'all', null)).toMatchObject({ ok: false, kind: 'refused' });
    expect(await f.library('all', null, '', 'best' as never, null)).toMatchObject({ ok: false, kind: 'refused' });
  });
  it('All tracks and Not in a playlist keep their rows and words, with the new row fields', async () => {
    const f = fake('normal');
    const all = must(await f.library('all', null, '', 'all', null));
    expect(all).toMatchObject({ view: 'all', key: null, folder: null, folder_kind: null, also: null, read_at: null, enabled: null });
    expect(all.rows.every((r) => r.wait === null && r.position === null && r.file_state !== 'no_file')).toBe(true);
    const unlisted = must(await f.library('unlisted', null, '', 'all', null));
    expect(unlisted).toMatchObject({ title: 'Not in a playlist', subtitle: ['2 tracks', 'in no playlist'] });
    expect(unlisted.rows.map((r) => r.place)).toEqual(['Old_Sets', 'Old_Sets']);
  });
});
