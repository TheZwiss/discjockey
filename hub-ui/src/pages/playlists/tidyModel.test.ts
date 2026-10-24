import { describe, expect, it } from 'vitest';
import type { BatchResult, RenameOffer, TidyRow, UndoPreview } from '$lib/bridge/types';
import {
  carryOver, confirmLabel, countLine, fileCountText, folderName, folderRows, goBackText, groupState, groups, initialQuestion, initialTicks,
  itemOfRow, movesOf, notMovedText, offerDetail, outcomeOf, pairsOf, problemToTell, progressDone, progressStart, progressStep,
  progressTotal, renameDetail, resultUndo, saveCount, saveFileCount, saveFiles, saveHeadline, saveItems, saveMoving, skipTone,
  tickedRows, tickedText, toggleGroup, toggleRename, toggleTick, undoItems, undoLabel, undoRowName, visibleRows,
} from './tidyModel';

let n = 0;
function row(from: string, to: string, extra: Partial<TidyRow> = {}): TidyRow {
  n += 1;
  return {
    track_id: `t${n}`, artist: 'A', title: `T${n}`, folder: to, duration_s: 200, status: 'lossless', quality: 'lossless',
    quality_label: 'Lossless', cutoff_hz: null, source: null, source_name: null, in_playlists: true, hidden: false,
    upgrade_ready: false, path: `Library/${from}/A - T${n}.aiff`, added: null, cover_url: null,
    file_id: n, from, to, from_path: `Library/${from}/A - T${n}.aiff`, placed_by: 'app', ticked: true, yours: false,
    skip: null, by_rename: null, ...extra,
  };
}
const yours = (from: string, to: string, extra: Partial<TidyRow> = {}) =>
  row(from, to, { placed_by: 'user', ticked: false, yours: true, ...extra });
const skipped = (from: string, to: string) =>
  row(from, to, { ticked: false, skip: { reason: 'offline', text: 'Offline, skipped' } });

describe('words', () => {
  it('counts files the I6 way, one and many', () => {
    expect(saveHeadline(1)).toBe('1 file would sit in a different folder');
    expect(saveHeadline(7)).toBe('7 files would sit in a different folder');
    expect(confirmLabel(1)).toBe('Move 1 file');
    expect(confirmLabel(4)).toBe('Move 4 files');
    expect(undoLabel(2)).toBe('Move 2 files back');
    expect(undoLabel(1)).toBe('Move 1 file back');
    expect(renameDetail(7)).toBe('One folder move instead of 7 file moves.');
    expect(renameDetail(1)).toBe('One folder move instead of 1 file move.');
    expect(tickedText(4, 6)).toBe('4 of 6 ticked');
    expect(goBackText(2, 3)).toBe('2 of 3 go back');
    expect(notMovedText(2)).toBe('2 not moved:');
    expect(folderName('')).toBe('Library');
    expect(folderName('Bouncy')).toBe('Bouncy');
  });
});

describe('groups and ticks', () => {
  const a = row('Powertrance', 'Hard_Bounce');
  const b = row('Bouncy', 'Hard_Bounce', { ticked: false });   // the backend may send an app row unticked
  const y1 = yours('Elsewhere', 'Bouncy');
  const y2 = yours('Elsewhere/not_lossless', 'Hard_Bounce/not_lossless');
  const s = skipped('Bouncy', 'Powertrance');
  const ys = yours('Elsewhere', 'Bouncy', { skip: { reason: 'name_taken', text: 'A file with this name is already in Bouncy' } });
  const rows = [a, y1, s, b, y2, ys];

  it('puts each row in one group: default moves, yours, can\'t move (a skipped row of yours can\'t move)', () => {
    const g = groups(rows);
    expect(g.main).toEqual([a, b]);
    expect(g.yours).toEqual([y1, y2]);
    expect(g.skipped).toEqual([s, ys]);
  });
  it('starts from the backend\'s ticks and never ticks a skipped row', () => {
    expect([...initialTicks([...rows, { ...s, ticked: true }])]).toEqual([a.file_id]);
    const t = initialTicks(rows);
    expect(toggleTick(t, s).has(s.file_id)).toBe(false);
    expect(toggleTick(t, y1).has(y1.file_id)).toBe(true);
    expect(toggleTick(toggleTick(t, a), a).has(a.file_id)).toBe(true);
  });
  it('the group control ticks all, shows "some" when only some are, and unticks all when all are', () => {
    const g = groups(rows).yours;
    let t: Set<number> = initialTicks(rows);
    expect(groupState(t, g)).toBe('none');
    t = toggleTick(t, y1);
    expect(groupState(t, g)).toBe('some');
    t = toggleGroup(t, g);
    expect(groupState(t, g)).toBe('all');
    expect(t.has(a.file_id)).toBe(true);
    t = toggleGroup(t, g);
    expect(groupState(t, g)).toBe('none');
    expect(t.has(a.file_id)).toBe(true);
  });
  it('sends the ticked rows in list order, defaults first, as [file_id, from_path]', () => {
    const t = toggleTick(toggleTick(initialTicks(rows), y2), b);
    expect(tickedRows(rows, t)).toEqual([a, b, y2]);
    expect(movesOf(rows, t)).toEqual([[a.file_id, a.from_path], [b.file_id, b.from_path], [y2.file_id, y2.from_path]]);
  });
});

