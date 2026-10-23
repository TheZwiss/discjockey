<script lang="ts">
  // End screen (design system §8 End), on ColumnFrame: the page header with Full report, stat cards (added with its
  // quality bar, then moved · need you as a pair: the up-to-date panel's numbers and composition), the notes the cards can't
  // count (stopped, upgrades to review, waiting), then Needs you, one list per playlist folder of the new files
  // (under a hint to add them in rekordbox; Show in Finder opens each) and Other changes, all list Surfaces of
  // ListRows. Every list keeps the action's slot, so the badges share one right edge. The foot holds Done, the one
  // filled button, or Sync the rest → with Done beside it.
  // A failed sync JobFinished shows its ProblemCard (a problem-tone card) in the same frame; Back to the plan in the
  // foot is the way on (a crash writes no report yet: docs/issues.md).
  import { onMount } from 'svelte';
  import { Badge, Button, Cover, ExternalLink, Hint, ListRow, PageHeader, ProblemCard, QualityBar, StatCard,
    Surface } from '$lib/components';
  import { ColumnFrame } from '$lib/frames';
  import { api } from '$lib/bridge/client';
  import type { Result, RunDetail } from '$lib/bridge/types';
  import { run } from '$lib/stores/run';
  import { markReady } from '$lib/ready';
  import { go } from '$lib/router';
  import { artistTitle, noteParts, plural, runIdFromReport } from '$lib/format';
  import { dismissedJob } from './view';
  import { fixHref, rowBadge } from './results';
  import { endModel, endTitle, otherDetail } from './endModel';

  let { run_id }: { run_id: string | null } = $props();
  let detail = $state<RunDetail | null>(null);
  let loadError = $state<string | null>(null);

  const mine = $derived($run.job_kind === 'sync' && ($run.phase === 'finished' || $run.phase === 'failed'));
  const failed = $derived(mine && $run.phase === 'failed' && !!$run.job_finished);
  const jobResult = $derived(($run.job_finished?.result ?? null) as { report?: string; new_since_preview?: number } | null);
  const newSince = $derived(mine && run_id && runIdFromReport(jobResult?.report) === run_id
    ? jobResult?.new_since_preview ?? null : null);
  const m = $derived(detail ? endModel(detail, newSince) : null);
  // a failed sync names its outcome like every other end title; the card under it says why
  const title = $derived(failed ? "Sync didn't finish" : m?.title ?? endTitle($run.run_finished?.exit_code));
  const problem = $derived($run.job_finished?.problem ?? 'crashed');
  const REVIEW = '#/todo?filter=upgrade_ready';
  const COLS = '--row-cols: 40px minmax(0, 1fr) auto';

  const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
  onMount(() => {
    if (failed || !run_id) { markReady('sync'); return; }
    void (async () => {
      let r = await api.run(run_id);
      // the run is filed right after its JobFinished; one retry covers that moment
      if (!r.ok) { await wait(500); r = await api.run(run_id); }
      if (r.ok) detail = r.run; else loadError = r.message;
      markReady('sync');
    })();
  });

  function dismiss() { if ($run.job_id !== null) dismissedJob.set($run.job_id); }
  function back() { dismiss(); void go('/sync'); }
  function done() { dismiss(); void go('/'); }
</script>

