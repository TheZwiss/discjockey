<script lang="ts" generics="K extends string">
  // OUTDATED (design system §7): use ToggleGroup or Segmented. Kept until phase 2 ends.
  import type { Quality } from '../bridge/types';
  import Chip from './Chip.svelte';
  type Option = { key: K; label: string; count?: number | null; quality?: Quality | null };
  let { options, value, onchange, hideZero = false, label = 'Filter' }:
    { options: Option[]; value: K; onchange: (k: K) => void; hideZero?: boolean; label?: string } = $props();
  const shown = $derived(options.filter((o) => !hideZero || o.count !== 0 || o.key === value));
</script>

<div class="chips" role="group" aria-label={label}>
  {#each shown as o (o.key)}
    <Chip label={o.label} count={o.count} quality={o.quality} active={o.key === value} onclick={() => onchange(o.key)} />
  {/each}
</div>

<style>
  .chips { display: flex; gap: 6px; flex-wrap: wrap; }
</style>
