// What the AIFF batch panel says (issue 33 stage D, plan §6.0.2, §3): Make all lossless files AIFF for a Library view,
// Convert for several selected files (Library or To-do) and the CDJ group's Convert all. Pure: AiffBatchPanel only
// draws this, AiffBatchFlow (flows.svelte.ts) holds the plan it read and the batch it runs. A batch's running rows and
// its end reuse stage B's helpers (decisionModel: progressRows, endRows, batchEnd); the words here are the AIFF ones.
import type { AiffPlan, AiffScope } from '$lib/bridge/types';
import type { Outcome } from '$lib/components/choiceModel';
import { sizeWords } from '$lib/format';
import { endNote, type BatchEnd } from './decisionModel';

/** Where the panel was opened: the convert job's origin (its batch scope) and To-do's words ("files for CDJs"). */
export type AiffOrigin = 'library' | 'todo';

/** One key per scope: the plan read and the batch run belong to it (a selection in any order is the same scope). */
export function scopeKey(scope: AiffScope): string {
  if (scope.kind === 'tracks') return `tracks:${[...scope.tracks].sort().join('|')}`;
  if (scope.kind === 'cdj') return 'cdj';
  return `lossless:${scope.view}:${scope.key ?? ''}`;
}

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);
const files = (n: number) => `${n} ${plural(n, 'file', 'files')}`;
/** The running list's title: "4 files" ("1 file"). */
export const filesSummary = files;

/** Plan §3: the format sentence, word for word (design §8). Shown when the plan converts at least one file. */
export const FORMAT_SENTENCE = 'Every file becomes a 16-bit/44.1 kHz AIFF, the format every CDJ plays and every download has; your original stays in Superseded/.';
/** Plan §3: the empty view (no filled button). */
export const EMPTY_VIEW = 'Every lossless file here is a clean AIFF already.';
/** A selection or the CDJ group with nothing to change and nothing left out (the engine's refusal words). */
export const NOTHING_TO_CHANGE = 'Nothing to change: these are clean AIFFs already.';
/** Plan §3: why the filled button is off while rekordbox runs and holds some of these files. */
export const QUIT_FIRST = 'Quit rekordbox before you start';
/** The engine's words for a selection none of which can change (fake/convert.ts NONE_CHANGEABLE). */
const NONE_CHANGEABLE = 'None of these can be changed right now.';
/** Plan §3: the head's first line of a Make all. */
export const MAKE_ALL_TITLE = 'Make all lossless files AIFF';

/** More items than this list the counts per kind, the files themselves folded under "Files" (plan §6.0.2): up to this
 *  many, the files are the list, each saying what happens to it, since a count of one beside a kind says less than the
 *  file's own name, and the user picked them by name. */
export const FILES_MAX = 8;
export type ListShape = 'files' | 'kinds';
export const listShape = (plan: Pick<AiffPlan, 'items'>): ListShape => (plan.items.length > FILES_MAX ? 'kinds' : 'files');

/** The panel's head, two lines (plan §3). null: not known yet (the plan is still being read), the line waits as a
 *  Skeleton of its own height. `label`: the view's title the page already shows, so a Make all's head is whole at once. */
export function panelHead(scope: AiffScope, plan: AiffPlan | null, origin: AiffOrigin, label?: string | null):
  { title: string | null; sub: string | null } {
  const k = plan ? plan.total : null;
  const can = k === null ? null : k ? `${k} can become clean AIFF` : 'Nothing to change';
  if (scope.kind === 'lossless') {
    const where = plan?.scope.label ?? label ?? null;
    return { title: MAKE_ALL_TITLE, sub: where ? `in ${where}` : null };
  }
  if (scope.kind === 'cdj') {
    const n = plan ? plan.total + plan.waiting.reduce((a, w) => a + w.n, 0) : null;
    return { title: n === null ? null : `${files(n)} for CDJs`, sub: k === null ? null : k ? `Convert all · ${k}` : 'Nothing to change' };
  }
  const n = scope.tracks.length;
  return { title: origin === 'todo' ? `${files(n)} for CDJs` : `${n} ${plural(n, 'track', 'tracks')} selected`, sub: can };
}

