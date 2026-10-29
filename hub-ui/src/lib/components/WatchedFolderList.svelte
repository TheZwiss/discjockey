<script lang="ts">
  // The watched folders as one list (plan library stage 4, W3), shared by Settings → Watched folders and Setup's
  // "Your existing music". Each row: its state as colour plus shape (✓ readable, ! offline, a spinner while it is
  // worked on) · the folder's name over its state line and, for an import folder, where it is (one line, the middle of a
  // long path gives way to "…" and the folder's own name stays; the full path is the tooltip; the × and the dialog
  // add the short path when two folders share a name) · its files, right-aligned · × Remove (the Library is always watched, so its slot stays
  // empty and the counts line up). Presentational: the page's WatchedFoldersFlow reads and changes the folders.
  // `grow`: the list fills a Panel's `fill` and scrolls inside (the folders grow over time).
  import type { WatchedFolderRow } from '$lib/bridge/types';
  import Button from './Button.svelte';
  import ListRow from './ListRow.svelte';
  import Skeleton from './Skeleton.svelte';
  import Spinner from './Spinner.svelte';
  import StatusMark from './StatusMark.svelte';
  import Surface from './Surface.svelte';
  import { count, folderLabel, folderLine, folderMark, pathParts } from './watchedFoldersModel';

  let { folders, label = 'Watched folders', onremove, removeOff = null, removing = null, grow = false,
    test = 'watched-folders' }: {
    folders: WatchedFolderRow[] | null; label?: string;
    /** × on an import folder's row; none: the list is shown only */
    onremove?: (f: WatchedFolderRow) => void;
    /** why Remove can't be used right now (another change runs): its tooltip, the button off */
    removeOff?: string | null;
    /** the folder whose removal is asked or under way: its button is off meanwhile (a spinner would widen the slot) */
    removing?: number | null;
    grow?: boolean; test?: string;
  } = $props();

  const rows = $derived(folders ?? []);
</script>

<Surface kind="list" {label} style="--row-cols: 16px minmax(0, 1fr) calc(var(--w-row-action) + var(--s-2) + var(--h-ctl-sm))"
  grow={grow ? { rows: Math.max(1, rows.length), tall: true } : undefined} data-test={test}>
  {#if !folders}
    <div class="wait"><Skeleton lines={2} /></div>
  {:else}
    {#each rows as f (f.id)}
      {@const mark = folderMark(f)}
      <ListRow height={52} wrap title={f.path} test="{test}-row-{f.kind === 'library' ? 'library' : f.id}"
        data-state={f.state}>
        {#snippet lead()}{#if mark === 'working'}<span class="spin"><Spinner size={12} label={folderLine(f)} /></span>
          {:else}<StatusMark tone={mark} quiet={mark === 'good'} />{/if}{/snippet}
        {#snippet name()}{f.name}{/snippet}
        {#snippet sub()}<span class="line">{folderLine(f)}</span>{#if f.kind === 'import'}{@const p = pathParts(f.path)}<span class="path"><span class="head">{p.head}</span><span class="tail">{p.tail}</span></span>{/if}{/snippet}
        {#snippet trailing()}
          <span class="files" title="{count(f.files)} {f.files === 1 ? 'file' : 'files'}">{count(f.files)}</span>
          <span class="act">{#if f.kind === 'import' && onremove}
            <Button variant="icon" size="sm" destructive aria-label="Remove {folderLabel(f, rows)}"
              title={removeOff ?? `Remove ${folderLabel(f, rows)}`}
              disabled={!!removeOff || removing === f.id} onclick={() => onremove?.(f)} data-test="{test}-remove-{f.id}">
              <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7" /></svg>
            </Button>
          {/if}</span>
        {/snippet}
      </ListRow>
    {/each}
  {/if}
</Surface>

<style>
  .wait { padding: var(--s-3) var(--s-4); }
  .spin { display: inline-grid; place-items: center; width: 16px; height: 16px; color: var(--text-muted); }
  /* the state line and where the folder is, each its own line (a 320 px panel has no room for both on one). The state
     line is words and wraps between them; the path never wraps */
  .line, .path { display: block; }
  .line { white-space: normal; overflow-wrap: normal; }
  /* the path on one line: the head gives way first ("/Volumes/…/Music"), the folder's own name stays whole unless
     it alone is wider than the column */
  .path { display: flex; min-width: 0; color: var(--text-label); white-space: nowrap; }
  .head { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .tail { flex: none; max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
  /* the trailing cell: the files in the row-action slot, right-aligned, then the 26 px Remove slot (empty for the
     Library), so the counts line up down the list */
  .files { width: var(--w-row-action); text-align: right; overflow: hidden; text-overflow: ellipsis;
    color: var(--text-label); }
  .act { display: inline-grid; place-items: center; width: var(--h-ctl-sm); flex: none; }
</style>
