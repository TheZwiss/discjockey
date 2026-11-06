import { describe, expect, it } from 'vitest';
import type { ActionKey, EstimateAccount, PlaylistService, PreviewAction, SyncAccount, SyncPreview } from '$lib/bridge/types';
import {
  chosenOf, everyOff, folderSwitch, memberOn, resolveLegacy, sectionOf,
  FULL_SCOPE, type Scope, dayBarInput, defaultHowMany, downloadsInScope, inScope, folderLabel, foldText, howManyOptions, inRunOrder, isKindKey, kindShares, weeklyItems, planCounts, switchTip, dayBarEmpty, leftOutBody, stripLine,
  kindOf, matches, mayWaitToday, nextSyncSet, presetN, presetTicks, presets, readHowMany, readScope, runCount,
  minutesFor, runsNothingToday, runTime, runTotals, scopeSet, sectionCounts, sections, sectionSummary, serviceRows, shouldAutoRead, shownPreset,
  readBlockLine, leftOutTitle, startLabel, tagOf, whyOf, toggleScope, waitsWhole, whyColumn,
  WAITING_ANSWERS_HREF, deferredChecksLine, waitingAnswersLine,
} from './planModel';

describe('the import hints (W9)', () => {
  it('say the songs that wait for an answer, singular for 1, nothing at 0', () => {
    expect(waitingAnswersLine(0)).toBeNull();
    expect(waitingAnswersLine(1)).toBe('1 song waits for your answer on the To-do page.');
    expect(waitingAnswersLine(3)).toBe('3 songs wait for your answer on the To-do page.');
    expect(WAITING_ANSWERS_HREF).toBe('#/todo?filter=same_song');
  });
  it('say the first upgrade checks left for later runs, singular for 1, nothing at 0', () => {
    expect(deferredChecksLine(0)).toBeNull();
    expect(deferredChecksLine(1)).toBe("1 first upgrade check of your imported music waits for later runs, so today's "
      + "Qobuz allowance isn't used up.");
    expect(deferredChecksLine(40)).toBe("40 first upgrade checks of your imported music wait for later runs, so "
      + "today's Qobuz allowance isn't used up.");
  });
});
import { keyId } from './selection';

const act = (kind: string, id: string, folder = 'Hard_Bounce', more: Partial<PreviewAction> = {}): PreviewAction => ({
  key: [kind, id, `Library/${folder}`] as ActionKey, kind, reason: kind === 'acquire' ? 'new' : null, track_id: id,
  artist: `Artist ${id}`, title: `Title ${id}`, folder, to_dir: `Library/${folder}`,
  to_not_lossless: false, src: null, cover_url: null, in: [P(folder)], ...more });
/** a playlist's target; in these tests a playlist's ref is its name */
const P = (name: string) => `playlist:${name}`;
const ids = (s: Set<string>) => [...s].map((k) => JSON.parse(k)[1]).sort();

describe('kinds and tags', () => {
  it('names every kind', () => {
    expect(kindOf(act('acquire', 'a'))).toBe('new');
    expect(kindOf(act('acquire', 'a', 'X', { reason: 'retry' }))).toBe('retry');
    expect(kindOf(act('acquire', 'a', 'X', { reason: 'redownload' }))).toBe('redownload');
    expect(kindOf(act('adopt_bought', 'a'))).toBe('bought');
    expect(kindOf(act('upgrade', 'a'))).toBe('weekly');
  });
  it('tags only what is not a plain new track', () => {
    expect(tagOf(act('acquire', 'a'))).toBeNull();
    expect(tagOf(act('acquire', 'a', 'X', { reason: 'retry' }))).toBe('not found last time');
    expect(tagOf(act('adopt_bought', 'a'))).toBe('bought file');
    expect(tagOf(act('upgrade', 'a'))).toBe('weekly check');
  });
  it('says why in words for every kind, a plain new track included (issue 35: the row tooltip)', () => {
    expect(whyOf(act('acquire', 'a'))).toBe('not downloaded yet');
    expect(whyOf(act('acquire', 'a', 'X', { reason: 'retry' }))).toBe('not found last time');
    expect(whyOf(act('acquire', 'a', 'X', { reason: 'redownload' }))).toBe('file gone');
    expect(whyOf(act('adopt_bought', 'a'))).toBe('bought file');
    expect(whyOf(act('upgrade', 'a'))).toBe('weekly check');
    // the tag is the same words, left out only for the plain new track
    for (const a of [act('acquire', 'a', 'X', { reason: 'retry' }), act('upgrade', 'a'), act('adopt_bought', 'a')])
      expect(tagOf(a)).toBe(whyOf(a));
  });
});

