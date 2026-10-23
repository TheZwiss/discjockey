<script lang="ts">
  // The page header (design system §5a): one block for every page, so the title, its status line, the page's actions
  // and Spotify's status sit in the same place with the same look everywhere (§12: a shared element is placed by its
  // block, never by the page).
  //   [title · sub] ............................ [actions] [Spotify status · Read Spotify]
  // - It spans its frame's content box and adds no padding of its own: the list area's content in ListPanelFrame (never
  //   the panel, which has its own head), the 900 px column in ColumnFrame, the page's padding box on a plain page.
  //   So the title starts where the rows start and the last control ends where the rows end, at every window size.
  // - Title and sub share one baseline (a 22 px title and a 12 px line centred on each other sat 4 px off it); both
  //   end in "…" instead of wrapping or pushing the controls out.
  // - `spotify`: the fixed slot at the right edge, used by the pages whose content comes from the last Spotify read
  //   (Dashboard, Sync, To-do). `spotifyInBody`: the page shows the read in progress and Spotify problems as cards in
  //   its body (Sync before the start), so the slot keeps only its control and the state is said once.
  // - `actions`: the page's own controls (search, Full report), left of the Spotify slot.
  // - `spotifyState`: the gallery only, shows a given Spotify state instead of the live one.
  import type { Snippet } from 'svelte';
  import SpotifyStatus from './SpotifyStatus.svelte';
  import type { SpotifyStatus as SpotifyState } from '../bridge/types';
  let { title, sub, actions, spotify = false, spotifyInBody = false, spotifyState }:
    { title: string; sub?: string; actions?: Snippet; spotify?: boolean; spotifyInBody?: boolean;
      spotifyState?: SpotifyState | null } = $props();
</script>

<header class="ph" data-page-header>
  <div class="lead">
    <h1 {title}>{title}</h1>
    {#if sub}<span class="sub" title={sub} data-test="page-sub">{sub}</span>{/if}
  </div>
  {#if actions || spotify}
    <div class="trail">
      {#if actions}<div class="actions">{@render actions()}</div>{/if}
      {#if spotify}<SpotifyStatus inBody={spotifyInBody} status={spotifyState} />{/if}
    </div>
  {/if}
</header>

<style>
  /* min-height = --h-btn, room for a control or the 22 px title's line box, so the header keeps its height
     whether or not it holds controls, and content below starts at the same y on every page */
  /* baseline: the slot's 12 px line and the controls' labels sit on the title's baseline (centred, they sat 3.8 px
     above it; Apple typography: one line, one baseline) */
  .ph { display: flex; align-items: baseline; gap: var(--s-4); min-height: var(--h-btn); min-width: 0; flex: none; }
  .lead { display: flex; align-items: baseline; gap: var(--s-3); min-width: 0; flex: 1 1 auto; }
  h1 { font-size: var(--fs-h1); white-space: nowrap; min-width: 0;
    overflow: hidden; text-overflow: ellipsis; flex: 0 1 auto; }
  /* long folder names: title and sub shorten with … instead of wrapping or pushing the controls out; the sub gives
     way first */
  .sub { color: var(--text-label); font-size: var(--fs-small); white-space: nowrap; min-width: 0; overflow: hidden;
    text-overflow: ellipsis; flex: 0 3 auto; }
  .trail { flex: none; display: flex; align-items: center; gap: var(--s-4); }
  .actions { display: flex; align-items: center; gap: var(--s-2); }
</style>