describe('the count line C', () => {
  it('pairs rows by from and to, in order of appearance', () => {
    expect(pairsOf([{ from: 'A', to: 'B' }, { from: 'C', to: 'B' }, { from: 'A', to: 'B' }, { from: 'D', to: 'E', n: 0 }]))
      .toEqual([{ from: 'A', to: 'B', n: 2 }, { from: 'C', to: 'B', n: 1 }]);
  });
  it('one pair, 2–3 pairs, more pairs, one file, nothing', () => {
    expect(countLine([{ from: 'Powertrance', to: 'Powertrance_2026', n: 8 }]))
      .toBe('8 files move from Powertrance to Powertrance_2026.');
    expect(countLine([{ from: '', to: 'Bouncy', n: 1 }])).toBe('1 file moves from Library to Bouncy.');
    expect(countLine([{ from: 'Elsewhere/not_lossless', to: 'Hard_Bounce/not_lossless', n: 1 },
      { from: 'Elsewhere', to: 'Bouncy', n: 1 }]))
      .toBe('2 files move: 1 from Elsewhere/not_lossless to Hard_Bounce/not_lossless, 1 from Elsewhere to Bouncy.');
    expect(countLine([{ from: 'P', to: 'H', n: 1 }, { from: 'B', to: 'H', n: 1 }, { from: 'C', to: 'H', n: 1 },
      { from: 'E', to: 'P', n: 1 }])).toBe('4 files move between 5 folders.');
    expect(countLine([])).toBeNull();
  });
});

