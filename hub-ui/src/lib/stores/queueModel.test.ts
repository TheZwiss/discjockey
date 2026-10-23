import { describe, expect, it } from 'vitest';
import { current, goTo, makeQueue, nextIndex, prevAction, setShuffle, single, type QueueItem } from './queueModel';

const source = { label: 'All tracks', href: '#/library' };
const item = (n: number): QueueItem => ({ track_id: `t${n}`, title: `Title ${n}`, artist: 'Artist', cover_url: null,
  duration_s: 200 });
const items = (n: number) => Array.from({ length: n }, (_, i) => item(i));
const ids = (q: { items: QueueItem[]; order: number[] }) => q.order.map((i) => q.items[i].track_id);

/** A rand() that walks a fixed list, so a shuffle is the same every run. */
const seq = (...xs: number[]) => { let i = 0; return () => xs[i++ % xs.length]; };

describe('makeQueue', () => {
  it('starts at the given item, in the list order, shuffle off', () => {
    const q = makeQueue(items(5), 2, source);
    expect(current(q).track_id).toBe('t2');
    expect(q.order).toEqual([0, 1, 2, 3, 4]);
    expect(q.shuffle).toBe(false);
    expect(q.source).toBe(source);
  });
  it('clamps a start outside the list', () => {
    expect(makeQueue(items(3), 9, source).at).toBe(2);
    expect(makeQueue(items(3), -4, source).at).toBe(0);
    expect(makeQueue(items(3), Number.NaN, source).at).toBe(0);
  });
});

describe('nextIndex', () => {
  it('walks the order and is null after the last', () => {
    let q = makeQueue(items(3), 0, source);
    const seen = [current(q).track_id];
    for (let n = nextIndex(q); n !== null; n = nextIndex(q)) { q = goTo(q, n); seen.push(current(q).track_id); }
    expect(seen).toEqual(['t0', 't1', 't2']);
    expect(nextIndex(q)).toBeNull();
  });
  it('follows a shuffled order, not the list', () => {
    const q = setShuffle(makeQueue(items(4), 0, source), true, seq(0, 0, 0));
    const n = nextIndex(q);
    expect(n).toBe(1);
    expect(current(goTo(q, n!)).track_id).toBe(q.items[q.order[1]].track_id);
  });
});

describe('prevAction', () => {
  const q = makeQueue(items(4), 2, source);
  it('restarts after the first 3 seconds', () => expect(prevAction(q, 3.5)).toEqual({ kind: 'restart' }));
  it('goes to the previous track within the first 3 seconds', () => {
    expect(prevAction(q, 3)).toEqual({ kind: 'go', at: 1 });
    expect(prevAction(q, 0)).toEqual({ kind: 'go', at: 1 });
  });
  it('always restarts on the first track', () => {
    const first = makeQueue(items(4), 0, source);
    expect(prevAction(first, 0)).toEqual({ kind: 'restart' });
    expect(prevAction(first, 90)).toEqual({ kind: 'restart' });
  });
});

describe('setShuffle', () => {
  it('keeps the current track, plays every track once and does not replay earlier ones', () => {
    const q = makeQueue(items(6), 2, source);
    const s = setShuffle(q, true, seq(0.1, 0.9, 0.5, 0.3));
    expect(s.shuffle).toBe(true);
    expect(current(s).track_id).toBe('t2');
    expect(s.at).toBe(2);
    expect(ids(s).slice(0, 3)).toEqual(['t0', 't1', 't2']);
    expect([...ids(s)].sort()).toEqual(['t0', 't1', 't2', 't3', 't4', 't5']);
    expect(ids(s).slice(3)).not.toEqual(['t3', 't4', 't5']);   // this rand does reorder the rest
  });
  it('is deterministic for the same rand and does not change the queue it was given', () => {
    const q = makeQueue(items(8), 0, source);
    const before = [...q.order];
    expect(setShuffle(q, true, seq(0.2, 0.7, 0.4)).order).toEqual(setShuffle(q, true, seq(0.2, 0.7, 0.4)).order);
    expect(q.order).toEqual(before);
    expect(q.shuffle).toBe(false);
  });
  it('survives a rand that returns 1 or more', () => {
    const s = setShuffle(makeQueue(items(5), 0, source), true, () => 1);
    expect([...ids(s)].sort()).toEqual(['t0', 't1', 't2', 't3', 't4']);
  });
  it('off again: the list order, at the same current track', () => {
    const on = goTo(setShuffle(makeQueue(items(6), 1, source), true, seq(0.9, 0.1, 0.6)), 3);
    const now = current(on);
    const off = setShuffle(on, false);
    expect(off.shuffle).toBe(false);
    expect(off.order).toEqual([0, 1, 2, 3, 4, 5]);
    expect(current(off)).toBe(now);
  });
  it('turning it on twice, or off when it is off, leaves the queue alone', () => {
    const q = makeQueue(items(5), 0, source);
    expect(setShuffle(q, false)).toBe(q);
    const s = setShuffle(q, true, seq(0.3));
    expect(setShuffle(s, true, seq(0.8))).toBe(s);
  });
  it('is a no-op for one item', () => {
    const q = makeQueue(items(1), 0, source);
    expect(single(q)).toBe(true);
    expect(setShuffle(q, true)).toBe(q);
    expect(setShuffle(q, true).shuffle).toBe(false);
  });
});

describe('single', () => {
  it('is true for one item only', () => {
    expect(single(makeQueue(items(1), 0, source))).toBe(true);
    expect(single(makeQueue(items(2), 0, source))).toBe(false);
  });
});

describe('goTo', () => {
  it('moves along the order and clamps', () => {
    const q = makeQueue(items(3), 0, source);
    expect(goTo(q, 2).at).toBe(2);
    expect(goTo(q, 7).at).toBe(2);
    expect(goTo(q, -1).at).toBe(0);
  });
});
