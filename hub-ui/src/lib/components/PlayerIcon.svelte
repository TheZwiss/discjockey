<script lang="ts" module>
  export type PlayerGlyph = 'play' | 'pause' | 'prev' | 'next' | 'shuffle' | 'hide' | 'show' | 'stop';
</script>

<script lang="ts">
  // The player's glyphs as 16 px line drawings (Button `icon` sizes and strokes them; text glyphs like ⏮ ⤮ render as
  // faint, uneven shapes at this size). `play` and `pause` are filled 10 px shapes for PlayButton's round face.
  let { name }: { name: PlayerGlyph } = $props();
</script>

{#if name === 'play'}
  <svg viewBox="0 0 10 10" aria-hidden="true" class="face"><path d="M2.6 1.2 9 5 2.6 8.8z" /></svg>
{:else if name === 'pause'}
  <svg viewBox="0 0 10 10" aria-hidden="true" class="face"><rect x="1.8" y="1.2" width="2.4" height="7.6" rx=".5" /><rect
    x="5.8" y="1.2" width="2.4" height="7.6" rx=".5" /></svg>
{:else}
  <svg viewBox="0 0 16 16" aria-hidden="true">
    {#if name === 'prev'}<path d="M4 3.5v9" /><path class="f" d="M13 3.6v8.8L6 8z" />
    {:else if name === 'next'}<path d="M12 3.5v9" /><path class="f" d="M3 3.6v8.8L10 8z" />
    {:else if name === 'shuffle'}<path d="M2 4.5h2.2c1.4 0 2.3.6 3.1 1.8l1.4 2.4c.8 1.2 1.7 1.8 3.1 1.8H14M2 11.5h2.2c1.2 0 2-.4 2.7-1.2M9.1 5.7c.7-.8 1.5-1.2 2.7-1.2H14M12.2 2.8 14 4.5l-1.8 1.7M12.2 9.8 14 11.5l-1.8 1.7" />
    {:else if name === 'hide'}<path d="M4.5 6.25 8 9.75l3.5-3.5" />
    {:else if name === 'show'}<path d="M4.5 9.75 8 6.25l3.5 3.5" />
    {:else}<path d="M5 5l6 6M11 5l-6 6" />{/if}
  </svg>
{/if}

<style>
  svg { display: block; }
  .face { width: 10px; height: 10px; fill: currentColor; }
  svg :global(.f) { fill: currentColor; stroke: none; }
  svg:not(.face) { stroke-linejoin: round; }
</style>
