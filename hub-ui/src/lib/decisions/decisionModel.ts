// The decisions a track can wait for, wherever its details show (To-do and the Library; mockup todo-decisions):
// the upgrade ("Replace with lossless", the "In rekordbox" choice), the rekordbox check a replace leaves (its steps,
// what was replaced, Undo), and duplicates ("Which file stays?"). Pure: the words, the choices and their outcomes,
// and which of them the selected Library track waits for (`decisionFor`). The components beside it render them.
import type {
  Alignment, DuplicateItem, FileSide, RekordboxCheckView, TodoItem, TrackDetail, Upgrade,
} from '$lib/bridge/types';
import { isDuplicate } from '$lib/bridge/types';
import type { Outcome } from '$lib/components/choiceModel';
import type { QueueItem } from '$lib/stores/queueModel';
import type { PlayerState } from '$lib/stores/player';
import { dayMonth } from '$lib/format';

/** Both ways are possible: an AIFF file (swap_possible) and the same edit (swap_safe). */
export const canSwap = (up: Upgrade | null | undefined): boolean => !!up && up.swap_safe && up.swap_possible;

/** The last part of a path ("Neon Riot - Neonfieber.aiff"). */
export function fileName(path: string): string {
  return path.split('/').filter(Boolean).at(-1) ?? path;
}

// ---------- ▶ on one file of a duplicate group or a question ----------
/** A file's id in the player's queue (the foot's link back selects its item through selectFromTrack). */
export const fileQueueId = (f: Pick<FileSide, 'file_id'>): string => `file:${f.file_id}`;

/** ▶ on a file: the files of the item that can play, as a queue starting at that file, so ⏭ goes on to the next copy
 *  and copies are compared one after the other. Null when that file can't play (offline, or no address). */
export function fileQueue(files: FileSide[], file_id: number, cover_url: string | null = null):
  { items: QueueItem[]; start: number; urls: Map<string, string> } | null {
  const playable = files.filter((f) => f.online && f.audio_url);
  const start = playable.findIndex((f) => f.file_id === file_id);
  if (start < 0) return null;
  return {
    items: playable.map((f) => ({ track_id: fileQueueId(f), artist: f.artist, title: f.title || fileName(f.path),
      cover_url, duration_s: f.duration_s || null })),
    start,
    urls: new Map(playable.map((f) => [fileQueueId(f), f.audio_url as string])),
  };
}

/** A file's ▶ as the player has it: its own sound loading or playing, else paused. */
export function fileState(p: Pick<PlayerState, 'track_id' | 'playing' | 'loading'>, f: Pick<FileSide, 'file_id'>):
  'playing' | 'paused' | 'loading' {
  if (p.track_id !== fileQueueId(f)) return 'paused';
  return p.loading ? 'loading' : p.playing ? 'playing' : 'paused';
}

/** "Keep both" for two files, "Keep all" for more (W8). */
export function keepLabel(n: number): string {
  return n > 2 ? 'Keep all' : 'Keep both';
}

// ---------- the upgrade decision (mockup todo-decisions) ----------
/** The two ways an upgrade goes in. Both put the lossless audio in place of the user's file ("Replace with
 *  lossless"); only rekordbox differs: Swap keeps the same rekordbox track ("Same track", AIFF and the same edit only),
 *  Add as new file makes a new one ("New track"). The engine's modes stay; the panel maps the choice to them. */
export type Way = 'swap' | 'add_new';
export type WayOption = { key: Way; name: string; summary: string; outcomes: Outcome[] };
export type UpgradeWays = {
  /** both ways are possible: the "In rekordbox" card is a choice (Same track recommended) */
  choice: boolean;
  options: WayOption[];
  /** no choice: what will happen (New track's outcomes) */
  fixed: Outcome[];
  /** why Same track isn't possible; null with a choice */
  reason: string | null;
};
export const KEPT_FILE: Outcome = { tone: 'file', text: 'Your old file is kept in Superseded/' };
export const QUIT_REKORDBOX = 'Tip: quit rekordbox before you replace';
/** How far apart the two versions start, in whole ms (an alignment or a check's measurement). */
const ms = (a: { offset_ms: number | null } | null | undefined) => Math.round(Math.abs(a?.offset_ms ?? 0));
const fits = (r: string | null | undefined) => r === 'exact' || r === 'shifted';

export function upgradeWays(up: Upgrade, swap: boolean): UpgradeWays {
  const r = up.alignment?.result;
  const same: WayOption = { key: 'swap', name: 'Same track', summary: 'Cues and beatgrid stay', outcomes: [
    { tone: 'kept', text: 'Your track keeps its cues' },
    ...(r === 'shifted' && ms(up.alignment) ? [{ tone: 'kept' as const, text: `Moved ${ms(up.alignment)} ms to sit on your cues` }] : [])] };
  const added: WayOption = { key: 'add_new', name: 'New track',
    summary: fits(r) ? 'Relocate your old track to keep cues' : 'Set the cues again', outcomes: [
      { tone: 'step', text: 'rekordbox lists it as a new track' },
      fits(r) ? { tone: 'kept', text: 'Relocate your old track: cues fit' }
        : r === 'different' ? { tone: 'step', text: 'A different edit: set the cues again' }
        : { tone: 'step', text: 'Unsure if your cues fit: listen first' }] };
  if (swap) return { choice: true, options: [same, added], fixed: [], reason: null };
  const reason = r === 'different' ? 'Same track needs the same edit'
    : !fits(r) ? 'Same track needs a measured match' : 'Same track needs an AIFF file';
  return { choice: false, options: [added], fixed: added.outcomes, reason };
}

