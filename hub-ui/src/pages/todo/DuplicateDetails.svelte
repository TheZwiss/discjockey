<script lang="ts">
  // Duplicates in the panel (plan library stage 4, 7.3, W8): the same audio, or the same song, in two or more files.
  // The head names the song (the track card, the why under it); then every file as its own card, labelled with the
  // folder it is in (what tells copies apart), "In your playlists" on the playlist song's copy, Move to Superseded at
  // the card's head like "Wrong song?" on the current file's card; inside, ▶ · the whole path · the quality. Then the
  // W8 note, and Keep both (Keep all for more than two) in the foot as the screen's one filled button.
  // Move to Superseded is a write job ("supersede", D10: journaled, no undo), so it asks first, naming the file; its
  // result says where the file went (a toast with the result's own words). The re-fetch keeps the group selected
  // while files are left in it (keepSelection), else goes on to the next to-do. Errors: runJob's toast, words as sent.
  import type { DuplicateItem, FileSide, Result } from '$lib/bridge/types';
  import { api, runJob } from '$lib/bridge/client';
  import { toasts } from '$lib/stores/toasts';
  import { NoteCard, QualityBadge, Surface, TrackHead, WriteButton, confirm } from '$lib/components';
  import { Panel } from '$lib/frames';
  import { fileFolder, fileName, keepLabel } from './todoModel';
  import FilePlay from './FilePlay.svelte';

  let { item }: { item: DuplicateItem } = $props();

  const g = $derived(item.pair);
  let busy = $state<number | 'keep' | null>(null);

  async function keep() {
    busy = 'keep';
    await runJob(api.keep_duplicates(g.group_id));
    busy = null;
  }
  async function supersede(f: FileSide) {
    if (!(await confirm({ title: `Move ${fileName(f.path)} to Superseded?`,
      body: 'Nothing is deleted: the file goes to Superseded/.', confirmLabel: 'Move to Superseded' }))) return;
    busy = f.file_id;
    const r = await runJob<{ result: Result }>(api.supersede_duplicate(g.group_id, f.file_id), { success: false });
    busy = null;
    if (r.ok && r.result?.result?.note) toasts.show({ tone: 'success', title: r.result.result.note });
  }
  const lastFolder = (path: string) => fileName(fileFolder(path));
</script>

{#snippet head()}
  <div class="details" data-test="duplicates" data-group={g.group_id} data-files={g.files.length}>
    <Surface kind="card">
      <TrackHead track={item} place={item.folder}><span class="why">{item.detail}</span></TrackHead>
    </Surface>
    {#each g.files as f (f.file_id)}
      <Surface kind="card" label={lastFolder(f.path)} summary={f.in_playlist ? 'In your playlists' : undefined}
        data-test="duplicate-file" data-file={f.file_id}>
        {#snippet header()}
          <WriteButton variant="link" size="sm" busy={busy === f.file_id} disabled={busy !== null && busy !== f.file_id}
            onclick={() => supersede(f)} data-test="supersede">Move to Superseded</WriteButton>
        {/snippet}
        <div class="file">
          <FilePlay files={g.files} file={f} cover={item.cover_url} test="duplicate-play" />
          <span class="path" title={f.path}>{#each f.path.split(/(?<=\/)/) as part, i (i)}{part}<wbr />{/each}</span>
          <QualityBadge quality={f.quality} label={f.quality_label} />
        </div>
      </Surface>
    {/each}
    <NoteCard data-test="duplicates-note">Nothing is deleted: the file goes to Superseded/.</NoteCard>
  </div>
{/snippet}

{#snippet foot()}
  <WriteButton variant="filled" wide busy={busy === 'keep'} disabled={busy !== null && busy !== 'keep'} onclick={keep}
    data-test="duplicates-keep">{keepLabel(g.files.length)}</WriteButton>
{/snippet}

<Panel {head} {foot} />

<style>
  .details { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
  .why { font-size: var(--fs-small); color: var(--text-muted); }
  /* ▶ · the path (read whole: it is what tells the copies apart) · the quality, on one row */
  .file { display: flex; align-items: center; gap: var(--s-3); min-width: 0; }
  /* it breaks after a "/" or between words, inside a word only when one part alone is wider than the column */
  .path { flex: 1; min-width: 0; font-size: var(--fs-small); color: var(--text-muted); overflow-wrap: break-word;
    word-break: normal; }
</style>
