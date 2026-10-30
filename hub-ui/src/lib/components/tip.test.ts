// The Tip action against a small stand-in DOM (the tests run in Node without a DOM library): just the element and
// window surface tip.ts touches, built on Node's EventTarget, with fake timers for the waits.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { tip, type TipParams } from './tip';
import { WARM_MS } from './infoTipModel';

class FakeEl extends EventTarget {
  id = '';
  className = '';
  textContent = '';
  style: Record<string, string> = {};
  children: FakeEl[] = [];
  attrs = new Map<string, string>();
  focusVisible = false;
  rect = { left: 10, top: 100, width: 30, height: 30, right: 40, bottom: 130 };
  scrollWidth = 0;
  clientWidth = 0;
  offsetWidth = 120;
  offsetHeight = 22;
  constructor(public tag: string) { super(); }
  setAttribute(k: string, v: string) { this.attrs.set(k, v); }
  getAttribute(k: string) { return this.attrs.get(k) ?? null; }
  hasAttribute(k: string) { return this.attrs.has(k); }
  removeAttribute(k: string) { this.attrs.delete(k); }
  replaceChildren(...c: FakeEl[]) { this.children = c; }
  append(...c: FakeEl[]) { this.children.push(...c); }
  remove() { body.children = body.children.filter((x) => x !== this); }
  showPopover() {}
  getBoundingClientRect() { return this.rect; }
  matches(sel: string) { return sel === ':focus-visible' ? this.focusVisible : false; }
  querySelector() { return null; }
  get text(): string { return [this.textContent, ...this.children.map((c) => c.text)].filter(Boolean).join('|'); }
}
const body = new FakeEl('body');
const win = new EventTarget();
const ev = (type: string, extra: Record<string, unknown> = {}) => Object.assign(new Event(type), extra);
const open = () => body.children.filter((c) => c.className.startsWith('dj-tip'));

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] });
  body.children = [];
  vi.stubGlobal('document', { createElement: (t: string) => new FakeEl(t), body });
  vi.stubGlobal('addEventListener', (...a: Parameters<EventTarget['addEventListener']>) => win.addEventListener(...a));
  vi.stubGlobal('removeEventListener', (...a: Parameters<EventTarget['removeEventListener']>) => win.removeEventListener(...a));
  vi.stubGlobal('innerWidth', 1280);
  vi.stubGlobal('innerHeight', 800);
});
afterEach(() => {
  // let every tip of a test go cold, so the next test starts with no warm tip
  vi.advanceTimersByTime(WARM_MS + 1);
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function mount(p: TipParams) {
  const node = new FakeEl('button');
  const a = tip(node as unknown as HTMLElement, p);
  return { node, a };
}

describe('tip', () => {
  it('waits 500 ms on a cold hover, and a pointer that leaves first opens nothing', () => {
    const { node, a } = mount({ text: 'To-do · 5 to look at', keys: '⌘3', side: 'right' });
    node.dispatchEvent(ev('pointerenter', { clientX: 20 }));
    vi.advanceTimersByTime(499);
    expect(open()).toHaveLength(0);
    vi.advanceTimersByTime(1);
    expect(open()).toHaveLength(1);
    expect(open()[0].className).toBe('dj-tip fade');
    expect(open()[0].text).toContain('To-do · 5 to look at|⌘3');
    expect(node.getAttribute('aria-describedby')).toBe(open()[0].id);
    node.dispatchEvent(ev('pointerleave'));
    expect(open()).toHaveLength(0);
    expect(node.hasAttribute('aria-describedby')).toBe(false);
    a.destroy();

    const b = mount('Sync');
    vi.advanceTimersByTime(WARM_MS + 1);
    b.node.dispatchEvent(ev('pointerenter', { clientX: 20 }));
    vi.advanceTimersByTime(300);
    b.node.dispatchEvent(ev('pointerleave'));
    vi.advanceTimersByTime(500);
    expect(open()).toHaveLength(0);
    b.a.destroy();
  });

  it('opens the next one at once and without a fade, and keeps one open', () => {
    const a = mount('Dashboard');
    const b = mount('Sync');
    a.node.dispatchEvent(ev('pointerenter', { clientX: 20 }));
    vi.advanceTimersByTime(500);
    b.node.dispatchEvent(ev('pointerenter', { clientX: 20 }));   // still over a: a is open
    expect(open().map((t) => t.text)).toEqual(['Sync']);
    expect(open()[0].className).toBe('dj-tip');
    b.node.dispatchEvent(ev('pointerleave'));
    vi.advanceTimersByTime(200);
    a.node.dispatchEvent(ev('pointerenter', { clientX: 20 }));   // just closed: warm
    expect(open().map((t) => t.text)).toEqual(['Dashboard']);
    a.a.destroy();
    b.a.destroy();
  });

  it('closes on a scroll and removes its window listeners', () => {
    const add = vi.spyOn(win, 'addEventListener');
    const remove = vi.spyOn(win, 'removeEventListener');
    const { node, a } = mount('Playlists');
    node.dispatchEvent(new Event('focus'));   // no focus ring: a pointer's focus opens nothing
    expect(open()).toHaveLength(0);
    node.focusVisible = true;
    node.dispatchEvent(new Event('focus'));
    expect(open()).toHaveLength(1);
    expect(open()[0].className).toBe('dj-tip');   // keyboard: at once, no fade
    win.dispatchEvent(new Event('scroll'));
    expect(open()).toHaveLength(0);
    expect(remove.mock.calls.map((c) => c[0]).sort()).toEqual(add.mock.calls.map((c) => c[0]).sort());
    a.destroy();
  });

  it('Escape closes the open tip and goes no further; with none open it passes', () => {
    const { node, a } = mount('Library');
    node.focusVisible = true;
    node.dispatchEvent(new Event('focus'));
    const esc = ev('keydown', { key: 'Escape' });
    const stop = vi.spyOn(esc, 'stopPropagation');
    win.dispatchEvent(esc);
    expect(open()).toHaveLength(0);
    expect(stop).toHaveBeenCalled();
    const again = ev('keydown', { key: 'Escape' });
    const stop2 = vi.spyOn(again, 'stopPropagation');
    win.dispatchEvent(again);
    expect(stop2).not.toHaveBeenCalled();
    a.destroy();
  });

  it('destroy removes an open tip and stops a pending one', () => {
    const a = mount('Settings');
    a.node.dispatchEvent(ev('pointerenter', { clientX: 20 }));
    a.a.destroy();
    vi.advanceTimersByTime(600);
    expect(open()).toHaveLength(0);
    const b = mount({ text: 'Rekordbox Library › Bounce\n61 files', show: true });
    expect(open().map((t) => t.text)).toEqual(['Rekordbox Library › Bounce|61 files']);
    b.a.destroy();
    expect(open()).toHaveLength(0);
  });

  it('takes the native title away and shows a cut-only tip only while the text is cut', () => {
    const node = new FakeEl('span');
    node.setAttribute('title', 'Hard_Bounce');
    const a = tip(node as unknown as HTMLElement, { text: 'Hard_Bounce', cut: true });
    expect(node.hasAttribute('title')).toBe(false);
    node.focusVisible = true;
    node.scrollWidth = 100; node.clientWidth = 100;
    node.dispatchEvent(new Event('focus'));
    expect(open()).toHaveLength(0);
    node.scrollWidth = 180;
    node.dispatchEvent(new Event('focus'));
    expect(open()).toHaveLength(1);
    a.destroy();
  });
});
