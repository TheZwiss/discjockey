// The words and counts of the missing files' actions (issue 43, plan docs/2026-11-17-missing-files-plan.md §5.4 and §7):
// a song whose file waits as missing gets Download again (a playlist song) or Remove from library (any other), from its
// Details foot and from the selection panel (several songs). Pure. The window shows the engine's words (`missing.will`,
// `missing.words`, the job's `words`) and its counts and decides nothing: which action a song has is the engine's
// `missing.action`, and whether it can run now is `missing.why_not`. The selection panel's button words, counts and the
// Remove question come from the engine's `missing_files_preview` (`button`, `confirm`, items' `will`), the head link's
// words from the group's `all.label`.
import type { MissingAction, MissingConfirm, MissingItemResult, MissingPreview, MissingResult, TodoItem, TrackDetail } from '$lib/bridge/types';
import type { MissingPreviews } from './flows.svelte';
import { plural } from '$lib/format';

/** The title of the drop zone's card on a missing song: the dropped file is put in as the song's file. */
export const PUT_BACK_TITLE = 'Put its file back';

/** The selection panel's head: "{k} songs selected". */
export const missingSelectedTitle = (k: number): string => `${plural(k, 'song', 'songs')} selected`;

/** One row of the selection panel: the engine's `will` words, or the `why_not` words dimmed (the song is skipped). */
export type MissingRowWords = { text: string; dim: boolean };
export function missingRowWords(i: Pick<TodoItem, 'missing'>): MissingRowWords {
  const m = i.missing;
  if (!m) return { text: '', dim: true };
  return m.why_not ? { text: m.words ?? '', dim: true } : { text: m.will, dim: false };
}

/** The selection panel's two buttons, from the engine's previews (`missing_files_preview` once per action over the
 *  selection): its `button` words ("Download again · {n}" / "Remove from library · {n}…"; null when no song runs) and the
 *  track ids the press sends, the items whose `will` is true. The Download again button is the filled one, so with only
 *  Remove selected the Remove button stays the danger one. `none` is the engine's one line for a selection nothing can run
 *  for, shown when both buttons are null: the line of the action the selected songs have (`actions`, their
 *  `missing.action`): Remove's ("Nothing to remove: 2 songs are skipped.") when every one has Remove, else Download
 *  again's ("Nothing to do: 3 songs are skipped."). */
export type MissingButton = { label: string; ids: string[]; confirm: MissingConfirm | null };
export type MissingButtons = { download: MissingButton | null; remove: MissingButton | null; none: string | null };
export function missingButtons(previews: { download_again: MissingPreview | null; remove: MissingPreview | null } | null,
  actions: MissingAction[] = []): MissingButtons {
  const one = (p: MissingPreview | null): MissingButton | null => (p?.button
    ? { label: p.button, ids: p.items.filter((i) => i.will).map((i) => i.track_id), confirm: p.confirm } : null);
  const download = one(previews?.download_again ?? null);
  const remove = one(previews?.remove ?? null);
  const removeOnly = actions.length > 0 && actions.every((a) => a === 'remove');
  const none = (removeOnly ? previews?.remove?.words : previews?.download_again?.words) ?? null;
  return { download, remove, none: download || remove ? null : none };
}

/** The previews only while they answer for exactly these songs, in this order: after the selection changed (a failed or
 *  pending read) the old answer's buttons would act on songs that are no longer selected, so it is dropped. */
export function currentPreviews(previews: MissingPreviews | null, ids: string[]): MissingPreviews | null {
  return previews && previews.ids.length === ids.length && previews.ids.every((id, i) => id === ids[i]) ? previews : null;
}

/** One row of the foot of a single song's details: the engine's button words and tone (`label`, `tone`), and when it
 *  can't run the engine's `foot_note` as its tip and as the Hint under it (the Upgrade ready reasons' pattern; null
 *  when the note above already says the reason). */
export type MissingFoot = { action: MissingAction; label: string; variant: 'filled' | 'danger'; disabled: boolean;
  tip: string | null; hint: string | null };
export function missingFoot(track: Pick<TrackDetail, 'missing'>): MissingFoot | null {
  const m = track.missing;
  if (!m) return null;
  return { action: m.action, label: m.label, variant: m.tone, disabled: m.why_not !== null, tip: m.foot_note, hint: m.foot_note };
}

/** The details' note for a missing file: the engine's `line` as its title and, as its text, `hint` (To-do, where the
 *  buttons are) or `hint_library` (the Library, whose foot only goes to To-do). */
export type MissingNote = { title: string; text: string };
export function missingNote(track: Pick<TrackDetail, 'missing'>, where: 'todo' | 'library' = 'todo'): MissingNote | null {
  const m = track.missing;
  return m ? { title: m.line, text: where === 'library' ? m.hint_library : m.hint } : null;
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
