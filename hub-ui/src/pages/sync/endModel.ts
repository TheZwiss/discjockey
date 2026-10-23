// The end screen of a sync, and of a past run opened from the dashboard: header lines, the stat cards with the quality
// bar, the new files grouped by playlist folder, what needs the user and the other changes, all from run(run_id).
import type { ByQuality, Result, RunDetail, RunSummary } from '$lib/bridge/types';
import { minutesLong, plural, runWhen } from '$lib/format';
import { verdict } from './cardState';
import { isProblem } from './results';

/** As NEW_FILE_SECTIONS in views.py: a new file in the library. */
export const NEW_FILE_SECTIONS = new Set(['new_lossless', 'new_not_lossless', 'fake', 'redownloaded', 'bought',
  'replaced', 'added_new']);
/** Changes worth a row of their own; "checked" (nothing better yet) is only counted. */
export const OTHER_SECTIONS = new Set(['upgrade_ready', 'swapped', 'moved', 'adopted', 'rekordbox_check',
  'discarded', 'rejected', 'hidden', 'unhidden', 'dropped']);

export type FolderGroup = { folder: string; reveal: string; rows: Result[] };

/** One line in the end screen's notes list: what the stat cards can't count. `review` adds the To-do link. */
export type EndNote = { text: string; test: string; review?: boolean };

export type EndModel = {
  title: string; sub: string; stats: LastSyncStats; notes: EndNote[];
  needs: Result[]; added: FolderGroup[]; other: Result[]; syncRest: boolean;
};

export type LastSyncStats = { added: number; moved: number; needs: number; byQuality: ByQuality | null };

/**
 * A run's numbers as the end screen shows them: the new files (and their split by quality, null when there are
 * none), the tracks moved (by the sync or found again after a move by hand) and how many need the user. The Sync
 * page's up-to-date panel shows the last run with these, so its cards agree with the end screen its link opens.
 */
export function lastSyncStats(run: RunDetail): LastSyncStats {
  const all = Object.values(run.sections).flat();
  const added = all.filter((r) => NEW_FILE_SECTIONS.has(r.section) && !!r.track_id);
  let byQuality: ByQuality | null = null;
  if (added.length) {
    byQuality = { lossless: 0, good_lossy: 0, weak: 0, fake: 0, missing: 0 };
    for (const r of added) byQuality[verdict(r).quality ?? 'good_lossy'] += 1;
  }
  const moved = all.filter((r) => (r.section === 'moved' || r.section === 'adopted') && !!r.track_id).length;
  return { added: added.length, moved, needs: run.needs_you.length, byQuality };
}

/** The last run's details as the Sync page holds them: its numbers, or 'failed' when they couldn't be read. */
export type LastSyncDetail = { run_id: string; stats: LastSyncStats | 'failed' };

/**
 * What the up-to-date panel shows for the last sync (`last` undefined: the summary is still loading; null: no sync
 * has run). 'loading' until the details of *that* run have settled, so the cards draw once with their final numbers
 * and bar; a reply for an older run doesn't count. Only when the details failed does it fall back to the summary's
 * counts, without a bar: its lossy count can't be split by quality.
 */
export function lastSyncView(last: RunSummary | null | undefined, detail: LastSyncDetail | null): LastSyncStats | 'loading' | null {
  if (last === undefined) return 'loading';
  if (last === null) return null;
  if (detail?.run_id !== last.run_id) return 'loading';
  if (detail.stats !== 'failed') return detail.stats;
  return { added: last.counts.lossless + last.counts.lossy, moved: last.counts.moved, needs: last.counts.problems,
    byQuality: null };
}

/** A reply for run `reply.run_id` replaces what is held only while that run is still the last one (`lastId`). */
export function keepDetail(held: LastSyncDetail | null, reply: LastSyncDetail, lastId: string | undefined): LastSyncDetail | null {
  return reply.run_id === lastId ? reply : held;
}

/** A finished run's details don't change: load them once per run, and again only after a failure. */
export function needsDetail(held: LastSyncDetail | null, lastId: string): boolean {
  return held?.run_id !== lastId || held.stats === 'failed';
}

