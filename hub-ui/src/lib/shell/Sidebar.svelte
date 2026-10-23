<script lang="ts">
  // Spec §4 / mockup layout.html option B: brand, the five areas, "Library" with every folder, Settings at the bottom;
  // while the player bar is hidden, its Now playing row above Settings. The frame's material (--sidebar-bg) is painted
  // by App behind the sidebar and the foot together, so the L they form has no seam.
  import { hub } from '../stores/hub';
  import { route, link, libraryHref } from '../router';
  import { NOT_IN_PLAYLIST } from '../bridge/types';
  import { updateLink } from '../appUpdate';
  import { ExternalLink } from '../components';
  import { player } from '../stores/player';
  import NowPlayingRow from './NowPlayingRow.svelte';

  const side = $derived($hub.sidebar);
  const update = $derived(updateLink($hub.app_update));
  const r = $derived($route);
  const libFolder = $derived(r.name === 'library' ? (r.params.folder ?? null) : undefined);
  const NAV = [
    { key: 'dashboard', href: '#/', glyph: '◉', label: 'Dashboard', also: ['runs'] },
    { key: 'sync', href: '#/sync', glyph: '⟳', label: 'Sync' },
    { key: 'todo', href: '#/todo', glyph: '✓', label: 'To-do' },
    { key: 'playlists', href: '#/playlists', glyph: '≡', label: 'Playlists' },
    { key: 'limits', href: '#/limits', glyph: '◔', label: 'Download limits' },
  ];
  const isOn = (n: (typeof NAV)[number]) => r.name === n.key || (n.also ?? []).includes(r.name);
</script>

<nav class="side chrome" aria-label="Main">
  <div class="head">
    <div class="brand"><span class="bdot" aria-hidden="true">●</span> Discjockey</div>
    <!-- a newer version is out (spec public-release §8): one quiet line that belongs to the brand, the link opens its page -->
    {#if update}<div class="update" data-test="update-line"><ExternalLink href={update.url}>{update.text}</ExternalLink></div>{/if}
  </div>
  {#each NAV as n (n.key)}
    <a class="nav" class:on={isOn(n)} href={n.href} use:link aria-current={isOn(n) ? 'page' : undefined} data-test="nav-{n.key}">
      <span class="g" aria-hidden="true"><span class="gl">{n.glyph}</span>{#if n.key === 'limits' && side?.limits_warning}<span class="warn"
        data-test="limits-dot"></span>{/if}</span><span class="t">{n.label}</span>
      {#if n.key === 'todo' && side && side.todo > 0}<span class="n num">{side.todo}</span>{/if}
    </a>
  {/each}

  <div class="grp caps">Library</div>
  <div class="folders">
    <a class="nav" class:on={libFolder === null} href="#/library" use:link data-test="nav-library">
      <span class="t">All tracks</span>{#if side}<span class="n num">{side.all_tracks}</span>{/if}
    </a>
    {#each side?.folders ?? [] as f (f.folder)}
      <a class="nav" class:on={libFolder === f.folder} class:dimmed={!f.in_playlists_txt} href={libraryHref(f.folder)} use:link
        title={f.in_playlists_txt ? f.folder : `${f.folder} · no longer in your playlists`}>
        <span class="t">{f.folder}</span><span class="n num">{f.tracks}</span>
      </a>
    {/each}
    {#if side && side.not_in_playlist > 0}
      <a class="nav" class:on={libFolder === NOT_IN_PLAYLIST} href={libraryHref(NOT_IN_PLAYLIST)} use:link>
        <span class="t">Not in a playlist</span><span class="n num">{side.not_in_playlist}</span>
      </a>
    {/if}
  </div>

  <!-- the hidden player bar, folded into the sidebar's foot (plan now-playing); the folders above give way -->
  <NowPlayingRow p={$player} />

  <a class="nav settings" class:on={r.name === 'settings'} href="#/settings" use:link data-test="nav-settings">
    <span class="g" aria-hidden="true"><span class="gl">⚙</span></span><span class="t">Settings</span>
  </a>
</nav>

<style>
  .side { width: var(--sidebar-w); flex-shrink: 0; border-right: var(--bw) solid var(--surface-line);
    padding: var(--s-4) 10px;
    display: flex; flex-direction: column; gap: 2px; min-height: 0; }
  .head { margin: 0 6px var(--s-3); min-width: 0; }
  .brand { color: var(--text-dim); font-weight: var(--fw-bold); white-space: nowrap; }
  /* the update line (spec public-release §8: "Discjockey 1.1 is available"): label size, the brand's left edge, the full
     sentence wrapped in balance into two even lines at 168 px; the nav moves down by it only while it shows, at most
     once per session */
  .update { font-size: var(--fs-label); line-height: 1.4; text-wrap: balance; }
  .bdot { font-size: var(--fs-small); }
  .nav { display: flex; align-items: center; gap: 9px; height: var(--h-ctl); flex-shrink: 0; padding: 0 var(--s-2);
    color: var(--text-nav);
    border-radius: var(--r-nav); text-decoration: none; white-space: nowrap; min-width: 0; }
  .nav:hover { color: var(--text); background-color: var(--ctl-hover); text-decoration: none; }
  /* hover fades in its fill and its text together (spec §6, --t-hover) and goes at once (exit faster than enter).
     The transition lives only on the hovered, unselected item, so selection never animates: the item that becomes
     selected and the one that stops being selected both change at once */
  .nav:not(.on):hover { transition: background-color var(--t-hover) var(--ease), color var(--t-hover) var(--ease); }
  /* the selected pill is a background image, which never transitions: it moves with the page at once */
  .nav.on { color: var(--text-strong); background-color: transparent;
    background-image: linear-gradient(var(--nav-on-bg), var(--nav-on-bg)); }
  /* held down: lit at once, no shrinking (it is a list item). The selected item is lit already, so it doesn't stack a
     second fill on its pill */
  .nav:active:not(.on) { background-color: var(--ctl-press); transition: none; }
  /* the mixed glyphs (◉ ⟳ ✓ ≡ ◔ ⚙) sit in one 14 px box, so they line up optically. Only the glyph is dimmed (.gl),
     not the warning dot beside it */
  .g { position: relative; width: 14px; text-align: center; flex-shrink: 0; font-size: var(--fs-small); }
  .gl { opacity: .8; }
  .warn { position: absolute; top: -1px; right: -4px; width: 6px; height: 6px; border-radius: var(--r-pill);
    background: var(--q-good); }  /* yellow = waiting or limited (spec §4) */
  .t { overflow: hidden; text-overflow: ellipsis; }
  .n { margin-left: auto; color: var(--text-label); font-size: var(--fs-label); padding-left: var(--s-1); }
  .dimmed { opacity: .5; }
  .grp { margin: var(--s-3) 7px var(--s-1); }
  .folders { display: flex; flex-direction: column; gap: 2px; overflow-y: auto; min-height: 0; flex: 1; }
  .settings { margin-top: var(--s-2); }
</style>
