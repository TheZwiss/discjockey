// What pressing a decision does, and its state while it runs, shared by To-do's and the Library's details so the same
// choice does the same thing on both pages (mockup todo-decisions). One flow per details panel: its cards (the choice,
// disabled while a job runs) and its foot (the buttons) read the same flow. Every action is a write job through
// runJob (its toast on a refusal); the finished job bumps filesVersion, and each page re-fetches what it shows.
import { api, rekordboxStatus, runJob, type JobOutcome } from '$lib/bridge/client';
import { onEvent } from '$lib/bridge/events';
import { waitForJob } from '$lib/stores/jobs';
import type {
  AiffBatchResult, AiffPlan, AiffScope, DuplicatePair, JobSnap, JobStart, MissingAction, MissingConfirm, MissingPreview, MissingResult, RekordboxCheckView,
  RekordboxStatus, TodoItem, UndoResult,
} from '$lib/bridge/types';
import { latestOnly } from '$lib/latest';
import { aiffProblem } from './aiffModel';
import { scopeKey } from './aiffBatchModel';
import { confirm } from '$lib/components/confirm';
import { toasts } from '$lib/stores/toasts';
import { problemCopy, successCopy } from '$lib/copy';
import {
  batchEnd, canTryAgain, discardConfirm, endRows, isOwnCheck, progressRows, runRow, undoAsk, undoManyConfirm, undoProblem, undoneToast,
  type BatchEnd,
  type BatchMode, type DuplicatePick, type RunRow, type UndoProblem, type UpgradeWays, type Way,
} from './decisionModel';
import { missingEnd, type MissingEnd } from './missingModel';

/** The bridge's name for each way (`upgrade(ids, mode)`): the page's own words stay as they are. */
const BRIDGE_MODE = { swap: 'same_track', add_new: 'new_track', discard: 'discard' } as const;

/** The upgrade and the rekordbox check it leaves: Replace (the "In rekordbox" pick), Discard, Done, Undo. `busy`
 *  names the running action; a page may set it for one of its own (To-do's Hide), so the buttons wait for that too. */
export class UpgradeFlow {
  picked = $state<Way | null>(null);
  busy = $state<string | null>(null);
  /** an undo's refusal, kept under its button until the next track */
  undoProblem = $state<string | null>(null);
  #for = '';
  #onact: (() => void) | undefined;

  /** `onact`: called as an action's job starts (after its confirm), so a page can keep the track it acted on in
   *  view (the Library's hold; To-do keeps its item by its own selection). */
  constructor(opts: { onact?: () => void } = {}) {
    this.#onact = opts.onact;
  }

