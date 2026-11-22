import { describe, expect, it } from 'vitest';
import type { PreviewAction, SyncPreview } from '$lib/bridge/types';
import { carryTicks, minutesLeft, pickedOf, upNext } from './selection';

const act = (kind: string, id: string, folder = 'Hard_Bounce', place = 1): PreviewAction => ({
  id: `act:${kind}:${id}:${place}`, kind, reason: kind === 'acquire' ? 'new' : null, track_id: id, artist: `Artist ${id}`, title: `Title ${id}`,
  folder, to_dir: `Library/${folder}`, to_not_lossless: false, src: null, cover_url: null, in: [] });
const preview = (...actions: PreviewAction[]): SyncPreview => ({
  read_status: { read_at: null, minutes_ago: 0, problem: null, message: '', lines_changed: false, reading: false, offline: false, auto_read: true,
    problem_service: null, services: [] },
  waiting_answers: 0, deferred_checks: 0,
  counts: null, groups: [{ key: 'acquire:new', label: 'Download (new)', actions }], estimate: null, never: [], folders: [],
  in_playlists: null, ambiguous: [],
  dropped: [], notes: [], empty: null, collections: {}, auto_upgrade: null, read_id: 'read:1', plan_id: null, presets: [],
  default_how_many: null, search: null });
const ids = (s: Set<string>) => [...s].map((k) => k.split(':')[2]).sort();

describe('ticks across a new preview', () => {
  const first = preview(act('acquire', 'a'), act('acquire', 'b'), act('adopt_bought', 'c'));
  it('ticks everything the first time', () => {
    expect(ids(carryTicks(first, null))).toEqual(['a', 'b', 'c']);
  });
  it('keeps ticks by id, drops gone actions, ticks new ones', () => {
    const ticked = carryTicks(first, null);
    ticked.delete(first.groups[0].actions[1].id);   // untick b
    const known = new Set([...carryTicks(first, null)]);
    const next = preview(act('acquire', 'b'), act('adopt_bought', 'c'), act('acquire', 'd'));
    expect(ids(carryTicks(next, { ticked, known }))).toEqual(['c', 'd']);
  });
  it('treats the same track with another target as a new action', () => {
    const ticked = new Set<string>();
    const known = new Set(['act:adopt_bought:c:1']);
    const next = preview(act('adopt_bought', 'c', 'Bouncy', 2));
    expect(ids(carryTicks(next, { ticked, known }))).toEqual(['c']);
  });
});

describe('the songs a sync was started with', () => {
  const p = preview(act('acquire', 'a'), act('acquire', 'b'), act('adopt_bought', 'c'));
  it('names the rows of the given ids in the preview order', () => {
    const [a, , c] = p.groups[0].actions;
    expect(pickedOf(p, [c.id, a.id]).map((x) => x.track_id)).toEqual(['a', 'c']);
    expect(pickedOf(p, new Set([c.id])).map((x) => [x.kind, x.artist, x.title, x.folder])).toEqual([['adopt_bought', 'Artist c', 'Title c', 'Hard_Bounce']]);
  });
  it('skips an id the preview no longer has, and knows no preview', () => {
    expect(pickedOf(p, ['act:acquire:gone:1', 'act:acquire:b:1']).map((x) => x.track_id)).toEqual(['b']);
    expect(pickedOf(null, ['act:acquire:b:1'])).toEqual([]);
  });
  it('follows the run order, not the order of the ids', () => {
    const [a, b] = p.groups[0].actions;
    const q = preview({ ...a, run: 1 }, { ...b, run: 0 });
    expect(pickedOf(q, [a.id, b.id]).map((x) => x.track_id)).toEqual(['b', 'a']);
  });
});

describe('up next and time left', () => {
  const plan = ['a', 'b', 'c', 'd', 'e'].map((id, i) => ({ kind: i === 1 ? 'adopt_bought' : 'acquire', track_id: id,
    title: id, artist: id }));
  it('is the plan minus done and the current one', () => {
    expect(upNext(plan, ['a', 'b'], 'c').map((x) => x.track_id)).toEqual(['d', 'e']);
    expect(upNext(plan, [], null)).toHaveLength(5);
  });
  it('counts 70 s per download still to do', () => {
    expect(minutesLeft(plan, ['a'])).toBe(4);   // c, d, e (b is a bought file) → 210 s
    expect(minutesLeft([], [])).toBeNull();
  });
});