/** The foot's filled button (plan §3): "Make {k} files AIFF" ("Make 1 file AIFF"); the CDJ group's and To-do's
 *  "Convert {k} to AIFF"; a plan of clean names only says what it does ("Give 3 files their clean names": a clean AIFF
 *  can't be made AIFF). `plan` null (still reading): the words without a number, the button off. */
export function runLabel(scope: AiffScope, plan: Pick<AiffPlan, 'items' | 'total'> | null, origin: AiffOrigin): string {
  const cdj = scope.kind === 'cdj' || origin === 'todo';
  if (!plan) return cdj ? 'Convert to AIFF' : 'Make AIFF';
  const k = plan.total;
  if (cdj) return `Convert ${k} to AIFF`;
  if (k && plan.items.every((i) => i.action === 'rename')) return k === 1 ? 'Give 1 file its clean name' : `Give ${k} files their clean names`;
  return `Make ${files(k)} AIFF`;
}

/** Plan §3's space words for a drive: `drive` is a folder on it; a drive under /Volumes is named by its own name, any
 *  other is the Mac's own disk. */
export function driveName(drive: string): string {
  const m = /^\/Volumes\/([^/]+)/.exec(drive);
  return m ? m[1] : 'this Mac';
}
export type SpaceRow = { drive: string; needs: string; free: string; enough: boolean };
/** The room per drive (plan §3 "Needs {size} on {drive} · {free} free"), cut at its "·" into the line and its quiet
 *  second line: at 320 px the whole sentence doesn't share one line with the key column. */
export function spaceRows(plan: Pick<AiffPlan, 'space'>): SpaceRow[] {
  return plan.space.filter((d) => d.needed > 0).map((d) => ({ drive: d.drive,
    needs: `Needs ${sizeWords(d.needed)} on ${driveName(d.drive)}`, free: `${sizeWords(d.free)} free`, enough: d.enough }));
}

/** Why the filled button is off, as the Hint under it (null: it can run). A short drive first, in the problem tone (it
 *  takes more than a click to fix), then rekordbox running while it holds some of these files (the run would stop at
 *  once). Nothing to change has no filled button at all. */
export function blockReason(plan: Pick<AiffPlan, 'space' | 'rekordbox'>): { text: string; tone: 'problem' | 'muted' } | null {
  const short = plan.space.find((d) => !d.enough);
  if (short) {
    return { tone: 'problem',
      text: `Not enough space on ${driveName(short.drive)}: ${sizeWords(short.needed)} needed, ${sizeWords(short.free)} free` };
  }
  if (plan.rekordbox.running && plan.rekordbox.needs_closed) return { tone: 'muted', text: QUIT_FIRST };
  return null;
}

/** The outcome rows of the card (plan §3): rekordbox keeps every track's cues (only when rekordbox holds some of these
 *  files: `needs_closed`), and where the originals go (only when something is converted: a rename keeps its file). */
export function planOutcomes(plan: Pick<AiffPlan, 'items' | 'rekordbox' | 'superseded_bytes'>): Outcome[] {
  const out: Outcome[] = [];
  const converts = plan.items.filter((i) => i.action === 'convert').length;
  if (plan.rekordbox.needs_closed) {
    out.push({ tone: 'kept', text: plan.items.length === 1 ? 'Your track keeps its cues, playlists and history'
      : 'Your tracks keep their cues, playlists and history' });
  }
  if (converts && plan.superseded_bytes > 0) {
    const size = sizeWords(plan.superseded_bytes);
    out.push({ tone: 'file', text: converts === 1 ? `Your original (${size}) goes to Superseded/ on the same drive.`
      : `Your originals (${size}) go to Superseded/ on the same drive.` });
  }
  return out;
}
export const showsFormat = (plan: Pick<AiffPlan, 'items'>): boolean => plan.items.some((i) => i.action === 'convert');