  /** A new track starts over: Same track picked again where both ways are possible, no old refusal. */
  follow(track_id: string): void {
    if (track_id === this.#for) return;
    this.#for = track_id;
    this.picked = null;
    this.undoProblem = null;
  }
  /** The picked way: Same track (swap) by default where both ways are possible, else the card's one way (New track,
   *  or Same track's clean AIFF where there is no rekordbox). */
  way(ways: Pick<UpgradeWays, 'choice' | 'way'> | null): Way {
    if (!ways) return 'add_new';
    return ways.choice ? (this.picked ?? 'swap') : ways.way;
  }
  /** Replace with lossless (swap / add_new) or Discard (spec §6.6). A replace needs no confirm: it can be undone until
   *  Done (the hint under it says so); Discard deletes the new version, so it asks. "changed": runJob shows "This
   *  track changed in the meantime."; the finished job re-fetches the page. `rev`: the one the card was read with: the
   *  write is refused `changed` when the song's record is not at that rev any more. */
  async upgrade(track_id: string, mode: Way | 'discard', rev: string | null = null): Promise<void> {
    if (mode === 'discard' && !(await confirm({ title: 'Throw away the new version?',
      body: 'Your current file stays. This version is not offered again.', confirmLabel: 'Discard', tone: 'danger' }))) return;
    this.busy = mode;
    this.#onact?.();
    await runJob(api.upgrade([track_id], BRIDGE_MODE[mode], null, rev));
    this.busy = null;
  }
  /** "Done, checked in rekordbox". */
  async checked(track_id: string): Promise<void> {
    this.busy = 'rekordbox';
    this.#onact?.();
    await runJob(api.rekordbox_checked([track_id]));
    this.busy = null;
  }
  /** "Undo the replace": asks first; a refusal (a file changed since, the step already done) shows as runJob's toast
   *  and stays under the button. */
  async undo(track_id: string, check: RekordboxCheckView | undefined): Promise<void> {
    if (!(await confirm(undoAsk([check])))) return;
    this.busy = 'undo';
    this.undoProblem = null;
    this.#onact?.();
    const r = await runJob<UndoResult>(api.undo_upgrade([track_id]), { success: false });
    this.busy = null;
    if (!r.ok) this.undoProblem = r.message;
    else toasts.show({ tone: 'success', title: r.result?.words || successCopy('undo_upgrade') || 'Undone.' });
  }
}

/** Convert to AIFF and Give it its clean name for one track (issue 33 stage D, plan §6.1): the button's running state,
 *  what a refusal or a skip said (the card's warn note, until the next track or the next press), and rekordbox as it is
 *  now (`rekordboxStatus`: the one answer the Sync page reads too), asked by `attach` while the card shows and when the
 *  window gets focus back (the user quits rekordbox, then returns) and after a job. `origin` is where the press came
 *  from (the job's batch scope: `library:selection` / `todo:selection`). One per panel. */
export class AiffFlow {
  busy = $state(false);
  problem = $state<string | null>(null);
  /** null until the first answer (or when the bridge couldn't say): the card then leaves out what depends on it */
  rekordbox = $state<RekordboxStatus | null>(null);
  #for = '';
  #origin: 'library' | 'todo';
  #onact: (() => void) | undefined;
  #reads = latestOnly();

  /** `onact`: called as the job starts, so a page keeps the track in view while its file and name change under it. */
  constructor(opts: { onact?: () => void; origin?: 'library' | 'todo' } = {}) {
    this.#onact = opts.onact;
    this.#origin = opts.origin ?? 'library';
  }

  /** A new track starts over: no old problem. */
  follow(track_id: string): void {
    if (track_id === this.#for) return;
    this.#for = track_id;
    this.problem = null;
  }
  async read(): Promise<void> {
    const ticket = this.#reads.next();
    const r = await rekordboxStatus();
    if (this.#reads.isLatest(ticket) && r) this.rekordbox = r;
  }
  /** Reads rekordbox's state now and again whenever the window gets focus, while the card shows; returns what stops it. */
  attach(): () => void {
    void this.read();
    const onFocus = () => void this.read();
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }
  /** The card's button: Convert to AIFF, or Give it its clean name. A refusal (rekordbox open, the song's reason) and a
   *  skipped track stay in `problem`; no toast, the card says it where the button is. */
  async run(track_id: string, action: 'convert' | 'rename'): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    this.problem = null;
    this.#onact?.();
    const out = await runJob<AiffBatchResult>(action === 'rename' ? api.rename([track_id]) : api.convert([track_id], this.#origin),
      { quiet: true, success: false });
    this.busy = false;
    this.problem = aiffProblem(out);
    void this.read();
  }
}

/** "Which file stays?": the pick (the app's recommendation until the user picks) and Keep. Keeping a file is
 *  one "supersede" write job (`keep_file`, D10: journaled, no undo) that moves every other file of the group. Keep both /
 *  Keep all is one "answer" job. */
export class DuplicateFlow {
  chosen = $state<DuplicatePick | undefined>(undefined);
  busy = $state(false);
  #for = '';
  #onact: ((keep: string[]) => void) | undefined;

  /** `onact`: called as a Keep's jobs start, with the paths of the files that stay (all of them for Keep both), so a
   *  page can follow the track that holds a kept file afterwards (the Library's hold). */
  constructor(opts: { onact?: (keep: string[]) => void } = {}) {
    this.#onact = opts.onact;
  }

  /** A new group starts over from the app's pick. */
  follow(group_id: string): void {
    if (group_id === this.#for) return;
    this.#for = group_id;
    this.chosen = undefined;
  }
  pick(g: Pick<DuplicatePair, 'recommended'>): DuplicatePick {
    return this.chosen !== undefined ? this.chosen : g.recommended ?? null;
  }
  async keep(g: DuplicatePair, pick: DuplicatePick): Promise<void> {
    if (pick === 'all') await this.#keepAll(g);
    else if (typeof pick === 'number') await this.#keepOne(g, pick);
  }
  async #keepAll(g: DuplicatePair): Promise<void> {
    this.busy = true;
    this.#onact?.(g.files.map((f) => f.path));
    await runJob(api.keep_duplicates(g.group_id, g.files.map((f) => f.path)));
    this.busy = false;
  }
  async #keepOne(g: DuplicatePair, keep: number): Promise<void> {
    this.busy = true;
    this.#onact?.(g.files.filter((x) => x.file_id === keep).map((x) => x.path));
    // one engine job moves every other file; its toast is the engine's own line ("Moved to …" / "Moved 2 files …")
    const r = await runJob(api.keep_file(g.group_id, keep, g.files.map((f) => f.path)), { success: false });
    this.busy = false;
    if (r.ok && r.message) toasts.show({ tone: 'success', title: r.message });
  }
}

/** The rekordbox checks of a batch card, or of several checks selected (plan stage B §6.4): Done for all of them, Undo
 *  for all that can (one `undo_upgrade` job, newest first) or for one row. One per panel: `follow` starts over for a
 *  new pick. An undo that left tracks as they were keeps its words until the next pick (`problem`: the line under the
 *  buttons, each refused track's reason for its row), also when the list is fetched again under the panel. */
export class ChecksFlow {
  /** `done`, `undo` (all) or `undo:<track_id>` (one row) */
  busy = $state<string | null>(null);
  problem = $state<UndoProblem | null>(null);
  #for = '';
  #onact: (() => void) | undefined;

