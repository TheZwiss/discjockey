// Ticks (by the action's id), the run's selection and "Up next" (plan Task 65). Pure, so it is tested. The plan page's
// own logic is in planModel.ts.
import type { PlannedAction, PreviewAction, SyncPreview } from '$lib/bridge/types';

export const SECONDS_PER_DOWNLOAD = 70;   // views formula (spec §6.9)

/** A ticked action the sync was started with, for "Up next" and the time left during the run (gap G1). */
export type Picked = { kind: string; track_id: string; title: string; artist: string; folder: string;
  cover_url?: string | null };

/** Every action of the preview in the order the sync works through them (the backend's `run` index). */
export function allActions(p: SyncPreview | null): PreviewAction[] {
  if (!p) return [];
  return p.groups.flatMap((g) => g.actions).map((a, i) => ({ a, i }))
    .sort((x, y) => (x.a.run ?? x.i) - (y.a.run ?? y.i)).map((x) => x.a);
}

/**
 * Ticks for a new preview: an action that was there before keeps its tick, a new one comes ticked, one that
 * disappeared is dropped. `prev` null (first preview) → everything ticked.
 */
export function carryTicks(next: SyncPreview, prev: { ticked: Set<string>; known: Set<string> } | null): Set<string> {
  const out = new Set<string>();
  for (const a of allActions(next)) {
    const id = a.id;
    if (!prev || !prev.known.has(id) || prev.ticked.has(id)) out.add(id);
  }
  return out;
}

const downloads = (kind: string) => kind === 'acquire' || kind === 'upgrade';

/** The rows of the preview with these ids (what the sync was started with: `job_status().last_sync.args.selected`), in
 *  run order, for "Up next" while the run's own plan has not arrived. An id the preview no longer has is skipped. */
export function pickedOf(p: SyncPreview | null, ids: Iterable<string>): Picked[] {
  const want = new Set(ids);
  return allActions(p).filter((a) => want.has(a.id)).map((a) => ({ kind: a.kind,
    track_id: a.track_id, title: a.title, artist: a.artist, folder: a.folder, cover_url: a.cover_url }));
}

/** The run's actions not done yet and not the current one, in order. `done`: track ids with a result. */
export function upNext<T extends { track_id: string }>(plan: T[], done: Iterable<string>, current: string | null): T[] {
  const gone = new Set(done);
  if (current) gone.add(current);
  return plan.filter((a) => !gone.has(a.track_id));
}

/** Minutes left: 70 s × remaining acquire/upgrade actions (including the current one); null when unknown. */
export function minutesLeft(plan: (PlannedAction | Picked)[], done: Iterable<string>): number | null {
  if (!plan.length) return null;
  const gone = new Set(done);
  const n = plan.filter((a) => !gone.has(a.track_id) && downloads(a.kind)).length;
  return Math.ceil((n * SECONDS_PER_DOWNLOAD) / 60);
}
