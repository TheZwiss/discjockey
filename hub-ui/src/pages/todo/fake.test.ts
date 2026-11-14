// Every To-do fake scenario loads, and the CDJ group and Convert / Rename check ones (issue 33 stage D, plan §6.4 S2)
// hold the data their state needs.
import { describe, expect, it } from 'vitest';
import { createFakeBridge } from '$lib/bridge/fake/bridge';
import { CDJ_IDS } from '$lib/bridge/fake/aiffScenes';
import { isBatch, type Todo, type TodoFilter } from '$lib/bridge/types';
import { scenarios } from './fake';

const bridge = (n: string) => createFakeBridge(`todo:${n}`, { speed: 1000 });
const todo = async (n: string, filter: TodoFilter = 'all') => (await bridge(n).todo(filter, false)) as Todo & { ok: true };
const group = async (n: string, key: string, filter: TodoFilter = 'all') => (await todo(n, filter)).groups.find((g) => g.key === key);

describe('the To-do fake scenarios', () => {
  it('every named scenario loads To-do (all and the CDJ filter) without error', async () => {
    for (const n of Object.keys(scenarios ?? {})) {
      const f = bridge(n);
      expect(await f.todo('all', false), n).toMatchObject({ ok: true });
      expect(await f.todo('cdj', true), n).toMatchObject({ ok: true });
    }
  });

  it('the CDJ group: six files with their short reasons, five that Convert all can run now (Cloud Library Sync waits)', async () => {
    for (const n of ['cdj', 'cdj-item', 'cdj-multi', 'cdj-all']) {
      const g = (await group(n, 'cdj', 'cdj'))!;
      expect(g.items.map((i) => i.track_id), n).toEqual(CDJ_IDS);
      expect(g.all, n).toEqual({ n: 5, k: 1 });
      expect(g.stopped, n).toBeNull();
    }
    const g = (await group('cdj', 'cdj', 'cdj'))!;
    expect(g.items.map((i) => i.detail)).toEqual([
      'FLAC 192 kHz · CDJs stop at 96 kHz', 'WAV 32-bit float · CDJs play 16/24-bit', "Opus · CDJs don't play it",
      'FLAC 176.4 kHz · CDJs stop at 96 kHz', 'AIFF 192 kHz · CDJs stop at 96 kHz', "Vorbis · CDJs don't play it"]);
    expect(g.items.map((i) => i.aiff)).toEqual([null, null, null, 'cloud', null, null]);
  });

  it('a stopped Convert all leaves Resume with the files left and takes the converted ones out of the group', async () => {
    const g = (await group('cdj-resume', 'cdj', 'cdj'))!;
    expect(g.stopped).toEqual({ batch_id: 1, left: 3 });
    expect(g.items.map((i) => i.track_id)).toEqual(['own:15', 'own:16', 'own:17', 'own:18']);
    const batch = (await group('cdj-resume', 'rekordbox_check', 'rekordbox_check'))!.items.filter(isBatch);
    expect(batch.map((b) => b.batch.tracks.map((t) => t.track_id))).toEqual([['own:13', 'own:14']]);
  });

  it('the checks: a Convert with rekordbox, one without, a clean name, and a batch of three converts', async () => {
    const one = (await group('check-converted', 'rekordbox_check', 'rekordbox_check'))!.items.find((i) => i.track_id === 'own:13')!;
    expect(one.check).toMatchObject({ reason: 'converted', rekordbox: { entries: 1 }, old_name: null });
    expect(one.check!.old_path).toMatch(/^Superseded\//);
    const none = (await group('check-converted-no-rekordbox', 'rekordbox_check', 'rekordbox_check'))!.items.find((i) => i.track_id === 'own:20')!;
    expect(none.check).toMatchObject({ reason: 'converted', rekordbox: null });
    const renamed = (await group('check-renamed', 'rekordbox_check', 'rekordbox_check'))!.items.find((i) => i.track_id === 'own:7')!;
    expect(renamed.check).toMatchObject({ reason: 'renamed', old_path: null });
    expect(renamed.check!.old_name).toMatch(/_-_.*\.aiff$/);
    const batch = (await group('check-convert-batch', 'rekordbox_check', 'rekordbox_check'))!.items.filter(isBatch);
    expect(batch).toHaveLength(1);
    expect(batch[0].batch).toMatchObject({ kind: 'convert', size: 3, started_by: 'cdj_all' });
    expect(batch[0].detail).toMatch(/ · Made AIFF$/);
    expect(batch[0].batch.tracks.map((t) => t.track_id)).toEqual(['own:13', 'own:14', 'own:17']);
  });
});