export function endTitle(exit_code: number | null | undefined): string {
  if (exit_code === 130) return 'Sync stopped';
  if (exit_code === 1) return 'Sync finished with some problems';
  return 'Sync finished';
}

const waiting = (n: number) => `${plural(n, 'track')} ${n === 1 ? 'waits' : 'wait'} for the next sync`;

/** The folders in playlists.txt order, the rest after them by name; in each, the tracks by artist and title. */
export function groupByFolder(rows: Result[], order: string[]): FolderGroup[] {
  const by = new Map<string, Result[]>();
  const name = (r: Result) => `${r.artist} - ${r.title}`;
  const sorted = [...rows].sort((a, b) => name(a).localeCompare(name(b)));
  for (const r of sorted) by.set(r.folder, [...(by.get(r.folder) ?? []), r]);
  const rank = (f: string) => { const i = order.indexOf(f); return i < 0 ? order.length : i; };
  return [...by.keys()].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
    .map((folder) => ({ folder, reveal: `Library/${folder}`, rows: by.get(folder)! }));
}

/**
 * The second line of a row in "Other changes": "from Bouncy" (moved), "found again after you moved it" (adopted), "no
 * longer in a playlist; the file stays" (dropped); else the verdict's line ("a better version waits for you" for a
 * ready upgrade, whether it is lossless or a ~256 kbps stream), else the result's note.
 */
export function otherDetail(r: Result): string {
  if (r.section === 'moved') {
    const from = /^from Library\/([^/]+)\//.exec(r.note)?.[1];
    return from ? `from ${from}` : '';
  }
  if (r.section === 'adopted') return 'found again after you moved it';
  if (r.section === 'dropped') return 'no longer in a playlist; the file stays';
  return verdict(r).line || r.note;
}

export function endModel(run: RunDetail, newSincePreview: number | null = null, now: Date | number = new Date()):
  EndModel {
  const when = runWhen(run.finished ?? run.started, now).replace(/^(Today|Yesterday)/, (m) => m.toLowerCase());
  const took = run.duration_s === null ? null : run.duration_s < 60 ? 'under a minute' : minutesLong(run.duration_s / 60);
  const all = Object.values(run.sections).flat();
  const inOrder = (keep: (r: Result) => boolean) => all.filter(keep);

  const added = inOrder((r) => NEW_FILE_SECTIONS.has(r.section) && !!r.track_id);
  const other = inOrder((r) => OTHER_SECTIONS.has(r.section) && !!r.track_id);
  const checked = run.sections.checked?.length ?? 0;
  const queued = run.queued ?? 0;
  const stoppedRun = run.exit_code === 130;

  const stats = lastSyncStats(run);
  // added, moved and need you are the stat cards; the notes say what they can't count, the stop first (it explains
  // the numbers), then what the user can act on, then what simply waits
  let stopped: string | null = null;
  if (stoppedRun) {
    const after = run.stopped_after !== null ? ` after ${plural(run.stopped_after, 'track')}` : '';
    stopped = `Stopped by you${after}. Nothing is half done; ${queued ? waiting(queued) : 'the next sync continues'}.`;
  }
  const notes: (EndNote | null)[] = [
    stopped ? { text: stopped, test: 'sync-stopped-line' } : null,
    run.upgrades_ready
      ? { text: `${plural(run.upgrades_ready, 'upgrade')} ready to review`, test: 'sync-upgrades', review: true } : null,
    newSincePreview
      ? { text: `${newSincePreview} new since the check, ${newSincePreview === 1 ? 'it waits' : 'they wait'} for the next sync`,
        test: 'sync-new-since' } : null,
    checked ? { text: `${plural(checked, 'track')} checked, nothing better yet`, test: 'sync-checked' } : null,
    !stoppedRun && queued ? { text: waiting(queued), test: 'sync-waits' } : null,
  ];
  return {
    title: endTitle(run.exit_code), sub: took ? `${when} · took ${took}` : when, stats,
    notes: notes.filter((x): x is EndNote => !!x),
    needs: run.needs_you.filter(isProblem), added: groupByFolder(added, run.folder_order ?? []), other,
    syncRest: stoppedRun && queued > 0,
  };
}
