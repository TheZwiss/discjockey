<script lang="ts">
  // The picked import folder's crates as switches (plan library stage 5, B7; mockup library-browser `#settings`,
  // `#settings-many`): on = a row in the sidebar's Folders. A folder with more crates than the sidebar holds (D8: more
  // than 25, all hidden until switched on) says so in a Hint under the group (the mockup's note card above it pushed
  // the group below its minimum at 1100 × 700, and the panel scrolled around a list that scrolls itself); its group searches by name and by the folders a
  // crate sits in, and All waits for a search that narrows it (312 at once would bring the flood back), None stays.
  // A switch saves at once (a brief save, D15, also while a sync runs): the rows show the new state straight away,
  // and a refused save puts them back with a toast. The saves go one after the other and put back by crateSaves
  // (cratesModel). `reload` reads the folders again after a save that stored something, so the rows then show what is stored.
  import type { WatchedFolderRow } from '$lib/bridge/types';
  import { Hint, ToggleGroup } from '$lib/components';
  import { saveCratesShown } from '$lib/stores/hub';
  import { toasts } from '$lib/stores/toasts';
  import { ALL_MAX, crateItems, crateSaves, tooManyText } from './cratesModel';

  let { folder, reload, test = 'folders-crates' }:
    { folder: WatchedFolderRow; reload: () => Promise<void>; test?: string } = $props();

  let pending = $state<Record<string, boolean>>({});
  const items = $derived(crateItems(folder, pending));
  const save = crateSaves({
    folder: () => folder, send: saveCratesShown, reload: () => reload(), pending: (p) => { pending = p; },
    failed: () => toasts.show({ tone: 'problem', title: 'Couldn’t save that. Try again.' }),
  });
</script>

<ToggleGroup label="In the sidebar" {items} grow placeholder="Search folders in {folder.name}…"
  allMax={folder.too_many ? ALL_MAX : undefined} onchange={(key, on) => void save([key], on)}
  onall={(on, keys) => void save(keys, on)} {test} rowTest="{test}-row" />
{#if folder.too_many}<div class="many"><Hint text={tooManyText(folder)} wrap data-test="{test}-too-many" /></div>{/if}

<style>
  /* the panel body's flex item: keeps its lines (the group above gives way, never the words) */
  .many { flex: none; min-width: 0; }
</style>
