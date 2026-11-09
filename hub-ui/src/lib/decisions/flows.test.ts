// The batch flows (issue 33 stage B) against the fake bridge, its events on the real events bus: the run-twice guard,
// adopting a batch the window didn't start, a refusal before a start, Again, covers/clear, and the checks flow.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { _resetBridge, api, installBridge } from '../bridge/client';
import { dispatch, onEvent } from '../bridge/events';
import { createFakeBridge } from '../bridge/fake/bridge';
import type { AiffBatchResult, JobSnap, Todo, TodoItem } from '../bridge/types';
import { answerConfirm, confirmRequest } from '../components/confirm';
import { _resetJobs, waitForJob } from '../stores/jobs';
import { toasts } from '../stores/toasts';
import { artistTitle } from '../format';
import { ChecksFlow, UpgradeBatchFlow } from './flows.svelte';

function setup(scenario = 'upgrade-multi', speed = 400) {
  (globalThis as any).window = new EventTarget();
  _resetBridge();
  _resetJobs();
  toasts.clear();
  const f = createFakeBridge(scenario, { speed, emit: dispatch });
  installBridge(f);
  const s = (f as any)._ctx.s;
  const group = async (key: string) => {
    const t = (await f.todo('all', false)) as Todo & { ok: true };
    return t.groups.find((g) => g.key === key);
  };
  const ready = async (): Promise<TodoItem[]> => (await group('upgrade_ready'))!.items.filter((i) => i.same_track === null);
  return { f, s, group, ready };
}
const name = (i: TodoItem) => artistTitle(i.artist, i.title);
const until = async (cond: () => boolean) => {
  for (let i = 0; i < 600 && !cond(); i++) await new Promise((r) => setTimeout(r, 3));
  if (!cond()) throw new Error('the condition never held');
};
const snap = (over: Partial<JobSnap>): JobSnap => ({ id: 1, kind: 'upgrade_batch', track_id: null, started: '', running: true,
  stopping: false, last: {}, results: [], finished: null, actions: [], ...over } as JobSnap);

beforeEach(() => { vi.spyOn(console, 'warn').mockImplementation(() => {}); });
afterEach(() => { vi.restoreAllMocks(); answerConfirm(false); delete (globalThis as any).window; });

