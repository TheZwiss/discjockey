import { describe, expect, it } from 'vitest';
import type { Result, RunDetail, RunSummary } from '$lib/bridge/types';
import {
  endModel, endTitle, groupByFolder, keepDetail, lastSyncStats, lastSyncView, needsDetail, otherDetail, type LastSyncDetail,
} from './endModel';

const r = (section: string, folder: string, title: string, extra: Partial<Result> = {}): Result => ({ section, folder,
  artist: 'A', title, track_id: title, note: '', status: null, source: null, cutoff_hz: null, path: null,
  error_kind: null, ...extra });
const NOW = new Date(2026, 9, 19, 23, 0);
const run = (results: Result[], extra: Partial<RunDetail> = {}): RunDetail => {
  const sections: Record<string, Result[]> = {};
  for (const x of results) (sections[x.section] ??= []).push(x);
  return { run_id: '2026-10-19_214700', started: '2026-10-19T21:23:00', finished: '2026-10-19T21:47:00',
    duration_s: 1440, exit_code: 0, counts: { lossless: 0, lossy: 0, problems: 0, moved: 0 }, stopped_after: null,
    sections, needs_you: results.filter((x) => ['missing', 'errors'].includes(x.section)),
    for_rekordbox: { new_files: 0, folders: [] }, upgrades_ready: 0, report_md: '', queued: 0,
    folder_order: ['Hard_Bounce', 'Powertrance', 'Bouncy'], ...extra };
};
const RESULTS = [
  r('new_lossless', 'Powertrance', 'p1', { status: 'lossless' }),
  r('moved', 'Hard_Bounce', 'm1', { note: 'from Library/Bouncy/A - m1.aiff' }),
  r('new_not_lossless', 'Hard_Bounce', 'h1', { status: 'not_lossless', cutoff_hz: 16000 }),
  r('missing', 'Bouncy', 'x1'),
  r('new_lossless', 'Zeta', 'z1', { status: 'lossless' }),
  r('new_lossless', 'Hard_Bounce', 'h2', { status: 'lossless' }),
  r('checked', 'Bouncy', 'c1'), r('checked', 'Bouncy', 'c2'),
  r('upgrade_ready', 'Bouncy', 'u1', { status: 'lossless' }),
];

describe('end screen', () => {
  it('groups the new files by playlist folder, in playlists.txt order, the rest by name after them', () => {
    const g = endModel(run(RESULTS), null, NOW).added;
    expect(g.map((x) => `${x.folder}: ${x.rows.map((y) => y.title).join(' ')}`)).toEqual([
      'Hard_Bounce: h1 h2', 'Powertrance: p1', 'Zeta: z1']);
    expect(g[0].reveal).toBe('Library/Hard_Bounce');
    expect(groupByFolder([], ['A'])).toEqual([]);
  });
  it('the stat cards count as the up-to-date panel does; the notes hold the rest', () => {
    const m = endModel(run(RESULTS), null, NOW);
    expect(m.stats).toEqual({ added: 4, moved: 1, needs: 1,
      byQuality: { lossless: 3, good_lossy: 0, weak: 1, fake: 0, missing: 0 } });
    expect(m.stats).toEqual(lastSyncStats(run(RESULTS)));
    expect(m.notes).toEqual([{ text: '2 tracks checked, nothing better yet', test: 'sync-checked' }]);
    expect(m.needs.map((x) => x.title)).toEqual(['x1']);
    expect(m.other.map((x) => x.title)).toEqual(['m1', 'u1']);
    expect(m.title).toBe('Sync finished');
    expect(m.sub).toBe('today 21:47 · took 24 min');
    expect(m.syncRest).toBe(false);
  });
  it('nothing new', () => {
    const m = endModel(run([r('checked', 'A', 'c1')], { duration_s: 20 }), null, NOW);
    expect(m.stats).toEqual({ added: 0, moved: 0, needs: 0, byQuality: null });
    expect(m.added).toEqual([]);
    expect(m.sub).toBe('today 21:47 · took under a minute');
  });
  it('a stopped sync says how many wait and offers the rest', () => {
    const m = endModel(run(RESULTS.slice(0, 1), { exit_code: 130, stopped_after: 1, queued: 145 }), 2, NOW);
    expect(m.title).toBe('Sync stopped');
    expect(m.notes).toEqual([
      { text: 'Stopped by you after 1 track. Nothing is half done; 145 tracks wait for the next sync.', test: 'sync-stopped-line' },
      { text: '2 new since the check, they wait for the next sync', test: 'sync-new-since' },
    ]);
    expect(m.syncRest).toBe(true);
    expect(endModel(run([], { exit_code: 130, stopped_after: 0 }), null, NOW).notes[0].text)
      .toBe('Stopped by you after 0 tracks. Nothing is half done; the next sync continues.');
  });
  it('a finished sync notes upgrades to review first, then the tracks over the limit', () => {
    expect(endModel(run([], { queued: 1, upgrades_ready: 2 }), null, NOW).notes).toEqual([
      { text: '2 upgrades ready to review', test: 'sync-upgrades', review: true },
      { text: '1 track waits for the next sync', test: 'sync-waits' },
    ]);
    expect(endTitle(1)).toBe('Sync finished with some problems');
    expect(endTitle(null)).toBe('Sync finished');
  });
  it('the second line of other changes', () => {
    expect(otherDetail(RESULTS[1])).toBe('from Bouncy');
    expect(otherDetail(r('moved', 'A', 'x', { note: 'odd' }))).toBe('');
    expect(otherDetail(r('upgrade_ready', 'A', 'x'))).toBe('a better version waits for you');
    expect(otherDetail(r('rekordbox_check', 'A', 'x', { note: 'analyse it again' }))).toBe('analyse it again');
  });
});

