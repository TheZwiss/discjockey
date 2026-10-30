<script lang="ts">
  // The hidden player (plan now-playing, The row): the foot folded into the sidebar's foot, above Settings. The group
  // label "Now playing", then one 32 px row: ⏯, the title (a click shows the bar again) and ⌃ Show player, with the
  // position as a 2 px line under the title. Only while hidden with a queue (`rowShown`); `p` and `motion` let
  // the gallery show it fixed, `hovered` with the pointer on ⌃.
  // `rail` (plan library stage 5 A4.4, notes N11): the sidebar folded to its 50 px rail, so the row stacks on the glyph
  // column: ⌃ Show player, the same 22 px play button, the row's 2 px position line under it. One tooltip names it all,
  // as the row's title does ("Artist - Title · list · Show player").
  import { fade } from 'svelte/transition';
  import { player, type PlayerState } from '../stores/player';
  import { Button, PlayButton, PlayerIcon, tip } from '../components';
  import { footPlayer, rowShown } from './footModel';

  let { p, motion = true, hovered = false, rail = false }:
    { p: PlayerState; motion?: boolean; hovered?: boolean; rail?: boolean } = $props();
  const f = $derived(footPlayer(p));
  // it fades in once the bar has folded away towards it (the bar takes 240 ms), and goes quickly on Show
  const appear = (node: Element) => fade(node, motion ? { delay: 180, duration: 150 } : { duration: 0 });
  const leave = (node: Element) => fade(node, { duration: motion ? 100 : 0 });
</script>

{#if f && rowShown(p) && rail}
  <div class="np rail" in:appear out:leave use:tip={{ text: `${f.tooltip} · Show player`, side: 'right' }}
    data-test="now-playing-row">
    <Button variant="icon" size="xs" aria-label="Show player" onclick={() => player.show()} data-test="row-show">
      <PlayerIcon name="show" /></Button>
    <PlayButton size={22} state={f.play === 'error' ? 'paused' : f.play} disabled={f.play === 'error'} title={null}
      onclick={() => player.toggle()} test="row-play" />
    <span class="pos" aria-hidden="true"><span style:transform="scaleX({f.frac ?? 0})"></span></span>
  </div>
{:else if f && rowShown(p)}
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
  /* the rail's stack, centred on the 30 px glyph column above Settings */
  .rail { width: 30px; align-items: center; gap: var(--s-1); padding-bottom: 2px; }
  .rail .pos { position: relative; left: auto; right: auto; bottom: auto; width: 22px; }
</style>
