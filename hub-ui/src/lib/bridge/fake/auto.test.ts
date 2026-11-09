// Auto-upgrade in the fake backend: the same answers as the engine (tests/test_hub_auto_upgrade.py).
import { describe, expect, it } from 'vitest';
import { createFakeBridge } from './bridge';
import type { HubEvent } from '../events';
import type { Fail, RekordboxStatus, SetupStatus, SyncPreview } from '../types';

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
