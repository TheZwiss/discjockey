// Where the Sync page's live view and end screen get their sync from (issue 39 E4b): the window's own (`run`, the
// window's events) or the one the Terminal runs (`followRun(job)`, its events file). One view draws both; what differs
// is only what is really different: the header says where it runs, Stop safely asks the engine to stop that job, and
// "Stopping…" comes from the followed job's status instead of the window's own mark.
import type { Readable } from 'svelte/store';
import { api } from '$lib/bridge/client';
import type { LastSync } from '$lib/bridge/types';
import { markStopping, run, type RunState } from '$lib/stores/run';
import type { SyncSource } from './view';

/** The header's status line of a Terminal sync's live view, beside "Sync running" / "Stopping…" */
export const TERMINAL_WHERE = 'In the Terminal';
/** The progress card's line while a Terminal sync joined late is read up to where it is (`followRun` publishes once
 *  caught up): its count, card and lists are not known yet */
export const JOINING = 'Looking up its progress…';

/** What Stop safely's round trip said: asked (and whether the view waits for the engine to say "stopping"), or the
 *  problem in the engine's words */
export type StopAsked = { ok: true; waits: boolean } | { ok: false; message: string };

export type LiveSource = {
  kind: SyncSource;
  /** the live state of the sync: the same `RunState` (and reducer) for both */
  run: Readable<RunState>;
  /** the sync whose ticked songs (`last_sync`) name Up next until its run's plan arrives; null: the newest sync's */
  job: string | null;
  /** the header's status line; none for the window's own */
  where: string | undefined;
  stop: () => Promise<StopAsked>;
};

/** The window's own sync: Stop safely stops the window's job and marks the run stopping at once (`markStopping`) */
export const ownSource: LiveSource = {
  kind: 'own', run, job: null, where: undefined,
  async stop() {
    const r = await api.stop();
    if (!r.ok) return { ok: false, message: r.message };
    if (r.stopped) markStopping();
    return { ok: true, waits: false };
  },
};

/** The Terminal's sync `job`, followed in `followed`: Stop safely writes that job's stop file (`stop(job_id)`), and the
 *  followed state turns "stopping" once the job says so; until then the button stays busy */
export function terminalSource(job: string, followed: Readable<RunState>): LiveSource {
  return {
    kind: 'terminal', run: followed, job, where: TERMINAL_WHERE,
    async stop() {
      const r = await api.stop(job);
      return r.ok ? { ok: true, waits: r.stopped } : { ok: false, message: r.message };
    },
  };
}

/** The record of what the shown sync was started with, or null when the newest sync is another one */
export const selectionOf = (source: Pick<LiveSource, 'job'>, last: LastSync | null): LastSync | null =>
  last && (source.job === null || last.job === source.job) ? last : null;

/** A Terminal sync joined late whose events are still being read: nothing of it is known yet (phase idle) */
export const joining = (source: Pick<LiveSource, 'kind'>, r: RunState): boolean =>
  source.kind === 'terminal' && r.phase === 'idle';
