// Small UI preferences in localStorage (pywebview keeps them across restarts). Every access in try/catch;
// keys get the prefix "discjockey.". Never credentials.
import { writable, type Writable } from 'svelte/store';

export const PREFIX = 'discjockey.';

function storage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

export function getPref<T>(key: string, fallback: T): T {
  try {
    const raw = storage()?.getItem(PREFIX + key);
    if (raw === null || raw === undefined) return fallback;
    const v = JSON.parse(raw);
    return v === null || typeof v !== typeof fallback ? fallback : (v as T);
  } catch {
    return fallback;
  }
}

export function setPref<T>(key: string, value: T): void {
  try {
    storage()?.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    /* full or blocked: the preference is just not kept */
  }
}

/** A store that starts from the saved value and saves every change. */
export function persisted<T>(key: string, fallback: T): Writable<T> {
  const w = writable<T>(getPref(key, fallback));
  return {
    subscribe: w.subscribe,
    set(v) { setPref(key, v); w.set(v); },
    update(fn) { w.update((v) => { const n = fn(v); setPref(key, n); return n; }); },
  };
}
