<script lang="ts">
  // OUTDATED (design system §7): use ListPanelFrame. Kept until phase 2 ends.
  // A thin wrapper so pages not yet redesigned get the docked fixed panel and the 900 px centred list at once.
  // `panelWidth` is ignored (the panel width is fixed); `.legacy` keeps the padding and scrolling the old panel had.
  import type { Snippet } from 'svelte';
  import ListPanelFrame from '../frames/ListPanelFrame.svelte';
  let { main, panel, emptyPanel = 'Pick a track to see its details.' }:
    { panelWidth?: number; main: Snippet; panel?: Snippet | null; emptyPanel?: string } = $props();
</script>

{#snippet legacy()}<div class="legacy">{@render panel?.()}</div>{/snippet}

<ListPanelFrame {main} panel={panel ? legacy : null} {emptyPanel} />

<style>
  .legacy { padding: var(--s-4); overflow-y: auto; height: 100%; display: flex; flex-direction: column; gap: var(--s-3);
    min-height: 0; }
</style>
