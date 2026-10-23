// Fake mode only: a playable WAV blob URL made in pure JS (8 kHz, 8 bit, mono, quiet), cached per (seconds, hz).
const cache = new Map<string, string>();
export const TONE_RATE = 8000;

export function toneWav(seconds: number, hz: number): Uint8Array {
  const n = Math.max(1, Math.round(seconds * TONE_RATE));
  const buf = new Uint8Array(44 + n);
  const v = new DataView(buf.buffer);
  const str = (o: number, s: string) => { for (let i = 0; i < s.length; i++) buf[o + i] = s.charCodeAt(i); };
  str(0, 'RIFF'); v.setUint32(4, 36 + n, true); str(8, 'WAVE'); str(12, 'fmt ');
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, TONE_RATE, true); v.setUint32(28, TONE_RATE, true); v.setUint16(32, 1, true); v.setUint16(34, 8, true);
  str(36, 'data'); v.setUint32(40, n, true);
  for (let i = 0; i < n; i++) {
    const t = i / TONE_RATE;
    const beat = Math.exp(-((t * 2.4) % 1) * 9);                 // a soft kick about 144 bpm
    const s = 0.18 * Math.sin(2 * Math.PI * hz * t) * (0.4 + 0.6 * beat) + 0.12 * Math.sin(2 * Math.PI * 55 * t) * beat;
    buf[44 + i] = Math.max(0, Math.min(255, Math.round(128 + 127 * s)));
  }
  return buf;
}

export function toneUrl(seconds: number, hz: number): string {
  const key = `${Math.round(seconds)}:${hz}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const url = URL.createObjectURL(new Blob([toneWav(seconds, hz) as BlobPart], { type: 'audio/wav' }));
  cache.set(key, url);
  return url;
}
