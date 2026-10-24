<script lang="ts">
  // Dashboard (spec "hub" §5.1, "design system" §8, mockup design-system/dashboard.html): the list is the library —
  // its health, what needs you, its folders; the panel is the next sync, built like Sync's panel (count and time
  // StatCards, the day card, the filled button in Start's place), with the last runs filling the space between.
  // Every list that grows over time is anchored and scrolls in place (Surface `grow`): the folders fill the list's
  // height, the runs the panel's; Needs you has at most three rows, so it keeps its height.
  import { untrack } from 'svelte';
  import { api } from '$lib/bridge/client';
  import type { Dashboard, Fail } from '$lib/bridge/types';
  import { dataVersion, hubSyncRunning, spotifyMissing } from '$lib/stores/hub';
  import { run } from '$lib/stores/run';
  import { markReady } from '$lib/ready';
  import { go, libraryHref, link } from '$lib/router';
  import {
    Button, DayBar, EmptyState, Hint, ListRow, NoteCard, PageHeader, ProblemCard, ProgressBar, QualityBar, Skeleton,
    StatCard, Surface,
  } from '$lib/components';
  import { ListPanelFrame, Panel } from '$lib/frames';
  import { EMPTY } from '$lib/copy';
  import type { DayBarInput } from '$lib/components/dayBarModel';
  import { plural } from '$lib/format';
  import { folderLine, healthCard, needsRows, nextSync } from './dashboardModel';
  import RunRow from './RunRow.svelte';

  let { params: _params, query: _query }: { params: Record<string, string>; query: URLSearchParams } = $props();

  let data = $state<Dashboard | null>(null);
  let error = $state<Fail | null>(null);
  let seq = 0;

  async function load() {
    const my = ++seq;
    const r = await api.dashboard();
    if (my !== seq) return;
    if (r.ok) {
      const { ok: _ok, ...rest } = r;
      data = rest;
      error = null;
    } else {
      error = r;   // old data (if any) stays on screen
    }
    markReady('dashboard');
  }
  // fetch on mount and after every finished job / refresh (old data stays while re-fetching)
  $effect(() => { void $dataVersion; untrack(() => void load()); });

  const empty = $derived(data?.empty ?? null);
  const health = $derived(data ? healthCard(data.tiles.lossless, empty) : null);
  const needs = $derived(data ? needsRows(data.needs_you) : []);
  const next = $derived(data ? nextSync(data, $hubSyncRunning, !$spotifyMissing && empty !== 'not_set_up') : null);
  const runShare = $derived($run.total ? Math.max(0, $run.index - 0.5) / $run.total : null);
  const now = Date.now();

  // the columns of each list (ListRow): Needs you and the runs as Sync's Could be better (icon · name · number ›);
  // the folders give their number column a fixed quality bar, so the bars start and end at one x at every width
  const NEED_COLS = '--row-cols: 16px minmax(0, 1fr) var(--w-row-action)';
  const FOLDER_COLS = '--row-cols: minmax(0, 1fr) 264px';
  const RUN_COLS = '--row-cols: 16px minmax(0, 1fr) 16px';
</script>

