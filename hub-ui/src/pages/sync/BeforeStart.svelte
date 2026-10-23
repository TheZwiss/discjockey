<script lang="ts">
  // Before the start (docs/archive/pre-public/hub-ui-pages/sync-REDESIGN.md): the plan per playlist with ticks and search on the left, "This run" on the
  // right (how many downloads, which playlists and kinds, Start sync). While Spotify is read, a card says which
  // playlist; nothing to do → "Up to date" with the last sync. Spotify is read by itself once per app session (the
  // hub when it opens, else this page when it opens first; shouldAutoRead) and by the backend whenever playlists.txt
  // changes; otherwise only with "↻ Read Spotify".
  import { onMount, untrack } from 'svelte';
  import {
    Button, EmptyState, Hint, NoteCard, PageHeader, ProblemCard, SearchField, Skeleton, WriteButton,
  } from '$lib/components';
  import { ListPanelFrame } from '$lib/frames';
  import { api, runJob } from '$lib/bridge/client';
  import type { Fail, PreviewAction, RunSummary, SyncPreview } from '$lib/bridge/types';
  import { dataVersion, hub, spotifyMissing, spotifyMissingKind, syncRunning, writeBlockedReason } from '$lib/stores/hub';
  import { toasts } from '$lib/stores/toasts';
  import { getPref, setPref } from '$lib/prefs';
  import { markReady } from '$lib/ready';
  import { latestOnly } from '$lib/latest';
  import { sayInBody } from '$lib/stores/shell';
  import { artistTitle, plural } from '$lib/format';
  import { PREF_LAST_SELECTION, carryTicks, keyId, picked } from './selection';
  import {
    PREF_HOW_MANY, PREF_SCOPE, defaultHowMany, facets, inRunOrder, inScope, isDownload, matches, nextSyncSet,
    mayWaitToday, kindOf, downloadsInScope, presetN, presetTicks, presets, readHowMany, readScope, runTotals, scopeSet, sections, shouldAutoRead, shownPreset,
    NOTHING_TODAY, runsNothingToday, sectionCounts, startLabel, toggleScope,
    type HowMany, type Scope, type Section,
  } from './planModel';
  import { keepDetail, lastSyncStats, lastSyncView, needsDetail, type LastSyncDetail } from './endModel';
  import ReadingCard from './plan/ReadingCard.svelte';
  import PlanRows from './plan/PlanRows.svelte';
  import PlanFolds from './plan/PlanFolds.svelte';
  import RunPanel from './plan/RunPanel.svelte';
  import UpToDate from './plan/UpToDate.svelte';
  import UpToDatePanel from './plan/UpToDatePanel.svelte';

  let preview = $state<SyncPreview | null>(null);
  let problem = $state<Fail | null>(null);
  let loading = $state(true);
  let ticked = $state(new Set<string>());
  let known = new Set<string>();
  let scope = $state<Scope>(readScope(getPref<object>(PREF_SCOPE, {})));
  /** a preset, or 'custom' once ticked by hand; null until the first preview gives the default */
  let howMany = $state<HowMany | 'custom' | null>(readHowMany(getPref<unknown>(PREF_HOW_MANY, null)));
  let query = $state('');
  /** undefined until the dashboard answers; null: no sync has run */
  let lastRun = $state<RunSummary | null | undefined>(undefined);
  let upgrades = $state<number | null>(null);
  let lastDetail = $state<LastSyncDetail | null>(null);
  let starting = $state(false);
  let startProblem = $state<Fail | null>(null);
  let neverBusy = $state<string | null>(null);

  // left null: no daily limit (only free sources are set up), so nothing waits for tomorrow
  const limitLeft = $derived(preview?.estimate ? preview.estimate.left : 0);
  const left = $derived(limitLeft === null ? Number.POSITIVE_INFINITY : Math.max(0, limitLeft));
  const limit = $derived(preview?.estimate?.limit ?? 0);
  const ordered = $derived(inRunOrder(preview));
  const scoped = $derived(ordered.filter((a) => inScope(a, scope)));
  const total = $derived(downloadsInScope(ordered, scope));
  const presetList = $derived(presets(total, left));
  const chosen = $derived(scoped.filter((a) => ticked.has(keyId(a.key))));
  // Later counts only what's in scope, so it agrees with "All N" and the days (issue 7)
  const totals = $derived(runTotals(chosen, total, left, limit,
    preview?.estimate?.minutes_by_downloads ?? []));
  const movesTicked = $derived(chosen.filter((a) => kindOf(a) === 'move').length);
  // only downloads that wait for the next sync are ticked: a run would do nothing today, so Start is off (Task 9B ruling)
  const nothingToday = $derived(runsNothingToday(chosen.length, totals.downloads, totals.uses, movesTicked));
  const nextSync = $derived(nextSyncSet(ordered, ticked, scope, left));
  // some ticked download may wait while others run today (fixed while the plan is)
  const mayWait = $derived(mayWaitToday(ordered.filter(isDownload).length, left));
  const facetLists = $derived(facets(ordered, preview?.folders ?? []));
  const visible = $derived(scoped.filter((a) => matches(a, query)));
  const sectionList = $derived<Section[]>(sections(visible, preview?.folders ?? []).map((s) =>
    ({ ...s, ...sectionCounts(scoped.filter((a) => a.folder === s.folder), ticked, nextSync) })));
  const searching = $derived(query.trim() !== '');
  const hidden = $derived(ordered.length - scoped.length);

  const reading = $derived($hub.refresh_running || !!preview?.spotify.reading);
  // the shared store first (it also knows a missing login before any read failed), so this card, the banner on
  // other pages and the header slot say the same state with the same words (spec §11)
  const spotifyProblem = $derived($spotifyMissingKind ?? preview?.spotify.problem ?? null);
  const lastView = $derived(lastSyncView(lastRun, lastDetail));
  // up to date with no sync ever and nothing that could be better: the frame's empty panel, not a blank Panel
  const upToDatePanel = $derived(preview?.empty === 'up_to_date'
    && !(lastView === null && !upgrades && !$hub.sidebar?.todo));
  const hasPlan = $derived(!!preview && preview.empty === null && ordered.length > 0);
  const neverBlocked = $derived($writeBlockedReason);
  // the shell's banners stay off only for what this view says itself (lib/stores/shell.ts): the console while Start
  // and its Hint show (a plan), Spotify while the card above the plan can show (a preview); up to date and the empty
  // states have no Start, so the console banner stays there (final review I1). While loading, both are claimed: the
  // body says them in nearly every outcome, and a banner drawn over the skeleton would jump away when the plan comes
  $effect(() => sayInBody({ console: loading || hasPlan, spotify: loading || (!problem && !!preview) }));
  const startTitle = $derived($hub.console_running ? 'A sync is running in the terminal. Its progress shows there.'
    : chosen.length === 0 ? 'Nothing ticked' : nothingToday ? NOTHING_TODAY : undefined);

  function applyPreset(h: HowMany) {
    ticked = presetTicks(ordered, scope, presetN(h, total, left));
  }

  // two quick data bumps (a JobFinished, then a refresh) can answer out of order: only the newest reply is applied
  const previews = latestOnly();
  const dashboards = latestOnly();
  async function load() {
    const ticket = previews.next();
    const r = await api.sync_preview();
    if (!previews.isLatest(ticket)) return;
    loading = false;
    if (!r.ok) { problem = r; markReady('sync'); return; }
    problem = null;
    const first = preview === null;
    const prev = { ticked, known };
    preview = r;
    known = new Set(inRunOrder(r).map((a) => keyId(a.key)));
    if (howMany === null) howMany = defaultHowMany(total, left);
    if (howMany === 'custom') ticked = carryTicks(r, first ? null : prev);
    else applyPreset(howMany);
    if (r.empty === 'up_to_date') void loadUpToDate();
    markReady('sync');
    if (first) autoRead(r);
  }
  async function loadUpToDate() {
    // the newest run is the dashboard's last_runs[0], so one call gives it and the upgrades count
    const ticket = dashboards.next();
    const dash = await api.dashboard();
    // an older reply would set lastRun back, and keepDetail would then drop the newer run's details (final review M12)
    if (!dashboards.isLatest(ticket)) return;
    if (dash.ok) { lastRun = dash.last_runs[0] ?? null; upgrades = dash.needs_you.upgrades; }
    else if (lastRun === undefined) lastRun = null;
    // the panel counts the last run as its end screen does and waits for these details (lastSyncView); a reply that
    // comes after a newer run took its place is dropped
    const id = lastRun?.run_id;
    if (!id || !needsDetail(lastDetail, id)) return;
    const r = await api.run(id);
    lastDetail = keepDetail(lastDetail, { run_id: id, stats: r.ok ? lastSyncStats(r.run) : 'failed' }, lastRun?.run_id);
  }
  /** The session's one automatic read, if the hub hasn't started it yet (never during a read or a sync). */
  function autoRead(r: SyncPreview) {
    if (!shouldAutoRead(r, { refreshRunning: $hub.refresh_running, syncRunning: $syncRunning })) return;
    void runJob(api.refresh(true), { success: false, quiet: true });
  }

  onMount(() => { void load(); });
  let seen = -1;
  $effect(() => {
    const v = $dataVersion;
    if (seen !== -1 && v !== seen) untrack(() => void load());
    seen = v;
  });

  // ---------- ticks ----------
  function toggle(a: PreviewAction) {
    const id = keyId(a.key);
    const next = new Set(ticked);
    if (next.has(id)) next.delete(id); else next.add(id);
    ticked = next;
    howMany = 'custom';
  }
  function tickFolder(folder: string, on: boolean) {
    const next = new Set(ticked);
    for (const a of scoped) if (a.folder === folder) { if (on) next.add(keyId(a.key)); else next.delete(keyId(a.key)); }
    ticked = next;
    howMany = 'custom';
  }
  /** "Sync only this artist": exactly the matches in scope are ticked. */
  function tickOnlyMatches() {
    ticked = new Set(visible.map((a) => keyId(a.key)));
    howMany = 'custom';
  }
  function pickHowMany(h: HowMany) {
    howMany = h;
    setPref(PREF_HOW_MANY, h);
    applyPreset(h);
  }
  function changeScope(what: 'folders' | 'kinds', key: string) {
    scope = toggleScope(scope, what, key);
    setPref(PREF_SCOPE, scope);
    if (howMany !== 'custom' && howMany !== null) applyPreset(howMany);
  }
  /** All · None in a panel group: the shown rows' keys on or off at once. */
  function changeScopeAll(what: 'folders' | 'kinds', keys: string[], on: boolean) {
    scope = scopeSet(scope, what, keys, on);
    setPref(PREF_SCOPE, scope);
    if (howMany !== 'custom' && howMany !== null) applyPreset(howMany);
  }

  // ---------- never download ----------
  async function never(a: PreviewAction) {
    neverBusy = a.track_id;
    const r = await runJob(api.never_download(a.track_id, true), { success: false });
    neverBusy = null;
    if (r.ok) {
      toasts.show({ tone: 'success', title: `Won't download ${artistTitle(a.artist, a.title)}`,
        body: 'It stays in your playlist. Find it under "Never download" below the plan.',
        action: { label: 'Undo', onclick: () => void again(a) } });
    }
  }
  async function again(a: PreviewAction) {
    neverBusy = a.track_id;
    const r = await runJob(api.never_download(a.track_id, false), { success: false });
    neverBusy = null;
    if (r.ok) toasts.show({ tone: 'success', title: `Back in the plan: ${artistTitle(a.artist, a.title)}` });
  }

  // ---------- start ----------
  async function start() {
    if (!preview || !chosen.length || nothingToday) return;
    const sel = picked(preview, new Set(chosen.map((a) => keyId(a.key))));
    setPref(PREF_LAST_SELECTION, sel);
    starting = true;
    startProblem = null;
    const out = await runJob(api.start_sync(sel.map((a) => a.key)), { quiet: true });
    starting = false;
    if (!out.ok && out.job_id === null) startProblem = { ok: false, kind: out.kind, message: out.message };
  }