describe("the weekly checks' switches (issues 35, 36)", () => {
  const plan = [act('upgrade', 'a', 'X'), act('upgrade', 'b', 'Y')];
  it('are both always there, also with no rows of their kind or switched off', () => {
    expect(weeklyItems(plan, { off: [], kinds: ['weekly'] })).toEqual([
      { key: 'retry', label: 'Missing songs', count: 0, on: true },
      { key: 'weekly', label: 'Lossy files', count: 2, on: false }]);
    expect(weeklyItems([], { off: [], kinds: [] }).map((i) => i.key)).toEqual(['retry', 'weekly']);
  });
  it('count only the playlists switched on', () => {
    expect(weeklyItems(plan, { off: [P('Y')], kinds: [] })[1].count).toBe(1);
  });
  it('say "more" in the left-out note only when rows stand above it', () => {
    expect(leftOutTitle(4, 0)).toBe('4 tracks left out');
    expect(leftOutTitle(1, 0)).toBe('1 track left out');
    expect(leftOutTitle(4, 12)).toBe('4 more tracks left out');
  });
  it('point the left-out note at the switches that did it', () => {
    expect(leftOutBody({ off: [P('A')], kinds: [] })).toBe('Playlists you switched off on the left.');
    expect(leftOutBody({ off: [], kinds: ['retry'] })).toBe('Weekly checks you switched off on the right.');
    expect(leftOutBody({ off: [P('A')], kinds: ['retry'] })).toMatch(/on the left and .* on the right/);
    expect(leftOutBody({ off: ['folder:/m/Techno'], kinds: [] })).toBe('Folders you switched off on the left.');
    expect(leftOutBody({ off: [P('A'), 'folder:/m/Techno'], kinds: [] })).toBe('Playlists and folders you switched off on the left.');
  });
});

describe('the kinds at a glance (issue 36)', () => {
  const all = [act('acquire', 'a', 'A'), act('acquire', 'b', 'A', { reason: 'retry' }), act('upgrade', 'c', 'B'),
    act('adopt_bought', 'd', 'B'), act('acquire', 'e', 'B', { reason: 'redownload' })];
  it('lists the kinds the plan has, downloads first, with their counts in the playlists switched on', () => {
    const k = kindShares(all, { off: [P('B')], kinds: [] }, { [P('A')]: 'A', [P('B')]: 'B' });
    expect(k.kinds.map((x) => [x.key, x.n])).toEqual([['new', 1], ['redownload', 0], ['retry', 1], ['weekly', 0], ['bought', 0]]);
    expect(k.total).toBe(2);
    expect([k.playlists, k.folders]).toEqual([1, 0]);
  });
  it('keeps a weekly check switched off in the list, marked off, out of the total', () => {
    const k = kindShares(all, { off: [], kinds: ['weekly'] });
    expect(k.kinds.find((x) => x.key === 'weekly')).toMatchObject({ n: 1, off: true });
    expect(k.total).toBe(4);
  });
  it('words the line under the count', () => {
    expect(stripLine(12, 3, 0, false)).toBe('to sync in 3 playlists');
    expect(stripLine(12, 1, 2, false)).toBe('to sync in 1 playlist and 2 folders');
    expect(stripLine(2, 0, 1, false)).toBe('to sync in 1 folder');
    expect(stripLine(0, 0, 0, false)).toBe('everything switched off');
    expect(stripLine(0, 0, 0, true)).toBe('every playlist and folder switched off');
  });
  it('counts a playlist without the weekly checks switched off (the old panel counted them)', () => {
    expect(planCounts(all, { off: [], kinds: ['weekly', 'retry'] })).toEqual({ [P('A')]: 1, [P('B')]: 2 });
  });
  it('says what a playlist switch does', () => {
    expect(switchTip('Techno', { enabled: true, on: true, n: 3, running: false })).toBe('Techno · 3 tracks to sync');
    expect(switchTip('Techno', { enabled: true, on: true, n: 0, running: false })).toBe('Techno · nothing to sync');
    expect(switchTip('Techno', { enabled: true, on: false, n: 3, running: false })).toBe('Techno · left out of the sync');
    expect(switchTip('Techno', { enabled: false, on: true, n: null, running: false })).toMatch(/Playlists page/);
    expect(switchTip('Techno', { enabled: true, on: true, n: null, running: true })).toMatch(/once the sync ends/);
  });
  it('words an empty day bar', () => {
    expect(dayBarEmpty(0, 0)).toBe('Everything switched off');
    expect(dayBarEmpty(4, 0)).toBe('Nothing ticked');
    expect(dayBarEmpty(4, 2)).toBe('No downloads');
  });
});

describe('scope and sections', () => {
  const all = [act('acquire', 'a', 'Ohne'), act('acquire', 'b', 'Voller'), act('adopt_bought', 'c', 'Voller'),
    act('upgrade', 'd', 'Voller'), act('acquire', 'e', 'Elsewhere')];
  it('toggles a folder or kind in and out', () => {
    const s = toggleScope(toggleScope(FULL_SCOPE, 'off', P('Ohne')), 'kinds', 'weekly');
    expect(s).toEqual({ off: [P('Ohne')], kinds: ['weekly'] });
    expect(toggleScope(s, 'off', P('Ohne')).off).toEqual([]);
  });
  it('reads a stored scope safely', () => {
    expect(readScope(null)).toEqual(FULL_SCOPE);
    // only the weekly checks switch as kinds now (issue 36): an older left-out kind is dropped, never kept unseen
    expect(readScope({ off: ['playlist:x', 'folder:/m/T', 'junk', 3], kinds: ['new', 'bogus', 'retry'] }))
      .toEqual({ off: ['playlist:x', 'folder:/m/T'], kinds: ['retry'] });
    // before issue 37 the playlists switched off were stored by name: kept until the sidebar names their targets
    expect(readScope({ folders: ['A', 3], kinds: [] })).toEqual({ off: [], kinds: [], legacy: ['A'] });
  });
  it('sections follow playlists.txt and keep the given order inside', () => {
    expect(sections(all, ['Voller', 'Ohne']).map((s) => [s.folder, s.rows.map((r) => r.track_id)]))
      .toEqual([['Voller', ['b', 'c', 'd']], ['Ohne', ['a']], ['Elsewhere', ['e']]]);
  });
});

