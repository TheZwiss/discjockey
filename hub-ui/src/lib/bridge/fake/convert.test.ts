// The fake mirrors Convert to AIFF, Give it its clean name, Make all lossless files AIFF and the CDJ group of the real
// bridge (issue 33 stage D). Every shape's keys come from tests/fixtures/hub_convert_shapes.json, which the real hub's
// test (tests/test_hub_api_convert.py) reads too; the behaviours are the ones the plan §5 D6/D7 names.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createFakeBridge } from './bridge';
import { cdjProblem, undoneWords } from './convert';
import type { FakeAudio, FakeState, FakeTrack } from './data';
import type { HubEvent } from '../events';
import type { AiffBatchResult, AiffPlan, Library, Todo, TrackDetail, UndoResult } from '../types';

const SHAPES: Record<string, string[]> = JSON.parse(readFileSync(
  fileURLToPath(new URL('../../../../../tests/fixtures/hub_convert_shapes.json', import.meta.url)), 'utf8'));
const keys = (name: string) => [...SHAPES[name]].sort();
const has = (o: object, name: string) => expect(Object.keys(o).sort()).toEqual(keys(name));

const DIR = '/Volumes/Example/Music';
/** An own file in DIR with the stored facts `audio` (and its extension): `convert-d7-<n>`. */
function own(s: FakeState, n: string, audio: FakeAudio, over: Partial<FakeTrack> = {}): FakeTrack {
  const t: FakeTrack = { ...s.tracks[0], track_id: `d7-${n}`, artist: 'Mira Nacht', title: `Song ${n}`, folder: '', duration_s: 200,
    status: 'lossless', cutoff_hz: null, source: 'manual', codec: 'pcm', in_playlists: false, hidden: false, playlists: [],
    upgrade: null, rekordbox_check: null, other: null, own: true, dir: DIR, away: undefined, file: undefined, audio, ...over };
  s.tracks.push(t);
  return t;
}
const MP3 = (kbps: number): FakeAudio => ({ codec: 'mp3', rate: 44100, bits: null, kbps, ext: 'mp3' });
const FLAC = (rate: number, bits = 24): FakeAudio => ({ codec: 'flac', rate, bits, kbps: null, ext: 'flac' });
const AIFF_CLEAN: FakeAudio = { codec: 'pcm_s16be', rate: 44100, bits: 16, kbps: null, ext: 'aiff', tagsClean: true };

function setup() {
  const evs: HubEvent[] = [];
  const f = createFakeBridge('normal', { speed: 400, emit: (e) => evs.push(e) });
  const s: FakeState = (f as any)._ctx.s;
  s.tracks = s.tracks.filter((t) => t.source !== 'manual');           // only the files this test sets up are own
  const finished = async (id: number) => {
    for (let i = 0; i < 400; i++) {
      const e = evs.find((x) => x.type === 'JobFinished' && x.job_id === id);
      if (e) return e as Extract<HubEvent, { type: 'JobFinished' }>;
      await new Promise((r) => setTimeout(r, 5));
    }
    throw new Error('the job did not finish');
  };
  const run = async (start: Promise<{ ok: boolean; job_id?: number }>) => {
    const r = await start;
    if (!r.ok) throw new Error(JSON.stringify(r));
    return finished(r.job_id!);
  };
  const plan = async (scope: Parameters<typeof f.aiff_plan>[0]) => ((await f.aiff_plan(scope)) as { plan: AiffPlan }).plan;
  const todo = async () => (await f.todo('all', false)) as Todo & { ok: true };
  const group = async (key: string) => (await todo()).groups.find((g) => g.key === key);
  const detail = async (id: string) => ((await f.track(id)) as { track: TrackDetail }).track;
  return { evs, f, s, run, plan, todo, group, detail };
}

