// T6, the fake's half (issue 39, phase 2): what the fake bridge answers, and the result of every job it finishes, must
// validate against the schema generated from discjockey/hub/shapes/ (schemas.gen.json), so the fake cannot show a field
// the engine lacks. The engine's half is the tests' check mode (discjockey/hub/shapes/__init__.py, note_answer).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Ajv2020 from 'ajv/dist/2020';
import schemas from '../schemas.gen.json';
import { CONTRACT_METHODS } from '../contract';
import type { HubEvent } from '../events';
import { SCENARIOS, createFakeBridge, pageScenarios } from './bridge';

const defs = (schemas as { $defs: Record<string, unknown> }).$defs;
const answers = (schemas as { answers: Record<string, string> }).answers;
const results = (schemas as { results: Record<string, string> }).results;
const ajv = new Ajv2020({ strict: false, allErrors: true });
const validators = new Map<string, ReturnType<Ajv2020['compile']>>();

/** The problems of `value` against the shape or alias `name` ("" when it fits). */
function problems(name: string, value: unknown): string {
  if (!validators.has(name)) validators.set(name, ajv.compile({ $ref: `#/$defs/${name}`, $defs: defs }));
  const check = validators.get(name)!;
  return check(value) ? '' : ajv.errorsText(check.errors);
}

const contract = new Set<string>(CONTRACT_METHODS);
/** The mapped methods of the window's contract (a cli-first method like `freshness` has no fake). */
const mapped = Object.keys(answers).filter((m) => contract.has(m));

