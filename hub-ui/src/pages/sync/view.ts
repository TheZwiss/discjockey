// Which Sync view shows (plan Task 65, "Which view shows"). Pure, so the routing rule is tested.
import { writable } from 'svelte/store';
import type { RunState } from '$lib/stores/run';
import { runIdFromReport } from '$lib/format';

export type SyncView = { view: 'before' } | { view: 'live' } | { view: 'end'; run_id: string | null };

const ACTIVE = new Set(['preparing', 'running', 'stopping']);

/**
 * `#/sync/run/:run_id` → end screen. A hub sync running → live view. A sync that finished in this session → its
 * end screen (unless the page was told to go back to the plan for that job). Else → before the start.
 */
export function whichView(run: RunState, hubSyncRunning: boolean, routeRunId: string | null | undefined,
  dismissedJob: number | null = null): SyncView {
  if (routeRunId) return { view: 'end', run_id: routeRunId };
  const mine = run.job_kind === 'sync';
  if (mine && ACTIVE.has(run.phase)) return { view: 'live' };
  if (mine && (run.phase === 'finished' || run.phase === 'failed') && run.job_id !== dismissedJob) {
    const report = run.run_finished?.report_path ?? (run.job_finished?.result as { report?: string } | null)?.report;
    return { view: 'end', run_id: runIdFromReport(report) };
  }
  if (hubSyncRunning) return { view: 'live' };
  return { view: 'before' };
}

/** Seam for the end screen (part B): "back to the plan" for this finished job. */
export const dismissedJob = writable<number | null>(null);
