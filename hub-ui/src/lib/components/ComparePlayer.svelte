<script lang="ts">
  // Current vs new without a gap: both files decoded once, one AudioBufferSourceNode restarted at the same offset.
  import { onDestroy } from 'svelte';
  import { claimSound, player, releaseSound } from '../stores/player';
  import { duration } from '../format';
  import Button from './Button.svelte';
  import { scrub } from './scrub';

  type Side = { url: string; label: string };
  let { a, b, cueText }: { a: Side; b: Side; cueText?: string } = $props();
  const ME = Symbol('compare');
  let phase = $state<'idle' | 'loading' | 'playing' | 'paused' | 'error'>('idle');
  let which = $state<'a' | 'b'>('a');
  let pos = $state(0);
  let length = $state(0);
  let ctx: AudioContext | null = null;
  let buffers: Record<'a' | 'b', AudioBuffer> | null = null;
  let source: AudioBufferSourceNode | null = null;
  let startedAt = 0;
  let raf = 0;

  function now(): number { return ctx ? Math.min(length, ctx.currentTime - startedAt) : 0; }
  function tick() { pos = now(); raf = requestAnimationFrame(tick); }
  function halt() {
    if (source) { source.onended = null; try { source.stop(); } catch { /* not started */ } source.disconnect(); source = null; }
    cancelAnimationFrame(raf);
  }
  function startAt(offset: number) {
    if (!ctx || !buffers) return;
    halt();
    const s = ctx.createBufferSource();
    s.buffer = buffers[which];
    s.connect(ctx.destination);
    s.onended = () => { if (source === s) { halt(); phase = 'paused'; pos = 0; } };
    s.start(0, Math.min(offset, buffers[which].duration - 0.01));
    startedAt = ctx.currentTime - offset;
    source = s;
    phase = 'playing';
    raf = requestAnimationFrame(tick);
  }
  async function load(): Promise<boolean> {
    if (buffers) return true;
    phase = 'loading';
    try {
      ctx = new AudioContext();
      const get = async (u: string) => ctx!.decodeAudioData(await (await fetch(u)).arrayBuffer());
      const [ba, bb] = await Promise.all([get(a.url), get(b.url)]);
      buffers = { a: ba, b: bb };
      length = Math.min(ba.duration, bb.duration);
      return true;
    } catch {
      phase = 'error';
      return false;
    }
  }
  async function play() {
    player.stop();
    claimSound(ME, pause);
    if (!(await load())) return;
    await ctx?.resume();
    startAt(pos);
  }
  function pause() { pos = now(); halt(); phase = 'paused'; }
  function pick(w: 'a' | 'b') {
    if (w === which) return;
    const at = phase === 'playing' ? now() : pos;
    which = w;
    if (phase === 'playing') startAt(at);
  }
  let dragged = $state<number | null>(null);   // while the bar is held: where it is, before the seek
  const shownPos = $derived(dragged !== null ? dragged * length : pos);
  const drag = {
    move: (f: number) => { if (length) dragged = f; },
    end: (f: number) => {
      dragged = null;
      if (!length) return;
      pos = f * length;
      if (phase === 'playing') startAt(pos);
    },
    cancel: () => { dragged = null; },
  };
  function key(e: KeyboardEvent) {
    if (!length) return;
    const d = e.key === 'ArrowRight' ? 5 : e.key === 'ArrowLeft' ? -5 : 0;
    if (!d) return;
    e.preventDefault();
    pos = Math.max(0, Math.min(length, pos + d));
    if (phase === 'playing') startAt(pos);
  }
  onDestroy(() => { halt(); releaseSound(ME); void ctx?.close(); ctx = null; buffers = null; });
</script>

<div class="cmp" data-phase={phase}>
  {#if phase === 'idle'}
    <Button size="sm" variant="primary" onclick={play}>▶ Compare</Button>
    {#if cueText}<span class="cue">{cueText}</span>{/if}
  {:else if phase === 'loading'}
    <Button size="sm" busy busyLabel="Loading both versions…" />
  {:else if phase === 'error'}
    <span class="err">Can't play these files.</span>
    <Button size="sm" onclick={() => { phase = 'idle'; buffers = null; }}>Try again</Button>
  {:else}
    <div class="top">
      <button type="button" class="pp" aria-label={phase === 'playing' ? 'Pause' : 'Play'}
        onclick={() => (phase === 'playing' ? pause() : play())}>{phase === 'playing' ? '❚❚' : '▶'}</button>
      <div class="switch" role="group" aria-label="Which version">
        <button type="button" class:on={which === 'a'} aria-pressed={which === 'a'} onclick={() => pick('a')}>{a.label}</button>
        <button type="button" class:on={which === 'b'} aria-pressed={which === 'b'} onclick={() => pick('b')}>{b.label}</button>
      </div>
      <span class="time num">{duration(shownPos)} / {duration(length)}</span>
    </div>
    <div class="bar" role="slider" tabindex="0" aria-label="Position" aria-valuemin={0} aria-valuemax={Math.round(length)}
      aria-valuenow={Math.round(shownPos)} use:scrub={drag} onkeydown={key}>
      <span style:width="{length ? (shownPos / length) * 100 : 0}%"></span>
    </div>
    {#if cueText}<span class="cue">{cueText}</span>{/if}
  {/if}
</div>

<style>
  .cmp { display: flex; flex-direction: column; gap: var(--s-2); align-items: flex-start; }
  .top { display: flex; align-items: center; gap: var(--s-3); width: 100%; }
  .pp { width: 30px; height: 30px; border-radius: var(--r-pill); border: var(--bw-accent) solid var(--accent);
    color: var(--accent-text); background: transparent; font-size: var(--fs-label); padding: 0; flex-shrink: 0; }
  .switch { display: inline-flex; border: var(--bw) solid var(--line-control); border-radius: var(--r-pill); padding: 2px; }
  .switch button { border: var(--bw) solid transparent; background: transparent; color: var(--text-muted); border-radius: var(--r-pill);
    padding: 2px var(--s-3); font-size: var(--fs-small); }
  .switch button.on { border-color: var(--accent); color: var(--accent-text); }
  .time { margin-left: auto; color: var(--text-muted); font-size: var(--fs-small); white-space: nowrap; min-width: 11ch; text-align: right; }
  .bar { width: 100%; height: 4px; touch-action: none; cursor: pointer; background: var(--bg-inset); border-radius: var(--r-pill); overflow: hidden; }
  .bar span { display: block; height: 100%; background: var(--accent); }
  .cue { color: var(--text-muted); font-size: var(--fs-small); }
  .err { color: var(--q-weak); font-size: var(--fs-small); }
</style>
