<script lang="ts">
  // Sync screen: before the start, the live view, or the end screen (plan Task 65, "Which view shows").
  import { run } from '$lib/stores/run';
  import { hubSyncRunning } from '$lib/stores/hub';
  import { dismissedJob, whichView } from './view';
  import BeforeStart from './BeforeStart.svelte';
  import LiveView from './LiveView.svelte';
  import EndScreen from './EndScreen.svelte';

  let { params, query: _query }: { params: Record<string, string>; query: URLSearchParams } = $props();
  const v = $derived(whichView($run, $hubSyncRunning, params.run_id, $dismissedJob));
</script>

<div class="sync" data-view={v.view}>
  {#if v.view === 'end'}
    {#key v.run_id}<EndScreen run_id={v.run_id} />{/key}
  {:else if v.view === 'live'}
    <LiveView />
  {:else}
    <BeforeStart />
  {/if}
</div>

<style>
  /* the frames bring the padding: ListPanelFrame before the start, ColumnFrame while running and at the end */
  .sync { height: 100%; min-height: 0; display: flex; flex-direction: column; }
</style>
