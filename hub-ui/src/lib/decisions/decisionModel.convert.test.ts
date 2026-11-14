// The rekordbox checks Convert to AIFF and Give it its clean name leave (issue 33 stage D §6.3): the single cards, the
// batch of converts, and what an undo asks and says.
import { describe, expect, it } from 'vitest';
import type { RekordboxCheckView, TodoItem } from '$lib/bridge/types';
import {
  NOT_IN_REKORDBOX, USB_STEP, batchCheckCard, batchListTitle, checkCard, checkRow, isOwnCheck, replacedCard, undoAsk, undoLabel,
} from './decisionModel';

const view = (extra: Partial<RekordboxCheckView> = {}): RekordboxCheckView => ({ reason: 'converted', since: '2026-11-14',
  match: null, offset_ms: null, moved: false, aligned: false, text: 'Your file is now an AIFF with a clean name and tags.',
  old_path: 'Superseded/Hard_Bounce/A - x.flac', reload_tag: true, batch: { id: 7, size: 3 }, rekordbox: { entries: 1, kept: [] },
  old_name: null, ...extra });
const check = (id: string, c: Partial<RekordboxCheckView> = {}): TodoItem => ({
  track_id: id, artist: 'A', title: id, folder: 'Hard_Bounce', duration_s: 200, status: 'lossless', quality: 'lossless',
  quality_label: 'LOSSLESS', cutoff_hz: null, source: 'qobuz', source_name: 'Qobuz', in_playlists: true, own: false,
  hidden: false, upgrade_ready: false, path: `Library/Hard_Bounce/A - ${id}.aiff`, added: null, cover_url: null,
  group: 'rekordbox_check', detail: 'an AIFF now: nothing to redo', free: false, file_state: 'here', can_undo: true, check: view(c) });
const name = (i: TodoItem) => `A – ${i.title}`;
const words = (s: { parts: { text: string }[]; note?: string }) => s.parts.map((p) => p.text).join('') + (s.note ? ` ${s.note}` : '');

describe('the single check of a Convert (converted)', () => {
  it('says its words, then only the USB step: no analyse step (the sound is the same), no Reload Tag (the text is written)', () => {
    const c = checkCard(view())!;
    expect(c.lead).toBe('Your file is now an AIFF with a clean name and tags.');
    expect(c.steps.map(words)).toEqual([words(USB_STEP)]);
    expect(c.summary).toBe('same track, cues kept');
    expect(checkCard(view({ rekordbox: { entries: 1, kept: ['title'] } }))!.hint).toBe('Kept your own title in rekordbox');
  });
  it('a file rekordbox doesn\'t have: no card of steps, the engine\'s text (first sentence + "not in your collection") stands', () => {
    expect(checkCard(view({ rekordbox: null }))).toBeNull();
    expect(checkCard(view({ rekordbox: { entries: 0, kept: [] } }))).toBeNull();
  });
  it('"Converted to AIFF" shows the new file and where the old one is, and what Undo does', () => {
    const r = replacedCard(view(), { path: 'Library/Hard_Bounce/A - x.aiff', quality: 'lossless' })!;
    expect(r.title).toBe('Converted to AIFF');
    expect(r.rows.map((x) => [x.name, x.where])).toEqual([['New AIFF with a clean name', 'in Library/Hard_Bounce'],
      ['Your old file', 'in Superseded/Hard_Bounce']]);
    expect(r.undo).toBe('Undo points rekordbox back at your old file.');
    expect(replacedCard(view({ rekordbox: null, old_path: null }), { path: null, quality: 'lossless' })!.undo)
      .toBe('Undo puts your old file back as it was.');
  });
});

describe('the single check of a clean name (renamed)', () => {
  it('has no steps at all: its words are the note', () => {
    expect(checkCard(view({ reason: 'renamed' }))).toBeNull();
    expect([isOwnCheck(view()), isOwnCheck(view({ reason: 'renamed' })), isOwnCheck(view({ reason: 'swapped' })), isOwnCheck(undefined)])
      .toEqual([true, true, false, false]);
  });
  it('"Given its clean name" shows the name now and the name before', () => {
    const r = replacedCard(view({ reason: 'renamed', old_path: null, old_name: 'A_-_x.aiff' }), { path: 'Library/Hard_Bounce/A - x.aiff', quality: 'lossless' })!;
    expect(r.title).toBe('Given its clean name');
    expect(r.rows.map((x) => [x.name, x.where])).toEqual([['A - x.aiff', 'its name now'], ['A_-_x.aiff', 'its name before']]);
    expect(r.undo).toBe('Undo gives it its old name and points rekordbox back at it.');
  });
});

