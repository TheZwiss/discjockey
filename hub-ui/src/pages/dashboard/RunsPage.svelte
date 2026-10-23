<script lang="ts">
  // #/runs (Task 66): every run, newest first, grouped by month for long lists; each opens its end screen. On the
  // Dashboard's frame (list + panel), so "All runs →" keeps the title where it was (issue 8): the list holds the runs
  // as the Dashboard's Last runs draws them (RunRow), one Surface per month; the panel adds them up.
  import { untrack } from 'svelte';
  import { api } from '$lib/bridge/client';
  import type { Fail, RunSummary } from '$lib/bridge/types';
  import { dataVersion } from '$lib/stores/hub';
  import { markReady } from '$lib/ready';
  import { plural } from '$lib/format';
  import { EmptyState, PageHeader, ProblemCard, Skeleton, StatCard, Surface } from '$lib/components';
  import { ListPanelFrame, Panel } from '$lib/frames';
  import { groupByMonth, runTotals } from './dashboardModel';
  import RunRow from './RunRow.svelte';

  let { params: _params, query: _query }: { params: Record<string, string>; query: URLSearchParams } = $props();

  let runs = $state<RunSummary[] | null>(null);
  let error = $state<Fail | null>(null);
  let seq = 0;
  async function load() {
    const my = ++seq;
    const r = await api.runs();
    if (my !== seq) return;
    if (r.ok) { runs = r.runs; error = null; } else error = r;
    markReady('runs');
  }
  $effect(() => { void $dataVersion; untrack(() => void load()); });

  const groups = $derived(runs ? groupByMonth(runs) : []);
  const totals = $derived(runs ? runTotals(runs) : null);
  const now = Date.now();
  const RUN_COLS = '--row-cols: 16px minmax(0, 1fr) 16px';
</script>

{#snippet main()}
  <PageHeader title="All runs" sub={runs?.length ? plural(runs.length, 'run') : undefined} />
  {#if error}
    <ProblemCard kind={error.kind} message={error.message} onretry={load} compact={!!runs} />
  {/if}
  {#if !runs}
    {#if !error}<Surface kind="card"><Skeleton lines={5} height={12} gap={14} /></Surface>{/if}
  {:else if !runs.length}
    <Surface kind="card" data-test="runs-empty">
      <EmptyState title="No runs yet." body="Your first sync shows up here." action={{ label: 'Go to Sync →', href: '#/sync' }} />
    </Surface>
  {:else}
    <div class="list" data-test="runs-list">
      {#each groups as g (g.label ?? 'all')}
        <Surface kind="list" label={g.label ?? undefined} summary={g.label ? plural(g.runs.length, 'run') : undefined}
          style={RUN_COLS} data-test="runs-group">
          {#each g.runs as r (r.run_id)}<RunRow run={r} {now} />{/each}
        </Surface>
      {/each}
    </div>
  {/if}
{/snippet}

{#snippet head()}
  <div class="stats" data-test="runs-totals">
    <StatCard value={totals?.runs ?? null} label={totals?.runs === 1 ? 'run' : 'runs'} />
    <StatCard value={totals?.added ?? null} label="tracks added" />
    <StatCard value={totals?.moved ?? null} label="moved" />
    <StatCard value={totals?.problems ?? null} label={totals?.problems === 1 ? 'problem' : 'problems'} />
  </div>
{/snippet}

{#snippet panel()}<Panel head={error && !runs ? undefined : head} />{/snippet}

<ListPanelFrame {main} {panel} />

<style>
  .list { display: flex; flex-direction: column; gap: var(--s-3); }
  .stats { display: grid; grid-template-columns: 1fr 1fr; gap: var(--s-3); }
</style>
