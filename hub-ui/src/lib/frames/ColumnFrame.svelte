<script lang="ts">
  // Single-column page frame (design system §3): the running sync, the end screen, Settings and Setup. Content grows
  // to --content-max, then centres; the area above `foot` scrolls. `foot` (the page's actions) sits below the
  // scroller at the same width and never scrolls away; the rule over it spans the content's width.
  // Vertical padding and the content's sizing work as in ListPanelFrame (space below the last row; a list that
  // scrolls inside itself marks its root `data-scrolls-itself`).
  import type { Snippet } from 'svelte';
  let { content, foot }: { content: Snippet; foot?: Snippet } = $props();
</script>

<div class="frame" data-frame="column">
  <div class="main" data-frame-main>
    <div class="content" data-frame-content data-max="--content-max">{@render content()}</div>
  </div>
  {#if foot}<div class="foot" data-frame-foot>{@render foot()}</div>{/if}
</div>

<style>
  .frame { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  .main { flex: 1 1 auto; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; padding-block: var(--s-4); }
  .content, .foot { align-self: center; width: 100%; max-width: var(--content-max); }
  .content { flex: 1 0 auto; display: flex; flex-direction: column; gap: var(--s-3); padding: 0 var(--s-5); }
  .content:has(:global([data-scrolls-itself])) { flex-shrink: 1; min-height: 0; }
  .foot { padding: var(--s-4) var(--s-5); }
  .foot { flex: none; display: flex; align-items: center; gap: var(--s-3); position: relative; }
  /* the rule over the foot spans the content's width, not its padding: it ends where the rows and the buttons end
     (spec §12 edges; it overshot both by --s-5 on each side, Task 10B) */
  .foot::before { content: ''; position: absolute; top: 0; left: var(--s-5); right: var(--s-5);
    border-top: var(--bw) solid var(--surface-line); }
</style>
