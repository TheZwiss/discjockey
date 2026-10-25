import { describe, expect, it } from 'vitest';
import type { Dashboard, RunSummary } from '$lib/bridge/types';
import { folderLine, groupByMonth, healthCard, needsRows, nextSync, runLine, runTotals } from './dashboardModel';

// the contract example (docs/hub-bridge-contract.md, dashboard())
const EX: Dashboard = {
  greeting: 'Good evening',
  spotify: { read_at: '2026-10-20T21:47:00', minutes_ago: 0, problem: null, message: '', stale: false, reading: false,
    offline: false, auto_read: true, problem_service: null, services: [] },
  tiles: {
    lossless: { share: 0.3333, lossless: 1, total: 3,
      by_quality: { lossless: 1, good_lossy: 0, weak: 1, fake: 0, missing: 1 } },
    qobuz_today: { used: 0, allowance: 80, limit: 60, carry_over: 20, extra: 0, remaining: 80 },
    still_to_load: { count: 2, days: 1, fits_today: true },
    account_today: null,
  },
  ready: { counts: { new: 2, retries: 0, redownloads: 0, bought: 0, weekly_checks: 0 },
    actions: 2, duration_min: 5, qobuz_limit: 60, qobuz_needed: 2, qobuz_left: 80, qobuz_uses: 2,
    accounts: [{ service: 'qobuz', name: 'Qobuz', uses: 2, left: 80, limit: 60, about: false }],
    left: 80, limit: 60 },
  needs_you: { upgrades: 1, swappable: 1, not_found: 1, weak: 1 },
  folders: [],
  last_runs: [], has_more_runs: false, next_checks: 0, empty: 'not_set_up',
};
const run = (over: Partial<RunSummary> = {}): RunSummary => ({ run_id: '2026-10-19_214700',
  started: '2026-10-19T21:47:00', finished: '2026-10-19T22:11:00', duration_s: 1440, exit_code: 0,
  counts: { lossless: 9, lossy: 2, problems: 0, moved: 3 }, stopped_after: null, ...over });

describe('needs you', () => {
  it('shows upgrades, not found and weak in this order, the count apart for its column', () => {
    const rows = needsRows(EX.needs_you);
    expect(rows.map((r) => r.key)).toEqual(['upgrades', 'not_found', 'weak']);
    expect(rows[0]).toMatchObject({ label: 'Upgrade ready', n: 1, sub: '1 can be swapped, cues stay',
      href: '#/todo?filter=upgrade_ready', tone: 'good' });
    expect(rows[1]).toMatchObject({ label: 'Not found', n: 1, sub: 'buy links ready', href: '#/todo?filter=not_found',
      tone: 'problem' });
    expect(rows[2]).toMatchObject({ label: 'Weak version', n: 1, sub: 'audibly lossy (≤ 17 kHz)', href: '#/todo?filter=weak',
      tone: 'problem' });
  });
  it('leaves out rows that are zero', () => {
    const rows = needsRows({ upgrades: 0, swappable: 0, not_found: 3, weak: 4 });
    expect(rows.map((r) => r.label)).toEqual(['Not found', 'Weak versions']);
    expect(needsRows({ upgrades: 0, swappable: 0, not_found: 0, weak: 0 })).toEqual([]);
  });
  it('says plural upgrades, and "listen and decide" when none can be swapped', () => {
    expect(needsRows({ upgrades: 3, swappable: 0, not_found: 0, weak: 0 })[0]).toMatchObject({ label: 'Upgrades ready',
      sub: 'listen and decide' });
  });
});

