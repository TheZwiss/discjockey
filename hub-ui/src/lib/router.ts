// Hash routes (plan 64.7). Pages get `params` and `query` as props.
import { readable, type Readable } from 'svelte/store';
import { NOT_IN_PLAYLIST, type Sidebar } from './bridge/types';

export type Route = { name: string; params: Record<string, string>; query: URLSearchParams; path: string };
type Pattern = { name: string; re: RegExp; keys: string[]; fixed?: Record<string, string> };

const P = (name: string, pattern: string, fixed?: Record<string, string>): Pattern => {
  const keys: string[] = [];
  const src = pattern.replace(/:(\w+)/g, (_, k) => { keys.push(k); return '([^/]+)'; });
  return { name, re: new RegExp(`^${src}/?$`), keys, fixed };
};
/** route → page key (pages/registry.ts) */
export const ROUTES: Pattern[] = [
  P('dashboard', '/'),
  P('runs', '/runs'),
  P('sync', '/sync'),
  P('sync', '/sync/run/:run_id'),
  P('todo', '/todo'),
  P('library', '/library'),
  P('library', '/library/playlist/:playlist'),
  P('library', '/library/folder/:folder'),
  P('library', '/library/not-in-playlist', { folder: NOT_IN_PLAYLIST }),
  P('playlists', '/playlists'),
  P('limits', '/limits'),
  P('limits', '/limits/:service'),
  P('limits', '/qobuz'),
  P('setup', '/setup'),
  P('setup', '/setup/:step'),
  P('settings', '/settings'),
  P('settings', '/settings/:row'),
  // Settings → Watched folders with one import folder picked (its crate switches; the path encoded whole)
  P('settings', '/settings/:row/:folder'),
  P('gallery', '/dev/gallery'),
];
export const SETUP_STEPS = ['music', 'existing', 'tools', 'spotify', 'downloads', 'playlists'];
/** Setup's retired steps (Qobuz and More sources became Downloads, spec settings-setup §8) → the step they are now. */
const RETIRED_SETUP_STEPS = new Map([['qobuz', 'downloads'], ['sources', 'downloads']]);
/** Settings' rows (`#/settings/<row>`), in the page's order. */
export const SETTINGS_ROWS = ['qobuz', 'youtube', 'soundcloud', 'spotify', 'youtube_music', 'music', 'folders', 'programs', 'about', 'reports'] as const;

/** "#/library/folder/Hard_Bounce?track=t2" → { name: 'library', params: { folder: 'Hard_Bounce' }, query } */
export function parseHash(hash: string): Route {
  const raw = (hash || '').replace(/^#/, '') || '/';
  const [p, q = ''] = raw.split('?');
  const path = p.startsWith('/') ? p : `/${p}`;
  const query = new URLSearchParams(q);
  for (const r of ROUTES) {
    const m = r.re.exec(path);
    if (!m) continue;
    const params: Record<string, string> = { ...(r.fixed ?? {}) };
    r.keys.forEach((k, i) => {
      try { params[k] = decodeURIComponent(m[i + 1]); } catch { params[k] = m[i + 1]; }
    });
    if (r.name === 'setup' && params.step) params.step = RETIRED_SETUP_STEPS.get(params.step) ?? params.step;
    if (r.name === 'setup' && params.step && !SETUP_STEPS.includes(params.step)) break;
    if (r.name === 'settings' && params.row && !(SETTINGS_ROWS as readonly string[]).includes(params.row)) break;
    if (r.name === 'settings' && params.folder !== undefined && params.row !== 'folders') break;
    return { name: r.name, params, query, path };
  }
  return { name: 'unknown', params: {}, query, path };
}

/** buildHash('/library/folder/:folder', { folder: 'Hard Bounce' }, { track: 't2' }) → "#/library/folder/Hard%20Bounce?track=t2" */
export function buildHash(pattern: string, params: Record<string, string> = {},
  query: Record<string, string | null | undefined> = {}): string {
  const path = pattern.replace(/:(\w+)/g, (_, k) => encodeURIComponent(params[k] ?? ''));
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== null && v !== undefined && v !== '') q.set(k, v);
  const qs = q.toString();
  return `#${path}${qs ? `?${qs}` : ''}`;
}
/** href('/todo?filter=weak') → '#/todo?filter=weak' */
export function href(path: string): string {
  return path.startsWith('#') ? path : `#${path.startsWith('/') ? path : `/${path}`}`;
}
/** What a library route shows (plan library stage 5 I5): every track, the tracks in no playlist, a playlist by its
 *  folder name (as playlists.txt spells it), or a folder by its path (`Library/<name>`, or an absolute path: an import
 *  folder or a crate). */
export type LibraryTarget = { kind: 'all' } | { kind: 'unlisted' } | { kind: 'playlist'; name: string }
  | { kind: 'folder'; path: string };
const isPath = (s: string) => s.startsWith('Library/') || s.startsWith('/');
/** The target of a library route's params. A `folder` param that is no path is a playlist's name: the links of
 *  before the playlist route (a player queue's href, a bookmark) keep working; `resolveTarget` turns one that names
 *  a Library folder no playlist uses into that folder once the sidebar is known. */
