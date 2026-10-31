// Which decision a track's details show (the Library's panel, as To-do's), and that the fake backend answers the
// decisions' calls made from the Library: replace → the check with its undo → undo → the upgrade again; Keep the file
// that stays. The words and choices themselves are pinned in pages/todo/todoModel.test.ts (they re-export from here).
import { describe, expect, it } from 'vitest';
import type { DuplicateItem, FileSide, TodoItem, TrackDetail, Upgrade } from '$lib/bridge/types';
import { createFakeBridge } from '$lib/bridge/fake/bridge';
import type { HubEvent } from '$lib/bridge/events';
import { canSwap, decisionFor } from './decisionModel';

const item = (id: string, extra: Partial<TodoItem> = {}): TodoItem => ({
  track_id: id, artist: 'A', title: id, folder: 'Hard_Bounce', duration_s: 200, status: 'not_lossless', quality: 'weak',
  quality_label: '16.0 kHz', cutoff_hz: 16000, source: 'youtube', source_name: 'YouTube', in_playlists: true, own: false,
  hidden: false, upgrade_ready: false, path: `Library/Hard_Bounce/A - ${id}.aiff`, added: null, cover_url: null,
  group: 'weak', detail: '', free: false, ...extra });
const side = (file_id: number, song_key: string | null, path: string): FileSide => ({ file_id, song_key, path, artist: 'A',
  title: 'x', duration_s: 200, quality: 'lossless', quality_label: 'LOSSLESS', online: true, audio_url: null,
  in_playlist: false });
const dup = (files: FileSide[]): DuplicateItem => ({ ...item('dup:1-2', { group: 'duplicate' }), group: 'duplicate',
  pair: { group_id: 'dup:1-2', why: 'same_audio', files, recommended: null, recommended_why: null } });
const up = { swap_safe: true, swap_possible: true } as Upgrade;
const track = (id: string, extra: { path?: string | null; upgrade?: Upgrade | null } = {}) =>
  ({ track_id: id, path: `Library/Hard_Bounce/A - ${id}.aiff`, upgrade: null, ...extra });

describe('the decision a track waits for', () => {
  it('the rekordbox check a replace left, from the to-do list', () => {
    const check = item('t2', { group: 'rekordbox_check', can_undo: true });
    expect(decisionFor([item('t1'), check], track('t2'))).toEqual({ kind: 'check', item: check });
  });
  it('a duplicate group one of its files is in, by its song or its path', () => {
    const g = dup([side(1, 't7', 'Library/Hard_Bounce/A - t7.aiff'), side(2, 'local:2', '/Volumes/X/Music/A - t7.aiff')]);
    expect(decisionFor([g], track('t7', { path: null }))).toEqual({ kind: 'duplicate', item: g });
    expect(decisionFor([g], track('local:9', { path: '/Volumes/X/Music/A - t7.aiff' }))).toEqual({ kind: 'duplicate', item: g });
    expect(decisionFor([g], track('t8'))).toBeNull();
  });
  it('the upgrade from the details, also for a track the to-do list does not show', () => {
    expect(decisionFor([], track('t2', { upgrade: up }))).toEqual({ kind: 'upgrade' });
    expect(decisionFor([item('t2', { group: 'upgrade_ready' })], track('t2', { upgrade: up }))).toEqual({ kind: 'upgrade' });
  });
  it('in the to-do list\'s order: the check and the duplicates before the upgrade; nothing else is a decision', () => {
    const g = dup([side(1, 't2', 'a.aiff'), side(2, null, 'b.aiff')]);
    expect(decisionFor([g], track('t2', { upgrade: up }))?.kind).toBe('duplicate');
    expect(decisionFor([item('t2', { group: 'rekordbox_check' }), g], track('t2'))?.kind).toBe('check');
    expect(decisionFor([item('t2', { group: 'weak' }), item('t2', { group: 'not_found' })], track('t2'))).toBeNull();
  });
  it('Same track only with an AIFF file and the same edit', () => {
    expect(canSwap(up)).toBe(true);
    expect(canSwap({ ...up, swap_possible: false })).toBe(false);
    expect(canSwap({ ...up, swap_safe: false })).toBe(false);
    expect(canSwap(null)).toBe(false);
  });
});

describe('the fake backend answers the decisions made from the Library', () => {
  const finished = (evs: HubEvent[], job_id: number, ms = 4000) => new Promise<void>((resolve, reject) => {
    const t0 = Date.now();
    const tick = () => {
      if (evs.some((e) => e.type === 'JobFinished' && e.job_id === job_id)) return resolve();
      if (Date.now() - t0 > ms) return reject(new Error('timeout'));
      setTimeout(tick, 5);
    };
    tick();
  });
  const fake = (scenario: string) => {
    const evs: HubEvent[] = [];
    return { evs, f: createFakeBridge(scenario, { speed: 200, emit: (e) => evs.push(e) }) };
  };
  const at = async (f: ReturnType<typeof fake>['f'], id: string) => {
    const [t, todo] = await Promise.all([f.track(id), f.todo('all', true)]);
    if (!t.ok || !todo.ok) throw new Error('read failed');
    return { t: t.track as TrackDetail, d: decisionFor(todo.groups.flatMap((g) => g.items), t.track) };
  };
  const job = async (evs: HubEvent[], start: Promise<{ ok: boolean; job_id?: number }>) => {
    const r = await start;
    if (!r.ok || r.job_id === undefined) throw new Error(JSON.stringify(r));
    await finished(evs, r.job_id);
  };

  it('replace → the check with its undo → undo → the upgrade again', async () => {
    const { evs, f } = fake('todo:upgrade-aiff-same');
    expect((await at(f, 't2')).d).toEqual({ kind: 'upgrade' });
    await job(evs, f.upgrade('t2', 'swap'));
    const after = await at(f, 't2');
    expect(after.t.upgrade).toBeNull();
    expect(after.d?.kind).toBe('check');
    if (after.d?.kind !== 'check') return;
    expect(after.d.item.check?.reason).toBe('swapped');
    expect(after.d.item.can_undo).toBe(true);
    await job(evs, f.undo_upgrade('t2'));
    expect((await at(f, 't2')).d).toEqual({ kind: 'upgrade' });
  });
  it('a Library track in a duplicate group: keeping it moves the other file away and the decision goes', async () => {
    const { evs, f } = fake('todo_duplicates');
    const before = await at(f, 't7');
    expect(before.d?.kind).toBe('duplicate');
    if (before.d?.kind !== 'duplicate') return;
    const g = before.d.item.pair;
    const other = g.files.find((x) => x.song_key !== 't7')!;
    await job(evs, f.supersede_duplicate(g.group_id, other.file_id, g.files.map((x) => x.path)));
    expect((await at(f, 't7')).d).toBeNull();
  });
});
