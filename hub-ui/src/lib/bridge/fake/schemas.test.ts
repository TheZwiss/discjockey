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
const SAMPLE_ARGS: Record<string, unknown[]> = {
  todo: ['all', true], track: ['t2'], missing_files_preview: [['t1', 't2'], 'download_again'],
  hide: ['t2', true], never_download: ['t2', true], upgrade: [['t2'], 'same_track'], undo_upgrade: [['t2']],
  upgrade_all: [], rekordbox_checked: [['t2']], missing_files: [['t1', 't2'], 'download_again'],
  add_bought_file: ['t2'], use_candidate: ['t2', CANDIDATE],
  use_link: ['t2', 'https://www.youtube.com/watch?v=abcdefghijk'], reject_current: ['t2'],
};
/** Why a mapped method cannot be called with fixed arguments. */
const NO_SAMPLE: Record<string, string> = {};

const scenarios = (): string[] => [...SCENARIOS, ...Object.keys(pageScenarios())];

describe('the schema checker', () => {
  const row = {
    track_id: 't1', artist: 'A', title: 'T', folder: 'House', duration_s: 268, status: 'lossless', quality: 'lossless',
    quality_label: 'LOSSLESS', cutoff_hz: null, source: 'qobuz', source_name: 'Qobuz', in_playlists: true, own: false,
    hidden: false, upgrade_ready: false, path: null, added: '2026-10-13T22:15:00', cover_url: null,
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
type Fake = { bridge: Record<string, (...a: unknown[]) => Promise<Record<string, unknown>>>; events: HubEvent[] };
function openFake(scenario: string): Fake {
  const events: HubEvent[] = [];
  const bridge = createFakeBridge(scenario, { speed: 1000, emit: (e) => events.push(e) }) as unknown as Fake['bridge'];
  return { bridge, events };
}

type Maps = { answers: Record<string, string>; results: Record<string, string> };

/** Calls `method` on a fake of `scenario`; the problems of its answer against `maps.answers[method]`, or, for a job,
 *  of its ok result against `maps.results[kind]` ("" for a problem answer, which is the Fail shape's). */
async function fakeProblems(method: string, args: unknown[], fake: Fake, maps: Maps): Promise<string> {
  const { bridge, events } = fake;
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
    for (const scenario of scenarios()) {
      const fake = openFake(scenario);
      for (const method of sampled) {
        expect(await fakeProblems(method, SAMPLE_ARGS[method], fake, { answers, results }), `${method} in ${scenario}`).toBe('');
      }
    }
  }, 300_000);

  it('finds the mismatch of a wrong shape for a read and for a job (the loop works)', async () => {
    const wrong = { answers: { library: 'Empty' }, results: { hide: 'Freshness' } };
    expect(await fakeProblems('library', ['all', null, '', 'all', 'artist'], openFake('normal'), wrong)).not.toBe('');
    const job = await fakeProblems('hide', ['t2', true], openFake('normal'), wrong);   // the job's result is not a Freshness
    expect(job).not.toBe('');
    expect(job).not.toMatch(/never finished|no result shape/);
  });
});
