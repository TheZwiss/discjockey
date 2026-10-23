// The frame's foot (plan now-playing, Task 2): what the player part shows, read from the player's state, and which
// keys reach the player. Pure: Foot.svelte, NowPlayingRow.svelte and App.svelte render and wire it.
import type { PlayerState } from '../stores/player';
import { current, nextIndex, single } from '../stores/queueModel';
import { artistTitle, duration } from '../format';

export type PlayState = 'playing' | 'paused' | 'loading' | 'error';
export type FootPlayer = {
  track_id: string; title: string; cover_url: string | null;
  /** the second line: "Artist · <list>", "Can't play this file." (`error`) or "End of <list>" (`end`) */
  sub: { kind: 'source' | 'error' | 'end'; text: string };
  /** the full names, for the tooltip of the cut title and line */
  tooltip: string;
  /** the list the queue plays from, with the track that plays now selected */
  href: string;
  play: PlayState;
  canPrev: boolean; canNext: boolean; canShuffle: boolean; shuffle: boolean;
  /** what part is played, 0..1; null while the track loads (no fill) */
  frac: number | null;
  pos: string; len: string; dur_s: number | null;
  /** seeking makes sense: the file is there and its length known */
  seekable: boolean;
};

/** The player part of the foot, or null without a queue (a single sound never shows in the frame). */
export function footPlayer(p: PlayerState): FootPlayer | null {
  const q = p.queue;
  if (!q) return null;
  const it = current(q);
  const one = single(q);
  const play: PlayState = p.error ? 'error' : p.loading && !p.ended ? 'loading' : p.playing ? 'playing' : 'paused';
  const dur = p.duration_s ?? it.duration_s;
  const list = q.source.label;
  const sub: FootPlayer['sub'] = p.error ? { kind: 'error', text: p.error }
    : p.ended ? { kind: 'end', text: `End of ${list}` }
    : { kind: 'source', text: `${it.artist} · ${list}` };
  const pos_s = p.ended && dur ? dur : play === 'loading' || play === 'error' ? 0 : p.position_s;
  return {
    track_id: it.track_id, title: it.title, cover_url: it.cover_url, sub,
    tooltip: `${artistTitle(it.artist, it.title)} · ${list}`,
    href: `${q.source.href}?track=${encodeURIComponent(it.track_id)}`,
    play,
    canPrev: !one, canNext: !one && !p.ended && nextIndex(q) !== null, canShuffle: !one, shuffle: q.shuffle,
    frac: play === 'loading' ? null : p.ended ? 1 : dur ? Math.min(1, Math.max(0, pos_s / dur)) : 0,
    pos: duration(pos_s), len: duration(dur), dur_s: dur ?? null,
    seekable: !!p.url && !p.error && !!dur,
  };
}

/** What the foot shows: the player part (with the sync's short form at its right end), the sync alone, or nothing. */
export type FootShape = { player: boolean; sync: boolean } | null;
export function footShape(p: PlayerState, syncShown: boolean): FootShape {
  const player = !!p.queue && !p.hidden;
  return player || syncShown ? { player, sync: syncShown } : null;
}

/** The hidden bar's row in the sidebar: only while hidden with a queue. */
export function rowShown(p: PlayerState): boolean {
  return !!p.queue && p.hidden;
}

export type KeyTarget = { tag: string; type: string | null; role: string | null; editable: boolean } | null;
export type PlayerKey = 'toggle' | 'next' | 'prev';
const FIELD = new Set(['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON']);
/** Roles whose own keys include Space or the arrows: the focused control keeps them. */
const OWN_KEYS = new Set(['button', 'slider', 'switch', 'checkbox', 'radio', 'menuitem', 'menuitemradio',
  'menuitemcheckbox', 'option', 'tab', 'combobox', 'textbox', 'searchbox', 'spinbutton', 'listbox']);

/** The element as playerKey reads it. */
export function keyTarget(el: Element | null): KeyTarget {
  if (!el || el === document.body || el === document.documentElement) return null;
  return { tag: el.tagName, type: el.getAttribute('type'), role: el.getAttribute('role'),
    editable: (el as HTMLElement).isContentEditable === true };
}

/**
 * Space plays/pauses, ⌘→ next, ⌘← previous (plan now-playing, Keys). None of them while focus is in a field, a
 * contenteditable, on a button or a slider (any control that uses Space or the arrows itself), or a dialog is open.
 * Other modifiers, and a held Space repeating, do nothing.
 */
export function playerKey(e: { key: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean;
  repeat: boolean }, t: KeyTarget, dialogOpen: boolean): PlayerKey | null {
  if (dialogOpen) return null;
  if (t && (FIELD.has(t.tag) || t.editable || (t.role !== null && OWN_KEYS.has(t.role)))) return null;
  if (e.ctrlKey || e.altKey || e.shiftKey) return null;
  if (e.key === ' ' && !e.metaKey) return e.repeat ? null : 'toggle';
  if (e.metaKey && e.key === 'ArrowRight') return 'next';
  if (e.metaKey && e.key === 'ArrowLeft') return 'prev';
  return null;
}
