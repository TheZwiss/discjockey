import { afterEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { createFakeBridge } from './bridge/fake/bridge';
import { _resetBridge, installBridge } from './bridge/client';
import { answerConfirm, confirmRequest } from './components/confirm';
import { dataVersion, refreshHub } from './stores/hub';
import { CLOSE_BODY, CLOSE_TITLE, OTHER_FILES_BODY, checkFolder, chooseFolder, isFail, useFolder } from './musicFolderFlow';

function fake(scenario: string) {
  (globalThis as any).window = new EventTarget();  // the bridge's window (node has no DOM)
  _resetBridge();
  const f = createFakeBridge(scenario);
  const s = (f as any)._ctx.s;
  s.folders['/Users/you/Other'] = { exists: true, usable: true, problem: null, kind: 'other_files', message: null };
  s.folders['/Users/you'] = { exists: true, usable: false, problem: 'system_folder', kind: null, message: null };
  installBridge(f);
  return { f, s };
}
/** answers the next confirm() with `ok` and hands back what it asked */
function answerNext(ok: boolean): Promise<{ title: string; body?: string }> {
  return new Promise((resolve) => {
    const stop = confirmRequest.subscribe((p) => {
      if (!p) return;
      queueMicrotask(() => { stop(); resolve({ title: p.title, body: p.body }); answerConfirm(ok); });
    });
  });
}

afterEach(() => { vi.restoreAllMocks(); answerConfirm(false); });

describe('musicFolderFlow', () => {
  it('chooses with the dialog and checks what is there', async () => {
    fake('no_music');
    expect(await chooseFolder()).toBe('/Users/you/Music/DJ Sets');
    expect(await checkFolder('/Users/you/Other')).toMatchObject({ usable: true, kind: 'other_files' });
  });
  it('binds a new folder without asking', async () => {
    const { s } = fake('no_music');
    expect(await useFolder('/Users/you/Music/Discjockey', { bound: false })).toBe('bound');
    expect(s.setup.music).toMatchObject({ state: 'ok', path: '/Users/you/Music/Discjockey' });
    expect(get(confirmRequest)).toBeNull();
  });
  it('asks before a folder with other files, and keeps it unbound on No', async () => {
    const { s } = fake('no_music');
    const asked = answerNext(false);
    expect(await useFolder('/Users/you/Other', { bound: false })).toBe('cancelled');
    expect((await asked).title).toMatch(/other files/);
    expect(s.setup.music.state).toBe('not_chosen');
  });
  it("hands on a refused folder with the engine's words", async () => {
    fake('no_music');
    const r = await useFolder('/Users/you', { bound: false });
    expect(isFail(r) && r.kind === 'refused' && r.message).toMatch(/belongs to macOS/);
  });
  it('a bound library asks that the app closes, then quits', async () => {
    const { f } = fake('normal');
    await refreshHub();
    const quit = vi.spyOn(f, 'quit');
    const asked = answerNext(true);
    expect(await useFolder('/Volumes/DJ SSD/New', { bound: true })).toBe('restart');
    expect(await asked).toEqual({ title: CLOSE_TITLE, body: CLOSE_BODY });
    expect(quit).toHaveBeenCalledOnce();
  });
  it('a failed folder dialog is a Fail, not a cancel', async () => {
    const { f } = fake('no_music');
    vi.spyOn(f, 'pick_folder').mockResolvedValue({ ok: false, kind: 'failed', message: 'The folder dialog could not open.' });
    const r = await chooseFolder();
    expect(isFail(r) && r.message).toBe('The folder dialog could not open.');
  });
  it('a cancelled folder dialog is null', async () => {
    const { s } = fake('no_music');
    s.pick = null;
    expect(await chooseFolder()).toBeNull();
  });
  it('reads everything again once a folder is bound', async () => {
    fake('no_music');
    const before = get(dataVersion);
    expect(await useFolder('/Users/you/Music/Discjockey', { bound: false })).toBe('bound');
    expect(get(dataVersion)).toBe(before + 1);
  });
  it('the folder already in use closes nothing and asks nothing', async () => {
    const { f, s } = fake('normal');
    await refreshHub();
    const path = s.setup.music.path as string;
    s.folders[path] = { exists: true, usable: true, problem: null, kind: 'discjockey_library', message: null };
    const quit = vi.spyOn(f, 'quit');
    expect(await useFolder(path, { bound: true })).toBe('bound');
    expect(get(confirmRequest)).toBeNull();
    expect(quit).not.toHaveBeenCalled();
  });
  it('a bound library and a folder with other files ask once, in one body', async () => {
    const { f } = fake('normal');
    await refreshHub();
    const quit = vi.spyOn(f, 'quit');
    const asked = answerNext(true);
    expect(await useFolder('/Users/you/Other', { bound: true })).toBe('restart');
    expect(await asked).toEqual({ title: CLOSE_TITLE, body: `${OTHER_FILES_BODY} ${CLOSE_BODY}` });
    expect(quit).toHaveBeenCalledOnce();
  });
  it('when quit fails after the folder is set, says saved (the choice is kept; nothing is bumped)', async () => {
    const { f } = fake('normal');
    await refreshHub();
    vi.spyOn(f, 'quit').mockResolvedValue({ ok: false, kind: 'busy', message: 'Discjockey is still busy with a change.' });
    const before = get(dataVersion);
    answerNext(true);
    const r = await useFolder('/Volumes/DJ SSD/New', { bound: true });
    expect(r).toBe('saved');
    expect(get(dataVersion)).toBe(before);
  });
});
