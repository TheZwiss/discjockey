import { describe, expect, it } from 'vitest';
import { EMPTY_RUN, type RunState } from '$lib/stores/run';
import { whichView } from './view';

const r = (o: Partial<RunState>): RunState => ({ ...EMPTY_RUN, job_id: 2, job_kind: 'sync', ...o });
const finished = r({ phase: 'finished', run_finished: { type: 'RunFinished', exit_code: 0,
  report_path: '/x/reports/2026-10-16_141111.md' } });

describe('whichView', () => {
  it('shows the end screen for a run id in the route', () => {
    expect(whichView(r({ phase: 'running' }), true, '2026-10-01_100000')).toEqual({ view: 'end',
      run_id: '2026-10-01_100000' });
  });
  it('shows the live view while a sync runs, also before the hub store knows', () => {
    expect(whichView(r({ phase: 'preparing' }), false, null)).toEqual({ view: 'live' });
    expect(whichView(EMPTY_RUN, true, null)).toEqual({ view: 'live' });
  });
  it('shows the end screen of a sync that just finished, until dismissed', () => {
    expect(whichView(finished, false, null)).toEqual({ view: 'end', run_id: '2026-10-16_141111' });
    expect(whichView(finished, false, null, 2)).toEqual({ view: 'before' });
  });
  it('shows the plan otherwise, also after a use_candidate download', () => {
    expect(whichView(EMPTY_RUN, false, null)).toEqual({ view: 'before' });
    expect(whichView(r({ job_kind: 'use_candidate', phase: 'running' }), false, null)).toEqual({ view: 'before' });
  });
});
