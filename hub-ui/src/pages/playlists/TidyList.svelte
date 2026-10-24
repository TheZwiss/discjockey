<script lang="ts">
  // The files a tidy-up or a save could move, as one anchored list in three groups (plan library stage 2, 6.2/6.3):
  // the files that move by default (no head: the list's label says what they are), "You put these here" with its one
  // control "Put these in playlist order too" as the group's first row (its tick sits in the ticks' column, shows a
  // dash while only some are ticked), then "Can't move" with a yellow ! and the reason. In the save question a folder
  // renamed on disk is one row in place of its files. Each row: tick · cover · "Artist – Title" · from → to; the
  // folders and reasons wrap (they are read whole), long names end in "…".
  import { Cover, ListRow, ListSection, StatusMark, Surface, Tick } from '$lib/components';
  import { artistTitle } from '$lib/format';
  import type { TidyRow } from '$lib/bridge/types';
  import {
    CANT_MOVE, YOURS_CONTROL, YOURS_HEADER, folderName, groupState, groups, type FolderRow, type Ticks,
  } from './tidyModel';

  let { label, summary, rows, ticks, folders = [], ontick, ongroup, yoursHeader = YOURS_HEADER,
    yoursControl = YOURS_CONTROL, dim = false, test = 'tidy-list' }: {
    label: string; summary?: string; rows: TidyRow[]; ticks: Ticks; folders?: FolderRow[];
    ontick: (r: TidyRow) => void; ongroup: (rows: TidyRow[]) => void;
    yoursHeader?: string; yoursControl?: string; dim?: boolean; test?: string;
  } = $props();

  const g = $derived(groups(rows));
  const yoursState = $derived(groupState(ticks, g.yours));
  // rows of the grow measure: files, folder rows, the yours head + control, the can't-move head
  const count = $derived(rows.length + folders.length + (g.yours.length ? 2 : 0) + (g.skipped.length ? 1 : 0));
</script>

<!-- a folder may break after a "/" (Powertrance_2026/ not_lossless), never inside a name; the arrow is spaced -->
{#snippet place(f: string)}
  {#each folderName(f).split('/') as part, i (i)}{#if i}/<wbr />{/if}{part}{/each}
{/snippet}
{#snippet route(from: string, to: string)}
  {@render place(from)} <span class="arrow" aria-label="to">→</span> {@render place(to)}
{/snippet}

{#snippet file(r: TidyRow)}
  {@const on = ticks.has(r.file_id)}
  <ListRow wrap off={!on} checked={on} onclick={() => ontick(r)} title={artistTitle(r.artist, r.title)}
    data-file={r.file_id} test="tidy-row">
    {#snippet lead()}<Tick {on} /><Cover url={r.cover_url} seed={r.track_id} size={28} />{/snippet}
    {#snippet name()}{artistTitle(r.artist, r.title)}{/snippet}
    {#snippet sub()}{@render route(r.from, r.to)}{/snippet}
  </ListRow>
{/snippet}

<Surface kind="list" {label} {summary} class={dim ? 'dim' : ''} style="--row-cols: 52px minmax(0, 1fr)"
  grow={{ rows: count, tall: true }} data-test={test}>
  {#each folders as f (f.from)}
    <ListRow wrap title="{f.from}, the whole folder" data-folder={f.from} test="tidy-folder">
      {#snippet lead()}<span class="gap"></span><span class="folder">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3">
          <path d="M2 4.5a1 1 0 0 1 1-1h3.2l1.3 1.5H13a1 1 0 0 1 1 1V12a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1z" /></svg></span>{/snippet}
      {#snippet name()}<span class="strong">{f.from}, the whole folder</span>{/snippet}
      {#snippet sub()}<span class="arrow" aria-label="to">→</span> {@render place(f.to)}{#if f.files}{` · ${f.files === 1 ? '1 file' : `${f.files} files`}`}{/if}{/snippet}
    </ListRow>
  {/each}
  {#each g.main as r (r.file_id)}{@render file(r)}{/each}
  {#if g.yours.length}
    <ListSection label={yoursHeader} summary={String(g.yours.length)} test="tidy-yours" />
    <ListRow checked={yoursState === 'all'} onclick={() => ongroup(g.yours)} title={yoursControl} test="tidy-yours-control">
      {#snippet lead()}<Tick on={yoursState === 'all'} mixed={yoursState === 'some'} />{/snippet}
      {#snippet name()}<span class="control">{yoursControl}</span>{/snippet}
    </ListRow>
    {#each g.yours as r (r.file_id)}{@render file(r)}{/each}
  {/if}
  {#if g.skipped.length}
    <ListSection label={CANT_MOVE} summary={String(g.skipped.length)} test="tidy-skipped" />
    {#each g.skipped as r (r.file_id)}
      <ListRow wrap title={artistTitle(r.artist, r.title)} data-file={r.file_id} test="tidy-skip">
        {#snippet lead()}<StatusMark tone="warn" /><Cover url={r.cover_url} seed={r.track_id} size={28} />{/snippet}
        {#snippet name()}{artistTitle(r.artist, r.title)}{/snippet}
        {#snippet sub()}<span class="reason">{r.skip?.text}</span>{/snippet}
      </ListRow>
    {/each}
  {/if}
</Surface>

<style>
  .arrow { color: var(--text-label); }
  .reason { color: var(--risk-notice); }
  .strong { color: var(--text-strong); font-weight: var(--fw-semi); }
  .control { color: var(--accent-text); font-weight: var(--fw-semi); }
  .gap { width: 16px; flex: none; }
  .folder { width: 28px; height: 28px; flex: none; display: grid; place-items: center; border-radius: var(--r-icon);
    border: var(--bw) solid var(--ctl-line); color: var(--text-muted); }
  :global([data-surface].dim) { opacity: var(--dim-locked); transition: opacity var(--t-state) var(--ease); }
</style>
