import { describe, expect, it } from 'vitest';
import type { AddedPlaylist, Playlists } from '$lib/bridge/types';
import {
  addRow, draftFrom, dropIndex, infoLine, isDirty, lines, loadedFrom, moveBy, priorities,
  remove, rename, reorder, shiftFor, toggle, undo, panelFor, previewRequests, overlapCards, foldTrack, folderBars, folderChanges, changeText, moveRoutes, statusLine,
  onOffText, losslessText,
  NO_PREVIEW, type PreviewAnswer, type PreviewState,
} from './changeModel';

const info = (name: string, n: number) => ({ name, owner_name: 'DJ One', yours: true, collaborative: false,
  readable: true, image_url: null, track_count: n, hint: 'Make your own copy.' });
// the contract example (playlists())
const EXAMPLE: Playlists = {
  version: '481d45b7d451c816dd949d1a86b559bf9083ef5d02f69831f870dafbccffc36b', problem: null, empty: null, tidy: { waiting: 0 },
  rows: [
    { index: 0, folder: 'Hard_Bounce', link: 'https://open.spotify.com/playlist/0DiscjockeyExampleList',
      playlist_id: '0DiscjockeyExampleList', service: 'spotify', service_name: 'Spotify', enabled: true, info: info('Name of 0Dis', 4), tracks: 4,
      quality: { lossless: 1, good_lossy: 0, weak: 1, fake: 0, missing: 2 } },
    { index: 1, folder: 'Powertrance', link: 'https://open.spotify.com/playlist/3DiscjockeyExampleList',
      playlist_id: '3DiscjockeyExampleList', service: 'spotify', service_name: 'Spotify', enabled: true, info: info('Name of 3Dis', 2), tracks: 2,
      quality: { lossless: 0, good_lossy: 0, weak: 1, fake: 0, missing: 1 } },
  ],
  overlaps: [{ track_id: 't2', artist: 'Armin Hermann', title: 'Get Naughty', cover_url: 'https://i.scdn.co/image/t2',
    downloaded: true, quality: 'weak', quality_label: '16.0 kHz', folders: ['Hard_Bounce', 'Powertrance'],
    lands_in: 'Hard_Bounce' }],
};
const loaded = loadedFrom(EXAMPLE);
const ADDED: AddedPlaylist = { playlist_id: '37i9dQZF1DXcBWIGoYBM5M',
  service: 'spotify', service_name: 'Spotify',
  link: 'https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M', info: info('Name of 37i9', 0), tracks: 0,
  readable: true, suggested_folder: 'Name_of_37i9', hint: null };

describe('lines()', () => {
  it('turns the contract example into lines, top first', () => {
    expect(lines(draftFrom(loaded))).toEqual([
      { folder: 'Hard_Bounce', link: 'https://open.spotify.com/playlist/0DiscjockeyExampleList', enabled: true },
      { folder: 'Powertrance', link: 'https://open.spotify.com/playlist/3DiscjockeyExampleList', enabled: true },
    ]);
  });
});

describe('dirty state', () => {
  const d = draftFrom(loaded);
  const [hb, pt] = d;
  it('is clean right after loading', () => expect(isDirty(d, loaded)).toBe(false));
  it('is dirty after reorder, rename, toggle, add and remove', () => {
    expect(isDirty(reorder(d, 1, 0), loaded)).toBe(true);
    expect(isDirty(rename(d, pt.key, 'Power_Trance'), loaded)).toBe(true);
    expect(isDirty(toggle(d, hb.key), loaded)).toBe(true);
    expect(isDirty(addRow(d, ADDED, 'Name_of_37i9'), loaded)).toBe(true);
    expect(isDirty(remove(d, hb.key), loaded)).toBe(true);
  });
  it('is clean after undo', () => {
    const changed = toggle(rename(reorder(d, 1, 0), pt.key, 'X'), hb.key);
    expect(isDirty(undo(loaded), loaded)).toBe(false);
    expect(isDirty(changed, loaded)).toBe(true);
  });
  it('is clean after moving a row back, or toggling twice, or renaming back', () => {
    expect(isDirty(reorder(reorder(d, 1, 0), 0, 1), loaded)).toBe(false);
    expect(isDirty(toggle(toggle(d, hb.key), hb.key), loaded)).toBe(false);
    expect(isDirty(rename(rename(d, hb.key, 'X'), hb.key, 'Hard_Bounce'), loaded)).toBe(false);
    expect(isDirty(moveBy(moveBy(d, hb.key, 1), hb.key, -1), loaded)).toBe(false);
  });
  it('without a loaded file nothing is dirty', () => expect(isDirty(d, null)).toBe(false));
});

