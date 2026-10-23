// The music-folder flow (spec public-release §4): the one place that calls pick_folder → check_music_folder →
// (confirm) → set_music_folder, so Setup, Settings and the missing screen choose a folder the same way. No UI of its
// own besides confirm(); callers show a Fail's message as the Hint under their FolderField or button.
import { api } from './bridge/client';
import type { Fail, FolderCheck } from './bridge/types';
import { confirm } from './components/confirm';
import { bumpData, hubNow } from './stores/hub';
import { CANT_USE_MESSAGE, needsConfirm } from './musicFolder';

/** A bridge refusal, as checkFolder and useFolder hand it on (callers show its message). */
export function isFail(x: unknown): x is Fail {
  return typeof x === 'object' && x !== null && (x as { ok?: unknown }).ok === false;
}

/** The Mac's folder dialog: the chosen path; null when the user cancelled it; a Fail when the dialog could not open
 *  (callers show its message, as they do for any bridge refusal). */
export async function chooseFolder(start: string | null = null): Promise<string | null | Fail> {
  const r = await api.pick_folder(start);
  return r.ok ? r.path : r;
}

/** What is in a folder and whether Discjockey can use it. */
export async function checkFolder(path: string): Promise<FolderCheck | Fail> {
  const r = await api.check_music_folder(path);
  if (!r.ok) return r;
  const { ok: _ok, ...check } = r;
  return check;
}

/** `saved`: the new folder is saved, but Discjockey could not close (quit refused, e.g. busy); it is used the next
 *  time Discjockey opens. */
export type UseResult = 'bound' | 'restart' | 'saved' | 'cancelled' | Fail;
export const SAVED_MESSAGE = "The new folder is saved. Discjockey couldn't close just now; it uses the new folder the "
  + 'next time you open it.';

export const CLOSE_TITLE = 'Discjockey closes to use the new folder';
export const CLOSE_BODY = 'Your music stays where it is. To move it, move the folder in Finder first, then choose it here.';
export const OTHER_FILES_BODY = 'Other files are in it. Discjockey adds its folders next to them.';

/** Makes `path` the music folder. `bound`: a library is in use now, so changing it closes the app (the engine
 *  answers `restart`). Asks first when the folder holds other files or the app has to close; 'cancelled' when the
 *  user said no. On 'bound' the shell and pages read everything again. */
export async function useFolder(path: string, { bound }: { bound: boolean }): Promise<UseResult> {
  const check = await checkFolder(path);
  if (isFail(check)) return check;
  if (!check.usable) {
    return { ok: false, kind: 'refused', message: check.message ?? CANT_USE_MESSAGE };
  }
  const current = hubNow().setup?.music;
  const closes = bound && !(current?.state === 'ok' && current.path === check.path);
  if (closes) {
    const ok = await confirm({ title: CLOSE_TITLE,
      body: needsConfirm(check) ? `${OTHER_FILES_BODY} ${CLOSE_BODY}` : CLOSE_BODY, confirmLabel: 'Close and use it' });
    if (!ok) return 'cancelled';
  } else if (needsConfirm(check)) {
    const ok = await confirm({ title: 'Use a folder with other files in it?', body: OTHER_FILES_BODY,
      confirmLabel: 'Use this folder' });
    if (!ok) return 'cancelled';
  }
  const r = await api.set_music_folder(check.path);
  if (!r.ok) return r;
  if (r.restart) {
    const q = await api.quit();
    return q.ok ? 'restart' : 'saved';
  }
  bumpData();
  return 'bound';
}
