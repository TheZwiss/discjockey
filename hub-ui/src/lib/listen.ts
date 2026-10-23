// Starting a list as the player's queue (plan now-playing): Library and To-do hand over the rows as shown; the
// snapshot (only rows with a file, in their order) is taken now and later filter changes don't touch it. Each item's
// file is asked for when it is about to play.
import { api } from './bridge/client';
import { player } from './stores/player';
import { snapshot, type QueueItem, type QueueSource } from './stores/queueModel';

async function fileOf(track_id: string): Promise<string | null> {
  const r = await api.track(track_id);
  return r.ok ? r.track.audio_url : null;
}

/** Plays `id` and then the rest of `rows`. False when that row has no file (nothing starts). */
export function listen(rows: readonly (QueueItem & { path: string | null })[], id: string, source: QueueSource): boolean {
  const s = snapshot(rows, id);
  if (!s) return false;
  player.playQueue({ items: s.items, start: s.start, source, resolve: fileOf });
  return true;
}
