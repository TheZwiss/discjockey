import { describe, expect, it } from 'vitest';
import type { DownloadTool, JobSnap } from '$lib/bridge/types';
import { cardJob, needsReopen, reopenNote, toolsCard, updateLines, updateOutcome } from './settingsModel';

const snap = (kind: string, running: boolean, finished: unknown = null): JobSnap => ({ id: 4, kind, track_id: null,
  started: '', running, stopping: false, last: {}, results: [], finished, actions: [] });

describe('a card picks up its job', () => {
  it('its own kind: the id while it runs, how it ended after; another kind or none: nothing', () => {
    expect(cardJob(snap('update_tools', true), 'update_tools')).toEqual({ id: 4, running: true });
    const fin = { ok: true, problem: null, message: '', result: { before: {}, after: {} } };
    expect(cardJob(snap('update_tools', false, fin), 'update_tools')).toEqual({ id: 4, running: false, finished: fin });
    expect(cardJob(snap('setup_spotify_login', true), 'setup_spotify_login')).toEqual({ id: 4, running: true });
    expect(cardJob(snap('sync', true), 'update_tools')).toBeNull();
    expect(cardJob(null, 'setup_spotify_login')).toBeNull();
  });
  it('the update: lines when it worked, the words when it failed, nothing when stopped', () => {
    expect(updateOutcome({ ok: true, result: { before: { streamrip: '2.1.0' }, after: { streamrip: '2.1.1' } } }))
      .toEqual({ lines: ['streamrip 2.1.0 → 2.1.1'], error: null, restart: false });
    expect(updateOutcome({ ok: false, problem: 'failed', message: "The tools couldn't be updated." }))
      .toEqual({ lines: null, error: "The tools couldn't be updated.", restart: false });
    expect(updateOutcome({ ok: false, problem: 'stopped', message: 'Stopped.' })).toEqual({ lines: null, error: null, restart: false });
    expect(updateOutcome(null)).toEqual({ lines: null, error: null, restart: false });
  });
  it('a reopen is asked for only when the engine says so', () => {
    const same = { before: { 'yt-dlp': '2026.10.28' }, after: { 'yt-dlp': '2026.10.28' } };
    expect(updateOutcome({ ok: true, result: { ...same, restart: false } }))
      .toEqual({ lines: ['yt-dlp 2026.10.28 (already the newest)'], error: null, restart: false });
    expect(updateOutcome({ ok: true, result: { before: { 'yt-dlp': '2026.10.21' }, after: { 'yt-dlp': '2026.10.28' },
      restart: true } }).restart).toBe(true);
  });
});

describe('update lines', () => {
  it('shows each tool with its old and new version', () => {
    expect(updateLines({ streamrip: '2.1.0', 'yt-dlp': '2026.09.01' }, { streamrip: '2.1.1', 'yt-dlp': '2026.10.10' }))
      .toEqual(['streamrip 2.1.0 → 2.1.1', 'yt-dlp 2026.09.01 → 2026.10.10']);
  });
  it('says when a tool was already the newest', () => {
    expect(updateLines({ streamrip: '2.1.0' }, { streamrip: '2.1.0' })).toEqual(['streamrip 2.1.0 (already the newest)']);
  });
  it('copes with a missing or odd answer', () => {
    expect(updateLines(null, { streamrip: '2.1.1' })).toEqual(['streamrip not installed → 2.1.1']);
    expect(updateLines('x', 3)).toEqual([]);
  });
});

import type {
  DownloadsAccount, DownloadsView, SetupStatus, SetupTools, WatchedFolderRow, WatchedFolders,
} from '$lib/bridge/types';
import {
  ROW_GLYPHS, ROW_GROUPS, SETTINGS_ROWS, checkedWhen, firstAttention, isAccountRow, rowLine, type RowContext,
} from './settingsModel';

const NOW = new Date(2026, 9, 22, 12, 0);
const acc = (over: Partial<DownloadsAccount> = {}): DownloadsAccount => ({ state: 'off', browser: null,
  browser_name: null, profile: null, profile_name: null, last_check: null, tracks: 0, ...over });
const view = (over: Partial<DownloadsView> = {}): DownloadsView => ({
  qobuz: { state: 'on', last_check: { ok: true, problem: null, kbps: null, at: '2026-10-22T09:15:00' }, tracks: 412 },
  youtube: acc(), soundcloud: acc(), library: { lossless: 412, account: 0, free: 31 }, ...over });
