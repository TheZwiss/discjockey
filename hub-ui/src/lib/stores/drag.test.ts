import { describe, expect, it } from 'vitest';
import { catchDrops } from './drag';

function drag(type: string, types: string[] = ['Files']): Event {
  return Object.assign(new Event(type), { dataTransfer: { types } });
}

describe('the drop catcher', () => {
  it('is hit only while a file is dragged over the window, so the drop lands on it and not on the page', () => {
    const doc = new EventTarget();
    const classes = new Set<string>();
    const catcher = { classList: { toggle: (c: string, on: boolean) => { if (on) classes.add(c); else classes.delete(c); } } };
    const on = () => classes.has('on');
    catchDrops(doc, catcher);
    expect(on()).toBe(false);
    doc.dispatchEvent(drag('dragenter', ['text/plain'])); // a text drag inside the page: not a file
    expect(on()).toBe(false);
    doc.dispatchEvent(drag('dragenter')); // over a row
    expect(on()).toBe(true);
    doc.dispatchEvent(drag('dragenter')); // ...then over the catcher itself
    doc.dispatchEvent(drag('dragleave')); // ...leaving the row
    expect(on()).toBe(true);
    doc.dispatchEvent(drag('dragleave')); // out of the window
    expect(on()).toBe(false);
    doc.dispatchEvent(drag('dragenter'));
    doc.dispatchEvent(drag('drop'));
    expect(on()).toBe(false);
  });
});
