<script lang="ts">
  // The rekordbox check a replace left (mockup todo-decisions, "After the step"; README "Upgrades"): "In rekordbox"
  // (yellow: it waits for the user) as numbered steps in place of a paragraph, then "Replaced with lossless" with where
  // each file is now and what Undo puts back (only while it can). Any other check (a wrong song fixed) keeps its one
  // note, the engine's whole instruction.
  import type { TodoItem } from '$lib/bridge/types';
  import { Hint, NoteCard, NumberedSteps, Surface } from '$lib/components';
  import { checkCard, localDay, replacedCard, sinceText } from './todoModel';

  let { item }: { item: TodoItem } = $props();

  const card = $derived(checkCard(item.check));
  const replaced = $derived(replacedCard(item.check, item));
  const since = $derived(sinceText(item.check?.since ?? null, localDay(new Date())));
</script>

{#if card}
  <Surface kind="card" tone="warn" label="In rekordbox" summary={card.summary} data-test="rekordbox-check"
    data-reason={item.check?.reason}>
    <div class="col">
      <NumberedSteps test="rekordbox-steps">
        {#each card.steps as s, i (i)}
          <li><span class="step">{#each s.parts as p, j (j)}{#if p.strong}<b>{p.text}</b>{:else}{p.text}{/if}{/each}{#if s.note}{' '}<span class="note">{s.note}</span>{/if}</span></li>
        {/each}
      </NumberedSteps>
      {#if card.hint}<Hint text={card.hint} wrap />{/if}
    </div>
  </Surface>
  {#if replaced}
    <Surface kind="card" label={replaced.title} summary={since || undefined} data-test="replaced">
      <div class="col">
        <div class="changes">
          {#each replaced.rows as r (r.name)}
            <div class="chg">
              <svg viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.3"
                stroke-linejoin="round">
                {#if r.icon === 'file'}<path d="M3.5 1.5h4.5l2.5 2.5v8.5h-7z" /><path d="M8 1.5V4h2.5" />
                {:else}<path d="M1.5 3.5h4l1.2 1.3h5.8v6.7h-11z" />{/if}
              </svg>
              <span class="p"><b title={r.name}>{r.name}</b><span title={r.where}>{r.where}</span></span>
            </div>
          {/each}
        </div>
        {#if item.can_undo}<Hint text={replaced.undo} />{/if}
      </div>
    </Surface>
  {/if}
{:else}
  <NoteCard tone="warn" data-test="rekordbox-check">{item.check?.text ?? item.detail}</NoteCard>
{/if}

<style>
  .col { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
  .step { font-size: var(--fs-small); line-height: 17px; color: var(--text); }
  .step b { font-weight: var(--fw-semi); }
  .note { color: var(--text-muted); }
  .changes { display: flex; flex-direction: column; }
  .chg { display: grid; grid-template-columns: 20px minmax(0, 1fr); gap: var(--s-2); align-items: center; padding: 7px 0;
    border-top: var(--bw) solid var(--line-soft); font-size: var(--fs-small); }
  .chg:first-child { border-top: 0; padding-top: 0; }
  .chg svg { width: 14px; height: 14px; color: var(--text-label); }
  .p { min-width: 0; display: flex; flex-direction: column; }
  .p b { font-weight: var(--fw-medium); color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .p span { color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