describe('reorder', () => {
  const d = draftFrom(loadedFrom({ version: 'v', rows: ['A', 'B', 'C', 'D'].map((f, i) => ({ ...EXAMPLE.rows[0],
    index: i, folder: f, link: `https://open.spotify.com/playlist/${f}id` })) }));
  const names = (x: typeof d) => x.map((r) => r.folder).join('');
  it('moves by from and to index', () => {
    expect(names(reorder(d, 1, 0))).toBe('BACD');
    expect(names(reorder(d, 0, 3))).toBe('BCDA');
    expect(names(reorder(d, 3, 1))).toBe('ADBC');
    expect(names(reorder(d, 2, 2))).toBe('ABCD');
    expect(names(reorder(d, 0, 99))).toBe('BCDA');
  });
  it('⌥↑ / ⌥↓ move one step and stop at the ends', () => {
    expect(names(moveBy(d, d[2].key, -1))).toBe('ACBD');
    expect(names(moveBy(d, d[0].key, -1))).toBe('ABCD');
    expect(names(moveBy(d, d[3].key, 1))).toBe('ABCD');
  });
  it('reorders by pointer positions: from index and the dragged centre give the drop index', () => {
    const mids = [20, 60, 100, 140];               // row centres, 40 px rows
    expect(dropIndex(mids, 1, 15)).toBe(0);        // B dragged above A
    expect(dropIndex(mids, 1, 60)).toBe(1);        // not moved
    expect(dropIndex(mids, 0, 105)).toBe(2);       // A dragged past C
    expect(dropIndex(mids, 0, 500)).toBe(3);
    expect(names(reorder(d, 1, dropIndex(mids, 1, 15)))).toBe('BACD');
  });
  it('other rows make room while dragging', () => {
    expect([0, 1, 2, 3].map((i) => shiftFor(i, 0, 2))).toEqual([0, -1, -1, 0]);
    expect([0, 1, 2, 3].map((i) => shiftFor(i, 3, 1))).toEqual([0, 1, 1, 0]);
  });
});

describe('rename', () => {
  const d = draftFrom(loaded);
  it('trims the name', () => expect(rename(d, d[1].key, '  PT  ')[1].folder).toBe('PT'));
});

describe('add and remove', () => {
  const d = draftFrom(loaded);
  it('adds at the bottom as a new, switched-on row', () => {
    const a = addRow(d, ADDED, 'Name_of_37i9');
    expect(a).toHaveLength(3);
    expect(a[2]).toMatchObject({ folder: 'Name_of_37i9', link: ADDED.link, enabled: true, isNew: true });
    expect(lines(a)[2]).toEqual({ folder: 'Name_of_37i9', link: ADDED.link, enabled: true });
  });
  it('removes a row', () => expect(lines(remove(d, d[0].key)).map((l) => l.folder)).toEqual(['Powertrance']));
});

describe('row texts', () => {
  const d = draftFrom(loaded);
  it('numbers switched-on rows, "–" for switched-off ones', () => {
    expect(priorities(toggle(addRow(d, ADDED, 'N'), d[0].key))).toEqual(['–', '1', '2']);
  });
  it('info line: name and owner, not read yet, unreadable, switched off', () => {
    expect(infoLine(d[0])).toEqual({ text: '"Name of 0Dis" · yours', tone: 'muted' });
    expect(infoLine({ ...d[0], info: null })).toEqual({ text: 'not read yet', tone: 'muted' });
    expect(infoLine({ ...d[0], info: { ...info('x', 0), yours: false, readable: false } }).tone).toBe('bad');
    expect(infoLine({ ...d[0], info: { ...info('x', 0), yours: false, collaborative: true } }).text).toBe('"x" · collaborative');
    expect(infoLine({ ...d[0], enabled: false }).text).toBe('switched off · files stay');
  });
  it('header status line and list summary count only what is switched on', () => {
    const off = toggle(d, d[1].key);
    expect(statusLine(d)).toBe('6 tracks in your playlists');
    expect(statusLine(off)).toBe('4 tracks in your playlists');
    expect(statusLine(addRow(d, ADDED, 'N'))).toBe('6 tracks in your playlists');
    expect(onOffText(d)).toBe('2 on');
    expect(onOffText(off)).toBe('1 on · 1 off');
  });
  it('lossless text beside the quality bar, none before anything is downloaded', () => {
    expect(losslessText(d[0].quality)).toBe('1 of 4 lossless');
    expect(losslessText({ lossless: 0, good_lossy: 0, weak: 0, fake: 0, missing: 0 })).toBeNull();
  });
});