const status = (over: Partial<SetupStatus> = {}): SetupStatus => ({
  music: { state: 'ok', path: '/Users/you/Music/Discjockey', suggested: '/Users/you/Music/Discjockey' },
  tools: { ffmpeg: true, ffprobe: true, deno: true }, spotify_app: true, spotify_login: true, qobuz: true,
  playlists: true, complete: true, next_step: null, version: '1.0.0', qobuz_skipped: false, spotify_skipped: false, spotify_user: 'dj',
  existing: false, import_folders: 0, import_skipped: false,
  accounts: { youtube: null, soundcloud: null }, ...over });
const tools = (missing: string[] = []): SetupTools => ({ tools: { ffmpeg: true, ffprobe: true, deno: true }, missing,
  hints: {}, redirect_uri: 'http://127.0.0.1:8888/callback',
  download_tools: { 'yt-dlp': { version: '2026.10.21', source: 'built_in', waiting: null, previous: null },
  streamrip: { version: '2.1.0', source: 'built_in', waiting: null, previous: null } },
  download_tools_problem: null });
const ctx = (over: Partial<RowContext> = {}): RowContext => ({ downloads: view(), status: status(), tools: tools(),
  reports: 23, now: NOW, ...over });

describe('settings rows', () => {
  it('Qobuz signed in, checked today; an account not set up', () => {
    expect(rowLine('qobuz', ctx())).toEqual({ tone: 'good', text: 'signed in · checked today' });
    expect(rowLine('youtube', ctx())).toEqual({ tone: 'none', text: 'not set up · about 256 kbps instead of 130' });
  });
  it('a working account says where and how good', () => {
    const yt = acc({ state: 'on', browser: 'chrome', browser_name: 'Chrome', profile: 'Profile 2', profile_name: 'DJ',
      last_check: { ok: true, problem: null, kbps: 256, at: '2026-10-21T10:00:00' } });
    expect(rowLine('youtube', ctx({ downloads: view({ youtube: yt }) }))).toEqual(
      { tone: 'good', text: 'via Chrome (DJ) · 256 kbps · checked 21 Oct' });
  });
  it('accounts that need the user', () => {
    const lost = acc({ state: 'off', browser: 'chrome', browser_name: 'Chrome' });
    expect(rowLine('youtube', ctx({ downloads: view({ youtube: lost }) }))).toEqual(
      { tone: 'problem', text: 'not signed in any more in Chrome' });
    expect(rowLine('soundcloud', ctx({ downloads: view({ soundcloud: acc({ state: 'no_premium' }) }) })).tone).toBe('warn');
    expect(rowLine('youtube', ctx({ downloads: view({ youtube: acc({ state: 'paused' }) }) })).text).toBe('paused today');
  });
  it('Qobuz rejected, left out', () => {
    const rejected = view({ qobuz: { state: 'off', tracks: 0,
      last_check: { ok: false, problem: 'login_failed', kbps: null, at: '2026-10-22T09:00:00' } } });
    expect(rowLine('qobuz', ctx({ downloads: rejected }))).toEqual({ tone: 'problem', text: "Qobuz didn't accept the login" });
    expect(rowLine('qobuz', ctx({ downloads: view({ qobuz: { state: 'skipped', last_check: null, tracks: 0 } }) })))
      .toEqual({ tone: 'none', text: 'left out' });
  });
  it('the About row says the version and the update answer, never as something to fix', () => {
    const url = 'https://github.com/TheZwiss/discjockey/releases/tag/v1.1.0';
    const upToDate = { state: 'up_to_date', current: '1.0.0', latest: null, url: null } as const;
    expect(rowLine('about', ctx({ update: upToDate }))).toEqual({ tone: null, text: '1.0.0 · up to date' });
    expect(rowLine('about', ctx({ update: { state: 'available', current: '1.0.0', latest: '1.1.0', url } })))
      .toEqual({ tone: null, text: '1.0.0 · 1.1 is available' });
    expect(rowLine('about', ctx({ update: { ...upToDate, state: 'unknown' } }))).toEqual({ tone: null, text: '1.0.0' });
    expect(rowLine('about', ctx({ update: null }))).toEqual({ tone: null, text: '1.0.0' });
    expect(rowLine('about', ctx({ status: null, update: upToDate }))).toEqual({ tone: null, text: '' });
  });
  it('Spotify, programs, About, reports', () => {
    expect(rowLine('spotify', ctx())).toEqual({ tone: 'good', text: 'connected as dj' });
    expect(rowLine('spotify', ctx({ status: status({ spotify_login: false }) }))).toEqual({ tone: 'problem', text: 'not connected' });
    expect(rowLine('programs', ctx({ tools: tools(['deno']) }))).toEqual({ tone: 'problem', text: 'deno missing' });
    expect(rowLine('about', ctx({ status: status({}) }))).toEqual({ tone: null, text: '1.0.0' });
    expect(rowLine('reports', ctx())).toEqual({ tone: null, text: '23 sync reports' });
    expect(rowLine('reports', ctx({ reports: 0 })).text).toBe('no reports yet');
  });
  it('a Spotify left out in Setup is no problem until playlists.txt uses it (plan stage 3, D1)', () => {
    const skipped = status({ spotify_app: false, spotify_login: false, spotify_skipped: true });
    expect(rowLine('spotify', ctx({ status: skipped }))).toEqual({ tone: 'none', text: 'left out' });
    expect(firstAttention(ctx({ status: skipped }))).toBe('qobuz');
    expect(rowLine('spotify', ctx({ status: skipped, spotifyUsed: true }))).toEqual({ tone: 'problem', text: 'not set up' });
    expect(firstAttention(ctx({ status: skipped, spotifyUsed: true }))).toBe('spotify');
  });
  it('a failed programs check says so instead of waiting, and is where Settings opens', () => {
    const failed = ctx({ tools: null, toolsFailed: true });
    expect(rowLine('programs', failed)).toEqual({ tone: 'problem', text: "couldn't check" });
    expect(firstAttention(failed)).toBe('programs');
  });
  it('loading rows say nothing yet', () => {
    expect(rowLine('qobuz', ctx({ downloads: null }))).toEqual({ tone: null, text: '' });
    expect(rowLine('programs', ctx({ tools: null }))).toEqual({ tone: null, text: '' });
  });
  it('opens the first row that needs the user, else Qobuz', () => {
    expect(firstAttention(ctx())).toBe('qobuz');
    expect(firstAttention(ctx({ tools: tools(['ffmpeg']) }))).toBe('programs');
    expect(firstAttention(ctx({ downloads: view({ soundcloud: acc({ state: 'paused' }) }) }))).toBe('soundcloud');
  });
  it('checked when', () => {
    expect(checkedWhen(null, NOW)).toBe('');
    expect(checkedWhen({ ok: true, problem: null, kbps: null, at: '2026-10-22T00:01:00' }, NOW)).toBe('checked today');
  });
});

