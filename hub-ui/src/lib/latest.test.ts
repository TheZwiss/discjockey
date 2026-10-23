import { describe, expect, it } from 'vitest';
import { latestOnly } from './latest';

describe('latestOnly', () => {
  it('keeps the reply of the newest request only', () => {
    const gate = latestOnly();
    const older = gate.next();
    const newer = gate.next();
    // the older reply comes last (a slow dashboard call): it must not overwrite the newer one
    expect(gate.isLatest(newer)).toBe(true);
    expect(gate.isLatest(older)).toBe(false);
  });
  it('keeps a lone request', () => {
    const gate = latestOnly();
    expect(gate.isLatest(gate.next())).toBe(true);
  });
  it('keeps two gates apart', () => {
    const a = latestOnly();
    const b = latestOnly();
    const t = a.next();
    b.next();
    b.next();
    expect(a.isLatest(t)).toBe(true);
  });
});
