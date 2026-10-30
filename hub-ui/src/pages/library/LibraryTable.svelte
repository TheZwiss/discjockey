<script lang="ts">
  // The track table (design system mockup design-system/library-layout.html): one `Surface kind="table" grow` that
  // fills the list area up to its rows and scrolls inside, its column head (`SortHeader`s and the ⓘ with the keys)
  // fixed above the rows. Columns: cover + track · artist · the optional ones · quality · a fixed slot for UPGRADE
  // (To-do's), so every badge ends at one x. The optional columns follow the table's own width, never the window's
  // (plan library stage 5 D10, notes N6): Folder (All tracks, Not in a playlist), then Length; they go in the
  // reverse order. The rows' width is measured (a ResizeObserver, which reports before the frame is painted, so a
  // column never shows for a frame at the wrong width) and `columnsAt` picks the columns, so the thresholds live in
  // one tested place; the head and the rows share the one grid. Above 300 rows only the visible ones are rendered
  // (windowSlice). A click or ↑ / ↓ picks a row (`onselect`; the page opens the details unless the user hid them by
  // hand); a click on a row's quality badge opens the details even then ("why is this weak?", N5). Enter plays,
  // right-click selects without picking (`onselect(id, false)`) and opens the shared menu; the cover is the
  // row's play button (▶ while the row is hovered, ❚❚ while it plays). A row whose file is away (its drive offline, its
  // watched folder not found: `file_state`) is dimmed, says why with an `AwayTag` in the quality column (the one fixed
  // column wide enough for "Folder not found" at every width; the quality stays in the panel and the filters), and
  // doesn't play: no ▶ on its cover, double-click and Enter do nothing, the menu has no Show in Finder.
  import { AwayTag, Badge, ContextMenu, Cover, InfoTip, QualityBadge, Skeleton, SortHeader, Surface, tip } from '$lib/components';
  import { artistTitle, duration } from '$lib/format';
  import type { LibraryRow, LibrarySort } from '$lib/bridge/types';
  import {
    columnsAt, folderCell, gridColumns, inTodo, moveSelection, playable, rowAway, rowOff, rowTitleTip, scrollToCenter,
    scrollToKeep, selectedIndex, sortState, windowSlice, type LibraryView, type SortColumn,
  } from './libraryModel';

  let { rows, loading = false, view = 'folder', sort, selected, playing = null, onsort, onselect, onplay, onfinder,
    ontodo, ondetails }: {
    rows: LibraryRow[]; loading?: boolean;
    /** which list: its optional columns (libraryModel.optionalColumns) */
    view?: LibraryView; sort: LibrarySort; selected: string | null;
    /** the track playing now */
    playing?: string | null;
    onsort: (c: SortColumn) => void;
    /** a row selected; `pick` false: selected for the right-click menu only, not picked to look at */
    onselect: (id: string, pick?: boolean) => void;
    onplay: (id: string) => void;
    onfinder: (id: string) => void; ontodo: (id: string) => void;
    /** open the details inspector (a quality badge, the menu's Show details); the row is selected first */
    ondetails: () => void;
  } = $props();

  const LABEL: Record<SortColumn, string> = { title: 'Track', artist: 'Artist', folder: 'Folder', length: 'Length',
    quality: 'Quality' };

  let root = $state<HTMLElement | undefined>();
  let scroller = $state<HTMLElement | null>(null);
  let scrollTop = $state(0);
  let viewport = $state(400);
  let rowH = $state(38);
  let hovered = $state<string | null>(null);
  let centred = false;
  let menu: { id: string; x: number; y: number; todo: boolean; finder: boolean } | null = $state(null);
  // the rows' own width (the `list` container's): what the optional columns follow
  let width = $state(0);

  const st = $derived(sortState(sort));
  const extra = $derived(columnsAt(view, width));
  const grid = $derived(gridColumns(extra));
  const slice = $derived(windowSlice(scrollTop, viewport, rowH, rows.length));
  const visible = $derived(rows.slice(slice.start, slice.end));
  const sorted = (c: SortColumn) => (st.column === c ? (st.desc ? 'desc' : 'asc') : null);

  $effect(() => {
    const el = scroller;
    if (!el || !root) return;
    const v = parseFloat(getComputedStyle(root).getPropertyValue('--h-row'));
    if (v > 0) rowH = v;
    viewport = el.clientHeight;
    width = el.clientWidth;
    const ro = new ResizeObserver(() => { viewport = el.clientHeight; width = el.clientWidth; });
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
    onselect(r.track_id, false);
    // an away file can't be shown in Finder (the panel offers it only for a file that is there)
    const finder = playable(r), todo = inTodo(r);
    menu = { id: r.track_id, x: e.clientX, y: e.clientY, todo, finder };
  }
  // a quality badge asks "why is this weak?": it selects its row and opens the details (a double-click on it doesn't
  // also play: the badge is a button of its own)
  function badge(e: MouseEvent, id: string) {
    e.stopPropagation();
    onselect(id);
    ondetails();
  }
  function pick(fn: (id: string) => void) {
    const id = menu?.id;
    menu = null;
    if (id) fn(id);
  }
</script>

{#snippet columns()}
  <div class="tr head" role="row" bind:this={root} style:grid-template-columns={grid}>
    <SortHeader label={LABEL.title} sorted={sorted('title')} onsort={() => onsort('title')} test="sort-title" />
    <SortHeader label={LABEL.artist} sorted={sorted('artist')} onsort={() => onsort('artist')} test="sort-artist" />
    {#each extra as c (c)}
      <SortHeader label={LABEL[c]} align={c === 'length' ? 'end' : 'start'} sorted={sorted(c)} onsort={() => onsort(c)}
        test="sort-{c}" />
    {/each}
    <SortHeader label={LABEL.quality} sorted={sorted('quality')} onsort={() => onsort('quality')} test="sort-quality" />
    <span class="tip"><InfoTip label="Keys and clicks" data-test="library-keys">Click a header to sort, again to turn it
      round. A click or ↑ ↓ selects a row and shows its details, unless you hid them. Double-click, Enter or the cover
      plays. ⌘I shows or hides the details; a quality badge shows them. Right-click: Show details, Show in Finder, Open
      in to-do.</InfoTip></span>
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
      <div class="tr" style:grid-template-columns={grid} class:sel={r.track_id === selected} class:off={rowOff(r) || !!away} role="row"
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
        {#each extra as c (c)}
          {#if c === 'length'}<span class="td num">{duration(r.duration_s)}</span>
          {:else}
            {@const place = folderCell(r, view)}
            <span class="td cut sub" class:quiet={!place || (view === 'all' && rowOff(r))} use:tip={place
              ? { text: place, cut: true } : null}>{place ?? '–'}</span>
          {/if}
        {/each}
        <span class="td">{#if away}<AwayTag state={away} test="away-{r.track_id}" />{:else}<button type="button"
          class="qbtn" tabindex="-1" use:tip={'Show details'} onclick={(e) => badge(e, r.track_id)}
          ondblclick={(e) => e.stopPropagation()} data-test="badge-{r.track_id}"><QualityBadge quality={r.quality}
          label={r.quality_label} checked={r.sound_checked} /></button>{/if}</span>
        <span class="td slot">{#if r.upgrade_ready}<Badge tone="lossless" text="UPGRADE" />{/if}</span>
      </div>
    {/each}
    <div class="spacer" aria-hidden="true" data-test="spacer-below" style:height="{(rows.length - slice.end) * rowH}px"></div>
  {/if}
</Surface>

{#if menu}
  <ContextMenu x={menu.x} y={menu.y} test="library-context-menu" onclose={() => (menu = null)}
    items={[{ label: 'Show details', test: 'menu-details', onpick: () => pick(() => ondetails()) },
      ...(menu.finder ? [{ label: 'Show in Finder', onpick: () => pick(onfinder) }] : []),
      ...(menu.todo ? [{ label: 'Open in to-do', test: 'menu-todo', onpick: () => pick(ontodo) }] : [])]} />
{/if}

<style>
  /* the columns belong to the table (gridColumns): cover + track · artist · optional · quality · UPGRADE slot. */
  .tr {
    display: grid; column-gap: var(--s-3); align-items: center; height: var(--h-row); padding: 0 var(--s-4);
    min-width: 0; color: var(--text); font-size: var(--fs-body); cursor: default;
    transition: background var(--t-hover) var(--ease);
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
  .sk { padding: var(--s-3) var(--s-4); }
  /* the quality badge is a button (it opens the details): no box of its own, a faint wash of the badge under the
     pointer says it can be clicked; it highlights, it doesn't shrink (a badge in a row) */
  .qbtn { display: inline-flex; padding: 0; border: 0; background: none; border-radius: var(--r-badge);
    cursor: default; transition: background var(--t-hover) var(--ease); }
  .qbtn:hover { background: var(--ctl-hover); }
  .qbtn:active { transform: none; background: var(--ctl-press); }
</style>
