// Auto-upgrade in the fake backend: the same answers as the engine (tests/test_hub_auto_upgrade.py).
import { describe, expect, it } from 'vitest';
import { createFakeBridge } from './bridge';
import type { HubEvent } from '../events';
import { AUTO_REFUSED_SHORT as FAKE_SHORT, autoLine, planPhase, phaseEvents, readyTracks } from './auto';
import { AUTO_REFUSED_SHORT } from '$lib/decisions/decisionModel';
import { isBatch } from '../types';
import type { Fail, RekordboxStatus, RunDetail, SetupStatus, SyncPreview, Todo, TodoItem } from '../types';

const until = (evs: HubEvent[], jobId: number, ms = 3000) => new Promise<HubEvent>((resolve, reject) => {
  const t0 = Date.now();
  const tick = () => {
    const hit = evs.find((e) => e.type === 'JobFinished' && e.job_id === jobId);
    if (hit) return resolve(hit);
    if (Date.now() - t0 > ms) return reject(new Error('timeout'));
    setTimeout(tick, 5);
  };
  tick();
});
function make(scenario: string) {
  const evs: HubEvent[] = [];
  const f = createFakeBridge(scenario, { speed: 50, emit: (e) => evs.push(e) });
  const run = async (start: Promise<unknown>) => {
    const s = (await start) as { ok: boolean; job_id?: number };
    return s.ok ? until(evs, s.job_id!) : (s as unknown as Fail);
  };
  const status = async () => (await f.setup_status()) as SetupStatus & { ok: true };
  return { f, run, status, evs };
}

describe('fake Auto-upgrade', () => {
  it('the switch is on by default, saves, and must be true or false', async () => {
    const m = make('normal');
    expect((await m.status()).auto_upgrade).toBe(true);
    expect(await m.run(m.f.set_auto_upgrade(false))).toMatchObject({ kind: 'set_auto_upgrade', ok: true });
    expect((await m.status()).auto_upgrade).toBe(false);
    expect(await m.run(m.f.set_auto_upgrade(true))).toMatchObject({ ok: true });
    expect((await m.status()).auto_upgrade).toBe(true);
    expect(await m.f.set_auto_upgrade('yes' as unknown as boolean)).toMatchObject({ ok: false, kind: 'refused', message: 'on must be true or false.' });
  });
  it('rekordbox_status answers its state and whether it runs', async () => {
    expect(await make('normal').f.rekordbox_status()).toEqual({ ok: true, state: 'ready', running: false } satisfies RekordboxStatus & { ok: true });
    const m = make('normal');
    m.f._ctx.s.rekordbox_running = true;
    m.f._ctx.s.rekordbox_state = 'unreadable';
    expect(await m.f.rekordbox_status()).toEqual({ ok: true, state: 'unreadable', running: true });
  });
  it('the preview counts the upgrades the phase would do, and is null with the switch off', async () => {
    const m = make('normal');
    await m.f.refresh();
    await new Promise((r) => setTimeout(r, 300));
    const on = (await m.f.sync_preview()) as SyncPreview & { ok: true };
    expect(on.auto_upgrade?.on).toBe(true);
    expect(on.auto_upgrade?.ready).toBeGreaterThanOrEqual(0);
    await m.run(m.f.set_auto_upgrade(false));
    expect(((await m.f.sync_preview()) as SyncPreview & { ok: true }).auto_upgrade).toBeNull();
  });
});

// ---------- the sync's last phase and the nine scenarios ----------
const ANY: [string, string, string][] = [['acquire', 't4', 'Library/Hard_Bounce']];
type Ev<T extends HubEvent['type']> = Extract<HubEvent, { type: T }>;
const preview = async (f: ReturnType<typeof make>['f']) => {
  await f.refresh();
  await new Promise((r) => setTimeout(r, 300));
  return (await f.sync_preview()) as SyncPreview & { ok: true };
};
const todo = async (f: ReturnType<typeof make>['f'], filter: 'all' | 'upgrade_ready' | 'rekordbox_check' = 'all') =>
  (await f.todo(filter, false)) as Todo & { ok: true };
