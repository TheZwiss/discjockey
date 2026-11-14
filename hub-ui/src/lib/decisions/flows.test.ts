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
import { AiffBatchFlow, AiffFlow, ChecksFlow, UpgradeBatchFlow } from './flows.svelte';
import type { AiffScope } from '../bridge/types';
import type { RunRow } from './decisionModel';

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

describe('AiffFlow (Convert and Give it its clean name for one track)', () => {
  it('runs Convert from the Library, shows the button busy meanwhile and ends without a problem; a second press does nothing', async () => {
    setup('library:aiff-flac', 1000);
    const convert = vi.spyOn(api, 'convert');
    const flow = new AiffFlow();
    const first = flow.run('own:1', 'convert');
    expect(flow.busy).toBe(true);
    await flow.run('own:1', 'convert');
    await first;
    expect(convert).toHaveBeenCalledTimes(1);
    expect(convert).toHaveBeenCalledWith(['own:1'], 'library');
    expect([flow.busy, flow.problem]).toEqual([false, null]);
  });
  it('a Rename calls rename, a To-do flow says todo as the origin', async () => {
    setup('library:aiff-rename', 1000);
    const rename = vi.spyOn(api, 'rename');
    const flow = new AiffFlow({ origin: 'todo' });
    await flow.run('own:7', 'rename');
    expect(rename).toHaveBeenCalledWith(['own:7']);
    const convert = vi.spyOn(api, 'convert');
    await flow.run('own:1', 'convert');
    expect(convert).toHaveBeenCalledWith(['own:1'], 'todo');
  });
  it('calls onact as the job starts, so the page keeps the track in view', async () => {
    setup('library:aiff-flac', 1000);
    const onact = vi.fn();
    await new AiffFlow({ onact }).run('own:1', 'convert');
    expect(onact).toHaveBeenCalledTimes(1);
  });
  it('rekordbox open: the refusal stays as the card\'s problem, no toast, until the next track', async () => {
    setup('library:aiff-rekordbox-open', 1000);
    const flow = new AiffFlow();
    await flow.run('own:1', 'convert');
    expect(flow.problem).toMatch(/^rekordbox is open\. Quit rekordbox/);
    expect(get(toasts)).toEqual([]);
    flow.follow('own:2');
    expect(flow.problem).toBeNull();
  });
  it('asks rekordbox when it attaches and when the window gets focus back; detaching stops it', async () => {
    const { s } = setup('library:aiff-flac', 1000);
    const flow = new AiffFlow();
    expect(flow.rekordbox).toBeNull();
    const off = flow.attach();
    await until(() => flow.rekordbox !== null);
    expect(flow.rekordbox).toEqual({ state: 'ready', running: false });
    s.rekordbox_running = true;
    window.dispatchEvent(new Event('focus'));
    await until(() => flow.rekordbox?.running === true);
    off();
    s.rekordbox_running = false;
    window.dispatchEvent(new Event('focus'));
    await new Promise((r) => setTimeout(r, 20));
    expect(flow.rekordbox?.running).toBe(true);
  });
});

