import { describe, expect, it } from 'vitest';
import { daysToLoad } from './days';

// The same cases as tests/test_hub_views.py::test_days_to_load (views.days_to_load).
describe('daysToLoad', () => {
  it('counts today only when something is left today', () => {
    expect(daysToLoad(0, 10, 60)).toBe(0);
    expect(daysToLoad(12, 43, 60)).toBe(1);
    expect(daysToLoad(43, 43, 60)).toBe(1);
    expect(daysToLoad(44, 43, 60)).toBe(2);
    expect(daysToLoad(250, 23, 60)).toBe(1 + 4);
    expect(daysToLoad(108, 30, 66)).toBe(1 + 2);
  });
  it('with nothing left today it starts tomorrow', () => {
    expect(daysToLoad(250, 0, 60)).toBe(5);
    expect(daysToLoad(108, 0, 66)).toBe(2);
    expect(daysToLoad(1, 0, 60)).toBe(1);
    expect(daysToLoad(108, -3, 66)).toBe(2);
  });
});