describe('how many', () => {
  it('offers the round numbers below the total, what fits today and all', () => {
    expect(presets(195, 10).map((p) => p.label)).toEqual(['5', '10 · fits today', '25', '50', 'All 195']);
    expect(presets(30, 0).map((p) => p.label)).toEqual(['5', '10', '25', 'All 30']);
    expect(presets(8, 60).map((p) => p.label)).toEqual(['5', 'All 8']);
    expect(presets(3, 2).map((p) => p.label)).toEqual(['2 · fits today', 'All 3']);
    expect(presets(0, 10)).toEqual([]);
  });
  it('starts with what fits today, or all when everything fits', () => {
    expect(defaultHowMany(195, 10)).toBe('fits');
    expect(defaultHowMany(8, 60)).toBe('all');
    expect(defaultHowMany(8, 0)).toBe('all');
    expect(presetN('fits', 195, 10)).toBe(10);
    expect(presetN(25, 8, 60)).toBe(8);
  });
  it('lights the chip that gives the same number', () => {
    const list = presets(8, 60);
    expect(shownPreset(25, list, 8, 60)).toBe('all');
    expect(shownPreset('fits', list, 8, 60)).toBe('all');
    expect(shownPreset(5, list, 8, 60)).toBe(5);
    expect(shownPreset('custom', list, 8, 60)).toBe('custom');
    expect(shownPreset(10, presets(195, 10), 195, 10)).toBe('fits');
  });
  it('reads a stored choice safely', () => {
    expect(readHowMany('fits')).toBe('fits');
    expect(readHowMany(25)).toBe(25);
    expect(readHowMany(-1)).toBeNull();
    expect(readHowMany('x')).toBeNull();
  });
  it('a preset ticks all bought files in scope and the first n downloads in run order', () => {
    const ordered = [act('adopt_bought', 'm', 'Voller'), act('acquire', 'a', 'Voller'), act('acquire', 'b', 'Ohne'),
      act('acquire', 'c', 'Voller'), act('upgrade', 'u', 'Voller')];
    expect(ids(presetTicks(ordered, FULL_SCOPE, 2))).toEqual(['a', 'b', 'm']);
    expect(ids(presetTicks(ordered, { off: [P('Ohne')], kinds: [] }, 2))).toEqual(['a', 'c', 'm']);
    expect(ids(presetTicks(ordered, { off: [], kinds: ['bought'] }, 9))).toEqual(['a', 'b', 'c', 'u']);
  });
});

describe('next sync and the summary', () => {
  const ordered = [act('adopt_bought', 'm'), act('acquire', 'a'), act('acquire', 'b'), act('acquire', 'c'), act('upgrade', 'u')];
  const all = new Set(ordered.map((a) => keyId(a.key)));
  it('ticked downloads after the first L in run order wait for the next sync', () => {
    expect(ids(nextSyncSet(ordered, all, FULL_SCOPE, 2))).toEqual(['c', 'u']);
    expect(ids(nextSyncSet(ordered, all, FULL_SCOPE, 0))).toEqual(['a', 'b', 'c', 'u']);
    expect(ids(nextSyncSet(ordered, all, FULL_SCOPE, 10))).toEqual([]);
    const noA = new Set([...all].filter((k) => JSON.parse(k)[1] !== 'a'));
    expect(ids(nextSyncSet(ordered, noA, FULL_SCOPE, 2))).toEqual(['u']);
  });
  // the engine's table (views.minutes_by_downloads): the page never repeats the formula, it looks the count up
  const table = [0, 5, 5, 5, 5, 5, 5, 10, 10, 10, 10];
  it('the minutes for a count of downloads are looked up in the engine\'s table', () => {
    expect(minutesFor(table, 0)).toBe(0);
    expect(minutesFor(table, 4)).toBe(5);
    expect(minutesFor(table, 10)).toBe(10);
    expect(minutesFor(table, 99)).toBe(10);   // never more than the table's last entry (what fits today)
    expect(minutesFor([], 3)).toBe(0);        // no preview yet
  });
  it('only the downloads that fit today take time; the rest follow over days', () => {
    expect(runTotals(ordered, 195, 10, 60, table)).toEqual({ tracks: 5, downloads: 4, uses: 4, minutes: 5, waiting: 0,
      after: 191, days: 1 + 4 });  // 6 still fit today, so today counts
    expect(runTotals(ordered, 4, 2, 60, table)).toMatchObject({ uses: 2, waiting: 2, after: 2, days: 1, minutes: 5 });
    expect(runTotals([], 0, 10, 60, table)).toMatchObject({ tracks: 0, minutes: 0, after: 0, days: 0 });
    // the issue's numbers: 108 to go, today's limit used up, 66 a day → 2 more days, as the dashboard says
    expect(runTotals(ordered, 108, 0, 66, [0])).toMatchObject({ uses: 0, minutes: 0, after: 108, days: 2 });
    // 4 ticked of 30 left today: the other 26 can still load today, so today counts (views.days_to_load)
    expect(runTotals(ordered, 108, 30, 66, table)).toMatchObject({ uses: 4, after: 104, days: 1 + 2 });
  });
  it('Later counts only the downloads in scope, so Today + Later is "All N" (issue 7)', () => {
    const plan = [act('acquire', 'a'), act('acquire', 'b'), act('acquire', 'c'), act('adopt_bought', 'm'),
      act('acquire', 'x', 'Off_List'), act('acquire', 'y', 'Off_List'), act('upgrade', 'w')];
    const scope: Scope = { off: [P('Off_List')], kinds: ['weekly'] };
    expect(downloadsInScope(plan, scope)).toBe(3);   // a, b, c: not Off_List's two, not the weekly check
    expect(downloadsInScope(plan, FULL_SCOPE)).toBe(6);
    const chosen = plan.filter((a) => inScope(a, scope));
    const t = runTotals(chosen, downloadsInScope(plan, scope), 2, 60, table);
    expect(t).toMatchObject({ uses: 2, after: 1, days: 1 });
    expect(t.uses + t.after).toBe(presets(downloadsInScope(plan, scope), 2).at(-1)!.n);   // "All 3"
    // nothing in scope: no Later, the switched-off tracks are only the plan's "left out" note
    expect(runTotals([], downloadsInScope(plan, { off: [P('Hard_Bounce'), P('Off_List')], kinds: [] }), 2, 60, table))
      .toMatchObject({ after: 0, days: 0 });
  });
});

