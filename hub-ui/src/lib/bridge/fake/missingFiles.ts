// Fake mode: the songs whose file waits as missing (issue 43, plan docs/2026-11-17-missing-files-plan.md §5): the rules
// and the words of discjockey/missing.py, the `missing` of a To-do item and of the track's details, the group's `all`,
// and the scenario `missing_files` (open it with ?scenario=missing_files) that shows every state the plan's shots need.
// The words are the engine's: fake/missingFiles.test.ts reads missing.py and pins each one.
import type { FakeState, FakeTrack } from './data';
import { dateOnly, makeUpgrade } from './data';
import { placeAt, trackPlace } from './library';
import { MUSIC_DIR, ownTrack } from './aiffScenes';
import type { MissingAction, MissingAll, MissingDetail, MissingItemResult, MissingPreview, MissingReason, MissingResult, MissingView,
  TodoItem } from '../types';

export const DOWNLOAD_AGAIN: MissingAction = 'download_again';
export const REMOVE: MissingAction = 'remove';
export const MISSING_ACTIONS: MissingAction[] = [DOWNLOAD_AGAIN, REMOVE];
export const BAD_MISSING_ACTION = 'action must be one of download_again, remove.';
/** The buttons' words, without the dots (missing.ACTION_WORDS) */
export const ACTION_WORDS: Record<MissingAction, string> = { download_again: 'Download again', remove: 'Remove from library' };
/** missing.REASONS: `wrong_action` names the action the song gets instead */
export const REASON_WORDS: Record<MissingReason, string> = {
  not_missing: 'Its file is back.',
  wrong_action: 'This song gets {other} instead.',
  found_twice: 'Its file is in several places now: keep one and it links again.',
  never: 'You chose Never download for it.',
  check_open: 'Its rekordbox check is still open: finish it first.',
  asked: 'You asked for it already: it happens at your next sync.',
};
/** missing.WILL */
export const WILL = {
  download: 'Downloads again at your next sync',
  place: 'Gets the better version already waiting for it at your next sync; nothing is downloaded',
  remove: 'Removed from your library',
};
/** missing.COMES_BACK and the hints built on it */
export const COMES_BACK = 'Put the file back in any watched folder and it links again with everything it had.';
export const HINT_DOWNLOAD = `${COMES_BACK} Or download it again at your next sync.`;
export const HINT_PLACE = `${COMES_BACK} Or press Download again: the better version already waiting for it goes in at your next `
  + 'sync, and nothing is downloaded.';
export const HINT_REMOVE = `${COMES_BACK} Or remove the song from your library.`;
export const HINT_REMOVE_PARKED = ' Its better version waiting in Upgrade ready goes with it.';
export const HINT_TWICE = "Delete or move away the copies you don't want; the one left links again.";

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
/** words.short_day: "12 Nov" in today's year, "12 Nov 2025" otherwise (a plain space, as the engine writes it) */
export function shortDay(iso: string, today: Date): string {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  const day = `${d} ${MONTHS[m - 1]}`;
  return y === today.getFullYear() ? day : `${day} ${y}`;
}

/** missing.action_for: a song in a playlist gets Download again, any other song Remove from library */
export const missingAction = (t: FakeTrack): MissingAction => (t.in_playlists ? DOWNLOAD_AGAIN : REMOVE);

/** missing.why_not: the first reason `action` can't run for the song now, else null */
export function whyNot(s: FakeState, t: FakeTrack, action: MissingAction): MissingReason | null {
  if (!t.missing) return 'not_missing';
  if (action !== missingAction(t)) return 'wrong_action';
  if (action === DOWNLOAD_AGAIN) {
    if (t.missing.found?.length) return 'found_twice';
    if (s.never.includes(t.track_id)) return 'never';
    if (t.fileGone) return 'asked';
  } else if (t.rekordbox_check) return 'check_open';
  return null;
}
/** missing.reason_words */
export function reasonWords(reason: MissingReason, action: MissingAction): string {
  const other = action === DOWNLOAD_AGAIN ? REMOVE : DOWNLOAD_AGAIN;
  return REASON_WORDS[reason].replace('{other}', ACTION_WORDS[other]);
}
/** missing.will_words */
export const willWords = (action: MissingAction, upgradeWaiting: boolean): string =>
  action === REMOVE ? WILL.remove : upgradeWaiting ? WILL.place : WILL.download;

