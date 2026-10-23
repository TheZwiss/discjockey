<script lang="ts">
  // OUTDATED (design system §7): use Surface. Kept until phase 2 ends.
  import type { Snippet } from 'svelte';
  let { label, title, tone = 'default', padded = true, header, children, footer }:
    { label?: string; title?: string; tone?: 'default' | 'accent' | 'problem'; padded?: boolean;
      header?: Snippet; children?: Snippet; footer?: Snippet } = $props();
</script>

<section class="card {tone}" class:padded>
  {#if label || title || header}
    <div class="head">
      <div class="titles">
        {#if label}<div class="caps">{label}</div>{/if}
        {#if title}<h3>{title}</h3>{/if}
      </div>
      {#if header}<div class="right">{@render header()}</div>{/if}
    </div>
  {/if}
  {@render children?.()}
  {#if footer}<div class="foot">{@render footer()}</div>{/if}
</section>

<style>
  .card { border: var(--bw) solid var(--line-card); border-radius: var(--r-card); background: var(--bg); min-width: 0; }
  .padded { padding: var(--s-3) var(--s-4); }
  .accent { border: var(--bw-accent) solid var(--accent); }
  .problem { border-color: var(--q-weak-line); }
  .head { display: flex; align-items: flex-start; gap: var(--s-3); margin-bottom: var(--s-2); }
  .titles { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  h3 { font-size: var(--fs-body); }
  .right { display: flex; align-items: center; gap: var(--s-2); }
  .foot { margin-top: var(--s-3); display: flex; gap: var(--s-2); align-items: center; flex-wrap: wrap; }
</style>