/** The arguments each mapped method is called with (a read with no argument needs none). */
const CANDIDATE = {
  source: 'qobuz', id: 'q9', title: 'Get Naughty', artist: 'Armin Hermann', duration_s: 268, url: null, isrc: null, album: null,
  label: null, image_url: null, key: 'qobuz:q9', source_name: 'Qobuz', length_diff_s: 0, can_preview: false, score: 1,
  matches: true, length_ok: true, current: false, rejected: false,
};
// The methods of one scenario share one fake, in this order: reads first, then the writes that keep the songs'
// files, then the ones that replace or reject a file (a later call sees what an earlier one did).
type Bridge = Record<string, (...a: unknown[]) => Promise<Record<string, unknown>>>;
/** A method's arguments: fixed, or taken from the fake's own data (a version the fake hands out, a line it holds). */
type Args = unknown[] | ((bridge: Bridge) => Promise<unknown[]>);
const LINES = [{ folder: 'Hard_Bounce', link: 'https://open.spotify.com/playlist/0DiscjockeyExampleList', enabled: true }];
type Dup = { group_id: string; files: { file_id: number; path: string }[] };
/** The first duplicate group To-do shows, or a made-up one the fake refuses. */
async function duplicate(b: Bridge): Promise<Dup> {
  const todo = (await b.todo('duplicate', true)) as { groups?: { items?: { pair?: Dup; group: string }[] }[] };
  return todo.groups?.flatMap((g) => g.items ?? []).find((i) => i.group === 'duplicate' && i.pair)?.pair ?? { group_id: 'dup:0,0', files: [{ file_id: 0, path: '' }] };
}
/** The first AIFF batch To-do shows (a batch to check), or 1. */
async function batchId(b: Bridge): Promise<number> {
  const todo = (await b.todo('rekordbox_check', true)) as { groups?: { items?: { batch?: { id: number } | null }[] }[] };
  return todo.groups?.flatMap((g) => g.items ?? []).find((i) => i.batch)?.batch?.id ?? 1;
}
const SAMPLE_ARGS: Record<string, Args> = {
  dashboard: [], sidebar: [], library: ['all', null, '', 'all', null], sync_preview: [], job_status: [], playlists: [],
  limits: ['qobuz'], limits_what_if: ['qobuz', 60, 0], runs: [], run: ['last'], spectrum: ['t1', 'current'],
  set_favourites: [['playlist:0DiscjockeyExampleList']],
  set_crate_shown: ['/Users/you/Music/Rekordbox Library/Hardtechno', true],
  set_crates_shown: [['/Users/you/Music/Rekordbox Library/Hardtechno'], null],
  stop_refresh: [], stop: [], stop_sign_in: [], refresh: [false], start_sync: [[]], save_limits: ['qobuz', 60, 0],
  mark_warnings_seen: ['qobuz'], rescan_library: [],
  todo: ['all', true], track: ['t2'], missing_files_preview: [['t1', 't2'], 'download_again'],
  hide: ['t2', true], never_download: ['t2', true], upgrade: [['t2'], 'same_track'], undo_upgrade: [['t2']],
  upgrade_all: [], rekordbox_checked: [['t2']], missing_files: [['t1', 't2'], 'download_again'],
  add_bought_file: ['t2'], use_candidate: ['t2', CANDIDATE],
  use_link: ['t2', 'https://www.youtube.com/watch?v=abcdefghijk'], reject_current: ['t2'],
  // E7d: setup, settings, the music folder, watched folders and the import, tidy-up, reads with network, AIFF
  setup_status: [], check_music_folder: ['/Users/you/Music/Discjockey'], retry_music_folder: [], rekordbox_status: [],
  app_update: [], downloads_view: [], find_logins: ['youtube'], setup_check_tools: [], watched_folders: [],
  check_import_folder: ['/Volumes/Example Drive/Music'], removal_preview: [2], tidy_preview: [], move_batches: [],
  undo_preview: [1], search_candidates: ['t2'], preview: ['t2', { ...CANDIDATE, source: 'youtube_music', can_preview: true }],
  add_playlist: ['https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M'], preview_playlist_change: [LINES],
  aiff_plan: [{ kind: 'lossless', view: 'all', key: null }], setup_skip_import: [],
  tidy_up: async (b) => {   // the files the fake's own tidy-up ticks
    const rows = ((await b.tidy_preview()) as { rows?: { ticked: boolean; file_id: number; from_path: string }[] }).rows;
    return [(rows ?? []).filter((r) => r.ticked).map((r) => [r.file_id, r.from_path])];
  },
  undo_moves: [1], start_import: [], answer_same_song: ['t7', 'own:211', true],
  supersede_duplicate: async (b) => { const d = await duplicate(b); return [d.group_id, d.files[d.files.length - 1].file_id, d.files.map((f) => f.path)]; },
  keep_duplicates: async (b) => { const d = await duplicate(b); return [d.group_id, d.files.map((f) => f.path)]; },
  convert: [['t2'], 'library'], rename: [['t2']], make_aiff: [{ kind: 'lossless', view: 'all', key: null }],
  batch_resume: async (b) => [await batchId(b)], batch_undo: async (b) => [await batchId(b)],
  save_playlists: async (b) => [LINES, ((await b.playlists()) as { version: string }).version, null],
  set_read_liked_music: [true], add_liked_music: [], set_auto_upgrade: [true],
  setup_account: ['youtube', 'chrome', null], account_sign_in: ['soundcloud', 'chrome', null], qobuz_check_login: [],
  setup_save_client_id: ['0123456789abcdef0123456789abcdef'], setup_spotify_login: [],
  setup_qobuz_login: ['dj@example.com', 'secret'], update_tools: [], rollback_tools: [],
  add_watched_folder: ['/Volumes/Example Drive/Old'], remove_watched_folder: [2], setup_forget_account: ['youtube'],
  spotify_sign_out: [], setup_skip_qobuz: [], setup_skip_spotify: [], set_music_folder: ['/Users/you/Music/Discjockey'],
  // E7e: the reads that answer `{}` and belong to no area
  show_in_finder: ['t2', 'current'], reveal: ['Library/House'], open_licenses: [], open_privacy_settings: [],
  open_external: ['https://example.com/'],
  open_report: async (b) => [((await b.runs()) as { runs?: { run_id: string }[] }).runs?.[0]?.run_id ?? '2026-01-01_000000'],
};
/** Why a mapped method cannot be called with fixed arguments. */
const NO_SAMPLE: Record<string, string> = {};

/** A scenario that holds one answer back for ever, to show the page's loading state (the fake's own, by design). */
const HELD: Record<string, string[]> = {
  'limits:loading': ['limits'],
  // a waiting sign-in and a running tool update never finish, to show the busy line
  'settings:yt-waiting': ['account_sign_in'], 'setup:downloads-waiting': ['account_sign_in'],
  'setup:downloads-cancelled': ['account_sign_in'], 'setup:spotify-waits': ['setup_spotify_login'],
  'settings:tools-updating': ['update_tools', 'rollback_tools'], 'settings:tools-going-back': ['update_tools', 'rollback_tools'],
};

const scenarios = (): string[] => [...SCENARIOS, ...Object.keys(pageScenarios())];

