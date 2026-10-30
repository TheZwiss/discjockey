// The checks of AddRow (paste a playlist link, check it, name its folder), shared by Playlists and Setup's first
// playlist. Pure. Playlists' rows use folderProblem for their rename too.
import type { PlaylistInfo, PlaylistService, ProblemKind } from '../bridge/types';

/** What the checks need of a playlist already in the list (Playlists' draft rows are one). */
export type PlaylistRef = { key: string; folder: string; link: string };

/** Folder name check for rename and add. null = fine, else the inline hint. */
export function folderProblem(name: string, rows: PlaylistRef[], ownKey: string | null = null): string | null {
  const n = name.trim();
  if (!n) return 'A folder name is needed.';
  if (n.includes('/')) return 'A folder name can\'t contain "/".';
  if (n === '.' || n === '..') return 'Pick another folder name.';
  const other = rows.find((r) => r.key !== ownKey && r.folder.toLowerCase() === n.toLowerCase());
  if (other) return `Another playlist already uses the folder ${other.folder}.`;
  return null;
}

/** The playlist a link names, for the duplicate check: a Qobuz playlist as `qobuz:<id>` (the player's and the store's
 *  link forms, like `sources/qobuz.py`), a Spotify one by its bare id, else the trimmed link. */
export function playlistKey(link: string): string {
  const l = (link ?? '').trim();
  const q = /qobuz\.com\/(?:[a-z]{2}-[a-z]{2}\/)?playlists?\/(?:[^/?#]+\/)?(\d+)/i.exec(l);
  if (q) return `qobuz:${q[1]}`;
  const m = /playlist[/:]([A-Za-z0-9]+)/.exec(l);
  return m ? m[1] : l;
}

export function hasLink(rows: PlaylistRef[], link: string): boolean {
  const k = playlistKey(link);
  return rows.some((r) => playlistKey(r.link) === k);
}

export function ownerText(info: PlaylistInfo): string {
  if (info.yours) return 'yours';
  if (info.collaborative) return 'collaborative';
  return info.owner_name;
}

/** Whether the shell's banner already says the login problem this answer is about (the same service, shown now): then
 *  the answer is only the bridge's sentence ("Connect Qobuz first."), without a second headline and Connect button
 *  (a state is said once, spec §11). The banner is on unless the page's body took it over (`saidInBody`). */
export function bannerSaysIt(error: { kind: ProblemKind; service: PlaylistService | null },
  block: { service: PlaylistService } | null, saidInBody: { readStatus?: boolean }): boolean {
  return (error.kind === 'not_set_up' || error.kind === 'login_expired') && !!error.service && !!block
    && block.service === error.service && !saidInBody.readStatus;
}
