// The tips open on the page (InfoTip and Tip share it): only one is open at a time, and while one is open, or right
// after one closed, the next opens at once (openTiming's warm rule). Each tip registers itself by its close function.
import type { TipWarmth } from './infoTipModel';

type Close = () => void;
let current: Close | null = null;
let lastClosedAt: number | null = null;

/** What the other tips are doing, seen from `self`. */
export function tipWarmth(self: Close): TipWarmth {
  return { otherOpen: current !== null && current !== self, lastClosedAt };
}
/** `self` opened: the one open until now closes. */
export function tipOpened(self: Close): void {
  const before = current;
  current = self;
  if (before && before !== self) before();
}
/** `self` closed (counts for the warm rule). */
export function tipClosed(self: Close, now = performance.now()): void {
  lastClosedAt = now;
  if (current === self) current = null;
}
/** `self` was removed while open (its page went away): it no longer counts as open. */
export function tipGone(self: Close): void {
  if (current === self) current = null;
}