describe('last sync stats (the up-to-date panel)', () => {
  it('counts what the end screen counts: added by quality, moved, need you', () => {
    expect(lastSyncStats(run(RESULTS))).toEqual({ added: 4, moved: 1, needs: 1,
      byQuality: { lossless: 3, good_lossy: 0, weak: 1, fake: 0, missing: 0 } });
  });
  it('has no quality bar when nothing was added', () => {
    expect(lastSyncStats(run([r('checked', 'A', 'c1')]))).toEqual({ added: 0, moved: 0, needs: 0, byQuality: null });
  });
  it('agrees with the end screen it links to', () => {
    const m = endModel(run(RESULTS), null, NOW);
    expect(lastSyncStats(run(RESULTS))).toEqual(m.stats);
  });
});

describe('the up-to-date panel waits for the last run\'s details (Task 9C I1)', () => {
  const summary = (run_id: string): RunSummary => ({ run_id, counts: { lossless: 3, lossy: 2, problems: 4, moved: 1 } }) as unknown as RunSummary;
  const stats = { added: 5, moved: 2, needs: 3, byQuality: { lossless: 3, good_lossy: 1, weak: 1, fake: 0, missing: 0 } };
  const done = (run_id: string): LastSyncDetail => ({ run_id, stats });

  it('waits while the summary or the details of that run are still loading, so the cards draw once', () => {
    expect(lastSyncView(undefined, null)).toBe('loading');
    expect(lastSyncView(summary('r2'), null)).toBe('loading');
  });
  it('shows nothing when no sync has run yet', () => {
    expect(lastSyncView(null, null)).toBeNull();
    expect(lastSyncView(null, done('r1'))).toBeNull();
  });
  it('never shows an older run\'s details for the newest run', () => {
    expect(lastSyncView(summary('r2'), done('r1'))).toBe('loading');
    expect(lastSyncView(summary('r2'), done('r2'))).toBe(stats);
  });
  it('falls back to the summary\'s counts, without a bar, only when the details failed', () => {
    expect(lastSyncView(summary('r2'), { run_id: 'r2', stats: 'failed' }))
      .toEqual({ added: 5, moved: 1, needs: 4, byQuality: null });
  });
  it('keeps a reply only when it belongs to the run shown now', () => {
    expect(keepDetail(null, done('r1'), 'r1')).toEqual(done('r1'));
    // a slow reply for r1 arrives after the page moved on to r2 (and maybe after r2's own reply)
    expect(keepDetail(done('r2'), done('r1'), 'r2')).toEqual(done('r2'));
    expect(keepDetail(null, done('r1'), 'r2')).toBeNull();
  });
  it('loads a finished run\'s details once, and again only after a failure', () => {
    expect(needsDetail(null, 'r1')).toBe(true);
    expect(needsDetail(done('r1'), 'r1')).toBe(false);
    expect(needsDetail(done('r1'), 'r2')).toBe(true);
    expect(needsDetail({ run_id: 'r1', stats: 'failed' }, 'r1')).toBe(true);
  });
});