const wasIn = (s: FakeState, t: FakeTrack): string => trackPlace(s, t) ?? '';

/** missing.item_detail: the item's one line */
export function itemDetail(s: FakeState, t: FakeTrack): string {
  const found = t.missing!.found ?? [];
  if (found.length) return `In ${found.length} places now · keep one and it links again`;
  const since = shortDay(t.missing!.since, s.now);
  const where = wasIn(s, t);
  return where ? `Missing since ${since} · was in ${where}` : `Missing since ${since}`;
}

/** missing.view: the `missing` of a To-do item, null when the song's file isn't marked missing */
export function missingView(s: FakeState, t: FakeTrack): MissingView | null {
  if (!t.missing) return null;
  const action = missingAction(t);
  const reason = whyNot(s, t, action);
  const waiting = !!t.upgrade;
  return { since: t.missing.since.slice(0, 10), place: wasIn(s, t), action, why_not: reason,
    words: reason ? reasonWords(reason, action) : null, will: willWords(action, waiting), upgrade_waiting: waiting };
}

function line(s: FakeState, t: FakeTrack): string {
  const found = t.missing!.found ?? [];
  if (found.length) {
    const where = found.map((p) => placeAt(s, p));
    const names = where.length > 1 ? `${where.slice(0, -1).join(', ')} and ${where[where.length - 1]}` : where[0];
    return `Found in ${found.length} places: ${names}.`;
  }
  const since = shortDay(t.missing!.since, s.now);
  const where = wasIn(s, t);
  return where ? `Not seen since ${since}. It was in ${where}.` : `Not seen since ${since}.`;
}
function hint(t: FakeTrack, action: MissingAction): string {
  if (t.missing!.found?.length) return HINT_TWICE;
  const waiting = !!t.upgrade;
  if (action === DOWNLOAD_AGAIN) return waiting ? HINT_PLACE : HINT_DOWNLOAD;
  return HINT_REMOVE + (waiting ? HINT_REMOVE_PARKED : '');
}
/** missing.detail_view: `track().missing`, the view plus its `line` and `hint` */
export function missingDetail(s: FakeState, t: FakeTrack): MissingDetail | null {
  const v = missingView(s, t);
  return v ? { ...v, line: line(s, t), hint: hint(t, v.action) } : null;
}

/** The group's `all`: the items not hidden whose action can run now, by action (what the head link and `--all` act on) */
export function missingAll(items: TodoItem[]): { all: MissingAll } {
  const n = (a: MissingAction) => items.filter((r) => !r.hidden && r.missing?.action === a && r.missing.why_not === null).length;
  return { all: { download_again: n(DOWNLOAD_AGAIN), remove: n(REMOVE) } };
}

// ---------- the two actions: the dry run and the job ----------

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
/** missing.summary: the one line of the dry run, the job's result and the commands. `plain` songs download again, `placed`
 *  get the parked version, `removed` are taken out, `skipped` don't run; `done`: the run is over (Remove says "Removed"). */
export function summary(action: MissingAction, plain: number, placed: number, removed: number, skipped: number, done = false): string {
  const tail = skipped ? `; ${skipped} ${skipped === 1 ? 'is' : 'are'} skipped` : '';
  if (action === REMOVE) {
    if (!removed) return `Nothing to remove: ${plural(skipped, 'song is', 'songs are')} skipped.`;
    return `${done ? 'Removed' : 'Removes'} ${plural(removed, 'song', 'songs')} from your library${tail}.`;
  }
  if (!plain && !placed) return `Nothing to do: ${plural(skipped, 'song is', 'songs are')} skipped.`;
  const it = placed === 1 ? 'it' : 'them';
  if (plain && placed) {
    return `${plural(plain, 'song downloads', 'songs download')} again and ${plural(placed, 'gets', 'get')} the better version `
      + `already waiting for ${it}, at your next sync${tail}.`;
  }
  if (placed) {
    return `${plural(placed, 'song gets', 'songs get')} the better version already waiting for ${it} at your next sync; `
      + `nothing is downloaded${tail}.`;
  }
  return `${plural(plain, 'song downloads', 'songs download')} again at your next sync${tail}.`;
}