describe('search and run order', () => {
  it('ignores case and accents and finds "Artist – Title"', () => {
    const a = act('acquire', 'x', 'X', { artist: 'Kölsch', title: 'Grey' });
    expect(matches(a, 'kolsch')).toBe(true);
    expect(matches(a, 'KÖLSCH – gr')).toBe(true);
    expect(matches(a, 'grey kol')).toBe(false);
    expect(matches(a, '  ')).toBe(true);
    expect(foldText('É')).toBe('e');
  });
  it('sorts by the backend run index', () => {
    const p = { groups: [{ key: 'acquire:new', label: '', actions: [act('acquire', 'a', 'X', { run: 2 }),
      act('acquire', 'b', 'X', { run: 1 })] }, { key: 'adopt_bought', label: '', actions: [act('adopt_bought', 'm', 'X', { run: 0 })] }],
    } as unknown as SyncPreview;
    expect(inRunOrder(p).map((a) => a.track_id)).toEqual(['m', 'b', 'a']);
  });
});

type DropFirst<T extends unknown[]> = T extends [unknown, ...infer R] ? R : never;
// The engine's tables (views.sync_estimate: `uses_by_downloads` for every count), built here from the accounts'
// `left`: Qobuz first takes up to what is left, a backup behind Qobuz gets none, without Qobuz the accounts fill up in
// order. tests/test_hub_views.py pins the engine's own numbers against views.split.
const withTables = (accounts: EstimateAccount[], most = 200): SyncAccount[] => {
  const qobuz = accounts.some((a) => a.service === 'qobuz');
  const at = (n: number) => { let rest = n; return accounts.map((a) => {
    const uses = qobuz && a.service !== 'qobuz' ? null : Math.min(rest, Math.max(a.left, 0));
    rest -= uses ?? 0; return uses; }); };
  const tables = Array.from({ length: most + 1 }, (_, n) => at(n));
  return accounts.map((a, i) => ({ ...a, uses_by_downloads: tables[0][i] === null ? null : tables.map((t) => t[i] as number) }));
};
const acc = (over: Partial<EstimateAccount>): EstimateAccount => ({ service: 'qobuz', name: 'Qobuz', uses: 10,
  left: 10, limit: 60, about: false, ...over });

// a service row's words and bar (`value` null: a backup behind Qobuz, drawn without a bar)
const lines = (accounts: EstimateAccount[], ...rest: DropFirst<Parameters<typeof serviceRows>>) =>
  serviceRows(withTables(accounts), ...rest).map(({ service, text, value }) => ({ service, text, value }));
