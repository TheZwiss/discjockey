<script lang="ts">
  // The browser column (plan library stage 5 A5, D4, I7; notes N2–N4, N9, N10, N13, N15): Library's collections beside
  // the rail, in the frame's material (Sidebar.svelte places it, moves it and sizes it). On top the filter field
  // ("Filter playlists, folders", the ⌘K cap), centred on the page header's row; under it one scroller: All tracks and
  // Not in a playlist without a head, then the sections whose heads fold and stick to the list's top and foot, solid
  // and square (`ListSection on="chrome" stick="both"`): Playlists (playlists.txt order, the download priority, or
  // A–Z by the head's toggle; a switched-off one in place at half strength; the service's own logo) and Folders (the
  // Library folders no playlist uses). Step B puts Favourites above Playlists. Every row is one line; a name that
  // doesn't fit ends in "…", and every collection row has a Tip with its words (I7).
  //
  // The filter (browserModel.ts): typing lists only the names that match, each once, in its own section (folded ones
  // open), the matching letters bold; one row carries the orange wash, the one Enter opens (the first match; ↑ ↓ move
  // it), and the last row hands the text to the track search ("Search tracks for “…”" ↵: All tracks with the text in
  // its search, `#/library?q=`). No motion: the list is rebuilt on each key. Esc clears and leaves the field (an open
  // Tip takes the first Esc). ⌘K anywhere asks for the field (`filterFocus`); the column answers once it stands.
  // Opening a collection (a click, Enter, the route) scrolls its row into view, whole beside the stuck heads.
  import { tick } from 'svelte';
  import { get } from 'svelte/store';
  import { hub } from '../stores/hub';
  import { route, link, go } from '../router';
  import { browserClosed, filterFocus, playlistsAz } from '../stores/chrome';
  import { Button, ListSection, SearchField, ServiceMark, tip } from '../components';
  import {
    HANDOFF, browserList, currentKey, highlightOf, moveHighlight, rowByKey, sortTip, toggleClosed,
    type BrowserRow, type Match,
  } from './browserModel';

  let query = $state('');
  /** the highlight the arrow keys moved to (null: the first match) */
  let moved = $state<string | null>(null);
  let input: HTMLInputElement | undefined = $state();
  let scroller: HTMLDivElement | undefined = $state();

  const side = $derived($hub.sidebar);
  const list = $derived(browserList({ side, query, az: $playlistsAz, closed: $browserClosed }));
  const filtering = $derived(list.targets.length > 0);
  const hi = $derived(highlightOf(list.targets, moved));
  const at = $derived(currentKey(side, $route.name === 'library' ? ($route.params.folder ?? null) : undefined));

  // a new text starts the highlight over at the first match
  let lastQuery = '';
  $effect.pre(() => {
    if (query !== lastQuery) { lastQuery = query; moved = null; }
  });

  function clear() {
    query = '';
    moved = null;
  }
  /** Opens a row (a click goes through its link; Enter through here). The filter clears; the field lets go, except
   *  for the hand-off, where the page's track search takes the focus. */
  function opened(r: BrowserRow) {
    clear();
    if (r.kind !== 'handoff') input?.blur();
  }
  function enter(r: BrowserRow) {
    opened(r);
    void go(r.href);
  }

  function keydown(e: KeyboardEvent) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!filtering) return;
      e.preventDefault();
      moved = moveHighlight(list.targets, hi, e.key === 'ArrowDown' ? 1 : -1);
      void tick().then(() => reveal(moved));
    } else if (e.key === 'Enter') {
      const r = hi ? rowByKey(list, hi) : null;
      if (!r) return;
      e.preventDefault();
      enter(r);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      clear();
      input?.blur();
    }
  }

  // ⌘K: each new request focuses the field and selects its text, once the column stands (into Library it is still
  // inert for a frame or two while the chrome waits for the page's first frame; Sidebar.svelte's motion)
  let seenFocus = get(filterFocus);
  $effect(() => {
    const n = $filterFocus;
    if (n === seenFocus) return;
    seenFocus = n;
    let frames = 0;
    let raf = 0;
    const tryFocus = () => {
      raf = 0;
      if (input && !input.closest('[inert]')) {
        input.focus();
        input.select();
        return;
      }
      if (++frames < 30) raf = requestAnimationFrame(tryFocus);
    };
    tryFocus();
    return () => cancelAnimationFrame(raf);
  });

  /** Scrolls a row whole into the list's view, beside the stuck heads (their height is each row's scroll margin), and
   *  only the list: the chrome around it never scrolls. */
  function reveal(key: string | null) {
    if (!key || !scroller) return;
    const el = scroller.querySelector<HTMLElement>(`[data-key="${CSS.escape(key)}"]`);
    if (!el) return;
    const r = el.getBoundingClientRect();
    const s = scroller.getBoundingClientRect();
    const cs = getComputedStyle(el);
    const top = r.top - (parseFloat(cs.scrollMarginTop) || 0);
    const bottom = r.bottom + (parseFloat(cs.scrollMarginBottom) || 0);
    if (top < s.top) scroller.scrollTop += top - s.top;
    else if (bottom > s.bottom) scroller.scrollTop += bottom - s.bottom;
  }
  // the collection on screen: its row comes into view (a click, Enter, ♫, a link from another page, a folded section
  // opened); not while filtering, where the highlight leads
  $effect(() => {
    const k = at;
    void list;
    if (!k || filtering) return;
    void tick().then(() => reveal(k));
  });

  function fold(key: string) {
    browserClosed.update((c) => toggleClosed(c, key));
  }
  const parts = (name: string, m: Match): [string, string, string] | null =>
    m ? [name.slice(0, m[0]), name.slice(m[0], m[1]), name.slice(m[1])] : null;
