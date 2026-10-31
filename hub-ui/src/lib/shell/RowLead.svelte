<script lang="ts">
  // A collection row's 14 px lead (the browser column, the full sidebar's Favourites; browserModel's `Lead`): the
  // service's own logo for a playlist, the folder outline for a folder that stands on its own (a watched folder, a
  // pinned crate, a Library folder no playlist uses), the yellow "!" (StatusMark warn, the mark Settings and AwayTag
  // use for the same state) while a folder's drive is away, or nothing. Decorative: the row's words say it.
  import { ServiceMark, StatusMark } from '../components';
  import type { CollectionRow } from './browserModel';

  let { row, lead = row.lead }: { row: CollectionRow; lead?: CollectionRow['lead'] } = $props();
</script>

<span class="lead">
  {#if lead === 'service' && row.kind === 'playlist' && row.service}<ServiceMark service={row.service} />
  {:else if lead === 'warn'}<span class="warn"><StatusMark tone="warn" /></span>
  {:else if lead === 'folder'}<svg class="folder" viewBox="0 0 14 12" aria-hidden="true"><path
    d="M1.2 2.2c0-.6.4-1 1-1h3.1l1.4 1.5h5.1c.6 0 1 .4 1 1v6.9c0 .6-.4 1-1 1H2.2c-.6 0-1-.4-1-1z" /></svg>
  {/if}
</span>

<style>
  .lead { width: 14px; height: 14px; flex: none; display: grid; place-items: center; }
  /* the outline a little quieter than the name; full strength on the row on screen */
  .folder { width: 14px; height: 12px; fill: none; stroke: currentColor; stroke-width: 1.2; stroke-linejoin: round; opacity: .8; }
  :global(.on) > .lead .folder { opacity: 1; }
  .warn { display: grid; place-items: center; }
</style>