describe('AiffBatchFlow (Make all lossless files AIFF, a selection\'s Convert, the CDJ group)', () => {
  const VIEW: AiffScope = { kind: 'lossless', view: 'folder', key: '/Volumes/Example Drive/Music' };
  const rowsOf = (flow: AiffBatchFlow): RunRow[] => flow.read!.plan!.items.map((i) => ({ track_id: i.track, name: i.name,
    sub: i.kind, cover_url: null, state: 'waiting', text: null }));

  it('reads the plan of its scope; a read again of the same scope keeps the plan on screen, a new scope starts over', async () => {
    setup('library:aiff-view', 1000);
    const flow = new AiffBatchFlow();
    const first = flow.load(VIEW);
    expect(flow.read).toMatchObject({ phase: 'loading', plan: null });
    await first;
    expect(flow.read).toMatchObject({ phase: 'ready', key: 'lossless:folder:/Volumes/Example Drive/Music' });
    expect(flow.read!.plan!.total).toBeGreaterThan(8);
    const plan = flow.read!.plan;
    const again = flow.load(VIEW);
    expect(flow.read).toMatchObject({ phase: 'loading', plan });
    await again;
    void flow.load({ kind: 'tracks', tracks: ['own:1', 'own:2'] });
    expect(flow.read).toMatchObject({ phase: 'loading', plan: null });
  });

  it('only the newest read is kept, and a refused read keeps its words', async () => {
    setup('library:aiff-view', 1000);
    const flow = new AiffBatchFlow();
    const a = flow.load(VIEW);
    const b = flow.load({ kind: 'tracks', tracks: ['own:1', 'own:7'] });
    await Promise.all([a, b]);
    expect(flow.read).toMatchObject({ phase: 'ready', key: 'tracks:own:1|own:7' });
    await flow.load({ kind: 'lossless', view: 'nowhere' as 'all', key: null });
    expect(flow.read).toMatchObject({ phase: 'error', plan: null, message: "That isn't a set of files Discjockey can make AIFF." });
  });

  it('Make all runs make_aiff for the view and ends with every file done', async () => {
    setup('library:aiff-view', 1000);
    const make = vi.spyOn(api, 'make_aiff');
    const flow = new AiffBatchFlow();
    await flow.load(VIEW);
    const rows = rowsOf(flow);
    const run = flow.start(VIEW, rows, false);
    expect(flow.view).toMatchObject({ phase: 'running', scope: 'lossless:folder:/Volumes/Example Drive/Music', total: rows.length });
    await flow.start(VIEW, rows, false); // a second press while it runs does nothing
    await run;
    expect(make).toHaveBeenCalledTimes(1);
    expect(make).toHaveBeenCalledWith(VIEW);
    expect(flow.view).toMatchObject({ phase: 'ended', end: { kind: 'done', done: rows.length }, again: null });
    expect(flow.view!.rows.every((r) => r.state === 'done')).toBe(true);
    expect(flow.covers(VIEW)).toBe(true);
    expect(flow.covers({ kind: 'cdj' })).toBe(false);
    flow.clear();
    expect(flow.view).toBeNull();
  });

  it('a selection runs convert with its origin; the songs it leaves out come back named, with their reasons', async () => {
    setup('library:aiff-selection', 1000);
    const convert = vi.spyOn(api, 'convert');
    const flow = new AiffBatchFlow();
    const scope: AiffScope = { kind: 'tracks', tracks: ['own:1', 'own:5', 'own:6', 'own:7', 'own:8', 'own:16'] };
    await flow.load(scope);
    expect(flow.read!.plan!.skipped.map((l) => l.track)).toEqual(['own:8', 'own:16']);
    await flow.start(scope, rowsOf(flow), false, 'todo');
    expect(convert).toHaveBeenCalledWith(scope.tracks, 'todo');
    const left = flow.view!.rows.filter((r) => r.state === 'skipped');
    expect(left.map((r) => r.track_id).sort()).toEqual(['own:16', 'own:8']);
    // named from the plan, the reason as the engine says it
    expect(left.every((r) => r.name !== r.track_id && !!r.text)).toBe(true);
  });

  it('a file skipped mid-way stays with its reason; the rest are made', async () => {
    setup('library:aiff-panel-ended', 1000);
    const flow = new AiffBatchFlow();
    await flow.load(VIEW);
    await flow.start(VIEW, rowsOf(flow), false);
    const skipped = flow.view!.rows.filter((r) => r.state === 'skipped');
    expect(skipped.map((r) => r.track_id)).toEqual(['own:6']);
    expect(skipped[0].text).toMatch(/^Discjockey couldn't line the new file up/);
    expect(flow.view!.end).toMatchObject({ kind: 'done', done: flow.view!.rows.length - 1 });
  });

  it('nothing to change ends refused with the engine\'s words', async () => {
    setup('library:aiff-view-empty', 1000);
    const flow = new AiffBatchFlow();
    await flow.start(VIEW, [], false);
    expect(flow.view).toMatchObject({ phase: 'ended', end: { kind: 'refused', message: 'Nothing to change: these are clean AIFFs already.' } });
  });

  it('Stop ends it between files with Resume · k left, and Resume runs the stopped batch', async () => {
    setup('library:aiff-panel-running', 100);
    const flow = new AiffBatchFlow();
    await flow.load(VIEW);
    const run = flow.start(VIEW, rowsOf(flow), false);
    await until(() => (flow.view?.done ?? 0) >= 1);
    await flow.stop();
    await run;
    const end = flow.view!.end!;
    expect(end.kind).toBe('stopped');
    expect(end.resume!.left).toBeGreaterThan(0);
    expect(flow.view!.rows.some((r) => r.state === 'waiting')).toBe(true);
    const resume = vi.spyOn(api, 'batch_resume');
    const again = flow.resume(end.resume!.batch_id);
    expect(flow.view).toMatchObject({ phase: 'running', scope: null });
    await again;
    expect(resume).toHaveBeenCalledWith(end.resume!.batch_id);
    expect(flow.view!.end).toMatchObject({ kind: 'done' });
    // a Resume shows for any scope's panel
    expect(flow.covers({ kind: 'cdj' })).toBe(true);
  });

  it('rekordbox open: the batch stops before the first file, with design §8\'s words and Resume', async () => {
    setup('library:aiff-rekordbox-open', 1000);
    const flow = new AiffBatchFlow();
    await flow.load(VIEW);
    await flow.start(VIEW, rowsOf(flow), false);
    expect(flow.view!.end).toMatchObject({ kind: 'rekordbox_open', done: 0 });
    expect(flow.view!.end!.resume).not.toBeNull();
  });

  it('a refusal before it started clears the view and says why in a toast', async () => {
    const { f } = setup('library:aiff-view', 1000);
    const flow = new AiffBatchFlow();
    const { job_id } = (await f.make_aiff(VIEW)) as { job_id: number }; // another write holds the engine
    await flow.start(VIEW, [], false);
    expect(flow.view).toBeNull();
    expect(get(toasts)).toMatchObject([{ tone: 'problem' }]);
    await waitForJob(job_id);
  });

  it('adopts an aiff_batch for several files and a resume of a Convert batch; never one file\'s job', async () => {
    const { f } = setup('library:aiff-panel-stopped', 1000);
    const flow = new AiffBatchFlow();
    const ups = new UpgradeBatchFlow();
    flow.adopt(snap({ id: 9, kind: 'aiff_batch', track_id: 'own:1' }));
    flow.adopt(snap({ id: 9, kind: 'aiff_batch', running: false }));
    flow.adopt(snap({ id: 9, kind: 'batch_resume', batch_kind: 'convert', track_id: 'own:1' }));
    expect(flow.view).toBeNull();
    // a Resume this flow starts is its own, on the live job and on a reload alike: the upgrade flow, asked to follow
    // the hub's job (its snapshot says `convert`), leaves it alone
    const batch = (await f.library('folder', '/Volumes/Example Drive/Music', '', 'all', null) as { aiff_stopped: { batch_id: number } }).aiff_stopped;
    const resume = vi.spyOn(api, 'batch_resume');
    const run = flow.resume(batch.batch_id);
    const jobId = ((await resume.mock.results[0].value) as { job_id: number }).job_id;
    const live = ((await f.job_status()) as { job: JobSnap }).job;
    expect(live).toMatchObject({ id: jobId, kind: 'batch_resume', batch_kind: 'convert' });
    ups.adopt(live);
    expect(ups.view).toBeNull();
    await run;
    // a running aiff_batch the window didn't start is followed to its end
    const start = await f.make_aiff(VIEW);
    flow.clear();
    flow.adopt(snap({ id: (start as { job_id: number }).job_id, kind: 'aiff_batch' }));
    expect(flow.view).toMatchObject({ phase: 'running', scope: null });
    await until(() => flow.view?.phase === 'ended');
    expect(flow.view!.end).toMatchObject({ kind: 'done' });
  });
});

describe('a resumed batch is followed by its batch kind after a reload', () => {
  const resumed = async (scenario: string): Promise<{ f: ReturnType<typeof setup>['f']; snap: JobSnap }> => {
    const { f, ready } = setup(scenario, scenario === 'upgrade-multi' ? 60 : 1000);
    let id: number;
    if (scenario === 'upgrade-multi') {
      const ids = (await ready()).map((i) => i.track_id).slice(0, 3);
      const start = (await f.upgrade(ids, 'swap')) as { job_id: number };
      let progressed = false;
      const off = onEvent((e) => { if (e.type === 'BatchProgress') progressed = true; });
      await until(() => progressed);
      off();
      await f.stop();
      await waitForJob(start.job_id);
      const t = (await f.todo('all', false)) as Todo & { ok: true };
      const stopped = t.groups.find((g) => g.key === 'upgrade_ready')!.stopped!;
      id = ((await f.batch_resume(stopped.batch_id)) as { job_id: number }).job_id;
    } else {
      const batch = (await f.library('folder', '/Volumes/Example Drive/Music', '', 'all', null) as { aiff_stopped: { batch_id: number } }).aiff_stopped;
      id = ((await f.batch_resume(batch.batch_id)) as { job_id: number }).job_id;
    }
    const job = ((await f.job_status()) as { job: JobSnap }).job;
    expect(job).toMatchObject({ id, kind: 'batch_resume', running: true });
    return { f, snap: job };
  };

  it('Same track\'s resume is the upgrade flow\'s, never the AIFF batch flow\'s', async () => {
    const { snap: job } = await resumed('upgrade-multi');
    expect(job.batch_kind).toBe('upgrade');
    const aiff = new AiffBatchFlow();
    const ups = new UpgradeBatchFlow();
    aiff.adopt(job);
    expect(aiff.view).toBeNull();
    ups.adopt(job);
    expect(ups.view).toMatchObject({ phase: 'running', mode: 'swap' });
    await until(() => ups.view?.phase === 'ended');
  });

  it('a Convert batch\'s resume is the AIFF batch flow\'s, never the upgrade flow\'s', async () => {
    const { snap: job } = await resumed('library:aiff-panel-stopped');
    expect(job.batch_kind).toBe('convert');
    const aiff = new AiffBatchFlow();
    const ups = new UpgradeBatchFlow();
    ups.adopt(job);
    expect(ups.view).toBeNull();
    aiff.adopt(job);
    expect(aiff.view).toMatchObject({ phase: 'running', scope: null });
    await until(() => aiff.view?.phase === 'ended');
  });

  it('a mixed batch is the AIFF batch flow\'s; a resume with no known kind is neither\'s', () => {
    const aiff = new AiffBatchFlow();
    const ups = new UpgradeBatchFlow();
    for (const batch_kind of [null, undefined]) {
      const job = snap({ id: 9, kind: 'batch_resume', batch_kind });
      aiff.adopt(job);
      ups.adopt(job);
    }
    expect([aiff.view, ups.view]).toEqual([null, null]);
    ups.adopt(snap({ id: 9, kind: 'batch_resume', batch_kind: 'mixed' }));
    expect(ups.view).toBeNull();
    // the job kinds that say whose they are need no batch kind
    ups.adopt(snap({ id: 9, kind: 'upgrade_discard', batch_kind: null }));
    expect(ups.view).toMatchObject({ phase: 'running', mode: 'discard' });
  });
});

describe('Undo of a Convert and a clean name (issue 33 stage D §6.3)', () => {
  const yes = () => { const stop = confirmRequest.subscribe((p) => { if (p) queueMicrotask(() => { stop(); answerConfirm(true); }); }); };
  const asked = () => { let title = ''; const stop = confirmRequest.subscribe((p) => { if (p) { title = p.title; queueMicrotask(() => { stop(); answerConfirm(true); }); } }); return () => title; };
  it('the toast is the engine\'s words, the question is a Convert\'s own', async () => {
    const { group } = setup('todo:check-converted', 1000);
    const one = (await group('rekordbox_check'))!.items.find((i) => i.track_id === 'own:13')!;
    expect(one.check!.reason).toBe('converted');
    const flow = new ChecksFlow();
    const title = asked();
    await flow.undo(['own:13'], one.check);
    expect(title()).toBe('Undo the conversion?');
    expect(get(toasts)).toMatchObject([{ tone: 'success', title: 'Conversion undone. Your old file is back.' }]);
  });
  it('several converts ask by count and say the engine\'s words for several', async () => {
    const { group } = setup('todo:check-convert-batch', 1000);
    const batch = (await group('rekordbox_check'))!.items.find((i) => i.batch)!;
    const tracks = batch.batch!.tracks;
    const flow = new ChecksFlow();
    const title = asked();
    await flow.undo(tracks.map((t) => t.track_id), undefined, tracks.map((t) => t.check));
    expect(title()).toBe('Undo 3 conversions?');
    expect(get(toasts)).toMatchObject([{ tone: 'success', title: 'Undone. Your old files are back.' }]);
  });
  it('the single card\'s undo (UpgradeFlow) toasts the same words', async () => {
    const { group } = setup('todo:check-renamed', 1000);
    const one = (await group('rekordbox_check'))!.items.find((i) => i.track_id === 'own:7')!;
    yes();
    const { UpgradeFlow } = await import('./flows.svelte');
    await new UpgradeFlow().undo('own:7', one.check);
    expect(get(toasts)).toMatchObject([{ tone: 'success', title: 'Clean name undone. Your old name is back.' }]);
  });
});