describe('UpgradeBatchFlow', () => {
  it('a second Replace or Resume while a batch runs does nothing: one call, one listener, one end', async () => {
    const { ready } = setup();
    const items = await ready();
    const flow = new UpgradeBatchFlow();
    const upgrade = vi.spyOn(api, 'upgrade');
    const resume = vi.spyOn(api, 'batch_resume');
    const first = flow.start('swap', items, false, name);
    await flow.start('swap', items, false, name);
    await flow.resume(1);
    expect(upgrade).toHaveBeenCalledTimes(1);
    expect(resume).not.toHaveBeenCalled();
    expect(flow.view).toMatchObject({ phase: 'running' });
    await first;
    expect(flow.view).toMatchObject({ phase: 'ended', end: { kind: 'done', done: items.length } });
    // the first run's progress still reached its rows
    expect(flow.view!.rows.filter((r) => r.state === 'done')).toHaveLength(items.length);
  });

  it('adopts a batch the hub runs that it did not start, from its last progress, and ends with all its tracks named', async () => {
    const { f, ready } = setup();
    const items = await ready();
    const flow = new UpgradeBatchFlow();
    flow.know(items.map((i) => [i.track_id, name(i)]));
    const start = await f.upgrade(items.map((i) => i.track_id), 'swap');
    const job_id = (start as { job_id: number }).job_id;
    const last = { batch_id: 1, done: 1, total: items.length, track_id: items[1].track_id, name: `${items[1].artist} - ${items[1].title}` };
    // a job for one track (track_id set) is that track's own panel's; a sync is no batch; neither is adopted
    flow.adopt(snap({ id: job_id, track_id: items[0].track_id, last: { BatchProgress: last } }));
    flow.adopt(snap({ id: job_id, kind: 'sync' }));
    flow.adopt(snap({ id: job_id, running: false }));
    expect(flow.view).toBeNull();
    flow.adopt(snap({ id: job_id, last: { BatchProgress: last }, stopping: true }));
    expect(flow.view).toMatchObject({ phase: 'running', mode: 'swap', tracks: null, done: 1, total: items.length, stopping: true,
      now: name(items[1]).replace(' - ', ' – ') });
    expect(flow.view!.now).toContain(' – ');
    expect(flow.view!.rows).toHaveLength(1);
    expect(flow.view!.rows[0]).toMatchObject({ track_id: items[1].track_id, state: 'now' });
    // a second adopt while it runs changes nothing
    const view = flow.view;
    flow.adopt(snap({ id: job_id, last: { BatchProgress: last } }));
    expect(flow.view).toBe(view);
    await until(() => flow.view?.phase === 'ended');
    expect(flow.view!.end).toMatchObject({ kind: 'done', done: items.length });
    // every track of the result has a row, named; the ones it had no progress row for from what the page knew
    expect(flow.view!.rows.map((r) => r.track_id).sort()).toEqual(items.map((i) => i.track_id).sort());
    expect(flow.view!.rows.every((r) => r.state === 'done')).toBe(true);
    expect(flow.view!.rows.find((r) => r.track_id === items[0].track_id)!.name).toBe(name(items[0]));
    // it shows for any selection of the group
    expect(flow.covers(['anything'])).toBe(true);
  });

  it('a track the flow has no name for, that passed before the window followed, is listed under its id', async () => {
    const { f, ready } = setup('upgrade-multi', 25);
    const items = await ready();
    const flow = new UpgradeBatchFlow();
    const seen: { track_id: string | null; name: string | null }[] = [];
    const off = onEvent((e) => { if (e.type === 'BatchProgress' && e.track_id) seen.push(e); });
    const { job_id } = (await f.upgrade_all()) as { job_id: number };
    await until(() => seen.length >= 2);
    off();
    const last = seen.at(-1)!;
    flow.adopt(snap({ id: job_id, last: { BatchProgress: { batch_id: 1, done: 1, total: items.length, ...last } } }));
    await until(() => flow.view?.phase === 'ended');
    const rows = flow.view!.rows;
    expect(rows.map((r) => r.track_id).sort()).toEqual(items.map((i) => i.track_id).sort());
    // the first one went by before the flow listened: its id; the ones that came after, by their names
    expect(rows.find((r) => r.track_id === seen[0].track_id)!.name).toBe(seen[0].track_id);
    expect(rows.find((r) => r.track_id === last.track_id)!.name).toBe(last.name!.replace(' - ', ' – '));
  });

  it('a refusal before it started clears the view, says why in a toast and keeps the decision', async () => {
    const { f, ready } = setup();
    const items = await ready();
    const flow = new UpgradeBatchFlow();
    const { job_id } = (await f.upgrade_all()) as { job_id: number }; // another write holds the engine
    await flow.start('swap', items, false, name);
    expect(flow.view).toBeNull();
    expect(get(toasts)).toMatchObject([{ tone: 'problem' }]);
    await waitForJob(job_id); // no job outlives its test
  });

  it('Again only when the end is not resumable; it runs the same call once rekordbox is closed', async () => {
    const { s, ready } = setup('upgrade-rekordbox-open');
    const items = await ready();
    const first = items.find((i) => s.tracks.find((t: any) => t.track_id === i.track_id).upgrade.swap_how === 'new_aiff')!;
    const flow = new UpgradeBatchFlow();
    // one track, rekordbox open before anything ran: the batch is closed, so nothing to resume, but a second try is worth it
    await flow.start('swap', [first], false, name);
    expect(flow.view).toMatchObject({ phase: 'ended', end: { kind: 'rekordbox_open', resume: null } });
    expect(flow.view!.again).toBeTypeOf('function');
    s.rekordbox_running = false;
    flow.view!.again!();
    expect(flow.view).toMatchObject({ phase: 'running' });
    await until(() => flow.view?.phase === 'ended');
    expect(flow.view).toMatchObject({ end: { kind: 'done', done: 1 }, again: null });
    // several tracks stopped by rekordbox have a batch to resume: no Again
    s.rekordbox_running = true;
    const rest = items.filter((i) => i !== first);
    await flow.start('swap', rest, false, name);
    expect(flow.view!.end).toMatchObject({ kind: 'rekordbox_open', resume: { left: rest.length } });
    expect(flow.view!.again).toBeNull();
  });

  it('Resume names every track of the batch, also those it never had a row for', async () => {
    const { ready, group } = setup('upgrade-multi', 25);
    const items = (await ready()).slice(0, 3);
    const flow = new UpgradeBatchFlow();
    flow.know(items.map((i) => [i.track_id, name(i)]));
    const run = flow.start('swap', items, false, name);
    await until(() => flow.view!.done >= 1 || flow.view!.now !== null);
    await flow.stop();
    expect(flow.view!.stopping).toBe(true);
    await run;
    expect(flow.view!.end).toMatchObject({ kind: 'stopped' });
    const left = flow.view!.end!.resume!;
    expect(left.left).toBeGreaterThan(0);
    expect((await group('upgrade_ready'))!.stopped).toMatchObject({ batch_id: left.batch_id, left: left.left });
    await flow.resume(left.batch_id);
    expect(flow.view).toMatchObject({ phase: 'ended', tracks: null, end: { kind: 'done' } });
    expect(flow.view!.rows.length).toBeGreaterThanOrEqual(left.left);
    expect(flow.view!.rows.every((r) => r.state === 'done' && !r.name.startsWith('t'))).toBe(true);
  });

  it('the hub answers the list per track while a batch runs: done tracks have left Upgrades ready before its end', async () => {
    const { ready, group } = setup('upgrade-multi', 60);
    const items = await ready();
    const flow = new UpgradeBatchFlow();
    const run = flow.start('swap', items, false, name);
    await until(() => flow.view!.done >= 1);
    const mid = (await ready()).length;
    expect(flow.view!.phase).toBe('running');
    expect(mid).toBeLessThan(items.length);
    await run;
    expect((await group('rekordbox_check'))!.items.length).toBeGreaterThan(0);
  });

  it('Stop ends a New track list between tracks with the rest planned', async () => {
    const { ready } = setup('upgrade-multi', 25);
    const items = await ready();
    const flow = new UpgradeBatchFlow();
    const run = flow.start('add_new', items, false, name);
    await until(() => flow.view!.now !== null);
    await flow.stop();
    await run;
    expect(flow.view!.end).toMatchObject({ kind: 'stopped' });
    expect(flow.view!.rows.some((r) => r.state === 'waiting')).toBe(true);
    expect(flow.view!.rows.some((r) => r.state === 'done')).toBe(true);
  });

  it('Discard asks first; a no starts nothing', async () => {
    const { ready } = setup();
    const items = await ready();
    const flow = new UpgradeBatchFlow();
    const asked = new Promise<void>((resolve) => {
      const stop = confirmRequest.subscribe((p) => { if (p) { queueMicrotask(() => { stop(); resolve(); answerConfirm(false); }); } });
    });
    await flow.start('discard', items, false, name);
    await asked;
    expect(flow.view).toBeNull();
  });

  it('covers: a batch started for tracks shows for a selection with one of them; clear keeps a running view', async () => {
    const { ready } = setup();
    const items = await ready();
    const flow = new UpgradeBatchFlow();
    expect(flow.covers([items[0].track_id])).toBe(false);
    const run = flow.start('swap', items.slice(0, 2), false, name);
    expect(flow.covers([items[0].track_id, 'x'])).toBe(true);
    expect(flow.covers(['x'])).toBe(false);
    flow.clear();
    expect(flow.view).toMatchObject({ phase: 'running' });
    await run;
    expect(flow.view).toMatchObject({ phase: 'ended' });
    flow.clear();
    expect(flow.view).toBeNull();
    expect(flow.covers([items[0].track_id])).toBe(false);
  });
});