describe('the save question', () => {
  const offer = (from: string, to: string, offered = true): RenameOffer => ({ from, to, files: 12, offered,
    why_not: offered ? null : `A folder called ${to} is already in your Library.`, option: 'Rename the folder on disk too',
    detail: 'One folder move instead of 12 file moves.' });
  const p1 = row('Powertrance', 'Powertrance_2026', { by_rename: 'Powertrance' });
  const p2 = row('Powertrance/not_lossless', 'Powertrance_2026/not_lossless', { by_rename: 'Powertrance' });
  const p3 = row('Powertrance', 'Powertrance_2026', { by_rename: 'Powertrance', skip: { reason: 'offline', text: 'Offline, skipped' }, ticked: false });
  const away = row('Elsewhere', 'Powertrance_2026');   // sits elsewhere: the rename doesn't move it
  const rows = [p1, p2, p3, away];

  it('turns an offered rename on by default; one that isn\'t offered can\'t be turned on', () => {
    const q = initialQuestion(rows, [offer('Powertrance', 'Powertrance_2026')]);
    expect([...q.renameOn]).toEqual(['Powertrance']);
    const no = initialQuestion(rows, [offer('Powertrance', 'Powertrance_2026', false)]);
    expect(no.renameOn.size).toBe(0);
    expect(toggleRename(no, 'Powertrance').renameOn.size).toBe(0);
    expect(offerDetail(no.renames[0])).toBe('A folder called Powertrance_2026 is already in your Library.');
  });
  it('the heading, the folder row, the detail and C count the folder\'s files from the offer, not the rows', () => {
    // the folder holds 12 files; the preview lists 3 of them (no playlist places the others) and moves them all
    const q = initialQuestion(rows, [offer('Powertrance', 'Powertrance_2026')]);
    expect(saveHeadline(saveFileCount(q))).toBe('13 files would sit in a different folder');
    expect(visibleRows(q)).toEqual([away]);
    expect(folderRows(q)).toEqual([{ from: 'Powertrance', to: 'Powertrance_2026', files: 12 }]);
    expect(offerDetail(q.renames[0])).toBe('One folder move instead of 12 file moves.');
    expect(saveCount(q)).toBe('13 files move: 12 from Powertrance to Powertrance_2026, 1 from Elsewhere to Powertrance_2026.');
    expect(saveMoving(q)).toBe(13);
  });
  it('on "leave" an offered rename says it doesn\'t apply; one that isn\'t offered keeps its own reason', () => {
    const q = initialQuestion(rows, [offer('Powertrance', 'Powertrance_2026')]);
    expect(offerDetail(q.renames[0], true)).toBe('Not renamed when you leave the files where they are.');
    expect(offerDetail(q.renames[0], false)).toBe('One folder move instead of 12 file moves.');
    const no = initialQuestion(rows, [offer('Powertrance', 'Powertrance_2026', false)]);
    expect(offerDetail(no.renames[0], true)).toBe('A folder called Powertrance_2026 is already in your Library.');
  });
  it('one file in the folder is "1 file"', () => {
    const q = initialQuestion(rows, [{ ...offer('Powertrance', 'Powertrance_2026'), files: 1 }]);
    expect(offerDetail(q.renames[0])).toBe('One folder move instead of 1 file move.');
    expect(saveCount(q)).toBe('2 files move: 1 from Powertrance to Powertrance_2026, 1 from Elsewhere to Powertrance_2026.');
  });
  it('with the rename off the files show again, ticked as the backend says', () => {
    const q = toggleRename(initialQuestion(rows, [offer('Powertrance', 'Powertrance_2026')]), 'Powertrance');
    expect(visibleRows(q)).toEqual(rows);
    expect(folderRows(q)).toEqual([]);
    expect(saveFileCount(q)).toBe(4);
    expect(saveCount(q)).toBe('3 files move: 1 from Powertrance to Powertrance_2026, '
      + '1 from Powertrance/not_lossless to Powertrance_2026/not_lossless, 1 from Elsewhere to Powertrance_2026.');
  });
  it('save files: leave moves nothing and renames nothing; move sends the renames that are on and the shown ticks', () => {
    const q = initialQuestion(rows, [offer('Powertrance', 'Powertrance_2026')]);
    expect(saveFiles(q, 'leave')).toEqual({ choice: 'leave', renames: [], moves: [] });
    expect(saveFiles(q, 'move')).toEqual({ choice: 'move', renames: [['Powertrance', 'Powertrance_2026']],
      moves: [[away.file_id, away.from_path]] });
    const off = toggleRename(q, 'Powertrance');
    expect(saveFiles(off, 'move').renames).toEqual([]);
    expect(saveFiles(off, 'move').moves.map((m) => m[0])).toEqual([p1.file_id, p2.file_id, away.file_id]);
  });
  it('the save\'s moves in the order they happen: folders first, then files', () => {
    const q = initialQuestion(rows, [offer('Powertrance', 'Powertrance_2026')]);
    expect(saveItems(q).map((i) => [i.key, i.folder])).toEqual([['dPowertrance', true], [`f${away.file_id}`, false]]);
    expect(itemOfRow(p1).label).toBe(`A – ${p1.title}`);
  });
  it('a newer preview keeps the user\'s ticks and switches for what both previews have', () => {
    const offers = [offer('Powertrance', 'Powertrance_2026')];
    let q = initialQuestion(rows, offers);
    q = toggleRename({ ...q, ticks: toggleTick(q.ticks, away) }, 'Powertrance');
    const fresh = row('Bouncy', 'Hard_Bounce');
    const next = carryOver(q, [...rows, fresh], offers);
    expect(next.ticks.has(away.file_id)).toBe(false);
    expect(next.ticks.has(p1.file_id)).toBe(true);
    expect(next.ticks.has(fresh.file_id)).toBe(true);
    expect(next.renameOn.size).toBe(0);
    expect(carryOver(null, rows, offers).renameOn.size).toBe(1);
  });
  it('nothing ticked and no rename: nothing moves', () => {
    const q = initialQuestion([{ ...away, ticked: false }], []);
    expect(saveMoving(q)).toBe(0);
    expect(saveCount(q)).toBeNull();
  });
});

