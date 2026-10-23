<script lang="ts">
  // The why's narrow form (spec §11, Task 9B I2), shared by Sync's plan rows and the Gallery's ListRow sample, so both
  // draw the same mark: below 680 px list width a row keeps its why as a mark before ⊘, the kind's icon (a tagged
  // row) and the yellow "next sync" dot (NextDot), in a fixed 26 px slot so marks line up down the list. The why
  // column (≥ 680 px list) says it in words, so the mark hides there. Nothing is drawn when the row has neither.
  import type { KindKey } from '../planModel';
  import KindIcon from './KindIcon.svelte';
  import NextDot from './NextDot.svelte';
  let { kind, next }: { kind: KindKey | null; next: boolean } = $props();
</script>

{#if kind || next}<span class="mark" aria-hidden="true"><span class="icon">{#if kind}<KindIcon {kind} />{/if}</span>{#if next}<NextDot
  data-test="sync-next-mark" />{/if}</span>{/if}

<style>
  .mark { display: grid; grid-template-columns: 16px 6px; align-items: center; gap: var(--s-1); width: 26px;
    color: var(--text-muted); }
  .icon { display: grid; place-items: center; }
  @container list (min-width: 680px) { .mark { display: none; } }
</style>
