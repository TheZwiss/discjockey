import { describe, expect, it } from 'vitest';
import {
  NONE, click, drop, escape, keep, move, only, selectAll, selectScope, single, type Selection,
} from './selectionModel';

// two scopes: u (multi) and c (multi); x keys take part in none
const order = ['c1', 'c2', 'u1', 'u2', 'u3', 'u4', 'x1'];
const scopeOf = (k: string) => (k.startsWith('x') ? null : k[0]);
const sel = (keys: string[], anchor: string | null = keys.at(-1) ?? null): Selection => ({ keys, anchor });

describe('selection: none, one, several, all', () => {
  it('none and one', () => {
    expect(only(NONE)).toBeNull();
    expect(only(single('u1'))).toBe('u1');
    expect(single(null)).toEqual(NONE);
    expect(only(sel(['u1', 'u2']))).toBeNull();
  });
  it('a plain click selects one, whatever was selected', () => {
    expect(click(sel(['u1', 'u2']), 'u3', {}, order, scopeOf)).toEqual(single('u3'));
    expect(click(NONE, 'c1', {}, order, scopeOf)).toEqual(single('c1'));
  });
  it('⌘-click toggles within the anchor\'s scope', () => {
    let s = click(single('u1'), 'u3', { meta: true }, order, scopeOf);
    expect(s).toEqual({ keys: ['u1', 'u3'], anchor: 'u3' });
    s = click(s, 'u1', { meta: true }, order, scopeOf);
    expect(s).toEqual({ keys: ['u3'], anchor: 'u3' });
    // taking the anchor out hands it to the last key picked before it
    s = click(sel(['u1', 'u2', 'u4'], 'u4'), 'u4', { meta: true }, order, scopeOf);
    expect(s).toEqual({ keys: ['u1', 'u2'], anchor: 'u2' });
  });
  it('⌘-click in another scope starts over; a key of no scope is a plain click', () => {
    expect(click(sel(['u1', 'u2']), 'c1', { meta: true }, order, scopeOf)).toEqual(single('c1'));
    expect(click(single('u1'), 'x1', { meta: true }, order, scopeOf)).toEqual(single('x1'));
    expect(click(single('x1'), 'u1', { shift: true }, order, scopeOf)).toEqual(single('u1'));
    expect(click(NONE, 'u2', { meta: true }, order, scopeOf)).toEqual(single('u2'));
  });
  it('⇧-click selects the range from the anchor in list order, both ways; the anchor stays', () => {
    expect(click(single('u1'), 'u3', { shift: true }, order, scopeOf)).toEqual({ keys: ['u1', 'u2', 'u3'], anchor: 'u1' });
    expect(click(single('u4'), 'u2', { shift: true }, order, scopeOf)).toEqual({ keys: ['u2', 'u3', 'u4'], anchor: 'u4' });
    // a range replaces the earlier range
    const s = click(single('u2'), 'u4', { shift: true }, order, scopeOf);
    expect(click(s, 'u3', { shift: true }, order, scopeOf)).toEqual({ keys: ['u2', 'u3'], anchor: 'u2' });
  });
  it('⇧-click stays inside the scope even when the order mixes scopes', () => {
    const mixed = ['u1', 'c1', 'u2', 'c2', 'u3'];
    expect(click(single('u1'), 'u3', { shift: true }, mixed, scopeOf).keys).toEqual(['u1', 'u2', 'u3']);
  });
  it('⌘A selects the anchor\'s whole scope; nothing for a key of no scope', () => {
    expect(selectAll(single('u2'), order, scopeOf)).toEqual({ keys: ['u1', 'u2', 'u3', 'u4'], anchor: 'u2' });
    expect(selectAll(single('x1'), order, scopeOf)).toEqual(single('x1'));
    expect(selectAll(NONE, order, scopeOf)).toEqual(NONE);
  });
  it('selects a whole scope with its first key the anchor (Upgrade all)', () => {
    expect(selectScope('u', order, scopeOf)).toEqual({ keys: ['u1', 'u2', 'u3', 'u4'], anchor: 'u1' });
    expect(selectScope('z', order, scopeOf)).toEqual(NONE);
  });
  it('Escape goes back to the anchor alone', () => {
    expect(escape(sel(['u1', 'u2', 'u3'], 'u2'))).toEqual(single('u2'));
    expect(escape(single('u1'))).toEqual(single('u1'));
  });
  it('↑ ↓ move one key from the anchor, ending a multi-selection', () => {
    expect(move(single('u1'), order, 1)).toEqual(single('u2'));
    expect(move(sel(['u1', 'u2', 'u3'], 'u3'), order, -1)).toEqual(single('u2'));
    expect(move(single('c1'), order, -1)).toEqual(single('c1'));
    expect(move(single('x1'), order, 1)).toEqual(single('x1'));
    expect(move(NONE, order, 1)).toEqual(single('c1'));
    expect(move(NONE, [], 1)).toEqual(NONE);
  });
  it('drops one key; the anchor moves to the last key left', () => {
    expect(drop(sel(['u1', 'u2', 'u3'], 'u3'), 'u3')).toEqual({ keys: ['u1', 'u2'], anchor: 'u2' });
    expect(drop(sel(['u1', 'u2'], 'u2'), 'u1')).toEqual({ keys: ['u2'], anchor: 'u2' });
    expect(drop(single('u1'), 'u9')).toEqual(single('u1'));
  });
});

describe('selection kept or pruned when items leave', () => {
  it('keeps the keys still listed and the anchor', () => {
    const after = ['c1', 'u1', 'u3', 'u4'];
    expect(keep(sel(['u1', 'u2', 'u3'], 'u1'), order, after)).toEqual({ keys: ['u1', 'u3'], anchor: 'u1' });
  });
  it('an anchor that left goes to the nearest selected key below, else above', () => {
    expect(keep(sel(['u1', 'u2', 'u4'], 'u2'), order, ['u1', 'u3', 'u4'])).toEqual({ keys: ['u1', 'u4'], anchor: 'u4' });
    expect(keep(sel(['u1', 'u4'], 'u4'), order, ['u1', 'u2'])).toEqual({ keys: ['u1'], anchor: 'u1' });
  });
  it('with no key left the fallback decides (default: the key now in the anchor\'s place)', () => {
    expect(keep(sel(['u2', 'u3'], 'u2'), order, ['c1', 'c2', 'u4'])).toEqual(single('u4'));
    expect(keep(sel(['u2'], 'u2'), order, [])).toEqual(NONE);
    expect(keep(sel(['u2'], 'u2'), order, ['c1'], () => 'c1')).toEqual(single('c1'));
    expect(keep(NONE, order, order, () => order[0])).toEqual(single('c1'));
  });
  it('an unchanged list keeps the selection as it is', () => {
    const s = sel(['u3', 'u1'], 'u1');
    expect(keep(s, order, order)).toEqual(s);
  });
});
