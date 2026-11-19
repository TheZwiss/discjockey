<script lang="ts">
  // Several songs of Missing files selected (issue 43, plan §7.4), the To-do panel while two or more of the group are
  // selected (or "Select all" picked the group). Modelled on UpgradeSelection, in two phases:
  // - decide: the selected songs as rows (fill: the one list of unknown length, scrolling in place), each with the
  //   engine's words for what its action does, or why it can't run now (dimmed: the press skips it), × to leave one out;
  //   the foot has one button per action the engine says can run for any of them (the flow reads `missing_files_preview`
  //   once per action over the selection: its `button` words and the songs whose `will` is true): "Download again · n"
  //   (the panel's one filled button) and "Remove from library · m…" (danger; it confirms first, with the engine's
  //   `confirm`). No song can run: no button, the engine's own line says so. One job per press.
  // - ended (until Done or the next pick): the job's own words as the head, and the songs it skipped with the engine's
  //   reason each (StatusMark warn, as UpgradeSelection's "not upgraded" rows); Done is the filled button. There is no
  //   batch, so no Resume and no Stop.
  // The flow (MissingFlow) is the page's, so its end survives the list fetching again as the songs leave the group.
  import type { TodoItem } from '$lib/bridge/types';
  import { Button, Cover, Hint, ListRow, NoteCard, StatusMark, Surface, WriteButton } from '$lib/components';
  import { untrack } from 'svelte';
  import { Panel } from '$lib/frames';
  import { writeBlockedReason } from '$lib/stores/hub';
  import { focusAfterDrop } from './decisionModel';
  import { refocus } from './focus';
  import type { MissingFlow } from './flows.svelte';
  import { currentPreviews, missingButtons, missingRowWords, missingSelectedTitle } from './missingModel';

  let { items, flow, nameOf, coverOf, ondrop, ondone }: {
    /** the selected songs, in list order */
    items: TodoItem[];
    /** the page's flow: its `busy` and `ended` are this panel's phase */
    flow: MissingFlow;
    /** "Artist – Title" of an item */
    nameOf: (i: TodoItem) => string;
    /** a skipped song's cover by track id, as the list shows it (null: the seeded one) */
    coverOf: (track_id: string) => string | null;
    /** × on a row: leave it out of the selection */
    ondrop: (i: TodoItem) => void;
    /** Done: the job's words are put away, the page selects the group's first song */
    ondone: () => void;
  } = $props();

  // while a job runs the rows stay as they were pressed: the list may fetch again under it as the songs leave the group
  let pressed = $state<TodoItem[] | null>(null);
  const rows = $derived(flow.busy && pressed ? pressed : items);
  // the engine is asked again when the selection changes (not while a job runs or its end shows: the songs leave the group)
  const asked = $derived(items.map((i) => i.track_id).join('\n'));
  // the answer counts only for the songs selected now: after the selection changed its buttons would act on others
  const current = $derived(currentPreviews(flow.previews, items.map((i) => i.track_id)));
  const buttons = $derived(missingButtons(current, items.flatMap((i) => (i.missing ? [i.missing.action] : []))));
  $effect(() => {
    const now = asked;
    untrack(() => { if (!flow.busy && !flow.ended && now) void flow.read(now.split('\n')); });
  });
  // a press waits for the answer about the selection as it is now
  const reading = $derived(!current || current.phase === 'loading');
  const ended = $derived(flow.ended);
  const blocked = $derived($writeBlockedReason);

  async function press(run: () => Promise<void>) {
    pressed = items;
    await run();
    pressed = null;
  }
  function download() { const b = buttons.download; if (b) void press(() => flow.downloadAgain(b.ids, { panel: true })); }
  function remove() { const b = buttons.remove; if (b) void press(() => flow.remove(b.ids, { panel: true, confirm: b.confirm })); }

  // Focus follows the foot: the pressed button is gone at the end, so Done takes it (only when focus was lost).
  let root = $state<HTMLElement>();
  let wasEnded = untrack(() => !!flow.ended);
  $effect(() => {
    const now = !!ended;
    untrack(() => {
      if (now && !wasEnded) void refocus(() => root?.querySelector<HTMLElement>('[data-test="missing-done"]'));
      wasEnded = now;
    });
  });
  /** × on a row: the selection gives it up, and the × of the row now in its place takes focus. */
  function drop(i: TodoItem) {
    const next = focusAfterDrop(items, items.indexOf(i))?.track_id;
    ondrop(i);
    if (next) void refocus(() => root?.querySelector<HTMLElement>(`[data-test="missing-row"][data-track="${CSS.escape(next)}"] [data-test="selection-drop"]`));
  }
