<script lang="ts">
  // The folds below the plan (spec §8), each a list Surface whose head is its fold button: "Never download" (with
  // Download again), tracks that left the playlists, tracks with more than one file, and the planner's notes. The
  // count and what it means sit in the head's summary; each track row names its playlist on a second line, so no
  // width hides it.
  // One grid with the plan above (spec §11, "one grid"): the rows keep the plan's 52 px lead, with an empty slot
  // where the tick would be, so every cover sits under its fold's label and every name under the plan's names. The
  // notes start on the label's line too.
  import { Button, Cover, ListRow, Surface } from '$lib/components';
  import type { PreviewAction, SyncPreview } from '$lib/bridge/types';
  import { artistTitle, plural } from '$lib/format';

  let { preview, busy, blocked, onagain }: {
    preview: SyncPreview;
    /** the track whose "Download again" runs */
    busy: string | null;
    /** why "Download again" can't be used right now, else null */
    blocked: string | null;
    onagain: (a: PreviewAction) => void;
  } = $props();

  // lead (tick slot + 8 + cover 28) · name + playlist · Download again (every row has the same button, so its column
  // is one width)
  const NEVER_COLS = '--row-cols: 52px minmax(0, 1fr) max-content';
  const PLAIN_COLS = '--row-cols: 52px minmax(0, 1fr)';
</script>

{#snippet lead(id: string, url: string | null)}<span class="slot"></span><Cover {url} seed={id} size={28} />{/snippet}

<div class="folds">
  {#if preview.never.length}
    <Surface kind="list" foldable open={false} label="Never download"
      summary="{plural(preview.never.length, 'track')} · your choice, the sync skips them" style={NEVER_COLS}
      data-test="sync-never-fold">
      {#each preview.never as a (a.track_id)}
        {#snippet cover()}{@render lead(a.track_id, a.cover_url)}{/snippet}
        {#snippet name()}{artistTitle(a.artist, a.title)}{/snippet}
        {#snippet sub()}{a.folder}{/snippet}
        {#snippet again()}
          <Button size="sm" variant="secondary" busy={busy === a.track_id} disabled={!!blocked && busy !== a.track_id}
            title={blocked ?? undefined} onclick={() => onagain(a)} data-test="sync-download-again">Download again</Button>
        {/snippet}
        <ListRow lead={cover} {name} {sub} trailing={again} title={artistTitle(a.artist, a.title)} test="sync-never-row"
          data-track={a.track_id} />
      {/each}
    </Surface>
  {/if}
  {#if preview.dropped.length}
    <Surface kind="list" foldable open={false} label="Left your playlists"
      summary="{plural(preview.dropped.length, 'track')} · their files stay" style={PLAIN_COLS} data-test="sync-dropped">
      {#each preview.dropped as x (x.track_id)}
        {#snippet cover()}{@render lead(x.track_id, null)}{/snippet}
        {#snippet name()}{artistTitle(x.artist, x.title)}{/snippet}
        {#snippet sub()}{x.folder}{/snippet}
        <ListRow lead={cover} {name} {sub} title={artistTitle(x.artist, x.title)} />
      {/each}
    </Surface>
  {/if}
  {#if preview.ambiguous.length}
    <Surface kind="list" foldable open={false} label="More than one file"
      summary="{plural(preview.ambiguous.length, 'track')} · the sync leaves {preview.ambiguous.length === 1 ? 'it' : 'them'} alone"
      style={PLAIN_COLS} data-test="sync-ambiguous">
      {#each preview.ambiguous as x (x.track_id)}
        {#snippet cover()}{@render lead(x.track_id, null)}{/snippet}
        {#snippet name()}{artistTitle(x.artist, x.title)}{/snippet}
        {#snippet sub()}{x.folder}{/snippet}
        <ListRow lead={cover} {name} {sub} title={artistTitle(x.artist, x.title)} />
      {/each}
    </Surface>
  {/if}
  {#if preview.notes.length}
    <Surface kind="list" foldable open={false} label="Notes" summary={plural(preview.notes.length, 'note')}
      data-test="sync-notes">
      {#each preview.notes as n, i (i)}<p class="note">{n}</p>{/each}
    </Surface>
  {/if}
</div>

<style>
  .folds { display: flex; flex-direction: column; gap: var(--s-3); }
  .folds:empty { display: none; }
  /* the tick's 16 px (Tick), left empty: these rows have nothing to tick */
  .slot { flex: none; width: 16px; }
  /* the label's line: the 16 px inset + the chevron's 16 px box + its gap */
  .note { margin: 0; padding: var(--s-3) var(--s-4) var(--s-3) calc(var(--s-4) + 16px + var(--s-2));
    color: var(--text-muted); font-size: var(--fs-small); }
</style>
