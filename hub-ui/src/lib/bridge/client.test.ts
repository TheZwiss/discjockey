import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { api, onNoLibrary, runJob, _resetBridge } from './client';
import { dispatch } from './events';
import { toasts } from '../stores/toasts';
import { _resetJobs } from '../stores/jobs';

function fakeWindow(methods: Record<string, (...a: any[]) => any>) {
  const w = new EventTarget() as any;
  w.pywebview = { api: methods };
  (globalThis as any).window = w;
}
const finished = (job_id: number, extra: object = {}) => ({ type: 'JobFinished', job_id, kind: 'hide', ok: true,
  problem: null, message: '', result: { track_id: 't2', result: {}, recovered: [] }, ...extra }) as any;

beforeEach(() => { _resetBridge(); _resetJobs(); toasts.clear(); vi.spyOn(console, 'warn').mockImplementation(() => {}); });
afterEach(() => { vi.restoreAllMocks(); delete (globalThis as any).window; });

describe('calls', () => {
  it('passes ok:false through unchanged', async () => {
    const fail = { ok: false, kind: 'offline', message: 'No connection.' };
    fakeWindow({ dashboard: async () => fail });
    expect(await api.dashboard()).toEqual(fail);
  });
  it('passes positional arguments in order', async () => {
    const seen: unknown[] = [];
    fakeWindow({ library: async (...a: unknown[]) => { seen.push(...a); return { ok: true }; } });
    await api.library('Hard_Bounce', 'gim', 'weak', '-added');
    expect(seen).toEqual(['Hard_Bounce', 'gim', 'weak', '-added']);
  });
  it('turns a rejected promise into crashed, without the original text', async () => {
    fakeWindow({ dashboard: async () => { throw new Error('Traceback: KeyError'); } });
    const r = await api.dashboard();
    expect(r).toEqual({ ok: false, kind: 'crashed', message: 'Something went wrong. Try again.' });
  });
  it('waits for pywebviewready', async () => {
    const w = new EventTarget() as any;
    (globalThis as any).window = w;
    const p = api.sidebar();
    w.pywebview = { api: { sidebar: async () => ({ ok: true, todo: 3 }) } };
    w.dispatchEvent(new Event('pywebviewready'));
    expect(await p).toMatchObject({ ok: true, todo: 3 });
  });
});

describe('runJob', () => {
  it('resolves when JobFinished arrives after the job id', async () => {
    fakeWindow({ hide: async () => ({ ok: true, job_id: 7 }) });
    const p = runJob(api.hide('t2', true));
    await new Promise((r) => setTimeout(r, 0));
    dispatch(finished(7));
    const out = await p;
    expect(out).toMatchObject({ ok: true, job_id: 7 });
    expect(get(toasts).map((t) => t.title)).toEqual(['Hidden from the to-do list.']);
  });
  it('resolves when JobFinished arrived before the bridge call returned', async () => {
    fakeWindow({ hide: async () => { dispatch(finished(8)); return { ok: true, job_id: 8 }; } });
    expect(await runJob(api.hide('t2', true))).toMatchObject({ ok: true, job_id: 8 });
  });
  it('resolves an immediate refusal at once with job_id null', async () => {
    fakeWindow({ hide: async () => ({ ok: false, kind: 'busy', message: 'Wait.' }) });
    const out = await runJob(api.hide('t2', true));
    expect(out).toEqual({ ok: false, job_id: null, kind: 'busy', message: 'Wait.' });
    expect(get(toasts)[0]).toMatchObject({ tone: 'problem', body: 'Wait.' });
  });
  it('quiet suppresses the problem toast', async () => {
    fakeWindow({ hide: async () => ({ ok: true, job_id: 9 }) });
    const p = runJob(api.hide('t2', true), { quiet: true });
    dispatch(finished(9, { ok: false, problem: 'changed', message: 'It changed.', result: null }));
    expect(await p).toEqual({ ok: false, job_id: 9, kind: 'changed', message: 'It changed.', result: null });
    expect(get(toasts)).toEqual([]);
  });
  it('a job that ends with a problem still hands over its result (a stopped move batch)', async () => {
    fakeWindow({ tidy_up: async () => ({ ok: true, job_id: 11 }) });
    const p = runJob(api.tidy_up([[1, 'Library/A/x.aiff']]), { quiet: true });
    const result = { batch_id: 3, title: 'Tidy-up', moved: 1, headline: 'Moved 1 file.', skipped: [], stopped: true };
    dispatch(finished(11, { ok: false, problem: 'stopped', message: 'Stopped.', result }));
    expect(await p).toMatchObject({ ok: false, kind: 'stopped', result });
  });
  it('success:false suppresses the success toast; recovered lines become an info toast', async () => {
    fakeWindow({ hide: async () => ({ ok: true, job_id: 10 }) });
    const p = runJob(api.hide('t2', true), { success: false });
    dispatch(finished(10, { result: { track_id: 't2', result: {}, recovered: [['Moved a file back', true]] } }));
    await p;
    expect(get(toasts).map((t) => [t.tone, t.body])).toEqual([['info', 'Moved a file back']]);
  });
});

describe('no_library', () => {
  it('tells the handlers on any call that answers it, and on no other failure', async () => {
    fakeWindow({
      todo: async () => ({ ok: false, kind: 'no_library', message: 'Gone.' }),
      dashboard: async () => ({ ok: false, kind: 'offline', message: 'No connection.' }),
    });
    const seen = vi.fn();
    const off = onNoLibrary(seen);
    await api.dashboard();
    expect(seen).not.toHaveBeenCalled();
    expect(await api.todo('all', false)).toMatchObject({ ok: false, kind: 'no_library' });
    expect(seen).toHaveBeenCalledTimes(1);
    off();
    await api.todo('all', false);
    expect(seen).toHaveBeenCalledTimes(1);
  });
});
