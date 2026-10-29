// Spectrum helpers (contract: data = base64 of cols*bands bytes, row by row in time, each row low→high frequency).
import type { Spectrum } from '../bridge/types';

export function decodeSpectrum(spec: Spectrum): Uint8Array {
  const bin = atob(spec.data);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** The mini player's waveform: the engine's peak per column, 0–1 (1 = the loudest column). */
export function envelope(spec: Spectrum | null): number[] {
  if (!spec) return [];
  const bin = atob(spec.waveform);
  return Array.from({ length: spec.cols }, (_, c) => (bin.charCodeAt(c) || 0) / 255);
}

/** The axis label at the top-left sits 3px from the top and is about 13px tall (11px type). */
const TOP_LABEL_PX = 3 + 13;
/** Air between that label and the dashed cutoff line, so the two never read as one ("cut off at 22.1 kHz"). */
const TOP_LABEL_GAP_PX = 6;
/** Strips lower than this (the upgrade compare's) have no room for any axis label. */
const TOP_LABEL_MIN_HEIGHT = 64;

/** Whether the top axis label (the highest frequency, e.g. "22.1 kHz") shows. It needs a strip of at least 64 px and,
 *  when there is a cutoff line (`cut` = its height as a fraction of the strip, 0–1; null = none), real room between
 *  the top and that line, measured in pixels: the line has to be a label and a gap below the top. A fraction rule
 *  failed on a small strip: 64 px with a cut at 0.725 leaves 17 px, and the label sat right on the line. */
export function showTopLabel(height: number, cut: number | null): boolean {
  if (height < TOP_LABEL_MIN_HEIGHT) return false;
  if (cut === null) return true;
  return (1 - cut) * height >= TOP_LABEL_PX + TOP_LABEL_GAP_PX;
}

/** "#rgb" / "#rrggbb" → [r, g, b]. */
export function hexRgb(hex: string): [number, number, number] {
  const h = hex.trim().replace('#', '');
  const full = h.length === 3 ? h.split('').map((x) => x + x).join('') : h.slice(0, 6);
  const n = parseInt(full || '0', 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** 256 colours between the stops (the --spec-0 … --spec-5 tokens). */
export function colourMap(stops: [number, number, number][]): Uint8ClampedArray {
  const lut = new Uint8ClampedArray(256 * 3);
  for (let v = 0; v < 256; v++) {
    const x = (v / 255) * (stops.length - 1);
    const i = Math.min(stops.length - 2, Math.floor(x));
    const f = x - i;
    for (let k = 0; k < 3; k++) lut[v * 3 + k] = stops[i][k] + (stops[i + 1][k] - stops[i][k]) * f;
  }
  return lut;
}
