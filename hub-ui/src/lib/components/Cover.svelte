<script lang="ts">
  // A track's cover; a failed or missing image is a placeholder drawn from the track id. With `onplay` it is the
  // track's play button (Library's rows, design system §7): ▶ shows over it while it is hovered or focused or while
  // `hint` says so (the page's row is hovered), ❚❚ while `playing`; a click plays or pauses. It stays out of the tab
  // order (`tabindex=-1`): the row's own keys play (Enter), so a long list isn't hundreds of tab stops.
  import { hashOf } from '../format';
  let { url, seed, size = 28, onplay, playing = false, hint = false, name = '' }: {
    url: string | null; seed: string; size?: 18 | 22 | 24 | 28 | 40 | 64 | 120 | 200;
    onplay?: () => void; playing?: boolean;
    /** show ▶ now (its row is hovered) */
    hint?: boolean;
    /** the track's name for the button's label ("Play Armin Hermann – Get Naughty") */
    name?: string;
  } = $props();
  // Which URL has loaded or failed, not a flag reset by an effect: a cached image can fire `load` before an effect
  // runs on a rebuilt row, and a reset after that would hide the cover for good.
  let loadedUrl = $state<string | null>(null);
  let failedUrl = $state<string | null>(null);
  const loaded = $derived(!!url && loadedUrl === url);
  const failed = $derived(!!url && failedUrl === url);
  const PAIRS = [['--cover-a', '--cover-b'], ['--cover-c', '--cover-d'], ['--cover-b', '--cover-c'],
    ['--cover-d', '--cover-a'], ['--cover-a', '--cover-c'], ['--cover-b', '--cover-d']];
  const pair = $derived(PAIRS[hashOf(seed ?? '') % PAIRS.length]);
  const radius = $derived(size >= 120 ? 'var(--r-art)' : 'var(--r-cover)');
  const bg = $derived(`linear-gradient(135deg, var(${pair[0]}), var(${pair[1]}))`);
  function click(e: MouseEvent) {
    e.stopPropagation();   // the row's own click selects; this one only plays
    onplay?.();
  }
</script>

{#snippet image()}
  {#if url && !failed}
    <img src={url} alt="" class:loaded loading="lazy" decoding="async" onload={() => (loadedUrl = url)}
      onerror={() => (failedUrl = url)} />
  {/if}
{/snippet}

{#if onplay}
  <button type="button" class="cover play" class:playing class:hint style:width="{size}px" style:min-width="{size}px" style:height="{size}px"
    style:border-radius={radius} style:background={bg} tabindex="-1" aria-label="{playing ? 'Pause' : 'Play'}{name ? ` ${name}` : ''}"
    title={playing ? 'Pause' : 'Play'} onclick={click} ondblclick={(e) => e.stopPropagation()} data-test="cover-play">
    {@render image()}
    <span class="ov" aria-hidden="true">
      {#if playing}<svg viewBox="0 0 10 10"><rect x="2" y="1.5" width="2.2" height="7" rx=".4" /><rect x="5.8" y="1.5" width="2.2" height="7" rx=".4" /></svg>
      {:else}<svg viewBox="0 0 10 10"><path d="M3 1.6 8.4 5 3 8.4z" /></svg>{/if}
    </span>
  </button>
{:else}
  <span class="cover" style:width="{size}px" style:height="{size}px" style:border-radius={radius} style:background={bg}
    aria-hidden="true">{@render image()}</span>
{/if}

<style>
  .cover { display: inline-block; flex-shrink: 0; overflow: hidden; position: relative; vertical-align: middle; }
  img { width: 100%; height: 100%; object-fit: cover; display: block; opacity: 0; transition: opacity var(--t-state) var(--ease); }
  img.loaded { opacity: 1; }
  /* the play button: as small as the cover, so it states its size as min-width for the checker (§6) */
  .play { padding: 0; border: 0; cursor: default; transition: transform var(--t-press) var(--ease); }
  .play:active { transform: scale(.97); }
  .ov { position: absolute; inset: 0; display: grid; place-items: center; background: var(--cover-scrim);
    opacity: 0; transition: opacity var(--t-hover) var(--ease); }
  .ov svg { width: 55%; height: 55%; fill: var(--text-strong); }
  .playing .ov svg { fill: var(--accent-text); }
  .play:hover .ov, .play:focus-visible .ov, .hint .ov, .playing .ov { opacity: 1; }
</style>
