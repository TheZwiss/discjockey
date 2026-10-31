import { describe, expect, it } from 'vitest';
import type { SetupStatus, SetupTools, WatchedFolderRow, WatchedFolders } from '$lib/bridge/types';
import {
  STEPS, STEP_LABELS, checkClientId, continueFilled, doneRedirect, mustChooseMusic, stripSteps, filledCard, firstStep, neighbour, nextRule, reachable, skipsExisting, stepsDone,
  takeSecret, toolFixes,
} from './setupModel';

const complete: SetupStatus = {
  music: { state: 'ok', path: '/Users/you/Music/Discjockey', suggested: '/Users/you/Music/Discjockey' },
  tools: { ffmpeg: true, ffprobe: true, deno: true }, spotify_app: true,
  spotify_login: true, qobuz: true, playlists: true, complete: true, next_step: null, version: '1.0.0',
  qobuz_skipped: false, spotify_skipped: false, existing: false, import_folders: 0, import_skipped: false,
  accounts: { youtube: null, soundcloud: null } };
const fresh: SetupStatus = { ...complete, spotify_app: false, spotify_login: false, qobuz: false, playlists: false,
  complete: false, next_step: 'spotify' };
const status = (over: Partial<SetupStatus>): SetupStatus => ({ ...complete, ...over });
const toolsOk: SetupTools = { tools: { ffmpeg: true, ffprobe: true, deno: true }, missing: [], hints: {},
  redirect_uri: 'http://127.0.0.1:8888/callback',
  download_tools: { 'yt-dlp': { version: '2026.10.21', source: 'built_in', waiting: null, previous: null },
  streamrip: { version: '2.1.0', source: 'built_in', waiting: null, previous: null } },
  download_tools_problem: null };
const toolsMissing: SetupTools = { ...toolsOk, tools: { ffmpeg: true, ffprobe: true, deno: false }, missing: ['deno'],
  hints: { deno: 'brew install deno' } };

describe('the steps', () => {
  it('are Music folder, Your existing music, Programs, Spotify, Downloads and First playlist, in that order', () => {
    expect(STEPS).toEqual(['music', 'existing', 'tools', 'spotify', 'downloads', 'playlists']);
    expect(STEPS.map((s) => STEP_LABELS[s])).toEqual(['Music folder', 'Your existing music', 'Programs', 'Spotify',
      'Downloads', 'First playlist']);
  });
  it('go back and forward along that order', () => {
    expect(neighbour('downloads', -1)).toBe('spotify');
    expect(neighbour('downloads', 1)).toBe('playlists');
    expect(neighbour('music', 1)).toBe('existing');
    expect(neighbour('tools', -1)).toBe('existing');
    expect(neighbour('existing', -1)).toBe('music');
    expect(neighbour('music', -1)).toBeNull();
    expect(neighbour('playlists', 1)).toBeNull();
  });
});

const noMusic = status({ music: { state: 'not_chosen', path: null, suggested: '/Users/you/Music/Discjockey' },
  complete: false, next_step: 'music', playlists: false });

describe('the music folder step', () => {
  it('is done once a folder is bound', () => {
    expect(stepsDone(complete).music).toBe(true);
    expect(stepsDone(noMusic).music).toBe(false);
  });
  it('is the only step to open while no folder is chosen, even with the programs there', () => {
    expect(firstStep(noMusic)).toBe('music');
    expect(firstStep({ ...noMusic, next_step: 'tools' })).toBe('music');
    expect(STEPS.filter((k) => reachable(k, noMusic))).toEqual(['music']);
    expect(mustChooseMusic(noMusic)).toBe(true);
    expect(mustChooseMusic(complete)).toBe(false);
  });
  it('lets Continue go on only with a folder', () => {
    expect(nextRule('music', noMusic, toolsOk)).toEqual({ allowed: false, why: 'Choose your music folder first.' });
    expect(nextRule('music', fresh, toolsOk)).toEqual({ allowed: true, why: null });
  });
  it('opens Settings → Music folder once setup is done', () => {
    expect(doneRedirect(complete, 'music')).toBe('/settings/music');
  });
});

