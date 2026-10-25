<script lang="ts">
  // Step 4, First playlist: the Playlists page's add row (the AddRow block: paste a link, check it, name its folder),
  // and the playlists in playlists.txt under it. Adding saves at once (save_playlists); the order and the rest are
  // Playlists' job later. Required: one playlist.
  import { api, runJob } from '$lib/bridge/client';
  import type { AddedPlaylist, ProblemKind } from '$lib/bridge/types';
  import { AddRow, Hint, ListRow, ProblemCard, Skeleton, Surface } from '$lib/components';
  import { plural } from '$lib/format';
  import { addRow, draftFrom, lines, loadedFrom, type Loaded } from '../playlists/changeModel';

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

<Surface kind="card" label="Add a Spotify or Qobuz playlist"
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
{:else if loaded.rows.length}
  <Surface kind="list" label="Your playlists" summary={plural(loaded.rows.length, 'playlist')}
    style="--row-cols: minmax(0, 1fr) auto" data-test="playlist-list">
    {#each loaded.rows as r (r.index)}
      <ListRow test="playlist-row">
        {#snippet name()}{r.folder}{/snippet}
        {#snippet sub()}{r.service_name} · {r.info ? `“${r.info.name}”` : r.link}{/snippet}
        {#snippet trailing()}<span class="count">{r.tracks == null ? '' : plural(r.tracks, 'track')}</span>{/snippet}
      </ListRow>
    {/each}
  </Surface>
  <Hint text="Add more and change their order later in Playlists." />
{/if}

<style>
  .problem { margin-top: var(--s-2); }
  .count { color: var(--text-label); font-size: var(--fs-small); font-variant-numeric: tabular-nums; white-space: nowrap; }
</style>
