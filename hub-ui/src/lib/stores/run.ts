// The live state of the current download job (sync, use_candidate, use_link) as a pure reducer (plan 64.5),
// so it can be fed the recorded streams in tests.
import { writable, type Readable } from 'svelte/store';
import { onEvent, type Action, type EventOf, type HubEvent, type Step } from '../bridge/events';
import type { JobSnap, PlannedAction } from '../bridge/types';

export const DOWNLOAD_KINDS = ['sync', 'use_candidate', 'use_link'];
export const MAX_MESSAGES = 20;
const SMOOTH = 0.3;   // weight of the newest rate sample
const READING = 'Reading your Spotify playlists';
/** "Reading your Spotify playlists · 2 of 7 · Powertrance" */
export const readingLine = (r: { index: number; total: number; folder: string }) =>
  `${READING} · ${r.index} of ${r.total} · ${r.folder}`;

export type RunState = {
  job_id: number | null; job_kind: string | null;
  /** the job's own track (use_candidate / use_link have no ActionStarted); null for a sync */
  job_track_id: string | null;
  phase: 'idle' | 'preparing' | 'running' | 'stopping' | 'finished' | 'failed';
  total: number | null; index: number;           // 1-based index of the current action
  planned: PlannedAction[];                      // RunStarted.actions: every action in run order ("Up next")
  current: Action | null; step: Step | null;
  progress: (EventOf<'Progress'> & { at: number; rate: number | null }) | null; // rate: units/s, smoothed
  waiting: (EventOf<'Waiting'> & { at: number }) | null;   // cleared by the next non-Waiting event of the action
  source: EventOf<'SourceChosen'> | null;   // for the current track only
  checked: EventOf<'Checked'> | null;       // for the current track only
  qobuz: { used: number; allowance: number } | null;
  usage: Record<string, { used: number; allowance: number }>;  // per service (AccountUsage)
  results: EventOf<'ActionFinished'>[];     // in order
  last_started_at: number | null;   // ActionStarted: a message before it is stale
  last_finished_at: number | null;
  run_finished: EventOf<'RunFinished'> | null;
  job_finished: EventOf<'JobFinished'> | null;
  messages: { level: 'info' | 'warning'; text: string; at: number }[];  // last 20, debug dropped
  started_at: number | null;
};

export const EMPTY_RUN: RunState = Object.freeze({
  job_id: null, job_kind: null, job_track_id: null, phase: 'idle', total: null, index: 0, planned: [],
  current: null, step: null, progress: null, waiting: null, source: null, checked: null, qobuz: null, usage: {}, results: [],
  last_started_at: null, last_finished_at: null, run_finished: null, job_finished: null, messages: [], started_at: null,
}) as RunState;

const ACTIVE = new Set<RunState['phase']>(['preparing', 'running', 'stopping']);
const currentTrack = (s: RunState) => s.current?.track_id ?? s.job_track_id;

