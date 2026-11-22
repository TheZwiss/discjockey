import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { dispatch, type HubEvent } from '../bridge/events';
import type { RunState } from './run';
import { liveMessage } from '../../pages/sync/results';

// the bridge is a stub: `job_events` answers what a test scripts; the hub's own reads (after a JobFinished) find nothing
const calls: [string, number][] = [];
let script: ((jobId: string, after: number) => unknown)[] = [];
vi.mock('../bridge/client', () => {
  const nothing = async () => ({ ok: false, kind: 'crashed', message: '' });
  return {
    api: {
      job_events: async (jobId: string, after: number) => { calls.push([jobId, after]); return (script.shift() ?? (() => answer([], after)))(jobId, after); },
      job_status: nothing, setup_status: nothing, sidebar: nothing, app_update: nothing,
    },
    onNoLibrary: () => {},
  };
});
const { followRun, shownSync, terminalSync } = await import('./follow');
const { run } = await import('./run');

let n = 0;
const nextId = () => `job:${(++n).toString(16).padStart(8, '0')}`;
const answer = (events: unknown[], next: number, status = 'running', done = false, end: HubEvent | null = null) =>
  ({ ok: true, events, next, status, done, finished: done ? end : null });
const started = (job_id: string): HubEvent => ({ type: 'JobStarted', job_id, kind: 'sync', track_id: null, batch_kind: null });
const runStarted = (total = 2): HubEvent => ({ type: 'RunStarted', total, actions: [] });
const action = (index: number): HubEvent => ({ type: 'ActionStarted', index, total: 2,
  action: { kind: 'acquire', track_id: `t${index}`, title: 'Title', artist: 'Artist' } as never });
const finished = (job_id: string, problem: string | null = null): HubEvent => ({ type: 'JobFinished', job_id, kind: 'sync', ok: problem === null,
  problem: problem as never, message: '', result: null });
const message = (text: string): HubEvent => ({ type: 'Message', level: 'info', text });

/** Subscribes and records every state the store publishes. */
function watch(id: string) {
  const seen: RunState[] = [];
  const off = followRun(id).subscribe((s) => seen.push(s));
  return { seen, off, last: () => seen[seen.length - 1] };
}
const tick = (ms = 0) => vi.advanceTimersByTimeAsync(ms);

beforeEach(() => { vi.useFakeTimers(); calls.length = 0; script = []; });
afterEach(() => { vi.useRealTimers(); });

