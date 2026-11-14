<script lang="ts">
  // The rekordbox check's foot (mockup todo-decisions, "After the step"), the same in To-do's and the Library's
  // details: "Done, checked in rekordbox" as the screen's one filled button and, while the replace that left the check
  // can still be undone (item.can_undo), "Undo the replace" (a Convert: "Undo the conversion", a clean name: "Undo the clean name") under it (full width, plain, the same width as Done), with
  // an undo's refusal under that until the next track (a warn NoteCard, as the batch card's foot).
  import type { TodoItem } from '$lib/bridge/types';
  import { NoteCard, WriteButton } from '$lib/components';
  import { undoLabel } from './decisionModel';
  import type { UpgradeFlow } from './flows.svelte';

  let { item, flow }: { item: TodoItem; flow: UpgradeFlow } = $props();
</script>

<WriteButton variant="filled" wide busy={flow.busy === 'rekordbox'} disabled={flow.busy === 'undo'}
  onclick={() => flow.checked(item.track_id)} data-test="rekordbox-done">Done, checked in rekordbox</WriteButton>
{#if item.can_undo}
  <WriteButton wide busy={flow.busy === 'undo'} disabled={flow.busy === 'rekordbox'}
    onclick={() => flow.undo(item.track_id, item.check)} title={item.check?.reason === 'converted' || item.check?.reason === 'renamed' ? 'Puts your old file or name back' : 'Puts your old file back; the new version waits again'}
    data-test="upgrade-undo">
    <svg class="undo" viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5"
      stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 3L2 5.5 4.5 8" /><path d="M2.3 5.5h6.2a3.2 3.2 0 010 6.4H6" /></svg>
    {undoLabel(item.check)}</WriteButton>
  {#if flow.undoProblem}<NoteCard tone="warn" data-test="undo-problem">{flow.undoProblem}</NoteCard>{/if}
{/if}

<style>
  .undo { width: 14px; height: 14px; flex-shrink: 0; }
</style>
