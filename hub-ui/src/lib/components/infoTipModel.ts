// When an InfoTip (design system §6) opens and closes. Pure, so every path is tested; InfoTip.svelte only turns DOM
// events into these events and applies the result (popover, focus, preventDefault).
//
// `via` says what holds the tip open: the pointer (`hover`, closes when it leaves), keyboard focus (`focus`, closes
// when focus leaves) or a click / Enter (`pin`, closes on the next one). `quiet` swallows the one focus event that
// Escape's own refocus of the ⓘ causes, so Escape never reopens the tip it closed.

export type TipVia = 'hover' | 'focus' | 'pin';
export type TipState = { open: boolean; via: TipVia | null; quiet: boolean };
export type TipEvent =
  | { type: 'hover' }                            // the pointer is over the ⓘ or its popover
  | { type: 'leave' }                            // the pointer left them (after the grace delay)
  | { type: 'focus'; keyboard: boolean }         // the ⓘ got focus; `keyboard` when it shows a focus ring
  | { type: 'blur' }                             // focus went somewhere outside the ⓘ and its popover
  | { type: 'activate'; keyboard: boolean }      // a click, or Enter / Space (`keyboard`)
  | { type: 'escape'; focusInTip: boolean }      // Escape; `focusInTip` when focus is on a link inside the popover
  | { type: 'dismiss' };                         // a press outside, a scroll or a resize
/** `refocus`: put focus back on the ⓘ. `handled`: the key was used, so it must not also close a Dialog around it. */
export type TipStep = { state: TipState; refocus: boolean; handled: boolean };

export const TIP_CLOSED: TipState = { open: false, via: null, quiet: false };
const step = (state: TipState, refocus = false, handled = false): TipStep => ({ state, refocus, handled });

export function tipStep(s: TipState, e: TipEvent): TipStep {
  switch (e.type) {
    case 'hover':
      return step(s.open ? { ...s, quiet: false } : { open: true, via: 'hover', quiet: false });
    case 'leave':
      return step(s.via === 'hover' ? TIP_CLOSED : s);
    case 'focus':
      if (s.quiet) return step({ ...s, quiet: false });
      return step(e.keyboard && s.via !== 'pin' ? { open: true, via: 'focus', quiet: false } : s);
    case 'blur':
    case 'dismiss':
      return step(TIP_CLOSED);
    case 'activate':
      // a click on a tip the pointer opened pins it; Enter on a tip that focus opened closes it (it is a toggle there)
      if (s.open && (s.via === 'pin' || e.keyboard)) return step(TIP_CLOSED);
      return step({ open: true, via: 'pin', quiet: false });
    case 'escape':
      if (!s.open) return step(s);
      // focus only comes back to the ⓘ from inside the popover; a field the user types in keeps it
      return step({ ...TIP_CLOSED, quiet: e.focusInTip }, e.focusInTip, true);
  }
}

// How a closed tip opens (design audit A10, Emil's tooltip rule). A hover waits HOVER_DELAY_MS, so a pointer that only
// crosses the panel flashes nothing; a click opens at once. Both fade in. Keyboard opens at once and without a fade
// (keyboard actions never animate). While the user is reading the tips one after another, the next one opens at once
// and without a fade: another tip is still open (the pointer left it less than its grace delay ago), or one closed
// less than WARM_MS ago. Only one tip is open at a time, so the one still open closes as this one opens.
// A `Tip` (the hover tooltip of an icon-only control or a cut row, tip.ts) waits TIP_DELAY_MS instead: it names what
// the pointer rests on, so it waits until the pointer stays (macOS's own tooltips wait longer still), and the warm
// rule below makes the rail's next icons answer at once.
export const HOVER_DELAY_MS = 300;
export const TIP_DELAY_MS = 500;
export const WARM_MS = 800;
export type TipOpening = { delay: number; fade: boolean };
/** What the other tips on the page are doing: one is open right now, and when the last one closed. */
export type TipWarmth = { otherOpen: boolean; lastClosedAt: number | null };

/** `hoverDelay`: how long a cold hover waits (InfoTip HOVER_DELAY_MS, Tip TIP_DELAY_MS). */
export function openTiming(how: 'hover' | 'click' | 'keyboard', now: number, w: TipWarmth,
  hoverDelay = HOVER_DELAY_MS): TipOpening {
  const warm = w.otherOpen || (w.lastClosedAt !== null && now - w.lastClosedAt < WARM_MS);
  if (warm || how === 'keyboard') return { delay: 0, fade: false };
  return { delay: how === 'hover' ? hoverDelay : 0, fade: true };
}

/** Where a Tip sits (tip.ts): `right` of its trigger, centred on it (a rail icon), or `below` it (a row), starting at
 *  `anchorX` (the pointer's x, as macOS places a tooltip; the trigger's left edge without one) and above it when the
 *  window has no room below. Kept `edge` px inside the window. `origin` is the trigger's spot in the tip's own box, so
 *  the tip grows out of what it names. */
export type TipSide = 'right' | 'below';
export type TipBox = { left: number; top: number; width: number; height: number };
export type TipPlace = { left: number; top: number; origin: string };
export const TIP_GAP = { right: 8, below: 4 } as const;

export function placeTip(t: TipBox, size: { width: number; height: number }, win: { width: number; height: number },
  side: TipSide, anchorX?: number, edge = 8): TipPlace {
  const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(v, Math.max(lo, hi)));
  if (side === 'right') {
    const right = t.left + t.width + TIP_GAP.right;
    // no room on the right (a trigger at the window's right edge): on its left instead
    const left = right + size.width <= win.width - edge ? right : Math.max(edge, t.left - TIP_GAP.right - size.width);
    const centre = t.top + t.height / 2;
    const top = clamp(centre - size.height / 2, edge, win.height - edge - size.height);
    return { left, top, origin: `${left >= right ? 0 : size.width}px ${centre - top}px` };
  }
  const below = t.top + t.height + TIP_GAP.below;
  const top = below + size.height <= win.height - edge ? below : Math.max(edge, t.top - TIP_GAP.below - size.height);
  const x = anchorX ?? t.left;
  const left = clamp(x, edge, win.width - edge - size.width);
  return { left, top, origin: `${x - left}px ${top === below ? 0 : size.height}px` };
}
