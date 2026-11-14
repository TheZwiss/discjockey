// Every Library fake scenario loads, and the Convert / Rename / Make all ones (issue 33 stage D, plan §6.4 S1) hold the
// data their state needs: the song to open, the plan's numbers, the stopped batch, the check.
import { describe, expect, it } from 'vitest';
import { createFakeBridge } from '$lib/bridge/fake/bridge';
import { MUSIC_DIR, MUSIC_SCOPE } from '$lib/bridge/fake/aiffScenes';
import type { HubEvent } from '$lib/bridge/events';
import type { AiffBatchResult, AiffPlan, Library, Todo, TrackDetail } from '$lib/bridge/types';
import type { Selection } from '$lib/components/selectionModel';
import { keepTableSelection } from './libraryModel';
import { scenarios } from './fake';

const name = (n: string) => `library:${n}`;
const bridge = (n: string) => createFakeBridge(name(n), { speed: 1000 });
const folder = async (f: ReturnType<typeof bridge>) => (await f.library('folder', MUSIC_DIR, '', 'all', null)) as Library & { ok: true };
const plan = async (f: ReturnType<typeof bridge>) =>
  ((await f.aiff_plan({ kind: 'lossless', view: 'folder', key: MUSIC_DIR })) as { ok: true; plan: AiffPlan }).plan;
const detail = async (f: ReturnType<typeof bridge>, id: string) => ((await f.track(id)) as { ok: true; track: TrackDetail }).track;

