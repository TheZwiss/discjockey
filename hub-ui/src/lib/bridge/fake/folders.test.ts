import { describe, expect, it } from 'vitest';
import { createFakeBridge } from './bridge';
import type { HubEvent } from '../events';
import type { QuestionItem, DuplicateItem, Todo } from '../types';

const until = (evs: HubEvent[], pred: (e: HubEvent) => boolean, ms = 4000) => new Promise<HubEvent>((resolve, reject) => {
  const t0 = Date.now();
  const tick = () => {
    const hit = evs.find(pred);
    if (hit) return resolve(hit);
    if (Date.now() - t0 > ms) return reject(new Error('timeout'));
    setTimeout(tick, 5);
  };
  tick();
});
const finished = (evs: HubEvent[], job_id: number) =>
  until(evs, (e) => e.type === 'JobFinished' && e.job_id === job_id) as Promise<Extract<HubEvent, { type: 'JobFinished' }>>;
const fake = (scenario: string, speed = 200) => {
  const evs: HubEvent[] = [];
  return { evs, f: createFakeBridge(scenario, { speed, emit: (e) => evs.push(e) }) };
};
const must = <T extends { ok: boolean }>(r: T): Extract<T, { ok: true }> => {
  if (!r.ok) throw new Error(JSON.stringify(r));
  return r as Extract<T, { ok: true }>;
};
const items = (t: Todo, key: string) => t.groups.find((g) => g.key === key)?.items ?? [];

