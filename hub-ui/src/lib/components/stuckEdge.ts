// Which edge of its scroller a sticky element stands on (plan library stage 5 A3.6, notes N15): ListSection's head
// gets its hairline only while it is stuck and rows pass beneath it, on that side. CSS can't tell (scroll-state
// queries aren't in WebKit), so this compares where the head is with where it would be without sticking: its previous
// sibling's bottom (or its parent's content top), plus its own top margin. Pushed down = stuck at the top, pulled up =
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

function naturalTop(el: HTMLElement, scroller: HTMLElement | null): number {
  const margin = parseFloat(getComputedStyle(el).marginTop) || 0;
  const prev = el.previousElementSibling;
  if (prev) return prev.getBoundingClientRect().bottom + margin;
  const parent = el.parentElement;
  if (!parent) return el.getBoundingClientRect().top;
  const cs = getComputedStyle(parent);
  const top = parent.getBoundingClientRect().top + (parseFloat(cs.borderTopWidth) || 0) + (parseFloat(cs.paddingTop) || 0);
  // the scroller's own box doesn't move when it scrolls; its content does
  return top + margin - (parent === scroller ? parent.scrollTop : 0);
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
