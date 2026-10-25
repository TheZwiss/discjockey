import { describe, expect, it } from 'vitest';
import type { Result } from '$lib/bridge/types';
import { chipCounts, coverMap, fixHref, listFor, liveMessage, rowBadge, segOptions } from './results';

const r = (section: string, extra: Partial<Result> = {}): Result => ({ section, folder: 'Hard_Bounce', artist: 'A',
  title: section, track_id: section, note: '', status: null, source: null, cutoff_hz: null, path: null,
  error_kind: null, ...extra });
const RESULTS = [
  r('new_lossless', { status: 'lossless', source: 'qobuz' }),
  r('missing', { error_kind: 'not_found' }),
  r('new_not_lossless', { status: 'not_lossless', source: 'youtube_music', cutoff_hz: 20000 }),
  r('moved'),
  r('errors', { error_kind: 'network' }),
  r('fake', { status: 'fake_lossless', cutoff_hz: 16000 }),
  r('upgrade_ready', { status: 'not_lossless', source: 'qobuz' }),
];

describe('result list', () => {
  it('counts each chip (Lossy = not_lossless and fake, Problems = missing/errors/conflicts/ambiguous)', () => {
    expect(chipCounts(RESULTS)).toEqual({ all: 7, lossless: 2, lossy: 2, problems: 2 });
    expect(chipCounts([])).toEqual({ all: 0, lossless: 0, lossy: 0, problems: 0 });
  });
  it('gives the filter strip its segments: counts, and a quality dot on all but All (spec §8)', () => {
    expect(segOptions(RESULTS)).toEqual([
      { key: 'all', label: 'All', count: 7 },
      { key: 'lossless', label: 'Lossless', count: 2, dot: 'lossless' },
      { key: 'lossy', label: 'Lossy', count: 2, dot: 'good_lossy' },
      { key: 'problems', label: 'Problems', count: 2, dot: 'weak' },
    ]);
    expect(segOptions([]).map((o) => o.count)).toEqual([0, 0, 0, 0]);
  });
  it('puts problems first and keeps run order', () => {
    const all = listFor(RESULTS, 'all');
    expect(all.problems.map((x) => x.section)).toEqual(['missing', 'errors']);
    expect(all.done.map((x) => x.section)).toEqual(['new_lossless', 'new_not_lossless', 'moved', 'fake', 'upgrade_ready']);
  });
  it('filters by chip', () => {
    expect(listFor(RESULTS, 'lossy').done.map((x) => x.section)).toEqual(['new_not_lossless', 'fake']);
    expect(listFor(RESULTS, 'lossy').problems).toEqual([]);
    expect(listFor(RESULTS, 'problems').done).toEqual([]);
    expect(listFor(RESULTS, 'lossless').done.map((x) => x.section)).toEqual(['new_lossless', 'upgrade_ready']);
  });
  it('labels the rows', () => {
    expect(RESULTS.map((x) => rowBadge(x).text)).toEqual(['LOSSLESS', 'NOT FOUND', '20.0 kHz · YT Music',
      'MOVED → Hard_Bounce', 'NO INTERNET · retried next run', 'FAKE · 16.0 kHz', 'UPGRADE READY']);
    expect(rowBadge(r('errors', { error_kind: 'qobuz' })).text).toBe('QOBUZ PROBLEM');
  });
  it('counts and labels an upgrade by the found file, not the current one (found_status, else the source rule)', () => {
    const up = (extra: Partial<Result>) => r('upgrade_ready', { status: 'not_lossless', ...extra });
    const sc = up({ source: 'soundcloud', found_status: 'lossless' });
    const q = up({ source: 'qobuz', found_status: 'not_lossless' });
    expect(chipCounts([sc, q])).toEqual({ all: 2, lossless: 1, lossy: 1, problems: 0 });
    expect(listFor([sc, q], 'lossless').done).toEqual([sc]);
    expect(listFor([sc, q], 'lossy').done).toEqual([q]);
    expect(rowBadge(sc)).toMatchObject({ tone: 'lossless', text: 'UPGRADE READY' });
    expect(rowBadge(q)).toMatchObject({ tone: 'good_lossy', text: 'UPGRADE READY · Qobuz' });
    expect(chipCounts([up({ source: 'qobuz' }), up({ source: 'soundcloud' })])).toMatchObject({ lossless: 1, lossy: 1 });
  });
  it('links problems to the to-do item', () => {
    expect(fixHref(r('missing', { track_id: 't 1' }))).toBe('#/todo?track=t%201');
    expect(fixHref(r('missing', { track_id: null }))).toBeNull();
  });
});

describe('below the live card', () => {
  const msg = (text: string, at: number) => ({ level: 'info' as const, text, at });
  it('shows the last message until a track starts or finishes after it', () => {
    const messages = [msg('Reading your playlists…', 100)];
    expect(liveMessage({ messages, last_started_at: null, last_finished_at: null })).toBe('Reading your playlists…');
    expect(liveMessage({ messages, last_started_at: 150, last_finished_at: null })).toBeNull();
    expect(liveMessage({ messages, last_started_at: null, last_finished_at: 150 })).toBeNull();
    expect(liveMessage({ messages: [...messages, msg('Qobuz paused for this run', 200)], last_started_at: 150,
      last_finished_at: null })).toBe('Qobuz paused for this run');
    expect(liveMessage({ messages: [], last_started_at: null, last_finished_at: null })).toBeNull();
  });
  it('finds each cover: the saved selection first (as in the plan), then the engine\'s link', () => {
    const covers = coverMap(
      [{ track_id: 'a', cover_url: 'local/a.jpg' }, { track_id: 'b' }, { track_id: 'c', cover_url: null }],
      [{ track_id: 'a', image_url: 'spotify/a' }, { track_id: 'b', image_url: 'spotify/b' }, { track_id: 'd' }]);
    expect(covers.get('a')).toBe('local/a.jpg');
    expect(covers.get('b')).toBe('spotify/b');
    expect(covers.get('c')).toBeUndefined();
    expect(covers.get('d')).toBeUndefined();
  });
});
