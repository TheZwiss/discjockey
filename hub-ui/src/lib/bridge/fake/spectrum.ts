// Fake mode only: a contract-shaped spectrum (400 × 128 bytes, base64) with the energy above the cutoff removed.
import type { Spectrum, Which } from '../types';

export const COLS = 400, BANDS = 128, MAX_HZ = 22050;

function rand(seed: number) {
  let x = seed | 0 || 1;
  return () => { x ^= x << 13; x ^= x >>> 17; x ^= x << 5; return ((x >>> 0) % 10000) / 10000; };
}

export function fakeSpectrumBytes(cutoff_hz: number | null, seed: number): Uint8Array {
  const r = rand(seed);
  const out = new Uint8Array(COLS * BANDS);
  const cutBand = cutoff_hz === null ? BANDS : Math.floor((cutoff_hz / MAX_HZ) * BANDS);
  for (let c = 0; c < COLS; c++) {
    const section = Math.sin((c / COLS) * Math.PI * 3 + seed) * 0.5 + 0.5;  // louder and quieter parts
    const kick = c % 8 < 2 ? 1 : 0.88;
    const breakdown = c > 210 && c < 250 ? 0.55 : 1;
    for (let b = 0; b < BANDS; b++) {
      if (b >= cutBand) { out[c * BANDS + b] = Math.round(r() * 6); continue; }
      const tilt = Math.pow(1 - b / BANDS, 0.9);                               // high bands are quieter
      const v = (0.62 + 0.3 * section) * tilt * kick * breakdown + (r() - 0.5) * 0.12;
      out[c * BANDS + b] = Math.max(0, Math.min(255, Math.round(v * 255)));
    }
  }
  return out;
}

function base64(bytes: Uint8Array): string {
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

export function fakeSpectrum(cutoff_hz: number | null, seed: number, duration_s = 180,
  which: Which = 'current'): Spectrum {
  return { cols: COLS, bands: BANDS, max_hz: MAX_HZ, duration_s, floor_db: -100,
    data: base64(fakeSpectrumBytes(cutoff_hz, seed)), which, cutoff_hz };
}
