// The sync's words in the frame's foot, from the run state: the long form when the foot shows only the sync, the
// short one at the right end of the player bar (plan now-playing).
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
  if (s.phase === 'preparing' || !s.total) return { lead: 'Reading playlists…', track: null, tail: null, pause: null, qobuz };
  const head = `Sync running · ${s.index} of ${s.total} · `;
  const t = s.current?.track;
  const name = t ? artistTitle(t.artists[0] ?? '', t.title) : null;
  const left = pauseLeft(s, now);
  if (s.waiting && (s.waiting.kind === 'between' || s.waiting.kind === 'break')) {
    return { lead: `${head}Protection pause ${duration(Math.ceil(left ?? 0))} · next `, track: name, tail: null, pause: null, qobuz };
  }
  const verb = s.step ? STEP_LABEL[s.step] : 'Searching';
  return { lead: `${head}${verb} `, track: name, tail: null, pause: null, qobuz };
}

/** The short form for the player bar's right end: "Sync 4 of 6"; the long form goes into its tooltip. */
export function activityShort(s: RunState): string {
  if (s.phase === 'stopping') return 'Stopping…';
  if (s.phase === 'preparing' || !s.total) return 'Reading playlists…';
  return `Sync ${s.index} of ${s.total}`;
}

/** The long form as one line (the short form's tooltip and the sync part's label). */
export function activityLine(a: ActivityText): string {
  return [[a.lead, a.track, a.tail].filter(Boolean).join('').trim(), a.pause, a.qobuz].filter(Boolean).join(' · ');
}

/** (index − 1 + step fraction) / total */
export function activityProgress(s: RunState): number {
  if (!s.total) return 0;
  const p = s.progress;
  const frac = p && p.total ? Math.min(1, p.done / p.total) * (p.step === 'download' ? 0.8 : 1) : 0;
  return Math.max(0, Math.min(1, (Math.max(0, s.index - 1) + frac) / s.total));
}