  /** `onact`: called as an action's job starts (after its confirm), so the page keeps these tracks in its panel
   *  while the list changes under it (the batch item that becomes a single check, or goes). */
  constructor(opts: { onact?: () => void } = {}) {
    this.#onact = opts.onact;
  }
  follow(key: string): void {
    if (key === this.#for) return;
    this.#for = key;
    this.problem = null;
  }
  /** "Done, checked in rekordbox" for every track of the card (or the selection). */
  async checked(track_ids: string[]): Promise<void> {
    if (!track_ids.length || this.busy) return;
    this.busy = 'done';
    this.#onact?.();
    await runJob(api.rekordbox_checked(track_ids));
    this.busy = null;
  }
  /** "Undo all {n}" / "Undo {n}" (asks first), or a row's "Undo this one" (`one`: asks the single card's question).
   *  `checks`: the tracks' checks, so a Convert or a clean name asks in its own words. The toast is the engine's `words`. */
  async undo(track_ids: string[], one?: RekordboxCheckView, checks?: (RekordboxCheckView | undefined)[]): Promise<void> {
    if (!track_ids.length || this.busy) return;
    const ask = one ? undoAsk([one]) : checks?.some(isOwnCheck) ? undoAsk(checks) : undoManyConfirm(track_ids.length);
    if (!(await confirm(ask))) return;
    this.busy = one ? `undo:${track_ids[0]}` : 'undo';
    this.problem = null;
    this.#onact?.();
    const out = await runJob<UndoResult>(api.undo_upgrade(track_ids), { quiet: true, success: false });
    this.busy = null;
    this.problem = undoProblem(out);
    const n = out.result?.undone ?? 0;
    if (n) toasts.show({ tone: 'success', title: out.result?.words || undoneToast(n) });
  }
}
/** What the selection panel reads of the engine before a press: `missing_files_preview` once per action over the
 *  selection (`ids` are the songs asked; null: not read yet). `loading` with an answer is a read again (the selection
 *  changed): the words stay on screen meanwhile, the buttons wait. */
export type MissingPreviews = { ids: string[]; download_again: MissingPreview | null; remove: MissingPreview | null;
  phase: 'loading' | 'ready' | 'error'; message: string };

/** Download again and Remove from library for songs whose file waits as missing (issue 43, plan §7.4): one job per
 *  press (`missing_files(ids, action)`), shared by To-do's details (one song) and the selection panel (several). The
 *  panel reads the engine's previews first (`read`: the button words, the songs that run and Remove's question);
 *  Remove asks first with the engine's `confirm` (the panel hands over the one it read; a single song's press reads
 *  it then). Nothing is lost by Download again, so it runs at once.
 *  After the job the songs have left the Missing files group: the page's selection follows as after a Discard (its
 *  `onact` is called as the job starts, after the confirm, so it keeps the panel). Where the words go depends on
 *  where it was pressed: from the panel (`panel: true`) they stay as `ended` (the job's words and the skipped songs
 *  with theirs) until `clear()`; else (the details' button) a toast (the engine's `words`; a skip says why). `busy`
 *  names the running action. */
export class MissingFlow {
  busy = $state<MissingAction | null>(null);
  ended = $state<MissingEnd | null>(null);
  previews = $state<MissingPreviews | null>(null);
  #onact: (() => void) | undefined;
  #name: (track_id: string) => string;
  #reads = latestOnly();

