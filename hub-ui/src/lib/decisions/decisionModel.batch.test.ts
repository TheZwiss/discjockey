// Several upgrades at once and the single panel's Same track for any format (plan issue 33 stage B §6.2, §6.3): the
// words and choices of the selection panel, the progress rows, how a batch ended, and the "In rekordbox" card of one
// track that isn't an AIFF, with rekordbox unreadable, or with no rekordbox on this Mac.
import { describe, expect, it } from 'vitest';
import type { AiffBatchResult, ItemResult, TodoItem, Upgrade } from '$lib/bridge/types';
import {
  QUIT_REKORDBOX, batchEnd, canTryAgain, defaultWay, discardConfirm, discardLabel, endGroups, endNote, endRows, endWords,
  focusAfterDrop, focusAfterRowGone, goes, panelFocus, progressRows, replaceManyLabel, resumeLabel, runRow, sameTrackWhy, selectedTitle, selectionWays, upgradeAllLabel,
  upgradeWays, type RunRow,
} from './decisionModel';

const item = (id: string, same_track: string | null, extra: Partial<TodoItem> = {}): TodoItem => ({
  track_id: id, artist: 'A', title: id, folder: 'Hard_Bounce', duration_s: 200, status: 'not_lossless', quality: 'weak',
  quality_label: '16.0 kHz', cutoff_hz: 16000, source: 'youtube', source_name: 'YouTube', in_playlists: true, own: false,
  hidden: false, upgrade_ready: true, path: `Library/Hard_Bounce/A - ${id}.aiff`, added: null, cover_url: null,
  group: 'upgrade_ready', detail: 'Lossless ready · cues can stay', free: false, file_state: 'here', same_track, ...extra });
const mp3 = (id: string, same: string | null = null) => item(id, same, { path: `Library/Hard_Bounce/A - ${id}.mp3` });

describe('several upgrades selected', () => {
  it('counts Same track, a choice and something else (the before-line) in Same track\'s outcomes', () => {
    const w = selectionWays([item('a', null), mp3('b'), item('c', 'needs_choice'), item('d', 'away')]);
    expect([w.n, w.m, w.k, w.choice, w.way]).toEqual([2, 1, 1, true, 'swap']);
    expect(w.options.map((o) => o.name)).toEqual(['Same track · 2', 'New track · 3']);
    expect(w.options[0].outcomes!.map((o) => [o.tone, o.text])).toEqual([
      ['kept', '2 keep their cues, playlists and history'], ['file', "Files that aren't AIFF become AIFF files"],
      ['step', QUIT_REKORDBOX], ['step', '1 needs your choice and stays'], ['step', '1 waits for something else']]);
    expect(w.count).toEqual({ swap: 2, add_new: 3 });
  });
  it('leaves out the AIFF line when every file going is an AIFF, and the stay lines at zero', () => {
    const w = selectionWays([item('a', null), item('b', null)]);
    expect(w.options[0].outcomes!.map((o) => o.text)).toEqual(['2 keep their cues, playlists and history', QUIT_REKORDBOX]);
    expect(w.options[1].outcomes!.map((o) => o.text)).toEqual(['rekordbox lists them as new tracks',
      'Relocate your old tracks: cues fit']);
  });
  it('one going says it in the singular', () => {
    const w = selectionWays([item('a', null), item('b', 'needs_choice'), item('c', 'needs_choice')]);
    expect(w.options[0].outcomes![0].text).toBe('1 keeps its cues, playlists and history');
    expect(w.options[0].outcomes!.at(-1)!.text).toBe('2 need your choice and stay');
    expect(w.options[1].outcomes![1].text).toBe('2 may be another edit: listen first');
  });
  it('with none for Same track there is no choice: new tracks, and why', () => {
    const all = selectionWays([item('a', 'needs_choice'), item('b', 'needs_choice')]);
    expect([all.choice, all.way, all.reason]).toEqual([false, 'add_new', 'Same track needs the same edit']);
    const mixed = selectionWays([item('a', 'needs_choice'), item('b', 'not_analysed')]);
    expect(mixed.reason).toBe('None of these can stay the same track: each row says why');
  });
  it('a row goes by the way picked; nothing to replace or no file keeps it out of both', () => {
    expect(goes(item('a', null), 'swap')).toBe(true);
    expect(goes(item('a', 'needs_choice'), 'swap')).toBe(false);
    expect(goes(item('a', 'needs_choice'), 'add_new')).toBe(true);
    expect(goes(item('a', 'not_analysed'), 'add_new')).toBe(true);
    for (const r of ['no_upgrade', 'file_missing', 'away']) expect(goes(item('a', r), 'add_new')).toBe(false);
  });
  it('says how each row goes, or why not, in a few words', () => {
    expect(sameTrackWhy(null)).toBe('Same track');
    expect(sameTrackWhy('needs_choice')).toBe('needs your choice');
    expect(sameTrackWhy('away')).toBe('drive not connected');
    expect(sameTrackWhy('something_new')).toBe("can't be upgraded right now");
  });
  it('names the buttons by the result and the count', () => {
    expect(replaceManyLabel(3, [item('a', null)])).toBe('Replace 3 with lossless');
    expect(replaceManyLabel(2, [item('a', null), item('b', null, { detail: '320 kbps ready · cues can stay' })]))
      .toBe('Replace 2 with the better versions');
    expect(discardLabel(3)).toBe('Discard 3 new versions');
    expect(discardLabel(1)).toBe('Discard 1 new version');
    expect(discardConfirm(4)).toMatchObject({ title: 'Throw away 4 new versions?',
      body: 'Your current files stay. These versions are not offered again.' });
    expect([selectedTitle(3), resumeLabel(2), upgradeAllLabel(12)]).toEqual(['3 upgrades selected', 'Resume · 2 left',
      'Upgrade all · 12']);
  });
});

