<script lang="ts">
  // Step 4, First playlist: the Playlists page's add row (the AddRow block: paste a link, check it, name its folder),
  // and the playlists in playlists.txt under it. Adding saves at once (save_playlists); the order and the rest are
  // Playlists' job later. Required: one playlist. Where a playlist's link is in each app (LinkGuide) stands open
  // under the Add card until the first playlist is in, then folds to one line under "Your playlists" (a click opens
  // it). The rows are Playlists' rows without the controls (sources round problem 7): cover, folder, then the
  // service's logo and "name" · owner · N tracks, from the same playlists() rows and changeModel lines; never the
  // raw link.
  import { api, runJob } from '$lib/bridge/client';
  import type { AddedPlaylist, ProblemKind } from '$lib/bridge/types';
  import { AddRow, Cover, Hint, LinkGuide, ListRow, ProblemCard, Skeleton, Surface } from '$lib/components';
  import { plural } from '$lib/format';
  import { addRow, draftFrom, lines, loadedFrom, setupLine, type Loaded } from '../playlists/changeModel';
  import PlaylistLine from '../playlists/PlaylistLine.svelte';

  let { onchanged }: { onchanged: () => void } = $props();

  let loaded = $state<Loaded | null>(null);
  let loadError = $state<{ kind: ProblemKind; message: string } | null>(null);
  let saveError = $state<{ kind: ProblemKind; message: string } | null>(null);

  async function load(): Promise<Loaded | null> {
    const r = await api.playlists();
    if (r.ok) { loaded = loadedFrom(r); loadError = null; } else loadError = { kind: r.kind, message: r.message };
    return r.ok ? loaded : null;
  }
  void load();

  const draft = $derived(loaded ? draftFrom(loaded) : []);
  let guideOpen = $state(false);

  /** true when the playlist is in playlists.txt; else the problem shows and AddRow keeps the playlist for a retry */
  async function save(a: AddedPlaylist, folder: string, retry: boolean): Promise<boolean> {
    const base = loaded ?? (await load());
    if (!base) { saveError = loadError; return false; }
    const r = await runJob(api.save_playlists(lines(addRow(draftFrom(base), a, folder)), base.version),
      { quiet: true, success: false });
    // the file changed in the meantime (Playlists, the console): read it again and add once more
    if (!r.ok && r.kind === 'changed' && retry) { if (await load()) return save(a, folder, false); }
    if (!r.ok) { saveError = { kind: r.kind, message: r.message }; return false; }
    await load();
    onchanged();
    return true;
  }
  async function added(a: AddedPlaylist, folder: string): Promise<boolean> {
    saveError = null;
    return save(a, folder, true);   // Add to the list shows the wait (AddRow keeps it busy until this answers)
  }
</script>

<Surface kind="card" label="Add a playlist"
  summary="Discjockey keeps each playlist's tracks in a folder of its own." data-test="playlist-add">
  <AddRow {draft} filled={!draft.length} onadd={added} />
  {#if saveError}
    <div class="problem" data-test="playlist-error">
      <ProblemCard alert compact kind={saveError.kind} message={saveError.message} />
    </div>
  {/if}
</Surface>

{#if loadError && !loaded}
  <ProblemCard kind={loadError.kind} message={loadError.message} onretry={() => void load()} />
{:else if !loaded}
  <Skeleton shape="card" height={80} />
{:else if draft.length}
  <Surface kind="list" label="Your playlists" summary={plural(draft.length, 'playlist')}
    style="--row-cols: 28px minmax(0, 1fr)" data-test="playlist-list">
    {#each draft as r (r.key)}
      {@const line = setupLine(r)}
      <ListRow height={52} test="playlist-row" title={line.tone === 'bad' ? line.text : undefined}>
        {#snippet lead()}<Cover url={r.info?.image_url ?? null} seed={r.link} size={28} />{/snippet}
        {#snippet name()}<span class="fname">{r.folder}</span>{/snippet}
        {#snippet sub()}<PlaylistLine service={r.service} text={line.text} tone={line.tone} />{/snippet}
      </ListRow>
    {/each}
  </Surface>
  <LinkGuide folded bind:open={guideOpen} data-test="setup-link-guide" />
  <Hint text="Add more and change their order later in Playlists." />
{:else}
  <LinkGuide data-test="setup-link-guide" />
{/if}

<style>
  .problem { margin-top: var(--s-2); }
  .fname { color: var(--text-strong); font-weight: var(--fw-semi); }
</style>
