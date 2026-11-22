// Sync's scope as a store (issues 36, 37, 39 V2.5b): the playlists and folders switched off for the sync and the weekly
// checks switched off. The collections switch in the browser column (the shell's chrome), the weekly checks in Sync's
// panel, and the plan reads both, so the scope lives here rather than in the page. It lives in settings.json
// (`sync_scope`), so the window and an agent's `sync scope` commands see one value: the store reads it with
// `sync_scope()` when the window starts and again when a job ends, and a switch sets the store at once and writes it
// with a `set_sync_scope` job (the engine takes one settings job at a time, so flips made while one runs are merged
// and sent when it ends: the last one wins, as a switch states the value it wants).
// `planCounts`: what the plan holds per collection (by target; only the kinds switched on), published by Sync's plan
// while it shows one, so the column's switch can say it in its tooltip; null when no plan is on screen.
import { writable, type Readable } from 'svelte/store';
import { api, runJob } from '../bridge/client';
import type { SyncScope } from '../bridge/types';
import { latestOnly } from '../latest';
import { FULL_SCOPE, toggleScope, type Scope } from '../../pages/sync/planModel';
import { dataVersion } from './hub';

const kindItem = (k: string) => `kind:${k}`;
const same = (a: Scope, b: Scope) => a.off.join('\n') === b.off.join('\n') && a.kinds.join('\n') === b.kinds.join('\n');
const fromEngine = (r: SyncScope): Scope => ({ off: r.off.map((c) => c.target), kinds: r.weekly_off.map((k) => k.kind) });

/** An item (a collection target or `kind:<k>`) -> whether it is left out, for the flips not sent yet. */
let flips = new Map<string, boolean>();
let sending = false;      // a set_sync_scope job is in flight
let failed = false;       // a job of this burst was refused or failed: the engine's value is read again at its end
let epoch = 0;            // counts the switches made here: a read that started before the last one is out of date
let value: Scope = FULL_SCOPE;
const reads = latestOnly();

// the store is read from the engine while somebody watches it (the shell's column always does)
const w = writable<Scope>(FULL_SCOPE, () => dataVersion.subscribe(() => { void reload(); }));
const put = (v: Scope) => { if (!same(v, value)) { value = v; w.set(v); } };

/** The engine's scope into the store, unless a switch of ours is not sent or answered yet (its value is newer). */
async function reload(): Promise<void> {
  if (sending || flips.size) return;
  const ticket = reads.next(), at = epoch;
  const r = await api.sync_scope();
  if (!r.ok || !reads.isLatest(ticket) || at !== epoch || sending || flips.size) return;
  put(fromEngine(r));
}

/** Sends the flips one job at a time; a job's result is the scope as saved, so the last one settles the store. */
async function flush(): Promise<void> {
  if (sending) return;
  sending = true;
  try {
    while (flips.size) {
      const batch = [...flips];
      flips = new Map();
      const r = await runJob<SyncScope>(api.set_sync_scope(
        batch.filter(([, off]) => !off).map(([i]) => i), batch.filter(([, off]) => off).map(([i]) => i)), { success: false });
      if (!r.ok) failed = true;
      else if (!flips.size) put(fromEngine(r.result));
    }
  } finally {
    sending = false;
  }
  if (failed) {
    failed = false;
    await reload();     // a refused or failed write: what the engine has is what is on
  }
}

function change(next: Scope): void {
  if (same(next, value)) return;
  for (const t of next.off) if (!value.off.includes(t)) flips.set(t, true);
  for (const t of value.off) if (!next.off.includes(t)) flips.set(t, false);
  for (const k of next.kinds) if (!value.kinds.includes(k)) flips.set(kindItem(k), true);
  for (const k of value.kinds) if (!next.kinds.includes(k)) flips.set(kindItem(k), false);
  epoch++;
  put(next);
  void flush();
}

export const syncScope: Readable<Scope> & { set(v: Scope): void; update(fn: (v: Scope) => Scope): void } = {
  subscribe: w.subscribe,
  set: change,
  update: (fn) => change(fn(value)),
};

/** A playlist or folder (its target) switched on or off for the sync (the browser column's switch). */
export const toggleCollection = (target: string) => syncScope.update((s) => toggleScope(s, 'off', target));

export const planCounts = writable<Record<string, number> | null>(null);