/** The "Edit" row under the comparison: a fact about the audio (the "In rekordbox" card says what it means). */
export function editLine(a: Alignment | null | undefined): { tone: 'lossless' | 'good_lossy' | 'other'; text: string } {
  const r = a?.result;
  if (r === 'exact') return { tone: 'lossless', text: 'The same edit as yours' };
  if (r === 'shifted') return { tone: 'lossless', text: ms(a) ? `The same edit, ${ms(a)} ms apart` : 'The same edit as yours' };
  if (r === 'different') return { tone: 'good_lossy', text: 'A different edit' };
  return { tone: 'other', text: "Couldn't compare them" };
}

/** The upgrade card's Now: what the current download was made from ("Opus · 135 kbps"), not the file itself (it is
 *  AIFF either way); an own or bought file has no source format, so its quality label stands in. */
export const nowLabel = (t: Pick<TrackDetail, 'source_format_line' | 'quality_label'>): string =>
  t.source_format_line ?? t.quality_label;

/** The main button: what replacing does, named by the result. */
export function replaceLabel(up: Upgrade): string {
  return up.what === 'lossless version' ? 'Replace with lossless' : 'Replace with the better version';
}

// ---------- the rekordbox check after a replace ----------
/** One numbered step: its words, parts in bold (a rekordbox command), and a muted note after them. */
export type CheckStep = { parts: { text: string; strong?: boolean }[]; note?: string };
export type CheckCard = { summary: string; steps: CheckStep[]; hint: string | null };
const RELOCATE_NEW: CheckStep = { parts: [{ text: 'The track shows as missing: ' }, { text: 'Auto Relocate', strong: true },
  { text: ' finds the new file by name' }] };

/** The steps in rekordbox after a swap or an added file (README "Upgrades"); null for any other check (its `text`). */
export function checkCard(c: RekordboxCheckView | undefined): CheckCard | null {
  if (!c) return null;
  const analyse: CheckStep = { parts: [{ text: 'Analyse it again, so the waveform shows the full sound' }],
    note: '(lock the beatgrid first if you set it by hand)' };
  const reload: CheckStep = { parts: [{ text: 'Right-click the track › ' }, { text: 'Reload Tag', strong: true }] };
  if (c.reason === 'swapped') {
    if (c.moved) {
      return { summary: 'same track, cues kept', hint: null, steps: [
        { parts: [{ text: 'The track shows as missing: ' }, { text: 'Auto Relocate', strong: true },
          { text: ' finds it by its name, cues and all' }] }, reload, analyse] };
    }
    return { summary: 'same track, cues kept', steps: [reload, analyse],
      hint: 'Shows as missing? Auto Relocate finds it by its name, cues and all.' };
  }
  if (c.reason === 'added_as_new') {
    const second: CheckStep = c.match === 'exact' ? { parts: [{ text: 'Analyse it again' }], note: '· your cues fit' }
      : c.match === 'shifted' ? { parts: [{ text: 'Analyse it again' }],
        note: ms(c) ? `· your cues fit to within ${ms(c)} ms` : '· your cues fit' }
      : { parts: [{ text: 'Analyse it again and ' }, { text: 'set the cues again', strong: true }],
        note: c.match === 'different' ? '· a different edit' : "· it couldn't be compared" };
    return { summary: 'a new track', steps: [RELOCATE_NEW, second], hint: null };
  }
  return null;
}

