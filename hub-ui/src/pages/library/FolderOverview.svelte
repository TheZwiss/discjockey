<script lang="ts">
  // The panel while no track is picked (design system mockup design-system/library.html): the folder at a glance
  // instead of an empty column. The lossless share as a StatCard over the quality bar with its legend (the number
  // the header used to say only as text, §4: a number plus a visual), then where to go from here as rows like
  // Dashboard's Needs you (icon · name · count ›): the upgrades ready (filters the table to them) and the tracks on
  // the to-do list (opens To-do). A Hint at the bottom says what picking a track shows. The summary ignores the
  // search and the filter (views.library), so the card stays the folder's while the table narrows.
  import { Hint, ListRow, QualityBar, StatCard, Surface } from '$lib/components';
  import { Panel } from '$lib/frames';
  import type { Library } from '$lib/bridge/types';
  import { overview } from './libraryModel';

  let { summary, onupgrades, ontodo }: {
    summary: Library['summary'] | null; onupgrades: () => void; ontodo: () => void;
  } = $props();

  const stat = $derived(summary ? overview(summary) : null);
  const COLS = '--row-cols: 16px minmax(0, 1fr) var(--w-row-action)';
</script>

{#snippet chev()}<svg class="chev" viewBox="0 0 16 16" aria-hidden="true"><path d="M6 4l4 4-4 4" /></svg>{/snippet}

{#snippet head()}
  <div class="col" data-test="library-overview">
    <StatCard value={stat?.value ?? null} unit={stat?.unit} label={stat?.label ?? 'lossless'} data-test="overview-share">
      {#if !summary || stat?.value !== null}<QualityBar by_quality={summary?.by_quality ?? null} legend />{/if}
    </StatCard>

    {#if summary && summary.tracks}
      <Surface kind="list" style={COLS} data-test="overview-rows">
        {#if summary.upgrades_ready}
          {#snippet lead()}<svg class="icon good" viewBox="0 0 16 16"><path d="M8 12.5V3.5M4.5 7 8 3.5 11.5 7M3.5 13.5h9" /></svg>{/snippet}
          {#snippet name()}{summary.upgrades_ready === 1 ? 'Upgrade ready' : 'Upgrades ready'}{/snippet}
          {#snippet sub()}show {summary.upgrades_ready === 1 ? 'it' : 'them'} in the table{/snippet}
          {#snippet trailing()}<span class="go"><span class="n">{summary.upgrades_ready}</span>{@render chev()}</span>{/snippet}
          <ListRow {lead} {name} {sub} {trailing} onclick={onupgrades} test="overview-upgrades" />
        {/if}
        {#if summary.to_do}
          {#snippet lead()}<svg class="icon problem" viewBox="0 0 16 16"><path d="M1.5 8c1.6-3.4 3.3-3.4 4.5 0s2.9 3.4 4.5 0 2.9-3.4 4 0" /></svg>{/snippet}
          {#snippet name()}On the to-do list{/snippet}
          {#snippet sub()}not lossless yet{/snippet}
          {#snippet trailing()}<span class="go"><span class="n">{summary.to_do}</span>{@render chev()}</span>{/snippet}
          <ListRow {lead} {name} {sub} {trailing} onclick={ontodo} test="overview-todo" />
        {:else if !summary.upgrades_ready}
          {#snippet lead()}<svg class="icon good" viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" /></svg>{/snippet}
          {#snippet name()}Nothing to do here{/snippet}
          <ListRow {lead} {name} test="overview-none" />
        {/if}
      </Surface>
    {/if}
  </div>
{/snippet}

{#snippet foot()}<div class="hint"><Hint text="Pick a track to see its details." /></div>{/snippet}

<Panel {head} {foot} />

<style>
  .col { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
  .icon, .chev { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round;
    stroke-linejoin: round; display: block; flex: none; }
  .icon.good { color: var(--q-lossless); }
  .icon.problem { color: var(--q-weak); }
  .go { display: flex; align-items: center; justify-content: flex-end; gap: var(--s-2); color: var(--text-muted); }
  .chev { color: var(--text-label); }
  .n { font-variant-numeric: tabular-nums; }
  .hint { display: flex; justify-content: center; }
</style>
