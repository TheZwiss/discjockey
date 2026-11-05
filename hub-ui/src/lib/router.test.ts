import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { buildHash, go, href, keyTarget, libraryHref, libraryTarget, onRouteChange, parseHash, resolveTarget, setLeaveGuard,
  settingsFolderHref, targetKey, type LibraryTarget } from './router';
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
    ['#/settings/folders/%2FVolumes%2FExample%20Drive%2FAlbums', 'settings', { row: 'folders', folder: '/Volumes/Example Drive/Albums' }],
    ['#/settings/music/%2FUsers%2Fyou', 'unknown', {}],  // only Watched folders picks a folder
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
    expect(libraryHref({ kind: 'all' })).toBe('#/library');
    expect(libraryHref({ kind: 'unlisted' })).toBe('#/library/not-in-playlist');
  });
  it('gives every library target its own route and reads it back (I5)', () => {
    const names = ['Hard Bounce', '100% Vinyl', 'Caf\u0065\u0301 › Sets', 'Café', 'a/b'];
    const targets: LibraryTarget[] = [{ kind: 'all' }, { kind: 'unlisted' },
      ...names.map((name) => ({ kind: 'playlist' as const, name })),
      ...names.map((n) => ({ kind: 'folder' as const, path: `Library/${n}` })),
      { kind: 'folder', path: '/Volumes/Example Drive/Hard › 2019' }, { kind: 'folder', path: '/Users/you/Music/100% Vinyl' }];
    for (const t of targets) {
      const r = parseHash(`${libraryHref(t)}?track=t2`);
      expect(r.name).toBe('library');
      expect(libraryTarget(r.params)).toEqual(t);
      expect(keyTarget(targetKey(t))).toEqual(t);
    }
    expect(libraryHref({ kind: 'playlist', name: 'Hard Bounce' })).toBe('#/library/playlist/Hard%20Bounce');
    expect(libraryHref({ kind: 'folder', path: 'Library/Old Sets' })).toBe('#/library/folder/Library%2FOld%20Sets');
    // NFC and NFD spellings stay what they were: the engine folds them
    expect(libraryTarget(parseHash(libraryHref({ kind: 'playlist', name: 'Cafe\u0301' })).params)).toEqual(
      { kind: 'playlist', name: 'Cafe\u0301' });
  });
  it('reads an old folder link that names no path as a playlist, and the sidebar turns it into its Library folder', () => {
    expect(libraryTarget(parseHash('#/library/folder/Hard_Bounce').params)).toEqual({ kind: 'playlist', name: 'Hard_Bounce' });
    const side = { playlists: [{ name: 'Techno' }], library_folders: [{ name: 'Old Sets', path: 'Library/Old Sets' }] } as never;
    expect(resolveTarget({ kind: 'playlist', name: 'old sets' }, side)).toEqual({ kind: 'folder', path: 'Library/Old Sets' });
    expect(resolveTarget({ kind: 'playlist', name: 'techno' }, side)).toEqual({ kind: 'playlist', name: 'techno' });
    expect(resolveTarget({ kind: 'playlist', name: 'Gone' }, side)).toEqual({ kind: 'playlist', name: 'Gone' });
    expect(resolveTarget({ kind: 'playlist', name: 'Old Sets' }, null)).toEqual({ kind: 'playlist', name: 'Old Sets' });
  });
  it('round-trips a watched folder for Settings, whatever its path holds', () => {
    for (const path of ['/Volumes/Example Drive/Albums', '/Users/you/Music/100% Vinyl', '/Users/you/Music/Caf\u0065\u0301 › Sets']) {
      const r = parseHash(settingsFolderHref(path));
      expect(r.name).toBe('settings');
      expect(r.params).toEqual({ row: 'folders', folder: path });
    }
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
