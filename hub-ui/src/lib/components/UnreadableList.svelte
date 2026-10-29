<script lang="ts">
  // The files the import couldn't read (plan library stage 4, W6), shared by Settings → Watched folders and Setup:
  // a foldable list headed "Couldn't read (n)"; each row the file's name over "{path}: {reason}", wrapping, since both
  // must be read whole; "Tried again at the next import." closes the list (beside the label it cut the label short
  // in a 320 px panel). Open while it is short, folded once it
  // would push the rest away (it sits in a Panel's `after`, which never shrinks). Nothing to show: nothing rendered.
  import type { UnreadableFile } from '$lib/bridge/types';
  import { shortPath } from '$lib/musicFolder';
  import Hint from './Hint.svelte';
  import ListRow from './ListRow.svelte';
  import StatusMark from './StatusMark.svelte';
  import Surface from './Surface.svelte';
  import { UNREADABLE_HINT, unreadableLabel, unreadableRow } from './watchedFoldersModel';

  /** up to this many rows the list starts open */
  const OPEN_UP_TO = 5;

  let { files, test = 'unreadable' }: { files: UnreadableFile[]; test?: string } = $props();

  const fileName = (p: string) => p.split('/').filter(Boolean).at(-1) ?? p;
</script>

{#if files.length}
  <Surface kind="list" label={unreadableLabel(files.length)} foldable
    open={files.length <= OPEN_UP_TO} tone="warn" style="--row-cols: 16px minmax(0, 1fr)" data-test={test}>
    {#each files as u (u.path)}
      <ListRow wrap title={u.path}>
        {#snippet lead()}<StatusMark tone="warn" />{/snippet}
        {#snippet name()}{fileName(u.path)}{/snippet}
        {#snippet sub()}{unreadableRow({ ...u, path: shortPath(u.path) })}{/snippet}
      </ListRow>
    {/each}
    <div class="foot"><Hint text={UNREADABLE_HINT} /></div>
  </Surface>
{/if}

<style>
  .foot { display: flex; align-items: center; min-height: var(--h-list-row); padding: 0 var(--s-4); min-width: 0; }
</style>