  /** `name`: "Artist – Title" of a track id, for the skipped songs of an end */
  constructor(opts: { onact?: () => void; name?: (track_id: string) => string } = {}) {
    this.#onact = opts.onact;
    this.#name = opts.name ?? ((id) => id);
  }

  /** The panel's Done, or the next pick: the end is put away. */
  clear(): void {
    this.ended = null;
  }
  /** Reads what both actions would do for `ids`; only the newest read's answer is kept. */
  async read(ids: string[]): Promise<void> {
    const ticket = this.#reads.next();
    const keep = this.previews;
    this.previews = { ids, download_again: keep?.download_again ?? null, remove: keep?.remove ?? null, phase: 'loading', message: '' };
    const ask = async (action: MissingAction) => {
      try { return await api.missing_files_preview(ids, action); } catch { return { ok: false as const, kind: 'crashed' as const, message: '' }; }
    };
    const [d, r] = await Promise.all([ask('download_again'), ask('remove')]);
    if (!this.#reads.isLatest(ticket)) return;
    if (d.ok && r.ok) { this.previews = { ids, download_again: d, remove: r, phase: 'ready', message: '' }; return; }
    const bad = d.ok ? r : d;
    // no stale buttons: the engine's message shows in the Hint instead
    this.previews = { ids, download_again: null, remove: null, phase: 'error',
      message: (!bad.ok && bad.message) || problemCopy(!bad.ok ? bad.kind : 'crashed').title };
  }
  /** `panel`: pressed in the selection panel (the end stays there), else the words are a toast. */
  async downloadAgain(ids: string[], opts: { panel?: boolean } = {}): Promise<void> {
    await this.#run(ids, 'download_again', !!opts.panel);
  }
  /** Asks first, with the engine's words: `opts.confirm` is the question the panel read (null: the engine has none to
   *  ask, so nothing runs); without it the engine is asked for these songs now. */
  async remove(ids: string[], opts: { panel?: boolean; confirm?: MissingConfirm | null } = {}): Promise<void> {
    if (!ids.length || this.busy) return;
    const q = opts.confirm !== undefined ? opts.confirm : await this.#question(ids);
    if (!q) return;
    if (!(await confirm({ title: q.title, body: q.body, confirmLabel: q.confirm_label, tone: q.tone }))) return;
    await this.#run(ids, 'remove', !!opts.panel);
  }
  /** Remove's question for `ids`, from the engine's dry run; null when it can't be asked or no song would run (the
   *  engine's words come as a toast). */
  async #question(ids: string[]): Promise<MissingConfirm | null> {
    const r = await api.missing_files_preview(ids, 'remove');
    if (!r.ok) { toasts.show({ tone: 'problem', title: problemCopy(r.kind).title, body: r.message || undefined }); return null; }
    if (!r.confirm) toasts.show({ tone: 'problem', title: r.words });
    return r.confirm;
  }