describe('fake watched folders', () => {
  it('lists the Library first and the import folders with their states', async () => {
    const normal = must(await fake('normal').f.watched_folders());
    expect(normal.folders.map((r) => [r.kind, r.name, r.state])).toEqual([['library', 'Library', 'online'], ['import', 'Music', 'online']]);
    expect(normal.stopped).toBe(false);
    const only = must(await fake('folders_library_only').f.watched_folders());
    expect(only.folders.map((r) => r.kind)).toEqual(['library']);
    const offline = must(await fake('folders_offline').f.watched_folders());
    expect(offline.folders.map((r) => r.state)).toEqual(['online', 'online', 'offline']);
    expect(offline.waiting).toBe(0);
    const bad = must(await fake('folders_couldnt_read').f.watched_folders());
    expect(bad.unreadable).toHaveLength(3);
    expect(bad.unreadable[0]).toMatchObject({ folder_id: bad.folders[1].id, reason: "macOS doesn't let Discjockey read it" });
    expect(bad.folders[1].unreadable).toBe(3);
  });

  it('checks a folder in the engine\'s words', async () => {
    const { f } = fake('normal');
    const check = async (path: string) => must(await f.check_import_folder(path));
    expect(await check('/Users/you/Music/Discjockey/Library')).toMatchObject({ usable: false, problem: 'music',
      message: 'This is inside your music folder, which Discjockey watches already.' });
    expect(await check('/Users/you/Music')).toMatchObject({ problem: 'holds_music',
      message: 'This folder holds your music folder. Choose a folder inside it instead.' });
    expect(await check('/Volumes/Example Drive/Music/Sub')).toMatchObject({ problem: 'watched',
      message: 'This is inside Music, which Discjockey watches already.' });
    expect(await check('/Volumes/Example Drive/Music')).toMatchObject({ problem: 'already',
      message: 'Discjockey watches this folder already.' });
    expect(await check('/Volumes/Gone/Missing')).toMatchObject({ problem: 'not_found', exists: false });
    expect(await check('Music')).toMatchObject({ problem: 'not_absolute' });
    expect(await check('/Volumes/Example Drive')).toMatchObject({ usable: true, kind: 'import',
      merges: ['/Volumes/Example Drive/Music'], merge_hints: ['Music is inside it and becomes part of it.'] });
    expect(await check('/Volumes/Other/Crates')).toMatchObject({ usable: true, problem: null, message: null, merges: [] });
  });

  it('adds a folder and imports it, with ImportProgress through the four phases', async () => {
    const { f, evs } = fake('folders_library_only');
    const before = must(await f.watched_folders());
    const start = must(await f.add_watched_folder('/Volumes/Other/Crates'));
    const done = await finished(evs, start.job_id);
    expect(done).toMatchObject({ kind: 'import', ok: true, message: 'Imported 180 files.' });
    expect(done.result).toMatchObject({ files: 180, left: 0, stopped: false, link_note: null });
    const phases = evs.filter((e) => e.type === 'ImportProgress').map((e) => (e as { phase: string }).phase);
    expect([...new Set(phases)]).toEqual(['scan', 'tags', 'sound', 'link']);
    const last = evs.filter((e) => e.type === 'ImportProgress' && e.phase === 'sound').at(-1) as { done: number; total: number };
    expect(last.done).toBe(last.total);
    const after = must(await f.watched_folders());
    expect(after.folders.map((r) => [r.name, r.state, r.files, r.waiting])).toEqual([['Library', 'online', before.folders[0].files, 0], ['Crates', 'online', 180, 0]]);
    const refused = await f.add_watched_folder('/Volumes/Other/Crates');
    expect(refused).toMatchObject({ ok: false, kind: 'refused', message: 'Discjockey watches this folder already.' });
  });

  it('answers busy with the import words while it runs, and Stop ends it with what is left', async () => {
    const { f, evs } = fake('folders_library_only', 20);
    const start = must(await f.add_watched_folder('/Volumes/Other/Crates'));
    await until(evs, (e) => e.type === 'ImportProgress' && e.phase === 'tags' && e.done > 0);
    for (const answer of [await f.start_import(), await f.hide('t2', true), await f.setup_skip_import()]) {
      expect(answer).toMatchObject({ ok: false, kind: 'busy', message: 'Discjockey is importing your music. Stop the import in '
        + 'Settings → Watched folders to do this now; it carries on later where it stopped.' });
    }
    expect(must(await f.watched_folders()).folders[1].state).toBe('importing');
    expect(must(await f.stop()).stopped).toBe(true);
    const done = await finished(evs, start.job_id);
    expect(done).toMatchObject({ ok: false, problem: 'stopped' });
    const result = done.result as { stopped: boolean; left: number };
    expect(result.stopped).toBe(true);
    expect(done.message).toBe(`Import stopped with ${result.left} files to go. It carries on where it stopped.`);
    const rows = must(await f.watched_folders());
    expect(rows.stopped).toBe(true);
    expect(rows.folders[1]).toMatchObject({ state: 'online', waiting: result.left });
    const again = must(await f.start_import());
    const second = await finished(evs, again.job_id);
    expect(second).toMatchObject({ ok: true });
    expect(must(await f.watched_folders())).toMatchObject({ stopped: false, waiting: 0 });
  });

  it('starts folders_importing half way through and holds there until Stop', async () => {
    const { f, evs } = fake('folders_importing');
    const status = must(await f.job_status());
    expect(status.job).toMatchObject({ kind: 'import', running: true });
    expect(status.job!.last.ImportProgress).toMatchObject({ phase: 'tags', done: 340, total: 1500 });
    const rows = must(await f.watched_folders());
    expect(rows.folders.map((r) => r.state)).toEqual(['online', 'importing', 'online']);
    await new Promise((r) => setTimeout(r, 100));
    expect(evs.filter((e) => e.type === 'ImportProgress').every((e) => (e as { done: number }).done === 340)).toBe(true);
    must(await f.stop());
    const done = await finished(evs, status.job!.id);
    expect(done).toMatchObject({ ok: false, problem: 'stopped', result: { stopped: true, files: 340, left: 1500 } });
  });

  it('removes a folder, with its counts, and refuses the Library', async () => {
    const { f, evs } = fake('normal');
    const rows = must(await f.watched_folders()).folders;
    expect(must(await f.removal_preview(rows[1].id))).toMatchObject({ name: 'Music', files: 1240, redownload: 4 });
    for (const bad of [rows[0].id, 99, '2' as unknown as number]) {
      expect(await f.removal_preview(bad)).toMatchObject({ ok: false, kind: 'refused', message: "That folder isn't one of the watched folders." });
      expect(await f.remove_watched_folder(bad)).toMatchObject({ ok: false, kind: 'refused' });
    }
    const start = must(await f.remove_watched_folder(rows[1].id));
    expect(await finished(evs, start.job_id)).toMatchObject({ kind: 'folders', ok: true, result: { files: 1240, redownload: 4 } });
    expect(must(await f.watched_folders()).folders.map((r) => r.kind)).toEqual(['library']);
  });

  it('takes over the folders inside a new one', async () => {
    const { f, evs } = fake('normal');
    const library = must(await f.watched_folders()).folders[0].files;
    const start = must(await f.add_watched_folder('/Volumes/Example Drive'));
    await finished(evs, start.job_id);
    const rows = must(await f.watched_folders()).folders;
    expect(rows.map((r) => [r.name, r.files])).toEqual([['Library', library], ['Example Drive', 1240 + 180]]);
  });
});

