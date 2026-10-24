// Tidy-up model of the Playlists page (plan library stage 2, task 6.1; pure). One list of files, three groups (the
// files that move by default, "You put these here", "Can't move"), the ticks per file, the count line `C`, the confirm
// label and what goes to the bridge. Used by the Tidy up files preview and by the save question, where a folder renamed
// on disk replaces its files' rows. The words are the plan's I6 (views.py says the same where it sends them).
import type {
  BatchResult, ProblemKind, RenameOffer, SaveFiles, SkippedMove, TidyRow, UndoPreview, UndoRow,
} from '$lib/bridge/types';

export type Ticks = ReadonlySet<number>;

// ---- I6 words ----
export const R1 = 'rekordbox may show the moved tracks as missing.';
export const R2 = 'Its Relocate finds them again by file name: Discjockey never renames them.';
export const U1 = 'You can undo this on this page.';
export const YOURS_HEADER = 'You put these here';
export const YOURS_CONTROL = 'Put these in playlist order too';
export const CANT_MOVE = "Can't move";
export const CANT_MOVE_BACK = "Can't move back";
export const LEAVE_HINT = 'If you leave them, Tidy up files can move them later.';
export const NOTHING_LEFT = 'Nothing left to undo';
export const NO_MOVES_YET = 'No files moved yet.';

/** A folder as the page shows it: `""` is the Library folder itself. */
export function folderName(f: string): string {
  return f === '' ? 'Library' : f;
}

const files = (n: number) => (n === 1 ? '1 file' : `${n} files`);

/** SAVE_HEADLINE: "{n} files would sit in a different folder". */
export function saveHeadline(n: number): string {
  return `${files(n)} would sit in a different folder`;
}

/** The confirm button: "Move 4 files" / "Move 1 file". */
export function confirmLabel(n: number): string {
  return `Move ${files(n)}`;
}

/** Undo's confirm button: "Move 2 files back". */
export function undoLabel(n: number): string {
  return `Move ${files(n)} back`;
}

/** The rename option's detail: "One folder move instead of 7 file moves." */
export function renameDetail(n: number): string {
  return `One folder move instead of ${n} file move${n === 1 ? '' : 's'}.`;
}

export function tickedText(ticked: number, of: number): string {
  return `${ticked} of ${of} ticked`;
}

export function goBackText(going: number, of: number): string {
  return `${going} of ${of} go back`;
}

/** The result's list head: "2 not moved:". */
export function notMovedText(n: number): string {
  return `${n} not moved:`;
}

// ---- groups and ticks ----

export type Groups = { main: TidyRow[]; yours: TidyRow[]; skipped: TidyRow[] };

/** The three groups in the backend's order: default moves, the user's own placements, the ones that can't move. */
export function groups(rows: TidyRow[]): Groups {
  return {
    main: rows.filter((r) => !r.skip && !r.yours),
    yours: rows.filter((r) => !r.skip && r.yours),
    skipped: rows.filter((r) => !!r.skip),
  };
}

/** The ticks a list starts with: the rows the backend ticks by default (a skipped row is never ticked). */
export function initialTicks(rows: TidyRow[]): Set<number> {
  return new Set(rows.filter((r) => r.ticked && !r.skip).map((r) => r.file_id));
}

/** Ticks or unticks one row; a skipped row can't be ticked. */
export function toggleTick(ticks: Ticks, row: TidyRow): Set<number> {
  const out = new Set(ticks);
  if (row.skip) return out;
  if (out.has(row.file_id)) out.delete(row.file_id); else out.add(row.file_id);
  return out;
}

export type GroupState = 'all' | 'some' | 'none';
export function groupState(ticks: Ticks, rows: TidyRow[]): GroupState {
  const n = rows.filter((r) => ticks.has(r.file_id)).length;
  return n === 0 ? 'none' : n === rows.length ? 'all' : 'some';
}

/** The group's control: ticks every row of the group, or unticks them all when they all are. */
export function toggleGroup(ticks: Ticks, rows: TidyRow[]): Set<number> {
  const out = new Set(ticks);
  const all = groupState(ticks, rows) === 'all';
  for (const r of rows) if (!r.skip) { if (all) out.delete(r.file_id); else out.add(r.file_id); }
  return out;
}

/** Rows that can be ticked (not skipped). */
export function tickable(rows: TidyRow[]): TidyRow[] {
  return rows.filter((r) => !r.skip);
}

/** The ticked rows, in list order (main group first, then the user's own): the order the moves happen in. */
export function tickedRows(rows: TidyRow[], ticks: Ticks): TidyRow[] {
  const g = groups(rows);
  return [...g.main, ...g.yours].filter((r) => ticks.has(r.file_id));
}

/** What `tidy_up` / `save_playlists` get: `[file_id, from_path]` of each ticked row. */
export function movesOf(rows: TidyRow[], ticks: Ticks): [number, string][] {
  return tickedRows(rows, ticks).map((r) => [r.file_id, r.from_path]);
}

// ---- the count line C ----