</script>

{#snippet main()}
  <div class="before" data-test="sync-before">
    <PageHeader title="Sync" spotify spotifyInBody />

    {#if loading}
      <Skeleton height={28} />
      <Skeleton lines={8} height={28} />
    {:else if problem}
      <ProblemCard kind={problem.kind} message={problem.message} onretry={load} />
    {:else if preview}
      <!-- Spotify's problem is said here once (the banner stays off on this view): no Retry, since Read Spotify sits
           in the header slot right above, its one place (spec §11) -->
      {#if spotifyProblem}
        <div data-test="spotify-problem">
          <ProblemCard kind={spotifyProblem} message={preview.spotify.message} spotify />
        </div>
      {/if}
      {#if reading}<ReadingCard progress={$hub.read_progress} stale={hasPlan || preview.empty === 'up_to_date'} />{/if}

      {#if preview.empty === 'up_to_date'}
        <UpToDate tracks={preview.in_playlists} playlists={preview.folders.length} />
        <PlanFolds {preview} busy={neverBusy} blocked={neverBlocked} onagain={again} />
      {:else if preview.empty || !hasPlan}
        <!-- "Read Spotify above" only while that button works; else the Spotify card above says why -->
        {#if !reading}<EmptyState kind={preview.empty ?? 'up_to_date'}
          body={preview.empty === 'no_preview' && $spotifyMissing ? '' : undefined} />{/if}
      {:else}
        <div class="search">
          <SearchField bind:value={query} placeholder="Find an artist or title…" shortcut="cmd+f" />
        </div>
        {#if searching}
          <div class="found" data-test="sync-search-head">
            {#if visible.length}
              <span>{plural(visible.length, 'match', 'matches')}</span>
              <Button size="sm" onclick={tickOnlyMatches} data-test="sync-tick-only">Tick only these</Button>
            {:else}
              <span>Nothing matches “{query.trim()}”.</span>
              <Button size="sm" variant="link" onclick={() => (query = '')}>Clear search</Button>
            {/if}
          </div>
        {/if}
        <div class="plan" class:dim={reading} data-test="sync-plan">
          <PlanRows sections={sectionList} {ticked} {nextSync} {mayWait} {neverBlocked} ontoggle={toggle} onfolder={tickFolder}
            onnever={never} />
          {#if hidden > 0 && !searching}
            <!-- a NoteCard, not a Hint: the controls it explains sit in the other column, and a Hint goes directly
                 under its own control (design language §2 "everything sits in a container", §5 Text; issue 7) -->
            <NoteCard title="{plural(hidden, 'more track')} left out" data-test="sync-hidden">
              Playlists or kinds you turned off on the right.</NoteCard>
          {/if}
        </div>
        <PlanFolds {preview} busy={neverBusy} blocked={neverBlocked} onagain={again} />
      {/if}
    {/if}
  </div>
{/snippet}

{#snippet startArea()}
  <WriteButton variant="filled" wide onclick={start} busy={starting} busyLabel="Starting…"
    disabled={chosen.length === 0 || nothingToday || $hub.console_running} title={startTitle} data-test="start-sync">
    {startLabel(chosen.length, totals.downloads, totals.uses, movesTicked)}</WriteButton>
  {#if $hub.console_running}<Hint text="A sync is running in the terminal" data-test="sync-console" />
  {:else if nothingToday}<Hint text={NOTHING_TODAY} data-test="sync-nothing-today" />{/if}
  {#if startProblem}<ProblemCard kind={startProblem.kind} message={startProblem.message} sync compact alert />{/if}
{/snippet}

{#snippet panel()}
  {#if hasPlan}
    <RunPanel summary={totals} left={limitLeft === null ? null : left} {limit} presets={presetList}
      accounts={preview?.estimate?.accounts ?? []}
      howMany={shownPreset(howMany ?? 'custom', presetList, total, left)} folders={facetLists.folders}
      kinds={facetLists.kinds} {scope} moves={movesTicked} onhowmany={pickHowMany} onscope={changeScope}
      onscopeall={changeScopeAll} start={startArea} />
  {:else if upToDatePanel}
    <UpToDatePanel last={lastRun ?? null} view={lastView} todo={$hub.sidebar?.todo ?? null} {upgrades} />
  {/if}
{/snippet}

<ListPanelFrame {main} panel={hasPlan || upToDatePanel ? panel : null}
  emptyPanel={reading ? 'The plan shows here when Spotify is read.' : preview?.empty === 'up_to_date'
    ? 'Your last sync shows here.' : 'The plan for the next sync shows here.'} />

<style>
  .before { display: flex; flex-direction: column; gap: var(--s-3); }
  .search { display: flex; }
  .search :global(.sf) { flex: 1; }
  .found { display: flex; align-items: center; gap: var(--s-3); color: var(--text-muted); font-size: var(--fs-small); }
  .plan { display: flex; flex-direction: column; gap: var(--s-3); transition: opacity var(--t-state) var(--ease); }
  .plan.dim { opacity: var(--dim-locked); }
</style>