describe('the schema checker', () => {
  const row = {
    track_id: 't1', artist: 'A', title: 'T', folder: 'House', duration_s: 268, status: 'lossless', quality: 'lossless',
    quality_label: 'LOSSLESS', cutoff_hz: null, source: 'qobuz', source_name: 'Qobuz', in_playlists: true, own: false,
    hidden: false, upgrade_ready: false, path: null, added: '2026-10-13T22:15:00', cover_url: null,
    rev: '0123456789',
  };
  it('accepts a TrackRow and fails a broken one', () => {
    expect(problems('TrackRow', row)).toBe('');
    expect(problems('TrackRow', { ...row, quality: 'purple' })).not.toBe('');
    expect(problems('TrackRow', { ...row, extra: 1 })).not.toBe('');
    const { artist: _artist, ...without } = row;
    expect(problems('TrackRow', without)).not.toBe('');
  });
  it('knows an alias, a nested shape and an optional key', () => {
    expect(problems('Quality', 'weak')).toBe('');
    expect(problems('Quality', 'bad')).not.toBe('');
    const fail = { ok: false, kind: 'busy', message: 'm', next: [{ run: 'x', why: 'y' }] };
    expect(problems('Fail', fail)).toBe('');
    expect(problems('Fail', { ...fail, next: [{ run: 'x' }] })).not.toBe('');
  });
  it('every mapped method has a sample or says why not, and neither list holds a stranger', () => {
    for (const m of mapped) expect(m in SAMPLE_ARGS || m in NO_SAMPLE, m).toBe(true);
    for (const m of [...Object.keys(SAMPLE_ARGS), ...Object.keys(NO_SAMPLE)]) expect(mapped, m).toContain(m);
  });
});

/** The fake's clock is stepped by `STEP_MS` up to `STEPS` times until a call has answered and its job has finished. */
const STEP_MS = 1_000;
const STEPS = 600;

/** One fake of a scenario and the events it sent: building one is the slow part, so a scenario's methods share it. */
type Fake = { bridge: Bridge; events: HubEvent[] };
function openFake(scenario: string): Fake {
  const events: HubEvent[] = [];
  const bridge = createFakeBridge(scenario, { speed: 1000, emit: (e) => events.push(e) }) as unknown as Bridge;
  return { bridge, events };
}

type Maps = { answers: Record<string, string>; results: Record<string, string> };

/** Calls `method` on a fake of `scenario`; the problems of its answer against `maps.answers[method]`, or, for a job,
 *  of its ok result against `maps.results[kind]` ("" for a problem answer, which is the Fail shape's). */
async function fakeProblems(method: string, how: Args, fake: Fake, maps: Maps): Promise<string> {
  const { bridge, events } = fake;
  const args = typeof how === 'function' ? await how(bridge) : how;
  const promise = bridge[method](...args);
  let first: Record<string, unknown> | undefined;
  void promise.then((v) => { first = v; });
  // Step the clock until the answer is there (a call does not run the fake's idle timers for ten virtual minutes).
  for (let t = 0; t < STEPS && !first; t++) await vi.advanceTimersByTimeAsync(STEP_MS);
  if (!first) return `${method}: no answer`;
  const { ok, ...answer } = first;
  if (ok !== true) return '';
  const keys = Object.keys(answer);
  if (keys.length === 1 && keys[0] === 'job_id') {   // a J method: follow the job to its JobFinished
    const finished = () => events.find((e) => e.type === 'JobFinished' && e.job_id === answer.job_id);
    for (let t = 0; t < STEPS && !finished(); t++) await vi.advanceTimersByTimeAsync(STEP_MS);
    const done = finished();
    if (done?.type !== 'JobFinished') return `${method}: the job never finished`;
    if (!done.ok || done.result == null) return '';
    const name = maps.results[done.kind];
    return name ? problems(name, done.result) : `job kind ${done.kind} has no result shape`;
  }
  return problems(maps.answers[method], answer);
}

describe('the fake bridge answers fit their schemas', () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it('every mapped method with a sample, in every scenario', async () => {
    const sampled = Object.keys(SAMPLE_ARGS).filter((m) => mapped.includes(m));
    const found: string[] = [];
    for (const scenario of scenarios()) {
      const fake = openFake(scenario);
      for (const method of sampled.filter((m) => !HELD[scenario]?.includes(m))) {
        const bad = await fakeProblems(method, SAMPLE_ARGS[method], fake, { answers, results });
        if (bad) found.push(`${method} in ${scenario}: ${bad}`);
      }
    }
    expect(found).toEqual([]);
  }, 300_000);

  it('finds the mismatch of a wrong shape for a read and for a job (the loop works)', async () => {
    const wrong = { answers: { library: 'Empty' }, results: { hide: 'Freshness' } };
    expect(await fakeProblems('library', ['all', null, '', 'all', 'artist'], openFake('normal'), wrong)).not.toBe('');
    const job = await fakeProblems('hide', ['t2', true], openFake('normal'), wrong);   // the job's result is not a Freshness
    expect(job).not.toBe('');
    expect(job).not.toMatch(/never finished|no result shape/);
  });
});