describe('a batch running and its end', () => {
  const rows: RunRow[] = [runRow(item('a', null), 'A – a'), runRow(item('b', null), 'A – b')];
  const res = (track: string, state: ItemResult['state'], extra: Partial<ItemResult> = {}): ItemResult =>
    ({ track, action: 'same_track', state, reason: null, message: null, path: null, rekordbox: null, ...extra });
  const result = (results: ItemResult[], extra: Partial<AiffBatchResult> = {}): AiffBatchResult => ({ batch: 7,
    state: 'done', stop_reason: null, total: results.length, done: 0, skipped: 0, failed: 0, results, backup: null,
    recovered: [], ...extra });

  it('marks the track in work, the one before it passed, and adds a track it didn\'t know', () => {
    let r = progressRows(rows, { track_id: 'a', name: 'A - a' });
    expect(r.map((x) => x.state)).toEqual(['now', 'waiting']);
    r = progressRows(r, { track_id: 'b', name: 'A - b' });
    expect(r.map((x) => x.state)).toEqual(['handled', 'now']);
    r = progressRows(r, { track_id: null, name: null });
    expect(r.map((x) => x.state)).toEqual(['handled', 'handled']);
    const resumed = progressRows([], { track_id: 'z', name: 'Some One - Song' });
    expect(resumed).toEqual([{ track_id: 'z', name: 'Some One – Song', sub: '', cover_url: null, state: 'now', text: null }]);
  });
  it('the end gives each track its answer, the engine\'s words with a capital', () => {
    const r = endRows(rows, [res('a', 'done'), res('b', 'skipped', { reason: 'timing', message: 'analyse it again' })]);
    expect(r.map((x) => [x.state, x.text])).toEqual([['done', null], ['skipped', 'Analyse it again']]);
    expect(endRows(rows, [res('a', 'done'), res('b', 'planned')]).map((x) => x.state)).toEqual(['done', 'waiting']);
    // no answer per track: nothing is claimed done
    expect(endRows([{ ...rows[0], state: 'now' }], []).map((x) => x.state)).toEqual(['handled']);
    expect(endGroups(endRows(rows, [res('a', 'skipped'), res('b', 'planned')])).left.map((x) => x.track_id)).toEqual(['b']);
  });
  it('the end adds a row for every result track without one, named by the lookup, else by its id', () => {
    const names: Record<string, string> = { c: 'Some One – Song' };
    const r = endRows([rows[0]], [res('a', 'done'), res('c', 'skipped', { reason: 'timing', message: 'analyse it again' }),
      res('d', 'planned')], (id) => names[id] ?? null);
    expect(r.map((x) => [x.track_id, x.name === x.track_id ? 'id' : x.name, x.state, x.text])).toEqual([
      ['a', rows[0].name, 'done', null], ['c', 'Some One – Song', 'skipped', 'Analyse it again'], ['d', 'id', 'waiting', null]]);
    // a Resume starts with no rows at all
    expect(endRows([], [res('a', 'done'), res('b', 'done')]).map((x) => [x.track_id, x.state])).toEqual([['a', 'done'], ['b', 'done']]);
  });
  it('done, with its words', () => {
    const e = batchEnd('swap', { ok: true, result: result([res('a', 'done'), res('b', 'done')]) });
    expect([e.kind, e.done, e.resume, endNote(e), canTryAgain(e)]).toEqual(['done', 2, null, null, false]);
    expect(endWords(e)).toEqual({ unit: 'tracks', label: 'upgraded, your cues stayed' });
    expect(endWords({ mode: 'add_new', done: 1 })).toEqual({ unit: 'track', label: 'added as new' });
    expect(endWords({ mode: 'discard', done: 2 })).toEqual({ unit: 'new versions', label: 'discarded' });
  });
  it('stopped by Stop: the line and Resume with the tracks left', () => {
    const e = batchEnd('swap', { ok: false, kind: 'stopped', message: 'Stopped after 1 of 3.',
      result: result([res('a', 'done'), res('b', 'planned'), res('c', 'planned')], { state: 'stopped', stop_reason: 'stop' }) });
    expect([e.kind, e.done, e.total, e.resume]).toEqual(['stopped', 1, 3, { batch_id: 7, left: 2 }]);
    expect(endNote(e)).toEqual({ tone: 'info', text: 'Stopped after 1 of 3.' });
    expect(canTryAgain(e)).toBe(false);
  });
  it('rekordbox open: before anything ran, and mid-way (design §8)', () => {
    const start = batchEnd('swap', { ok: false, kind: 'rekordbox_open', message: '',
      result: result([res('a', 'planned'), res('b', 'planned')], { state: 'stopped', stop_reason: 'rekordbox_open' }) });
    expect(endNote(start)!.text).toBe('rekordbox is open. Quit rekordbox, then try again. Discjockey changes your rekordbox tracks only while rekordbox is closed.');
    expect(start.resume).toEqual({ batch_id: 7, left: 2 });
    const mid = batchEnd('swap', { ok: false, kind: 'rekordbox_open', message: '',
      result: result([res('a', 'done'), res('b', 'planned')], { state: 'stopped', stop_reason: 'rekordbox_open' }) });
    expect(endNote(mid)).toEqual({ tone: 'warn',
      text: 'rekordbox was opened, so Discjockey stopped after 1 of 2. Quit rekordbox and press Resume.' });
    // a batch of one closed before it ran: no Resume, so Try again
    const one = batchEnd('swap', { ok: false, kind: 'rekordbox_open', message: '',
      result: result([res('a', 'skipped', { reason: 'rekordbox_open' })], { state: 'done' }) });
    expect([one.resume, canTryAgain(one)]).toEqual([null, true]);
  });
  it('refused and busy say why; refused offers nothing to try again', () => {
    const r = batchEnd('swap', { ok: false, kind: 'refused', message: 'None of these can be upgraded right now.',
      result: result([res('a', 'skipped')]) });
    expect([r.kind, canTryAgain(r), endNote(r)!.text]).toEqual(['refused', false, 'None of these can be upgraded right now.']);
    const b = batchEnd('swap', { ok: false, kind: 'busy', message: '', result: null });
    expect(endNote(b)!.text).toBe('Discjockey is already changing your rekordbox library in another window or the Terminal.');
    expect(batchEnd('swap', { ok: false, kind: 'crashed', message: 'x' }).kind).toBe('failed');
  });
});

