// The Terminal's sync, as a job the window can follow in the fake backend: the recorded sync, line by line, as the
// engine's `job_events` serves a job's events.jsonl (the fake Terminal job is `JOB` in every scenario; the console
// scenarios hold the library with it). It runs on the fake's clock like its own replay (`Replay`: a line every 150 ms,
// a Progress or Waiting a second, divided by the fake's speed) and ends as the Terminal's job does: its last events are
// in the file, then the window's watch sends the `JobFinished` and `ConsoleBusy(false)`. Scenarios (`console:sync-*`):
//   live      from its start to its end
//   reading   frozen before RunStarted
//   running   frozen mid-download (a first open of a job half done)
//   ended     the whole file at once; the end is sent once the window has read it
// Its run is filed like the window's own (`onEnded`, the bridge's afterSync) the moment its last line is in the file, as
// the Terminal's sync writes its report before it ends, so its end screen loads that run.
import type { FakeState } from './data';
import type { HubEvent } from '../events';
import type { JobEvents } from '../types';
import { consoleEvent, JOB, setConsole, type TerminalMode } from './console';
import { Replay, STREAMS, SYNC_LINES, SYNC_START_LINE, lineOf, rewrite } from './replay';

/** The most lines one `job_events` answer carries (HubApi: JOB_EVENTS_PAGE) */
export const PAGE = 500;
/** The 1-based line of the recorded sync's RunStarted: "reading" is frozen right before it */
const RUN_STARTED_LINE = lineOf(STREAMS.sync, (e) => e.type === 'RunStarted');

export type TerminalOpts = { s: FakeState; speed: number; emit: (e: HubEvent) => void; reportPath: string; mode: TerminalMode;
  /** the job's whole file, once its last line is in: the fake files its run */
  onEnded?: (lines: readonly HubEvent[]) => void };

export class TerminalJob {
  /** the job's events.jsonl so far, one event a line */
  private lines: HubEvent[] = [];
  private replay: Replay | null = null;
  private reported = false;
  status: 'running' | 'stopping' | 'done' = 'running';

  constructor(private o: TerminalOpts) {
    const sync = STREAMS.sync;
    const upTo = { live: SYNC_START_LINE, reading: RUN_STARTED_LINE - 1, running: SYNC_LINES.downloading, ended: sync.length }[o.mode];
    if (o.s.console_running) o.s.console_line = '';   // it has not said how far it is yet
    for (let i = SYNC_START_LINE - 1; i < upTo; i++) this.push(rewrite(sync[i], JOB, o.reportPath), false);
    if (o.mode === 'ended') { this.status = 'done'; o.onEnded?.(this.lines); return; }
    this.replay = new Replay({ events: sync, from: upTo + 1, jobId: JOB, speed: o.speed,
      freeze: o.mode === 'live' ? null : upTo, reportPath: o.reportPath, emit: (e) => this.push(e, true),
      onDone: () => { this.status = 'done'; o.onEnded?.(this.lines); this.report(); } });
    this.replay.start();
  }

  /** The line `ConsoleBusy` carries follows the stream: "<index> of <total>" at each ActionStarted */
  private push(e: HubEvent, live = false): void {
    this.lines.push(e);
    const { s } = this.o;
    if (e.type !== 'ActionStarted' || !s.console_running) return;
    s.console_line = `${e.index} of ${e.total}`;
    if (live) this.o.emit(consoleEvent(s));
  }

  /** The end the window's watch sends: the job's JobFinished, then ConsoleBusy(false) */
  private report(): void {
    if (this.reported) return;
    this.reported = true;
    const finished = [...this.lines].reverse().find((e) => e.type === 'JobFinished');
    if (finished) this.o.emit(finished);
    setConsole(this.o.s, false);
    this.o.emit(consoleEvent(this.o.s));
  }

  /** `job_events`: the lines from `after` on, at most `PAGE`, the status read before them */
  read(after: number): JobEvents {
    const status = this.status;
    const events = this.lines.slice(after, after + PAGE);
    if (this.status === 'done' && !this.reported) setTimeout(() => this.report(), 0);   // "ended": the window has loaded it
    return { events, next: after + events.length, status, done: status === 'done' && events.length < PAGE };
  }

  /** Stop safely, as `stop(job_id)` writes the stop file: false for a job that has ended */
  stop(): boolean {
    if (this.status === 'done') return false;
    this.status = 'stopping';
    this.replay?.stop();
    return true;
  }
}
