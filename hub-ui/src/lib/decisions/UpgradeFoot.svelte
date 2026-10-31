<script lang="ts">
  // The upgrade decision's foot (mockup todo-decisions), the same in To-do's and the Library's details: "Replace with
  // lossless" as the screen's one filled button (the "In rekordbox" pick: Same track = swap, New track = add_new),
  // "Discard the new version" under it, and when a replace can be undone. Its flow is the one UpgradeCards reads.
  import type { Upgrade } from '$lib/bridge/types';
  import { Hint, WriteButton } from '$lib/components';
  import { replaceLabel, type Way } from './decisionModel';
  import type { UpgradeFlow } from './flows.svelte';

  let { track_id, upgrade, way, flow }: { track_id: string; upgrade: Upgrade; way: Way; flow: UpgradeFlow } = $props();
</script>

<WriteButton variant="filled" wide busy={flow.busy === way} disabled={flow.busy !== null && flow.busy !== way}
  onclick={() => flow.upgrade(track_id, way)} data-test="upgrade-replace" data-mode={way}>{replaceLabel(upgrade)}</WriteButton>
<WriteButton wide busy={flow.busy === 'discard'} disabled={flow.busy !== null && flow.busy !== 'discard'}
  onclick={() => flow.upgrade(track_id, 'discard')} title="Deletes the new version; it isn't offered again"
  data-test="upgrade-discard">Discard the new version</WriteButton>
<div class="centered"><Hint text="You can undo a replace until you press Done" /></div>

<style>
  .centered :global(.hint) { text-align: center; }
</style>
