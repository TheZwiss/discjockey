import { describe, expect, it } from 'vitest';
import { watchRescan } from './rescan';

type Fn = (e?: unknown) => void;

function target() {
  const fns = new Map<string, Set<Fn>>();
  return {
    addEventListener: (t: string, f: Fn) => { fns.set(t, (fns.get(t) ?? new Set()).add(f)); },
    removeEventListener: (t: string, f: Fn) => { fns.get(t)?.delete(f); },
    fire: (t: string) => fns.get(t)?.forEach((f) => f()),
    count: (t: string) => fns.get(t)?.size ?? 0,
  };
}

describe('watchRescan', () => {
  const setup = () => {
    const doc = Object.assign(target(), { visibilityState: 'visible' });
    const win = target();
    let clock = 0, scans = 0;
    const stop = watchRescan(doc, win, () => { scans++; }, () => clock);
    return { doc, win, stop, tick: (ms: number) => { clock += ms; }, scans: () => scans };
  };
  it('scans once at start', () => {
    expect(setup().scans()).toBe(1);
  });
  it('scans when the window comes back after more than a minute (blur, focus)', () => {
    const t = setup();
    t.win.fire('blur'); t.tick(61_000); t.win.fire('focus');
    expect(t.scans()).toBe(2);
  });
  it('does not scan after a short stay in the background', () => {
    const t = setup();
    t.win.fire('blur'); t.tick(30_000); t.win.fire('focus');
    expect(t.scans()).toBe(1);
  });
  it('blur + hidden, then focus + visible, scans once', () => {
    const t = setup();
    t.win.fire('blur'); t.doc.visibilityState = 'hidden'; t.doc.fire('visibilitychange');
    t.tick(120_000);
    t.win.fire('focus'); t.doc.visibilityState = 'visible'; t.doc.fire('visibilitychange');
    expect(t.scans()).toBe(2);
  });
  it('the clean-up removes the listeners', () => {
    const t = setup();
    t.stop();
    expect(t.doc.count('visibilitychange') + t.win.count('blur') + t.win.count('focus')).toBe(0);
  });
});
