// The AIFF batch panel's rules (issue 33 stage D, plan §6.0.2, §3): the head's words per scope and while the plan is
// read, the filled button's words and why it is off, the >8 rule, the left-out list, the notes and outcome rows, the
// phase, and the end's words.
import { describe, expect, it } from 'vitest';
import type { AiffPlan, AiffPlanItem, AiffScope } from '$lib/bridge/types';
import {
  EMPTY_VIEW, FILES_MAX, NOTHING_TO_CHANGE, QUIT_FIRST, aiffEndNote, aiffRunLabel, blockReason, driveName, emptyWords, leftCount,
  leftRows, listShape, lossyNote, madeWords, panelHead, panelPhase, planOutcomes, runLabel, scopeKey, showsFormat, spaceRows,
} from './aiffBatchModel';
import { resumeLabel, type BatchEnd } from './decisionModel';

const item = (n: number, action: 'convert' | 'rename' = 'convert', kind = 'flac'): AiffPlanItem => ({ track: `own:${n}`,
  name: `Artist ${n} - Title`, action, kind, from: 'FLAC · 16-bit · 44.1 kHz', path: `${n}.flac`, new_path: `${n}.aiff`,
  superseded: action === 'convert' ? `Superseded/${n}.flac` : null, bytes: action === 'convert' ? 50_000_000 : 0, cdj: null });
const SEL: AiffScope = { kind: 'tracks', tracks: ['own:3', 'own:1', 'own:2'] };
const VIEW: AiffScope = { kind: 'lossless', view: 'folder', key: '/Volumes/Example Drive/Music' };
const CDJ: AiffScope = { kind: 'cdj' };
function plan(o: Partial<AiffPlan> = {}, scope: AiffScope = SEL, label = 'Selection'): AiffPlan {
  const items = o.items ?? [item(1), item(2)];
  return { scope: { ...scope, label } as AiffPlan['scope'], items, skipped: [], waiting: [],
    kinds: [{ kind: 'flac', label: 'FLAC → AIFF', n: items.length }], lossy: 0, total: items.length,
    space: [{ drive: '/Volumes/Example Drive/Music', needed: 100_000_000, free: 400_000_000_000, enough: true }],
    superseded_bytes: 60_000_000, rekordbox: { state: 'ready', running: false, needs_closed: true }, ...o };
}
const end = (o: Partial<BatchEnd>): BatchEnd => ({ mode: 'swap', kind: 'done', done: 0, total: 0, message: '', resume: null, ...o });

describe('scopeKey', () => {
  it('is one key per scope: a selection in any order is the same', () => {
    expect(scopeKey(SEL)).toBe(scopeKey({ kind: 'tracks', tracks: ['own:1', 'own:2', 'own:3'] }));
    expect(scopeKey(VIEW)).not.toBe(scopeKey({ ...VIEW, key: '/Volumes/Example Drive/Other' }));
    expect(scopeKey(CDJ)).toBe('cdj');
  });
});

describe('panelHead', () => {
  it('a selection: "{n} tracks selected" at once, "{k} can become clean AIFF" once read, "Nothing to change" for none', () => {
    expect(panelHead(SEL, null, 'library')).toEqual({ title: '3 tracks selected', sub: null });
    expect(panelHead(SEL, plan(), 'library')).toEqual({ title: '3 tracks selected', sub: '2 can become clean AIFF' });
    expect(panelHead(SEL, plan({ items: [] }), 'library').sub).toBe('Nothing to change');
  });
  it('a view: the title at once, "in {label}" from the page while the plan is read, then from the plan', () => {
    expect(panelHead(VIEW, null, 'library')).toEqual({ title: 'Make all lossless files AIFF', sub: null });
    expect(panelHead(VIEW, null, 'library', 'Music')).toEqual({ title: 'Make all lossless files AIFF', sub: 'in Music' });
    expect(panelHead(VIEW, plan({}, VIEW, 'Hard Bounce'), 'library', 'Music').sub).toBe('in Hard Bounce');
  });
  it('the CDJ group: "{n} files for CDJs" counting the waiting ones, "Convert all · {k}"; To-do\'s selection says CDJs too', () => {
    const p = plan({ waiting: [{ reason: 'cloud', message: 'x', n: 1 }] }, CDJ, "Won't play well on CDJs");
    expect(panelHead(CDJ, null, 'todo')).toEqual({ title: null, sub: null });
    expect(panelHead(CDJ, p, 'todo')).toEqual({ title: '3 files for CDJs', sub: 'Convert all · 2' });
    expect(panelHead({ kind: 'tracks', tracks: ['own:1', 'own:2'] }, plan(), 'todo').title).toBe('2 files for CDJs');
  });
});

