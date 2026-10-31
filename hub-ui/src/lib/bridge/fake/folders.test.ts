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
    const missing = must(await fake('folders_missing').f.watched_folders());
    expect(missing.folders.map((r) => r.state)).toEqual(['online', 'online', 'missing']);
    expect(missing.waiting).toBe(0);
    const bad = must(await fake('folders_couldnt_read').f.watched_folders());
    expect(bad.unreadable).toHaveLength(3);
    expect(bad.unreadable[0]).toMatchObject({ folder_id: bad.folders[1].id, reason: "macOS doesn't let Discjockey read it" });
    expect(bad.folders[1].unreadable).toBe(3);
  });

  it('long names and folders on other drives', async () => {
    const r = must(await fake('folders_long_names').f.watched_folders());
    expect(r.folders.map((x) => x.name)).toEqual(['Library', 'Music', 'Crates Mix', 'Peak Hour Rarities and Other Long Folder Names']);
    expect(r.unreadable.map((u) => u.reason)).toEqual(['The file is empty', 'The file is empty', "Discjockey can't find sound it can read in it"]);
    expect(r.unreadable[0].path).not.toBe(r.unreadable[1].path);
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
    expect(q.pair.file).toMatchObject({ song_key: 'local:103', quality: 'weak', in_playlist: false, online: true });
    expect(q.pair.file.audio_url).toMatch(/^data:|^blob:/);   // an import folder's file plays too (file/<id>)
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
    const wrong = must(await f.keep_duplicates(ds[0].pair.group_id, ['/x/else.aiff']));
    expect(await finished(evs, wrong.job_id)).toMatchObject({ ok: false, problem: 'changed' });
    const start = must(await f.keep_duplicates(ds[0].pair.group_id, ds[0].pair.files.map((x) => x.path)));
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
    const shown = pair.files.map((x) => x.path);
    const other = must(await f.supersede_duplicate(pair.group_id, own.file_id, [shown[0], '/x/else.aiff']));
    expect(await finished(evs, other.job_id)).toMatchObject({ ok: false, problem: 'changed' });
    const start = must(await f.supersede_duplicate(pair.group_id, own.file_id, shown));
    const done = await finished(evs, start.job_id);
    expect(done).toMatchObject({ kind: 'supersede', ok: true });
    expect((done.result as { result: { section: string; path: string } }).result)
      .toMatchObject({ section: 'replaced', path: 'Superseded/Music/Rave Kollektiv - Bis zum Morgen.aiff' });
    expect(must(await f.todo('all', false)).chips.duplicate).toBe(1);
    const again = must(await f.supersede_duplicate(pair.group_id, own.file_id, shown));
    expect(await finished(evs, again.job_id)).toMatchObject({ ok: false, problem: 'changed' });
    expect(await f.keep_duplicates('nope', [])).toMatchObject({ ok: false, kind: 'refused' });
  });

  it('marks files whose sound is not checked as checked in the Library rows', async () => {
    const lib = must(await fake('normal').f.library('all', null, '', 'all', 'artist'));
    expect(lib.rows.every((r) => r.sound_checked === true)).toBe(true);
  });

  it('library: subtitle parts and summary.not_lossless follow the engine (I7)', async () => {
    const f = fake('normal').f;
    const all = must(await f.library('all', null, '', 'all', 'artist'));
    expect(all.subtitle).toEqual([`${all.rows.length} tracks`, 'every folder']);
    const q = all.summary.by_quality;
    expect(all.summary.not_lossless).toBe(q.good_lossy + q.weak + q.fake);
    expect(must(await f.library('all', null, '', 'weak', 'artist')).summary.not_lossless).toBe(all.summary.not_lossless);
    expect(must(await f.library('unlisted', null, '', 'all', 'artist')).subtitle).toEqual(['2 tracks', 'in no playlist']);
    expect(must(await f.library('folder', 'Library/Old_Sets', '', 'all', 'artist')).subtitle).toEqual(
      ['2 tracks', 'no playlist uses it', 'Library › Old_Sets']);
    const hb = must(await f.library('playlist', 'Hard_Bounce', '', 'all', 'artist'));
    expect(hb.subtitle).toEqual([`${hb.summary.tracks} tracks`, 'Spotify playlist', 'Library › Hard_Bounce']);
    const found = must(await f.library('playlist', 'Hard_Bounce', 'a', 'weak', 'artist'));   // search and filter don't change it
    expect(found.rows.length).toBeLessThan(hb.rows.length);
    expect(found.subtitle).toEqual(hb.subtitle);
    expect(must(await f.library('all', null, 'zzzz-no-such-track', 'all', 'artist')).subtitle).toEqual([`${all.rows.length} tracks`, 'every folder']);
    expect(must(await f.library('playlist', 'Tekke_Ecke', '', 'all', 'artist')).subtitle.slice(1)).toEqual(
      ['Spotify playlist', 'switched off', 'Library › Tekke_Ecke']);
  });

  it('library:browser has 38 playlist lines, two switched off, one long name, two Library folders', async () => {
    const side = must(await fake('library:browser').f.sidebar());
    expect(side.playlists).toHaveLength(38);
    expect(side.playlists.filter((p) => !p.enabled)).toHaveLength(2);
    expect(new Set(side.playlists.map((p) => p.ref)).size).toBe(38);
    expect(Math.max(...side.playlists.map((p) => p.name.length))).toBeGreaterThan(60);
    expect(side.playlists.some((p) => p.songs === null)).toBe(true);
    expect(side.library_folders.map((x) => x.name)).toEqual(['Crate_Dumps', 'Elsewhere', 'Old_Sets']);
    expect(side.playlists.map((p) => p.service)).toContain('qobuz');
  });

  it('library:unchecked has own files whose sound is not checked: out of the counts, in All, with their own words', async () => {
    const f = fake('library:unchecked').f;
    const all = must(await f.library('all', null, '', 'all', 'artist'));
    const open = all.rows.filter((r) => !r.sound_checked).map((r) => r.track_id);
    expect(open).toEqual(['local:1', 'local:2']);
    expect(all.chips.all).toBe(all.rows.length);
    expect(all.summary.by_quality.lossless).toBe(all.rows.filter((r) => r.quality === 'lossless').length - 2);
    expect(must(await f.library('all', null, '', 'lossless', 'artist')).rows.some((r) => r.track_id === 'local:1')).toBe(false);
    expect(must(await f.library('all', null, '', 'all', '-quality')).rows[0].sound_checked).toBe(false);
    const d = must(await f.track('local:1')).track;
    expect(d).toMatchObject({ sound_checked: false, source_full: 'your own file', source_name: 'own file',
      quality_line: 'Your own file (PCM) · sound not checked yet', format_line: 'uncompressed PCM' });
    expect(must(await f.track('local:3')).track.quality_line).toBe('Your own file (PCM) · verified lossless');
    expect(must(await f.todo('all', false)).groups.flatMap((g) => g.items).some((i) => i.track_id.startsWith('local:'))).toBe(false);
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

  it('settings:crates_importing brings Incoming one more crate on each step of its import', async () => {
    const { evs, f } = fake('settings:crates_importing');
    const incoming = (r: Awaited<ReturnType<typeof f.watched_folders>>) =>
      must(r).folders.find((x) => x.path === '/Users/you/Music/Incoming')!;
    const before = incoming(await f.watched_folders());
    expect(before.crates).toHaveLength(11);
    expect(before.too_many).toBe(false);
    const job = must(await f.start_import()).job_id;
    await finished(evs, job);
    const after = incoming(await f.watched_folders());
    expect(after.crates).toHaveLength(24);
    expect(after.too_many).toBe(false);
    // the later crates came in among the first ones, by name
    expect(after.crates.map((c) => c.label)).toEqual([...after.crates.map((c) => c.label)].sort());
    expect(after.files).toBe(before.files + 13 * 3);
  });
});
