// The live sync card as a pure function of the run state and the clock (plan Task 65, "The card state machine").
import type { Action, Step } from '$lib/bridge/events';
import type { Dashboard, ProblemKind, Quality, Result } from '$lib/bridge/types';
import type { RunState } from '$lib/stores/run';
import { STEP_LABEL } from '$lib/copy';
import { duration, khz, megabytes } from '$lib/format';

export const ANALYSED_MS = 4000;
/** Steps that end the analysed card early: the next track's real work has begun. */
const WORK_STEPS = new Set<Step>(['download', 'convert', 'check', 'analyse', 'compare']);
const BASE_STEPS: Step[] = ['search', 'download', 'check', 'convert', 'analyse'];
const NO_STEPS = new Set(['move', 'adopt', 'adopt_bought']);

export const SOURCE_NAME: Record<string, string> = {
  qobuz: 'Qobuz', youtube_music: 'YT Music', soundcloud: 'SoundCloud', youtube: 'YouTube', manual: 'bought',
};
export const sourceName = (s: string | null | undefined) => (s ? SOURCE_NAME[s] ?? s : null);

export type Card =
  | { kind: 'preparing'; text: string }
  | { kind: 'working'; action: Action; step: Step | null; steps: Step[]; detail: string; source: string | null }
  | { kind: 'downloading'; action: Action; steps: Step[]; source: string | null; doneMB: string; totalMB: string | null;
      percent: number | null; secondsLeft: number | null }
  | { kind: 'converting'; action: Action; steps: Step[]; source: string | null; lengthLine: string | null;
      lengthOk: boolean | null; done_s: number; total_s: number | null }
  | { kind: 'analysed'; result: Result; action: Action }
  | { kind: 'pause'; waiting: 'between' | 'break'; remaining_s: number; total_s: number; label: string;
      nextUp: Action; afterThat: number; source: string | null }
  | { kind: 'stopping' }
  | { kind: 'finished'; exit_code: number }
  | { kind: 'failed'; problem: ProblemKind; message: string };

export function stepsFor(action: Action): Step[] {
  if (NO_STEPS.has(action.kind)) return [];
  return action.kind === 'upgrade' ? [...BASE_STEPS, 'compare'] : BASE_STEPS;
}

export function lengthLine(c: { file_duration_s: number; spotify_duration_s: number; ok: boolean } | null):
  string | null {
  if (!c) return null;
  const f = duration(c.file_duration_s), sp = duration(c.spotify_duration_s);
  return c.ok ? `Length matches (${f} = Spotify ${sp})` : `Length differs (${f}, Spotify ${sp})`;
}

function noStepDetail(a: Action): string {
  if (a.kind === 'move') return `Moving to ${a.folder}…`;
  if (a.kind === 'adopt_bought') return 'Adding the bought file…';
  return `Picking up the file in ${a.folder}…`;
}

const SERVICE_NAMES: Record<string, string> = { qobuz: 'Qobuz', youtube: 'YouTube Premium', soundcloud: 'SoundCloud Go+' };

type Count = { used: number; allowance: number };
/** The dashboard's Qobuz count until the run's first AccountUsage, only when Qobuz is set up (not "I don't have
 * Qobuz", not free sources only): then it is the first service with a daily limit. */
export function qobuzFallback(tiles: Pick<Dashboard['tiles'], 'qobuz_today' | 'account_today'>): Count | null {
  return tiles.account_today?.service === 'qobuz'
    ? { used: tiles.qobuz_today.used, allowance: tiles.qobuz_today.allowance } : null;
}
/** "Qobuz 12 of 60 today · YouTube Premium 3 of 30 today" for the live header: Qobuz first, then the accounts. */
export function liveUsage(qobuzToday: Count | null, usage: Record<string, Count>): string[] {
  const counted = { ...(qobuzToday ? { qobuz: qobuzToday } : {}), ...usage };
  return Object.entries(counted)
    .map(([service, u]) => `${SERVICE_NAMES[service] ?? service} ${u.used} of ${u.allowance} today`);
}

