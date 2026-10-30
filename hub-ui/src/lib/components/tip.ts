// `Tip`: the hover tooltip of an icon-only control (the rail's page icons, a fold button) and of a row whose name is
// cut (plan library stage 5 A3.3, notes N1 and the motion table). Used as an action: `use:tip={'To-do (⌘3)'}`.
//
// - Text only, one line per "\n": the first line in the text colour, the others muted under it (a crate's full path,
//   then "61 files"). It names what the pointer rests on; anything to read or click goes into an InfoTip or a menu.
// - Opens after TIP_DELAY_MS (500 ms) of hover, so a pointer crossing the rail flashes nothing; while another tip is
//   open or just closed (InfoTips too, tipRegistry.ts), the next opens at once and without a fade, so moving down the
//   rail reads each name straight away. Keyboard focus (a focus ring) opens it at once, without a fade. It closes at
//   once: the pointer leaves, a press, a scroll, Escape, focus leaves.
// - Fades and grows from scale(.97) out of its trigger in --t-pop (base.css `.dj-tip`), placed by `placeTip`:
//   `side: 'right'` beside the trigger (the rail), `'below'` under it at the pointer (a row, as macOS does).
// - `cut`: only when the text is cut ("…"): `true` checks the element itself, a selector checks the element inside it
//   that ends in "…" (a row's name).
// - In the top layer (popover API), so no list, panel or dialog clips it. While open the trigger is described by it
//   (`aria-describedby`); the trigger keeps its own `aria-label` (an icon-only button needs one anyway).
// - Never together with a native `title` on the same element (two tooltips): the action takes the title away.
// - `show`: open for good, outside the one-at-a-time rule, following its trigger on scroll (the gallery only).
import { openTiming, placeTip, TIP_DELAY_MS, type TipSide } from './infoTipModel';
import { tipClosed, tipGone, tipOpened, tipWarmth } from './tipRegistry';

export type TipOptions = { text: string; side?: TipSide; cut?: boolean | string; show?: boolean };
export type TipParams = string | TipOptions | null | undefined;

const norm = (p: TipParams): TipOptions | null => {
  if (!p) return null;
  const o = typeof p === 'string' ? { text: p } : p;
  return o.text ? o : null;
};
let ids = 0;

export function tip(node: HTMLElement, params: TipParams) {
  let opts = norm(params);
  let el: HTMLDivElement | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let pointerX: number | undefined;
  let described: string | null = null;   // the trigger's own aria-describedby, given back on close
  const id = `dj-tip-${++ids}`;

  const takeTitle = () => { if (node.hasAttribute('title')) node.removeAttribute('title'); };
  takeTitle();

  function isCut(): boolean {
    if (!opts?.cut) return true;
    const t = opts.cut === true ? node : node.querySelector<HTMLElement>(opts.cut);
    return !!t && t.scrollWidth > t.clientWidth + 0.5;
  }
  function fill(target: HTMLDivElement, text: string) {
    target.replaceChildren(...text.split('\n').map((line, i) => {
      const s = document.createElement('span');
      s.className = i ? 'lb' : 'ln';
      s.textContent = line;
      return s;
    }));
  }
  function place() {
    if (!el || !opts) return;
    const r = node.getBoundingClientRect();
    const p = placeTip({ left: r.left, top: r.top, width: r.width, height: r.height },
      { width: el.offsetWidth, height: el.offsetHeight }, { width: innerWidth, height: innerHeight },
      opts.side ?? 'below', opts.side === 'right' ? undefined : pointerX);
    el.style.left = `${p.left}px`;
    el.style.top = `${p.top}px`;
    el.style.transformOrigin = p.origin;
  }
  function open(fade: boolean) {
    clearTimeout(timer);
    if (!opts || el || !isCut()) return;
    el = document.createElement('div');
    el.id = id;
    el.className = `dj-tip${fade ? ' fade' : ''}`;
    el.setAttribute('role', 'tooltip');
    el.setAttribute('popover', 'manual');
    fill(el, opts.text);
    document.body.append(el);
    if (el.showPopover) el.showPopover();
    place();
    described = node.getAttribute('aria-describedby');
    node.setAttribute('aria-describedby', described ? `${described} ${id}` : id);
    if (!opts.show) {
      tipOpened(close);
      addEventListener('scroll', close, true);
      addEventListener('keydown', key, true);
      addEventListener('resize', close);
    } else {
      addEventListener('scroll', place, true);
      addEventListener('resize', place);
    }
  }
  function detach(): boolean {
    clearTimeout(timer);
    if (!el) return false;
    removeEventListener('scroll', close, true);
    removeEventListener('keydown', key, true);
    removeEventListener('resize', close);
    removeEventListener('scroll', place, true);
    removeEventListener('resize', place);
    el.remove();
    el = null;
    if (described) node.setAttribute('aria-describedby', described);
    else node.removeAttribute('aria-describedby');
    described = null;
    return true;
  }
  function close() {
    const shown = opts?.show;
    if (detach() && !shown) tipClosed(close);
  }
  function key(e: KeyboardEvent) { if (e.key === 'Escape') close(); }

  function enter(e: PointerEvent) {
    pointerX = e.clientX;
    if (!opts || opts.show || el) return;
    const t = openTiming('hover', performance.now(), tipWarmth(close), TIP_DELAY_MS);
    if (t.delay === 0) open(t.fade);
    else timer = setTimeout(() => open(t.fade), t.delay);
  }
  function move(e: PointerEvent) { if (!el) pointerX = e.clientX; }
  function leave() { if (!opts?.show) close(); }
  function focus() { if (opts && !opts.show && node.matches(':focus-visible')) open(false); }

  node.addEventListener('pointerenter', enter);
  node.addEventListener('pointermove', move);
  node.addEventListener('pointerleave', leave);
  node.addEventListener('pointerdown', leave);
  node.addEventListener('focus', focus);
  node.addEventListener('blur', leave);
  if (opts?.show) open(false);

  return {
    update(next: TipParams) {
      const was = opts;
      opts = norm(next);
      takeTitle();
      if (!opts) { close(); return; }
      if (el && was?.show !== opts.show) { close(); if (opts.show) open(false); return; }
      if (el) { fill(el, opts.text); place(); }
      else if (opts.show) open(false);
    },
    destroy() {
      node.removeEventListener('pointerenter', enter);
      node.removeEventListener('pointermove', move);
      node.removeEventListener('pointerleave', leave);
      node.removeEventListener('pointerdown', leave);
      node.removeEventListener('focus', focus);
      node.removeEventListener('blur', leave);
      if (detach()) tipGone(close);
    },
  };
}
