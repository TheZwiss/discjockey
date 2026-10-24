<script lang="ts">
  // Playlists (spec §5.5, design system mockup design-system/playlists.html): the rows of playlists.txt (top =
  // highest priority), edited as a draft and saved with save_playlists(lines, loaded_version). ListPanelFrame: the
  // header (Spotify slot: the only Read Spotify), the paste field, then one Surface list anchored to the window that
  // scrolls in place. The panel (ChangePanel) says what the unsaved change does; its foot is Undo · Save, the screen's
  // one filled button, or the save question's two saves when the change puts files in another folder. "Tidy up files"
  // (header, beside Read Spotify; orange with the count while files are out of place) and an Undo of a recent move
  // open MovesPanel in the panel's place: preview, progress, result. A save that moves files shows its progress there
  // too.
  import { untrack } from 'svelte';
  import {
    AddRow, Button, EmptyState, Hint, InfoTip, NoteCard, PageHeader, ProblemCard, Skeleton, Surface, confirm,
  } from '$lib/components';
  import { ListPanelFrame } from '$lib/frames';
  import { api, runJob } from '$lib/bridge/client';
  import type { AddedPlaylist, BatchResult, Playlists, ProblemKind, SaveFiles } from '$lib/bridge/types';
  import { dataVersion } from '$lib/stores/hub';
  import { toasts } from '$lib/stores/toasts';
  import { problemCopy, detailLine } from '$lib/copy';
  import { setLeaveGuard } from '$lib/router';
  import { markReady } from '$lib/ready';
  import Row from './Row.svelte';
  import ChangePanel from './ChangePanel.svelte';
  import MovesPanel, { type MovesEntry } from './MovesPanel.svelte';
  import { problemToTell, type MoveItem } from './tidyModel';
  import {
    addRow, draftFrom, dropIndex, folderChanges, isDirty, lines, loadedFrom, moveBy, onOffText, priorities, remove,
    rename, reorder, shiftFor, statusLine, toggle, undo, type DraftRow, type Loaded, type Panel, type PanelTab,
  } from './changeModel';

  let { params: _params, query: _query }: { params: Record<string, string>; query: URLSearchParams } = $props();

  let pl = $state<Playlists | null>(null);
  let loaded = $state<Loaded | null>(null);
  let draft = $state<DraftRow[]>([]);
  let loadError = $state<{ kind: ProblemKind; message: string } | null>(null);
  let changedElsewhere = $state<string | null>(null);
  let saving = $state(false);
  let panel = $state<Panel | null>(null);
  let retry = $state(0);
  let ready = false;
  let tab = $state<PanelTab>('overlaps');
  let flow = $state<MovesEntry | null>(null);   // MovesPanel in the panel's place
  let flowTurn = $state(0);                     // a new flow mounts a fresh MovesPanel
  let movesBusy = $state(false);                // files are moving: the panel stays, Tidy up files waits

  const dirty = $derived(isDirty(draft, loaded));
  const prios = $derived(priorities(draft));
  const draftLines = $derived(lines(draft));
  const waiting = $derived(pl?.tidy?.waiting ?? 0);
  // what the unsaved change does to each folder, said under its playlist ("gets 27 more")
  const changes = $derived(dirty ? folderChanges(panel?.preview ?? null) : new Map<string, number>());

  // ---------- loading ----------
  let turn = 0;
  let resetWanted = false;   // survives a newer background fetch (JobFinished bumps $dataVersion during a save)
  async function load(reset = false): Promise<void> {
    if (reset) resetWanted = true;
    const t = ++turn;
    const r = await api.playlists();
    if (t !== turn) return;
    if (!ready) { ready = true; markReady('playlists'); }
    if (!r.ok) {
      if (!loaded || resetWanted) loadError = { kind: r.kind, message: r.message };
      return;
    }
    loadError = null;
    // a re-fetch in the background never throws away unsaved changes (nor the version they are based on)
    if (!resetWanted && loaded && isDirty(draft, loaded)) return;
    resetWanted = false;
    pl = r;
    loaded = loadedFrom(r);
    draft = draftFrom(loaded);
    changedElsewhere = null;
  }
  $effect(() => {
    void $dataVersion;
    void retry;
    untrack(() => { void load(); });
  });

  // ---------- leave guard ----------
  $effect(() => {
    setLeaveGuard(() => !isDirty(draft, loaded) || confirm({ title: 'You have unsaved changes. Leave without saving?',
      confirmLabel: 'Leave', tone: 'danger' }));
    return () => setLeaveGuard(null);
  });

  // ---------- the moves panel ----------
  function openFlow(e: MovesEntry) { flow = e; flowTurn++; }
  function closeFlow() { flow = null; }
  // an edit to the list brings the change panel back (a flow that isn't moving files is dropped)
  $effect(() => { if (dirty && flow && !movesBusy) untrack(closeFlow); });

  // ---------- saving ----------
  /** `files`: the save question's answer (null: the change moves no files); `items`: what moves, for the progress. */
  async function save(files: SaveFiles | null, items: MoveItem[]) {
    if (!loaded || !dirty) return;
    saving = true;
    const job = runJob<{ version: string; batches: BatchResult[] }>(
      api.save_playlists(lines(draft), loaded.version, files), { quiet: true });
    if (files?.choice === 'move') { movesBusy = true; openFlow({ kind: 'save', items, outcome: job }); }
    const out = await job;
    saving = false;
    if (!out.ok && out.kind === 'changed') { changedElsewhere = out.message; return; }
    // the job ran quiet (the moves panel follows it): a failure is told here, also one that still moved something
    const bad = problemToTell(out);
    if (bad) toasts.show({ tone: 'problem', title: problemCopy(bad.kind).title, body: bad.message || undefined });
    // saved even when it ended early (a Stop after the file was written): the panel shows what moved
    if (out.ok || out.result) await load(true);
  }
  async function reload() {
    if (dirty && !(await confirm({ title: 'Throw away your changes and load the file again?',
      confirmLabel: 'Throw away', tone: 'danger' }))) return;
    await load(true);
  }

  // ---------- editing ----------
  async function removeRow(r: DraftRow) {
    if (!r.isNew && !(await confirm({ title: 'Remove this playlist from Discjockey?',
      body: `Its files stay in Library/${r.folder}.`, confirmLabel: 'Remove', tone: 'danger' }))) return;
    draft = remove(draft, r.key);
  }
  function added(a: AddedPlaylist, folder: string): boolean { draft = addRow(draft, a, folder); return true; }
  async function move(key: string, delta: number) {
    draft = moveBy(draft, key, delta);
    await Promise.resolve();
    listEl()?.querySelector<HTMLElement>(`[data-key="${CSS.escape(key)}"]`)?.focus();
  }

  // ---------- pointer reorder (no HTML5 drag-and-drop: the window's file-drop handler covers the whole document) ----
  type Drag = { from: number; startY: number; dy: number; mids: number[]; pitch: number; to: number };
  let drag = $state<Drag | null>(null);
  const listEl = () => document.querySelector<HTMLElement>('[data-test="list"]');

  function startDrag(e: PointerEvent, i: number) {
    const el = listEl();
    if (e.button !== 0 || !el) return;
    e.preventDefault();
    const rects = [...el.querySelectorAll<HTMLElement>('[data-key]')].map((el) => el.getBoundingClientRect());
    if (!rects[i]) return;
    const mids = rects.map((r) => r.top + r.height / 2);
    const pitch = rects.length > 1 ? Math.abs(rects[1].top - rects[0].top) : rects[i].height;
    drag = { from: i, startY: e.clientY, dy: 0, mids, pitch, to: i };
    window.addEventListener('pointermove', dragMove);
    window.addEventListener('pointerup', dragEnd);
    window.addEventListener('pointercancel', dragCancel);
  }
  function dragMove(e: PointerEvent) {
    if (!drag) return;
    drag.dy = e.clientY - drag.startY;
    drag.to = dropIndex(drag.mids, drag.from, drag.mids[drag.from] + drag.dy);
  }
  function stopListening() {
    window.removeEventListener('pointermove', dragMove);
    window.removeEventListener('pointerup', dragEnd);
    window.removeEventListener('pointercancel', dragCancel);
  }
  function dragEnd(e: PointerEvent) {
    if (drag) { dragMove(e); draft = reorder(draft, drag.from, drag.to); }
    drag = null;
    stopListening();
  }
  function dragCancel() { drag = null; stopListening(); }
  $effect(() => () => stopListening());
  function offsetOf(i: number): number {
    if (!drag) return 0;
    return i === drag.from ? drag.dy : shiftFor(i, drag.from, drag.to) * drag.pitch;
  }
