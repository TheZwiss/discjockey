import { describe, expect, it } from 'vitest';
import syncRaw from '$fixtures/hub_events_sync.jsonl?raw';
import stoppedRaw from '$fixtures/hub_events_stopped.jsonl?raw';
import type { HubEvent } from '../bridge/events';
import { ACTIVE_PHASES, EMPTY_RUN, reduceRun, runFromSnapshot, type RunState } from './run';
import { JobRecord, lineOf } from '../bridge/fake/replay';

const lines = (raw: string): HubEvent[] => raw.split('\n').filter((l) => l.trim()).map((l) => JSON.parse(l));
const sync = lines(syncRaw);
const stopped = lines(stoppedRaw);
const feed = (evs: HubEvent[], now = 1000) => evs.reduce<RunState>((s, e) => reduceRun(s, e, now), EMPTY_RUN);
const planned = (sync.find((e) => e.type === 'RunStarted') as Extract<HubEvent, { type: 'RunStarted' }>).actions;

describe('reduceRun with the recorded sync', () => {
  const s = feed(sync);
  it('collects the 5 results in order', () => {
    expect(s.results.map((r) => r.result.section)).toEqual(['new_lossless', 'missing', 'new_not_lossless', 'errors',
      'upgrade_ready']);
    expect(s.results[3].result.error_kind).toBe('network');
  });
  it('keeps the Qobuz count, the run end and the phase', () => {
    expect(s.qobuz).toEqual({ used: 2, allowance: 80 });
    expect(s.run_finished?.exit_code).toBe(1);
    expect(s.phase).toBe('finished');
    expect(s.job_id).toBe(2);
    expect(s.planned).toHaveLength(5);
    expect(planned).toHaveLength(5);
  });
  it('ignores the refresh job and drops debug messages', () => {
    expect(s.job_kind).toBe('sync');
    expect(s.messages.map((m) => m.text)).toEqual(['Reading your playlists · 2 of 2 · Powertrance',
      'Looking up the bitrate of 1 older download...']);
  });
  it('is in the protection pause before Get Naughty (its SourceChosen comes just before the pause)', () => {
    const pause = lineOf(sync, (e) => e.type === 'Waiting' && e.kind === 'between');
    const before = feed(sync.slice(0, pause - 1));
    expect(sync[pause - 2].type).toBe('SourceChosen');
    expect(before.source?.source).toBe('qobuz');
    const inPause = feed(sync.slice(0, pause));
    expect(inPause.waiting?.kind).toBe('between');
    expect(inPause.current?.track.title).toBe('Get Naughty');
    expect(inPause.source?.title).toBe('Get Naughty');
    expect(inPause.index).toBe(planned.length);
    const id = inPause.current?.track_id;
    const after = feed(sync.slice(0, lineOf(sync, (e) => e.type === 'Progress' && e.track_id === id, 1)));
    expect(after.waiting).toBeNull();
    expect(after.step).toBe('download');
  });
  it('notes when the last track started', () => {
    const i = sync.findIndex((e) => e.type === 'ActionStarted');
    expect(sync.slice(0, i).reduce<RunState>((s, e) => reduceRun(s, e, 500), EMPTY_RUN).last_started_at).toBeNull();
    expect(reduceRun(feed(sync.slice(0, i)), sync[i], 700).last_started_at).toBe(700);
  });
  it('ignores Progress for another track', () => {
    const at = feed(sync.slice(0, 62));
    const other = reduceRun(at, { type: 'Progress', track_id: 'someone-else', step: 'download', done: 1, total: 2,
      unit: 'bytes' }, 2000);
    expect(other).toBe(at);
  });
  it('smooths the download rate from the last two Progress events', () => {
    // "non stop" downloads 90173 bytes a sample; its first sample is at sync[i]
    const i = lineOf(sync, (e) => e.type === 'Progress' && e.step === 'download' && e.done === 90173) - 1;
    let s2 = feed(sync.slice(0, i));
    s2 = reduceRun(s2, sync[i], 1000);
    expect(s2.progress?.rate).toBeNull();
    s2 = reduceRun(s2, sync[i + 1], 2000);
    expect(s2.progress?.rate).toBeCloseTo(90173, 0);
    s2 = reduceRun(s2, sync[i + 2], 2500);
    expect(s2.progress?.rate).toBeCloseTo(0.3 * 180346 + 0.7 * 90173, 0);
  });
  it('events of another job are ignored', () => {
    const fin = reduceRun(feed(sync.slice(0, 65)), { type: 'JobFinished', job_id: 99, kind: 'hide', ok: true,
      problem: null, message: '', result: null }, 1);
    expect(fin.phase).toBe('running');
  });
  it('a failed job ends in failed with its problem', () => {
    const f = reduceRun(feed(sync.slice(0, 65)), { type: 'JobFinished', job_id: 2, kind: 'sync', ok: false,
      problem: 'crashed', message: 'x', result: null }, 1);
    expect(f.phase).toBe('failed');
    expect(f.job_finished?.problem).toBe('crashed');
  });
});

