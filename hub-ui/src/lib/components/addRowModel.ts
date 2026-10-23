// The checks of AddRow (paste a playlist link, check it, name its folder), shared by Playlists and Setup's first
// playlist. Pure. Playlists' rows use folderProblem for their rename too.
import type { PlaylistInfo } from '../bridge/types';

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

/** The Spotify playlist id of a link (or the trimmed link when it has none). */
export function playlistKey(link: string): string {
  const m = /playlist[/:]([A-Za-z0-9]+)/.exec(link ?? '');
  return m ? m[1] : (link ?? '').trim();
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
