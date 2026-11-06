<script lang="ts" module>
  export type BarPart = { key: string; n: number; colour: string; label: string; off?: boolean };
</script>

<script lang="ts">
  // A whole in its parts, 6 px (issue 36; QualityBar's shape and height for a whole that isn't qualities): each part
  // as wide as its share, in its own colour (`colour`, a token), in the order given. `off`: switched off, the part
  // dims (dim means switched off, nothing else). Nothing to show: the empty track. The bar is one image for a screen
  // reader, its parts in words (`label`).
  let { parts }: { parts: BarPart[] } = $props();
  const total = $derived(parts.reduce((t, p) => t + p.n, 0));
  const said = $derived(total ? parts.filter((p) => p.n > 0).map((p) => `${p.n} ${p.label}`).join(' · ') : 'Nothing');
</script>

<div class="sbar" role="img" aria-label={said} title={total ? said : undefined} data-test="share-bar">
  {#each parts as p (p.key)}
    {#if p.n > 0}<span class:off={p.off} style:width="{(p.n / total) * 100}%" style:background={p.colour}
      data-part={p.key}></span>{/if}
  {/each}
</div>

<style>
  .sbar { display: flex; height: 6px; border-radius: var(--r-pill); overflow: hidden; background: var(--bg-inset); }
  /* a hairline of the track between two parts, so neighbours of near colours stay two */
  span { display: block; height: 100%; min-width: 2px; transition: width var(--t-reply) var(--ease), opacity var(--t-state) var(--ease); }
  span + span { box-shadow: inset 1px 0 0 var(--bg-inset); }
  .off { opacity: var(--dim-locked); }
</style>
