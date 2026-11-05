<script lang="ts">
  import type { Quality } from '../bridge/types';
  import Badge from './Badge.svelte';
  // `checked` false: an imported file whose sound isn't judged yet. Its quality is only the codec's guess, so the badge
  // is neutral (no quality colour, no kHz) and says so; the colours come back when the sound check has run.
  // `titled` false: no title of its own, where a Tip already says it (TrackHead's state line: its word, or the badge's
  // Tip when the word is hidden), so one hover never shows two tooltips.
  let { quality, label, upgrade = false, checked = true, titled = true }: { quality: Quality; label: string;
    upgrade?: boolean; checked?: boolean; titled?: boolean } = $props();
</script>

{#if checked}
  <span class="qb"><Badge tone={quality} text={label} />{#if upgrade}<span title={titled ? 'Upgrade ready' : undefined}><Badge tone="accent"
        text="↑" /></span>{/if}</span>
{:else}
  <span class="qb" title={titled ? "The sound hasn't been checked yet" : undefined} data-test="not-checked"><Badge tone="muted"
      text="Not checked" /></span>
{/if}

<style>
  .qb { display: inline-flex; gap: var(--s-1); align-items: center; }
</style>