</script>

{#snippet main()}
  <PageHeader title="Playlists" sub={loaded ? statusLine(draft) : undefined} {actions} spotify />
  <AddRow {draft} onadd={added} />

  {#if pl?.problem}
    <NoteCard tone="problem" data-test="file-problem">playlists.txt needs fixing: {pl.problem}</NoteCard>
  {/if}
  {#if changedElsewhere}
    <Surface kind="card" tone="problem" label="playlists.txt was changed elsewhere." data-test="changed-elsewhere">
      {#snippet header()}<Button size="sm" onclick={reload} data-test="reload">Reload</Button>{/snippet}
      <Hint text={detailLine(changedElsewhere, 'Load it again before saving.')} />
    </Surface>
  {/if}

  {#if loadError && !loaded}
    <ProblemCard kind={loadError.kind} message={loadError.message} onretry={() => retry++} />
  {:else if !loaded}
    <div data-test="playlists-loading"><Skeleton lines={5} height={52} gap={2} /></div>
  {:else if !draft.length}
    <Surface kind="card" data-test="playlists-empty">
      <EmptyState title="No playlists yet." body="Paste a Spotify playlist link above." action={null} />
    </Surface>
  {:else}
    <Surface kind="list" label="Your playlists" summary={onOffText(draft)} grow={{ rows: draft.length, tall: true }}
      style="--row-cols: 76px minmax(0, 1fr) auto; --row-cols-wide: 76px minmax(0, 1fr) 132px auto"
      class={drag ? 'dragging' : ''} role="listbox" aria-label="Playlists, top = highest priority" data-test="list">
      {#snippet header()}
        <Hint text="top = highest priority · drag ⋮⋮ or ⌥↑ ⌥↓" data-test="priority-hint" />
        <InfoTip label="About the order">A track in several playlists is downloaded once, into the folder of the
          highest one.</InfoTip>
      {/snippet}
      {#each draft as row, i (row.key)}
        <Row {row} prio={prios[i]} {draft} delta={changes.get(row.folder) ?? null} offset={offsetOf(i)}
          dragging={drag?.from === i} onhandledown={(e) => startDrag(e, i)} onmove={(d) => move(row.key, d)}
          onrename={(f) => (draft = rename(draft, row.key, f))} ontoggle={() => (draft = toggle(draft, row.key))}
          onremove={() => removeRow(row)} />
      {/each}
    </Surface>
  {/if}
{/snippet}

{#snippet actions()}
  <Button variant={waiting ? 'primary' : 'secondary'} disabled={!loaded || dirty || movesBusy}
    title={dirty ? 'Save or undo your changes first.' : movesBusy ? 'Files are moving.' : undefined}
    onclick={() => openFlow({ kind: 'tidy' })} data-test="tidy-button">Tidy up files{#if waiting}<span class="count"
      class:off={!loaded || dirty || movesBusy} data-test="tidy-waiting">{waiting}</span>{/if}</Button>
{/snippet}

{#snippet side()}
  {#if flow && (!dirty || movesBusy)}
    {#key flowTurn}
      <MovesPanel entry={flow} onclose={closeFlow} onlist={() => { closeFlow(); tab = 'moves'; }}
        onbusy={(b) => (movesBusy = b)} />
    {/key}
  {:else}
    <ChangePanel {dirty} lines={draftLines} overlaps={pl?.overlaps ?? []} rows={pl?.rows ?? []} {saving} {tab}
      onpanel={(p) => (panel = p)} ontab={(t) => (tab = t)} onundo={() => loaded && (draft = undo(loaded))}
      onsave={save} onundobatch={(id) => openFlow({ kind: 'undo', batch_id: id })} />
  {/if}
{/snippet}

<ListPanelFrame {main} panel={side} />

<style>
  /* while a row is dragged the others make room smoothly; the dragged one follows the pointer 1:1 */
  :global([data-test='list'].dragging .pl:not(.drag)) { transition: transform var(--t-state) var(--ease); }
  :global([data-test='list']) { user-select: none; }
  .count { margin-left: var(--s-2); color: var(--accent-text); font-variant-numeric: tabular-nums;
    transition: color var(--t-state) var(--ease); }
  .count.off { color: inherit; }
</style>
