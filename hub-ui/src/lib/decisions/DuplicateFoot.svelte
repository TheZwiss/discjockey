<script lang="ts">
  // "Which file stays?"'s foot, the same in To-do's and the Library's details: the one filled button names the result
  // ("Keep the AIFF"; off with "Choose the file that stays" until a pick), the line under it says the others aren't
  // deleted. Its flow is the one DuplicateChoice picks in.
  import type { DuplicateItem } from '$lib/bridge/types';
  import { Hint, WriteButton } from '$lib/components';
  import { keepWords } from './decisionModel';
  import type { DuplicateFlow } from './flows.svelte';

  let { item, flow }: { item: DuplicateItem; flow: DuplicateFlow } = $props();

  const g = $derived(item.pair);
  const pick = $derived(flow.pick(g));
  const words = $derived(keepWords(g.files, pick));
</script>

<WriteButton variant="filled" wide busy={flow.busy} disabled={!words.ready} onclick={() => void flow.keep(g, pick)}
  data-test="duplicates-keep">{words.label}</WriteButton>
{#if words.hint}<div class="centered"><Hint text={words.hint} wrap data-test="duplicates-hint" /></div>{/if}

<style>
  .centered :global(.hint) { text-align: center; }
</style>