describe('Client ID check', () => {
  it('accepts 32 hex characters in any case', () => {
    expect(checkClientId('4f1c0a9b2d3e4f5a6b7c8d9e0f1ae9a2')).toBe('ok');
    expect(checkClientId('4F1C0A9B2D3E4F5A6B7C8D9E0F1AE9A2')).toBe('ok');
  });
  it('trims spaces around it', () => {
    expect(checkClientId('  4f1c0a9b2d3e4f5a6b7c8d9e0f1ae9a2 \n')).toBe('ok');
  });
  it('refuses wrong length, other letters and spaces inside', () => {
    expect(checkClientId('4f1c0a9b2d3e4f5a6b7c8d9e0f1ae9a')).toBe('bad');
    expect(checkClientId('zf1c0a9b2d3e4f5a6b7c8d9e0f1ae9a2')).toBe('bad');
    expect(checkClientId('4f1c0a9b2d3e4f5a 6b7c8d9e0f1ae9a2')).toBe('bad');
  });
  it('is empty for nothing typed', () => {
    expect(checkClientId('   ')).toBe('empty');
  });
});

describe('steps done', () => {
  it('follows setup_status', () => {
    expect(stepsDone(complete)).toEqual({ music: true, existing: false, tools: true, spotify: true, downloads: true,
      playlists: true });
    expect(stepsDone(fresh)).toEqual({ music: true, existing: false, tools: true, spotify: false, downloads: false,
      playlists: false });
  });
  it('counts Your existing music as done once setup_status says so (a folder watched, or skipped)', () => {
    expect(stepsDone(status({ existing: true, import_folders: 1 })).existing).toBe(true);
    expect(stepsDone(status({ existing: true, import_skipped: true })).existing).toBe(true);
    expect(stepsDone(status({ existing: false })).existing).toBe(false);
  });
  it('skips Your existing music on Continue only when no folder is watched, by the status or by the folders read', () => {
    const lib: WatchedFolderRow = { id: 1, path: '/Users/you/Library', name: 'Library', kind: 'library', state: 'online',
      files: 3, waiting: 0, unreadable: 0, crates: [], too_many: false };
    const crates: WatchedFolderRow = { ...lib, id: 2, name: 'Crates', kind: 'import' };
    const folders = (...f: WatchedFolderRow[]): WatchedFolders => ({ folders: f, unreadable: [], waiting: 0, stopped: false });
    expect(skipsExisting(status({ existing: false }), null)).toBe(true);
    expect(skipsExisting(status({ existing: false }), folders(lib))).toBe(true);
    // a folder was just added: the status may not know yet, the folders do
    expect(skipsExisting(status({ existing: false }), folders(lib, crates))).toBe(false);
    expect(skipsExisting(status({ existing: true }), null)).toBe(false);
  });
  it('needs the app and the login for Spotify, and every program for Programs', () => {
    expect(stepsDone(status({ spotify_login: false })).spotify).toBe(false);
    expect(stepsDone(status({ spotify_login: false, spotify_skipped: true })).spotify).toBe(true);   // "I don't use Spotify"
    expect(stepsDone(status({ tools: { ffmpeg: true, ffprobe: false, deno: true } })).tools).toBe(false);
  });
  it('counts Downloads as done with Qobuz signed in or left out ("I don\'t have Qobuz")', () => {
    expect(stepsDone(status({ qobuz: true })).downloads).toBe(true);
    expect(stepsDone(status({ qobuz: false, qobuz_skipped: true })).downloads).toBe(true);
    expect(stepsDone(status({ qobuz: false, qobuz_skipped: false })).downloads).toBe(false);
  });
});

