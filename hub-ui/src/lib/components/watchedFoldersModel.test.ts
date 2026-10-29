import { describe, expect, it } from 'vitest';
import type { JobSnap, WatchedFolderRow, WatchedFolders } from '$lib/bridge/types';
import {
  UNREADABLE_HINT, canContinue, doneLine, filesText, folderLine, folderMark, importView, phaseLine, phaseShare,
  folderLabel, pathParts, removeWords, settingsLine, sharesName, stoppedLine, unreadableLabel, unreadableSub, unreadableWhere,
  fitPath,
} from './watchedFoldersModel';

describe('fitPath', () => {
  const upTo = (n: number) => (s: string) => s.length <= n;   // a width measured in characters
  const NB = '\u00A0';
  it('names the drive first, then what is inside it: "Example Drive › Music"', () => {
    expect(fitPath('/Volumes/Example Drive/Music', upTo(40))).toEqual({ head: `Example Drive ›${NB}`, tail: 'Music' });
    expect(fitPath('/Volumes/New Volume/Some Crates', upTo(40))).toEqual({ head: `New Volume ›${NB}`, tail: 'Some Crates' });
    expect(fitPath('/Volumes/Example Drive/Music/Sets/', upTo(40))).toEqual({ head: `Example Drive ›${NB}`, tail: 'Music/Sets' });
    expect(fitPath('/Volumes/Example Drive', upTo(40))).toEqual({ head: 'Example Drive', tail: '' });
  });
  it('gives up the folders inside the drive whole from the front, the drive stays whole', () => {
    expect(fitPath('/Volumes/Example Drive/Music/Old/Sets', upTo(30)).tail).toBe('Music/Old/Sets');   // 16 + 14
    expect(fitPath('/Volumes/Example Drive/Music/Old/Sets', upTo(29)).tail).toBe('…/Old/Sets');
    expect(fitPath('/Volumes/Example Drive/Music/Old/Sets', upTo(24)).tail).toBe('…/Sets');
  });
  it('cuts the middle of the last folder only when it alone is too wide, the drive still whole', () => {
    const r = fitPath('/Volumes/Example Drive/Long Crates Name', upTo(24));
    expect(r.head).toBe(`Example Drive ›${NB}`);
    expect(r.tail).toBe('Lon…Name');
    expect(fitPath('/Volumes/Example Drive/Music/Long Crates Name', upTo(24)).tail).toBe('…/Lo…ame');
    // nothing of the folder fits beside the drive: "…" stands for it
    expect(fitPath('/Volumes/Example Drive/Music', upTo(18))).toEqual({ head: `Example Drive ›${NB}`, tail: '…' });
    expect(fitPath('/Volumes/Example Drive/Music', upTo(3))).toEqual({ head: `Example Drive ›${NB}`, tail: '…' });
  });
  it('gives up whole folders from the front elsewhere, home as ~', () => {
    expect(fitPath('/Users/you/Music/Old/Crates', upTo(18)).head).toBe('~/Music/Old');
    expect(fitPath('/Users/you/Music/Old/Crates', upTo(17)).head).toBe('…/Old');
    expect(fitPath('/Archive/Music/Old/Crates', upTo(18)).head).toBe('…/Music/Old');
  });
  it('cuts the shortest form\'s end when nothing fits, "…" right before the tail, no blank', () => {
    expect(fitPath('/Archive Drive/Music', upTo(10))).toEqual({ head: '/Ar…', tail: '/Music' });
    expect(fitPath('/Archive Drive/Music', upTo(3))).toEqual({ head: '…', tail: '/Music' });
    expect(fitPath('/Crates', upTo(1))).toEqual({ head: '', tail: '/Crates' });
  });
});

const row = (over: Partial<WatchedFolderRow> = {}): WatchedFolderRow => ({ id: 2, path: '/Volumes/Example Drive/Music',
  name: 'Music', kind: 'import', state: 'online', files: 1240, waiting: 0, unreadable: 0, ...over });
const lib = row({ id: 1, kind: 'library', name: 'Library', path: '/Users/you/Music/Discjockey/Library', files: 412 });
const data = (over: Partial<WatchedFolders> = {}): WatchedFolders => ({ folders: [lib, row()], unreadable: [], waiting: 0,
  stopped: false, ...over });
const job = (over: Partial<JobSnap> = {}): JobSnap => ({ id: 7, kind: 'import', track_id: null, started: '', running: true,
  stopping: false, last: {}, results: [], finished: null, actions: [], ...over });