const ready = async (f: ReturnType<typeof make>['f']) => (await todo(f, 'upgrade_ready')).groups.find((g) => g.key === 'upgrade_ready')!.items;
/** Starts the sync and returns its stored run once it has finished. */
async function syncRun(m: ReturnType<typeof make>) {
  const done = await m.run(m.f.start_sync(ANY));
  expect(done).toMatchObject({ type: 'JobFinished', kind: 'sync' });
  const runs = (await m.f.runs()) as { ok: true; runs: { run_id: string }[] };
  const r = (await m.f.run(runs.runs[0].run_id)) as { ok: true; run: RunDetail };
  return r.run;
}

describe('fake sync: the Auto-upgrade phase', () => {
  it('sync:auto-done: 9 go in as one batch, rekordbox opens after the 10th (3 wait), 1 is refused', async () => {
    const m = make('sync:auto-done');
    const p = await preview(m.f);
    expect(p.auto_upgrade).toEqual({ on: true, ready: 13 });
    const run = await syncRun(m);
    const msgs = m.evs.filter((e): e is Ev<'Message'> => e.type === 'Message').map((e) => e.text);
    expect(msgs).toContain('Upgrading 13 tracks at the end of the sync...');
    const bp = m.evs.filter((e): e is Ev<'BatchProgress'> => e.type === 'BatchProgress');
    expect(bp).toHaveLength(10);                        // the batch reached 10 tracks; rekordbox opened before the 11th
    expect(bp[3]).toMatchObject({ done: 3, total: 13 });
    expect(bp.every((e) => e.batch_id === bp[0].batch_id)).toBe(true);
    const a = run.auto_upgrade!;
    expect(a).toMatchObject({ batch: bp[0].batch_id, done: 9, waiting: 3, refused: 1, failed: 0, stopped: false, dry_run: false });
    expect(a.backup).toMatch(/^\d{4}-\d\d-\d\dT\d\d-\d\d-\d\dZ$/);
    expect(a.results).toHaveLength(13);
    expect(a.results.filter((r) => r.state === 'done').every((r) => r.how !== null)).toBe(true);
    expect(a.results.filter((r) => r.state === 'waiting').map((r) => r.reason)).toEqual(['rekordbox_open', 'rekordbox_open', 'rekordbox_open']);
    expect(a.results.find((r) => r.state === 'refused')).toMatchObject({ reason: 'timing' });
    expect(a.line).toBe("Upgraded 9 tracks; your cues stayed. 3 wait for rekordbox to be closed. 1 couldn't go in; To-do says why.");
    // the sections agree with the block; the counts with the sections
    expect(run.sections.upgraded).toHaveLength(9);
    expect(run.sections.upgrade_waits).toHaveLength(4);
    expect(run.sections.upgraded.every((r) => r.status === 'lossless' && r.path)).toBe(true);
    expect(run.counts.lossless).toBe(a.done + (run.sections.new_lossless?.length ?? 0) + (run.sections.swapped?.length ?? 0)
      + (run.sections.redownloaded?.length ?? 0));
    // what To-do says afterwards
    expect((await m.f.rekordbox_status()) as RekordboxStatus).toMatchObject({ running: true });
    const rows = await ready(m.f);
    expect(rows).toHaveLength(5);                       // 3 waiting + 1 refused + the one edit that needs a choice (a base row)
    expect(rows.filter((r) => r.detail === 'Waits for rekordbox to be closed')).toHaveLength(3);
    expect(rows.filter((r) => r.detail === "Couldn't line it up · not upgraded at your sync")).toHaveLength(1);
    const checks = (await todo(m.f, 'rekordbox_check')).groups[0].items[0];
    expect(isBatch(checks) && checks.batch).toMatchObject({ size: 9, started_by: 'auto_upgrade' });
    expect(checks.detail).toMatch(/Upgraded during your sync$/);
    // the preview counts what is left to do (the refused one is held out; the 3 that wait are still ready)
    expect((await m.f.sync_preview() as SyncPreview & { ok: true }).auto_upgrade).toEqual({ on: true, ready: 3 });
  });

  it('sync:auto-done mirrors the engine: one row per track, en dash names, how on every row, the batch closed done', async () => {
    const m = make('sync:auto-done');
    await preview(m.f);
    const run = await syncRun(m);
    const a = run.auto_upgrade!;
    // a track the phase filed is told once: no upgrade_ready row beside its upgraded / upgrade_waits row (auto_upgrade._file)
    const phase = new Set([...(run.sections.upgraded ?? []), ...(run.sections.upgrade_waits ?? [])].map((r) => r.track_id));
    expect((run.sections.upgrade_ready ?? []).filter((r) => phase.has(r.track_id))).toEqual([]);
    expect(phase.size).toBe(13);
    expect(a.results.every((r) => r.name.includes(' \u2013 ') && r.how !== null)).toBe(true);   // BatchProgress.name too
    expect(m.evs.filter((e): e is Ev<'BatchProgress'> => e.type === 'BatchProgress' && !!e.name).every((e) => e.name!.includes(' \u2013 '))).toBe(true);
    // end_auto closes the batch done, with no stop reason, so To-do never offers Resume for it
    expect(await m.f.batch_resume(a.batch!)).toMatchObject({ ok: false, message: 'This batch is not stopped, so there is nothing to resume.' });
    // the refusal is recorded in the engine's own sentence (design \u00a78)
    expect(a.results.find((r) => r.state === 'refused')!.message)
      .toBe("Discjockey couldn't line the new file up with your rekordbox track exactly, so nothing was changed. Analyse the track again in rekordbox and try again.");
  });

  it('the To-do badge counts each row of To-do once, per scenario (a batch of checks is one card)', async () => {
    const badge = async (m: ReturnType<typeof make>) => ((await m.f.sidebar()) as { ok: true; todo: number }).todo;
    const groups = async (m: ReturnType<typeof make>) => (await todo(m.f)).groups.map((g) => `${g.key}:${g.items.length}`).join(' ');
    // normal: 19 rows, 2 of them upgrades ready (Get Naughty and the edit that needs a choice)
    const n = make('normal');
    expect(await badge(n)).toBe(19);
    // sync:auto-done: 12 more upgrades parked, from tracks that were weak or good lossy (they leave those rows): 23 rows
    const m = make('sync:auto-done');
    expect(await badge(m)).toBe(23);
    await syncRun(m);
    // after the sync the 9 upgraded tracks are one check card (+1), 3 wait and 1 is refused (still ready rows, each
    // counted once, not again under the report's upgrade_waits), and the 9 are no longer weak or lossy rows
    expect(await groups(m)).toBe('rekordbox_check:2 upgrade_ready:5 not_found:3 good_lossy:3 fake:3 other:1');
    expect(await badge(m)).toBe(16);
    expect(await badge(m)).toBe((await todo(m.f)).chips.all);
    // sync:auto-rekordbox-open: Get Naughty, the choice edit and 3 more (the same 19 rows); the phase changes no row
    const w = make('sync:auto-rekordbox-open');
    const waiting = await badge(w);
    expect(waiting).toBe(19);
    await syncRun(w);
    expect(await badge(w)).toBe(waiting + 1);                  // the +1 is the sync's own download (non stop, a good lossy row), not the phase
    // todo:auto-refused: one refusal per reason is a row of its own
    const r = make('todo:auto-refused');
    expect(await badge(r)).toBe(19);
    expect(await badge(r)).toBe((await todo(r.f)).chips.all);
  });

  it('sync:auto-done keeps an earlier sync with the phase in the reports', async () => {
    const m = make('sync:auto-done');
    const runs = ((await m.f.runs()) as { ok: true; runs: { auto_upgrade: RunDetail['auto_upgrade'] }[] }).runs;
    expect(runs.filter((r) => r.auto_upgrade)).toHaveLength(1);
    expect(runs.find((r) => r.auto_upgrade)!.auto_upgrade).toMatchObject({ done: 3, waiting: 0, refused: 0, line: 'Upgraded 3 tracks; your cues stayed.' });
    expect(runs.filter((r) => !r.auto_upgrade).length).toBeGreaterThanOrEqual(3);   // the other reports have no block
  });

  it('sync:auto-rekordbox-open: 4 ready, rekordbox open: no batch, all 4 wait and are marked', async () => {
    const m = make('sync:auto-rekordbox-open');
    expect((await preview(m.f)).auto_upgrade).toEqual({ on: true, ready: 4 });
    expect(await m.f.rekordbox_status()).toMatchObject({ running: true });
    const run = await syncRun(m);
    expect(m.evs.some((e) => e.type === 'BatchProgress')).toBe(false);
    expect(m.evs.filter((e): e is Ev<'Message'> => e.type === 'Message').map((e) => e.text)).toContain('4 upgrades wait for rekordbox to be closed.');
    expect(run.auto_upgrade).toMatchObject({ batch: null, backup: null, done: 0, waiting: 4, refused: 0, stopped: false,
      line: '4 upgrades wait for rekordbox to be closed.' });
    expect(run.sections.upgrade_waits).toHaveLength(4);
    expect(run.sections.upgraded).toBeUndefined();
    const details = (await ready(m.f)).map((r) => r.detail);
    expect(details.filter((d) => d === 'Waits for rekordbox to be closed')).toHaveLength(4);
    expect(details).toHaveLength(5);                    // and the edit that needs a choice (a base row)
    // a waiting upgrade still counts as ready for the next sync
    expect((await m.f.sync_preview() as SyncPreview & { ok: true }).auto_upgrade).toEqual({ on: true, ready: 4 });
  });

  it('the toolbar toggle (rekordbox open) is the state the phase meets at its start', async () => {
    const m = make('normal');
    expect(planPhase(m.f._ctx.s, 1)).toMatchObject({ batch: 1, order: ['t2'] });
    m.f._ctx.s.rekordbox_running = true;
    expect(planPhase(m.f._ctx.s, 1)).toMatchObject({ batch: null, order: [], rows: [{ track: 't2', state: 'waiting', reason: 'rekordbox_open' }] });
  });

  it('switch off: no phase, no block, no preview count', async () => {
    const m = make('sync:auto-done');
    await m.run(m.f.set_auto_upgrade(false));
    expect((await preview(m.f)).auto_upgrade).toBeNull();
    const run = await syncRun(m);
    expect(run.auto_upgrade).toBeNull();
    expect(m.evs.some((e) => e.type === 'BatchProgress')).toBe(false);
    expect(run.sections.upgraded).toBeUndefined();
    expect(await ready(m.f)).toHaveLength(14);          // 13 + the edit that needs a choice: nothing was touched
    expect((await ready(m.f)).filter((r) => r.detail.startsWith('Waits') || r.detail.endsWith('not upgraded at your sync'))).toHaveLength(0);
  });

  it('switch on but nothing ready: the block is there with nothing to say', async () => {
    const m = make('normal');
    m.f._ctx.s.tracks.forEach((t) => { t.upgrade = null; });
    const run = await syncRun(m);
    expect(run.auto_upgrade).toMatchObject({ batch: null, done: 0, waiting: 0, refused: 0, line: null });
  });

  it('a Stop in the phase ends the batch: the rest were not reached (exit 130)', async () => {
    const m = make('sync:auto-done');
    await m.f.start_sync(ANY);
    const t0 = Date.now();
    while (!m.evs.some((e) => e.type === 'BatchProgress' && e.done === 2) && Date.now() - t0 < 5000) await new Promise((r) => setTimeout(r, 5));
    expect(await m.f.stop()).toMatchObject({ ok: true, stopped: true });
    while (!m.evs.some((e) => e.type === 'JobFinished') && Date.now() - t0 < 8000) await new Promise((r) => setTimeout(r, 5));
    const runs = (await m.f.runs()) as { ok: true; runs: { run_id: string }[] };
    const run = ((await m.f.run(runs.runs[0].run_id)) as { ok: true; run: RunDetail }).run;
    const a = run.auto_upgrade!;
    expect(run.exit_code).toBe(130);
    expect(a.stopped).toBe(true);
    expect(a.done + a.waiting + a.refused).toBe(13);
    expect(a.done).toBeGreaterThanOrEqual(2);
    expect(a.results.filter((r) => r.reason === 'not_reached').length).toBe(a.waiting);   // rekordbox never opened: Stop came first
    expect(a.line).toMatch(/wait for your next sync\.$/);
    expect(run.sections.upgraded).toHaveLength(a.done);
    expect(await m.f.rekordbox_status()).toMatchObject({ running: false });
    const checks = (await todo(m.f, 'rekordbox_check')).groups[0].items[0];
    expect(a.done === 1 ? checks.batch === undefined : isBatch(checks) && checks.batch.size === a.done).toBe(true);
    expect(((await todo(m.f, 'upgrade_ready')).groups[0].stopped ?? null)).toBeNull();   // no Resume for an automatic batch
  });

  it('a Stop before the phase: no phase at all', async () => {
    const m = make('sync:auto-done');
    await m.f.start_sync(ANY);
    const t0 = Date.now();
    while (!m.evs.some((e) => e.type === 'ActionStarted') && Date.now() - t0 < 5000) await new Promise((r) => setTimeout(r, 5));
    await m.f.stop();
    while (!m.evs.some((e) => e.type === 'JobFinished') && Date.now() - t0 < 8000) await new Promise((r) => setTimeout(r, 5));
    const runs = (await m.f.runs()) as { ok: true; runs: { run_id: string }[] };
    const run = ((await m.f.run(runs.runs[0].run_id)) as { ok: true; run: RunDetail }).run;
    expect(run.exit_code).toBe(130);
    expect(run.auto_upgrade).toBeNull();
    expect(m.evs.some((e) => e.type === 'BatchProgress')).toBe(false);
  });

  it('sync:auto-running: a sync already in its phase, 3 of 8 done, the 4th in work', async () => {
    const m = make('sync:auto-running');
    expect((await m.f.rekordbox_status()) as RekordboxStatus).toMatchObject({ running: false });
    const js = (await m.f.job_status()) as { ok: true; job: { kind: string; running: boolean; last: Record<string, any> } };
    expect(js.job).toMatchObject({ kind: 'sync', running: true });
    expect(js.job.last.BatchProgress).toMatchObject({ done: 3, total: 8 });
    expect(js.job.last.BatchProgress.name).toBeTruthy();
    expect(js.job.last.Message.text).toBe('Upgrading 8 tracks at the end of the sync...');
    expect(js.job.last.RunFinished).toBeUndefined();
  });

  it('the end screen\'s short reasons are To-do\'s (views.AUTO_REFUSED_SHORT), capitalised', () => {
    expect(Object.fromEntries(Object.entries(FAKE_SHORT).map(([k, v]) => [k, v[0].toUpperCase() + v.slice(1)]))).toEqual(AUTO_REFUSED_SHORT);
  });
  it('the line is report.auto_upgrade_line: singulars, n = 0, the next-sync clause', () => {
    const r = (state: string, reason: string | null = null) => ({ track: 'x', name: 'x', state, reason, message: null, how: null }) as never;
    expect(autoLine({ done: 1, refused: 0, results: [] })).toBe('Upgraded 1 track; your cues stayed.');
    expect(autoLine({ done: 1, refused: 1, results: [r('waiting', 'rekordbox_open'), r('waiting', 'busy')] }))
      .toBe("Upgraded 1 track; your cues stayed. 1 waits for rekordbox to be closed. 1 waits for your next sync. 1 couldn't go in; To-do says why.");
    expect(autoLine({ done: 0, refused: 1, results: [r('waiting', 'rekordbox_open')] }))
      .toBe("1 upgrade waits for rekordbox to be closed. 1 upgrade couldn't go in; To-do says why.");
    expect(autoLine({ done: 0, refused: 0, results: [r('waiting', 'not_reached'), r('waiting', 'not_reached')] }))
      .toBe('2 upgrades wait for your next sync.');
    expect(autoLine({ done: 0, refused: 0, results: [] })).toBeNull();
  });

  it('phaseEvents: a batch that got through sends the closing progress; one that rekordbox stopped does not', () => {
    const s = make('normal').f._ctx.s;
    const plan = planPhase(s, 4)!;
    const evs = phaseEvents(plan);
    expect(evs.map((e) => e.type)).toEqual(['Message', 'BatchProgress', 'BatchProgress']);
    expect(evs.at(-1)).toMatchObject({ batch_id: 4, done: 1, total: 1, track_id: null, name: null });
    expect(readyTracks(s).map((t) => t.track_id)).toEqual(['t2']);
  });
});

