<script lang="ts">
  // The browser column's contents (plan library stage 5, D4; notes N2–N4): Library's collections beside the rail, in
  // the frame's material. This is step A4's form, the collections the sidebar's old Library group listed, each on one
  // line: All tracks and Not in a playlist on top, then Playlists (playlists.txt order, a switched-off one at half
  // strength, the service's own logo) and Folders (the Library folders no playlist uses). A5 builds the column proper
  // here (the filter field, folding and sticky section heads, the A–Z order, the drag edge); Sidebar.svelte places it
  // and moves it.
  import { hub } from '../stores/hub';
  import { route, link, libraryHref } from '../router';
  import { NOT_IN_PLAYLIST } from '../bridge/types';
  import { ServiceMark, tip } from '../components';

  const side = $derived($hub.sidebar);
  const at = $derived($route.name === 'library' ? ($route.params.folder ?? null) : undefined);
  const rows = $derived([
    { key: null, name: 'All tracks', n: side?.all_tracks ?? null },
    ...(side && side.not_in_playlist > 0 ? [{ key: NOT_IN_PLAYLIST, name: 'Not in a playlist', n: side.not_in_playlist }] : []),
  ]);
</script>

<div class="list" data-test="browser">
  {#each rows as v (v.key ?? '')}
    <a class="row" class:on={at === v.key} href={libraryHref(v.key)} use:link aria-current={at === v.key ? 'page' : undefined}
      data-test={v.key === null ? 'browser-all' : 'browser-unlisted'}>
      <span class="t">{v.name}</span>{#if v.n !== null}<span class="n num">{v.n}</span>{/if}
    </a>
  {/each}

  {#if side?.playlists.length}
    <div class="sh">Playlists <span class="num">{side.playlists.length}</span></div>
    {#each side.playlists as f, i (`${i}:${f.ref}`)}
      <a class="row" class:on={at === f.name} class:off={!f.enabled} href={libraryHref(f.name)} use:link
        use:tip={{ text: f.enabled ? f.name : `${f.name}\nSwitched off: its files stay, nothing new downloads`, cut: '.t' }}
        aria-current={at === f.name ? 'page' : undefined}>
        <span class="lead">{#if f.service}<ServiceMark service={f.service} />{/if}</span>
        <span class="t">{f.name}</span><span class="n num">{f.tracks}</span>
      </a>
    {/each}
  {/if}

  {#if side?.library_folders.length}
    <div class="sh">Folders</div>
    {#each side.library_folders as f (f.folder)}
      <a class="row" class:on={at === f.folder} href={libraryHref(f.folder)} use:link
        use:tip={{ text: `Library › ${f.folder}\nNo playlist uses it` }} aria-current={at === f.folder ? 'page' : undefined}>
        <span class="lead"><svg viewBox="0 0 14 14" aria-hidden="true"><path d="M1.6 3.6c0-.6.4-1 1-1h2.9l1.3 1.4h4.6c.6 0 1 .4 1 1v5.9c0 .6-.4 1-1 1H2.6c-.6 0-1-.4-1-1z"/></svg></span>
        <span class="t">{f.folder}</span><span class="n num">{f.tracks}</span>
      </a>
    {/each}
  {/if}
</div>

<style>
  .list { display: flex; flex-direction: column; gap: 2px; min-height: 0; flex: 1; overflow-y: auto; padding: 0 8px 10px; }
  .row { display: flex; align-items: center; gap: 9px; height: var(--h-ctl); flex-shrink: 0; padding: 0 var(--s-2);
    color: var(--text-nav); border-radius: var(--r-nav); text-decoration: none; white-space: nowrap; min-width: 0; }
  .row:hover { color: var(--text); background-color: var(--ctl-hover); text-decoration: none; }
  .row:not(.on):hover { transition: background-color var(--t-hover) var(--ease), color var(--t-hover) var(--ease); }
  .row.on { color: var(--text-strong); background-image: linear-gradient(var(--nav-on-bg), var(--nav-on-bg)); }
  .row:active:not(.on) { background-color: var(--ctl-press); transition: none; }
  .lead { width: 14px; height: 14px; flex: none; display: grid; place-items: center; }
  .lead svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 1.2; stroke-linejoin: round; opacity: .8; }
  .t { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .n { flex: none; margin-left: var(--s-1); color: var(--text-label); font-size: var(--fs-label); }
  .on .n { color: var(--text-muted); }
  .off { opacity: .5; }
  .sh { display: flex; align-items: center; gap: 6px; height: 28px; flex: none; margin-top: var(--s-2); padding: 0 var(--s-2);
    color: var(--text-label); font-size: var(--fs-small); font-weight: var(--fw-semi); }
  .sh .num { font-weight: normal; }
</style>
