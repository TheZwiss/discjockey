<script lang="ts">
  // The Playlists panel (design system mockup design-system/playlists.html), as a Panel whose foot is the page's
  // Undo · Save. Nothing unsaved: the tracks that are in several playlists, as a number and as one list grouped by
  // the playlist that loses them ("Powertrance · lands in Hard_Bounce"). Unsaved: preview_playlist_change(lines),
  // debounced 300 ms; request ids drop answers that arrive out of order; while a newer answer loads the last one
  // stays, dimmed. The preview shows every part that applies, numbers first: new downloads and their days, tracks
  // that stop updating, each changed folder's count after the change on one bar scale (DeltaBar), then the tracks that
  // change folder grouped by route as the panel's one growing list, and what stays safe as one line above the foot
  // (the full checklist behind its ⓘ). A problem is a red
  // NoteCard; the panel tells the page (onpanel) whether Save is allowed and what the change does to each folder.
  import { untrack, type Snippet } from 'svelte';
  import {
    Cover, DeltaBar, Hint, InfoTip, ListRow, ListSection, NoteCard, ProblemCard, QualityBadge, Spinner, StatCard, Surface,
  } from '$lib/components';
  import { Panel } from '$lib/frames';
  import { api } from '$lib/bridge/client';
  import type { PlaylistLine, Playlists } from '$lib/bridge/types';
  import { networkReadsAllowed } from '$lib/stores/hub';
  import { plural } from '$lib/format';
  import {
    NO_PREVIEW, PREVIEW_AFTER_SYNC, folderBars, moveRoutes, overlapCards, panelFor, previewRequests, type FoldRow,
    type Panel as PanelState, type PreviewState,
  } from './changeModel';

  let { dirty, lines, overlaps, rows, onpanel, foot }: {
    dirty: boolean;                          // the draft differs from the loaded file
    lines: PlaylistLine[];                   // lines(draft), top first
    overlaps: Playlists['overlaps'];         // from playlists(), for the "not dirty" view
    rows: { folder: string; tracks: number | null }[];   // the saved rows, for the playlists' track counts
    onpanel: (p: PanelState) => void;        // what the panel shows now (Save allowed, the preview)
    foot: Snippet;                           // Undo · Save
  } = $props();

  const DEBOUNCE_MS = 300;
  const req = previewRequests();
  let preview = $state<PreviewState>(NO_PREVIEW);

  async function ask(ls: PlaylistLine[], id: number) {
    const r = await api.preview_playlist_change(ls);
    if (req.isLatest(id)) preview = { loading: false, answer: r };
  }

  $effect(() => {
    const ls = lines;
    if (!dirty) { req.cancel(); preview = NO_PREVIEW; return; }
    if (!$networkReadsAllowed) {
      req.cancel();
      preview = { loading: false, answer: { ok: false, kind: 'sync_running', message: PREVIEW_AFTER_SYNC } };
      return;
    }
    const id = req.next();   // planned now, so an answer to older lines no longer counts
    untrack(() => { preview = { loading: true, answer: preview.answer?.ok ? preview.answer : null }; });
    const t = setTimeout(() => ask(ls, id), DEBOUNCE_MS);
    return () => clearTimeout(t);
  });

  function retry() {
    const id = req.next();
    preview = { loading: true, answer: preview.answer };
    ask(lines, id);
  }

  const panel = $derived(panelFor(dirty, preview, overlaps));
  $effect(() => { onpanel(panel); });

  const cards = $derived(panel.view === 'overlaps' ? overlapCards(panel.overlaps, rows) : []);
  const p = $derived(panel.preview && !panel.preview.problem ? panel.preview : null);
  const bars = $derived(p ? folderBars(p.folders) : { rows: [], max: 0 });
  const routes = $derived(p ? moveRoutes(p) : []);
  const moving = $derived(routes.reduce((n, r) => n + r.rows.length, 0));
  // the backend's headline only when no number or list says the change (rename of an empty folder, nothing changes)
  const headlineOnly = $derived(!!p && !p.new_downloads && !p.stopped && !bars.rows.length && !moving
    && !p.unknown.length);
</script>

