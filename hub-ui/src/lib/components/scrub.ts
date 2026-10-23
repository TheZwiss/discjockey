// Dragging on a position bar (MiniPlayer, ComparePlayer): the bar follows the pointer while the button is held, the
// seek happens once on release. A plain click is a drag of zero length.

export function fractionAt(clientX: number, left: number, width: number): number {
  if (!(width > 0)) return 0;
  return Math.min(1, Math.max(0, (clientX - left) / width));
}

export type ScrubOptions = { move: (f: number) => void; end: (f: number) => void; cancel: () => void };

/** Svelte action. The pointer is captured, so the drag goes on when it leaves the bar. */
export function scrub(node: HTMLElement, options: ScrubOptions) {
  let o = options;
  let id: number | null = null;
  const at = (e: PointerEvent) => {
    const r = node.getBoundingClientRect();
    return fractionAt(e.clientX, r.left, r.width);
  };
  function down(e: PointerEvent) {
    if (e.button !== 0) return;
    id = e.pointerId;
    node.setPointerCapture?.(id);
    e.preventDefault();
    o.move(at(e));
  }
  function move(e: PointerEvent) { if (e.pointerId === id) o.move(at(e)); }
  function up(e: PointerEvent) {
    if (e.pointerId !== id) return;
    id = null;
    o.end(at(e));
  }
  function cancel(e: PointerEvent) {
    if (e.pointerId !== id) return;
    id = null;
    o.cancel();
  }
  const on = [['pointerdown', down], ['pointermove', move], ['pointerup', up], ['pointercancel', cancel]] as const;
  for (const [t, f] of on) node.addEventListener(t, f as EventListener);
  return {
    update(next: ScrubOptions) { o = next; },
    destroy() { for (const [t, f] of on) node.removeEventListener(t, f as EventListener); },
  };
}