// ---- part B: the right panel ----
// the contract example (preview_playlist_change), with the nit as the backend sends it
const MOVES: PreviewAnswer = {
  ok: true, kind: 'moves', headline: '1 track change folder',
  folders: [{ folder: 'Powertrance', before: 1, after: 2 }, { folder: 'Hard_Bounce', before: 4, after: 3 }],
  tidy: null, renames: [], reroutes: [], new_downloads: 0, days: 0, stopped: 0, unknown: [],
  checklist: ['No downloads, no Qobuz quota used', 'Nothing is deleted'], problem: null,
};
const ready = (a: PreviewAnswer): PreviewState => ({ loading: false, answer: a });
const as = (kind: 'add' | 'rename' | 'switch_off' | 'unknown' | 'none', extra = {}): PreviewAnswer =>
  ({ ...MOVES, kind, folders: [], headline: `${kind} headline`, ...extra } as PreviewAnswer);

describe('panelFor', () => {
  const ov = EXAMPLE.overlaps;
  it('shows the overlaps when nothing is unsaved, whatever the preview says', () => {
    for (const p of [NO_PREVIEW, ready(MOVES), ready({ ...MOVES, problem: 'bad' } as PreviewAnswer)]) {
      const r = panelFor(false, p, ov);
      expect(r).toMatchObject({ view: 'overlaps', saveAllowed: true, dim: false, preview: null });
      expect(r.overlaps).toBe(ov);
    }
  });
  it('is loading while the first answer is on its way', () => {
    expect(panelFor(true, NO_PREVIEW, ov)).toMatchObject({ view: 'loading', saveAllowed: true });
    expect(panelFor(true, { loading: true, answer: null }, ov).view).toBe('loading');
  });
  it('keeps the previous answer dimmed while a newer one loads', () => {
    expect(panelFor(true, { loading: true, answer: MOVES }, ov)).toMatchObject({ view: 'moves', dim: true });
  });
  it('moves: the headline exactly as the backend sends it', () => {
    const r = panelFor(true, ready(MOVES), ov);
    expect(r).toMatchObject({ view: 'moves', dim: false, saveAllowed: true });
    expect(r.preview?.headline).toBe('1 track change folder');
    expect(r.preview).not.toHaveProperty('ok');
  });
  it.each(['add', 'rename', 'switch_off', 'unknown', 'none'] as const)('%s → its own view', (kind) => {
    const r = panelFor(true, ready(as(kind, kind === 'unknown' ? { unknown: ['line 3: not a playlist link'] } : {})), ov);
    expect(r).toMatchObject({ view: kind, saveAllowed: true });
  });
  it('problem → Save disabled, also while a newer answer loads', () => {
    const bad = { ...as('add'), problem: 'Two playlists use the folder Hard_Bounce.' } as PreviewAnswer;
    expect(panelFor(true, ready(bad), ov)).toMatchObject({ view: 'problem', saveAllowed: false });
    expect(panelFor(true, { loading: true, answer: bad }, ov)).toMatchObject({ view: 'problem', dim: true, saveAllowed: false });
  });
  it('sync_running → the "after the sync" view, Save not blocked by the panel', () => {
    const a: PreviewAnswer = { ok: false, kind: 'sync_running', message: 'Not while a sync runs.' };
    expect(panelFor(true, ready(a), ov)).toMatchObject({ view: 'sync_running', saveAllowed: true });
  });
  it('other failures → failed with the message', () => {
    const a: PreviewAnswer = { ok: false, kind: 'offline', message: 'No internet connection.' };
    expect(panelFor(true, ready(a), ov)).toMatchObject({ view: 'failed', fail: a, saveAllowed: true });
  });
});