{#snippet chev()}<svg class="chev" viewBox="0 0 16 16"><path d="M6 4l4 4-4 4" /></svg>{/snippet}

{#snippet main()}
  <PageHeader title={data?.greeting ?? 'Hello'} spotify />

  {#if error}
    <ProblemCard kind={error.kind} message={error.message} onretry={load} compact={!!data} />
  {/if}

  {#if empty === 'not_set_up' || empty === 'no_playlists'}
    <Surface kind="card" data-test="dashboard-empty">
      {#if empty === 'no_playlists'}
        <EmptyState kind="no_playlists" action={{ label: 'Add your first playlist →', href: '#/playlists' }} />
      {:else}
        <EmptyState kind="not_set_up" />
      {/if}
    </Surface>
  {/if}

  {#if data || !error}
    <!-- while it loads the card draws "—" and a waiting bar: the block keeps its height, nothing below moves -->
    <StatCard value={health?.value ?? null} unit={health?.unit} label={health?.label ?? 'lossless'} data-test="health"
      valueTest="health-share">
      {#if !data || health?.value !== null}<QualityBar by_quality={data?.tiles.lossless.by_quality ?? null} legend />{/if}
    </StatCard>
  {/if}

  {#if !data && !error}
    <Surface kind="card" label="Needs you"><Skeleton lines={3} height={12} gap={14} /></Surface>
  {:else if data}
    <Surface kind="list" label="Needs you" summary={needs.length ? String(needs.reduce((a, n) => a + n.n, 0)) : undefined}
      style={NEED_COLS} data-test="needs-you">
      {#each needs as n (n.key)}
        {#snippet lead()}<svg class="icon {n.tone}" viewBox="0 0 16 16">{#if n.key === 'upgrades'}<path
          d="M8 12.5V3.5M4.5 7 8 3.5 11.5 7M3.5 13.5h9" />{:else if n.key === 'not_found'}<path
          d="M7 11.5a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9zM10.3 10.3l3.2 3.2" />{:else}<path
          d="M1.5 8c1.6-3.4 3.3-3.4 4.5 0s2.9 3.4 4.5 0 2.9-3.4 4 0" />{/if}</svg>{/snippet}
        {#snippet name()}{n.label}{/snippet}
        {#snippet sub()}{n.sub}{/snippet}
        <!-- the row's button is icon + name; the count and chevron are the same link, out of the tab order -->
        {#snippet trailing()}<a class="go" href={n.href} use:link tabindex="-1" aria-hidden="true"><span
          class="n">{n.n}</span>{@render chev()}</a>{/snippet}
        <ListRow {lead} {name} {sub} {trailing} onclick={() => void go(n.href.slice(1))} title="{n.n} · {n.label} · {n.sub}"
          test="need-{n.key}" />
      {:else}
        {#snippet lead()}<svg class="icon good" viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" /></svg>{/snippet}
        {#snippet name()}Nothing needs you right now{/snippet}
        <ListRow {lead} {name} test="needs-none" />
      {/each}
    </Surface>

    {#if data.folders.length}
      <Surface kind="list" label="Folders" summary={plural(data.folders.length, 'playlist')} style={FOLDER_COLS}
        grow={{ rows: data.folders.length }} data-test="folders">
        {#each data.folders as f (f.folder)}
          {@const line = folderLine(f)}
          {@const href = libraryHref(f.folder)}
          {#snippet name()}{f.folder}{/snippet}
          {#snippet trailing()}<a class="go fold" {href} use:link tabindex="-1" aria-hidden="true"><span class="qb"><QualityBar
            by_quality={f.by_quality} /></span><span class="share">{line.short}</span>{@render chev()}</a>{/snippet}
          <ListRow {name} {trailing} onclick={() => void go(href.slice(1))} title={line.full} test="folder-row" />
        {/each}
      </Surface>
    {/if}
  {/if}
{/snippet}

{#snippet head()}
  {#if !next}
    <!-- loading: the ready shape with "—", so nothing jumps when the numbers come -->
    <div class="stats"><StatCard value={null} label="tracks today" /><StatCard value={null} label="run time" /></div>
  {:else if next.state === 'running'}
    <StatCard value={Math.max(1, $run.index)} unit={$run.total ? `of ${$run.total}` : undefined} label="tracks · sync running"
      data-test="next-running">
      <ProgressBar value={runShare} pace="live" label="Sync progress" />
    </StatCard>
  {:else if next.state === 'unread'}
    <Surface kind="card" data-test="next-unread"><EmptyState title={EMPTY.no_preview.title} body={next.line ?? undefined} /></Surface>
  {:else if next.state === 'up_to_date'}
    <Surface kind="card" tone="good" data-test="next-up-to-date">
      <div class="done"><svg class="icon good" viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" /></svg>
        <div class="done-text"><span class="done-title">Up to date</span><Hint
          text="{plural(data?.folders.length ?? 0, 'playlist')} · {plural(data?.tiles.lossless.total ?? 0, 'track')}" /></div></div>
    </Surface>
    {#if next.day}{@render dayCard(next.day, next.limits)}{/if}
    {#if next.checks}
      <StatCard value={next.checks} label="weekly checks in the next sync" data-test="next-checks" />
    {/if}
  {:else}
    <div class="stats" data-test="next-sync">
      <StatCard value={next.count} label="track{next.count === 1 ? '' : 's'} today" valueTest="next-count" />
      <StatCard value={next.time.value} unit={next.time.unit} label="run time" data-test="next-time" />
    </div>
    {@render dayCard(next.day, next.limits)}
    {#if next.limitReached}
      <NoteCard tone="warn" title="Downloads start tomorrow · moves still run" data-test="next-limit-reached" />
    {/if}
  {/if}
{/snippet}

{#snippet dayCard(input: DayBarInput, limits: { text: string; full: string } | null)}
  <Surface kind="card" data-test="next-day">
    <DayBar {input} data-test="next-daybar" />
    <div class="limits"><span class="what" title={limits?.full}>{limits?.text ?? ''}</span><Button variant="link" size="sm" href="#/limits"
      data-test="next-limits-link">Download limits →</Button></div>
  </Surface>
{/snippet}

{#snippet fill()}
  {#if data?.last_runs.length}
    <Surface kind="list" label="Last runs" style={RUN_COLS} grow={{ rows: data.last_runs.length, tall: true }}
      data-test="last-runs">
      {#snippet header()}<Button variant="link" size="sm" href="#/runs" data-test="all-runs">All runs →</Button>{/snippet}
      {#each data.last_runs as r (r.run_id)}<RunRow run={r} {now} />{/each}
    </Surface>
  {/if}
{/snippet}

{#snippet after()}
  {#if data && !data.last_runs.length}
    <Surface kind="card" label="Last runs" data-test="no-runs"><Hint text="No runs yet · your first sync shows up here" /></Surface>
  {/if}
{/snippet}

{#snippet foot()}
  {#if next?.state === 'running'}
    <Button variant="filled" wide href="#/sync" data-test="open-sync">Open the sync →</Button>
  {:else if next?.state === 'ready'}
    <Button variant="filled" wide href="#/sync" data-test="review-start">Review &amp; start →</Button>
  {/if}
{/snippet}

{#snippet panel()}
  <Panel {head} fill={data?.last_runs.length ? fill : undefined} after={data && !data.last_runs.length ? after : undefined}
    foot={next?.state === 'running' || next?.state === 'ready' ? foot : undefined} />
{/snippet}

<ListPanelFrame {main} {panel} />

<style>
  .stats { display: grid; grid-template-columns: 1fr 1fr; gap: var(--s-3); }
  /* as Sync's day card: the limit at the left, the way to change it at the card's right edge */
  .limits { display: flex; align-items: baseline; justify-content: space-between; gap: var(--s-3); min-width: 0;
    font-size: var(--fs-small); color: var(--text-muted); white-space: nowrap; }
  .what { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .done { display: flex; align-items: center; gap: var(--s-3); min-width: 0; }
  .done-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .done-title { color: var(--text-strong); font-weight: var(--fw-semi); }
  .icon, .chev { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round;
    stroke-linejoin: round; display: block; flex: none; }
  .icon { color: var(--text-muted); }
  .icon.good { color: var(--q-lossless); }
  .icon.problem { color: var(--q-weak); }
  .go { display: flex; align-items: center; justify-content: flex-end; gap: var(--s-2); color: var(--text-muted);
    text-decoration: none; min-width: 0; }
  .go:hover { color: var(--text); text-decoration: none; }
  .chev { color: var(--text-label); }
  .n, .share { font-variant-numeric: tabular-nums; }
  /* a fixed bar and number column: every folder's bar starts and ends at the same x */
  .qb { flex: none; width: 160px; }
  .share { flex: none; width: 72px; text-align: right; }
</style>
