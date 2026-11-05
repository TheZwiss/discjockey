<script lang="ts">
  // The line under a playlist's folder name (sources round problem 7), on Playlists' rows and Setup's: the service's
  // own logo, its Tip the service's name (the name in words left the line: at 1100 it cut the owner, and the logo is
  // quicker to read, as in the Library sidebar), then the line's words (changeModel's infoLine / setupLine). A problem
  // keeps its logo and its red words. `before`: words that lead the line after the logo (the unsaved change's
  // "gets 27 more ·").
  import type { Snippet } from 'svelte';
  import { ServiceMark, logoOf, tip } from '$lib/components';
  import type { PlaylistService } from '$lib/bridge/types';
  import { PLAYLIST_SERVICE_NAMES } from '$lib/copy';

  let { service, text, tone = 'muted', before, test }: {
    service: PlaylistService; text: string; tone?: 'muted' | 'bad'; before?: Snippet; test?: string;
  } = $props();
</script>

<span class="mark" use:tip={PLAYLIST_SERVICE_NAMES[service]} data-test={test}><ServiceMark service={logoOf(service)}
  label={PLAYLIST_SERVICE_NAMES[service]} /></span>{@render before?.()}<span class:bad={tone === 'bad'}>{text}</span>

<style>
  /* in the row's one cut line: the 14 px logo sits on the text's middle, 6 px before the words (AddRow's found line) */
  .mark { display: inline-flex; vertical-align: -2px; margin-right: 6px; }
  .bad { color: var(--q-weak); }
</style>