describe('service rows', () => {
  it('Qobuz first, the accounts catch what Qobuz lacks', () => {
    expect(lines([acc({}), acc({ service: 'youtube', name: 'YouTube Premium', uses: null, left: 30, limit: 30,
      about: true })], 12)).toEqual([
      { service: 'qobuz', text: 'Qobuz today: uses 10 of 10 left', value: 1 },
      { service: 'youtube', text: "YouTube Premium: 30 left today · for tracks Qobuz doesn't have", value: null }]);
  });
  it('without Qobuz the accounts fill up, as an estimate', () => {
    expect(lines([acc({ service: 'youtube', name: 'YouTube Premium', uses: 4, left: 30, limit: 30,
      about: true })], 4)).toEqual([{ service: 'youtube', text: 'YouTube Premium: uses about 4 of 30 left',
      value: 4 / 30 }]);
  });
  it("counts the DJ's ticked downloads, not the whole plan", () => {
    // 80 left, 150 planned (the server's estimate says 80), the DJ ticks 20
    expect(lines([acc({ uses: 80, left: 80 })], 20)).toEqual([
      { service: 'qobuz', text: 'Qobuz today: uses 20 of 80 left', value: 0.25 }]);
    expect(lines([acc({ service: 'youtube', name: 'YouTube Premium', uses: 30, left: 30, limit: 30, about: true }),
      acc({ service: 'soundcloud', name: 'SoundCloud Go+', uses: 20, left: 20, limit: 20, about: true })], 35)).toEqual([
      { service: 'youtube', text: 'YouTube Premium: uses about 30 of 30 left', value: 1 },
      { service: 'soundcloud', text: 'SoundCloud Go+: uses about 5 of 20 left', value: 5 / 20 }]);
  });
  it('drops a used-up service while the limit-reached warning shows', () => {
    expect(lines([acc({ uses: 0, left: 0 })], 5, { limitReached: true })).toEqual([]);
    expect(lines([acc({ uses: 0, left: 0 }), acc({ service: 'youtube', name: 'YouTube Premium', uses: null,
      left: 30, limit: 30, about: true })], 5, { limitReached: true })).toEqual([
      { service: 'youtube', text: "YouTube Premium: 30 left today · for tracks Qobuz doesn't have", value: null }]);
    expect(lines([acc({ uses: 0, left: 0 })], 5)).toHaveLength(1);  // the dashboard still says it
  });
  it('nothing to say without downloads or accounts', () => {
    expect(lines([], 5)).toEqual([]);
    expect(lines([acc({ uses: 0 })], 0)).toEqual([]);
  });
});
describe('the automatic Spotify read', () => {
  const sp = (more: Partial<SyncPreview['read_status']> = {}): SyncPreview['read_status'] => ({ read_at: null, minutes_ago: null,
    problem: null, message: '', stale: false, reading: false, offline: false, auto_read: false, problem_service: null, services: [], ...more });
  const pv = (read_status = sp(), empty: SyncPreview['empty'] = null) => ({ read_status, empty });
  const idle = { refreshRunning: false, syncRunning: false };
  it('reads once per session: only while the hub has not read by itself yet', () => {
    expect(shouldAutoRead(pv(), idle)).toBe(true);
    // a second open of the Sync page, or the page after a window reload: the hub remembers its read
    expect(shouldAutoRead(pv(sp({ auto_read: true })), idle)).toBe(false);
  });
  it('a stopped or failed first read is not redone by itself, however old the last read is', () => {
    expect(shouldAutoRead(pv(sp({ auto_read: true, read_at: null })), idle)).toBe(false);
    expect(shouldAutoRead(pv(sp({ auto_read: true, problem: 'offline', offline: true, minutes_ago: 600,
      read_at: '2026-10-19T08:00:00' })), idle)).toBe(false);
  });
  it('never while reading, during a sync, or before setup', () => {
    expect(shouldAutoRead(pv(sp({ reading: true })), idle)).toBe(false);
    expect(shouldAutoRead(pv(), { refreshRunning: true, syncRunning: false })).toBe(false);
    expect(shouldAutoRead(pv(), { refreshRunning: false, syncRunning: true })).toBe(false);
    expect(shouldAutoRead(pv(sp({ problem: 'not_set_up' })), idle)).toBe(false);
    expect(shouldAutoRead(pv(sp(), 'not_set_up'), idle)).toBe(false);
  });
});

describe('folder names', () => {
  it('never leaves a playlist row blank', () => {
    expect(folderLabel('')).toBe('Your own music');
    expect(folderLabel('  ')).toBe('Your own music');
    expect(folderLabel('Techno')).toBe('Techno');
  });
});

describe('panel models', () => {
  const t = { tracks: 69, downloads: 66, uses: 66, minutes: 75, waiting: 0, after: 36, days: 1 };
  it('feeds the day bar', () => expect(dayBarInput(t, 66)).toEqual({ today: 66, later: 36, limited: true, laterDays: 1 }));
  it('has no later without a limit', () => expect(dayBarInput({ ...t, after: 0 }, null)).toMatchObject({ limited: false, later: 0 }));
  it('labels Start by tracks', () => expect(startLabel(69, 66, 66)).toBe('Start sync · 69 tracks'));
  it('labels Start by what still runs when no download fits today', () => expect(startLabel(80, 77, 0)).toBe('Start sync · 3 tracks'));
  it('says just Start sync when nothing is ticked', () => expect(startLabel(0, 0, 0)).toBe('Start sync'));
  it('labels one track in the singular', () => expect(startLabel(1, 1, 1)).toBe('Start sync · 1 track'));
  it('counts only what runs today, not the ticked downloads that wait (9B I1)', () =>
    expect(startLabel(196, 195, 10)).toBe('Start sync · 11 tracks'));
  it('gives no count when nothing runs today', () => expect(startLabel(5, 5, 0)).toBe('Start sync'));
  it("counts a run's tracks as what runs today", () => {
    expect(runCount(196, 195, 10)).toBe(11);
    expect(runCount(69, 66, 66)).toBe(69);
    expect(runCount(80, 77, 0)).toBe(3);     // limit used up: only the bought files run
    expect(runCount(5, 5, 0)).toBe(0);
  });
  it('runs nothing today when only waiting downloads are ticked', () => {
    expect(runsNothingToday(5, 5, 0)).toBe(true);       // limit used up, only downloads ticked
    expect(runsNothingToday(0, 0, 0)).toBe(false);      // nothing ticked is its own reason
    expect(runsNothingToday(80, 77, 0)).toBe(false);    // the bought files still run
    expect(runsNothingToday(196, 195, 10)).toBe(false); // 10 downloads fit today
    expect(runsNothingToday(5, 5, 5)).toBe(false);      // no limit: every download runs
  });
});

