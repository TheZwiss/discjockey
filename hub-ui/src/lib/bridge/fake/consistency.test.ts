import { afterEach, describe, expect, it, vi } from 'vitest';
import { createFakeBridge, pageScenarios } from './bridge';
import type { Fail } from '../types';
import { makeState } from './data';
import { downloads } from './downloads';
import { at } from './logins';
import { cards } from './limits';

const noop = () => {};
const val = <T>(r: T | Fail): T => { if ((r as Fail).ok === false) throw new Error('refused'); return r as T; };
const clockAt = (h: number, m = 5) => { const d = new Date(); d.setHours(h, m, 0, 0); return d; };

describe('fake clock', () => {
  afterEach(() => vi.useRealTimers());

  // the fake's own day, at every time of day: a sign dated "today" is in the past, so YouTube is paused all day
  it.each([0, 1, 8, 11, 12, 23])('the settings:paused scenario pauses YouTube at %i:05', (h) => {
    const now = clockAt(h);
    const s = makeState('normal', now);
    pageScenarios()['settings:paused'](s);
    expect(downloads(s).youtube.state).toBe('paused');
    expect(cards(s).find((c) => c.service === 'youtube')?.paused).toBe(true);
    for (const hour of [9, 10, 11]) {
      const t = new Date(at(s, hour)).getTime();
      expect(t).toBeLessThanOrEqual(now.getTime());
      expect(new Date(at(s, hour)).toDateString()).toBe(now.toDateString());
    }
    // earlier hours stay earlier
    expect(at(s, 9) <= at(s, 10) && at(s, 10) <= at(s, 11)).toBe(true);
  });

  it('no sample time lies after the clock, however early in the day', () => {
    for (const h of [0, 3, 9, 20]) {
      const now = clockAt(h, 30);
      const s = makeState('normal', now);
      const stamps = [s.qobuz.last_download, ...s.runs.map((r) => r.started)].filter((x): x is string => !!x);
      for (const x of stamps) expect(new Date(x).getTime()).toBeLessThanOrEqual(now.getTime());
    }
  });
});

describe('fake counts', () => {
  it('give every playlist one song count on the Playlists page, in the Library sidebar and in its Library view', async () => {
    const f = createFakeBridge('normal', { speed: 100, emit: noop });
    const rows = val(await f.playlists()).rows;
    const side = val(await f.sidebar()).playlists;
    expect(rows.length).toBeGreaterThan(5);
    for (const r of rows) {
      const sidebar = side.find((p) => p.name === r.folder)!;
      expect(sidebar.songs, r.folder).toBe(sidebar.songs === null ? null : r.tracks);
      if (sidebar.songs !== null) {
        const lib = val(await f.library('playlist', r.folder, '', 'all', null));
        expect(lib.songs?.listed, r.folder).toBe(r.tracks);
      }
    }
    // the three the Playlists page used to count apart (downloaded files only)
    expect(rows.slice(0, 3).map((r) => r.tracks)).toEqual(side.slice(0, 3).map((p) => p.songs));
    expect(rows[0].tracks).toBeGreaterThan(11);
  });

  it('count the quality tally of a row over the same songs as its count', async () => {
    const f = createFakeBridge('normal', { speed: 100, emit: noop });
    for (const r of val(await f.playlists()).rows) {
      if (r.info?.readable === false) continue;
      const tallied = Object.values(r.quality).reduce((a, b) => a + b, 0);
      expect(tallied, r.folder).toBeLessThanOrEqual(r.tracks ?? 0);
    }
  });
});

describe('fake empty playlists scenario', () => {
  it('has no to-do items and no limits warning without playlists', async () => {
    const f = createFakeBridge('playlists:empty', { speed: 100, emit: noop });
    expect(val(await f.playlists()).rows).toEqual([]);
    const side = val(await f.sidebar());
    expect(side).toMatchObject({ todo: 0, limits_warning: false, playlists: [] });
    expect(side.not_in_playlist).toBe(side.all_tracks);
    expect(val(await f.dashboard()).folders).toEqual([]);
  });
});
