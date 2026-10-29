<script lang="ts">
  // The track table (design system mockup design-system/library.html): one `Surface kind="table" grow` that fills
  // the list area up to its rows and scrolls inside, its column head (`SortHeader`s and the ⓘ with the keys) fixed
  // above the rows. Columns: cover + track · artist · the optional ones · length · quality · a fixed slot for UPGRADE
  // (To-do's), so every badge ends at one x. The optional columns appear as the table itself gets wider
  // (`@container list`, spec §3): Source, then Added; in All tracks Folder first. Above 300 rows only the visible
  // ones are rendered (windowSlice). ↑ / ↓ select, Enter plays, right-click opens the shared menu; the cover is the
  // row's play button (▶ while the row is hovered, ❚❚ while it plays). A row whose file is away (its drive offline, its
  // watched folder not found: `file_state`) is dimmed, says why with an `AwayTag` in the quality column (the one fixed
  // column wide enough for "Folder not found" at every width; the quality stays in the panel and the filters), and
  // doesn't play: no ▶ on its cover, double-click and Enter do nothing, the menu has no Show in Finder.
  import { AwayTag, Badge, ContextMenu, Cover, InfoTip, QualityBadge, Skeleton, SortHeader, Surface } from '$lib/components';
  import { artistTitle, dayMonth, duration } from '$lib/format';
  import type { LibraryRow, LibrarySort } from '$lib/bridge/types';
  import {
    folderCell, inTodo, moveSelection, optionalColumns, playable, rowAway, rowOff, rowTitleTip, scrollToCenter, scrollToKeep, selectedIndex,
    sortState, windowSlice, type LibraryView, type SortColumn,
  } from './libraryModel';

  let { rows, loading = false, view = 'folder', sort, selected, playing = null, onsort, onselect, onplay, onfinder,
    ontodo }: {
    rows: LibraryRow[]; loading?: boolean;
    /** All tracks: the rows come from several folders, so Folder is a column. A folder and Not in a playlist (whose
     *  rows would all say the same) show Source first. */
    view?: LibraryView; sort: LibrarySort; selected: string | null;
    /** the track playing now */
    playing?: string | null;
    onsort: (c: SortColumn) => void; onselect: (id: string) => void; onplay: (id: string) => void;
    onfinder: (id: string) => void; ontodo: (id: string) => void;
  } = $props();

  const LABEL: Record<SortColumn, string> = { title: 'Track', artist: 'Artist', folder: 'Folder', source: 'Source',
    added: 'Added', length: 'Length', quality: 'Quality' };

  let root = $state<HTMLElement | undefined>();
  let scroller = $state<HTMLElement | null>(null);
  let scrollTop = $state(0);
  let viewport = $state(400);
  let rowH = $state(38);
  let hovered = $state<string | null>(null);
  let centred = false;
  let menu: { id: string; x: number; y: number; todo: boolean; finder: boolean } | null = $state(null);

  const st = $derived(sortState(sort));
  const extra = $derived(optionalColumns(view));
  const allTracks = $derived(view === 'all');
  const slice = $derived(windowSlice(scrollTop, viewport, rowH, rows.length));
  const visible = $derived(rows.slice(slice.start, slice.end));
  const sorted = (c: SortColumn) => (st.column === c ? (st.desc ? 'desc' : 'asc') : null);

  $effect(() => {
    const el = scroller;
    if (!el || !root) return;
    const v = parseFloat(getComputedStyle(root).getPropertyValue('--h-row'));
    if (v > 0) rowH = v;
    viewport = el.clientHeight;
    const ro = new ResizeObserver(() => { viewport = el.clientHeight; });
    ro.observe(el);
    const onScroll = () => { scrollTop = el.scrollTop; menu = null; };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => { ro.disconnect(); el.removeEventListener('scroll', onScroll); };
  });

  // The selected row stays in view (first load with ?track=: in the middle).
  $effect(() => {
    const i = selectedIndex(rows, selected);
    const el = scroller;
    if (!el || !rows.length) return;
    if (i < 0) { centred = true; return; }
    const next = centred ? scrollToKeep(el.scrollTop, el.clientHeight, rowH, i) : scrollToCenter(el.clientHeight, rowH, i);
    centred = true;
    if (next !== el.scrollTop) { el.scrollTop = next; scrollTop = next; }
  });

  function key(e: KeyboardEvent) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const id = moveSelection(rows, selected, e.key === 'ArrowDown' ? 1 : -1);
      if (id) onselect(id);
    } else if (e.key === 'Enter' && selected) {
      e.preventDefault();
      const r = rows.find((x) => x.track_id === selected);
      if (r && playable(r)) onplay(selected);   // an away row's file isn't there: nothing to try
    } else if (e.key === 'Escape' && menu) {
      menu = null;
    }
  }
  function context(e: MouseEvent, r: LibraryRow) {
    e.preventDefault();
    onselect(r.track_id);
    // an away file can't be shown in Finder (the panel offers it only for a file that is there)
    const finder = playable(r), todo = inTodo(r);
    menu = finder || todo ? { id: r.track_id, x: e.clientX, y: e.clientY, todo, finder } : null;
  }
  function pick(fn: (id: string) => void) {
    const id = menu?.id;
    menu = null;
    if (id) fn(id);
  }
