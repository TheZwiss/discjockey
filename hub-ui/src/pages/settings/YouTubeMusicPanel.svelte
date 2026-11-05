<script lang="ts">
  // Settings' YouTube Music panel (sources round problem 3, plan D5/D8, I3): public and unlisted playlists need no
  // login, so the one choice is Liked music, read through the YouTube login the downloads use. The card says what
  // needs nothing; one switch row "Read my Liked music" saves at once (set_read_liked_music); the warning stays in both
  // states (before the choice it explains, after it reminds). Without a YouTube login the switch is locked off with
  // the reason and, in the same card under it, a link to the YouTube Premium row. Once the choice is on and no Liked
  // music line is listed, the panel's one filled button "Add Liked music to Playlists" adds it (add_liked_music),
  // since YouTube Music shares no link for it. The state comes from setup_status's `youtube_music` (the hub store), read again after each job.
  import { api, runJob } from '$lib/bridge/client';
  import type { SetupStatus } from '$lib/bridge/types';
  import { Button, Hint, NoteCard, Skeleton, Surface, ToggleRow, WriteButton } from '$lib/components';
  import { Panel } from '$lib/frames';
  import { go } from '$lib/router';
  import { LIKED_WARNING, likedPanel } from './settingsModel';

  let { status, disabledWhy = null, onchanged }: {
    status: SetupStatus | null; disabledWhy?: string | null; onchanged: () => void;
  } = $props();

  /** the choice being saved: the switch shows it at once, until the read-again status says the same */
  let pending = $state<boolean | null>(null);
  let adding = $state(false);
  let error = $state<string | null>(null);
  const y = $derived(status?.youtube_music ?? null);
  const view = $derived(y ? likedPanel(y, pending) : null);
  const off = $derived(!!disabledWhy);
  $effect(() => { if (y && pending !== null && y.liked_music === pending) pending = null; });

  async function setLiked(on: boolean) {
    if (!view || view.locked || off || pending !== null) return;
    error = null;
    pending = on;
    const r = await runJob(api.set_read_liked_music(on), { quiet: true, success: false });
    if (!r.ok) { pending = null; if (r.kind !== 'stopped') error = r.message; }
    onchanged();
  }
  async function addLiked() {
    error = null;
    adding = true;
    const r = await runJob<{ folder: string }>(api.add_liked_music(), { quiet: true,
      success: 'Liked music is in your playlists.' });
    adding = false;
    if (!r.ok && r.kind !== 'stopped') error = r.message;
    onchanged();
  }
</script>

{#snippet signIn()}
  <Button variant="link" size="sm" onclick={() => void go('/settings/youtube')}
    data-test="liked-music-sign-in">Go to YouTube Premium</Button>
{/snippet}

{#snippet head()}
  <div class="col" data-test="settings-youtube-music">
    {#if !view}
      <Skeleton lines={3} />
    {:else}
      <Surface kind="card" label="YouTube Music">
        <p class="note">Public and unlisted playlists need no login.</p>
      </Surface>
      <Surface kind="list" data-test="liked-music">
        <ToggleRow item={{ key: 'liked', label: 'Read my Liked music', on: view.on }} sub={view.sub}
          disabled={view.locked || off} title={view.locked ? view.sub : disabledWhy ?? undefined}
          action={view.locked ? signIn : undefined} onchange={(_k, on) => void setLiked(on)} test="liked-music-switch" />
      </Surface>
      <NoteCard tone="warn" data-test="liked-music-warning">{LIKED_WARNING}</NoteCard>
      {#if error}<NoteCard tone="problem" data-test="liked-music-error">{error}</NoteCard>{/if}
    {/if}
  </div>
{/snippet}

{#snippet why()}{#if disabledWhy}<Hint text={disabledWhy} />{/if}{/snippet}

{#snippet foot()}
  <WriteButton variant="filled" wide busy={adding} disabled={off} title={disabledWhy ?? undefined} onclick={addLiked}
    data-test="add-liked-music">Add Liked music to Playlists</WriteButton>
{/snippet}

<Panel {head} after={why} foot={view?.canAdd ? foot : undefined} />

<style>
  .col { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
  /* a card's explanation: muted, wrapping (RowPanel's and AccountPanel's sub line) */
  .note { margin: 0; color: var(--text-muted); font-size: var(--fs-small); line-height: 1.45; overflow-wrap: anywhere; }
</style>