describe('the single panel: Same track for any format (§6.3)', () => {
  const align = { drift_ms: 0, offset_ms: 0, offset_samples: 0, result: 'exact', text: '' };
  const upgrade = (o: Partial<Upgrade> = {}): Upgrade => ({ file: 'x', source: 'qobuz', source_name: 'Qobuz', source_id: '1',
    found: '2026-11-08', what: 'lossless version', quality_line: '', format_line: 'FLAC · lossless', alignment: align,
    cue_text: '', swap_safe: true, swap_possible: true, why_not: null, swap_how: 'in_place',
    rekordbox: { state: 'ready', running: false }, auto_refused: null, audio_url: null, ...o });
  it('an AIFF in place: as before, with the quit tip under the choice', () => {
    const w = upgradeWays(upgrade(), true);
    expect([w.choice, w.way, w.tip]).toEqual([true, 'swap', QUIT_REKORDBOX]);
    expect(w.options[0].outcomes).toEqual([{ tone: 'kept', text: 'Your track keeps its cues' }]);
  });
  it('a file that isn\'t AIFF: Same track recommended with design §8\'s three outcomes, no separate tip', () => {
    const w = upgradeWays(upgrade({ swap_how: 'new_aiff' }), true);
    expect([w.choice, w.tip]).toEqual([true, null]);
    expect(w.options[0].outcomes!.map((o) => o.text)).toEqual(['Your track keeps its cues, playlists and history',
      'Becomes an AIFF file', 'Quit rekordbox before you replace']);
  });
  it('rekordbox unreadable: no choice, a new track, and why', () => {
    const w = upgradeWays(upgrade({ swap_how: 'new_aiff', swap_possible: false, why_not: 'rekordbox_unreadable',
      rekordbox: { state: 'unreadable', running: false } }), false);
    expect([w.choice, w.way, w.reason, w.tip]).toEqual([false, 'add_new',
      'Same track needs a rekordbox library Discjockey can open', null]);
  });
  it('no rekordbox on this Mac: no choice, the clean AIFF, and Replace runs Same track', () => {
    const up = upgrade({ swap_how: 'new_aiff', rekordbox: { state: 'none', running: false } });
    const w = upgradeWays(up, true);
    expect([w.choice, w.way, w.reason]).toEqual([false, 'swap', 'No rekordbox on this Mac: the new file is a new track']);
    expect(w.fixed.map((o) => o.text)).toEqual(['Becomes an AIFF file']);
    expect(defaultWay(up, true)).toBe('swap');
  });
  it('another reason says itself; New track needs no tip', () => {
    const w = upgradeWays(upgrade({ swap_possible: false, why_not: 'not_analysed' }), false);
    expect([w.reason, w.tip]).toEqual(['Same track needs the track analysed in rekordbox first', null]);
    expect(defaultWay(null, false)).toBe('add_new');
  });
});

