<script lang="ts">
  // The hidden player (plan now-playing, The row): the foot folded into the sidebar's foot, above Settings. The group
  // label "Now playing", then one 32 px row: ⏯, the title (a click shows the bar again) and ⌃ Show player, with the
  // position as a 2 px line under the title. Only while hidden with a queue (`rowShown`); `p` and `motion` let
  // the gallery show it fixed, `hovered` with the pointer on ⌃.
  import { fade } from 'svelte/transition';
  import { player, type PlayerState } from '../stores/player';
  import { Button, PlayButton, PlayerIcon } from '../components';
  import { footPlayer, rowShown } from './footModel';

  let { p, motion = true, hovered = false }: { p: PlayerState; motion?: boolean; hovered?: boolean } = $props();
  const f = $derived(footPlayer(p));
  // it fades in once the bar has folded away towards it (the bar takes 240 ms), and goes quickly on Show
  const appear = (node: Element) => fade(node, motion ? { delay: 180, duration: 150 } : { duration: 0 });
  const leave = (node: Element) => fade(node, { duration: motion ? 100 : 0 });
</script>

{#if f && rowShown(p)}
  <div class="np" in:appear out:leave data-test="now-playing-row">
    <div class="grp caps">Now playing</div>
    <div class="row" class:hovered>
      <PlayButton size={22} state={f.play === 'error' ? 'paused' : f.play} disabled={f.play === 'error'}
        onclick={() => player.toggle()} test="row-play" />
      <button type="button" class="title" title="{f.tooltip} · Show player" onclick={() => player.show()}
        data-row-hit data-test="row-title">{f.title}</button>
      <span class="show" class:hovered><Button variant="icon" size="xs" aria-label="Show player" title="Show player"
        onclick={() => player.show()} data-test="row-show"><PlayerIcon name="show" /></Button></span>
      <span class="pos" aria-hidden="true"><span style:transform="scaleX({f.frac ?? 0})"></span></span>
    </div>
  </div>
{/if}

<style>
  .np { flex-shrink: 0; display: flex; flex-direction: column; }
  /* the "Library" label's place and style */
  .grp { margin: var(--s-3) 7px var(--s-1); }
  .show { display: flex; }
  .row { position: relative; display: grid; grid-template-columns: 22px minmax(0, 1fr) 22px; column-gap: var(--s-2);
    align-items: center; height: 32px; padding: 0 var(--s-1); border-radius: var(--r-nav); }
  .row:hover, .row.hovered { background-color: var(--ctl-hover); }
  .title { min-width: 0; height: 100%; padding: 0; border: 0; background: none; text-align: left; color: var(--text);
    font-size: var(--fs-body); font-weight: var(--fw-medium); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .title:active { transform: none; }
  .show.hovered :global(.btn) { background: var(--ctl-hover); color: var(--text); }
  /* the position under the title, between the two buttons */
  .pos { position: absolute; left: 34px; right: 34px; bottom: 3px; height: 2px; border-radius: 1px; background: var(--ctl-line);
    overflow: hidden; pointer-events: none; }
  .pos span { position: absolute; inset: 0; background: var(--accent); transform-origin: 0 50%; }
</style>
