<script lang="ts">
  // "Your music folder isn't there" (spec public-release §4): shown by the shell in place of every page while the
  // chosen folder can't be found (an unplugged drive, a renamed folder). No chrome: nothing else works without it.
  // Never a dead end: Try again (the screen's one filled button) and Choose another… are always there; both lead
  // into the app as soon as a folder is bound (bumpData → the gate clears).
  import { ColumnFrame } from '../frames';
  import { Button, FolderField, Hint, PageHeader, Surface } from '../components';
  import { api } from '../bridge/client';
  import { bumpData } from '../stores/hub';
  import { SAVED_MESSAGE, chooseFolder, isFail, useFolder } from '../musicFolderFlow';
  import type { MusicStatus } from '../bridge/types';
  import { onMount } from 'svelte';
  import { markReady } from '../ready';

  let { music }: { music: MusicStatus } = $props();

  onMount(() => markReady('music-missing'));

  let busy = $state<'retry' | 'choose' | null>(null);
  let reply = $state<{ text: string; tone: 'muted' | 'problem' } | null>(null);

  async function retry() {
    busy = 'retry'; reply = null;
    const r = await api.retry_music_folder();
    busy = null;
    if (!r.ok) { reply = { text: r.message, tone: 'problem' }; return; }
    if (r.music.state === 'ok') { bumpData(); return; }
    reply = { text: 'Still not there.', tone: 'problem' };
  }

  async function chooseAnother() {
    busy = 'choose'; reply = null;
    const path = await chooseFolder(music.suggested);
    if (isFail(path)) reply = { text: path.message, tone: 'problem' };
    else if (path) {
      const r = await useFolder(path, { bound: false });
      if (isFail(r)) reply = { text: r.message, tone: 'problem' };
      else if (r === 'saved') reply = { text: SAVED_MESSAGE, tone: 'muted' };
      // 'restart': the folder is saved and Discjockey closes; the next start uses it
    }
    busy = null;
  }
</script>

{#snippet content()}
  <PageHeader title="Your music folder isn't there" />
  <Surface tone="problem" label="Music folder" data-test="music-missing-card">
    <div class="body">
      <FolderField path={music.path} test="music-missing-folder" />
      <Hint text="If it is on an external drive, connect the drive." />
    </div>
  </Surface>
{/snippet}

{#snippet foot()}
  <Button onclick={chooseAnother} busy={busy === 'choose'} disabled={busy === 'retry'} data-test="music-choose">
    Choose another…</Button>
  <span class="reply">{#if reply}<Hint text={reply.text} tone={reply.tone} data-test="music-reply" />{/if}</span>
  <Button variant="filled" onclick={retry} busy={busy === 'retry'} disabled={busy === 'choose'} data-test="music-retry">
    Try again</Button>
{/snippet}

<div class="screen" data-test="music-missing"><ColumnFrame {content} {foot} /></div>

<style>
  .screen { height: 100vh; min-height: 0; background: var(--bg); color: var(--text); }
  .body { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
  /* the answer sits right beside the button it answers, like Setup's reason beside Continue */
  .reply { flex: 1; min-width: 0; display: flex; justify-content: flex-end; }
</style>