</script>

{#snippet head()}
  {#if ended}
    <!-- the engine's one line for the job ("2 songs download again at your next sync; 1 is skipped.") -->
    <NoteCard title={ended.words} data-test="missing-end" data-action={ended.action} />
  {/if}
{/snippet}

{#snippet fill()}
  {#if ended}
    <Surface kind="list" label="Skipped" summary={String(ended.skipped.length)} style="--row-cols: 52px minmax(0, 1fr)"
      grow={{ rows: ended.skipped.length, tall: true }} data-test="missing-skipped">
      {#each ended.skipped as r (r.track_id)}
        <ListRow wrap wrapName title={r.name} test="missing-skipped-row" data-track={r.track_id}>
          {#snippet lead()}<span class="lead"><span class="mark" data-mark><StatusMark tone="warn" /></span><Cover
            url={coverOf(r.track_id)} seed={r.track_id} size={28} /></span>{/snippet}
          {#snippet name()}{r.name}{/snippet}
          {#snippet sub()}<span class="warn">{r.text}</span>{/snippet}
        </ListRow>
      {/each}
    </Surface>
  {:else}
    <Surface kind="list" label={missingSelectedTitle(rows.length)} style="--row-cols: 28px minmax(0, 1fr) var(--h-ctl-sm)"
      grow={{ rows: rows.length, tall: true }} data-test="missing-rows">
      {#each rows as i (i.track_id)}
        {@const w = missingRowWords(i)}
        <ListRow off={w.dim} wrap title={nameOf(i)} test="missing-row" data-track={i.track_id} data-runs={!w.dim}>
          {#snippet lead()}<Cover url={i.cover_url} seed={i.track_id} size={28} />{/snippet}
          {#snippet name()}{nameOf(i)}{/snippet}
          {#snippet sub()}{w.text}{/snippet}
          {#snippet trailing()}
            <Button variant="icon" size="xs" aria-label="Leave {nameOf(i)} out" tip="Leave out of the selection"
              disabled={!!flow.busy} onclick={() => drop(i)} data-test="selection-drop">
              <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 2l6 6M8 2l-6 6"
                stroke="currentColor" stroke-width="1.3" stroke-linecap="round" /></svg></Button>
          {/snippet}
        </ListRow>
      {/each}
    </Surface>
  {/if}
{/snippet}

{#snippet foot()}
  {#if ended}
    <Button variant="filled" wide onclick={ondone} data-test="missing-done">Done</Button>
  {:else}
    {#if buttons.download}
      <WriteButton variant="filled" wide busy={flow.busy === 'download_again'} disabled={flow.busy === 'remove' || reading}
        onclick={download} data-test="missing-download">{buttons.download.label}</WriteButton>
    {/if}
    {#if buttons.remove}
      <WriteButton variant="danger" wide busy={flow.busy === 'remove'} disabled={flow.busy === 'download_again' || reading}
        onclick={remove} data-test="missing-remove">{buttons.remove.label}</WriteButton>
    {/if}
    {#if blocked}
      <div class="centered"><Hint text={blocked} /></div>
    {:else if flow.previews?.phase === 'error' && !buttons.download && !buttons.remove}
      <div class="centered"><Hint text={flow.previews?.message ?? ''} wrap data-test="missing-none" /></div>
    {:else if buttons.none}
      <div class="centered"><Hint text={buttons.none} wrap data-test="missing-none" /></div>
    {/if}
  {/if}
{/snippet}

<div class="sel" bind:this={root} data-test="missing-selection" data-phase={ended ? 'ended' : flow.busy ? 'running' : 'decide'}>
  <Panel head={ended ? head : undefined} fill={!ended || ended.skipped.length ? fill : undefined} {foot} />
</div>

<style>
  .sel { display: contents; }
  /* mark · cover on a fixed grid, as UpgradeSelection's rows */
  .lead { display: grid; grid-template-columns: 16px 28px; column-gap: var(--s-2); align-items: center; }
  .mark { display: grid; place-items: center; width: 16px; height: 16px; }
  .centered :global(.hint) { text-align: center; }
  /* a reason's words in the colour of its mark, as the moves panel's (MovesPanel) */
  .warn { color: var(--risk-notice); }
</style>
