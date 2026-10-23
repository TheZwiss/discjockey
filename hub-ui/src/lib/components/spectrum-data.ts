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
