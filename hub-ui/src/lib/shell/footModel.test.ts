import { describe, expect, it } from 'vitest';
import type { PlayerState } from '../stores/player';
import { goTo, makeQueue, setShuffle, type QueueItem } from '../stores/queueModel';
import { footPlayer, footShape, playerKey, rowShown, type KeyTarget } from './footModel';

const item = (n: number): QueueItem => ({ track_id: `t${n}`, title: `Title ${n}`, artist: `Artist ${n}`, cover_url: null,
  duration_s: 150 });
const source = { label: 'All tracks', href: '#/library' };
const queue = (n: number, at = 0) => goTo(makeQueue(Array.from({ length: n }, (_, i) => item(i)), 0, source), at);
const state = (o: Partial<PlayerState> = {}): PlayerState => ({ url: 'blob:a', title: 'Artist 0 – Title 0', track_id: 't0',
  playing: true, loading: false, position_s: 72, duration_s: 150, error: null, queue: queue(3), hidden: false,
  ended: false, ...o });

describe('footPlayer', () => {
  it('is nothing without a queue: a single sound stays out of the frame', () => {
    expect(footPlayer(state({ queue: null }))).toBeNull();
  });
  it('playing: the track, "Artist · list", the times and the played part', () => {
    const f = footPlayer(state())!;
    expect([f.title, f.sub, f.play, f.pos, f.len, f.frac]).toEqual(['Title 0',
      { kind: 'source', text: 'Artist 0 · All tracks' }, 'playing', '1:12', '2:30', 0.48]);
    expect(f.tooltip).toBe('Artist 0 – Title 0 · All tracks');
    expect([f.canPrev, f.canNext, f.canShuffle, f.shuffle, f.seekable]).toEqual([true, true, true, false, true]);
  });
  it('links to the list with the track that plays now selected, not the one it started from', () => {
    expect(footPlayer(state({ queue: queue(3, 2) }))!.href).toBe('#/library?track=t2');
  });
  it('loading: no fill, the known length, no seeking yet', () => {
    const f = footPlayer(state({ url: null, loading: true, playing: false, position_s: 0, duration_s: null }))!;
    expect([f.play, f.frac, f.pos, f.len, f.seekable]).toEqual(['loading', null, '0:00', '2:30', false]);
  });
  it("can't play: says so on the second line, ▶ is off, ⏮ ⏭ still work", () => {
    const f = footPlayer(state({ error: "Can't play this file.", playing: false, url: null }))!;
    expect([f.sub.kind, f.sub.text, f.play, f.canPrev, f.canNext, f.seekable]).toEqual(['error',
      "Can't play this file.", 'error', true, true, false]);
  });
  it('the end of the list: "End of <list>", full line, ⏭ grey', () => {
    const f = footPlayer(state({ queue: queue(3, 2), ended: true, playing: false, position_s: 149.6 }))!;
    expect([f.sub.text, f.frac, f.pos, f.canNext, f.play]).toEqual(['End of All tracks', 1, '2:30', false, 'paused']);
  });
  it('a list of one: ⤮ ⏮ ⏭ grey', () => {
    const f = footPlayer(state({ queue: queue(1) }))!;
    expect([f.canPrev, f.canNext, f.canShuffle]).toEqual([false, false, false]);
  });
  it('shuffle on', () => {
    expect(footPlayer(state({ queue: setShuffle(queue(3), true, () => 0) }))!.shuffle).toBe(true);
  });
});

describe('footShape and the row', () => {
  it('the player part while a queue is up and shown, the sync beside it', () => {
    expect(footShape(state(), false)).toEqual({ player: true, sync: false });
    expect(footShape(state(), true)).toEqual({ player: true, sync: true });
  });
  it('hidden or stopped: only the sync, or no foot at all', () => {
    expect(footShape(state({ hidden: true }), true)).toEqual({ player: false, sync: true });
    expect(footShape(state({ hidden: true }), false)).toBeNull();
    expect(footShape(state({ queue: null }), false)).toBeNull();
  });
  it('the row only while hidden with a queue', () => {
    expect(rowShown(state({ hidden: true }))).toBe(true);
    expect(rowShown(state())).toBe(false);
    expect(rowShown(state({ queue: null, hidden: true }))).toBe(false);
  });
});

describe('playerKey', () => {
  const k = (key: string, o: Partial<{ metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean; repeat: boolean }> = {}) =>
    ({ key, metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, repeat: false, ...o });
  const el = (tag: string, o: Partial<NonNullable<KeyTarget>> = {}): KeyTarget => ({ tag, type: null, role: null, editable: false, ...o });
  it('Space plays/pauses, ⌘→ next, ⌘← previous', () => {
    expect(playerKey(k(' '), null, false)).toBe('toggle');
    expect(playerKey(k('ArrowRight', { metaKey: true }), null, false)).toBe('next');
    expect(playerKey(k('ArrowLeft', { metaKey: true }), el('DIV', { role: 'grid' }), false)).toBe('prev');
  });
  it('not in a field, a contenteditable, on a button or a slider, or with a dialog open', () => {
    for (const t of [el('INPUT', { type: 'search' }), el('TEXTAREA'), el('SELECT'), el('DIV', { editable: true }),
      el('BUTTON'), el('DIV', { role: 'slider' }), el('A', { role: 'button' })]) {
      expect(playerKey(k(' '), t, false)).toBeNull();
      expect(playerKey(k('ArrowRight', { metaKey: true }), t, false)).toBeNull();
    }
    expect(playerKey(k(' '), null, true)).toBeNull();
  });
  it('other keys, other modifiers and a held Space do nothing', () => {
    expect(playerKey(k('ArrowRight'), null, false)).toBeNull();
    expect(playerKey(k(' ', { shiftKey: true }), null, false)).toBeNull();
    expect(playerKey(k('ArrowRight', { metaKey: true, shiftKey: true }), null, false)).toBeNull();
    expect(playerKey(k(' ', { repeat: true }), null, false)).toBeNull();
    expect(playerKey(k('Enter'), null, false)).toBeNull();
  });
});
