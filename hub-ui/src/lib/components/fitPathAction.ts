// Fills a path's two spans (head, tail) with the form of the path that fits the element's width (fitPath), measured
// with the element's own font, again whenever its width changes or the fonts finish loading. Used by
// WatchedFolderList's rows and by a Surface head's `fitLabel`; the spans start empty in the markup, so only this action
// writes them. `Options.room`: the width the path may take when it is not the element's own (a label in a head
// shares the line with its summary and buttons; the label itself only takes what its text needs).
import { fitMiddle } from '$lib/format';
import { fitPath } from './watchedFoldersModel';

/** `wrapRoom`: the width the path may take on a line of its own. Given, a path that doesn't fit whole in `room` is
 *  tried against it, because its element's neighbours wrap below it when it takes that much (a head's link). */
export type FitOptions = {
  room?: (el: HTMLElement) => number; wrapRoom?: (el: HTMLElement) => number; observe?: (el: HTMLElement) => HTMLElement;
};

/** The width inside a head: what its label may take when its other children wrap onto the next line. */
export function headInner(el: HTMLElement): number {
  const parent = el.parentElement;
  if (!parent) return 0;
  const cs = getComputedStyle(parent);
  return parent.clientWidth - (parseFloat(cs.paddingLeft) || 0) - (parseFloat(cs.paddingRight) || 0);
}

/** The width a head's label may take: the head's inner width less what its other children and the gaps take. */
export function headRoom(el: HTMLElement): number {
  const parent = el.parentElement;
  if (!parent) return 0;
  const cs = getComputedStyle(parent);
  const others = Array.from(parent.children).filter((c) => c !== el);
  const gap = parseFloat(cs.columnGap) || 0;
  const inner = headInner(el);
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
    const fitsIn = (w: number) => (text: string) => !ctx || w === 0 || ctx.measureText(text).width <= w;
    if (ctx) ctx.font = `${s.fontStyle} ${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
    let r = fitPath(current, fitsIn(width));
    if (opts.wrapRoom) {
      // not whole beside its neighbours: on a line of its own it may take the whole inner width (they wrap below)
      const whole = fitPath(current, () => true);
      if (r.head + r.tail !== whole.head + whole.tail) r = fitPath(current, fitsIn(opts.wrapRoom(el)));
    }
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

/** A name's text in the form that fits the element's width (fitMiddle: the middle gives way, both ends stay), measured
 *  with the element's own font, again when its width changes or the fonts finish loading. MiddleText uses it. */
export function fitMiddleAction(el: HTMLElement, text: string) {
  let current = text;
  const ctx = document.createElement('canvas').getContext('2d');
  function run() {
    const width = el.getBoundingClientRect().width;
    // no canvas (tests) or not laid out yet: the whole text, and the element's ellipsis does the rest
    if (!ctx || width === 0) { el.textContent = current; return; }
    const s = getComputedStyle(el);
    ctx.font = `${s.fontStyle} ${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
    el.textContent = fitMiddle(current, (t) => ctx.measureText(t).width <= width);
  }
  const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(run);
  ro?.observe(el);
  run();
  void document.fonts?.ready.then(run);
  return {
    update(t: string) { current = t; run(); },
    destroy() { ro?.disconnect(); },
  };
}

/** A Surface head's label: the path whole in the head's free width, else on a line of its own with the head's links below it
 *  (`Surface .head.wraps`), and cut only when even that is too narrow; re-fitted when the head resizes. */
export function fitHeadLabel(el: HTMLElement, path: string) {
  return fitPathAction(el, path, { room: headRoom, wrapRoom: headInner, observe: (e) => e.parentElement ?? e });
}
