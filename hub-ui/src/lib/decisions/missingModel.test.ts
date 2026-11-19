// The Missing files words and counts (issue 43, plan §5.4 and §7.4) against the fake bridge's scenario `missing_files`,
// which answers as the engine does: the window shows the engine's words and counts what it is told.
import { describe, expect, it } from 'vitest';
import type { MissingPreview, MissingResult, Todo, TodoItem, TrackDetail } from '../bridge/types';
import { createFakeBridge } from '../bridge/fake/bridge';
import { missingSet, REASON_WORDS } from '../bridge/fake/missingFiles';
import {
  currentPreviews, missingButtons, missingEnd, missingFoot, missingNote, missingRowWords, missingSelectedTitle,
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

describe('the labels (§5.4)', () => {
  it('the selection\'s head (the buttons\' words and the confirm are the engine\'s)', () => {
    expect(missingSelectedTitle(2)).toBe('2 songs selected');
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
    expect(missingFoot(await detail(ids.ownCheck))).toMatchObject({ action: 'remove', disabled: true, tip: REASON_WORDS.check_open,
      hint: REASON_WORDS.check_open });
  });
  it('a state is said once: a song found in several places has its words in the note, the foot keeps neither tip nor hint', async () => {
    const { ids, detail } = await scene();
    const twice = await detail(ids.twice);
    expect(missingFoot(twice)).toMatchObject({ action: 'download_again', disabled: true, tip: null, hint: null });
    expect(missingNote(twice)!.title).toMatch(/^Found in 2 places/);
  });
  it('the foot takes the engine\'s label, tone and foot_note as they come (the window decides none of them)', async () => {
    const { ids, detail } = await scene();
    const d = await detail(ids.own);
    const m = d.missing!;
    expect(missingFoot({ missing: { ...m, label: 'L!', tone: 'filled', why_not: 'check_open', foot_note: 'N!' } }))
      .toEqual({ action: m.action, label: 'L!', variant: 'filled', disabled: true, tip: 'N!', hint: 'N!' });
    expect(missingFoot({ missing: { ...m, label: 'L!', tone: 'danger', why_not: 'found_twice', words: 'said above', foot_note: null } }))
      .toEqual({ action: m.action, label: 'L!', variant: 'danger', disabled: true, tip: null, hint: null });
  });
  it('the note is the engine\'s line and hint, nothing built here; none for a song that is not missing', async () => {
    const { ids, detail } = await scene();
    const d = await detail(ids.parked);
    expect(missingNote(d)).toEqual({ title: d.missing!.line, text: d.missing!.hint });
    expect(missingNote(d)!.text).toContain('nothing is downloaded');
    // the Library's note carries the library hint (its foot only goes to To-do)
    expect(missingNote(d, 'library')).toEqual({ title: d.missing!.line, text: d.missing!.hint_library });
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
  // the previews as the flow reads them: the engine's `missing_files_preview` once per action over the selection
  const previews = async (f: any, ids: string[]) => ({
    download_again: ((await f.missing_files_preview(ids, 'download_again')) as MissingPreview),
    remove: ((await f.missing_files_preview(ids, 'remove')) as MissingPreview) });
  it('the buttons are the engine\'s words, the ids those it says will run; the songs that can\'t run are in neither', async () => {
    const { f, ids } = await scene();
    const b = missingButtons(await previews(f, [ids.plain, ids.parked, ids.twice, ids.own, ids.ownCheck]));
    expect(b.download).toMatchObject({ label: 'Download again · 2', ids: [ids.plain, ids.parked], confirm: null });
    expect(b.remove).toMatchObject({ label: 'Remove from library · 1…', ids: [ids.own] });
    expect(b.remove!.confirm).toMatchObject({ title: 'Remove from your library?', confirm_label: 'Remove', tone: 'danger' });
    expect(b.none).toBeNull();
  });
  it('one kind selected: only its button; none can run: the engine\'s line', async () => {
    const { f, ids } = await scene();
    expect(missingButtons(await previews(f, [ids.plain, ids.parked])).remove).toBeNull();
    const own = missingButtons(await previews(f, [ids.own, ids.ownParked]));
    expect(own.download).toBeNull();
    expect(own.remove!.confirm!.title).toBe('Remove 2 songs from your library?');
    const none = missingButtons(await previews(f, [ids.twice, ids.ownCheck]));
    expect(none).toMatchObject({ download: null, remove: null, none: 'Nothing to do: 2 songs are skipped.' });
    expect(missingButtons(null)).toEqual({ download: null, remove: null, none: null });
  });
  it('the line for "nothing can run" is the one of the action the selected songs have', async () => {
    const { f, ids, by } = await scene();
    const p = await previews(f, [ids.ownCheck, ids.own].slice(0, 1).concat(ids.ownCheck));
    const two = { download_again: p.download_again, remove: p.remove };
    expect(p.remove.words).not.toBe(p.download_again.words);
    const acts = (...i: string[]) => i.map((x) => by(x).missing!.action);
    expect(missingButtons(two, acts(ids.ownCheck)).none).toBe(p.remove.words);
    expect(missingButtons(two, acts(ids.twice)).none).toBe(p.download_again.words);
    expect(missingButtons(two, acts(ids.twice, ids.ownCheck)).none).toBe(p.download_again.words);
    expect(missingButtons(two, []).none).toBe(p.download_again.words);
  });
  it('the answer is current only for the songs selected now; a stale one is dropped so no button acts on other songs', async () => {
    const { f, ids } = await scene();
    const p = { ids: [ids.plain, ids.parked], ...(await previews(f, [ids.plain, ids.parked])), phase: 'ready' as const, message: '' };
    expect(currentPreviews(p, [ids.plain, ids.parked])).toBe(p);
    expect(currentPreviews(p, [ids.plain])).toBeNull();
    expect(currentPreviews(p, [ids.parked, ids.plain])).toBeNull();
    expect(currentPreviews(null, [ids.plain])).toBeNull();
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