describe('settings list', () => {
  it('every row has a glyph and sits in exactly one group', () => {
    const grouped = ROW_GROUPS.flatMap((g) => g.rows);
    expect([...grouped].sort()).toEqual([...SETTINGS_ROWS].sort());
    for (const r of SETTINGS_ROWS) expect(ROW_GLYPHS[r]).toBeTruthy();
  });
  it('This Mac holds the music folder, the watched folders, programs, About and reports', () => {
    expect(ROW_GROUPS.find((g) => g.label === 'This Mac')?.rows).toEqual(['music', 'folders', 'programs', 'about',
      'reports']);
  });
  it('the music folder row shows the folder, short, as good; it never opens first while it is fine', () => {
    expect(rowLine('music', ctx())).toEqual({ tone: 'good', text: '~/Music/Discjockey' });
    expect(firstAttention(ctx())).not.toBe('music');
  });
  it('the watched folders row: Library only, what is watched, an offline drive, the running import live', () => {
    const lib: WatchedFolderRow = { id: 1, path: '/Users/you/Music/Discjockey/Library', name: 'Library', kind: 'library',
      state: 'online', files: 412, waiting: 0, unreadable: 0 };
    const drive: WatchedFolderRow = { id: 2, path: '/Volumes/Example Drive/Music', name: 'Music', kind: 'import',
      state: 'online', files: 1240, waiting: 0, unreadable: 0 };
    const wf = (folders: WatchedFolderRow[], over: Partial<WatchedFolders> = {}): WatchedFolders =>
      ({ folders, unreadable: [], waiting: 0, stopped: false, ...over });
    expect(rowLine('folders', ctx())).toEqual({ tone: null, text: '' });   // still reading: the skeleton
    expect(rowLine('folders', ctx({ folders: wf([lib]) }))).toEqual({ tone: 'none', text: 'Library only' });
    expect(rowLine('folders', ctx({ folders: wf([lib, drive]) }))).toEqual({ tone: 'good', text: '1 folder · 1,240 files' });
    const crates = { ...drive, id: 3, name: 'Crates', path: '/Volumes/Example Drive/Crates', files: 1 };
    expect(rowLine('folders', ctx({ folders: wf([lib, drive, crates]) })).text).toBe('2 folders · 1,241 files');
    const old = { ...drive, id: 4, name: 'Old Drive', state: 'offline' as const };
    expect(rowLine('folders', ctx({ folders: wf([lib, drive, old]) }))).toEqual({ tone: 'warn', text: 'Old Drive is offline' });
    // an offline drive waits; it is no reason to open Settings at the watched folders
    expect(firstAttention(ctx({ folders: wf([lib, old]) }))).toBe('qobuz');
    const job = { id: 9, kind: 'import', track_id: null, started: '', running: true, stopping: false, results: [],
      finished: null, actions: [], last: { ImportProgress: { type: 'ImportProgress', phase: 'tags', done: 340, total: 1500,
        unreadable: 0 } } };
    expect(rowLine('folders', ctx({ folders: wf([lib, old]), job }))).toEqual({ tone: null, text: 'Reading tags · 340 of 1,500' });
    // the next phase restarts its count, and the row says which phase it is in
    const sound = { ...job, last: { ImportProgress: { type: 'ImportProgress', phase: 'sound', done: 0, total: 1500, unreadable: 0 } } };
    expect(rowLine('folders', ctx({ folders: wf([lib, old]), job: sound })).text).toBe('Checking the sound · 0 of 1,500');
    // two folders with one name: the offline line says which by its short path
    const same = { ...old, id: 5, name: 'Music', path: '/Users/you/Music' };
    expect(rowLine('folders', ctx({ folders: wf([lib, drive, same, { ...same, id: 6, state: 'online' as const, path: '/Volumes/X/Music' }]) })).text)
      .toBe('Music (~/Music) is offline');
    expect(rowLine('folders', ctx({ folders: null, job: { ...job, last: {} } }))).toEqual({ tone: null,
      text: 'Looking for music files' });
  });
  it('only the download services open an account panel', () => {
    expect(SETTINGS_ROWS.filter(isAccountRow)).toEqual(['qobuz', 'youtube', 'soundcloud']);
  });
});

