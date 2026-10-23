import { describe, expect, it } from 'vitest';
import { parseHash } from '../router';
import { chipLabel, chipTone, ladderLine, limitsHref, ladderState, premiumWords, qobuzLit, qobuzWords, type RungState } from './ladderModel';
import type { DownloadsView } from '../bridge/types';

const acc = (state: string) => ({ state, browser: null, browser_name: null, profile: null, profile_name: null,
  last_check: null, tracks: 0 }) as DownloadsView['youtube'];
const view = (q: string, yt: string, sc: string): DownloadsView => ({
  qobuz: { state: q, last_check: null, tracks: 0 } as DownloadsView['qobuz'], youtube: acc(yt), soundcloud: acc(sc),
  library: { lossless: 0, account: 0, free: 0 } });
const line = (q: string, yt: string, sc: string) => ladderLine(ladderState(view(q, yt, sc)));

describe('ladderState', () => {
  it('copies each state and lights the accounts rung for a working account', () => {
    expect(ladderState(view('on', 'on', 'off'))).toEqual({ qobuz: 'on', youtube: 'on', soundcloud: 'off', accounts: true });
    expect(ladderState(view('on', 'off', 'on')).accounts).toBe(true);
  });
  it('a SoundCloud login without confirmed Go+ is still used, so it lights the rung (R26)', () => {
    expect(ladderState(view('on', 'off', 'no_premium')).accounts).toBe(true);
  });
  it('a YouTube login without Premium does not light it', () => {
    expect(ladderState(view('on', 'no_premium', 'off')).accounts).toBe(false);
  });
  it('a paused, used-up or unreadable account does not light it', () => {
    expect(ladderState(view('on', 'paused', 'off'))).toEqual({ qobuz: 'on', youtube: 'paused', soundcloud: 'off', accounts: false });
    expect(ladderState(view('on', 'used_up', 'unreadable')).accounts).toBe(false);
  });
});

describe('qobuzLit', () => {
  it('counts a paused or used-up Qobuz as there (it comes back tomorrow)', () => {
    expect((['on', 'paused', 'used_up'] as RungState[]).map(qobuzLit)).toEqual([true, true, true]);
    expect((['off', 'skipped'] as RungState[]).map(qobuzLit)).toEqual([false, false]);
  });
});

describe('ladderLine (spec §4: four sentences)', () => {
  it('names the account that carries the 256 rung', () => {
    expect(line('on', 'off', 'on')).toBe("Songs Qobuz doesn't have come in at about 256 kbps through SoundCloud Go+.");
    expect(line('on', 'on', 'on')).toBe("Songs Qobuz doesn't have come in at about 256 kbps through YouTube Premium.");
    expect(line('on', 'off', 'no_premium')).toBe("Songs Qobuz doesn't have come in at about 256 kbps through SoundCloud Go+.");
  });
  it('a paused or used-up Qobuz still counts', () => {
    expect(line('paused', 'on', 'off')).toBe("Songs Qobuz doesn't have come in at about 256 kbps through YouTube Premium.");
    expect(line('used_up', 'off', 'off')).toBe("Songs Qobuz doesn't have come from free YouTube at about 130 kbps.");
  });
  it('says what is missing without accounts', () => {
    expect(line('on', 'off', 'off')).toBe("Songs Qobuz doesn't have come from free YouTube at about 130 kbps.");
    expect(line('on', 'paused', 'off')).toBe("Songs Qobuz doesn't have come from free YouTube at about 130 kbps.");
  });
  it('without Qobuz', () => {
    expect(line('skipped', 'on', 'off')).toBe("Without Qobuz nothing comes in lossless, except the artists' own files.");
    expect(line('off', 'off', 'off')).toBe('Without Qobuz or an account, most songs come in at about 130 kbps.');
    expect(line('skipped', 'no_premium', 'unreadable')).toBe('Without Qobuz or an account, most songs come in at about 130 kbps.');
  });
});

describe('chips', () => {
  it('tone: ✓ for on, ! for anything the user should look at, dashed for nothing', () => {
    expect((['on', 'no_premium', 'paused', 'used_up', 'off', 'unreadable', 'skipped'] as RungState[]).map(chipTone))
      .toEqual(['good', 'warn', 'warn', 'warn', 'none', 'none', 'none']);
  });
  it('label says the state in words, with the full account name', () => {
    expect(chipLabel('youtube', 'on')).toBe('YouTube Premium: signed in');
    expect(chipLabel('soundcloud', 'no_premium')).toBe('SoundCloud Go+: Go+ not confirmed');
    expect(chipLabel('youtube', 'no_premium')).toBe('YouTube Premium: Premium not confirmed');
    expect(chipLabel('youtube', 'paused')).toBe('YouTube Premium: paused today, see Download limits');
    expect(chipLabel('soundcloud', 'used_up')).toBe('SoundCloud Go+: used up today, see Download limits');
    expect(chipLabel('soundcloud', 'unreadable')).toBe("SoundCloud Go+: the login can't be read");
    expect(chipLabel('youtube', 'off')).toBe('YouTube Premium: not set up');
  });
});

describe('sub-lines', () => {
  it('Qobuz', () => {
    expect(qobuzWords('on', false)).toBe('signed in');
    expect(qobuzWords('paused', false)).toBe('signed in · paused today');
    expect(qobuzWords('paused', true)).toBe('paused today');
    expect(qobuzWords('used_up', false)).toBe('signed in · used up today');
    expect(qobuzWords('skipped', false)).toBe('not used');
    expect(qobuzWords('off', true)).toBe('not signed in');
  });
  it('Premium streams, lit: through whichever account works', () => {
    const w = (yt: string, sc: string, compact = false) => premiumWords(ladderState(view('on', yt, sc)), compact);
    expect(w('on', 'off')).toBe('through YouTube Premium');
    expect(w('off', 'on')).toBe('through SoundCloud Go+');
    expect(w('on', 'on')).toBe('through YouTube Premium and SoundCloud Go+');
    expect(w('on', 'on', true)).toBe('through Premium and Go+');
    expect(w('off', 'no_premium')).toBe('through SoundCloud · Go+ not confirmed');
    expect(w('off', 'no_premium', true)).toBe('Go+ not confirmed');
    expect(w('on', 'no_premium')).toBe('through YouTube Premium');
  });
  it('Premium streams, not lit: why, YouTube first', () => {
    const w = (yt: string, sc: string, compact = false) => premiumWords(ladderState(view('on', yt, sc)), compact);
    expect(w('off', 'off')).toBe('needs YouTube Premium or SoundCloud Go+');
    expect(w('off', 'off', true)).toBe('needs Premium or Go+');
    expect(w('paused', 'off')).toBe('YouTube Premium paused today');
    expect(w('paused', 'off', true)).toBe('YouTube paused today');
    expect(w('off', 'used_up')).toBe('SoundCloud Go+ used up today');
    expect(w('unreadable', 'paused')).toBe("can't read the YouTube login");
    expect(w('no_premium', 'off', true)).toBe('Premium not confirmed');
  });
});

describe('limitsHref', () => {
  it('paused or used up goes to that service on the Download limits page', () => {
    for (const service of ['qobuz', 'youtube', 'soundcloud'] as const) {
      for (const s of ['paused', 'used_up']) {
        const r = parseHash(limitsHref(service, s)!);
        expect(r.name).toBe('limits');
        expect(r.params.service).toBe(service);
      }
    }
  });
  it('every other state picks its row instead', () => {
    for (const s of ['on', 'off', 'skipped', 'no_premium', 'unreadable']) expect(limitsHref('youtube', s)).toBeNull();
  });
});