describe('runLabel: the filled button', () => {
  it('"Make {k} files AIFF", "Make 1 file AIFF"; the words without a number while the plan is read', () => {
    expect(runLabel(SEL, plan(), 'library')).toBe('Make 2 files AIFF');
    expect(runLabel(SEL, plan({ items: [item(1)] }), 'library')).toBe('Make 1 file AIFF');
    expect(runLabel(VIEW, null, 'library')).toBe('Make AIFF');
  });
  it('the CDJ group and To-do: "Convert {k} to AIFF"', () => {
    expect(runLabel(CDJ, plan(), 'todo')).toBe('Convert 2 to AIFF');
    expect(runLabel(SEL, plan({ items: [item(1), item(2), item(3)] }), 'todo')).toBe('Convert 3 to AIFF');
    expect(runLabel(CDJ, null, 'todo')).toBe('Convert to AIFF');
  });
  it('clean names only say what they do; a mix of both makes AIFF', () => {
    expect(runLabel(SEL, plan({ items: [item(1, 'rename', 'name'), item(2, 'rename', 'name')] }), 'library'))
      .toBe('Give 2 files their clean names');
    expect(runLabel(SEL, plan({ items: [item(1, 'rename', 'name')] }), 'library')).toBe('Give 1 file its clean name');
    expect(runLabel(SEL, plan({ items: [item(1, 'rename', 'name'), item(2)] }), 'library')).toBe('Make 2 files AIFF');
  });
});

describe('blockReason: why the filled button is off', () => {
  it('a short drive, in the problem tone, with its numbers', () => {
    const p = plan({ space: [{ drive: '/Volumes/Example Drive/Music', needed: 1_240_000_000, free: 180_000_000, enough: false }] });
    expect(blockReason(p)).toEqual({ tone: 'problem', text: 'Not enough space on Example Drive: 1.2 GB needed, 180 MB free' });
  });
  it('rekordbox running while it holds some of these files; running without them, or closed, is no reason', () => {
    expect(blockReason(plan({ rekordbox: { state: 'ready', running: true, needs_closed: true } })))
      .toEqual({ tone: 'muted', text: QUIT_FIRST });
    expect(blockReason(plan({ rekordbox: { state: 'ready', running: true, needs_closed: false } }))).toBeNull();
    expect(blockReason(plan())).toBeNull();
  });
  it('a short drive comes first when both hold', () => {
    const p = plan({ rekordbox: { state: 'ready', running: true, needs_closed: true },
      space: [{ drive: '/Users/you/Music', needed: 2e9, free: 1e9, enough: false }] });
    expect(blockReason(p)?.text).toBe('Not enough space on this Mac: 2.0 GB needed, 1.0 GB free');
  });
});

describe('space rows', () => {
  it('names a drive by its own name under /Volumes, any other the Mac', () => {
    expect(driveName('/Volumes/Example Drive/Music/Library')).toBe('Example Drive');
    expect(driveName('/Users/you/Music/Discjockey')).toBe('this Mac');
  });
  it('"Needs {size} on {drive}" over "{free} free"; a drive that needs nothing (renames only) has no row', () => {
    const p = plan({ space: [{ drive: '/Volumes/Example Drive/Music', needed: 1_240_000_000, free: 412_300_000_000, enough: true },
      { drive: '/Users/you/Music', needed: 0, free: 1e9, enough: true }] });
    expect(spaceRows(p)).toEqual([{ drive: '/Volumes/Example Drive/Music', needs: 'Needs 1.2 GB on Example Drive',
      free: '412.3 GB free', enough: true }]);
  });
});

describe('the >8 rule', () => {
  it(`up to ${FILES_MAX} files are the list; more lead with the counts per kind`, () => {
    expect(listShape(plan({ items: Array.from({ length: FILES_MAX }, (_, i) => item(i)) }))).toBe('files');
    expect(listShape(plan({ items: Array.from({ length: FILES_MAX + 1 }, (_, i) => item(i)) }))).toBe('kinds');
  });
});

describe('Left as they are', () => {
  it('a selection: each left-out song with its reason', () => {
    const p = plan({ skipped: [{ track: 'own:8', name: 'A - B', reason: 'named_already', message: 'A clean AIFF with its clean name already.' }] });
    expect(leftRows(p)).toEqual([{ key: 'own:8', track: 'own:8', name: 'A - B', text: 'A clean AIFF with its clean name already.', n: 1 }]);
  });
  it('a view or the CDJ group: the waiting files counted by reason, never named', () => {
    const p = plan({ waiting: [{ reason: 'away', message: "The file's drive isn't connected, so nothing was changed.", n: 2 },
      { reason: 'cloud', message: 'In Cloud Library Sync.', n: 1 }] }, VIEW, 'Music');
    const rows = leftRows(p);
    expect(rows.map((r) => [r.track, r.name, r.n])).toEqual([[null, '2 files', 2], [null, '1 file', 1]]);
    expect(leftCount(rows)).toBe(3);
  });
});

