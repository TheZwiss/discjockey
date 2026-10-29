<script lang="ts">
  // The round play/pause button of every player (MiniPlayer, the foot, the sidebar's Now playing row): an accent ring,
  // ▶ or ❚❚ drawn in the accent text colour, a spinner while the sound loads. `size` 30 (a player) or 22 (a row). `subject` names the file for the screen reader (several buttons on one screen).
  // Off (no file, can't play) keeps the ring in grey, never goes away. Like every icon-only control it states its size
  // as `min-width`, so the checker reads it as natural.
  import PlayerIcon from './PlayerIcon.svelte';
  import Spinner from './Spinner.svelte';

  let { state, size = 30, disabled = false, onclick, test, subject }: {
    state: 'playing' | 'paused' | 'loading'; size?: 30 | 22; disabled?: boolean; onclick: () => void; test?: string;
    /** what it plays, for a screen reader when several of these share a screen ("Play Neonfieber.aiff") */
    subject?: string;
  } = $props();
  const label = $derived(state === 'playing' ? 'Pause' : state === 'loading' ? 'Loading' : 'Play');
  const spoken = $derived(subject && state !== 'loading' ? `${label} ${subject}` : label);
</script>

<button type="button" class="pp" class:sm={size === 22} style:width="{size}px" style:min-width="{size}px"
  style:height="{size}px" aria-label={spoken} title={label} {disabled} {onclick} data-test={test}>
  {#if state === 'loading'}<Spinner size={size === 22 ? 9 : 11} />{:else}<PlayerIcon name={state === 'playing' ? 'pause' : 'play'} />{/if}
</button>

<style>
  .pp { border-radius: var(--r-pill); border: var(--bw-accent) solid var(--accent); color: var(--accent-text);
    background: transparent; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0;
    padding: 0; transition: border-color var(--t-hover) var(--ease), transform var(--t-press) ease-out; }
  .pp:hover:not(:disabled) { border-color: var(--accent-text); }
  .pp:disabled { border-color: var(--line-control); color: var(--text-disabled); }
  .pp:disabled:active { transform: none; }
  .sm :global(.face) { width: 8px; height: 8px; }
</style>
