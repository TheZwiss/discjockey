// The AIFF card of one track (issue 33 stage D, plan §6.1, §3): when it shows, its button, the reason the button is off,
// the rows, the outcome rows, the two notes and what a finished job says when the track didn't go.
import { describe, expect, it } from 'vitest';
import type { AiffBatchResult, ItemResult, RekordboxStatus, TrackAiff } from '$lib/bridge/types';
import type { JobOutcome } from '$lib/bridge/client';
import {
  AIFF_LINE, CONVERT_LABEL, LOSSY_NOTE, REKORDBOX_OPEN_WORDS, RENAME_LABEL, aiffAction, aiffBlocked, aiffLabel, aiffNotes, aiffOutcomes,
  aiffProblem, aiffRows, aiffShown, aiffVariant,
} from './aiffModel';
import { formatWords } from '$lib/format';
import { QUIT_FIRST } from './aiffBatchModel';

const CDJ = { short: 'FLAC: CDJs refuse it', words: 'Most CDJs and XDJs refuse FLAC.' };
const convert = (extra: Partial<TrackAiff> = {}): TrackAiff => ({ action: 'convert', why_not: null, kind: 'flac',
  from: 'FLAC · 24-bit · 96 kHz', to: AIFF_LINE, name_now: 'Neon Riot - Neonfieber.flac', new_name: 'Neon Riot - Neonfieber.aiff',
  bytes: 61_400_000, lossy: false, cdj: null, ...extra });
const rename = (extra: Partial<TrackAiff> = {}): TrackAiff => ({ action: 'rename', why_not: null, kind: 'name', from: AIFF_LINE,
  to: null, name_now: 'neon_riot_-_neonfieber_(Original_Mix).aiff', new_name: 'Neon Riot - Neonfieber.aiff', bytes: 0, lossy: false,
  cdj: null, ...extra });
// a file with no step at all (named already, away, ...): the engine answers `action` null
const none = (why_not: string, extra: Partial<TrackAiff> = {}): TrackAiff => ({ action: null, why_not, kind: null,
  from: 'FLAC · 24-bit · 96 kHz', to: null, name_now: 'Neon Riot - Neonfieber.flac', new_name: null, bytes: 0, lossy: false, cdj: null, ...extra });
// a blocked step (A-1): the step's own values, `why_not` says why it waits
const blocked = (why_not: string, extra: Partial<TrackAiff> = {}): TrackAiff => ({ ...convert(), why_not, ...extra });
// no free name: a rename with no new name and no room needed
const noName = (extra: Partial<TrackAiff> = {}): TrackAiff => ({ ...rename(), why_not: 'rename_blocked', new_name: null, ...extra });
const rb = (state: RekordboxStatus['state'], running = false): RekordboxStatus => ({ state, running });

describe('when the card shows', () => {
  it('for a file with an action, and for the three reasons the card explains', () => {
    expect(aiffShown(convert(), null, false)).toBe(true);
    expect(aiffShown(rename(), null, false)).toBe(true);
    for (const r of ['rekordbox_unreadable', 'cloud']) expect(aiffShown(blocked(r), null, false), r).toBe(true);
    expect(aiffShown(noName(), null, false)).toBe(true);
    // the same reasons without a step (an older answer) still show the card with its Hint
    for (const r of ['rekordbox_unreadable', 'cloud', 'rename_blocked']) expect(aiffShown(none(r), null, false), r).toBe(true);
  });
  it('not for a download, a clean AIFF with its name, a file that is away or missing, or with nothing known', () => {
    expect(aiffShown(null, null, false)).toBe(false);
    expect(aiffShown(undefined, null, false)).toBe(false);
    for (const r of ['named_already', 'away', 'file_missing', 'downloaded', 'no_name', 'upgrade_waits']) {
      expect(aiffShown(none(r), null, false), r).toBe(false);
    }
    expect(aiffShown(convert(), null, true)).toBe(false);
  });
  it('never beside a decision: the upgrade, the check a step left and a duplicate group win', () => {
    expect(aiffShown(convert(), { kind: 'upgrade' }, false)).toBe(false);
    expect(aiffShown(convert(), { kind: 'check', item: {} as never }, false)).toBe(false);
    expect(aiffShown(rename(), { kind: 'duplicate', item: {} as never }, false)).toBe(false);
  });
});

