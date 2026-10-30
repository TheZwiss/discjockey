import { describe, expect, it } from 'vitest';
import { HOVER_DELAY_MS, openTiming, placeTip, TIP_DELAY_MS, TIP_GAP, TIP_CLOSED, tipStep, WARM_MS, type TipEvent, type TipState, type TipStep } from './infoTipModel';

/** Runs the events from closed and returns the last step. */
function run(...events: TipEvent[]) {
  let s: TipState = TIP_CLOSED;
  let last: TipStep = { state: s, refocus: false, handled: false };
  for (const e of events) { last = tipStep(s, e); s = last.state; }
  return last;
}
const hover: TipEvent = { type: 'hover' };
const leave: TipEvent = { type: 'leave' };
const kbdFocus: TipEvent = { type: 'focus', keyboard: true };
const click: TipEvent = { type: 'activate', keyboard: false };
const enter: TipEvent = { type: 'activate', keyboard: true };
const escape = (focusInTip = false): TipEvent => ({ type: 'escape', focusInTip });

describe('info tip', () => {
  it('opens on hover and closes when the pointer leaves', () => {
    expect(run(hover).state.open).toBe(true);
    expect(run(hover, leave).state).toEqual(TIP_CLOSED);
  });
  it('closes a hovered tip on Escape without taking focus', () => {
    const r = run(hover, escape());
    expect(r.state.open).toBe(false);
    expect(r).toMatchObject({ refocus: false, handled: true });
    expect(run(hover, escape(), leave).state.open).toBe(false);   // and stays closed when the pointer goes
  });
  it('closes a focused tip on Escape, keeps focus and does not reopen', () => {
    const r = run(kbdFocus, escape());
    expect(r).toMatchObject({ state: { open: false }, refocus: false, handled: true });
    expect(run(kbdFocus, escape(), hover, leave).state.open).toBe(false);   // hover after it doesn't stick
  });
  it('brings focus back from a link in the popover on Escape and swallows that focus', () => {
    const r = run(click, escape(true));
    expect(r).toMatchObject({ state: { open: false }, refocus: true, handled: true });
    expect(run(click, escape(true), kbdFocus).state.open).toBe(false);
    expect(run(click, escape(true), kbdFocus, hover).state.open).toBe(true);   // only that one focus
  });
  it('leaves Escape alone while closed, so a Dialog around it can close', () => {
    expect(run(escape()).handled).toBe(false);
    expect(run(hover, leave, escape()).handled).toBe(false);
  });
  it('pins on a click and closes on the second', () => {
    expect(run(click).state).toMatchObject({ open: true, via: 'pin' });
    expect(run(click, leave).state.open).toBe(true);
    expect(run(click, click).state.open).toBe(false);
    expect(run(hover, click).state).toMatchObject({ open: true, via: 'pin' });   // a hovered tip gets pinned
    expect(run(hover, click, leave).state.open).toBe(true);
  });
  it('opens on keyboard focus but not on focus a click leaves', () => {
    expect(run(kbdFocus).state).toMatchObject({ open: true, via: 'focus' });
    expect(run({ type: 'focus', keyboard: false }).state.open).toBe(false);
  });
  it('stays open while focused even when the pointer leaves', () => {
    expect(run(kbdFocus, hover, leave).state.open).toBe(true);
  });
  it('toggles with Enter: closes a tip focus opened, opens a closed one', () => {
    expect(run(kbdFocus, enter).state.open).toBe(false);
    expect(run(kbdFocus, enter, enter).state).toMatchObject({ open: true, via: 'pin' });
  });
  it('closes on blur and on a press outside, scroll or resize', () => {
    expect(run(click, { type: 'blur' }).state).toEqual(TIP_CLOSED);
    expect(run(kbdFocus, { type: 'dismiss' }).state).toEqual(TIP_CLOSED);
    expect(run(hover, { type: 'dismiss' }).state).toEqual(TIP_CLOSED);
  });
});