const tool = (o: Partial<DownloadTool> = {}): DownloadTool =>
  ({ version: '2026.10.21', source: 'built_in', waiting: null, previous: null, ...o });

describe('the Download tools card', () => {
  it('says where each version came from', () => {
    const c = toolsCard({ 'yt-dlp': tool({ version: '2026.10.28', source: 'updated', previous: '2026.10.21' }),
      streamrip: tool({ version: '2.1.0' }) });
    expect(c.rows).toEqual([{ name: 'yt-dlp', value: '2026.10.28 (updated)' },
      { name: 'streamrip', value: '2.1.0 (built in)' }]);
    expect(c.back).toBe('2026.10.21');
    expect(c.waiting).toBeNull();
  });
  it('a version waiting for a reopen, and a missing tool', () => {
    const c = toolsCard({ 'yt-dlp': tool({ waiting: '2026.10.28', previous: '2026.10.21' }),
      streamrip: tool({ version: null }) });
    expect(c.waiting).toBe('2026.10.28');
    expect(c.rows[1]).toEqual({ name: 'streamrip', value: 'not installed' });
  });
  it('nothing yet', () => {
    expect(toolsCard(null)).toEqual({ rows: [], waiting: null, back: null });
  });
  it('a rollback job is the card\'s own too', () => {
    expect(cardJob(snap('rollback_tools', true), 'rollback_tools')).toEqual({ id: 4, running: true });
  });
});

describe('when Discjockey has to be opened again', () => {
  it('only when a yt-dlp waits or the last change said so', () => {
    expect(needsReopen({ waiting: null }, false)).toBe(false);
    expect(needsReopen({ waiting: '2026.10.28' }, false)).toBe(true);
    expect(needsReopen({ waiting: null }, true)).toBe(true);
    expect(needsReopen({ waiting: '2026.10.28' }, true)).toBe(true);
  });
  it('"already the newest" and unread versions need no reopen', () => {
    const out = updateOutcome({ ok: true, result: { before: { 'yt-dlp': 'a' }, after: { 'yt-dlp': 'a' }, restart: false } });
    expect(needsReopen(toolsCard(null), out.restart)).toBe(false);
    const changed = updateOutcome({ ok: true, result: { before: { 'yt-dlp': 'a' }, after: { 'yt-dlp': 'b' }, restart: true } });
    expect(needsReopen(toolsCard(null), changed.restart)).toBe(true);
  });
  it('the note names the version that starts being used, in plain words', () => {
    expect(reopenNote('2026.10.28', 'update_tools', false)).toEqual({ title: 'Open Discjockey again',
      text: 'Quit Discjockey and open it again to start using yt-dlp 2026.10.28.' });
    expect(reopenNote(null, 'rollback_tools', false).text).toBe(
      'Quit Discjockey and open it again to start using the earlier yt-dlp.');
    expect(reopenNote(null, 'update_tools', false).text).toContain('the new yt-dlp');
    expect(reopenNote(null, null, true).text).toBe('Open Discjockey again to start using the new yt-dlp.');
  });
});
