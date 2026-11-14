<script lang="ts">
  // The AIFF card of one track (issue 33 stage D, plan §6.1): what Convert to AIFF or Give it its clean name would do
  // for this file, the same in the Library's details and, in U3, in To-do's CDJ item (each with its own foot: AiffFoot
  // is the Library's). The card is the "AIFF" Surface with its rows (NOW, BECOMES, NAME and SPACE for a Convert; NAME
  // alone for a Rename, as old name over new name: file names are too long to share a 320 px line; the old name gives way
  // in its middle, the new one is shown whole and wraps; a blocked step shows the same rows, its Hint says why) and, for a Convert
  // with a rekordbox Discjockey can open, design §8's outcome rows. Around it, as sibling NoteCards (a note inside a
  // card would be a container in a container): the job's problem and what the CDJs refuse in the file (warn, above, where the
  // sync's refusals stand in UpgradeCards) and, for a lossy file, what the AIFF costs (info, under it). The button and
  // why it may be off are the foot's. `rekordbox` is the one answer the Sync page reads too (AiffFlow.rekordbox); null
  // until it is known leaves out what depends on it.
  import type { RekordboxStatus, TrackAiff } from '$lib/bridge/types';
  import { KeyValue, MiddleText, NoteCard, OutcomeList, Surface } from '$lib/components';
  import { aiffNotes, aiffOutcomes, aiffRows } from './aiffModel';

  let { aiff, rekordbox = null, problem = null }: {
    aiff: TrackAiff; rekordbox?: RekordboxStatus | null;
    /** what the last press said when the track didn't go: a refusal (rekordbox open) or the track's own skip */
    problem?: string | null;
  } = $props();

  const rows = $derived(aiffRows(aiff));
  const outcomes = $derived(aiffOutcomes(aiff, rekordbox));
  const notes = $derived(aiffNotes(aiff));
</script>

{#if problem}<NoteCard tone="warn" data-test="aiff-problem">{problem}</NoteCard>{/if}
{#each notes.above as n (n.key)}<NoteCard tone={n.tone} data-test="aiff-{n.key}">{n.text}</NoteCard>{/each}

<Surface kind="card" label="AIFF" data-test="aiff-card" data-action={aiff.action ?? 'none'} data-kind={aiff.kind}>
  <div class="col">
    {#if rows.length}
      <div class="rows">
        {#each rows as r (r.key)}
          {#if r.key === 'name'}
            <KeyValue keyWidth={76} k={r.k}>
              <span class="names" data-test="aiff-name">
                <MiddleText text={r.from ?? ''} />
                {#if r.to}<span class="to"><span class="arrow" aria-hidden="true">→</span><span class="new" data-test="aiff-new-name">{r.to}</span></span>{/if}
              </span>
            </KeyValue>
          {:else}<KeyValue keyWidth={76} k={r.k} v={r.v} />{/if}
        {/each}
      </div>
    {/if}
    {#if outcomes.length}<OutcomeList items={outcomes} test="aiff-outcomes" />{/if}
  </div>
</Surface>

{#each notes.below as n (n.key)}<NoteCard tone={n.tone} data-test="aiff-{n.key}">{n.text}</NoteCard>{/each}

<style>
  .col { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
  .rows { display: flex; flex-direction: column; }
  /* the name now, then the name it gets on its own line: the old one is the past, so it is the quiet one */
  .names { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .names > :global(.mid:first-child:not(:last-child)) { color: var(--text-muted); }
  /* the new name is the one to read: whole, wrapping where the column ends; only the old name gives way in its middle */
  .new { min-width: 0; overflow-wrap: anywhere; }
  .to { display: grid; grid-template-columns: 14px minmax(0, 1fr); align-items: baseline; min-width: 0; }
  .arrow { color: var(--text-label); }
</style>
