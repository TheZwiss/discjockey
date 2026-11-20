import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Ajv2020 from 'ajv/dist/2020';
import schema from '$fixtures/hub_events.schema.json';
import type { HubEvent } from '../events';
import type { JobEvents } from '../types';
import { createFakeBridge } from './bridge';
import { STREAMS, SYNC_LINES, SYNC_START_LINE } from './replay';
import { get } from 'svelte/store';
import { dispatch } from '../events';
import { _resetBridge, installBridge } from '../client';
import { hub, hubSyncRunning, refreshHub } from '../../stores/hub';
import { followRun, terminalSync } from '../../stores/follow';
import { run, type RunState } from '../../stores/run';
import { dismissJob, dismissedJobs, whichView, type SyncView } from '../../../pages/sync/view';

const JOB = 'job:00000c0d';
const validate = new Ajv2020({ strict: false }).compile(schema);

/** A fake of `scenario` with its clock under the test's control, and the events it sent */
function open(scenario: string) {
  const sent: HubEvent[] = [];
  const bridge = createFakeBridge(scenario, { emit: (e) => sent.push(e) });
  const read = async (after: number) => {
    const r = await bridge.job_events(JOB, after);
    if (!r.ok) throw new Error(`job_events refused: ${r.message}`);
    return r as { ok: true } & JobEvents;
  };
  /** every line from the start, as the window reads them one answer after the other */
  const readAll = async () => {
    let after = 0;
    const lines: HubEvent[] = [];
    for (;;) {
      const r = await read(after);
      lines.push(...(r.events as HubEvent[]));
      if (r.done || r.next === after) return { lines, last: r };
      after = r.next;
    }
  };
  const holder = async () => (await bridge.job_status() as { console: { line: string | null; text: string } | null }).console;
  return { bridge, sent, read, readAll, holder };
}
const tick = (ms: number) => vi.advanceTimersByTimeAsync(ms);
const sync = STREAMS.sync.slice(SYNC_START_LINE - 1);

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

describe('the Terminal sync a window can follow, in the fake backend', () => {
  it('console:sync-live: advances with the clock, ends done, then sends JobFinished and ConsoleBusy(false)', async () => {
    const f = open('console:sync-live');
    expect(await f.holder()).toMatchObject({ text: 'Sync running in the Terminal' });   // it has not said how far it is yet
    const first = await f.read(0);
    expect(first).toMatchObject({ status: 'running', done: false });
    expect(first.events.length).toBeLessThan(sync.length);
    expect(first.events[0]).toMatchObject({ type: 'JobStarted', job_id: JOB, kind: 'sync' });
    await tick(5000);
    const later = await f.read(0);
    expect(later.events.length).toBeGreaterThan(first.events.length);
    expect((await f.read(later.next)).events.length).toBeGreaterThanOrEqual(0);
    expect(await f.holder()).toMatchObject({ line: expect.stringMatching(/^\d+ of \d+$/) });
    expect(f.sent.some((e) => e.type === 'ConsoleBusy' && e.running && /^\d+ of \d+$/.test(e.line ?? ''))).toBe(true);
    expect(f.sent.some((e) => e.type === 'JobFinished')).toBe(false);

    await tick(10 * 60_000);
    const { lines, last } = await f.readAll();
    expect(lines).toHaveLength(sync.length);
    expect(lines.at(-1)).toMatchObject({ type: 'JobFinished', job_id: JOB });
    expect(last).toMatchObject({ status: 'done', done: true });
    const end = f.sent.slice(-2);
    expect(end[0]).toMatchObject({ type: 'JobFinished', job_id: JOB, kind: 'sync' });
    expect(end[1]).toMatchObject({ type: 'ConsoleBusy', running: false });
    expect(await f.holder()).toBeNull();
    for (const e of lines) expect(validate(e), `${JSON.stringify(e)} ${JSON.stringify(validate.errors)}`).toBe(true);
  });

  it('console:sync-reading is frozen before RunStarted, and says no progress line', async () => {
    const f = open('console:sync-reading');
    await tick(60_000);
    const { lines, last } = await f.readAll();
    expect(lines.length).toBeGreaterThan(0);
    expect(lines.some((e) => e.type === 'RunStarted')).toBe(false);
    expect(lines[0]).toMatchObject({ type: 'JobStarted', job_id: JOB });
    expect(last).toMatchObject({ status: 'running', done: false });
    expect(await f.holder()).toMatchObject({ line: null, text: 'Sync running in the Terminal' });
  });

  it('console:sync-running is frozen at the second download Progress of its recorded sync, with its progress line', async () => {
    const f = open('console:sync-running');
    const a = await f.readAll();
    await tick(60_000);
    const b = await f.readAll();
    expect(b.lines).toHaveLength(SYNC_LINES.downloading - SYNC_START_LINE + 1);
    expect(b.lines).toEqual(a.lines);
    expect(b.lines.at(-1)).toMatchObject({ type: 'Progress', track_id: 't5', step: 'download' });
    expect(b.lines.some((e) => e.type === 'ActionStarted')).toBe(true);
    expect(await f.holder()).toMatchObject({ line: expect.stringMatching(/^\d+ of \d+$/) });
  });

  it('console:sync-ended serves the whole file at once, and sends the end once it was loaded', async () => {
    const f = open('console:sync-ended');
    await tick(60_000);
    expect(f.sent).toEqual([]);                                   // nobody has looked yet
    const r = await f.read(0);
    expect(r.events).toHaveLength(sync.length);
    expect(r).toMatchObject({ status: 'done', done: true, next: sync.length });
    await tick(1);
    expect(f.sent.map((e) => e.type)).toEqual(['JobFinished', 'ConsoleBusy']);
    expect(f.sent[1]).toMatchObject({ running: false });
    expect(await f.holder()).toBeNull();
    await f.read(0);
    await tick(1000);
    expect(f.sent).toHaveLength(2);                               // sent once
  });

  it('answers at most 500 lines at a time and counts positions in lines', async () => {
    const f = open('console:sync-ended');
    const r = await f.read(5);
    expect(r.events[0]).toEqual((await f.read(0)).events[5]);
    expect(r.next).toBe(sync.length);
    expect(await f.read(sync.length + 50)).toMatchObject({ events: [], next: sync.length + 50, done: true });
  });

  it('every scenario answers the sample job, and any other id is refused as unknown_id', async () => {
    const f = open('normal');
    const r = await f.read(0);
    expect(r.events[0]).toMatchObject({ type: 'JobStarted', job_id: JOB });
    for (const call of [() => f.bridge.job_events('job:00000001', 0), () => f.bridge.stop('job:00000001')]) {
      expect(await call()).toMatchObject({ ok: false, kind: 'bad_args', reason: 'unknown_id' });
    }
  });

  it('stop(job) ends the stream as the own replay\'s Stop does: stopping at once, then stopped', async () => {
    const f = open('console:sync-live');
    await tick(8000);
    expect(await f.bridge.stop(JOB)).toEqual({ ok: true, stopped: true });
    expect((await f.read(0)).status).toMatch(/stopping|done/);
    await tick(60_000);
    const { lines, last } = await f.readAll();
    expect(last).toMatchObject({ status: 'done', done: true });
    expect(lines.length).toBeLessThan(sync.length);
    expect(lines.at(-2)).toMatchObject({ type: 'RunFinished', exit_code: 130 });   // what the own replay's Stop ends with
    expect(lines.at(-1)).toMatchObject({ type: 'JobFinished', job_id: JOB, kind: 'sync' });
    expect(f.sent.at(-1)).toMatchObject({ type: 'ConsoleBusy', running: false });
    expect(await f.bridge.stop(JOB)).toEqual({ ok: true, stopped: false });   // over: nothing to stop
    expect(await f.bridge.stop()).toEqual({ ok: true, stopped: false });      // the window's own job is another thing
  });
});

