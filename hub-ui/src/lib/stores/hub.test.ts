import { afterEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { installBridge, _resetBridge } from '../bridge/client';
import { dispatch } from '../bridge/events';
import { EMPTY_HUB, hub, refreshHub, refreshOnNoLibrary, reduceHub, spotifyMissingIn, spotifyMissingKindIn } from './hub';

describe('reduceHub', () => {
  it('tracks the write job from JobStarted to JobFinished', () => {
    let s = reduceHub(EMPTY_HUB, { type: 'JobStarted', job_id: 3, kind: 'sync', track_id: null });
    expect(s.job).toMatchObject({ id: 3, kind: 'sync', running: true });
    s = reduceHub(s, { type: 'RunStarted', total: 1, actions: [{ kind: 'acquire', track_id: 't4', title: 'AEIOU', artist: 'Pegassi' }] });
    expect(s.job?.actions).toHaveLength(1);
    s = reduceHub(s, { type: 'JobFinished', job_id: 3, kind: 'sync', ok: true, problem: null, message: '', result: null });
    expect(s.job).toMatchObject({ id: 3, running: false });
  });
  it('a sign-in waits in its own slot and never blocks a write', () => {
    let s = reduceHub(EMPTY_HUB, { type: 'JobStarted', job_id: 5, kind: 'account_sign_in', track_id: null });
    expect(s.job).toBeNull();
    expect(s.sign_in).toMatchObject({ id: 5, running: true });
    s = reduceHub(s, { type: 'JobStarted', job_id: 6, kind: 'sync', track_id: null });
    expect(s.job).toMatchObject({ id: 6, running: true });
    s = reduceHub(s, { type: 'JobFinished', job_id: 5, kind: 'account_sign_in', ok: true, problem: null, message: '',
      result: null });
    expect(s.sign_in).toMatchObject({ id: 5, running: false });
    expect(s.job).toMatchObject({ id: 6, running: true });
  });
  it('a refresh is not a write job', () => {
    const s = reduceHub(EMPTY_HUB, { type: 'JobStarted', job_id: 1, kind: 'refresh', track_id: null });
    expect(s.job).toBeNull();
    expect(s.refresh_running).toBe(true);
    expect(reduceHub(s, { type: 'JobFinished', job_id: 1, kind: 'refresh', ok: true, problem: null, message: '',
      result: null }).refresh_running).toBe(false);
  });
  it('remembers that the read was stopped until the next read starts', () => {
    let s = reduceHub(EMPTY_HUB, { type: 'JobStarted', job_id: 1, kind: 'refresh', track_id: null });
    expect(s.read_stopped).toBe(false);
    s = reduceHub(s, { type: 'JobFinished', job_id: 1, kind: 'refresh', ok: false, problem: 'stopped',
      message: 'Stopped.', result: null });
    expect(s.refresh_running).toBe(false);
    expect(s.read_stopped).toBe(true);
    s = reduceHub(s, { type: 'JobStarted', job_id: 2, kind: 'refresh', track_id: null });
    expect(s.read_stopped).toBe(false);
    expect(reduceHub(s, { type: 'JobFinished', job_id: 2, kind: 'refresh', ok: true, problem: null, message: '',
      result: null }).read_stopped).toBe(false);
  });
  it('keeps which playlist is being read until the read ends', () => {
    let s = reduceHub(EMPTY_HUB, { type: 'JobStarted', job_id: 1, kind: 'refresh', track_id: null });
    s = reduceHub(s, { type: 'ReadingPlaylist', index: 3, total: 7, folder: 'Powertrance' });
    expect(s.read_progress).toEqual({ index: 3, total: 7, folder: 'Powertrance' });
    s = reduceHub(s, { type: 'JobFinished', job_id: 1, kind: 'refresh', ok: true, problem: null, message: '',
      result: null });
    expect(s.read_progress).toBeNull();
  });
  it("a sync's own read ends at RunStarted", () => {
    let s = reduceHub(EMPTY_HUB, { type: 'JobStarted', job_id: 2, kind: 'sync', track_id: null });
    s = reduceHub(s, { type: 'ReadingPlaylist', index: 1, total: 2, folder: 'Hard_Bounce' });
    expect(s.read_progress?.index).toBe(1);
    expect(reduceHub(s, { type: 'RunStarted', total: 0, actions: [] }).read_progress).toBeNull();
  });
  it('follows the console', () => {
    expect(reduceHub(EMPTY_HUB, { type: 'ConsoleBusy', running: true }).console_running).toBe(true);
  });
  it('AppUpdate replaces the update answer', () => {
    const url = 'https://github.com/TheZwiss/discjockey/releases/tag/v1.1.0';
    const s = reduceHub(EMPTY_HUB, { type: 'AppUpdate', state: 'available', current: '1.0.0', latest: '1.1.0', url });
    expect(s.app_update).toEqual({ state: 'available', current: '1.0.0', latest: '1.1.0', url });
    expect(reduceHub(s, { type: 'AppUpdate', state: 'up_to_date', current: '1.1.0', latest: null, url: null })
      .app_update?.state).toBe('up_to_date');
  });
});

describe('spotifyMissingIn', () => {
  const ok = { read_at: '2026-10-21T10:00:00Z', minutes_ago: 2, problem: null, message: '', stale: false, reading: false,
    offline: false, auto_read: false };
  it('is false while nothing is known yet and while Spotify is connected', () => {
    expect(spotifyMissingIn(null, null)).toBe(false);
    expect(spotifyMissingIn({ spotify_login: true } as never, ok as never)).toBe(false);
  });
  it('is true when the login is missing, not set up or expired', () => {
    expect(spotifyMissingIn({ spotify_login: false } as never, ok as never)).toBe(true);
    expect(spotifyMissingIn(null, { ...ok, problem: 'not_set_up' } as never)).toBe(true);
    expect(spotifyMissingIn(null, { ...ok, problem: 'login_expired' } as never)).toBe(true);
  });
  it('is false for problems a read can fix (offline)', () => {
    expect(spotifyMissingIn(null, { ...ok, problem: 'offline', offline: true } as never)).toBe(false);
  });
});

describe('spotifyMissingKindIn', () => {
  const ok = { read_at: null, minutes_ago: null, problem: null, message: '', stale: false, reading: false,
    offline: false, auto_read: false };
  it('names the expired login, else "not set up" for a missing login, else nothing', () => {
    expect(spotifyMissingKindIn(null, { ...ok, problem: 'login_expired' } as never)).toBe('login_expired');
    expect(spotifyMissingKindIn({ spotify_login: false } as never, ok as never)).toBe('not_set_up');
    expect(spotifyMissingKindIn(null, { ...ok, problem: 'not_set_up' } as never)).toBe('not_set_up');
    expect(spotifyMissingKindIn({ spotify_login: true } as never, { ...ok, problem: 'offline' } as never)).toBeNull();
  });
});

describe('a no_library answer from any page', () => {
  afterEach(() => { _resetBridge(); delete (globalThis as any).window; });
  const music = (state: string) => ({ ok: true, music: { state, path: '/Volumes/DJ', suggested: '/x' } });
  function bridge(setupState: () => string) {
    const calls = { setup: 0 };
    const w = new EventTarget() as any;
    (globalThis as any).window = w;
    installBridge({
      job_status: async () => ({ ok: true, job: null, refresh_running: false, console_running: false, spotify: null,
        sign_in: null }),
      setup_status: async () => { calls.setup += 1; return music(setupState()); },
      sidebar: async () => ({ ok: false, kind: 'no_library', message: 'Gone.' }),
      app_update: async () => ({ ok: true, state: 'unknown', current: '1.0.0', latest: null, url: null }),
      todo: async () => ({ ok: false, kind: 'no_library', message: 'Gone.' }),
    });
    return calls;
  }
  it('reads the setup state again, so the gate shows the missing screen', async () => {
    let state = 'ok';
    const calls = bridge(() => state);
    await refreshHub();
    expect(get(hub).setup?.music.state).toBe('ok');
    const { api } = await import('../bridge/client');
    state = 'missing';
    await api.todo('all', false);
    await vi.waitFor(() => expect(get(hub).setup?.music.state).toBe('missing'));
    const after = calls.setup;
    await api.todo('all', false);  // the gate knows now: no more reads
    await new Promise((r) => setTimeout(r, 20));
    expect(calls.setup).toBe(after);
  });
  it('does not loop on the sidebar call of its own refresh', async () => {
    const calls = bridge(() => 'ok');
    await refreshHub();  // the gate knows "ok"
    const before = calls.setup;
    refreshOnNoLibrary();
    await vi.waitFor(() => expect(calls.setup).toBe(before + 1));
    await new Promise((r) => setTimeout(r, 30));
    expect(calls.setup).toBe(before + 1);
  });
});

describe('an AppUpdate event that arrives while a refresh runs', () => {
  afterEach(() => { _resetBridge(); delete (globalThis as any).window; });
  it('is not overwritten by the older app_update() answer', async () => {
    (globalThis as any).window = new EventTarget();
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => { release = r; });
    installBridge({
      job_status: async () => ({ ok: true, job: null, refresh_running: false, console_running: false, spotify: null,
        sign_in: null }),
      setup_status: async () => ({ ok: true, music: { state: 'ok', path: '/Volumes/DJ', suggested: '/x' } }),
      sidebar: async () => ({ ok: false, kind: 'no_library', message: 'Gone.' }),
      app_update: async () => { await gate; return { ok: true, state: 'unknown', current: '1.0.0', latest: null, url: null }; },
    });
    const refresh = refreshHub();
    dispatch({ type: 'AppUpdate', state: 'available', current: '1.0.0', latest: '1.1.0',
      url: 'https://github.com/TheZwiss/Discjockey/releases/tag/v1.1.0' });
    release();
    await refresh;
    expect(get(hub).app_update?.state).toBe('available');
    await refreshHub();  // nothing newer arrived during this one: its answer is taken again
    expect(get(hub).app_update?.state).toBe('unknown');
  });
});