/** missing._counts: (plain, placed, removed, skipped) of rows that carry `will` and `upgrade_waiting` */
function counts(action: MissingAction, rows: { will: boolean; upgrade_waiting: boolean }[]): [number, number, number, number] {
  const will = rows.filter((r) => r.will);
  if (action === REMOVE) return [0, 0, will.length, rows.length - will.length];
  const placed = will.filter((r) => r.upgrade_waiting).length;
  return [will.length - placed, placed, 0, rows.length - will.length];
}

/** missing.preview: what `action` would do for `ids`, one item per song in the order asked (a key that is no song is
 *  `not_missing`). Reads only. */
export function previewMissing(s: FakeState, ids: string[], action: MissingAction): MissingPreview {
  const items = ids.map((id) => {
    const t = s.tracks.find((x) => x.track_id === id);
    const reason = t ? whyNot(s, t, action) : 'not_missing';
    const waiting = !!t?.upgrade;
    return { track_id: id, artist: t?.artist ?? '', title: t?.title ?? '', place: t ? wasIn(s, t) : '',
      since: t?.missing ? t.missing.since.slice(0, 10) : null, will: reason === null, reason,
      words: reason === null ? willWords(action, waiting) : reasonWords(reason, action), upgrade_waiting: waiting };
  });
  const n = items.filter((i) => i.will).length;
  return { action, items, n, skipped: items.length - n, words: summary(action, ...counts(action, items)) };
}

/**
 * missing.download_again / missing.remove, as the job runs them: each song is asked again (`whyNot`), a song the action
 * does not fit is skipped with its reason, never switched to the other action. Download again sets `fileGone` and changes
 * nothing else (the song leaves To-do; the parked version stays); Remove deletes the song, its answers and its parked
 * version, and no music file (there is none). The result is the engine's `MissingResult`.
 */
export function runMissing(s: FakeState, ids: string[], action: MissingAction): MissingResult {
  const results: MissingItemResult[] = [];
  const waiting = new Set<string>();
  for (const id of ids) {
    const t = s.tracks.find((x) => x.track_id === id);
    const reason = t ? whyNot(s, t, action) : 'not_missing';
    if (!t || reason) {
      results.push({ track_id: id, action, state: 'skipped', reason, words: reasonWords(reason!, action) });
      continue;
    }
    if (t.upgrade) waiting.add(id);
    results.push({ track_id: id, action, state: 'done', reason: null, words: willWords(action, !!t.upgrade) });
    if (action === DOWNLOAD_AGAIN) t.fileGone = true;
    else {
      s.tracks.splice(s.tracks.indexOf(t), 1);
      s.never = s.never.filter((k) => k !== id);
      s.favourites = s.favourites.filter((k) => k !== id);
    }
  }
  const rows = results.map((r) => ({ will: r.state === 'done', upgrade_waiting: waiting.has(r.track_id) }));
  return { action, results, done: results.filter((r) => r.state === 'done').map((r) => r.track_id),
    skipped: results.filter((r) => r.state === 'skipped').map((r) => r.track_id),
    words: summary(action, ...counts(action, rows), true), recovered: [] };
}

// ---------- the scenario ----------

const OFFLINE_DIR = '/Volumes/Old Drive/Music';
const daysBefore = (s: FakeState, n: number) => dateOnly(new Date(s.now.getTime() - n * 86400000));

/** A parked better version for the song: it turns lossy first (a lossless song has nothing to upgrade). */
function park(s: FakeState, t: FakeTrack): void {
  Object.assign(t, { status: 'not_lossless', cutoff_hz: 16000, codec: 'mp3', kbps: 192 });
  if (t.own) t.audio = { codec: 'mp3', rate: 44100, bits: null, kbps: 192, ext: 'mp3' };
  else Object.assign(t, { source: 'youtube_music' });
  t.upgrade = makeUpgrade(t, 'exact', dateOnly(s.now), false);
}

