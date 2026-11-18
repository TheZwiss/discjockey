// Issue 43, group E3a2: the fake's missing files answer as the engine does (discjockey/missing.py, hub/views.py) and
// the scenario `missing_files` shows every state the plan's shots need.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createFakeBridge } from './bridge';
import {
  ACTION_WORDS, COMES_BACK, HINT_DOWNLOAD, HINT_PLACE, HINT_REMOVE, HINT_REMOVE_PARKED, HINT_TWICE, REASON_WORDS, WILL,
  missingSet, shortDay, summary, whyNot,
} from './missingFiles';
import type { HubEvent } from '../events';
import type { Fail, Library, MissingPreview, MissingResult, Todo, TodoItem, TrackDetail } from '../types';

const py = readFileSync(fileURLToPath(new URL('../../../../../discjockey/missing.py', import.meta.url)), 'utf8');
const words = readFileSync(fileURLToPath(new URL('../../../../../discjockey/words.py', import.meta.url)), 'utf8');

const val = <T>(r: T | Fail): T => { if ((r as Fail).ok === false) throw new Error(`refused: ${(r as Fail).message}`); return r as T; };
const strings = (src: string) => [...src.matchAll(/"((?:[^"\\]|\\.)*)"/g)].map((m) => m[1].replace(/\\(.)/g, '$1'));
/** The value of a top-level constant of missing.py: its string literals, joined (an implicit concatenation too). */
function constant(name: string): string {
  const m = new RegExp(`^${name} = ([\\s\\S]*?)(?=\\n\\S)`, 'm').exec(py);
  if (!m) throw new Error(`${name} is not in missing.py`);
  return strings(m[1]).join('');
}
/** The `"key": "value"` pairs of a top-level dict of missing.py. */
function table(name: string): Record<string, string> {
  const m = new RegExp(`^${name} = \\{([\\s\\S]*?)\\n\\}`, 'm').exec(py);
  if (!m) throw new Error(`${name} is not in missing.py`);
  return Object.fromEntries([...m[1].matchAll(/"(\w+)": "((?:[^"\\]|\\.)*)"/g)].map((x) => [x[1], x[2]]));
}
/** The quoted keys of the dict a function returns, between its `def` and the next `def`. */
function keysOf(fn: string): string[] {
  const body = py.slice(py.indexOf(`def ${fn}(`)).split(/\ndef /)[0];
  return [...body.matchAll(/"(\w+)":/g)].map((x) => x[1]);
}

describe('the fake speaks the engine\'s words (missing.py)', () => {
  it('the reasons, the will words and the buttons', () => {
    expect(REASON_WORDS).toEqual(table('REASONS'));
    expect(WILL).toEqual(table('WILL'));
    const m = /^ACTION_WORDS = \{(.*?)\}/m.exec(py)!;
    expect(Object.values(ACTION_WORDS)).toEqual(strings(m[1]));
  });
  it('the hints', () => {
    const comes = constant('COMES_BACK');
    expect(COMES_BACK).toBe(comes);
    const built = (name: string) => constant(name).replace('{COMES_BACK}', comes);
    expect(HINT_DOWNLOAD).toBe(built('HINT_DOWNLOAD'));
    expect(HINT_PLACE).toBe(built('HINT_PLACE'));
    expect(HINT_REMOVE).toBe(built('HINT_REMOVE'));
    expect(HINT_REMOVE_PARKED).toBe(constant('HINT_REMOVE_PARKED'));
    expect(HINT_TWICE).toBe(constant('HINT_TWICE'));
  });
  it('the fields of the item\'s missing and of the track\'s details', () => {
    const view = ['since', 'place', 'action', 'why_not', 'words', 'will', 'upgrade_waiting'];
    expect(keysOf('view')).toEqual(view);
    expect(keysOf('detail_view')).toEqual(['line', 'hint']);
  });
  it('the sentences of the item and the details line', () => {
    // the fake writes them in missingFiles.ts (itemDetail, line); each template is still in missing.py
    for (const t of ['f"In {len(found)} places now · keep one and it links again"', 'f"Missing since {since} · was in {where}"',
      'f"Missing since {since}"', 'f"Not seen since {since}. It was in {where}."', 'f"Not seen since {since}."',
      'f"Found in {len(found)} places: {names}."']) expect(py).toContain(t);
  });
  it('the day words', () => {
    expect(words).toContain('day = f"{d.day} {MONTHS[d.month - 1]}"');
    expect(shortDay('2026-11-12', new Date(2026, 10, 18))).toBe('12 Nov');
    expect(shortDay('2025-11-12', new Date(2026, 10, 18))).toBe('12 Nov 2025');
  });
});