describe('fake To-do, Settings and Setup: the Auto-upgrade states', () => {
  it('todo:auto-waits: 3 of 5 ready upgrades wait for rekordbox; Replace stays', async () => {
    const m = make('todo:auto-waits');
    const rows = await ready(m.f);
    expect(rows).toHaveLength(6);                       // Get Naughty, the edit that needs a choice, and 4 more
    expect(rows.filter((r) => r.detail === 'Waits for rekordbox to be closed')).toHaveLength(3);
    const marked = rows.filter((r) => r.detail === 'Waits for rekordbox to be closed')[0];
    const t = (await m.f.track(marked.track_id)) as { ok: true; track: { upgrade: { auto_waits: boolean; auto_refused: unknown } } };
    expect(t.track.upgrade).toMatchObject({ auto_waits: true, auto_refused: null });
    expect(rows.filter((r) => r.same_track === null)).toHaveLength(5);   // Replace stays for all of those
    expect((await m.f.sync_preview() as SyncPreview & { ok: true }).auto_upgrade?.ready).toBe(5);   // waiting ones count
  });

  it('todo:auto-refused: one refusal per reason, each with the engine\'s words', async () => {
    const m = make('todo:auto-refused');
    const rows = await ready(m.f);
    const refused = rows.filter((r) => r.detail.endsWith(' · not upgraded at your sync'));
    expect(refused.map((r) => r.detail.split(' · ')[0]).sort()).toEqual(
      ["Couldn't compare it", "Couldn't line it up", 'In Cloud Library Sync', 'Not analysed in rekordbox', 'Not enough free space']);
    const reasons = new Set<string>();
    for (const r of refused) {
      const t = (await m.f.track(r.track_id)) as { ok: true; track: { upgrade: { auto_refused: { reason: string; message: string; at: string } } } };
      const a = t.track.upgrade.auto_refused;
      reasons.add(a.reason);
      expect(a.message.length).toBeGreaterThan(20);
      expect(a.at).toMatch(/^\d{4}-/);
    }
    expect([...reasons].sort()).toEqual(['cloud', 'needs_choice', 'not_analysed', 'space', 'timing']);
    expect(rows).toHaveLength(7);                       // with Get Naughty and the edit that needs a choice, which are not refused
    expect(rows.filter((r) => !r.detail.endsWith('not upgraded at your sync')).length).toBe(2);
    expect((await m.f.sync_preview() as SyncPreview & { ok: true }).auto_upgrade?.ready).toBe(1);   // refused ones are held out
  });

  it('todo:auto-batch: four tracks upgraded by a sync are one card, named from the sync', async () => {
    const m = make('todo:auto-batch');
    const t = await todo(m.f, 'rekordbox_check');
    const item = t.groups.find((g) => g.key === 'rekordbox_check')!.items.find((i): i is TodoItem => isBatch(i))!;
    expect(item.batch).toMatchObject({ id: 7, size: 4, started_by: 'auto_upgrade' });
    expect(item.batch!.tracks).toHaveLength(4);
    expect(item.detail).toMatch(/ · Upgraded during your sync$/);
  });

  it('settings:upgrades-on / -off and setup:downloads-auto answer the switch', async () => {
    expect((await make('settings:upgrades-on').status()).auto_upgrade).toBe(true);
    expect((await make('settings:upgrades-off').status()).auto_upgrade).toBe(false);
    const setup = await make('setup:downloads-auto').status();
    expect(setup).toMatchObject({ auto_upgrade: true, qobuz: true, next_step: 'playlists', complete: false });   // as setup:downloads-all: open #/setup/downloads
  });
});
