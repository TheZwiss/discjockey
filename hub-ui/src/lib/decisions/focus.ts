// Focus that follows a panel's change (issue 33 stage B): a button that was pressed is gone (Replace → Stop, ✕, Undo this
// one), and the browser drops focus on the page. It goes to the next thing to press, only when it was lost: never out of
// the list, a dialog or a field the user moved to.
import { tick } from 'svelte';

/** Focus is on the page (or on an element that left the document). */
export function focusLost(): boolean {
  const a = document.activeElement;
  return !a || a === document.body || !a.isConnected;
}
/** After the DOM has caught up: focus `find()`'s element when focus was lost. */
export async function refocus(find: () => HTMLElement | null | undefined): Promise<void> {
  await tick();
  if (typeof document === 'undefined' || !focusLost()) return;
  find()?.focus();
}