describe('the Library fake scenarios', () => {
  it('every named scenario loads the library and the Music folder without error', async () => {
    for (const n of Object.keys(scenarios ?? {})) {
      const f = bridge(n);
      expect(await f.library('all', null, '', 'all', null), n).toMatchObject({ ok: true });
      expect(await f.todo('all', false), n).toMatchObject({ ok: true });
    }
  });

  it('the aiff scenarios show the Music folder with its 24 songs and name each state of S1', async () => {
    const names = Object.keys(scenarios ?? {}).filter((n) => n.startsWith('aiff-'));
    expect(names).toHaveLength(19);   // plan §6.4 S1 names 19 states (its "≤ 18" is a miscount)
    for (const n of names) {
      const lib = await folder(bridge(n));
      expect(lib, n).toMatchObject({ ok: true, view: 'folder' });
      expect(lib.rows, n).toHaveLength(24);
    }
  });

  it('a lossless FLAC is a Convert, a lossy file too (outlined), a CDJ file says why, a messy clean AIFF is a Rename', async () => {
    const f = bridge('aiff-flac');
    expect((await detail(f, 'own:1')).aiff).toMatchObject({ action: 'convert', kind: 'flac', lossy: false, cdj: null,
      from: 'FLAC · 24-bit · 96 kHz', to: 'AIFF · 16-bit · 44.1 kHz' });
    expect((await detail(f, 'own:10')).aiff).toMatchObject({ action: 'convert', kind: 'mp3', lossy: true, cdj: null });
    expect((await detail(f, 'own:13')).aiff).toMatchObject({ action: 'convert', kind: 'flac', lossy: false,
      cdj: { short: 'FLAC 192 kHz · CDJs stop at 96 kHz' } });
    const rename = (await detail(f, 'own:7')).aiff!;
    expect(rename).toMatchObject({ action: 'rename', to: null, bytes: 0 });
    expect(rename.name_now).toMatch(/_-_.*_\(Original_Mix\)\.aiff$/);
    expect(rename.new_name).toMatch(/^[^_]+ - [^_]+\.aiff$/);
    expect((await detail(f, 'own:8')).aiff).toMatchObject({ action: null, why_not: 'named_already' });
  });

  it('blocked: rekordbox unreadable gives why_not rekordbox_unreadable; rekordbox open keeps the plan and says it runs', async () => {
    expect((await detail(bridge('aiff-blocked'), 'own:1')).aiff).toMatchObject({ action: 'convert', why_not: 'rekordbox_unreadable', to: 'AIFF · 16-bit · 44.1 kHz' });   // blocked, still the step's own answer
    const open = bridge('aiff-rename-blocked');
    expect((await detail(open, 'own:7')).aiff).toMatchObject({ action: 'rename' });
    expect((await plan(open)).rekordbox).toMatchObject({ state: 'ready', running: true, needs_closed: true });
  });

  it('the view plan: kinds, space, waiting; empty, short of room and rekordbox open', async () => {
    const p = await plan(bridge('aiff-view'));
    expect(p.scope).toMatchObject({ kind: 'lossless', view: 'folder' });
    expect(p.total).toBeGreaterThan(12);
    expect(p.kinds.map((k) => k.label)).toEqual(expect.arrayContaining(['FLAC → AIFF', 'WAV → AIFF', 'ALAC → AIFF',
      'AIFF 24-bit or above 44.1 kHz → 16-bit', 'New tags', 'Clean name only']));
    expect(p.waiting).toEqual([{ reason: 'cloud', message: expect.any(String), n: 1 }]);
    expect(p.space.every((r) => r.enough)).toBe(true);
    expect(p.lossy).toBe(0);
    const empty = await plan(bridge('aiff-view-empty'));
    expect(empty).toMatchObject({ total: 0, items: [], waiting: [] });
    const space = await plan(bridge('aiff-view-space'));
    expect(space.space.some((r) => !r.enough)).toBe(true);
    expect((await plan(bridge('aiff-rekordbox-open'))).rekordbox).toMatchObject({ running: true, needs_closed: true });
  });

  it('a selection lists what it leaves as it is; the lossy one counts its lossy songs', async () => {
    const f = bridge('aiff-selection');
    const r = (await f.aiff_plan({ kind: 'tracks', tracks: ['own:1', 'own:5', 'own:6', 'own:7', 'own:8', 'own:16'] })) as { ok: true; plan: AiffPlan };
    expect(r.plan.items.map((i) => i.action)).toEqual(['convert', 'convert', 'convert', 'rename']);
    expect(r.plan.skipped.map((s) => s.reason).sort()).toEqual(['cloud', 'named_already']);
    const lossy = (await bridge('aiff-selection-lossy').aiff_plan({ kind: 'tracks', tracks: ['own:2', 'own:10', 'own:11', 'own:12'] })) as { ok: true; plan: AiffPlan };
    expect(lossy.plan).toMatchObject({ total: 4, lossy: 3 });
  });

  it('a stopped Make all shows Resume with the songs left; a finished Convert leaves its check', async () => {
    const stopped = await folder(bridge('aiff-panel-stopped'));
    expect(stopped.aiff_stopped).toEqual({ batch_id: 1, left: 7 });
    expect((await folder(bridge('aiff-view'))).aiff_stopped).toBeNull();
    const f = bridge('aiff-check-converted');
    const item = ((await f.todo('rekordbox_check', false)) as Todo & { ok: true }).groups.find((g) => g.key === 'rekordbox_check')!.items.find((i) => i.track_id === 'own:1');
    expect(item).toMatchObject({ track_id: 'own:1', check: { reason: 'converted', rekordbox: { entries: 1 } } });
    expect((await detail(f, 'own:1')).aiff).toMatchObject({ action: null, why_not: 'named_already' });
    expect(MUSIC_SCOPE).toBe(`library:folder:${MUSIC_DIR}`);
  });

  it('a Make all over the folder runs to its end: the ended scenario skips one file, the rekordbox-open one refuses', async () => {
    const run = async (n: string) => {
      const evs: HubEvent[] = [];
      const f = createFakeBridge(name(n), { speed: 1000, emit: (e) => evs.push(e) });
      const r = await f.make_aiff({ kind: 'lossless', view: 'folder', key: MUSIC_DIR });
      if (!r.ok) throw new Error(JSON.stringify(r));
      for (let i = 0; i < 600; i++) {
        const e = evs.find((x) => x.type === 'JobFinished' && x.job_id === r.job_id);
        if (e) return e as Extract<HubEvent, { type: 'JobFinished' }>;
        await new Promise((res) => setTimeout(res, 5));
      }
      throw new Error('the job did not finish');
    };
    const ended = await run('aiff-panel-ended');
    expect(ended.ok).toBe(true);
    const result = ended.result as AiffBatchResult;
    expect(result.state).toBe('done');
    expect(result.skipped).toBe(1);
    expect(result.done).toBeGreaterThan(10);
    const open = await run('aiff-rekordbox-open');
    expect(open).toMatchObject({ ok: false, problem: 'rekordbox_open' });
  });

  it('the table follows a selection\'s Convert and keeps the selection on the same tracks', async () => {
    const evs: HubEvent[] = [];
    const f = createFakeBridge(name('aiff-multi'), { speed: 1000, emit: (e) => evs.push(e) });
    const ids = ['own:1', 'own:2', 'own:6', 'own:7'];
    const keys = async () => (await folder(f)).rows.map((r) => r.track_id);
    const before = await keys();
    const sel: Selection = { keys: ids, anchor: 'own:7' };
    expect(ids.every((id) => before.includes(id))).toBe(true);
    const r = await f.convert(ids, 'library');
    if (!r.ok) throw new Error(JSON.stringify(r));
    for (let i = 0; i < 600 && !evs.some((x) => x.type === 'JobFinished' && x.job_id === r.job_id); i++) {
      await new Promise((res) => setTimeout(res, 5));
    }
    const lib = await folder(f);
    // the rows now hold the AIFFs (a new format and name), the tracks are the same ones
    expect(lib.rows.find((x) => x.track_id === 'own:1')?.path).toMatch(/\.aiff?$/i);
    expect(keepTableSelection(sel, before, await keys())).toBe(sel);
  });
});
