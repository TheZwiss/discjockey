// Fills a path's two spans (head, tail) with the form of the path that fits the element's width (fitPath), measured
// with the element's own font, again whenever its width changes or the fonts finish loading. Used by
// WatchedFolderList's rows and by a Surface head's `fitLabel`; the spans start empty in the markup, so only this action
// writes them. `Options.room`: the width the path may take when it is not the element's own (a label in a head
// shares the line with its summary and buttons; the label itself only takes what its text needs).
import { fitPath } from './watchedFoldersModel';

export type FitOptions = { room?: (el: HTMLElement) => number; observe?: (el: HTMLElement) => HTMLElement };

/** The width a head's label may take: the head's inner width less what its other children and the gaps take. */
export function headRoom(el: HTMLElement): number {
  const parent = el.parentElement;
  if (!parent) return 0;
  const cs = getComputedStyle(parent);
  const others = Array.from(parent.children).filter((c) => c !== el);
  const gap = parseFloat(cs.columnGap) || 0;
  const inner = parent.clientWidth - (parseFloat(cs.paddingLeft) || 0) - (parseFloat(cs.paddingRight) || 0);
  return inner - others.reduce((n, c) => n + c.getBoundingClientRect().width, 0) - gap * others.length;
}

export function fitPathAction(el: HTMLElement, path: string, opts: FitOptions = {}) {
  let current = path;
  const ctx = document.createElement('canvas').getContext('2d');
  function run() {
    const [head, tail] = Array.from(el.children) as HTMLElement[];
    if (!head || !tail) return;
    const s = getComputedStyle(el);
    const width = opts.room ? opts.room(el) : el.getBoundingClientRect().width;
    // no canvas (tests) or not laid out yet: the whole path, and the row's ellipsis does the rest
    const fits = (text: string) => !ctx || width === 0 || ctx.measureText(text).width <= width;
    if (ctx) ctx.font = `${s.fontStyle} ${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
    const r = fitPath(current, fits);
    head.textContent = r.head;
    tail.textContent = r.tail;
  }
  const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(run);
  ro?.observe(opts.observe ? opts.observe(el) : el);
  run();
  void document.fonts?.ready.then(run);
  return {
    update(p: string) { current = p; run(); },
    destroy() { ro?.disconnect(); },
  };
}

/** A Surface head's label: the path in the head's free width, re-fitted when the head resizes. */
export function fitHeadLabel(el: HTMLElement, path: string) {
  return fitPathAction(el, path, { room: headRoom, observe: (e) => e.parentElement ?? e });
}
