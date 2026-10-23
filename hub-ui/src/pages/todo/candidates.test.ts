import { describe, expect, it } from 'vitest';
import type { Candidate } from '$lib/bridge/types';
import { canUse, lengthText, lengthTone, previewOffer, progressText, secondLine } from './candidates';

const cand = (more: Partial<Candidate> = {}): Candidate => ({
  source: 'youtube_music', id: 'x', title: 'Get Naughty', artist: 'Armin Hermann', duration_s: 268, url: null,
  isrc: null, album: null, label: null, image_url: null, key: 'youtube_music:x', source_name: 'YT Music',
  length_diff_s: 0, can_preview: true, score: 90, matches: true, length_ok: true, current: false, rejected: false,
  ...more,
});

describe('length colour', () => {
  it('is green within ±3 s and yellow outside', () => {
    expect(lengthTone(cand({ length_diff_s: 0 }))).toBe('ok');
    expect(lengthTone(cand({ length_diff_s: 3 }))).toBe('ok');
    expect(lengthTone(cand({ length_diff_s: -3 }))).toBe('ok');
    expect(lengthTone(cand({ length_diff_s: 3.1 }))).toBe('warn');
    expect(lengthTone(cand({ length_diff_s: -41 }))).toBe('warn');
  });
  it('has no colour and shows "–" when the length is unknown', () => {
    expect(lengthTone(cand({ length_diff_s: null, duration_s: null }))).toBe('none');
    expect(lengthText(cand({ duration_s: null }))).toBe('–');
    expect(lengthText(cand({ duration_s: 268 }))).toBe('4:28');
  });
});

describe('which rows offer ▶ and Use this', () => {
  it('offers ▶ when the backend can preview, never for Qobuz', () => {
    expect(previewOffer(cand())).toEqual({ show: true, title: null });
    expect(previewOffer(cand({ can_preview: false }))).toEqual({ show: false, title: null });
    expect(previewOffer(cand({ source: 'qobuz', can_preview: true }))).toEqual({ show: false,
      title: 'Qobuz versions have no preview.' });
  });
  it('offers Use this except on the current file and on rejected versions', () => {
    expect(canUse(cand())).toBe(true);
    expect(canUse(cand({ current: true }))).toBe(false);
    expect(canUse(cand({ rejected: true }))).toBe(false);
  });
  it('labels the current and rejected rows', () => {
    expect(secondLine(cand({ current: true }))).toBe('current · you marked it as wrong');
    expect(secondLine(cand({ rejected: true }))).toBe('Armin Hermann · rejected before');
    expect(secondLine(cand())).toBe('Armin Hermann');
  });
});

describe('download progress line', () => {
  it('names the step, with the percentage while downloading', () => {
    const progress = { type: 'Progress', track_id: 't17', step: 'download', done: 64, total: 100, unit: 'bytes',
      at: 0, rate: null } as never;
    expect(progressText({ step: 'download', progress })).toBe('Downloading… 64 %');
    expect(progressText({ step: 'check', progress: null })).toBe('Checking the length…');
    expect(progressText({ step: 'convert', progress: null })).toBe('Converting…');
    expect(progressText({ step: null, progress: null })).toBe('Starting…');
  });
});