async function setup(scenario = 'missing_files') {
  const f = createFakeBridge(scenario, { speed: 100, emit: () => {} });
  const s = (f as any)._ctx.s;
  const todo = async (filter = 'all', hidden = false) => val(await f.todo(filter as never, hidden)) as Todo;
  const group = async (hidden = false) => (await todo('all', hidden)).groups.find((g) => g.key === 'missing_file');
  const item = async (id: string, hidden = true) => ((await group(hidden))?.items ?? []).find((i) => i.track_id === id) as TodoItem | undefined;
  const detail = async (id: string) => val(await f.track(id)).track as TrackDetail;
  return { f, s, todo, group, item, detail, set: missingSet(s)! };
}

describe('the scenario missing_files', () => {
  it('has the Missing files group second, after Check in rekordbox', async () => {
    const { todo } = await setup();
    const t = await todo();
    expect(t.groups.map((g) => g.key).slice(0, 2)).toEqual(['rekordbox_check', 'missing_file']);
    const g = t.groups[1];
    expect(g.label).toBe('Missing files');
    expect(g.hint).toBe('not where they were; put a file back and it links again');
  });

  it('a playlist song: Download again, its place and day', async () => {
    const { item, set, s } = await setup();
    const it = (await item(set.plain))!;
    expect(it.missing).toMatchObject({ action: 'download_again', why_not: null, words: null, upgrade_waiting: false,
      will: WILL.download });
    expect(it.missing!.since).toBe(it.missing!.since.slice(0, 10));
    expect(it.detail).toBe(`Missing since ${shortDay(it.missing!.since, s.now)} · was in ${it.missing!.place}`);
    expect(it.file_state).toBe('file_missing');
    expect(it.group).toBe('missing_file');
    expect(it.free).toBe(false);
  });

  it('a playlist song with a parked upgrade gets it put in, nothing is downloaded', async () => {
    const { item, detail, set } = await setup();
    const it = (await item(set.parked))!;
    expect(it.missing).toMatchObject({ action: 'download_again', why_not: null, upgrade_waiting: true, will: WILL.place });
    expect((await detail(set.parked)).missing!.hint).toBe(HINT_PLACE);
  });

  it('a song found in two places: Download again is blocked, the line names both', async () => {
    const { item, detail, set } = await setup();
    const it = (await item(set.twice))!;
    expect(it.detail).toBe('In 2 places now · keep one and it links again');
    expect(it.missing).toMatchObject({ why_not: 'found_twice', words: REASON_WORDS.found_twice });
    const d = (await detail(set.twice)).missing!;
    expect(d.line).toMatch(/^Found in 2 places: Crates and Old\.$/);
    expect(d.hint).toBe(HINT_TWICE);
  });

  it('a song marked Never download is blocked by it', async () => {
    const { item, set } = await setup();
    expect((await item(set.never))!.missing).toMatchObject({ why_not: 'never', words: REASON_WORDS.never });
  });

  it('an own song gets Remove, with the parked version\'s line, and an open check blocks it', async () => {
    const { item, detail, set } = await setup();
    expect((await item(set.own))!.missing).toMatchObject({ action: 'remove', why_not: null, will: WILL.remove });
    expect((await detail(set.own)).missing!.hint).toBe(HINT_REMOVE);
    expect((await item(set.ownParked))!.missing).toMatchObject({ action: 'remove', upgrade_waiting: true, will: WILL.remove });
    expect((await detail(set.ownParked)).missing!.hint).toBe(HINT_REMOVE + HINT_REMOVE_PARKED);
    expect((await item(set.ownCheck))!.missing).toMatchObject({ action: 'remove', why_not: 'check_open', words: REASON_WORDS.check_open });
  });

  it('an own song with an open check is in both groups and counted once', async () => {
    const { todo, set } = await setup();
    const t = await todo();
    const inGroups = t.groups.filter((g) => g.items.some((i) => i.track_id === set.ownCheck)).map((g) => g.key);
    expect(inGroups).toEqual(['rekordbox_check', 'missing_file']);
    const keys = t.groups.flatMap((g) => g.items.map((i) => i.track_id));
    expect(keys.filter((k) => k === set.ownCheck)).toHaveLength(2);
  });

  it('a song on a drive that is away is offline: the drive wins over the mark', async () => {
    const { item, detail, set } = await setup();
    expect((await item(set.ownOffline))!.file_state).toBe('offline');
    const d = await detail(set.ownOffline);
    expect(d.file_state).toBe('offline');
    expect(d.missing).not.toBeNull();
    expect(d.audio_url).toBeNull();
  });

  it('a hidden song is listed only with Show hidden and is left out of the group\'s all', async () => {
    const { group, set } = await setup();
    const shown = (await group())!;
    expect(shown.items.map((i) => i.track_id)).not.toContain(set.hidden);
    const all = (await group(true))!;
    expect(all.items.map((i) => i.track_id)).toContain(set.hidden);
    const runnable = (a: string) => all.items.filter((i) => !i.hidden && i.missing!.action === a && i.missing!.why_not === null).length;
    expect((all as { all: unknown }).all).toEqual({ download_again: runnable('download_again'), remove: runnable('remove') });
    // plain + parked can download again; own + ownParked + ownOffline can be removed (twice, never and the check are blocked)
    expect((all as { all: unknown }).all).toEqual({ download_again: 2, remove: 3 });
  });

  it('a song whose Download again was asked leaves To-do; its details say next sync and the Library row still lists it', async () => {
    const { todo, detail, f, set } = await setup();
    const t = await todo('all', true);
    expect(t.groups.flatMap((g) => g.items.map((i) => i.track_id))).not.toContain(set.asked);
    expect((await detail(set.asked)).next_qobuz_check).toBe('next_sync');
    expect((await detail(set.asked)).missing).not.toBeNull();
    const lib = val(await f.library('all', null, '', 'all', null)) as Library;
    expect(lib.rows.find((r) => r.track_id === set.asked)!.file_state).toBe('file_missing');
  });

  it('the group wins over every other group but Check in rekordbox, and Upgrade all leaves a missing song out', async () => {
    const { todo, set } = await setup();
    const t = await todo('all', true);
    for (const id of [set.parked, set.ownParked]) {
      expect(t.groups.filter((g) => g.items.some((i) => i.track_id === id)).map((g) => g.key)).toEqual(['missing_file']);
    }
    const up = t.groups.find((g) => g.key === 'upgrade_ready');
    expect(up?.items.map((i) => i.track_id) ?? []).not.toContain(set.parked);
  });

  it('chips count the group, and the sidebar\'s to-do counts the song', async () => {
    const { todo } = await setup();
    const t = await todo();
    // plain, parked, twice, never, own, ownParked, ownCheck, ownOffline (the hidden one only with Show hidden)
    expect(t.chips.missing_file).toBe(8);
    expect(t.hidden_count).toBeGreaterThanOrEqual(1);
  });

  it('Library rows say file_missing, unless the drive is away', async () => {
    const { f, set } = await setup();
    const lib = val(await f.library('all', null, '', 'all', null)) as Library;
    const state = (id: string) => lib.rows.find((r) => r.track_id === id)!.file_state;
    expect(state(set.plain)).toBe('file_missing');
    expect(state(set.own)).toBe('file_missing');
    expect(state(set.ownOffline)).toBe('offline');
  });

  it('the details of a song that is there carry no missing, and the player is off for a missing one', async () => {
    const { detail, set, s } = await setup();
    const there = s.tracks.find((t: { track_id: string; missing?: unknown; status: string; in_playlists: boolean; own?: boolean }) =>
      !t.missing && t.status === 'lossless' && t.in_playlists && !t.own);
    expect((await detail(there.track_id)).missing).toBeNull();
    expect((await detail(set.plain)).audio_url).toBeNull();
    expect((await detail(set.plain)).file_state).toBe('file_missing');
  });
});

