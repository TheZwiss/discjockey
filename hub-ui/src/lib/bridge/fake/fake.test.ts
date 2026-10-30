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
    const lib = await f.library('all', null, '', 'all', 'artist');
    if (!lib.ok) throw new Error();
    expect(lib.rows.length).toBeGreaterThan(1000);
    for (const r of lib.rows) {
      expect(r.path).toMatch(/^Library\/[^/]+(\/not_lossless)?\/[^/]+ - [^/]+\.aiff$/);
      expect(r.path).not.toMatch(/\((v?\d+|new)\)|\s\d+\.aiff$/);
    }
  });
  it('lists an own song of an imported folder under the folder name, never blank', async () => {
    const f = createFakeBridge('normal', { speed: 50, emit: () => {} });
    const p = await f.sync_preview();
    if (!p.ok) throw new Error();
    const all = p.groups.flatMap((g) => g.actions);
    expect(all.every((x) => x.folder.trim() !== '')).toBe(true);
    expect(all.find((x) => x.track_id === 'own-techno-1')).toMatchObject({ kind: 'upgrade', folder: 'Techno' });
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
    // Elsewhere: files moved there by hand (their songs say another folder), counted where they sit
    expect(side.library_folders).toEqual([{ path: 'Library/Elsewhere', name: 'Elsewhere', files: 3 },
      { path: 'Library/Old_Sets', name: 'Old_Sets', files: 2 }]);
    expect(side.playlists.map((x) => [x.name, x.service, x.enabled]).slice(3, 7)).toEqual([
      ['03_06_2026', 'spotify', true], ['Tekke_Ecke', 'spotify', false], ['Hard_Techno', 'spotify', true],
      ['Qobuz_Picks', 'qobuz', true]]);
    const pl = await f.playlists();
    if (!pl.ok) throw new Error();
    expect(pl.rows).toHaveLength(7);   // six Spotify lines (one without access) and one from Qobuz
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
    f._ctx.s.read_status = { ...f._ctx.s.read_status, auto_read: false };  // the hub has not read by itself yet
    const first = await f.refresh(true);
    if (!first.ok) throw new Error();
    const p = await f.sync_preview();
    expect(p.ok && p.read_status.auto_read).toBe(true);
    expect(await f.stop_refresh()).toMatchObject({ ok: true, stopped: true });
    const fin = evs.find((e) => e.type === 'JobFinished' && e.job_id === first.job_id);
    expect(fin).toMatchObject({ problem: 'stopped' });
    expect(await f.refresh(true)).toMatchObject({ ok: false, kind: 'refused' }); // a stopped first read is not redone
    const manual = await f.refresh();
    if (!manual.ok) throw new Error();
    await until(evs, (e) => e.type === 'JobFinished' && e.job_id === manual.job_id);
    const js = await f.job_status();
    expect(js.ok && js.read_status.auto_read).toBe(true);
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

describe('fake tidy-up', () => {
  const finished = (evs: HubEvent[], id: number) => until(evs, (e) => e.type === 'JobFinished' && e.job_id === id)
    .then((e) => e as Extract<HubEvent, { type: 'JobFinished' }>);
  const make = (hooks: (s: ReturnType<typeof createFakeBridge>['_ctx']['s']) => void = () => {}) => {
    const evs: HubEvent[] = [];
    const f = createFakeBridge('normal', { speed: 100, emit: (e) => evs.push(e) });
    hooks(f._ctx.s);
    return { f, evs };
  };
  const preview = async (f: ReturnType<typeof createFakeBridge>) => {
    const p = await f.tidy_preview();
    if (!p.ok) throw new Error();
    return p;
  };

  it('the preview has rows to tick, your own placement, a taken name and an offline file', async () => {
    const { f } = make();
    const p = await preview(f);
    expect(p.rows.filter((r) => r.ticked).length).toBe(p.ticked);
    expect(p.rows.filter((r) => r.yours).length).toBeGreaterThan(0);
    expect(p.rows.map((r) => r.skip?.reason).filter(Boolean).sort()).toEqual(['name_taken', 'offline']);
    expect(p.rows.every((r) => !r.skip || !r.ticked)).toBe(true);
    expect(p.yours).toMatchObject({ header: 'You put these here', control: 'Put these in playlist order too' });
    expect(p.rows[0]).toMatchObject({ from_path: p.rows[0].path, by_rename: null });
    expect(p.empty).toBeNull();
    const pl = await f.playlists();
    if (!pl.ok) throw new Error();
    expect(pl.tidy.waiting).toBe(p.ticked);
  });

  it('a tidy-up moves the ticked files, logs a batch and the undo puts them back (one file moved on)', async () => {
    const { f, evs } = make();
    const seeded = await f.move_batches();
    if (!seeded.ok) throw new Error();
    expect(seeded.total).toBe(2);
    const old = seeded.batches.find((b) => b.title === 'Tidy-up')!;
    expect(old.undoable).toBe(old.moved - 1);  // one of its files was moved on by hand
    const undo = await f.undo_preview(old.id);
    if (!undo.ok) throw new Error();
    expect(undo.rows.every((r) => r.kind === 'file' && r.files === null)).toBe(true);
    expect(undo.rows.filter((r) => r.skip?.reason === 'moved_on')).toHaveLength(1);
    expect(undo.rows.find((r) => r.skip)?.skip?.text).toBe('Moved or changed since');
    expect(undo.moving).toBe(undo.rows.filter((r) => !r.skip).length);
    expect(undo.nothing_left).toBe(false);
    expect(await f.undo_preview(999)).toMatchObject({ ok: false, kind: 'refused' });
    const rows = (await preview(f)).rows.filter((r) => r.ticked);
    const start = await f.tidy_up(rows.map((r) => [r.file_id, r.from_path]));
    if (!start.ok) throw new Error();
    const done = await finished(evs, start.job_id);
    expect(done.ok).toBe(true);
    expect(done.result).toMatchObject({ title: 'Tidy-up', moved: rows.length, stopped: false, skipped: [],
      headline: `Moved ${rows.length} files.` });
    expect(evs.filter((e) => e.type === 'MovesProgress')).toHaveLength(rows.length);
    expect((await preview(f)).rows.filter((r) => r.ticked)).toHaveLength(0);
    const log = await f.move_batches();
    if (!log.ok) throw new Error();
    expect(log.batches[0]).toMatchObject({ title: 'Tidy-up', moved: rows.length, undone_by: null, undoable: rows.length });
    const mine = log.batches[0].id;
    const u = await f.undo_moves(mine);
    if (!u.ok) throw new Error();
    const back = await finished(evs, u.job_id);
    expect(back.result).toMatchObject({ title: 'Undo of: Tidy-up', moved: rows.length, headline: `Moved ${rows.length} files back.` });
    expect((await preview(f)).rows.filter((r) => r.ticked)).toHaveLength(rows.length);
    const log2 = await f.move_batches();
    if (!log2.ok) throw new Error();
    expect(log2.batches.find((b) => b.id === mine)).toMatchObject({ undone_by: back.result.batch_id, undoable: 0 });
  });

  it('a file that changed since the list was shown is skipped, and malformed moves are refused', async () => {
    const { f, evs } = make();
    const row = (await preview(f)).rows.find((r) => r.ticked)!;
    const start = await f.tidy_up([[row.file_id, 'Library/Somewhere/else.aiff']]);
    if (!start.ok) throw new Error();
    const done = await finished(evs, start.job_id);
    expect(done.result).toMatchObject({ moved: 0, headline: 'Moved 0 files. 1 not moved:' });
    expect(done.result.skipped[0].text).toBe('Changed since the list was shown');
    for (const bad of [null, [], [[1]], [['1', 'a']], [[1, '']]]) {
      expect(await f.tidy_up(bad as never)).toMatchObject({ ok: false, kind: 'refused' });
    }
  });

  it('hooks: a failing move, a stopped batch and no rows', async () => {
    const failing = make((s) => { s.tidy.failMove = 1; });
    const rows = (await preview(failing.f)).rows.filter((r) => r.ticked);
    const a = await failing.f.tidy_up(rows.map((r) => [r.file_id, r.from_path]));
    if (!a.ok) throw new Error();
    const failed = await finished(failing.evs, a.job_id);
    expect(failed.ok).toBe(true);
    expect(failed.result.skipped.map((x: { text: string }) => x.text)).toEqual(["Couldn't move it: the drive is full"]);
    const stopped = make((s) => { s.tidy.stopAfter = 1; });
    const b = await stopped.f.tidy_up((await preview(stopped.f)).rows.filter((r) => r.ticked).map((r) => [r.file_id, r.from_path]));
    if (!b.ok) throw new Error();
    const cut = await finished(stopped.evs, b.job_id);
    expect(cut).toMatchObject({ ok: false, problem: 'stopped' });
    expect(cut.result).toMatchObject({ stopped: true, moved: 1 });
    expect(cut.result.skipped[0].text).toBe('Not moved: the moves were stopped first');
    const none = make((s) => { s.tidy.noRows = true; });
    expect(await preview(none.f)).toMatchObject({ rows: [], ticked: 0, empty: 'Every file is where the playlist order puts it.' });
  });

  it('only your own placements left: the preview says so and the button stays usable', async () => {
    const { f } = make();
    const rows = (await preview(f)).rows;
    for (const r of rows) if (!r.yours) f._ctx.s.tidy.placed[r.track_id] = 'user';
    const p = await preview(f);
    expect(p.ticked).toBe(0);
    expect(p.empty).toMatch(/files are where you put them, not where the playlist order puts them\.$/);
  });

  it('the save preview sends tidy rows and rename offers, and the save asks the question', async () => {
    const { f, evs } = make();
    const pl = await f.playlists();
    if (!pl.ok) throw new Error();
    const lines = pl.rows.map((r) => ({ folder: r.folder, link: r.link, enabled: r.enabled }));
    const swapped = [lines[1], lines[0], ...lines.slice(2)];
    const c = await f.preview_playlist_change(swapped);
    if (!c.ok) throw new Error();
    expect('moves' in c).toBe(false);
    expect(c.kind).toBe('moves');
    expect(c.tidy!.headline).toMatch(/^\d+ files? would sit in a different folder$/);
    expect(c.headline).toBe(c.tidy!.headline);
    expect(c.checklist).toEqual(['No downloads, no Qobuz quota used', 'Nothing is deleted', 'Files move only if you choose to',
      'Moves can be undone on this page']);
    const renamed = lines.map((l, i) => (i === 0 ? { ...l, folder: 'Hard_New' } : l));
    const r = await f.preview_playlist_change(renamed);
    if (!r.ok) throw new Error();
    expect(r.kind).toBe('rename');
    expect(r.renames[0]).toMatchObject({ from: 'Hard_Bounce', to: 'Hard_New', offered: true, why_not: null,
      option: 'Rename the folder on disk too' });
    // the rename on disk covers the files that sit in the folder; a file put elsewhere moves on its own
    const inFolder = (x: { from: string }) => x.from.replace(/\/not_lossless$/, '') === 'Hard_Bounce';
    expect(r.tidy!.rows.filter(inFolder).length).toBeGreaterThan(0);
    expect(r.tidy!.rows.every((x) => x.by_rename === (inFolder(x) ? 'Hard_Bounce' : null))).toBe(true);
    const v = pl.version;
    const save = await f.save_playlists(renamed, v, { choice: 'move', renames: [['Hard_Bounce', 'Hard_New']], moves: [] });
    if (!save.ok) throw new Error();
    const done = await finished(evs, save.job_id);
    expect(done.ok).toBe(true);
    const folders = await f.library('all', null, '', 'all', 'artist');
    if (!folders.ok) throw new Error();
    const carried = folders.rows.filter((x) => x.path?.startsWith('Library/Hard_New/')).length;
    expect(carried).toBeGreaterThan(1);
    // a folder move counts the files it carried, in the result, the log and the undo preview
    expect(done.result.batches[0]).toMatchObject({ title: 'Renamed Hard_Bounce to Hard_New', moved: carried });
    expect(done.result.batches[0].headline).toBe(`Moved ${carried} files.`);
    const log = await f.move_batches();
    if (!log.ok) throw new Error();
    expect(log.batches.find((b) => b.id === done.result.batches[0].batch_id)!.summary).toBe(`${carried} files moved`);
    const undo = await f.undo_preview(done.result.batches[0].batch_id);
    if (!undo.ok) throw new Error();
    expect(undo.rows).toMatchObject([{ kind: 'folder', files: carried }]);
    expect(undo.moving).toBe(carried);
  });

  it('a Stop during the save wait saves the file, runs no batch and ends stopped with the new version', async () => {
    const { f, evs } = make();
    const pl = await f.playlists();
    if (!pl.ok) throw new Error();
    const lines = pl.rows.map((r) => ({ folder: r.folder, link: r.link, enabled: r.enabled }));
    const swapped = [lines[1], lines[0], ...lines.slice(2)];
    const rows = (await preview(f)).rows;
    const save = await f.save_playlists(swapped, pl.version, { choice: 'move', renames: [], moves: rows.map((r) => [r.file_id, r.from_path]) });
    if (!save.ok) throw new Error();
    expect(await f.stop()).toMatchObject({ ok: true, stopped: true });
    const done = await finished(evs, save.job_id);
    expect(done).toMatchObject({ ok: false, problem: 'stopped' });
    const after = await f.playlists();
    if (!after.ok) throw new Error();
    expect(after.version).not.toBe(pl.version);
    expect(done.result).toEqual({ version: after.version, batches: [] });
  });

  it('save checks folder names by the real rules and undo refuses a batch nobody recorded', async () => {
    const { f } = make();
    const pl = await f.playlists();
    if (!pl.ok) throw new Error();
    const lines = pl.rows.map((r) => ({ folder: r.folder, link: r.link, enabled: r.enabled }));
    const named = (folder: string) => [{ ...lines[0], folder }, ...lines.slice(1)];
    for (const bad of ['a/b', 'a\\b', 'a:b', '.hidden', '..', 'Not_Lossless', 'x'.repeat(101)]) {
      expect(await f.save_playlists(named(bad), pl.version, null), bad).toMatchObject({ ok: false, kind: 'refused' });
    }
    expect(await f.save_playlists(named('Caf\u00e9, 2024 (live)'), pl.version, null)).toMatchObject({ ok: true });
    expect(await f.undo_moves(9999)).toMatchObject({ ok: false, kind: 'refused', message: 'Discjockey has no record of these moves.' });
  });

  it('save with leave makes the retargeted files yours; malformed answers are refused', async () => {
    const { f, evs } = make();
    const pl = await f.playlists();
    if (!pl.ok) throw new Error();
    const lines = pl.rows.map((r) => ({ folder: r.folder, link: r.link, enabled: r.enabled }));
    const swapped = [lines[1], lines[0], ...lines.slice(2)];
    const before = (await preview(f)).rows.length;
    for (const bad of ['move', { choice: 'x' }, { choice: 'move', moves: [[1]] }, { choice: 'move', renames: [['a']] }]) {
      expect(await f.save_playlists(swapped, pl.version, bad as never)).toMatchObject({ ok: false, kind: 'refused' });
    }
    const save = await f.save_playlists(swapped, pl.version, { choice: 'leave', renames: [], moves: [] });
    if (!save.ok) throw new Error();
    const done = await finished(evs, save.job_id);
    expect(done.result.batches).toEqual([]);
    const after = await preview(f);
    expect(after.rows.length).toBeGreaterThan(before);  // the retargeted files sit where they were, as yours
    expect(after.rows.filter((r) => r.yours).length).toBeGreaterThan(0);
  });
});

describe('fake backend: Qobuz playlists (stage 3)', () => {
  it('lists a Qobuz playlist row with its ref, service and hint', async () => {
    const f = createFakeBridge('normal');
    const pl = await f.playlists();
    if (!pl.ok) throw new Error();
    const row = pl.rows.find((r) => r.service === 'qobuz')!;
    expect(row).toMatchObject({ link: 'https://open.qobuz.com/playlist/900000001', playlist_id: 'qobuz:900000001',
      service_name: 'Qobuz' });
    expect(row.info).toMatchObject({ owner_name: 'Example Curator', readable: true });
    expect(row.info!.hint).toMatch(/public/);
    expect(pl.rows.find((r) => r.service === 'spotify')).toMatchObject({ service_name: 'Spotify',
      playlist_id: '0DiscjockeyExampleList' });
  });
  it('a track of the Qobuz playlist links to Qobuz, the others to Spotify', async () => {
    const f = createFakeBridge('normal');
    const q = await f.track('qobuz:112358');
    const sp = await f.track('t1');
    if (!q.ok || !sp.ok) throw new Error();
    expect(q.track.track_link).toEqual({ url: 'https://open.qobuz.com/track/112358', label: 'Open in Qobuz' });
    expect(sp.track.track_link).toEqual({ url: 'https://open.spotify.com/track/t1', label: 'Open in Spotify' });
  });
  it('add_playlist reads a Qobuz link; qobuz_unreadable answers the Qobuz words; qobuz_not_connected asks to connect', async () => {
    const link = 'https://open.qobuz.com/playlist/777000123';
    const read = await createFakeBridge('normal', { speed: 50 }).add_playlist(link);
    expect(read).toMatchObject({ ok: true, playlist_id: 'qobuz:777000123', service: 'qobuz', service_name: 'Qobuz',
      readable: true });
    expect(await createFakeBridge('qobuz_unreadable', { speed: 50 }).add_playlist(link)).toEqual({ ok: false,
      kind: 'playlist_unreadable', service: 'qobuz',
      message: "Qobuz doesn't show this playlist. It must be public or one of yours. Check the link." });
    expect(await createFakeBridge('qobuz_not_connected', { speed: 50 }).add_playlist(link)).toMatchObject({ ok: false,
      kind: 'not_set_up', service: 'qobuz' });
    const sp = await createFakeBridge('normal', { speed: 50 }).add_playlist('https://open.spotify.com/playlist/37i9dQZF1DX');
    expect(sp).toMatchObject({ ok: true, playlist_id: '37i9dQZF1DX', service: 'spotify' });
  });
  it('the read status names the services; qobuz_not_connected has Qobuz unconnected and the problem about it', async () => {
    const ok = await createFakeBridge('normal').dashboard();
    const bad = await createFakeBridge('qobuz_not_connected').dashboard();
    if (!ok.ok || !bad.ok) throw new Error();
    expect(ok.read_status).toMatchObject({ problem: null, problem_service: null });
    expect(ok.read_status.services.map((x) => [x.service, x.connected])).toEqual([['spotify', true], ['qobuz', true]]);
    expect(bad.read_status.services.find((x) => x.service === 'qobuz')).toMatchObject({ name: 'Qobuz', connected: false });
    expect(bad.read_status).toMatchObject({ problem: 'not_set_up', problem_service: 'qobuz' });
  });
  it('setup_skip_spotify counts the Spotify step as done', async () => {
    const evs: HubEvent[] = [];
    const f = createFakeBridge('first_run', { speed: 50, emit: (e) => evs.push(e) });
    const before = await f.setup_status();
    if (!before.ok) throw new Error();
    expect(before).toMatchObject({ spotify_skipped: false, next_step: 'spotify' });
    const start = await f.setup_skip_spotify();
    if (!start.ok) throw new Error();
    const done = await until(evs, (e) => e.type === 'JobFinished' && e.job_id === start.job_id);
    expect(done).toMatchObject({ kind: 'setup_skip_spotify', ok: true });
    const after = await f.setup_status();
    if (!after.ok) throw new Error();
    expect(after.spotify_skipped).toBe(true);
    expect(after.next_step).not.toBe('spotify');
  });
});
