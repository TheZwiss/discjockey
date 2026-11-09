// The rekordbox checks Same track leaves (plan issue 33 stage B §6.4): the single `repointed` card, the batch card's
// steps and rows, several checks selected, an undo of several, and the Library finding a batch's track.
import { describe, expect, it } from 'vitest';
import type { BatchCheckItem, RekordboxCheckView, TodoItem, TrackDetail } from '$lib/bridge/types';
import {
  NOT_IN_REKORDBOX, USB_STEP, batchCheckCard, batchRowName, batchRowSub, checkCard, checkRow, checkTracks, checksTitle,
  decisionFor, inRekordbox, keptLine, replacedCard, tracksSummary, undoAllLabel, undoFoot, undoManyConfirm, undoManyLabel, undoProblem,
  undoneToast,
} from './decisionModel';

const view = (extra: Partial<RekordboxCheckView> = {}): RekordboxCheckView => ({ reason: 'repointed', since: '2026-11-08',
  match: 'exact', offset_ms: 0, moved: false, aligned: true, text: 'the engine text', old_path: 'Superseded/Hard_Bounce/A - x.mp3',
  reload_tag: false, batch: { id: 7, size: 3 }, rekordbox: { entries: 1, kept: [] }, ...extra });
const check = (id: string, c: Partial<RekordboxCheckView> = {}, extra: Partial<TodoItem> = {}): TodoItem => ({
  track_id: id, artist: 'A', title: id, folder: 'Hard_Bounce', duration_s: 200, status: 'lossless', quality: 'lossless',
  quality_label: 'LOSSLESS', cutoff_hz: null, source: 'qobuz', source_name: 'Qobuz', in_playlists: true, own: false,
  hidden: false, upgrade_ready: false, path: `Library/Hard_Bounce/A - ${id}.aiff`, added: null, cover_url: null,
  group: 'rekordbox_check', detail: 'analyse again', free: false, file_state: 'here', can_undo: true, check: view(c), ...extra });
const name = (i: TodoItem) => `A – ${i.title}`;
const words = (s: { parts: { text: string }[]; note?: string }) => s.parts.map((p) => p.text).join('') + (s.note ? ` ${s.note}` : '');

describe('the single check Same track leaves (repointed)', () => {
  it('keeps the card: analyse again, the USB stick, "Replaced with lossless" with the new AIFF and the old file', () => {
    const c = checkCard(view())!;
    expect(c.summary).toBe('same track, cues kept');
    expect(c.steps.map(words)).toEqual(['Analyse it again, so the waveform shows the full sound (lock the beatgrid first if you set it by hand)',
      words(USB_STEP)]);
    expect(c.hint).toBeNull();
    const r = replacedCard(view(), { path: 'Library/Hard_Bounce/A - x.aiff', quality: 'lossless' })!;
    expect(r.rows.map((x) => [x.name, x.where])).toEqual([['New AIFF, lossless', 'in Library/Hard_Bounce'],
      ['Your old file', 'in Superseded/Hard_Bounce']]);
    expect(r.undo).toBe('Undo points rekordbox back at your old file.');
  });
  it('Reload Tag only where Discjockey couldn\'t write the text; a kept edit is its hint', () => {
    expect(checkCard(view({ reload_tag: true }))!.steps[0].parts.map((p) => p.text).join('')).toBe('Right-click the track › Reload Tag');
    expect(checkCard(view({ rekordbox: { entries: 1, kept: ['title'] } }))!.hint).toBe('Kept your own title in rekordbox');
  });
  it('a new AIFF rekordbox doesn\'t have: no steps, the engine\'s text says so', () => {
    expect(checkCard(view({ rekordbox: null }))).toBeNull();
    expect(checkCard(view({ rekordbox: { entries: 0, kept: [] } }))).toBeNull();
    expect(replacedCard(view({ rekordbox: null }), { path: 'Library/x/A.aiff', quality: 'lossless' })!.undo)
      .toBe('Undo puts your old file back as it was.');
  });
  it('a swap Discjockey wrote rekordbox for drops Reload Tag; an older swap keeps it', () => {
    const swapped = (reload_tag: boolean) => checkCard(view({ reason: 'swapped', reload_tag, rekordbox: null }))!.steps.length;
    expect([swapped(false), swapped(true)]).toEqual([1, 2]);
  });
  it('who is in rekordbox: a record of what was written, else only an older swap', () => {
    expect(inRekordbox(view())).toBe(true);
    expect(inRekordbox(view({ rekordbox: { entries: 0, kept: [] } }))).toBe(false);
    expect(inRekordbox(view({ rekordbox: null }))).toBe(false);
    expect(inRekordbox(view({ reason: 'swapped', rekordbox: null }))).toBe(true);
    expect(inRekordbox(undefined)).toBe(false);
  });
  it('kept fields read as one sentence', () => {
    expect(keptLine([])).toBe('');
    expect(keptLine(['artist', 'comment'])).toBe('Kept your own artist and comment in rekordbox');
    expect(keptLine(['title', 'artist', 'album'])).toBe('Kept your own title, artist and album in rekordbox');
  });
});

