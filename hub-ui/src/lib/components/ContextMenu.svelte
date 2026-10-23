<script lang="ts" module>
  /** `key`: unique among the items when two labels can be the same (two profiles named "Person 1"; the label is the
   *  default key). `note`: a quiet mark after the label, in its own column ("signed in", "default browser"); `good`
   *  colours it as a working state. */
  export type MenuItem = { label: string; onpick: () => void; test?: string; key?: string; note?: string | null;
    good?: boolean };
</script>

<script lang="ts">
  // Small menu at the pointer (right-click) or under a button (Segmented's "More"). Closes on a pick, a click
  // elsewhere, Esc, resize, any scroll (it is fixed, so it would drift from what it belongs to) and when the window
  // loses focus. Never leaves the window: near the right or bottom edge it shifts back in. `focusFirst` (opened from
  // the keyboard) puts focus on the first item and opens it without its fade (keyboard actions never animate, spec §6);
  // arrows, Home and End move between items.
  let { x, y, items, onclose, test, focusFirst = false }:
    { x: number; y: number; items: MenuItem[]; onclose: () => void; test?: string; focusFirst?: boolean } = $props();
  const EDGE = 8;
  let el: HTMLDivElement | undefined = $state();
  let size = $state({ w: 0, h: 0 });
  $effect(() => { if (el) size = { w: el.offsetWidth, h: el.offsetHeight }; });
  $effect(() => { if (el && focusFirst) el.querySelector<HTMLButtonElement>('[role=menuitem]')?.focus(); });
  // capture: a scroll of any list or column, not only the window's own
  $effect(() => {
    const close = () => onclose();
    window.addEventListener('scroll', close, true);
    return () => window.removeEventListener('scroll', close, true);
  });
  function key(e: KeyboardEvent) {
    const all = Array.from(el?.querySelectorAll<HTMLButtonElement>('[role=menuitem]') ?? []);
    if (!all.length) return;
    const i = all.indexOf(document.activeElement as HTMLButtonElement);
    const to = e.key === 'ArrowDown' ? (i + 1) % all.length : e.key === 'ArrowUp' ? (i - 1 + all.length) % all.length
      : e.key === 'Home' ? 0 : e.key === 'End' ? all.length - 1 : -1;
    if (to < 0) return;
    e.preventDefault();
    all[to].focus();
  }
  const left = $derived(Math.max(EDGE, Math.min(x, window.innerWidth - EDGE - size.w)));
  const top = $derived(Math.max(EDGE, Math.min(y, window.innerHeight - EDGE - size.h)));
  // it grows out of the point it was opened at (the pointer, or the button's bottom-left corner)
  const origin = $derived(`${x - left}px ${y - top}px`);
</script>

<svelte:window onclick={onclose} onblur={onclose} onresize={onclose}
  onkeydown={(e) => { if (e.key === 'Escape') onclose(); }} />

<div class="menu" class:instant={focusFirst} role="menu" tabindex="-1" bind:this={el} onkeydown={key} style:left="{left}px" style:top="{top}px"
  style:transform-origin={origin} data-test={test}>
  {#each items as it (it.key ?? it.label)}
    <button type="button" role="menuitem" data-test={it.test} class:noted={!!it.note}
      onclick={(e) => { e.stopPropagation(); it.onpick(); }}><span class="label">{it.label}</span>{#if it.note}<span
        class="note" class:good={it.good}>{it.note}</span>{/if}</button>
  {/each}
</div>

<style>
  /* popover material (the lightest layer); fades in and grows from .97 out of where it was opened (spec §6: ≤ 150 ms),
     goes at once when it closes. Opened from the keyboard it is there at once (.instant) */
  .menu { position: fixed; z-index: 20; display: flex; flex-direction: column; min-width: 160px; padding: var(--s-1);
    background: var(--popover-bg); border: var(--bw) solid var(--popover-line); border-radius: var(--r-surface);
    box-shadow: var(--surface-highlight), var(--shadow);
    transition: opacity var(--t-pop) var(--ease), transform var(--t-pop) var(--ease); }
  @starting-style { .menu { opacity: 0; transform: scale(.97); } }
  .menu.instant { transition: none; }
  /* items are rows: they light up (never darker than the menu) and stay lit while held, without shrinking */
  button { color: var(--text); text-align: left; padding: var(--s-1) var(--s-2); border-radius: var(--r-ctl);
    font-size: var(--fs-small); }
  button:hover, button:focus-visible, button:active { background: var(--ctl-press); }
  button:active { transform: none; }
  button:focus-visible { outline-offset: -2px; }
  /* a noted item: the label, then its note at the right edge (a column, so notes line up down the menu) */
  .noted { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: var(--s-4); align-items: baseline; }
  .label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .note { color: var(--text-label); font-size: var(--fs-label); white-space: nowrap; }
  .note.good { color: var(--risk-safe); }
</style>
