import { describe, expect, it } from 'vitest';
import { colourMap, decodeSpectrum, envelope, hexRgb } from './spectrum-data';
import { fakeSpectrum } from '../bridge/fake/spectrum';

describe('spectrum helpers', () => {
  it('decodes the contract shape and removes energy above the cutoff', () => {
    const s = fakeSpectrum(16000, 7);
    const d = decodeSpectrum(s);
    expect(d.length).toBe(s.cols * s.bands);
    const cut = Math.floor((16000 / s.max_hz) * s.bands);
    let above = 0, below = 0;
    for (let c = 0; c < s.cols; c++) { above += d[c * s.bands + cut + 2]; below += d[c * s.bands + 5]; }
    expect(above / s.cols).toBeLessThan(10);
    expect(below / s.cols).toBeGreaterThan(60);
  });
  it('envelope is one value per column, 0–1', () => {
    const e = envelope(fakeSpectrum(null, 3));
    expect(e).toHaveLength(400);
    expect(Math.max(...e)).toBeCloseTo(1);
    expect(Math.min(...e)).toBeGreaterThanOrEqual(0);
    expect(envelope(null)).toEqual([]);
  });
  it('colour map runs from the first to the last stop', () => {
    expect(hexRgb('#ff5a1f')).toEqual([255, 90, 31]);
    expect(hexRgb('#000')).toEqual([0, 0, 0]);
    const lut = colourMap([[0, 0, 0], [255, 255, 255]]);
    expect([...lut.slice(0, 3)]).toEqual([0, 0, 0]);
    expect([...lut.slice(255 * 3)]).toEqual([255, 255, 255]);
  });
});
