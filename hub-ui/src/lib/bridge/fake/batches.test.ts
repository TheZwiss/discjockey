// The fake mirrors the Same track batches of the real bridge (issue 33 stage B): lists in, BatchProgress, Stop and
// Resume, rekordbox_open, the batch check item, batch undo.
import { describe, expect, it } from 'vitest';
import { createFakeBridge } from './bridge';
import type { HubEvent } from '../events';
import { isBatch, type AiffBatchResult, type Todo, type TodoItem, type UndoResult } from '../types';

function setup(scenario = 'upgrade-multi') {
  const evs: HubEvent[] = [];
  const f = createFakeBridge(scenario, { speed: 400, emit: (e) => evs.push(e) });
  const finished = async (id: number) => {
    for (let i = 0; i < 400; i++) {
      const e = evs.find((x) => x.type === 'JobFinished' && x.job_id === id);
      if (e) return e as Extract<HubEvent, { type: 'JobFinished' }>;
      await new Promise((r) => setTimeout(r, 5));
    }
    throw new Error('the job did not finish');
  };
  const run = async (start: Promise<{ ok: boolean; job_id?: number }>) => {
    const r = await start;
    if (!r.ok) throw new Error(JSON.stringify(r));
    return finished(r.job_id!);
  };
  const group = async (key: string) => {
    const t = (await f.todo('all', false)) as Todo & { ok: true };
    return t.groups.find((g) => g.key === key);
  };
  return { evs, f, run, group };
}

describe('the fake bridge: Same track batches', () => {
  it('bad input is refused like the real bridge', async () => {
    const { f } = setup();
    for (const bad of ['t1', [], [3], null]) {
      expect(await f.upgrade(bad as never, 'swap')).toMatchObject({ ok: false, kind: 'refused' });
    }
    expect(await f.batch_resume(99)).toMatchObject({ ok: false, kind: 'refused' });
  });

  it('Upgrade all runs one batch with progress; its checks are one item; Undo all puts them back', async () => {
    const { evs, f, run, group } = setup();
    const before = await group('upgrade_ready');
    expect(before?.all).toBeDefined();
    const n = before!.all!.n;
    expect(n).toBeGreaterThan(1);
    expect(before!.items.filter((i) => i.same_track === null).length).toBe(n);
    const done = await run(f.upgrade_all());
    expect(done).toMatchObject({ kind: 'upgrade_batch', ok: true });
    const r = done.result as AiffBatchResult;
    expect([r.state, r.done, r.total]).toEqual(['done', n, r.total]);
    const progress = evs.filter((e) => e.type === 'BatchProgress');
    expect(progress.at(-1)).toMatchObject({ batch_id: r.batch, done: r.total, total: r.total, track_id: null });
    const checks = await group('rekordbox_check');
    const batch = checks!.items.find(isBatch);
    expect(batch).toMatchObject({ key: `batch:${r.batch}`, track_id: `batch:${r.batch}` });
    expect(batch!.batch.size).toBe(n);
    expect(batch!.batch.tracks.every((t: TodoItem) => t.check?.batch?.id === r.batch && t.can_undo)).toBe(true);
    const undone = await run(f.batch_undo(r.batch!));
    expect(undone).toMatchObject({ kind: 'batch_undo', ok: true });
    const u = undone.result as UndoResult;
    expect([u.batch, u.undone, u.total]).toEqual([r.batch, n, n]);
    expect((await group('upgrade_ready'))!.all!.n).toBe(n);
  });

  it('rekordbox open stops a batch with a file that needs a write, before anything changed', async () => {
    const { f, run, group } = setup('upgrade-rekordbox-open');
    const ids = (await group('upgrade_ready'))!.items.filter((i) => i.same_track === null).map((i) => i.track_id);
    const done = await run(f.upgrade(ids, 'swap'));
    expect(done).toMatchObject({ ok: false, problem: 'rekordbox_open' });
    expect((done.result as AiffBatchResult).stop_reason).toBe('rekordbox_open');
    expect((await group('upgrade_ready'))!.stopped).toMatchObject({ left: ids.length });
  });

  it('Stop leaves the rest planned and Resume does it; rekordbox open stops with its own problem', async () => {
    const { evs, f, run, group } = setup();
    const ids = (await group('upgrade_ready'))!.items.filter((i) => i.same_track === null).map((i) => i.track_id).slice(0, 3);
    const start = f.upgrade(ids, 'swap');
    for (let i = 0; i < 400 && !evs.some((e) => e.type === 'BatchProgress'); i++) await new Promise((r) => setTimeout(r, 2));
    await f.stop();
    const stopped = await run(start);
    expect(stopped).toMatchObject({ ok: false, problem: 'stopped' });
    expect((stopped.result as AiffBatchResult).stop_reason).toBe('stop');
    const g = await group('upgrade_ready');
    expect(g!.stopped!.left).toBeGreaterThan(0);
    const resumed = await run(f.batch_resume(g!.stopped!.batch_id));
    expect(resumed).toMatchObject({ kind: 'batch_resume', ok: true });
    expect((await group('upgrade_ready'))?.stopped ?? null).toBeNull();
  });
});
