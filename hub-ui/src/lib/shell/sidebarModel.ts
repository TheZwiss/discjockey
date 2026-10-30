// What the sidebar's page rows say beyond their names (plan library stage 5, I7 and N11), in both forms: the rail's
// tooltips (the name, then the row's signal in words; the shortcut is the Tip's key cap), the count column of the full
// form and the rail's marks. Pure: Sidebar.svelte renders it.
import type { PageKey } from './keys';

export type NavSignals = {
  todo: number;
  /** the hub's own sync while it runs: which action of how many (total null while the playlists are read) */
  sync: { index: number; total: number | null; frac: number } | null;
  /** a set-up service has a warning sign not yet seen, or is paused today (`Sidebar.limits_warning`) */
  limitsWarning: boolean;
};

/** The rail's tooltip text of a page (its first line; `keys` is drawn as a cap after it). */
export function navTip(page: PageKey, label: string, s: NavSignals): string {
  if (page === 'todo' && s.todo > 0) return `${label} · ${s.todo} to look at`;
  if (page === 'sync' && s.sync) {
    return s.sync.total ? `${label} · syncing, ${s.sync.index} of ${s.sync.total}` : `${label} · reading playlists`;
  }
  if (page === 'limits' && s.limitsWarning) return `${label} · a warning sign to look at, or a service paused today`;
  return label;
}

/** The full form's count column: To-do's count, the running sync's "12/40". */
export function navCount(page: PageKey, s: NavSignals): string | null {
  if (page === 'todo' && s.todo > 0) return String(s.todo);
  if (page === 'sync' && s.sync?.total) return `${s.sync.index}/${s.sync.total}`;
  return null;
}

/** The rail's count pill on To-do's glyph: the count, held to two digits so the pill stays inside the rail (the
 *  tooltip has the whole number). */
export function railPill(todo: number): string | null {
  if (todo <= 0) return null;
  return todo > 99 ? '99+' : String(todo);
}
