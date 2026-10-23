<script lang="ts">
  // One on/off row (design system §4): switch · lead (cover or icon) · name · count on a fixed grid, so every row of
  // a group lines up. The whole row is the button (`role="switch"`, `aria-checked`); lives inside a
  // `Surface kind="list"` (ToggleGroup), where the rule checker lets rows fill the width. An off row dims its name,
  // count and lead. `disabled` keeps it focusable (`aria-disabled`, like Button) but ignores clicks, and the whole
  // row reads as unavailable (muted name and count, faded lead, faded switch).
  // Lead: a 24 px Cover, or a glyph in `<span class="toggle-icon">↓</span>` (the bordered icon box styled here).
  import type { Snippet } from 'svelte';
  import Switch from './Switch.svelte';
  import type { ToggleItem } from './toggleModel';

  let { item, lead, onchange, disabled = false, title, test }:
    { item: ToggleItem; lead?: Snippet; onchange: (key: string, on: boolean) => void; disabled?: boolean;
      /** the tooltip, e.g. why a disabled row is off (ToggleGroup `disabledReason`) */
      title?: string; test?: string } = $props();

  function click() { if (!disabled) onchange(item.key, !item.on); }
</script>

<button type="button" role="switch" aria-checked={item.on} aria-disabled={disabled || undefined} class="row"
  class:off={!item.on} class:no-lead={!lead} class:locked={disabled} data-key={item.key} data-test={test} {title}
  onclick={click}>
  <Switch on={item.on} label={item.label} {disabled} />
  {#if lead}<span class="lead" aria-hidden="true">{@render lead()}</span>{/if}
  <span class="name">{item.label}</span>
  <span class="count">{item.count ?? ''}</span>
</button>

<style>
  .row { display: grid; grid-template-columns: 30px 24px 1fr 32px; align-items: center; column-gap: var(--s-3);   /* ListRow's column gap */
    width: 100%; min-height: var(--h-row); padding: 0 var(--s-4); text-align: left; color: var(--text); font-size: var(--fs-body);
    transition: background var(--t-hover) var(--ease); }
  .row.no-lead { grid-template-columns: 30px 1fr 32px; }
  .row:hover:not(.locked) { background: var(--ctl-hover); }
  /* the stretching knob is the press feedback; a whole row shrinking would jump */
  .row:active { transform: none; transition: background var(--t-hover) var(--ease); }
  .row:focus-visible { outline-offset: -2px; border-radius: calc(var(--r-surface) - var(--bw)); }   /* concentric with the list's corner */
  .lead { display: grid; place-items: center; width: 24px; height: 24px; overflow: hidden;
    transition: opacity var(--t-state) var(--ease); }
  .name { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    transition: color var(--t-state) var(--ease), opacity var(--t-state) var(--ease); }
  .count { text-align: right; color: var(--text-muted); font-size: var(--fs-small); font-variant-numeric: tabular-nums;
    white-space: nowrap; transition: color var(--t-state) var(--ease), opacity var(--t-state) var(--ease); }
  /* off stays readable: the user reads an off name to decide whether to turn it on (rule 8, as ListRow); the
     switch and the faded lead carry the state */
  .off .name { color: var(--text-muted); }
  .off .count { color: var(--text-label); }
  .lead > :global(.toggle-icon) { display: grid; place-items: center; width: 24px; height: 24px;
    border: var(--bw) solid var(--ctl-line); border-radius: var(--r-icon); color: var(--text-muted); font-size: var(--fs-small); }
  .off .lead { opacity: var(--dim-cover); }
  .locked:not(.off) .name, .locked:not(.off) .count { color: var(--text-muted); }
  .locked:not(.off) .lead { opacity: var(--dim-locked); }
</style>
