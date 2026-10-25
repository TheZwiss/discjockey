// Fake mode only: replays the recorded engine streams (tests/fixtures/*.jsonl) as if a real run was going on.
import syncRaw from '$fixtures/hub_events_sync.jsonl?raw';
import stoppedRaw from '$fixtures/hub_events_stopped.jsonl?raw';
import type { HubEvent } from '../events';
import type { JobSnap } from '../types';

/** Fixture Spotify ids → the fake library's ids (same tracks, see data.ts). */
export const ID_MAP: Record<string, string> = {
  '4uLU6hMCjMI75M1A2tKUQC': 't1', '1301WleyT98MSxVHPZCA6M': 't3',
  '3n3Ppam7vgaVa1iaRUc9Lp': 't5', '2takcwOaAZWiXQijPHIx7B': 't4', '7ouMYWpwJ422jRcDASZB7P': 't2',
};
function mapIds(raw: string): string {
  let out = raw;
  for (const [a, b] of Object.entries(ID_MAP)) out = out.split(a).join(b);
  return out;
}
const parse = (raw: string): HubEvent[] => mapIds(raw).split('\n').filter((l) => l.trim()).map((l) => JSON.parse(l));
export const STREAMS = { sync: parse(syncRaw), stopped: parse(stoppedRaw) };

/** The 1-based line of the `nth` (0-based) event that `pred` matches. Finds moments by what happens, not by a fixed
 *  line number, so a re-recorded fixture keeps the moments; throws when there is no such event. */
export function lineOf(evs: HubEvent[], pred: (e: HubEvent) => boolean, nth = 0): number {
  let seen = 0;
  for (let i = 0; i < evs.length; i++) if (pred(evs[i]) && seen++ === nth) return i + 1;
  throw new Error(`no event #${nth} matches in the recorded stream`);
}
const sync = STREAMS.sync;
/** 1-based fixture line of the sync job's JobStarted (the refresh job comes first). */
export const SYNC_START_LINE = lineOf(sync, (e) => e.type === 'JobStarted' && e.kind === 'sync');
/** Moments of the recorded sync the fake scenarios start or stop at (1-based lines). */
export const SYNC_LINES = {
  /** mid-download of "non stop" (t5): its second download Progress */
  downloading: lineOf(sync, (e) => e.type === 'Progress' && e.track_id === 't5' && e.step === 'download', 1),
  /** "non stop" (t5) is in its conversion: the sync:converting scenario freezes here */
  converting: lineOf(sync, (e) => e.type === 'StepChanged' && e.track_id === 't5' && e.step === 'convert'),
  /** Get Naughty's source is chosen, the protection pause comes next */
  sourceBeforePause: lineOf(sync, (e) => e.type === 'SourceChosen' && e.track_id === 't2'),
  /** well into the protection pause before Get Naughty (about 34 s left) */
  inPause: lineOf(sync, (e) => e.type === 'Waiting' && e.kind === 'between' && e.remaining < 35),
  /** Gone Track's (t3) fallback search started: the errors scenario crashes after it */
  crash: lineOf(sync, (e) => e.type === 'StepChanged' && e.track_id === 't3' && e.step === 'search', 1),
};

/** What Python's job_status() keeps per job (jobs.py JobRecord). */
export class JobRecord {
  last: Record<string, any> = {};
  usage: Record<string, any> = {};
  results: any[] = [];
  finished: any | null = null;
  running = true;
  stopping = false;
  constructor(public id: number, public kind: string, public track_id: string | null, public started: string) {}
  record(e: HubEvent): void {
    this.last[e.type] = e;
    if (e.type === 'AccountUsage') this.usage[e.service] = e;
    if (e.type === 'ActionFinished') this.results.push(e);
    if (e.type === 'JobFinished') { this.finished = e; this.running = false; this.stopping = false; }
  }
  snapshot(): JobSnap {
    return { id: this.id, kind: this.kind, track_id: this.track_id, started: this.started, running: this.running,
      stopping: this.stopping, last: { ...this.last }, usage: Object.values(this.usage), results: [...this.results], finished: this.finished,
      actions: [...(this.last.RunStarted?.actions ?? [])] };
  }
}