describe('health card', () => {
  it('lossless share 0.3333 → "33" "%" with the tracks and the not found', () => {
    expect(healthCard(EX.tiles.lossless, null)).toEqual({ value: '33', unit: '%', label: 'lossless · 1 of 3 tracks · 1 not found' });
    expect(healthCard({ ...EX.tiles.lossless, by_quality: { ...EX.tiles.lossless.by_quality, missing: 0 } }, null).label)
      .toBe('lossless · 1 of 3 tracks');
  });
  it('has no number without tracks', () => {
    expect(healthCard({ ...EX.tiles.lossless, share: null, total: 0, lossless: 0 }, null))
      .toEqual({ value: null, unit: undefined, label: 'lossless · no tracks yet' });
    expect(healthCard(EX.tiles.lossless, 'empty_library').value).toBeNull();
  });
});

describe('next sync (the panel)', () => {
  const ready = EX.ready!;
  const with_ = (r: Partial<typeof ready>, d: Partial<Dashboard> = {}) => ({ ...EX, ...d, ready: { ...ready, ...r } });
  it('is running while the hub syncs, whatever ready says', () => {
    expect(nextSync(EX, true, true).state).toBe('running');
  });
  it('is unread while ready is null, pointing at the header\'s Read Spotify only when it can read', () => {
    expect(nextSync({ ...EX, ready: null }, false, true)).toMatchObject({ state: 'unread', line: expect.any(String) });
    expect(nextSync({ ...EX, ready: null }, false, false)).toMatchObject({ state: 'unread', line: null });
  });
  it('counts what runs today and its time, and draws the whole day: used, this sync, left', () => {
    const d = with_({ actions: 16, qobuz_needed: 12, qobuz_uses: 12, duration_min: 20, left: 43, limit: 60,
      counts: { ...ready.counts, new: 12, bought: 1, weekly_checks: 3 } },
    { tiles: { ...EX.tiles, qobuz_today: { ...EX.tiles.qobuz_today, used: 37, remaining: 43 } } });
    expect(nextSync(d, false, true)).toEqual({ state: 'ready', count: 16,
      time: { value: '~20', unit: 'min' }, limitReached: false, limits: { text: 'Qobuz · 80 today', full: 'Qobuz: 60 a day + 20 carried over' },
      day: { today: 12, later: 0, limited: true, laterDays: 0, day: { used: 37, allowance: 80 } } });
  });
  it('leaves the downloads over today\'s limit for later and does not count them', () => {
    const d = with_({ actions: 70, qobuz_needed: 66, qobuz_uses: 43, left: 43, limit: 60,
      counts: { ...ready.counts, new: 66, bought: 4 } });
    const r = nextSync(d, false, true);
    expect(r).toMatchObject({ state: 'ready', count: 47 });
    expect(r.state === 'ready' && r.day).toMatchObject({ today: 43, later: 23, laterDays: 1 });
  });
  it('says the limit is reached when only bought files run today', () => {
    const d = with_({ actions: 80, qobuz_needed: 77, qobuz_uses: 0, duration_min: 0, left: 0, limit: 60,
      counts: { ...ready.counts, new: 77, bought: 3 } });
    expect(nextSync(d, false, true)).toMatchObject({ state: 'ready', limitReached: true, count: 3 });
  });
  it('draws the plain bar without a daily limit', () => {
    const r = nextSync(with_({ left: null, limit: 0 }), false, true);
    expect(r).toMatchObject({ state: 'ready', limits: null, day: { limited: false, day: undefined } });
  });
  it('names the account that counts when Qobuz is not set up', () => {
    const d = with_({}, { tiles: { ...EX.tiles, account_today: { service: 'youtube', name: 'YouTube Premium', set_up: true,
      used: 4, allowance: 40, warnings: 0, new_warnings: 0, paused: false } } });
    expect(nextSync(d, false, true)).toMatchObject({ limits: { text: 'YouTube Premium · 84 today', full: 'YouTube Premium: 60 a day' } });
  });
  it('is up to date with 0 actions: the day as used and left, and the weekly checks waiting', () => {
    const d = with_({ actions: 0, qobuz_needed: 0, qobuz_uses: 0, left: 43 },
      { next_checks: 3, tiles: { ...EX.tiles, qobuz_today: { ...EX.tiles.qobuz_today, used: 37, remaining: 43 } } });
    expect(nextSync(d, false, true)).toEqual({ state: 'up_to_date', checks: 3, limits: { text: 'Qobuz · 80 today', full: 'Qobuz: 60 a day + 20 carried over' },
      day: { today: 0, later: 0, limited: true, laterDays: 0, day: { used: 37, allowance: 80 } } });
    expect(nextSync(with_({ actions: 0, left: null }), false, true)).toMatchObject({ day: null, limits: null });
  });
});

