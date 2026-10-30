// The chrome's keys (plan library stage 5, D18; notes "Keyboard"): ⌘1–⌘6 the pages in the rail's order, ⌘, Settings,
// ⌘K Library with the filter focused, ⌘I Library's details inspector, ⌃⌘S fold the sidebar. One window-level handler
// (App.svelte) owns them. They clash with none of today's keys: Space and ⌘← ⌘→ stay the player's (`playerKey`,
// untouched), ⌘F stays SearchField's, ↑ ↓ Enter Esc belong to whatever has focus, and the native menu keeps ⌘H ⌥⌘H ⌘Q
// ⌃⌘F ⌘X ⌘C ⌘V ⌘A. Every one carries ⌘, so they work while a text field has focus too; never while a dialog is open,
// never repeated by a held key. Digits match `code` (Digit1…), so a keyboard layout whose digits need Shift (AZERTY)
// still reaches them; letters match `key`, as macOS menus do. Pure: the handler reads the result.
import type { NavIconName } from '../components';

export type PageKey = 'dashboard' | 'sync' | 'todo' | 'playlists' | 'limits' | 'library' | 'settings';
export type NavPage = { key: PageKey; href: string; icon: NavIconName; label: string; keys: string; also?: string[] };

/** The app's pages in the rail's order, with their shortcuts. Library's href is where it was left (`lastLibrary`). */
export const NAV: NavPage[] = [
  { key: 'dashboard', href: '#/', icon: 'dashboard', label: 'Dashboard', keys: '⌘1', also: ['runs'] },
  { key: 'sync', href: '#/sync', icon: 'sync', label: 'Sync', keys: '⌘2' },
  { key: 'todo', href: '#/todo', icon: 'todo', label: 'To-do', keys: '⌘3' },
  { key: 'playlists', href: '#/playlists', icon: 'playlists', label: 'Playlists', keys: '⌘4' },
  { key: 'limits', href: '#/limits', icon: 'limits', label: 'Download limits', keys: '⌘5' },
  { key: 'library', href: '#/library', icon: 'library', label: 'Library', keys: '⌘6' },
];
export const SETTINGS: NavPage = { key: 'settings', href: '#/settings', icon: 'settings', label: 'Settings', keys: '⌘,' };
export const FOLD_KEYS = '⌃⌘S';

export type ChromeKey = { kind: 'page'; page: PageKey } | { kind: 'filter' } | { kind: 'inspector' } | { kind: 'fold' };
export type KeyLike = { key: string; code: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean;
  repeat: boolean };

const DIGITS: Record<string, PageKey> = { Digit1: 'dashboard', Digit2: 'sync', Digit3: 'todo', Digit4: 'playlists',
  Digit5: 'limits', Digit6: 'library' };

/**
 * What a key press asks of the chrome, or null when it's none of its keys (then nothing is prevented). `onLibrary`:
 * ⌘I has a meaning only there.
 */
export function chromeKey(e: KeyLike, ctx: { dialogOpen: boolean; onLibrary: boolean }): ChromeKey | null {
  if (ctx.dialogOpen || !e.metaKey || e.altKey || e.shiftKey || e.repeat) return null;
  const k = e.key.toLowerCase();
  if (e.ctrlKey) return k === 's' ? { kind: 'fold' } : null;
  if (DIGITS[e.code]) return { kind: 'page', page: DIGITS[e.code] };
  if (k === ',') return { kind: 'page', page: 'settings' };
  if (k === 'k') return { kind: 'filter' };
  if (k === 'i') return ctx.onLibrary ? { kind: 'inspector' } : null;
  return null;
}
