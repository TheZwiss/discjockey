<script lang="ts">
  // One track line: cover · "Artist – Title" over "folder · detail" · quality badge · FREE. The badge and the FREE tag
  // sit in fixed-width columns, so they line up from row to row whatever the text. Selection, dim (not in a playlist).
  import type { Snippet } from 'svelte';
  import type { TrackRow } from '../bridge/types';
  import { artistTitle } from '../format';
  import Badge from './Badge.svelte';
  import Cover from './Cover.svelte';
  import QualityBadge from './QualityBadge.svelte';

  let { track, detail, selected = false, dim = false, showFolder = false, free, onclick, ondblclick, oncontextmenu,
    trailing }: { track: TrackRow; detail?: string; selected?: boolean; dim?: boolean; showFolder?: boolean;
      /** the artist gives it away; undefined: no FREE column at all */
      free?: boolean;
      onclick?: (e: MouseEvent) => void; ondblclick?: (e: MouseEvent) => void;
      oncontextmenu?: (e: MouseEvent) => void; trailing?: Snippet } = $props();
  const line2 = $derived([showFolder ? track.folder : '', detail ?? ''].filter(Boolean).join(' · '));
  function key(e: KeyboardEvent) {
    if ((e.key === 'Enter' || e.key === ' ') && onclick) { e.preventDefault(); onclick(e as unknown as MouseEvent); }
  }
</script>

<div class="row" class:selected class:dim class:clickable={!!onclick} role="button" tabindex="0"
  aria-pressed={selected} data-track={track.track_id} {onclick} {ondblclick} {oncontextmenu} onkeydown={key}>
  <Cover url={track.cover_url} seed={track.track_id} size={40} />
  <span class="who">
    <span class="name" title={artistTitle(track.artist, track.title)}><span class="artist">{track.artist}</span><span
        class="sep">{' – '}</span><span class="title">{track.title}</span></span>
    {#if line2}<span class="line2" title={line2}>{line2}</span>{/if}
  </span>
  <span class="q"><QualityBadge quality={track.quality} label={track.quality_label} upgrade={track.upgrade_ready} /></span>
  {#if free !== undefined}
    <span class="free" data-test="free-tag">{#if free}<span title="The artist gives it away for free"><Badge
          tone="accent" text="FREE" /></span>{/if}</span>
  {/if}
  {#if trailing}<span class="trailing">{@render trailing()}</span>{/if}
</div>

<style>
  .row {
    display: flex; align-items: center; gap: var(--s-3); min-height: 48px; padding: 4px var(--s-2);
    border-bottom: var(--bw) solid var(--line-row); color: var(--text); min-width: 0;
  }
  .clickable:hover { background: var(--bg-hover); }
  .selected, .selected:hover { background: var(--bg-selected); box-shadow: inset var(--bw-accent) 0 0 var(--accent); }
  .selected .title, .selected .artist { color: var(--text-strong); }
  .dim { opacity: .55; }
  .who { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
  /* long names: the artist takes at most 45 %, so the title stays readable */
  .name { min-width: 0; display: flex; align-items: baseline; white-space: nowrap; overflow: hidden; }
  .artist, .title { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .artist { color: var(--text-muted); flex: 0 1 auto; max-width: 45%; }
  .title { flex: 0 1 auto; }
  .sep { color: var(--text-label); white-space: pre; flex: none; }
  .line2 { color: var(--text-label); font-size: var(--fs-small); white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; }
  /* fixed columns: the badges form one straight line */
  .q { flex: none; width: 100px; display: flex; }
  .free { flex: none; width: 40px; display: flex; }
  .trailing { display: inline-flex; gap: var(--s-1); }
</style>
