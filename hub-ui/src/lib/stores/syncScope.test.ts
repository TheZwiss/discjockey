import { afterEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { createFakeBridge } from '../bridge/fake/bridge';
import { _resetBridge, installBridge } from '../bridge/client';
import { dispatch } from '../bridge/events';
import { _resetJobs } from './jobs';
import { toasts } from './toasts';
import { syncScope, toggleCollection } from './syncScope';
import { toggleScope } from '../../pages/sync/planModel';

const BOUNCE = 'playlist:0DiscjockeyExampleList';
const HARD = 'folder:Library/Hard_Bounce';

/** A window whose bridge is the fake, its job events routed to the stores as the app does. */
function fake() {
  (globalThis as any).window = new EventTarget();  // the bridge's window (node has no DOM)
  _resetBridge();
  _resetJobs();   // a new fake numbers its jobs again: an older finished job of the same id would end a wait too soon
  const f = createFakeBridge('normal', { speed: 50, emit: dispatch });
  installBridge(f);
  return f;
}
const engine = async (f: ReturnType<typeof fake>) => {
  const r = await f.sync_scope();
  if (!r.ok) throw new Error('no scope');
  return { off: r.off.map((c) => c.target), kinds: r.weekly_off.map((k) => k.kind) };
};

/** The window starts on a fake whose scope is `scope`: somebody watches the store (the browser column always does), it
 *  reads the engine's value. */
let unsubscribe = () => {};
async function start(scope: { off: string[]; weekly_off: ('retry' | 'weekly')[] } = { off: [], weekly_off: [] }) {
  const f = fake();
  f._ctx.s.scope = scope;
  unsubscribe();
  unsubscribe = syncScope.subscribe(() => {});
  await vi.waitFor(() => expect(get(syncScope)).toEqual({ off: scope.off, kinds: scope.weekly_off }));
  return f;
}
afterEach(() => { unsubscribe(); vi.restoreAllMocks(); });

describe('the Sync scope store', () => {
  it('starts from the engine and a switch is written there', async () => {
    const f = await start({ off: [HARD], weekly_off: ['retry'] });
    toggleCollection(BOUNCE);
    expect(get(syncScope).off).toEqual([HARD, BOUNCE]);            // at once, before the job has run
    await vi.waitFor(async () => expect(await engine(f)).toEqual({ off: [HARD, BOUNCE], kinds: ['retry'] }));
  });

  it('two flips in a row both persist: the second waits for the first job', async () => {
    const f = await start();
    const spy = vi.spyOn(f, 'set_sync_scope');
    syncScope.update((s) => toggleScope(s, 'off', BOUNCE));
    syncScope.update((s) => toggleScope(s, 'kinds', 'weekly'));    // made while the first job is not finished
    syncScope.update((s) => toggleScope(s, 'off', HARD));          // and a third, merged with the second
    expect(get(syncScope)).toEqual({ off: [BOUNCE, HARD], kinds: ['weekly'] });
    await vi.waitFor(async () => expect(await engine(f)).toEqual({ off: [BOUNCE, HARD], kinds: ['weekly'] }));
    expect(spy.mock.calls).toEqual([[[], [BOUNCE]], [[], ['kind:weekly', HARD]]]);   // two jobs, never two at once
    expect(get(syncScope)).toEqual({ off: [BOUNCE, HARD], kinds: ['weekly'] });
  });

  it('a switch flipped back before it is sent says the last value', async () => {
    const f = await start();
    syncScope.update((s) => toggleScope(s, 'off', BOUNCE));
    syncScope.update((s) => toggleScope(s, 'kinds', 'retry'));
    syncScope.update((s) => toggleScope(s, 'kinds', 'retry'));     // retry on again
    await vi.waitFor(async () => expect(await engine(f)).toEqual({ off: [BOUNCE], kinds: [] }));
    expect(get(syncScope)).toEqual({ off: [BOUNCE], kinds: [] });
  });

  it('a refused job shows its problem and the scope is read again', async () => {
    const f = await start();
    vi.spyOn(f, 'set_sync_scope').mockResolvedValue({ ok: false, kind: 'refused', message: 'That is not a playlist.' });
    const shown: string[] = [];
    const stop = toasts.subscribe((list) => { shown.push(...list.map((t) => t.body ?? '')); });
    syncScope.update((s) => toggleScope(s, 'off', BOUNCE));
    expect(get(syncScope).off).toEqual([BOUNCE]);
    await vi.waitFor(() => expect(get(syncScope)).toEqual({ off: [], kinds: [] }));   // back to what the engine has
    expect(shown).toContain('That is not a playlist.');
    stop();
  });

  it('a read made while a switch is unsent does not put the old value back', async () => {
    const f = await start();
    syncScope.update((s) => toggleScope(s, 'off', BOUNCE));
    dispatch({ type: 'JobFinished', job_id: 'job:other', kind: 'scan', ok: true, problem: null, message: '', result: {}, service: null } as never);
    await new Promise((r) => setTimeout(r, 5));
    expect(get(syncScope).off).toEqual([BOUNCE]);
    await vi.waitFor(async () => expect((await engine(f)).off).toEqual([BOUNCE]));
  });
});
