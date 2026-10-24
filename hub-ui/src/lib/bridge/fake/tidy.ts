// Fake mode: the tidy-up, the move log, undo and the save question (plan library stage 2, I5/I6). The words are
// views.py's, verbatim. A file's target is its track's `folder`; where it sits is `at ?? folder`.
import type { HubEvent } from '../events';
import type {
  BatchResult, MoveBatch, MoveBatches, RenameOffer, SaveFiles, SkippedMove, TidyPreview, TidyRow, UndoPreview,
} from '../types';
import { pathOf, trackRow, type FakeBatch, type FakeMove, type FakeState, type FakeTrack } from './data';

const SKIP_OFFLINE = 'Offline, skipped';
const SKIP_NOT_FOUND = 'Not where Discjockey last saw it';
const SKIP_CHANGED = 'Changed since the list was shown';
const SKIP_STOPPED = 'Not moved: the moves were stopped first';
const SKIP_MOVED_ON = 'Moved or changed since';
const FAILED_FULL = "Couldn't move it: the drive is full";
export const NO_BATCH = 'Discjockey has no record of these moves.';
export const NOTHING_CHOSEN = 'No files were chosen to move.';
const FOLDER_TAKEN = (name: string) => `A folder called ${name} is already in your Library.`;
const EMPTY = 'Every file is where the playlist order puts it.';
const REKORDBOX = ['rekordbox may show the moved tracks as missing.',
  'Its Relocate finds them again by file name: Discjockey never renames them.'];