describe('ChecksFlow', () => {
  async function withChecks() {
    const env = setup();
    const items = (await env.ready()).slice(0, 2);
    const done = await env.f.upgrade(items.map((i) => i.track_id), 'swap');
    await waitForJob((done as { job_id: number }).job_id);
    const checks = (await env.group('rekordbox_check'))!.items.flatMap((i) => (i as any).batch?.tracks ?? [i]) as TodoItem[];
    return { ...env, checks };
  }
  /** answers the next confirm with yes */
  const yes = () => { const stop = confirmRequest.subscribe((p) => { if (p) queueMicrotask(() => { stop(); answerConfirm(true); }); }); };

  it('Done runs once while it works', async () => {
    const { checks } = await withChecks();
    const flow = new ChecksFlow();
    const call = vi.spyOn(api, 'rekordbox_checked');
    const first = flow.checked(checks.map((t) => t.track_id));
    expect(flow.busy).toBe('done');
    await flow.checked(checks.map((t) => t.track_id));
    await first;
    expect(call).toHaveBeenCalledTimes(1);
    expect(flow.busy).toBeNull();
    await flow.checked([]);
    expect(call).toHaveBeenCalledTimes(1);
  });

  it('a refused undo keeps its words until the next pick; follow starts over only for a new key', async () => {
    const { checks, s } = await withChecks();
    const flow = new ChecksFlow();
    s.undoRefuse = { [checks[0].track_id]: 'the file changed since' };
    flow.follow('a');
    yes();
    await flow.undo(checks.map((t) => t.track_id));
    expect(flow.busy).toBeNull();
    expect(flow.problem).toMatchObject({ rows: { [checks[0].track_id]: 'The file changed since' } });
    flow.follow('a');
    expect(flow.problem).not.toBeNull();
    flow.follow('b');
    expect(flow.problem).toBeNull();
  });

  it('does not undo when the question is answered no, and onact fires as an action starts', async () => {
    const { checks } = await withChecks();
    const onact = vi.fn();
    const flow = new ChecksFlow({ onact });
    const call = vi.spyOn(api, 'undo_upgrade');
    const no = () => { const stop = confirmRequest.subscribe((p) => { if (p) queueMicrotask(() => { stop(); answerConfirm(false); }); }); };
    no();
    await flow.undo(checks.map((t) => t.track_id));
    expect(call).not.toHaveBeenCalled();
    expect(onact).not.toHaveBeenCalled();
    await flow.checked(checks.map((t) => t.track_id));
    expect(onact).toHaveBeenCalledTimes(1);
  });
});
