<script lang="ts">
  // shape: 'line' stands in for text (badge radius); 'card' for a whole card, with the card radius it will have
  let { lines = 1, height = 12, width = '100%', gap = 8, shape = 'line' }:
    { lines?: number; height?: number; width?: string; gap?: number; shape?: 'line' | 'card' } = $props();
</script>

<div class="skeleton" class:card={shape === 'card'} style:gap="{gap}px" aria-hidden="true">
  {#each Array(lines) as _, i (i)}
    <span style:height="{height}px" style:width={i === lines - 1 && lines > 1 ? '62%' : width}></span>
  {/each}
</div>

<style>
  .skeleton { display: flex; flex-direction: column; width: 100%; }
  span { display: block; border-radius: var(--r-badge); background: var(--bg-inset); animation: dj-shimmer 1.6s ease-in-out infinite; }
  .card span { border-radius: var(--r-surface); }
</style>