  async #run(ids: string[], action: MissingAction, panel: boolean): Promise<void> {
    if (!ids.length || this.busy) return;
    this.busy = action;
    this.ended = null;
    this.#onact?.();
    const out = await runJob<MissingResult>(api.missing_files(ids, action), { quiet: true, success: false });
    this.busy = null;
    const result = out.result ?? null;
    // refused before it started (busy, console, a sync running): nothing ran, a toast says why
    if (!out.ok && out.job_id === null) {
      toasts.show({ tone: 'problem', title: problemCopy(out.kind).title, body: out.message || undefined });
      return;
    }
    if (panel) {
      this.ended = missingEnd(result, this.#name);
      if (!this.ended && !out.ok) toasts.show({ tone: 'problem', title: problemCopy(out.kind).title, body: out.message || undefined });
      return;
    }
    // the details' button: the words as a toast; every song skipped (the job ends `changed`) says the song's reason
    const words = result?.words || (out.ok ? '' : out.message);
    if (out.ok) { if (words) toasts.show({ tone: 'success', title: words }); return; }
    const why = result?.results.find((r) => r.state === 'skipped')?.words;
    toasts.show({ tone: 'problem', title: problemCopy(out.kind).title, body: why || words || undefined });
  }
}

/** Which flow follows a batch job the window didn't start (the window was reloaded). `batch_resume` is one kind for
 *  Same track's batches and for Convert's, so the job's `batch_kind` decides: `convert` and `mixed` are the AIFF
 *  batch flow's, `upgrade` the upgrade batch flow's. A resume with no kind (`null` or missing: a hub that doesn't say)
 *  is neither's: guessing would show a Convert batch under Same track's words (or the other way round), so the window
 *  follows none and only learns of its end from the list and the events. */
const resumeIsAiff = (job: JobSnap): boolean => job.batch_kind === 'convert' || job.batch_kind === 'mixed';
const resumeIsUpgrade = (job: JobSnap): boolean => job.batch_kind === 'upgrade';

/** The write jobs of an upgrade list or batch (contract "Upgrades and batches"): each sends BatchProgress. */
export const BATCH_JOBS = ['upgrade_batch', 'batch_resume', 'upgrade_add_new', 'upgrade_discard'];
const MODE_OF: Record<string, BatchMode> = { upgrade_batch: 'swap', batch_resume: 'swap', upgrade_add_new: 'add_new',
  upgrade_discard: 'discard' };
/** What the selection panel shows of a batch: running (its rows, the count, Stop) or ended (until the next pick).
 *  `tracks`: the track ids it was started for (null: found running, or a Resume; it then shows for any selection of
 *  the group). */
export type BatchView = { phase: 'running' | 'ended'; mode: BatchMode; tracks: string[] | null; rows: RunRow[];
  done: number; total: number; now: string | null; stopping: boolean; end: BatchEnd | null;
  /** runs the same call again (an end with nothing to resume) */
  again: (() => void) | null };

/** Several upgrades at once (plan stage B §6.2): Replace (Same track as one batch, `upgrade_all` when the selection is
 *  the whole group; New track and Discard as lists), Stop, Resume, and what came of it. One per window, outside any
 *  component, so the progress survives the To-do panel switching to another row and back, and a page opened while a
 *  batch runs finds it (`adopt`, from the hub's job). The one-track decision stays UpgradeFlow's. */
export class UpgradeBatchFlow {
  view = $state<BatchView | null>(null);
  #off: (() => void) | null = null;
  /** track_id → "Artist – Title" of the tracks the page or the progress has named, so the end can name a track that
   *  never had a progress row (a Resume, a batch found running, a track skipped before it was in work) */
  #known = new Map<string, string>();

  /** The page tells the flow the names of the tracks it lists. */
  know(names: Iterable<[string, string]>): void {
    for (const [id, name] of names) this.#known.set(id, name);
  }

