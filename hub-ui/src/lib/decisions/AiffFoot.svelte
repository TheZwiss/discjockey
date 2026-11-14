<script lang="ts">
  // The AIFF card's foot in the Library's details (plan §6.1): "Convert to AIFF" or "Give it its clean name", the
  // panel's one filled button for a lossless file, a file the CDJs refuse and a Rename, an outlined one for any other
  // lossy file (a choice that costs space, not a recommendation). A card that can't run keeps the button, off, with the
  // reason as the Hint under it. Its flow is the one AiffCard's page holds (a To-do panel passes its own foot).
  import type { TrackAiff } from '$lib/bridge/types';
  import { Hint, WriteButton } from '$lib/components';
  import { aiffAction, aiffBlocked, aiffLabel, aiffVariant } from './aiffModel';
  import type { AiffFlow } from './flows.svelte';

  let { track_id, aiff, flow }: { track_id: string; aiff: TrackAiff; flow: AiffFlow } = $props();

  const blocked = $derived(aiffBlocked(aiff, flow.rekordbox));
  const variant = $derived(aiffVariant(aiff));
  const action = $derived(aiffAction(aiff));
</script>

<WriteButton variant={variant === 'filled' ? 'filled' : 'secondary'} wide busy={flow.busy} disabled={!!blocked}
  onclick={() => flow.run(track_id, action)} data-test="aiff-run" data-action={action} data-variant={variant}>{aiffLabel(aiff)}</WriteButton>
{#if blocked}<div class="reason"><Hint text={blocked} wrap data-test="aiff-blocked" /></div>{/if}

<style>
  .reason :global(.hint) { text-align: center; }
</style>
