// What pressing a decision does, and its state while it runs, shared by To-do's and the Library's details so the same
// choice does the same thing on both pages (mockup todo-decisions). One flow per details panel: its cards (the choice,
// disabled while a job runs) and its foot (the buttons) read the same flow. Every action is a write job through
// runJob (its toast on a refusal); the finished job bumps filesVersion, and each page re-fetches what it shows.
import { api, runJob } from '$lib/bridge/client';
import type { DuplicatePair, RekordboxCheckView, Result } from '$lib/bridge/types';
import { confirm } from '$lib/components/confirm';
import { toasts } from '$lib/stores/toasts';
import { groupIdOf, type DuplicatePick, type Way } from './decisionModel';

/** The upgrade and the rekordbox check it leaves: Replace (the "In rekordbox" pick), Discard, Done, Undo. `busy`
 *  names the running action; a page may set it for one of its own (To-do's Hide), so the buttons wait for that too. */
export class UpgradeFlow {
  picked = $state<Way | null>(null);
  busy = $state<string | null>(null);
  /** an undo's refusal, kept under its button until the next track */
  undoProblem = $state<string | null>(null);
  #for = '';

  /** A new track starts over: Same track picked again where both ways are possible, no old refusal. */
  follow(track_id: string): void {
    if (track_id === this.#for) return;
    this.#for = track_id;
    this.picked = null;
    this.undoProblem = null;
  }
  /** The picked way: Same track (swap) by default where both ways are possible, else New track. */
  way(swap: boolean): Way {
    return swap ? (this.picked ?? 'swap') : 'add_new';
  }
  /** Replace with lossless (swap / add_new) or Discard (spec §6.6). A replace needs no confirm: it can be undone until
   *  Done (the hint under it says so); Discard deletes the new version, so it asks. "changed": runJob shows "This
   *  track changed in the meantime."; the finished job re-fetches the page. */
  async upgrade(track_id: string, mode: Way | 'discard'): Promise<void> {
    if (mode === 'discard' && !(await confirm({ title: 'Throw away the new version?',
      body: 'Your current file stays. This version is not offered again.', confirmLabel: 'Discard', tone: 'danger' }))) return;
    this.busy = mode;
    await runJob(api.upgrade(track_id, mode));
    this.busy = null;
  }
  /** "Done, checked in rekordbox". */
  async checked(track_id: string): Promise<void> {
    this.busy = 'rekordbox';
    await runJob(api.rekordbox_checked(track_id));
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
    const r = await runJob(api.undo_upgrade(track_id));
    this.busy = null;
    if (!r.ok) this.undoProblem = r.message;
  }
}

/** "Which file stays?": the pick (the app's recommendation until the user picks) and Keep. Keeping a file is
 *  "supersede" write jobs (D10: journaled, no undo), one per file that goes; after each, the group is the one of the
 *  files left (groupIdOf), so a group of three takes two jobs. Keep both / Keep all is one "answer" job. */
export class DuplicateFlow {
  chosen = $state<DuplicatePick | undefined>(undefined);
  busy = $state(false);
  #for = '';

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
    await runJob(api.keep_duplicates(g.group_id, g.files.map((f) => f.path)));
    this.busy = false;
  }
  async #keepOne(g: DuplicatePair, keep: number): Promise<void> {
    this.busy = true;
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
