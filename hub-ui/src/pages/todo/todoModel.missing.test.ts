// To-do's Missing files group (issue 43, plan §7.1, §7.2): the model's parts, with the fake bridge's scenario
// `missing_files` for the engine's shapes.
import { describe, expect, it } from 'vitest';
import type { Todo, TodoItem, TrackDetail } from '$lib/bridge/types';
import { createFakeBridge } from '$lib/bridge/fake/bridge';
import { missingAll, missingSet } from '$lib/bridge/fake/missingFiles';
import { rowAway } from '$lib/format';
import {
  MULTI_GROUPS, actionsFor, headerSub, itemKey, missingAllKeys, missingGroup, multiMissing, multiScope,
  rowDim, rowSub, selectFromTrack, segOptions,
} from './todoModel';

async function scene() {
  const f = createFakeBridge('missing_files');
  const ids = missingSet((f as any)._ctx.s)!;
  const todo = (await f.todo('all', false)) as Todo & { ok: true };
  const shown = (await f.todo('all', true)) as Todo & { ok: true };
  const detail = async (id: string) => ((await f.track(id)) as { ok: true; track: TrackDetail }).track;
  const item = (id: string) => shown.groups.find((g) => g.key === 'missing_file')!.items.find((i) => i.track_id === id)!;
  return { f, ids, todo, shown, detail, item };
}

describe('the group in the list', () => {
  it('Missing files comes second and several can be selected at once', async () => {
    const { todo, ids, item } = await scene();
    const keys = todo.groups.map((g) => g.key);
    expect(keys.indexOf('missing_file')).toBe(keys[0] === 'rekordbox_check' ? 1 : 0);
    expect(MULTI_GROUPS).toContain('missing_file');
    const scope = multiScope([item(ids.plain), item(ids.own)]);
    expect(scope(itemKey(item(ids.plain)))).toBe('missing_file');
  });
  it('a row says its file is missing in the quality slot, an offline drive wins, and its sub line is folder · detail', async () => {
    const { item, ids } = await scene();
    expect(rowAway(item(ids.plain))).toBe('file_missing');
    expect(rowAway(item(ids.ownOffline))).toBe('offline');
    expect(rowDim(item(ids.plain))).toBe(true);   // as every file that is away: dimmed, the tag says why it can't play
    const i = item(ids.plain);
    expect(rowSub(i)).toBe([i.folder, i.detail].filter(Boolean).join(' · '));
    expect(rowSub(i)).toContain('Missing since');
    expect(rowSub({ ...i, folder: '' })).toBe(i.detail);
  });
  it('the head link is the engine\'s words over the songs shown; Select all selects exactly those (the hidden one is left out)', async () => {
    const { todo, shown, ids } = await scene();
    const g = missingGroup(todo)!;
    expect(g.all!.label).toBe(`Select all · ${g.items.filter((i) => !i.hidden).length}`);
    expect(g.all!.label).toMatch(/^Select all · \d+$/);
    // the hidden song is in the shown answer only; the head's keys leave it out either way
    const gs = missingGroup(shown)!;
    expect(gs.items.some((i) => i.track_id === ids.hidden)).toBe(true);
    expect(missingAllKeys(gs)).toEqual(gs.items.filter((i) => i.track_id !== ids.hidden).map(itemKey));
    expect(gs.all!.label).toBe(g.all!.label);
    expect(missingAllKeys(null)).toEqual([]);
  });
  it('one song shown, or no group: the engine sends no label, so the page shows no head link', async () => {
    const { todo } = await scene();
    const items = missingGroup(todo)!.items;
    expect(missingGroup(null)).toBeNull();
    expect(missingAll(items.slice(0, 1)).all.label).toBeNull();
    expect(missingAll(items.slice(0, 2)).all.label).toBe('Select all · 2');
    expect(missingAll([]).all.label).toBeNull();
  });
  it('multiMissing: two or more items, all of the group', async () => {
    const { item, ids } = await scene();
    expect(multiMissing([item(ids.plain)])).toBe(false);
    expect(multiMissing([item(ids.plain), item(ids.own)])).toBe(true);
    expect(multiMissing([item(ids.plain), { ...item(ids.own), group: 'weak' } as TodoItem])).toBe(false);
  });
  it('the Library\'s link finds the item by its track', async () => {
    const { shown, ids } = await scene();
    const items = shown.groups.flatMap((g) => g.items);
    expect(selectFromTrack(items, ids.twice)).toBe(`missing_file/${ids.twice}`);
  });
  it('the page header counts the songs whose file is missing, and with only those it does not say "Nothing to do"', () => {
    const none = { all: 0, rekordbox_check: 0, missing_file: 0, same_song: 0, duplicate: 0, cdj: 0, upgrade_ready: 0, not_found: 0, weak: 0, good_lossy: 0, fake: 0, other: 0 };
    expect(headerSub({ chips: { ...none, missing_file: 1 }, check_tracks: 0 })).toEqual(['1 song is missing its file']);
    expect(headerSub({ chips: { ...none, missing_file: 3, weak: 2 }, check_tracks: 0 })).toEqual(['2 tracks are not lossless yet', '3 songs are missing their file']);
    expect(segOptions({ ...none, missing_file: 2 }, 'all').find((o) => o.key === 'missing_file')).toMatchObject({ label: 'Missing', count: 2 });
  });
});

describe('one item (actionsFor)', () => {
  it('a playlist song: Download again, the note, the bought file stays, no upgrade decision, no buy links', async () => {
    const { ids, detail } = await scene();
    const a = actionsFor(await detail(ids.parked), 'missing_file');
    expect(a.main).toBe('download_again');
    expect(a.missing!.foot).toMatchObject({ label: 'Download again', variant: 'filled', disabled: false });
    expect(a.missing!.note.title).toContain('Missing since');
    expect(a.dropZone).toBe(true);
    expect(a.upgrade).toBeNull();
    expect(a.buy).toBe(false);
    expect(a.hide).toBe('hide');
    expect(a.listen).toBe(true);   // as every file that is away: the player stays, switched off
  });
  it('an own song: Remove from library…, no drop zone', async () => {
    const { ids, detail } = await scene();
    const a = actionsFor(await detail(ids.ownParked), 'missing_file');
    expect(a.main).toBe('remove');
    expect(a.missing!.foot).toMatchObject({ label: 'Remove from library…', variant: 'danger' });
    expect(a.dropZone).toBe(false);
  });
  it('a song the action can\'t run for: the button disabled with the engine\'s reason as tip and hint', async () => {
    const { ids, detail } = await scene();
    const a = actionsFor(await detail(ids.twice), 'missing_file');
    expect(a.missing!.foot).toMatchObject({ disabled: true, tip: "Delete or move away the copies you don't want; the one left links again." });
    expect(a.missing!.foot.hint).toBeNull();   // the note above says it: a state is said once
    expect(a.missing!.note.text).toBe("Delete or move away the copies you don't want; the one left links again.");
  });
  it('a hidden song offers Unhide', async () => {
    const { ids, detail } = await scene();
    expect(actionsFor(await detail(ids.hidden), 'missing_file').hide).toBe('unhide');
  });
  it('the same song seen from another group keeps that group\'s actions and has no missing foot', async () => {
    const { ids, detail } = await scene();
    const a = actionsFor(await detail(ids.ownCheck), 'rekordbox_check');
    expect(a.missing).toBeNull();
    expect(a.main).toBe('rekordbox');
  });
});
