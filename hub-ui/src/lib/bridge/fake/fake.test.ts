import { describe, expect, it } from 'vitest';
import { createFakeBridge } from './bridge';
import { STREAMS } from './replay';
import { minutesByDownloads } from './minutes';
import { LIBRARY_METHODS } from '../contract';
import type { HubEvent } from '../events';

const until = (evs: HubEvent[], pred: (e: HubEvent) => boolean, ms = 3000) => new Promise<HubEvent>((resolve, reject) => {
  const t0 = Date.now();
  const tick = () => {
    const hit = evs.find(pred);
    if (hit) return resolve(hit);
    if (Date.now() - t0 > ms) return reject(new Error('timeout'));
    setTimeout(tick, 5);
  };
  tick();
});

describe('fake minutes table', () => {
  // the same numbers as tests/test_hub_views.py: the fake mimics views.minutes_by_downloads
  it('follows run_minutes: 70 s a download, rounded to 5 minutes, halves to even, at least 5', () => {
    const t = minutesByDownloads(200);
    expect(t).toHaveLength(201);
    expect([0, 1, 10, 45, 195].map((n) => t[n])).toEqual([0, 5, 10, 50, 230]);
  });
});

describe('fake backend', () => {
  it('library file names are "Artist - Title" without suffixes', async () => {
    const f = createFakeBridge('big');
    const lib = await f.library(null, '', 'all', 'artist');
    if (!lib.ok) throw new Error();
    expect(lib.rows.length).toBeGreaterThan(1000);
    for (const r of lib.rows) {
      expect(r.path).toMatch(/^Library\/[^/]+(\/not_lossless)?\/[^/]+ - [^/]+\.aiff$/);
      expect(r.path).not.toMatch(/\((v?\d+|new)\)|\s\d+\.aiff$/);
    }
  });
  it('"never download" moves a planned download out of the plan and back, like the backend', async () => {
    const evs: HubEvent[] = [];
    const f = createFakeBridge('normal', { speed: 50, emit: (e) => evs.push(e) });
    const before = await f.sync_preview();
    if (!before.ok) throw new Error();
    const a = before.groups[0].actions[0];
    expect(before.groups.flatMap((g) => g.actions).map((x) => x.run).sort((x, y) => x! - y!))
      .toEqual(before.groups.flatMap((g) => g.actions).map((_, i) => i));
    const start = await f.never_download(a.track_id, true);
    if (!start.ok) throw new Error();
    await until(evs, (e) => e.type === 'JobFinished' && e.job_id === start.job_id);
    const after = await f.sync_preview();
    if (!after.ok) throw new Error();
    expect(after.never.map((x) => x.track_id)).toEqual([a.track_id]);
    expect(after.groups.flatMap((g) => g.actions).some((x) => x.track_id === a.track_id)).toBe(false);
    expect(after.estimate?.qobuz_needed).toBe((before.estimate?.qobuz_needed ?? 0) - 1);
    expect(await f.never_download('not-in-plan', true)).toMatchObject({ ok: false, kind: 'changed' });
  });
  it('the normal scenario has every state the pages need', async () => {
    const f = createFakeBridge('normal');
    const todo = await f.todo('all', false);
    if (!todo.ok) throw new Error();
    expect(todo.groups.map((g) => g.key)).toEqual(['rekordbox_check', 'upgrade_ready', 'not_found', 'weak',
      'good_lossy', 'fake', 'other']);
    expect(todo.hidden_count).toBe(1);
    const up = todo.groups.find((g) => g.key === 'upgrade_ready')!.items;
    expect(up.map((i) => i.detail).sort()).toEqual(["doesn't match: would be a new rekordbox entry", 'matches exactly, cues stay']);
    const side = await f.sidebar();
    if (!side.ok) throw new Error();
    expect(side.not_in_playlist).toBe(2);
    expect(side.folders.find((x) => x.folder === 'Old_Sets')?.in_playlists_txt).toBe(false);
    const pl = await f.playlists();
    if (!pl.ok) throw new Error();
    expect(pl.rows).toHaveLength(6);
    expect(pl.rows.filter((r) => !r.enabled)).toHaveLength(1);
    expect(pl.rows.filter((r) => r.info && !r.info.readable)).toHaveLength(1);
    const runs = await f.runs();
    if (!runs.ok) throw new Error();
    expect(runs.runs.map((r) => r.exit_code)).toEqual([1, 130, 0]);
    expect(runs.runs[1].stopped_after).toBe(61);
    const usage = await f.limits('qobuz');
    if (!usage.ok) throw new Error();
    expect(usage.usage!.days).toHaveLength(14);
  });
  it('a write changes what the reads return (hide leaves the to-do list)', async () => {
    const evs: HubEvent[] = [];
    const f = createFakeBridge('normal', { speed: 100, emit: (e) => evs.push(e) });
    const before = await f.todo('weak', false);
    if (!before.ok) throw new Error();
    const id = before.groups[0].items[0].track_id;
    const start = await f.hide(id, true);
    if (!start.ok) throw new Error();
    expect(await f.hide(id, true)).toMatchObject({ ok: false, kind: 'busy' });
    await until(evs, (e) => e.type === 'JobFinished' && e.job_id === start.job_id);
    const after = await f.todo('weak', false);
    if (!after.ok) throw new Error();
    expect(after.groups.flatMap((g) => g.items).some((i) => i.track_id === id)).toBe(false);
  });
  it('account_sign_in: waiting, then checking, then the login is saved with its profile', async () => {
    const evs: HubEvent[] = [];
    const f = createFakeBridge('normal', { speed: 50, emit: (e) => evs.push(e) });
    const found = await f.find_logins('youtube');
    if (!found.ok) throw new Error();
    expect(found.browsers.map((b) => b.id)).toEqual(['chrome', 'safari']);
    const start = await f.account_sign_in('youtube', 'chrome', 'Profile 2');
    if (!start.ok) throw new Error();
    const done = await until(evs, (e) => e.type === 'JobFinished' && e.job_id === start.job_id);
    expect(done).toMatchObject({ ok: true, result: { saved: true, profile: 'Profile 2' } });
    expect(evs.filter((e) => e.type === 'SignInPhase').map((e) => (e as { phase: string }).phase))
      .toEqual(['waiting', 'checking']);
    const st = await f.setup_status();
    if (!st.ok) throw new Error();
    expect(st.accounts.youtube).toMatchObject({ browser: 'chrome', profile: 'Profile 2', profile_name: 'Work' });
    const d = await f.downloads_view();
    if (!d.ok) throw new Error();
    expect(d.downloads.youtube.state).toBe('on');
  });
  it('setup_account records a failed check on the saved login, like the engine; another login stays as it was', async () => {
    const evs: HubEvent[] = [];
    const f = createFakeBridge('normal', { speed: 50, emit: (e) => evs.push(e) });
    const works = { ok: true, problem: null, kbps: 256, message: '✓' };
    f._ctx.accountResult('youtube', 'safari', null, works);  // a Safari login saved earlier
    const start = await f.setup_account('youtube', 'safari');  // "Use this login": Safari can't be read now
    if (!start.ok) throw new Error();
    const done = await until(evs, (e) => e.type === 'JobFinished' && e.job_id === start.job_id);
    expect(done).toMatchObject({ ok: true, result: { saved: false, check: { problem: 'cookies_unreadable' } } });
    const d = await f.downloads_view();
    if (!d.ok) throw new Error();
    expect(d.downloads.youtube).toMatchObject({ state: 'unreadable', browser: 'safari' });
    f._ctx.accountResult('soundcloud', 'chrome', 'Profile 2', works);
    const r = f._ctx.accountResult('soundcloud', 'chrome', null, { ...works, ok: false, problem: 'not_logged_in' });
    expect(r.saved).toBe(false);
    expect(f._ctx.s.accounts.soundcloud).toMatchObject({ profile: 'Profile 2', lastCheck: { ok: true } });
    expect(f._ctx.accountResult('soundcloud', 'firefox', null, { ...works, ok: false, problem: 'no_premium' }).saved)
      .toBe(true);  // SoundCloud without Go+ is saved all the same
  });
  it('account_sign_in: Cancel stops only the sign-in; Safari without access ends at once', async () => {
    const evs: HubEvent[] = [];
    const f = createFakeBridge('normal', { speed: 1, emit: (e) => evs.push(e) });
    const start = await f.account_sign_in('soundcloud', 'chrome');
    if (!start.ok) throw new Error();
    await until(evs, (e) => e.type === 'SignInPhase');
    expect(await f.stop_sign_in()).toMatchObject({ ok: true, stopped: true });
    expect(await until(evs, (e) => e.type === 'JobFinished' && e.job_id === start.job_id)).toMatchObject(
      { ok: false, problem: 'stopped' });
    const evs2: HubEvent[] = [];
    const g = createFakeBridge('normal', { speed: 50, emit: (e) => evs2.push(e) });
    const s2 = await g.account_sign_in('youtube', 'safari');
    if (!s2.ok) throw new Error();
    const d2 = await until(evs2, (e) => e.type === 'JobFinished' && e.job_id === s2.job_id);
    expect(d2).toMatchObject({ ok: false, problem: 'failed' });
  });
  it('account_sign_in: a sign-in that never sees the login gives up with the 10-minute message', async () => {
    const evs: HubEvent[] = [];
    const f = createFakeBridge('normal', { speed: 50, emit: (e) => evs.push(e) });
    f._ctx.s.signInTimesOut = true;
    const start = await f.account_sign_in('youtube', 'chrome');
    if (!start.ok) throw new Error();
    const done = await until(evs, (e) => e.type === 'JobFinished' && e.job_id === start.job_id);
    expect(done).toMatchObject({ ok: false, problem: 'failed', message: "Didn't see a login in 10 minutes. Sign in again." });
    expect(evs.filter((e) => e.type === 'SignInPhase').map((e) => (e as { phase: string }).phase)).toEqual(['waiting']);
    const st = await f.setup_status();
    if (!st.ok) throw new Error();
    expect(st.accounts.youtube).toBeNull();
  });
  it('unanswered methods come back crashed, the rest still answer', async () => {
    const f = createFakeBridge('setup:unreachable', { speed: 50 });
    expect(await f.setup_status()).toMatchObject({ ok: false, kind: 'crashed' });
    expect(await f.downloads_view()).toMatchObject({ ok: true });
  });
  it('downloads_view: Qobuz on, no accounts; the library counted by rung', async () => {
    const f = createFakeBridge('normal', { speed: 50 });
    const r = await f.downloads_view();
    if (!r.ok) throw new Error();
    const d = r.downloads;
    expect(d.qobuz.state).toBe('on');
    expect(d.youtube).toMatchObject({ state: 'off', browser: null, tracks: 0 });
    expect(d.library.lossless + d.library.account + d.library.free).toBeGreaterThan(0);
    expect(d.qobuz.tracks).toBeGreaterThan(0);
  });
  it('update_tools then rollback_tools change download_tools as the engine does', async () => {
    const evs: HubEvent[] = [];
    const f = createFakeBridge('normal', { speed: 50, emit: (e) => evs.push(e) });
    const tools = async () => {
      const t = await f.setup_check_tools();
      if (!t.ok) throw new Error();
      if (!t.download_tools) throw new Error();
      return t.download_tools['yt-dlp'];
    };
    expect(await tools()).toEqual({ version: '2026.10.21', source: 'built_in', waiting: null, previous: null });
    const up = await f.update_tools();
    if (!up.ok) throw new Error();
    expect(await until(evs, (e) => e.type === 'JobFinished' && e.job_id === up.job_id)).toMatchObject(
      { ok: true, result: { before: { 'yt-dlp': '2026.10.21' }, after: { 'yt-dlp': '2026.10.28' }, restart: true } });
    expect(await tools()).toEqual({ version: '2026.10.21', source: 'built_in', waiting: '2026.10.28', previous: '2026.10.21' });
    const back = await f.rollback_tools();
    if (!back.ok) throw new Error();
    expect(await until(evs, (e) => e.type === 'JobFinished' && e.job_id === back.job_id)).toMatchObject(
      { ok: true, result: { before: { 'yt-dlp': '2026.10.28' }, after: { 'yt-dlp': '2026.10.21' }, restart: false } });
    expect(await tools()).toEqual({ version: '2026.10.21', source: 'built_in', waiting: null, previous: null });
    const again = await f.rollback_tools();
    if (!again.ok) throw new Error();
    expect(await until(evs, (e) => e.type === 'JobFinished' && e.job_id === again.job_id))
      .toMatchObject({ ok: false, problem: 'refused' });
  });
  it('setup:soundcloud-no-go saves the SoundCloud login although the check is not ok, like the backend', async () => {
    const evs: HubEvent[] = [];
    const f = createFakeBridge('setup:soundcloud-no-go', { speed: 50, emit: (e) => evs.push(e) });
    const start = await f.setup_account('soundcloud', 'chrome');
    if (!start.ok) throw new Error();
    const done = await until(evs, (e) => e.type === 'JobFinished' && e.job_id === start.job_id);
    expect(done).toMatchObject({ ok: true, result: { service: 'soundcloud', browser: 'chrome', saved: true,
      check: { ok: false, problem: 'no_premium', kbps: 128 } } });
    const st = await f.setup_status();
    if (!st.ok) throw new Error();
    expect(st.accounts.soundcloud).toMatchObject({ browser: 'chrome' });
    // other scenarios keep the normal answer
    const evs2: HubEvent[] = [];
    const g = createFakeBridge('setup:playlists', { speed: 50, emit: (e) => evs2.push(e) });
    const s2 = await g.setup_account('soundcloud', 'chrome');
    if (!s2.ok) throw new Error();
    expect(await until(evs2, (e) => e.type === 'JobFinished' && e.job_id === s2.job_id))
      .toMatchObject({ result: { saved: true, check: { ok: true } } });
  });
  it('the console scenario refuses writes; offline refuses network reads', async () => {
    expect(await createFakeBridge('console').hide('t2', true)).toMatchObject({ ok: false, kind: 'console' });
    expect(await createFakeBridge('offline').search_candidates('t2')).toMatchObject({ ok: false, kind: 'offline' });
  });
  it('syncing starts with a running job that job_status shows at once', async () => {
    const f = createFakeBridge('syncing');
    const js = await f.job_status();
    if (!js.ok || !js.job) throw new Error();
    expect(js.job).toMatchObject({ kind: 'sync', running: true });
    const planned = STREAMS.sync.find((e) => e.type === 'RunStarted') as Extract<HubEvent, { type: 'RunStarted' }>;
    expect(js.job.actions).toHaveLength(planned.actions.length);
    expect(js.job.last.Progress).toMatchObject({ step: 'download' });   // mid-download, as the scenario says
    expect(await f.search_candidates('t2')).toMatchObject({ ok: false, kind: 'sync_running' });
  });
  it('stop ends a replayed sync with exit 130', async () => {
    const evs: HubEvent[] = [];
    const f = createFakeBridge('normal', { speed: 50, emit: (e) => evs.push(e) });
    const start = await f.start_sync([]);
    if (!start.ok) throw new Error();
    await until(evs, (e) => e.type === 'JobFinished');
    const s2 = await f.start_sync([['acquire', 't4', 'Library/Hard_Bounce']]);
    if (!s2.ok) throw new Error();
    await until(evs, (e) => e.type === 'ActionStarted' && e.index === 2);
    expect(await f.stop()).toMatchObject({ ok: true, stopped: true });
    const run = await until(evs, (e) => e.type === 'RunFinished', 8000);
    expect(run).toMatchObject({ exit_code: 130 });
  });
  it('reads Spotify by itself once per session; "↻ Read Spotify" still reads; Stop ends the read at once', async () => {
    const evs: HubEvent[] = [];
    const f = createFakeBridge('normal', { speed: 50, emit: (e) => evs.push(e) });
    f._ctx.s.spotify = { ...f._ctx.s.spotify, auto_read: false };  // the hub has not read by itself yet
    const first = await f.refresh(true);
    if (!first.ok) throw new Error();
    const p = await f.sync_preview();
    expect(p.ok && p.spotify.auto_read).toBe(true);
    expect(await f.stop_refresh()).toMatchObject({ ok: true, stopped: true });
    const fin = evs.find((e) => e.type === 'JobFinished' && e.job_id === first.job_id);
    expect(fin).toMatchObject({ problem: 'stopped' });
    expect(await f.refresh(true)).toMatchObject({ ok: false, kind: 'refused' }); // a stopped first read is not redone
    const manual = await f.refresh();
    if (!manual.ok) throw new Error();
    await until(evs, (e) => e.type === 'JobFinished' && e.job_id === manual.job_id);
    const js = await f.job_status();
    expect(js.ok && js.spotify.auto_read).toBe(true);
  });
});