describe('first step', () => {
  it('opens at next_step', () => {
    expect(firstStep(fresh)).toBe('spotify');
    expect(firstStep({ ...fresh, next_step: 'tools' })).toBe('tools');
    expect(firstStep({ ...fresh, next_step: 'downloads' })).toBe('downloads');
  });
  it('skips Programs when every program is there', () => {
    expect(firstStep(complete)).toBe('spotify');
    expect(firstStep(status({ tools: { ffmpeg: false, ffprobe: false, deno: true } }))).toBe('tools');
  });
});

describe('reachable steps', () => {
  it('are the done steps and the first open one', () => {
    expect(reachable('spotify', fresh)).toBe(true);
    expect(reachable('tools', fresh)).toBe(true);
    expect(reachable('downloads', fresh)).toBe(false);
    expect(reachable('playlists', fresh)).toBe(false);
  });
  it('never wait for Your existing music, which opens as soon as the music folder is bound', () => {
    expect(reachable('existing', fresh)).toBe(true);
    expect(reachable('existing', noMusic)).toBe(false);
    // left undone, it locks nothing after it
    expect(reachable('tools', status({ existing: false }))).toBe(true);
    expect(reachable('spotify', status({ existing: false, complete: false }))).toBe(true);
  });
});

describe('Continue', () => {
  it('Programs: only when nothing is missing', () => {
    expect(nextRule('tools', fresh, toolsOk).allowed).toBe(true);
    expect(nextRule('tools', fresh, toolsMissing)).toEqual({ allowed: false,
      why: 'Install the missing programs, then Check again.' });
    expect(nextRule('tools', fresh, null).allowed).toBe(false);
  });
  it('Spotify and First playlist: only when that part is set up', () => {
    expect(nextRule('spotify', fresh, toolsOk).allowed).toBe(false);
    expect(nextRule('spotify', status({}), toolsOk).allowed).toBe(true);
    expect(nextRule('spotify', fresh, toolsOk).why).toBe("Connect Spotify, or choose I don't use Spotify.");
    expect(nextRule('spotify', { ...fresh, spotify_skipped: true }, toolsOk).allowed).toBe(true);
    expect(nextRule('playlists', fresh, toolsOk)).toEqual({ allowed: false, why: 'Add a playlist first.' });
    expect(nextRule('playlists', complete, toolsOk).allowed).toBe(true);
  });
  it('Downloads: Qobuz signed in, or I don\'t have Qobuz', () => {
    expect(nextRule('downloads', status({ qobuz: false }), toolsOk)).toEqual({ allowed: false,
      why: "Sign in to Qobuz, or choose I don't have Qobuz." });
    expect(nextRule('downloads', status({ qobuz: false, qobuz_skipped: true }), toolsOk).allowed).toBe(true);
    expect(nextRule('downloads', complete, toolsOk).allowed).toBe(true);
  });
});

describe('the one filled card on the Downloads step', () => {
  it('is Qobuz while Qobuz is required', () => {
    expect(filledCard(status({ qobuz: false }))).toBe('qobuz');
  });
  it('is none once Qobuz is signed in or left out (Continue is filled then)', () => {
    expect(filledCard(complete)).toBeNull();
    expect(filledCard(status({ qobuz: false, qobuz_skipped: true }))).toBeNull();
    expect(nextRule('downloads', status({ qobuz: false, qobuz_skipped: true }), null).allowed).toBe(true);
  });
  it('Your existing music: always, filled only once the step is done (Add folder… is the filled one before)', () => {
    const open = status({ existing: false });
    expect(nextRule('existing', open, null)).toEqual({ allowed: true, why: null });
    expect(continueFilled('existing', open, nextRule('existing', open, null))).toBe(false);
    const done = status({ existing: true, import_folders: 1 });
    expect(continueFilled('existing', done, nextRule('existing', done, null))).toBe(true);
    // a required step: filled whenever Continue is allowed
    expect(continueFilled('tools', fresh, nextRule('tools', fresh, toolsOk))).toBe(true);
    expect(continueFilled('tools', fresh, nextRule('tools', fresh, toolsMissing))).toBe(false);
  });
});

