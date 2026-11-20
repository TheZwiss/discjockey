// Following a job another process runs (issue 39 E4): the engine's `job_events` read serves the job's events.jsonl
// (+ its rolling tail), the same lines `job follow --jsonl` prints, and this store turns them into the `RunState` the
// Sync page's live view shows for the window's own sync (`reduceRun`). The window works out nothing of its own: what
// is on screen is what the events say, plus `status: stopping` and the end the window's watch reports.
import { writable, type Readable } from 'svelte/store';
import { api } from '../bridge/client';
import { onEvent, type EventOf, type HubEvent } from '../bridge/events';
import { hub } from './hub';
import { ACTIVE_PHASES, EMPTY_RUN, reduceRun, type RunState } from './run';

/** How often a followed job is asked for its new events */
export const POLL_MS = 1000;
/** The most lines one `job_events` answer carries (HubApi: JOB_EVENTS_PAGE): a full answer means more are waiting */
export const PAGE = 500;

const followed = new Map<string, Readable<RunState>>();

/**
 * The live state of the job `jobId`, one store per job id: it polls `job_events` once a second while anyone is
 * subscribed (and at once again while an answer was full), and stops after the job's last events. A job joined late
 * (or a reload) is caught up without publishing the hundreds of past states: the view gets the first state after the
 * answers stop coming back full.
 */
export function followRun(jobId: string): Readable<RunState> {
  let store = followed.get(jobId);
  if (!store) followed.set(jobId, store = makeFollow(jobId));
  return store;
}

function makeFollow(jobId: string): Readable<RunState> {
  let after = 0;                       // the position of the next line to ask for (the answer's `next`)
  let reduced: RunState = EMPTY_RUN;
  let held: EventOf<'JobFinished'> | null = null;     // a `console` JobFinished line: a retry's, not the end
  let ended: EventOf<'JobFinished'> | null = null;    // the window's own JobFinished for this job, waiting for the file's last lines
  let active = false, asking = false, again = false;
  let over = false;                    // nothing more to read: the job's last events were delivered, or the id is unknown
  let timer: ReturnType<typeof setTimeout> | null = null;
  let changed = false;                 // `reduced` moved since it was published
  const store = writable<RunState>(EMPTY_RUN, () => {
    active = true;
    const off = onEvent(onHubEvent);
    schedule(0);
    return () => { active = false; off(); if (timer) clearTimeout(timer); timer = null; };
  });

  const reduce = (e: HubEvent) => { reduced = reduceRun(reduced, e, Date.now()); changed = true; };
  const publish = () => { if (changed) { changed = false; store.set(reduced); } };
  const stopping = () => {
    if (ACTIVE_PHASES.includes(reduced.phase) && reduced.phase !== 'stopping') { reduced = { ...reduced, phase: 'stopping' }; changed = true; }
  };
  const schedule = (ms: number) => {
    if (!active || over) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(poll, ms);
  };

  /** The end the watch reports (it rebuilds the JobFinished from the job's result.json, written after its last events):
   *  applied once the file's last lines are in, so no event after the end is lost. */
  function onHubEvent(e: HubEvent): void {
    if (e.type !== 'JobFinished' || e.job_id !== jobId) return;
    if (over) { reduce(e); publish(); return; }
    ended = e;
    if (asking) again = true; else schedule(0);
  }

  async function poll(): Promise<void> {
    timer = null;
    if (!active || asking || over) return;
    asking = true;
    const from = after;
    let answer: Awaited<ReturnType<typeof api.job_events>> | null = null;
    try { answer = await api.job_events(jobId, from); } catch { answer = null; } finally { asking = false; }
    if (!active) return;                                    // unsubscribed meanwhile: ask again from `from` when someone is back
    let full = false;
    if (answer?.ok) {
      for (const e of answer.events as HubEvent[]) {
        held = null;                                         // a later line: that JobFinished was a retry's
        if (e.type === 'JobFinished' && e.problem === 'console') held = e; else reduce(e);
      }
      after = answer.next;
      full = answer.next - from >= PAGE;
      if (answer.status === 'stopping') stopping();
      if (answer.done) {
        if (held) { reduce(held); held = null; }            // it was the last line: the job ended busy
        over = true;
      }
      if (!full && ended) { reduce(ended); ended = null; }
      if (!full) publish();                                 // while full: still catching up, nothing shown yet
    } else if (answer && (answer as { reason?: string }).reason === 'unknown_id') {
      over = true;
    }                                                        // any other failure keeps the state; the next poll tries again
    const more = again; again = false;
    schedule(full || more ? 0 : POLL_MS);
  }

  return { subscribe: store.subscribe };
}

/** The Terminal's sync the window shows (E4b routes the Sync page by it): `running` while `$hub.console` is a sync, kept
 *  with `running: false` once the console clears (the watch sends the JobFinished, then ConsoleBusy(false), in one look,
 *  so the end screen still has its job), replaced by the next console sync, null once a job of another kind holds the library. */
export type TerminalSync = { job: string; running: boolean };
export const terminalSync: Readable<TerminalSync | null> = (() => {
  const store = writable<TerminalSync | null>(null);
  let current: TerminalSync | null = null;
  hub.subscribe((h) => {
    const c = h.console;
    let next: TerminalSync | null;
    if (!c) next = current && { job: current.job, running: false };
    else if (c.kind === 'sync' && c.job) next = { job: c.job, running: true };
    else next = null;
    if (next?.job === current?.job && next?.running === current?.running) return;
    current = next;
    store.set(next);
  });
  return { subscribe: store.subscribe };
})();
