import { describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { EMPTY_RUN, type RunState } from '$lib/stores/run';
import { dismissJob, dismissedJobs, endRunId, whichView, type ViewInput } from './view';

const OWN = 'job:00000002', TERM = 'job:00000c0d';
const r = (o: Partial<RunState>, job_id = OWN): RunState => ({ ...EMPTY_RUN, job_id, job_kind: 'sync', ...o });
const finished = (job_id: string, stamp: string): RunState => r({ phase: 'finished', run_finished: { type: 'RunFinished',
  exit_code: 0, report_path: `/x/reports/${stamp}.md` } }, job_id);
const view = (o: Partial<ViewInput>) => whichView({ own: EMPTY_RUN, hubSyncRunning: false, ...o });
const terminal = (run: RunState, running = true) => ({ sync: { job: TERM, running }, run });

describe('whichView: the window\'s own sync', () => {
  it('shows the end screen for a run id in the route', () => {
    expect(view({ own: r({ phase: 'running' }), hubSyncRunning: true, route: '2026-10-01_100000' }))
      .toEqual({ view: 'end', run_id: '2026-10-01_100000', source: 'own' });
  });
  it('shows the live view while a sync runs, also before the hub store knows', () => {
    expect(view({ own: r({ phase: 'preparing' }) })).toEqual({ view: 'live', source: 'own' });
    expect(view({ hubSyncRunning: true })).toEqual({ view: 'live', source: 'own' });
  });
  it('shows the end screen of a sync that just finished, until dismissed', () => {
    const own = finished(OWN, '2026-10-16_141111');
    expect(view({ own })).toEqual({ view: 'end', run_id: '2026-10-16_141111', source: 'own' });
    expect(view({ own, dismissed: new Set([OWN]) })).toEqual({ view: 'before' });
  });
  it('a failed sync with no report has an end screen without a run id', () => {
    const own = r({ phase: 'failed', job_finished: { type: 'JobFinished', job_id: OWN, kind: 'sync', ok: false,
      problem: 'login_expired', message: 'Log in again.', result: null } });
    expect(view({ own })).toEqual({ view: 'end', run_id: null, source: 'own' });
    expect(endRunId(own)).toBeNull();
  });
  it('shows the plan otherwise, also after a use_candidate download', () => {
    expect(view({})).toEqual({ view: 'before' });
    expect(view({ own: r({ job_kind: 'use_candidate', phase: 'running' }) })).toEqual({ view: 'before' });
  });
});

describe('whichView: a sync the Terminal runs', () => {
  it('the own sync wins', () => {
    expect(view({ own: r({ phase: 'running' }), terminal: terminal(r({ phase: 'running' }, TERM)) }))
      .toEqual({ view: 'live', source: 'own' });
  });
  it('shows its live view while it runs, also while its state is still being read (idle) and after the console cleared', () => {
    expect(view({ terminal: terminal(r({ phase: 'running' }, TERM)) })).toEqual({ view: 'live', source: 'terminal' });
    expect(view({ terminal: terminal(EMPTY_RUN) })).toEqual({ view: 'live', source: 'terminal' });
    // the watch's JobFinished lands one poll after ConsoleBusy(false): the view stays live, it doesn't flash the plan
    expect(view({ terminal: terminal(r({ phase: 'running' }, TERM), false) })).toEqual({ view: 'live', source: 'terminal' });
  });
  it('a Terminal sync that runs is newer than an own end screen still open', () => {
    expect(view({ own: finished(OWN, '2026-10-16_141111'), terminal: terminal(r({ phase: 'running' }, TERM)) }))
      .toEqual({ view: 'live', source: 'terminal' });
  });
  it('at its end shows its end screen by its report\'s run id, until the person goes back to the plan', () => {
    const t = terminal(finished(TERM, '2026-11-20_210000'), false);
    expect(view({ terminal: t })).toEqual({ view: 'end', run_id: '2026-11-20_210000', source: 'terminal' });
    // its events say it ended before the window's watch cleared the console: the end shows already
    expect(view({ terminal: { ...t, sync: { job: TERM, running: true } } }))
      .toEqual({ view: 'end', run_id: '2026-11-20_210000', source: 'terminal' });
    expect(view({ terminal: t, dismissed: new Set([TERM]) })).toEqual({ view: 'before' });
  });
  it('a Terminal sync that ended before anything of it was read keeps the plan', () => {
    expect(view({ terminal: terminal(EMPTY_RUN, false) })).toEqual({ view: 'before' });
  });
  it('with an own and a Terminal end open, the newer (the engine\'s newest sync) shows; the own when that is unknown', () => {
    const own = finished(OWN, '2026-10-16_141111'), t = terminal(finished(TERM, '2026-11-20_210000'), false);
    expect(view({ own, terminal: t, newest: TERM })).toMatchObject({ view: 'end', source: 'terminal' });
    expect(view({ own, terminal: t, newest: OWN })).toMatchObject({ view: 'end', source: 'own' });
    expect(view({ own, terminal: t, newest: null })).toMatchObject({ view: 'end', source: 'own' });
    // going back to the plan from one does not bring the other back once that was dismissed too
    expect(view({ own, terminal: t, newest: TERM, dismissed: new Set([TERM]) })).toMatchObject({ view: 'end', source: 'own' });
    expect(view({ own, terminal: t, dismissed: new Set([OWN, TERM]) })).toEqual({ view: 'before' });
  });
  it('a Terminal tidy-up (no Terminal sync) keeps the plan', () => {
    expect(view({ terminal: null })).toEqual({ view: 'before' });
  });
  it('a Terminal sync that ended keeps its end screen when a Terminal tidy-up starts after it (terminalSync keeps the sync)', () => {
    const t = terminal(finished(TERM, '2026-11-20_210000'), false);   // what terminalSync holds while the tidy-up runs
    expect(view({ terminal: t })).toEqual({ view: 'end', run_id: '2026-11-20_210000', source: 'terminal' });
    expect(view({ terminal: t, dismissed: new Set([TERM]) })).toEqual({ view: 'before' });   // Done: now the plan, with the tidy-up's note
  });
});

describe('dismissJob', () => {
  it('keeps every job the person went back from', () => {
    dismissJob('job:a'); dismissJob('job:b'); dismissJob('job:a');
    expect([...get(dismissedJobs)]).toEqual(expect.arrayContaining(['job:a', 'job:b']));
    expect(get(dismissedJobs).size).toBeGreaterThanOrEqual(2);
  });
});
