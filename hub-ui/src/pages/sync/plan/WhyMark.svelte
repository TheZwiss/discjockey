<script lang="ts">
  // A plan row's kind mark (issue 35), shared by Sync's plan rows and the Gallery's ListRow sample, so both draw the
  // same: every row, at every width, shows why it is in the list as its kind's icon (KindIcon, the same one What to do
  // shows beside the kind's name, so the panel is the legend), in a fixed 26 px slot before ⊘ so the icons line up
  // down the list. Below 680 px list width the slot also holds the yellow "next sync" dot (NextDot); from 680 px the
  // why column says that in words, so the dot hides there and the icon stays. The icon takes the row's muted text
  // colour: a kind is not a quality, a problem or a wait, and orange (action, selection) is the ticks' colour.
  import type { KindKey } from '../planModel';
  import KindIcon from './KindIcon.svelte';
  import NextDot from './NextDot.svelte';
  let { kind, next }: { kind: KindKey; next: boolean } = $props();
</script>

<span class="mark" aria-hidden="true" data-test="sync-kind" data-kind={kind}><span class="icon"><KindIcon {kind} /></span>{#if next}<NextDot
  data-test="sync-next-mark" />{/if}</span>

<style>
  .mark { display: grid; grid-template-columns: 16px 6px; align-items: center; gap: var(--s-1); width: 26px;
    color: var(--text-muted); }
  .icon { display: grid; place-items: center; }
  @container list (min-width: 680px) { .mark :global([data-test="sync-next-mark"]) { display: none; } }
</style>
