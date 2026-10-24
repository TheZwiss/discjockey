import { describe, expect, it } from 'vitest';
import { dayBar } from './dayBarModel';

describe('day bar', () => {
  it('splits today and tomorrow', () => {
    const r = dayBar({ today: 66, later: 36, limited: true, laterDays: 1 });
    expect(r.segs.map((s) => s.label)).toEqual(['Today 66', 'Tomorrow 36']);
    expect(r.segs.map((s) => s.grow)).toEqual([66, 36]);
    expect(r.caption).toBeNull();
  });
  it('says how many days when it takes longer', () => {
    expect(dayBar({ today: 10, later: 185, limited: true, laterDays: 4 }).segs[1].label).toBe('Later 185 · ~4 days');
  });
  it('has one segment without a daily limit', () => {
    const r = dayBar({ today: 120, later: 0, limited: false, laterDays: 0 });
    expect(r.segs.map((s) => s.label)).toEqual(['Today 120']);
    expect(r.caption).toBe('No daily limit');
  });
  it('shows only later once the limit is reached', () => {
    const r = dayBar({ today: 0, later: 77, limited: true, laterDays: 2 });
    expect(r.segs).toEqual([{ kind: 'later', label: 'Later 77 · ~2 days', n: 77, grow: 77 }]);
  });
  it('is empty when nothing is ticked', () => {
    expect(dayBar({ today: 0, later: 0, limited: true, laterDays: 0 }).segs).toEqual([]);
  });
  // edges beyond the brief
  it('shows only later when nothing fits today', () => {
    const r = dayBar({ today: 0, later: 40, limited: true, laterDays: 1 });
    expect(r.segs.map((s) => [s.kind, s.label])).toEqual([['later', 'Tomorrow 40']]);
  });
  it('drops later without a daily limit', () => {
    const r = dayBar({ today: 50, later: 9, limited: false, laterDays: 1 });
    expect(r.segs.map((s) => s.kind)).toEqual(['today']);
  });
  it('reads "Tomorrow" when the day count is unknown (0)', () => {
    expect(dayBar({ today: 5, later: 8, limited: true, laterDays: 0 }).segs[1].label).toBe('Tomorrow 8');
  });

  describe('day mode (Dashboard: the whole daily limit)', () => {
    const day = (used: number, allowance: number) => ({ used, allowance });
    it('puts what is used ahead of this sync and what is left after it', () => {
      const r = dayBar({ today: 15, later: 0, limited: true, laterDays: 0, day: day(37, 80) });
      expect(r.segs.map((s) => [s.kind, s.label, s.grow])).toEqual([['used', 'Used 37', 37], ['today', 'This sync 15', 15],
        ['free', '28 left', 28]]);
    });
    it('shows later instead of left when the sync needs more than today has', () => {
      const r = dayBar({ today: 43, later: 20, limited: true, laterDays: 1, day: day(37, 80) });
      expect(r.segs.map((s) => s.label)).toEqual(['Used 37', 'This sync 43', 'Tomorrow 20']);
    });
    it('drops the used segment before the first download of the day', () => {
      expect(dayBar({ today: 5, later: 0, limited: true, laterDays: 0, day: day(0, 60) }).segs.map((s) => s.kind))
        .toEqual(['today', 'free']);
    });
    it('shows used and left with nothing to sync', () => {
      expect(dayBar({ today: 0, later: 0, limited: true, laterDays: 0, day: day(37, 80) }).segs.map((s) => s.label))
        .toEqual(['Used 37', '43 left']);
    });
    it('shows used and tomorrow when the day is used up', () => {
      const r = dayBar({ today: 0, later: 30, limited: true, laterDays: 1, day: day(80, 80) });
      expect(r.segs.map((s) => s.label)).toEqual(['Used 80', 'Tomorrow 30']);
    });
    it('is the plain bar without a daily limit', () => {
      const r = dayBar({ today: 12, later: 0, limited: false, laterDays: 0, day: day(0, 0) });
      expect(r.segs.map((s) => s.label)).toEqual(['Today 12']);
      expect(r.caption).toBe('No daily limit');
    });
  });
});
