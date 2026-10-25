import { afterEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { installBridge, _resetBridge } from '../bridge/client';
import { dispatch } from '../bridge/events';
import { EMPTY_HUB, hub, refreshHub, refreshOnNoLibrary, readBlockIn, readNeedsSetupIn, reduceHub } from './hub';
import type { SetupStatus, SpotifyStatus } from '../bridge/types';

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
  it('a background scan is no activity: it keeps the job slot, the reading progress and the reading line', () => {
    let s = reduceHub(EMPTY_HUB, { type: 'JobStarted', job_id: 2, kind: 'sync', track_id: null });
    s = reduceHub(s, { type: 'ReadingPlaylist', index: 1, total: 2, folder: 'Hard_Bounce' });
    s = reduceHub(s, { type: 'JobStarted', job_id: 3, kind: 'scan', track_id: null });
    expect(s.job).toMatchObject({ id: 2, kind: 'sync', running: true });
    s = reduceHub(s, { type: 'JobFinished', job_id: 3, kind: 'scan', ok: true, problem: null, message: '', result: null });
    expect(s.job).toMatchObject({ id: 2, running: true });
    expect(s.read_progress).toEqual({ index: 1, total: 2, folder: 'Hard_Bounce' });
  });
  it('a scan alone leaves the job slot empty', () => {
    let s = reduceHub(EMPTY_HUB, { type: 'JobStarted', job_id: 3, kind: 'scan', track_id: null });
    s = reduceHub(s, { type: 'JobFinished', job_id: 3, kind: 'scan', ok: true, problem: null, message: '', result: null });
    expect(s.job).toBeNull();
  });
  it("a sync's finish ends the reading line; another write job's finish does not", () => {
    let s = reduceHub(EMPTY_HUB, { type: 'JobStarted', job_id: 2, kind: 'sync', track_id: null });
    s = reduceHub(s, { type: 'ReadingPlaylist', index: 1, total: 2, folder: 'Hard_Bounce' });
    expect(reduceHub(s, { type: 'JobFinished', job_id: 2, kind: 'sync', ok: false, problem: 'crashed', message: '',
      result: null }).read_progress).toBeNull();
    let t = reduceHub(EMPTY_HUB, { type: 'JobStarted', job_id: 4, kind: 'refresh', track_id: null });
    t = reduceHub(t, { type: 'ReadingPlaylist', index: 1, total: 2, folder: 'Hard_Bounce' });
    t = reduceHub(t, { type: 'JobStarted', job_id: 5, kind: 'download_track', track_id: 't1' });
    expect(reduceHub(t, { type: 'JobFinished', job_id: 5, kind: 'download_track', ok: true, problem: null, message: '',
      result: null }).read_progress).not.toBeNull();
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

describe('readBlockIn: the read is blocked only by a service playlists.txt uses (plan stage 3, D1)', () => {
  const both = (spotify: boolean, qobuz: boolean): SpotifyStatus['services'] => [
    { service: 'spotify', name: 'Spotify', connected: spotify }, { service: 'qobuz', name: 'Qobuz', connected: qobuz }];
  const ok: SpotifyStatus = { read_at: '2026-10-21T10:00:00Z', minutes_ago: 2, problem: null, problem_service: null,
    message: '', services: both(true, true), stale: false, reading: false, offline: false, auto_read: false };
  it('is null while nothing is known yet and while every used service is connected', () => {
    expect(readBlockIn(null)).toBeNull();
    expect(readBlockIn(ok)).toBeNull();
  });
  it('names the first used service that is not connected', () => {
    expect(readBlockIn({ ...ok, services: both(true, false) })).toEqual({ kind: 'not_set_up', service: 'qobuz' });
    expect(readBlockIn({ ...ok, services: both(false, false) })).toEqual({ kind: 'not_set_up', service: 'spotify' });
  });
  it('ignores a service playlists.txt does not use (a Spotify left out with only Qobuz lines)', () => {
    expect(readBlockIn({ ...ok, services: [{ service: 'qobuz', name: 'Qobuz', connected: true }] })).toBeNull();
    expect(readBlockIn({ ...ok, services: [] })).toBeNull();
  });
  it("takes the read's expired login, with its service (Spotify when the bridge doesn't say)", () => {
    expect(readBlockIn({ ...ok, problem: 'login_expired', problem_service: 'spotify' }))
      .toEqual({ kind: 'login_expired', service: 'spotify' });
    expect(readBlockIn({ ...ok, problem: 'login_expired' })).toEqual({ kind: 'login_expired', service: 'spotify' });
  });
  it("takes a read's missing login only with its service (without one it is a missing playlists.txt)", () => {
    expect(readBlockIn({ ...ok, services: both(true, false), problem: 'not_set_up', problem_service: 'qobuz' }))
      .toEqual({ kind: 'not_set_up', service: 'qobuz' });
    expect(readBlockIn({ ...ok, problem: 'not_set_up' })).toBeNull();
  });
  it("drops a read's stored missing login once that service is connected (the user logged in since)", () => {
    expect(readBlockIn({ ...ok, problem: 'not_set_up', problem_service: 'qobuz' })).toBeNull();
    // the other service being down still blocks, and names itself
    expect(readBlockIn({ ...ok, services: both(false, true), problem: 'not_set_up', problem_service: 'qobuz' }))
      .toEqual({ kind: 'not_set_up', service: 'spotify' });
  });
  it('keeps a stored missing login when the poll does not list the service at all', () => {
    expect(readBlockIn({ ...ok, services: [], problem: 'not_set_up', problem_service: 'qobuz' }))
      .toEqual({ kind: 'not_set_up', service: 'qobuz' });
  });
  it('keeps a stored expired login even when the service is connected', () => {
    expect(readBlockIn({ ...ok, problem: 'login_expired', problem_service: 'qobuz' }))
      .toEqual({ kind: 'login_expired', service: 'qobuz' });
  });
  it('is null for problems a read can fix (offline)', () => {
    expect(readBlockIn({ ...ok, problem: 'offline', offline: true })).toBeNull();
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

describe('a scan job in job_status', () => {
  afterEach(() => { _resetBridge(); delete (globalThis as any).window; });
  const snap = (kind: string) => ({ id: 9, kind, track_id: null, started: '2026-10-24T10:00:00', running: true,
    stopping: false, last: {}, results: [], finished: null, actions: [] });
  function bridge(job: unknown) {
    (globalThis as any).window = new EventTarget();
    installBridge({
      job_status: async () => ({ ok: true, job, refresh_running: false, console_running: false, spotify: null,
        sign_in: null }),
      setup_status: async () => ({ ok: true, music: { state: 'ok', path: '/Volumes/DJ', suggested: '/x' } }),
      sidebar: async () => ({ ok: false, kind: 'no_library', message: 'Gone.' }),
      app_update: async () => ({ ok: true, state: 'unknown', current: '1.0.0', latest: null, url: null }),
    });
  }
  it('stays out of the job slot, like its events', async () => {
    bridge(snap('scan'));
    await refreshHub();
    expect(get(hub).job).toBeNull();
  });
  it('does not replace a sync that is running', async () => {
    bridge(snap('sync'));
    await refreshHub();
    expect(get(hub).job).toMatchObject({ kind: 'sync', running: true });
  });
});

describe('readNeedsSetupIn: a not_set_up without a service is a missing playlists.txt (first-run Dashboard, §5a)', () => {
  const ok: SpotifyStatus = { read_at: null, minutes_ago: null, problem: 'not_set_up', problem_service: null,
    message: '', services: [], stale: false, reading: false, offline: false, auto_read: false };
  const setup = (playlists: boolean) => ({ playlists }) as unknown as SetupStatus;
  it('is true for the missing playlists.txt, which is no login block', () => {
    expect(readNeedsSetupIn(ok, null)).toBe(true);
    expect(readNeedsSetupIn(ok, setup(false))).toBe(true);
    expect(readBlockIn(ok)).toBeNull();
  });
  it('is false once setup says playlists.txt exists (the stored problem is stale; a read must be able to clear it)', () => {
    expect(readNeedsSetupIn(ok, setup(true))).toBe(false);
  });
  it('is false while nothing is known, with no problem, and for a login problem (that has its own block)', () => {
    expect(readNeedsSetupIn(null, null)).toBe(false);
    expect(readNeedsSetupIn({ ...ok, problem: null }, null)).toBe(false);
    expect(readNeedsSetupIn({ ...ok, problem_service: 'qobuz' }, null)).toBe(false);
    expect(readNeedsSetupIn({ ...ok, services: [{ service: 'qobuz', name: 'Qobuz', connected: false }] }, null)).toBe(false);
  });
});
