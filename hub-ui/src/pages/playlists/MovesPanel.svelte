<script module lang="ts">
  import type { JobOutcome } from '$lib/bridge/client';
  import type { BatchResult } from '$lib/bridge/types';
  import type { MoveItem } from './tidyModel';

  /** What opened the panel: Tidy up files, an Undo of the move log, or a save that moves files (the page runs the
   *  save itself and hands its outcome over). */
  export type MovesEntry =
    | { kind: 'tidy' }
    | { kind: 'undo'; batch_id: number }
    | { kind: 'save'; items: MoveItem[];
      outcome: Promise<JobOutcome<{ version: string; batches: BatchResult[] }>> };
</script>

<script lang="ts">
  // The Playlists panel while files move (plan library stage 2, 6.3/6.4; approved mockup): the Tidy up files preview
  // (one list in three groups, the warning card above Cancel · Move N files), the undo confirmation (the rows going
  // back marked ↩, "Can't move back" with reasons, U_WARN/U_RENAME, Cancel · Move N files back), the progress
  // (MovesProgress drives the number and the bar, done rows get a ✓; Stop) and the result (the number moved, the
  // "not moved" list with reasons; Undo · Done). The list scrolls inside the panel; the warning and the foot stay.
  import { untrack } from 'svelte';
  import {
    Button, Cover, EmptyState, ListRow, ListSection, NoteCard, ProblemCard, ProgressBar, Skeleton, StatCard,
    StatusMark, Surface, Tick, WriteButton,
  } from '$lib/components';
  import { Panel } from '$lib/frames';
  import { api, runJob } from '$lib/bridge/client';
  import { onEvent } from '$lib/bridge/events';
  import type { ProblemKind, TidyPreview, UndoPreview } from '$lib/bridge/types';
  import { problemCopy } from '$lib/copy';
  import { toasts } from '$lib/stores/toasts';
  import TidyList from './TidyList.svelte';
  import {
    CANT_MOVE_BACK, NOTHING_LEFT, R1, R2, U1, confirmLabel, countLine, folderName, goBackText, groups,
    initialTicks, itemOfRow, movesOf, notMovedText, outcomeOf, pairsOf, progressDone, progressStart, progressStep,
    progressTotal, resultUndo, skipTone, tickable, tickedRows, tickedText, toggleGroup, toggleTick, undoItems,
    undoLabel, type Outcome,
  } from './tidyModel';

  let { entry, onclose, onlist, onbusy }: {
    entry: MovesEntry;
    onclose: () => void;              // Cancel, Done
    onlist: () => void;               // a result of several batches: Undo opens the Recent moves list
    onbusy: (busy: boolean) => void;  // while files move (the page keeps this panel open)
  } = $props();

  const TIDY_TITLE = 'Tidy up files';
  const SAVE_TITLE = 'Saved playlists';

  type Step =
    | { s: 'loading' }
    | { s: 'failed'; kind: ProblemKind; message: string; retry: () => void }
    | { s: 'tidy'; preview: TidyPreview; ticks: Set<number> }
    | { s: 'undo'; preview: UndoPreview }
    | { s: 'moving'; title: string; items: MoveItem[]; back: boolean }
    | { s: 'result'; outcome: Outcome };
  let step = $state<Step>({ s: 'loading' });
  let progress = $state(progressStart(0));
  let stopping = $state(false);

  // ---------- reads ----------
  async function loadTidy() {
    step = { s: 'loading' };
    const r = await api.tidy_preview();
    if (!r.ok) { step = { s: 'failed', kind: r.kind, message: r.message, retry: loadTidy }; return; }
    const { ok: _ok, ...preview } = r;
    step = { s: 'tidy', preview, ticks: initialTicks(preview.rows) };
  }
  async function loadUndo(batch_id: number) {
    step = { s: 'loading' };
    const r = await api.undo_preview(batch_id);
    if (!r.ok) { step = { s: 'failed', kind: r.kind, message: r.message, retry: () => loadUndo(batch_id) }; return; }
    const { ok: _ok, ...preview } = r;
    step = { s: 'undo', preview };
  }

  // ---------- moving ----------
  $effect(() => onEvent((e) => {
    if (e.type === 'MovesProgress' && step.s === 'moving') progress = progressStep(progress, e);
  }));

  function startMoving(title: string, items: MoveItem[], back: boolean) {
    progress = progressStart(items.length);
    stopping = false;
    step = { s: 'moving', title, items, back };
    onbusy(true);
  }
  function problem(kind: ProblemKind, message: string) {
    toasts.show({ tone: 'problem', title: problemCopy(kind).title, body: message || undefined });
  }

  async function moveTicked(preview: TidyPreview, ticks: Set<number>) {
    const rows = tickedRows(preview.rows, ticks);
    startMoving(TIDY_TITLE, rows.map(itemOfRow), false);
    const out = await runJob<BatchResult>(api.tidy_up(movesOf(preview.rows, ticks)), { quiet: true, success: false });
    onbusy(false);
    if (out.ok) step = { s: 'result', outcome: outcomeOf([out.result]) };
    else if (out.result) step = { s: 'result', outcome: outcomeOf([out.result]) };
    else { problem(out.kind, out.message); await loadTidy(); }
  }
  async function moveBack(preview: UndoPreview) {
    startMoving(preview.title, undoItems(preview), true);
    const out = await runJob<BatchResult>(api.undo_moves(preview.batch_id), { quiet: true, success: false });
    onbusy(false);
    if (out.ok) step = { s: 'result', outcome: outcomeOf([out.result], true) };
    else if (out.result) step = { s: 'result', outcome: outcomeOf([out.result], true) };
    else { problem(out.kind, out.message); await loadUndo(preview.batch_id); }
  }
  async function followSave(e: Extract<MovesEntry, { kind: 'save' }>) {
    startMoving(SAVE_TITLE, e.items, false);
    const out = await e.outcome;
    onbusy(false);
    const batches = out.ok ? out.result.batches : out.result?.batches ?? [];
    // a save that failed before it moved anything is the page's to say (changed elsewhere, refused, …)
    if (out.ok || batches.length) step = { s: 'result', outcome: outcomeOf(batches) };
    else onclose();
  }
  async function stop() {
    stopping = true;
    const r = await api.stop();
    if (!r.ok) { stopping = false; problem(r.kind, r.message); }
  }

  function undoResult(o: Outcome) {
    const u = resultUndo(o);
    if (u === 'list') onlist();
    else if (u) void loadUndo(u.batch);
  }

  $effect(() => {
    const e = entry;
    untrack(() => {
      if (e.kind === 'tidy') void loadTidy();
      else if (e.kind === 'undo') void loadUndo(e.batch_id);
      else void followSave(e);
    });
  });
  $effect(() => () => onbusy(false));

  // ---------- what each step shows ----------
  const tidy = $derived(step.s === 'tidy' ? step : null);
  const tidyTicked = $derived(tidy ? tickedRows(tidy.preview.rows, tidy.ticks) : []);
  const tidyCount = $derived(countLine(pairsOf(tidyTicked)));
  const undo = $derived(step.s === 'undo' ? step.preview : null);
  const undoGoing = $derived(undo ? undo.rows.filter((r) => !r.skip) : []);
  const undoSkipped = $derived(undo ? undo.rows.filter((r) => r.skip) : []);
  const moving = $derived(step.s === 'moving' ? step : null);
  const done = $derived(progressDone(progress));
  const total = $derived(progressTotal(progress));
  const result = $derived(step.s === 'result' ? step.outcome : null);
  const hasFill = $derived(!!tidy?.preview.rows.length || !!undo?.rows.length || !!moving
    || !!result?.skipped.length);