const progress = (phase: 'scan' | 'tags' | 'sound' | 'link', done = 0, total = 0) =>
  ({ type: 'ImportProgress' as const, phase, done, total, unreadable: 0 });

describe('a folder row (W3)', () => {
  it('says its state in the engine words, the Library always watched', () => {
    expect(folderLine(lib)).toBe('Always watched');
    expect(folderLine(row())).toBe('Online');
    expect(folderLine(row({ state: 'offline' }))).toBe('Offline: connect the drive');
    expect(folderLine(row({ state: 'scanning' }))).toBe('Checking for new files');
  });
  it("never carries the import's run numbers: while it runs, a folder says how many of its files wait", () => {
    expect(folderLine(row({ state: 'importing', files: 1840, waiting: 1500 }))).toBe('Importing · 1,500 waiting');
    expect(folderLine(row({ state: 'importing', files: 1840, waiting: 1 }))).toBe('1 file waiting');
    expect(folderLine(row({ state: 'importing', files: 1840, waiting: 0 }))).toBe('Importing');
  });
  it('tells two folders with one name apart by the short path (~ for home)', () => {
    const a = row({ id: 3, name: 'Crates', path: '/Users/you/Music/Crates' });
    const b = row({ id: 4, name: 'crates', path: '/Volumes/Example Drive/Crates' });
    expect(sharesName(a, [lib, a, b])).toBe(true);
    expect(sharesName(a, [lib, a, row()])).toBe(false);
    expect(folderLabel(a, [lib, a, b])).toBe('Crates (~/Music/Crates)');
    expect(folderLabel(a, [lib, a])).toBe('Crates');
  });
  it('keeps the end of a path on its one line, the middle gives way', () => {
    expect(pathParts('/Archive/Example Drive/Music')).toEqual({ head: '/Archive/Example Drive', tail: '/Music' });
    expect(pathParts('/Users/you/Music/Crates/')).toEqual({ head: '~/Music', tail: '/Crates' });
    expect(pathParts('/Crates')).toEqual({ head: '', tail: '/Crates' });
    expect(pathParts('/Users/you')).toEqual({ head: '~', tail: '' });
  });
  it('marks it as colour plus shape: readable, offline, worked on', () => {
    expect(folderMark(lib)).toBe('good');
    expect(folderMark(row({ state: 'offline' }))).toBe('warn');
    expect(folderMark(row({ state: 'importing' }))).toBe('working');
    expect(folderMark({ ...lib, state: 'scanning' })).toBe('working');
  });
  it('counts in the singular for 1', () => {
    expect(filesText(1)).toBe('1 file');
    expect(filesText(0)).toBe('0 files');
    expect(filesText(12400)).toBe('12,400 files');
  });
});

describe('the import (W6)', () => {
  it('says each phase, with counts where it counts', () => {
    expect(phaseLine(progress('scan'))).toBe('Looking for music files');
    expect(phaseLine(progress('tags', 340, 1500))).toBe('Reading tags · 340 of 1,500');
    expect(phaseLine(progress('sound', 1, 2))).toBe('Checking the sound · 1 of 2');
    expect(phaseLine(progress('link'))).toBe('Linking to your playlists');
    expect(phaseShare(progress('tags', 375, 1500))).toBe(0.25);
    expect(phaseShare(progress('scan'))).toBeNull();
    expect(phaseShare(progress('link'))).toBeNull();
  });
  it('stopped and done, singular for 1', () => {
    expect(stoppedLine(1160)).toBe('Import stopped with 1,160 files to go. It carries on where it stopped.');
    expect(stoppedLine(1)).toBe('Import stopped with 1 file to go. It carries on where it stopped.');
    expect(doneLine(1)).toBe('Imported 1 file.');
  });
  it("follows the hub's import job: running from its last ImportProgress, looking for files until the first", () => {
    expect(importView(job(), data())).toEqual({ kind: 'running', line: 'Looking for music files', share: null, stopping: false });
    expect(importView(job({ stopping: true, last: { ImportProgress: progress('tags', 340, 1500) } }), data()))
      .toMatchObject({ line: 'Reading tags · 340 of 1,500', stopping: true });
    // another job is no import
    expect(importView(job({ kind: 'sync' }), data())).toBeNull();
    expect(importView(null, data())).toBeNull();
  });
  it('stopped this session with files left: the stopped line, and Continue import while nothing imports', () => {
    const stopped = data({ stopped: true, waiting: 1160 });
    expect(importView(job({ running: false, finished: { ok: false, problem: 'stopped', message: '' } }), stopped))
      .toEqual({ kind: 'stopped', line: stoppedLine(1160) });
    expect(canContinue(null, stopped)).toBe(true);
    expect(canContinue(job(), stopped)).toBe(false);
    expect(canContinue(null, data())).toBe(false);
    // files waiting without a stop (a drive came back): Continue import is offered, no stopped line
    expect(canContinue(null, data({ waiting: 4 }))).toBe(true);
    expect(importView(null, data({ waiting: 4 }))).toBeNull();
  });
  it("ends with the engine's words, else counts the result; a failure says its message", () => {
    const fin = (ok: boolean, message: string, problem: string | null = null) =>
      job({ running: false, finished: { ok, problem, message, result: { files: 180 } } });
    expect(importView(fin(true, 'Imported 180 files.'), data())).toEqual({ kind: 'done', line: 'Imported 180 files.' });
    expect(importView(fin(true, ''), data())).toEqual({ kind: 'done', line: 'Imported 180 files.' });
    expect(importView(fin(false, 'Something went wrong. Try again.', 'crashed'), data()))
      .toEqual({ kind: 'failed', line: 'Something went wrong. Try again.' });
    expect(importView(fin(false, '', 'stopped'), data())).toBeNull();
  });
});