describe('the batch card', () => {
  it('names the row by its size and day', () => {
    expect(batchRowName(3)).toBe('3 tracks upgraded');
    expect(batchRowSub('2026-11-08', '2026-11-08')).toBe('today · Same track');
    expect(batchRowSub('2026-11-01', '2026-11-08')).toMatch(/^1\sNov · Same track$/);
    expect(batchRowSub(null, '2026-11-08')).toBe('Same track');
  });
  it('steps for all: analyse them again, the USB stick; no Reload Tag when every text was written', () => {
    const c = batchCheckCard([check('a'), check('b')], name)!;
    expect(c.summary).toBe('same tracks, cues kept');
    expect(c.steps.map(words)).toEqual([
      'Analyse them again, so the waveform shows the full sound (lock the beatgrid first if you set it by hand)',
      'On a USB stick? The stick still plays the old files. Rebuild the stick in rekordbox before your next gig']);
  });
  it('Reload Tag for the tracks whose text wasn\'t written, by name; missing swaps first', () => {
    const c = batchCheckCard([check('a', { reload_tag: true }), check('b'), check('c', { reason: 'swapped', moved: true }),
      check('d', { reload_tag: true })], name)!;
    expect(c.steps[0].list).toEqual(['A – c']);
    expect(words(c.steps[0])).toBe('This one shows as missing: Auto Relocate finds it by its name, cues and all');
    expect(c.steps[1].parts.some((p) => p.strong && p.text === 'Reload Tag')).toBe(true);
    expect(c.steps[1].list).toEqual(['A – a', 'A – d']);
    expect(c.steps[1].note).toContain("don't select all");
  });
  it('only the tracks rekordbox has get steps: one of them says "it", none is no card', () => {
    const one = batchCheckCard([check('a'), check('b', { rekordbox: { entries: 0, kept: [] } })], name)!;
    expect(one.summary).toBe('same track, cues kept');
    expect(words(one.steps[0])).toMatch(/^Analyse it again/);
    expect(one.steps[1]).toEqual(USB_STEP);
    expect(batchCheckCard([check('a', { rekordbox: null })], name)).toBeNull();
  });
  it('a row per track: the new file, what was kept, a file rekordbox doesn\'t have, whether it can be undone', () => {
    expect(checkRow(check('a', { rekordbox: { entries: 1, kept: ['title'] } }), 'A – a', 'file'))
      .toEqual({ track_id: 'a', name: 'A – a', sub: 'A - a.aiff', notes: ['Kept your own title in rekordbox'], can_undo: true,
        cover_url: null });
    expect(checkRow(check('b', { rekordbox: { entries: 0, kept: [] } }, { can_undo: false }), 'A – b', 'file'))
      .toMatchObject({ notes: [NOT_IN_REKORDBOX], can_undo: false });
    // several checks selected: the row says what is left to do, the list row's own line
    expect(checkRow(check('c'), 'A – c', 'detail').sub).toBe('analyse again');
  });
});

