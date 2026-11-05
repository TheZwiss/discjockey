<script lang="ts">
  // Songs held back until "Is this the same song?" is answered (plan library stage 4, W9; issue 27): the warn note
  // with the way to To-do's questions. Shared by the plan's run panel (why its count is smaller) and the Up-to-date
  // view (where every remaining song waits for an answer, so nothing else would point at them). Nothing at 0.
  import { Button, NoteCard } from '$lib/components';
  import { WAITING_ANSWERS_HREF, waitingAnswersLine } from '../planModel';

  let { n }: { n: number } = $props();
  const line = $derived(waitingAnswersLine(n));
</script>

{#if line}
  <NoteCard tone="warn" data-test="sync-waiting-answers">{line}
    <div class="act"><Button variant="link" size="sm" href={WAITING_ANSWERS_HREF} data-test="sync-waiting-link">To-do →</Button></div>
  </NoteCard>
{/if}

<style>
  .act { margin-top: var(--s-1); }
</style>