describe('section head and why column', () => {
  it('counts the ticks', () => expect(sectionSummary(3, 5, 0)).toBe('3 of 5 ticked'));
  it('says once how many ticked rows wait', () =>
    expect(sectionSummary(118, 118, 118)).toBe('118 of 118 ticked · 118 next sync'));
  it('gives the column to a section with a tag', () =>
    expect(whyColumn([act('acquire', '1'), act('upgrade', '2')], false)).toBe(true));
  it('leaves it out for plain new tracks when nothing can wait', () =>
    expect(whyColumn([act('acquire', '1'), act('acquire', '2')], false)).toBe(false));
  it('gives it to new tracks that may wait for the next sync', () =>
    expect(whyColumn([act('acquire', '1')], true)).toBe(true));
});

describe('next sync in a section (N1)', () => {
  it('says it once when every ticked download waits', () => expect(waitsWhole(3, 3)).toBe(true));
  it('counts a ticked bought file as ticked, never as a download that waits', () => {
    const rows = [act('acquire', '1'), act('acquire', '2'), act('adopt_bought', '3')];
    const ids = rows.map((a) => keyId(a.key));
    const c = sectionCounts(rows, new Set(ids), new Set(ids.slice(0, 2)));
    expect(c).toEqual({ total: 3, ticked: 3, waiting: 2, downloads: 2 });
    expect(waitsWhole(c.waiting, c.downloads)).toBe(true);   // every ticked download waits: the head says it once
  });
  it('says it per row when only some ticked downloads wait', () => expect(waitsWhole(2, 3)).toBe(false));
  it('says nothing without waiting rows', () => expect(waitsWhole(0, 0)).toBe(false));
  it('may wait when the plan holds more downloads than are left', () => expect(mayWaitToday(195, 10)).toBe(true));
  it('never waits row by row with nothing left today (all wait, the head says it)', () => expect(mayWaitToday(195, 0)).toBe(false));
  it('never waits without a daily limit', () => expect(mayWaitToday(195, Number.POSITIVE_INFINITY)).toBe(false));
});

describe('run panel (9B)', () => {
  it('gives the time card an estimate (~, as the service rows) and a unit', () => {
    expect(runTime(75, 69)).toEqual({ value: '~75', unit: 'min' });   // "~1 h 15 min" was cut off in the card at 1280
    expect(runTime(10, 17)).toEqual({ value: '~10', unit: 'min' });
    expect(runTime(115, 99)).toEqual({ value: '~115', unit: 'min' });
    expect(runTime(120, 99)).toEqual({ value: '~2', unit: 'h' });
    expect(runTime(140, 99)).toEqual({ value: '~2.5', unit: 'h' });    // to the half hour
  });
  it('says a minute or two for bought files only, and 0 min when nothing runs', () => {
    expect(runTime(0, 3)).toEqual({ value: '1–2', unit: 'min' });
    expect(runTime(0, 0)).toEqual({ value: '0', unit: 'min' });
  });
  it('knows the kinds it has an icon for', () => {
    expect(isKindKey('bought')).toBe(true);
    expect(isKindKey('move')).toBe(false);   // the sync never moves a file
    expect(isKindKey('something-new')).toBe(false);
  });
  it('turns several playlists off and on at once (All · None)', () => {
    const s = { off: [P('A')], kinds: [] };
    expect(scopeSet(s, 'off', [P('A'), P('B'), P('C')], false)).toEqual({ off: [P('A'), P('B'), P('C')], kinds: [] });
    expect(scopeSet({ off: [P('A'), P('B'), P('C')], kinds: [] }, 'off', [P('A'), P('C')], true)).toEqual({ off: [P('B')], kinds: [] });
    expect(scopeSet({ off: [], kinds: [] }, 'kinds', ['bought'], false)).toEqual({ off: [], kinds: ['bought'] });
    expect(s).toEqual({ off: [P('A')], kinds: [] });   // the input is not changed
  });
  it('marks the amount that fits today with ✦', () => {
    expect(howManyOptions(presets(195, 64)).map((o) => [o.key, o.label])).toEqual([
      ['5', '5'], ['10', '10'], ['25', '25'], ['50', '50'], ['fits', '64 ✦'], ['all', 'All 195']]);
  });
  const acc = (o: object) => ({ service: 'qobuz', name: 'Qobuz', uses: 10, left: 10, limit: 60, about: false, ...o }) as never;
  it('gives each service a short "U of L" for its row', () => {
    expect(serviceRows(withTables([acc({}), acc({ service: 'youtube', name: 'YouTube Premium', uses: null, left: 30, limit: 30,
      about: true })]), 12).map((r) => [r.name, r.short, r.value])).toEqual([
      ['Qobuz', '10 of 10', 1], ['YouTube', '30 left', null]]);
    expect(serviceRows(withTables([acc({ service: 'youtube', name: 'YouTube Premium', uses: 4, left: 30, limit: 30, about: true })]), 4)
      .map((r) => [r.short, r.text])).toEqual([['~4 of 30', 'YouTube Premium: uses about 4 of 30 left']]);
  });
});

