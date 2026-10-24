import { describe, expect, it } from 'vitest';
import { RESCAN_AFTER_MS, shouldRescan } from './rescanModel';

describe('shouldRescan', () => {
  it('never when the window was not in the background', () => {
    expect(shouldRescan(null, 1_000_000)).toBe(false);
  });
  it('not for a minute or less', () => {
    expect(shouldRescan(1000, 1000)).toBe(false);
    expect(shouldRescan(1000, 1000 + RESCAN_AFTER_MS)).toBe(false);
  });
  it('after more than a minute', () => {
    expect(shouldRescan(1000, 1000 + RESCAN_AFTER_MS + 1)).toBe(true);
  });
});
