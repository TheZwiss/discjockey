// The decisions of TrackHead (sources round I4, notes problem 5). Pure, so every case is pinned.
import type { PlaylistService, TrackLink } from '../bridge/types';
import { PLAYLIST_SERVICE_NAMES } from '../copy';
import { duration } from '../format';

/** "Artist · 3:12 · place": the parts that are known, in that order. It stays on one line and ends in "…" when the
 *  panel is narrow; the whole line is then its Tip. */
export function headLine(artist: string, durationS: number | null | undefined, place: string): string {
  return [artist, durationS == null ? '' : duration(durationS), place].filter(Boolean).join(' · ');
}

const BY_LABEL = new Map<string, PlaylistService>(
  (Object.entries(PLAYLIST_SERVICE_NAMES) as [PlaylistService, string][]).map(([s, name]) => [`Open in ${name}`, s]));

/** The service a track's page belongs to, for the logo beside "Open in {Service} ↗". The engine writes the label
 *  from the same names (`views.track_link`: "Open in {PLAYLIST_SERVICES[service]}"), so the label names it; a label
 *  this table doesn't know gives no logo, and the row still shows the link. */
export function linkService(link: TrackLink): PlaylistService | null {
  return BY_LABEL.get(link.label) ?? null;
}

/** Whether the badge's word went onto the hidden second line: the word shows whole beside the badge or not at all
 *  (then the badge's Tip says it). `badgeTop` and `wordTop` are their offsets in the line's box; a word that wrapped
 *  sits a line lower. */
export function wordHidden(badgeTop: number, wordTop: number): boolean {
  return wordTop - badgeTop > 1;
}
