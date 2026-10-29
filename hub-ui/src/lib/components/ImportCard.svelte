<script lang="ts">
  // The import of the user's own music as one card (plan library stage 4, W6), shared by Settings → Watched folders
  // and Setup's "Your existing music": while it runs, its phase line over a live bar with Stop at the card head's
  // end; once stopped, how many files are left; at its end, how many came in. The import starts by itself (D14);
  // this card only follows it. Presentational: `view` from `importView`, the actions from the page's flow.
  // `oncontinue`: Continue import inside the card (Setup, whose step actions sit in their cards); Settings keeps it in
  // its panel foot instead and passes none.
  import Button from './Button.svelte';
  import ProgressBar from './ProgressBar.svelte';
  import StatusMark from './StatusMark.svelte';
  import Surface from './Surface.svelte';
  import WriteButton from './WriteButton.svelte';
  import type { ImportView } from './watchedFoldersModel';

  let { view, onstop, oncontinue, continueFilled = false, starting = false, test = 'import-card' }: {
    view: ImportView; onstop?: () => void; oncontinue?: () => void; continueFilled?: boolean; starting?: boolean;
    test?: string;
  } = $props();

  const tone = $derived(view.kind === 'done' ? 'good' : view.kind === 'failed' ? 'problem' : 'default');
</script>

<Surface kind="card" label="Import" {tone} data-test={test} data-kind={view.kind}>
  {#snippet header()}
    {#if view.kind === 'running' && onstop}
      <Button size="sm" busy={view.stopping} busyLabel="Stopping" disabled={view.stopping} onclick={onstop}
        data-test="{test}-stop">Stop</Button>
    {/if}
  {/snippet}
  {#if view.kind === 'running'}
    <div class="run">
      <span class="line" data-test="{test}-line">{view.line}</span>
      <ProgressBar value={view.share} pace="live" label={view.line} />
    </div>
  {:else}
    <div class="state">
      {#if view.kind === 'done'}<StatusMark tone="good" />{:else if view.kind === 'failed'}<StatusMark tone="problem" />
      {:else}<StatusMark tone="warn" />{/if}
      <span class="text" data-test="{test}-line">{view.line}</span>
    </div>
    {#if view.kind === 'stopped' && oncontinue}
      <div><WriteButton variant={continueFilled ? 'filled' : 'primary'} size="sm" busy={starting} onclick={oncontinue}
        data-test="{test}-continue">Continue import</WriteButton></div>
    {/if}
  {/if}
</Surface>

<style>
  .run { display: flex; flex-direction: column; gap: var(--s-2); min-width: 0; }
  .line { color: var(--text-strong); font-variant-numeric: tabular-nums; min-width: 0; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap; }
  .state { display: grid; grid-template-columns: 16px minmax(0, 1fr); gap: var(--s-2); align-items: start; min-width: 0; }
  /* the stopped and done lines are sentences: they wrap inside the card, beside the mark's gutter */
  .text { color: var(--text-strong); line-height: 1.45; overflow-wrap: anywhere; }
</style>
