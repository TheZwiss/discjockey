<script lang="ts">
  // Several upgrades selected (plan issue 33 stage B §6.2), the To-do panel while two or more items of Upgrade ready
  // are selected (or "Upgrade all" selected the group). One Panel in three phases, the way the Playlists moves panel
  // reads (MovesPanel: the number and its bar on top, the rows below, Stop in the foot):
  // - decide: the selected tracks as rows (fill: the one list of unknown length, scrolling in place), each saying how
  //   it goes under the picked way and dimmed where it stays; "In rekordbox" as the single panel's ChoiceGroup, Same
  //   track · n (recommended) carrying Upgrade all's before-line in its outcomes, New track · N; the foot's one filled
  //   button "Replace n with lossless", Discard, and when a replace can be undone;
  // - running: how many of how many with the track in work and its bar, the rows marked as they pass, Stop;
  // - ended (until the next pick): the number done in its words, a note when it ended early (stopped, rekordbox open,
  //   busy, refused) and the tracks not done with their reasons; Done, or Resume · k left / Try again.
  // The batch itself is the window's UpgradeBatchFlow, so its progress survives a pick of another row.
  import type { TodoItem } from '$lib/bridge/types';
  import {
    Button, ChoiceGroup, Cover, Hint, ListRow, ListSection, NoteCard, OutcomeList, ProgressBar, Spinner, StatCard, StatusMark, Surface,
    WriteButton, type ChoiceOption, type Outcome,
  } from '$lib/components';
  import { Panel } from '$lib/frames';
  import { writeBlockedReason } from '$lib/stores/hub';
  import {
    endGroups, endNote, endWords, goes, leftTitle, notDoneTitle, replaceManyLabel, discardLabel, resumeLabel, sameTrackWhy, selectedTitle,
    selectionWays, type RunRow, type Way,
  } from './decisionModel';
  import { upgradeBatch, type UpgradeBatchFlow } from './flows.svelte';

  let { items, all, nameOf, ondrop, ondone, onact, flow = upgradeBatch }: {
    /** the selected items, in list order */
    items: TodoItem[];
    /** the selection is the whole group: Same track runs as Upgrade all */
    all: boolean;
    /** "Artist – Title" of an item */
    nameOf: (i: TodoItem) => string;
    /** ✕ on a row: leave it out of the selection */
    ondrop: (i: TodoItem) => void;
    /** Done: the end is put away, the page selects the group's first item */
    ondone: () => void;
    /** a batch starts from this panel (Replace, Discard, Resume, Try again): the page keeps the panel until the next pick */
    onact?: () => void;
    flow?: UpgradeBatchFlow;
  } = $props();

  const KEPT_FILES: Outcome = { tone: 'file', text: 'Your old files are kept in Superseded/' };
  let picked = $state<Way | null>(null);
  const ways = $derived(selectionWays(items));
  const way = $derived<Way>(ways.choice ? picked ?? 'swap' : ways.way);
  const count = $derived(ways.count[way]);
  const options = $derived(ways.options.map((o): ChoiceOption<Way> => ({ key: o.key, name: o.name, summary: o.summary,
    outcomes: o.outcomes, recommended: o.key === 'swap', test: `way-${o.key}` })));
  const view = $derived(flow.view);
  const blocked = $derived($writeBlockedReason);

  const RUN_TITLE = { swap: 'Upgrading', add_new: 'Adding as new tracks', discard: 'Discarding' };
  const ended = $derived(view?.phase === 'ended' ? endGroups(view.rows) : { notDone: [], left: [] });
  const endCount = $derived(ended.notDone.length + ended.left.length);
  const words = $derived(view?.end ? endWords(view.end) : null);
  const note = $derived(view?.end ? endNote(view.end) : null);

  function replace() { onact?.(); void flow.start(way, items.filter((i) => goes(i, way)), all && way === 'swap', nameOf); }
  function discard() { onact?.(); void flow.start('discard', items, false, nameOf); }
  function resume(batch_id: number) { onact?.(); void flow.resume(batch_id); }
  function done() { flow.clear(); ondone(); }
