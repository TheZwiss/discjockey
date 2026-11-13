import { describe, expect, it } from 'vitest';
import { EMPTY_RUN, type RunState } from '../stores/run';
import { activityLine, activityShort, activityText } from './activity';

const run = (o: Partial<RunState>): RunState => ({ ...EMPTY_RUN, ...o });

describe('activityShort (the player bar\'s right end)', () => {
  it('says which action of how many', () => {
    expect(activityShort(run({ phase: 'running', total: 6, index: 4 }))).toBe('Sync 4 of 6');
  });
  it('says reading and stopping like the long form', () => {
    expect(activityShort(run({ phase: 'preparing' }))).toBe('Reading playlists…');
    expect(activityShort(run({ phase: 'running', total: null }))).toBe('Reading playlists…');
    expect(activityShort(run({ phase: 'stopping', total: 6, index: 2 }))).toBe('Stopping…');
  });
});

describe('activityLine (its tooltip)', () => {
  it('joins the long form into one sentence, the Qobuz count last', () => {
    const s = run({ phase: 'running', total: 6, index: 4, qobuz: { used: 1, allowance: 80 } });
    expect(activityLine(activityText(s, 0))).toBe('Sync running · 4 of 6 · Searching · Qobuz 1 of 80 today');
  });
});

describe('the sync\'s Auto-upgrade phase', () => {
  const upgrading = run({ phase: 'upgrading', total: 6, index: 6, upgrade: { batch_id: 3, done: 2, total: 9, name: 'Artist - Title' } });
  it('names the track and how many are done', () => {
    expect(activityLine(activityText(upgrading, 0))).toBe('Upgrading · Artist - Title · 2 of 9 upgraded');
    expect(activityShort(upgrading)).toBe('2 of 9 upgraded');
  });
  it('after the last track only the count is left', () => {
    const end = run({ phase: 'upgrading', total: 6, index: 6, upgrade: { batch_id: 3, done: 9, total: 9, name: null } });
    expect(activityLine(activityText(end, 0))).toBe('Upgrading · 9 of 9 upgraded');
    expect(activityShort(end)).toBe('9 of 9 upgraded');
  });
});