const UNDO_NOTE = 'You can undo this on this page.';
const SKIPPED_TEXT = { offline: SKIP_OFFLINE, not_found: SKIP_NOT_FOUND } as const;

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many.replace('{n}', String(n)));
const sub = (t: FakeTrack) => (t.status === 'lossless' ? '' : '/not_lossless');
/** a folder of `Library/` as the page shows it (relative; the not_lossless sub-folder included) */
const dirOf = (t: FakeTrack, folder: string) => `${folder}${sub(t)}`;
/** the folder part of a snapshot path, relative to `Library/` */
const folderOfPath = (path: string) => path.replace(/^Library\//, '').split('/').slice(0, -1).join('/');
const fileId = (s: FakeState, t: FakeTrack) => s.tracks.indexOf(t) + 1;
export const trackOfId = (s: FakeState, id: number) => (Number.isInteger(id) ? s.tracks[id - 1] : undefined);
const placedBy = (s: FakeState, t: FakeTrack): 'app' | 'user' | 'import' => s.tidy.placed[t.track_id] ?? 'app';
export const hasFile = (t: FakeTrack) => t.status !== 'missing';
export const outOfPlace = (t: FakeTrack) => hasFile(t) && t.in_playlists && t.at !== undefined && t.at !== t.folder;

// ---------- the seed: a believable library (tidy_preview rows, a move log with one moved-on file) ----------

/** Called once by createFakeBridge: some files out of place (app, user, name taken, offline) and a short log. */
export function seedTidy(s: FakeState): void {
  const files = s.tracks.filter((t) => hasFile(t) && t.in_playlists && !t.other && !t.rekordbox_check && !t.hidden
    && !t.upgrade && s.playlists.some((p) => p.folder === t.folder));
  if (files.length < 12) return;
  const folders = s.playlists.map((p) => p.folder);
  const elsewhere = (t: FakeTrack, n = 0) => folders.filter((f) => f !== t.folder)[n % (folders.length - 1)];
  const [a, b, c, d, e, f, g, h, i, j, k, l] = files;
  for (const [n, t] of [a, b, c].entries()) t.at = elsewhere(t, n);
  for (const t of [d, e]) { t.at = 'Elsewhere'; s.tidy.placed[t.track_id] = 'user'; }
  f.at = elsewhere(f, 1); s.tidy.skips[f.track_id] = 'name_taken';
  g.at = elsewhere(g, 2); s.tidy.skips[g.track_id] = 'offline';
  // the log: a tidy-up two days ago (i has been moved by hand since), a save an hour ago
  i.at = 'Elsewhere';
  const at = (ms: number) => new Date(s.now.getTime() - ms).toISOString().slice(0, 19);
  const done = (t: FakeTrack, from: string): FakeMove => ({ kind: 'file', track_id: t.track_id,
    label: `${t.artist} - ${t.title}`, src: `Library/${dirOf(t, from)}/${t.artist} - ${t.title}.aiff`,
    dst: `Library/${dirOf(t, t.folder)}/${t.artist} - ${t.title}.aiff`, state: 'done', reason: null, text: null,
    placedBefore: 'app' });
  s.tidy.batches.push(
    { id: 1, at: at(2 * 86400e3), startedBy: 'tidy', about: null, undoes: null,
      moves: [done(h, elsewhere(h)), done(i, elsewhere(i)), done(j, elsewhere(j, 1))] },
    { id: 2, at: at(3600e3), startedBy: 'save', about: null, undoes: null,
      moves: [done(k, elsewhere(k)), done(l, elsewhere(l))] });
  s.tidy.nextBatch = 3;
}

// ---------- reads ----------

function skipOf(s: FakeState, t: FakeTrack, to: string): TidyRow['skip'] {
  const reason = s.tidy.skips[t.track_id];
  if (!reason) return null;
  return { reason, text: reason === 'name_taken' ? `A file with this name is already in ${to || 'Library'}`
    : SKIPPED_TEXT[reason] };
}

/** The row of a file that goes to `toFolder` (its track's folder in the tidy-up; the new one in a save preview). */
export function tidyRow(s: FakeState, t: FakeTrack, toFolder: string, byRename: string | null = null): TidyRow {
  const from = dirOf(t, t.at ?? t.folder), to = dirOf(t, toFolder);
  const skip = skipOf(s, t, to);
  const placed = placedBy(s, t);
  return { ...trackRow(t), file_id: fileId(s, t), from, to, from_path: pathOf(t) ?? '', placed_by: placed,
    ticked: !skip && placed === 'app', yours: placed !== 'app', skip, by_rename: byRename };
}

export function tidyWaiting(s: FakeState): number {
  if (s.tidy.noRows) return 0;
  return s.tracks.filter((t) => outOfPlace(t) && !s.tidy.skips[t.track_id] && placedBy(s, t) === 'app').length;
}

export function tidyPreview(s: FakeState): TidyPreview {
  const rows = s.tidy.noRows ? [] : s.tracks.filter(outOfPlace).map((t) => tidyRow(s, t, t.folder));
  const ticked = rows.filter((r) => r.ticked).length;
  const yours = rows.filter((r) => r.yours);
  const movable = yours.filter((r) => !r.skip).length;
  const empty = !rows.length ? EMPTY : !ticked && movable
    ? plural(movable, '1 file is where you put it, not where the playlist order puts it.',
      '{n} files are where you put them, not where the playlist order puts them.') : null;
  return { rows, ticked, rekordbox: [...REKORDBOX], undo_note: UNDO_NOTE, empty,
    yours: yours.length ? { count: yours.length, movable, mark: 'You put this here', header: 'You put these here',
      control: 'Put these in playlist order too' } : null };
}

function titleOf(s: FakeState, b: FakeBatch): string {
  if (b.startedBy === 'rename') return `Renamed ${b.about?.from} to ${b.about?.to}`;
  if (b.startedBy === 'undo') {
    const target = s.tidy.batches.find((x) => x.id === b.undoes);
    return target ? `Undo of: ${titleOf(s, target)}` : 'Undo';
  }
  return b.startedBy === 'save' ? 'Saved playlists' : 'Tidy-up';
}

/** how many done moves could still be undone: the file is at `dst` today (a folder: the folder is there) */
function undoable(s: FakeState, b: FakeBatch): number {
  return b.moves.filter((m) => m.state === 'done' && canGoBack(s, m)).length;
}
function canGoBack(s: FakeState, m: FakeMove): boolean {
  if (m.kind === 'folder') return s.tracks.some((t) => hasFile(t) && pathOf(t)?.startsWith(`${m.dst}/`));
  const t = m.track_id ? s.tracks.find((x) => x.track_id === m.track_id) : undefined;
  return !!t && pathOf(t) === m.dst;
}
const summary = (moved: number, skipped: number) =>
  plural(moved, '1 file moved', '{n} files moved') + (skipped ? ` · ${skipped} not moved` : '');

export function moveBatches(s: FakeState): MoveBatches {
  const newest = [...s.tidy.batches].reverse();
  const batches: MoveBatch[] = newest.slice(0, 20).map((b) => {
    const moved = b.moves.filter((m) => m.state === 'done').length;
    const skipped = b.moves.length - moved;
    const by = newest.find((u) => u.undoes === b.id);
    return { id: b.id, at: b.at, title: titleOf(s, b), moved, skipped, undoable: undoable(s, b),
      undone_by: by ? by.id : null, summary: summary(moved, skipped) };
  });
  return { batches, total: s.tidy.batches.length };
}

export function undoPreview(s: FakeState, id: unknown): UndoPreview | null {
  const b = s.tidy.batches.find((x) => x.id === id);
  if (!b) return null;
  const rows = b.moves.filter((m) => m.state === 'done').reverse().map((m) => ({
    label: m.label,
    from: m.kind === 'folder' ? m.dst.replace(/^Library\//, '') : folderOfPath(m.dst),
    to: m.kind === 'folder' ? m.src.replace(/^Library\//, '') : folderOfPath(m.src),
    skip: canGoBack(s, m) ? null : { reason: 'moved_on', text: m.kind === 'folder'
      ? `The folder ${m.dst.replace(/^Library\//, '')} isn't there any more` : SKIP_MOVED_ON } }));
  const going = [...b.moves].reverse().filter((m) => m.state === 'done' && canGoBack(s, m));
  const moving = going.reduce((n, m) => n + (m.kind === 'file' ? 1
    : s.tracks.filter((t) => hasFile(t) && pathOf(t)?.startsWith(`${m.dst}/`)).length), 0);
  const warning = moving ? [plural(moving, '1 file goes back to where it was. rekordbox may show it as missing again; '
    + 'Relocate finds it by file name.', '{n} files go back to where they were. rekordbox may show them as missing '
    + 'again; Relocate finds them by file name.')] : [];
  const folder = going.find((m) => m.kind === 'folder');
  if (folder) {
    const old = folder.src.replace(/^Library\//, '');
    warning.push(`The folder goes back to its old name ${old}, with everything in it, and the playlist is called ${old} again.`);
  }
  return { batch_id: b.id, title: titleOf(s, b), rows, moving, warning, nothing_left: !going.length };
}

// ---------- running a batch ----------

/** One move to make: `apply` changes the fake files when it happens. */
export type Planned = {
  kind: 'file' | 'folder'; track: FakeTrack | null; label: string; src: string; dst: string;
  skip: [string, string] | null; apply: () => void; undo?: () => void;
};
/** Stop between two moves (`stop()` of the bridge sets it). */
export type MoveRun = { stopped: boolean };

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

function toSkipped(m: FakeMove): SkippedMove {
  const [from, to] = m.kind === 'folder' ? [m.src.replace(/^Library\//, ''), m.dst.replace(/^Library\//, '')]
    : [folderOfPath(m.src), folderOfPath(m.dst)];
  return { label: m.label, from, to, reason: m.reason ?? 'failed', text: m.text ?? '' };
}

export function batchResult(s: FakeState, b: FakeBatch, stopped: boolean): BatchResult {
  const moved = b.moves.filter((m) => m.state === 'done').length;
  const skipped = b.moves.filter((m) => m.state === 'skipped').map(toSkipped);
  const back = b.startedBy === 'undo' ? ' back' : '';
  let headline = plural(moved, `Moved 1 file${back}.`, `Moved {n} files${back}.`);
  if (skipped.length) headline += ` ${skipped.length} not moved:`;
  return { batch_id: b.id, title: titleOf(s, b), moved, headline, skipped, stopped };
}

/** Runs the plan move by move (a `MovesProgress` after each, Stop and the `stopAfter` hook between two), records the
 *  batch in the log and returns it. */
export async function runBatch(s: FakeState, emit: (e: HubEvent) => void, run: MoveRun, pause: number,
  startedBy: FakeBatch['startedBy'], plan: Planned[], opts: { about?: { from: string; to: string }; undoes?: number } = {},
): Promise<{ result: BatchResult; stopped: boolean }> {
  const batch: FakeBatch = { id: s.tidy.nextBatch++, at: new Date(s.now).toISOString().slice(0, 19), startedBy,
    about: opts.about ?? null, undoes: opts.undoes ?? null, moves: [] };
  s.tidy.batches.push(batch);
  let stopped = false;
  for (const [i, p] of plan.entries()) {
    if (run.stopped || (s.tidy.stopAfter !== null && i >= s.tidy.stopAfter)) { stopped = true; break; }
    await sleep(pause);
    const before = p.track ? placedBy(s, p.track) : 'app';
    const move = (state: FakeMove['state'], reason: string | null, text: string | null): FakeMove => ({ kind: p.kind,
      track_id: p.track ? p.track.track_id : null, label: p.label, src: p.src, dst: p.dst, state, reason, text,
      placedBefore: before });
    if (p.skip) batch.moves.push(move('skipped', p.skip[0], p.skip[1]));
    else if (s.tidy.failMove === i) batch.moves.push(move('skipped', 'failed', FAILED_FULL));
    else { p.apply(); batch.moves.push(move('done', null, null)); }
    emit({ type: 'MovesProgress', batch_id: batch.id, done: i + 1, total: plan.length });
  }
  if (stopped) {
    for (const p of plan.slice(batch.moves.length)) {
      batch.moves.push({ kind: p.kind, track_id: p.track ? p.track.track_id : null, label: p.label, src: p.src,
        dst: p.dst, state: 'skipped', reason: 'stopped', text: SKIP_STOPPED, placedBefore: 'app' });
    }
  }
  return { result: batchResult(s, batch, stopped), stopped };
}

// ---------- plans ----------

/** `[[file_id, from_path]]` as the page sends it, or null when it is malformed */
export function validMoves(moves: unknown): [number, string][] | null {
  if (!Array.isArray(moves)) return null;
  for (const m of moves) {
    if (!Array.isArray(m) || m.length !== 2 || !Number.isInteger(m[0]) || typeof m[1] !== 'string' || !m[1]) return null;
  }
  return moves as [number, string][];
}

/** The tidy-up of the sent files: each moves to its track's folder if it still looks as shown. `accept`: other
 *  spellings of a file's path the page may send (the path from before a rename in the same save). */
export function planTidy(s: FakeState, moves: [number, string][], accept: Map<string, string> = new Map()): Planned[] {
  const seen = new Set<number>();
  const plan: Planned[] = [];
  for (const [id, path] of moves) {
    if (seen.has(id)) continue;
    seen.add(id);
    const t = trackOfId(s, id);
    if (!t) { plan.push({ kind: 'file', track: null, label: path.split('/').pop()?.replace(/\.aiff$/, '') ?? path,
      src: path, dst: path, skip: ['not_found', SKIP_NOT_FOUND], apply: () => {} }); continue; }
    const now = pathOf(t) ?? '';
    const dst = `Library/${dirOf(t, t.folder)}/${t.artist} - ${t.title}.aiff`;
    const label = `${t.artist} - ${t.title}`;
    const skip: [string, string] | null = path !== now && accept.get(t.track_id) !== path ? ['changed', SKIP_CHANGED]
      : !outOfPlace(t) ? ['not_found', SKIP_NOT_FOUND]
        : s.tidy.skips[t.track_id] ? [s.tidy.skips[t.track_id], skipOf(s, t, dirOf(t, t.folder))!.text]
          : null;
    plan.push({ kind: 'file', track: t, label, src: now, dst, skip, apply: () => {
      delete t.at; delete s.tidy.placed[t.track_id];
    } });
  }
  return plan;
}

/** The undo of a batch: its done moves in reverse, each back where it was if it is still where the batch left it. */
export function planUndo(s: FakeState, b: FakeBatch): Planned[] {
  return [...b.moves].reverse().filter((m) => m.state === 'done').map((m): Planned => {
    const t = m.track_id ? s.tracks.find((x) => x.track_id === m.track_id) ?? null : null;
    const ok = canGoBack(s, m);
    if (m.kind === 'folder') {
      const [old, now] = [m.src.replace(/^Library\//, ''), m.dst.replace(/^Library\//, '')];
      return { kind: 'folder', track: null, label: m.label, src: m.dst, dst: m.src,
        skip: ok ? null : ['moved_on', `The folder ${now} isn't there any more`],
        apply: () => renameFolder(s, now, old) };
    }
    return { kind: 'file', track: t, label: m.label, src: m.dst, dst: m.src,
      skip: ok ? null : ['moved_on', SKIP_MOVED_ON], apply: () => {
        if (!t) return;
        const back = folderOfPath(m.src).replace(/\/not_lossless$/, '');
        if (back === t.folder) delete t.at; else t.at = back;
        if (m.placedBefore === 'app') delete s.tidy.placed[t.track_id]; else s.tidy.placed[t.track_id] = m.placedBefore;
      } };
  });
}

/** `Library/old` becomes `Library/new` as one move: its files, their playlists and the songs' folders follow. */
export function renameFolder(s: FakeState, old: string, now: string): void {
  for (const t of s.tracks) {
    if (t.at === old) t.at = now;
    if (t.folder === old) t.folder = now;
    if (t.at === t.folder) delete t.at;
    t.playlists = t.playlists.map((f) => (f === old ? now : f));
  }
  for (const p of s.playlists) if (p.folder === old) p.folder = now;
}

export function planRename(s: FakeState, old: string, now: string): Planned {
  const taken = s.tracks.some((t) => hasFile(t) && (t.at ?? t.folder) === now) || s.extraFolders.some((f) => f.folder === now);
  return { kind: 'folder', track: null, label: old, src: `Library/${old}`, dst: `Library/${now}`,
    skip: taken ? ['name_taken', FOLDER_TAKEN(now)] : null, apply: () => renameFolder(s, old, now) };
}

// ---------- the save question ----------

/** `[old, new]` pairs and the choice, or null when `files` is malformed (null is allowed: nothing to ask) */
export function validSaveFiles(files: unknown): SaveFiles | null | 'bad' {
  if (files === null || files === undefined) return null;
  const f = files as Partial<SaveFiles>;
  if (typeof f !== 'object' || (f.choice !== 'leave' && f.choice !== 'move')) return 'bad';
  const renames = f.renames ?? [];
  if (!Array.isArray(renames) || renames.some((r) => !Array.isArray(r) || r.length !== 2
    || typeof r[0] !== 'string' || typeof r[1] !== 'string' || !/^[\w .-]+$/.test(r[0]) || !/^[\w .-]+$/.test(r[1]))) return 'bad';
  const moves = validMoves(f.moves ?? []);
  return moves ? { choice: f.choice, renames, moves } : 'bad';
}

/** The target folder of every song under the order of `lines`: its first switched-on playlist (the others keep it). */
export function targetsUnder(s: FakeState, lines: { folder: string; enabled: boolean }[]): Map<string, string> {
  const out = new Map<string, string>();
  for (const t of s.tracks) {
    const first = lines.filter((l) => l.enabled).map((l) => l.folder).find((f) => t.playlists.includes(f));
    if (first && first !== t.folder) out.set(t.track_id, first);
  }
  return out;
}

/** What a save does to the songs: the folder each one gets under `lines` (first switched-on playlist it is in,
 *  a renamed playlist counted under its old name too) when that is not its folder now, and the playlist renames. */
export function retargets(s: FakeState, lines: { folder: string; link: string; enabled: boolean }[]) {
  const renames: [string, string][] = lines.flatMap((l) => {
    const was = s.playlists.find((o) => o.link === l.link);
    return was && was.folder !== l.folder && was.folder.toLowerCase() !== l.folder.toLowerCase()
      ? [[was.folder, l.folder] as [string, string]] : [];
  });
  const byRename = new Map(renames);
  const memberOf = (t: FakeTrack, l: { folder: string; link: string }) => t.playlists.includes(l.folder)
    || t.playlists.includes(s.playlists.find((o) => o.link === l.link)?.folder ?? '\0');
  const moved = new Map<string, { to: string; by: string | null }>();
  for (const t of s.tracks) {
    const target = lines.find((l) => l.enabled && memberOf(t, l))?.folder;
    if (target === undefined || target === t.folder) continue;
    moved.set(t.track_id, { to: target, by: byRename.get(t.folder) === target ? t.folder : null });
  }
  return { renames, moved };
}

export function renameOffers(s: FakeState, renames: [string, string][], lines: { folder: string }[]): RenameOffer[] {
  const files = (folder: string) => s.tracks.filter((t) => hasFile(t) && (t.at ?? t.folder) === folder).length;
  const taken = (name: string) => s.tracks.some((t) => (t.at ?? t.folder) === name && hasFile(t))
    || s.extraFolders.some((f) => f.folder === name);
  return renames.filter(([was]) => files(was) > 0 || s.extraFolders.some((f) => f.folder === was)).map(([was, now]) => {
    const inUse = lines.some((l) => l.folder === was);
    const why = taken(now) ? FOLDER_TAKEN(now) : inUse ? `${was} is still the folder of another playlist.` : null;
    const n = files(was);
    return { from: was, to: now, files: n, offered: why === null, why_not: why, option: 'Rename the folder on disk too',
      detail: `One folder move instead of ${n} file move${n === 1 ? '' : 's'}.` };
  });
}
