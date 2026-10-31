<script lang="ts">
  // Library (spec §5.4; plan library stage 5 A6, notes N5–N7 and N14, mockup design-system/library-layout.html): on
  // ListPanelFrame (`wide`, the table gets up to 1200 px) in inspector mode. The list area: the header (title, the
  // subtitle's parts that drop whole, the track search, the details toggle), the collection at a glance as a 72 px
  // SummaryStrip, the quality filter as one Segmented, then the tracks as one table Surface that fills the height and
  // scrolls in place (LibraryTable). No docked panel: the docked panel squeezed the table, so the selected track's
  // details (TrackDetails, the same cards as To-do's, its decisions decided here as there) are an inspector that comes when wanted: picking a track (a
  // click, ↑ ↓) opens it, it follows the selection and stays open (remembered, closed at first). It never stands
  // empty: with no track selected, or the selected one off the table (filtered or searched away, gone, an empty
  // folder), it closes and the toggle waits, disabled, until there is a track again (`detailsStand`). Closing it with the
  // toggle or ⌘I hides it by hand: picks then only select, and the toggle shows the choice in words ("Show details",
  // a dashed outline, the glyph struck through) until the user opens the details by hand (the toggle, ⌘I, a quality
  // badge, the menu's Show details); the rules are `detailsAfter` in stores/chrome.ts. A right-click selects without
  // opening (the menu is what it asks for). A double-click or Enter plays. Below 1240 px the open inspector steps the
  // browser column back behind the rail (the chrome's job, stores/chrome.ts).
  // The views (plan library stage 5, B6): a playlist lists its songs in its order (`#`), a song without a file too
  // (Waiting / NOT FOUND, its details from the row itself), then the other files of its folder in an `Also in this
  // folder` section; a folder view has its own columns (Subfolder, Playlist). Each view kind remembers its own sort.
  // The empty states are worded by the view (`pageEmpty`); a playlist never read has Read playlists in the header's
  // read-status slot (its one place, design language §4); a watched folder with too many crates for the sidebar links
  // to Settings' list, where the user picks the ones to show.
  import { untrack, type ComponentProps } from 'svelte';
  import {
    Button, EmptyState, PageHeader, ProblemCard, SearchField, Segmented, Skeleton, Spectrum, SummaryStrip, Surface,
  } from '$lib/components';
  import { decisionFor } from '$lib/decisions';
  import { ListPanelFrame } from '$lib/frames';
  import { api } from '$lib/bridge/client';
  import type {
    Fail, Library, LibraryFilter, LibrarySort, LibraryView, ProblemKind, TodoItem, TrackDetail,
  } from '$lib/bridge/types';
  import { filesVersion, hub, hubNow } from '$lib/stores/hub';
  import {
    detailsHidden, detailsShown, detailsSubject, pickTrack, showDetails, toggleInspector, trackOffTable,
  } from '$lib/stores/chrome';
  import { player } from '$lib/stores/player';
  import { listen } from '$lib/listen';
  import { toasts } from '$lib/stores/toasts';
  import { problemCopy } from '$lib/copy';
  import { getPref, setPref } from '$lib/prefs';
  import { go, libraryHref, settingsFolderHref } from '$lib/router';
  import { markReady } from '$lib/ready';
  import LibraryTable from './LibraryTable.svelte';
  import TrackDetails from './TrackDetails.svelte';
  import {
    LEGACY_SORT_KEY, LIBRARY_FILTERS, allRows, alsoHint, filterKey, hasSubfolders, heldRow, holdApplies, libraryCalls,
    nextSort, offTable, withHeld, type Hold,
    pageEmpty, playQueue, playlistColumnFor, artistColumnFor, shownSort, rowOf, segOptions, sortKey, subtitleParts, tableKind, todoHref, tooManyFor,
    viewSort, type LibraryCall,
    type SortColumn,
  } from './libraryModel';
  import { NOT_IN_PLAYLIST } from '$lib/bridge/types';

  let { params, query }: { params: Record<string, string>; query: URLSearchParams } = $props();
  type Spec = ComponentProps<typeof Spectrum>['spectrum'];

  const folder = $derived(params.folder ?? null);
  // each view kind's sort: what the user chose here, else what was saved, else the kind's default
  let sorts = $state<Partial<Record<LibraryView, LibrarySort>>>({});
  const sortOf = (v: LibraryView): LibrarySort => sorts[v]
    ?? viewSort(v, getPref<string | null>(sortKey(v), null), getPref<string | null>(LEGACY_SORT_KEY, null));
  let filter = $state<LibraryFilter>('all');
  let search = $state('');
  let q = $state('');
  let lib = $state<Library | null>(null);
  /** the route's folder param `lib` was asked for (its own `key` is the engine's spelling of it) */
  let libFor = $state<string | null>(null);
  let libError: { kind: ProblemKind; message: string } | null = $state(null);
  let loading = $state(true);
  let selected = $state<string | null>(untrack(() => query.get('track')));
  // the track just acted on in the details stays on the table and selected (libraryModel Hold, keepHeld)
  let hold = $state<Hold | null>(null);
  $effect(() => {
    const h = hold;
    if (h && (selected !== h.id || !holdApplies(h, folder, q, filter))) untrack(() => { hold = null; });
  });

  let detail = $state<TrackDetail | null>(null);
  let detailLoading = $state(false);
  let gone = $state(false);
  let detailError = $state<Fail | null>(null);
  let spectrum = $state<Spec>(null);
  let spectrumLoading = $state(false);
  let spectrumError = $state<string | null>(null);
  let upgradeSpectrum = $state<Spec>(null);
  /** the files version the current spectrum was drawn at: a replace keeps the file's name (and so its audio_url) but
   *  not its sound, so a new version draws it again (the old picture stays meanwhile) */
  let spectrumAt = -1;
  // the to-do list's items, fetched with the details: the rekordbox check a replace left and the duplicate groups
  // aren't in a track's details, and the panel decides them as To-do's does (decisionFor)
  let todoItems = $state<TodoItem[]>([]);
  let ready = false;
  let retry = $state(0);

  // folder change → its remembered filter, a fresh search
  $effect(() => {
    const f = folder;
    untrack(() => {
      const saved = getPref<string>(filterKey(f), 'all');
      filter = ((LIBRARY_FILTERS as string[]).includes(saved) ? saved : 'all') as LibraryFilter;
      search = '';
      q = '';
    });
  });
  // ?q= from the browser column's hand-off ("Search tracks for “…”", plan library stage 5 A5, notes N3): the text goes
  // into the track search at once (no debounce), over every quality, and the field takes the focus; the route then
  // drops the q, so the search is the page's own again (clearing it, a reload, Back don't bring the text back). After
  // the folder's effect above, which starts a folder with an empty search.
  const handed = $derived(query.get('q'));
  let searchInput: HTMLInputElement | undefined = $state();
  $effect(() => {
    const text = handed;
    if (text === null) return;
    untrack(() => {
      search = text;
      q = text.trim();
      filter = 'all';
      const rest = new URLSearchParams(query);
      rest.delete('q');
      const qs = rest.toString();
      void go(`${libraryHref(folder)}${qs ? `?${qs}` : ''}`, { replace: true });
      requestAnimationFrame(() => searchInput?.focus());
    });
  });
  // ?track= from outside (sidebar, other pages)
  $effect(() => {
    const t = query.get('track');
    if (t !== untrack(() => selected)) selected = t;
  });
  // 200 ms debounce for the search
  $effect(() => {
    const v = search;
    const h = setTimeout(() => { q = v.trim(); }, 200);
    return () => clearTimeout(h);
  });

  /** The first call that doesn't come back gone (a name asked as a playlist may be a Library folder); when every one
   *  does, the first one's answer (a name is a playlist's first: the words say so). Each call goes with its own view's
   *  sort, so a name asked before the sidebar is there (as a playlist, then as a folder) is answered in the right order
   *  at once. */
  async function askLibrary(calls: LibraryCall[], query: string, filt: LibraryFilter,
    order: (v: LibraryView) => LibrarySort) {
    const ask = (c: LibraryCall) => api.library(c.view, c.key, query, filt, order(c.view));
    const first = await ask(calls[0]);
    let r = first;
    for (const next of calls.slice(1)) {
      if (!r.ok || r.empty !== 'gone') break;
      r = await ask(next);
    }
    return r.ok && r.empty === 'gone' ? first : r;
  }
  // the view the page shows (before an answer: the route's first call; then the answer's own, which a name asked as
  // a playlist may turn into a folder) and so its sort. The fetch doesn't follow it: the view settles when the sidebar
  // comes (a name it lists as a Library folder flips playlist → folder), and a fetch on that flip would ask again in
  // the other sort. Each call takes its own view's sort instead (askLibrary), and a sort chosen by the user (`sorts`)
  // asks again.
  const view = $derived<LibraryView>(lib && libFor === folder ? lib.view : libraryCalls(folder, $hub.sidebar)[0].view);
  const sort = $derived(sortOf(view));
  // whether the Playlist column can say anything (libraryModel.playlistColumnFor): the collection's last answer without
  // search or filter, held while one is on so the columns don't jump; before one, the answer at hand
  let playlistHeld = $state<{ for: string | null; value: boolean; artist: boolean } | null>(null);
  let libTurn = 0;
  $effect(() => {
    const args = [folder, q, filter] as const;
    const chosen = { ...sorts };
    void $filesVersion;
    void retry;
    const turn = ++libTurn;
    untrack(() => { loading = true; });
    const order = (v: LibraryView) => chosen[v] ?? sortOf(v);
    void askLibrary(libraryCalls(args[0], hubNow().sidebar), args[1], args[2], order).then(async (r) => {
      if (turn !== libTurn) return;
      if (r.ok) r = await keepHeld(r, order);
      if (turn !== libTurn) return;
      loading = false;
      if (r.ok) {
        lib = r;
        libFor = args[0];
        if (!args[1] && args[2] === 'all') playlistHeld = { for: args[0], value: playlistColumnFor(r), artist: artistColumnFor(r) };
        libError = null;
        if (filter !== 'all' && r.chips[filter] === 0 && !q) setFilter('all');
      } else {
        libError = { kind: r.kind, message: r.message };
      }
      if (!ready) { ready = true; markReady('library'); }
    });
  });

  // the held track (Hold) on a new answer: still listed, it stays selected; a duplicate's Keep that took its row (its
  // file went, or the engine's heir renamed it) moves the selection to the track that has the kept file now. Not
  // listed (filtered away: a replace under "Upgrade ready" leaves it lossless), its row is asked from the same view
  // without filter and search, then from All tracks, and put back where it stood, so the details keep its result and
  // Undo instead of closing. Not found anywhere: the details say the track isn't here any more.
  async function keepHeld<L extends Library>(r: L, order: (v: LibraryView) => LibrarySort): Promise<L> {
    const h = hold;
    if (!holdApplies(h, folder, q, filter)) return r;
    const follow = (id: string) => { if (id !== h.id) { hold = { ...h, id }; select(id, false); } };
    const here = heldRow(allRows(r), h);
    if (here) { follow(here.track_id); return r; }
    const before = libFor === folder ? lib : null;
    for (const c of [{ view: r.view, key: r.key }, { view: 'all' as const, key: null }]) {
      const a = await api.library(c.view, c.key, '', 'all', order(c.view));
      if (!a.ok) continue;
      const row = heldRow(allRows(a), h);
      if (row) { follow(row.track_id); return withHeld(r, row, before, h.id); }
    }
    return r;
  }
  function acted(keep: string[] | null) {
    if (selected) hold = { id: selected, keep, folder, q, filter };
  }

  let trackTurn = 0;
  let trackRetry = $state(0);
  // the selected row when it is a song without a file: its details come from the row (the engine may not know it yet)
  const selRow = $derived(rowOf(lib, selected));
  const noFileRow = $derived(selRow?.file_state === 'no_file' ? selRow : null);
  // a song still waiting for its file: nothing to ask (its details are the row's; a song only just read isn't one the
  // engine's track() knows)
  const skipTrack = $derived(noFileRow?.wait === 'waiting');
  $effect(() => {
    const id = selected;
    const skip = skipTrack;
    const version = $filesVersion;
    void trackRetry;
    const turn = ++trackTurn;
    untrack(() => {
      gone = false;
      detailError = null;
      if (!id || skip) { detail = null; detailLoading = false; return; }
      if (detail?.track_id !== id) { detail = null; spectrum = null; upgradeSpectrum = null; }
      void loadTrack(id, turn, version);
    });
  });

  // one to-do read per files version (every finished job bumps it), shared by the picks in between: ↑ ↓ through the
  // table asks for each track's details, not for the whole list again; hidden tracks too (their decisions are here)
  let todoAsk: { version: number; items: Promise<TodoItem[]> } | null = null;
  function todoAt(version: number): Promise<TodoItem[]> {
    if (todoAsk?.version !== version) {
      todoAsk = { version, items: api.todo('all', true).then((r) => (r.ok ? r.groups.flatMap((g) => g.items) : todoItems)) };
    }
    return todoAsk.items;
  }

  async function loadTrack(id: string, turn: number, version: number) {
    detailLoading = true;
    // together, so the panel never shows the details of after a job beside the to-do list of before it
    const [r, items] = await Promise.all([api.track(id), todoAt(version)]);
    if (turn !== trackTurn) return;
    detailLoading = false;
    if (!r.ok) {
      if (r.kind === 'refused' || r.kind === 'changed') gone = true;
      else detailError = r;
      return;
    }
    const t = r.track;
    const fresh = detail?.track_id !== t.track_id || detail?.audio_url !== t.audio_url;
    detail = t;
    todoItems = items;
    if (!t.audio_url) { spectrum = null; return; }
    if (fresh || !spectrum || spectrumAt !== version) {
      spectrumAt = version;
      spectrumLoading = true;
      spectrumError = null;
      const s = await api.spectrum(id, 'current');
      if (turn !== trackTurn) return;
      spectrumLoading = false;
      if (s.ok) spectrum = s.spectrum;
      else { spectrum = null; spectrumError = s.message; }
    }
    upgradeSpectrum = null;
    if (t.upgrade) {
      const s = await api.spectrum(id, 'upgrade');
      if (turn === trackTurn && s.ok) upgradeSpectrum = s.spectrum;
    }
  }

  function setFilter(f: LibraryFilter) {
    filter = f;
    setPref(filterKey(folder), f);
  }
  function onsort(c: SortColumn) {
    const next = nextSort(shown, c);
    sorts = { ...sorts, [view]: next };
    setPref(sortKey(view), next);
  }
  // `pick`: the user chose this track in the table (a click, ↑ ↓), which opens the details unless hidden by hand
  function select(id: string, pick = true) {
    if (pick) pickTrack();
    selected = id;
    void go(`${libraryHref(folder)}?track=${encodeURIComponent(id)}`, { replace: true });
  }
  // ▶ starts the folder as shown (filter, search and sort applied) as the queue, from this track: a playlist's songs,
  // then the other files of its folder, as the table lists them. The rows come sorted from the engine
  // (`api.library(…, sort)`), and the table shows them in that order.
  function play(id: string) {
    const label = (lib?.title ?? 'All tracks') + (q ? ` · “${q}”` : '');
    // the queue holds the rows whose file is there: ⏭ never lands on a file on an ejected drive or a song not downloaded
    if (!lib || !listen(playQueue(lib), id, { label, href: libraryHref(folder) })) {
      toasts.show({ tone: 'problem', title: "Can't play this file." });
    }
  }
  async function finder(id: string) {
    const r = await api.show_in_finder(id, 'current');
    if (!r.ok) toasts.show({ tone: 'problem', title: problemCopy(r.kind).title, body: r.message || undefined });
  }
  function todo(id: string) {
    void go(todoHref(id));
  }
  const options = $derived(segOptions(lib?.chips, filter));
  // the header's second line: its parts in order of importance, the last dropping first when the header is narrow; a
  // read playlist's songs without a file are a part of their own after the count
  const sub = $derived(lib ? subtitleParts(lib) : undefined);
  const emptyLibrary = $derived(lib?.empty === 'empty_library');
  // a playlist or folder that isn't there any more: nothing to search and no track to show, so the header keeps only
  // the title (the empty state's All tracks is the way on)
  const viewGone = $derived(lib?.empty === 'gone');
  // what the list area says when the table has nothing (or a playlist's own part is empty beside its folder's files)
  const empty = $derived(lib ? pageEmpty(lib, q, filter) : { page: null, line: null });
  // the strip and the filter count the files the collection holds: none, nothing to sum up or to filter
  const hasFiles = $derived(!!lib && lib.summary.tracks > 0);
  // the table's kind (its columns), and whether a folder view has crates inside it (its Subfolder column)
  const kind = $derived(lib ? tableKind(lib) : 'library');
  const subfolders = $derived(!!lib && hasSubfolders(lib, $hub.sidebar));
  const neverRead = $derived(lib?.view === 'playlist' && lib.empty !== 'gone' && lib.read_at === null);
  // a watched folder with more crates than the sidebar holds: the link to Settings' list of them
  const tooMany = $derived(tooManyFor(lib, $hub.sidebar));
  const playlistColumn = $derived(!lib ? true : playlistHeld && playlistHeld.for === libFor ? playlistHeld.value
    : playlistColumnFor(lib));
  // the same for the Artist column (artistColumnFor); with it gone a sort by Artist reads as one by Track
  const artistColumn = $derived(!lib ? true : playlistHeld && playlistHeld.for === libFor ? playlistHeld.artist
    : artistColumnFor(lib));
  const shown = $derived(shownSort(sort, artistColumn));
  const decision = $derived(detail ? decisionFor(todoItems, detail) : null);
  // a duplicate's file playing in the foot links back to this track in this view
  const playSource = $derived(detail ? { label: lib?.title ?? 'All tracks',
    href: `${libraryHref(folder)}?track=${encodeURIComponent(detail.track_id)}` } : undefined);
  const pending = $derived(noFileRow ? { row: noFileRow,
    next: detail?.track_id === noFileRow.track_id ? detail.next_qobuz_check : null, off: lib?.enabled === false } : null);
  const playing = $derived($player.playing ? $player.track_id : null);
  function playOrPause(id: string) {
    if ($player.track_id === id && $player.url) player.toggle();
    else play(id);
  }
  // the details stand only with a track to show: the chrome reads the selection from the route, the page tells it when
  // that track is off the table, so ⌘I waits, nothing steps the browser back, and no inspector stands empty
  const selectedOff = $derived(offTable(lib, libFor, folder, selected));
  $effect(() => { trackOffTable.set(selectedOff); });
  $effect(() => () => trackOffTable.set(false));
  const detailsOpen = $derived($detailsShown);
  const handHidden = $derived($detailsHidden);
  // nothing to show: the toggle keeps its place and its words (hidden by hand: "Show details"), disabled, and says why
  const detailsTip = $derived(!$detailsSubject ? { text: 'Select a track to see its details', keys: '⌘I' }
    : detailsOpen ? { text: 'Hide details', keys: '⌘I' }
    : handHidden ? { text: "Hidden by you: selecting a track won't open them", keys: '⌘I' }
    : { text: 'Show details', keys: '⌘I' });