describe('service rows look the count up in the engine tables', () => {
  const sa = (o: object) => ({ service: 'qobuz', name: 'Qobuz', uses: 3, left: 3, limit: 60, about: false,
    uses_by_downloads: [0, 1, 2, 3], ...o }) as SyncAccount;
  it('reads the entry for the ticked count and takes the last one for a larger count', () => {
    expect(serviceRows([sa({})], 2).map((r) => r.short)).toEqual(['2 of 3']);
    expect(serviceRows([sa({})], 50).map((r) => r.short)).toEqual(['3 of 3']);
    expect(serviceRows([sa({}), sa({ service: 'youtube', name: 'YouTube Premium', uses: null, uses_by_downloads: null,
      about: true })], 2).map((r) => r.short)).toEqual(['2 of 3', '3 left']);
  });
});

describe('service rows name the service, the tooltip names the plan (Task 9C M1)', () => {
  const acc = (service: EstimateAccount['service'], name: string, left: number): EstimateAccount =>
    ({ service, name, uses: null, left, limit: left, about: false });
  it('uses the short service name in the row and keeps the full one in the tooltip', () => {
    const rows = serviceRows(withTables([acc('qobuz', 'Qobuz', 10), acc('youtube', 'YouTube Premium', 30),
      acc('soundcloud', 'SoundCloud Go+', 48)]), 20);
    expect(rows.map((r) => r.name)).toEqual(['Qobuz', 'YouTube', 'SoundCloud']);
    expect(rows[1].text).toContain('YouTube Premium');
    expect(rows[2].text).toContain('SoundCloud Go+');
  });
});

describe('readBlockLine: what a missing login affects on Sync\'s card', () => {
  const row = (folder: string, service: PlaylistService, enabled = true) => ({ folder, service, enabled });
  it('names the folder of the one switched-on Qobuz line and says the rest still syncs', () => {
    expect(readBlockLine('not_set_up', 'qobuz', [row('Peak', 'spotify'), row('Qobuz_Picks', 'qobuz')]))
      .toBe("Qobuz_Picks isn't read until Qobuz is connected. Your other playlists sync as usual.");
  });
  it('names SoundCloud or YouTube Music the same way', () => {
    expect(readBlockLine('login_expired', 'soundcloud', [row('Sets', 'soundcloud'), row('Peak', 'spotify')]))
      .toBe('Sets isn\'t read until you connect SoundCloud again. Your other playlists sync as usual.');
    expect(readBlockLine('not_set_up', 'youtube_music', null))
      .toBe("Your YouTube Music playlists aren't read until YouTube Music is connected.");
  });
  it('lists two or three folders, then counts the rest; ignores switched-off lines', () => {
    const rows = ['A', 'B', 'C', 'D', 'E'].map((f) => row(f, 'qobuz'));
    expect(readBlockLine('not_set_up', 'qobuz', rows.slice(0, 2)))
      .toBe("A and B aren't read until Qobuz is connected.");
    expect(readBlockLine('not_set_up', 'qobuz', rows)).toBe("A, B, C and 2 more aren't read until Qobuz is connected.");
    expect(readBlockLine('not_set_up', 'qobuz', [row('A', 'qobuz'), row('B', 'qobuz', false), row('X', 'spotify', false)]))
      .toBe("A isn't read until Qobuz is connected.");
  });
  it('speaks of the service\'s playlists while the lines are not known, and promises nothing about the others', () => {
    expect(readBlockLine('not_set_up', 'qobuz', null)).toBe("Your Qobuz playlists aren't read until Qobuz is connected.");
  });
  it('words an expired login as connecting again, for either service', () => {
    expect(readBlockLine('login_expired', 'spotify', [row('Peak', 'spotify'), row('Q', 'qobuz')]))
      .toBe("Peak isn't read until you connect Spotify again. Your other playlists sync as usual.");
  });
});

