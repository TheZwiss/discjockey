// The measuring half of a grow list (design system §11, issue 10), shared by ToggleGroup `grow` and Surface `grow`:
// above its minimum, a cut list rounds its rows' area down to whole rows plus the peek (growSpare) and hands the px
// above that to its host (Panel's spacer above the foot, GROW_SPARE), measured from the space it is given (its box
// plus what the spacer holds), so applying the spare changes nothing. `node` is the list's scroller; its box is the
// Surface around it, whose min-height and `--min-rows` (set in CSS) are the minimum. Outside a host the list simply
// ends where its space ends. The host comes from the component (getContext only works there).
import { growSpare, type GrowSpareHost } from './toggleModel';

export function growFill(node: HTMLElement, host: GrowSpareHost | undefined) {
  let stop = () => {};
  const start = (h: GrowSpareHost | undefined) => {
    const box = node.closest<HTMLElement>('[data-surface]');
    if (!h || !box) return () => {};
    const leave = h.join();
    const px = (v: string) => parseFloat(v) || 0;
    let frame = 0;
    const measure = () => {
      const [a, b] = Array.from(node.children) as HTMLElement[];
      const height = box.getBoundingClientRect().height;
      h.set(growSpare({
        given: height + h.height(), chrome: height - node.clientHeight, content: node.scrollHeight,
        pitch: a && b ? b.getBoundingClientRect().top - a.getBoundingClientRect().top : 0,
        rule: b ? px(getComputedStyle(b).borderTopWidth) : 0,
        // the min-height holds the peek (--peek), so the cut above it repeats the min-height's own
        floor: px(getComputedStyle(box).minHeight),
        minRows: px(getComputedStyle(box).getPropertyValue('--min-rows')),
      }));
    };
    // set on the next frame, not inside the observer's callback, so the resize it causes is a new observation
    const ro = new ResizeObserver(() => { cancelAnimationFrame(frame); frame = requestAnimationFrame(measure); });
    ro.observe(box);
    return () => { ro.disconnect(); cancelAnimationFrame(frame); h.set(0); leave(); };
  };
  stop = start(host);
  return {
    update(next: GrowSpareHost | undefined) { stop(); stop = start(next); },
    destroy() { stop(); },
  };
}