describe('several checks selected, and their undo', () => {
  const batch: BatchCheckItem = { ...check('batch:7', {}, { key: 'batch:7' }), group: 'rekordbox_check', key: 'batch:7',
    batch: { id: 7, size: 2, started: '2026-11-08', tracks: [check('b1'), check('b2')] } };
  it('a batch stands for its tracks', () => {
    expect(checkTracks([batch, check('c1')]).map((t) => t.track_id)).toEqual(['b1', 'b2', 'c1']);
  });
  it('the words: title, Undo all n / Undo n, the question', () => {
    expect(checksTitle(4)).toBe('4 checks selected');
    expect([undoAllLabel(3), undoManyLabel(2)]).toEqual(['Undo all 3', 'Undo 2']);
    expect(undoManyConfirm(3)).toMatchObject({ title: 'Undo 3 replaces?', confirmLabel: 'Undo 3',
      body: 'Your old files go back where they were. The new versions wait in Upgrades ready again.' });
    expect(undoManyConfirm(1).title).toBe('Undo 1 replace?');
  });
  it('the list counts its tracks next to the checks selected (a batch among them has several)', () => {
    expect([tracksSummary(1), tracksSummary(5)]).toEqual(['1 track', '5 tracks']);
    expect(checksTitle(1)).toBe('1 check selected');
    expect(checksTitle(2)).toBe('2 checks selected');
    expect(checkTracks([batch, check('c1')])).toHaveLength(3);
  });
  it('the foot: Undo all n only when every track can go, else Undo n and how many cannot', () => {
    const all = undoFoot([check('a'), check('b')]);
    expect([all.ids, all.label, all.cant]).toEqual([['a', 'b'], 'Undo all 2', null]);
    const some = undoFoot([check('a'), check('b', {}, { can_undo: false }), check('c', {}, { can_undo: false })]);
    expect([some.ids, some.label, some.cant]).toEqual([['a'], 'Undo 1', "2 can't be undone"]);
    // a track just refused is not offered again; its row says why, so the muted line doesn't count it
    const refused = undoFoot([check('a'), check('b')], { b: 'the file changed' });
    expect([refused.ids, refused.label, refused.cant]).toEqual([['a'], 'Undo 1', null]);
    expect(undoFoot([check('a', {}, { can_undo: false })]).ids).toEqual([]);
  });
  it('the toast counts what came back', () => {
    expect([undoneToast(1), undoneToast(2)]).toEqual(['Upgrade undone. Your old file is back.',
      '2 upgrades undone. Your old files are back.']);
  });
  it('an undo that put everything back says nothing', () => {
    expect(undoProblem({ ok: true, result: { batch: null, total: 2, undone: 2, refused: 0, failed: 0, recovered: [],
      results: [{ track: 'a', state: 'undone', reason: null, message: 'back' }] } })).toBeNull();
  });
  it('refused tracks: each row gets its reason, one line counts them', () => {
    const p = undoProblem({ ok: true, result: { batch: null, total: 3, undone: 2, refused: 1, failed: 0, recovered: [],
      results: [{ track: 'a', state: 'undone', reason: null, message: '' },
        { track: 'b', state: 'refused', reason: 'changed', message: 'this track was changed in rekordbox since' }] } })!;
    expect(p).toEqual({ line: '1 not undone: its row says why', rows: { b: 'This track was changed in rekordbox since' } });
  });
  it('rekordbox open: design §8\'s words, nothing per row to say', () => {
    const msg = 'Quit rekordbox to undo: Discjockey points your rekordbox track back at your old file only while rekordbox is closed.';
    expect(undoProblem({ ok: false, kind: 'rekordbox_open', message: msg, result: { batch: null, total: 1, undone: 0,
      refused: 0, failed: 0, recovered: [], results: [{ track: 'a', state: 'waiting', reason: 'rekordbox_open', message: '' }] } }))
      .toEqual({ line: msg, rows: {} });
    // a refusal before the job (busy): its own words
    expect(undoProblem({ ok: false, kind: 'busy', message: 'Something else is changing your library.' })!.line)
      .toBe('Something else is changing your library.');
  });
  it('the Library finds a track a batch upgraded: its own single check', () => {
    const t = { track_id: 'b2', path: null, upgrade: null } as unknown as TrackDetail;
    expect(decisionFor([batch], t)).toEqual({ kind: 'check', item: batch.batch.tracks[1] });
  });
});
