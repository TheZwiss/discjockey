// Sync's scope as a store (issue 36): the playlists switched off for the sync and the weekly checks switched off.
// The playlists switch in the browser column (the shell's chrome), the weekly checks in Sync's panel, and the plan
// reads both, so the scope lives here rather than in the page. Remembered (`sync.scope`, the key the page used
// before); a stored value is read through `readScope`, which drops anything that no longer has a switch.
// `planCounts`: what the plan holds per playlist (only the kinds switched on), published by Sync's plan while it
// shows one, so the column's switch can say it in its tooltip; null when no plan is on screen.
import { writable, type Writable } from 'svelte/store';
import { getPref, setPref } from '../prefs';
import { PREF_SCOPE, readScope, toggleScope, type Scope } from '../../pages/sync/planModel';

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

/** A playlist switched on or off for the sync (the browser column's switch). */
export const togglePlaylist = (name: string) => syncScope.update((s) => toggleScope(s, 'folders', name));

export const planCounts = writable<Record<string, number> | null>(null);
