<script lang="ts">
  import type { Quality } from '../bridge/types';
  import Badge from './Badge.svelte';
  // `checked` false: an imported file whose sound isn't judged yet. Its quality is only the codec's guess, so the badge
  // is neutral (no quality colour, no kHz) and says so; the colours come back when the sound check has run.
  let { quality, label, upgrade = false, checked = true }: { quality: Quality; label: string; upgrade?: boolean;
    checked?: boolean } = $props();
</script>

{#if checked}
  <span class="qb"><Badge tone={quality} text={label} />{#if upgrade}<span title="Upgrade ready"><Badge tone="accent"
        text="↑" /></span>{/if}</span>
{:else}
  <span class="qb" title="The sound hasn't been checked yet" data-test="not-checked"><Badge tone="muted"
      text="Not checked" /></span>
{/if}

<style>
  .qb { display: inline-flex; gap: var(--s-1); align-items: center; }
</style>