describe('fake To-do of the import', () => {
  it('lists the questions as a group with the engine\'s why lines', async () => {
    const t = must(await fake('todo_same_song').f.todo('all', false));
    expect(t.groups.map((g) => g.key).slice(0, 3)).toEqual(['rekordbox_check', 'same_song', 'upgrade_ready']);
    expect(t.chips).toMatchObject({ same_song: 5, duplicate: 0 });
    const qs = items(t, 'same_song') as QuestionItem[];
    expect(qs.map((q) => q.detail).sort()).toEqual([
      'Same artist and title, 4 s longer', 'Same artist and title, 8 s shorter',
      "Same artist and title, the length couldn't be read", 'Same title, different artist',
      'Same title, no artist in your file']);
    const q = qs.find((x) => x.pair.why === 'length' && x.pair.delta_s === 4)!;
    expect(q.pair.file).toMatchObject({ song_key: 'local:103', quality: 'weak', in_playlist: false, audio_url: null });
    expect(q.pair.track).toMatchObject({ title: 'Kick it Hard', folder: 'Hard_Bounce', duration_s: 188 });
    expect(must(await fake('todo_same_song').f.sidebar()).todo).toBe(t.chips.all);
  });

  it('answers a question: it leaves the list and the sync preview', async () => {
    const { f, evs } = fake('sync_waiting_answers');
    expect(must(await f.sync_preview())).toMatchObject({ waiting_answers: 2, deferred_checks: 40 });
    const [q] = items(must(await f.todo('all', false)), 'same_song') as QuestionItem[];
    const start = must(await f.answer_same_song(q.pair.song_key, q.pair.own_key, true));
    expect(await finished(evs, start.job_id)).toMatchObject({ kind: 'answer', ok: true, result: {} });
    expect(must(await f.sync_preview()).waiting_answers).toBe(1);
    const stale = must(await f.answer_same_song(q.pair.song_key, q.pair.own_key, false));
    expect(await finished(evs, stale.job_id)).toMatchObject({ ok: false, problem: 'changed' });
    expect(await f.answer_same_song(1 as unknown as string, 'local:1', true)).toMatchObject({ ok: false, kind: 'refused' });
  });

  it('shows a group of three as one item, and "Keep all" answers every file of it', async () => {
    const { f, evs } = fake('todo_duplicates_three');
    const t = must(await f.todo('all', false));
    const ds = items(t, 'duplicate') as DuplicateItem[];
    expect(ds.map((d) => [d.pair.why, d.pair.files.length, d.detail])).toEqual([
      ['same_audio', 3, 'The same audio in 3 files'], ['same_song', 2, '2 files of the same song']]);
    expect(ds[1].pair.files.find((x) => x.in_playlist)!.audio_url).toMatch(/^data:|^blob:/);
    const start = must(await f.keep_duplicates(ds[0].pair.group_id));
    await finished(evs, start.job_id);
    const after = must(await f.todo('all', false));
    expect((items(after, 'duplicate') as DuplicateItem[]).map((d) => d.pair.files.length)).toEqual([2]);
    expect(after.chips.duplicate).toBe(1);
  });

  it('moves one duplicate to Superseded: the group goes when one file is left', async () => {
    const { f, evs } = fake('todo_duplicates');
    const pair = (items(must(await f.todo('all', false)), 'duplicate') as DuplicateItem[])
      .find((d) => d.pair.why === 'same_song')!.pair;
    const own = pair.files.find((x) => !x.in_playlist)!;
    const start = must(await f.supersede_duplicate(pair.group_id, own.file_id));
    const done = await finished(evs, start.job_id);
    expect(done).toMatchObject({ kind: 'supersede', ok: true });
    expect((done.result as { result: { section: string; path: string } }).result)
      .toMatchObject({ section: 'replaced', path: 'Superseded/Music/Rave Kollektiv - Bis zum Morgen.aiff' });
    expect(must(await f.todo('all', false)).chips.duplicate).toBe(1);
    const again = must(await f.supersede_duplicate(pair.group_id, own.file_id));
    expect(await finished(evs, again.job_id)).toMatchObject({ ok: false, problem: 'changed' });
    expect(await f.keep_duplicates('nope')).toMatchObject({ ok: false, kind: 'refused' });
  });

  it('marks files whose sound is not checked as checked in the Library rows', async () => {
    const lib = must(await fake('normal').f.library(null, '', 'all', 'artist'));
    expect(lib.rows.every((r) => r.sound_checked === true)).toBe(true);
  });
});

describe('fake Setup step "Your existing music"', () => {
  it('is done by a folder or a skip and never changes the required steps', async () => {
    const empty = must(await fake('setup_existing_empty').f.setup_status());
    expect(empty).toMatchObject({ existing: false, import_folders: 0, import_skipped: false });
    const added = must(await fake('setup_existing_added').f.setup_status());
    expect(added).toMatchObject({ existing: true, import_folders: 1, import_skipped: false });
    expect(added.next_step).toBe(empty.next_step);
    const { f } = fake('setup_existing_empty');
    expect(await f.setup_skip_import()).toEqual({ ok: true });
    expect(must(await f.setup_status())).toMatchObject({ existing: true, import_folders: 0, import_skipped: true });
  });
});
