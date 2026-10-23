<script lang="ts">
  // Nothing to do (spec §8): a Surface card with the good tone, a drawn check, "Up to date", one line of numbers
  // ("5 playlists · 49 tracks", §6: labels and numbers, not sentences) and + Add a playlist (link). Read Spotify is
  // not repeated here: it has one place, the page header's Spotify slot right above (spec §5a, §11). The check is drawn (stroke 1.6, as KindIcon and ⊘): a ✓ glyph
  // renders thin and uneven at small sizes (spec §11). Green + the check shape carry the state (§4).
  import { Button, Surface } from '$lib/components';
  import { plural } from '$lib/format';

  let { tracks, playlists }: { tracks: number | null; playlists: number } = $props();
</script>

<Surface kind="card" tone="good" style="--mark: 28px" data-test="sync-up-to-date">
  <div class="done">
    <svg class="mark" viewBox="0 0 28 28" aria-hidden="true"><circle cx="14" cy="14" r="14" /><path d="M8.5 14.5l3.5 3.5 7.5-8" /></svg>
    <div class="text">
      <p class="title">Up to date</p>
      <p class="line" data-test="sync-up-to-date-line">{plural(playlists, 'playlist')}{tracks !== null
        ? ` · ${plural(tracks, 'track')}` : ''}</p>
    </div>
  </div>
  <div class="acts">
    <Button size="sm" variant="link" href="#/playlists" data-test="sync-add-playlist">+ Add a playlist</Button>
  </div>
</Surface>

<style>
  .done { display: flex; align-items: center; gap: var(--s-3); min-width: 0; }
  .mark { flex: none; width: var(--mark); height: var(--mark); }
  .mark circle { fill: var(--q-lossless-bar); }
  .mark path { fill: none; stroke: var(--text-on-accent); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
  .text { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .title { margin: 0; color: var(--text-strong); font-size: var(--fs-title); font-weight: var(--fw-bold); line-height: 1.2; }
  .line { margin: 0; color: var(--text-muted); font-variant-numeric: tabular-nums; }
  /* the actions start under the text, not under the check: one left edge for everything the card says */
  .acts { display: flex; align-items: center; gap: var(--s-4); padding-left: calc(var(--mark) + var(--s-3)); }
</style>