</script>

<!-- a folder may break after a "/" (Powertrance_2026/ not_lossless), never inside a name; the arrow is spaced -->
{#snippet place(f: string)}
  {#each folderName(f).split('/') as part, i (i)}{#if i}/<wbr />{/if}{part}{/each}
{/snippet}
{#snippet route(from: string, to: string)}
  {@render place(from)} <span class="arrow" aria-label="to">→</span> {@render place(to)}
{/snippet}

{#snippet head()}
  {#if step.s === 'loading'}
    <div data-test="moves-loading"><Skeleton lines={4} height={52} gap={2} /></div>
  {:else if step.s === 'failed'}
    <ProblemCard kind={step.kind} message={step.message} onretry={step.retry} />
  {:else if tidy}
    {#if !tidy.preview.rows.length}
      <Surface kind="card" data-test="tidy-empty">
        <EmptyState title={tidy.preview.empty ?? 'Every file is where the playlist order puts it.'} action={null} />
      </Surface>
    {:else if tidy.preview.empty}
      <NoteCard data-test="tidy-only-yours">{tidy.preview.empty}</NoteCard>
    {/if}
  {:else if undo?.nothing_left}
    <NoteCard data-test="undo-nothing-left">{NOTHING_LEFT}</NoteCard>
  {:else if moving}
    {@const folder = moving.items.some((i) => i.folder)}
    <StatCard value={done} unit="of {total}" label={folder ? 'moved' : moving.back ? 'files moved back' : 'files moved'}
      valueTest="moves-done" data-test="moves-progress">
      <ProgressBar value={total ? done / total : 0} label="Files moved" />
    </StatCard>
  {:else if result}
    <StatCard value={result.moved} unit={result.moved === 1 ? 'file' : 'files'}
      label={result.back ? 'moved back' : 'moved'} valueTest="moves-moved" data-test="moves-result" />
  {/if}
{/snippet}

{#snippet fill()}
  {#if tidy}
    {@const g = groups(tidy.preview.rows)}
    <TidyList label={TIDY_TITLE} summary={tickedText(tidyTicked.length, tickable(tidy.preview.rows).length)}
      rows={tidy.preview.rows} ticks={tidy.ticks} yoursHeader={tidy.preview.yours?.header}
      yoursControl={tidy.preview.yours?.control} ontick={(r) => { tidy.ticks = toggleTick(tidy.ticks, r); }}
      ongroup={() => { tidy.ticks = toggleGroup(tidy.ticks, g.yours); }} />
  {:else if undo}
    <Surface kind="list" label={undo.title} summary={goBackText(undoGoing.length, undo.rows.length)}
      style="--row-cols: 16px minmax(0, 1fr)" grow={{ rows: undo.rows.length + (undoSkipped.length ? 1 : 0), tall: true }}
      data-test="undo-list">
      {#each undoGoing as r, i (i)}
        <ListRow wrap title={r.label} test="undo-row">
          {#snippet lead()}<StatusMark tone="back" />{/snippet}
          {#snippet name()}{r.label}{/snippet}
          {#snippet sub()}{@render route(r.from, r.to)}{/snippet}
        </ListRow>
      {/each}
      {#if undoSkipped.length}
        <ListSection label={CANT_MOVE_BACK} summary={String(undoSkipped.length)} test="undo-skipped" />
        {#each undoSkipped as r, i (i)}
          <ListRow wrap title={r.label} test="undo-skip">
            {#snippet lead()}<StatusMark tone="warn" />{/snippet}
            {#snippet name()}{r.label}{/snippet}
            {#snippet sub()}<span class="warn">{r.skip?.text}</span>{/snippet}
          </ListRow>
        {/each}
      {/if}
    </Surface>
  {:else if moving}
    <Surface kind="list" label={moving.title} summary="{moving.items.length} moving"
      style="--row-cols: 52px minmax(0, 1fr)" grow={{ rows: moving.items.length, tall: true }} data-test="moves-list">
      {#each moving.items as it, i (it.key)}
        {@const isDone = i < done}
        <ListRow wrap title={it.label} data-done={isDone || undefined} test="moving-row">
          {#snippet lead()}
            {#if it.skip}<StatusMark tone="warn" />
            {:else if isDone}<StatusMark tone="good" quiet />
            {:else if moving.back}<StatusMark tone="back" />
            {:else}<Tick on />{/if}
            {#if it.folder}<span class="folder" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3">
                <path d="M2 4.5a1 1 0 0 1 1-1h3.2l1.3 1.5H13a1 1 0 0 1 1 1V12a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1z" /></svg></span>
            {:else}<Cover url={it.cover_url} seed={it.track_id ?? it.key} size={28} />{/if}
          {/snippet}
          {#snippet name()}{it.folder ? `${it.label}, the whole folder` : it.label}{/snippet}
          {#snippet sub()}{#if it.skip}<span class="warn">{it.skip}</span>{:else}{@render route(it.from, it.to)}{/if}{/snippet}
        </ListRow>
      {/each}
    </Surface>
  {:else if result && result.skipped.length}
    <Surface kind="list" label={notMovedText(result.skipped.length)} style="--row-cols: 16px minmax(0, 1fr)"
      grow={{ rows: result.skipped.length, tall: true }} data-test="moves-skipped">
      {#each result.skipped as s, i (i)}
        <ListRow wrap title={s.label} test="skipped-row">
          {#snippet lead()}<StatusMark tone={skipTone(s.reason)} />{/snippet}
          {#snippet name()}{s.label}{/snippet}
          {#snippet sub()}<span class={skipTone(s.reason) === 'problem' ? 'bad' : 'warn'}>{s.text}</span>{/snippet}
        </ListRow>
      {/each}
    </Surface>
  {/if}
{/snippet}

{#snippet after()}
  {#if tidy && tidyCount}
    <NoteCard tone="warn" title={tidyCount} data-test="tidy-warning">
      {[...tidy.preview.rekordbox, tidy.preview.undo_note].join(' ')}</NoteCard>
  {:else if undo && undo.warning.length}
    <NoteCard tone="warn" data-test="undo-warning">
      {#each undo.warning as w (w)}<p class="line">{w}</p>{/each}</NoteCard>
  {/if}
{/snippet}

{#snippet foot()}
  <div class="foot">
    {#if tidy && !tidy.preview.rows.length}
      <Button wide onclick={onclose} data-test="moves-cancel">Cancel</Button>
    {:else if tidy}
      <Button onclick={onclose} data-test="moves-cancel">Cancel</Button>
      <WriteButton wide variant="filled" disabled={!tidyTicked.length}
        title={tidyTicked.length ? undefined : 'Tick the files to move first.'}
        onclick={() => tidy && moveTicked(tidy.preview, tidy.ticks)} data-test="tidy-move">{confirmLabel(tidyTicked.length)}</WriteButton>
    {:else if undo}
      <Button onclick={onclose} data-test="moves-cancel">Cancel</Button>
      <WriteButton wide variant="filled" disabled={!undo.moving} title={undo.moving ? undefined : NOTHING_LEFT}
        onclick={() => undo && moveBack(undo)} data-test="undo-move">{undoLabel(undo.moving)}</WriteButton>
    {:else if moving}
      <Button wide busy={stopping} busyLabel="Stopping" onclick={stop} data-test="moves-stop">Stop</Button>
    {:else if result}
      <Button disabled={!resultUndo(result)} title={resultUndo(result) ? undefined : NOTHING_LEFT}
        onclick={() => result && undoResult(result)} data-test="result-undo">Undo</Button>
      <Button wide variant="filled" onclick={onclose} data-test="moves-done">Done</Button>
    {:else}
      <Button wide onclick={onclose} data-test="moves-cancel">Cancel</Button>
    {/if}
  </div>
{/snippet}

<div class="moves" data-test="moves-panel" data-step={step.s}>
  <Panel {head} fill={hasFill ? fill : undefined} {after} {foot} />
</div>

<style>
  .moves { display: contents; }
  .foot { display: flex; gap: var(--s-2); }
  .arrow { color: var(--text-label); }
  .warn { color: var(--risk-notice); }
  .bad { color: var(--q-weak); }
  .line { margin: 0; }
  .line + .line { margin-top: var(--s-1); }
  .folder { width: 28px; height: 28px; flex: none; display: grid; place-items: center; border-radius: var(--r-icon);
    border: var(--bw) solid var(--ctl-line); color: var(--text-muted); }
</style>
