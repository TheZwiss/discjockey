<script lang="ts">
  // One of a few things to pick, as a card that shows its state right where you click (Download limits' services:
  // name, today's usage, status). A row of them is a tablist (the caller's wrapper has role="tablist"); ← / → move
  // between them. The picked card carries the accent edge and wash; `off` (not set up) is a dashed outline, still
  // clickable (it leads to its setup). Equal cards: the caller lays them out on an equal-column grid.
  import type { Snippet } from 'svelte';

  let { title, selected = false, off = false, onclick, children, test }: {
    title: string; selected?: boolean; off?: boolean; onclick: () => void; children: Snippet; test?: string;
  } = $props();

  function key(e: KeyboardEvent) {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const tabs = [...((e.currentTarget as HTMLElement).parentElement?.querySelectorAll<HTMLElement>('[role=tab]') ?? [])];
    const i = tabs.indexOf(e.currentTarget as HTMLElement) + (e.key === 'ArrowRight' ? 1 : -1);
    tabs[(i + tabs.length) % tabs.length]?.focus();
    e.preventDefault();
  }
</script>

<button type="button" class="sel" class:on={selected} class:off role="tab" aria-selected={selected}
  tabindex={selected ? 0 : -1} data-row-hit data-surface {onclick} onkeydown={key} data-test={test}>
  <span class="title">{title}</span>
  {@render children()}
</button>

<style>
  .sel { display: flex; flex-direction: column; align-items: stretch; gap: var(--s-2); min-width: 0;
    padding: var(--s-3); text-align: left; font: inherit; color: var(--text); cursor: pointer;
    background: var(--surface); border: var(--bw) solid var(--surface-line); border-radius: var(--r-surface);
    box-shadow: var(--surface-highlight);
    transition: border-color var(--t-state) var(--ease), transform var(--t-press) var(--ease); }
  .sel:hover { border-color: var(--line-control); }
  .sel:active { transform: scale(.98); }
  .sel.on { border-color: var(--accent-line); background: linear-gradient(var(--accent-wash-strong), var(--accent-wash)); }
  .sel.off { border-style: dashed; background: none; box-shadow: none; }
  .sel:focus-visible { outline: var(--bw-accent) solid var(--accent-line); outline-offset: 2px; }
  .title { color: var(--text-strong); font-weight: var(--fw-semi); white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; }
</style>
