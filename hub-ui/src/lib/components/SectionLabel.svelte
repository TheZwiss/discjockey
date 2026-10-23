<script lang="ts">
  // OUTDATED (design system §7): use a Surface label. Kept until phase 2 ends.
  let { text, count, hint }: { text: string; count?: number | null; hint?: string } = $props();
</script>

<div class="sl">
  <span class="caps">{text}</span>
  {#if count !== undefined && count !== null}<span class="n">{count}</span>{/if}
  {#if hint}<span class="hint">· {hint}</span>{/if}
</div>

<style>
  .sl { display: flex; align-items: baseline; gap: 6px; margin-top: var(--s-2); }
  .n { color: var(--text-label); font-size: var(--fs-label); font-variant-numeric: tabular-nums; }
  .hint { color: var(--text-label); font-size: var(--fs-small); }
</style>
