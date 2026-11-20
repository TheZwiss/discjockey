import { beforeEach, describe, expect, it, vi } from 'vitest';
import { readable } from 'svelte/store';
import { EMPTY_RUN, type RunState } from '$lib/stores/run';

// the bridge is a stub that records what Stop safely asks; the run store's mark is a spy
const stops: (string | undefined)[] = [];
let answer: unknown = { ok: true, stopped: true };
vi.mock('$lib/bridge/client', () => ({
  api: { stop: async (job_id?: string) => { stops.push(job_id); return answer; } },
  onNoLibrary: () => {},
}));
const marks = vi.fn();
vi.mock('$lib/stores/run', async (orig) => ({ ...(await orig<typeof import('$lib/stores/run')>()), markStopping: () => marks() }));
const { JOINING, TERMINAL_WHERE, joining, ownSource, selectionOf, terminalSource } = await import('./liveSource');
const { run } = await import('$lib/stores/run');

const JOB = 'job:00000c0d';
const followed = readable<RunState>(EMPTY_RUN);
beforeEach(() => { stops.length = 0; marks.mockClear(); answer = { ok: true, stopped: true }; });

describe('the own source', () => {
  it('is the window\'s run with no status line, its Stop the window\'s own with the mark at once', async () => {
    expect(ownSource).toMatchObject({ kind: 'own', job: null, where: undefined });
    expect(ownSource.run).toBe(run);
    expect(await ownSource.stop()).toEqual({ ok: true, waits: false });
    expect(stops).toEqual([undefined]);
    expect(marks).toHaveBeenCalledOnce();
  });
  it('marks nothing when nothing was stopped, and passes a refusal on', async () => {
    answer = { ok: true, stopped: false };
    expect(await ownSource.stop()).toEqual({ ok: true, waits: false });
    answer = { ok: false, kind: 'crashed', message: 'It broke.' };
    expect(await ownSource.stop()).toEqual({ ok: false, message: 'It broke.' });
    expect(marks).not.toHaveBeenCalled();
  });
});

describe('the Terminal source', () => {
  const t = terminalSource(JOB, followed);
  it('is the followed state, its header says where it runs', () => {
    expect(t).toMatchObject({ kind: 'terminal', job: JOB, where: 'In the Terminal' });
    expect(TERMINAL_WHERE).toBe('In the Terminal');
    expect(t.run).toBe(followed);
  });
  it('Stop safely stops that job (stop(job_id)) and waits for its "stopping", with no mark of the window\'s own', async () => {
    expect(await t.stop()).toEqual({ ok: true, waits: true });
    expect(stops).toEqual([JOB]);
    answer = { ok: true, stopped: false };   // it had ended: nothing to wait for
    expect(await t.stop()).toEqual({ ok: true, waits: false });
    answer = { ok: false, kind: 'bad_args', message: 'No such job.' };
    expect(await t.stop()).toEqual({ ok: false, message: 'No such job.' });
    expect(marks).not.toHaveBeenCalled();
  });
  it('is joining while nothing of the job was read yet', () => {
    expect(joining(t, EMPTY_RUN)).toBe(true);
    expect(joining(t, { ...EMPTY_RUN, phase: 'preparing' })).toBe(false);
    expect(joining(ownSource, EMPTY_RUN)).toBe(false);   // the own view keeps its "Getting ready" card
    expect(JOINING).toBe('Looking up its progress…');
  });
});

describe('selectionOf', () => {
  const last = { job: JOB, args: { plan_id: 'plan:abc', selected: ['a1'] }, ended: null };
  it('the own view takes the newest sync\'s record, the Terminal view only its own job\'s', () => {
    expect(selectionOf(ownSource, last)).toBe(last);
    expect(selectionOf(terminalSource(JOB, followed), last)).toBe(last);
    expect(selectionOf(terminalSource('job:00000001', followed), last)).toBeNull();
    expect(selectionOf(ownSource, null)).toBeNull();
  });
});
