// confirm({title, body, confirmLabel, tone}) → Promise<boolean>, shown by ConfirmHost (mounted once in App.svelte).
import { writable, type Readable } from 'svelte/store';

export type ConfirmOptions = { title: string; body?: string; confirmLabel?: string; cancelLabel?: string;
  tone?: 'primary' | 'danger' };
type Pending = ConfirmOptions & { resolve: (ok: boolean) => void };
const pending = writable<Pending | null>(null);
export const confirmRequest: Readable<Pending | null> = { subscribe: pending.subscribe };

export function confirm(o: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    pending.update((p) => { p?.resolve(false); return { ...o, resolve }; });
  });
}
export function answerConfirm(ok: boolean): void {
  pending.update((p) => { p?.resolve(ok); return null; });
}