describe('preview requests', () => {
  it('drops answers that arrive out of order', async () => {
    const req = previewRequests();
    let shown: string | null = null;
    const ask = async (id: number, answer: string, ms: number) => {
      await new Promise((r) => setTimeout(r, ms));
      if (req.isLatest(id)) shown = answer;
    };
    const slow = ask(req.next(), 'old', 30);
    const fast = ask(req.next(), 'new', 5);
    await Promise.all([slow, fast]);
    expect(shown).toBe('new');
  });
  it('cancel drops the answer in flight', () => {
    const req = previewRequests();
    const id = req.next();
    req.cancel();
    expect(req.isLatest(id)).toBe(false);
    expect(req.isLatest(req.next())).toBe(true);
  });
});

describe('panel texts', () => {
  it('one card per playlist that gives tracks to a higher one, in list order, with what stays', () => {
    const o = (id: string, folders: string[]) => ({ track_id: id, artist: 'A', title: id, cover_url: null,
      downloaded: false, quality: 'missing' as const, quality_label: null, folders, lands_in: folders[0] });
    const rows = [{ folder: 'H', tracks: 10 }, { folder: 'P', tracks: 63 }, { folder: 'D', tracks: 39 },
      { folder: 'B', tracks: null }];
    const cards = overlapCards([o('x', ['P', 'D']), o('y', ['H', 'D']), o('z', ['P', 'D']), o('w', ['H', 'P', 'B'])],
      rows);
    expect(cards.map((c) => [c.folder, c.total, c.keeps, c.lost.length])).toEqual([
      ['P', 63, 62, 1], ['D', 39, 36, 3], ['B', null, null, 1]]);
    expect(cards[1].goTo).toEqual([{ to: 'H', count: 1 }, { to: 'P', count: 2 }]);
    expect(cards[1].hint).toBe('1 in H · 2 in P');
    expect(cards[0].hint).toBe('lands in H');
    expect(cards[0].lost.map((t) => t.track_id)).toEqual(['w']);
    expect(overlapCards([], rows)).toEqual([]);
  });
  it('the move view: changed folders with their count after and the difference, on one scale', () => {
    const f = (folder: string, before: number, after: number) => ({ folder, before, after });
    expect(folderBars([f('S', 23, 50), f('H', 38, 38), f('P', 288, 284), f('B', 291, 271)])).toEqual({
      rows: [{ folder: 'S', after: 50, delta: 27 }, { folder: 'P', after: 284, delta: -4 },
        { folder: 'B', after: 271, delta: -20 }], max: 27 });
    expect(folderBars([f('H', 3, 3)])).toEqual({ rows: [], max: 0 });
  });
  it('the main list says what the change does to each playlist', () => {
    const p = { ...(MOVES as Extract<PreviewAnswer, { ok: true }>) };
    expect([...folderChanges(p)]).toEqual([['Powertrance', 1], ['Hard_Bounce', -1]]);
    expect(folderChanges(null).size).toBe(0);
    expect(changeText(27)).toBe('gets 27 more');
    expect(changeText(-20)).toBe('gives 20 away');
  });
  it('groups the tracks that land elsewhere later by route, biggest first', () => {
    const rr = (id: string, from: string, to: string) => ({ track_id: id, artist: 'A', title: id, cover_url: null,
      downloaded: false, quality: 'missing' as const, quality_label: null, from, to });
    const r = moveRoutes({ reroutes: [rr('a', 'H', 'P'), rr('b', 'H', 'S'), rr('c', 'B', 'S'), rr('d', 'H', 'S')] });
    expect(r.map((x) => [x.from, x.to, x.rows.map((t) => t.track_id)])).toEqual([
      ['H', 'S', ['b', 'd']], ['H', 'P', ['a']], ['B', 'S', ['c']]]);
    expect(r[0].rows[0].badge).toBeNull();
    expect(moveRoutes({ reroutes: [] })).toEqual([]);
  });
  it('a track row of a fold: the quality badge once downloaded, else "not downloaded yet"', () => {
    const t = { track_id: 't', artist: 'A', title: 'B', cover_url: null, downloaded: true, quality: 'weak' as const,
      quality_label: '16.0 kHz' };
    expect(foldTrack(t, '→ P')).toEqual({ track_id: 't', name: 'A – B', cover_url: null, note: '→ P',
      badge: { quality: 'weak', label: '16.0 kHz' } });
    expect(foldTrack({ ...t, downloaded: false, quality: 'missing', quality_label: null }).badge).toBeNull();
    expect(foldTrack({ ...t, downloaded: false, quality: 'missing', quality_label: null, never: true }, '→ P').note)
      .toBe('→ P · never download');
  });
});
