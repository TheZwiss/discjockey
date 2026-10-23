<script lang="ts">
  import { player } from '../stores/player';
  import { duration } from '../format';
  import PlayButton from './PlayButton.svelte';
  import { scrub } from './scrub';

  // `start`: how this sound begins when it isn't the one playing (a page starts its list as a queue, plan
  // now-playing). Without it the MiniPlayer plays its own file alone, as in the gallery.
  let { url, title, track_id = null, envelope = [], length_s = null, start }:
    { url: string | null; title: string; track_id?: string | null; envelope?: number[]; length_s?: number | null;
      start?: () => void } = $props();
  // the playing sound is this track's: its file, or its place in a queue that is still loading it
  const active = $derived(!!url && ($player.url === url || (track_id !== null && $player.track_id === track_id)));
  const playing = $derived(active && $player.playing);
  const loading = $derived(active && $player.loading);
  const pos = $derived(active ? $player.position_s : 0);
  const dur = $derived(active && $player.duration_s ? $player.duration_s : length_s);
  let dragged = $state<number | null>(null);   // while the bar is held: where it is, before the seek
  const frac = $derived(dragged ?? (dur ? Math.min(1, pos / dur) : 0));
  const shownPos = $derived(dragged !== null && dur ? dragged * dur : pos);
  const error = $derived(active ? $player.error : null);
  const bars = $derived(envelope.length ? Array.from({ length: 80 }, (_, i) => envelope[Math.floor((i / 80) * envelope.length)] ?? 0) : []);

  function toggle() {
    if (!url) return;
    if (active) player.toggle();
    else begin();
  }
  function begin() {
    if (!url) return;
    if (start) start();
    else player.play({ url, title, track_id });
  }
  function seekTo(f: number) {
    if (!url || !dur) return;
    if (!active) {
      begin();
      if (start) return;   // a queue loads its file first: it starts from the top, a seek would go nowhere
    }
    player.seek(f * dur);
  }
  const drag = $derived({
    move: (f: number) => { if (url && dur) dragged = f; },
    end: (f: number) => { dragged = null; seekTo(f); },
    cancel: () => { dragged = null; },
  });
  function key(e: KeyboardEvent) {
    if (!dur) return;
    if (e.key === 'ArrowRight') { e.preventDefault(); seekTo(Math.min(1, frac + 5 / dur)); }
    if (e.key === 'ArrowLeft') { e.preventDefault(); seekTo(Math.max(0, frac - 5 / dur)); }
  }
</script>

<div class="mini" class:disabled={!url}>
  <PlayButton state={loading ? 'loading' : playing ? 'playing' : 'paused'} disabled={!url} onclick={toggle} />
  <div class="bar" class:wave={bars.length > 0} role="slider" tabindex={url ? 0 : -1} aria-label="Position"
    aria-valuemin={0} aria-valuemax={Math.round(dur ?? 0)} aria-valuenow={Math.round(shownPos)} use:scrub={drag} onkeydown={key}>
    {#if bars.length}
      {#each bars as v, i (i)}<span class="w" class:played={i / bars.length < frac} style:height="{Math.max(8, v * 100)}%"></span>{/each}
    {:else}
      <span class="fill" style:width="{frac * 100}%"></span>
    {/if}
  </div>
  {#if error}<span class="err">{error}</span>{:else}<span class="time num">{duration(shownPos)} / {duration(dur)}</span>{/if}
</div>

<style>
  .mini { display: flex; align-items: center; gap: var(--s-3); min-width: 0; }
  .bar { flex: 1; height: 4px; touch-action: none; cursor: pointer; background: var(--bg-inset); border-radius: var(--r-pill); position: relative; overflow: hidden; }
  .bar.wave { height: 28px; background: transparent; display: flex; align-items: center; gap: 1px; border-radius: 0; }
  .fill { display: block; height: 100%; background: var(--accent); }
  .w { flex: 1; background: var(--line-control); border-radius: 1px; min-width: 1px; }
  .w.played { background: var(--accent); }
  /* fixed width: the seek bar must not jump when the length arrives */
  .time { color: var(--text-muted); font-size: var(--fs-small); white-space: nowrap; min-width: 11ch; text-align: right; }
  .err { color: var(--q-weak); font-size: var(--fs-small); }
  .disabled { opacity: .6; }
  .disabled .bar { cursor: default; }
</style>