describe('update notice', () => {
  it('app_update: up to date in normal, a newer version in update_available', async () => {
    expect(await createFakeBridge('normal').app_update())
      .toEqual({ ok: true, state: 'up_to_date', current: '1.0.0', latest: null, url: null });
    const r = await createFakeBridge('update_available').app_update();
    expect(r).toMatchObject({ ok: true, state: 'available', latest: '1.1.0' });
    expect(await createFakeBridge('offline').app_update())
      .toEqual({ ok: true, state: 'unknown', current: '1.0.0', latest: null, url: null });
    expect((r as { url: string }).url).toMatch(/^https:\/\/github\.com\/TheZwiss\/discjockey\/releases\/tag\//);
  });
});

describe('music folder', () => {
  it('answers no_library for library methods until a folder is chosen', async () => {
    const f = createFakeBridge('no_music');
    expect(await f.todo('all', false)).toMatchObject({ ok: false, kind: 'no_library' });
    expect((await f.setup_status()) as { next_step: string }).toMatchObject({ next_step: 'music' });
    expect(await f.set_music_folder('/Users/you/Music/Discjockey')).toMatchObject({ ok: true, restart: false });
    expect((await f.todo('all', false)).ok).toBe(true);
  });
  it('asks to restart when a bound folder changes', async () => {
    const f = createFakeBridge('normal');
    expect(await f.set_music_folder('/Users/you/Music/Other')).toMatchObject({ ok: true, restart: true });
  });
  it('names the missing folder, and refuses a path that is not absolute', async () => {
    const f = createFakeBridge('music_missing');
    expect(await f.sidebar()).toMatchObject({ ok: false, kind: 'no_library',
      message: expect.stringContaining('/Volumes/DJ SSD/Discjockey') });
    expect(await f.retry_music_folder()).toMatchObject({ ok: true, music: { state: 'missing' } });
    expect(await f.check_music_folder('Music')).toMatchObject({ usable: false, problem: 'not_absolute' });
    expect(await f.set_music_folder('Music')).toMatchObject({ ok: false, kind: 'refused' });
    expect(await f.check_music_folder('/Users/you/Music/New')).toMatchObject({ usable: true, kind: 'new' });
    expect(await f.reveal('.')).toMatchObject({ ok: false, kind: 'no_library' });
  });
  it('every library method answers no_library in no_music, with the engine message', async () => {
    const f = createFakeBridge('no_music');
    for (const name of LIBRARY_METHODS) {
      const r = await (f as any)[name]();
      expect(r, name).toMatchObject({ ok: false, kind: 'no_library',
        message: 'Choose your music folder first: it is the first step of Setup.' });
    }
  });
  it('binds another folder while the chosen one is missing, and counts nothing until then', async () => {
    const f = createFakeBridge('music_missing');
    expect(await f.setup_status()).toMatchObject({ playlists: false, complete: false, next_step: 'music' });
    const d = await f.downloads_view();
    expect(d.ok && d.downloads.library).toEqual({ lossless: 0, account: 0, free: 0 });
    expect(await f.set_music_folder('/Users/you/Music/Back')).toMatchObject({ ok: true, restart: false,
      music: { state: 'ok', path: '/Users/you/Music/Back' } });
  });
  it('reports each folder kind and problem, with the engine text unless the entry has its own', async () => {
    const f = createFakeBridge('normal');
    const s = (f as any)._ctx.s;
    s.folders['/Users/you/a'] = { exists: true, usable: true, problem: null, kind: 'empty', message: null };
    s.folders['/Users/you/b'] = { exists: true, usable: true, problem: null, kind: 'discjockey_library', message: null };
    s.folders['/Users/you/c'] = { exists: true, usable: true, problem: null, kind: 'other_files', message: null };
    s.folders['/Users/you/d'] = { exists: true, usable: false, problem: 'system_folder', kind: null, message: null };
    s.folders['/Users/you/e'] = { exists: true, usable: false, problem: 'not_writable', kind: null, message: null };
    for (const [p, kind] of [['a', 'empty'], ['b', 'discjockey_library'], ['c', 'other_files']]) {
      expect(await f.check_music_folder(`/Users/you/${p}`)).toMatchObject({ usable: true, kind });
    }
    expect(await f.check_music_folder('/Users/you/d')).toMatchObject({ usable: false, problem: 'system_folder',
      message: expect.stringContaining('belongs to macOS') });
    expect(await f.set_music_folder('/Users/you/e')).toMatchObject({ ok: false, kind: 'refused',
      message: "Discjockey can't write in that folder. Choose one of your own folders." });
    expect(await f.check_music_folder('~/Music/X')).toMatchObject({ path: '/Users/you/Music/X', kind: 'new' });
  });
  it('shows the music folder itself with reveal(".")', async () => {
    expect(await createFakeBridge('normal').reveal('.')).toMatchObject({ ok: true });
  });
});
