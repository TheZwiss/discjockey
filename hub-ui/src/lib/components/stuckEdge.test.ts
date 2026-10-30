import { describe, expect, it } from 'vitest';
import { naturalOffset, stuckSide } from './stuckEdge';

describe('stuckSide', () => {
  it('is not stuck where it sits anyway (sub-pixel rounding included)', () => {
    expect(stuckSide(100, 100)).toBeNull();
    expect(stuckSide(100.3, 100)).toBeNull();
  });
  it('is stuck at the top when the scroller pushed it down from its place', () => {
    expect(stuckSide(40, -120)).toBe('top');
  });
  it('is stuck at the foot when it was pulled up from a place below the scroller', () => {
    expect(stuckSide(560, 900)).toBe('bottom');
  });
});

describe('naturalOffset', () => {
  it('is right after the sibling before it, plus its own margin', () => {
    expect(naturalOffset(200, [], 4)).toBe(204);
  });
  it('counts the heads in between by their size, wherever they are stuck', () => {
    // a folded Playlists head (32 px, 4 px margin) right above Folders: Folders sits below it, not below its stuck rect
    expect(naturalOffset(200, [{ height: 32, margin: 4 }], 4)).toBe(240);
    expect(naturalOffset(200, [{ height: 32, margin: 4 }, { height: 28, margin: 0 }], 0)).toBe(264);
  });
  it('counts a flex parent\'s row gap before each head and before itself', () => {
    expect(naturalOffset(200, [], 10, 2)).toBe(212);
    expect(naturalOffset(200, [{ height: 28, margin: 10 }], 10, 2)).toBe(252);
    // the first child: no gap above it
    expect(naturalOffset(0, [], 0, 2, false)).toBe(0);
  });
});