export function reduceRun(s: RunState, e: HubEvent, now: number): RunState {
  switch (e.type) {
    case 'JobStarted':
      if (!DOWNLOAD_KINDS.includes(e.kind)) return s;
      return { ...EMPTY_RUN, job_id: e.job_id, job_kind: e.kind, job_track_id: e.track_id, phase: 'preparing',
        started_at: now };
    case 'JobFinished':
      if (e.job_id !== s.job_id) return s;
      return { ...s, phase: e.ok ? 'finished' : 'failed', job_finished: e, waiting: null };
    default:
      break;
  }
  if (!ACTIVE.has(s.phase)) return s;   // engine events belong to the running download job only
  const mine = (track_id: string) => track_id === currentTrack(s);
  switch (e.type) {
    case 'RunStarted':
      return { ...s, phase: s.phase === 'stopping' ? 'stopping' : 'running', total: e.total, planned: e.actions ?? [] };
    case 'ActionStarted':
      return { ...s, phase: s.phase === 'stopping' ? 'stopping' : 'running', index: e.index, total: e.total,
        current: e.action, step: null, progress: null, waiting: null, source: null, checked: null,
        last_started_at: now };
    case 'StepChanged':
      if (!mine(e.track_id)) return s;
      return { ...s, step: e.step, waiting: null,
        progress: s.progress && s.progress.step === e.step ? s.progress : null };
    case 'Progress': {
      if (!mine(e.track_id)) return s;
      const prev = s.progress;
      let rate: number | null = null;
      if (prev && prev.step === e.step && prev.track_id === e.track_id && e.done >= prev.done) {
        const dt = (now - prev.at) / 1000;
        if (dt > 0) {
          const inst = (e.done - prev.done) / dt;
          rate = prev.rate === null ? inst : SMOOTH * inst + (1 - SMOOTH) * prev.rate;
        } else rate = prev.rate;
      }
      return { ...s, step: e.step, progress: { ...e, at: now, rate }, waiting: null };
    }
    case 'Waiting':
      return { ...s, waiting: { ...e, at: now } };
    case 'SourceChosen':
      return mine(e.track_id) ? { ...s, source: e, waiting: null } : s;
    case 'Checked':
      return mine(e.track_id) ? { ...s, checked: e, waiting: null } : s;
    case 'AccountUsage': {
      const u = { used: e.used, allowance: e.allowance };
      return { ...s, usage: { ...s.usage, [e.service]: u }, qobuz: e.service === 'qobuz' ? u : s.qobuz };
    }
    case 'ActionFinished':
      return { ...s, results: [...s.results, e], last_finished_at: now, waiting: null };
    case 'RunFinished':
      return { ...s, run_finished: e, waiting: null };
    case 'Message':
      if (e.level === 'debug') return s;
      return { ...s, messages: [...s.messages, { level: e.level, text: e.text, at: now }].slice(-MAX_MESSAGES) };
    case 'ReadingPlaylist': {
      // "Reading your Spotify playlists · 2 of 7 · Powertrance" replaces the plain reading line (and the last count)
      const text = readingLine(e);
      const keep = s.messages.at(-1)?.text.startsWith(READING) ? s.messages.slice(0, -1) : s.messages;
      return { ...s, messages: [...keep, { level: 'info' as const, text, at: now }].slice(-MAX_MESSAGES) };
    }
    default:
      return s;
  }
}

/**
 * The same state after a reload, from job_status().job. `last` holds the newest event of each type without their
 * order, so: track events count only for the current action's track; a Waiting only while it still counts down;
 * Progress only for the current step.
 */
export function runFromSnapshot(job: JobSnap, now: number): RunState {
  let s = reduceRun(EMPTY_RUN, { type: 'JobStarted', job_id: job.id, kind: job.kind, track_id: job.track_id }, now);
  if (s.phase === 'idle') return s;
  const started = Date.parse(job.started);
  s = { ...s, started_at: Number.isNaN(started) ? now : started };
  const last = job.last ?? {};
  const apply = (e: HubEvent | undefined) => { if (e) s = reduceRun(s, e, now); };
  apply(last.RunStarted);
  for (const r of job.results ?? []) apply(r);
  const started_action = last.ActionStarted as EventOf<'ActionStarted'> | undefined;
  if (started_action && started_action.index > (job.results?.length ?? 0)) {
    const results = s.results;
    apply(started_action);
    s = { ...s, results };
    apply(last.StepChanged);
    apply(last.SourceChosen);
    apply(last.Checked);
    const p = last.Progress as EventOf<'Progress'> | undefined;
    if (p && p.step === s.step) apply(p);
    const w = last.Waiting as EventOf<'Waiting'> | undefined;
    if (w && w.remaining > 0) apply(w);
  } else if (started_action) {
    s = { ...s, index: started_action.index, total: started_action.total, current: started_action.action };
  }
  // the newest AccountUsage of every service; an older bridge only has the newest one overall in `last`
  if (job.usage?.length) for (const u of job.usage) apply(u);
  else apply(last.AccountUsage);
  apply(last.RunFinished);
  if (job.stopping && ACTIVE.has(s.phase)) s = { ...s, phase: 'stopping' };
  if (job.finished) apply(job.finished);
  return s;
}

const store = writable<RunState>(EMPTY_RUN);
onEvent((e) => store.update((s) => reduceRun(s, e, Date.now())));

export const run: Readable<RunState> = { subscribe: store.subscribe };
/** Seeds the store after a reload (main.ts). */
export function seedRun(job: JobSnap): void {
  store.set(runFromSnapshot(job, Date.now()));
}
/** Called by the Stop safely button after api.stop() returned stopped:true. */
export function markStopping(): void {
  store.update((s) => (ACTIVE.has(s.phase) ? { ...s, phase: 'stopping' } : s));
}
