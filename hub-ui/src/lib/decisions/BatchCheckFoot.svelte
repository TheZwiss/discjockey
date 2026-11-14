<script lang="ts">
  // The foot of a batch card or of several checks selected (plan issue 33 stage B §6.4), read as the single check's
  // foot (CheckFoot): "Done, checked in rekordbox" ("Done" when none of them is in rekordbox) as the screen's one filled
  // button for every track shown, and under
  // it, full width and plain, "Undo all {n}" when every track can be undone, else "Undo {n}" (n the tracks that can
  // still be undone; none: no button) with the muted line "{k} can't be undone" under it. Under them what an undo left
  // as a warn NoteCard at the panel's full width, the colour of the rows' reasons (design §8's words when rekordbox is
  // open; the track not undone by name, or how many, each row says why). A batch the sync started (`fromSync`) names
  // its undo "Undo all from this sync".
  import type { TodoItem } from '$lib/bridge/types';
  import { Hint, NoteCard, WriteButton } from '$lib/components';
  import { doneLabel, undoFoot, undoProblemLine, undoTitle } from './decisionModel';
  import type { ChecksFlow } from './flows.svelte';

  let { tracks, flow, nameOf, fromSync = false }: { tracks: TodoItem[]; flow: ChecksFlow; nameOf: (i: TodoItem) => string;
    /** the batch is the sync's Auto-upgrade: its undo reads "Undo all from this sync" */
    fromSync?: boolean } = $props();

  // a track whose undo was just refused isn't offered again until the next pick: it would only be refused again
  const undo = $derived(undoFoot(tracks, flow.problem?.rows, fromSync));
  const undone = $derived(tracks.filter((t) => undo.ids.includes(t.track_id)).map((t) => t.check));
  const names = $derived(new Map(tracks.map((t) => [t.track_id, nameOf(t)])));
</script>

<WriteButton variant="filled" wide busy={flow.busy === 'done'} disabled={!!flow.busy && flow.busy !== 'done'}
  onclick={() => flow.checked(tracks.map((t) => t.track_id))} data-test="rekordbox-done">{doneLabel(tracks.map((t) => t.check))}</WriteButton>
{#if undo.ids.length}
  <WriteButton wide busy={flow.busy === 'undo' || !!flow.busy?.startsWith('undo:')} busyLabel={flow.busy?.startsWith('undo:') ? 'Undoing' : undefined}
    disabled={!!flow.busy && !flow.busy.startsWith('undo')}
    onclick={() => flow.undo(undo.ids, undefined, undone)} title={undoTitle(undone)}
    data-test="checks-undo">
    <svg class="undo" viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5"
      stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 3L2 5.5 4.5 8" /><path d="M2.3 5.5h6.2a3.2 3.2 0 010 6.4H6" /></svg>
    {undo.label}</WriteButton>
{/if}
{#if undo.cant}<div class="cant"><Hint text={undo.cant} data-test="undo-cant" /></div>{/if}
{#if flow.problem}
  <NoteCard tone={flow.problem.tone} data-test="undo-problem">{undoProblemLine(flow.problem, (id) => names.get(id) ?? 'A track')}</NoteCard>
{/if}

<style>
  .undo { width: 14px; height: 14px; flex-shrink: 0; }
  .cant :global(.hint) { text-align: center; }
</style>
