<script lang="ts">
  import type { Quality } from '../bridge/types';
  import Badge from './Badge.svelte';
  let { quality, label, upgrade = false }: { quality: Quality; label: string; upgrade?: boolean } = $props();
</script>

<span class="qb"><Badge tone={quality} text={label} />{#if upgrade}<span title="Upgrade ready"><Badge tone="accent"
      text="↑" /></span>{/if}</span>

<style>
  .qb { display: inline-flex; gap: var(--s-1); align-items: center; }
</style>
