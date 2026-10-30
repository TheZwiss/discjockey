// `Tip`: the hover tooltip of an icon-only control (the rail's page icons, a fold button) and of a row whose name is
// cut (plan library stage 5 A3.3, notes N1 and the motion table). Used as an action:
// `use:tip={{ text: 'To-do · 5 to look at', keys: '⌘3', side: 'right' }}`, or `use:tip={'Hard_Bounce'}`.
//
// - Text only, one line per "\n": the first line in the text colour, the others muted under it (a crate's full path,
//   then "61 files"). `keys`: the shortcut as a muted key cap at the first line's end ("⌘3"), as macOS menus print
//   it. It names what the pointer rests on; anything to read or click goes into an InfoTip or a menu.
// - Opens after TIP_DELAY_MS (500 ms) of hover, so a pointer crossing the rail flashes nothing; while another tip is
//   open or just closed (InfoTips too, tipRegistry.ts), the next opens at once and without a fade, so moving down the
//   rail reads each name straight away. Keyboard focus (a focus ring) opens it at once, without a fade. Only one tip
//   is open at a time. It closes at once: the pointer leaves, a press, a scroll, focus leaves, Escape (which it then
//   keeps: one Escape closes one layer, so it doesn't also clear the field below).
// - Fades and grows from scale(.97) out of its trigger in --t-pop (base.css `.dj-tip`), placed by `placeTip`:
//   `side: 'right'` beside the trigger (the rail), `'below'` under it at the pointer (a row, as macOS does).
// - `atPointer`: for a tall, thin trigger (the browser column's edge): the tip stands beside it at the pointer's
//   height, not beside its middle (`side: 'right'`).
// - `cut`: only when the text is cut ("…"): `true` checks the element itself, a selector checks the element inside it
//   that ends in "…" (a row's name).
// - In the top layer (popover API), so no list, panel or dialog clips it. While open the trigger is described by it
//   (`aria-describedby`); the trigger keeps its own `aria-label` (an icon-only button needs one anyway).
// - Never together with a native `title` on the same element (two tooltips): the action takes the title away.
// - `show` (the gallery only): opens at once and stays through scrolls and the pointer leaving, following its
//   trigger; it still is the one open tip, so the next tip that opens closes it.
import { openTiming, placeTip, TIP_DELAY_MS, type TipSide } from './infoTipModel';
import { tipClosed, tipGone, tipOpened, tipWarmth } from './tipRegistry';

export type TipOptions = { text: string; keys?: string; side?: TipSide; cut?: boolean | string; show?: boolean;
  atPointer?: boolean };
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
  let pointerY: number | undefined;
  let described: string | null = null;   // the trigger's own aria-describedby, given back on close
  const id = `dj-tip-${++ids}`;

  const takeTitle = () => { if (node.hasAttribute('title')) node.removeAttribute('title'); };
  takeTitle();

  function isCut(): boolean {
    if (!opts?.cut) return true;
    const t = opts.cut === true ? node : node.querySelector<HTMLElement>(opts.cut);
    return !!t && t.scrollWidth > t.clientWidth + 0.5;
  }
  function fill(target: HTMLDivElement, o: TipOptions) {
    target.replaceChildren(...o.text.split('\n').map((line, i) => {
      const s = document.createElement('span');
      s.className = i ? 'lb' : 'ln';
      s.textContent = line;
      if (!i && o.keys) {
        const k = document.createElement('kbd');
        k.textContent = o.keys;
        s.append(k);
      }
      return s;
    }));
  }
  function place() {
    if (!el || !opts) return;
    const r = node.getBoundingClientRect();
    const atY = opts.atPointer && pointerY !== undefined;
    const p = placeTip({ left: r.left, top: atY ? pointerY! : r.top, width: r.width, height: atY ? 0 : r.height },
      { width: el.offsetWidth, height: el.offsetHeight }, { width: innerWidth, height: innerHeight },
      opts.side ?? 'below', opts.side === 'right' ? undefined : pointerX);
    // a tip shown for good hides while its trigger is scrolled out of the window, instead of sticking to an edge
    el.style.visibility = opts.show && (r.bottom < 0 || r.top > innerHeight) ? 'hidden' : '';
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
    fill(el, opts);
    document.body.append(el);
    if (el.showPopover) el.showPopover();
    place();
    described = node.getAttribute('aria-describedby');
    node.setAttribute('aria-describedby', described ? `${described} ${id}` : id);
    tipOpened(close);
    addEventListener('keydown', key, true);
    addEventListener('scroll', scrolled, true);
    addEventListener('resize', scrolled);
  }
  function close() {
    clearTimeout(timer);
    if (!el) return;
    removeEventListener('keydown', key, true);
    removeEventListener('scroll', scrolled, true);
    removeEventListener('resize', scrolled);
    el.remove();
    el = null;
    if (described) node.setAttribute('aria-describedby', described);
    else node.removeAttribute('aria-describedby');
    described = null;
    tipClosed(close);
  }
  function scrolled() { if (opts?.show) place(); else close(); }
  function key(e: KeyboardEvent) {
    if (e.key !== 'Escape' || !el) return;
    close();
    e.stopPropagation();
  }

  function enter(e: PointerEvent) {
    pointerX = e.clientX;
    pointerY = e.clientY;
    if (!opts || opts.show || el) return;
    const t = openTiming('hover', performance.now(), tipWarmth(close), TIP_DELAY_MS);
    if (t.delay === 0) open(t.fade);
    else timer = setTimeout(() => open(t.fade), t.delay);
  }
  function move(e: PointerEvent) { if (!el) { pointerX = e.clientX; pointerY = e.clientY; } }
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
      if (was?.show && !opts.show) { close(); return; }
      if (el) { fill(el, opts); place(); }
      else if (opts.show && !was?.show) open(false);
    },
    destroy() {
      node.removeEventListener('pointerenter', enter);
      node.removeEventListener('pointermove', move);
      node.removeEventListener('pointerleave', leave);
      node.removeEventListener('pointerdown', leave);
      node.removeEventListener('focus', focus);
      node.removeEventListener('blur', leave);
      clearTimeout(timer);
      if (el) {
        removeEventListener('keydown', key, true);
        removeEventListener('scroll', scrolled, true);
        removeEventListener('resize', scrolled);
        el.remove();
        el = null;
        tipGone(close);
      }
    },
  };
}
