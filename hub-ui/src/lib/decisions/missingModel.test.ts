// The Missing files words and counts (issue 43, plan §5.4 and §7.4) against the fake bridge's scenario `missing_files`,
// which answers as the engine does: the window shows the engine's words and counts what it is told.
import { describe, expect, it } from 'vitest';
import type { MissingResult, Todo, TodoItem, TrackDetail } from '../bridge/types';
import { createFakeBridge } from '../bridge/fake/bridge';
import { missingSet, REASON_WORDS } from '../bridge/fake/missingFiles';
import {
  DOWNLOAD_AGAIN_LABEL, REMOVE_LABEL, downloadAgainManyLabel, missingButtons, missingEnd, missingFoot, missingLabel, missingNote,
  missingRowWords, missingSelectedTitle, removeConfirm, removeManyLabel, selectAllLabel, selectAllShown,
} from './missingModel';

async function scene() {
  const f = createFakeBridge('missing_files');
  const ids = missingSet((f as any)._ctx.s)!;
  const t = (await f.todo('all', true)) as Todo & { ok: true };
  const items = t.groups.find((g) => g.key === 'missing_file')!.items;
  const by = (id: string): TodoItem => items.find((i) => i.track_id === id)!;
  const detail = async (id: string) => ((await f.track(id)) as { ok: true; track: TrackDetail }).track;
  return { f, ids, items, by, detail };
}

describe('the labels and the confirm (§5.4)', () => {
  it('the buttons of one song and of a selection', () => {
    expect(DOWNLOAD_AGAIN_LABEL).toBe('Download again');
    expect(REMOVE_LABEL).toBe('Remove from library…');
    expect(missingLabel('download_again')).toBe('Download again');
    expect(missingLabel('remove')).toBe('Remove from library…');
    expect(downloadAgainManyLabel(3)).toBe('Download again · 3');
    expect(removeManyLabel(2)).toBe('Remove from library · 2…');
    expect(missingSelectedTitle(2)).toBe('2 songs selected');
    expect(selectAllLabel(4)).toBe('Select all · 4');
  });
  it('Select all shows from two songs that can act', () => {
    expect([0, 1, 2, 5].map(selectAllShown)).toEqual([false, false, true, true]);
  });
  it('Remove asks in the singular and the plural, danger', () => {
    expect(removeConfirm(1)).toMatchObject({ title: 'Remove from your library?', confirmLabel: 'Remove', tone: 'danger',
      body: "Their files aren't in your watched folders. Discjockey forgets these songs, your answers about them and any better "
        + 'version waiting for them. If a file comes back later, it is added as a new song.' });
    expect(removeConfirm(3).title).toBe('Remove 3 songs from your library?');
  });
});

describe('one song: the foot and the note', () => {
  it('a playlist song: Download again, filled, enabled, no reason', async () => {
    const { ids, detail } = await scene();
    expect(missingFoot(await detail(ids.plain))).toEqual({ action: 'download_again', label: 'Download again', variant: 'filled',
      disabled: false, tip: null, hint: null });
  });
  it('an own song: Remove from library… in the danger variant', async () => {
    const { ids, detail } = await scene();
    expect(missingFoot(await detail(ids.own))).toMatchObject({ action: 'remove', label: 'Remove from library…', variant: 'danger',
      disabled: false });
  });
  it('a song the action can not run for: disabled, the engine reason as tip and hint', async () => {
    const { ids, detail } = await scene();
    expect(missingFoot(await detail(ids.twice))).toMatchObject({ action: 'download_again', disabled: true,
      tip: REASON_WORDS.found_twice, hint: REASON_WORDS.found_twice });
    expect(missingFoot(await detail(ids.ownCheck))).toMatchObject({ action: 'remove', disabled: true, tip: REASON_WORDS.check_open });
  });
  it('the note is the engine\'s line and hint, nothing built here; none for a song that is not missing', async () => {
    const { ids, detail } = await scene();
    const d = await detail(ids.parked);
    expect(missingNote(d)).toEqual({ title: d.missing!.line, text: d.missing!.hint });
    expect(missingNote(d)!.text).toContain('nothing is downloaded');
    expect(missingNote({ missing: null })).toBeNull();
    expect(missingFoot({ missing: null })).toBeNull();
  });
});

describe('several songs: the rows, the counts and the buttons', () => {
  it('a row says what happens (`will`) or, dimmed, why not (the engine\'s words)', async () => {
    const { ids, by } = await scene();
    expect(missingRowWords(by(ids.plain))).toEqual({ text: 'Downloads again at your next sync', dim: false });
    expect(missingRowWords(by(ids.parked))).toEqual({ text: 'Gets the better version already waiting for it at your next sync; nothing is downloaded', dim: false });
    expect(missingRowWords(by(ids.own))).toEqual({ text: 'Removed from your library', dim: false });
    expect(missingRowWords(by(ids.twice))).toEqual({ text: REASON_WORDS.found_twice, dim: true });
    expect(missingRowWords({ missing: undefined })).toEqual({ text: '', dim: true });
  });
  it('counts by the engine\'s action with no reason; the songs that can\'t run are in neither', async () => {
    const { ids, by } = await scene();
    const b = missingButtons([by(ids.plain), by(ids.parked), by(ids.twice), by(ids.own), by(ids.ownCheck)]);
    expect(b.n).toBe(2);
    expect(b.m).toBe(1);
    expect(b.download).toEqual({ label: 'Download again · 2', ids: [ids.plain, ids.parked] });
    expect(b.remove).toEqual({ label: 'Remove from library · 1…', ids: [ids.own] });
  });
  it('one kind selected: only its button', async () => {
    const { ids, by } = await scene();
    expect(missingButtons([by(ids.plain), by(ids.parked)]).remove).toBeNull();
    expect(missingButtons([by(ids.own), by(ids.ownParked)]).download).toBeNull();
    expect(missingButtons([by(ids.twice), by(ids.ownCheck)])).toMatchObject({ n: 0, m: 0, download: null, remove: null });
    expect(missingButtons([])).toMatchObject({ n: 0, m: 0 });
  });
});

describe('what the job said', () => {
  const result = (over: Partial<MissingResult> = {}): MissingResult => ({ action: 'remove', done: ['a'], skipped: ['b'], words: 'Removed 1 song from your library; 1 is skipped.',
    results: [{ track_id: 'a', action: 'remove', state: 'done', reason: null, words: 'Removed from your library' },
      { track_id: 'b', action: 'remove', state: 'skipped', reason: 'check_open', words: REASON_WORDS.check_open }], recovered: [], ...over });
  it('the words, the count and the skipped with their reason words', () => {
    expect(missingEnd(result(), (id) => `N ${id}`)).toEqual({ action: 'remove', words: 'Removed 1 song from your library; 1 is skipped.', done: 1,
      skipped: [{ track_id: 'b', name: 'N b', text: REASON_WORDS.check_open }] });
  });
  it('a skipped song with no words shows an empty line, a missing result is null', () => {
    const r = result();
    r.results[1].words = null;
    expect(missingEnd(r, (id) => id)!.skipped[0].text).toBe('');
    expect(missingEnd(null, (id) => id)).toBeNull();
    expect(missingEnd(undefined, (id) => id)).toBeNull();
  });
});