describe('the button', () => {
  it('says Convert to AIFF or Give it its clean name', () => {
    expect([aiffLabel(convert()), aiffAction(convert())]).toEqual([CONVERT_LABEL, 'convert']);
    expect([aiffLabel(rename()), aiffAction(rename())]).toEqual([RENAME_LABEL, 'rename']);
    // a blocked card carries the step it would run: its `action` decides, never the file's format line
    expect(aiffAction(blocked('rekordbox_unreadable'))).toBe('convert');
    expect(aiffLabel(blocked('cloud'))).toBe(CONVERT_LABEL);
    expect(aiffAction(noName())).toBe('rename');
    expect(aiffLabel(noName())).toBe(RENAME_LABEL);
    // a 16-bit / 44.1 kHz AIFF whose tags are wrong is a Convert, blocked or not (it is not a rename)
    expect(aiffAction(blocked('rekordbox_unreadable', { kind: 'tags', from: AIFF_LINE }))).toBe('convert');
    expect(aiffAction(convert({ kind: 'tags', from: AIFF_LINE }))).toBe('convert');
  });
  it('is filled for a lossless file, a file the CDJs refuse and a Rename; outlined for any other lossy file', () => {
    expect(aiffVariant(convert())).toBe('filled');
    expect(aiffVariant(convert({ kind: 'mp3', from: 'MP3 · 320 kbps', lossy: true }))).toBe('outline');
    expect(aiffVariant(convert({ kind: 'mp3', from: 'MP3 · 320 kbps', lossy: true, cdj: CDJ }))).toBe('filled');
    expect(aiffVariant(rename())).toBe('filled');
    expect(aiffVariant(blocked('cloud', { lossy: true }))).toBe('outline');
    expect(aiffVariant(noName())).toBe('filled');
  });
});

describe('why the button is off', () => {
  it('rekordbox\'s library can\'t be opened, a track in Cloud Library Sync, no free name: design §8\'s words, each under 90 characters', () => {
    const texts = [aiffBlocked(blocked('rekordbox_unreadable'), rb('ready')), aiffBlocked(blocked('cloud'), rb('ready')),
      aiffBlocked(noName(), null)];
    expect(texts).toEqual([
      "Discjockey can't open rekordbox's library yet, so it can't point your track at the file.",
      "This track is in rekordbox's Cloud Library Sync, which Discjockey doesn't change yet.",
      // the engine's own sentence (A6): a name clash, not rekordbox's fault; "Nothing was changed." left out, nothing ran
      'Every name this file could take is in use, so it keeps its name for now.']);
    for (const t of texts) expect(t!.length).toBeLessThanOrEqual(90);
  });
  it('a Rename waits while rekordbox is open, and when its library can\'t be opened, with the reason first', () => {
    expect(aiffBlocked(rename(), rb('ready', true))).toBe("rekordbox is open, so Discjockey can't point your track at the new name.");
    const unreadable = aiffBlocked(rename(), rb('unreadable'))!;
    expect(unreadable).toBe("rekordbox's library can't be opened, so Discjockey can't point your track at the new name.");
    expect(unreadable.length).toBeLessThanOrEqual(90);
  });
  it('a Rename runs while rekordbox is closed, not known yet or not on this Mac; a Convert is never switched off by it', () => {
    expect(aiffBlocked(rename(), rb('ready', false))).toBeNull();
    expect(aiffBlocked(rename(), null)).toBeNull();
    expect(aiffBlocked(rename(), rb('none', true))).toBeNull();
    expect(aiffBlocked(convert(), rb('ready', true))).toBeNull();
  });
});

describe('the rows', () => {
  it('a Convert says NOW, BECOMES, NAME (old over new) and SPACE', () => {
    expect(aiffRows(convert())).toEqual([
      { key: 'now', k: 'Now', v: 'FLAC · 24\u2011bit · 96 kHz' }, { key: 'becomes', k: 'Becomes', v: formatWords(AIFF_LINE) },
      { key: 'name', k: 'Name', v: null, from: 'Neon Riot - Neonfieber.flac', to: 'Neon Riot - Neonfieber.aiff' },
      { key: 'space', k: 'Space', v: '+61 MB; your original goes to Superseded/' }]);
  });
  it('the space in GB from a billion bytes', () => {
    expect(aiffRows(convert({ bytes: 1_240_000_000 })).at(-1)!.v).toBe('+1.2 GB; your original goes to Superseded/');
  });
  it('a name that stays (an AIFF that ends where it was) is the name once', () => {
    const [, , name] = aiffRows(convert({ kind: 'tags', from: AIFF_LINE, name_now: 'A - B.aiff', new_name: 'A - B.aiff' }));
    expect(name).toMatchObject({ key: 'name', from: 'A - B.aiff', to: undefined });
  });
  it('a Rename is the NAME row alone, no space', () => {
    expect(aiffRows(rename())).toEqual([{ key: 'name', k: 'Name', v: null, from: 'neon_riot_-_neonfieber_(Original_Mix).aiff',
      to: 'Neon Riot - Neonfieber.aiff' }]);
  });
  it('a file with no step says what it is now, nothing else', () => {
    expect(aiffRows(none('cloud'))).toEqual([{ key: 'now', k: 'Now', v: 'FLAC · 24\u2011bit · 96 kHz' }]);
    expect(aiffRows(none('cloud', { from: null }))).toEqual([]);
  });
  it('a blocked step shows the rows of the step it would run: Now, Becomes, Name, Space', () => {
    for (const r of ['rekordbox_unreadable', 'cloud']) expect(aiffRows(blocked(r)), r).toEqual(aiffRows(convert()));
    expect(aiffRows(blocked('cloud')).map((x) => x.key)).toEqual(['now', 'becomes', 'name', 'space']);
  });
  it('no free name: the Name row alone, the name once (nothing to point at)', () => {
    expect(aiffRows(noName())).toEqual([{ key: 'name', k: 'Name', v: null, from: 'neon_riot_-_neonfieber_(Original_Mix).aiff', to: undefined }]);
  });
});