<!-- one result: cover · Artist – Title over its detail line · badge · action slot (Fix → or Review →) -->
{#snippet row(r: Result, detailLine: string, action: 'fix' | 'review' | null, shops = false)}
  {@const b = rowBadge(r)}
  {@const fix = action === 'fix' ? fixHref(r) : null}
  <ListRow test="end-row" data-section={r.section} title={artistTitle(r.artist, r.title)} height={52}>
    {#snippet lead()}<Cover url={r.cover_url ?? null} seed={r.track_id ?? r.title} size={40} />{/snippet}
    {#snippet name()}{artistTitle(r.artist, r.title)}{/snippet}
    {#snippet sub()}
      {#if detailLine}<span title={detailLine}>{detailLine}</span>{/if}
      {#if shops}
        {#each noteParts(r.note) as p, j (j)}{#if 'href' in p}<span class="shop"><ExternalLink href={p.href} label={p.label} /></span>{/if}{/each}
      {/if}
    {/snippet}
    {#snippet trailing()}
      <Badge tone={b.tone} text={b.text} />
      <span class="act">
        {#if fix}<Button variant="link" size="sm" href={fix} data-test="end-fix">Fix →</Button>
        {:else if action === 'review'}<Button variant="link" size="sm" href={REVIEW}>Review →</Button>{/if}
      </span>
    {/snippet}
  </ListRow>
{/snippet}

{#snippet header()}
  <PageHeader {title} sub={failed ? undefined : m?.sub}>
    {#snippet actions()}
      {#if m && run_id && !failed}
        <Button variant="link" size="sm" onclick={() => run_id && api.open_report(run_id)} data-test="open-report">
          Full report ↗</Button>
      {/if}
    {/snippet}
  </PageHeader>
{/snippet}

{#snippet content()}
  {@render header()}
  {#if failed && $run.job_finished}
    <div data-test="sync-failed" data-problem={problem}>
      <!-- a crash under "Sync didn't finish" is "Something went wrong": the sync wording ("The sync stopped
           unexpectedly") would say the title again -->
      <ProblemCard kind={problem} message={$run.job_finished.message} sync={problem !== 'crashed'}
        report={run_id ? { run_id } : null} />
    </div>
  {:else if loadError}
    <ProblemCard kind="refused" message={loadError} />
  {:else if !m}
    <!-- the stat cards themselves with "—" and a waiting bar: the blocks hold their own shape and height, so nothing
         jumps when the numbers draw (final review I4) -->
    <div class="stats" aria-busy="true" data-test="sync-totals-wait">
      <StatCard value={null} label="added"><QualityBar by_quality={null} height={6} legend /></StatCard>
      <div class="pair"><StatCard value={null} label="moved" /><StatCard value={null} label="need you" /></div>
    </div>
  {:else}
    <div class="stats" data-test="sync-totals">
      <StatCard value={m.stats.added} label="added" valueTest="end-added">
        {#if m.stats.byQuality}<QualityBar by_quality={m.stats.byQuality} height={6} legend />{/if}
      </StatCard>
      <div class="pair">
        <StatCard value={m.stats.moved} label="moved" valueTest="end-moved" />
        <StatCard value={m.stats.needs} label={m.stats.needs === 1 ? 'needs you' : 'need you'} valueTest="end-needs" />
      </div>
    </div>

    {#if m.notes.length}
      <Surface kind="list" data-test="sync-notes" style="--row-cols: minmax(0, 1fr) auto">
        {#each m.notes as n (n.test)}
          <ListRow test={n.test} title={n.text}>
            {#snippet name()}{n.text}{/snippet}
            {#snippet trailing()}{#if n.review}<Button variant="link" size="sm" href={REVIEW}>Review →</Button>{/if}{/snippet}
          </ListRow>
        {/each}
      </Surface>
    {/if}

    {#if m.needs.length}
      <Surface kind="list" label="Needs you" summary={String(m.needs.length)} data-test="sync-needs-you" style={COLS}>
        {#each m.needs as r, i (i)}{@render row(r, r.folder, 'fix', true)}{/each}
      </Surface>
    {/if}

    {#if m.added.length}
      <div class="added" data-test="sync-added">
        <Hint text="Add the new files in rekordbox: Show in Finder opens each folder." data-test="end-rekordbox" />
        {#each m.added as g (g.folder)}
          <Surface kind="list" label={g.folder} summary={plural(g.rows.length, 'new track')} data-test="end-group"
            data-folder={g.folder} style={COLS}>
            {#snippet header()}
              <Button variant="link" size="sm" onclick={() => api.reveal(g.reveal)}
                title="Open the folder to add the new files in rekordbox" data-test="end-reveal">Show in Finder ↗</Button>
            {/snippet}
            {#each g.rows as r, i (r.track_id ?? i)}{@render row(r, r.note, null)}{/each}
          </Surface>
        {/each}
      </div>
    {/if}

    {#if m.other.length}
      <Surface kind="list" label="Other changes" summary={String(m.other.length)} data-test="sync-other" style={COLS}>
        {#each m.other as r, i (r.track_id ?? i)}
          {@render row(r, otherDetail(r), r.section === 'upgrade_ready' ? 'review' : null)}
        {/each}
      </Surface>
    {/if}
  {/if}
{/snippet}

{#snippet foot()}
  <div class="acts">
    {#if failed}
      <Button onclick={back} data-test="back-to-plan">Back to the plan</Button>
      <Button variant="filled" onclick={done} data-test="sync-done-button">Done</Button>
    {:else if m?.syncRest}
      <Button onclick={done} data-test="sync-done-button">Done</Button>
      <Button variant="filled" onclick={back} data-test="back-to-plan">Sync the rest →</Button>
    {:else}
      <Button variant="filled" onclick={done} data-test="sync-done-button">Done</Button>
    {/if}
  </div>
{/snippet}

<div class="end" data-test="sync-end" data-run={run_id ?? ''} data-state={failed ? 'failed' : detail ? 'loaded' : 'loading'}>
  <ColumnFrame {content} {foot} />
</div>

<style>
  .end { flex: 1; min-height: 0; display: flex; flex-direction: column; }
  /* the up-to-date panel's composition (same numbers, §11): added with its quality bar across, then moved · need you
     as a pair, each card as tall as what it holds, so none is an empty box */
  .stats { display: flex; flex-direction: column; gap: var(--s-3); }
  .pair { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--s-3); }
  .added { display: flex; flex-direction: column; gap: var(--s-3); }
  .shop { margin-left: var(--s-3); }
  /* the action's slot, in every list of the view, so the badges share one right edge whether or not a row has an
     action; the same 64 px as the running view's (RunList) */
  .act { display: inline-flex; justify-content: flex-end; min-width: var(--w-row-action); }
  /* the actions sit at the foot's right edge, the filled one last (macOS: the default button at the right) */
  .acts { margin-left: auto; display: flex; align-items: center; gap: var(--s-2); }
</style>