</script>

{#snippet name(text: string, m: Match)}
  {@const p = parts(text, m)}
  <span class="t">{#if p}{p[0]}<b class="hl">{p[1]}</b>{p[2]}{:else}{text}{/if}</span>
{/snippet}

<div class="col" data-test="browser">
  <div class="find">
    <SearchField bind:value={query} bind:input placeholder="Filter playlists, folders" shortcut="cmd+k" fill
      onkeydown={keydown} test="browser-filter" />
  </div>

  <div class="list" bind:this={scroller} data-test="browser-list">
    {#each list.views as v (v.key)}
      <a class="row" class:on={at === v.key} href={v.href} use:link onclick={() => opened(v)} data-key={v.key}
        aria-current={at === v.key ? 'page' : undefined}
        data-test={v.key === 'view:all' ? 'browser-all' : 'browser-unlisted'}>
        <span class="t">{v.name}</span><span class="n num">{v.count}</span>
      </a>
    {/each}

    {#each list.sections as s (s.key)}
      <ListSection label={s.label} summary={s.count === null ? undefined : String(s.count)} on="chrome" stick="both"
        fold={{ open: s.open, toggle: () => fold(s.key), disabled: !s.foldable }} test="browser-section-{s.key}">
        {#if s.key === 'playlists'}
          <span class="sort" use:tip={sortTip($playlistsAz)}>
            <Button variant="icon" size="xs" pressed={$playlistsAz} aria-label="Order A to Z"
              onclick={() => playlistsAz.update((v) => !v)} data-test="browser-az">
              <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M1.5 3h9M1.5 6h6.5M1.5 9h4" /></svg>
            </Button>
          </span>
        {/if}
      </ListSection>
      {#if s.open}
        {#each s.rows as r (r.key)}
          <a class="row" class:on={at === r.key} class:kb={hi === r.key} class:off={r.kind === 'playlist' && !r.enabled}
            href={r.href} use:link use:tip={r.tip} onclick={() => opened(r)} data-key={r.key}
            aria-current={at === r.key ? 'page' : undefined} data-test="browser-row">
            <span class="lead">
              {#if r.kind === 'playlist'}
                {#if r.service}<ServiceMark service={r.service} />{/if}
              {:else}
                <svg class="folder" viewBox="0 0 14 12" aria-hidden="true"><path
                  d="M1.2 2.2c0-.6.4-1 1-1h3.1l1.4 1.5h5.1c.6 0 1 .4 1 1v6.9c0 .6-.4 1-1 1H2.2c-.6 0-1-.4-1-1z" /></svg>
              {/if}
            </span>
            {@render name(r.name, r.match)}
            <span class="n num">{r.count}</span>
          </a>
        {/each}
      {/if}
    {/each}

    {#if list.handoff}
      {@const h = list.handoff}
      <a class="row handoff" class:kb={hi === HANDOFF} class:alone={!list.sections.length} href={h.href} use:link
        use:tip={h.tip} onclick={() => opened(h)} data-key={HANDOFF} data-test="browser-handoff">
        <span class="lead"><svg class="mag" viewBox="0 0 12 12" aria-hidden="true"><circle cx="5.2" cy="5.2" r="3.9" /><path
          d="M8.1 8.1 11 11" /></svg></span>
        <span class="t">Search tracks for “{h.text}”</span>
        <span class="n ret" aria-hidden="true">↵</span>
      </a>
    {/if}
  </div>
</div>

<style>
  /* the 10 px under the list belong to the column, not the scroller: a head stuck at the list's foot is its last
     pixel, and no row shows below it */
  .col { flex: 1; min-height: 0; display: flex; flex-direction: column; padding-bottom: 10px; }
  .find { flex: none; padding: 0 var(--s-2) 6px; }
  /* one scroller for the rows and their heads; no scrollbar of its own (the column is chrome, the stuck heads and the
     rows passing under them say there is more) */
  .list { position: relative; flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 2px;
    overflow-y: auto; padding: 0 var(--s-2); scrollbar-width: none; }
  .list::-webkit-scrollbar { display: none; }
  /* a section's head stands a little apart from the rows above it */
  .list > :global([data-list-section]) { margin-top: 10px; }

  .row { display: flex; align-items: center; gap: 9px; height: var(--h-ctl); flex-shrink: 0; padding: 0 var(--s-2);
    color: var(--text-nav); border-radius: var(--r-nav); text-decoration: none; white-space: nowrap; min-width: 0; }
  .row:hover { color: var(--text); background-color: var(--ctl-hover); text-decoration: none; }
  .row:not(.on):hover { transition: background-color var(--t-hover) var(--ease), color var(--t-hover) var(--ease); }
  /* the collection on screen: the sidebar's pill, at once (a background image never transitions) */
  .row.on { color: var(--text-strong); background-image: linear-gradient(var(--nav-on-bg), var(--nav-on-bg)); }
  .row:active:not(.on) { background-color: var(--ctl-press); transition: none; }
  /* while filtering, the one row Enter opens: the orange wash (on the hand-off with ↵) */
  .row.kb { color: var(--text-strong); background-color: var(--accent-wash-strong); }
  /* a switched-off playlist: the one dim in the column, the whole row with its logo */
  .row.off { opacity: var(--dim-locked); }
  .lead { width: 14px; height: 14px; flex: none; display: grid; place-items: center; }
  .folder { width: 14px; height: 12px; fill: none; stroke: currentColor; stroke-width: 1.2; stroke-linejoin: round; opacity: .8; }
  .on .folder { opacity: 1; }
  .t { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .hl { color: var(--text-strong); font-weight: var(--fw-semi); }
  .n { flex: none; min-width: 14px; margin-left: var(--s-1); text-align: right; color: var(--text-label);
    font-size: var(--fs-label); }
  .on .n, .kb .n { color: var(--text-muted); }

  .handoff { margin-top: 6px; }
  .handoff.alone { margin-top: 0; }
  .mag { width: 12px; height: 12px; fill: none; stroke: currentColor; stroke-width: 1.3; stroke-linecap: round;
    color: var(--text-muted); }
  .ret { font-size: var(--fs-small); visibility: hidden; }
  .handoff.kb .ret { visibility: visible; }

  .sort { display: inline-flex; }
  .sort :global(svg) { fill: none; stroke: currentColor; stroke-width: 1.3; stroke-linecap: round; }
</style>
