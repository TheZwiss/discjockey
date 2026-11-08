<script lang="ts">
  // To-do (Task 67, spec §5.3; design system mockup design-system/todo.html, option A): on ListPanelFrame. The list
  // area: the header, the filter strip (Segmented: All and four groups, the rest under More), then ONE list Surface
  // that fills the height and scrolls in place (`grow`), whatever the library's size: the groups are ListSection
  // heads among its rows, sticking while their rows pass, so a long group never pushes the others off screen. Show
  // hidden sits in the list's head. The panel is the selected to-do (Details: its own Panel, the main action in the
  // foot). The import's two groups (plan library stage 4) bring their own panels: QuestionDetails and
  // DuplicateDetails, built from the item's `pair` alone (their songs need no track() call: a question's song may not
  // be downloaded, a duplicate group is no track).
  // Multi-select (issue 33 stage B §6.1, lib/components/selectionModel): ⌘-click, ⇧-click and ⌘A select several items
  // of one group where the group allows it (todoModel MULTI_GROUPS); every selected row wears the picked wash, and
  // two or more Upgrade ready items show the selection panel (lib/decisions/UpgradeSelection). The group's head
  // carries "Upgrade all · n" (selects the group) or, while a Same track batch is stopped, "Resume · k left". A batch
  // keeps its panel until the next pick, also when its tracks have left the group (`pinned`).
  import { tick, untrack } from 'svelte';
  import { api } from '$lib/bridge/client';
  import { isDuplicate, isQuestion } from '$lib/bridge/types';
  import { hub, writeBlockedReason } from '$lib/stores/hub';
  import type { Fail, Todo, TodoFilter, TodoItem, TrackDetail } from '$lib/bridge/types';
  import { filesVersion } from '$lib/stores/hub';
  import {
    NO_SELECTION, clickSelect, dropSelected, escapeSelection, isSelected, keepSelected, moveSelected, onlySelected,
    selectAll, selectOne, selectScope, type Selection,
  } from '$lib/components';
  import { UpgradeSelection, upgradeBatch } from '$lib/decisions';
  import { resumeLabel, upgradeAllLabel } from '$lib/decisions/decisionModel';
  import { getPref, setPref } from '$lib/prefs';
  import { markReady } from '$lib/ready';
  import {
    AwayTag, Badge, Button, Cover, EmptyState, ListRow, ListSection, PageHeader, ProblemCard, Segmented, Skeleton, Surface,
  } from '$lib/components';
  import { ListPanelFrame, Panel } from '$lib/frames';
  import { artistTitle, rowAway } from '$lib/format';
  import {
    FILTER_MAX, segOptions, filterFrom, findHeld, flatten, ghostOf, headerSub, holdApplies, itemKey, keepSelection,
    multiScope, openCount, queueRows, rowBadge, rowDim, selectAfterHide, selectFromTrack, upgradeGroup, withHeldItem,
    type TodoHold,
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
  let sel = $state<Selection>(NO_SELECTION);
  const selKey = $derived(onlySelected(sel));
  let wantTrack: string | null = untrack(() => query.get('track'));
  let seq = 0;

  const items = $derived(flatten(data));
  const selected = $derived(items.find((i) => itemKey(i) === selKey) ?? null);
  const order = $derived(items.map(itemKey));
  const scopeOf = $derived(multiScope(items));
  // two or more Upgrade ready items: the selection panel; a batch's panel also stays for its own tracks while it runs,
  // and after it until the next pick (`pinned`)
  const selItems = $derived(items.filter((i) => isSelected(sel, itemKey(i))));
  const multiUp = $derived(selItems.length > 1 && selItems.every((i) => i.group === 'upgrade_ready'));
  let pinned = $state(false);
  const batchShown = $derived(!!upgradeBatch.view && (pinned || multiUp
    || (selected?.group === 'upgrade_ready' && upgradeBatch.covers([selected.track_id]))));
  const selPanel = $derived(multiUp || batchShown);
  const upGroup = $derived(upgradeGroup(data));
  const wholeGroup = $derived(!!upGroup && multiUp && upGroup.items.filter((i) => !i.hidden).every((i) => isSelected(sel, itemKey(i))));
  // a batch the hub runs that this window didn't start (it was reloaded): its panel follows it
  $effect(() => { const j = $hub.job; untrack(() => upgradeBatch.adopt(j)); });

  // The item just acted on in the details stays in the list and selected (todoModel TodoHold): the user's own pick,
  // another filter or Show hidden ends it. When that left a re-fetch that had put the item back, the list asks again.
  let hold = $state<TodoHold | null>(null);
  $effect(() => {
    const h = hold;
    if (h && !holdApplies(h, selKey, filter, showHidden)) {
      untrack(() => {
        hold = null;
        if (h.put && h.filter === filter && h.showHidden === showHidden) void load();
      });
    }
  });
  // The row a load put into the list that the answer didn't list (the held item is no open to-do of this filter): the
  // section heads count the open items, so not that one, as the chips don't.
  let extraKey = $state<string | null>(null);
  function acted(keep: string[] | null) {
    if (!selected || !selKey) return;
    // a second action on an item that was put in keeps the "ask again when it ends"
    const put = holdApplies(hold, selKey, filter, showHidden) && !!hold?.put;
    hold = { key: selKey, id: selected.track_id, keep, filter, showHidden, put, ghost: false };
  }

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
    if (sel.anchor) document.querySelector<HTMLElement>(`[data-key="${CSS.escape(sel.anchor)}"] button.main`)?.focus();
  }

  async function load() {
    const my = ++seq;
    const r = await api.todo(filter, showHidden);
    if (my !== seq) return;
    if (r.ok) {
      const { ok: _ok, ...base } = r;
      let rest: Todo = base;
      const before = items;
      let after = flatten(rest);
      const fromQuery = selectFromTrack(after, wantTrack);
      if (wantTrack && !fromQuery && filter !== 'all') {
        pick('all');   // the asked-for track is outside the chosen chip: show everything (reloads, keeps wantTrack)
        return;
      }
      wantTrack = null;
      // the held item: still listed, or (a replace under "Upgrades" took it to "Check in rekordbox") put back in the
      // section it stood in, from the whole to-do list; with no to-do left of it, its row as it was
      let held: TodoItem | null = null;
      let next = hold;
      let put = false;
      if (!fromQuery && hold && holdApplies(hold, selKey, filter, showHidden)) {
        const h = hold;
        held = findHeld(after, h);
        let ghost = false;
        let live = true;
        if (!held && filter !== 'all') {
          const all = await api.todo('all', showHidden);
          if (my !== seq) return;
          // the user may have picked another item meanwhile (the hold ended): then nothing is held and the pick stays
          live = hold === h;
          held = live && all.ok ? findHeld(flatten(all), h) : null;
          put = !!held;
        }
        const old = before.find((i) => itemKey(i) === h.key);
        if (live && !held && !h.keep && old) { held = ghostOf(old); put = true; ghost = true; }
        if (held && put) {
          rest = withHeldItem(rest, held, data, h.key);
          after = flatten(rest);
        }
        if (held) next = { ...h, key: itemKey(held), put: put || h.put, ghost };
      }
      data = rest;
      extraKey = held && !fromQuery && put ? itemKey(held) : null;
      error = null;
      const was = sel.anchor;
      sel = fromQuery ? selectOne(fromQuery) : held ? selectOne(itemKey(held))
        : keepSelected(sel, before.map(itemKey), after.map(itemKey), (a) => keepSelection(a, before, after));
      if (held && !fromQuery) hold = next;
      if (was !== null && sel.anchor !== was) void focusSelected();
    } else {
      error = r;   // old data stays on screen
    }
    markReady('todo');
  }
  // on mount, after every finished job, a drive coming or going and on filter / show-hidden changes
  $effect(() => { void $filesVersion; void filter; void showHidden; untrack(() => void load()); });

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
      if (k) { pickOne(k); } else { wantTrack = t; void load(); }
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
    void $filesVersion;
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
  /** A pick of the user's own: a batch's end goes away with its panel (a running batch goes on). */
  function picked(next: Selection) {
    sel = next;
    pinned = false;
    upgradeBatch.clear();
  }
  function pickOne(key: string | null) { picked(selectOne(key)); }
  function choose(key: string, e: MouseEvent) {
    picked(clickSelect(sel, key, { meta: e.metaKey, shift: e.shiftKey }, order, scopeOf));
  }

  function keydown(e: KeyboardEvent) {
    if (e.ctrlKey || e.altKey || e.defaultPrevented) return;
    const t = e.target as HTMLElement | null;
    if (t?.closest('input, textarea, select, dialog, [role=dialog], [role=slider]')) return;
    if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && !e.metaKey) {
      e.preventDefault();
      picked(moveSelected(sel, order, e.key === 'ArrowDown' ? 1 : -1));
    } else if (e.key === 'a' && e.metaKey && !e.shiftKey) {
      const all = selectAll(sel, order, scopeOf);
      if (all !== sel) { e.preventDefault(); picked(all); }
    } else if (e.key === 'Escape' && !e.metaKey && sel.keys.length > 1) {
      e.preventDefault();
      picked(escapeSelection(sel));
    }
  }
  function hidden() {
    if (!showHidden && selKey) pickOne(selectAfterHide(items, selKey));
  }

  /** "Upgrade all · n": the group selected, its first item the anchor; the panel then offers it. */
  function upgradeAll() { picked(selectScope('upgrade_ready', order, scopeOf)); }
  /** "Resume · k left": confirmed when the batch started, so it runs at once; its panel shows the progress. */
  function resume(batch_id: number) {
    upgradeBatch.clear();
    pinned = true;
    void upgradeBatch.resume(batch_id);
  }
  /** The selection panel's Done: back to the group's first item (or the list's first one). */
  function batchDone() {
    pinned = false;
    const first = upGroup?.items[0] ?? items[0];
    sel = selectOne(first ? itemKey(first) : null);
  }
  // the panel's own Resume says it while it shows that batch's end, so the head doesn't say it twice
  const headResume = $derived(upGroup?.stopped && !(batchShown && upgradeBatch.view?.end?.resume?.batch_id === upGroup.stopped.batch_id)
    ? upGroup.stopped : null);

  // Part B: the "Wrong song?" / "Find a version" dialog opens for this track.
  let versionsFor = $state<TrackDetail | null>(null);
  function openVersions(t: TrackDetail) { versionsFor = t; }

  // one list: sections only when it shows more than one group; a single group names the list itself
  // the strip only when there is something to choose: All alone would be one stretched segment
  const options = $derived(data ? segOptions(data.chips, filter) : []);
  const sections = $derived((data?.groups.length ?? 0) > 1);
  const only = $derived(!sections ? data?.groups[0] ?? null : null);
  const rowCount = $derived(items.length + (sections ? data?.groups.length ?? 0 : 0));
  // cover · "Artist – Title" over "folder · detail" · quality badge (or the AwayTag of a file that is away), then a
  // fixed slot for UPGRADE / FREE / HIDDEN, so every badge ends at one x down the whole list
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
    {@const away = rowAway(i)}
    {#if away}<AwayTag state={away} test="todo-away" />{:else}<Badge tone={b.quality} text={b.label} />{/if}
    <span class="act">{#if i.hidden}<Badge tone="muted" text="HIDDEN" />{:else if i.upgrade_ready}<Badge tone="lossless"
      text="UPGRADE" />{:else if i.free}<span title="The artist gives it away for free"><Badge tone="accent"
      text="FREE" /></span>{/if}</span>
  {/snippet}
  {@const on = isSelected(sel, key)}
  <ListRow {lead} {name} {sub} {trailing} selected={on} reveal={on && key === sel.anchor} pick off={rowDim(i)}
    onclick={(e) => choose(key, e)}
    title={artistTitle(i.artist, i.title)} test="todo-row" data-key={key} data-track={i.track_id} />
{/snippet}

{#snippet groupAction()}
  <!-- a stopped batch is resumed, not started again: while one waits the head offers only Resume (or nothing while
       the panel's own Resume says it) -->
  {#if headResume}
    {@const r = headResume}
    <Button variant="link" size="sm" disabled={!!$writeBlockedReason} title={$writeBlockedReason ?? undefined}
      onclick={() => resume(r.batch_id)} data-test="todo-resume">{resumeLabel(r.left)}</Button>
  {:else if !upGroup?.stopped && upGroup?.all?.n}
    <Button variant="link" size="sm" onclick={upgradeAll} data-test="todo-upgrade-all">{upgradeAllLabel(upGroup.all.n)}</Button>
  {/if}
{/snippet}

{#snippet main()}
  <PageHeader title="To-do" sub={data ? headerSub(data.chips) : undefined} readStatus />

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
      <Surface kind="list" label={only ? only.label : 'All to-dos'} summary={only ? String(openCount(only.items, extraKey)) : undefined} hint={only?.hint} summaryTest="todo-count"
        header={data.hidden_count || showHidden ? hiddenToggle : undefined} style={COLS}
        action={only?.key === 'upgrade_ready' ? groupAction : undefined}
        grow={{ rows: rowCount, tall: true }} data-test="todo-list">
        {#each data.groups as g (g.key)}
          {#if sections}<ListSection label={g.label} summary={String(openCount(g.items, extraKey))} hint={g.hint}
            action={g.key === 'upgrade_ready' ? groupAction : undefined} test="todo-section" />{/if}
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
  {#if selPanel}
    <UpgradeSelection items={selItems.filter((i) => i.group === 'upgrade_ready')} all={wholeGroup}
      nameOf={(i) => artistTitle(i.artist, i.title)} ondrop={(i) => picked(dropSelected(sel, itemKey(i)))}
      ondone={batchDone} onact={() => (pinned = true)} />
  {:else if selected && isQuestion(selected)}
    {#key itemKey(selected)}<QuestionDetails item={selected} />{/key}
  {:else if selected && isDuplicate(selected)}
    {#key selected.pair.group_id}<DuplicateDetails item={selected} onacted={acted} />{/key}
  {:else if track}
    <Details {track} item={selected?.track_id === track.track_id && !hold?.ghost ? selected : null} onhidden={hidden}
      onversions={openVersions} onlisten={() => track && listenFrom(track)} onacted={() => acted(null)} />
  {:else}
    <Panel head={trackError ? failed : waiting} />
  {/if}
{/snippet}

{#snippet nothing()}
  <div class="nothing" data-test="todo-nothing"><EmptyState title="Nothing to decide"
    body="When a better version arrives or two files are the same song, you choose here." /></div>
{/snippet}

<!-- with no to-do left the panel says when it will have something, never blank (mockup todo-decisions) -->
<ListPanelFrame {main} panel={selected || selPanel ? panel : data?.empty === 'all_lossless' || data?.empty === 'all_hidden' ? nothing : null}
  emptyPanel="Pick a track to see what you can do." />

{#if versionsFor}
  {#key versionsFor.track_id}
    <WrongSongDialog track={versionsFor} onclose={() => (versionsFor = null)} />
  {/key}
{/if}

<style>
  /* the badge's slot after it: 64 px fits UPGRADE, the widest, so every quality badge ends at one x */
  .act { display: inline-flex; justify-content: flex-end; min-width: var(--w-row-action); }
  .again { display: flex; justify-content: center; }
  .nothing { height: 100%; display: flex; align-items: center; justify-content: center; padding: 0 var(--s-5); }
</style>