describe('the fake bridge: the CDJ rule and the plan', () => {
  it('cdjProblem is the engine rule: only what the CDJ-3000 and the CDJ-2000NXS2 refuse', () => {
    const rule = (a: FakeAudio, ext: string) => cdjProblem(a, ext)?.reason ?? null;
    expect(rule(MP3(320), 'mp3')).toBeNull();
    expect(rule(MP3(321), 'mp3')).toBe('bitrate');
    expect(rule(FLAC(96000), 'flac')).toBeNull();
    expect(rule(FLAC(176400), 'flac')).toBe('rate_high');
    expect(rule({ codec: 'aac', rate: 48000, bits: null, kbps: 256 }, 'm4a')).toBeNull();
    expect(rule({ codec: 'mp3', rate: 96000, bits: null, kbps: 128 }, 'mp3')).toBe('rate_high');
    expect(rule({ codec: 'pcm_s24le', rate: 44100, bits: 24, kbps: null }, 'wav')).toBeNull();
    expect(rule({ codec: 'pcm_f32le', rate: 44100, bits: 32, kbps: null }, 'wav')).toBe('bits');
    expect(rule({ codec: 'opus', rate: 48000, bits: null, kbps: 128 }, 'opus')).toBe('format');
    expect(rule({ codec: 'mp3', rate: null, bits: null, kbps: null }, 'mp3')).toBeNull();   // nothing known never flags
    expect(cdjProblem(MP3(400), 'mp3')!.short).toBe("MP3 400 kbps · CDJs stop at 320");
  });

  it('track().aiff: convert, rename, named already, a blocked file, and no answer for a download', async () => {
    const { f, s, detail } = setup();
    own(s, 'mp3', MP3(400));
    own(s, 'name', AIFF_CLEAN, { file: `${DIR}/Messy [FREE DL].aiff` });
    own(s, 'named', AIFF_CLEAN);
    const mp3 = (await detail('d7-mp3')).aiff!;
    has(mp3, 'track_aiff');
    expect(mp3).toMatchObject({ action: 'convert', why_not: null, kind: 'mp3', to: 'AIFF · 16-bit · 44.1 kHz', lossy: true,
      from: 'MP3 · 44.1 kHz · 400 kbps', name_now: 'Mira Nacht - Song mp3.mp3', new_name: 'Mira Nacht - Song mp3.aiff' });
    expect(mp3.bytes).toBeGreaterThan(0);
    has(mp3.cdj!, 'cdj_words');
    expect((await detail('d7-name')).aiff).toMatchObject({ action: 'rename', kind: 'name', to: null, bytes: 0,
      name_now: 'Messy [FREE DL].aiff', new_name: 'Mira Nacht - Song name.aiff' });
    expect((await detail('d7-named')).aiff).toMatchObject({ action: null, why_not: 'named_already', new_name: null,
      from: 'AIFF · 16-bit · 44.1 kHz', name_now: 'Mira Nacht - Song named.aiff' });
    s.rekordbox_state = 'unreadable';
    // blocked, but still the step's own answer (judged as if rekordbox were not in the way): Becomes, Name and Space show
    const blocked = (await detail('d7-mp3')).aiff!;
    has(blocked, 'track_aiff');
    expect(blocked).toMatchObject({ action: 'convert', why_not: 'rekordbox_unreadable', kind: 'mp3', to: 'AIFF · 16-bit · 44.1 kHz',
      from: 'MP3 · 44.1 kHz · 400 kbps', name_now: 'Mira Nacht - Song mp3.mp3', new_name: 'Mira Nacht - Song mp3.aiff', lossy: true });
    expect(blocked.bytes).toBe(mp3.bytes);
    expect((await detail('d7-name')).aiff).toMatchObject({ action: 'rename', why_not: 'rekordbox_unreadable', kind: 'name', to: null,
      bytes: 0, new_name: 'Mira Nacht - Song name.aiff' });
    expect((await detail('d7-named')).aiff).toMatchObject({ action: null, why_not: 'named_already', new_name: null });   // no action to show
    s.rekordbox_state = undefined;
    s.tracks.find((t) => t.track_id === 'd7-mp3')!.cloud = true;           // Cloud Library Sync: blocked the same way
    expect((await detail('d7-mp3')).aiff).toMatchObject({ action: 'convert', why_not: 'cloud', kind: 'mp3', new_name: 'Mira Nacht - Song mp3.aiff' });
    s.tracks.find((t) => t.track_id === 'd7-mp3')!.cloud = false;
    const download = s.tracks.find((t) => t.source === 'qobuz' && t.status === 'lossless')!;
    expect((await detail(download.track_id)).aiff).toBeNull();
    const up = s.tracks.find((t) => t.upgrade)!;
    expect((await detail(up.track_id)).aiff).toBeNull();                   // the upgrade decision stands
    void f;
  });

  it('aiff_plan: every scope in one shape, kinds in the engine order, space per drive, what waits', async () => {
    const { s, plan } = setup();
    own(s, 'flac', FLAC(192000));
    own(s, 'wav', { codec: 'pcm_s24le', rate: 44100, bits: 24, kbps: null, ext: 'wav' });
    own(s, 'mp3', MP3(400));
    own(s, 'name', AIFF_CLEAN, { file: `${DIR}/Messy.aiff` });
    own(s, 'named', AIFF_CLEAN);
    own(s, 'away', FLAC(44100, 16), { away: 'offline' });
    const sel = await plan({ kind: 'tracks', tracks: ['d7-mp3', 'd7-named', 'd7-away', 'd7-mp3'] });
    has(sel, 'plan'); has(sel.rekordbox, 'plan_rekordbox');
    has(sel.items[0], 'plan_item'); has(sel.skipped[0], 'plan_left'); has(sel.waiting[0], 'plan_waiting');
    has(sel.kinds[0], 'plan_kind'); has(sel.space[0], 'plan_space');
    expect(sel.scope).toEqual({ kind: 'tracks', tracks: ['d7-mp3', 'd7-named', 'd7-away'], label: 'Selection' });   // each song once
    expect(sel.items.map((i) => i.track)).toEqual(['d7-mp3']);              // a track listed twice counts once
    expect(sel.skipped.map((l) => [l.track, l.reason])).toEqual([['d7-named', 'named_already'], ['d7-away', 'away']]);
    expect(sel.waiting.map((w) => [w.reason, w.n])).toEqual([['away', 1]]);
    expect([sel.total, sel.lossy, sel.rekordbox.needs_closed]).toEqual([1, 1, true]);
    // the lossless files of All tracks: the lossy MP3 is not in; kinds in the panel's order
    const all = await plan({ kind: 'lossless', view: 'all', key: null });
    expect(all.scope).toMatchObject({ kind: 'lossless', view: 'all', label: expect.any(String) });
    expect(all.items.map((i) => i.track).sort()).toEqual(['d7-flac', 'd7-name', 'd7-wav']);
    expect(all.kinds.map((k) => [k.kind, k.label, k.n])).toEqual([['flac', 'FLAC → AIFF', 1], ['wav', 'WAV → AIFF', 1],
      ['name', 'Clean name only', 1]]);
    expect(all.skipped).toEqual([]);                                        // skipped is for a selection only
    expect(all.waiting.map((w) => w.reason)).toEqual(['away']);             // but what waits is counted in every scope
    expect(all.lossy).toBe(0);
    expect(all.space).toEqual([{ drive: '/Users/you/Music/Discjockey', needed: expect.any(Number), free: 400_000_000_000, enough: true },
      { drive: '/Volumes/Example', needed: expect.any(Number), free: 400_000_000_000, enough: true }]);
    // a short drive
    s.freeBytes = { '/Volumes/Example': 1000 };
    expect((await plan({ kind: 'lossless', view: 'all', key: null })).space.find((d) => d.drive === '/Volumes/Example'))
      .toMatchObject({ free: 1000, enough: false });
    // the CDJ group is the same files the To-do group lists
    expect((await plan({ kind: 'cdj' })).items.map((i) => i.track).sort()).toEqual(['d7-flac', 'd7-mp3']);
    expect(await plan({ kind: 'cdj' })).toMatchObject({ scope: { kind: 'cdj', label: "Won't play well on CDJs" } });
  });

  it('bad scopes are refused like the real bridge', async () => {
    const { f } = setup();
    for (const bad of [null, 'cdj', {}, { kind: 'all' }, { kind: 'tracks', tracks: [] }, { kind: 'tracks', tracks: 'a' },
      { kind: 'lossless', view: 'elsewhere' }, { kind: 'lossless', view: 'playlist' }]) {
      expect(await f.aiff_plan(bad as never), JSON.stringify(bad)).toMatchObject({ ok: false, kind: 'refused' });
    }
    expect(await f.make_aiff({ kind: 'tracks', tracks: ['a'] } as never)).toMatchObject({ ok: false, kind: 'refused' });
    expect(await f.convert([], 'library')).toMatchObject({ ok: false, kind: 'refused' });
    expect(await f.convert(['a'], 'sync' as never)).toMatchObject({ ok: false, kind: 'refused' });
  });
});

