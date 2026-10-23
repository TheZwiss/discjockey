<script lang="ts">
  import type { ByQuality, Quality } from '../bridge/types';
  import { QUALITIES } from '../bridge/types';
  // by_quality null: not known yet. The empty track shimmers and the legend holds one line of its own height, so a
  // card that draws its bar later keeps its height (final review I4: placeholders built from the real blocks)
  let { by_quality, height = 6, legend = false }: { by_quality: ByQuality | null; height?: 4 | 6; legend?: boolean } = $props();
  const NAMES: Record<Quality, string> = { lossless: 'lossless', good_lossy: 'good lossy', weak: 'weak', fake: 'fake',
    missing: 'missing' };
  const known = $derived(by_quality ?? { lossless: 0, good_lossy: 0, weak: 0, fake: 0, missing: 0 });
  const total = $derived(QUALITIES.reduce((a, q) => a + (known[q] ?? 0), 0));
  const title = $derived(QUALITIES.filter((q) => known[q]).map((q) => `${known[q]} ${NAMES[q]}`).join(' · '));
</script>

<div class="qbar" class:wait={!by_quality} style:height="{height}px" role="img"
  aria-label={by_quality ? title || 'No tracks' : 'Loading'} title={title || undefined}>
  {#if total}
    {#each QUALITIES as q (q)}
      {#if known[q]}<span class={q} style:width="{(known[q] / total) * 100}%"></span>{/if}
    {/each}
  {/if}
</div>
{#if legend}
  <div class="legend">
    {#if by_quality}
      {#each QUALITIES as q (q)}
        {#if by_quality[q]}<span><i class={q}></i>{by_quality[q]} {NAMES[q]}</span>{/if}
      {/each}
    {:else}<span class="wait line">&nbsp;</span>{/if}
  </div>
{/if}

<style>
  .qbar { display: flex; width: 100%; border-radius: 3px; overflow: hidden; background: var(--bg-inset); }
  .qbar span { display: block; height: 100%; }
  .lossless { background: var(--q-lossless-bar); }
  .good_lossy { background: var(--q-good-bar); }
  .weak, .missing { background: var(--q-weak-bar); }
  .fake { background: var(--q-fake-bar); }
  .missing { opacity: .55; }
  .legend { display: flex; flex-wrap: wrap; gap: var(--s-1) var(--s-3); margin-top: 6px; color: var(--text-muted);
    font-size: var(--fs-small); }
  .legend span { display: inline-flex; align-items: center; gap: 5px; }
  .wait { animation: dj-shimmer 1.6s ease-in-out infinite; }
  /* the waiting legend keeps its line's height but draws a cap-height pill (.7em of the legend's 12 px), the weight
     of the small muted text and dots it stands for; a full-line slab read heavier than the 6 px bar above it
     (final review fix B) */
  .line { width: 48%; position: relative; }
  .line::before { content: ''; position: absolute; left: 0; right: 0; top: 50%; height: .7em; transform: translateY(-50%);
    border-radius: var(--r-pill); background: var(--bg-inset); }
  .legend i { width: 7px; height: 7px; border-radius: var(--r-pill); display: inline-block; }
</style>
