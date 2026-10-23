<script lang="ts">
  // Library (spec §5.4; design system mockup design-system/library.html): on ListPanelFrame (`wide`, the table gets
  // up to 1200 px). The list area: the header (title · track count, search), the quality filter as one Segmented,
  // then the tracks as one table Surface that fills the height and scrolls in place (LibraryTable). The panel is the
  // picked track (TrackDetails, the same cards as To-do's) or, with nothing picked, the folder at a glance
  // (FolderOverview).
  import { untrack, type ComponentProps } from 'svelte';
  import {
    EmptyState, PageHeader, ProblemCard, SearchField, Segmented, Skeleton, Spectrum, Surface, confirm,
  } from '$lib/components';
  import { ListPanelFrame } from '$lib/frames';
  import { api, runJob } from '$lib/bridge/client';
  import type { Fail, Library, LibraryFilter, LibrarySort, ProblemKind, TrackDetail } from '$lib/bridge/types';
  import { dataVersion } from '$lib/stores/hub';
  import { player } from '$lib/stores/player';
  import { toasts } from '$lib/stores/toasts';
  import { problemCopy } from '$lib/copy';
  import { artistTitle, plural } from '$lib/format';
  import { getPref, setPref } from '$lib/prefs';
  import { go, libraryHref } from '$lib/router';
  import { markReady } from '$lib/ready';
  import LibraryTable from './LibraryTable.svelte';
  import TrackDetails from './TrackDetails.svelte';
  import FolderOverview from './FolderOverview.svelte';
  import {
    DEFAULT_SORT, LIBRARY_FILTERS, SORT_KEY, filterKey, isSort, nextSort, segOptions, todoHref, type SortColumn,
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
    void $dataVersion;
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
    void $dataVersion;
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
  function select(id: string) {
    selected = id;
    void go(`${libraryHref(folder)}?track=${encodeURIComponent(id)}`, { replace: true });
  }
  async function play(id: string) {
    let t = detail?.track_id === id ? detail : null;
    if (!t) {
      const r = await api.track(id);
      if (!r.ok) { toasts.show({ tone: 'problem', title: problemCopy(r.kind).title, body: r.message || undefined }); return; }
      t = r.track;
    }
    if (!t.audio_url) { toasts.show({ tone: 'problem', title: "Can't play this file." }); return; }
    player.play({ url: t.audio_url, title: artistTitle(t.artist, t.title), track_id: t.track_id });
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
  const sub = $derived(lib ? plural(lib.summary.tracks, 'track') : undefined);
  const emptyLibrary = $derived(lib?.empty === 'empty_library');
  const noFiles = $derived(!!lib && !emptyLibrary && lib.summary.tracks === 0);
  const noRows = $derived(!!lib && !emptyLibrary && !noFiles && lib.rows.length === 0);
  // All tracks and Not in a playlist hold tracks of several folders: Folder becomes a column
  const allTracks = $derived(folder === null || folder === NOT_IN_PLAYLIST);
  const playing = $derived($player.playing ? $player.track_id : null);
  function playOrPause(id: string) {
    if ($player.track_id === id && $player.url) player.toggle();
    else void play(id);
  }
</script>

{#snippet main()}
  <PageHeader title={lib?.title ?? (folder === null ? 'All tracks' : folder === NOT_IN_PLAYLIST ? 'Not in a playlist' : folder)} {sub}>
    {#snippet actions()}<SearchField bind:value={search} placeholder="Search title, artist…" shortcut="cmd+f" />{/snippet}
  </PageHeader>
  {#if libError && !lib}
    <ProblemCard kind={libError.kind} message={libError.message} onretry={() => { retry++; }} />
  {:else if !lib}
    <Surface kind="card"><Skeleton lines={8} height={18} gap={14} /></Surface>
  {:else if emptyLibrary}
    <Surface kind="card" data-test="library-empty">
      <EmptyState title="No tracks yet. Run a sync to fill your library." action={{ label: 'Open Sync', href: '#/sync' }} />
    </Surface>
  {:else}
    {#if libError}<ProblemCard compact kind={libError.kind} message={libError.message} />{/if}
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
      <LibraryTable rows={lib.rows} {loading} {allTracks} {sort} {selected} {playing} {onsort} onselect={select}
        onplay={playOrPause} onfinder={(id) => void finder(id)} ontodo={todo} />
    {/if}
  {/if}
{/snippet}

{#snippet panel()}
  {#if selected}
    <TrackDetails {detail} loading={detailLoading} {gone} error={detailError} {spectrum} {spectrumLoading} {spectrumError}
      {upgradeSpectrum} {swapping} onretry={() => { trackRetry++; }}
      onfinder={() => detail && void finder(detail.track_id)} ontodo={() => detail && todo(detail.track_id)}
      onswap={() => void swap()} />
  {:else}
    <FolderOverview summary={lib && !emptyLibrary ? lib.summary : null} onupgrades={() => setFilter('upgrade_ready')}
      ontodo={() => void go('/todo')} />
  {/if}
{/snippet}

<ListPanelFrame {main} panel={emptyLibrary ? null : panel} emptyPanel="No tracks yet." wide />
