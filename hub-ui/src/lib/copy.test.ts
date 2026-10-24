import { describe, expect, it } from 'vitest';
import { PLAN_COUNT_WORDS, detailLine, problemCopy } from './copy';

describe('detailLine', () => {
  it('drops a detail that only repeats the headline', () => {
    expect(detailLine('Your Spotify login has expired.', 'Your Spotify login has expired.')).toBe('');
  });
  it('keeps what the detail adds after the headline', () => {
    expect(detailLine('Something went wrong. Try again.', 'Something went wrong')).toBe('Try again.');
  });
  it('shows any other message verbatim', () => {
    expect(detailLine('The playlist changed on Spotify.', 'Something went wrong')).toBe('The playlist changed on Spotify.');
    expect(detailLine(null, 'Something went wrong')).toBe('');
  });
});

describe('PLAN_COUNT_WORDS', () => {
  it('names each plan count once, for the Dashboard and Sync', () => {
    expect(PLAN_COUNT_WORDS.map(([k]) => k)).toEqual(['new', 'retries', 'redownloads', 'bought',
      'weekly_checks']);
  });
});

describe('Spotify missing: one wording and one link on every page (spec §11)', () => {
  it('says "not connected" for Spotify, with the Settings link the expired login uses', () => {
    const missing = problemCopy('not_set_up', { spotify: true });
    const expired = problemCopy('login_expired', { spotify: true });
    expect(missing.title).toBe("Spotify isn't connected.");
    expect(expired.title).toBe('Your Spotify login has expired.');
    expect(missing.action).toEqual(expired.action);
    expect(expired.action).toEqual({ label: 'Connect Spotify →', href: '#/settings/spotify' });
  });
});
