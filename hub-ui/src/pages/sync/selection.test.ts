import { describe, expect, it } from 'vitest';
import type { ActionKey, PreviewAction, SyncPreview } from '$lib/bridge/types';
import { carryTicks, keyId, minutesLeft, picked, upNext } from './selection';

const act = (kind: string, id: string, folder = 'Hard_Bounce'): PreviewAction => ({ key: [kind, id, `Library/${folder}`] as
  ActionKey, kind, reason: kind === 'acquire' ? 'new' : null, track_id: id, artist: `Artist ${id}`, title: `Title ${id}`,
  folder, from_folder: null, to_dir: `Library/${folder}`, to_not_lossless: false, src: null, cover_url: null });
const preview = (...actions: PreviewAction[]): SyncPreview => ({
  spotify: { read_at: null, minutes_ago: 0, problem: null, message: '', stale: false, reading: false, offline: false, auto_read: true },
  counts: null, groups: [{ key: 'acquire:new', label: 'Download (new)', actions }], estimate: null, never: [], folders: [],
  in_playlists: null, ambiguous: [],
  dropped: [], notes: [], empty: null });
const ids = (s: Set<string>) => [...s].map((k) => JSON.parse(k)[1]).sort();

describe('ticks across a new preview', () => {
  const first = preview(act('acquire', 'a'), act('acquire', 'b'), act('move', 'c'));
  it('ticks everything the first time', () => {
    expect(ids(carryTicks(first, null))).toEqual(['a', 'b', 'c']);
  });
  it('keeps ticks by key, drops gone actions, ticks new ones', () => {
    const ticked = carryTicks(first, null);
    ticked.delete(keyId(first.groups[0].actions[1].key));   // untick b
    const known = new Set([...carryTicks(first, null)]);
    const next = preview(act('acquire', 'b'), act('move', 'c'), act('acquire', 'd'));
    expect(ids(carryTicks(next, { ticked, known }))).toEqual(['c', 'd']);
  });
  it('treats the same track with another target as a new action', () => {
    const ticked = new Set<string>();
    const known = new Set([keyId(['move', 'c', 'Library/Hard_Bounce'])]);
    const next = preview(act('move', 'c', 'Bouncy'));
    expect(ids(carryTicks(next, { ticked, known }))).toEqual(['c']);
  });
});

describe('the saved selection', () => {
  it('keeps the ticked actions in the preview order', () => {
    const p = preview(act('acquire', 'a'), act('acquire', 'b'), act('move', 'c'));
    const t = new Set([keyId(p.groups[0].actions[2].key), keyId(p.groups[0].actions[0].key)]);
    expect(picked(p, t).map((x) => x.track_id)).toEqual(['a', 'c']);
  });
});

describe('up next and time left', () => {
  const plan = ['a', 'b', 'c', 'd', 'e'].map((id, i) => ({ kind: i === 1 ? 'move' : 'acquire', track_id: id,
    title: id, artist: id }));
  it('is the plan minus done and the current one', () => {
    expect(upNext(plan, ['a', 'b'], 'c').map((x) => x.track_id)).toEqual(['d', 'e']);
    expect(upNext(plan, [], null)).toHaveLength(5);
  });
  it('counts 70 s per download still to do', () => {
    expect(minutesLeft(plan, ['a'])).toBe(4);   // c, d, e (b is a move) → 210 s
    expect(minutesLeft([], [])).toBeNull();
  });
});
