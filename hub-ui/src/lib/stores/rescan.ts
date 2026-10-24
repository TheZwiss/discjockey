// The window's triggers for rescan_library: once at start, then whenever the window comes back to the front after
// more than a minute (visibilitychange, or focus after blur). busy/console answers are ignored: a running sync
// scans by itself, and the next trigger tries again. No toast: the scan says nothing unless something changed.
import { api } from '../bridge/client';
import { shouldRescan } from './rescanModel';

type Listener = (e?: unknown) => void;
type Target = { addEventListener(type: string, fn: Listener): void; removeEventListener(type: string, fn: Listener): void };
type Doc = Target & { visibilityState: string };

/** Starts the watching and the first scan; returns the clean-up. `scan` is injected for tests. */
export function watchRescan(doc: Doc, win: Target, scan: () => unknown = () => api.rescan_library(),
  now: () => number = Date.now): () => void {
  let hiddenSince: number | null = null;
  const away = () => { hiddenSince ??= now(); };
  const back = () => {
    const was = hiddenSince;
    hiddenSince = null;
    if (shouldRescan(was, now())) void scan();
  };
  const onVisibility = () => (doc.visibilityState === 'hidden' ? away() : back());
  doc.addEventListener('visibilitychange', onVisibility);
  win.addEventListener('blur', away);
  win.addEventListener('focus', back);
  void scan();
  return () => {
    doc.removeEventListener('visibilitychange', onVisibility);
    win.removeEventListener('blur', away);
    win.removeEventListener('focus', back);
  };
}
