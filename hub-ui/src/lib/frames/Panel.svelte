<script lang="ts">
  // The panel inside ListPanelFrame (design system §3). `head` and `after` keep their natural height; `fill` holds
  // the one list of unknown length (ToggleGroup grow), which takes the spare height up to its own rows' height and
  // scrolls inside itself when that doesn't fit; its minimum (up to 3 rows) is its own. `foot` holds the page's main action
  // and never scrolls away. When even fill's minimum doesn't fit, the whole body scrolls while `foot` stays, and the
  // body's end above the foot fades (edgeFade), so content cut there reads as more below, not as the end. That cut
  // falls wherever the window ends, so the body's fade runs over a row's height (--h-row) instead of the lists'
  // 16 px: whatever the cut, some row content sits inside the fade, never only a row's padding (spec §11, Task 7).
  // Above its minimum a cut fill list ends a peek into a row (spec §11, issue 10): it hands the px under that peek to
  // the panel (`GROW_SPARE`), which holds them in a spacer at the body's end, above the foot, where the spare height
  // of a list that fits already sits. When space runs out the list gives way first, down to its minimum, then the
  // spacer; its negative margin cancels the body's gap, so an empty spacer takes no room. One grow group per Panel:
  // the spacer holds one group's spare, so a second would overwrite the first's (dev mode warns, final review M6).
  import { setContext } from 'svelte';
  import { edgeFade } from '$lib/components/edgeFade';
  import { GROW_SPARE, type GrowSpareHost } from '$lib/components/toggleModel';
  import type { Snippet } from 'svelte';
  let { head, fill, after, foot }: { head?: Snippet; fill?: Snippet; after?: Snippet; foot?: Snippet } = $props();

  let spare = $state(0);
  let spacer: HTMLDivElement | undefined = $state();
  let growers = 0;
  setContext<GrowSpareHost>(GROW_SPARE, {
    set: (px) => { spare = px; },
    height: () => spacer?.getBoundingClientRect().height ?? 0,
    join: () => {
      growers += 1;
      if (import.meta.env.DEV && growers > 1) console.warn('Panel: one grow group per Panel; a second one overwrites the first\'s spare height');
      return () => { growers -= 1; };
    },
  });
</script>

<div class="panel" data-panel-root>
  <div class="body" use:edgeFade>
    {#if head}<div class="head" data-panel-head>{@render head()}</div>{/if}
    {#if fill}<div class="fill" data-panel-fill>{@render fill()}</div>{/if}
    {#if after}<div class="after" data-panel-after>{@render after()}</div>{/if}
    {#if fill}<div class="spare" bind:this={spacer} style:height="{spare}px" aria-hidden="true"></div>{/if}
  </div>
  {#if foot}<div class="foot" data-panel-foot>{@render foot()}</div>{/if}
</div>

<style>
  .panel { display: flex; flex-direction: column; height: 100%; min-height: 0; padding: var(--s-5) var(--s-5) 0; }
  .body { flex: 1 1 auto; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: var(--s-3);
    --fade-len: var(--h-row); }
  .head, .after { flex: none; display: flex; flex-direction: column; gap: var(--s-3); }
  /* fill is a slot without a box: its list is the body's own flex item, so the list's own minimum (up to 3 rows, which it
     knows with or without its search) is the one that holds, and a fixed guess here can't disagree with it (spec
     §11, Task 9B fix round 1). The list grows to its rows' height, never past it; the spare height goes above the
     foot, where Start sits */
  .fill { display: contents; }
  /* the cut list's spare px (issue 10): a near-zero shrink so the list gives way first above its minimum and the
     spacer once the list is at it; the margin cancels the body's gap */
  .spare { flex: 0 0.001 auto; min-height: 0; margin-top: calc(-1 * var(--s-3)); }
  .foot { flex: none; padding: var(--s-3) 0 var(--s-5); display: flex; flex-direction: column; gap: var(--s-2); }
</style>