describe('followRun', () => {
  it('reduces the job\'s events to the live phases and asks on from the position it was given', async () => {
    const id = nextId();
    script = [() => answer([started(id), runStarted(), action(1)], 3), () => answer([], 3)];
    const w = watch(id);
    expect(w.last().phase).toBe('idle');
    await tick();
    expect(w.last()).toMatchObject({ job_id: id, phase: 'running', index: 1, total: 2 });
    await tick(1000);
    expect(calls).toEqual([[id, 0], [id, 3]]);
    w.off();
  });

  it('a page of events a message and a track share a millisecond: the message the track left behind is not shown', async () => {
    const id = nextId();
    script = [() => answer([started(id), message('Looking up the bitrate of 1 older download...'), runStarted(), action(1)], 4)];
    const w = watch(id);
    await tick();
    expect(w.last()).toMatchObject({ phase: 'running', index: 1 });
    expect(liveMessage(w.last())).toBeNull();
    w.off();
  });

  it('polls once a second, and the same store serves a second subscriber with one poll', async () => {
    const id = nextId();
    const a = watch(id), b = watch(id);
    expect(followRun(id)).toBe(followRun(id));
    await tick(3500);
    expect(calls.length).toBe(4);      // at once, then at 1, 2 and 3 s: not twice each
    expect(get(followRun(id))).toBe(a.last());
    expect(b.last()).toBe(a.last());
    a.off(); b.off();
  });

  it('a full answer is followed at once, and nothing is published until the catch-up ends', async () => {
    const id = nextId();
    const lines = [started(id), runStarted(), ...Array.from({ length: 498 }, (_, i) => message(`m${i}`))];
    script = [() => answer(lines, 500), () => answer([action(1)], 501)];
    const w = watch(id);
    await tick();
    expect(w.seen.map((s) => s.phase)).toEqual(['idle']);   // the first answer was full: the catch-up goes on, nothing shown yet
    await tick(1);
    expect(calls).toEqual([[id, 0], [id, 500]]);   // the second came without waiting a second
    expect(w.seen.map((s) => s.phase)).toEqual(['idle', 'running']);   // one state published, not hundreds
    expect(w.last()).toMatchObject({ index: 1, job_id: id });
    w.off();
  });

  it('ignores every JobFinished line (a retry\'s end, a busy one more lines follow) and ends only on the answer\'s finished', async () => {
    const retried = nextId();
    script = [() => answer([started(retried), finished(retried, 'console')], 2), () => answer([started(retried), runStarted()], 4)];
    const a = watch(retried);
    await tick();
    expect(a.last().phase).toBe('preparing');      // the retry's end did not end it
    await tick(1000);
    expect(a.last()).toMatchObject({ phase: 'running', job_finished: null });
    a.off();

    const busy = nextId();
    script = [() => answer([started(busy), finished(busy, 'busy')], 2), () => answer([started(busy), runStarted()], 4)];
    const b = watch(busy);
    await tick();
    expect(b.last().phase).toBe('preparing');      // a `busy` line is retried too: it is not "didn't finish"
    await tick(1000);
    expect(b.last().phase).toBe('running');
    b.off();
  });

  it('a lost job whose file has no JobFinished ends on the answer\'s finished', async () => {
    const id = nextId();
    const lost: HubEvent = { type: 'JobFinished', job_id: id, kind: 'sync', ok: false, problem: 'failed', message: 'The job was lost.', result: null };
    script = [() => answer([started(id), runStarted()], 2, 'lost', true, lost)];
    const w = watch(id);
    await tick();
    expect(w.last()).toMatchObject({ phase: 'failed' });
    expect(w.last().job_finished).toEqual(lost);
    await tick(5000);
    expect(calls.length).toBe(1);                  // over: not asked again
    w.off();
  });

  it('applies the end to a file that holds no JobStarted line', async () => {
    const id = nextId();
    const end: HubEvent = { type: 'JobFinished', job_id: id, kind: 'sync', ok: true, problem: null, message: '', result: null };
    script = [() => answer([], 0, 'done', true, end)];
    const w = watch(id);
    await tick();
    expect(w.last()).toMatchObject({ phase: 'finished', job_id: id, job_kind: 'sync' });
    w.off();
  });

  it('the window\'s own JobFinished only makes it ask at once: the end is the answer\'s', async () => {
    const id = nextId();
    script = [() => answer([started(id), runStarted()], 2), () => answer([action(2)], 3, 'done', true, finished(id))];
    const w = watch(id);
    await tick();
    expect(w.last().phase).toBe('running');
    dispatch(finished(id));
    expect(w.last().phase).toBe('running');        // the event itself changes nothing
    await tick();
    expect(calls.at(-1)).toEqual([id, 2]);          // asked at once, not in a second
    expect(w.last()).toMatchObject({ phase: 'finished', index: 2 });
    dispatch(finished(nextId()));                   // another job's end is none of its business
    expect(w.last().phase).toBe('finished');
    w.off();
  });

  it('shows stopping while the job\'s status says so', async () => {
    const id = nextId();
    script = [() => answer([started(id), runStarted()], 2), () => answer([], 2, 'stopping'), () => answer([action(2)], 3, 'stopping')];
    const w = watch(id);
    await tick();
    expect(w.last().phase).toBe('running');
    await tick(1000);
    expect(w.last().phase).toBe('stopping');
    await tick(1000);
    expect(w.last()).toMatchObject({ phase: 'stopping', index: 2 });   // events on the way down keep it stopping
    w.off();
  });

  it('stops polling after done, and a new subscriber does not start it again', async () => {
    const id = nextId();
    script = [() => answer([started(id), finished(id)], 2, 'done', true, finished(id))];
    const w = watch(id);
    await tick(10_000);
    expect(calls.length).toBe(1);
    expect(w.last().phase).toBe('finished');
    w.off();
    const again = watch(id);
    await tick(5000);
    expect(calls.length).toBe(1);
    expect(again.last().phase).toBe('finished');   // the state was kept
    again.off();
  });

  it('stops the timer when the last subscriber leaves, and goes on from the same position when one is back', async () => {
    const id = nextId();
    script = [() => answer([started(id), runStarted()], 2)];
    const a = watch(id), b = watch(id);
    await tick();
    a.off();
    await tick(2000);
    expect(calls.length).toBe(3);                  // b still subscribed: polling on
    b.off();
    expect(vi.getTimerCount()).toBe(0);
    await tick(5000);
    expect(calls.length).toBe(3);
    const c = watch(id);
    await tick();
    expect(calls.at(-1)).toEqual([id, 2]);
    expect(c.last().phase).toBe('running');
    c.off();
  });

  it('an answer that arrives after the last unsubscribe is kept, and the next subscriber asks from its next', async () => {
    const id = nextId();
    let release!: () => void;
    script = [() => new Promise((r) => { release = () => r(answer([started(id), runStarted()], 2)); }), () => answer([], 2)];
    const w = watch(id);
    await tick();
    w.off();
    release();
    await tick();
    expect(vi.getTimerCount()).toBe(0);              // nothing is asked while nobody looks
    expect(get(followRun(id))).toMatchObject({ job_id: id, phase: 'running' });   // the lines were reduced
    const again = watch(id);
    await tick();
    expect(calls.at(-1)).toEqual([id, 2]);          // the engine's reader counted them as delivered: ask from their next
    expect(again.last().phase).toBe('running');
    again.off();
  });

  it('an end that arrives after the last unsubscribe is kept too', async () => {
    const id = nextId();
    let release!: () => void;
    script = [() => new Promise((r) => { release = () => r(answer([started(id), runStarted()], 2, 'done', true, finished(id))); })];
    const w = watch(id);
    await tick();
    w.off();
    release();
    await tick();
    expect(get(followRun(id)).phase).toBe('finished');
    const again = watch(id);
    await tick(3000);
    expect(calls.length).toBe(1);                    // over: the job is not asked again
    again.off();
  });

  it('two Progress lines of one slot in one answer give the rate of the whole interval', async () => {
    const id = nextId();
    const bytes = (done: number): HubEvent => ({ type: 'Progress', track_id: 't1', step: 'download', done, total: 5000, unit: 'bytes' });
    script = [() => answer([started(id), runStarted(), action(1), bytes(0)], 4), () => answer([bytes(500), bytes(1000)], 6)];
    const w = watch(id);
    await tick();
    await tick(1000);
    // 1000 bytes in the second between the polls, not 500 (the first line over the whole second, the second over none)
    expect(w.last().progress).toMatchObject({ done: 1000, rate: 1000 });
    w.off();
  });

  it('keeps the two newest followed jobs, and lets go of an unsubscribed older one; a subscribed one stays', async () => {
    const [a, b, c, d] = [nextId(), nextId(), nextId(), nextId()];
    script = [() => answer([started(a), runStarted()], 2)];
    const kept = watch(a);                           // a stays subscribed
    await tick();
    const first = followRun(b);
    const second = followRun(c);
    expect(followRun(c)).toBe(second);
    followRun(d);                                    // b is the oldest idle one: let go
    expect(followRun(b)).not.toBe(first);
    expect(get(followRun(a)).job_id).toBe(a);        // a was never let go
    kept.off();
  });

  it('keeps the state and tries again after a failed answer, and gives up on an unknown id', async () => {
    const id = nextId();
    script = [() => answer([started(id), runStarted()], 2), () => ({ ok: false, kind: 'crashed', message: '' }), () => answer([action(1)], 3)];
    const w = watch(id);
    await tick();
    await tick(1000);
    expect(w.last().phase).toBe('running');
    await tick(1000);
    expect(calls.map((c) => c[1])).toEqual([0, 2, 2]);
    expect(w.last().index).toBe(1);
    w.off();

    const gone = nextId();
    script = [() => ({ ok: false, kind: 'bad_args', reason: 'unknown_id', message: 'There is no job here.' })];
    const g = watch(gone);
    await tick(10_000);
    expect(calls.filter((c) => c[0] === gone).length).toBe(1);
    expect(g.last().phase).toBe('idle');
    g.off();
  });
});