describe('playlists and folders in and out of the sync (issue 37)', () => {
  const W = 'folder:/Volumes/Ex/Techno';
  const C = 'folder:/Volumes/Ex/Techno/2019';
  const L = 'folder:Library/Old Stuff';
  const off = (...t: string[]): Scope => ({ off: t, kinds: [] });
  // a song in two playlists, one in a playlist and a folder's crate, an own song in a crate, one in a Library folder
  const two = act('upgrade', 'two', 'A', { in: [P('A'), P('B')] });
  const mixed = act('acquire', 'mixed', 'A', { reason: 'retry', in: [P('A'), W, C] });
  const own = act('upgrade', 'own', 'Techno › 2019', { in: [W, C] });
  const lib = act('upgrade', 'lib', 'Old Stuff', { in: [L] });
  const loose = act('upgrade', 'loose', 'Your own music', { in: [] });
  const names = { [P('A')]: 'A', [P('B')]: 'B', [W]: 'Techno', [C]: 'Techno › 2019', [L]: 'Old Stuff' };

  it('a song is in while any playlist or folder it belongs to is on, out only when every one is off', () => {
    expect(memberOn(two, off(P('A')))).toBe(true);    // switching A on or off never takes B's track away
    expect(memberOn(two, off(P('B')))).toBe(true);
    expect(memberOn(two, off(P('A'), P('B')))).toBe(false);
    // a playlist and a folder: the folder switched off leaves it in through the playlist, and the other way round
    expect(memberOn(mixed, off(W))).toBe(true);
    expect(memberOn(mixed, off(P('A')))).toBe(true);
    expect(memberOn(mixed, off(P('A'), W))).toBe(false);
    expect(memberOn(lib, off(L))).toBe(false);
    expect(memberOn(lib, off(P('A'), W))).toBe(true);
  });
  it('a folder switched off takes its crates along; a crate switched off in a folder that is on is off', () => {
    expect(memberOn(own, off(W))).toBe(false);
    expect(memberOn(own, off(C))).toBe(false);
    expect(memberOn(own, FULL_SCOPE)).toBe(true);
    expect(memberOn(mixed, off(P('A'), C))).toBe(false);
  });
  it('leaves out every kind of row whose song is out, a kind added later too', () => {
    const odd = act('relocate', 'odd', 'Old Stuff', { in: [L] });
    expect(inScope(odd, off(L))).toBe(false);
    expect(inScope(odd, FULL_SCOPE)).toBe(true);
    // a row in no collection has no switch: nothing leaves it out
    expect(inScope(loose, off(P('A'), W, L))).toBe(true);
  });
  it('Start sends only ticked rows in scope', () => {
    const plan = [two, mixed, own, lib];
    const ticked = new Set(plan.map((a) => keyId(a.key)));
    expect(chosenOf(plan, ticked, off(W, L)).map((a) => a.track_id)).toEqual(['two', 'mixed']);
    expect(chosenOf(plan, new Set([keyId(own.key)]), off(C)).map((a) => a.track_id)).toEqual([]);
    expect(everyOff(plan, off(P('A'), P('B'), W, L))).toBe(true);
    expect(everyOff(plan, off(P('A'), W, L))).toBe(false);
  });
  it('a row stands under its own section while that is on, else under the first collection on', () => {
    expect(sectionOf(two, FULL_SCOPE, names)).toBe('A');
    expect(sectionOf(two, off(P('A')), names)).toBe('B');
    expect(sectionOf(mixed, off(P('A')), names)).toBe('Techno › 2019');
    expect(sectionOf(own, FULL_SCOPE, names)).toBe('Techno › 2019');
    expect(sectionOf(loose, FULL_SCOPE, names)).toBe('Your own music');
    const s = kindShares([two, mixed, own, lib], off(P('A')), names);
    expect([s.total, s.playlists, s.folders]).toEqual([4, 1, 2]);   // B; Techno › 2019 and Old Stuff
    expect(sections([two, own, lib], ['A', 'B'], (a) => sectionOf(a, off(P('A')), names)).map((x) => x.folder))
      .toEqual(['B', 'Techno › 2019', 'Old Stuff']);
  });
  it('counts per collection for the column\'s tooltips', () => {
    expect(planCounts([two, mixed, own, lib], FULL_SCOPE)).toEqual({ [P('A')]: 2, [P('B')]: 1, [W]: 2, [C]: 2, [L]: 1 });
  });
  it('a folder\'s switch goes by the folders around it; a hidden crate goes with its folder', () => {
    const around = [{ target: W, name: 'Techno' }];
    expect(folderSwitch(C, around, false, FULL_SCOPE)).toEqual({ on: true, can: true, under: null, follows: null });
    expect(folderSwitch(C, around, false, off(C))).toEqual({ on: false, can: true, under: null, follows: null });
    // its folder off: shown off, can't turn on until the folder is on; its own setting is kept for then
    expect(folderSwitch(C, around, false, off(W, C))).toEqual({ on: false, can: false, under: 'Techno', follows: null });
    expect(folderSwitch(C, around, false, off(W))).toMatchObject({ on: false, can: false, under: 'Techno' });
    expect(folderSwitch(C, around, true, off(C))).toEqual({ on: true, can: false, under: null, follows: 'Techno' });
    expect(folderSwitch(W, [], false, off(W))).toEqual({ on: false, can: true, under: null, follows: null });
  });
  it('says what a folder switch does', () => {
    expect(switchTip('2019', { enabled: true, on: false, n: 3, running: false, under: 'Techno' }))
      .toBe('2019 · left out with Techno · switch Techno on first');
    expect(switchTip('2019', { enabled: true, on: true, n: 3, running: false, follows: 'Techno' }))
      .toBe('2019 · not in the sidebar, so it goes with Techno');
  });
  it('turns the playlists an older version stored by name into targets, dropping names no playlist has', () => {
    const s = readScope({ folders: ['A', 'Gone'], kinds: ['weekly'] });
    expect(resolveLegacy(s, [{ name: 'A', ref: 'ra' }, { name: 'A', ref: 'ra2' }, { name: 'B', ref: 'rb' }]))
      .toEqual({ off: ['playlist:ra', 'playlist:ra2'], kinds: ['weekly'] });
    expect(resolveLegacy(FULL_SCOPE, [])).toBe(FULL_SCOPE);
  });
});