export function libraryTarget(params: Record<string, string | undefined>): LibraryTarget {
  if (params.playlist !== undefined) return { kind: 'playlist', name: params.playlist };
  const f = params.folder;
  if (f === undefined) return { kind: 'all' };
  if (f === NOT_IN_PLAYLIST) return { kind: 'unlisted' };
  return isPath(f) ? { kind: 'folder', path: f } : { kind: 'playlist', name: f };
}
const same = (a: string, b: string): boolean => a.normalize('NFC').toLowerCase() === b.normalize('NFC').toLowerCase();
/** A playlist target the sidebar doesn't list but names a Library folder of (an old link to a folder no playlist
 *  uses) → that folder; anything else as it is. Without the sidebar the target stays. */
export function resolveTarget(t: LibraryTarget, side: Pick<Sidebar, 'playlists' | 'library_folders'> | null): LibraryTarget {
  if (t.kind !== 'playlist' || !side || side.playlists.some((p) => same(p.name, t.name))) return t;
  const lib = side.library_folders.find((f) => same(f.name, t.name));
  return lib ? { kind: 'folder', path: lib.path } : t;
}
/** The library route of a target; `libraryTarget(parseHash(libraryHref(t)).params)` gives `t` back. */
export function libraryHref(t: LibraryTarget): string {
  if (t.kind === 'all') return '#/library';
  if (t.kind === 'unlisted') return '#/library/not-in-playlist';
  if (t.kind === 'playlist') return buildHash('/library/playlist/:playlist', { playlist: t.name });
  return buildHash('/library/folder/:folder', { folder: t.path });
}
/** A target as one string, for comparing two (the page's "the answer is for this route"): null for All tracks. */
export function targetKey(t: LibraryTarget): string | null {
  return t.kind === 'all' ? null : t.kind === 'unlisted' ? NOT_IN_PLAYLIST
    : t.kind === 'playlist' ? `playlist:${t.name}` : `folder:${t.path}`;
}
/** `targetKey` back to its target. */
export function keyTarget(k: string | null): LibraryTarget {
  if (k === null) return { kind: 'all' };
  if (k === NOT_IN_PLAYLIST) return { kind: 'unlisted' };
  return k.startsWith('playlist:') ? { kind: 'playlist', name: k.slice(9) } : { kind: 'folder', path: k.slice(7) };
}
/** Settings → Watched folders with an import folder picked, its crates' switches shown (Library's "Show some in the
 *  sidebar…" lands here). */
export function settingsFolderHref(path: string): string {
  return buildHash('/settings/:row/:folder', { row: 'folders', folder: path });
}

// ---------- leave guard ----------
type Guard = () => Promise<boolean> | boolean;
let guard: Guard | null = null;
/** Playlists uses it for unsaved changes. null removes it. */
export function setLeaveGuard(fn: Guard | null): void {
  guard = fn;
}
async function allowed(): Promise<boolean> {
  if (!guard) return true;
  try {
    return !!(await guard());
  } catch {
    return false;
  }
}

// ---------- the live route ----------
const hasWindow = () => typeof window !== 'undefined' && !!window.location;
let lastHash = hasWindow() ? window.location.hash : '';
let restoring = false;
const routeListeners = new Set<(r: Route) => void>();
const changeListeners = new Set<(r: Route) => void>();

function announce(): void {
  const r = parseHash(window.location.hash);
  for (const fn of changeListeners) fn(r);
  for (const fn of routeListeners) fn(r);
}

/** Navigates (asks the leave guard first). Resolves false when the guard kept the page. */
export async function go(path: string, opts: { replace?: boolean } = {}): Promise<boolean> {
  const target = href(path);
  if (!hasWindow()) return false;
  if (target === window.location.hash) return true;
  if (!(await allowed())) return false;
  guard = null;
  lastHash = target;
  if (opts.replace) window.history.replaceState(null, '', target);
  else window.history.pushState(null, '', target);
  announce();
  return true;
}

/** Back/forward or a typed hash: the guard can still keep the page (the old hash comes back). */
async function onHashChange(): Promise<void> {
  if (restoring) { restoring = false; return; }
  const target = window.location.hash;
  if (target === lastHash) return;
  if (!(await allowed())) {
    restoring = true;
    window.location.hash = lastHash;
    return;
  }
  guard = null;
  lastHash = target;
  announce();
}

/** Every route change (not the first). The shell uses it to call api.select(null) outside To-do. */
export function onRouteChange(fn: (r: Route) => void): () => void {
  changeListeners.add(fn);
  return () => changeListeners.delete(fn);
}

export const route: Readable<Route> = readable(parseHash(hasWindow() ? window.location.hash : ''), (set) => {
  if (!hasWindow()) return;
  const fn = (r: Route) => set(r);
  routeListeners.add(fn);
  set(parseHash(window.location.hash));
  const hc = () => void onHashChange();
  window.addEventListener('hashchange', hc);
  return () => { routeListeners.delete(fn); window.removeEventListener('hashchange', hc); };
});

/** use:link on an <a href="#/…">: navigates through go() (so the leave guard is asked). */
export function link(node: HTMLAnchorElement): { destroy(): void } {
  const click = (e: MouseEvent) => {
    const h = node.getAttribute('href') ?? '';
    if (!h.startsWith('#') || e.metaKey || e.ctrlKey || e.button !== 0) return;
    e.preventDefault();
    void go(h);
  };
  node.addEventListener('click', click);
  return { destroy: () => node.removeEventListener('click', click) };
}
