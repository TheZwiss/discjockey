<script lang="ts">
  // The why column of a plan row (spec §8), shared by Sync and the Gallery's ListRow demo so both read the same:
  // the tag in plain muted text, then "next sync" led by a 6 px yellow dot (spec §4: yellow means waiting or
  // limited). The dot carries the state and separates it from the tag; the words stay muted, so a list where many
  // rows wait doesn't outshout its track names (spec §11, "next sync").
  import NextDot from './NextDot.svelte';
  let { tag, next }: { tag: string | null; next: boolean } = $props();
  const NEXT = "Ticked, but today's downloads are used up before it. It waits for the next sync.";
</script>

{#if tag}<span class="tag" data-test="sync-tag">{tag}</span>{/if}
{#if next}<span class="next" data-test="sync-next" title={NEXT}><NextDot />next sync</span>{/if}

<style>
  .tag { flex: 0 1 auto; }
  .next { flex: none; display: inline-flex; align-items: center; gap: var(--s-1); }
</style>
