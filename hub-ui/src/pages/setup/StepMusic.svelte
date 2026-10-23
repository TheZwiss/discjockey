<script lang="ts">
  // Step 1, Music folder (spec public-release §4): where Discjockey keeps the music, the playlists' folders and the
  // reports. Until it is bound this is the only step Setup shows (every later one may read the library). One of two:
  // a new folder (the suggested ~/Music/Discjockey, or Discjockey inside a folder you pick) or a folder you already
  // have; a `Segmented`, as every one-of choice (design language §2). The FolderField says what is there; the one
  // filled button is the next thing to do: Choose… while an existing folder isn't picked yet, else Use this folder.
  // Once bound, the folder with a ✓ and where to change it; Continue (the foot) is the filled one then.
  import { untrack } from 'svelte';
  import type { FolderCheck, SetupStatus } from '$lib/bridge/types';
  import { Button, FolderField, Hint, Segmented, StatusMark, Surface } from '$lib/components';
  import { newFolderPath, parentOf } from '$lib/musicFolder';
  import { checkFolder, chooseFolder, isFail, useFolder } from '$lib/musicFolderFlow';
  import { writeBlockedReason } from '$lib/stores/hub';

  let { status }: { status: SetupStatus } = $props();

  type Mode = 'new' | 'existing';
  let mode = $state<Mode>('new');
  let parent = $state<string | null>(null);   // new: the folder Discjockey goes into (null: the suggested one)
  let picked = $state<string | null>(null);   // existing: the folder chosen
  let check = $state<FolderCheck | null>(null);
  let error = $state<string | null>(null);
  let choosing = $state(false);
  let setting = $state(false);

  const bound = $derived(status.music.state === 'ok');
  const path = $derived(mode === 'new' ? (parent ? newFolderPath(parent) : status.music.suggested) : picked);
  const usable = $derived(!!check && check.usable && !check.problem);
  const blocked = $derived($writeBlockedReason);
  const pickFirst = $derived(mode === 'existing' && !picked);

  // what is in the folder on screen; only the newest answer counts
  let turn = 0;
  $effect(() => {
    const p = path;
    untrack(() => {
      const t = ++turn;
      check = null;
      if (!p || bound) return;
      void checkFolder(p).then((r) => {
        if (t !== turn) return;
        if (isFail(r)) { error = r.message; return; }
        check = r;
      });
    });
  });

  function setMode(m: Mode) { mode = m; error = null; }
  async function choose() {
    error = null;
    choosing = true;
    const start = mode === 'new' ? (parent ?? parentOf(status.music.suggested)) : picked;
    const r = await chooseFolder(start);
    choosing = false;
    if (r === null) return;
    if (isFail(r)) { error = r.message; return; }
    if (mode === 'new') parent = r; else picked = r;
  }
  async function use() {
    if (!path) return;
    error = null;
    setting = true;
    const r = await useFolder(path, { bound: false });
    setting = false;
    if (isFail(r)) error = r.message;
    // 'bound': the hub reads everything again and the page shows this step done
  }
</script>

<Surface kind="card" label="Music folder" summary="Your music, its playlist folders and the sync reports live here."
  tone={bound ? 'good' : 'default'} data-test="music-card">
  {#if bound}
    <div class="col" data-test="music-done">
      <FolderField path={status.music.path} test="music-folder" />
      <div class="line"><StatusMark tone="good" /><Hint text="Change it later in Settings → Music folder." wrap /></div>
    </div>
  {:else}
    <div class="col" data-test="music-choose" data-mode={mode}>
      <Segmented label="Music folder" value={mode} onchange={setMode} test="music-mode"
        options={[{ key: 'new', label: 'A new folder' }, { key: 'existing', label: 'A folder I already have' }]} />
      <FolderField {path} {check} onchoose={choose} busy={choosing} disabled={!!blocked && !setting}
        label={mode === 'new' ? 'Choose where…' : 'Choose…'} filled={pickFirst || (!!check && !usable)} test="music-folder" />
      {#if error}<Hint tone="problem" text={error} wrap data-test="music-error" />{/if}
      <div class="actions">
        <Button variant={usable ? 'filled' : 'secondary'} busy={setting} disabled={!usable || !!blocked || choosing}
          title={blocked ?? undefined} onclick={use} data-test="music-use">Use this folder</Button>
      </div>
    </div>
  {/if}
</Surface>

<style>
  .col { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
  .line { display: flex; align-items: flex-start; gap: var(--s-2); min-width: 0; }
  .actions { display: flex; align-items: center; gap: var(--s-3); min-width: 0; }
</style>
