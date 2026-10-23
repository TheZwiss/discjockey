<script lang="ts" module>
  export { envelope } from './spectrum-data';
</script>

<script lang="ts">
  // Canvas cols × bands (y = band, low at the bottom), colour map --spec-0…5 by v/255, dashed cutoff line.
  import type { Spectrum } from '../bridge/types';
  import { khz } from '../format';
  import { colourMap, decodeSpectrum, hexRgb } from './spectrum-data';
  import Skeleton from './Skeleton.svelte';

  let { spectrum, height = 96, loading = false, cutoffLabel = true, error = null, noFile = false }:
    { spectrum: Spectrum | null; height?: number; loading?: boolean; cutoffLabel?: boolean; error?: string | null;
      noFile?: boolean } = $props();
  let canvas: HTMLCanvasElement | undefined = $state();

  $effect(() => {
    if (!canvas || !spectrum) return;
    const css = getComputedStyle(document.documentElement);
    const stops = [0, 1, 2, 3, 4, 5].map((i) => hexRgb(css.getPropertyValue(`--spec-${i}`)));
    const lut = colourMap(stops);
    const { cols, bands } = spectrum;
    const d = decodeSpectrum(spectrum);
    canvas.width = cols;
    canvas.height = bands;
    const g = canvas.getContext('2d');
    if (!g) return;
    const img = g.createImageData(cols, bands);
    for (let c = 0; c < cols; c++) {
      for (let b = 0; b < bands; b++) {
        const v = d[c * bands + b] ?? 0;
        const p = ((bands - 1 - b) * cols + c) * 4;
        img.data[p] = lut[v * 3]; img.data[p + 1] = lut[v * 3 + 1]; img.data[p + 2] = lut[v * 3 + 2]; img.data[p + 3] = 255;
      }
    }
    g.putImageData(img, 0, 0);
  });
  const cut = $derived(spectrum?.cutoff_hz ? Math.min(1, spectrum.cutoff_hz / spectrum.max_hz) : null);
</script>

<div class="spec" style:height="{height}px">
  {#if loading}
    <Skeleton height={height - 2} />
  {:else if error}
    <div class="msg bad">{error}</div>
  {:else if !spectrum || noFile}
    <div class="msg">No file yet</div>
  {:else}
    <canvas bind:this={canvas} aria-label="Spectrum{cut ? `, cut off at ${khz(spectrum.cutoff_hz)}` : ''}"></canvas>
    {#if cut !== null}
      <div class="cut" style:bottom="{cut * 100}%"></div>
      <!-- near the top the label goes below the line; above it, it would be cut off by the frame -->
      {#if cutoffLabel}<span class="cutlabel" style:bottom={cut > 0.75 ? `calc(${cut * 100}% - 1.4em - 2px)` : `calc(${cut * 100}% + 2px)`}>cut off at {khz(spectrum.cutoff_hz)}</span>{/if}
    {/if}
    <!-- small strips (upgrade compare) have no room for the top label, and near the top it would sit on the
         cutoff line -->
    {#if height >= 64 && (cut === null || cut < 0.8)}<span class="axis top">{khz(spectrum.max_hz)}</span>{/if}
  {/if}
</div>

<style>
  .spec { position: relative; border: var(--bw) solid var(--line-card); border-radius: 6px; overflow: hidden; background: var(--bg); }
  canvas { width: 100%; height: 100%; display: block; }
  .cut { position: absolute; left: 0; right: 0; border-top: var(--bw) dashed var(--text-strong); opacity: .7; }
  .cutlabel { position: absolute; right: 6px; font-size: var(--fs-label); color: var(--text-strong);
    text-shadow: 0 0 3px var(--bg), 0 0 3px var(--bg); }
  .axis { position: absolute; left: 6px; font-size: var(--fs-label); color: var(--text-muted);
    text-shadow: 0 0 3px var(--bg), 0 0 3px var(--bg); }
  .axis.top { top: 3px; }
  .msg { height: 100%; display: flex; align-items: center; justify-content: center; color: var(--text-label);
    font-size: var(--fs-small); }
  .bad { color: var(--q-weak); }
</style>
