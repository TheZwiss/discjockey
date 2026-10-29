<script lang="ts">
  // The watched folders as one list (plan library stage 4, W3), shared by Settings → Watched folders and Setup's
  // "Your existing music". Each row: its state as colour plus shape (✓ readable, ! offline, a spinner while it is
  // worked on) · the folder's name over its state line and where it is (wrapping: two folders may share a name, the
  // path tells them apart) · its files, right-aligned · × Remove (the Library is always watched, so its slot stays
  // empty and the counts line up). Presentational: the page's WatchedFoldersFlow reads and changes the folders.
  // `grow`: the list fills a Panel's `fill` and scrolls inside (the folders grow over time).
  import type { WatchedFolderRow } from '$lib/bridge/types';
  import { shortPath } from '$lib/musicFolder';
  import Button from './Button.svelte';
  import ListRow from './ListRow.svelte';
  import Skeleton from './Skeleton.svelte';
  import Spinner from './Spinner.svelte';
  import StatusMark from './StatusMark.svelte';
  import Surface from './Surface.svelte';
  import { count, folderLine, folderMark } from './watchedFoldersModel';

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
        {#snippet sub()}<span class="line">{folderLine(f)}</span>{#if f.kind === 'import'}<span class="path">{#each shortPath(f.path).split('/') as part, i (i)}{#if i}/<wbr />{/if}{part}{/each}</span>{/if}{/snippet}
        {#snippet trailing()}
          <span class="files" title="{count(f.files)} {f.files === 1 ? 'file' : 'files'}">{count(f.files)}</span>
          <span class="act">{#if f.kind === 'import' && onremove}
            <Button variant="icon" size="sm" destructive aria-label="Remove {f.name}" title={removeOff ?? `Remove ${f.name}`}
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
  /* the state line and where the folder is, each its own line, so the path is read whole */
  .line, .path { display: block; }
  /* a long path breaks after a "/" (the <wbr>s), inside a name only when a single name is wider than the column */
  .path { color: var(--text-label); overflow-wrap: break-word; word-break: normal; }
  /* the trailing cell: the files in the row-action slot, right-aligned, then the 26 px Remove slot (empty for the
     Library), so the counts line up down the list */
  .files { width: var(--w-row-action); text-align: right; overflow: hidden; text-overflow: ellipsis;
    color: var(--text-label); }
  .act { display: inline-grid; place-items: center; width: var(--h-ctl-sm); flex: none; }
</style>