describe('where focus goes when a panel changes under it', () => {
  const end = (over: object = {}) => ({ resume: null, ...over });
  it('Stop while a batch runs, then the filled button of its end', () => {
    expect(panelFocus(null)).toBeNull();
    expect(panelFocus({ phase: 'running', end: null, again: null })).toBe('batch-stop');
    expect(panelFocus({ phase: 'ended', end: end({ resume: { batch_id: 1, left: 2 } }), again: null })).toBe('batch-resume');
    expect(panelFocus({ phase: 'ended', end: end(), again: () => {} })).toBe('batch-again');
    expect(panelFocus({ phase: 'ended', end: end(), again: null })).toBe('batch-close');
  });
  it('after a ✕ the row now in its place, the last row when it was last, none when none is left', () => {
    expect(focusAfterDrop(['a', 'b', 'c'], 0)).toBe('b');
    expect(focusAfterDrop(['a', 'b', 'c'], 1)).toBe('c');
    expect(focusAfterDrop(['a', 'b', 'c'], 2)).toBe('b');
    expect(focusAfterDrop(['a'], 0)).toBeNull();
  });
  it('after a row is undone the next undo, else the one before it, else nothing (Done)', () => {
    const all = new Set(['a', 'b', 'c']);
    expect(focusAfterRowGone(['a', 'b', 'c'], ['a', 'c'], all)).toBe('c');
    expect(focusAfterRowGone(['a', 'b', 'c'], ['a', 'b'], all)).toBe('b');
    expect(focusAfterRowGone(['a', 'b', 'c'], ['a', 'c'], new Set(['a']))).toBe('a');
    expect(focusAfterRowGone(['a', 'b'], ['a'], new Set())).toBeNull();
    expect(focusAfterRowGone(['a', 'b'], ['a', 'b'], all)).toBeNull();
  });
});
