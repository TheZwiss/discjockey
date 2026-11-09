<script lang="ts">
  // The rekordbox checks of one Same track batch, and of several checks selected (plan issue 33 stage B §6.4): the To-do
  // panel while a batch item ("3 tracks upgraded") or two or more checks are selected. One Panel, read as the single
  // check card reads (CheckCards: "In rekordbox" first, then what changed) and laid out as the upgrade selection panel
  // (UpgradeSelection: the tracks as the one list of unknown length in `fill`, scrolling in place):
  // - a batch: "In rekordbox" (yellow: it waits for the user) as numbered steps for the tracks rekordbox has (Reload
  //   Tag only for the tracks whose text Discjockey couldn't write, by name; analyse them again; the USB stick), then
  //   "Upgraded n today" with a row per track: its new file, what was kept as the user edited it, a file rekordbox
  //   doesn't have, and "Undo this one" while it can;
  // - several checks: "{N} checks selected" (N list items) over "{n} tracks", with a row per track saying what is left
  //   to do in rekordbox (each check can be of another kind, so the row's own line, as in the to-do list).
  // The foot is BatchCheckFoot: Done for all of them, Undo all n (every track can go) / Undo n and how many can't. An
  // undo that left tracks as they were says why in their rows, one line under the buttons.
  import { untrack } from 'svelte';
  import type { TodoItem } from '$lib/bridge/types';
  import { Cover, ListRow, NumberedSteps, Surface, WriteButton } from '$lib/components';
  import { Panel } from '$lib/frames';
  import BatchCheckFoot from './BatchCheckFoot.svelte';
  import {
    batchCheckCard, checkRow, checksTitle, focusAfterRowGone, localDay, sinceText, tracksSummary, type CheckRow,
  } from './decisionModel';
  import { refocus } from './focus';
  import type { ChecksFlow } from './flows.svelte';

  let { tracks, batch = null, selected = tracks.length, nameOf, flow }: {
    /** the checks' tracks, in list order (a batch item's `batch.tracks`, or every selected item with batches opened) */
    tracks: TodoItem[];
    /** several checks selected: how many list items that is (a batch among them is one item, several tracks); the
     *  title counts items as the list, tab and chips do, the summary the tracks */
    selected?: number;
    /** the batch these tracks are (one batch item selected), null for several checks selected */
    batch?: { id: number; started: string | null } | null;
    nameOf: (i: TodoItem) => string;
    flow: ChecksFlow;
  } = $props();

  const card = $derived(batch ? batchCheckCard(tracks, nameOf) : null);
  const rows = $derived(tracks.map((t) => checkRow(t, nameOf(t), batch ? 'file' : 'detail')));
  const day = $derived(batch ? sinceText(batch.started, localDay(new Date())) : '');
  const refused = $derived(flow.problem?.rows ?? {});
  const byId = $derived(new Map(tracks.map((t) => [t.track_id, t])));

  // "Undo this one" takes its row out of the list: focus goes to the next row's undo, else Done (only when it was lost)
  let root = $state<HTMLElement>();
  let before = untrack(() => rows.map((r) => r.track_id));
  $effect(() => {
    const ids = rows.map((r) => r.track_id);
    const withUndo = new Set(rows.filter((r) => r.can_undo && !refused[r.track_id]).map((r) => r.track_id));
    untrack(() => {
      const was = before;
      before = ids;
      if (ids.length >= was.length) return;
      const next = focusAfterRowGone(was, ids, withUndo);
      void refocus(() => (next
        ? root?.querySelector<HTMLElement>(`[data-test="check-row"][data-track="${CSS.escape(next)}"] [data-test="check-row-undo"]`)
        : null) ?? root?.querySelector<HTMLElement>('[data-test="rekordbox-done"]'));
    });
  });
</script>

