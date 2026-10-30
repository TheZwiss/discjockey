// Which edge of its scroller a sticky element stands on (plan library stage 5 A3.6, notes N15): ListSection's head
// gets its hairline only while it is stuck and rows pass beneath it, on that side. CSS can't tell (scroll-state
// queries aren't in WebKit), so this compares where the head is with where it would be without sticking: after its
// nearest sibling that never sticks (or its parent's content top), plus the heads in between, its own top margin and
// the parent's row gaps between them. Pushed down = stuck at the top, pulled up =
// stuck at the foot.

export type StuckSide = 'top' | 'bottom' | null;

/** `top`: where the element is; `natural`: where it would be without sticking (both in viewport px). */
export function stuckSide(top: number, natural: number): StuckSide {
  const d = top - natural;
  return d > 0.5 ? 'top' : d < -0.5 ? 'bottom' : null;
}

function scrollParent(el: HTMLElement): HTMLElement | null {
  for (let p = el.parentElement; p; p = p.parentElement) {
    if (/(auto|scroll)/.test(getComputedStyle(p).overflowY)) return p;
  }
  return null;
}

/** Where an element would sit without sticking: `base` is the bottom of the nearest sibling before it that never
 *  sticks (or its parent's content top), and `heads` the sticky heads between them, nearest first. Their own rects
 *  may be stuck (a folded section's head right above the next one), so they count by their size, not their place. */
export function naturalOffset(base: number, heads: { height: number; margin: number }[], ownMargin: number,
  gap = 0, afterSibling = true): number {
  // a flex or grid parent's row gap stands between each two of its children (the browser column's 2 px)
  const gaps = (heads.length + (afterSibling ? 1 : 0)) * gap;
  return heads.reduce((y, h) => y + h.height + h.margin, base) + ownMargin + gaps;
}

const isHead = (el: Element) => el.hasAttribute('data-list-section');
const marginOf = (el: Element) => {
  const cs = getComputedStyle(el);
  return (parseFloat(cs.marginTop) || 0) + (parseFloat(cs.marginBottom) || 0);
};

function naturalTop(el: HTMLElement, scroller: HTMLElement | null): number {
  const heads: { height: number; margin: number }[] = [];
  let prev = el.previousElementSibling;
  while (prev && isHead(prev)) {
    heads.push({ height: (prev as HTMLElement).offsetHeight, margin: marginOf(prev) });
    prev = prev.previousElementSibling;
  }
  const parent = el.parentElement;
  if (!parent) return el.getBoundingClientRect().top;
  const pcs = getComputedStyle(parent);
  const gap = /flex|grid/.test(pcs.display) ? parseFloat(pcs.rowGap) || 0 : 0;
  let base: number;
  if (prev) base = prev.getBoundingClientRect().bottom + (parseFloat(getComputedStyle(prev).marginBottom) || 0);
  else {
    base = parent.getBoundingClientRect().top + (parseFloat(pcs.borderTopWidth) || 0) + (parseFloat(pcs.paddingTop) || 0)
      // the scroller's own box doesn't move when it scrolls; its content does
      - (parent === scroller ? parent.scrollTop : 0);
  }
  return naturalOffset(base, heads, parseFloat(getComputedStyle(el).marginTop) || 0, gap, !!prev);
}

/** Sets `data-stuck="top" | "bottom"` on the element while it is stuck; none while it sits where it would anyway. */
export function stuckEdge(node: HTMLElement) {
  let scroller: HTMLElement | null = null;
  let frame = 0;
  const check = () => {
    frame = 0;
    const side = stuckSide(node.getBoundingClientRect().top, naturalTop(node, scroller));
    if (side) node.dataset.stuck = side;
    else delete node.dataset.stuck;
  };
  const later = () => { if (!frame) frame = requestAnimationFrame(check); };
  const target: HTMLElement | Window = (scroller = scrollParent(node)) ?? window;
  target.addEventListener('scroll', later, { passive: true });
  const ro = new ResizeObserver(later);
  if (scroller) ro.observe(scroller);
  if (node.parentElement) ro.observe(node.parentElement);
  later();
  return {
    destroy() {
      target.removeEventListener('scroll', later);
      ro.disconnect();
      if (frame) cancelAnimationFrame(frame);
    },
  };
}