describe('terminalSync', () => {
  const busy = (running: boolean, kind: string | null = 'sync', job: string | null = 'job:00000c0d', where = 'In the Terminal'): HubEvent =>
    ({ type: 'ConsoleBusy', running, job: running ? job : null, kind: running ? kind : null, line: null, text: running ? 'Sync running in the Terminal' : null,
      where: running ? where : null });

  it('follows the console\'s sync, is kept after the console clears, and is replaced by the next console sync', () => {
    expect(get(terminalSync)).toBeNull();
    dispatch(busy(true));
    expect(get(terminalSync)).toEqual({ job: 'job:00000c0d', running: true, where: 'In the Terminal' });
    dispatch(busy(false));
    expect(get(terminalSync)).toEqual({ job: 'job:00000c0d', running: false, where: 'In the Terminal' });
    dispatch(busy(true, 'sync', 'job:00000c0e'));
    expect(get(terminalSync)).toEqual({ job: 'job:00000c0e', running: true, where: 'In the Terminal' });
    dispatch(busy(false));
  });

  it('keeps where the sync runs, as the engine says it: another window\'s sync is not "In the Terminal"', () => {
    dispatch(busy(true, 'sync', 'job:00000c20', 'In another window'));
    expect(get(terminalSync)).toEqual({ job: 'job:00000c20', running: true, where: 'In another window' });
    dispatch(busy(false));
    expect(get(terminalSync)).toEqual({ job: 'job:00000c20', running: false, where: 'In another window' });   // kept with the end
    dispatch(busy(true, 'sync', 'job:00000c21'));
    dispatch(busy(false));
  });

  it('keeps an ended sync while a job of another kind (or one nobody can name) holds the library', () => {
    dispatch(busy(true, 'sync', 'job:00000c10'));
    dispatch(busy(false));
    expect(get(terminalSync)).toEqual({ job: 'job:00000c10', running: false, where: 'In the Terminal' });
    dispatch(busy(true, 'tidy', 'job:00000c11'));
    expect(get(terminalSync)).toEqual({ job: 'job:00000c10', running: false, where: 'In the Terminal' });
    dispatch(busy(false));
    dispatch(busy(true, null, null));
    expect(get(terminalSync)).toEqual({ job: 'job:00000c10', running: false, where: 'In the Terminal' });
    dispatch(busy(false));
    dispatch(busy(true, 'sync', 'job:00000c12'));   // only another sync replaces it
    expect(get(terminalSync)).toEqual({ job: 'job:00000c12', running: true, where: 'In the Terminal' });
    dispatch(busy(true, 'tidy', 'job:00000c13'));   // a sync that is replaced straight by a tidy-up has ended
    expect(get(terminalSync)).toEqual({ job: 'job:00000c12', running: false, where: 'In the Terminal' });
    dispatch(busy(false));
  });
});