describe('a done setup opens Settings', () => {
  it('sends each step to its Settings row (the first playlist to Playlists)', () => {
    expect(doneRedirect(complete, 'tools')).toBe('/settings/programs');
    expect(doneRedirect(complete, 'existing')).toBe('/settings/folders');
    expect(doneRedirect(complete, 'spotify')).toBe('/settings/spotify');
    expect(doneRedirect(complete, 'downloads')).toBe('/settings/qobuz');
    expect(doneRedirect(complete, 'playlists')).toBe('/playlists');
  });
  it('sends #/setup to Settings', () => {
    expect(doneRedirect(complete, null)).toBe('/settings');
    expect(doneRedirect(status({ complete: false }), null)).toBeNull();
  });
  it('keeps an open setup in the guide', () => {
    expect(doneRedirect(fresh, 'spotify')).toBeNull();
    expect(doneRedirect(fresh, null)).toBeNull();
  });
  it("keeps a Spotify left out in the guide's Spotify step, where Settings sends it to make the app (plan stage 3, D1)", () => {
    const skipped = status({ spotify_app: false, spotify_login: false, spotify_skipped: true });
    expect(doneRedirect(skipped, 'spotify')).toBeNull();
    expect(doneRedirect(skipped, 'downloads')).toBe('/settings/qobuz');
    expect(doneRedirect(skipped, null)).toBe('/settings');
  });
});

describe('the step strip', () => {
  it('marks done steps, the current one, the next open one and the ones not reachable yet', () => {
    const s = status({ qobuz: false, playlists: false, complete: false });
    expect(stripSteps('downloads', s).map((x) => [x.key, x.state])).toEqual([
      ['music', 'done'], ['existing', 'open'], ['tools', 'done'], ['spotify', 'done'], ['downloads', 'current'],
      ['playlists', 'locked'],
    ]);
    expect(stripSteps('spotify', s).map((x) => x.state)).toEqual(['done', 'open', 'done', 'current', 'open', 'locked']);
    expect(stripSteps('existing', status({ existing: true })).map((x) => x.state).slice(0, 2)).toEqual(['done', 'current']);
  });
  it('shows a done step that is open on screen as current', () => {
    expect(stripSteps('spotify', complete)[3]).toEqual({ key: 'spotify', label: 'Spotify', state: 'current', done: true });
  });
});

describe('secrets are not kept', () => {
  it('takeSecret empties the input element', () => {
    const el = { value: 'my password' };
    expect(takeSecret(el)).toBe('my password');
    expect(el.value).toBe('');
  });
});

describe('the Terminal line under a missing program', () => {
  it('once per command: a missing ffmpeg and ffprobe show brew install ffmpeg under ffmpeg only', () => {
    const t: SetupTools = { ...toolsOk, tools: { ffmpeg: false, ffprobe: false, deno: false },
      missing: ['ffmpeg', 'ffprobe', 'deno'], hints: { ffmpeg: 'Run: brew install ffmpeg', ffprobe: 'brew install ffmpeg (ffprobe comes with it)',
        deno: 'brew install deno' } };
    expect(toolFixes(t)).toEqual({ ffmpeg: 'brew install ffmpeg', deno: 'brew install deno' });
  });
  it('nothing for a program that is there, or without a hint; the hint itself when it has no brew line', () => {
    expect(toolFixes(toolsOk)).toEqual({});
    expect(toolFixes(null)).toEqual({});
    expect(toolFixes(toolsMissing)).toEqual({ deno: 'brew install deno' });
    expect(toolFixes({ ...toolsMissing, hints: { deno: 'Install deno from deno.com' } })).toEqual({ deno: 'Install deno from deno.com' });
    expect(toolFixes({ ...toolsMissing, hints: {} })).toEqual({});
  });
});
