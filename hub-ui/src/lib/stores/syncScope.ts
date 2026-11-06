// Sync's scope as a store (issues 36, 37): the playlists and folders switched off for the sync and the weekly checks
// switched off. The collections switch in the browser column (the shell's chrome), the weekly checks in Sync's panel,
// and the plan reads both, so the scope lives here rather than in the page. Remembered (`sync.scope`, the key the page
// used before); a stored value is read through `readScope`, which drops anything that no longer has a switch, and the
// playlists an older version stored by name become targets once the sidebar names them (`resolveLegacy`).
// `planCounts`: what the plan holds per collection (by target; only the kinds switched on), published by Sync's plan
// while it shows one, so the column's switch can say it in its tooltip; null when no plan is on screen.
import { get, writable, type Writable } from 'svelte/store';
import { getPref, setPref } from '../prefs';
import { PREF_SCOPE, readScope, resolveLegacy, toggleScope, type Scope } from '../../pages/sync/planModel';
import { hub } from './hub';

function scopeStore(): Writable<Scope> {
  const w = writable<Scope>(readScope(getPref<unknown>(PREF_SCOPE, {})));
  const save = (v: Scope) => { setPref(PREF_SCOPE, v); return v; };
  return {
    subscribe: w.subscribe,
    set: (v) => w.set(save(v)),
    update: (fn) => w.update((v) => save(fn(v))),
  };
}
export const syncScope = scopeStore();

// an older scope's playlist names, resolved as soon as the sidebar lists the playlists (once: then there are none)
hub.subscribe((h) => {
  const s = get(syncScope);
  if (h.sidebar && s.legacy?.length) syncScope.set(resolveLegacy(s, h.sidebar.playlists));
});

/** A playlist or folder (its target) switched on or off for the sync (the browser column's switch). */
export const toggleCollection = (target: string) => syncScope.update((s) => toggleScope(s, 'off', target));

export const planCounts = writable<Record<string, number> | null>(null);
