// Fills a path's two spans (head, tail) with the form of the path that fits the element's width (fitPath), measured
// with the element's own font, again whenever its width changes or the fonts finish loading. Used by
// WatchedFolderList's rows; the spans start empty in the markup, so only this action writes them.
import { fitPath } from './watchedFoldersModel';

export function fitPathAction(el: HTMLElement, path: string) {
  let current = path;
  const ctx = document.createElement('canvas').getContext('2d');
  function run() {
    const [head, tail] = Array.from(el.children) as HTMLElement[];
    if (!head || !tail) return;
    const s = getComputedStyle(el);
    const width = el.getBoundingClientRect().width;
    // no canvas (tests) or not laid out yet: the whole path, and the row's ellipsis does the rest
    const fits = (text: string) => !ctx || width === 0 || ctx.measureText(text).width <= width;
    if (ctx) ctx.font = `${s.fontStyle} ${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
    const r = fitPath(current, fits);
    head.textContent = r.head;
    tail.textContent = r.tail;
  }
  const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(run);
  ro?.observe(el);
  run();
  void document.fonts?.ready.then(run);
  return {
    update(p: string) { current = p; run(); },
    destroy() { ro?.disconnect(); },
  };
}