describe('progress', () => {
  it('adds up the batches of one job and never lets the total shrink', () => {
    let p = progressStart(5);
    expect([progressDone(p), progressTotal(p)]).toEqual([0, 5]);
    p = progressStep(p, { batch_id: 3, done: 1, total: 1 });
    p = progressStep(p, { batch_id: 4, done: 1, total: 4 });
    p = progressStep(p, { batch_id: 4, done: 2, total: 4 });
    expect([progressDone(p), progressTotal(p)]).toEqual([3, 5]);
    expect(progressTotal(progressStep(progressStart(1), { batch_id: 1, done: 0, total: 3 }))).toBe(3);
  });
  it('undo lists the moves that run, in order; a row that can\'t go back is recorded skipped before the run', () => {
    const u: UndoPreview = { batch_id: 1, title: 'Undo of: Tidy-up', moving: 8, warning: [], nothing_left: false,
      rows: [{ label: 'A - B', kind: 'file', files: null, from: 'X', to: 'Y', skip: null },
        { label: 'C - D', kind: 'file', files: null, from: 'X', to: 'Z',
          skip: { reason: 'moved_on', text: 'Moved or changed since' } },
        { label: 'Sets_2025', kind: 'folder', files: 7, from: 'Sets_2025', to: 'Old_Sets', skip: null }] };
    const items = undoItems(u);
    expect(items.map((i) => i.label)).toEqual(['A - B', 'Sets_2025']);
    expect(items.map((i) => [i.folder, i.files])).toEqual([[false, null], [true, 7]]);
  });
  it('undo progress marks the planned moves done as the batch reports them', () => {
    const u: UndoPreview = { batch_id: 1, title: 'Undo of: Tidy-up', moving: 3, warning: [], nothing_left: false,
      rows: [{ label: 'skip', kind: 'file', files: null, from: 'X', to: 'Y',
        skip: { reason: 'offline', text: 'Offline, skipped' } },
      { label: 'A', kind: 'file', files: null, from: 'X', to: 'Y', skip: null },
      { label: 'B', kind: 'file', files: null, from: 'X', to: 'Y', skip: null }] };
    const items = undoItems(u);
    let p = progressStart(items.length);
    expect(progressTotal(p)).toBe(2);   // the skipped row isn't a planned move
    p = progressStep(p, { batch_id: 9, done: 1, total: 2 });
    expect(items.map((_, i) => i < progressDone(p))).toEqual([true, false]);   // A is done, B isn't
  });
  it('says file or folder, and how many files a folder carries', () => {
    expect(undoRowName({ label: 'A - B', kind: 'file' })).toBe('A - B');
    expect(undoRowName({ label: 'Sets_2025', kind: 'folder' })).toBe('Sets_2025, the whole folder');
    expect(fileCountText(null)).toBeNull();
    expect(fileCountText(1)).toBe('1 file');
    expect(fileCountText(7)).toBe('7 files');
  });
});

describe('results', () => {
  const r = (id: number | null, moved: number, skipped: BatchResult['skipped'] = []): BatchResult =>
    ({ batch_id: id, title: 'Tidy-up', moved, headline: '', skipped, stopped: false });
  const failed = { label: 'K - N', from: 'A', to: 'B', reason: 'failed', text: "Couldn't move it: the drive is full" };
  const stopped = { label: 'L - C', from: 'A', to: 'B', reason: 'stopped', text: 'Not moved: the moves were stopped first' };
  it('adds the batches of one job up', () => {
    const o = outcomeOf([r(7, 1), r(8, 2, [failed, stopped])]);
    expect(o).toMatchObject({ moved: 3, back: false, batchIds: [7, 8] });
    expect(o.skipped).toEqual([failed, stopped]);
    expect(outcomeOf([r(9, 2)], true).back).toBe(true);
  });
  it('Undo of a result: one batch → its confirmation, several → the list, nothing moved → off', () => {
    expect(resultUndo(outcomeOf([r(7, 2)]))).toEqual({ batch: 7 });
    expect(resultUndo(outcomeOf([r(7, 1), r(8, 2)]))).toBe('list');
    expect(resultUndo(outcomeOf([r(7, 0, [failed])]))).toBeNull();
    expect(resultUndo(outcomeOf([r(null, 0)]))).toBeNull();
  });
  it('a failed move is a problem, the rest are warnings', () => {
    expect(skipTone('failed')).toBe('problem');
    expect(skipTone('stopped')).toBe('warn');
    expect(skipTone('offline')).toBe('warn');
  });
});

describe('problemToTell', () => {
  it('tells every failed job, also one that still carries a result', () => {
    expect(problemToTell({ ok: false, kind: 'crashed', message: 'The disk is gone' }))
      .toEqual({ kind: 'crashed', message: 'The disk is gone' });
    expect(problemToTell({ ok: false, kind: 'busy', message: '' })).toEqual({ kind: 'busy', message: '' });
  });
  it('says nothing after a Stop the user pressed, or after a success', () => {
    expect(problemToTell({ ok: false, kind: 'stopped', message: 'Stopped.' })).toBeNull();
    expect(problemToTell({ ok: true })).toBeNull();
  });
});
