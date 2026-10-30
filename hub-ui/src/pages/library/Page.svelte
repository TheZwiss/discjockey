<script lang="ts">
  // Library (spec §5.4; plan library stage 5 A6, notes N5–N7 and N14, mockup design-system/library-layout.html): on
  // ListPanelFrame (`wide`, the table gets up to 1200 px) in inspector mode. The list area: the header (title, the
  // subtitle's parts that drop whole, the track search, the details toggle), the collection at a glance as a 72 px
  // SummaryStrip, the quality filter as one Segmented, then the tracks as one table Surface that fills the height and
  // scrolls in place (LibraryTable). No docked panel: the docked panel squeezed the table, so the selected track's
  // details (TrackDetails, the same cards as To-do's) are an inspector that comes when wanted: picking a track (a
  // click, ↑ ↓) opens it, it follows the selection and stays open (remembered, closed at first). Closing it with the
  // toggle or ⌘I hides it by hand: picks then only select, and the toggle shows the choice in words ("Details hidden",
  // a dashed outline, the glyph struck through) until the user opens the details by hand (the toggle, ⌘I, a quality
  // badge, the menu's Show details); the rules are `detailsAfter` in stores/chrome.ts. A right-click selects without
  // opening (the menu is what it asks for). A double-click or Enter plays. Below 1240 px the open inspector steps the
  // browser column back behind the rail (the chrome's job, stores/chrome.ts).
  import { untrack, type ComponentProps } from 'svelte';
  import {
    Button, EmptyState, PageHeader, ProblemCard, SearchField, Segmented, Skeleton, Spectrum, SummaryStrip, Surface, confirm,
  } from '$lib/components';
  import { ListPanelFrame } from '$lib/frames';
  import { api, runJob } from '$lib/bridge/client';
  import type { Fail, Library, LibraryFilter, LibrarySort, ProblemKind, TrackDetail } from '$lib/bridge/types';
  import { filesVersion } from '$lib/stores/hub';
  import { detailsHidden, detailsShown, inspectorAvailable, pickTrack, showDetails, toggleInspector } from '$lib/stores/chrome';
  import { player } from '$lib/stores/player';
  import { listen } from '$lib/listen';
  import { toasts } from '$lib/stores/toasts';
  import { problemCopy } from '$lib/copy';
  import { getPref, setPref } from '$lib/prefs';
  import { go, libraryHref } from '$lib/router';
  import { markReady } from '$lib/ready';
  import LibraryTable from './LibraryTable.svelte';
  import TrackDetails from './TrackDetails.svelte';
  import {
    DEFAULT_SORT, LIBRARY_FILTERS, SORT_KEY, filterKey, isSort, libraryView, nextSort, playable, segOptions, todoHref, type SortColumn,
  } from './libraryModel';
  import { NOT_IN_PLAYLIST } from '$lib/bridge/types';

  let { params, query }: { params: Record<string, string>; query: URLSearchParams } = $props();
  type Spec = ComponentProps<typeof Spectrum>['spectrum'];

  const folder = $derived(params.folder ?? null);
  const savedSort = getPref<string>(SORT_KEY, DEFAULT_SORT);
  let sort = $state<LibrarySort>(isSort(savedSort) ? savedSort : DEFAULT_SORT);
  let filter = $state<LibraryFilter>('all');
  let search = $state('');
  let q = $state('');
  let lib = $state<Library | null>(null);
  let libError: { kind: ProblemKind; message: string } | null = $state(null);
  let loading = $state(true);
  let selected = $state<string | null>(untrack(() => query.get('track')));

  let detail = $state<TrackDetail | null>(null);
  let detailLoading = $state(false);
  let gone = $state(false);
  let detailError = $state<Fail | null>(null);
  let spectrum = $state<Spec>(null);
  let spectrumLoading = $state(false);
  let spectrumError = $state<string | null>(null);
  let upgradeSpectrum = $state<Spec>(null);
  let swapping = $state(false);
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

  let libTurn = 0;
  $effect(() => {
    const args = [folder, q, filter, sort] as const;
    void $filesVersion;
    void retry;
    const turn = ++libTurn;
    untrack(() => { loading = true; });
    void api.library(...args).then((r) => {
      if (turn !== libTurn) return;
      loading = false;
      if (r.ok) {
        lib = r;
        libError = null;
        if (filter !== 'all' && r.chips[filter] === 0 && !q) setFilter('all');
      } else {
        libError = { kind: r.kind, message: r.message };
      }
      if (!ready) { ready = true; markReady('library'); }
    });
  });

  let trackTurn = 0;
  let trackRetry = $state(0);
  $effect(() => {
    const id = selected;
    void $filesVersion;
    void trackRetry;
    const turn = ++trackTurn;
    untrack(() => {
      gone = false;
      detailError = null;
      if (!id) { detail = null; return; }
      if (detail?.track_id !== id) { detail = null; spectrum = null; upgradeSpectrum = null; }
      void loadTrack(id, turn);
    });
  });

  async function loadTrack(id: string, turn: number) {
    detailLoading = true;
    const r = await api.track(id);
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
    if (!t.audio_url) { spectrum = null; return; }
    if (fresh || !spectrum) {
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
    sort = nextSort(sort, c);
    setPref(SORT_KEY, sort);
  }
  // `pick`: the user chose this track in the table (a click, ↑ ↓), which opens the details unless hidden by hand
  function select(id: string, pick = true) {
    if (pick) pickTrack();
    selected = id;
    void go(`${libraryHref(folder)}?track=${encodeURIComponent(id)}`, { replace: true });
  }
  // ▶ starts the folder as shown (filter, search and sort applied) as the queue, from this track. The rows come
  // sorted from the engine (`api.library(…, sort)`), and the table shows them in that order.
  function play(id: string) {
    const label = (lib?.title ?? 'All tracks') + (q ? ` · “${q}”` : '');
    // the queue holds the rows whose file is there: ⏭ never lands on a file on an ejected drive
    if (!lib || !listen(lib.rows.filter(playable), id, { label, href: libraryHref(folder) })) {
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
  async function swap() {
    const id = detail?.track_id;
    if (!id) return;
    const yes = await confirm({ title: 'Swap the files?', body: 'rekordbox keeps the cue points and the beatgrid.',
      confirmLabel: 'Swap' });
    if (!yes) return;
    swapping = true;
    await runJob(api.upgrade(id, 'swap'));
    swapping = false;
  }

  const options = $derived(segOptions(lib?.chips, filter));
  // the header's second line: its parts in order of importance, the last dropping first when the header is narrow
  const sub = $derived(lib?.subtitle);
  const emptyLibrary = $derived(lib?.empty === 'empty_library');
  const noFiles = $derived(!!lib && !emptyLibrary && lib.summary.tracks === 0);
  const noRows = $derived(!!lib && !emptyLibrary && !noFiles && lib.rows.length === 0);
  // which list (its optional columns): All tracks and Not in a playlist name the folder, a playlist doesn't
  const view = $derived(libraryView(folder));
  const playing = $derived($player.playing ? $player.track_id : null);
  function playOrPause(id: string) {
    if ($player.track_id === id && $player.url) player.toggle();
    else play(id);
  }
  // the details: only where there is a library to show (the empty page has no table to select in)
  const detailsOpen = $derived($detailsShown && !emptyLibrary);
  const handHidden = $derived($detailsHidden && !emptyLibrary);
  const detailsTip = $derived(detailsOpen ? { text: 'Hide details', keys: '⌘I' }
    : handHidden ? { text: "Show details\nHidden by you: selecting a track won't open them", keys: '⌘I' }
    : { text: 'Show details', keys: '⌘I' });
  // the chrome knows too: with an empty library ⌘I does nothing and a remembered open inspector steps nothing back
  $effect(() => { inspectorAvailable.set(!emptyLibrary); });
  $effect(() => () => inspectorAvailable.set(true));
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
  <PageHeader title={lib?.title ?? (folder === null ? 'All tracks' : folder === NOT_IN_PLAYLIST ? 'Not in a playlist' : folder)} {sub}>
    {#snippet actions()}<SearchField bind:value={search} bind:input={searchInput} placeholder="Search title, artist…" shortcut="cmd+f"
      test="library-search" />{#if !emptyLibrary}<Button variant="icon"
        icon={handHidden ? detailsHiddenIcon : detailsIcon} pressed={detailsOpen}
        switchedOff={handHidden ? 'Details hidden' : undefined}
        aria-label={detailsOpen ? 'Hide details' : handHidden ? 'Details hidden, show details' : 'Show details'}
        tip={detailsTip} aria-keyshortcuts="Meta+I" onclick={toggleInspector} data-test="library-details"
        data-hidden={handHidden || undefined} />{/if}{/snippet}
  </PageHeader>
  {#if libError && !lib}
    <ProblemCard kind={libError.kind} message={libError.message} onretry={() => { retry++; }} />
  {:else if !lib}
    <!-- waiting: the strip at its height with dashes, so nothing moves when the numbers come -->
    <SummaryStrip summary={null} onupgrades={() => {}} ontodo={() => {}} />
    <Surface kind="card"><Skeleton lines={8} height={18} gap={14} /></Surface>
  {:else if emptyLibrary}
    <Surface kind="card" data-test="library-empty">
      <EmptyState title="No tracks yet. Run a sync to fill your library." action={{ label: 'Open Sync', href: '#/sync' }} />
    </Surface>
  {:else}
    {#if libError}<ProblemCard compact kind={libError.kind} message={libError.message} />{/if}
    <SummaryStrip summary={lib.summary} onupgrades={() => setFilter('upgrade_ready')} ontodo={() => void go('/todo')} />
    {#if !noFiles}<Segmented {options} value={filter} onchange={setFilter} label="Quality" test="library-filter" />{/if}
    {#if noFiles}
      <Surface kind="card" data-test="library-no-files"><EmptyState title="No files in this folder yet." /></Surface>
    {:else if noRows && q}
      <Surface kind="card" data-test="library-no-match">
        <EmptyState title={`Nothing matches “${q}”.`} action={{ label: 'Clear search', onclick: () => { search = ''; q = ''; } }} />
      </Surface>
    {:else if noRows}
      <Surface kind="card" data-test="library-no-filter-match">
        <EmptyState title="Nothing matches this filter." action={{ label: 'Show all', onclick: () => setFilter('all') }} />
      </Surface>
    {:else}
      <LibraryTable rows={lib.rows} {loading} {view} {sort} {selected} {playing} {onsort} onselect={select}
        onplay={playOrPause} onfinder={(id) => void finder(id)} ontodo={todo} ondetails={showDetails} />
    {/if}
  {/if}
{/snippet}

{#snippet panel()}
  <TrackDetails {detail} loading={detailLoading} {gone} error={detailError} {spectrum} {spectrumLoading} {spectrumError}
    {upgradeSpectrum} {swapping} onretry={() => { trackRetry++; }}
    onfinder={() => detail && void finder(detail.track_id)} ontodo={() => detail && todo(detail.track_id)}
    onswap={() => void swap()} onlisten={() => detail && play(detail.track_id)} />
{/snippet}

<ListPanelFrame {main} panel={selected ? panel : null} emptyPanel="Select a track to see its details." wide
  panelMode="inspector" open={detailsOpen} panelLabel="Track details" />
