// Toasts: bottom right above the activity bar; up to 3; info/success hide after 5 s, problems stay until closed.
import { writable, type Readable } from 'svelte/store';

export type ToastTone = 'info' | 'success' | 'problem';
export type ToastAction = { label: string; href?: string; onclick?: () => void };
export type Toast = { id: number; tone: ToastTone; title: string; body?: string; action?: ToastAction };

export const MAX_TOASTS = 3;
export const AUTO_HIDE_MS = 5000;

const list = writable<Toast[]>([]);
let next = 1;
const timers = new Map<number, ReturnType<typeof setTimeout>>();

function dismiss(id: number): void {
  const t = timers.get(id);
  if (t) clearTimeout(t);
  timers.delete(id);
  list.update((l) => l.filter((x) => x.id !== id));
}

function show(t: Omit<Toast, 'id'>): number {
  const id = next++;
  list.update((l) => {
    const all = [...l, { ...t, id }];
    while (all.length > MAX_TOASTS) {
      // drop the oldest one that hides by itself first, else the oldest
      const i = all.findIndex((x) => x.tone !== 'problem');
      const [gone] = all.splice(i >= 0 && i < all.length - 1 ? i : 0, 1);
      const timer = timers.get(gone.id);
      if (timer) clearTimeout(timer);
      timers.delete(gone.id);
    }
    return all;
  });
  if (t.tone !== 'problem') timers.set(id, setTimeout(() => dismiss(id), AUTO_HIDE_MS));
  return id;
}

function clear(): void {
  for (const t of timers.values()) clearTimeout(t);
  timers.clear();
  list.set([]);
}

export const toasts: Readable<Toast[]> & { show: typeof show; dismiss: typeof dismiss; clear: typeof clear } = {
  subscribe: list.subscribe, show, dismiss, clear,
};