describe('info tip opening', () => {
  const cold = { otherOpen: false, lastClosedAt: null };
  const closedAt = (t: number) => ({ otherOpen: false, lastClosedAt: t });
  it('waits before a hover opens it, so a passing pointer flashes nothing; both fade in', () => {
    expect(openTiming('hover', 10_000, cold)).toEqual({ delay: HOVER_DELAY_MS, fade: true });
    expect(openTiming('click', 10_000, cold)).toEqual({ delay: 0, fade: true });
  });
  it('opens at once without a fade from the keyboard', () => {
    expect(openTiming('keyboard', 10_000, cold)).toEqual({ delay: 0, fade: false });
  });
  it('opens the next tip at once without a fade right after one closed', () => {
    expect(openTiming('hover', 10_000, closedAt(10_000 - WARM_MS + 1))).toEqual({ delay: 0, fade: false });
    expect(openTiming('click', 10_000, closedAt(9_900))).toEqual({ delay: 0, fade: false });
    expect(openTiming('hover', 10_000, closedAt(10_000 - WARM_MS))).toEqual({ delay: HOVER_DELAY_MS, fade: true });   // cooled down
  });
  it('opens the next tip at once without a fade while the one the pointer just left is still open', () => {
    // the quick reader: from one ⓘ to the next inside the first one's grace delay, so it hasn't closed yet
    expect(openTiming('hover', 10_000, { otherOpen: true, lastClosedAt: null })).toEqual({ delay: 0, fade: false });
    expect(openTiming('click', 10_000, { otherOpen: true, lastClosedAt: null })).toEqual({ delay: 0, fade: false });
    // an open tip counts however long ago the last one closed
    expect(openTiming('hover', 10_000, { otherOpen: true, lastClosedAt: 1_000 })).toEqual({ delay: 0, fade: false });
  });
});

describe('tip opening (Tip)', () => {
  const cold = { otherOpen: false, lastClosedAt: null };
  it('waits longer on a cold hover, and the next one opens at once', () => {
    expect(openTiming('hover', 10_000, cold, TIP_DELAY_MS)).toEqual({ delay: 500, fade: true });
    expect(openTiming('hover', 10_000, { otherOpen: false, lastClosedAt: 9_800 }, TIP_DELAY_MS)).toEqual({ delay: 0, fade: false });
    expect(openTiming('keyboard', 10_000, cold, TIP_DELAY_MS)).toEqual({ delay: 0, fade: false });
  });
});

describe('tip placement', () => {
  const win = { width: 1280, height: 800 };
  const size = { width: 120, height: 22 };
  it('sits right of a rail icon, centred on it, growing out of its left edge', () => {
    const p = placeTip({ left: 10, top: 100, width: 30, height: 30 }, size, win, 'right');
    expect(p).toEqual({ left: 40 + TIP_GAP.right, top: 104, origin: '0px 11px' });
  });
  it('goes left of a trigger at the window\'s right edge', () => {
    const p = placeTip({ left: 1200, top: 100, width: 30, height: 30 }, size, win, 'right');
    expect(p.left).toBe(1200 - TIP_GAP.right - 120);
    expect(p.origin).toBe('120px 11px');
  });
  it('stays inside the window vertically', () => {
    expect(placeTip({ left: 10, top: 2, width: 30, height: 10 }, size, win, 'right').top).toBe(8);
    expect(placeTip({ left: 10, top: 790, width: 30, height: 10 }, size, win, 'right').top).toBe(800 - 8 - 22);
  });
  it('sits below a row at the pointer, above it when there is no room below', () => {
    const r = { left: 60, top: 200, width: 240, height: 30 };
    expect(placeTip(r, size, win, 'below', 150)).toEqual({ left: 150, top: 230 + TIP_GAP.below, origin: '0px 0px' });
    expect(placeTip(r, size, win, 'below')).toMatchObject({ left: 60 });
    const low = { ...r, top: 770 };
    expect(placeTip(low, size, win, 'below', 150)).toEqual({ left: 150, top: 770 - TIP_GAP.below - 22, origin: '0px 22px' });
  });
  it('is pushed in from the window\'s right edge, its origin still at the pointer', () => {
    const p = placeTip({ left: 1100, top: 200, width: 170, height: 30 }, size, win, 'below', 1250);
    expect(p.left).toBe(1280 - 8 - 120);
    expect(p.origin).toBe(`${1250 - p.left}px 0px`);
  });
});
