<script lang="ts" generics="K extends string">
  // One choice of a few (design system §4): one bordered strip of segments on a single line that never wraps
  // (labels shorten with "…"), optional quality dot and count per segment (no dot at a count of 0: nothing of that quality is there). More than `max` options: the rest sit in
  // a "More ▾" menu, and the chosen one always stays on the strip (splitOptions). Replaces filter Chips.
  // Keyboard as a radio group: Tab reaches the chosen segment, arrows/Home/End choose along the strip.
  import { tick } from 'svelte';
  import ContextMenu, { type MenuItem } from './ContextMenu.svelte';
  import { isTight, splitOptions, tabStop, type SegOption } from './segmentedModel';

  let { options, value, onchange, label, max = 6, test }:
    { options: SegOption<K>[]; value: K; onchange: (k: K) => void; label: string; max?: number; test?: string } =
    $props();

  const split = $derived(splitOptions(options, value, max));
  const stop = $derived(tabStop(split.shown, value));   // the chosen segment, or the first when none is chosen
  const sub = (suffix: string) => (test ? `${test}-${suffix}` : undefined);
  const withCount = (o: SegOption<K>) => (o.count === undefined || o.count === null ? o.label : `${o.label} · ${o.count}`);

  let strip: HTMLDivElement | undefined = $state();
  let radios: HTMLDivElement | undefined = $state();
  // tight: the segments at their full labels don't fit the strip (isTight), so the unchosen ones may shorten. Measured
  // from the full labels, not from the strip's overflow, so shortening them never flips it back (no oscillation).
  let tight = $state(false);
  function natural(b: HTMLElement): number {
    const cs = getComputedStyle(b);
    const kids = [...b.children] as HTMLElement[];
    return parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight) + parseFloat(cs.columnGap || '0') * Math.max(0, kids.length - 1)
      + kids.reduce((w, k) => w + (k.classList.contains('label') ? k.scrollWidth : k.getBoundingClientRect().width), 0);
  }
  function measure() {
    if (!radios) return;
    tight = isTight([...radios.querySelectorAll<HTMLElement>(':scope > button')].map(natural), radios.clientWidth);
  }
  $effect(() => {
    void split.shown; void value;   // new labels, counts or choice: measure again once they are drawn
    if (!radios) return;
    const ro = new ResizeObserver(measure);
    ro.observe(radios);
    measure();
    return () => ro.disconnect();
  });
  let menu = $state<{ x: number; y: number; keyboard: boolean } | null>(null);
  let moreBtn: HTMLButtonElement | undefined = $state();
  const menuItems = $derived<MenuItem[]>(split.more.map((o) => ({
    label: withCount(o), test: sub(o.key), onpick: () => { menu = null; void choose(o.key); },
  })));

  async function choose(k: K) {
    if (k !== value) onchange(k);
    await tick();
    strip?.querySelector<HTMLButtonElement>(`[data-key="${CSS.escape(k)}"]`)?.focus();
  }
  function key(e: KeyboardEvent, i: number) {
    const n = split.shown.length;
    const to = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? (i + 1) % n
      : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? (i - 1 + n) % n
      : e.key === 'Home' ? 0 : e.key === 'End' ? n - 1 : -1;
    if (to < 0) return;
    e.preventDefault();
    void choose(split.shown[to].key);
  }
  function openMore(e: MouseEvent) {
    e.stopPropagation();   // the menu closes on any window click, this one included
    if (menu) { menu = null; return; }
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    menu = { x: r.left, y: r.bottom + 4, keyboard: e.detail === 0 };   // detail 0: Enter or Space, not a pointer
  }
  // Esc (or a click elsewhere) from inside the menu gives focus back to "More", so keyboard users aren't dropped
  function closeMenu() {
    const inside = !!(document.activeElement as HTMLElement | null)?.closest('[role=menu]');
    menu = null;
    if (inside) moreBtn?.focus();
  }
  // a tooltip only where the label is shortened
  function tip(e: PointerEvent, full: string) {
    const b = e.currentTarget as HTMLElement;
    const l = b.querySelector<HTMLElement>('.label');
    if (l && l.scrollWidth > l.clientWidth) b.title = full; else b.removeAttribute('title');
  }
</script>