</script>

{#snippet detailsIcon()}
  <!-- the macOS inspector symbol: a window with its right-hand pane -->
  <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="2.5" width="13" height="11" rx="2.4" /><path d="M10 2.5v11" />
    <path d="M11.6 5.2h1.3M11.6 7.2h1.3M11.6 9.2h1.3" /></svg>
{/snippet}
{#snippet detailsHiddenIcon()}
  <!-- the same window, its pane empty and struck through (hidden on purpose, like eye.slash) -->
  <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="2.5" width="13" height="11" rx="2.4" /><path d="M10 2.5v11" />
    <path d="M1.8 1.6l12.4 12.8" /></svg>
{/snippet}

{#snippet main()}
  <PageHeader title={lib?.title ?? (folder === null ? 'All tracks' : folder === NOT_IN_PLAYLIST ? 'Not in a playlist' : folder)} {sub}
    readStatus={neverRead}>
    {#snippet actions()}{#if tooMany}<Button variant="link" size="sm" href={settingsFolderHref(tooMany.path)}
        tip={`${tooMany.crate_count} folders with music, too many for the sidebar: choose which to show in Settings`}
        data-test="library-show-some">Show some in the sidebar…</Button>{/if}{#if !viewGone}<SearchField bind:value={search}
      bind:input={searchInput} placeholder="Search title, artist…" shortcut="cmd+f"
      test="library-search" />{/if}{#if !emptyLibrary && !viewGone}<Button variant="icon"
        icon={handHidden ? detailsHiddenIcon : detailsIcon} pressed={detailsOpen} disabled={!$detailsSubject}
        switchedOff={handHidden ? 'Show details' : undefined}
        aria-label={detailsOpen ? 'Hide details' : 'Show details'}
        tip={detailsTip} aria-keyshortcuts="Meta+I" onclick={toggleInspector} data-test="library-details"
        data-hidden={handHidden || undefined} />{/if}{/snippet}
  </PageHeader>
  {#if libError && !lib}
    <ProblemCard kind={libError.kind} message={libError.message} onretry={() => { retry++; }} />
  {:else if !lib}
    <!-- waiting: the strip at its height with dashes, so nothing moves when the numbers come -->
    <SummaryStrip summary={null} onupgrades={() => {}} ontodo={() => {}} />
    <Surface kind="card"><Skeleton lines={8} height={18} gap={14} /></Surface>
  {:else}
    {#if libError}<ProblemCard compact kind={libError.kind} message={libError.message} />{/if}
    {#if hasFiles}
      <SummaryStrip summary={lib.summary} onupgrades={() => setFilter('upgrade_ready')} ontodo={() => void go('/todo')} />
      <Segmented {options} value={filter} onchange={setFilter} label="Quality" test="library-filter" />
    {/if}
    {#if empty.page}
      {@const e = empty.page}
      <Surface kind="card" data-test="library-empty-{e.kind}">
        <EmptyState title={e.title} body={e.body} action={e.kind === 'library' ? { label: 'Open Sync', href: '#/sync' }
          : e.kind === 'gone' ? { label: 'All tracks', href: '#/library' }
          : e.kind === 'search' ? { label: 'Clear search', onclick: () => { search = ''; q = ''; } }
          : e.kind === 'filter' ? { label: 'Show all', onclick: () => setFilter('all') } : null} />
      </Surface>
    {:else}
      <LibraryTable rows={lib.rows} also={lib.also} alsoHint={alsoHint(lib.title, neverRead)} emptyLine={empty.line} {loading} {kind}
        {subfolders} {playlistColumn} {artistColumn} off={lib.enabled === false} sort={shown} {selected} {playing} {onsort} onselect={select} onplay={playOrPause}
        onfinder={(id) => void finder(id)} ontodo={todo} ondetails={showDetails} />
    {/if}
  {/if}
{/snippet}

{#snippet panel()}
  <TrackDetails {detail} {decision} {playSource} {pending} loading={detailLoading} {gone} error={detailError} {spectrum}
    {spectrumLoading} {spectrumError} {upgradeSpectrum} onretry={() => { trackRetry++; }}
    onfinder={() => detail && void finder(detail.track_id)} ontodo={() => { const id = pending?.row.track_id ?? detail?.track_id; if (id) todo(id); }}
    onlisten={() => detail && play(detail.track_id)} onacted={acted} />
{/snippet}

<ListPanelFrame {main} panel={selected ? panel : null} emptyPanel="Select a track to see its details." wide
  panelMode="inspector" open={detailsOpen} panelLabel="Track details" />
