import { describe, expect, it } from 'vitest';
import { stuckSide } from './stuckEdge';

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
