// The watched folders' controller (plan library stage 4, I11), shared by Settings → Watched folders and Setup's
// "Your existing music": the only part of them that talks to the bridge. The blocks (WatchedFolderList,
// ImportCard, UnreadableList) render from what it holds. The page creates one flow and calls `mount()` once, which
// reads the folders and reads them again after every finished job and while an import runs (each phase change, and
// at most once a second while it counts), so the rows' counts follow the import.
// Add folder…: the Mac's folder dialog → check_import_folder → its refusal as the line under the button, or
// add_watched_folder, which imports in the same job; the folders it takes over are said with the engine's merge
// lines. The import itself is never started here on its own (D14: the hub starts it); Continue import and Stop are
// the user's.
import { api, runJob } from '$lib/bridge/client';
import { onEvent } from '$lib/bridge/events';
import type { ProblemKind, WatchedFolderRow, WatchedFolders } from '$lib/bridge/types';
import { shortPath } from '$lib/musicFolder';
import { chooseFolder, isFail } from '$lib/musicFolderFlow';
import { dataVersion } from '$lib/stores/hub';
import { confirm } from './confirm';
import { removeWords, sharesName } from './watchedFoldersModel';

/** The line under Add folder…: a refusal (the engine's words) or what the add took over (its merge lines). */
export type AddNote = { tone: 'problem' | 'info'; lines: string[] };

/** How often the rows are read again while an import counts (a phase change reads them at once). */
const REREAD_MS = 1000;

export class WatchedFoldersFlow {
  data = $state<WatchedFolders | null>(null);
  error = $state<{ kind: ProblemKind; message: string } | null>(null);
  note = $state<AddNote | null>(null);
  /** Add folder… is between the dialog and the add's answer */
  adding = $state(false);
  /** Continue import was pressed and the hub hasn't answered yet */
  starting = $state(false);
  /** the folder whose removal is asked or under way */
  removing = $state<number | null>(null);

  private turn = 0;
  private lastPath: string | null = null;

  /** Reads the folders; only the newest answer counts. */
  load = async (): Promise<void> => {
    const t = ++this.turn;
    const r = await api.watched_folders();
    if (t !== this.turn) return;
    if (r.ok) {
      const { ok: _ok, ...rest } = r;
      this.data = rest;
      this.error = null;
    } else this.error = { kind: r.kind, message: r.message };
  };

  /** Starts reading and following; returns the cleanup. */
  mount(): () => void {
    let phase: string | null = null;
    let lastRead = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const reread = () => { lastRead = Date.now(); timer = null; void this.load(); };
    const offEvents = onEvent((e) => {
      if (e.type === 'JobStarted' && e.kind === 'import') { phase = null; reread(); return; }
      if (e.type !== 'ImportProgress') return;
      if (e.phase !== phase) { phase = e.phase; if (timer) clearTimeout(timer); reread(); return; }
      if (!timer) timer = setTimeout(reread, Math.max(0, REREAD_MS - (Date.now() - lastRead)));
    });
    // dataVersion calls at once (the first read) and after every finished job
    const offData = dataVersion.subscribe(() => void this.load());
    return () => { offEvents(); offData(); if (timer) clearTimeout(timer); this.turn++; };
  }

  /** Add folder…: pick, check, add (the add starts the import). */
  add = async (): Promise<void> => {
    this.note = null;
    this.adding = true;
    try {
      const picked = await chooseFolder(this.lastPath);
      if (picked === null) return;
      if (isFail(picked)) { this.note = { tone: 'problem', lines: [picked.message] }; return; }
      this.lastPath = picked;
      const c = await api.check_import_folder(picked);
      if (!c.ok) { this.note = { tone: 'problem', lines: [c.message] }; return; }
      if (!c.usable) { this.note = { tone: 'problem', lines: [c.message ?? ''] }; return; }
      const r = await api.add_watched_folder(c.path);
      if (!r.ok) { this.note = { tone: 'problem', lines: [r.message] }; return; }
      if (c.merge_hints.length) this.note = { tone: 'info', lines: [...c.merge_hints] };
      await this.load();
    } finally {
      this.adding = false;
    }
  };

  /** Remove: what goes (removal_preview), asked in a dialog; the files themselves stay. */
  remove = async (f: WatchedFolderRow): Promise<void> => {
    if (f.kind !== 'import') return;
    this.note = null;
    this.removing = f.id;
    try {
      const p = await api.removal_preview(f.id);
      if (!p.ok) { this.note = { tone: 'problem', lines: [p.message] }; return; }
      const w = removeWords(p, sharesName(f, this.data?.folders ?? []) ? shortPath(f.path) : null);
      const yes = await confirm({ title: w.title, body: w.body, confirmLabel: 'Remove folder', cancelLabel: 'Cancel',
        tone: 'danger' });
      if (!yes) return;
      const r = await runJob(api.remove_watched_folder(f.id), { quiet: true, success: false });
      if (!r.ok && r.kind !== 'stopped') this.note = { tone: 'problem', lines: [r.message] };
      await this.load();
    } finally {
      this.removing = null;
    }
  };

  /** Continue import: the stopped import carries on where it stopped. */
  continueImport = async (): Promise<void> => {
    this.note = null;
    this.starting = true;
    const r = await api.start_import();
    this.starting = false;
    if (!r.ok) this.note = { tone: 'problem', lines: [r.message] };
  };

  stop = async (): Promise<void> => {
    const r = await api.stop();
    if (!r.ok) this.note = { tone: 'problem', lines: [r.message] };
  };
}
