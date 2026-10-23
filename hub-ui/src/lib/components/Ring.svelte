<script lang="ts">
  // Qobuz "37 of 80", or a pause countdown "0:34" that keeps counting between events.
  import { duration } from '../format';
  let { value, max, size = 120, label, sub, tone = 'accent', countdown = false }:
    { value: number; max: number; size?: number; label?: string; sub?: string; tone?: 'accent' | 'lossless' | 'muted';
      countdown?: boolean } = $props();
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
  const stroke = $derived(Math.max(4, Math.round(size / 18)));
  const r = $derived((size - stroke) / 2);
  const circ = $derived(2 * Math.PI * r);
  const frac = $derived(max > 0 ? Math.max(0, Math.min(1, shown / max)) : 0);
  const text = $derived(label ?? (countdown ? duration(Math.ceil(shown)) : String(Math.round(shown))));
</script>

<div class="ring" style:width="{size}px" style:height="{size}px" role="img"
  aria-label={countdown ? `${duration(Math.ceil(shown))} left` : `${Math.round(value)} of ${max}`}>
  <svg width={size} height={size} viewBox="0 0 {size} {size}">
    <circle class="track" cx={size / 2} cy={size / 2} {r} stroke-width={stroke} />
    <circle class="val {tone}" cx={size / 2} cy={size / 2} {r} stroke-width={stroke} stroke-dasharray={circ}
      stroke-dashoffset={circ * (1 - frac)} transform="rotate(-90 {size / 2} {size / 2})" />
  </svg>
  <div class="mid">
    <span class="big num" style:font-size={size >= 110 ? 'var(--fs-stat)' : 'var(--fs-title)'}>{text}</span>
    {#if sub}<span class="sub">{sub}</span>{/if}
  </div>
</div>

<style>
  .ring { position: relative; flex-shrink: 0; }
  svg { display: block; }
  circle { fill: none; }
  .track { stroke: var(--bg-inset); }
  .val { stroke-linecap: round; }
  .accent { stroke: var(--accent); }
  .lossless { stroke: var(--q-lossless-bar); }
  .muted { stroke: var(--text-label); }
  .mid { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; }
  .big { font-weight: var(--fw-bold); color: var(--text-strong); line-height: 1.1; }
  .sub { color: var(--text-muted); font-size: var(--fs-small); }
</style>
