<script lang="ts">
  // The frame's foot (plan now-playing, mockup hub-mockups/now-playing.html): a 44 px bar along the window's bottom
  // in the sidebar's material, one L-shaped frame with the sidebar around the page. Only the page's edge has a line
  // (from the sidebar's right border to the window's right edge), and while a queue plays that line is the position:
  // the played part in the accent, thicker with a knob and the time under the pointer while hovered, click or drag to
  // seek. The bar: the track and its list (a link back to the list, the playing track selected) · the transport,
  // centred on the window · the sync's short form, shuffle, Hide player, Stop. With no queue, or hidden, the foot
  // holds only the sync (SyncPart's long form). App renders it; the gallery passes fixed states (`motion` off,
  // `edge` the pointer's place on the line) and `run` for the sync part.
  import { get } from 'svelte/store';
  import { quintOut, cubicInOut } from 'svelte/easing';
  import type { TransitionConfig } from 'svelte/transition';
  import { player, type PlayerState } from '../stores/player';
  import type { RunState } from '../stores/run';
  import { link } from '../router';
  import { duration } from '../format';
  import { Button, Cover, PlayButton, PlayerIcon } from '../components';
  import { scrub } from '../components/scrub';
  import SyncPart from './SyncPart.svelte';
  import { footPlayer, footShape } from './footModel';

  let { p, sync = false, motion = true, edge = null, run }: {
    p: PlayerState; sync?: boolean; motion?: boolean;
    /** gallery: show the line as if the pointer were on it at this fraction */
    edge?: number | null;
    run?: RunState;
  } = $props();

  const shape = $derived(footShape(p, sync));
  const f = $derived(footPlayer(p));

  // ---------- motion (plan now-playing, Motion) ----------
  // Appear: up from the window's bottom edge (220 ms, strong ease-out). The foot's own height moves with it (`frame`),
  // so the sidebar's foot (Settings, the Now playing row) and the page's lower edge glide instead of jumping by 44 px
  // when the foot comes or goes as a whole. Stop: down again (180 ms). Hide: the bar's contents move left
  // towards the sidebar's corner and fade (240 ms, ease-in-out), then the row fades in there; Show: the same path
  // back (280 ms). Only transform and opacity; reduced motion cross-fades. Track changes, play/pause, shuffle and the
  // keys don't animate.
  let wasHidden = false;
  let unfolding = false;   // the bar comes back from the sidebar row (Show), not up from the window's bottom
  $effect.pre(() => {
    const h = p.hidden;
    if (wasHidden && !h && p.queue) unfolding = true;
    wasHidden = h;
  });
  const reduced = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const FOLD_PX = 40;
  function moves(_node: Element, _o: unknown, { direction }: { direction: 'in' | 'out' | 'both' }): TransitionConfig {
    if (!motion) return { duration: 0 };
    const out = direction === 'out';
    const fold = out ? get(player).hidden : unfolding;
    if (!out) unfolding = false;
    if (reduced()) return { duration: 150, css: (t) => `opacity: ${t}` };
    if (fold) {
      return { duration: out ? 240 : 280, easing: cubicInOut,
        css: (t, u) => `opacity: ${t}; transform: translateX(${-FOLD_PX * u}px)` };
    }
    return { duration: out ? 180 : 220, easing: quintOut, css: (_t, u) => `transform: translateY(${u * 100}%)` };
  }
  /** The whole foot comes or goes: its height follows (clipped meanwhile), its contents ride on the top edge. */
  function frame(node: Element, o: unknown, opts: { direction: 'in' | 'out' | 'both' }): TransitionConfig {
    const out = opts.direction === 'out';
    const fold = out ? get(player).hidden : unfolding;
    const m = moves(node, o, opts);
    if (!m.duration || reduced()) return m;
    const h = (node as HTMLElement).offsetHeight;
    const grow = (t: number) => `overflow: hidden; height: ${t * h}px;`;
    if (fold) return { ...m, css: (t, u) => `${grow(t)} ${m.css!(t, u)}` };
    return { ...m, css: (t) => grow(t) };
  }
  function fades(_node: Element): TransitionConfig {
    return motion ? { duration: 150, css: (t) => `opacity: ${t}` } : { duration: 0 };
  }

  // ---------- the position on the page's edge ----------
  let dragged = $state<number | null>(null);   // while the line is held: where it is, before the seek
  let hover = $state<number | null>(null);     // the pointer's place on the line, for the time label
  const frac = $derived(dragged ?? f?.frac ?? null);
  const shownPos = $derived(dragged !== null && f?.dur_s ? duration(dragged * f.dur_s) : f?.pos ?? '');
  const tipAt = $derived(dragged ?? hover ?? edge);
  const seekable = $derived(!!f?.seekable);
  const drag = $derived({
    move: (x: number) => { if (seekable) dragged = x; },
    end: (x: number) => { const d = f?.dur_s; dragged = null; if (seekable && d) player.seek(x * d); },
    cancel: () => { dragged = null; },
  });
  function track(e: PointerEvent) {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    hover = r.width > 0 ? Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) : null;
  }
  function key(e: KeyboardEvent) {
    const d = f?.dur_s;
    if (!seekable || !d || frac === null) return;
    if (e.key === 'ArrowRight') { e.preventDefault(); player.seek(Math.min(d, (frac + 5 / d) * d)); }
    if (e.key === 'ArrowLeft') { e.preventDefault(); player.seek(Math.max(0, (frac - 5 / d) * d)); }
  }