export function delayOf(e: HubEvent, speed: number): number {
  return ((e.type === 'Waiting' || e.type === 'Progress') ? 1000 : 150) / Math.max(0.01, speed);
}

export type ReplayOpts = {
  events: HubEvent[];          // the whole stream
  from: number;                // 1-based line to start with
  jobId: number;
  speed: number;
  freeze?: number | null;      // stop after this 1-based line and wait (screenshots)
  reportPath: string;
  emit: (e: HubEvent) => void;
  onDone?: () => void;
  /** turns the last part into a crash: stop after this line, then the run filed with its crash note (RunFinished
   *  exit 1) and JobFinished crashed carrying that report, as jobs.sync_work does */
  crashAfter?: number | null;
};

/** Rewrites a fixture event for this replay: the job id, the report path. */
export function rewrite(e: HubEvent, jobId: number, reportPath: string): HubEvent {
  if (e.type === 'JobFinished' && e.result?.report) {
    return { ...e, job_id: jobId, result: { ...e.result, report: reportPath } };
  }
  if (e.type === 'JobStarted' || e.type === 'JobFinished') return { ...e, job_id: jobId } as HubEvent;
  if (e.type === 'RunFinished') return { ...e, report_path: reportPath };
  return e;
}

export class Replay {
  private i: number;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private stopping = false;
  private inDownload = false;
  done = false;
  constructor(private o: ReplayOpts) { this.i = o.from - 1; }

  start(): void { this.schedule(); }
  cancel(): void { if (this.timer) clearTimeout(this.timer); this.timer = null; this.done = true; }

  /** Stop safely: ends after the current action (at once when it hasn't started downloading yet). */
  stop(): void {
    this.stopping = true;
    if (!this.inDownload && this.timer) { clearTimeout(this.timer); this.timer = null; this.endStopped(); }
  }

  private schedule(): void {
    if (this.done) return;
    const e = this.o.events[this.i];
    if (!e) return this.finish();
    if (this.o.freeze && this.i + 1 > this.o.freeze) return;      // frozen: wait forever
    this.timer = setTimeout(() => this.step(), delayOf(e, this.o.speed));
  }

  private step(): void {
    this.timer = null;
    const e = rewrite(this.o.events[this.i], this.o.jobId, this.o.reportPath);
    if (this.stopping && e.type === 'ActionStarted') return this.endStopped();
    if (e.type === 'StepChanged') this.inDownload = e.step !== 'search';
    if (e.type === 'ActionStarted' || e.type === 'ActionFinished') this.inDownload = false;
    if (this.stopping && e.type === 'Waiting') { this.i++; return this.schedule(); }  // stop ends pauses at once
    this.o.emit(e);
    this.i++;
    if (this.o.crashAfter && this.i >= this.o.crashAfter) return this.crash();
    if (e.type === 'JobFinished') return this.finish();
    if (this.stopping && e.type === 'ActionFinished') return this.endStopped();
    this.schedule();
  }

  private endStopped(): void {
    if (this.done) return;
    const tail = STREAMS.stopped.slice(-2).map((e) => rewrite(e, this.o.jobId, this.o.reportPath));
    this.o.emit(tail[0]);
    this.o.emit(tail[1]);
    this.finish();
  }

  private crash(): void {
    const report = this.o.reportPath;
    this.o.emit({ type: 'RunFinished', exit_code: 1, report_path: report });
    this.o.emit({ type: 'JobFinished', job_id: this.o.jobId, kind: 'sync', ok: false, problem: 'crashed',
      message: "The sync stopped unexpectedly. Everything done up to then is saved, and the next sync carries on from there.",
      result: { exit_code: 1, report, actions: this.actions(), new_since_preview: 0 }, service: null });
    this.finish();
  }

  /** How many actions the replayed run planned (its RunStarted), for the crashed sync's result. */
  private actions(): number {
    const started = this.o.events.find((e) => e.type === 'RunStarted');
    return started && started.type === 'RunStarted' ? started.total : 0;
  }

  private finish(): void {
    if (this.done) return;
    this.done = true;
    this.o.onDone?.();
  }
}