  /** Replace (`swap` / `add_new`) or Discard (confirmed first) for the selected items; `all`: the selection is the
   *  whole group, so Same track goes as Upgrade all. Only the items the way replaces are run. */
  async start(mode: BatchMode, items: TodoItem[], all: boolean, name: (i: TodoItem) => string): Promise<void> {
    if (this.view?.phase === 'running') return; // a second press while one runs (the first call's listener must stay)
    if (mode === 'discard' && !(await confirm(discardConfirm(items.length)))) return;
    const ids = items.map((i) => i.track_id);
    this.know(items.map((i) => [i.track_id, name(i)]));
    // a rev is the check of one song's record: only a one-song list sends it
    const call = () => mode === 'swap' && all ? api.upgrade_all()
      : ids.length === 1 ? api.upgrade(ids, BRIDGE_MODE[mode], null, items[0].rev) : api.upgrade(ids, BRIDGE_MODE[mode], null);
    await this.#run(mode, ids, items.map((i) => runRow(i, name(i))), call);
  }
  /** Resume · k left: the stopped batch's planned tracks (their rows come with its progress). */
  async resume(batch_id: number): Promise<void> {
    if (this.view?.phase === 'running') return;
    await this.#run('swap', null, [], () => api.batch_resume(batch_id));
  }
  /** Stop between tracks (the one in work finishes). */
  async stop(): Promise<void> {
    if (!this.view || this.view.phase !== 'running') return;
    this.view.stopping = true;
    const r = await api.stop();
    if (!r.ok && this.view) {
      this.view.stopping = false;
      toasts.show({ tone: 'problem', title: "Couldn't stop.", body: r.message || undefined });
    }
  }
  /** Done (or the next pick): the end is put away. A running batch stays. */
  clear(): void {
    if (this.view?.phase === 'ended') this.view = null;
  }
  /** A batch job the hub reports running that this flow didn't start (the window was reloaded): follow its progress.
   *  A job for one track (`track_id` set) is that track's own decision panel's, never adopted. */
  adopt(job: JobSnap | null): void {
    if (!job?.running || job.track_id !== null || !BATCH_JOBS.includes(job.kind) || this.view?.phase === 'running') return;
    if (job.kind === 'batch_resume' && !resumeIsUpgrade(job)) return;
    const last = job.last?.BatchProgress as { done: number; total: number; track_id: string | null; name: string | null } | undefined;
    this.view = { phase: 'running', mode: MODE_OF[job.kind], tracks: null, rows: last ? progressRows([], last) : [],
      done: last?.done ?? 0, total: last?.total ?? 0, now: last?.name ? last.name.replace(' - ', ' – ') : null, stopping: job.stopping, end: null, again: null };
    this.#listen();
    void this.#follow(job.id);
  }
  /** Whether the panel shows this batch for a selection: always while it runs or ended for these tracks. */
  covers(ids: string[]): boolean {
    const v = this.view;
    if (!v) return false;
    return !v.tracks || ids.some((id) => v.tracks!.includes(id));
  }

  async #run(mode: BatchMode, tracks: string[] | null, rows: RunRow[], call: () => Promise<JobStart>): Promise<void> {
    this.view = { phase: 'running', mode, tracks, rows, done: 0, total: rows.length, now: null, stopping: false,
      end: null, again: null };
    this.#listen();
    const out = await runJob<AiffBatchResult>(call(), { quiet: true, success: false });
    this.#end(mode, out, () => void this.#run(mode, tracks, rows.map((r) => ({ ...r, state: 'waiting', text: null })), call));
  }
  async #follow(job_id: string): Promise<void> {
    const fin = await waitForJob(job_id);
    const mode = this.view?.mode ?? 'swap';
    this.#end(mode, fin.ok ? { ok: true, job_id, result: fin.result as AiffBatchResult }
      : { ok: false, job_id, kind: fin.problem ?? 'crashed', message: fin.message, result: (fin.result ?? null) as AiffBatchResult | null }, null);
  }
  #end(mode: BatchMode, out: JobOutcome<AiffBatchResult>, again: (() => void) | null): void {
    this.#off?.();
    this.#off = null;
    const end = batchEnd(mode, out);
    // refused before it started (busy, console, a sync running): nothing ran, the decision stays and a toast says why
    if (!out.ok && out.job_id === null) {
      this.view = null;
      toasts.show({ tone: 'problem', title: problemCopy(out.kind).title, body: out.message || undefined });
      return;
    }
    const v = this.view;
    const rows = endRows(v?.rows ?? [], out.result?.results ?? [], (id) => this.#known.get(id) ?? null);
    this.view = { phase: 'ended', mode, tracks: v?.tracks ?? null, rows, done: end.done, total: end.total || rows.length,
      now: null, stopping: false, end, again: canTryAgain(end) ? again : null };
  }
  #listen(): void {
    this.#off?.();
    this.#off = onEvent((e) => {
      if (e.type !== 'BatchProgress' || this.view?.phase !== 'running') return;
      const v = this.view;
      v.rows = progressRows(v.rows, e);
      v.done = e.done;
      v.total = e.total;
      v.now = e.name ? e.name.replace(' - ', ' – ') : null;
      if (e.track_id && v.now) this.#known.set(e.track_id, v.now);
    });
  }
}
/** The window's one batch flow. */
export const upgradeBatch = new UpgradeBatchFlow();

