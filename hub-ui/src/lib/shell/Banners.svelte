<script lang="ts">
  // Banners push the page down; they never cover it. A view whose body says the same state where it bites takes the
  // banner over through `bannersSaidInBody` (lib/stores/shell.ts), the one way a page does it: Sync's before-start
  // view says the console only while it shows Start with its Hint "A sync is running in the terminal", and the
  // playlists read state with its card above the plan (spec §11, Task 10A). Every other view, Sync's up-to-date and empty
  // ones too, keeps the banner, so a view never loses the warning (final review I1).
  import { hub, readBlock } from '../stores/hub';
  import { bannersSaidInBody } from '../stores/shell';
  import { BANNER, problemCopy } from '../copy';
  import Banner from '../components/Banner.svelte';
  // one wording and one link per state on every page: the same copy Sync's card shows
  const readCopy = $derived($readBlock ? problemCopy($readBlock.kind, { service: $readBlock.service }) : null);
</script>

{#if $hub.console_running && !$bannersSaidInBody.console}<div data-test="banner-console"><Banner tone="warn" text={BANNER.console} /></div>{/if}
{#if readCopy && !$bannersSaidInBody.readStatus}
  <div data-test="banner-read-status"><Banner tone="info" text={readCopy.title}
    action={readCopy.action?.href ? { label: readCopy.action.label, href: readCopy.action.href } : undefined} /></div>
{/if}
