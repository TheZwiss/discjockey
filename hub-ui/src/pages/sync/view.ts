// Which Sync view shows (plan Task 65, "Which view shows"; issue 39 E4b: the Terminal's sync too). Pure, so the routing
// rule is tested.
import { writable } from 'svelte/store';
import { ACTIVE_PHASES, type RunState } from '$lib/stores/run';
import type { TerminalSync } from '$lib/stores/follow';
import { runIdFromReport } from '$lib/format';

/** Whose sync a live view or an end screen shows: the window's own, or the one the Terminal runs (`followRun`) */
export type SyncSource = 'own' | 'terminal';
export type SyncView = { view: 'before' } | { view: 'live'; source: SyncSource }
  | { view: 'end'; run_id: string | null; source: SyncSource };

export type ViewInput = {
  /** the window's own download job (`run`) */
  own: RunState;
  /** the hub store says the window's own sync runs (it can know before the run store does, after a reload) */
  hubSyncRunning: boolean;
  /** `#/sync/run/:run_id` */
  route?: string | null;
  /** the finished jobs the person went back to the plan from */
  dismissed?: ReadonlySet<string>;
  /** the Terminal's sync (`terminalSync`) and its followed state; null while there is none */
  terminal?: { sync: Pick<TerminalSync, 'job' | 'running'>; run: RunState } | null;
  /** the newest sync of this music folder (`last_sync.job`, the engine's registry): which end is the later one */
  newest?: string | null;
};

const ACTIVE = new Set<string>(ACTIVE_PHASES);
const ended = (r: RunState) => r.job_kind === 'sync' && (r.phase === 'finished' || r.phase === 'failed');

/** The run id of a finished sync's report (its RunFinished, else its JobFinished result); null with none (a sync that
 *  failed before it filed one) */
export function endRunId(r: RunState): string | null {
  return runIdFromReport(r.run_finished?.report_path ?? (r.job_finished?.result as { report?: string } | null)?.report);
}

/**
 * `#/sync/run/:run_id` → end screen. The window's own sync running → its live view. Else the Terminal's sync running
 * → its live view (also while its state catches up, and until its end has arrived). Else a sync that finished in this
 * session → its end screen, until the person went back to the plan from it; when both the own and the Terminal's
 * have one, the newer (the engine's newest sync), the own when that is not known. Else the hub store's own sync
 * (before the run store knows it) → its live view. Else → before the start: a Terminal job of another kind (a
 * tidy-up, a scan) keeps the plan with its note.
 */
export function whichView(i: ViewInput): SyncView {
  const dismissed = i.dismissed ?? new Set<string>();
  if (i.route) return { view: 'end', run_id: i.route, source: 'own' };
  const own = i.own.job_kind === 'sync' ? i.own : null;
  if (own && ACTIVE.has(own.phase)) return { view: 'live', source: 'own' };
  // the two can't run at once (one library lock): a Terminal sync that runs is newer than any own end
  const t = i.terminal ?? null;
  if (t && !ended(t.run) && (t.sync.running || ACTIVE.has(t.run.phase))) return { view: 'live', source: 'terminal' };
  const open = (r: RunState | null): r is RunState => !!r && ended(r) && r.job_id !== null && !dismissed.has(r.job_id);
  const ownEnd = open(own), terminalEnd = t !== null && open(t.run) && t.run.job_id === t.sync.job;
  if (terminalEnd && (!ownEnd || (i.newest != null && i.newest === t.run.job_id))) {
    return { view: 'end', run_id: endRunId(t.run), source: 'terminal' };
  }
  if (ownEnd) return { view: 'end', run_id: endRunId(i.own), source: 'own' };
  if (i.hubSyncRunning) return { view: 'live', source: 'own' };
  return { view: 'before' };
}

/** The finished jobs the person went back to the plan from (the end screen's Done, Back to the plan, Sync the rest) */
export const dismissedJobs = writable<ReadonlySet<string>>(new Set());
export function dismissJob(job: string): void {
  dismissedJobs.update((s) => (s.has(job) ? s : new Set([...s, job])));
}