describe('notes and outcome rows', () => {
  it('the lossy note: none, one, several', () => {
    expect(lossyNote(0)).toBeNull();
    expect(lossyNote(1)).toBe('1 of these is lossy: an AIFF made from it sounds the same and takes 5–10 times the space.');
    expect(lossyNote(3)).toBe('3 of these are lossy: an AIFF made from them sounds the same and takes 5–10 times the space.');
  });
  it('rekordbox keeps the cues only where it holds some of the files; the originals go to Superseded/ only for converts', () => {
    expect(planOutcomes(plan())).toEqual([{ tone: 'kept', text: 'Your tracks keep their cues, playlists and history' },
      { tone: 'file', text: 'Your originals (60 MB) go to Superseded/ on the same drive.' }]);
    expect(planOutcomes(plan({ items: [item(1)] }))).toEqual([{ tone: 'kept', text: 'Your track keeps its cues, playlists and history' },
      { tone: 'file', text: 'Your original (60 MB) goes to Superseded/ on the same drive.' }]);
    expect(planOutcomes(plan({ rekordbox: { state: 'none', running: false, needs_closed: false },
      items: [item(1, 'rename', 'name')], superseded_bytes: 0 }))).toEqual([]);
  });
  it('the format sentence only when something is converted', () => {
    expect(showsFormat(plan())).toBe(true);
    expect(showsFormat(plan({ items: [item(1, 'rename', 'name')] }))).toBe(false);
  });
});

describe('panelPhase', () => {
  it('loading until the first plan; a read again keeps the plan on screen', () => {
    expect(panelPhase(null, null)).toBe('loading');
    expect(panelPhase({ phase: 'loading', plan: null }, null)).toBe('loading');
    expect(panelPhase({ phase: 'loading', plan: plan() }, null)).toBe('decide');
  });
  it('error without a plan; empty with nothing to change and nothing left out; decide otherwise', () => {
    expect(panelPhase({ phase: 'error', plan: null }, null)).toBe('error');
    expect(panelPhase({ phase: 'ready', plan: plan({ items: [] }) }, null)).toBe('empty');
    expect(panelPhase({ phase: 'ready', plan: plan({ items: [], skipped: [{ track: 'a', name: 'a', reason: 'cloud', message: 'm' }] }) }, null))
      .toBe('decide');
    expect(panelPhase({ phase: 'ready', plan: plan({ items: [], waiting: [{ reason: 'away', message: 'm', n: 1 }] }, VIEW) }, null))
      .toBe('decide');
  });
  it('the batch\'s phase wins while it runs and until its end is put away', () => {
    expect(panelPhase({ phase: 'ready', plan: plan() }, { phase: 'running' })).toBe('running');
    expect(panelPhase(null, { phase: 'ended' })).toBe('ended');
  });
  it('the empty words: a view says every file is clean, a selection the engine\'s', () => {
    expect(emptyWords(VIEW)).toBe(EMPTY_VIEW);
    expect(emptyWords(SEL)).toBe(NOTHING_TO_CHANGE);
  });
});

describe('running and ended words', () => {
  it('the running label names the file in work', () => {
    expect(aiffRunLabel('A - B', false)).toBe('Making AIFF · A - B');
    expect(aiffRunLabel(null, true)).toBe('Giving clean names');
  });
  it('"Made {n} files AIFF" as the StatCard says it', () => {
    expect(madeWords(3, false)).toEqual({ unit: 'files', label: 'made AIFF' });
    expect(madeWords(1, false)).toEqual({ unit: 'file', label: 'made AIFF' });
    expect(madeWords(2, true)).toEqual({ unit: 'files', label: 'given their clean names' });
  });
  it('the end note: a stop counts, rekordbox opening says design §8\'s words, a refusal its own or the general ones', () => {
    expect(aiffEndNote(end({ kind: 'stopped', done: 2, total: 5 }))).toEqual({ tone: 'info', text: 'Stopped after 2 of 5.' });
    expect(aiffEndNote(end({ kind: 'rekordbox_open', done: 1, total: 3 }))?.text)
      .toBe('rekordbox was opened, so Discjockey stopped after 1 of 3. Quit rekordbox and press Resume.');
    expect(aiffEndNote(end({ kind: 'refused', message: NOTHING_TO_CHANGE }))).toEqual({ tone: 'warn', text: NOTHING_TO_CHANGE });
    expect(aiffEndNote(end({ kind: 'refused' }))?.text).toBe('None of these can be changed right now.');
    expect(aiffEndNote(end({ kind: 'done', done: 3, total: 3 }))).toBeNull();
  });
  it('Resume · {k} left', () => {
    expect(resumeLabel(7)).toBe('Resume · 7 left');
  });
});
