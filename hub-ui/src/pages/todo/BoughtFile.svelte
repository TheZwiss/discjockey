<script lang="ts">
  // The bought file (drag and drop, spec §6.6). Python handles the drop on the whole document; this zone reacts to
  // FileDropped: add the file to the selected track, show macOS's refusal inline (a drop with nothing selected is
  // toasted by the shell).
  import type { TrackDetail } from '$lib/bridge/types';
  import { api, runJob } from '$lib/bridge/client';
  import { onEvent } from '$lib/bridge/events';
  import { artistTitle } from '$lib/format';
  import { Button, DropZone } from '$lib/components';
  import { dragging } from '$lib/stores/drag';
  import { dropDecision, filedAs } from './todoModel';

  let { track }: { track: TrackDetail } = $props();
  let busy = $state(false);
  let error = $state<string | null>(null);
  let fileName = $state<string | null>(null);
  let canRetry = $state(false);     // the add was refused (e.g. busy): the dropped file is kept, so try again

  $effect(() => onEvent((e) => {
    if (e.type !== 'FileDropped' || busy) return;
    const d = dropDecision(e, track.track_id);
    if (d.do === 'message') { error = d.text; fileName = e.name; canRetry = false; }
    else if (d.do === 'add') { fileName = e.name; void add(); }
  }));

  async function add() {
    error = null; canRetry = false; busy = true;
    const o = await runJob(api.add_bought_file(track.track_id), { quiet: true });
    busy = false;
    if (o.ok) { fileName = null; return; }      // success toast from runJob; the page re-fetches
    error = o.message; canRetry = o.job_id === null;
  }
  const zone = $derived($dragging ? 'dragging' : busy ? 'busy' : error ? 'blocked' : 'idle');
</script>

<div class="bought" data-test="bought-file" data-state={zone}>
  <DropZone trackName={artistTitle(track.artist, track.title)} expectedName={filedAs(track.bought_name)}
    {busy} {error} {fileName} />
  {#if canRetry && error && !busy}
    <Button size="sm" onclick={add} data-test="add-again">Add {fileName ?? 'the file'} again</Button>
  {/if}
</div>

<style>
  .bought { display: flex; flex-direction: column; gap: var(--s-2); align-items: flex-start; }
  .bought > :global(:first-child) { align-self: stretch; }
</style>
