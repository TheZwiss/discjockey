<script lang="ts">
  // List + panel page frame (design system §3). The panel is docked at the right edge at --panel-w (--panel-w-narrow
  // below a 1240 px window, one fixed step) and never takes free width. The list area takes the rest and scrolls; its
  // content grows to --content-max (`wide`: --content-max-wide, the Library table), then centres. The vertical padding
  // sits on the scroller so the last row keeps space below it. `.content` grows to the scroller's height and never
  // shrinks below its content (a shrunk box would let the rows overflow past the padding); a list that scrolls inside
  // itself marks its root `data-scrolls-itself`, and then `.content` keeps exactly the scroller's height instead.
  // Optional columns query the list itself (Surface's rows are the `list` container), not this area.
  import type { Snippet } from 'svelte';
  import EmptyState from '../components/EmptyState.svelte';
  let { main, panel = null, emptyPanel = 'Pick a track to see its details.', wide = false }:
    { main: Snippet; panel?: Snippet | null; emptyPanel?: string; wide?: boolean } = $props();
</script>

<div class="frame" data-frame="list-panel">
  <div class="main" data-frame-main>
    <div class="content" class:wide data-frame-content data-max={wide ? '--content-max-wide' : '--content-max'}>{@render main()}</div>
  </div>
  <aside data-panel>
    {#if panel}{@render panel()}{:else}<div class="empty"><EmptyState title={emptyPanel} /></div>{/if}
  </aside>
</div>

<style>
  .frame { display: flex; height: 100%; min-height: 0; }
  /* a sticky Surface head sticks at the scroller's top edge, not below its padding */
  .main { flex: 1 1 auto; min-width: 0; overflow-y: auto; display: flex; flex-direction: column;
    padding-block: var(--s-4); --sticky-top: calc(-1 * var(--s-4)); }
  .content { flex: 1 0 auto; align-self: center; width: 100%; max-width: var(--content-max);
    padding: 0 var(--s-5); display: flex; flex-direction: column; gap: var(--s-3); }
  .content:has(:global([data-scrolls-itself])) { flex-shrink: 1; min-height: 0; }
  /* only that list gives way: everything above it keeps its height (a Segmented clips its overflow, so it could
     otherwise shrink to a sliver; To-do at 1100 with 299 to-dos) */
  .content:has(:global([data-scrolls-itself])) > :global(:not([data-scrolls-itself])) { flex-shrink: 0; }
  .content.wide { max-width: var(--content-max-wide); }
  aside { flex: none; width: var(--panel-w); background: var(--panel-bg); border-left: var(--bw) solid var(--surface-line);
    min-height: 0; display: flex; flex-direction: column; }
  @media (width < 1240px) { aside { width: var(--panel-w-narrow); } }
  .empty { margin: auto 0; padding: var(--s-4); }
</style>
