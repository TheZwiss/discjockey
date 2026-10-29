<script lang="ts">
  // To-do (Task 67, spec §5.3; design system mockup design-system/todo.html, option A): on ListPanelFrame. The list
  // area: the header, the filter strip (Segmented: All and four groups, the rest under More), then ONE list Surface
  // that fills the height and scrolls in place (`grow`), whatever the library's size: the groups are ListSection
  // heads among its rows, sticking while their rows pass, so a long group never pushes the others off screen. Show
  // hidden sits in the list's head. The panel is the selected to-do (Details: its own Panel, the main action in the
  // foot). The import's two groups (plan library stage 4) bring their own panels: QuestionDetails and
  // DuplicateDetails, built from the item's `pair` alone (their songs need no track() call: a question's song may not
  // be downloaded, a duplicate group is no track).
  import { tick, untrack } from 'svelte';
  import { api } from '$lib/bridge/client';
  import { isDuplicate, isQuestion } from '$lib/bridge/types';
  import type { Fail, Todo, TodoFilter, TodoItem, TrackDetail } from '$lib/bridge/types';
  import { dataVersion } from '$lib/stores/hub';
  import { getPref, setPref } from '$lib/prefs';
  import { markReady } from '$lib/ready';
  import {
    Badge, Button, Cover, EmptyState, ListRow, ListSection, PageHeader, ProblemCard, Segmented, Skeleton, Surface,
  } from '$lib/components';
  import { ListPanelFrame, Panel } from '$lib/frames';
  import { artistTitle } from '$lib/format';
  import {
    FILTER_MAX, segOptions, filterFrom, flatten, headerSub, itemKey, keepSelection, moveSelection, queueRows, rowBadge, rowOff,
    selectAfterHide, selectFromTrack,
  } from './todoModel';
  import Details from './Details.svelte';
  import QuestionDetails from './QuestionDetails.svelte';
  import DuplicateDetails from './DuplicateDetails.svelte';
  import { listen } from '$lib/listen';
  import { player } from '$lib/stores/player';
  import WrongSongDialog from './WrongSongDialog.svelte';

  let { params: _params, query }: { params: Record<string, string>; query: URLSearchParams } = $props();

  let filter = $state<TodoFilter>(filterFrom(untrack(() => query.get('filter')), getPref('todo.filter', 'all')));
  let showHidden = $state(false);
  let data = $state<Todo | null>(null);
  let error = $state<Fail | null>(null);
  let selKey = $state<string | null>(null);
  let wantTrack: string | null = untrack(() => query.get('track'));
  let seq = 0;

  const items = $derived(flatten(data));
  const selected = $derived(items.find((i) => itemKey(i) === selKey) ?? null);

  // ▶ in the details starts the to-do list as the queue: its rows with a file, in the order shown. A track that
  // isn't among them (the list changed meanwhile) plays on its own.
  function listenFrom(t: TrackDetail) {
    if (listen(queueRows(items), t.track_id, { label: 'To-do', href: '#/todo' })) return;
    if (t.audio_url) player.play({ url: t.audio_url, title: artistTitle(t.artist, t.title), track_id: t.track_id });
  }

  // After an answer, Keep or Move to Superseded the selection moves on and the button that was pressed is gone, so
  // focus would fall to the page. It goes to the row now selected, so the arrow keys and Tab carry on from there.
  // Only when focus was lost (on the page, or in the old panel): never out of a dialog, a field or the list itself.
  async function focusSelected() {
    await tick();
    const a = document.activeElement;
    if (a && a !== document.body && !a.closest('[data-panel]')) return;
    if (selKey) document.querySelector<HTMLElement>(`[data-key="${CSS.escape(selKey)}"] button.main`)?.focus();
  }

  async function load() {
    const my = ++seq;
    const r = await api.todo(filter, showHidden);
    if (my !== seq) return;
    if (r.ok) {
      const { ok: _ok, ...rest } = r;
      const before = items;
      const after = flatten(rest);
      const fromQuery = selectFromTrack(after, wantTrack);
      if (wantTrack && !fromQuery && filter !== 'all') {
        pick('all');   // the asked-for track is outside the chosen chip: show everything (reloads, keeps wantTrack)
        return;
      }
      wantTrack = null;
      data = rest;
      error = null;
      const was = selKey;
      selKey = fromQuery ?? keepSelection(selKey, before, after);
      if (was !== null && selKey !== was) void focusSelected();
    } else {
      error = r;   // old data stays on screen
    }
    markReady('todo');
  }
  // on mount, after every finished job and on filter / show-hidden changes
  $effect(() => { void $dataVersion; void filter; void showHidden; untrack(() => void load()); });

  // Sync's "Fix →" links: ?track= while the page is already open
  let lastQueryTrack = untrack(() => query.get('track'));
  let lastQueryFilter = untrack(() => query.get('filter'));
  $effect(() => {
    const f = query.get('filter');
    if (f && f !== lastQueryFilter) { lastQueryFilter = f; untrack(() => pick(filterFrom(f, filter))); }
  });
  $effect(() => {
    const t = query.get('track');
    if (t && t !== lastQueryTrack) {
      lastQueryTrack = t;
      const k = selectFromTrack(items, t);
      if (k) { selKey = k; } else { wantTrack = t; void load(); }
    }
  });

  // details: track() on selection, again after every finished job (the old one stays while re-fetching)
  let track = $state<TrackDetail | null>(null);
  let trackError = $state<Fail | null>(null);
  let tseq = 0;
  // the import's items have their panel from the item itself: no track() for them, and no track to select
  const selId = $derived(selected && !selected.pair ? selected.track_id : null);
  let lastSelected: string | null | undefined = undefined;
  $effect(() => {
    const id = selId;
    void $dataVersion;
    untrack(() => {
      if (id !== lastSelected) { lastSelected = id; void api.select(id); }
      void loadTrack(id);
    });
  });
  async function loadTrack(id: string | null) {
    const my = ++tseq;
    if (!id) { track = null; trackError = null; return; }
    if (track && track.track_id !== id) track = null;
    const r = await api.track(id);
    if (my !== tseq) return;
    if (r.ok) { track = r.track; trackError = null; } else trackError = r;
  }

  function pick(f: TodoFilter) {
    filter = f;
    setPref('todo.filter', f);
  }
  function choose(key: string) { selKey = key; }

  function keydown(e: KeyboardEvent) {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    if (e.metaKey || e.ctrlKey || e.altKey || e.defaultPrevented) return;
    const t = e.target as HTMLElement | null;
    if (t?.closest('input, textarea, select, dialog, [role=dialog], [role=slider]')) return;
    e.preventDefault();
    selKey = moveSelection(items, selKey, e.key === 'ArrowDown' ? 1 : -1);
  }
  function hidden() {
    if (!showHidden && selKey) selKey = selectAfterHide(items, selKey);
  }

  // Part B: the "Wrong song?" / "Find a version" dialog opens for this track.
  let versionsFor = $state<TrackDetail | null>(null);
  function openVersions(t: TrackDetail) { versionsFor = t; }

  // one list: sections only when it shows more than one group; a single group names the list itself
  // the strip only when there is something to choose: All alone would be one stretched segment
  const options = $derived(data ? segOptions(data.chips, filter) : []);
  const sections = $derived((data?.groups.length ?? 0) > 1);
  const only = $derived(!sections ? data?.groups[0] ?? null : null);
  const rowCount = $derived(items.length + (sections ? data?.groups.length ?? 0 : 0));
  // cover · "Artist – Title" over "folder · detail" · quality badge, then a fixed slot for UPGRADE / FREE / HIDDEN,
  // so every badge ends at one x down the whole list
  const COLS = '--row-cols: 28px minmax(0, 1fr) auto';
