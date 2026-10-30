<script lang="ts">
  // Qobuz "37 of 80", or a pause countdown "0:34" that keeps counting between events. `mark`: a thin ring round a
  // glyph with nothing inside (the rail's running sync round ⟳, plan library stage 5 N11): 2 px, decorative (the
  // glyph's tooltip says it in words), its arc moving linearly with the progress at the live pace.
  import { duration } from '../format';
  let { value, max, size = 120, label, sub, tone = 'accent', countdown = false, mark = false }:
    { value: number; max: number; size?: number; label?: string; sub?: string; tone?: 'accent' | 'lossless' | 'muted';
      countdown?: boolean; mark?: boolean } = $props();
  let shown = $state(0);
  $effect(() => {
    shown = value;
    if (!countdown) return;
    const from = value, t0 = performance.now();
    let raf = 0;
    const tick = () => { shown = Math.max(0, from - (performance.now() - t0) / 1000); if (shown > 0) raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  });
  const stroke = $derived(mark ? 2 : Math.max(4, Math.round(size / 18)));
  const r = $derived((size - stroke) / 2);
  const circ = $derived(2 * Math.PI * r);
  const frac = $derived(max > 0 ? Math.max(0, Math.min(1, shown / max)) : 0);
  const text = $derived(label ?? (countdown ? duration(Math.ceil(shown)) : String(Math.round(shown))));
</script>

<div class="ring" class:mark style:width="{size}px" style:height="{size}px" role={mark ? undefined : 'img'}
  aria-hidden={mark || undefined}
  aria-label={mark ? undefined : countdown ? `${duration(Math.ceil(shown))} left` : `${Math.round(value)} of ${max}`}>
  <svg width={size} height={size} viewBox="0 0 {size} {size}">
    <circle class="track" cx={size / 2} cy={size / 2} {r} stroke-width={stroke} />
    <circle class="val {tone}" cx={size / 2} cy={size / 2} {r} stroke-width={stroke} stroke-dasharray={circ}
      stroke-dashoffset={circ * (1 - frac)} transform="rotate(-90 {size / 2} {size / 2})" />
  </svg>
  {#if !mark}<div class="mid">
    <span class="big num" style:font-size={size >= 110 ? 'var(--fs-stat)' : 'var(--fs-title)'}>{text}</span>
    {#if sub}<span class="sub">{sub}</span>{/if}
  </div>{/if}
</div>

<style>
  .ring { position: relative; flex-shrink: 0; }
  svg { display: block; }
  circle { fill: none; }
  .track { stroke: var(--bg-inset); }
  .val { stroke-linecap: round; }
  .mark .track { stroke: var(--ctl-line); }
  .mark .val { transition: stroke-dashoffset var(--t-live) linear; }
  .accent { stroke: var(--accent); }
  .lossless { stroke: var(--q-lossless-bar); }
  .muted { stroke: var(--text-label); }
  .mid { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; }
  .big { font-weight: var(--fw-bold); color: var(--text-strong); line-height: 1.1; }
  .sub { color: var(--text-muted); font-size: var(--fs-small); }
</style>