export type Pair = { from: string; to: string; n: number };

/** Pairs (from → to) with their counts, in the order they first appear. */
export function pairsOf(items: { from: string; to: string; n?: number }[]): Pair[] {
  const out: Pair[] = [];
  for (const it of items) {
    const p = out.find((x) => x.from === it.from && x.to === it.to);
    if (p) p.n += it.n ?? 1; else out.push({ from: it.from, to: it.to, n: it.n ?? 1 });
  }
  return out.filter((p) => p.n > 0);
}

/** The count line `C` (I6), or null when nothing moves. One pair: "8 files move from A to B."; 2–3 pairs:
 *  "{n} files move: {a} from A to B, {b} from C to D."; more: "{n} files move between {k} folders." */
export function countLine(pairs: Pair[]): string | null {
  const n = pairs.reduce((a, p) => a + p.n, 0);
  if (!n) return null;
  const verb = n === 1 ? '1 file moves' : `${n} files move`;
  const ft = (p: Pair) => `from ${folderName(p.from)} to ${folderName(p.to)}`;
  if (pairs.length === 1) return `${verb} ${ft(pairs[0])}.`;
  if (pairs.length <= 3) return `${verb}: ${pairs.map((p) => `${p.n} ${ft(p)}`).join(', ')}.`;
  const k = new Set(pairs.flatMap((p) => [p.from, p.to])).size;
  return `${verb} between ${k} folders.`;
}

// ---- the save question: folder renames on disk ----

/** A folder renamed on disk, in place of its files' rows. `files` = the files in the folder (the offer's count, the
 *  one count this row, the option's detail, the heading and `C` all come from: the folder moves as a whole, so it
 *  carries more than the rows the preview lists when files sit in it that no playlist places). */
export type FolderRow = { from: string; to: string; files: number };

/** The save question's choices: ticks, and which offered renames are on (all on by default). */
export type SaveQuestion = { rows: TidyRow[]; renames: RenameOffer[]; ticks: Ticks; renameOn: ReadonlySet<string> };

export function initialQuestion(rows: TidyRow[], renames: RenameOffer[]): SaveQuestion {
  return { rows, renames, ticks: initialTicks(rows), renameOn: new Set(renames.filter((r) => r.offered).map((r) => r.from)) };
}

/** A newer preview of the same draft: its rows and renames, keeping what the user chose for the files and folders
 *  both previews have (a file new to the list starts as the backend ticks it). */
export function carryOver(old: SaveQuestion | null, rows: TidyRow[], renames: RenameOffer[]): SaveQuestion {
  const next = initialQuestion(rows, renames);
  if (!old) return next;
  const known = new Set(old.rows.map((r) => r.file_id));
  const ticks = new Set([...next.ticks].filter((id) => !known.has(id)));
  for (const r of rows) if (known.has(r.file_id) && old.ticks.has(r.file_id) && !r.skip) ticks.add(r.file_id);
  const renameOn = new Set([...next.renameOn].filter((f) => {
    const was = old.renames.find((o) => o.from === f);
    return !was || !was.offered || old.renameOn.has(f);
  }));
  return { ...next, ticks, renameOn };
}

export function toggleRename(q: SaveQuestion, from: string): SaveQuestion {
  const offer = q.renames.find((r) => r.from === from);
  if (!offer?.offered) return q;
  const on = new Set(q.renameOn);
  if (on.has(from)) on.delete(from); else on.add(from);
  return { ...q, renameOn: on };
}

/** The rows shown: a rename that is on hides the files it moves (its folder row stands for them). */
export function visibleRows(q: SaveQuestion): TidyRow[] {
  return q.rows.filter((r) => !(r.by_rename && q.renameOn.has(r.by_rename)));
}

/** The folder rows of the renames that are on. */
export function folderRows(q: SaveQuestion): FolderRow[] {
  return q.renames.filter((r) => r.offered && q.renameOn.has(r.from))
    .map((r) => ({ from: r.from, to: r.to, files: r.files }));
}

/** The option's detail line, counted from the offer's files. */
export function offerDetail(offer: RenameOffer): string {
  return offer.offered ? renameDetail(offer.files) : offer.why_not ?? '';
}

/** The files the save question is about: the shown rows, and each folder renamed on disk with all it carries. */
export function saveFileCount(q: SaveQuestion): number {
  return visibleRows(q).length + folderRows(q).reduce((a, f) => a + f.files, 0);
}

/** `C` for the save question: each folder row as one pair, then the ticked rows still shown. */
export function saveCount(q: SaveQuestion): string | null {
  const shown = visibleRows(q);
  return countLine(pairsOf([
    ...folderRows(q).map((f) => ({ from: f.from, to: f.to, n: f.files })),
    ...tickedRows(shown, q.ticks),
  ]));
}

/** How many files "Save and move the files" moves (0: the button is off). */
export function saveMoving(q: SaveQuestion): number {
  return folderRows(q).reduce((a, f) => a + f.files, 0) + tickedRows(visibleRows(q), q.ticks).length;
}

