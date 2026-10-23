// True while a file is dragged over the window (document-level counter; plan 64.5). Never an HTML5 drag source.
import { readable } from 'svelte/store';

/** Calls `set(true)` while a file (not text from the page) is dragged over `target`, `set(false)` once it leaves or
 *  is dropped. Returns the clean-up. */
function watchFileDrags(target: EventTarget, set: (on: boolean) => void): () => void {
  let depth = 0;
  const hasFiles = (e: Event) => {
    const dt = (e as DragEvent).dataTransfer;
    return !!dt && [...dt.types].includes('Files');
  };
  const enter = (e: Event) => { if (!hasFiles(e)) return; depth++; set(true); };
  const leave = (e: Event) => { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) set(false); };
  const end = () => { depth = 0; set(false); };
  target.addEventListener('dragenter', enter);
  target.addEventListener('dragleave', leave);
  target.addEventListener('drop', end);
  target.addEventListener('dragend', end);
  return () => {
    target.removeEventListener('dragenter', enter);
    target.removeEventListener('dragleave', leave);
    target.removeEventListener('drop', end);
    target.removeEventListener('dragend', end);
  };
}

export const dragging = readable(false, (set) => {
  if (typeof document === 'undefined') return;
  return watchFileDrags(document, set);
});

/** The drop catcher (#drop-catcher in index.html): an empty element over the whole window that pywebview's drop
 *  handler sits on. pywebview sends the whole event to Python, the element it sits on included with everything inside
 *  it, so it must not sit on the document (that was the whole page on every dragover, and the window froze). The
 *  catcher is hit only while a file is dragged (class "on"), so the drop lands on it; clicks never do. */
export function catchDrops(target: EventTarget, catcher: { classList: { toggle(c: string, on: boolean): unknown } }) {
  return watchFileDrags(target, (on) => { catcher.classList.toggle('on', on); });
}