describe("couldn't read (W6)", () => {
  const folders = [lib, row({ path: '/Volumes/Example Drive/Music', name: 'Music' })];
  const u = (path: string) => ({ folder_id: 2, path, reason: "macOS doesn't let Discjockey read it" });
  it('heads the list with the count', () => {
    expect(unreadableLabel(3)).toBe("Couldn't read (3)");
    expect(UNREADABLE_HINT).toBe('Tried again at the next import.');
  });
  it("says where the file is, not its name again: the folder inside the watched one, or that one's name at its root", () => {
    expect(unreadableWhere(u('/Volumes/Example Drive/Music/Old/Sets/a.wav'), folders)).toBe('Old/Sets');
    expect(unreadableWhere(u('/Volumes/Example Drive/Music/a.wav'), folders)).toBe('Music');
    expect(unreadableSub(u('/Volumes/Example Drive/Music/Old/a.wav'), folders))
      .toBe("Old · macOS doesn't let Discjockey read it");
    // a folder that is gone from the list: the file's folder, short
    expect(unreadableWhere({ folder_id: 9, path: '/Users/you/Music/Crates/a.wav', reason: '' }, folders)).toBe('~/Music/Crates');
  });
});

describe("Settings' row (W2)", () => {
  it('names the import phase as the card does', () => {
    const j = (phase: 'tags' | 'sound', done: number) => job({ last: { ImportProgress: progress(phase, done, 1500) } });
    expect(settingsLine(data(), j('tags', 340))).toEqual({ tone: null, text: 'Reading tags · 340 of 1,500' });
    expect(settingsLine(data(), j('sound', 0)).text).toBe('Checking the sound · 0 of 1,500');
    expect(settingsLine(data(), job()).text).toBe('Looking for music files');
  });
});

describe('remove (W4)', () => {
  it('names the folder and its files; the files stay', () => {
    expect(removeWords({ name: 'Music', files: 1240, redownload: 0 })).toEqual({ title: 'Remove Music?',
      body: 'Discjockey forgets its 1,240 files. The files stay where they are.' });
    expect(removeWords({ name: 'Crates', files: 1, redownload: 0 }).body)
      .toBe('Discjockey forgets its 1 file. The files stay where they are.');
  });
  it('keeps the title and says which folder it is when two share the name', () => {
    expect(removeWords({ name: 'Music', files: 10, redownload: 0 }, '~/Music')).toEqual({ title: 'Remove Music?',
      body: 'This is the folder at ~/Music. Discjockey forgets its 10 files. The files stay where they are.' });
  });
  it('says the playlist songs that had their only copy there, singular for 1', () => {
    expect(removeWords({ name: 'Music', files: 1240, redownload: 4 }).body).toBe('Discjockey forgets its 1,240 files. '
      + 'The files stay where they are. 4 songs from your playlists had their only copy there. They will be downloaded '
      + 'again at the next sync.');
    expect(removeWords({ name: 'Music', files: 10, redownload: 1 }).body).toBe('Discjockey forgets its 10 files. '
      + 'The files stay where they are. 1 song from your playlists had its only copy there. It will be downloaded '
      + 'again at the next sync.');
  });
});