/** `save_playlists`' third argument. Leave: nothing moves, no folder is renamed. Move: the renames that are on, then
 *  the ticked rows still shown. */
export function saveFiles(q: SaveQuestion, choice: 'leave' | 'move'): SaveFiles {
  if (choice === 'leave') return { choice, renames: [], moves: [] };
  return { choice, renames: folderRows(q).map((f) => [f.from, f.to]), moves: movesOf(visibleRows(q), q.ticks) };
}

// ---- progress ----

/** What moves, as the progress list shows it: a folder renamed on disk (with the files it carries) or a file. */
export type MoveItem = { key: string; label: string; from: string; to: string; folder: boolean; files: number | null;
  track_id: string | null; cover_url: string | null };

export function itemOfRow(r: TidyRow): MoveItem {
  return { key: `f${r.file_id}`, label: `${r.artist} – ${r.title}`, from: r.from, to: r.to, folder: false, files: null,
    track_id: r.track_id, cover_url: r.cover_url };
}

export function itemOfFolder(f: FolderRow): MoveItem {
  return { key: `d${f.from}`, label: f.from, from: f.from, to: f.to, folder: true, files: f.files, track_id: null,
    cover_url: null };
}

/** The save's moves in the order they happen: the folder renames, then the files. */
export function saveItems(q: SaveQuestion): MoveItem[] {
  return [...folderRows(q).map(itemOfFolder), ...tickedRows(visibleRows(q), q.ticks).map(itemOfRow)];
}

/** What an undo run moves, in the order it runs. A row that can't go back isn't here: the batch records it skipped
 *  before anything moves, so the run's progress (`MovesProgress`, moves handled of moves planned) counts only these;
 *  the result lists the skipped ones with their reasons. */
export function undoItems(p: UndoPreview): MoveItem[] {
  return p.rows.filter((r) => !r.skip).map((r, i) => ({ key: `u${i}`, label: r.label, from: r.from, to: r.to,
    folder: r.kind === 'folder', files: r.kind === 'folder' ? r.files : null, track_id: null, cover_url: null }));
}

/** An undo row's name: a folder says so ("Old_Sets, the whole folder"), a file is its "Artist - Title". */
export function undoRowName(r: Pick<UndoRow, 'label' | 'kind'>): string {
  return r.kind === 'folder' ? `${r.label}, the whole folder` : r.label;
}

/** A folder's file count for the line under its name ("7 files"); null for a file, which has no count. */
export function fileCountText(n: number | null): string | null {
  return n === null ? null : files(n);
}

/** Progress over the batches of one job (a save runs a batch per folder rename, then one for the files): each
 *  batch's latest `MovesProgress`. `expected`: the moves the page asked for, so the total doesn't shrink between two
 *  batches. */
export type Progress = { batches: [number, { done: number; total: number }][]; expected: number };

export function progressStart(expected: number): Progress {
  return { batches: [], expected };
}

export function progressStep(p: Progress, e: { batch_id: number; done: number; total: number }): Progress {
  const rest = p.batches.filter(([id]) => id !== e.batch_id);
  return { ...p, batches: [...rest, [e.batch_id, { done: e.done, total: e.total }]] };
}

export function progressDone(p: Progress): number {
  return p.batches.reduce((a, [, b]) => a + b.done, 0);
}

export function progressTotal(p: Progress): number {
  return Math.max(p.expected, p.batches.reduce((a, [, b]) => a + b.total, 0));
}

// ---- results ----

/** One result for the panel from a job's batches (a save may run several). */
export type Outcome = { moved: number; skipped: SkippedMove[]; back: boolean; batchIds: number[] };

export function outcomeOf(results: BatchResult[], back = false): Outcome {
  return {
    moved: results.reduce((a, r) => a + r.moved, 0),
    skipped: results.flatMap((r) => r.skipped),
    back,
    batchIds: results.filter((r) => r.batch_id !== null && r.moved > 0).map((r) => r.batch_id as number),
  };
}

/** What the result's Undo does: one batch → its undo confirmation; several → the Recent moves list; none → off. */
export function resultUndo(o: Outcome): { batch: number } | 'list' | null {
  if (!o.batchIds.length) return null;
  return o.batchIds.length === 1 ? { batch: o.batchIds[0] } : 'list';
}

/** The tone of a "not moved" row's mark: a failed move is a problem, the rest are warnings. */
export function skipTone(reason: string): 'problem' | 'warn' {
  return reason === 'failed' ? 'problem' : 'warn';
}

/** The problem the page tells (a toast) after a move job that ran `quiet`: every failure except a Stop the user
 *  pressed, which explains itself (the result lists what was not moved). Null: nothing to tell. */
export function problemToTell(out: { ok: boolean; kind?: ProblemKind; message?: string }):
  { kind: ProblemKind; message: string } | null {
  if (out.ok || !out.kind || out.kind === 'stopped') return null;
  return { kind: out.kind, message: out.message ?? '' };
}