describe('every other scenario stays as it was', () => {
  it.each(['normal', 'big', 'todo_duplicates'])('%s has no missing group and no missing in a track\'s details', async (name) => {
    const { todo, detail, s } = await setup(name);
    const t = await todo('all', true);
    expect(t.groups.find((g) => g.key === 'missing_file')).toBeUndefined();
    expect(t.chips.missing_file).toBe(0);
    expect((await detail(s.tracks[0].track_id)).missing).toBeNull();
  });
});

describe('whyNot, as missing.why_not', () => {
  it('names the first reason that applies, every one of the six', async () => {
    const { s, set } = await setup();
    const t = (id: string) => s.tracks.find((x: { track_id: string }) => x.track_id === id);
    expect(whyNot(s, t(set.plain), 'download_again')).toBeNull();
    expect(whyNot(s, t(set.plain), 'remove')).toBe('wrong_action');
    expect(whyNot(s, t(set.own), 'download_again')).toBe('wrong_action');
    expect(whyNot(s, t(set.twice), 'download_again')).toBe('found_twice');
    expect(whyNot(s, t(set.never), 'download_again')).toBe('never');
    expect(whyNot(s, t(set.asked), 'download_again')).toBe('asked');
    expect(whyNot(s, t(set.ownCheck), 'remove')).toBe('check_open');
    const back = s.tracks.find((x: { missing?: unknown }) => !x.missing);
    expect(whyNot(s, back, 'download_again')).toBe('not_missing');
  });
});