describe('the fake bridge: the CDJ group in To-do', () => {
  it('lists the flagged own files with their problem and Convert answer; the group carries all {n, k} and stopped', async () => {
    const { f, s, todo, group } = setup();
    own(s, 'mp3', MP3(400));
    own(s, 'flac', FLAC(192000), { away: 'offline' });
    own(s, 'ok', MP3(320));
    own(s, 'hid', MP3(400), { hidden: true });
    const t = await todo();
    expect(t.chips.cdj).toBe(2);
    expect(t.chips.all).toBeGreaterThanOrEqual(2);
    // a hidden member is counted as hidden and listed only with Show hidden
    const shown = (await f.todo('cdj', true)) as Todo & { ok: true };
    expect(shown.groups[0].items.map((i) => i.track_id)).toEqual(['d7-mp3', 'd7-flac', 'd7-hid']);
    expect(shown.hidden_count).toBe(t.hidden_count);
    expect(shown.chips.cdj).toBe(2);
    const g = (await group('cdj'))!;
    expect(g).toMatchObject({ label: "Won't play well on CDJs", hint: 'CDJs refuse or stutter on these files', stopped: null });
    has(g.all!, 'cdj_group_all');
    expect(g.all).toEqual({ n: 1, k: 1 });                                  // the away file waits
    expect(g.items.map((i) => i.track_id)).toEqual(['d7-mp3', 'd7-flac']);
    expect(Object.keys(g.items[0])).toEqual(expect.arrayContaining(SHAPES.cdj_item_extra));
    has(g.items[0].cdj!, 'cdj_why');
    expect(g.items.map((i) => [i.detail === i.cdj!.short, i.aiff, i.file_state])).toEqual([[true, null, 'here'], [true, 'away', 'offline']]);
  });

  it('Convert all runs the group as one batch from To-do; its files leave the group and the batch is one check item', async () => {
    const { f, s, run, group, todo } = setup();
    own(s, 'mp3', MP3(400));
    own(s, 'flac', FLAC(192000));
    const done = await run(f.make_aiff({ kind: 'cdj' }));
    expect(done).toMatchObject({ kind: 'aiff_batch', ok: true });
    const r = done.result as AiffBatchResult;
    has(r, 'batch_result'); has(r.results[0], 'item_result');
    expect(r).toMatchObject({ state: 'done', total: 2, done: 2, skipped: 0 });
    expect(r.results.map((i) => [i.track, i.action, i.state])).toEqual([['d7-mp3', 'convert', 'done'], ['d7-flac', 'convert', 'done']]);
    expect(await group('cdj')).toBeUndefined();                             // an AIFF now: CDJs play it
    const item = (await group('rekordbox_check'))!.items[0];
    expect(item.detail).toMatch(/ · Made AIFF$/);
    has(item.batch!, 'batch');
    expect(item.batch).toMatchObject({ size: 2, started_by: 'cdj_all', kind: 'convert' });
    has(item.batch!.tracks[0].check!, 'check_view');
    expect(item.batch!.tracks[0].check).toMatchObject({ reason: 'converted', old_name: null,
      old_path: 'Superseded/Mira Nacht - Song mp3.mp3' });
    expect(item.batch!.tracks[0].detail).toBe('an AIFF now: nothing to redo');
    expect((await todo()).chips.cdj).toBe(0);
  });

  it('Resume on the group is a stopped Convert all, and Upgrade ready shows none of it', async () => {
    const { f, s, run, group, plan } = setup();
    own(s, 'mp3', MP3(400));
    own(s, 'flac', FLAC(192000));
    s.rekordbox_running = true;
    const stopped = await run(f.make_aiff({ kind: 'cdj' }));
    expect(stopped).toMatchObject({ ok: false, problem: 'rekordbox_open' });
    const r = stopped.result as AiffBatchResult;
    expect([r.state, r.stop_reason, r.done]).toEqual(['stopped', 'rekordbox_open', 0]);
    const g = (await group('cdj'))!;
    has(g.stopped!, 'stopped');
    expect(g.stopped).toEqual({ batch_id: r.batch, left: 2 });
    expect((await group('upgrade_ready'))?.stopped ?? null).toBeNull();
    expect(((await f.library('all', null, '', 'all', null)) as Library & { ok: true }).aiff_stopped).toBeNull();   // scope todo:cdj
    s.rekordbox_running = false;
    const resumed = await run(f.batch_resume(r.batch!));
    expect(resumed).toMatchObject({ kind: 'batch_resume', ok: true });
    const snap = async () => ((await f.job_status()) as { job: { kind: string; batch_kind: string | null } }).job;
    expect(await snap()).toMatchObject({ kind: 'batch_resume', batch_kind: 'convert' });   // a reload tells whose batch it was
    expect((await group('cdj'))).toBeUndefined();
    expect((await plan({ kind: 'cdj' })).total).toBe(0);
  });
});

