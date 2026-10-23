// The music folder, pure (spec public-release §4): how a path is shown, what the shell does about the folder's
// state, and the one line that says what a checked folder holds. Used by FolderField, the shell gate, the missing
// screen, Setup's first step and Settings.
import type { FolderCheck, SetupStatus } from './bridge/types';

/** `/Users/<name>/…` → `~/…` (the Mac's own short form); any other path is shown as it is. */
export function shortPath(path: string): string {
  const m = /^\/Users\/[^/]+(\/.*)?$/.exec(path);
  if (!m) return path;
  return m[1] && m[1] !== '/' ? `~${m[1]}` : '~';
}

/** What the shell does: `setup` = no folder chosen yet (only Setup is open), `missing` = the chosen folder isn't
 *  there (the missing screen instead of every page), null = the app as usual (also before the first answer). */
export function musicGate(setup: SetupStatus | null): 'setup' | 'missing' | null {
  const state = setup?.music?.state;
  if (state === 'not_chosen') return 'setup';
  if (state === 'missing') return 'missing';
  return null;
}

/** Said when the engine refuses a folder without giving its own reason. */
export const CANT_USE_MESSAGE = "Discjockey can't use this folder. Choose another one.";

export type CheckLine = { tone: 'good' | 'warn' | 'problem' | null; text: string };

/** The one line under a checked folder: what is there, or why it can't be used (the engine's own words). */
export function checkLine(check: FolderCheck | null): CheckLine {
  if (!check) return { tone: null, text: '' };
  if (check.problem || !check.usable) {
    return { tone: 'problem', text: check.message ?? CANT_USE_MESSAGE };
  }
  switch (check.kind) {
    case 'new': return { tone: 'good', text: 'Discjockey makes this folder.' };
    case 'empty': return { tone: 'good', text: 'An empty folder.' };
    case 'discjockey_library': return { tone: 'good', text: 'Your Discjockey library is here; it is used as it is.' };
    case 'other_files': return { tone: 'warn', text: 'Other files are in it. Discjockey adds its folders next to them.' };
    default: return { tone: null, text: '' };
  }
}

/** Only a folder that already holds other files asks before it is used. */
export function needsConfirm(check: FolderCheck | null): boolean {
  return !!check && check.usable && !check.problem && check.kind === 'other_files';
}

/** The folder Discjockey makes inside a chosen parent: `<parent>/Discjockey`. */
export function newFolderPath(parent: string): string {
  const p = parent.replace(/\/+$/, '');
  return `${p}/Discjockey`;
}

/** The folder that holds `path` (`/Users/you/Music/Sets` → `/Users/you/Music`); the root holds itself. */
export function parentOf(path: string): string {
  return path.replace(/\/+$/, '').replace(/\/[^/]+$/, '') || '/';
}
