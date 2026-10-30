import { describe, expect, it } from 'vitest';
import { allDisabled, filterItems, groupSummary, growSpare, SEARCH_FROM, setOn, visibleKeys } from './toggleModel';
const items = [
  { key: 'a', label: 'Ohne_Quatsch', count: 41, on: true },
  { key: 'b', label: 'Kölsch Mix', count: 3, on: false },
  { key: 'c', label: 'Tekke_Ecke', count: 9, on: true },
];
describe('toggle groups', () => {
  it('says how many are on', () => expect(groupSummary(items)).toBe('2 of 3 on'));
  it('says "all on" plainly too', () => expect(groupSummary(items.map((i) => ({ ...i, on: true })))).toBe('3 of 3 on'));
  it('finds without accents or case', () => expect(filterItems(items, 'kolsch').map((i) => i.key)).toEqual(['b']));
  it('returns everything for an empty query', () => expect(filterItems(items, '  ')).toHaveLength(3));
  it('finds a row by its extra words too', () => {
    const albums = [{ key: 'x', label: 'Night Tapes', on: false, find: 'Aphex' }, { key: 'y', label: 'Aphex Mix', on: false },
      { key: 'z', label: 'Dawn', on: false }];
    expect(filterItems(albums, 'aphex').map((i) => i.key)).toEqual(['x', 'y']);
  });
  it('searches from seven rows', () => expect(SEARCH_FROM).toBe(7));
});

describe('toggle group edges', () => {
  it('counts an empty group', () => expect(groupSummary([])).toBe('0 of 0 on'));
  it('says none are on', () => expect(groupSummary(items.map((i) => ({ ...i, on: false })))).toBe('0 of 3 on'));
  it('finds with accents in the query', () => expect(filterItems(items, 'KÖL').map((i) => i.key)).toEqual(['b']));
  it('finds nothing for a missing name', () => expect(filterItems(items, 'zzz')).toEqual([]));
});

describe('All · None with a search', () => {
  it('acts on the rows the search shows', () => expect(visibleKeys(items, 'tekke')).toEqual(['c']));
  it('acts on every row without a search', () => expect(visibleKeys(items, '')).toEqual(['a', 'b', 'c']));
  // rows outside the given keys hold the opposite of the target value, so flipping them would fail the test
  const mixed = [
    { key: 'a', label: 'Ohne_Quatsch', on: true },
    { key: 'b', label: 'Kölsch Mix', on: false },
    { key: 'c', label: 'Tekke_Ecke', on: true },
    { key: 'd', label: 'Kölsch Deep', on: false },
  ];
  it('switches only the given rows', () =>
    expect(setOn(mixed, ['a'], false).map((i) => [i.key, i.on])).toEqual([['a', false], ['b', false], ['c', true], ['d', false]]));
  it('leaves rows outside the search alone', () =>
    expect(setOn(mixed, visibleKeys(mixed, 'kolsch'), true).map((i) => [i.key, i.on]))
      .toEqual([['a', true], ['b', true], ['c', true], ['d', true]]));
  it('None with a search keeps the hidden rows on', () =>
    expect(setOn(mixed, visibleKeys(mixed, 'kolsch'), false).map((i) => [i.key, i.on]))
      .toEqual([['a', true], ['b', false], ['c', true], ['d', false]]));
  it('All with a search keeps the hidden rows off', () =>
    expect(setOn(mixed, visibleKeys(mixed, 'ohne'), true).map((i) => [i.key, i.on]))
      .toEqual([['a', true], ['b', false], ['c', true], ['d', false]]));
  it('does not change the items passed in', () => { setOn(items, ['a'], false); expect(items[0].on).toBe(true); });
});

