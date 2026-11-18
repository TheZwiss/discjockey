// The words and counts of the missing files' actions (issue 43, plan docs/2026-11-17-missing-files-plan.md §5.4 and §7):
// a song whose file waits as missing gets Download again (a playlist song) or Remove from library (any other), from its
// Details foot and from the selection panel (several songs). Pure. The window shows the engine's words (`missing.will`,
// `missing.words`, the job's `words`) and its counts and decides nothing: which action a song has is the engine's
// `missing.action`, and whether it can run now is `missing.why_not`; counting the selection by those two is formatting
// (as UpgradeSelection counts `same_track`).
import type { MissingAction, MissingItemResult, MissingResult, TodoItem, TrackDetail } from '$lib/bridge/types';
import { plural } from '$lib/format';

/** The buttons' words for one song (§5.4): Remove asks first, so its label has the dots. */
export const DOWNLOAD_AGAIN_LABEL = 'Download again';
export const REMOVE_LABEL = 'Remove from library…';
export const missingLabel = (action: MissingAction): string => (action === 'remove' ? REMOVE_LABEL : DOWNLOAD_AGAIN_LABEL);

/** The selection panel's head: "{k} songs selected". */
export const missingSelectedTitle = (k: number): string => `${plural(k, 'song', 'songs')} selected`;
/** The selection panel's buttons (§5.4): "Download again · {n}" and "Remove from library · {m}…". */
export const downloadAgainManyLabel = (n: number): string => `${DOWNLOAD_AGAIN_LABEL} · ${n}`;
export const removeManyLabel = (m: number): string => `Remove from library · ${m}…`;
/** The head link of the group: "Select all · {n}", shown from two (with one, the row's own button does it). */
export const selectAllLabel = (n: number): string => `Select all · ${n}`;
export const selectAllShown = (n: number): boolean => n >= 2;

/** Remove's question (§5.4); several songs ask in the plural. */
export function removeConfirm(m: number) {
  return { title: m === 1 ? 'Remove from your library?' : `Remove ${m} songs from your library?`,
    body: "Their files aren't in your watched folders. Discjockey forgets these songs, your answers about them and any "
      + 'better version waiting for them. If a file comes back later, it is added as a new song.',
    confirmLabel: 'Remove', tone: 'danger' as const };
}

/** The `missing` of an item the action can run for now, by the engine's words: its `action` is set and `why_not` null. */
const canRun = (i: Pick<TodoItem, 'missing'>, action: MissingAction): boolean =>
  i.missing?.action === action && i.missing.why_not === null;

/** One row of the selection panel: the engine's `will` words, or the `why_not` words dimmed (the song is skipped). */
export type MissingRowWords = { text: string; dim: boolean };
export function missingRowWords(i: Pick<TodoItem, 'missing'>): MissingRowWords {
  const m = i.missing;
  if (!m) return { text: '', dim: true };
  return m.why_not ? { text: m.words ?? '', dim: true } : { text: m.will, dim: false };
}

/** The selection panel's two buttons: the count of the selected songs each runs for now (by the engine's `action` with
 *  `why_not` null), the label with it, and the track ids it sends. A kind with no song runnable shows no button; the
 *  Download again button is the filled one, so with only Remove selected the Remove button stays the danger one. */
export type MissingButtons = {
  n: number; m: number;
  download: { label: string; ids: string[] } | null;
  remove: { label: string; ids: string[] } | null;
};
export function missingButtons(items: Pick<TodoItem, 'track_id' | 'missing'>[]): MissingButtons {
  const download = items.filter((i) => canRun(i, 'download_again')).map((i) => i.track_id);
  const remove = items.filter((i) => canRun(i, 'remove')).map((i) => i.track_id);
  return { n: download.length, m: remove.length,
    download: download.length ? { label: downloadAgainManyLabel(download.length), ids: download } : null,
    remove: remove.length ? { label: removeManyLabel(remove.length), ids: remove } : null };
}

/** One row of the foot of a single song's details: the button, its variant, and when it can't run the engine's reason
 *  as its tip and as the Hint under it (the Upgrade ready reasons' pattern). */
export type MissingFoot = { action: MissingAction; label: string; variant: 'filled' | 'danger'; disabled: boolean;
  tip: string | null; hint: string | null };
export function missingFoot(track: Pick<TrackDetail, 'missing'>): MissingFoot | null {
  const m = track.missing;
  if (!m) return null;
  const why = m.why_not ? (m.words ?? '') || null : null;
  return { action: m.action, label: missingLabel(m.action), variant: m.action === 'remove' ? 'danger' : 'filled',
    disabled: m.why_not !== null, tip: why, hint: why };
}

/** The details' note for a missing file: the engine's `line` as its title and `hint` as its text. */
export type MissingNote = { title: string; text: string };
export function missingNote(track: Pick<TrackDetail, 'missing'>): MissingNote | null {
  const m = track.missing;
  return m ? { title: m.line, text: m.hint } : null;
}

// ---------- what the job said ----------
/** A song the job skipped: the engine's words for why ("This song gets Remove from library instead."). */
export type MissingSkipped = { track_id: string; name: string; text: string };
/** The selection panel's ended phase: the job's `words` (the engine's one line) and the skipped songs with their words
 *  (OutcomeList, as `notDone` of a batch); `done` counts what ran. `result` null (the job failed without one): only
 *  `words` is empty and the page keeps its problem toast. */
export type MissingEnd = { action: MissingAction; words: string; done: number; skipped: MissingSkipped[] };
export function missingEnd(result: MissingResult | null | undefined, name: (track_id: string) => string): MissingEnd | null {
  if (!result) return null;
  const skipped = result.results.filter((r): r is MissingItemResult => r.state === 'skipped')
    .map((r) => ({ track_id: r.track_id, name: name(r.track_id), text: r.words ?? '' }));
  return { action: result.action, words: result.words, done: result.done.length, skipped };
}