describe('folders and runs', () => {
  it('folder line: short for the column, whole for the tooltip', () => {
    expect(folderLine({ folder: 'A', tracks: 49, lossless_share: 0.82, by_quality: EX.tiles.lossless.by_quality }))
      .toEqual({ short: '49 · 82 %', full: 'A · 49 tracks · 82 % lossless · 1 not found' });
    expect(folderLine({ folder: 'A', tracks: 49, lossless_share: 0.82,
      by_quality: { ...EX.tiles.lossless.by_quality, missing: 0 } }).full).toBe('A · 49 tracks · 82 % lossless');
    expect(folderLine({ folder: 'B', tracks: 0, lossless_share: null, by_quality: EX.tiles.lossless.by_quality }))
      .toEqual({ short: 'empty', full: 'B · empty' });
  });
  it('run line: when, length, counts, stopped', () => {
    const now = new Date('2026-10-20T10:00:00');
    const l = runLine(run(), now);
    expect(l.title).toBe('Yesterday 21:47 · 24 min');
    expect(l.parts).toEqual([{ text: '9 lossless', tone: 'ok' }, { text: '2 lossy', tone: 'warn' },
      { text: '3 moved', tone: null }]);
    expect(l.href).toBe('#/sync/run/2026-10-19_214700');
    expect(l.note).toBeNull();
    expect(l.status).toBe('ok');
    expect(runLine(run({ exit_code: 1 }), now).status).toBe('failed');
    expect(runLine(run({ exit_code: 130 }), now).status).toBe('stopped');
    expect(runLine(run({ exit_code: 0, stopped_after: 3 }), now).status).toBe('stopped');
    const bad = runLine(run({ exit_code: 1, counts: { lossless: 1, lossy: 0, problems: 2, moved: 0 } }), now);
    expect(bad.parts).toEqual([{ text: '1 lossless', tone: 'ok' }, { text: '2 problems', tone: 'bad' }]);
    expect(runLine(run({ exit_code: 130, stopped_after: 61 }), now).note).toBe('stopped by you after 61 tracks');
    expect(runLine(run({ counts: { lossless: 0, lossy: 0, problems: 0, moved: 0 } }), now).parts)
      .toEqual([{ text: 'nothing changed', tone: null }]);
  });
  it('adds the runs up for All runs\' panel', () => {
    expect(runTotals([run(), run({ counts: { lossless: 1, lossy: 0, problems: 2, moved: 0 } })]))
      .toEqual({ runs: 2, added: 12, moved: 3, problems: 2 });
    expect(runTotals([])).toEqual({ runs: 0, added: 0, moved: 0, problems: 0 });
  });
  it('groups long lists by month, newest first', () => {
    const many = Array.from({ length: 12 }, (_, i) => run({ run_id: `r${i}`,
      started: i < 5 ? `2026-10-${String(15 - i).padStart(2, '0')}T21:00:00` : `2026-09-${String(28 - i).padStart(2, '0')}T21:00:00` }));
    const g = groupByMonth(many);
    expect(g.map((x) => [x.label, x.runs.length])).toEqual([['October 2026', 5], ['September 2026', 7]]);
    expect(groupByMonth(many.slice(0, 3))).toEqual([{ label: null, runs: many.slice(0, 3) }]);
  });
});