// ---------- the two actions ----------

/** A scenario with its events kept, and the two calls with the job awaited (the job's `JobFinished`). */
async function acting() {
  const evs: HubEvent[] = [];
  const f = createFakeBridge('missing_files', { speed: 100, emit: (e: HubEvent) => evs.push(e) });
  const s = (f as any)._ctx.s;
  const set = missingSet(s)!;
  const finished = async (id: string) => {
    for (let i = 0; i < 400; i++) {
      const e = evs.find((x) => x.type === 'JobFinished' && x.job_id === id);
      if (e) return e as Extract<HubEvent, { type: 'JobFinished' }>;
      await new Promise((r) => setTimeout(r, 5));
    }
    throw new Error('the job did not finish');
  };
  const run = async (ids: string[], action: 'download_again' | 'remove') => {
    const started = await f.missing_files(ids, action) as { ok: true; job_id: string };
    return finished(started.job_id);
  };
  const preview = async (ids: string[], action: 'download_again' | 'remove') => val(await f.missing_files_preview(ids, action)) as MissingPreview;
  const todoIds = async () => ((await f.todo('all', true)) as Todo).groups.find((g) => g.key === 'missing_file')?.items.map((i) => i.track_id) ?? [];
  return { f, s, set, run, preview, todoIds, evs };
}

