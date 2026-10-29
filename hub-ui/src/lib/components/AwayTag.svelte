<script lang="ts">
  // Why a track's file isn't there to play, said in a list row (Library's table, library stage 4 fix K): the warn mark
  // (the `!` a watched folder's row shows for the same state) and the panel's short words, "Offline" or "Folder not
  // found"; the panel's whole line is the tooltip ("Offline: connect the drive"). Whole, never cut: the row's title
  // gives way first. A dim alone already means something else (a downloaded song that left every playlist), so an away
  // row always carries this tag.
  import type { FileState } from '../bridge/types';
  import { FILE_STATE_TAG, FILE_STATE_WORDS } from '../format';
  import StatusMark from './StatusMark.svelte';

  let { state, test }: { state: Exclude<FileState, 'here'>; test?: string } = $props();
</script>

<span class="away" title={FILE_STATE_WORDS[state]} data-state={state} data-test={test}>
  <StatusMark tone="warn" /><span class="word">{FILE_STATE_TAG[state]}</span>
</span>

<style>
  .away { display: inline-flex; flex: none; align-items: center; gap: var(--s-1); color: var(--text-muted);
    font-size: var(--fs-small); white-space: nowrap; }
</style>