describe('a batch of converts', () => {
  it('has the USB step once, for the tracks rekordbox has: nothing else, nothing at all for clean names or files it hasn\'t', () => {
    const three = [check('a'), check('b'), check('c')];
    const c = batchCheckCard(three, name)!;
    expect(c.summary).toBe('same tracks, cues kept');
    expect(c.steps.map(words)).toEqual(['On a USB stick? The stick still plays the old files. Rebuild the stick in rekordbox before your next gig']);
    expect(batchCheckCard([check('a')], name)!.steps.map(words)).toEqual([words(USB_STEP)]);
    expect(batchCheckCard([check('a', { reason: 'renamed' }), check('b', { reason: 'renamed' })], name)).toBeNull();
    expect(batchCheckCard([check('a', { rekordbox: null })], name)).toBeNull();
    expect(batchCheckCard([check('a', { reason: 'renamed' }), check('b')], name)!.steps).toHaveLength(1);
  });
  it('mixed with an upgrade it keeps the upgrade\'s steps (analyse again for it alone)', () => {
    const c = batchCheckCard([check('a'), check('u', { reason: 'repointed', reload_tag: false })], name)!;
    expect(c.steps.map(words)).toEqual(['Analyse it again, so the waveform shows the full sound (lock the beatgrid first if you set it by hand)',
      'On a USB stick? The stick still plays the old files. Rebuild the stick in rekordbox before your next gig']);
  });
  it('lists each track with its new name, and says a file rekordbox doesn\'t have', () => {
    const r = checkRow(check('a'), 'A – a', 'file');
    expect(r.sub).toBe('A - a.aiff');
    expect(checkRow(check('b', { rekordbox: null }), 'A – b', 'file').notes).toEqual([NOT_IN_REKORDBOX]);
    expect(checkRow(check('c', { reason: 'renamed', rekordbox: null }), 'A – c', 'file').notes).toEqual([NOT_IN_REKORDBOX]);
    expect(r.notes).toEqual([]);
  });
  it('its list is titled by what the checks are', () => {
    const c = (reason: string) => ({ check: view({ reason }) });
    expect([batchListTitle([c('converted'), c('converted')]), batchListTitle([c('renamed')]), batchListTitle([c('converted'), c('renamed')]),
      batchListTitle([c('swapped'), c('repointed')]), batchListTitle([c('converted'), c('swapped')])])
      .toEqual(['Made AIFF', 'Clean names', 'Changed', 'Upgraded', 'Changed']);
  });
});

describe('Undo for a Convert or a clean name', () => {
  it('asks and labels in its own words; an upgrade keeps its replace question', () => {
    expect(undoAsk([view()])).toMatchObject({ title: 'Undo the conversion?', confirmLabel: 'Undo the conversion' });
    expect(undoAsk([view({ reason: 'renamed' })])).toMatchObject({ title: 'Undo the clean name?', confirmLabel: 'Undo the clean name' });
    expect(undoAsk([view(), view(), view()])).toMatchObject({ title: 'Undo 3 conversions?', confirmLabel: 'Undo 3' });
    expect(undoAsk([view({ reason: 'renamed' }), view({ reason: 'renamed' })]).title).toBe('Undo 2 clean names?');
    expect(undoAsk([view(), view({ reason: 'renamed' })])).toMatchObject({ title: 'Undo 2 changes?',
      body: 'Your old files and names go back where they were.' });
    expect(undoAsk([view({ reason: 'swapped' })])).toMatchObject({ title: 'Undo the replace?',
      body: 'Your old audio goes back in the file. The new version waits in Upgrades ready again.' });
    expect(undoAsk([view({ reason: 'repointed' }), view({ reason: 'repointed' })]).title).toBe('Undo 2 replaces?');
    expect([undoLabel(view()), undoLabel(view({ reason: 'renamed' })), undoLabel(view({ reason: 'repointed' })), undoLabel(undefined)])
      .toEqual(['Undo the conversion', 'Undo the clean name', 'Undo the replace', 'Undo the replace']);
  });
});