/** The lossless playlist songs of the plain scenarios a scenario may change (the generated ones: t7 on). */
function playlistPool(s: FakeState): FakeTrack[] {
  return s.tracks.filter((t) => /^t([7-9]|\d\d+)$/.test(t.track_id) && t.in_playlists && !t.hidden && !t.rekordbox_check
    && !t.other && !t.upgrade && !t.away && !t.own && t.status === 'lossless');
}

/** What the scenario `missing_files` made of which song, by track id. */
export type MissingSet = Record<'plain' | 'parked' | 'twice' | 'never' | 'hidden' | 'asked' | 'own' | 'ownParked' | 'ownCheck' | 'ownOffline', string>;
const sets = new WeakMap<FakeState, MissingSet>();
/** The scenario's songs for a state it made (tests and shots); undefined for any other state. */
export const missingSet = (s: FakeState): MissingSet | undefined => sets.get(s);

/**
 * `missing_files`: the plain scenario plus ten songs whose file waits as missing, one for each state of plan §7.5.
 *   plain      playlist song          Download again; "Downloads again at your next sync"
 *   parked     playlist song          Download again with a parked better version: "Gets the better version already waiting…"
 *   twice      playlist song          found in two places: Download again blocked (`found_twice`)
 *   never      playlist song          "Never download" chosen: Download again blocked (`never`)
 *   hidden     playlist song          hidden: only with Show hidden, left out of the group's `all`
 *   asked      playlist song          Download again was asked (`fileGone`): in no group; Library: next sync
 *   own        own song               Remove from library
 *   ownParked  own song               Remove with a parked better version (the hint's extra line)
 *   ownCheck   own song               Remove blocked by an open rekordbox check (`check_open`); also in Check in rekordbox
 *   ownOffline own song, drive away   file_state `offline` wins over the missing mark; Remove
 */
export function missingScenario(s: FakeState): void {
  const [plain, parked, twice, never, hidden, asked] = playlistPool(s);
  if (!asked) throw new Error('missing_files: the plain scenario has too few playlist songs');
  const mark = (t: FakeTrack, daysAgo: number, found?: string[]) => { t.missing = { since: daysBefore(s, daysAgo), ...(found ? { found } : {}) }; };
  mark(plain, 6);
  park(s, parked); mark(parked, 3);
  mark(twice, 9, [`${MUSIC_DIR}/Crates/${twice.artist} - ${twice.title}.aiff`, `${MUSIC_DIR}/Old/${twice.artist} - ${twice.title}.aiff`]);
  mark(never, 12); s.never.push(never.track_id);
  mark(hidden, 15); hidden.hidden = true;
  mark(asked, 2); asked.fileGone = true;

  const own = ownTrack(s, 21), ownParked = ownTrack(s, 22), ownCheck = ownTrack(s, 23), ownOffline = ownTrack(s, 24);
  mark(own, 40);
  park(s, ownParked); mark(ownParked, 21);
  mark(ownCheck, 5); ownCheck.rekordbox_check = { reason: 'renamed', since: daysBefore(s, 8), oldName: `${ownCheck.artist}_-_${ownCheck.title}` };
  // its folder sits on a drive that isn't there: the drive wins over the mark
  s.imp.folders.push({ id: s.imp.nextId++, path: OFFLINE_DIR, kind: 'import', offline: true, imported: 1, waiting: 0, redownload: 0 });
  Object.assign(ownOffline, { dir: OFFLINE_DIR, away: 'offline' as const });
  mark(ownOffline, 30);

  sets.set(s, { plain: plain.track_id, parked: parked.track_id, twice: twice.track_id, never: never.track_id,
    hidden: hidden.track_id, asked: asked.track_id, own: own.track_id, ownParked: ownParked.track_id,
    ownCheck: ownCheck.track_id, ownOffline: ownOffline.track_id });
}

export const missingScenarios: Record<string, (s: FakeState) => void> = { missing_files: missingScenario };
