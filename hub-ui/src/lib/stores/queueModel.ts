// The play queue's rules (plan now-playing, Task 1): a snapshot of the list a preview started from, walked in
// `order`. Pure: no DOM, no timers; player.ts holds the one live queue and the sound.

export type QueueItem = { track_id: string; title: string; artist: string; cover_url: string | null;
  duration_s: number | null };
/** Where the queue came from: its name ("All tracks") and a link that selects the playing track. */
export type QueueSource = { label: string; href: string };
/** `order` holds indices into `items` in play order; `at` is the position in `order` of the current track. */
export type Queue = { items: QueueItem[]; order: number[]; at: number; shuffle: boolean; source: QueueSource };

/** ⏮ restarts the track when it has played longer than this (seconds). */
export const RESTART_AFTER_S = 3;

/** The list as it is, shuffle off, starting at `start` (an index into `items`; out of range is clamped). */
export function makeQueue(items: QueueItem[], start: number, source: QueueSource): Queue {
  const at = items.length ? Math.max(0, Math.min(items.length - 1, Math.trunc(start) || 0)) : 0;
  return { items, order: items.map((_, i) => i), at, shuffle: false, source };
}

export function current(q: Queue): QueueItem {
  return q.items[q.order[q.at]];
}

export function single(q: Queue): boolean {
  return q.items.length === 1;
}

/** The position in `order` that plays after the current track, or null at the end. */
export function nextIndex(q: Queue): number | null {
  return q.at + 1 < q.order.length ? q.at + 1 : null;
}

/** What ⏮ does: restart the track after its first 3 s (and always on the first track), else go one back. */
export function prevAction(q: Queue, position_s: number): { kind: 'restart' } | { kind: 'go'; at: number } {
  if (position_s > RESTART_AFTER_S || q.at === 0) return { kind: 'restart' };
  return { kind: 'go', at: q.at - 1 };
}

/** The same queue with `at` moved to a position in `order` (out of range is clamped). */
export function goTo(q: Queue, at: number): Queue {
  return { ...q, at: Math.max(0, Math.min(q.order.length - 1, at)) };
}

/**
 * On: the current track stays current, the tracks before it keep their place (they are not replayed) and the rest
 * is shuffled (Fisher-Yates; `rand` returns [0, 1) and is injectable for tests). Off: the list's own order again,
 * continuing from the current track. A queue of one has nothing to shuffle and is returned as it is.
 */
export function setShuffle(q: Queue, on: boolean, rand: () => number = Math.random): Queue {
  if (single(q) || q.shuffle === on) return q;
  if (!on) return { ...q, order: q.items.map((_, i) => i), at: q.order[q.at], shuffle: false };
  const rest = q.order.slice(q.at + 1);
  for (let i = rest.length - 1; i > 0; i--) {
    const j = Math.min(i, Math.floor(rand() * (i + 1)));
    [rest[i], rest[j]] = [rest[j], rest[i]];
  }
  return { ...q, order: [...q.order.slice(0, q.at + 1), ...rest], shuffle: true };
}

/**
 * The queue's snapshot of a list as it is shown (plan now-playing, Decisions): the rows that have a file, in their
 * order, cut down to what the queue needs. `start` is the place of `id` in it; null when that row has no file (or
 * isn't in the list), so there is nothing to start from.
 */
export function snapshot(rows: readonly (QueueItem & { path: string | null })[], id: string):
  { items: QueueItem[]; start: number } | null {
  const items = rows.filter((r) => r.path !== null).map(({ track_id, title, artist, cover_url, duration_s }) =>
    ({ track_id, title, artist, cover_url, duration_s }));
  const start = items.findIndex((r) => r.track_id === id);
  return start < 0 ? null : { items, start };
}
