<script lang="ts">
  // The panel while nothing is to do (spec §8), on `Panel` like "This run", so the panel keeps one structure in every
  // state. head = the last sync as the end screen counts it (`lastSyncStats`, the screen "See what came in →" opens):
  // a StatCard for what was added with its quality bar and legend as the number's visual (§4), the run's time and the
  // link on one line at the card's right edge (as "Download limits →" in the day card), then moved and need-you as two
  // StatCards. after = Could be better, a grouped list of rows (icon · label · count · ›) that open To-do; the
  // count and chevron sit in a fixed right column, and the whole row is the link.
  import { Button, ListRow, QualityBar, StatCard, Surface } from '$lib/components';
  import { Panel } from '$lib/frames';
  import type { RunSummary } from '$lib/bridge/types';
  import { runWhen } from '$lib/format';
  import { go, link } from '$lib/router';
  import type { LastSyncStats } from '../endModel';

  // view: lastSyncView, 'loading' until the last run's details settled (the cards then draw once, bar included)
  let { last, view, todo, upgrades }: {
    last: RunSummary | null; view: LastSyncStats | 'loading' | null; todo: number | null; upgrades: number | null;
  } = $props();
  const when = $derived(last ? runWhen(last.finished ?? last.started).replace(/^(Today|Yesterday)/, (m) => m.toLowerCase()) : '');
  const better = $derived([
    upgrades ? { key: 'upgrades', label: 'Upgrades ready', n: upgrades, path: '/todo?filter=upgrade_ready' } : null,
    todo ? { key: 'todo', label: 'In To-do', n: todo, path: '/todo' } : null,
  ].filter((x) => x !== null));
</script>

{#snippet head()}
  {#if view !== null}
    <!-- while the details load ('loading') the same cards draw with "—" and a waiting bar: the blocks hold their own
         shape and height, so nothing below moves when the numbers come (final review I4) -->
    {@const shown = view === 'loading' ? null : view}
    <StatCard value={shown?.added ?? null} label="added in the last sync" aria-busy={!shown || undefined}
      data-test={shown ? 'sync-last-run' : 'sync-last-wait'}>
      <div class="run">
        {#if !shown || shown.byQuality}<QualityBar by_quality={shown?.byQuality ?? null} legend />{/if}
        <div class="when"><span>{when}</span>
          <Button variant="link" size="sm" href={last ? `#/sync/run/${last.run_id}` : undefined} disabled={!last}
            data-test={shown ? 'last-run' : undefined}>See what came in →</Button></div>
      </div>
    </StatCard>
    <div class="stats">
      <StatCard value={shown?.moved ?? null} label="moved" data-test={shown ? 'sync-last-moved' : undefined} />
      <StatCard value={shown?.needs ?? null} label={shown?.needs === 1 ? 'needs you' : 'need you'}
        data-test={shown ? 'sync-last-needs' : undefined} />
    </div>
  {/if}
{/snippet}

{#snippet after()}
  {#if better.length}
    <Surface kind="list" label="Could be better" style="--row-cols: 16px minmax(0, 1fr) var(--w-row-action)" data-test="sync-could-be-better">
      {#each better as b (b.key)}
        {#snippet lead()}<svg class="icon" viewBox="0 0 16 16">{#if b.key === 'upgrades'}<path d="M8 12.5V3.5M4.5 7 8 3.5 11.5 7M3.5 13.5h9" />{:else}<path
          d="M2.5 4.5l1 1 2-2M2.5 10.5l1 1 2-2M7.5 4.5h6M7.5 10.5h6" />{/if}</svg>{/snippet}
        {#snippet name()}{b.label}{/snippet}
        <!-- the row's button is lead + name; the count and chevron are the same link, out of the tab order -->
        {#snippet trailing()}<a class="go" href="#{b.path}" use:link tabindex="-1" aria-hidden="true"><span
          class="n">{b.n}</span><svg class="chev" viewBox="0 0 16 16"><path d="M6 4l4 4-4 4" /></svg></a>{/snippet}
        <ListRow {lead} {name} {trailing} onclick={() => void go(b.path)} title="{b.n} · {b.label}" test="sync-better-{b.key}" />
      {/each}
    </Surface>
  {/if}
{/snippet}

<Panel {head} after={better.length ? after : undefined} />

<style>
  .stats { display: grid; grid-template-columns: 1fr 1fr; gap: var(--s-3); }
  .run { display: flex; flex-direction: column; gap: var(--s-3); }
  /* the run's time at the left, the way to its details at the card's right edge (as the day card's limits line) */
  .when { display: flex; align-items: baseline; justify-content: space-between; gap: var(--s-3); min-width: 0;
    font-size: var(--fs-small); color: var(--text-muted); white-space: nowrap; }
  .icon, .chev { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round;
    stroke-linejoin: round; }
  .icon { color: var(--text-muted); display: block; }
  .go { display: flex; align-items: center; justify-content: flex-end; gap: var(--s-1); color: var(--text-muted);
    text-decoration: none; }
  .go:hover { color: var(--text); text-decoration: none; }
  .n { font-variant-numeric: tabular-nums; }
  .chev { color: var(--text-label); }
</style>
