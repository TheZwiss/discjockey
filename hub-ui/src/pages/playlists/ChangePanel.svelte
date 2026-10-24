<script lang="ts">
  // The Playlists panel (design system mockup design-system/playlists.html; tidy-up mockup, plan library stage 2 6.2/6.4)
  // as a Panel whose foot is the page's Undo · Save. Nothing unsaved: one Segmented on top, "In several playlists" (the
  // tracks in several playlists, as a number and as one list grouped by the playlist that loses them) or "Recent
  // moves" (the move log, newest first, each with Undo or "Nothing left to undo"). Unsaved:
  // preview_playlist_change(lines), debounced 300 ms; request ids drop answers that arrive out of order; while a newer
  // answer loads the last one stays, dimmed. The preview shows every part that applies, numbers first: new downloads
  // and their days, tracks that stop updating, then either the save question (a change that puts files in another
  // folder: the rename on disk as a switch, the files as one list, the warning card, Save and move · Save, leave
  // files where they are) or each changed folder's count after the change (DeltaBar) and the tracks without a file
  // that land elsewhere later. A problem is a red NoteCard; Save is off while it shows.
  import { untrack } from 'svelte';
  import {
    Button, Cover, DeltaBar, EmptyState, Hint, InfoTip, ListRow, ListSection, NoteCard, ProblemCard, QualityBadge,
    Segmented, Spinner, StatCard, Surface, ToggleRow, WriteButton,
  } from '$lib/components';
  import { Panel } from '$lib/frames';
  import { api } from '$lib/bridge/client';
  import type { MoveBatches, PlaylistLine, Playlists, ProblemKind, SaveFiles } from '$lib/bridge/types';
  import { dataVersion, networkReadsAllowed } from '$lib/stores/hub';
  import { runWhen } from '$lib/format';
  import {
    NO_PREVIEW, PREVIEW_AFTER_SYNC, folderBars, moveRoutes, overlapCards, panelFor, previewRequests, type FoldRow,
    type Panel as PanelState, type PanelTab, type PreviewState,
  } from './changeModel';
  import TidyList from './TidyList.svelte';
  import {
    LEAVE_HINT, NOTHING_LEFT, NO_MOVES_YET, R1, R2, U1, carryOver, folderRows, groups, offerDetail, saveCount,
    saveFileCount, saveFiles, saveHeadline, saveItems, saveMoving, toggleGroup, toggleRename,
    toggleTick, visibleRows, type MoveItem, type SaveQuestion,
  } from './tidyModel';

  let { dirty, lines, overlaps, rows, saving, tab, onpanel, ontab, onundo, onsave, onundobatch }: {
    dirty: boolean;                          // the draft differs from the loaded file
    lines: PlaylistLine[];                   // lines(draft), top first
    overlaps: Playlists['overlaps'];         // from playlists(), for the "not dirty" view
    rows: { folder: string; tracks: number | null }[];   // the saved rows, for the playlists' track counts
    saving: boolean;                         // a save is running
    tab: PanelTab;                           // nothing unsaved: which list the panel shows
    onpanel: (p: PanelState) => void;        // what the panel shows now (Save allowed, the preview)
    ontab: (t: PanelTab) => void;
    onundo: () => void;                      // back to the loaded file
    onsave: (files: SaveFiles | null, items: MoveItem[]) => void;   // files: the save question's answer
    onundobatch: (batch_id: number) => void; // Undo of a recent move
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

  // ---------- the save question ----------
  let question = $state<SaveQuestion | null>(null);
  $effect(() => {
    const pv = panel.preview;
    const t = pv && !pv.problem ? pv.tidy : null;
    untrack(() => { question = t && pv ? carryOver(question, t.rows, pv.renames) : null; });
  });
  const q = $derived(question);
  // the pointer or the keyboard is on "Save, leave files where they are": it renames no folder, so the switch greys out
  let leaving = $state(false);
  const qGroups = $derived(q ? groups(visibleRows(q)) : null);
  const qShown = $derived(q ? visibleRows(q) : []);
  const qCount = $derived(q ? saveCount(q) : null);
  const qMoving = $derived(q ? saveMoving(q) : 0);
  // a rename that can't be offered for a reason the user can act on is shown locked; `no_folder` isn't shown at all
  const offers = $derived(q ? q.renames.filter((r) => r.offered || r.why_not) : []);

  // ---------- recent moves ----------
  let moves = $state<MoveBatches | null>(null);
  let movesFail = $state<{ kind: ProblemKind; message: string } | null>(null);
  let movesTurn = 0;
  async function loadMoves() {
    const t = ++movesTurn;
    const r = await api.move_batches();
    if (t !== movesTurn) return;
    if (r.ok) { const { ok: _ok, ...m } = r; moves = m; movesFail = null; }
    else movesFail = { kind: r.kind, message: r.message };
  }
  $effect(() => {
    void $dataVersion;
    if (dirty) return;
    untrack(() => { void loadMoves(); });
  });
  const showMoves = $derived(panel.view === 'overlaps' && tab === 'moves');

  const cards = $derived(panel.view === 'overlaps' && !showMoves ? overlapCards(panel.overlaps, rows) : []);
  const p = $derived(panel.preview && !panel.preview.problem ? panel.preview : null);
  const bars = $derived(p && !q ? folderBars(p.folders) : { rows: [], max: 0 });
  const routes = $derived(p && !q ? moveRoutes(p) : []);
  const moving = $derived(routes.reduce((n, r) => n + r.rows.length, 0));
  // the backend's headline only when no number or list says the change (rename of an empty folder, nothing changes)
  const headlineOnly = $derived(!!p && !q && !p.new_downloads && !p.stopped && !bars.rows.length && !moving
    && !p.unknown.length);
  const hasFill = $derived((panel.view === 'overlaps' && (showMoves ? true : cards.length > 0)) || !!(p && q)
    || !!(p && routes.length));
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
      <Segmented label="What the panel shows" value={tab} onchange={ontab} test="panel-tab"
        options={[{ key: 'overlaps', label: 'In several playlists', count: panel.overlaps.length },
          { key: 'moves', label: 'Recent moves', count: moves?.total ?? null }]} />
      {#if showMoves}
        {#if movesFail}
          <ProblemCard compact kind={movesFail.kind} message={movesFail.message} onretry={loadMoves} />
        {:else if moves && !moves.batches.length}
          <Surface kind="card" data-test="moves-empty"><EmptyState title={NO_MOVES_YET} action={null} /></Surface>
        {/if}
      {:else}
        <StatCard value={panel.overlaps.length} unit={panel.overlaps.length === 1 ? 'track' : 'tracks'}
          label={panel.overlaps.length ? 'in several playlists, downloaded once' : 'in several playlists'} data-test="overlaps" />
      {/if}
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
        {#if q && offers.length}
          <Surface kind="list" data-test="rename-offers">
            {#each offers as o (o.from)}
              <ToggleRow item={{ key: o.from, label: o.option, on: o.offered && q.renameOn.has(o.from) }}
                sub={offerDetail(o, leaving)} disabled={!o.offered || leaving} title={o.offered ? undefined : o.why_not ?? undefined}
                onchange={(k) => { if (question) question = toggleRename(question, k); }} test="rename-{o.from}" />
            {/each}
          </Surface>
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
  {#if showMoves}
    {#if moves?.batches.length}
      <Surface kind="list" style="--row-cols: minmax(0, 1fr) var(--w-row-action)" grow={{ rows: moves.batches.length, tall: true }}
        data-test="recent-moves">
        {#each moves.batches as b (b.id)}
          <ListRow wrap title={b.title} data-batch={b.id} test="batch">
            {#snippet name()}{b.title}{/snippet}
            {#snippet sub()}{runWhen(b.at)} · {b.undoable ? b.summary : NOTHING_LEFT}{/snippet}
            {#snippet trailing()}
              <Button size="sm" disabled={!b.undoable} title={b.undoable ? undefined : NOTHING_LEFT}
                onclick={() => onundobatch(b.id)} data-test="batch-undo-{b.id}">Undo</Button>
            {/snippet}
          </ListRow>
        {/each}
      </Surface>
    {/if}
  {:else if p && q}
    <TidyList label={saveHeadline(saveFileCount(q))} rows={qShown} ticks={q.ticks} folders={folderRows(q)}
      dim={panel.dim} test="save-files"
      ontick={(r) => { if (question) question = { ...question, ticks: toggleTick(question.ticks, r) }; }}
      ongroup={() => { if (question && qGroups) question = { ...question, ticks: toggleGroup(question.ticks, qGroups.yours) }; }} />
  {:else if panel.view === 'overlaps' && cards.length}
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
  {#if p && q}
    {#if qCount}
      <NoteCard tone="warn" title={qCount} class={panel.dim ? 'dim' : ''} data-test="save-warning">
        {[R1, R2, U1].join(' ')}</NoteCard>
    {/if}
    <div class="safe" class:dim={panel.dim} data-test="checklist">
      <Hint wrap text={LEAVE_HINT} data-test="leave-hint" />
      {#if p.checklist.length}<InfoTip label="What this change keeps safe">{p.checklist.join('. ')}.</InfoTip>{/if}
    </div>
  {:else if p && p.checklist.length}
    <!-- what stays safe, in one line above Save (the tracks list keeps the height); the full list behind the ⓘ -->
    <div class="safe" class:dim={panel.dim} data-test="checklist">
      <Hint text="Nothing is deleted · at the next sync" />
      <InfoTip label="What this change keeps safe">{p.checklist.join('. ')}.</InfoTip>
    </div>
  {/if}
{/snippet}

{#snippet foot()}
  {#if p && q}
    <!-- the main action sits by Undo, as in every foot; the long "leave" save gets the full width above (1100 px) -->
    <div class="foot two">
      <WriteButton wide busy={saving} disabled={panel.dim} title={panel.dim ? 'Working out what changes…' : undefined}
        onpointerenter={() => (leaving = true)} onpointerleave={() => (leaving = false)}
        onfocus={() => (leaving = true)} onblur={() => (leaving = false)}
        onclick={() => question && onsave(saveFiles(question, 'leave'), [])} data-test="save-leave">Save, leave files where they are</WriteButton>
      <div class="line">
        <Button disabled={saving} onclick={onundo} data-test="undo">Undo</Button>
        <WriteButton wide variant="filled" busy={saving} disabled={panel.dim || !qMoving}
          title={panel.dim ? 'Working out what changes…' : !qMoving ? 'Tick the files to move first.' : undefined}
          onclick={() => question && onsave(saveFiles(question, 'move'), saveItems(question))} data-test="save-move">Save and move the files</WriteButton>
      </div>
    </div>
  {:else}
    <div class="foot">
      <Button disabled={!dirty || saving} onclick={onundo} data-test="undo">Undo</Button>
      <WriteButton wide variant="filled" busy={saving} disabled={!dirty || !panel.saveAllowed || panel.view === 'loading'}
        title={!dirty ? 'Nothing to save yet.' : !panel.saveAllowed ? 'Fix the problem first.'
          : panel.view === 'loading' ? 'Working out what changes…' : undefined}
        onclick={() => onsave(null, [])} data-test="save">Save</WriteButton>
    </div>
  {/if}
{/snippet}

<Panel {head} fill={hasFill ? fill : undefined} {after} {foot} />

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
  /* a Hint that wraps fills the line and puts the ⓘ at the edge: room for the ⓘ's 22 px hit ring (margin -2 px) */
  .safe:has(> :global(.hint.wrap)) { padding-right: 2px; }
  .foot { display: flex; gap: var(--s-2); }
  .foot.two { flex-direction: column; }
  .line { display: flex; gap: var(--s-2); }
</style>