</script>

<svelte:window onkeydown={keydown} />

{#snippet hiddenToggle()}
  {#if data && (data.hidden_count || showHidden)}
    <Button variant="link" muted size="sm" onclick={() => (showHidden = !showHidden)} data-test="show-hidden">
      {showHidden ? 'Hide hidden tracks' : `Show hidden · ${data.hidden_count}`}</Button>
  {/if}
{/snippet}

{#snippet row(i: TodoItem)}
  {@const key = itemKey(i)}
  {#snippet lead()}<Cover url={i.cover_url} seed={i.track_id} size={28} />{/snippet}
  {#snippet name()}{artistTitle(i.artist, i.title)}{/snippet}
  {#snippet sub()}{[i.folder, i.detail].filter(Boolean).join(' · ')}{/snippet}
  {#snippet trailing()}
    {@const b = rowBadge(i)}
    <Badge tone={b.quality} text={b.label} />
    <span class="act">{#if i.hidden}<Badge tone="muted" text="HIDDEN" />{:else if i.upgrade_ready}<Badge tone="lossless"
      text="UPGRADE" />{:else if i.free}<span title="The artist gives it away for free"><Badge tone="accent"
      text="FREE" /></span>{/if}</span>
  {/snippet}
  <ListRow {lead} {name} {sub} {trailing} selected={key === selKey} off={rowOff(i)} onclick={() => choose(key)}
    title={artistTitle(i.artist, i.title)} test="todo-row" data-key={key} data-track={i.track_id} />
{/snippet}

{#snippet main()}
  <PageHeader title="To-do" sub={data ? headerSub(data.chips) : undefined} spotify />

  {#if error}
    <ProblemCard kind={error.kind} message={error.message} onretry={load} compact={!!data} />
  {/if}

  {#if data}
    {#if options.length > 1}
      <Segmented {options} value={filter} onchange={pick} label="Show" max={FILTER_MAX} test="todo-filter" />
    {/if}
    {#if data.empty}
      <Surface kind="card" data-test="todo-empty">
        <EmptyState kind={data.empty} />
        {#if data.hidden_count || showHidden}<div class="again">{@render hiddenToggle()}</div>{/if}
      </Surface>
    {:else}
      <Surface kind="list" label={only ? only.label : 'All to-dos'} summary={only ? String(only.items.length) : undefined} hint={only?.hint}
        header={data.hidden_count || showHidden ? hiddenToggle : undefined} style={COLS}
        grow={{ rows: rowCount, tall: true }} data-test="todo-list">
        {#each data.groups as g (g.key)}
          {#if sections}<ListSection label={g.label} summary={String(g.items.length)} hint={g.hint} test="todo-section" />{/if}
          {#each g.items as i (itemKey(i))}{@render row(i)}{/each}
        {/each}
      </Surface>
    {/if}
  {:else if !error}
    <Surface kind="card"><Skeleton lines={8} height={28} gap={8} /></Surface>
  {/if}
{/snippet}

{#snippet waiting()}<Skeleton lines={6} height={18} gap={10} />{/snippet}
{#snippet failed()}
  {#if trackError}<ProblemCard kind={trackError.kind} message={trackError.message} compact onretry={() => loadTrack(selId)} />{/if}
{/snippet}

{#snippet panel()}
  {#if selected && isQuestion(selected)}
    {#key itemKey(selected)}<QuestionDetails item={selected} />{/key}
  {:else if selected && isDuplicate(selected)}
    {#key selected.pair.group_id}<DuplicateDetails item={selected} />{/key}
  {:else if track}
    <Details {track} item={selected?.track_id === track.track_id ? selected : null} onhidden={hidden}
      onversions={openVersions} onlisten={() => track && listenFrom(track)} />
  {:else}
    <Panel head={trackError ? failed : waiting} />
  {/if}
{/snippet}

<ListPanelFrame {main} panel={selected ? panel : null} emptyPanel="Pick a track to see what you can do." />

{#if versionsFor}
  {#key versionsFor.track_id}
    <WrongSongDialog track={versionsFor} onclose={() => (versionsFor = null)} />
  {/key}
{/if}

<style>
  /* the badge's slot after it: 64 px fits UPGRADE, the widest, so every quality badge ends at one x */
  .act { display: inline-flex; justify-content: flex-end; min-width: var(--w-row-action); }
  .again { display: flex; justify-content: center; }
</style>