/** The folder a path is in ("Library/Hard_Bounce" from "Library/Hard_Bounce/x.aiff"). */
const dirOf = (path: string) => path.slice(0, Math.max(0, path.lastIndexOf('/')));
export type ReplacedRow = { icon: 'file' | 'folder'; name: string; where: string };
export type ReplacedCard = { title: string; rows: ReplacedRow[]; undo: string };
/** "Replaced with lossless": where each file is now, and what Undo puts back. Null for a check of another kind. */
export function replacedCard(c: RekordboxCheckView | undefined, item: Pick<TodoItem, 'path' | 'quality'>): ReplacedCard | null {
  if (!c || (c.reason !== 'swapped' && c.reason !== 'added_as_new')) return null;
  const title = item.quality === 'lossless' ? 'Replaced with lossless' : 'Replaced with the better version';
  const here = item.path ? `in ${dirOf(item.path)}` : 'in your library';
  const old = c.old_path ? `in ${dirOf(c.old_path)}` : 'in Superseded/';
  const now = item.quality === 'lossless' ? 'lossless' : 'the better version';
  if (c.reason === 'swapped') {
    return { title, undo: 'Undo puts your old audio back in the file.', rows: [
      { icon: 'file', name: `Your file, now ${now}`, where: here },
      { icon: 'folder', name: 'A copy of the old audio', where: old }] };
  }
  return { title, undo: 'Undo puts both back as they were.', rows: [
    { icon: 'file', name: `New file, ${now}`, where: here },
    { icon: 'folder', name: 'Your old file', where: old }] };
}
/** A date's calendar day in local time, "YYYY-MM-DD" (as the engine writes `since`). */
export function localDay(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
/** "today" or "31 Oct" for a check's `since` (YYYY-MM-DD), against today's date. */
export function sinceText(since: string | null, today: string): string {
  if (!since) return '';
  return since.slice(0, 10) === today.slice(0, 10) ? 'today' : dayMonth(since);
}

// ---------- duplicates: which file stays ----------
const FORMATS: Record<string, string> = { aiff: 'AIFF', aif: 'AIFF', wav: 'WAV', flac: 'FLAC', mp3: 'MP3', m4a: 'M4A',
  aac: 'AAC', ogg: 'OGG', opus: 'Opus', alac: 'ALAC' };
/** "AIFF" from a file's extension. */
export function fileFormat(path: string): string {
  const ext = /\.([^./]+)$/.exec(path)?.[1]?.toLowerCase() ?? '';
  return FORMATS[ext] ?? ext.toUpperCase();
}
/** The last folder of a file's path ("Old" from ".../Music/Old/x.aiff"). */
export function lastFolder(path: string): string {
  const d = dirOf(path);
  return d.slice(d.lastIndexOf('/') + 1);
}
const FOLDER_IN_LABEL = 16;   // longer folder names make "Keep the one in …" too wide for the foot at 1100
/** What tells this file apart from the others in a few words ("the AIFF", "the lossless file", "the one in Old"), or
 *  null when nothing short does. */
export function fileWords(f: FileSide, files: FileSide[]): string | null {
  const others = files.filter((x) => x.file_id !== f.file_id);
  const fmt = fileFormat(f.path);
  if (fmt && others.every((x) => fileFormat(x.path) !== fmt)) return `the ${fmt}`;
  if (others.every((x) => x.quality_label !== f.quality_label)) {
    return f.quality === 'lossless' ? 'the lossless file' : `the ${f.quality_label} file`;
  }
  const dir = lastFolder(f.path);
  if (dir && dir.length <= FOLDER_IN_LABEL && others.every((x) => lastFolder(x.path) !== dir)) return `the one in ${dir}`;
  return null;
}
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
/** Under the duplicates' button: the files that don't stay aren't deleted (one line at 1100). */
export const SUPERSEDED_NOT_DELETED = 'Not deleted: kept in Superseded/';
/** The pick in "Which file stays?": a file's id, 'all' (Keep both / Keep all), or null (nothing picked yet). */
export type DuplicatePick = number | 'all' | null;
/** The foot's button and the line under it: named by the result ("Keep the AIFF", then "Not deleted: kept in
 *  Superseded/"); with no pick it is off and asks for one. */
export function keepWords(files: FileSide[], pick: DuplicatePick): { label: string; hint: string | null; ready: boolean } {
  if (pick === null) return { label: 'Choose the file that stays', hint: null, ready: false };
  if (pick === 'all') return { label: keepLabel(files.length), hint: null, ready: true };
  const kept = files.find((f) => f.file_id === pick);
  if (!kept) return { label: 'Choose the file that stays', hint: null, ready: false };
  const label = `Keep ${fileWords(kept, files) ?? 'this file'}`;
  // which file leaves is already in its row ("→ Goes to Superseded/"); the line says only that it isn't deleted
  return { label: cap(label), hint: SUPERSEDED_NOT_DELETED, ready: true };
}
/** A duplicate group's id from its file ids (models.group_id): the group left after one of its files moved. */
export function groupIdOf(ids: number[]): string {
  return 'dup:' + [...ids].sort((a, b) => a - b).join('-');
}

// ---------- which decision a track waits for (the Library's details) ----------
/** What the details of one track decide, in the to-do list's order (its groups' order: the rekordbox check, the
 *  duplicates, then the upgrade): the check a replace (or a wrong song) left, a duplicate group one of its files is
 *  in, the upgrade parked for it; null when it waits for none of them. The check and the group come from the to-do
 *  list (the track's details don't carry them); the upgrade from the details, so a track the to-do list doesn't show
 *  (in no playlist) can still be upgraded. */
export type Decision = { kind: 'check'; item: TodoItem } | { kind: 'duplicate'; item: DuplicateItem }
  | { kind: 'upgrade' } | null;
export function decisionFor(items: TodoItem[], track: Pick<TrackDetail, 'track_id' | 'path' | 'upgrade'>): Decision {
  for (const i of items) {
    if (i.group === 'rekordbox_check' && !i.pair && i.track_id === track.track_id) return { kind: 'check', item: i };
    if (isDuplicate(i) && i.pair.files.some((f) => f.song_key === track.track_id || (!!track.path && f.path === track.path))) {
      return { kind: 'duplicate', item: i };
    }
  }
  return track.upgrade ? { kind: 'upgrade' } : null;
}
