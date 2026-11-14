// The decisions a track can wait for, wherever its details show (To-do and the Library; mockup todo-decisions):
// the upgrade ("Replace with lossless", the "In rekordbox" choice), the rekordbox check a replace leaves (its steps,
// what was replaced, Undo), and duplicates ("Which file stays?"). Pure: the words, the choices and their outcomes,
// and which of them the selected Library track waits for (`decisionFor`). The components beside it render them.
import type {
  AiffBatchResult, Alignment, AutoRefused, BatchCheck, DuplicateItem, FileSide, ItemResult, ProblemKind, RekordboxCheckView, TodoItem, TrackDetail,
  UndoResult, Upgrade,
} from '$lib/bridge/types';
import { isBatch, isDuplicate } from '$lib/bridge/types';
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
  /** no choice: what will happen */
  fixed: Outcome[];
  /** why Same track isn't possible, or what it means here (no rekordbox on this Mac); null with a choice */
  reason: string | null;
  /** the way the foot runs without a choice: New track, or Same track's clean AIFF where there is no rekordbox */
  way: Way;
  /** the line under the choice: quit rekordbox first, only where a rekordbox write follows and no outcome says it */
  tip: string | null;
};
export const KEPT_FILE: Outcome = { tone: 'file', text: 'Your old file is kept in Superseded/' };
/** Where a rekordbox write follows (design §8's console tip, plan stage B §6.3) */
export const QUIT_REKORDBOX = 'Quit rekordbox before you replace';
const QUIT_STEP: Outcome = { tone: 'step', text: QUIT_REKORDBOX };
export const BECOMES_AIFF: Outcome = { tone: 'file', text: 'Becomes an AIFF file' };
export const NO_REKORDBOX = 'No rekordbox on this Mac: the new file is a new track';
/** The no-choice card's title: "In rekordbox" would sit over "No rekordbox on this Mac", so there the card is the file's. */
export const waysTitle = (w: Pick<UpgradeWays, 'reason'>): string => (w.reason === NO_REKORDBOX ? 'The new file' : 'In rekordbox');
/** Why Same track can't run for one track, as the line under the "In rekordbox" card (design §8 where it has words;
 *  `needs_choice` is said from the measurement, see upgradeWays). */
const WHY_NOT_LINE: Record<string, string> = {
  rekordbox_unreadable: 'Same track needs a rekordbox library Discjockey can open. Update Discjockey, or replace it as a new track.',
  not_analysed: 'Same track needs the track analysed in rekordbox first. Analyse it there, or replace it as a new track.',
  timing: 'Same track needs the track analysed again in rekordbox. Analyse it again, or replace it as a new track.',
  cloud: "Same track can't change a track in rekordbox's Cloud Library Sync yet. Replace it as a new track instead.",
  file_missing: 'Same track needs your file where Discjockey expects it. Put it back, then try again.',
  away: "Same track needs your file's drive connected. Connect it, then try again.",
};
/** How far apart the two versions start, in whole ms (an alignment or a check's measurement). */
const ms = (a: { offset_ms: number | null } | null | undefined) => Math.round(Math.abs(a?.offset_ms ?? 0));
const fits = (r: string | null | undefined) => r === 'exact' || r === 'shifted';

/** The "In rekordbox" card of one track (plan stage B §6.3). Same track runs for any format now: an AIFF takes the
 *  audio in place (`swap_how` in_place), any other file becomes a new AIFF that rekordbox's track is pointed at
 *  (new_aiff: design §8's three outcomes). Without rekordbox on this Mac there is no track to keep: no choice, "a new
 *  track", and the foot runs Same track's clean AIFF (undoable). */