export function cardState(r: RunState, now: number,
  qobuzToday: { used: number; allowance: number } | null = null): Card {
  if (r.phase === 'stopping') return { kind: 'stopping' };
  if (r.phase === 'failed') {
    return { kind: 'failed', problem: (r.job_finished?.problem ?? 'crashed') as ProblemKind,
      message: r.job_finished?.message ?? '' };
  }
  if (r.phase === 'finished') {
    const res = r.job_finished?.result as { exit_code?: number } | null | undefined;
    return { kind: 'finished', exit_code: r.run_finished?.exit_code ?? res?.exit_code ?? 0 };
  }
  const a = r.current;
  if (!a) {
    const info = [...r.messages].reverse().find((m) => m.level === 'info');
    return { kind: 'preparing', text: info?.text ?? 'Getting ready…' };
  }
  const steps = stepsFor(a);
  const source = r.source?.source ?? null;
  const w = r.waiting;
  if (w && (w.kind === 'between' || w.kind === 'break') && w.remaining > 0) {
    return { kind: 'pause', waiting: w.kind, remaining_s: Math.max(0, w.remaining - (now - w.at) / 1000),
      total_s: w.total, label: w.label, nextUp: a, afterThat: Math.max(0, (r.total ?? r.index) - r.index), source };
  }
  const last = r.results.at(-1);
  if (last && r.last_finished_at !== null) {
    const ownResult = last.action.track_id === a.track_id;   // no newer ActionStarted yet: keep the result up
    const fresh = now - r.last_finished_at < ANALYSED_MS && !(r.step && WORK_STEPS.has(r.step));
    if (ownResult || fresh) return { kind: 'analysed', result: last.result, action: last.action };
  }
  if (!steps.length) return { kind: 'working', action: a, step: null, steps, detail: noStepDetail(a), source };
  const p = r.progress;
  if (r.step === 'download' && p && p.step === 'download' && p.unit === 'bytes') {
    const pct = p.total ? Math.min(100, Math.round((p.done / p.total) * 100)) : null;
    const left = p.total && p.rate && p.rate > 0 ? Math.max(0, Math.ceil((p.total - p.done) / p.rate)) : null;
    return { kind: 'downloading', action: a, steps, source, doneMB: megabytes(p.done),
      totalMB: p.total ? megabytes(p.total) : null, percent: pct, secondsLeft: left };
  }
  if (r.step === 'convert') {
    const sec = p && p.step === 'convert' && p.unit === 'seconds' ? p : null;
    return { kind: 'converting', action: a, steps, source, lengthLine: lengthLine(r.checked),
      lengthOk: r.checked ? r.checked.ok : null, done_s: sec?.done ?? 0,
      total_s: sec?.total ?? r.checked?.file_duration_s ?? null };
  }
  const step = r.step ?? 'search';
  let detail = `${STEP_LABEL[step] ?? 'Working'}…`;
  if (w && (w.kind === 'search' || w.kind === 'fallback')) {
    const left = Math.ceil(Math.max(0, w.remaining - (now - w.at) / 1000));
    if (left > 0) detail = `${w.label} · ${left} s`;
  } else if (step === 'check' && r.checked) {
    detail = lengthLine(r.checked) ?? detail;
  }
  return { kind: 'working', action: a, step, steps, detail, source };
}

/** Index of the step shown as current (accent); every step before it is done. -1 = all done. */
export function stepIndex(card: Card): number {
  if (card.kind === 'downloading') return card.steps.indexOf('download');
  if (card.kind === 'converting') return card.steps.indexOf('convert');
  if (card.kind === 'working') return card.step ? card.steps.indexOf(card.step) : 0;
  return -1;
}

const FILE_SECTIONS = new Set(['new_lossless', 'new_not_lossless', 'fake', 'upgrade_ready', 'swapped', 'added_new',
  'bought', 'replaced', 'redownloaded', 'adopted', 'recovered']);
const PROBLEM_SECTIONS = new Set(['missing', 'errors', 'conflicts', 'ambiguous']);

export type Verdict = { tone: Quality | 'accent' | 'muted' | 'other'; quality: Quality | null; label: string;
  line: string; hasFile: boolean };

/** Is the file an upgrade check found lossless? found_status says; results from before it: Qobuz finds are lossless, any
 * other is taken as the lossy stream (the result's own status is the current file's). */
export const foundLossless = (res: Result): boolean =>
  res.found_status != null ? res.found_status === 'lossless' : res.source === 'qobuz';

/** Badge and short line for a finished track ("LOSSLESS · full spectrum up to 22 kHz", "16.0 kHz · audibly lossy"). */
export function verdict(res: Result): Verdict {
  const hasFile = FILE_SECTIONS.has(res.section) && !!res.track_id;
  if (res.section === 'moved') return { tone: 'other', quality: null, label: `MOVED → ${res.folder}`, line: '', hasFile };
  if (res.section === 'upgrade_ready') {
    // the result's status is the current file's; the found file's quality is foundLossless (a SoundCloud original can
    // be lossless)
    const q: Quality = foundLossless(res) ? 'lossless' : 'good_lossy';
    return { tone: q, quality: q, label: 'UPGRADE READY', line: 'a better version waits for you', hasFile };
  }
  if (PROBLEM_SECTIONS.has(res.section)) {
    if (res.section === 'missing') return { tone: 'missing', quality: 'missing', label: 'NOT FOUND', line: '', hasFile };
    if (res.error_kind === 'network') {
      return { tone: 'missing', quality: 'missing', label: 'NO INTERNET', line: 'tried again next run', hasFile };
    }
    if (res.error_kind === 'qobuz') return { tone: 'missing', quality: 'missing', label: 'QOBUZ PROBLEM', line: '', hasFile };
    return { tone: 'missing', quality: 'missing', label: 'PROBLEM', line: '', hasFile };
  }
  if (res.status === 'lossless') {
    return { tone: 'lossless', quality: 'lossless', label: 'LOSSLESS', line: 'full spectrum up to 22 kHz', hasFile };
  }
  if (res.status === 'fake_lossless') {
    return { tone: 'fake', quality: 'fake', label: `FAKE · ${khz(res.cutoff_hz)}`, line: 'not really lossless', hasFile };
  }
  if (res.status === 'not_lossless') {
    const weak = res.cutoff_hz !== null && res.cutoff_hz <= 17000;
    const label = res.cutoff_hz !== null ? khz(res.cutoff_hz) : 'LOSSY';
    return { tone: weak ? 'weak' : 'good_lossy', quality: weak ? 'weak' : 'good_lossy', label,
      line: weak ? 'audibly lossy' : 'lossy, hard to hear', hasFile };
  }
  return { tone: 'muted', quality: null, label: res.section.replace(/_/g, ' ').toUpperCase(), line: '', hasFile };
}
