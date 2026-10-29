import { describe, expect, it } from 'vitest';
import { colourMap, decodeSpectrum, envelope, hexRgb, showTopLabel } from './spectrum-data';
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
  it('envelope is the engine\'s waveform: one peak per column, 0–1', () => {
    const e = envelope(fakeSpectrum(null, 3));
    expect(e).toHaveLength(400);
    expect(Math.max(...e)).toBeCloseTo(1);
    expect(Math.min(...e)).toBeGreaterThanOrEqual(0);
    expect(envelope(null)).toEqual([]);
  });
  it('a loud transient shows as its peak, not as the column\'s mean energy', () => {
    const s = fakeSpectrum(null, 3);
    const wave = new Uint8Array(s.cols).fill(40);
    wave[100] = 255;                                     // the kick's attack
    const flat = new Uint8Array(s.cols * s.bands).fill(60); // every column equally loud as a spectrum
    const bin = (b: Uint8Array) => btoa(String.fromCharCode(...b));
    const e = envelope({ ...s, data: bin(flat), waveform: bin(wave) });
    expect(e[100]).toBe(1);
    expect(e[99]).toBeCloseTo(40 / 255);
  });
  it('colour map runs from the first to the last stop', () => {
    expect(hexRgb('#ff5a1f')).toEqual([255, 90, 31]);
    expect(hexRgb('#000')).toEqual([0, 0, 0]);
    const lut = colourMap([[0, 0, 0], [255, 255, 255]]);
    expect([...lut.slice(0, 3)]).toEqual([0, 0, 0]);
    expect([...lut.slice(255 * 3)]).toEqual([255, 255, 255]);
  });
});

describe('showTopLabel', () => {
  it('hides the label on strips too low for any axis label, with or without a cutoff', () => {
    expect(showTopLabel(40, null)).toBe(false);
    expect(showTopLabel(56, 0.3)).toBe(false);
  });
  it('shows it when there is no cutoff line', () => {
    expect(showTopLabel(64, null)).toBe(true);
  });
  it('hides it when the line is closer to the top than a label and a gap (a 16 kHz file in the 64 px strip)', () => {
    expect(showTopLabel(64, 0.725)).toBe(false);
    expect(showTopLabel(64, 0.8)).toBe(false);
  });
  it('shows it when the line is far enough down in the 64 px strip', () => {
    expect(showTopLabel(64, 0.5)).toBe(true);
    expect(showTopLabel(64, 0.65)).toBe(true);
  });
  it('measures in pixels: the same cutoff fits a taller strip', () => {
    expect(showTopLabel(110, 0.75)).toBe(true);
    expect(showTopLabel(110, 0.9)).toBe(false);
  });
  it('22 px between the top and the line is enough, less is not', () => {
    expect(showTopLabel(88, 0.75)).toBe(true);
    expect(showTopLabel(88, 0.76)).toBe(false);
  });
});