{#snippet track(r: FoldRow)}
  <ListRow height={40} title={r.name}>
    {#snippet lead()}<Cover url={r.cover_url} seed={r.track_id} size={28} />{/snippet}
    {#snippet name()}{r.name}{/snippet}
    {#snippet trailing()}
      {#if r.note}<span class="note">{r.note}</span>{/if}
      {#if r.badge}<QualityBadge quality={r.badge.quality} label={r.badge.label} />
      {:else if !r.note}<span class="note">not downloaded yet</span>{/if}
    {/snippet}
  </ListRow>
{/snippet}

{#snippet head()}
  <div class="part" class:dim={panel.dim} data-test="change-panel" aria-busy={panel.dim || undefined}>
    {#if panel.view === 'overlaps'}
      <StatCard value={panel.overlaps.length} unit={panel.overlaps.length === 1 ? 'track' : 'tracks'}
        label={panel.overlaps.length ? 'in several playlists, downloaded once' : 'in several playlists'} data-test="overlaps" />
    {:else if panel.view === 'loading'}
      <Surface kind="card" data-test="preview-loading">
        <span class="working"><Spinner size={16} />Working out what changes…</span>
      </Surface>
    {:else if panel.view === 'sync_running'}
      <NoteCard tone="warn" title={PREVIEW_AFTER_SYNC} data-test="preview-sync_running">
        You can keep editing. Save works again after the sync.</NoteCard>
    {:else if panel.view === 'failed' && panel.fail}
      <div data-test="preview-failed">
        <ProblemCard alert compact kind={panel.fail.kind} message={panel.fail.message} onretry={retry} />
      </div>
    {:else if panel.view === 'problem' && panel.preview?.problem}
      <NoteCard tone="problem" data-test="preview-problem">
        <span data-test="preview-problem-text">{panel.preview.problem}</span></NoteCard>
    {:else if p}
      <div class="part" data-test="preview-{panel.view}">
        {#if p.new_downloads}
          <div class="pair">
            <StatCard value={p.new_downloads} label={p.new_downloads === 1 ? 'new download' : 'new downloads'}
              data-test="stat-new" />
            {#if p.days}
              <StatCard value={p.days} unit={p.days === 1 ? 'day' : 'days'} label="at your daily limit"
                data-test="stat-days" />
            {/if}
          </div>
        {/if}
        {#if p.stopped}
          <StatCard value={p.stopped} unit={p.stopped === 1 ? 'track' : 'tracks'}
            label="stop updating · their files stay" data-test="stat-stopped" />
        {/if}
        {#if p.unknown.length}
          <NoteCard title="Discjockey hasn't read the new playlist yet" data-test="preview-unknown">
            {p.unknown.join(' · ')}</NoteCard>
        {/if}
        {#if headlineOnly}
          <Surface kind="card" label={p.headline} data-test="preview-headline">
            <Hint text="Read Spotify after saving to see its tracks." />
          </Surface>
        {/if}
        {#if bars.rows.length}
          <Surface kind="list" label={bars.rows.length === 1 ? '1 folder changes' : `${bars.rows.length} folders change`}
            style="--row-cols: minmax(0, 1fr) auto" data-test="folder-changes">
            {#snippet header()}<Hint text="files after" />{/snippet}
            {#each bars.rows as f (f.folder)}
              <ListRow height={40} title={f.folder} data-folder={f.folder}>
                {#snippet name()}<span class:top={f.delta > 0}>{f.folder}</span>{/snippet}
                {#snippet trailing()}
                  <DeltaBar value={f.delta} max={bars.max} />
                  <span class="after">{f.after}</span>
                  <span class="diff" class:gain={f.delta > 0}>{f.delta > 0 ? '+' : '−'}{Math.abs(f.delta)}</span>
                {/snippet}
              </ListRow>
            {/each}
          </Surface>
        {/if}
      </div>
    {/if}
  </div>
{/snippet}

{#snippet fill()}
  {#if panel.view === 'overlaps' && cards.length}
    <Surface kind="list" label="Where they land" style="--row-cols: 28px minmax(0, 1fr) auto"
      grow={{ rows: cards.length + cards.reduce((n, c) => n + c.lost.length, 0) }} data-test="overlap-list">
      {#each cards as c (c.folder)}
        <ListSection label={c.folder} summary={String(c.lost.length)} hint={c.hint} test="overlap-section" />
        {#each c.lost as t (t.track_id)}
          {@render track({ track_id: t.track_id, name: `${t.artist} – ${t.title}`, cover_url: t.cover_url,
            note: c.goTo.length > 1 ? `→ ${t.lands_in}` : null,
            badge: t.downloaded && t.quality_label ? { quality: t.quality, label: t.quality_label } : null })}
        {/each}
      {/each}
    </Surface>
  {:else if p && routes.length}
    <Surface kind="list" label={moving === 1 ? '1 track moves' : `${moving} tracks move`}
      class={panel.dim ? 'dim' : ''} style="--row-cols: 28px minmax(0, 1fr) auto"
      grow={{ rows: routes.length + moving }} data-test="moves">
      {#each routes as r (`${r.from}→${r.to}`)}
        <ListSection label="{r.from} → {r.to}" summary={String(r.rows.length)} test="route" />
        {#each r.rows as t (t.track_id)}{@render track(t)}{/each}
      {/each}
    </Surface>
  {/if}
{/snippet}

{#snippet after()}
  {#if p && p.checklist.length}
    <!-- what stays safe, in one line above Save (the tracks list keeps the height); the full list behind the ⓘ -->
    <div class="safe" class:dim={panel.dim} data-test="checklist">
      <Hint text="Nothing is deleted · at the next sync" />
      <InfoTip label="What this change keeps safe">{p.checklist.join('. ')}.</InfoTip>
    </div>
  {/if}
{/snippet}

<Panel {head} fill={(panel.view === 'overlaps' && cards.length) || (p && routes.length) ? fill : undefined} {after}
  {foot} />

<style>
  .part { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0;
    transition: opacity var(--t-state) var(--ease); }
  .dim, :global(.dim[data-surface]) { opacity: var(--dim-locked); }
  .pair { display: grid; grid-template-columns: 1fr 1fr; gap: var(--s-3); }
  .working { display: flex; align-items: center; gap: var(--s-2); color: var(--text-muted); }
  .note { color: var(--text-label); }
  .after { min-width: 32px; text-align: right; color: var(--text-strong); font-weight: var(--fw-semi); }
  .diff { min-width: 28px; text-align: right; color: var(--text-muted); font-size: var(--fs-label); }
  .gain { color: var(--accent-text); }
  .top { color: var(--text-strong); font-weight: var(--fw-semi); }
  .safe { display: flex; align-items: center; gap: var(--s-2); min-width: 0; }
  .safe > :global(:first-child) { min-width: 0; }
</style>
