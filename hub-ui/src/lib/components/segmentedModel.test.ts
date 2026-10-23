import { describe, expect, it } from 'vitest';
import { isTight, splitOptions, tabStop } from './segmentedModel';
const o = (k: string) => ({ key: k, label: k.toUpperCase() });
const eight = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'].map(o);
describe('segmented overflow', () => {
  it('shows six and puts the rest in More', () => {
    const r = splitOptions(eight, 'a');
    expect(r.shown.map((x) => x.key)).toEqual(['a', 'b', 'c', 'd', 'e', 'f']);
    expect(r.more.map((x) => x.key)).toEqual(['g', 'h']);
  });
  it('keeps the selected option visible', () => {
    const r = splitOptions(eight, 'h');
    expect(r.shown.map((x) => x.key)).toEqual(['a', 'b', 'c', 'd', 'e', 'h']);
    expect(r.more.map((x) => x.key)).toEqual(['f', 'g']);
  });
  it('has no More with six or fewer', () => expect(splitOptions(eight.slice(0, 4), 'b').more).toEqual([]));
});

describe('segmented overflow edges', () => {
  it('does not change the options passed in', () => {
    const copy = eight.map((x) => ({ ...x }));
    splitOptions(eight, 'h');
    expect(eight).toEqual(copy);
  });
  it('keeps a chosen option already on the strip where it is', () => {
    const r = splitOptions(eight, 'c');
    expect(r.shown.map((x) => x.key)).toEqual(['a', 'b', 'c', 'd', 'e', 'f']);
  });
  it('honours a smaller max', () => {
    const r = splitOptions(eight, 'g', 3);
    expect(r.shown.map((x) => x.key)).toEqual(['a', 'b', 'g']);
    expect(r.more.map((x) => x.key)).toEqual(['c', 'd', 'e', 'f', 'h']);
  });
  it('shows exactly six without a More', () => expect(splitOptions(eight.slice(0, 6), 'f').more).toEqual([]));
});

describe('segmented with a value that matches no option', () => {
  it('still splits by order', () => {
    const r = splitOptions(eight, 'zz' as string);
    expect(r.shown.map((x) => x.key)).toEqual(['a', 'b', 'c', 'd', 'e', 'f']);
    expect(r.more.map((x) => x.key)).toEqual(['g', 'h']);
  });
  it('makes the first segment the Tab stop', () => expect(tabStop(eight.slice(0, 6), 'custom')).toBe('a'));
  it('makes the chosen segment the Tab stop', () => expect(tabStop(eight.slice(0, 6), 'c')).toBe('c'));
  it('has no Tab stop without options', () => expect(tabStop([], 'a')).toBeNull());
});

describe('isTight', () => {
  it('is tight when the labels at full width need more than the strip has', () => {
    expect(isTight([178, 120, 87], 258)).toBe(true);
  });
  it('is not tight when they fit, also exactly, and allows a sub-pixel of rounding', () => {
    expect(isTight([60, 60, 60, 60], 470)).toBe(false);
    expect(isTight([100, 100], 200)).toBe(false);
    expect(isTight([100.3, 100.3], 200)).toBe(false);
  });
  it('is not tight without segments or before the strip has a width', () => {
    expect(isTight([], 300)).toBe(false);
    expect(isTight([80, 90], 0)).toBe(false);
  });
});
