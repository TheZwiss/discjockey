<script lang="ts">
  // Head of a track's details panel (To-do, Library; design system §7): a 64 px cover with the lines next to it, one
  // line each: title, "Artist · 3:12 · place", then `children` (the quality badge and its words). `action` sits at
  // the title's right end (To-do's Hide), so every kind of to-do has it in one place.
  import type { Snippet } from 'svelte';
  import type { TrackDetail } from '../bridge/types';
  import { duration } from '../format';
  import Cover from './Cover.svelte';

  let { track, place, action, children }: {
    track: Pick<TrackDetail, 'cover_url' | 'track_id' | 'title' | 'artist' | 'duration_s'>; place: string;
    /** at the title's right end, e.g. Hide */
    action?: Snippet;
    /** under the lines, e.g. the quality badge (To-do) */
    children?: Snippet;
  } = $props();
  const line = $derived([track.artist, duration(track.duration_s), place].filter(Boolean).join(' · '));
</script>

<div class="head">
  <Cover url={track.cover_url} seed={track.track_id} size={64} />
  <div class="lines">
    <div class="top">
      <h2 class="title" title={track.title}>{track.title}</h2>
      {#if action}<span class="action">{@render action()}</span>{/if}
    </div>
    <div class="sub" title={line}>{line}</div>
    {#if children}<div class="extra">{@render children()}</div>{/if}
  </div>
</div>

<style>
  .head { display: flex; gap: var(--s-3); align-items: center; min-width: 0; }
  .lines { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .top { display: flex; align-items: baseline; gap: var(--s-2); min-width: 0; }
  .title { flex: 1; min-width: 0; margin: 0; font-size: var(--fs-title); font-weight: var(--fw-semi);
    color: var(--text-strong); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .action { flex: none; }
  .sub { font-size: var(--fs-small); color: var(--text-muted); min-width: 0; overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; }
  .extra { margin-top: var(--s-1); min-width: 0; }
</style>
