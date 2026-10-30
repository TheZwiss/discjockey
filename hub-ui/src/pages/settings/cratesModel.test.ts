import { describe, expect, it } from 'vitest';
import type { Crate, WatchedFolderRow } from '$lib/bridge/types';
import { crateChanges, crateItems, pickedFolder, tooManyText } from './cratesModel';

const W = '/Users/you/Music/Rekordbox Library';
const crate = (rel: string, over: Partial<Crate> = {}): Crate => ({ path: `${W}/${rel}`, label: rel.split('/').join(' › '),
  name: rel.split('/').pop()!, tip: ['Rekordbox Library', ...rel.split('/')].join(' › '), files: 4, hidden: false,
  has_crates: false, ...over });
const folder = (over: Partial<WatchedFolderRow> = {}): WatchedFolderRow => ({ id: 2, path: W, name: 'Rekordbox Library',
  kind: 'import', state: 'online', files: 30, waiting: 0, unreadable: 0,
  crates: [crate('Bounce'), crate('Edits', { hidden: true }), crate('Hardtechno/2019')], too_many: false, ...over });
const lib = folder({ id: 1, kind: 'library', name: 'Library', path: '/Users/you/Music/Discjockey/Library', crates: [] });
const albums = folder({ id: 3, path: '/Volumes/Example Drive/Albums', name: 'Albums', too_many: true,
  crates: [crate('Aphex/Night Tapes', { label: 'Night Tapes', hidden: true })] });

describe('the picked folder', () => {
  it("is the route's, matched as a path", () => {
    expect(pickedFolder([lib, folder(), albums], '/Volumes/Example Drive/Albums/')?.id).toBe(3);
    const nfd = folder({ id: 4, path: '/Volumes/Café/Sets' });
    expect(pickedFolder([lib, nfd], '/Volumes/Café/Sets')?.id).toBe(4);
  });
  it('else the first import folder with crates; none without crates', () => {
    expect(pickedFolder([lib, folder({ id: 5, crates: [] }), albums], undefined)?.id).toBe(3);
    expect(pickedFolder([lib, folder(), albums], '/Users/you/Gone')?.id).toBe(2);
    expect(pickedFolder([lib], '/Users/you/Music/Discjockey/Library')).toBeNull();
    expect(pickedFolder(null, undefined)).toBeNull();
  });
});

describe('the switch rows', () => {
  it('say each crate as the sidebar does, on while in the sidebar', () => {
    expect(crateItems(folder())).toEqual([
      { key: `${W}/Bounce`, label: 'Bounce', count: 4, on: true, tip: 'Rekordbox Library › Bounce', find: '' },
      { key: `${W}/Edits`, label: 'Edits', count: 4, on: false, tip: 'Rekordbox Library › Edits', find: '' },
      { key: `${W}/Hardtechno/2019`, label: 'Hardtechno › 2019', count: 4, on: true,
        tip: 'Rekordbox Library › Hardtechno › 2019', find: 'Hardtechno' },
    ]);
  });
  it('show a save under way at once', () => {
    expect(crateItems(folder(), { [`${W}/Edits`]: true, [`${W}/Bounce`]: false }).map((i) => i.on)).toEqual([false, true, true]);
  });
  it('find an album by the folder it sits in', () => expect(crateItems(albums)[0].find).toBe('Aphex'));
});

describe('what a switch saves', () => {
  it('only the crates that change, null where the default gives it', () => {
    const keys = [`${W}/Bounce`, `${W}/Edits`, `${W}/Hardtechno/2019`];
    expect(crateChanges(folder(), keys, true)).toEqual([{ path: `${W}/Edits`, shown: null }]);
    expect(crateChanges(folder(), keys, false)).toEqual([{ path: `${W}/Bounce`, shown: false },
      { path: `${W}/Hardtechno/2019`, shown: false }]);
    expect(crateChanges(folder(), keys, false, { [`${W}/Bounce`]: false })).toEqual([{ path: `${W}/Hardtechno/2019`, shown: false }]);
  });
  it('under a folder with too many crates, on is stored and off is the default', () => {
    const p = albums.crates[0].path;
    expect(crateChanges(albums, [p], true)).toEqual([{ path: p, shown: true }]);
    expect(crateChanges(albums, [p], false, { [p]: true })).toEqual([{ path: p, shown: null }]);
  });
  it('ignores keys that are no crate of the folder', () => expect(crateChanges(folder(), ['/elsewhere'], true)).toEqual([]));
});

it('the too-many note counts the crates', () => {
  expect(tooManyText({ crates: Array.from({ length: 312 }, (_, i) => crate(`A${i}`)) }))
    .toBe('312 folders with music, too many for the sidebar: switch on the ones you want to see.');
});