describe('the fake bridge: Convert, Rename and Make all', () => {
  it('convert on a selection: the songs left out come back as skipped results; Rename leaves what needs a Convert', async () => {
    const { f, s, run, plan, group } = setup();
    own(s, 'mp3', MP3(128));
    own(s, 'name', AIFF_CLEAN, { file: `${DIR}/Messy.aiff` });
    own(s, 'named', AIFF_CLEAN);
    const r = (await run(f.convert(['d7-mp3', 'd7-name', 'd7-named']))).result as AiffBatchResult;
    expect(r).toMatchObject({ state: 'done', total: 3, done: 2, skipped: 1 });
    expect(r.results.map((i) => [i.track, i.action, i.state, i.reason])).toEqual([['d7-mp3', 'convert', 'done', null],
      ['d7-name', 'rename', 'done', null], ['d7-named', 'convert', 'skipped', 'named_already']]);
    expect(r.results[2].message).toBe('A clean AIFF with its clean name already.');
    expect(r.results[0].path).toBe(`${DIR}/Mira Nacht - Song mp3.aiff`);
    expect(r.results[1].path).toBe(`${DIR}/Mira Nacht - Song name.aiff`);
    const checks = (await group('rekordbox_check'))!.items[0].batch!.tracks;
    expect(checks.map((t) => [t.check!.reason, t.check!.old_name, t.detail])).toEqual([['converted', null, 'an AIFF now: nothing to redo'],
      ['renamed', 'Messy.aiff', 'clean name now']]);
    expect(checks[1].check!.old_path).toBeNull();
    expect((await plan({ kind: 'lossless', view: 'all', key: null })).total).toBe(0);   // nothing left to make
    // Rename alone
    own(s, 'mp3b', MP3(128));
    own(s, 'nameb', AIFF_CLEAN, { file: `${DIR}/Other.aiff` });
    const ren = (await run(f.rename(['d7-mp3b', 'd7-nameb']))).result as AiffBatchResult;
    expect(ren.results.map((i) => [i.track, i.state, i.reason])).toEqual([['d7-nameb', 'done', null], ['d7-mp3b', 'skipped', 'needs_convert']]);
  });

  it('refusals carry the engine words: one song its own, several the general sentence, make_aiff "nothing to change"', async () => {
    const { f, s, run } = setup();
    own(s, 'named', AIFF_CLEAN);
    own(s, 'named2', AIFF_CLEAN);
    const one = await run(f.convert(['d7-named']));
    expect(one).toMatchObject({ ok: false, problem: 'refused', message: 'A clean AIFF with its clean name already.' });
    expect((one.result as AiffBatchResult)).toMatchObject({ batch: null, state: 'done', total: 1, skipped: 1 });
    expect(await run(f.convert(['d7-named', 'd7-named2']))).toMatchObject({ problem: 'refused', message: 'None of these can be changed right now.' });
    const all = await run(f.make_aiff({ kind: 'lossless', view: 'all', key: null }));
    expect(all).toMatchObject({ ok: false, problem: 'refused', message: 'Nothing to change: these are clean AIFFs already.' });
    expect((all.result as AiffBatchResult)).toMatchObject({ batch: null, total: 0 });
    const down = s.tracks.find((t) => t.source === 'qobuz' && t.status === 'lossless')!;
    expect(await run(f.convert([down.track_id]))).toMatchObject({ problem: 'refused', message: expect.stringContaining('downloaded this file') });
  });

  it('one song alone meets an open rekordbox: closed, no Resume; several stop and offer it in the Library', async () => {
    const { f, s, run, plan } = setup();
    own(s, 'a', FLAC(44100, 16));
    own(s, 'b', FLAC(44100, 16));
    s.rekordbox_running = true;
    expect((await plan({ kind: 'tracks', tracks: ['d7-a'] })).rekordbox).toEqual({ state: 'ready', running: true, needs_closed: true });
    const alone = await run(f.convert(['d7-a']));
    expect(alone).toMatchObject({ ok: false, problem: 'rekordbox_open' });
    expect((alone.result as AiffBatchResult).state).toBe('done');
    const many = await run(f.make_aiff({ kind: 'lossless', view: 'all', key: null }));
    expect(many).toMatchObject({ ok: false, problem: 'rekordbox_open' });
    const lib = (await f.library('all', null, '', 'all', null)) as Library & { ok: true };
    expect(lib.aiff_stopped).toEqual({ batch_id: (many.result as AiffBatchResult).batch, left: 2 });
    has(lib.aiff_stopped!, 'stopped');
    // a file rekordbox doesn't hold runs while it is open
    s.tracks.find((t) => t.track_id === 'd7-a')!.inRekordbox = false;
    s.tracks.find((t) => t.track_id === 'd7-b')!.inRekordbox = false;
    expect((await run(f.convert(['d7-a', 'd7-b']))).result).toMatchObject({ state: 'done', done: 2 });
  });

  it('Stop ends a batch between files; Resume does the rest; undo says what came back and puts the files back', async () => {
    const { f, s, run, evs, detail } = setup();
    s.batchStep = 2000;
    own(s, 'a', FLAC(44100, 16));
    own(s, 'b', FLAC(44100, 16));
    own(s, 'c', AIFF_CLEAN, { file: `${DIR}/Messy.aiff` });
    const start = f.make_aiff({ kind: 'lossless', view: 'all', key: null });
    for (let i = 0; i < 400 && !evs.some((e) => e.type === 'BatchProgress'); i++) await new Promise((x) => setTimeout(x, 1));
    expect(await f.stop()).toMatchObject({ ok: true, stopped: true });
    const stopped = await run(start);
    expect(stopped).toMatchObject({ ok: false, problem: 'stopped' });
    const sr = stopped.result as AiffBatchResult;
    expect(sr).toMatchObject({ state: 'stopped', stop_reason: 'stop', total: 3 });
    const left = sr.results.filter((i) => i.state === 'planned').length;
    expect(left).toBeGreaterThan(0);
    const lib = (await f.library('all', null, '', 'all', null)) as Library & { ok: true };
    expect(lib.aiff_stopped).toEqual({ batch_id: sr.batch, left });
    const resumed = (await run(f.batch_resume(sr.batch!))).result as AiffBatchResult;
    expect(resumed).toMatchObject({ state: 'done', total: 3, done: 3 });
    // Undo on one track says the engine's words and puts its old file back
    const one = (await run(f.undo_upgrade(['d7-a']))).result as UndoResult;
    expect(one).toMatchObject({ undone: 1, words: 'Conversion undone. Your old file is back.' });
    expect((await detail('d7-a')).aiff).toMatchObject({ action: 'convert', name_now: 'Mira Nacht - Song a.flac' });
    const rn = (await run(f.undo_upgrade(['d7-c']))).result as UndoResult;
    expect(rn.words).toBe('Clean name undone. Your old name is back.');
    const rest = (await run(f.batch_undo(sr.batch!))).result as UndoResult;
    has(rest, 'undo_result_success');
    expect(rest.words).toBe('Conversion undone. Your old file is back.');
  });

  it('the words of an undo follow the checks it undid', () => {
    expect(undoneWords(['converted'])).toBe('Conversion undone. Your old file is back.');
    expect(undoneWords(['renamed'])).toBe('Clean name undone. Your old name is back.');
    expect(undoneWords(['swapped'])).toBe('Upgrade undone. Your old file is back.');
    expect(undoneWords(['converted', 'swapped'])).toBe('Undone. Your old files are back.');
    expect(undoneWords(['renamed', 'renamed'])).toBe('Undone. Your old names are back.');
    expect(undoneWords(['converted', 'renamed'])).toBe('Undone. Your old files and names are back.');
  });

  it('a song that changed under the batch is skipped with the run-time reason', async () => {
    const { f, s, run } = setup();
    own(s, 'a', MP3(128));
    own(s, 'b', MP3(128));
    s.batchSkip = { 'd7-b': 'not_analysed' };
    const r = (await run(f.convert(['d7-a', 'd7-b']))).result as AiffBatchResult;
    expect(r.results.map((i) => [i.track, i.state, i.reason])).toEqual([['d7-a', 'done', null], ['d7-b', 'skipped', 'not_analysed']]);
  });

  it('a seeded batch is there from the start: a stopped Make all is the Library header\'s Resume and resumes', async () => {
    const f = createFakeBridge('normal', { speed: 400, prepare: (s) => {
      s.tracks = s.tracks.filter((t) => t.source !== 'manual');
      own(s, 'a', FLAC(44100, 16));
      own(s, 'b', FLAC(44100, 16));
      s.batches = [{ kind: 'convert', scope: 'library:all', state: 'stopped', started_by: 'make_aiff',
        items: [{ track: 'd7-a', action: 'convert', state: 'done' }, { track: 'd7-b', action: 'convert', state: 'planned' }] }];
    } });
    const lib = (await f.library('all', null, '', 'all', null)) as Library & { ok: true };
    expect(lib.aiff_stopped).toEqual({ batch_id: 1, left: 1 });
    expect(((await f.todo('all', false)) as Todo & { ok: true }).groups.find((g) => g.key === 'upgrade_ready')?.stopped ?? null).toBeNull();
    expect(await f.batch_resume(1)).toMatchObject({ ok: true });
  });
});
