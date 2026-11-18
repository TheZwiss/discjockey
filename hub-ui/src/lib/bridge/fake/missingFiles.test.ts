// Issue 43, group E3a2: the fake's missing files answer as the engine does (discjockey/missing.py, hub/views.py) and
// the scenario `missing_files` shows every state the plan's shots need.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createFakeBridge } from './bridge';
import {
  ACTION_WORDS, COMES_BACK, HINT_DOWNLOAD, HINT_PLACE, HINT_REMOVE, HINT_REMOVE_PARKED, HINT_TWICE, REASON_WORDS, WILL,
  missingSet, shortDay, whyNot,
} from './missingFiles';
import type { Fail, Library, Todo, TodoItem, TrackDetail } from '../types';

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
