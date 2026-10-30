import { describe, expect, it } from 'vitest';
import { tipClosed, tipGone, tipOpened, tipWarmth } from './tipRegistry';

describe('tipRegistry', () => {
  it('keeps one tip open: opening another closes the first', () => {
    const closed: string[] = [];
    const a = () => { closed.push('a'); tipClosed(a, 1_000); };
    const b = () => { closed.push('b'); tipClosed(b, 2_000); };
    tipOpened(a);
    expect(tipWarmth(b).otherOpen).toBe(true);
    expect(tipWarmth(a).otherOpen).toBe(false);
    tipOpened(b);
    expect(closed).toEqual(['a']);
    expect(tipWarmth(a)).toEqual({ otherOpen: true, lastClosedAt: 1_000 });
    tipClosed(b, 3_000);
    expect(tipWarmth(a)).toEqual({ otherOpen: false, lastClosedAt: 3_000 });
  });
  it('forgets a tip removed while open', () => {
    const a = () => {};
    const b = () => {};
    tipOpened(a);
    tipGone(a);
    expect(tipWarmth(b).otherOpen).toBe(false);
  });
});
