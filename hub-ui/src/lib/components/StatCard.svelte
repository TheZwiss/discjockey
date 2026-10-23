<script lang="ts">
  // One quantity as a big number (design system §7): a `Surface` card with the number at the stat size (30 px,
  // tight tracking, tabular), its `unit` small beside it and the `label` under it. Nothing known yet (`null`) reads
  // "—". `children` go under the label: a ProgressBar, a Ring or a quality bar, so the number has its visual.
  // `valueTest` puts a `data-test` on the number alone (without the unit); other attributes go onto the card.
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';
  import Surface from './Surface.svelte';

  type Props = Omit<HTMLAttributes<HTMLElement>, 'children'> & {
    value: string | number | null; unit?: string; label: string; children?: Snippet; valueTest?: string;
  };
  let { value, unit, label, children, valueTest, class: className, ...rest }: Props = $props();
  const shown = $derived(value === null || value === undefined || value === '' ? '—' : String(value));
</script>

<Surface {...rest} class="stat-card {className ?? ''}">
  <div class="top">
    <div class="num"><span data-test={valueTest}>{shown}</span>{#if unit}<span class="unit">{unit}</span>{/if}</div>
    <div class="label">{label}</div>
  </div>
  {#if children}<div>{@render children()}</div>{/if}
</Surface>

<style>
  /* number and label sit close together, as one unit; the card's own gap parts them from the extra */
  .top { display: flex; flex-direction: column; gap: var(--s-1); min-width: 0; }
  .num {
    font-size: var(--fs-stat); letter-spacing: var(--ls-stat); line-height: 1; font-weight: var(--fw-bold);
    color: var(--text-strong); font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; min-width: 0;
  }
  .unit { font-size: var(--fs-body); font-weight: var(--fw-medium); color: var(--text-muted); letter-spacing: 0; margin-left: var(--s-1); }
  .label { font-size: var(--fs-label); color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
