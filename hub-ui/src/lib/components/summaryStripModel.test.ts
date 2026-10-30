import { describe, expect, it } from 'vitest';
import type { Library } from '../bridge/types';
import { stripView } from './summaryStripModel';

const sum = (o: Partial<Library['summary']> = {}): Library['summary'] => ({
  tracks: 472, lossless_share: 290 / 460,
  by_quality: { lossless: 290, good_lossy: 120, weak: 41, fake: 9, missing: 0 },
  upgrades_ready: 6, to_do: 170, not_lossless: 170, ...o,
});

describe('stripView', () => {
  it('says the share, its checked tracks, and both rows as links', () => {
    expect(stripView(sum())).toEqual({
      share: '63', line: '290 of 460 checked tracks',
      upgrades: { count: '6', link: true },
      notLossless: { count: '170', link: true, todo: 'all in To-do', tip: null },
      mix: [{ quality: 'good_lossy', n: 120 }, { quality: 'weak', n: 41 }, { quality: 'fake', n: 9 }],
    });
  });
  it("marks Not lossless yet with the qualities it holds, not one quality's colour", () => {
    expect(stripView(sum({ by_quality: { lossless: 10, good_lossy: 3, weak: 0, fake: 2, missing: 4 } })).mix)
      .toEqual([{ quality: 'good_lossy', n: 3 }, { quality: 'fake', n: 2 }]);
    expect(stripView(sum({ by_quality: { lossless: 10, good_lossy: 0, weak: 0, fake: 0, missing: 0 } })).mix).toEqual([]);
    expect(stripView(null).mix).toEqual([]);
  });
  it('counts with thousands separators', () => {
    const v = stripView(sum({ tracks: 5318, lossless_share: 3776 / 5306,
      by_quality: { lossless: 3776, good_lossy: 900, weak: 500, fake: 130, missing: 0 }, not_lossless: 1530, to_do: 1530 }));
    expect(v.share).toBe('71');
    expect(v.line).toBe('3,776 of 5,306 checked tracks');
    expect(v.notLossless.count).toBe('1,530');
  });
  it('says how many are in To-do when fewer, with the reason as the tooltip', () => {
    const v = stripView(sum({ to_do: 41 }));
    expect(v.notLossless).toEqual({ count: '170', link: true, todo: '41 in To-do',
      tip: "41 of them in To-do: files of your own in no playlist aren't" });
  });
  it('has no link and no › when none is in To-do', () => {
    const v = stripView(sum({ to_do: 0 }));
    expect(v.notLossless).toMatchObject({ link: false, todo: 'none in To-do',
      tip: "None of them in To-do: files of your own in no playlist aren't" });
  });
  it('says nothing about To-do when every checked track is lossless', () => {
    const v = stripView(sum({ lossless_share: 1, by_quality: { lossless: 460, good_lossy: 0, weak: 0, fake: 0, missing: 0 },
      not_lossless: 0, to_do: 0, upgrades_ready: 0 }));
    expect(v.share).toBe('100');
    expect(v.upgrades).toEqual({ count: '0', link: false });
    expect(v.notLossless).toEqual({ count: '0', link: false, todo: null, tip: null });
  });
  it('to_do above not_lossless (missing songs) still reads all', () => {
    expect(stripView(sum({ to_do: 200 })).notLossless.todo).toBe('all in To-do');
  });
  it('waits with dashes, and says why a share is missing', () => {
    expect(stripView(null)).toMatchObject({ share: null, line: 'lossless', upgrades: { count: '—', link: false } });
    expect(stripView(sum({ tracks: 0, lossless_share: null, not_lossless: 0, to_do: 0, upgrades_ready: 0,
      by_quality: { lossless: 0, good_lossy: 0, weak: 0, fake: 0, missing: 0 } })).line).toBe('lossless · no tracks yet');
    expect(stripView(sum({ lossless_share: null, by_quality: { lossless: 0, good_lossy: 0, weak: 0, fake: 0, missing: 0 },
      not_lossless: 0, to_do: 0 }))).toMatchObject({ share: null, line: 'lossless · none checked yet' });
  });
});
