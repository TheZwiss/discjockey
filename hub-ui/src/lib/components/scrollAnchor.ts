// Scroll anchoring for a list that grows while it is open (design system §11, the anchored-list rule; live check of
// plan library stage 5): rows that come or go above the ones on screen never move what the user is looking at.
// Settings' crate switches during an import were the case: a reread a second brought new crates in by name, the rows
// on screen slid down a row or five each time, and WebKit (no CSS scroll anchoring) moved the scroll on top of it
// (measured: 4 moves of up to 190 px in 11 s). The action holds one row, the anchor: the first row whole on screen at
// the top (anchorIndex), at its offset from the scroller's top. When the scroller's rows change (a MutationObserver on its
// children, which reports after the update and before the frame is painted) and the anchor moved, the scroll moves
// by as much, so the anchor stays where it was. A list at its top stays at its top (a row that arrives first shows,
// as CSS scroll anchoring does); a list whose anchor went away keeps its scroll. The browser's own anchoring is off
// on the node (`overflow-anchor: none`), so the two never both correct one change. Row heights and the scroller's own
// size changing are left to layout: only rows coming, going or moving count.

/** A row's place in the scroller, its top and bottom measured from the scroller's visible top (px). */
export type RowSpan = { top: number; bottom: number };

/** The index of the anchor among `rows` (in DOM order): the first row whole on screen at the top (the one the eye
 *  holds; a row cut by the top edge above it may slide out of sight), else the first row partly there, or -1. */
export function anchorIndex(rows: RowSpan[]): number {
  const whole = rows.findIndex((r) => r.top >= -0.5);
  return whole >= 0 ? whole : rows.findIndex((r) => r.bottom > 0.5);
}

/** How far the scroll moves to put the anchor back: `before` and `after` its offset from the visible top (px), or
 *  0 when the list sat at its top, the anchor is gone (null) or it moved less than half a px. */
export function anchorShift(scrollTop: number, before: number | null, after: number | null): number {
  if (scrollTop <= 0 || before === null || after === null) return 0;
  const d = after - before;
  return Math.abs(d) > 0.5 ? d : 0;
}

export function scrollAnchor(node: HTMLElement) {
  let anchor: { el: Element; offset: number } | null = null;
  const offsetOf = (el: Element) => el.getBoundingClientRect().top - node.getBoundingClientRect().top;
  const record = () => {
    if (node.scrollTop <= 0) { anchor = null; return; }
    const top = node.getBoundingClientRect().top;
    const kids = Array.from(node.children);
    const i = anchorIndex(kids.map((k) => { const r = k.getBoundingClientRect(); return { top: r.top - top, bottom: r.bottom - top }; }));
    anchor = i < 0 ? null : { el: kids[i], offset: offsetOf(kids[i]) };
  };
  const mo = new MutationObserver(() => {
    const a = anchor;
    const shift = anchorShift(node.scrollTop, a?.offset ?? null, a && a.el.isConnected && a.el.parentNode === node ? offsetOf(a.el) : null);
    if (shift) node.scrollTop += shift;
    record();
  });
  mo.observe(node, { childList: true });
  node.style.overflowAnchor = 'none';
  node.addEventListener('scroll', record, { passive: true });
  record();
  return {
    destroy() {
      mo.disconnect();
      node.removeEventListener('scroll', record);
    },
  };
}
