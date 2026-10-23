<script lang="ts">
  // OUTDATED (design system §7): use ToggleGroup or Segmented. Kept until phase 2 ends.
  import type { Quality } from '../bridge/types';
  let { label, count, quality, active = false, onclick, dim = false }:
    { label: string; count?: number | null; quality?: Quality | null; active?: boolean; onclick?: () => void;
      dim?: boolean } = $props();
</script>

<button type="button" class="chip" class:active class:dim={dim || count === 0} aria-pressed={active} {onclick}>
  {#if quality}<span class="dot {quality}"></span>{/if}
  <span>{label}</span>
  {#if count !== undefined && count !== null}<span class="n">{count}</span>{/if}
</button>

<style>
  .chip {
    display: inline-flex; align-items: center; gap: 6px; padding: 3px 11px; border-radius: var(--r-pill);
    border: var(--bw) solid var(--line-control); background: transparent; color: var(--text-muted);
    font-size: var(--fs-small); line-height: 1.5; white-space: nowrap; transition: border-color var(--t-fast), transform var(--t-press) ease-out;
  }
  .chip:hover { border-color: var(--line-control-hover); }
  .active { border-color: var(--accent); color: var(--accent-text); background: var(--accent-wash); }
  .active:hover { border-color: var(--accent); }
  .dim:not(.active) { color: var(--text-label); }
  .n { color: var(--text-label); font-variant-numeric: tabular-nums; }
  .active .n { color: var(--accent-text); }
  .dot { width: 7px; height: 7px; border-radius: var(--r-pill); background: var(--q-other-bar); }
  .dot.lossless { background: var(--q-lossless); }
  .dot.good_lossy { background: var(--q-good); }
  .dot.weak, .dot.missing { background: var(--q-weak); }
  .dot.fake { background: var(--q-fake); }
</style>
