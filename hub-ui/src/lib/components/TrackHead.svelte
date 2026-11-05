<script lang="ts">
  // Head of a track's details panel (To-do, Library; design system §7): a 64 px cover with the lines next to it: the
  // title, "Artist · 3:12 · place", the state line (`badge` and its `word`), then `children`. `action` sits at the
  // title's right end, on its first line (To-do's Hide), beside the title only: the lines under it keep the full width.
  // What gives way in a narrow panel (320 px, sources round I4, notes problem 5):
  // - the title never: it wraps whole (the title is what the user came to read);
  // - the meta line stays on one line and ends in "…"; the whole line is then its Tip;
  // - the badge's word shows whole or not at all: it wraps onto a second line the head hides, and the badge's Tip
  //   says it then (a cut word read as a different word: "lossy, aud…"). VoiceOver still reads the hidden word.
  // `link` (the song's page on its service, `track_link`) adds a row at the foot of the card: the service's logo and
  // "Open in {Service} ↗". It belongs to the song, file or no file, so a waiting song (`empty`) shows it too. The row
  // reaches the card's edges, so TrackHead is the one content of a padded `Surface kind="card"` (as every page has it).
  import type { Snippet } from 'svelte';
  import type { TrackDetail, TrackLink } from '../bridge/types';
  import { PLAYLIST_SERVICE_NAMES } from '../copy';
  import Cover from './Cover.svelte';
  import ExternalLink from './ExternalLink.svelte';
  import ServiceMark from './ServiceMark.svelte';
  import { logoOf } from './serviceLogos';
  import { tip } from './tip';
  import { headLine, linkService, wordHidden } from './trackHeadModel';

  let { track, place, empty = false, link = null, badge, word, action, children }: {
    track: Pick<TrackDetail, 'cover_url' | 'track_id' | 'title' | 'artist' | 'duration_s'>; place: string;
    /** no file yet: the cover's place is an empty dashed outline (Cover `empty`), as in the table's row */
    empty?: boolean;
    /** the song's page on its service: the "Open in {Service} ↗" row at the card's foot */
    link?: TrackLink | null;
    /** the state line's badge (QualityBadge, Badge); `word` says it in words beside it, whole or not at all */
    badge?: Snippet;
    word?: string;
    /** at the title's right end, e.g. Hide */
    action?: Snippet;
    /** under the lines, e.g. a duplicate's reason */
    children?: Snippet;
  } = $props();
  const line = $derived(headLine(track.artist, track.duration_s, place));
  const service = $derived(link ? linkService(link) : null);

  let badgeEl: HTMLElement | undefined = $state();
  let wordEl: HTMLElement | undefined = $state();
  let hidden = $state(false);
  // the word's place is known only once laid out: measure on every size change of the line (the panel's width)
  $effect(() => {
    const b = badgeEl, w = wordEl;
    void word;   // a new word measures again
    if (!b || !w) { hidden = false; return; }
    const measure = () => { hidden = wordHidden(b.offsetTop, w.offsetTop); };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(b.parentElement ?? b);
    return () => ro.disconnect();
  });
</script>

<div class="th">
  <div class="head">
    <Cover url={track.cover_url} seed={track.track_id} size={64} {empty} />
    <div class="lines">
      <div class="top">
        <h2 class="title">{track.title}</h2>
        {#if action}<span class="action">{@render action()}</span>{/if}
      </div>
      {#if line}<div class="sub" use:tip={{ text: line, cut: true }} data-test="head-line">{line}</div>{/if}
      {#if badge}
        <div class="state" data-test="head-state">
          <span class="badge" bind:this={badgeEl} use:tip={hidden && word ? word : null}>{@render badge()}</span>
          {#if word}<span class="word" bind:this={wordEl}
            data-hidden={hidden || undefined}>{word}</span>{/if}
        </div>
      {/if}
      {#if children}<div class="extra">{@render children()}</div>{/if}
    </div>
  </div>
  {#if link}
    <div class="open" data-test="head-link">
      {#if service}<ServiceMark service={logoOf(service)} label={PLAYLIST_SERVICE_NAMES[service]} />{/if}
      <ExternalLink href={link.url} label={link.label} />
    </div>
  {/if}
</div>

<style>
  .th { display: flex; flex-direction: column; min-width: 0; }
  .head { display: flex; gap: var(--s-3); align-items: center; min-width: 0; }
  .lines { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .top { display: flex; align-items: baseline; gap: var(--s-2); min-width: 0; }
  .title { flex: 1; min-width: 0; margin: 0; font-size: var(--fs-title); font-weight: var(--fw-semi);
    color: var(--text-strong); overflow-wrap: anywhere; }
  .action { flex: none; }
  .sub { font-size: var(--fs-small); color: var(--text-muted); min-width: 0; white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; }
  /* one line, the badge's height: a word that doesn't fit beside the badge wraps onto the second line, which the
     clip hides (row-gap pushes it fully out of the box) */
  .state { position: relative; display: flex; flex-wrap: wrap; align-items: center; column-gap: var(--s-2);
    row-gap: var(--s-4); height: var(--h-badge-line); overflow: hidden; margin-top: var(--s-1); min-width: 0;
    --h-badge-line: 20px; }
  .badge { flex: none; display: inline-flex; align-items: center; height: var(--h-badge-line); }
  .word { flex: none; white-space: nowrap; font-size: var(--fs-small); color: var(--text-muted);
    line-height: var(--h-badge-line); }
  .extra { margin-top: var(--s-1); min-width: 0; }
  /* the song's page, at the card's foot: ruled like a list row, edge to edge inside the card's padding */
  .open { display: flex; align-items: center; gap: var(--s-2); min-height: var(--h-list-row);
    margin: var(--s-3) calc(-1 * var(--s-4)) calc(-1 * var(--s-4)); padding: 0 var(--s-4);
    border-top: var(--bw) solid var(--line-soft); font-size: var(--fs-small); min-width: 0; }
  .open :global(.ext) { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
