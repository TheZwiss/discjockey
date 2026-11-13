// What pressing a decision does, and its state while it runs, shared by To-do's and the Library's details so the same
// choice does the same thing on both pages (mockup todo-decisions). One flow per details panel: its cards (the choice,
// disabled while a job runs) and its foot (the buttons) read the same flow. Every action is a write job through
// runJob (its toast on a refusal); the finished job bumps filesVersion, and each page re-fetches what it shows.
import { api, rekordboxStatus, runJob, type JobOutcome } from '$lib/bridge/client';
import { onEvent } from '$lib/bridge/events';
import { waitForJob } from '$lib/stores/jobs';
import type {
  AiffBatchResult, AiffPlan, AiffScope, DuplicatePair, JobSnap, JobStart, RekordboxCheckView, RekordboxStatus, Result, TodoItem, UndoResult,
} from '$lib/bridge/types';
import { latestOnly } from '$lib/latest';
import { aiffProblem } from './aiffModel';
import { scopeKey } from './aiffBatchModel';
import { confirm } from '$lib/components/confirm';
import { toasts } from '$lib/stores/toasts';
import { problemCopy } from '$lib/copy';
import {
  batchEnd, canTryAgain, discardConfirm, endRows, groupIdOf, progressRows, runRow, undoManyConfirm, undoProblem, undoneToast, type BatchEnd,
  type BatchMode, type DuplicatePick, type RunRow, type UndoProblem, type UpgradeWays, type Way,
} from './decisionModel';

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
   *  track changed in the meantime."; the finished job re-fetches the page. */
  async upgrade(track_id: string, mode: Way | 'discard'): Promise<void> {
    if (mode === 'discard' && !(await confirm({ title: 'Throw away the new version?',
      body: 'Your current file stays. This version is not offered again.', confirmLabel: 'Discard', tone: 'danger' }))) return;
    this.busy = mode;
    this.#onact?.();
    await runJob(api.upgrade([track_id], mode));
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
    const swapped = check?.reason === 'swapped';
    if (!(await confirm({ title: 'Undo the replace?',
      body: swapped ? 'Your old audio goes back in the file. The new version waits in Upgrades ready again.'
        : 'Your old file goes back where it was. The new version waits in Upgrades ready again.',
      confirmLabel: 'Undo the replace' }))) return;
    this.busy = 'undo';
    this.undoProblem = null;
    this.#onact?.();
    const r = await runJob(api.undo_upgrade([track_id]));
    this.busy = null;
    if (!r.ok) this.undoProblem = r.message;
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
 *  "supersede" write jobs (D10: journaled, no undo), one per file that goes; after each, the group is the one of the
 *  files left (groupIdOf), so a group of three takes two jobs. Keep both / Keep all is one "answer" job. */
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
    let left = [...g.files];
    let last: Result | null = null;
    for (const f of g.files.filter((x) => x.file_id !== keep)) {
      const r = await runJob<{ result: Result }>(api.supersede_duplicate(groupIdOf(left.map((x) => x.file_id)), f.file_id,
        left.map((x) => x.path)), { success: false });
      if (!r.ok) break;
      last = r.result?.result ?? null;
      left = left.filter((x) => x !== f);
    }
    this.busy = false;
    const moved = g.files.length - left.length;
    if (moved === 1 && last?.note) toasts.show({ tone: 'success', title: last.note });
    else if (moved > 1) toasts.show({ tone: 'success', title: `Moved ${moved} files to Superseded/.` });
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
  /** "Undo all {n}" / "Undo {n}" (asks first), or a row's "Undo this one" (`one`: asks the single card's question). */
  async undo(track_ids: string[], one?: RekordboxCheckView): Promise<void> {
    if (!track_ids.length || this.busy) return;
    const ask = one ? undoOneConfirm(one) : undoManyConfirm(track_ids.length);
    if (!(await confirm(ask))) return;
    this.busy = one ? `undo:${track_ids[0]}` : 'undo';
    this.problem = null;
    this.#onact?.();
    const out = await runJob<UndoResult>(api.undo_upgrade(track_ids), { quiet: true, success: false });
    this.busy = null;
    this.problem = undoProblem(out);
    const n = out.result?.undone ?? 0;
    if (n) toasts.show({ tone: 'success', title: undoneToast(n) });
  }
}
/** The single card's undo question for one row of a batch card (UpgradeFlow.undo asks the same). */
function undoOneConfirm(c: RekordboxCheckView) {
  return { title: 'Undo the replace?', confirmLabel: 'Undo the replace',
    body: c.reason === 'swapped' ? 'Your old audio goes back in the file. The new version waits in Upgrades ready again.'
      : 'Your old file goes back where it was. The new version waits in Upgrades ready again.' };
}

/** The jobs the window's AIFF batch flow runs (its `batch_resume` too, a kind it shares with Same track), so the
 *  upgrade batch flow never takes one of them for its own when a page asks it to follow the hub's job. */
const aiffJobs = new Set<number>();

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
    const call = () => mode === 'swap' && all ? api.upgrade_all() : api.upgrade(ids, mode);
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
    if (!job?.running || job.track_id !== null || !BATCH_JOBS.includes(job.kind) || this.view?.phase === 'running'
      || aiffJobs.has(job.id)) return;
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
  async #follow(job_id: number): Promise<void> {
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
  /** A batch the hub runs that this window didn't start (it was reloaded): follow its progress. Only `aiff_batch` for
   *  several files: one file's job (`track_id` set) is its card's, and a `batch_resume` found running can't be told
   *  from Same track's, which UpgradeBatchFlow follows. */
  adopt(job: JobSnap | null): void {
    if (!job?.running || job.track_id !== null || job.kind !== 'aiff_batch' || this.view?.phase === 'running') return;
    aiffJobs.add(job.id);
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
    const start = call();
    void start.then((r) => { if (r?.ok) aiffJobs.add(r.job_id); }, () => {});
    const out = await runJob<AiffBatchResult>(start, { quiet: true, success: false });
    this.#end(out, () => void this.#run(scope, rows.map((r) => ({ ...r, state: 'waiting', text: null })), renames, call));
  }
  async #follow(job_id: number): Promise<void> {
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