/** Plan §3: the lossy note (info), null when none is lossy. */
export function lossyNote(n: number): string | null {
  if (n <= 0) return null;
  return n === 1 ? '1 of these is lossy: an AIFF made from it sounds the same and takes 5–10 times the space.'
    : `${n} of these are lossy: an AIFF made from them sounds the same and takes 5–10 times the space.`;
}

/** What a file's row says under its name: its kind's label ("FLAC → AIFF", "Clean name only"). */
export function kindLabel(plan: Pick<AiffPlan, 'kinds'>, kind: string): string {
  return plan.kinds.find((k) => k.kind === kind)?.label ?? kind;
}

/** "Left as they are": a selection's files the plan leaves out, each with its reason; a view's or the CDJ group's
 *  waiting files counted by reason (they are never items, and the engine names no file for them). */
export type LeftRow = { key: string; track: string | null; name: string; text: string; n: number };
export function leftRows(plan: Pick<AiffPlan, 'scope' | 'skipped' | 'waiting'>): LeftRow[] {
  if (plan.scope.kind === 'tracks') {
    return plan.skipped.map((l) => ({ key: l.track, track: l.track, name: l.name, text: l.message, n: 1 }));
  }
  return plan.waiting.map((w) => ({ key: `waiting:${w.reason}`, track: null, name: files(w.n), text: w.message, n: w.n }));
}
export const leftCount = (rows: LeftRow[]): number => rows.reduce((a, r) => a + r.n, 0);
export const LEFT_TITLE = 'Left as they are';

/** The panel's phase: the batch's while it runs or until its end is put away, else the plan's. */
export type PanelPhase = 'loading' | 'error' | 'empty' | 'decide' | 'running' | 'ended';
export function panelPhase(read: { phase: 'loading' | 'ready' | 'error'; plan: AiffPlan | null } | null,
  run: { phase: 'running' | 'ended' } | null): PanelPhase {
  if (run) return run.phase;
  if (!read || (read.phase === 'loading' && !read.plan)) return 'loading';
  if (read.phase === 'error' && !read.plan) return 'error';
  const plan = read.plan!;
  return plan.items.length || plan.skipped.length || plan.waiting.length ? 'decide' : 'empty';
}
/** The empty state's words (plan §3: a view; the engine's words for a selection or the CDJ group). */
export const emptyWords = (scope: AiffScope): string => (scope.kind === 'lossless' ? EMPTY_VIEW : NOTHING_TO_CHANGE);

// ---------- running and ended ----------
/** The running panel's label under the number: what is going on, with the file in work (plan §3; stage B's form). */
export function aiffRunLabel(now: string | null, renames: boolean): string {
  const what = renames ? 'Giving clean names' : 'Making AIFF';
  return now ? `${what} · ${now}` : what;
}
/** The end's number and its words (plan §3 "Made {n} files AIFF"), as a StatCard says them: "3 files" over
 *  "made AIFF"; a batch of clean names only "given their clean names". */
export function madeWords(done: number, renames: boolean): { unit: string; label: string } {
  return { unit: plural(done, 'file', 'files'), label: renames ? (done === 1 ? 'given its clean name' : 'given their clean names') : 'made AIFF' };
}
/** The ended panel's two lists: "Left as they are" (skipped or failed, with their reasons: plan §3's skipped header)
 *  and the files the batch didn't reach, "Still to do" (what Resume does; stage B's "{k} left" would sit beside "Left
 *  as they are" and read as the same thing). */
export const STILL_TO_DO = 'Still to do';
/** The note over a batch that ended early (stage B's words: design §8's rekordbox ones, "Stopped after 2 of 4."), with
 *  the AIFF refusal when the engine gave no words. */
export function aiffEndNote(e: BatchEnd): { tone: 'info' | 'warn'; text: string } | null {
  if (e.kind === 'refused') return { tone: 'warn', text: e.message || NONE_CHANGEABLE };
  return endNote(e);
}
