<script lang="ts">
  // Only a picture of where to drop: pywebview catches the drop on the whole window (FileDropped event).
  import { dragging } from '../stores/drag';
  import MiddleText from './MiddleText.svelte';
  import PathText from './PathText.svelte';
  import Spinner from './Spinner.svelte';
  let { trackName, expectedName, busy = false, error = null, fileName = null, over }:
    { trackName: string; expectedName?: string; busy?: boolean; error?: string | null; fileName?: string | null;
      over?: boolean } = $props();
  // `over` only for the gallery: shows the dragging look without a drag
  const dragged = $derived(over ?? $dragging);
</script>

<div class="dz" class:over={dragged && !busy} class:busy class:bad={!!error && !dragged} data-test="dropzone"
  aria-label="Drop zone for the bought file of {trackName}">
  {#if busy}
    <!-- the name has a line of its own: it breaks nowhere, a long one gives way in its middle (the end, ".wav", stays) -->
    <Spinner size={14} /><p class="big">Adding…</p>
    <div class="file"><MiddleText text={fileName ?? trackName} /></div>
  {:else if dragged}
    <p class="big">Drop it to add it to {trackName}</p>
  {:else}
    <p class="big">Drag the file here</p>
    <p class="small">WAV, AIFF, FLAC or MP3 · renamed and filed automatically</p>
    <!-- the target breaks only after a "/"; a name stays whole unless it alone is wider than the zone -->
    {#if expectedName}<p class="small path"><PathText path={expectedName} lead="→ " /></p>{/if}
    {#if error}<p class="err">{error}</p>{/if}
  {/if}
</div>

<style>
  .dz { border: var(--bw-accent) dashed var(--line-control); border-radius: var(--r-surface); padding: var(--s-4);
    display: flex; flex-direction: column; align-items: center; gap: 4px; text-align: center; color: var(--text-muted);
    transition: border-color var(--t-press), background-color var(--t-press); }
  .over { border-color: var(--accent); background: var(--accent-wash); color: var(--accent-text); }
  .busy { border-style: solid; }
  .bad { border-color: var(--q-weak-line); }
  .big { font-weight: var(--fw-semi); }
  .file { align-self: stretch; min-width: 0; font-weight: var(--fw-semi); }
  .small { font-size: var(--fs-small); color: var(--text-label); }
  .path { max-width: 100%; }
  .err { color: var(--q-weak); font-size: var(--fs-small); max-width: 420px; user-select: text; -webkit-user-select: text; }
</style>