describe('the summary line, as missing.summary (tests/test_missing_actions.py pins the same sentences)', () => {
  it.each([
    ['download_again', 1, 0, 0, 0, '1 song downloads again at your next sync.'],
    ['download_again', 2, 0, 0, 1, '2 songs download again at your next sync; 1 is skipped.'],
    ['download_again', 0, 1, 0, 0, '1 song gets the better version already waiting for it at your next sync; nothing is downloaded.'],
    ['download_again', 0, 2, 0, 0, '2 songs get the better version already waiting for them at your next sync; nothing is downloaded.'],
    ['download_again', 1, 1, 0, 0, '1 song downloads again and 1 gets the better version already waiting for it, at your next sync.'],
    ['download_again', 2, 2, 0, 0, '2 songs download again and 2 get the better version already waiting for them, at your next sync.'],
    ['download_again', 0, 0, 0, 3, 'Nothing to do: 3 songs are skipped.'],
    ['remove', 0, 0, 1, 0, 'Removes 1 song from your library.'],
    ['remove', 0, 0, 3, 2, 'Removes 3 songs from your library; 2 are skipped.'],
    ['remove', 0, 0, 0, 1, 'Nothing to remove: 1 song is skipped.'],
  ] as const)('%s %i %i %i %i', (action, plain, placed, removed, skipped, line) => {
    expect(summary(action, plain, placed, removed, skipped)).toBe(line);
  });
  it('says "Removed" once the run is over, and names the same fragments as missing.py', () => {
    expect(summary('remove', 0, 0, 2, 0, true)).toBe('Removed 2 songs from your library.');
    for (const t of ['Nothing to remove: ', 'Nothing to do: ', "'Removed' if done else 'Removes'", 'from your library', 'again and ',
      'the better version already waiting for ', 'at your next sync; nothing is downloaded', "'is' if skipped == 1 else 'are'"]) {
      expect(py).toContain(t);
    }
  });
});

describe('missing_files_preview', () => {
  it('says per song what would happen, in the order asked, and one line for all', async () => {
    const { preview, set } = await acting();
    const p = await preview([set.parked, 'nope', set.plain, set.own], 'download_again');
    expect(p.items.map((i) => i.track_id)).toEqual([set.parked, 'nope', set.plain, set.own]);
    expect(p.items.map((i) => [i.will, i.reason])).toEqual([[true, null], [false, 'not_missing'], [true, null], [false, 'wrong_action']]);
    expect(p.items[0]).toMatchObject({ upgrade_waiting: true, words: WILL.place });
    expect(p.items[1]).toMatchObject({ artist: '', title: '', place: '', since: null, words: REASON_WORDS.not_missing });
    expect(p.items[2]).toMatchObject({ words: WILL.download, since: expect.stringMatching(/^\d{4}-\d\d-\d\d$/) });
    expect(p.items[3].words).toBe('This song gets Remove from library instead.');
    expect([p.n, p.skipped]).toEqual([2, 2]);
    expect(p.words).toBe('1 song downloads again and 1 gets the better version already waiting for it, at your next sync; 2 are skipped.');
  });
  it('marks the parked version Remove would delete, and changes nothing', async () => {
    const { preview, set, s, todoIds } = await acting();
    const before = await todoIds();
    const p = await preview([set.own, set.ownParked, set.ownCheck], 'remove');
    expect(p.items.map((i) => i.upgrade_waiting)).toEqual([false, true, false]);
    expect(p.items[2]).toMatchObject({ will: false, reason: 'check_open' });
    expect(p.words).toBe('Removes 2 songs from your library; 1 is skipped.');
    expect(await todoIds()).toEqual(before);
    expect(s.tracks.some((t: { track_id: string }) => t.track_id === set.own)).toBe(true);
  });
  it('refuses an unknown action and no songs', async () => {
    const { f, set } = await acting();
    expect(await f.missing_files_preview([set.plain], 'forget' as never)).toMatchObject({ ok: false, kind: 'refused' });
    expect(await f.missing_files_preview([], 'remove')).toMatchObject({ ok: false, message: 'No tracks were chosen.' });
  });
});