// a grow group's cut (spec §11, issue 10): real WebKit sizes, rows 38 px + 1 px rule, head 40 + rule + 2 borders
describe('grow group cut', () => {
  const rowsArea = (k: number) => k * 39 - 1 + 19;   // k whole rows and the peek of the next
  // floor: the box's min-height (3 rows and the peek: 178 px), the one source of the peek
  const base = { chrome: 43, content: 10 * 39 - 1, pitch: 39, rule: 1, floor: 43 + rowsArea(3), minRows: 3 };
  it('moves a cut just under a rule back into a peek (sync-before@1100: 5 px under the 4th row)', () =>
    expect(growSpare({ ...base, given: 43 + 4 * 39 + 5 })).toBe(4 * 39 + 5 - rowsArea(3)));
  it('rows of different heights: the cut lands inside the last row its peek fits into, measured', () => {
    // rows at 0, 52, 104, a wrapped row at 156, a section head at 230, rows at 262 and 314
    const tops = [0, 52, 104, 156, 230, 262, 314];
    const peek = base.floor - base.chrome - (base.minRows * base.pitch - base.rule);
    const at = (area: number) => growSpare({ ...base, given: base.chrome + area, content: 366, tops });
    expect(at(270)).toBe(Math.floor(270 - (262 - peek / 2)));  // 8 px into the row at 262: back into the head
    expect(at(285)).toBe(0);                                  // 23 px into it: the peek (19) fits, the cut stays
    expect(at(240)).toBe(Math.floor(240 - (230 - peek / 2)));  // 10 px into the head: back into the wrapped row
    expect(at(120)).toBe(0);                                  // under the minimum rows
  });
  it('leaves a cut that already is a peek alone', () => expect(growSpare({ ...base, given: 43 + rowsArea(4) })).toBe(0));
  it('gives nothing when the rows fit', () => expect(growSpare({ ...base, given: 43 + base.content })).toBe(0));
  it('gives nothing at or under the minimum (the min-height holds there)', () => {
    expect(growSpare({ ...base, given: 43 + rowsArea(3) })).toBe(0);
    expect(growSpare({ ...base, given: 100 })).toBe(0);
  });
  it('gives nothing at the minimum even when the min-height\'s peek is not half the measured row (probe 2: 2 px held)', () => {
    const floor = 43 + 3 * 39 - 1 + 21;   // the CSS peek rounds 2 px apart from the measured half row
    expect(growSpare({ ...base, floor, given: floor })).toBe(0);
  });
  it('repeats the min-height\'s own peek above the minimum', () => {
    const floor = 43 + 3 * 39 - 1 + 21;
    expect(growSpare({ ...base, floor, given: floor + 39 })).toBe(0);
    expect(growSpare({ ...base, floor, given: floor + 39 + 7 })).toBe(7);
  });
  it('peeks at the last row too', () => {
    const content = 5 * 39 - 1;
    expect(growSpare({ ...base, content, given: 43 + content - 4 })).toBe(content - 4 - rowsArea(4));
  });
  it('lands every cut on a peek, with less than a row to spare', () => {
    for (let r = rowsArea(3); r < base.content - 0.5; r += 0.5) {   // within 0.5 px the rows fit
      const spare = growSpare({ ...base, given: 43 + r });
      expect(spare).toBeGreaterThanOrEqual(0);
      expect(spare).toBeLessThan(39);
      expect((Math.floor(r - spare) + 1 - 19) % 39).toBe(0);
    }
  });
  it('depends only on the space given, so applying it changes nothing (no oscillation)', () => {
    const given = 43 + 4 * 39 + 20;
    const spare = growSpare({ ...base, given });
    // after applying, the box is given − spare and the spacer holds spare: the space given is the same
    expect(growSpare({ ...base, given: (given - spare) + spare })).toBe(spare);
  });
  it('gives nothing without a row pitch (fewer than 2 rows)', () =>
    expect(growSpare({ ...base, pitch: 0, given: 60, content: 80 })).toBe(0));
});

describe('All with a cap', () => {
  const rows = (n: number, on = false) => Array.from({ length: n }, (_, i) => ({ key: `k${i}`, label: `Row ${i}`, on }));
  it('is on at the cap and off one row past it', () => {
    expect(allDisabled(rows(25), 25)).toBe(false);
    expect(allDisabled(rows(26), 25)).toBe(true);
  });
  it('has no cap without allMax', () => expect(allDisabled(rows(300))).toBe(false));
  it('is off when every shown row is on, or none is shown', () => {
    expect(allDisabled(rows(3, true), 25)).toBe(true);
    expect(allDisabled([], 25)).toBe(true);
  });
});