/** The plan the AIFF batch panel read for its scope (`key`: aiffBatchModel.scopeKey). `loading` with a `plan` is a
 *  read again of the same scope (a file changed, the window got focus back): the plan stays on screen meanwhile, so
 *  only a first read shows placeholders. `error` keeps the words of a read that failed. */
export type AiffPlanRead = { key: string; phase: 'loading' | 'ready' | 'error'; plan: AiffPlan | null; message: string };
/** What the AIFF batch panel shows of its batch: running, or ended until Done. `scope`: the scope key it was started
 *  for (null: a Resume or a batch found running, which shows for any scope); `renames`: a batch of clean names only. */
export type AiffRunView = { phase: 'running' | 'ended'; scope: string | null; rows: RunRow[]; done: number; total: number;
  now: string | null; stopping: boolean; renames: boolean; end: BatchEnd | null;
  /** runs the same call again (an end with nothing to resume) */
  again: (() => void) | null };

/** Make all lossless files AIFF, a selection's Convert and the CDJ group's Convert all (issue 33 stage D, plan §6.0.2):
 *  the plan of the panel's scope (`aiff_plan`, read again on a file change and on window focus while the panel shows
 *  it), and the batch it starts (job `aiff_batch`, progress BatchProgress), Stop, Resume and what came of it. One per
 *  window, outside any component, as UpgradeBatchFlow: the progress survives the Library picking another row or the
 *  page closing, and a page opened while a batch runs finds it (`adopt`). One track's Convert stays AiffFlow's. */
export class AiffBatchFlow {
  read = $state<AiffPlanRead | null>(null);
  view = $state<AiffRunView | null>(null);
  #reads = latestOnly();
  #off: (() => void) | null = null;
  /** track_id → name of the files the plans and the progress named, so the end can name a file that never had a
   *  progress row (a Resume, a batch found running, a song a selection left out) */
  #known = new Map<string, string>();

  know(names: Iterable<[string, string]>): void {
    for (const [id, name] of names) this.#known.set(id, name);
  }

