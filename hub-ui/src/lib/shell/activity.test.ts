import { describe, expect, it } from 'vitest';
import { EMPTY_RUN, type RunState } from '../stores/run';
import { activityLine, activityShort, activityText } from './activity';

const run = (o: Partial<RunState>): RunState => ({ ...EMPTY_RUN, ...o });

describe('activityShort (the player bar\'s right end)', () => {
  it('says which action of how many', () => {
    expect(activityShort(run({ phase: 'running', total: 6, index: 4 }))).toBe('Sync 4 of 6');
  });
  it('says reading and stopping like the long form', () => {
    expect(activityShort(run({ phase: 'preparing' }))).toBe('Reading Spotify…');
    expect(activityShort(run({ phase: 'running', total: null }))).toBe('Reading Spotify…');
    expect(activityShort(run({ phase: 'stopping', total: 6, index: 2 }))).toBe('Stopping…');
  });
});

describe('activityLine (its tooltip)', () => {
  it('joins the long form into one sentence, the Qobuz count last', () => {
    const s = run({ phase: 'running', total: 6, index: 4, qobuz: { used: 1, allowance: 80 } });
    expect(activityLine(activityText(s, 0))).toBe('Sync running · 4 of 6 · Searching · Qobuz 1 of 80 today');
  });
});