describe('the stopped stream', () => {
  it('ends with exit 130 and 2 results', () => {
    const s = feed(stopped);
    expect(s.run_finished?.exit_code).toBe(130);
    expect(s.results).toHaveLength(2);
    expect(s.phase).toBe('finished');
  });
});

describe('runFromSnapshot', () => {
  const snapOf = (evs: HubEvent[]) => {
    const start = evs.find((e) => e.type === 'JobStarted' && e.kind === 'sync') as Extract<HubEvent, { type: 'JobStarted' }>;
    const rec = new JobRecord(start.job_id, 'sync', null, '2026-10-16T14:11:00');
    for (const e of evs.slice(evs.indexOf(start))) rec.record(e);
    return rec.snapshot();
  };
  const strip = (s: RunState) => ({ ...s, messages: [], started_at: null });
  for (const n of [11, 35, 65, 88, 105]) {
    it(`gives the same state as replaying the first ${n} events`, () => {
      expect(strip(runFromSnapshot(snapOf(sync.slice(0, n)), 1000))).toEqual(strip(feed(sync.slice(0, n))));
    });
  }
  it('restores the usage of every service, not only the last one that reported', () => {
    const usage = (service: string, used: number, allowance: number): HubEvent => ({ type: 'AccountUsage', service, used, allowance });
    const evs = [...sync.slice(0, 11), usage('qobuz', 3, 80), usage('youtube', 5, 20), usage('qobuz', 4, 80), usage('youtube', 6, 20)];
    const s = runFromSnapshot(snapOf(evs), 1000);
    expect(s.usage).toEqual({ qobuz: { used: 4, allowance: 80 }, youtube: { used: 6, allowance: 20 } });
    expect(s.qobuz).toEqual({ used: 4, allowance: 80 });
    expect(strip(s)).toEqual(strip(feed(evs)));
  });
  it('a finished job is finished', () => {
    expect(runFromSnapshot(snapOf(sync), 1000).phase).toBe('finished');
  });
  it('a job that is stopping says so', () => {
    const snap = { ...snapOf(sync.slice(0, 65)), stopping: true };
    expect(runFromSnapshot(snap, 1000).phase).toBe('stopping');
  });
});

describe('the sync\'s Auto-upgrade phase (issue 33 stage C)', () => {
  const batch = (done: number, total: number, name: string | null): HubEvent =>
    ({ type: 'BatchProgress', batch_id: 4, done, total, track_id: name ? 't1' : null, name });
  // the recorded sync up to its last ActionFinished: the run's actions are over, the phase starts
  const afterActions = sync.slice(0, sync.findIndex((e) => e.type === 'RunFinished'));

  it('goes upgrading with where the batch is, and stays there until the run ends', () => {
    const s = feed([...afterActions, batch(0, 3, 'Artist - One')]);
    expect(s.phase).toBe('upgrading');
    expect(s.upgrade).toEqual({ batch_id: 4, done: 0, total: 3, name: 'Artist - One' });
    const last = reduceRun(reduceRun(s, batch(3, 3, null), 2000), sync.find((e) => e.type === 'RunFinished')!, 3000);
    expect(last.phase).toBe('upgrading');
    expect(last.upgrade).toEqual({ batch_id: 4, done: 3, total: 3, name: null });
    const done = reduceRun(last, sync.find((e) => e.type === 'JobFinished' && e.kind === 'sync')!, 4000);
    expect(done.phase).toBe('finished');
  });
  it('a Stop in the phase stays stopping while the batch goes on', () => {
    const s = reduceRun({ ...feed([...afterActions, batch(1, 3, 'Artist - Two')]), phase: 'stopping' }, batch(2, 3, 'Artist - Three'), 2000);
    expect(s.phase).toBe('stopping');
    expect(s.upgrade?.done).toBe(2);
  });
  it('is part of the active phases and ignores the batch events of any other job', () => {
    expect(ACTIVE_PHASES).toContain('upgrading');
    expect(reduceRun(EMPTY_RUN, batch(0, 2, 'x'), 1)).toBe(EMPTY_RUN);
    const other = reduceRun(EMPTY_RUN, { type: 'JobStarted', job_id: 9, kind: 'use_candidate', track_id: 't1', batch_kind: null }, 1);
    expect(reduceRun(other, batch(0, 2, 'x'), 2).upgrade).toBeNull();
  });
  it('comes back from a reload with the same state', () => {
    const evs = [...afterActions, batch(1, 3, 'Artist - Two')];
    const start = evs.find((e) => e.type === 'JobStarted' && e.kind === 'sync') as Extract<HubEvent, { type: 'JobStarted' }>;
    const rec = new JobRecord(start.job_id, 'sync', null, '2026-10-16T14:11:00');
    for (const e of evs.slice(evs.indexOf(start))) rec.record(e);
    const again = runFromSnapshot(rec.snapshot(), 1000);
    expect(again.phase).toBe('upgrading');
    expect(again.upgrade).toEqual({ batch_id: 4, done: 1, total: 3, name: 'Artist - Two' });
  });
});