export function upgradeWays(up: Upgrade, swap: boolean): UpgradeWays {
  const r = up.alignment?.result;
  const newAiff = up.swap_how === 'new_aiff';
  const shifted = r === 'shifted' && ms(up.alignment) ? [{ tone: 'kept' as const, text: `Moved ${ms(up.alignment)} ms to sit on your cues` }] : [];
  const same: WayOption = { key: 'swap', name: 'Same track', summary: 'Cues and beatgrid stay', outcomes: newAiff
    ? [{ tone: 'kept', text: 'Your track keeps its cues, playlists and history' }, ...shifted, BECOMES_AIFF, QUIT_STEP]
    : [{ tone: 'kept', text: 'Your track keeps its cues' }, ...shifted] };
  const added: WayOption = { key: 'add_new', name: 'New track',
    summary: fits(r) ? 'Relocate your old track to keep cues' : 'Set the cues again', outcomes: [
      { tone: 'step', text: 'rekordbox lists it as a new track' },
      fits(r) ? { tone: 'kept', text: 'Relocate your old track: cues fit' }
        : r === 'different' ? { tone: 'step', text: 'A different edit: set the cues again' }
        : { tone: 'step', text: 'Unsure if your cues fit: listen first' }] };
  const ready = up.rekordbox?.state !== 'none';
  if (swap && newAiff && !ready) {
    return { choice: false, options: [same], fixed: [BECOMES_AIFF], reason: NO_REKORDBOX, way: 'swap', tip: null };
  }
  if (swap) {
    return { choice: true, options: [same, added], fixed: [], reason: null, way: 'swap',
      tip: !newAiff && up.rekordbox?.state === 'ready' ? QUIT_REKORDBOX : null };
  }
  const why = up.why_not && up.why_not !== 'needs_choice' ? WHY_NOT_LINE[up.why_not] : undefined;
  const reason = why ?? (r === 'different' ? 'Same track needs the same edit'
    : !fits(r) ? 'Same track needs a measured match' : up.why_not ? "Same track isn't possible for this track right now"
    : 'Same track needs an AIFF file');
  return { choice: false, options: [added], fixed: added.outcomes, reason, way: 'add_new', tip: null };
}
/** The way the foot runs before the user picks: Same track where it can run, else upgradeWays' fixed way. */
export function defaultWay(up: Upgrade | null | undefined, swap: boolean): Way {
  return up ? upgradeWays(up, swap).way : 'add_new';
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
/** Now's Tip (notes problem 6): the value is what the AIFF was made from, which FORMAT in the details doesn't say. Only
 *  for a download (a source format); an own or bought file's quality label needs no such word (the Tip then shows the
 *  value itself when it is cut). */
export const NOW_TIP = 'Your AIFF was made from this';
export const nowTip = (t: Pick<TrackDetail, 'source_format_line'>): string | null => (t.source_format_line ? NOW_TIP : null);

/** The main button: what replacing does, named by the result. */
export function replaceLabel(up: Upgrade): string {
  return up.what === 'lossless version' ? 'Replace with lossless' : 'Replace with the better version';
}

// ---------- the sync's Auto-upgrade in the upgrade panel (issue 33 stage C plan §3, §6.3) ----------
/** Design §8's waiting sentence, with this panel's own action: Replace works only with rekordbox closed, so the Hint says
 *  to quit it first (stage review B8; the list's "press Upgrade all" is the engine's own). */
export const AUTO_WAITS_HINT = 'Waits for rekordbox: it goes in at your next sync, or quit it and press Replace.';
/** To-do's short word for a refusal the sync's phase recorded (views.AUTO_REFUSED_SHORT, capitalised): the sub of a
 *  "Couldn't go in" row on the end screen, where the full sentence is the row's tooltip. */
export const AUTO_REFUSED_SHORT: Record<AutoRefused['reason'], string> = {
  timing: "Couldn't line it up", not_analysed: 'Not analysed in rekordbox', cloud: 'In Cloud Library Sync',
  space: 'Not enough free space', needs_choice: "Couldn't compare it",
};
/** What the sync's last phase left on a parked upgrade, as the panel shows it: the waiting sentence as a Hint under the
 *  actions, or the refusal as a warn NoteCard above them. One of the two, as the to-do row's line (views.upgrade_detail:
 *  waiting first), so the row and the panel never say two things; Replace works either way (plan §0.8). */
export function autoNotes(up: Pick<Upgrade, 'auto_waits' | 'auto_refused'>): { waits: boolean; refused: AutoRefused | null } {
  const waits = !!up.auto_waits;
  return { waits, refused: waits ? null : up.auto_refused ?? null };
}

// ---------- the rekordbox check after a replace ----------
/** One numbered step: its words, parts in bold (a rekordbox command), a muted note after them, and the tracks it is
 *  for when it is for some of several (`list`, names under the words: the batch card's Reload Tag). */
export type CheckStep = { parts: { text: string; strong?: boolean }[]; note?: string; list?: string[] };
/** `lead`: the check's own words when they say more than the steps (a Convert: what became of the file), shown above them. */
export type CheckCard = { summary: string; steps: CheckStep[]; hint: string | null; lead?: string };
/** The checks Convert to AIFF and Give it its clean name leave (issue 33 stage D): Discjockey wrote rekordbox's text
 *  itself and the sound is the same, so there is no Reload Tag and no analyse step. */
export const isOwnCheck = (c: Pick<RekordboxCheckView, 'reason'> | undefined): boolean =>
  c?.reason === 'converted' || c?.reason === 'renamed';
/** An added file is never found by Auto Relocate (its name or extension can differ, and the old file now sits in
 *  Superseded/): the user points the old track at it by hand. */
const RELOCATE_NEW: CheckStep = { parts: [{ text: 'Right-click your old track › ' }, { text: 'Relocate', strong: true },
  { text: ' › choose the new file' }] };

/** The beatgrid note of every "analyse again" step (design §8's check text). */
const BEATGRID = '(lock the beatgrid first if you set it by hand)';
/** design §8's USB step, result 3 (until the live test says otherwise). */
export const USB_STEP: CheckStep = { parts: [{ text: 'On a USB stick? The stick still plays the old file. ' },
  { text: 'Rebuild the stick', strong: true }, { text: ' in rekordbox before your next gig' }] };
/** Whether a Same track step left the track in rekordbox (it wrote rekordbox's own track): false for a file rekordbox
 *  doesn't have (no rekordbox on this Mac, or not in its collection), where there is nothing to do there. A swap from
 *  before stage B (no `rekordbox` record) is in rekordbox: that is why it left a check. */
export function inRekordbox(c: Pick<RekordboxCheckView, 'reason' | 'rekordbox'> | undefined): boolean {
  if (!c) return false;
  if (c.rekordbox) return c.rekordbox.entries > 0;
  return c.reason === 'swapped';
}
/** "Kept your own title and artist in rekordbox" (design §8's result note, kept edit); '' when nothing was kept. */
export function keptLine(kept: string[] | undefined | null): string {
  const k = kept ?? [];
  if (!k.length) return '';
  const words = k.length === 1 ? k[0] : `${k.slice(0, -1).join(', ')} and ${k.at(-1)}`;
  return `Kept your own ${words} in rekordbox`;
}
/** design §8's result note for a file rekordbox doesn't have, shortened to a row's sub-line (the same meaning). */
export const NOT_IN_REKORDBOX = 'Not in your rekordbox collection, so there was nothing to keep there';

/** The steps in rekordbox after a swap, an added file or Same track's new AIFF (README "Upgrades"); null for any
 *  other check (its `text`), and for a new AIFF rekordbox doesn't have (its text says so). Reload Tag only where
 *  Discjockey couldn't write rekordbox's text itself (`reload_tag`): where it could, Reload Tag would only overwrite
 *  the user's own edits. */
export function checkCard(c: RekordboxCheckView | undefined): CheckCard | null {
  if (!c) return null;
  const analyse: CheckStep = { parts: [{ text: 'Analyse it again, so the waveform shows the full sound' }], note: BEATGRID };
  const reload: CheckStep = { parts: [{ text: 'Right-click the track › ' }, { text: 'Reload Tag', strong: true }] };
  const reloads = c.reload_tag ? [reload] : [];
  // a Convert's rekordbox track plays the new file with everything it had: only a USB stick still has the old one; a
  // clean name (and a file rekordbox doesn't have) leaves nothing to do, the check's words say it whole
  if (c.reason === 'converted') {
    if (!inRekordbox(c)) return null;
    return { summary: 'same track, cues kept', steps: [USB_STEP], hint: keptLine(c.rekordbox?.kept) || null, lead: c.text };
  }
  if (c.reason === 'renamed') return null;
  if (c.reason === 'repointed') {
    if (!inRekordbox(c)) return null;
    return { summary: 'same track, cues kept', steps: [...reloads, analyse, USB_STEP],
      hint: keptLine(c.rekordbox?.kept) || null };
  }
  if (c.reason === 'swapped') {
    if (c.moved) {
      return { summary: 'same track, cues kept', hint: null, steps: [
        { parts: [{ text: 'The track shows as missing: ' }, { text: 'Auto Relocate', strong: true },
          { text: ' finds it by its name, cues and all' }] }, ...reloads, analyse] };
    }
    return { summary: 'same track, cues kept', steps: [...reloads, analyse],
      hint: keptLine(c.rekordbox?.kept) || 'Shows as missing? Auto Relocate finds it by its name, cues and all.' };
  }
  if (c.reason === 'added_as_new') {
    const lined = c.aligned && (c.match === 'exact' || c.match === 'shifted');
    const second: CheckStep = lined ? { parts: [{ text: 'Analyse it again' }], note: '· your cues fit exactly' }
      : c.match === 'exact' ? { parts: [{ text: 'Analyse it again' }], note: '· your cues fit' }
      : c.match === 'shifted' ? { parts: [{ text: 'Analyse it again' }],
        note: ms(c) ? `· your cues fit to within ${ms(c)}\u00a0ms` : '· your cues fit' }
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
  if (c?.reason === 'converted') {
    return { title: 'Converted to AIFF', undo: inRekordbox(c) ? 'Undo points rekordbox back at your old file.'
      : 'Undo puts your old file back as it was.', rows: [
      { icon: 'file', name: 'New AIFF with a clean name', where: item.path ? `in ${dirOf(item.path)}` : 'in your library' },
      { icon: 'folder', name: 'Your old file', where: c.old_path ? `in ${dirOf(c.old_path)}` : 'in Superseded/' }] };
  }
  if (c?.reason === 'renamed') {
    return { title: 'Given its clean name', undo: inRekordbox(c) ? 'Undo gives it its old name and points rekordbox back at it.'
      : 'Undo gives it its old name back.', rows: [
      { icon: 'file', name: item.path ? fileName(item.path) : 'Its clean name', where: 'its name now' },
      { icon: 'file', name: c.old_name ?? 'Its old name', where: 'its name before' }] };
  }
  if (!c || (c.reason !== 'swapped' && c.reason !== 'added_as_new' && c.reason !== 'repointed')) return null;
  const title = item.quality === 'lossless' ? 'Replaced with lossless' : 'Replaced with the better version';
  const here = item.path ? `in ${dirOf(item.path)}` : 'in your library';
  const old = c.old_path ? `in ${dirOf(c.old_path)}` : 'in Superseded/';
  const now = item.quality === 'lossless' ? 'lossless' : 'the better version';
  if (c.reason === 'swapped') {
    return { title, undo: 'Undo puts your old audio back in the file.', rows: [
      { icon: 'file', name: `Your file, now ${now}`, where: here },
      { icon: 'folder', name: 'A copy of the old audio', where: old }] };
  }
  if (c.reason === 'repointed') {
    return { title, undo: inRekordbox(c) ? 'Undo points rekordbox back at your old file.'
      : 'Undo puts your old file back as it was.', rows: [
      { icon: 'file', name: `New AIFF, ${now}`, where: here },
      { icon: 'folder', name: 'Your old file', where: old }] };
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
    // a track a batch upgraded is decided on its own here (its single check card): the batch is one item in To-do
    const own = isBatch(i) ? i.batch.tracks.find((t) => t.track_id === track.track_id) : i;
    if (own && own.group === 'rekordbox_check' && !own.pair && own.track_id === track.track_id) return { kind: 'check', item: own };
    if (isDuplicate(i) && i.pair.files.some((f) => f.song_key === track.track_id || (!!track.path && f.path === track.path))) {
      return { kind: 'duplicate', item: i };
    }
  }
  return track.upgrade ? { kind: 'upgrade' } : null;
}

// ---------- several upgrades selected (plan stage B §6.2) ----------
/** Why Same track can't run for a row of the selection (TodoItem `same_track`), in a few words for its sub-line. */
const SAME_TRACK_WHY: Record<string, string> = {
  needs_choice: 'needs your choice', no_upgrade: 'no new version waiting', file_missing: 'file not found',
  away: 'drive not connected', rekordbox_unreadable: "rekordbox's library can't be opened",
  timing: 'analyse it again in rekordbox', not_analysed: 'not analysed in rekordbox yet',
  cloud: "in rekordbox's Cloud Library Sync", rekordbox_open: 'rekordbox is open',
  busy: 'rekordbox is being changed elsewhere', unclean: "rekordbox didn't close normally",
  changed: 'changed in rekordbox meanwhile', space: 'not enough free space', rename_blocked: "can't be renamed now",
};
export function sameTrackWhy(reason: string | null | undefined): string {
  if (!reason) return 'Same track';
  return SAME_TRACK_WHY[reason] ?? "can't be upgraded right now";
}
/** Reasons that keep a track out of any upgrade, New track too: there is nothing to replace, or no file to replace. */
const NOWHERE = ['no_upgrade', 'file_missing', 'away'];
/** Whether an item of the selection is replaced by the way picked. */
export function goes(i: Pick<TodoItem, 'same_track'>, way: Way): boolean {
  return way === 'swap' ? !i.same_track : !NOWHERE.includes(i.same_track ?? '');
}
const isAiff = (path: string | null) => !!path && /\.aiff?$/i.test(path);
/** The engine's row line starts "Lossless ready" for a lossless upgrade (views.upgrade_status), "320 kbps ready" else. */
const lossless = (i: Pick<TodoItem, 'detail'>) => i.detail.startsWith('Lossless');
const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);

export type SelectionWays = UpgradeWays & {
  /** Same track can run / needs your choice / waits for something else (the before-line, design §8) */
  n: number; m: number; k: number;
  /** how many each way replaces */
  count: Record<Way, number>;
};
/** The "In rekordbox" card for several upgrades: Same track · n (recommended) and New track · N; the before-line
 *  (`beforeLine`) is the panel head's, said once. With no item for Same track there is no choice: "a new track" and why. */
export function selectionWays(items: Pick<TodoItem, 'same_track' | 'path'>[]): SelectionWays {
  const n = items.filter((i) => !i.same_track).length;
  const m = items.filter((i) => i.same_track === 'needs_choice').length;
  const k = items.length - n - m;
  const count = { swap: n, add_new: items.filter((i) => goes(i, 'add_new')).length };
  const aiffAll = items.filter((i) => goes(i, 'swap')).every((i) => isAiff(i.path));
  const same: WayOption = { key: 'swap', name: `Same track · ${n}`, summary: 'Cues and beatgrid stay', outcomes: [
    { tone: 'kept', text: `${n} ${plural(n, 'keeps its cues, playlists and history', 'keep their cues, playlists and history')}` },
    ...(aiffAll ? [] : [{ tone: 'file' as const, text: "Files that aren't AIFF become AIFF files" }]),
    QUIT_STEP] };
  // `needs_choice` is a different edit or one nobody measured (the item doesn't say which): "may be" is true of both
  const differ = m;
  const added: WayOption = { key: 'add_new', name: `New track · ${count.add_new}`,
    summary: differ ? 'Cues may need setting again' : 'Relocate your old tracks to keep cues', outcomes: [
      { tone: 'step', text: 'rekordbox lists them as new tracks' },
      differ ? { tone: 'step', text: `${differ} may be another edit: listen first` }
        : { tone: 'kept', text: 'Relocate your old tracks: cues fit' }] };
  if (n) return { choice: true, options: [same, added], fixed: [], reason: null, way: 'swap', tip: null, n, m, k, count };
  const reason = m === items.length ? 'Same track needs the same edit' : 'None of these can stay the same track: each row says why';
  return { choice: false, options: [added], fixed: added.outcomes, reason, way: 'add_new', tip: null, n, m, k, count };
}
/** The panel head's before-line (design §8: "{n} upgrades keep their cues. {m} need your choice and stay.", plan §3 adds
 *  "{k} wait for something else."): what Same track does for the selection and what stays. Null when nothing stays (the
 *  Same track outcome already says all of them keep their cues) or nothing can be Same track (the card says why). */
export function beforeLine(w: Pick<SelectionWays, 'n' | 'm' | 'k'>): string | null {
  if (!w.n || !(w.m || w.k)) return null;
  return [`${w.n} ${plural(w.n, 'upgrade keeps its cues.', 'upgrades keep their cues.')}`,
    ...(w.m ? [`${w.m} ${plural(w.m, 'needs your choice and stays.', 'need your choice and stay.')}`] : []),
    ...(w.k ? [`${w.k} ${plural(w.k, 'waits for something else.', 'wait for something else.')}`] : [])].join(' ');
}
/** "Upgrade all · n" is offered from two: with one, the row's own button does it. */
export const upgradeAllShown = (n: number): boolean => n >= 2;
/** The CDJ group's head: "Convert all · n" (shown from two, as "Upgrade all"). */
export const convertAllLabel = (n: number): string => `Convert all · ${n}`;
/** The selection's main button, named by the result and the count the picked way replaces. */
export function replaceManyLabel(count: number, items: Pick<TodoItem, 'detail'>[]): string {
  return items.every(lossless) ? `Replace ${count} with lossless` : `Replace ${count} with the better versions`;
}
export const discardLabel = (n: number): string => `Discard ${n} new ${plural(n, 'version', 'versions')}`;
export const discardConfirm = (n: number) => ({ title: `Throw away ${n} new ${plural(n, 'version', 'versions')}?`,
  body: 'Your current files stay. These versions are not offered again.', confirmLabel: 'Discard', tone: 'danger' as const });
export const selectedTitle = (n: number): string => `${n} upgrades selected`;
export const resumeLabel = (left: number): string => `Resume · ${left} left`;
export const upgradeAllLabel = (n: number): string => `Upgrade all · ${n}`;

// ---------- a batch running and its end (plan stage B §6.2) ----------
export type BatchMode = Way | 'discard';
/** One row of the running panel: `now` the track in work, `handled` passed (done or skipped is only known at the end),
 *  then the end's own state and words. */
export type RunRow = { track_id: string; name: string; sub: string; cover_url: string | null;
  state: 'waiting' | 'now' | 'handled' | 'done' | 'skipped' | 'failed'; text: string | null };
export const runRow = (i: Pick<TodoItem, 'track_id' | 'folder' | 'cover_url'>, name: string): RunRow =>
  ({ track_id: i.track_id, name, sub: i.folder, cover_url: i.cover_url, state: 'waiting', text: null });
/** BatchProgress: the track it names is now in work, the one before it is handled; null after the last. A track the
 *  rows don't hold (a resumed batch, a batch found running) is added under its name. */
export function progressRows(rows: RunRow[], e: { track_id: string | null; name: string | null }): RunRow[] {
  const out = rows.map((r) => (r.state === 'now' && r.track_id !== e.track_id ? { ...r, state: 'handled' as const } : r));
  if (e.track_id === null) return out;
  const at = out.findIndex((r) => r.track_id === e.track_id);
  if (at < 0) return [...out, { track_id: e.track_id, name: (e.name ?? e.track_id).replace(' - ', ' – '), sub: '', cover_url: null,
    state: 'now', text: null }];
  out[at] = { ...out[at], state: 'now' };
  return out;
}
/** The rows with the end's answer per track: done, skipped or failed with the engine's words; a track the batch never
 *  reached (stopped) waits. A track the answer holds that has no row (a Resume starts with none, a batch found running
 *  starts from its last event, a track skipped before it was in work) gets one, named by `nameOf` (else its id). */
export function endRows(rows: RunRow[], results: ItemResult[], nameOf: (track_id: string) => string | null = () => null): RunRow[] {
  // no answer per track (a job that failed outright): what passed stays "passed", nothing is claimed done
  if (!results.length) return rows.map((r) => (r.state === 'now' ? { ...r, state: 'handled' as const } : r));
  const have = new Set(rows.map((r) => r.track_id));
  const added: RunRow[] = [];
  for (const r of results) {
    if (have.has(r.track)) continue;
    have.add(r.track);
    added.push({ track_id: r.track, name: nameOf(r.track) ?? r.track, sub: '', cover_url: null, state: 'waiting', text: null });
  }
  const by = new Map(results.map((r) => [r.track, r]));
  return [...rows, ...added].map((r) => {
    const x = by.get(r.track_id);
    if (!x) return r.state === 'now' || r.state === 'handled' ? { ...r, state: 'done' } : r;
    if (x.state === 'done') return { ...r, state: 'done', text: null };
    if (x.state === 'skipped' || x.state === 'failed') return { ...r, state: x.state, text: cap(x.message ?? sameTrackWhy(x.reason)) };
    return { ...r, state: 'waiting', text: null };
  });
}
/** Whether an end is worth the same call again: something outside the batch was in the way (rekordbox open, another
 *  writer, an error), and its batch can't be resumed. A finished or refused batch would only do the same again. */
export const canTryAgain = (e: Pick<BatchEnd, 'kind' | 'resume'>): boolean =>
  !e.resume && (e.kind === 'rekordbox_open' || e.kind === 'busy' || e.kind === 'failed');
/** The ended panel's lists: the tracks not done (skipped, failed: with their reasons) and those the batch didn't reach. */
export function endGroups(rows: RunRow[]): { notDone: RunRow[]; left: RunRow[] } {
  return { notDone: rows.filter((r) => r.state === 'skipped' || r.state === 'failed'),
    left: rows.filter((r) => r.state === 'waiting') };
}
export const leftTitle = (k: number): string => `${k} left`;
/** The ended panel's number is dropped where the note already says it ("Stopped after 2 of 4.", rekordbox opening
 *  mid-way): the same count twice in one panel reads as two facts. */
export const endNoteSaysCount = (e: Pick<BatchEnd, 'kind' | 'done'>): boolean =>
  e.kind === 'stopped' || (e.kind === 'rekordbox_open' && e.done > 0);
/** The running panel's number: how many are done, of how many (the track in work is the label's). */
export const runUnit = (total: number): string => `of ${total} done`;
/** The running panel's label under the number: what is going on, with the track in work. */
export function runLabel(mode: BatchMode, now: string | null): string {
  const what = mode === 'add_new' ? 'Adding as new tracks' : mode === 'discard' ? 'Discarding' : 'Upgrading';
  return now ? `${what} · ${now}` : what;
}
/** How a batch ended, for the panel: `resume` while its batch is stopped with tracks left. */
export type BatchEnd = { mode: BatchMode; kind: 'done' | 'stopped' | 'rekordbox_open' | 'busy' | 'refused' | 'failed';
  done: number; total: number; message: string; resume: { batch_id: number; left: number } | null };
export function batchEnd(mode: BatchMode, out: { ok: boolean; kind?: ProblemKind; message?: string;
  result?: AiffBatchResult | null }): BatchEnd {
  const r = out.result ?? null;
  const done = r ? r.results.filter((x) => x.state === 'done').length : 0;
  const total = r?.total ?? 0;
  const left = r ? r.results.filter((x) => x.state === 'planned').length : 0;
  const resume = r && r.batch !== null && r.state === 'stopped' && left ? { batch_id: r.batch, left } : null;
  if (out.ok) return { mode, kind: 'done', done, total, message: '', resume: null };
  const kind = out.kind === 'stopped' || out.kind === 'rekordbox_open' || out.kind === 'busy' || out.kind === 'refused'
    ? out.kind : 'failed';
  return { mode, kind, done, total, message: out.message ?? '', resume };
}
/** The end's number and its words (§3: "{n} upgraded, your cues stayed."). */
export function endWords(e: Pick<BatchEnd, 'mode' | 'done'>): { unit: string; label: string } {
  const unit = plural(e.done, 'track', 'tracks');
  if (e.mode === 'add_new') return { unit, label: 'added as new' };
  if (e.mode === 'discard') return { unit: plural(e.done, 'new version', 'new versions'), label: 'discarded' };
  return { unit, label: e.done ? 'upgraded, your cues stayed' : 'upgraded' };
}
/** Where focus goes when the selection panel's foot changes under it (the pressed button is gone): Stop while a batch
 *  runs, then at its end the filled button, Resume / Try again / Done. `data-test` of the button; null: no phase. */
export function panelFocus(v: { phase: 'running' | 'ended'; end: { resume: unknown } | null; again: unknown } | null | undefined):
  string | null {
  if (!v) return null;
  if (v.phase === 'running') return 'batch-stop';
  return v.end?.resume ? 'batch-resume' : v.again ? 'batch-again' : 'batch-close';
}
/** The selection panel's ✕ took a row out: the row that now stands at its place (the last one when it was last), its
 *  ✕ is where focus goes; null when no row is left (the panel gives way to the details). */
export function focusAfterDrop<T>(rows: T[], at: number): T | null {
  const left = rows.filter((_, i) => i !== at);
  return left.length ? left[Math.min(at, left.length - 1)] : null;
}
/** A row of the batch card left (its undo): the next track with an undo of its own, else the one before it; null when
 *  none is left (focus then goes to Done). `before` / `after`: the track ids in order, `withUndo` those that can still be undone. */
export function focusAfterRowGone(before: string[], after: string[], withUndo: ReadonlySet<string>): string | null {
  const gone = before.findIndex((id) => !after.includes(id));
  if (gone < 0) return null;
  const later = before.slice(gone + 1).filter((id) => after.includes(id) && withUndo.has(id));
  if (later.length) return later[0];
  const earlier = before.slice(0, gone).filter((id) => after.includes(id) && withUndo.has(id));
  return earlier.at(-1) ?? null;
}
export const notDoneTitle = (m: number, mode: BatchMode): string =>
  `${m} not ${mode === 'discard' ? 'discarded' : 'upgraded'}`;
/** The note over a batch that ended early (design §8's words; §3's stopped line). */
export function endNote(e: BatchEnd): { tone: 'info' | 'warn'; text: string } | null {
  if (e.kind === 'stopped') return { tone: 'info', text: `Stopped after ${e.done} of ${e.total}.` };
  if (e.kind === 'rekordbox_open') {
    return { tone: 'warn', text: e.done ? `rekordbox was opened, so Discjockey stopped after ${e.done} of ${e.total}. Quit rekordbox and press Resume.`
      : 'rekordbox is open. Quit rekordbox, then try again. Discjockey changes your rekordbox tracks only while rekordbox is closed.' };
  }
  if (e.kind === 'busy') return { tone: 'warn', text: 'Discjockey is already changing your rekordbox library in another window or the Terminal.' };
  if (e.kind === 'refused') return { tone: 'warn', text: e.message || 'None of these can be upgraded right now.' };
  if (e.kind === 'failed') return { tone: 'warn', text: e.message || "That didn't work." };
  return null;
}

// ---------- the rekordbox checks of a batch, and several checks selected (plan stage B §6.4) ----------
/** The tracks a list of check items stands for: a batch item gives its tracks, every other item itself. */
export function checkTracks(items: TodoItem[]): TodoItem[] {
  return items.flatMap((i) => (isBatch(i) ? i.batch.tracks : [i]));
}
/** A batch item's row in the to-do list: "{n} tracks upgraded" over "{day} · Same track" (§3). */
export const batchRowName = (n: number, kind: BatchCheck['kind'] = null): string =>
  (kind === 'convert' || kind === 'mixed' ? `${n} tracks` : `${n} tracks upgraded`);
/** What a batch's row says it was: "Same track", or for the sync's Auto-upgrade "Upgraded during your sync" (plan §3). */
export const AUTO_BATCH_SUB = 'Upgraded during your sync';
export const isAutoBatch = (startedBy: string | null | undefined): boolean => startedBy === 'auto_upgrade';
export function batchRowSub(started: string | null, today: string, startedBy: string | null = null,
  kind: BatchCheck['kind'] = null, renamed = false): string {
  const day = sinceText(started, today);
  // a Convert batch says what it made ("Clean name" when every check is a clean name, the engine's own word)
  const how = isAutoBatch(startedBy) ? AUTO_BATCH_SUB : kind === 'convert' || kind === 'mixed' ? (renamed ? 'Clean name' : 'Made AIFF') : 'Same track';
  return day ? `${day} · ${how}` : how;
}
/** The "In rekordbox" card of a batch: the steps for the tracks rekordbox has (Reload Tag only for the tracks whose
 *  text Discjockey couldn't write, by name; design §8's words for several tracks), null when rekordbox has none of
 *  them (each row then says so). */
export function batchCheckCard(tracks: TodoItem[], nameOf: (i: TodoItem) => string): CheckCard | null {
  const rb = tracks.filter((t) => inRekordbox(t.check));
  // a clean name leaves nothing to do in rekordbox; a Convert only the USB stick (the sound is the same, the text is
  // written): the steps below are for the upgrades among them
  const ups = rb.filter((t) => !isOwnCheck(t.check));
  const usb = rb.filter((t) => t.check?.reason !== 'renamed');
  if (!usb.length) return null;
  const many = usb.length > 1;
  const reload = ups.filter((t) => t.check?.reload_tag);
  const moved = ups.filter((t) => t.check?.reason === 'swapped' && t.check.moved);
  const steps: CheckStep[] = [];
  if (moved.length) {
    steps.push({ parts: [{ text: moved.length > 1 ? 'These show as missing: ' : 'This one shows as missing: ' },
      { text: 'Auto Relocate', strong: true }, { text: moved.length > 1 ? ' finds them by their names, cues and all'
        : ' finds it by its name, cues and all' }], list: moved.map(nameOf) });
  }
  if (reload.length) {
    steps.push({ parts: [{ text: "In rekordbox's Collection, select " },
      { text: reload.length > 1 ? 'these tracks (⌘-click each)' : 'this track' }, { text: ', right-click › ' },
      { text: 'Reload Tag', strong: true }, { text: ' · ' }, { text: "don't select all", strong: true },
      { text: ': it replaces every name you changed in rekordbox' }], list: reload.map(nameOf) });
  }
  if (ups.length) {
    steps.push({ parts: [{ text: ups.length > 1 ? 'Analyse them again, so the waveform shows the full sound'
      : 'Analyse it again, so the waveform shows the full sound' }], note: BEATGRID });
  }
  steps.push(many ? { parts: [{ text: 'On a USB stick? The stick still plays the old files. ' },
    { text: 'Rebuild the stick', strong: true }, { text: ' in rekordbox before your next gig' }] } : USB_STEP);
  return { summary: many ? 'same tracks, cues kept' : 'same track, cues kept', steps, hint: null };
}
/** The batch list's title ("Upgraded", "Made AIFF" for Converts, "Clean names" when all are clean names, "Changed" for a mix). */
export function batchListTitle(tracks: Pick<TodoItem, 'check'>[]): string {
  const r = tracks.map((t) => t.check?.reason);
  if (r.length && r.every((x) => x === 'converted')) return 'Made AIFF';
  if (r.length && r.every((x) => x === 'renamed')) return 'Clean names';
  return r.some((x) => x === 'converted' || x === 'renamed') ? 'Changed' : 'Upgraded';
}
/** One track's row on a batch card or in several selected checks: its new file's name (batch) or what is left to do
 *  in rekordbox (several checks: the to-do row's own line), and the notes design §8 gives a track's result. */
export type CheckRow = { track_id: string; name: string; sub: string; notes: string[]; can_undo: boolean;
  cover_url: string | null };
export function checkRow(i: TodoItem, name: string, sub: 'file' | 'detail'): CheckRow {
  const c = i.check;
  const notes = [keptLine(c?.rekordbox?.kept)];
  if ((c?.reason === 'repointed' || isOwnCheck(c)) && !inRekordbox(c)) notes.push(NOT_IN_REKORDBOX);
  return { track_id: i.track_id, name, cover_url: i.cover_url, can_undo: !!i.can_undo,
    sub: sub === 'file' && i.path ? fileName(i.path) : i.detail, notes: notes.filter(Boolean) };
}
export const checksTitle = (n: number): string => `${n} ${plural(n, 'check', 'checks')} selected`;
/** The selection list's summary: its tracks (a batch among the checks counts for all of its tracks). */
export const tracksSummary = (n: number): string => `${n} ${plural(n, 'track', 'tracks')}`;
/** "Undo all {n}" (every track can go), "Undo {n}" (n: the tracks that can be undone). */
export const undoAllLabel = (n: number): string => `Undo all ${n}`;
export const undoManyLabel = (n: number): string => `Undo ${n}`;
/** The sync's batch: "Undo all from this sync" in place of "Undo all {n}" (design §2.5, plan §3). */
export const UNDO_SYNC_LABEL = 'Undo all from this sync';
/** The foot's undo for the tracks of a batch card or several checks: the tracks that can be undone now (a track whose
 *  undo was just refused isn't offered again until the next pick), the button's words ("Undo all {n}" only when every
 *  track can go, else "Undo {n}") and the muted line for the tracks that have nothing to undo ("{k} can't be undone";
 *  the refused ones say why in their rows and under the buttons). */
export function undoFoot(tracks: Pick<TodoItem, 'track_id' | 'can_undo'>[], refused: Record<string, string> = {},
  fromSync = false): { ids: string[]; label: string; cant: string | null } {
  const ids = tracks.filter((t) => t.can_undo && !refused[t.track_id]).map((t) => t.track_id);
  const none = tracks.filter((t) => !t.can_undo).length;
  const all = fromSync ? UNDO_SYNC_LABEL : undoAllLabel(ids.length);
  return { ids, label: ids.length === tracks.length ? all : undoManyLabel(ids.length),
    cant: none ? `${none} can't be undone` : null };
}
/** What an undo asks and what its button says, by what is undone: an upgrade's replace (its new version waits again), a
 *  Convert (the old file comes back) or a clean name (the old name comes back); a mix of kinds says the common words.
 *  `confirmLabel` is the button's. One check: its own question; several: how many. */
export function undoAsk(checks: (Pick<RekordboxCheckView, 'reason'> | undefined)[]): { title: string; body: string; confirmLabel: string } {
  const own = checks.filter(isOwnCheck).length;
  const n = checks.length;
  if (!own) return n === 1 ? { title: 'Undo the replace?', confirmLabel: 'Undo the replace',
    body: checks[0]?.reason === 'swapped' ? 'Your old audio goes back in the file. The new version waits in Upgrades ready again.'
      : 'Your old file goes back where it was. The new version waits in Upgrades ready again.' } : undoManyConfirm(n);
  const reasons = new Set(checks.map((c) => c?.reason));
  if (n === 1 && reasons.has('converted')) return { title: 'Undo the conversion?', confirmLabel: 'Undo the conversion',
    body: 'Your old file goes back where it was, and your rekordbox track plays it again.' };
  if (n === 1) return { title: 'Undo the clean name?', confirmLabel: 'Undo the clean name',
    body: 'Your file gets its old name back, and your rekordbox track follows it.' };
  const what = own === n && reasons.size === 1 ? (reasons.has('converted') ? 'conversions' : 'clean names') : 'changes';
  return { title: `Undo ${n} ${what}?`, confirmLabel: `Undo ${n}`,
    body: own === n && reasons.size === 1 ? (reasons.has('converted') ? 'Your old files go back where they were.' : 'Your files get their old names back.')
      : 'Your old files and names go back where they were.' };
}
/** The single check's undo button: "Undo the replace" for an upgrade, "Undo the conversion", "Undo the clean name". */
export const undoLabel = (c: Pick<RekordboxCheckView, 'reason'> | undefined): string => undoAsk([c]).confirmLabel;
export const undoManyConfirm = (n: number) => ({ title: `Undo ${n} ${plural(n, 'replace', 'replaces')}?`,
  body: n === 1 ? 'Your old file goes back where it was. The new version waits in Upgrades ready again.'
    : 'Your old files go back where they were. The new versions wait in Upgrades ready again.',
  confirmLabel: `Undo ${n}` });
/** The toast after an undo of several, by how many came back (one: the single undo's own words). */
export const undoneToast = (n: number): string => (n === 1 ? 'Upgrade undone. Your old file is back.'
  : `${n} upgrades undone. Old files are back.`);
/** What an undo of several left to say (design §8's undo words): the tracks not undone with their reasons, shown in
 *  their rows, and one line under the buttons (rekordbox open: §8's words; a refusal before the job: its words;
 *  tracks refused: how many, each row says why). Null when everything was undone. `tone`: a step left for the user
 *  or something to wait for (rekordbox open, busy, tracks refused, as their rows) is `warn`; only a failure is `problem`. */
export type UndoProblem = { line: string; rows: Record<string, string>; tone: 'warn' | 'problem';
  /** the one track the line is about when exactly one wasn't undone (the foot names it), else null */
  track: string | null };
/** The line under the buttons: one track not undone is named (the foot works with its row scrolled away), several are
 *  counted (each row says why), and any other problem (rekordbox open, busy) is its own words. */
export function undoProblemLine(p: UndoProblem, nameOf: (id: string) => string): string {
  return p.track ? `${nameOf(p.track)} not undone` : p.line;
}
export function undoProblem(out: { ok: boolean; kind?: ProblemKind; message?: string; result?: UndoResult | null }):
  UndoProblem | null {
  const r = out.result ?? null;
  const rows: Record<string, string> = {};
  for (const x of r?.results ?? []) {
    if (x.state === 'refused' || x.state === 'failed') rows[x.track] = cap(x.message || 'Not undone');
  }
  const refused = Object.keys(rows).length;
  if (!out.ok && (out.kind === 'rekordbox_open' || !refused)) {
    return { line: out.message || "That didn't work.", rows, track: null,
      tone: out.kind === 'failed' || out.kind === 'crashed' || !out.kind ? 'problem' : 'warn' };
  }
  if (!refused) return null;
  return { line: `${refused} not undone: ${refused > 1 ? 'each row says why' : 'its row says why'}`, rows, tone: 'warn',
    track: refused === 1 ? Object.keys(rows)[0] : null };
}
