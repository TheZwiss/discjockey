// Ticks, the saved selection and "Up next" (plan Task 65). Pure, so it is tested. The plan page's own logic is in
// planModel.ts.
import type { ActionKey, PlannedAction, PreviewAction, SyncPreview } from '$lib/bridge/types';

export const PREF_LAST_SELECTION = 'sync.lastSelection';
export const SECONDS_PER_DOWNLOAD = 70;   // views formula (spec §6.9)

/** A stored ticked action, for "Up next" and the time left during the run (gap G1). */
export type Picked = { key: ActionKey; kind: string; track_id: string; title: string; artist: string; folder: string;
  cover_url?: string | null };

export const keyId = (k: ActionKey | readonly string[]) => JSON.stringify(k);
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
    const id = keyId(a.key);
    if (!prev || !prev.known.has(id) || prev.ticked.has(id)) out.add(id);
  }
  return out;
}

const downloads = (kind: string) => kind === 'acquire' || kind === 'upgrade';

/** The ticked actions in run order, saved at Start for "Up next" during the run. */
export function picked(p: SyncPreview, ticked: Set<string>): Picked[] {
  return allActions(p).filter((a) => ticked.has(keyId(a.key))).map((a) => ({ key: a.key, kind: a.kind,
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
