import { describe, expect, it } from 'vitest';
import type { AutoUpgradeResult, Result, RunDetail, RunSummary } from '$lib/bridge/types';
import {
  endModel, endTitle, groupByFolder, keepDetail, lastSyncStats, lastSyncView, needsDetail, otherDetail, upgradedDetail, type LastSyncDetail,
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
    auto_upgrade: null, sections, needs_you: results.filter((x) => ['missing', 'errors'].includes(x.section)),
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

describe('end screen: the sync\'s Auto-upgrade', () => {
  const res = (track: string, state: AutoUpgradeResult['state'], reason: string | null, how: AutoUpgradeResult['how'] = 'in_place'):
    AutoUpgradeResult => ({ track, name: `A – ${track}`, state, reason, message: null, how });
  const block = (line: string | null, results: AutoUpgradeResult[] = BLOCK) => ({ batch: 3, backup: null, done: 2, waiting: 2, refused: 1,
    failed: 0, stopped: false, dry_run: false, results, line });
  // two upgraded, one waits for rekordbox, one was not reached (tried again next sync), one refused (timing)
  const BLOCK = [res('g1', 'done', null, 'new_aiff'), res('g2', 'done', null, 'in_place'), res('w1', 'waiting', 'rekordbox_open', null),
    res('w2', 'waiting', 'changed', null), res('f1', 'refused', 'timing', null)];
  const PHASE = [
    r('upgraded', 'Bouncy', 'g1', { status: 'lossless', note: 'new file A - g1.aiff, lined up with rekordbox; the old one moved to Superseded/' }),
    r('upgraded', 'Bouncy', 'g2', { status: 'lossless', note: 'Replaced in place. Kept your own title / artist in rekordbox.' }),
    r('upgrade_waits', 'Bouncy', 'w1', { note: 'Waits for rekordbox to be closed: it is upgraded at your next sync, or press Upgrade all.' }),
    r('upgrade_waits', 'Bouncy', 'w2', { note: 'Your rekordbox track changed while Discjockey was working on it, so nothing was changed. Try again.' }),
    r('upgrade_waits', 'Bouncy', 'f1', { note: "Discjockey couldn't line the new file up with your rekordbox track exactly, so nothing was changed. Analyse the track again in rekordbox and try again." }),
  ];
  const LINE = "Upgraded 2 tracks; your cues stayed. 1 waits for rekordbox to be closed. 1 waits for your next sync. 1 couldn't go in; To-do says why.";
  it('splits the phase by each track\'s state in the block: upgraded, still waiting, couldn\'t go in', () => {
    const m = endModel(run([...RESULTS, ...PHASE], { auto_upgrade: block(LINE) }), null, NOW);
    expect(m.upgraded.map((x) => x.r.title)).toEqual(['g1', 'g2']);
    expect(m.waiting.map((x) => x.r.title)).toEqual(['w1', 'w2']);
    expect(m.refused.map((x) => x.r.title)).toEqual(['f1']);
    expect(m.auto.map((p) => `${p.label} ${p.rows.length}`)).toEqual(['Upgraded 2', 'Still waiting 2', "Couldn't go in 1"]);
    expect(m.notes.map((n) => n.test)).toEqual(['sync-auto-upgrade', 'sync-checked']);
    expect(m.notes[0].text).toBe(LINE);
  });
  it('the counts match the block\'s: waiting + refused are the upgrade_waits rows', () => {
    const m = endModel(run([...RESULTS, ...PHASE], { auto_upgrade: block(LINE) }), null, NOW);
    const b = run([...RESULTS, ...PHASE], { auto_upgrade: block(LINE) }).auto_upgrade!;
    expect(m.upgraded.length).toBe(BLOCK.filter((x) => x.state === 'done').length);
    expect(m.waiting.length).toBe(BLOCK.filter((x) => x.state === 'waiting').length);
    expect(m.refused.length).toBe(BLOCK.filter((x) => x.state === 'refused').length);
    expect(b.results).toHaveLength(m.upgraded.length + m.waiting.length + m.refused.length);
  });
  it('a waiting row says why in a few words; the engine\'s sentence is its tooltip', () => {
    const m = endModel(run([...RESULTS, ...PHASE], { auto_upgrade: block(LINE) }), null, NOW);
    expect(m.waiting.map((x) => x.sub)).toEqual(['Waits for rekordbox to be closed', 'Waits for your next sync']);
    expect(m.waiting[1].tip).toMatch(/^Your rekordbox track changed/);
    // not reached and busy are tried again by the next sync as well
    const more = [res('w1', 'waiting', 'not_reached', null), res('w2', 'waiting', 'busy', null)];
    const m2 = endModel(run(PHASE.slice(2, 4), { auto_upgrade: block(null, more) }), null, NOW);
    expect(m2.waiting.map((x) => x.sub)).toEqual(['Waits for your next sync', 'Waits for your next sync']);
  });
  it('a refused row carries To-do\'s short reason as its sub and the full sentence as its tooltip', () => {
    const reasons = ['timing', 'not_analysed', 'cloud', 'space', 'needs_choice'];
    const results = reasons.map((x, k) => res(`f${k}`, 'refused', x, null));
    const rows = reasons.map((_, k) => r('upgrade_waits', 'Bouncy', `f${k}`, { note: `Sentence ${k}.` }));
    const m = endModel(run(rows, { auto_upgrade: block(null, results) }), null, NOW);
    expect(m.refused.map((x) => x.sub)).toEqual(["Couldn't line it up", 'Not analysed in rekordbox', 'In Cloud Library Sync',
      'Not enough free space', "Couldn't compare it"]);
    expect(m.refused.map((x) => x.tip)).toEqual(['Sentence 0.', 'Sentence 1.', 'Sentence 2.', 'Sentence 3.', 'Sentence 4.']);
    expect(m.waiting).toEqual([]);
  });
  it('an Upgraded row says how it went, and keeps the engine\'s note only when it has kept edits or no rekordbox track', () => {
    const m = endModel(run([...RESULTS, ...PHASE], { auto_upgrade: block(LINE) }), null, NOW);
    expect(m.upgraded[0].sub).toBe('Now an AIFF file; rekordbox follows it');
    expect(m.upgraded[1].sub).toBe('Kept your own title / artist in rekordbox');
    expect(upgradedDetail('x', 'in_place')).toBe('Same AIFF, lossless audio');
    expect(upgradedDetail("This file isn't in your rekordbox collection, so there was nothing to keep there.", 'new_aiff'))
      .toBe("This file isn't in your rekordbox collection, so there was nothing to keep there");
    expect(upgradedDetail("Kept your own title in rekordbox. This file isn't in your rekordbox collection, so there was nothing to keep there.", 'in_place'))
      .toBe("Kept your own title in rekordbox · This file isn't in your rekordbox collection, so there was nothing to keep there");
    expect(upgradedDetail('whatever', undefined)).toBe('');
  });
  it('the phase\'s tracks are not new files, nor other changes, nor counted as added', () => {
    const m = endModel(run([...RESULTS, ...PHASE], { auto_upgrade: block(LINE) }), null, NOW);
    expect(m.stats.added).toBe(4);
    expect(m.added.flatMap((g) => g.rows).map((x) => x.title)).not.toContain('g1');
    expect(m.other.map((x) => x.title)).toEqual(['m1', 'u1']);
  });
  it('leaves an empty part out: only waiting tracks, only upgraded ones, only refused ones', () => {
    const waitingOnly = endModel(run(PHASE.slice(2, 4), { auto_upgrade: block('2 upgrades wait.') }), null, NOW);
    expect(waitingOnly.upgraded).toEqual([]);
    expect(waitingOnly.refused).toEqual([]);
    expect(waitingOnly.auto.map((p) => p.key)).toEqual(['waiting']);
    const upgradedOnly = endModel(run(PHASE.slice(0, 2), { auto_upgrade: block('Upgraded 2 tracks; your cues stayed.') }), null, NOW);
    expect(upgradedOnly.waiting).toEqual([]);
    expect(upgradedOnly.auto.map((p) => p.key)).toEqual(['upgraded']);
    const refusedOnly = endModel(run(PHASE.slice(4), { auto_upgrade: block(null) }), null, NOW);
    expect(refusedOnly.auto.map((p) => p.key)).toEqual(['refused']);
  });
  it('a run with nothing to say has no note (the line is null), and a switch-off run shows no part', () => {
    expect(endModel(run(PHASE, { auto_upgrade: block(null) }), null, NOW).notes).toEqual([]);
    const off = endModel(run(RESULTS), null, NOW);
    expect(off.upgraded).toEqual([]);
    expect(off.waiting).toEqual([]);
    expect(off.refused).toEqual([]);
    expect(off.auto).toEqual([]);
    expect(off.notes.map((n) => n.test)).toEqual(['sync-checked']);
  });
  it('the note comes after the stop line and before the other notes', () => {
    const m = endModel(run(PHASE, { exit_code: 130, stopped_after: 2, queued: 3, upgrades_ready: 1, auto_upgrade: block(LINE) }), null, NOW);
    expect(m.notes.map((n) => n.test)).toEqual(['sync-stopped-line', 'sync-auto-upgrade', 'sync-upgrades']);
  });
  it('a track without an id is not listed (no row can open it)', () => {
    const m = endModel(run([r('upgraded', 'Bouncy', 'g3', { track_id: null })], { auto_upgrade: block(LINE) }), null, NOW);
    expect(m.upgraded).toEqual([]);
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
