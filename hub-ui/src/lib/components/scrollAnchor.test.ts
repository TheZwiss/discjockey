import { describe, expect, it } from 'vitest';
import { anchorIndex, anchorShift } from './scrollAnchor';

const rows = (tops: number[], h = 38) => tops.map((top) => ({ top, bottom: top + h }));

describe('scrollAnchor', () => {
  it('holds the first row whole on screen, past one cut by the top edge', () => {
    expect(anchorIndex(rows([-58, -20, 18, 56]))).toBe(2);
    expect(anchorIndex(rows([-38, 0, 38]))).toBe(1);
  });
  it('falls back to a row cut by the top edge when none is whole there, and to none in an empty list', () => {
    expect(anchorIndex(rows([-150, -20], 100))).toBe(1);
    expect(anchorIndex([])).toBe(-1);
  });
  it('moves the scroll by as much as the anchor moved', () => {
    expect(anchorShift(59, 18, 208)).toBe(190);
    expect(anchorShift(400, 18, -20)).toBe(-38);
  });
  it('leaves a list at its top, a gone anchor and a sub-pixel move alone', () => {
    expect(anchorShift(0, 18, 56)).toBe(0);
    expect(anchorShift(59, 18, null)).toBe(0);
    expect(anchorShift(59, null, 56)).toBe(0);
    expect(anchorShift(59, 18, 18.4)).toBe(0);
  });
});
