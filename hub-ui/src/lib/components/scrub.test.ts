import { describe, expect, it } from 'vitest';
import { fractionAt, scrub } from './scrub';

function fakeBar() {
  const listeners: Record<string, (e: unknown) => void> = {};
  const node = {
    getBoundingClientRect: () => ({ left: 100, width: 200 }),
    setPointerCapture: () => {},
    addEventListener: (t: string, f: (e: unknown) => void) => { listeners[t] = f; },
    removeEventListener: (t: string) => { delete listeners[t]; },
  };
  const fire = (t: string, clientX: number, pointerId = 1, button = 0) =>
    listeners[t]?.({ clientX, pointerId, button, preventDefault: () => {} });
  return { node: node as unknown as HTMLElement, listeners, fire };
}

describe('fractionAt', () => {
  it('maps the pointer to 0..1 and clamps outside the bar', () => {
    expect(fractionAt(200, 100, 200)).toBe(0.5);
    expect(fractionAt(50, 100, 200)).toBe(0);
    expect(fractionAt(400, 100, 200)).toBe(1);
    expect(fractionAt(150, 100, 0)).toBe(0);
  });
});

describe('scrub', () => {
  it('follows the pointer while held and seeks once on release', () => {
    const moves: number[] = [];
    const ends: number[] = [];
    const bar = fakeBar();
    scrub(bar.node, { move: (f) => moves.push(f), end: (f) => ends.push(f), cancel: () => {} });
    bar.fire('pointermove', 150);          // hovering without a press does nothing
    bar.fire('pointerdown', 120);
    bar.fire('pointermove', 200);
    bar.fire('pointermove', 350);          // past the end: captured, clamped
    bar.fire('pointerup', 260);
    bar.fire('pointermove', 280);          // released: no more moves
    expect(moves).toEqual([0.1, 0.5, 1]);
    expect(ends).toEqual([0.8]);
  });

  it('ignores other buttons, and a cancelled drag does not seek', () => {
    let ended = false;
    let cancelled = false;
    const bar = fakeBar();
    scrub(bar.node, { move: () => {}, end: () => { ended = true; }, cancel: () => { cancelled = true; } });
    bar.fire('pointerdown', 150, 1, 2);
    bar.fire('pointerup', 150);
    expect(ended).toBe(false);
    bar.fire('pointerdown', 150);
    bar.fire('pointercancel', 150);
    bar.fire('pointerup', 150);
    expect(ended).toBe(false);
    expect(cancelled).toBe(true);
  });

  it('removes its listeners on destroy', () => {
    const bar = fakeBar();
    scrub(bar.node, { move: () => {}, end: () => {}, cancel: () => {} }).destroy();
    expect(Object.keys(bar.listeners)).toEqual([]);
  });
});
