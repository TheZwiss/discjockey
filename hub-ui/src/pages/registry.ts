// route → lazy page import (plan 64.7). Never edited by page agents: a page exports its component from index.ts.
import type { Component } from 'svelte';

export type PageProps = { params: Record<string, string>; query: URLSearchParams };
export type PageEntry = { key: string; load: () => Promise<Component<PageProps>>; chrome: 'app' | 'none' };
type Mod = { default: Component<PageProps>; [name: string]: unknown };
const pick = (m: Mod, name = 'default') => (m[name] ?? m.default) as Component<PageProps>;

export const PAGES: Record<string, PageEntry> = {
  dashboard: { key: 'dashboard', load: () => import('./dashboard/index').then((m) => pick(m)), chrome: 'app' },
  runs: { key: 'runs', load: () => import('./dashboard/index').then((m) => pick(m, 'RunsPage')), chrome: 'app' },
  sync: { key: 'sync', load: () => import('./sync/index').then((m) => pick(m)), chrome: 'app' },
  todo: { key: 'todo', load: () => import('./todo/index').then((m) => pick(m)), chrome: 'app' },
  library: { key: 'library', load: () => import('./library/index').then((m) => pick(m)), chrome: 'app' },
  playlists: { key: 'playlists', load: () => import('./playlists/index').then((m) => pick(m)), chrome: 'app' },
  limits: { key: 'limits', load: () => import('./limits/index').then((m) => pick(m)), chrome: 'app' },
  setup: { key: 'setup', load: () => import('./setup/index').then((m) => pick(m)), chrome: 'none' },
  settings: { key: 'settings', load: () => import('./settings/index').then((m) => pick(m)), chrome: 'app' },
  unknown: { key: 'unknown', load: () => import('./NotFound.svelte').then((m) => m.default as Component<PageProps>), chrome: 'app' },
};
if (import.meta.env.VITE_FAKE === '1') {
  PAGES.gallery = { key: 'gallery', load: () => import('$lib/dev/Gallery.svelte').then((m) => m.default as unknown as Component<PageProps>),
    chrome: 'app' };
}

export function pageFor(name: string): PageEntry {
  return PAGES[name] ?? PAGES.unknown;
}