</script>

{#if shape}
  <footer class="foot chrome" data-test="foot" in:frame out:frame>
    {#if shape.player && f}
      <div class="part" in:moves out:moves data-test="foot-player">
        <div class="edge" class:live={seekable} class:held={dragged !== null} class:demo={edge !== null} role="slider"
          tabindex={seekable ? 0 : -1} aria-label="Position" aria-valuemin={0} aria-valuemax={Math.round(f.dur_s ?? 0)}
          aria-valuenow={Math.round((frac ?? 0) * (f.dur_s ?? 0))} aria-valuetext="{shownPos} of {f.len}"
          aria-disabled={!seekable || undefined} use:scrub={drag} onkeydown={key} onpointermove={track}
          onpointerleave={() => (hover = null)} data-test="foot-edge">
          <span class="track" aria-hidden="true"></span>
          {#if frac !== null}
            <span class="thick" aria-hidden="true"><span class="fill" style:transform="scaleX({frac})"></span></span>
            <span class="knobrow" aria-hidden="true" style:transform="translateX({frac * 100}%)"><span class="knob"></span></span>
          {/if}
          {#if seekable && tipAt !== null && f.dur_s}
            <span class="tip num" aria-hidden="true" style:--h={tipAt}>{duration(tipAt * f.dur_s)}</span>
          {/if}
        </div>

        <div class="bar">
          <a class="item" href={f.href} use:link title={f.tooltip} data-test="foot-track">
            <Cover url={f.cover_url} seed={f.track_id} size={28} />
            <span class="lines">
              <span class="t">{f.title}</span>
              <span class="s" class:err={f.sub.kind === 'error'} data-test="foot-sub">{f.sub.text}</span>
            </span>
          </a>

          <div class="mid">
            <span class="tm l num" data-test="foot-pos">{shownPos}</span>
            <Button variant="icon" aria-label="Previous" title="Previous" disabled={!f.canPrev} onclick={() => player.prev()}
              data-test="foot-prev"><PlayerIcon name="prev" /></Button>
            <PlayButton state={f.play === 'error' ? 'paused' : f.play} disabled={f.play === 'error'}
              onclick={() => player.toggle()} test="foot-play" />
            <Button variant="icon" aria-label="Next" title="Next" disabled={!f.canNext} onclick={() => player.next()}
              data-test="foot-next"><PlayerIcon name="next" /></Button>
            <span class="tm r num">{f.len}</span>
          </div>

          <div class="end">
            {#if shape.sync}<SyncPart short fixed={run} /><span class="sep" aria-hidden="true"></span>{/if}
            <Button variant="icon" aria-label="Shuffle" title="Shuffle" pressed={f.shuffle} disabled={!f.canShuffle}
              onclick={() => player.setShuffle(!f.shuffle)} data-test="foot-shuffle"><PlayerIcon name="shuffle" /></Button>
            <span class="sep" aria-hidden="true"></span>
            <Button variant="icon" aria-label="Hide player" title="Hide player" onclick={() => player.hide()}
              data-test="foot-hide"><PlayerIcon name="hide" /></Button>
            <Button variant="icon" aria-label="Stop" title="Stop" onclick={() => player.stop()}
              data-test="foot-stop"><PlayerIcon name="stop" /></Button>
          </div>
        </div>
      </div>
    {:else}
      <div class="part only" in:fades out:fades><SyncPart fixed={run} /></div>
    {/if}
  </footer>
{/if}

<style>
  /* the frame's material is painted once behind sidebar and foot (App's .app), so the L has no seam; the foot itself
     is transparent and only its contents move */
  .foot { position: relative; height: var(--activity-h); flex-shrink: 0; z-index: 2; }
  /* the page's lower edge: continues the sidebar's right border into an L */
  .foot::before { content: ''; position: absolute; left: calc(var(--sidebar-w) - var(--bw)); right: 0; top: 0;
    height: var(--bw); background: var(--surface-line); }
  .part { position: absolute; inset: 0 0 auto; height: var(--activity-h); }   /* on the top edge while `frame` runs */
  .only { padding: 0 var(--s-4) 0 18px; }

  /* the bar: three columns, the middle one centred on the window. The padding is the same on both sides (so the
     centre is the window's), the left column adds the rest of the sidebar items' inset (18 px, the nav glyphs'
     edge); at the right the Stop glyph then ends 18 px from the window's edge too */
  .bar { height: 100%; display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: center;
    column-gap: var(--s-6); padding: 0 var(--s-2); }
  .item { display: grid; grid-template-columns: 28px minmax(0, 1fr); column-gap: 10px; align-items: center;
    justify-self: start; max-width: 100%; min-width: 0; margin-left: var(--s-1); padding: 4px 6px;
    border-radius: var(--r-nav); text-decoration: none; color: inherit; }
  .item:hover { text-decoration: none; background: var(--ctl-hover); transition: background-color var(--t-hover) var(--ease); }
  .item:active { background: var(--ctl-press); }
  .lines { display: flex; flex-direction: column; min-width: 0; line-height: 1.25; }
  .t, .s { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .t { color: var(--text-strong); font-size: var(--fs-body); font-weight: var(--fw-semi); }
  .s { color: var(--text-muted); font-size: var(--fs-small); }
  .s.err { color: var(--q-weak); }

  /* the transport: the times have one fixed width each side, so ⏯ sits exactly on the window's centre and nothing
     moves as the numbers change */
  .mid { display: flex; align-items: center; gap: 6px; }
  .tm { width: 44px; font-size: var(--fs-label); color: var(--text-label); white-space: nowrap; }
  .tm.l { text-align: right; }
  .tm.r { text-align: left; }

  .end { display: flex; align-items: center; justify-content: flex-end; gap: var(--s-1); min-width: 0; }
  .sep { width: var(--bw); height: 18px; background: var(--ctl-line); flex: none; margin: 0 var(--s-2); }

  /* ---------- the position line: a 10 px hit area centred on the 2 px played part ---------- */
  .edge { position: absolute; left: var(--sidebar-w); right: 0; top: -4px; height: 10px; z-index: 1; touch-action: none;
    outline: none; }
  .edge.live { cursor: pointer; }
  .track, .thick { position: absolute; left: 0; right: 0; top: 3px; height: 4px; border-radius: 2px; }
  .track { background: var(--line-control); opacity: 0; }
  /* 4 px drawn, shown at half height (2 px on the page's edge) until the pointer comes */
  .thick { transform: scaleY(.5); overflow: hidden; }
  .fill { position: absolute; inset: 0; background: var(--accent); transform-origin: 0 50%; }
  .knobrow { position: absolute; left: 0; top: -1px; width: 100%; height: 12px; pointer-events: none; }
  .knob { position: absolute; left: -6px; top: 0; width: 12px; height: 12px; border-radius: var(--r-pill);
    background: var(--text-strong); box-shadow: 0 1px 4px var(--cover-scrim); opacity: 0;
    transform: scale(.6); }
  .tip { position: absolute; bottom: 14px; left: clamp(24px, calc(var(--h) * 100%), calc(100% - 24px));
    transform: translateX(-50%); padding: 2px 6px; border-radius: var(--r-icon); background: var(--popover-bg);
    border: var(--bw) solid var(--popover-line); box-shadow: var(--shadow); color: var(--text-strong);
    font-size: var(--fs-label); font-weight: var(--fw-semi); white-space: nowrap; pointer-events: none; opacity: 0; }
  .track, .thick, .knob, .tip { transition: opacity var(--t-hover) var(--ease), transform var(--t-hover) var(--ease); }
  .live:hover .track, .live:focus-visible .track, .held .track, .demo .track { opacity: 1; }
  .live:hover .thick, .live:focus-visible .thick, .held .thick, .demo .thick { transform: none; }
  .live:hover .knob, .live:focus-visible .knob, .held .knob, .demo .knob { opacity: 1; transform: none; }
  .live:hover .tip, .held .tip, .demo .tip { opacity: 1; }
  /* while held the line follows the pointer 1:1 */
  .held .fill, .held .knobrow { transition: none; }
</style>
