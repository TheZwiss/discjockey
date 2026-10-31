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

const SC_SET = /^https?:\/\/(?:(?:www|m)\.)?soundcloud\.com\/([\w-]+)\/sets\/([:\w-]+)(?:\/([^?/#]+))?\/?(?:[?#].*)?$/i;
const SC_LIKES = /^https?:\/\/(?:(?:www|m)\.)?soundcloud\.com\/([\w-]+)\/likes\/?(?:[?#].*)?$/i;
const YT_HOSTS = ['youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'];
const YT_LIST_ID = /^[A-Za-z0-9_-]+$/;

/** `soundcloud:<id>` like `sources/soundcloud.py` `recognise`: the link's path lowercased, a private set's secret
 *  token keeping its case. null when the link is no SoundCloud set or likes list. */
function soundcloudKey(l: string): string | null {
  const s = SC_SET.exec(l);
  if (s) {
    const user = s[1].toLowerCase();
    if (user === 'discover') return null;
    const id = `${user}/sets/${s[2].toLowerCase()}`;
    return `soundcloud:${s[3] ? `${id}/${s[3]}` : id}`;
  }
  const k = SC_LIKES.exec(l);
  if (k && k[1].toLowerCase() !== 'discover') return `soundcloud:${k[1].toLowerCase()}/likes`;
  return null;
}

/** `youtube_music:<list id>` like `sources/youtube_music.py` `recognise`: the `list=` id (case kept) of a
 *  playlist or watch link, or a music.youtube.com `browse/VL<id>` link; other query keys are ignored. */
function youtubeMusicKey(l: string): string | null {
  let u: URL;
  try { u = new URL(l); } catch { return null; }
  if ((u.protocol !== 'http:' && u.protocol !== 'https:') || !YT_HOSTS.includes(u.hostname.toLowerCase())) return null;
  const path = u.pathname.replace(/\/+$/, '');
  let id: string | null = null;
  if (path === '/browse' || path.startsWith('/browse/')) {
    const item = path.slice('/browse/'.length);
    if (u.hostname.toLowerCase() === 'music.youtube.com' && item.startsWith('VL') && !item.includes('/')) id = item.slice(2);
  } else if (path === '/playlist' || (path === '/watch' && u.searchParams.get('v'))) {
    id = u.searchParams.get('list');
  }
  return id && YT_LIST_ID.test(id) ? `youtube_music:${id}` : null;
}

/** The playlist a link names, for the duplicate check: a Qobuz, SoundCloud or YouTube Music playlist as
 *  `service:<id>` (the engine's `recognise` forms), a Spotify one by its bare id, else the trimmed link. */
export function playlistKey(link: string): string {
  const l = (link ?? '').trim();
  const q = /qobuz\.com\/(?:[a-z]{2}-[a-z]{2}\/)?playlists?\/(?:[^/?#]+\/)?(\d+)/i.exec(l);
  if (q) return `qobuz:${q[1]}`;
  const other = soundcloudKey(l) ?? youtubeMusicKey(l);
  if (other) return other;
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