describe('shownSync (the sync the sidebar and the foot show)', () => {
  const busy = (running: boolean, job = 'job:00000c30'): HubEvent =>
    ({ type: 'ConsoleBusy', running, job: running ? job : null, kind: running ? 'sync' : null, line: null,
      text: running ? 'Sync running in the Terminal' : null, where: running ? 'In the Terminal' : null });
  const ownStarted = (job_id: string): HubEvent => ({ type: 'JobStarted', job_id, kind: 'sync', track_id: null, batch_kind: null });
  /** Subscribes and keeps the newest value */
  function look() {
    let value: RunState | null | undefined;
    const off = shownSync.subscribe((v) => { value = v; });
    return { off, value: () => value };
  }

  it('is null while no sync runs', () => {
    const l = look();
    expect(l.value()).toBeNull();
    l.off();
  });

  it('is the window\'s own run while its own sync runs, also while the Terminal holds the console state', async () => {
    const l = look();
    dispatch(ownStarted('job:00000c31'));
    expect(l.value()).toBe(get(run));
    expect(l.value()).toMatchObject({ job_id: 'job:00000c31', phase: 'preparing' });
    dispatch(busy(true, 'job:00000c32'));
    await tick();
    expect(l.value()).toBe(get(run));
    expect(calls.filter((c) => c[0] === 'job:00000c32')).toEqual([]);   // the Terminal's job is not asked while the own one is shown
    dispatch(finished('job:00000c31'));
    dispatch(busy(false));
    expect(l.value()).toBeNull();
    l.off();
  });

  it('is the Terminal\'s followed sync while the console says it runs, and null once it has ended', async () => {
    const job = 'job:00000c33';
    script = [() => answer([started(job), runStarted(2), action(2)], 3)];
    const l = look();
    dispatch(busy(true, job));
    await tick();
    expect(l.value()).toMatchObject({ job_id: job, job_kind: 'sync', phase: 'running', index: 2, total: 2 });
    expect(calls[0]).toEqual([job, 0]);
    await tick(1000);                                   // it goes on polling while shown
    expect(calls.length).toBe(2);
    dispatch(busy(false));
    expect(l.value()).toBeNull();
    l.off();
    await tick(5000);
    expect(calls.length).toBe(2);                       // and nothing is asked any more
  });
});
