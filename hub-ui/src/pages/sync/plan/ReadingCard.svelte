<script lang="ts">
  // While the playlists are read (spec §8): a Surface card, the way every status sits in a container (§4). The spinner and
  // the title read first; which playlist, out of how many, sits at the card's right edge as a count, and the bar under
  // them shows the same share (§4: a quantity is a number plus a visual). The card is neutral, not orange: orange is
  // action and selection (§4), and this is status; the bar keeps the accent because it is the read the user (or the
  // hub) started moving. `stale` (a plan or the up-to-date card is shown below, from the last read) adds the Hint
  // that says so; on the first read there is nothing below and the panel already says where the plan will show.
  import { Hint, ProgressBar, Spinner, Surface } from '$lib/components';
  import type { ReadProgress } from '$lib/stores/hub';
  let { progress, stale = false }: { progress: ReadProgress | null; stale?: boolean } = $props();
  const value = $derived(progress ? Math.max(0.04, (progress.index - 0.5) / Math.max(progress.total, 1)) : null);
</script>

<Surface kind="card" class="reading-card" role="status" data-test="sync-reading">
  <div class="line">
    <Spinner size={12} label="Reading playlists" />
    <span class="title">Reading your playlists</span>
    {#if progress}<span class="where" data-test="sync-reading-where" title="{progress.index} of {progress.total} · {progress.folder}"><span
      class="n">{progress.index} of {progress.total}</span> · {progress.folder}</span>{/if}
  </div>
  <ProgressBar {value} pace="live" label="Reading playlists" />
  {#if stale}<Hint text="What's below is from the last read · it updates when this is done" />{/if}
</Surface>

<style>
  .line { display: flex; align-items: center; gap: var(--s-2); min-width: 0; color: var(--text-muted); }
  .title { flex: none; font-weight: var(--fw-semi); color: var(--text-strong); white-space: nowrap; }
  /* the count at the card's right edge, where counts sit in every list (§4); a long folder name ends in "…" */
  .where { margin-left: auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    font-size: var(--fs-small); color: var(--text-muted); }
  .n { color: var(--text); font-variant-numeric: tabular-nums; }
</style>
