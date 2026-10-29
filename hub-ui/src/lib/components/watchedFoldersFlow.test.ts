import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { _resetBridge } from '../bridge/client';
import { dispatch } from '../bridge/events';
import type { SetupStatus, WatchedFolderRow } from '../bridge/types';
import { skipsExisting } from '../../pages/setup/setupModel';
import { _resetJobs } from '../stores/jobs';
import { answerConfirm, confirmRequest } from './confirm';
import { WatchedFoldersFlow } from './watchedFoldersFlow.svelte';

const row = (over: Partial<WatchedFolderRow> = {}): WatchedFolderRow => ({ id: 2, path: '/Volumes/Example Drive/Music',
  name: 'Music', kind: 'import', state: 'online', files: 1240, waiting: 0, unreadable: 0, ...over });
const LIB = row({ id: 1, kind: 'library', name: 'Library', path: '/Users/you/Music/Discjockey/Library', files: 412 });
const list = (...folders: WatchedFolderRow[]) => ({ ok: true, folders, unreadable: [], waiting: 0, stopped: false });
const STATUS = { existing: false } as SetupStatus;

let calls: [string, unknown[]][] = [];
let folders: ReturnType<typeof list> | { ok: false; kind: string; message: string } = list(LIB);
function fakeWindow(over: Record<string, (...a: any[]) => any> = {}) {
  const rec = (name: string, answer: unknown) => async (...a: unknown[]) => { calls.push([name, a]); return answer; };
  const w = new EventTarget() as any;
  w.pywebview = { api: {
    watched_folders: async () => folders,
    pick_folder: rec('pick_folder', { ok: true, path: '/Volumes/Example Drive/Music' }),
    check_import_folder: async (path: string) => ({ ok: true, path, exists: true, usable: true, problem: null, kind: 'import',
      message: null, merges: [], merge_hints: [] }),
    add_watched_folder: rec('add_watched_folder', { ok: true, job_id: 5 }),
    removal_preview: rec('removal_preview', { ok: true, name: 'Music', files: 1240, redownload: 4 }),
    remove_watched_folder: rec('remove_watched_folder', { ok: true, job_id: 6 }),
    start_import: rec('start_import', { ok: true, job_id: 7 }),
    stop: rec('stop', { ok: true, stopped: true }),
    ...over,
  } };
  (globalThis as any).window = w;
}
const flush = () => new Promise((r) => setTimeout(r, 0));
const names = () => calls.map(([n]) => n);
/** answers the next confirm() with `ok` and hands back what it asked */
function answerNext(ok: boolean): Promise<{ title: string; body?: string; confirmLabel?: string }> {
  return new Promise((resolve) => {
    const stop = confirmRequest.subscribe((p) => {
      if (!p) return;
      queueMicrotask(() => { stop(); resolve({ title: p.title, body: p.body, confirmLabel: p.confirmLabel }); answerConfirm(ok); });
    });
  });
}

beforeEach(() => { _resetBridge(); _resetJobs(); calls = []; folders = list(LIB);
  vi.spyOn(console, 'warn').mockImplementation(() => {}); });
afterEach(() => { vi.restoreAllMocks(); answerConfirm(false); delete (globalThis as any).window; });

