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

describe('a playlist service missing: one wording and one link per service on every page (spec §11)', () => {
  it('says "not connected" for Spotify, with the Settings link the expired login uses', () => {
    const missing = problemCopy('not_set_up', { service: 'spotify' });
    const expired = problemCopy('login_expired', { service: 'spotify' });
    expect(missing.title).toBe("Spotify isn't connected.");
    expect(expired.title).toBe('Your Spotify login has expired.');
    expect(missing.action).toEqual(expired.action);
    expect(expired.action).toEqual({ label: 'Connect Spotify →', href: '#/settings/spotify' });
  });
  it("names Qobuz with its own card and Settings' Qobuz login (I8 W6)", () => {
    expect(problemCopy('not_set_up', { service: 'qobuz' })).toEqual({ title: "Qobuz isn't connected.",
      action: { label: 'Connect Qobuz →', href: '#/settings/qobuz' } });
  });
  it("keeps the engine's not_set_up (no playlists.txt) when no service caused it", () => {
    expect(problemCopy('not_set_up').title).toBe("Discjockey isn't set up yet.");
    expect(problemCopy('not_set_up', { service: null }).action?.href).toBe('#/setup');
  });
  it('never hard-codes one service\'s words for an unreadable playlist: the engine\'s message says it', () => {
    expect(problemCopy('playlist_unreadable', { service: 'qobuz' }).hint).toBeUndefined();
    expect(problemCopy('playlist_unreadable').hint).toBeUndefined();
  });
});