describe('the outcome rows of a Convert', () => {
  it('with rekordbox ready: the track keeps its cues, the file becomes an AIFF; the step only while it runs', () => {
    expect(aiffOutcomes(convert(), rb('ready', false)).map((o) => [o.tone, o.text])).toEqual([
      ['kept', 'Your track keeps its cues, playlists and history'], ['file', 'Becomes an AIFF file']]);
    expect(aiffOutcomes(convert(), rb('ready', true)).map((o) => [o.tone, o.text])).toEqual([
      ['kept', 'Your track keeps its cues, playlists and history'], ['file', 'Becomes an AIFF file'], ['step', QUIT_FIRST]]);
  });
  it('none without a rekordbox Discjockey can open, while its state is unknown, or for a Rename or a card that can\'t run', () => {
    expect(aiffOutcomes(convert(), rb('none'))).toEqual([]);
    expect(aiffOutcomes(convert(), rb('unreadable', true))).toEqual([]);
    expect(aiffOutcomes(convert(), null)).toEqual([]);
    expect(aiffOutcomes(rename(), rb('ready', true))).toEqual([]);
    expect(aiffOutcomes(none('cloud'), rb('ready'))).toEqual([]);
    expect(aiffOutcomes(blocked('cloud'), rb('ready'))).toEqual([]);  // it doesn't run: no outcome to promise
  });
});

describe('the notes', () => {
  it('what the CDJs refuse is a warn note with its words, above the card', () => {
    expect(aiffNotes(convert({ cdj: CDJ }))).toEqual({ above: [{ key: 'cdj', tone: 'warn', text: CDJ.words }], below: [] });
  });
  it('a lossy Convert says what the AIFF costs, an info note under the card', () => {
    expect(aiffNotes(convert({ lossy: true, kind: 'mp3' }))).toEqual({ above: [], below: [{ key: 'lossy', tone: 'info', text: LOSSY_NOTE }] });
    expect(LOSSY_NOTE).toBe('An AIFF made from this sounds the same and takes 5–10 times the space.');
  });
  it('both for a lossy file the CDJs refuse; none for a lossless one, a Rename, or a card that can\'t run', () => {
    const n = aiffNotes(convert({ lossy: true, kind: 'mp3', cdj: CDJ }));
    expect([n.above.length, n.below.length]).toEqual([1, 1]);
    expect(aiffNotes(convert())).toEqual({ above: [], below: [] });
    expect(aiffNotes(rename()).below).toEqual([]);
    expect(aiffNotes(none('cloud', { lossy: true })).below).toEqual([]);
    expect(aiffNotes(blocked('cloud', { lossy: true, kind: 'mp3' })).below).toEqual([]);
  });
});

describe('a job that did not take the track', () => {
  const done = (results: Partial<ItemResult>[]): JobOutcome<AiffBatchResult> => ({ ok: true, job_id: 1, result: { batch: 1, state: 'done',
    stop_reason: null, total: results.length, done: 0, skipped: results.length, failed: 0, backup: null, recovered: [],
    results: results.map((r) => ({ track: 'own:1', action: 'convert', state: 'skipped', reason: null, message: null, path: null,
      rekordbox: null, ...r })) } });
  it('a refusal says its own words; rekordbox open has design §8\'s as a fallback', () => {
    expect(aiffProblem({ ok: false, job_id: 3, kind: 'refused', message: 'Nothing here can be changed.' })).toBe('Nothing here can be changed.');
    expect(aiffProblem({ ok: false, job_id: 3, kind: 'rekordbox_open', message: '' })).toBe(REKORDBOX_OPEN_WORDS);
    expect(aiffProblem({ ok: false, job_id: null, kind: 'busy', message: '' })).toBe("That didn't work.");
  });
  it('a skipped or failed track says why; a track that went says nothing', () => {
    expect(aiffProblem(done([{ message: 'Analyse the track again in rekordbox.' }]))).toBe('Analyse the track again in rekordbox.');
    expect(aiffProblem(done([{ state: 'failed', message: 'Disk full.' }]))).toBe('Disk full.');
    expect(aiffProblem(done([{ reason: 'rekordbox_open' }]))).toBe(REKORDBOX_OPEN_WORDS);
    expect(aiffProblem(done([{ state: 'done' }]))).toBeNull();
    expect(aiffProblem(done([]))).toBeNull();
  });
});
