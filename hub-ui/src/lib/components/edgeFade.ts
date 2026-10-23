// Scroll edge effect (design system §11, Task 9B fix round 1): marks the ends of a scroller that have content
// beyond them (`data-fade-above`, `data-fade-below`); base.css fades a marked end. One action for every scroller
// (ToggleGroup's rows, Panel's body), so they fade the same. It measures on scroll, when the scroller or one of its
// children changes size, and when children come or go (a search, a NoteCard appearing). A child without a box
// (`display: contents`, Panel's fill slot) has no size of its own: its children are watched in its place (Task 9B
// fix round 2), so the Playlists group growing or shrinking inside the slot still re-measures the panel body.
// Children that come or go are handled one by one (final review M13): a search keystroke in a long ToggleGroup
// touches only the rows it adds or removes, with no getComputedStyle walk over the whole tree. Limit: a child is
// looked at when it arrives, so one that switches to or from `display: contents` later is not noticed (none does).
export function edgeFade(node: HTMLElement) {
  const measure = () => {
    node.toggleAttribute('data-fade-below', node.scrollHeight - node.scrollTop - node.clientHeight > 1);
    node.toggleAttribute('data-fade-above', node.scrollTop > 1);
  };
  const ro = new ResizeObserver(measure);
  // a box is observed for size; a box-less slot for its children coming and going, and its children in its place
  const add = (child: Element) => {
    if (getComputedStyle(child).display === 'contents') walk(child);
    else ro.observe(child);
  };
  const forget = (gone: Element) => {
    ro.unobserve(gone);
    for (const inner of Array.from(gone.querySelectorAll('*'))) ro.unobserve(inner);
  };
  const mo = new MutationObserver((records) => {
    for (const r of records) {
      for (const n of Array.from(r.removedNodes)) if (n instanceof Element) forget(n);
      for (const n of Array.from(r.addedNodes)) if (n instanceof Element && n.parentNode === r.target) add(n);
    }
    measure();
  });
  function walk(parent: Element) {
    mo.observe(parent, { childList: true });
    for (const child of Array.from(parent.children)) add(child);
  }
  ro.observe(node);
  walk(node);
  node.addEventListener('scroll', measure, { passive: true });
  measure();
  return {
    destroy() {
      ro.disconnect();
      mo.disconnect();
      node.removeEventListener('scroll', measure);
    },
  };
}
