<script lang="ts">
  // Sync screen: before the start, the live view, or the end screen (plan Task 65, "Which view shows"), of the window's
  // own sync or of the one the Terminal runs (issue 39 E4b). The Terminal's is followed (`followRun`, which reads the
  // job's events only while someone subscribes) for as long as this page knows it, so its live view and its end screen
  // stay current.
  import { readable } from 'svelte/store';
  import { EMPTY_RUN, run } from '$lib/stores/run';
  import { hub, hubSyncRunning } from '$lib/stores/hub';
  import { followRun, terminalSync } from '$lib/stores/follow';
  import { dismissedJobs, lastSyncEnd, whichView } from './view';
  import { ownSource, terminalSource } from './liveSource';
  import BeforeStart from './BeforeStart.svelte';
  import LiveView from './LiveView.svelte';
  import EndScreen from './EndScreen.svelte';

  let { params, query: _query }: { params: Record<string, string>; query: URLSearchParams } = $props();
  const NONE = readable(EMPTY_RUN);
  const followed = $derived($terminalSync ? followRun($terminalSync.job) : NONE);
  const v = $derived(whichView({ own: $run, hubSyncRunning: $hubSyncRunning, route: params.run_id, dismissed: $dismissedJobs,
    terminal: $terminalSync && { sync: $terminalSync, run: $followed }, newest: $hub.last_sync?.job ?? null, lastEnd: $lastSyncEnd }));
  const terminalJob = $derived($terminalSync?.job ?? null);
  const source = $derived(v.view !== 'before' && v.source === 'terminal' && terminalJob
    ? terminalSource(terminalJob, followed, $terminalSync?.where ?? null) : ownSource);
</script>

<div class="sync" data-view={v.view} data-source={v.view === 'before' ? null : v.source}>
  {#if v.view === 'end'}
    {#key `${v.source}:${v.run_id}`}<EndScreen run_id={v.run_id} run={source.run} />{/key}
  {:else if v.view === 'live'}
    {#key `${source.kind}:${source.job}`}<LiveView {source} />{/key}
  {:else}
    <BeforeStart />
  {/if}
</div>

<style>
  /* the frames bring the padding: ListPanelFrame before the start, ColumnFrame while running and at the end */
  .sync { height: 100%; min-height: 0; display: flex; flex-direction: column; }
</style>