{#snippet undoGlyph()}
  <svg class="undo" viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5"
    stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 3L2 5.5 4.5 8" /><path d="M2.3 5.5h6.2a3.2 3.2 0 010 6.4H6" /></svg>
{/snippet}

{#snippet row(r: CheckRow)}
  {@const why = refused[r.track_id]}
  <ListRow wrap title={r.name} test="check-row" data-track={r.track_id} data-refused={why ? 'true' : undefined}>
    {#snippet lead()}<Cover url={r.cover_url} seed={r.track_id} size={28} />{/snippet}
    {#snippet name()}{r.name}{/snippet}
    {#snippet sub()}<span class="line one" title={r.sub}>{r.sub}</span>{#each r.notes as n (n)}<span class="line note">{n}</span>{/each}{#if why}<span
      class="line warn" data-test="check-row-refused">{why}</span>{/if}{/snippet}
    {#snippet trailing()}
      {#if r.can_undo && !why}
        {@const t = byId.get(r.track_id)}
        <!-- no spinner in a 26 px square: while it runs every action of the panel waits, the foot says it's busy -->
        <WriteButton variant="icon" size="sm" muted tip="Undo this one" aria-label="Undo {r.name}" disabled={!!flow.busy}
          onclick={() => t?.check && flow.undo([r.track_id], t.check)} data-test="check-row-undo">{@render undoGlyph()}</WriteButton>
      {/if}
    {/snippet}
  </ListRow>
{/snippet}

{#snippet head()}
  {#if card}
    <Surface kind="card" tone="warn" label="In rekordbox" summary={card.summary} data-test="rekordbox-check"
      data-reason="batch">
      <NumberedSteps tone="warn" test="rekordbox-steps">
        {#each card.steps as s, i (i)}
          <li><span class="step">{#each s.parts as p, j (j)}{#if p.strong}<b>{p.text}</b>{:else}{p.text}{/if}{/each}{#if s.note}{' '}<span
            class="note">{s.note}</span>{/if}{#if s.list}<span class="names" data-test="step-tracks">{#each s.list as n (n)}<span
            class="name" title={n}>{n}</span>{/each}</span>{/if}</span></li>
        {/each}
      </NumberedSteps>
    </Surface>
  {/if}
{/snippet}

{#snippet fill()}
  <!-- the row grid: cover · name over its lines · the undo slot, kept on every row so the names end at one x -->
  <Surface kind="list" label={batch ? 'Upgraded' : checksTitle(selected)} summary={batch ? String(tracks.length) : tracksSummary(tracks.length)}
    hint={batch && day ? (day === 'today' ? 'today' : `on ${day}`) : undefined}
    style="--row-cols: 28px minmax(0, 1fr) var(--h-ctl-sm)" grow={{ rows: rows.length, tall: true }}
    data-test={batch ? 'batch-tracks' : 'check-selection-rows'}>
    {#each rows as r (r.track_id)}{@render row(r)}{/each}
  </Surface>
{/snippet}

{#snippet foot()}<BatchCheckFoot {tracks} {flow} />{/snippet}

<div class="checks" bind:this={root} data-test="check-batch" data-mode={batch ? 'batch' : 'selection'}>
  <Panel head={card ? head : undefined} {fill} {foot} />
</div>

<style>
  .checks { display: contents; }
  .step { display: block; min-width: 0; font-size: var(--fs-small); line-height: 17px; color: var(--text); }
  .step b { font-weight: var(--fw-semi); }
  .note { color: var(--text-muted); }
  /* the tracks a step is for, one per line under its words, in the text's colour: names to find in rekordbox */
  .names { display: flex; flex-direction: column; margin-top: var(--s-1); min-width: 0; }
  .name { font-size: var(--fs-small); line-height: 17px; color: var(--text-muted); white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; }
  .line { display: block; }
  /* the file's name (or the row's to-do line) stays on one line and ends in "…": only the notes are sentences to wrap */
  .line.one { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .line.note { color: var(--text-label); }
  /* a refused undo's reason in the colour of a step left for the user, as the batch panel's skipped rows */
  .line.warn { color: var(--risk-notice); }
  .undo { width: 14px; height: 14px; flex-shrink: 0; }
</style>
