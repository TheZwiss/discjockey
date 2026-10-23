// Wrong song? dialog logic (Task 67 part B, spec §6.6): length colour, which rows offer ▶ and Use this, copy.
import type { Candidate, TrackDetail } from '$lib/bridge/types';
import type { RunState } from '$lib/stores/run';
import { artistTitle, duration } from '$lib/format';

/** A length within this many seconds of Spotify's counts as the same length (green). */
export const LENGTH_OK_S = 3;
export const SEARCHING = 'Searching Qobuz, YouTube Music, SoundCloud and YouTube…';
export const SEARCH_BLOCKED = "Searching isn't possible while a sync runs.";
export const NOTHING_FOUND = 'Nothing found. Paste a link if you know one.';
export const QOBUZ_NO_PREVIEW = 'Qobuz versions have no preview.';
export const NONE_CONFIRM = {
  title: 'None of these?', confirmLabel: 'None of these', tone: 'danger' as const,
  body: 'The current file moves to Superseded, and the next sync searches again. Your playlists stay as they are.',
};

export type Tone = 'ok' | 'warn' | 'none';
type C = Pick<Candidate, 'source' | 'can_preview' | 'current' | 'rejected' | 'length_diff_s' | 'duration_s'
  | 'artist' | 'score'>;

export function lengthTone(c: Pick<Candidate, 'length_diff_s'>): Tone {
  if (c.length_diff_s === null || c.length_diff_s === undefined) return 'none';
  return Math.abs(c.length_diff_s) <= LENGTH_OK_S ? 'ok' : 'warn';
}
export function lengthText(c: Pick<Candidate, 'duration_s'>): string {
  return c.duration_s === null ? '–' : duration(c.duration_s);
}
export function matchText(c: Pick<Candidate, 'score'>): string { return c.score === null ? '–' : `${c.score} %`; }
export function matchTone(c: Pick<Candidate, 'score'>): Tone {
  return c.score === null ? 'none' : c.score >= 80 ? 'ok' : 'warn';
}

/** ▶ only when the backend can make a preview; Qobuz rows never (with the reason as tooltip). */
export function previewOffer(c: Pick<C, 'source' | 'can_preview'>): { show: boolean; title: string | null } {
  if (c.source === 'qobuz') return { show: false, title: QOBUZ_NO_PREVIEW };
  return { show: !!c.can_preview, title: null };
}
/** "Use this" is not offered on the current file or on a version rejected before. */
export function canUse(c: Pick<C, 'current' | 'rejected'>): boolean { return !c.current && !c.rejected; }

export function secondLine(c: Pick<C, 'current' | 'rejected' | 'artist'>): string {
  if (c.current) return 'current · you marked it as wrong';
  return c.rejected ? `${c.artist} · rejected before` : c.artist;
}
export function dialogTitle(t: Pick<TrackDetail, 'artist' | 'title'>): string {
  return `Pick another version: ${artistTitle(t.artist, t.title)}`;
}
export function subLine(spotify_s: number | null): string {
  return `Spotify: ${duration(spotify_s)} · sorted by how well they match · ▶ plays a 20-second preview`;
}

/** The line under the progress bar while a "Use this" / "Use link" download runs. */
export function progressText(r: Pick<RunState, 'step' | 'progress'>): string {
  const p = r.progress;
  switch (r.step) {
    case 'download':
      return p && p.unit === 'bytes' && p.total ? `Downloading… ${Math.round((p.done / p.total) * 100)} %` : 'Downloading…';
    case 'check': return 'Checking the length…';
    case 'convert': return 'Converting…';
    case 'analyse': case 'compare': return 'Checking the file…';
    case 'search': return 'Looking up this version…';
    default: return 'Starting…';
  }
}
export function progressValue(r: Pick<RunState, 'step' | 'progress'>): number | null {
  const p = r.progress;
  if (!p || !p.total || p.step !== r.step) return null;
  return p.done / p.total;
}
