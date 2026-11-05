// YouTube Music's Liked music in the fake backend: the same answers as the engine (tests/test_hub_api_liked_music.py).
import { describe, expect, it } from 'vitest';
import { createFakeBridge } from './bridge';
import type { HubEvent } from '../events';
import type { Fail, Playlists, SetupStatus } from '../types';
import { LIKED_LINK } from './liked';

const OFF = 'Reading your Liked music is off. Turn it on in Settings.';
const until = (evs: HubEvent[], jobId: number, ms = 3000) => new Promise<HubEvent>((resolve, reject) => {
  const t0 = Date.now();
  const tick = () => {
    const hit = evs.find((e) => e.type === 'JobFinished' && e.job_id === jobId);
    if (hit) return resolve(hit);
    if (Date.now() - t0 > ms) return reject(new Error('timeout'));
    setTimeout(tick, 5);
  };
  tick();
});
function make(scenario: string) {
  const evs: HubEvent[] = [];
  const f = createFakeBridge(scenario, { speed: 50, emit: (e) => evs.push(e) });
  const run = async (start: Promise<unknown>) => {
    const s = (await start) as { ok: boolean; job_id?: number };
    if (!s.ok) return s as unknown as Fail;
    return until(evs, s.job_id!);
  };
  const status = async () => { const r = await f.setup_status(); if (!r.ok) throw new Error(); return r as SetupStatus & { ok: true }; };
  const page = async () => { const r = await f.playlists(); if (!r.ok) throw new Error(); return r as Playlists & { ok: true }; };
  return { f, run, status, page };
}

describe('fake Liked music', () => {
  it('setup_status says the choice, whether it can be turned on and whether it is listed', async () => {
    expect((await make('normal').status()).youtube_music).toEqual({ liked_music: false, can_turn_on: false, listed: false });
    expect((await make('settings:liked-off').status()).youtube_music).toEqual({ liked_music: false, can_turn_on: true, listed: false });
    expect((await make('settings:liked-on').status()).youtube_music).toEqual({ liked_music: true, can_turn_on: true, listed: false });
    expect((await make('settings:liked-no-login').status()).youtube_music).toEqual({ liked_music: false, can_turn_on: false, listed: false });
    expect((await make('playlists:liked-listed-off').status()).youtube_music).toEqual({ liked_music: false, can_turn_on: true, listed: true });
  });

  it('set_read_liked_music is refused without a YouTube login and saved with one', async () => {
    const without = make('settings:liked-no-login');
    expect(await without.run(without.f.set_read_liked_music(true))).toMatchObject({ kind: 'set_read_liked_music', ok: false, problem: 'not_set_up' });
    expect((await without.status()).youtube_music.liked_music).toBe(false);
    const withLogin = make('settings:liked-off');
    expect(await withLogin.run(withLogin.f.set_read_liked_music(true))).toMatchObject({ ok: true });
    expect((await withLogin.status()).youtube_music.liked_music).toBe(true);
    expect(await withLogin.run(withLogin.f.set_read_liked_music(false))).toMatchObject({ ok: true });
    expect((await withLogin.status()).youtube_music.liked_music).toBe(false);
    expect(await withLogin.f.set_read_liked_music('yes' as unknown as boolean)).toMatchObject({ ok: false, kind: 'refused' });
  });

  it('forgetting the YouTube login turns the choice off for good', async () => {
    const m = make('settings:liked-on');
    expect(await m.run(m.f.setup_forget_account('youtube'))).toMatchObject({ ok: true });
    expect((await m.status()).youtube_music).toMatchObject({ liked_music: false, can_turn_on: false });
  });

  it('add_playlist answers setting_off for a pasted Liked music link while it is off, and reads it while it is on', async () => {
    for (const scenario of ['settings:liked-off', 'settings:liked-no-login']) {
      expect(await make(scenario).f.add_playlist(LIKED_LINK)).toEqual({ ok: false, kind: 'setting_off',
        setting: 'read_liked_music', service: 'youtube_music', message: OFF });
    }
    const on = await make('settings:liked-on').f.add_playlist('https://www.youtube.com/watch?v=EXAMPLEid01&list=LM');
    expect(on).toMatchObject({ ok: true, playlist_id: 'youtube_music:LM', service: 'youtube_music', link: LIKED_LINK,
      readable: true, suggested_folder: 'Liked_music', info: { name: 'Liked music', yours: true } });
    // an ordinary YouTube Music playlist is untouched by the choice
    expect(await make('settings:liked-off').f.add_playlist('https://music.youtube.com/playlist?list=PLEXAMPLE0001'))
      .toMatchObject({ ok: true, service: 'youtube_music' });
  });

  it('add_liked_music appends one line, then says exists; it refuses while the choice is off', async () => {
    const off = make('settings:liked-off');
    expect(await off.run(off.f.add_liked_music())).toMatchObject({ ok: false, problem: 'setting_off', message: OFF });
    const m = make('settings:liked-on');
    const before = (await m.page()).rows.length;
    expect(await m.run(m.f.add_liked_music())).toMatchObject({ ok: true, result: { folder: 'Liked_music' } });
    const after = await m.page();
    expect(after.rows).toHaveLength(before + 1);
    expect(after.rows.at(-1)).toMatchObject({ folder: 'Liked_music', link: LIKED_LINK, playlist_id: 'youtube_music:LM',
      enabled: true, needs_setting: null });
    expect((await m.status()).youtube_music.listed).toBe(true);
    expect(await m.run(m.f.add_liked_music())).toMatchObject({ ok: false, problem: 'exists' });
    expect((await m.page()).rows).toHaveLength(before + 1);
  });

  it('a listed Liked music row says which choice it needs while the choice is off', async () => {
    const m = make('playlists:liked-listed-off');
    const rows = (await m.page()).rows;
    expect(rows.map((r) => r.needs_setting)).toEqual([...rows.slice(0, -1).map(() => null), 'read_liked_music']);
    expect(await m.run(m.f.set_read_liked_music(true))).toMatchObject({ ok: true });
    expect((await m.page()).rows.every((r) => r.needs_setting === null)).toBe(true);
  });
});