{#if options.length}
  <div class="seg" bind:this={strip} data-test={test}>
    <div class="radios" class:tight bind:this={radios} data-tight={tight || undefined} role="radiogroup" aria-label={label}>
      {#each split.shown as o, i (o.key)}
        {@const on = o.key === value}
        <button type="button" role="radio" aria-checked={on} tabindex={o.key === stop ? 0 : -1} class:on data-key={o.key}
          data-test={sub(o.key)} onpointerenter={(e) => tip(e, o.label)} onclick={() => choose(o.key)} onkeydown={(e) => key(e, i)}>
          {#if o.dot && o.count !== 0}<span class="dot {o.dot}" aria-hidden="true"></span>{/if}
          <span class="label">{o.label}</span>
          {#if o.count !== undefined && o.count !== null}<span class="count">{o.count}</span>{/if}
        </button>
      {/each}
    </div>
    {#if split.more.length}
      <button type="button" class="more" bind:this={moreBtn} aria-haspopup="menu" aria-expanded={!!menu} data-test={sub('more')}
        onclick={openMore}>More ▾</button>
    {/if}
  </div>
{/if}
{#if menu}
  <ContextMenu x={menu.x} y={menu.y} items={menuItems} onclose={closeMenu} focusFirst={menu.keyboard} test={sub('menu')} />
{/if}

<style>
  .seg { display: flex; flex-wrap: nowrap; width: 100%; min-width: 0; height: var(--h-ctl); border: var(--bw) solid var(--ctl-line);
    border-radius: var(--r-ctl); background: var(--ctl-bg); overflow: hidden; }
  .radios { display: flex; flex-wrap: nowrap; flex: 1 1 auto; min-width: 0; }
  button { display: flex; align-items: center; justify-content: center; gap: 5px; min-width: 0; padding: 0 var(--s-2);
    font-size: var(--fs-small); color: var(--text-muted); white-space: nowrap; }
  /* equal segments (from 0, not from their labels), so a full-width strip reads as one even control; a label longer
     than its equal share keeps its width (automatic minimum, flexbox §4.5) and the others share the rest, so equal
     widths never cut a label that fits the strip (measured: RunPanel's "All 195" read "All …" at 1100) */
  .radios button { flex: 1 1 0; min-width: auto; }
  /* a tight strip (the full labels don't fit): the unchosen segments may shorten to "…" and share what is left */
  .radios.tight button:not(.on) { min-width: 0; }
  .radios button + button, .more { border-left: var(--bw) solid var(--ctl-line); }
  /* hover fades in its fill and its text together (spec §6, --t-hover) and goes at once. Only the hovered, unchosen
     segment carries the transition, so a choice (click or arrow key) changes both segments at once */
  button:hover:not(.on) { background-color: var(--ctl-hover); color: var(--text);
    transition: background-color var(--t-hover) var(--ease), color var(--t-hover) var(--ease); }
  /* joined segments don't shrink inside the strip that clips them (it would open gaps at the dividers): held down,
     a segment lights up at once instead, as a macOS segmented control does */
  button:active { transform: none; }
  button:active:not(.on) { background-color: var(--ctl-press); transition: none; }
  button:focus-visible { outline-offset: -2px; }
  /* the choice is a background image, which never transitions: a click or an arrow key moves it at once */
  .on { background-image: linear-gradient(var(--accent-wash-strong), var(--accent-wash-strong)); color: var(--accent-text); }
  /* in a tight strip the others shorten first; the chosen label keeps up to half the strip: its automatic minimum
     is its content, capped by the max-width (flexbox §4.5), while the others (.tight) may shrink to 0. Only in a
     tight strip: elsewhere the cap would cut a chosen label wider than half the strip although everything fits */
  .radios .on { min-width: auto; }
  .radios.tight .on { max-width: 50%; }
  .more { flex: none; }
  .label { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .count { flex: none; color: var(--text-label); font-variant-numeric: tabular-nums; }
  .dot { flex: none; width: 7px; height: 7px; border-radius: var(--r-pill); background: var(--q-other); }
  .dot.lossless { background: var(--q-lossless); }
  .dot.good_lossy { background: var(--q-good); }
  .dot.weak, .dot.missing { background: var(--q-weak); }
  .dot.fake { background: var(--q-fake); }
</style>
