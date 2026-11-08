<script lang="ts">
  // The foot of a batch card or of several checks selected (plan issue 33 stage B §6.4), read as the single check's
  // foot (CheckFoot): "Done, checked in rekordbox" as the screen's one filled button for every track shown, and under
  // it, full width and plain, "Undo all {n}" (a batch) or "Undo {n}" (a selection), n the tracks that can still be
  // undone (none: no button). Under them the one line an undo left (design §8's words when rekordbox is open; how many
  // weren't undone, each row says why).
  import type { TodoItem } from '$lib/bridge/types';
  import { Hint, WriteButton } from '$lib/components';
  import { undoAllLabel, undoManyLabel } from './decisionModel';
  import type { ChecksFlow } from './flows.svelte';

  let { tracks, batch, flow }: { tracks: TodoItem[]; batch: { id: number } | null; flow: ChecksFlow } = $props();

  // a track whose undo was just refused isn't offered again until the next pick: it would only be refused again
  const undoable = $derived(tracks.filter((t) => t.can_undo && !flow.problem?.rows[t.track_id]).map((t) => t.track_id));
</script>

<WriteButton variant="filled" wide busy={flow.busy === 'done'} disabled={!!flow.busy && flow.busy !== 'done'}
  onclick={() => flow.checked(tracks.map((t) => t.track_id))} data-test="rekordbox-done">Done, checked in rekordbox</WriteButton>
{#if undoable.length}
  <WriteButton wide busy={flow.busy === 'undo' || !!flow.busy?.startsWith('undo:')} busyLabel={flow.busy?.startsWith('undo:') ? 'Undoing' : undefined}
    disabled={!!flow.busy && !flow.busy.startsWith('undo')}
    onclick={() => flow.undo(undoable)} title="Puts your old files back; the new versions wait again"
    data-test="checks-undo">
    <svg class="undo" viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5"
      stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 3L2 5.5 4.5 8" /><path d="M2.3 5.5h6.2a3.2 3.2 0 010 6.4H6" /></svg>
    {batch ? undoAllLabel(undoable.length) : undoManyLabel(undoable.length)}</WriteButton>
{/if}
{#if flow.problem}<Hint text={flow.problem.line} tone="problem" wrap data-test="undo-problem" />{/if}

<style>
  .undo { width: 14px; height: 14px; flex-shrink: 0; }
</style>
