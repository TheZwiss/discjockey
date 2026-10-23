<script lang="ts">
  // Shell (spec §4, mockup layout.html option B): sidebar | content (banners on top, page below) | activity bar.
  import type { Component } from 'svelte';
  import { route, go } from '$lib/router';
  import { pageFor, type PageProps } from './pages/registry';
  import { hubSyncRunning, hub } from '$lib/stores/hub';
  import { musicGate } from '$lib/musicFolder';
  import { attachAudio } from '$lib/stores/player';
  import { onEvent } from '$lib/bridge/events';
  import { toasts } from '$lib/stores/toasts';
  import { clearReady } from '$lib/ready';
  import Sidebar from '$lib/shell/Sidebar.svelte';
  import ActivityBar from '$lib/shell/ActivityBar.svelte';
  import Banners from '$lib/shell/Banners.svelte';
  import ToastHost from '$lib/shell/ToastHost.svelte';
  import ErrorBoundary from '$lib/shell/ErrorBoundary.svelte';
  import ConfirmHost from '$lib/components/ConfirmHost.svelte';
  import MusicMissing from '$lib/shell/MusicMissing.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';

  const entry = $derived(pageFor($route.name));
  let Page = $state<Component<PageProps> | null>(null);
  let loadedKey = $state<string | null>(null);
  let failed = $state(false);
  $effect(() => {
    const e = entry;
    if (loadedKey === e.key) return;
    clearReady();
    failed = false;
    let live = true;
    e.load().then((c) => { if (live) { Page = c; loadedKey = e.key; } }).catch(() => { if (live) failed = true; });
    return () => { live = false; };
  });
  // The music folder (spec public-release §4): pages wait for the first setup answer, so none asks for library data
  // that isn't there. `missing` shows its own screen instead of every page; `setup` (no folder chosen yet) keeps the
  // user in Setup, whose first step chooses it.
  const gate = $derived(musicGate($hub.setup));
  const held = $derived(!$hub.booted || (gate === 'setup' && $route.name !== 'setup'));
  $effect(() => {
    if (gate === 'setup' && $route.name !== 'setup' && location.hash !== '#/setup/music') {
      void go('/setup/music', { replace: true });
    }
  });
  const chrome = $derived(entry.chrome === 'app' && gate !== 'missing');
  const showActivity = $derived(chrome && $hubSyncRunning && $route.name !== 'sync');

  let audio: HTMLAudioElement | undefined = $state();
  $effect(() => (audio ? attachAudio(audio) : undefined));

  // A dropped file that no track on screen can take: say so (the To-do page shows its own drops inline).
  $effect(() => onEvent((e) => {
    if (e.type !== 'FileDropped') return;
    if (e.track_id === null || (!e.readable && $route.name !== 'todo')) {
      toasts.show({ tone: 'problem', title: e.readable ? 'Select a track first.' : "Can't read this file.", body: e.message });
    }
  }));

  let FakeToolbar = $state<Component | null>(null);
  if (import.meta.env.VITE_FAKE === '1') {
    import('$lib/dev/FakeToolbar.svelte').then((m) => (FakeToolbar = m.default as Component));
  }
</script>

<div class="app" class:nochrome={!chrome} data-booted={$hub.booted || undefined}>
  <div class="body">
    {#if chrome}<Sidebar />{/if}
    <div class="content">
      {#if chrome}<Banners />{/if}
      <main class="page" data-page={gate === 'missing' ? 'music-missing' : entry.key}>
        {#if gate === 'missing' && $hub.setup}
          <MusicMissing music={$hub.setup.music} />
        {:else if failed}
          <p class="loadfail">This screen could not be loaded. Close Discjockey and open it again.</p>
        {:else if Page && loadedKey === entry.key && !held}
          {#key $route.name}
            <ErrorBoundary><Page params={$route.params} query={$route.query} /></ErrorBoundary>
          {/key}
        {:else}
          <div class="loading"><Skeleton lines={4} height={14} /></div>
        {/if}
      </main>
      <ToastHost />
    </div>
  </div>
  {#if showActivity}<ActivityBar />{/if}
</div>
<audio bind:this={audio} hidden preload="auto"></audio>
<ConfirmHost />
{#if FakeToolbar}<FakeToolbar />{/if}

<style>
  .app { height: 100vh; display: flex; flex-direction: column; min-width: 1100px; min-height: 0; }
  .body { flex: 1; display: flex; min-height: 0; }
  .content { flex: 1; display: flex; flex-direction: column; min-width: 0; min-height: 0; position: relative; }
  .page { flex: 1; min-height: 0; overflow: auto; }
  .nochrome .page { overflow-y: auto; }
  .loading { width: min(100%, var(--content-max)); padding: var(--s-5); }
  .loadfail { padding: var(--s-6); color: var(--text-muted); }
</style>
