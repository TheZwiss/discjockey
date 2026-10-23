// Keeps the last 50 JobFinished events by job id. JobFinished can arrive before the bridge call that started the
// job returns (two different paths from Python), so runJob checks this cache first.
import { onEvent, type EventOf } from '../bridge/events';

export type JobFinished = EventOf<'JobFinished'>;
export const KEEP_FINISHED = 50;

const finished = new Map<number, JobFinished>();
const waiters = new Map<number, ((e: JobFinished) => void)[]>();

onEvent((e) => {
  if (e.type !== 'JobFinished') return;
  finished.set(e.job_id, e);
  while (finished.size > KEEP_FINISHED) finished.delete(finished.keys().next().value as number);
  const ws = waiters.get(e.job_id);
  waiters.delete(e.job_id);
  for (const w of ws ?? []) w(e);
});

export function finishedJob(job_id: number): JobFinished | undefined {
  return finished.get(job_id);
}

/** Resolves with the JobFinished of this job, at once when it already arrived. */
export function waitForJob(job_id: number): Promise<JobFinished> {
  const done = finished.get(job_id);
  if (done) return Promise.resolve(done);
  return new Promise((resolve) => {
    waiters.set(job_id, [...(waiters.get(job_id) ?? []), resolve]);
  });
}

/** Tests only. */
export function _resetJobs(): void {
  finished.clear();
  waiters.clear();
}
