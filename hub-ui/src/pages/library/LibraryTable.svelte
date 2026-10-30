<script lang="ts">
  // The track table (design system mockup design-system/library-layout.html): one `Surface kind="table" grow` that
  // fills the list area up to its rows and scrolls inside, its column head (`SortHeader`s and the ⓘ with the keys)
  // fixed above the rows. Columns: a playlist's `#` · cover + track · artist · the optional ones · quality · a fixed
  // slot for UPGRADE (To-do's), so every badge ends at one x. The optional columns follow the table's own width, never
  // the window's (plan library stage 5 D10, notes N6): Folder or Subfolder, Playlist, Length, each by the table's kind;
  // they go in the reverse order. The rows' width is measured (a ResizeObserver, which reports before the frame is
  // painted, so a column never shows for a frame at the wrong width) and `columnsAt` picks the columns, so the
  // thresholds live in one tested place; the head and the rows share the one grid. A playlist's view lists its songs,
  // then, under the `Also in this folder` section head, the other files of its folder (`also`, D9): one table, one
  // grid. Above 300 lines only the visible ones are rendered (windowSlice). A click or ↑ / ↓ picks a row (`onselect`;
  // the page opens the details unless the user hid them by hand); a click on a row's quality badge opens the details
  // even then ("why is this weak?", N5). Enter plays, right-click selects without picking (`onselect(id, false)`) and
  // opens the shared menu; the cover is the row's play button (▶ while the row is hovered, ❚❚ while it plays).
  // Row signals (D6): a dimmed lead is a song that left every playlist, a file that is away (an `AwayTag` in the
  // quality column says why), or a playlist song without a file (a dashed empty cover; "Waiting" in muted words or the
  // red NOT FOUND badge in the quality column). Only a row whose file is there plays.
  // `playlistColumn` false: no row of the collection's unfiltered answer is in a playlist, so the Playlist column would
  // say "–" on every row and only take room from the cut titles (D10 amended); the page holds it while a search or
  // filter is on.
  import {
    AwayTag, Badge, ContextMenu, Cover, InfoTip, ListLine, ListSection, MiddleText, QualityBadge, Skeleton, SortHeader, Surface, tip,
  } from '$lib/components';
  import { artistTitle, duration } from '$lib/format';
  import type { LibraryRow, LibrarySort } from '$lib/bridge/types';
  import {
    NOT_FOUND_HIDDEN_TIP, NOT_FOUND_TIP, NOT_FOUND_WORD, columnsAt, folderCell, gridColumns, lineTop, moveSelection,
    playable, playlistCell, rowAway, rowDim, rowInTodo, rowTitleTip, centerLine, keepLine, selectedIndex,
    sortColumns, sortState, subfolderCell, tableLines, titleNote, waitWords, windowSlice, type OptionalColumn, type SortColumn,
    type TableKind,
  } from './libraryModel';

  let { rows, also = null, alsoHint = '', emptyLine = null, loading = false, kind = 'library', subfolders = false,
    playlistColumn = true, off = false, sort,
    selected, playing = null, onsort, onselect, onplay, onfinder, ontodo, ondetails }: {
    rows: LibraryRow[];
    /** a playlist's other files of its folder, under their own section head (null elsewhere) */
    also?: LibraryRow[] | null; alsoHint?: string;
    /** the playlist's own part has no rows but `also` has: what the table says above the section */
    emptyLine?: string | null;
    loading?: boolean;
    /** which collection: its optional columns (libraryModel.optionalColumns) and its sortable heads */
    kind?: TableKind;
    /** a watched folder or crate with crates inside it: the Subfolder column */
    subfolders?: boolean;
    /** whether the Playlist column can say anything (libraryModel.columnsAt's `playlists`) */
    playlistColumn?: boolean;
    /** a switched-off playlist: its songs without a file wait for nothing (libraryModel.waitWords) */
    off?: boolean;
    sort: LibrarySort; selected: string | null;
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

  const LABEL: Record<SortColumn | OptionalColumn, string> = { order: '#', title: 'Track', artist: 'Artist',
    folder: 'Folder', subfolder: 'Subfolder', playlist: 'Playlist', length: 'Length', quality: 'Quality' };

  let root = $state<HTMLElement | undefined>();
  let scroller = $state<HTMLElement | null>(null);
  let scrollTop = $state(0);
  let viewport = $state(400);
  let rowH = $state(38);
  let otherH = $state(32);
  let hovered = $state<string | null>(null);
  let centred = false;
  let menu: { id: string; x: number; y: number; todo: boolean; finder: boolean } | null = $state(null);
  // the rows' own width (the `list` container's): what the optional columns follow
  let width = $state(0);

  const playlist = $derived(kind === 'playlist');
  const viewOf = $derived(kind === 'library' || kind === 'watched' || kind === 'crate' ? 'folder' as const : kind);
  const sortable = $derived(new Set<string>(sortColumns(viewOf)));
  const st = $derived(sortState(sort));
  const extra = $derived(columnsAt(kind, width, subfolders, playlistColumn));
  const grid = $derived(gridColumns(extra, playlist));
  const lines = $derived(tableLines(rows, also, emptyLine));
  const wait = $derived(waitWords(off));
  // what ↑ ↓ walk and a selection is found in: the rows, the section's included, in the table's order
  const walk = $derived(lines.flatMap((l) => (l.kind === 'row' ? [l.row] : [])));
  const slice = $derived(windowSlice(scrollTop, viewport, rowH, lines.length));
  const visible = $derived(lines.slice(slice.start, slice.end).map((l, i) => ({ l, i: slice.start + i })));
  const above = $derived(lineTop(lines, slice.start, rowH, otherH));
  const below = $derived(lineTop(lines, lines.length, rowH, otherH) - lineTop(lines, slice.end, rowH, otherH));
  const sorted = (c: SortColumn) => (st.column === c ? (st.desc ? 'desc' : 'asc') : null);

  $effect(() => {
    const el = scroller;
    if (!el || !root) return;
    const cs = getComputedStyle(root);
    const v = parseFloat(cs.getPropertyValue('--h-row'));
    if (v > 0) rowH = v;
    const h = parseFloat(cs.getPropertyValue('--h-section'));
    if (h > 0) otherH = h;
    viewport = el.clientHeight;
    width = el.clientWidth;
    const ro = new ResizeObserver(() => { viewport = el.clientHeight; width = el.clientWidth; });
    ro.observe(el);
    const onScroll = () => { scrollTop = el.scrollTop; menu = null; };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => { ro.disconnect(); el.removeEventListener('scroll', onScroll); };
  });

  // The selected row stays in view (first load with ?track=: in the middle). Its top is measured in lines (rows and
  // the section head have their own heights); a row of the section keeps clear of its head, which may be stuck.
  $effect(() => {
    const i = lines.findIndex((l) => l.kind === 'row' && l.row.track_id === selected);
    const el = scroller;
    if (!el || !lines.length) return;
    if (i < 0) { centred = true; return; }
    const line = lines[i];
    const top = lineTop(lines, i, rowH, otherH);
    const clear = line.kind === 'row' && line.also ? otherH : 0;
    const next = centred ? keepLine(el.scrollTop, el.clientHeight, top, rowH, clear) : centerLine(el.clientHeight, top, rowH);
    centred = true;
    if (next !== el.scrollTop) { el.scrollTop = next; scrollTop = next; }
  });

  function key(e: KeyboardEvent) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const id = moveSelection(walk, selected, e.key === 'ArrowDown' ? 1 : -1);
      if (id) onselect(id);
    } else if (e.key === 'Enter' && selected) {
      e.preventDefault();
      const r = walk[selectedIndex(walk, selected)];
      if (r && playable(r)) onplay(selected);   // an away row's file isn't there, a waiting song has none: nothing to try
    } else if (e.key === 'Escape' && menu) {
      menu = null;
    }
  }
  function context(e: MouseEvent, r: LibraryRow) {
    e.preventDefault();
    onselect(r.track_id, false);
    // a file that isn't there can't be shown in Finder (the panel offers it only for a file that is there)
    menu = { id: r.track_id, x: e.clientX, y: e.clientY, todo: rowInTodo(r), finder: playable(r) };
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

{#snippet head(c: SortColumn | OptionalColumn)}
  {#if sortable.has(c)}
    <SortHeader label={LABEL[c]} align={c === 'length' || c === 'order' ? 'end' : 'start'} sorted={sorted(c as SortColumn)}
      onsort={() => onsort(c as SortColumn)} test="sort-{c}" />
  {:else}
    <!-- the engine has no sort by this column: its name, not a button -->
    <SortHeader label={LABEL[c]} test="head-{c}" />
  {/if}
{/snippet}

{#snippet columns()}
  <div class="tr head" role="row" bind:this={root} style:grid-template-columns={grid}>
    {#if playlist}{@render head('order')}{/if}
    {@render head('title')}
    {@render head('artist')}
    {#each extra as c (c)}{@render head(c)}{/each}
    {@render head('quality')}
    <span class="tip"><InfoTip label="Keys and clicks" data-test="library-keys">Click a header to sort, again to turn it
      round. A click or ↑ ↓ selects a row and shows its details, unless you hid them. Double-click, Enter or the cover
      plays. ⌘I shows or hides the details; a quality badge shows them. Right-click: Show details, Show in Finder, Open
      in to-do.</InfoTip></span>
  </div>
{/snippet}

{#snippet place(text: string | null)}
  {#if text}<span class="td sub"><MiddleText {text} sep="›" /></span>{:else}<span class="td sub quiet">–</span>{/if}
{/snippet}

<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<Surface kind="table" grow={{ rows: Math.max(1, lines.length) }} {columns} bind:scroller role="grid" aria-label="Tracks"
  tabindex={0} onkeydown={key} data-test="library-table">
  {#if loading && !lines.length}
    <div class="sk"><Skeleton lines={8} height={14} gap={24} /></div>
  {:else}
    <div class="spacer" aria-hidden="true" data-test="spacer-above" style:height="{above}px"></div>
    {#each visible as { l, i } (l.kind === 'row' ? l.row.track_id : `${l.kind}-${i}`)}
      {#if l.kind === 'section'}
        <ListSection label="Also in this folder" summary={String(also?.length ?? 0)} hint={alsoHint} test="library-also" />
      {:else if l.kind === 'empty'}
        <ListLine text={l.text} test="library-main-empty" />
      {:else}
        {@const r = l.row}
        {@const away = rowAway(r)}
        {@const noFile = r.file_state === 'no_file'}
        {@const note = titleNote(r, kind)}
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <div class="tr" style:grid-template-columns={grid} class:sel={r.track_id === selected} class:off={rowDim(r)} role="row"
          tabindex="-1" aria-selected={r.track_id === selected} data-test="row-{r.track_id}" data-away={away}
          data-wait={r.wait ?? undefined}
          onclick={() => onselect(r.track_id)} ondblclick={() => { if (playable(r)) onplay(r.track_id); }}
          oncontextmenu={(e) => context(e, r)}
          onpointerenter={() => (hovered = r.track_id)} onpointerleave={() => { if (hovered === r.track_id) hovered = null; }}>
          {#if playlist}<span class="td num pos">{r.position ?? ''}</span>{/if}
          <span class="td title" title={note ? `${rowTitleTip(r, artistTitle(r.artist, r.title))}\n${note}`
            : rowTitleTip(r, artistTitle(r.artist, r.title))}>
            <span class="cov" class:nofile={noFile}><Cover url={r.cover_url} seed={r.track_id} size={22} playing={playing === r.track_id}
              hint={hovered === r.track_id} name={artistTitle(r.artist, r.title)} empty={noFile}
              onplay={playable(r) ? () => onplay(r.track_id) : undefined} /></span>
            {#if note}<span class="nm"><span class="cut name">{r.title}</span><span class="cut note"
              data-test="note-{r.track_id}">{note}</span></span>
            {:else}<span class="cut name">{r.title}</span>{/if}
          </span>
          <span class="td cut sub">{r.artist}</span>
          {#each extra as c (c)}
            {#if c === 'length'}<span class="td num">{noFile && !r.duration_s ? '–' : duration(r.duration_s)}</span>
            {:else if c === 'folder'}{@render place(folderCell(r))}
            {:else if c === 'subfolder'}{@render place(subfolderCell(r))}
            {:else}
              {@const pl = playlistCell(r)}
              {#if pl}<span class="td"><Badge tone="muted" text={pl.name} more={pl.more} tip={pl.tip} /></span>
              {:else}<span class="td sub quiet">–</span>{/if}
            {/if}
          {/each}
          <span class="td">{#if noFile}{#if r.wait === 'not_found'}<Badge tone="missing" text={NOT_FOUND_WORD} tip={r.hidden ? NOT_FOUND_HIDDEN_TIP : NOT_FOUND_TIP}
              test="wait-{r.track_id}" />{:else}<Badge tone="quiet" text={wait.word} tip={wait.tip} test="wait-{r.track_id}" />{/if}
            {:else if away}<AwayTag state={away} test="away-{r.track_id}" />{:else}<button type="button"
            class="qbtn" tabindex="-1" use:tip={'Show details'} onclick={(e) => badge(e, r.track_id)}
            ondblclick={(e) => e.stopPropagation()} data-test="badge-{r.track_id}"><QualityBadge quality={r.quality}
            label={r.quality_label} checked={r.sound_checked} /></button>{/if}</span>
          <span class="td slot">{#if r.upgrade_ready}<Badge tone="lossless" text="UPGRADE" />{/if}</span>
        </div>
      {/if}
    {/each}
    <div class="spacer" aria-hidden="true" data-test="spacer-below" style:height="{below}px"></div>
  {/if}
</Surface>

{#if menu}
  <ContextMenu x={menu.x} y={menu.y} test="library-context-menu" onclose={() => (menu = null)}
    items={[{ label: 'Show details', test: 'menu-details', onpick: () => pick(() => ondetails()) },
      ...(menu.finder ? [{ label: 'Show in Finder', onpick: () => pick(onfinder) }] : []),
      ...(menu.todo ? [{ label: 'Open in to-do', test: 'menu-todo', onpick: () => pick(ontodo) }] : [])]} />
{/if}

<style>
  /* the columns belong to the table (gridColumns): # · cover + track · artist · optional · quality · UPGRADE slot. */
  .tr {
    display: grid; column-gap: var(--s-3); align-items: center; height: var(--h-row); padding: 0 var(--s-4);
    min-width: 0; color: var(--text); font-size: var(--fs-body); cursor: default;
    transition: background var(--t-hover) var(--ease);
  }
  .tr.head { height: var(--h-list-row); }
  /* a row's rule is its top edge; after the section head the head is the line above the first row of its files */
  .tr:not(.head) + .tr, :global([data-list-section]) + .tr { border-top: var(--bw) solid var(--line-soft); }
  .tr:not(.head):hover { background: var(--ctl-hover); }
  .tr.sel, .tr.sel:hover { background: var(--nav-on-bg); }
  .tr.off .name { color: var(--text-muted); }
  .tr.off .cov { opacity: var(--dim-cover); }
  /* the dashed empty cover is already the faint thing: dimmed again it would vanish */
  .tr.off .cov.nofile { opacity: 1; }
  .td { min-width: 0; }
  /* the title, and after it a playlist row's "in …" note, which gives way first and whole: the title keeps its
     width (up to all of it) and the note takes what is left, so the title is cut only once the note is gone */
  .title { display: flex; align-items: center; gap: var(--s-2); }
  .nm { display: flex; align-items: baseline; gap: var(--s-2); flex: 1; min-width: 0; }
  .nm .name { flex: none; max-width: 100%; }
  .note { flex: 0 1 auto; min-width: 0; color: var(--text-label); font-size: var(--fs-small); }
  .cov { display: flex; flex: none; transition: opacity var(--t-state) var(--ease); }
  .cut { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sub { color: var(--text-muted); font-size: var(--fs-small); }
  .quiet { color: var(--text-label); }
  .num { justify-self: end; color: var(--text-muted); font-size: var(--fs-small); font-variant-numeric: tabular-nums; }
  .pos { color: var(--text-label); }
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