describe('WatchedFoldersFlow', () => {
  it("shows an add's refusal in the engine's words, unchanged, and adds nothing", async () => {
    const words = 'This is inside your music folder, which Discjockey watches already.';
    fakeWindow({ check_import_folder: async () => ({ ok: true, path: '/Users/you/Music/Discjockey/Library/x', exists: true,
      usable: false, problem: 'music', kind: null, message: words, merges: [], merge_hints: [] }) });
    const f = new WatchedFoldersFlow();
    await f.add();
    expect(f.note).toEqual({ tone: 'problem', lines: [words] });
    expect(names()).not.toContain('add_watched_folder');
    expect(f.adding).toBe(false);
    // a refusal of the call itself (another change runs) says its own words too
    fakeWindow({ check_import_folder: async () => ({ ok: false, kind: 'busy', message: 'Wait until the current change is finished.' }) });
    await f.add();
    expect(f.note).toEqual({ tone: 'problem', lines: ['Wait until the current change is finished.'] });
  });

  it('adds a usable folder and says what it took over with the engine merge lines (W5)', async () => {
    const hints = ['Crates is inside it and becomes part of it.', 'Old is inside it and becomes part of it.'];
    fakeWindow({ check_import_folder: async (path: string) => ({ ok: true, path, exists: true, usable: true, problem: null,
      kind: 'import', message: null, merges: ['/Volumes/Example Drive/Music/Crates'], merge_hints: hints }) });
    const f = new WatchedFoldersFlow();
    await f.add();
    expect(calls.find(([n]) => n === 'add_watched_folder')?.[1]).toEqual(['/Volumes/Example Drive/Music']);
    expect(f.note).toEqual({ tone: 'info', lines: hints });
    // the next dialog starts where the last one was
    await f.add();
    expect(calls.filter(([n]) => n === 'pick_folder').at(-1)?.[1]).toEqual(['/Volumes/Example Drive/Music']);
  });

  it('a cancelled dialog changes nothing', async () => {
    fakeWindow({ pick_folder: async () => ({ ok: true, path: null }) });
    const f = new WatchedFoldersFlow();
    await f.add();
    expect(f.note).toBeNull();
    expect(names()).not.toContain('add_watched_folder');
  });

  it("Remove asks with removal_preview's numbers (W4), then removes and reads again; Cancel removes nothing", async () => {
    fakeWindow();
    folders = list(LIB, row());
    const f = new WatchedFoldersFlow();
    await f.load();
    const asked = answerNext(true);
    const p = f.remove(f.data!.folders[1]);
    expect(await asked).toEqual({ title: 'Remove Music?', confirmLabel: 'Remove folder',
      body: 'Discjockey forgets its 1,240 files. The files stay where they are. 4 songs from your playlists had their '
        + 'only copy there. They will be downloaded again at the next sync.' });
    await flush();
    dispatch({ type: 'JobFinished', job_id: 6, kind: 'remove_watched_folder', ok: true, problem: null, message: '', result: null } as any);
    await p;
    expect(calls.find(([n]) => n === 'removal_preview')?.[1]).toEqual([2]);
    expect(calls.find(([n]) => n === 'remove_watched_folder')?.[1]).toEqual([2]);
    expect(f.removing).toBeNull();

    calls = [];
    const no = answerNext(false);
    await f.remove(f.data!.folders[1]);
    await no;
    expect(names()).toEqual(['removal_preview']);
    // the Library is never removed
    await f.remove(f.data!.folders[0]);
    expect(names()).toEqual(['removal_preview']);
  });

  it('two folders with one name: the dialog keeps the title and says which one by its short path', async () => {
    fakeWindow({ removal_preview: async () => ({ ok: true, name: 'Music', files: 10, redownload: 0 }) });
    folders = list(LIB, row({ id: 3, name: 'Music', path: '/Users/you/Music' }), row());
    const f = new WatchedFoldersFlow();
    await f.load();
    const asked = answerNext(false);
    await f.remove(f.data!.folders[1]);
    expect(await asked).toMatchObject({ title: 'Remove Music?',
      body: 'This is the folder at ~/Music. Discjockey forgets its 10 files. The files stay where they are.' });
  });

  it('Stop and Continue import call the bridge; a refusal shows its words', async () => {
    fakeWindow();
    const f = new WatchedFoldersFlow();
    await f.stop();
    expect(names()).toEqual(['stop']);
    const p = f.continueImport();
    expect(f.starting).toBe(true);
    await p;
    expect(names()).toEqual(['stop', 'start_import']);
    expect(f.starting).toBe(false);
    expect(f.note).toBeNull();
    fakeWindow({ start_import: async () => ({ ok: false, kind: 'busy', message: 'Wait until the current change is finished.' }) });
    await f.continueImport();
    expect(f.note).toEqual({ tone: 'problem', lines: ['Wait until the current change is finished.'] });
  });

  it('a failed read after a good one keeps the rows and shows the error until the next good read', async () => {
    fakeWindow();
    folders = list(LIB, row());
    const f = new WatchedFoldersFlow();
    await f.load();
    expect(f.error).toBeNull();
    folders = { ok: false, kind: 'crashed', message: 'Something went wrong. Try again.' };
    await f.load();
    expect(f.error).toEqual({ kind: 'crashed', message: 'Something went wrong. Try again.' });
    expect(f.data?.folders).toHaveLength(2);
    folders = list(LIB, row());
    await f.load();
    expect(f.error).toBeNull();
  });

  it('Setup skips the step on Continue only while no folder is watched', async () => {
    fakeWindow();
    const f = new WatchedFoldersFlow();
    await f.load();
    expect(skipsExisting(STATUS, f.data)).toBe(true);
    // Add folder…, then a quick Continue before the status knows: the folders say it is watched
    folders = list(LIB, row());
    await f.add();
    expect(skipsExisting(STATUS, f.data)).toBe(false);
  });
});
