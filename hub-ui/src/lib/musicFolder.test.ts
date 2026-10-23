import { describe, expect, it } from 'vitest';
import { checkLine, musicGate, needsConfirm, newFolderPath, parentOf, shortPath } from './musicFolder';
import type { FolderCheck, MusicState, SetupStatus } from './bridge/types';

const chk = (o: Partial<FolderCheck>): FolderCheck =>
  ({ path: '/Users/you/Music/Discjockey', exists: true, usable: true, problem: null, kind: 'empty', message: null, ...o });
const setup = (state: MusicState) =>
  ({ music: { state, path: state === 'not_chosen' ? null : '/Volumes/DJ SSD/Discjockey', suggested: '/Users/you/Music/Discjockey' } }) as unknown as SetupStatus;

describe('shortPath', () => {
  it('shortens the home folder to ~', () => {
    expect(shortPath('/Users/you/Music/Discjockey')).toBe('~/Music/Discjockey');
    expect(shortPath('/Users/you')).toBe('~');
    expect(shortPath('/Users/you/')).toBe('~');
  });
  it('leaves other paths as they are', () => {
    expect(shortPath('/Volumes/DJ SSD/Discjockey')).toBe('/Volumes/DJ SSD/Discjockey');
    expect(shortPath('/Users')).toBe('/Users');
  });
  it('keeps spaces', () => {
    expect(shortPath('/Users/dj name/My Music/DJ Sets')).toBe('~/My Music/DJ Sets');
  });
});

describe('musicGate', () => {
  it('waits for the first answer', () => expect(musicGate(null)).toBeNull());
  it('ok is the app as usual', () => expect(musicGate(setup('ok'))).toBeNull());
  it('not chosen sends to Setup', () => expect(musicGate(setup('not_chosen'))).toBe('setup'));
  it('missing shows the missing screen', () => expect(musicGate(setup('missing'))).toBe('missing'));
});

describe('checkLine', () => {
  it('says nothing before a check', () => expect(checkLine(null)).toEqual({ tone: null, text: '' }));
  it('names every kind', () => {
    expect(checkLine(chk({ kind: 'new', exists: false }))).toEqual({ tone: 'good', text: 'Discjockey makes this folder.' });
    expect(checkLine(chk({ kind: 'empty' }))).toEqual({ tone: 'good', text: 'An empty folder.' });
    expect(checkLine(chk({ kind: 'discjockey_library' })))
      .toEqual({ tone: 'good', text: 'Your Discjockey library is here; it is used as it is.' });
    expect(checkLine(chk({ kind: 'other_files' })))
      .toEqual({ tone: 'warn', text: 'Other files are in it. Discjockey adds its folders next to them.' });
  });
  it("a problem says the engine's message", () => {
    const m = "Discjockey can't write in that folder. Choose one of your own folders.";
    expect(checkLine(chk({ usable: false, problem: 'not_writable', kind: null, message: m }))).toEqual({ tone: 'problem', text: m });
  });
  it('a problem without a message still says something', () => {
    expect(checkLine(chk({ usable: false, problem: 'not_a_folder', kind: null })).text).toMatch(/Choose another/);
  });
});

describe('needsConfirm', () => {
  it('only for other files', () => {
    expect(needsConfirm(chk({ kind: 'other_files' }))).toBe(true);
    for (const kind of ['new', 'empty', 'discjockey_library'] as const) expect(needsConfirm(chk({ kind }))).toBe(false);
    expect(needsConfirm(chk({ usable: false, problem: 'system_folder', kind: null }))).toBe(false);
    expect(needsConfirm(null)).toBe(false);
  });
});

describe('newFolderPath', () => {
  it('adds Discjockey to the parent', () => {
    expect(newFolderPath('/Users/you/Music')).toBe('/Users/you/Music/Discjockey');
    expect(newFolderPath('/Volumes/DJ SSD/')).toBe('/Volumes/DJ SSD/Discjockey');
    expect(newFolderPath('/')).toBe('/Discjockey');
  });
});

describe('parentOf', () => {
  it('drops the last part', () => {
    expect(parentOf('/Users/you/Music/Discjockey')).toBe('/Users/you/Music');
    expect(parentOf('/Volumes/DJ SSD/Discjockey')).toBe('/Volumes/DJ SSD');
    expect(parentOf('/Users/you/Music/')).toBe('/Users/you');
    expect(parentOf('/Volumes')).toBe('/');
    expect(parentOf('/')).toBe('/');
  });
});
