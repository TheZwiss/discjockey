// The watched folders and the import of the user's own music (plan library stage 4, I11/I12): the words every
// part says, shared by Settings → Watched folders and Setup's "Your existing music". Pure: the callers pass in what
// the bridge answered (watched_folders, the hub's write job with its last ImportProgress).
import type { EventOf } from '$lib/bridge/events';
import type { ImportResult, JobSnap, RemovalPreview, UnreadableFile, WatchedFolderRow, WatchedFolders } from '$lib/bridge/types';

export type ImportProgress = EventOf<'ImportProgress'>;

/** A count as people read it: 1,240. */
export const count = (n: number): string => Math.max(0, Math.round(n)).toLocaleString('en-US');
/** "1 file" · "1,240 files" */
export const filesText = (n: number): string => `${count(n)} ${n === 1 ? 'file' : 'files'}`;

// ---------- one folder's row (W3) ----------
/** The row's state line: the Library is always watched; an import folder says whether it can be read now and how
 *  far its import got (its files minus the ones still waiting). */
export function folderLine(f: WatchedFolderRow): string {
  if (f.kind === 'library') return 'Your Library · always watched';
  switch (f.state) {
    case 'online': return 'Online';
    case 'offline': return 'Offline: connect the drive';
    case 'scanning': return 'Checking for new files';
    case 'importing': return `Importing · ${count(f.files - f.waiting)} of ${count(f.files)}`;
  }
}
/** The row's mark: ✓ readable, ! offline (it keeps its files, it only waits), a spinner while it is worked on. */
export type FolderMark = 'good' | 'warn' | 'working';
export function folderMark(f: WatchedFolderRow): FolderMark {
  if (f.state === 'offline') return 'warn';
  if (f.state === 'scanning' || f.state === 'importing') return 'working';
  return 'good';
}

// ---------- the import (W6) ----------
/** The phase line of a running import. */
export function phaseLine(p: Pick<ImportProgress, 'phase' | 'done' | 'total'>): string {
  switch (p.phase) {
    case 'scan': return 'Looking for music files';
    case 'tags': return `Reading tags · ${count(p.done)} of ${count(p.total)}`;
    case 'sound': return `Checking the sound · ${count(p.done)} of ${count(p.total)}`;
    case 'link': return 'Linking to your playlists';
  }
}
/** How far the phase got, 0..1; null while there is nothing to count (looking for files, linking). */
export function phaseShare(p: Pick<ImportProgress, 'phase' | 'done' | 'total'>): number | null {
  if (p.phase === 'scan' || p.phase === 'link' || p.total <= 0) return null;
  return Math.max(0, Math.min(1, p.done / p.total));
}
export const stoppedLine = (left: number): string =>
  `Import stopped with ${filesText(left)} to go. It carries on where it stopped.`;
export const doneLine = (files: number): string => `Imported ${filesText(files)}.`;

/** What the import card shows. `running`: the phase (the last ImportProgress, "looking for files" until the first
 *  one comes); `stopped`: the user stopped it this session and files are left; `done` / `failed`: how the last
 *  import of this session ended. null: nothing to say. `canContinue`: Continue import is offered (files wait and no
 *  import runs); the import never starts from the page on its own (D14: the hub starts it). */
export type ImportView =
  | { kind: 'running'; line: string; share: number | null; stopping: boolean }
  | { kind: 'stopped'; line: string }
  | { kind: 'done'; line: string }
  | { kind: 'failed'; line: string };
export function importView(job: JobSnap | null, folders: WatchedFolders | null): ImportView | null {
  const own = job?.kind === 'import' ? job : null;
  if (own?.running) {
    const p = (own.last?.ImportProgress as ImportProgress | undefined) ?? { phase: 'scan' as const, done: 0, total: 0 };
    return { kind: 'running', line: phaseLine(p), share: phaseShare(p), stopping: own.stopping };
  }
  if (folders?.stopped && folders.waiting > 0) return { kind: 'stopped', line: stoppedLine(folders.waiting) };
  const fin = own?.finished;
  if (fin && fin.problem !== 'stopped') {
    if (fin.ok) {
      const r = fin.result as ImportResult | null;
      return { kind: 'done', line: fin.message || doneLine(r?.files ?? 0) };
    }
    if (fin.message) return { kind: 'failed', line: fin.message };
  }
  return null;
}
export function canContinue(job: JobSnap | null, folders: WatchedFolders | null): boolean {
  return !!folders && folders.waiting > 0 && !(job?.kind === 'import' && job.running);
}

// ---------- couldn't read (W6) ----------
export const unreadableLabel = (n: number): string => `Couldn't read (${count(n)})`;
export const unreadableRow = (u: UnreadableFile): string => `${u.path}: ${u.reason}`;
export const UNREADABLE_HINT = 'Tried again at the next import.';

// ---------- remove (W4) ----------
export function removeWords(p: RemovalPreview): { title: string; body: string } {
  const forget = `Discjockey forgets its ${filesText(p.files)}. The files stay where they are.`;
  const again = p.redownload <= 0 ? ''
    : p.redownload === 1
      ? ' 1 song from your playlists had its only copy there. It will be downloaded again at the next sync.'
      : ` ${count(p.redownload)} songs from your playlists had their only copy there. They will be downloaded again at `
        + 'the next sync.';
  return { title: `Remove ${p.name}?`, body: forget + again };
}

// ---------- Settings' row (W2) ----------
/** The Watched folders row's line in Settings: the running import first (live from ImportProgress), then a drive
 *  that is offline, then what is watched. `tone` null: no mark (the import is under way). */
export function settingsLine(folders: WatchedFolders | null, job: JobSnap | null):
  { tone: 'good' | 'warn' | 'none' | null; text: string } {
  const view = importView(job, folders);
  if (view?.kind === 'running') {
    const p = job?.last?.ImportProgress as ImportProgress | undefined;
    return { tone: null, text: p && (p.phase === 'tags' || p.phase === 'sound')
      ? `Importing · ${count(p.done)} of ${count(p.total)}` : view.line };
  }
  if (!folders) return { tone: null, text: '' };
  const imports = folders.folders.filter((f) => f.kind === 'import');
  const offline = imports.find((f) => f.state === 'offline');
  if (offline) return { tone: 'warn', text: `${offline.name} is offline` };
  if (!imports.length) return { tone: 'none', text: 'Library only' };
  const files = imports.reduce((n, f) => n + f.files, 0);
  return { tone: 'good', text: `${count(imports.length)} ${imports.length === 1 ? 'folder' : 'folders'} · ${filesText(files)}` };
}
