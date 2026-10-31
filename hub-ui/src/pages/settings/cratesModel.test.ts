import { describe, expect, it, vi } from 'vitest';
import type { Crate, WatchedFolderRow } from '$lib/bridge/types';
import { crateChanges, crateItems, crateSaves, pickedFolder, tooManyText, type CrateChange,
  type CrateSaveResult } from './cratesModel';

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
    const nfc = '/Volumes/Caf\u00e9/Sets';
    const nfd = '/Volumes/Cafe\u0301/Sets';
    expect(nfc).not.toBe(nfd);
    // the folder holds one form, the route the other, both ways
    expect(pickedFolder([lib, folder({ id: 4, path: nfc }), folder({ id: 6, path: '/Volumes/Other' })], nfd)?.id).toBe(4);
    expect(pickedFolder([lib, folder({ id: 4, path: nfd }), folder({ id: 6, path: '/Volumes/Other' })], nfc)?.id).toBe(4);
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
    .toBe('312 folders with music, too many for the sidebar: switch on some, or search, then use All.');
});

// the saves behind the switches: a fake store that answers when told, and the rows' pending state as the page sees it
describe('the saves', () => {
  type Call = { changes: CrateChange[]; answer: (r: CrateSaveResult) => void };
  const rig = (f = folder()) => {
    const calls: Call[] = [];
    const log: string[] = [];
    let pending: Record<string, boolean> = {};
    let current = f;
    const reload = vi.fn(async () => { log.push(`reload with ${JSON.stringify(pending)}`); });
    const failed = vi.fn();
    const save = crateSaves({
      folder: () => current,
      send: (changes) => new Promise<CrateSaveResult>((answer) => calls.push({ changes, answer })),
      reload, pending: (p) => { pending = p; }, failed,
    });
    const tick = () => new Promise((r) => setTimeout(r, 0));
    return { calls, log, save, reload, failed, tick, pending: () => pending, setFolder: (n: WatchedFolderRow) => { current = n; } };
  };
  const [BOUNCE, EDITS, HARD] = [`${W}/Bounce`, `${W}/Edits`, `${W}/Hardtechno/2019`];

  it('shows a click at once and sends it', async () => {
    const t = rig();
    const done = t.save([EDITS], true);
    expect(t.pending()).toEqual({ [EDITS]: true });
    await t.tick();
    expect(t.calls[0].changes).toEqual([{ path: EDITS, shown: null }]);
    t.calls[0].answer({ saved: [EDITS], failed: null });
    await done;
    expect(t.pending()).toEqual({});
    expect(t.reload).toHaveBeenCalledOnce();
    expect(t.failed).not.toHaveBeenCalled();
  });

  it('sends a later click only after the earlier one is answered', async () => {
    const t = rig();
    const a = t.save([EDITS], true);
    const b = t.save([BOUNCE], false);
    await t.tick();
    expect(t.calls).toHaveLength(1);
    t.calls[0].answer({ saved: [EDITS], failed: null });
    await a; await t.tick();
    expect(t.calls).toHaveLength(2);
    t.calls[1].answer({ saved: [BOUNCE], failed: null });
    await b;
    expect(t.pending()).toEqual({});
  });

  it('an older failed answer never takes back a later click', async () => {
    const t = rig();
    const a = t.save([EDITS], true);        // Edits on
    const b = t.save([EDITS], false);       // and off again, before the first is answered
    expect(t.pending()).toEqual({ [EDITS]: false });
    await t.tick();
    t.calls[0].answer({ saved: [], failed: { kind: 'busy' } });
    await a; await t.tick();
    expect(t.pending()).toEqual({ [EDITS]: false });   // the later click still shows
    expect(t.failed).toHaveBeenCalledOnce();
  });

  it('rapid on, off, on of one crate: the last click wins and each is stored in order', async () => {
    const t = rig();
    const all = [t.save([EDITS], true), t.save([EDITS], false), t.save([EDITS], true)];
    expect(t.pending()).toEqual({ [EDITS]: true });
    for (let i = 0; i < 3; i++) {
      await t.tick();
      expect(t.calls).toHaveLength(i + 1);
      t.calls[i].answer({ saved: t.calls[i].changes.map((c) => c.path), failed: null });
      // while a later click is waiting, the crate keeps its latest value
      if (i < 2) { await t.tick(); expect(t.pending()).toEqual({ [EDITS]: true }); }
    }
    await Promise.all(all);
    expect(t.calls.map((c) => c.changes[0].shown)).toEqual([null, false, null]);
    expect(t.pending()).toEqual({});
  });

  it('a busy after k of n leaves k stored and puts the other n - k back, before the reload', async () => {
    const t = rig();
    const done = t.save([BOUNCE, HARD], false);   // None: both on now
    expect(t.pending()).toEqual({ [BOUNCE]: false, [HARD]: false });
    await t.tick();
    t.calls[0].answer({ saved: [BOUNCE], failed: { kind: 'busy' } });
    await done;
    // at the reload the refused one is already back, the stored one still shows its new value
    expect(t.log).toEqual([`reload with ${JSON.stringify({ [BOUNCE]: false })}`]);
    expect(t.pending()).toEqual({});
    expect(t.failed).toHaveBeenCalledOnce();
  });

  it('a refusal with nothing stored puts everything back and reads nothing again', async () => {
    const t = rig();
    const done = t.save([BOUNCE, HARD], false);
    await t.tick();
    t.calls[0].answer({ saved: [], failed: { kind: 'busy' } });
    await done;
    expect(t.pending()).toEqual({});
    expect(t.reload).not.toHaveBeenCalled();
  });

  it('queues a second All · None while the first runs: stored in order, the last click shows', async () => {
    const t = rig();
    const keys = [BOUNCE, EDITS, HARD];
    const first = t.save(keys, true);      // All: only Edits changes
    const second = t.save(keys, false);    // None, straight after: all three change against what the rows show
    expect(t.pending()).toEqual({ [EDITS]: false, [BOUNCE]: false, [HARD]: false });
    await t.tick();
    expect(t.calls).toHaveLength(1);
    t.calls[0].answer({ saved: [EDITS], failed: null });
    await first; await t.tick();
    expect(t.pending()).toEqual({ [EDITS]: false, [BOUNCE]: false, [HARD]: false });
    expect(t.calls).toHaveLength(2);
    t.calls[1].answer({ saved: [BOUNCE, EDITS, HARD], failed: null });
    await second;
    expect(t.pending()).toEqual({});
  });

  it('does nothing for a click that changes nothing', async () => {
    const t = rig();
    await t.save([BOUNCE], true);
    expect(t.calls).toHaveLength(0);
  });
});