  /** Reads the plan of `scope`. A new scope starts from placeholders, the same one keeps its plan on screen while it
   *  reads again; only the newest read's answer is kept. */
  async load(scope: AiffScope): Promise<void> {
    const key = scopeKey(scope);
    const ticket = this.#reads.next();
    const keep = this.read?.key === key ? this.read.plan : null;
    this.read = { key, phase: 'loading', plan: keep, message: '' };
    let r: Awaited<ReturnType<typeof api.aiff_plan>>;
    try {
      r = await api.aiff_plan(scope);
    } catch {
      r = { ok: false, kind: 'crashed', message: '' };
    }
    if (!this.#reads.isLatest(ticket)) return;
    if (r.ok) {
      this.know([...r.plan.items, ...r.plan.skipped].map((i): [string, string] => [i.track, i.name]));
      this.read = { key, phase: 'ready', plan: r.plan, message: '' };
    } else {
      this.read = { key, phase: 'error', plan: keep, message: r.message || problemCopy(r.kind).title };
    }
  }

  /** The panel's filled button: a selection's Convert (`convert`: each file's own answer, a Convert or its clean name;
   *  the songs the plan leaves out come back as skipped), Make all or the CDJ group's Convert all (`make_aiff`).
   *  `rows`: the plan's items as the running list shows them; `renames`: the plan has clean names only. */
  async start(scope: AiffScope, rows: RunRow[], renames: boolean, origin: 'library' | 'todo' = 'library'): Promise<void> {
    if (this.view?.phase === 'running') return; // a second press while one runs (the first call's listener must stay)
    this.know(rows.map((r): [string, string] => [r.track_id, r.name]));
    const call = () => (scope.kind === 'tracks' ? api.convert(scope.tracks, origin) : api.make_aiff(scope));
    await this.#run(scopeKey(scope), rows, renames, call);
  }
  /** Resume · k left: the stopped batch's planned files (their rows come with its progress). */
  async resume(batch_id: number): Promise<void> {
    if (this.view?.phase === 'running') return;
    await this.#run(null, [], false, () => api.batch_resume(batch_id));
  }
  /** Stop between files (the one in work finishes). */
  async stop(): Promise<void> {
    if (!this.view || this.view.phase !== 'running') return;
    this.view.stopping = true;
    const r = await api.stop();
    if (!r.ok && this.view) {
      this.view.stopping = false;
      toasts.show({ tone: 'problem', title: "Couldn't stop.", body: r.message || undefined });
    }
  }
  /** Done (or the next pick): the end is put away. A running batch stays. */
  clear(): void {
    if (this.view?.phase === 'ended') this.view = null;
  }
  /** A batch the hub runs that this window didn't start (it was reloaded): follow its progress. `aiff_batch` for
   *  several files (one file's job, `track_id` set, is its card's), and a `batch_resume` whose batch kind is a
   *  Convert's or a mixed one (`resumeIsAiff`); a resume of Same track's batch is UpgradeBatchFlow's. */
  adopt(job: JobSnap | null): void {
    if (!job?.running || job.track_id !== null || this.view?.phase === 'running') return;
    if (job.kind !== 'aiff_batch' && !(job.kind === 'batch_resume' && resumeIsAiff(job))) return;
    const last = job.last?.BatchProgress as { done: number; total: number; track_id: string | null; name: string | null } | undefined;
    this.view = { phase: 'running', scope: null, rows: last ? progressRows([], last) : [], done: last?.done ?? 0,
      total: last?.total ?? 0, now: last?.name ?? null, stopping: job.stopping, renames: false, end: null, again: null };
    this.#listen();
    void this.#follow(job.id);
  }
  /** Whether the panel of `scope` shows the batch: the one started for it, or a Resume or a batch found running. */
  covers(scope: AiffScope): boolean {
    const v = this.view;
    return !!v && (v.scope === null || v.scope === scopeKey(scope));
  }

  async #run(scope: string | null, rows: RunRow[], renames: boolean, call: () => Promise<JobStart>): Promise<void> {
    this.view = { phase: 'running', scope, rows, done: 0, total: rows.length, now: null, stopping: false, renames, end: null,
      again: null };
    this.#listen();
    const out = await runJob<AiffBatchResult>(call(), { quiet: true, success: false });
    this.#end(out, () => void this.#run(scope, rows.map((r) => ({ ...r, state: 'waiting', text: null })), renames, call));
  }
  async #follow(job_id: string): Promise<void> {
    const fin = await waitForJob(job_id);
    this.#end(fin.ok ? { ok: true, job_id, result: fin.result as AiffBatchResult }
      : { ok: false, job_id, kind: fin.problem ?? 'crashed', message: fin.message, result: (fin.result ?? null) as AiffBatchResult | null }, null);
  }
  #end(out: JobOutcome<AiffBatchResult>, again: (() => void) | null): void {
    this.#off?.();
    this.#off = null;
    // the mode only picks stage B's upgrade words, which the AIFF panel doesn't use (aiffBatchModel has its own)
    const end = batchEnd('swap', out);
    // refused before it started (busy, console, a sync running): nothing ran, the plan stays and a toast says why
    if (!out.ok && out.job_id === null) {
      this.view = null;
      toasts.show({ tone: 'problem', title: problemCopy(out.kind).title, body: out.message || undefined });
      return;
    }
    const v = this.view;
    const rows = endRows(v?.rows ?? [], out.result?.results ?? [], (id) => this.#known.get(id) ?? null);
    this.view = { phase: 'ended', scope: v?.scope ?? null, rows, done: end.done, total: end.total || rows.length, now: null,
      stopping: false, renames: v?.renames ?? false, end, again: canTryAgain(end) ? again : null };
  }
  #listen(): void {
    this.#off?.();
    this.#off = onEvent((e) => {
      if (e.type !== 'BatchProgress' || this.view?.phase !== 'running') return;
      const v = this.view;
      v.rows = progressRows(v.rows, e);
      v.done = e.done;
      v.total = e.total;
      v.now = e.name;
      if (e.track_id && e.name) this.#known.set(e.track_id, e.name);
    });
  }
}
/** The window's one AIFF batch flow. */
export const aiffBatch = new AiffBatchFlow();
