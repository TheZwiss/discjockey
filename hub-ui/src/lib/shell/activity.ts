// The activity bar's words, from the run state (also used by the Sync screen's header if it wants).
import type { RunState } from '../stores/run';
import { STEP_LABEL } from '../copy';
import { artistTitle, duration } from '../format';

export type ActivityText = { lead: string; track: string | null; tail: string | null; pause: string | null;
  qobuz: string | null };

export function pauseLeft(s: RunState, now: number): number | null {
  if (!s.waiting) return null;
  return Math.max(0, s.waiting.remaining - (now - s.waiting.at) / 1000);
}

export function activityText(s: RunState, now: number): ActivityText {
  const qobuz = s.qobuz ? `Qobuz ${s.qobuz.used} of ${s.qobuz.allowance} today` : null;
  if (s.phase === 'stopping') return { lead: 'Stopping…', track: null, tail: null, pause: null, qobuz };
  if (s.phase === 'preparing' || !s.total) return { lead: 'Reading Spotify…', track: null, tail: null, pause: null, qobuz };
  const head = `Sync running · ${s.index} of ${s.total} · `;
  const t = s.current?.track;
  const name = t ? artistTitle(t.artists[0] ?? '', t.title) : null;
  const left = pauseLeft(s, now);
  if (s.waiting && (s.waiting.kind === 'between' || s.waiting.kind === 'break')) {
    return { lead: `${head}Protection pause ${duration(Math.ceil(left ?? 0))} · next `, track: name, tail: null, pause: null, qobuz };
  }
  const verb = s.current?.kind === 'move' ? 'Moving' : s.step ? STEP_LABEL[s.step] : 'Searching';
  return { lead: `${head}${verb} `, track: name, tail: null, pause: null, qobuz };
}

/** (index − 1 + step fraction) / total */
export function activityProgress(s: RunState): number {
  if (!s.total) return 0;
  const p = s.progress;
  const frac = p && p.total ? Math.min(1, p.done / p.total) * (p.step === 'download' ? 0.8 : 1) : 0;
  return Math.max(0, Math.min(1, (Math.max(0, s.index - 1) + frac) / s.total));
}