describe('missing_files', () => {
  it('Download again sets file_gone: the song leaves To-do, the parked version stays', async () => {
    const { run, set, s, todoIds, f } = await acting();
    const e = await run([set.plain, set.parked], 'download_again');
    expect(e).toMatchObject({ ok: true, kind: 'missing_files', problem: null });
    const r = e.result as MissingResult;
    expect(r).toMatchObject({ action: 'download_again', done: [set.plain, set.parked], skipped: [], recovered: [] });
    expect(r.results.map((x) => [x.state, x.reason, x.words])).toEqual([['done', null, WILL.download], ['done', null, WILL.place]]);
    expect(r.words).toBe('1 song downloads again and 1 gets the better version already waiting for it, at your next sync.');
    const ids = await todoIds();
    expect(ids).not.toContain(set.plain);
    expect(ids).not.toContain(set.parked);
    const parked = s.tracks.find((t: { track_id: string }) => t.track_id === set.parked);
    expect(parked.upgrade).toBeTruthy();
    expect(parked.missing).toBeTruthy();
    expect((val(await f.track(set.plain)) as { track: TrackDetail }).track.next_qobuz_check).toBe('next_sync');
  });

  it('a song the action does not fit is skipped with its reason; the run still ends ok', async () => {
    const { run, set, s } = await acting();
    const e = await run([set.plain, set.own, set.twice, set.never, set.asked, 'nope'], 'download_again');
    const r = e.result as MissingResult;
    expect(e.ok).toBe(true);
    expect(r.done).toEqual([set.plain]);
    expect(r.results.map((x) => x.reason)).toEqual([null, 'wrong_action', 'found_twice', 'never', 'asked', 'not_missing']);
    expect(r.results[1].words).toBe('This song gets Remove from library instead.');
    expect(r.words).toBe('1 song downloads again at your next sync; 5 are skipped.');
    expect(s.tracks.find((t: { track_id: string }) => t.track_id === set.own).fileGone).toBeFalsy();
  });

  it('every song skipped ends the job changed with the result kept', async () => {
    const { run, set } = await acting();
    const e = await run([set.own], 'download_again');
    expect(e).toMatchObject({ ok: false, problem: 'changed', message: 'Nothing to do: 1 song is skipped.' });
    expect(e.result).toMatchObject({ action: 'download_again', done: [], skipped: [set.own] });
  });

  it('Remove deletes an own song and its parked version, and only what was asked', async () => {
    const { run, set, s, todoIds } = await acting();
    const count = s.tracks.length;
    const e = await run([set.own, set.ownParked, set.ownCheck, set.plain], 'remove');
    const r = e.result as MissingResult;
    expect(r.done).toEqual([set.own, set.ownParked]);
    expect(r.results.map((x) => x.reason)).toEqual([null, null, 'check_open', 'wrong_action']);
    expect(r.results[0].words).toBe(WILL.remove);
    expect(r.words).toBe('Removed 2 songs from your library; 2 are skipped.');
    const left = s.tracks.map((t: { track_id: string }) => t.track_id);
    expect(left).toHaveLength(count - 2);
    expect(left).not.toContain(set.own);
    expect(left).not.toContain(set.ownParked);
    expect(left).toContain(set.ownCheck);
    expect(left).toContain(set.plain);
    expect(await todoIds()).not.toContain(set.own);
  });

  it('Remove twice: the second finds nothing and ends changed', async () => {
    const { run, set } = await acting();
    await run([set.own], 'remove');
    const e = await run([set.own], 'remove');
    expect(e).toMatchObject({ ok: false, problem: 'changed', message: 'Nothing to remove: 1 song is skipped.' });
  });

  it('refuses an unknown action and no songs, and answers busy while a job runs', async () => {
    const { f, set } = await acting();
    expect(await f.missing_files([set.plain], 'forget' as never)).toMatchObject({ ok: false, kind: 'refused' });
    expect(await f.missing_files([], 'remove')).toMatchObject({ ok: false, message: 'No tracks were chosen.' });
    expect(await f.missing_files([set.plain], 'download_again')).toMatchObject({ ok: true });
    expect(await f.missing_files([set.own], 'remove')).toMatchObject({ ok: false, kind: 'busy' });
  });
});
