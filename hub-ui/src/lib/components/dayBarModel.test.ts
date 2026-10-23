import { describe, expect, it } from 'vitest';
import { dayBar } from './dayBarModel';

describe('day bar', () => {
  it('splits today and tomorrow', () => {
    const r = dayBar({ today: 66, later: 36, limited: true, laterDays: 1, moves: 0 });
    expect(r.segs.map((s) => s.label)).toEqual(['Today 66', 'Tomorrow 36']);
    expect(r.segs.map((s) => s.grow)).toEqual([66, 36]);
    expect(r.caption).toBeNull();
  });
  it('says how many days when it takes longer', () => {
    expect(dayBar({ today: 10, later: 185, limited: true, laterDays: 4, moves: 0 }).segs[1].label).toBe('Later 185 · ~4 days');
  });
  it('has one segment without a daily limit', () => {
    const r = dayBar({ today: 120, later: 0, limited: false, laterDays: 0, moves: 0 });
    expect(r.segs.map((s) => s.label)).toEqual(['Today 120']);
    expect(r.caption).toBe('No daily limit');
  });
  it('shows moves only when the limit is reached', () => {
    const r = dayBar({ today: 0, later: 77, limited: true, laterDays: 2, moves: 3 });
    // sized by its label, not by a share, so "Today: 3 moves" always reads next to a long later segment
    expect(r.segs[0]).toEqual({ kind: 'today', label: 'Today: 3 moves', n: 0, grow: 0, fit: true });
    expect(r.segs[1].label).toBe('Later 77 · ~2 days');
  });
  it('is empty when nothing is ticked', () => {
    expect(dayBar({ today: 0, later: 0, limited: true, laterDays: 0, moves: 0 }).segs).toEqual([]);
  });
  // edges beyond the brief
  it('says "1 move" for a single move', () => {
    expect(dayBar({ today: 0, later: 5, limited: true, laterDays: 1, moves: 1 }).segs[0].label).toBe('Today: 1 move');
  });
  it('shows the moves segment when nothing waits for later', () => {
    const r = dayBar({ today: 0, later: 0, limited: true, laterDays: 0, moves: 2 });
    expect(r.segs).toEqual([{ kind: 'today', n: 0, label: 'Today: 2 moves', grow: 0, fit: true }]);
  });
  it('sizes only the moves segment by its label', () => {
    expect(dayBar({ today: 66, later: 36, limited: true, laterDays: 1, moves: 3 }).segs.map((s) => s.fit)).toEqual([false, false]);
  });
  it('shows only later when nothing fits today and there are no moves', () => {
    const r = dayBar({ today: 0, later: 40, limited: true, laterDays: 1, moves: 0 });
    expect(r.segs.map((s) => [s.kind, s.label])).toEqual([['later', 'Tomorrow 40']]);
  });
  it('drops later without a daily limit', () => {
    const r = dayBar({ today: 50, later: 9, limited: false, laterDays: 1, moves: 0 });
    expect(r.segs.map((s) => s.kind)).toEqual(['today']);
  });
  it('reads "Tomorrow" when the day count is unknown (0)', () => {
    expect(dayBar({ today: 5, later: 8, limited: true, laterDays: 0, moves: 0 }).segs[1].label).toBe('Tomorrow 8');
  });

  describe('day mode (Dashboard: the whole daily limit)', () => {
    const day = (used: number, allowance: number) => ({ used, allowance });
    it('puts what is used ahead of this sync and what is left after it', () => {
      const r = dayBar({ today: 15, later: 0, limited: true, laterDays: 0, moves: 0, day: day(37, 80) });
      expect(r.segs.map((s) => [s.kind, s.label, s.grow])).toEqual([['used', 'Used 37', 37], ['today', 'This sync 15', 15],
        ['free', '28 left', 28]]);
    });
    it('shows later instead of left when the sync needs more than today has', () => {
      const r = dayBar({ today: 43, later: 20, limited: true, laterDays: 1, moves: 0, day: day(37, 80) });
      expect(r.segs.map((s) => s.label)).toEqual(['Used 37', 'This sync 43', 'Tomorrow 20']);
    });
    it('drops the used segment before the first download of the day', () => {
      expect(dayBar({ today: 5, later: 0, limited: true, laterDays: 0, moves: 0, day: day(0, 60) }).segs.map((s) => s.kind))
        .toEqual(['today', 'free']);
    });
    it('shows used and left with nothing to sync', () => {
      expect(dayBar({ today: 0, later: 0, limited: true, laterDays: 0, moves: 0, day: day(37, 80) }).segs.map((s) => s.label))
        .toEqual(['Used 37', '43 left']);
    });
    it('names a moves-only sync by its moves', () => {
      const r = dayBar({ today: 0, later: 30, limited: true, laterDays: 1, moves: 2, day: day(80, 80) });
      expect(r.segs.map((s) => s.label)).toEqual(['Used 80', 'This sync: 2 moves', 'Tomorrow 30']);
    });
    it('is the plain bar without a daily limit', () => {
      const r = dayBar({ today: 12, later: 0, limited: false, laterDays: 0, moves: 0, day: day(0, 0) });
      expect(r.segs.map((s) => s.label)).toEqual(['Today 12']);
      expect(r.caption).toBe('No daily limit');
    });
  });
});
