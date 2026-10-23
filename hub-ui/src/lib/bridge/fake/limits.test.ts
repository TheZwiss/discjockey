import { describe, expect, it } from 'vitest';
import { makeState } from './data';
import { cards, gate, limits, split, zones } from './limits';

describe('fake limits', () => {
  it('matches the backend rules', () => {
    const s = makeState('normal');
    expect(cards(s).map((c) => c.set_up)).toEqual([true, false, false]);
    expect(limits(s, 'youtube', 10).usage).toBeNull();
    s.accounts.youtube = { ...s.qobuz, limit: 30, carry_over: 0, used_today: 3, signals: [], browser: 'chrome' };
    expect(split(s, 12)[1]).toMatchObject({ service: 'youtube', uses: null, about: true });
    s.qobuzSkipped = true;
    expect(gate(s)).toEqual({ remaining: 27, limit: 30 });
    expect(zones('youtube')[1]).toEqual({ name: 'normal', from: 21, to: 30 });
  });
});