</script>

{#snippet columns()}
  <div class="tr head" class:all={allTracks} role="row" bind:this={root}>
    <SortHeader label={LABEL.title} sorted={sorted('title')} onsort={() => onsort('title')} test="sort-title" />
    <SortHeader label={LABEL.artist} sorted={sorted('artist')} onsort={() => onsort('artist')} test="sort-artist" />
    {#each extra as c, i (c)}
      <span class="o o{i + 1}"><SortHeader label={LABEL[c]} sorted={sorted(c)} onsort={() => onsort(c)} test="sort-{c}" /></span>
    {/each}
    <SortHeader label={LABEL.length} align="end" sorted={sorted('length')} onsort={() => onsort('length')} test="sort-length" />
    <SortHeader label={LABEL.quality} sorted={sorted('quality')} onsort={() => onsort('quality')} test="sort-quality" />
    <span class="tip"><InfoTip label="Keys and clicks" data-test="library-keys">Click a header to sort, again to turn it
      round. ↑ ↓ move. Double-click, Enter or the cover plays. Right-click: Show in Finder, Open in to-do.</InfoTip></span>
  </div>
{/snippet}

<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<Surface kind="table" grow={{ rows: Math.max(1, rows.length) }} {columns} bind:scroller role="grid" aria-label="Tracks"
  tabindex={0} onkeydown={key} data-test="library-table">
  {#if loading && !rows.length}
    <div class="sk"><Skeleton lines={8} height={14} gap={24} /></div>
  {:else}
    <div class="spacer" aria-hidden="true" data-test="spacer-above" style:height="{slice.start * rowH}px"></div>
    {#each visible as r (r.track_id)}
      {@const away = rowAway(r)}
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <div class="tr" class:all={allTracks} class:sel={r.track_id === selected} class:off={rowOff(r) || !!away} role="row"
        tabindex="-1" aria-selected={r.track_id === selected} data-test="row-{r.track_id}" data-away={away}
        onclick={() => onselect(r.track_id)} ondblclick={() => { if (!away) onplay(r.track_id); }}
        oncontextmenu={(e) => context(e, r)}
        onpointerenter={() => (hovered = r.track_id)} onpointerleave={() => { if (hovered === r.track_id) hovered = null; }}>
        <span class="td title" title={rowTitleTip(r, artistTitle(r.artist, r.title))}>
          <span class="cov"><Cover url={r.cover_url} seed={r.track_id} size={22} playing={playing === r.track_id}
            hint={hovered === r.track_id} name={artistTitle(r.artist, r.title)}
            onplay={away ? undefined : () => onplay(r.track_id)} /></span>
          <span class="cut">{r.title}</span>
        </span>
        <span class="td cut sub">{r.artist}</span>
        {#each extra as c, i (c)}
          <span class="td cut sub o o{i + 1}" class:quiet={c === 'folder' && rowOff(r)}>
            {c === 'folder' ? folderCell(r) : c === 'source' ? (r.source_name ?? '–') : (dayMonth(r.added) || '–')}</span>
        {/each}
        <span class="td num">{duration(r.duration_s)}</span>
        <span class="td">{#if away}<AwayTag state={away} test="away-{r.track_id}" />{:else}<QualityBadge
          quality={r.quality} label={r.quality_label} checked={r.sound_checked} />{/if}</span>
        <span class="td slot">{#if r.upgrade_ready}<Badge tone="lossless" text="UPGRADE" />{/if}</span>
      </div>
    {/each}
    <div class="spacer" aria-hidden="true" data-test="spacer-below" style:height="{(rows.length - slice.end) * rowH}px"></div>
  {/if}
</Surface>

{#if menu}
  <ContextMenu x={menu.x} y={menu.y} test="library-context-menu" onclose={() => (menu = null)}
    items={[...(menu.finder ? [{ label: 'Show in Finder', onpick: () => pick(onfinder) }] : []),
      ...(menu.todo ? [{ label: 'Open in to-do', test: 'menu-todo', onpick: () => pick(ontodo) }] : [])]} />
{/if}

<style>
  /* the columns belong to the table: cover + track · artist · optional · length · quality · UPGRADE slot.
     The quality column fits the widest badge (FAKE · 16.0 kHz), so every badge starts at one x. */
  .tr {
    --c-track: minmax(0, 1.6fr); --c-artist: minmax(0, 1.2fr); --c-end: 52px 116px var(--w-row-action);
    display: grid; grid-template-columns: var(--c-track) var(--c-artist) var(--c-end); column-gap: var(--s-3);
    align-items: center; height: var(--h-row); padding: 0 var(--s-4); min-width: 0; color: var(--text);
    font-size: var(--fs-body); cursor: default; transition: background var(--t-hover) var(--ease);
  }
  .tr.head { height: var(--h-list-row); }
  .tr:not(.head) + .tr { border-top: var(--bw) solid var(--line-soft); }
  .tr:not(.head):hover { background: var(--ctl-hover); }
  .tr.sel, .tr.sel:hover { background: var(--nav-on-bg); }
  .tr.off .title .cut { color: var(--text-muted); }
  .tr.off .cov { opacity: var(--dim-cover); }
  .td { min-width: 0; }
  .title { display: flex; align-items: center; gap: var(--s-2); }
  .cov { display: flex; flex: none; transition: opacity var(--t-state) var(--ease); }
  .cut { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sub { color: var(--text-muted); font-size: var(--fs-small); }
  .quiet { color: var(--text-label); }
  .num { justify-self: end; color: var(--text-muted); font-size: var(--fs-small); font-variant-numeric: tabular-nums; }
  .slot { display: flex; justify-content: flex-end; }
  .tip { display: flex; justify-content: flex-end; }
  .o { display: none; }
  .sk { padding: var(--s-3) var(--s-4); }

  /* more space shows more (spec §3): the table's own width, never the window's. A folder: Source, then Added. */
  @container list (min-width: 620px) {
    .tr { grid-template-columns: var(--c-track) var(--c-artist) 84px var(--c-end); }
    .o1 { display: block; }
  }
  @container list (min-width: 800px) {
    .tr { grid-template-columns: var(--c-track) var(--c-artist) 84px 64px var(--c-end); }
    .o2 { display: block; }
  }
  /* All tracks: Folder, then Source, then Added */
  @container list (min-width: 620px) {
    .tr.all { grid-template-columns: var(--c-track) var(--c-artist) 120px var(--c-end); }
    .tr.all .o2 { display: none; }
  }
  @container list (min-width: 780px) {
    .tr.all { grid-template-columns: var(--c-track) var(--c-artist) 120px 84px var(--c-end); }
    .tr.all .o2 { display: block; }
  }
  @container list (min-width: 940px) {
    .tr.all { grid-template-columns: var(--c-track) var(--c-artist) 120px 84px 64px var(--c-end); }
    .o3 { display: block; }
  }
</style>