describe('the Sync page on a Terminal sync of the fake (console:sync-live), through the window\'s stores', () => {
  afterEach(() => { _resetBridge(); delete (globalThis as any).window; });

  it('routes to its live view, follows it track by track, then to its end screen, whose run is filed', async () => {
    (globalThis as any).window = new EventTarget();   // the bridge's window (node has no DOM)
    _resetBridge();
    const f = createFakeBridge('console:sync-live', { speed: 1, emit: dispatch });
    installBridge(f);
    await refreshHub();
    const views: SyncView[] = [];
    let sync = get(terminalSync), state: RunState | null = null;
    expect(sync).toEqual({ job: JOB, running: true });
    const offSync = terminalSync.subscribe((t) => { sync = t; });
    const offRun = followRun(JOB).subscribe((s) => { state = s; });   // the page's subscription keeps it polling
    const look = () => {
      const v = whichView({ own: get(run), hubSyncRunning: get(hubSyncRunning), dismissed: get(dismissedJobs),
        terminal: sync && { sync, run: state! }, newest: get(hub).last_sync?.job ?? null });
      if (JSON.stringify(v) !== JSON.stringify(views.at(-1))) views.push(v);
      return v;
    };
    expect(look()).toEqual({ view: 'live', source: 'terminal' });
    await tick(4000);
    expect(look()).toEqual({ view: 'live', source: 'terminal' });
    expect(state!).toMatchObject({ job_id: JOB, job_kind: 'sync' });
    expect(['running', 'preparing']).toContain(state!.phase);
    for (let i = 0; i < 400 && !state!.results.length; i++) await tick(1000);
    expect(state!.results.length).toBeGreaterThan(0);                  // a track done, the next one in work
    expect(look()).toEqual({ view: 'live', source: 'terminal' });
    for (let i = 0; i < 400 && look().view === 'live'; i++) await tick(5000);
    const end = look();
    expect(end).toMatchObject({ view: 'end', source: 'terminal' });
    expect(views.map((v) => v.view)).toEqual(['live', 'end']);   // never the plan in between
    const run_id = (end as { run_id: string | null }).run_id;
    expect(run_id).toMatch(/^\d{4}-\d\d-\d\d_\d{6}$/);
    expect(await f.run(run_id!)).toMatchObject({ ok: true });
    expect(get(terminalSync)).toEqual({ job: JOB, running: false });
    dismissJob(JOB);
    expect(look()).toEqual({ view: 'before' });
    offRun(); offSync();
  });
});
