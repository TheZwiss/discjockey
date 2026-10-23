import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { buildHash, go, href, libraryHref, onRouteChange, parseHash, setLeaveGuard } from './router';
import { NOT_IN_PLAYLIST } from './bridge/types';

describe('parseHash', () => {
  it.each([
    ['', 'dashboard', {}],
    ['#/', 'dashboard', {}],
    ['#/runs', 'runs', {}],
    ['#/sync', 'sync', {}],
    ['#/sync/run/2026-10-16_132430', 'sync', { run_id: '2026-10-16_132430' }],
    ['#/todo?filter=weak&track=t2', 'todo', {}],
    ['#/library', 'library', {}],
    ['#/library/folder/Hard_Bounce', 'library', { folder: 'Hard_Bounce' }],
    ['#/library/folder/03%2006%202026', 'library', { folder: '03 06 2026' }],
    ['#/library/not-in-playlist?track=t9', 'library', { folder: NOT_IN_PLAYLIST }],
    ['#/playlists', 'playlists', {}],
    ['#/qobuz', 'limits', {}],
    ['#/limits', 'limits', {}],
    ['#/limits/youtube', 'limits', { service: 'youtube' }],
    ['#/setup', 'setup', {}],
    ['#/setup/downloads', 'setup', { step: 'downloads' }],
    ['#/setup/tools', 'setup', { step: 'tools' }],
    ['#/setup/music', 'setup', { step: 'music' }],
    ['#/settings/music', 'settings', { row: 'music' }],
    ['#/setup/playlists', 'setup', { step: 'playlists' }],
    ['#/setup/dock', 'unknown', {}],  // the retired Dock step
    // the retired Qobuz and More sources steps are the Downloads step now (old links, bookmarks)
    ['#/setup/qobuz', 'setup', { step: 'downloads' }],
    ['#/setup/sources', 'setup', { step: 'downloads' }],
    ['#/settings/youtube', 'settings', { row: 'youtube' }],
    ['#/settings/nonsense', 'unknown', {}],
    ['#/settings', 'settings', {}],
    ['#/dev/gallery', 'gallery', {}],
    ['#/setup/nonsense', 'unknown', {}],
    ['#/nowhere', 'unknown', {}],
  ])('%s → %s', (hash, name, params) => {
    const r = parseHash(hash);
    expect(r.name).toBe(name);
    expect(r.params).toEqual(params);
  });
  it('reads the query', () => {
    const r = parseHash('#/todo?filter=weak&track=t2');
    expect(r.query.get('filter')).toBe('weak');
    expect(r.query.get('track')).toBe('t2');
  });
});

describe('buildHash and href', () => {
  it('builds and round-trips', () => {
    const h = buildHash('/library/folder/:folder', { folder: 'Hard Bounce/x' }, { track: 't2', empty: '' });
    expect(h).toBe('#/library/folder/Hard%20Bounce%2Fx?track=t2');
    expect(parseHash(h).params.folder).toBe('Hard Bounce/x');
    expect(href('/todo')).toBe('#/todo');
    expect(href('todo')).toBe('#/todo');
    expect(href('#/x')).toBe('#/x');
    expect(libraryHref(null)).toBe('#/library');
    expect(libraryHref(NOT_IN_PLAYLIST)).toBe('#/library/not-in-playlist');
  });
});

describe('go and the leave guard', () => {
  beforeEach(() => {
    const loc = { hash: '#/' };
    (globalThis as any).window = {
      location: loc,
      history: { pushState: (_: unknown, __: string, h: string) => { loc.hash = h; },
        replaceState: (_: unknown, __: string, h: string) => { loc.hash = h; } },
      addEventListener() {}, removeEventListener() {},
    };
  });
  afterEach(() => { setLeaveGuard(null); delete (globalThis as any).window; });

  it('navigates and tells the listeners', async () => {
    const seen: string[] = [];
    const off = onRouteChange((r) => seen.push(r.name));
    expect(await go('/todo')).toBe(true);
    expect(window.location.hash).toBe('#/todo');
    expect(seen).toEqual(['todo']);
    off();
  });
  it('a guard that says no keeps the page; yes lets it go and is removed', async () => {
    setLeaveGuard(() => false);
    expect(await go('/qobuz')).toBe(false);
    expect(window.location.hash).toBe('#/');
    setLeaveGuard(async () => true);
    expect(await go('/qobuz')).toBe(true);
    expect(window.location.hash).toBe('#/qobuz');
    setLeaveGuard(() => { throw new Error('x'); });
    expect(await go('/sync')).toBe(false);
  });
});