</script>

{#snippet mark(r: RunRow)}
  <span class="mark" data-mark>
    {#if r.state === 'now'}<Spinner size={12} label="Working on it" />
    {:else if r.state === 'handled'}<StatusMark tone="good" quiet />
    {:else if r.state === 'done'}<StatusMark tone="good" />
    {:else if r.state === 'skipped'}<StatusMark tone="warn" />
    {:else if r.state === 'failed'}<StatusMark tone="problem" />
    {:else if r.state === 'waiting' && view?.phase === 'ended'}<StatusMark tone="none" />{/if}
  </span>
{/snippet}

{#snippet runRows(rows: RunRow[])}
  {#each rows as r (r.track_id)}
    <ListRow wrap title={r.name} test="run-row" data-track={r.track_id} data-state={r.state}>
      {#snippet lead()}<span class="lead">{@render mark(r)}<Cover url={r.cover_url} seed={r.track_id} size={28} /></span>{/snippet}
      {#snippet name()}{r.name}{/snippet}
      {#snippet sub()}{#if r.text}<span class={r.state === 'failed' ? 'bad' : 'warn'}>{r.text}</span>{:else}{r.sub}{/if}{/snippet}
    </ListRow>
  {/each}
{/snippet}
{#snippet runList(rows: RunRow[], label: string, test: string, more?: { label: string; rows: RunRow[] })}
  <Surface kind="list" {label} summary={String(rows.length)} style="--row-cols: 52px minmax(0, 1fr)"
    grow={{ rows: rows.length + (more ? more.rows.length + 1 : 0), tall: true }} data-test={test}>
    {@render runRows(rows)}
    {#if more}
      <ListSection label={more.label} summary={String(more.rows.length)} test="batch-left" />
      {@render runRows(more.rows)}
    {/if}
  </Surface>
{/snippet}

{#snippet head()}
  {#if view?.phase === 'running'}
    <StatCard value={view.done} unit="of {view.total || view.rows.length}" label={view.now ?? 'Starting'}
      valueTest="batch-done" data-test="batch-progress">
      <ProgressBar value={view.total ? view.done / view.total : 0} label={RUN_TITLE[view.mode]} />
    </StatCard>
  {:else if view?.phase === 'ended' && view.end && words}
    <!-- the number only when something was done or the batch finished: "0 upgraded" over a note that says why adds nothing -->
    {#if view.done || view.end.kind === 'done'}
      <StatCard value={view.done} unit={words.unit} label={words.label} valueTest="batch-result" data-test="batch-result" />
    {/if}
    {#if note}<NoteCard tone={note.tone} data-test="batch-note" data-kind={view.end.kind}>{note.text}</NoteCard>{/if}
  {/if}
{/snippet}

{#snippet fill()}
  {#if view?.phase === 'running'}
    {@render runList(view.rows, RUN_TITLE[view.mode], 'batch-rows')}
  {:else if view?.phase === 'ended'}
    {#if ended.notDone.length}
      {@render runList(ended.notDone, notDoneTitle(ended.notDone.length, view.mode), 'batch-not-done',
        ended.left.length ? { label: leftTitle(ended.left.length), rows: ended.left } : undefined)}
    {:else if ended.left.length}
      {@render runList(ended.left, leftTitle(ended.left.length), 'batch-not-done')}
    {/if}
  {:else}
    <Surface kind="list" label={selectedTitle(items.length)} style="--row-cols: 28px minmax(0, 1fr) var(--h-ctl-sm)"
      grow={{ rows: items.length, tall: true }} data-test="selection-rows">
      {#each items as i (i.track_id)}
        {@const going = goes(i, way)}
        <ListRow off={!going} title={nameOf(i)} test="selection-row" data-track={i.track_id} data-goes={going}>
          {#snippet lead()}<Cover url={i.cover_url} seed={i.track_id} size={28} />{/snippet}
          {#snippet name()}{nameOf(i)}{/snippet}
          {#snippet sub()}{going ? (way === 'swap' ? 'Same track' : 'New track') : sameTrackWhy(i.same_track)}{/snippet}
          {#snippet trailing()}
            <Button variant="icon" size="sm" muted aria-label="Leave {nameOf(i)} out" tip="Leave out of the selection"
              onclick={() => ondrop(i)} data-test="selection-drop">
              <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 2l6 6M8 2l-6 6"
                stroke="currentColor" stroke-width="1.3" stroke-linecap="round" /></svg></Button>
          {/snippet}
        </ListRow>
      {/each}
    </Surface>
  {/if}
{/snippet}

{#snippet keptFiles()}<OutcomeList items={[KEPT_FILES]} />{/snippet}

{#snippet after()}
  {#if !view}
    {#if ways.choice}
      <ChoiceGroup label="In rekordbox" {options} value={way} onchange={(w) => (picked = w)} foot={keptFiles}
        test="selection-ways" />
    {:else}
      <Surface kind="card" label="In rekordbox" summary="new tracks" data-test="selection-ways" data-choice="false">
        <div class="fixed">
          <OutcomeList items={[...ways.fixed, KEPT_FILES]} />
          {#if ways.reason}<Hint text={ways.reason} wrap class="reason" data-test="selection-why" />{/if}
        </div>
      </Surface>
    {/if}
  {/if}
{/snippet}

{#snippet foot()}
  {#if view?.phase === 'running'}
    <Button wide busy={view.stopping} busyLabel="Stopping" onclick={() => flow.stop()} data-test="batch-stop">Stop</Button>
  {:else if view?.phase === 'ended' && view.end}
    {@const end = view.end}
    {#if end.resume || view.again}
      <div class="row">
        <Button onclick={done} data-test="batch-done-plain">Done</Button>
        {#if end.resume}
          {@const r = end.resume}
          <WriteButton variant="filled" wide onclick={() => resume(r.batch_id)} data-test="batch-resume">{resumeLabel(r.left)}</WriteButton>
        {:else}
          <WriteButton variant="filled" wide onclick={() => { onact?.(); view?.again?.(); }} data-test="batch-again">Try again</WriteButton>
        {/if}
      </div>
    {:else}
      <Button variant="filled" wide onclick={done} data-test="batch-close">Done</Button>
    {/if}
  {:else}
    <WriteButton variant="filled" wide disabled={!count} title={count ? undefined : 'None of these can be replaced this way'}
      onclick={replace} data-test="selection-replace" data-mode={way}>{replaceManyLabel(count, items.filter((i) => goes(i, way)))}</WriteButton>
    <WriteButton wide onclick={discard} title="Deletes the new versions; they aren't offered again"
      data-test="selection-discard">{discardLabel(items.length)}</WriteButton>
    <div class="centered"><Hint text={blocked ?? 'You can undo a replace until you press Done'} /></div>
  {/if}
{/snippet}

<div class="sel" data-test="upgrade-selection" data-phase={view?.phase ?? 'decide'} data-end={view?.end?.kind}>
  <Panel head={view ? head : undefined} fill={view?.phase !== 'ended' || endCount ? fill : undefined} {after} {foot} />
</div>

<style>
  .sel { display: contents; }
  /* mark · cover on a fixed grid, so the covers stay in one column whatever the mark (none, ✓, spinner) */
  .lead { display: grid; grid-template-columns: 16px 28px; column-gap: var(--s-2); align-items: center; }
  .mark { display: grid; place-items: center; width: 16px; height: 16px; }
  .fixed { display: flex; flex-direction: column; gap: var(--s-2); }
  .fixed :global(.reason) { color: var(--text-label); }
  .row { display: flex; gap: var(--s-2); }
  .centered :global(.hint) { text-align: center; }
  /* a reason's words in the colours of its mark, as the moves panel's (MovesPanel) */
  .warn { color: var(--risk-notice); }
  .bad { color: var(--q-weak); }
</style>
