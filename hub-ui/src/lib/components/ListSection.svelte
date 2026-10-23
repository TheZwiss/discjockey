<script lang="ts">
  // A section head inside one list Surface (design system §7, To-do): the list's rows come in groups, and each group
  // is named here, as a row-high head between them (name · count · one-line hint), the way Mail groups by date. It
  // sits among the rows as a sibling (the rows stay direct children of the list, so their rules and columns hold) and
  // sticks to the top of the list's scroller while its rows pass, so the group in view is always named; the next head
  // pushes it away. It is a heading (level 3) for screen readers. The head is the scroller's top edge while stuck, so
  // a Surface with sections doesn't fade its top end (Surface CSS). `data-list-section` marks it for that rule.
  type Props = { label: string; summary?: string; hint?: string; test?: string };
  let { label, summary, hint, test }: Props = $props();
</script>

<div class="section" data-list-section data-test={test}>
  <span class="title" role="heading" aria-level="3">{label}</span>
  {#if summary}<span class="summary">{summary}</span>{/if}
  {#if hint}<span class="hint">{hint}</span>{/if}
</div>

<style>
  /* the caption's 16 px inset, so the name starts where the rows' covers do */
  /* the line under it is a shadow on the next row's own rule, so it stays one hairline and travels with the head
     while it is stuck */
  .section { position: sticky; top: 0; z-index: 1; display: flex; align-items: center; gap: var(--s-2);
    min-height: var(--h-section); padding: 0 var(--s-4); background: var(--surface);
    box-shadow: 0 var(--bw) 0 var(--line-soft); min-width: 0; white-space: nowrap; }
  .title { flex: none; color: var(--text); font-size: var(--fs-small); font-weight: var(--fw-semi); }
  .summary { flex: none; color: var(--text-muted); font-size: var(--fs-small); font-variant-numeric: tabular-nums; }
  .hint { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-label);
    font-size: var(--fs-small); }
</style>
