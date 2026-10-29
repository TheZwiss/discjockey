// The watched folders and the import of the user's own music (plan library stage 4, I11/I12): the words every
// part says, shared by Settings → Watched folders and Setup's "Your existing music". Pure: the callers pass in what
// the bridge answered (watched_folders, the hub's write job with its last ImportProgress).
import type { EventOf } from '$lib/bridge/events';
import type { ImportResult, JobSnap, RemovalPreview, UnreadableFile, WatchedFolderRow, WatchedFolders } from '$lib/bridge/types';
import { shortPath } from '$lib/musicFolder';

export type ImportProgress = EventOf<'ImportProgress'>;

/** A count as people read it: 1,240. */
export const count = (n: number): string => Math.max(0, Math.round(n)).toLocaleString('en-US');
/** "1 file" · "1,240 files" */
export const filesText = (n: number): string => `${count(n)} ${n === 1 ? 'file' : 'files'}`;

// ---------- one folder's row (W3) ----------
/** The row's state line. The Library is always watched. A row never carries the import's run numbers (the import
 *  card and Settings' row do; a row's own files-minus-waiting disagreed with them, the phases restart at 0): while an
 *  import runs it says how many of the folder's files still wait. */
export function folderLine(f: WatchedFolderRow): string {
  if (f.kind === 'library') return 'Always watched';
  switch (f.state) {
    case 'online': return 'Online';
    case 'offline': return 'Offline: connect the drive';
    case 'scanning': return 'Checking for new files';
    case 'importing':
      if (f.waiting <= 0) return 'Importing';
      return f.waiting === 1 ? '1 file waiting' : `Importing · ${count(f.waiting)} waiting`;
  }
}

/** Two watched folders may share a name (`~/Music/Crates`, `/Volumes/Drive/Crates`); then the path tells them apart. */
export const sharesName = (f: WatchedFolderRow, all: WatchedFolderRow[]): boolean =>
  all.some((o) => o.id !== f.id && o.name.toLowerCase() === f.name.toLowerCase());
/** The folder as a sentence names it: its name, with its short path (~ for home) when another folder has the name. */
export const folderLabel = (f: WatchedFolderRow, all: WatchedFolderRow[]): string =>
  sharesName(f, all) ? `${f.name} (${shortPath(f.path)})` : f.name;
/** A path in a row: one line, the end (the folder's own name) always kept, the middle given up with "…" when the
 *  column is narrow (the row lays `head` out shrinking and `tail` fixed). */
export function pathParts(path: string): { head: string; tail: string } {
  const p = shortPath(path).replace(/\/+$/, '');
  const i = p.lastIndexOf('/');
  return i < 0 ? { head: p, tail: '' } : { head: p.slice(0, i), tail: p.slice(i) };
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
/** Where a file sits: its folder relative to the watched folder it was found in, or that folder's name when it sits at
 *  its root (the title already is the file's name, the path's top would only repeat what the row above says). */
export function unreadableWhere(u: UnreadableFile, folders: WatchedFolderRow[]): string {
  const dir = u.path.replace(/\/[^/]*$/, '');
  const root = folders.find((f) => f.id === u.folder_id);
  if (!root) return shortPath(dir);
  const base = root.path.replace(/\/+$/, '');
  if (dir === base || !dir.startsWith(`${base}/`)) return root.name;
  return dir.slice(base.length + 1);
}
/** The sub line under a file's name: "{where} · {reason}". */
export const unreadableSub = (u: UnreadableFile, folders: WatchedFolderRow[]): string =>
  `${unreadableWhere(u, folders)} · ${u.reason}`;
export const UNREADABLE_HINT = 'Tried again at the next import.';

// ---------- remove (W4) ----------
/** `where`: the folder's short path, given when another watched folder has its name (the title stays W4's, the body
 *  says which one it is). */
export function removeWords(p: RemovalPreview, where: string | null = null): { title: string; body: string } {
  const which = where ? `This is the folder at ${where}. ` : '';
  const forget = `Discjockey forgets its ${filesText(p.files)}. The files stay where they are.`;
  const again = p.redownload <= 0 ? ''
    : p.redownload === 1
      ? ' 1 song from your playlists had its only copy there. It will be downloaded again at the next sync.'
      : ` ${count(p.redownload)} songs from your playlists had their only copy there. They will be downloaded again at `
        + 'the next sync.';
  return { title: `Remove ${p.name}?`, body: which + forget + again };
}

// ---------- Settings' row (W2) ----------
/** The Watched folders row's line in Settings: the running import first, named by phase as the import card names it
 *  ("Reading tags · 340 of 1,500": the counts restart at 0 in the next phase), then a drive that is offline, then
 *  what is watched. `tone` null: no mark (the import is under way). */
export function settingsLine(folders: WatchedFolders | null, job: JobSnap | null):
  { tone: 'good' | 'warn' | 'none' | null; text: string } {
  const view = importView(job, folders);
  if (view?.kind === 'running') return { tone: null, text: view.line };
  if (!folders) return { tone: null, text: '' };
  const imports = folders.folders.filter((f) => f.kind === 'import');
  const offline = imports.find((f) => f.state === 'offline');
  if (offline) return { tone: 'warn', text: `${folderLabel(offline, folders.folders)} is offline` };
  if (!imports.length) return { tone: 'none', text: 'Library only' };
  const files = imports.reduce((n, f) => n + f.files, 0);
  return { tone: 'good', text: `${count(imports.length)} ${imports.length === 1 ? 'folder' : 'folders'} · ${filesText(files)}` };
}
