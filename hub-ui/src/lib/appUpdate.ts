// The update notice's words (spec public-release §8). Pure: the hub store passes in what app_update() / AppUpdate said.
import type { AppUpdate } from './bridge/types';

/** "1.1.0" → "1.1", "2.0.0" → "2.0", "1.1.2" stays (the spec's "Discjockey 1.1 is available"). */
export function shortVersion(v: string): string {
  const m = /^(\d+)\.(\d+)\.(\d+)$/.exec(v);
  return m && m[3] === '0' ? `${m[1]}.${m[2]}` : v;
}

/** The sidebar's line and Settings' link: only when a newer version is out and its page is known. */
export function updateLink(u: AppUpdate | null): { text: string; url: string } | null {
  if (!u || u.state !== 'available' || !u.latest || !u.url) return null;
  return { text: `Discjockey ${shortVersion(u.latest)} is available`, url: u.url };
}

/** The About row's state after the version: "up to date", "1.1 is available", or null without an answer. */
export function aboutLine(u: AppUpdate | null): string | null {
  if (u?.state === 'up_to_date') return 'up to date';
  const link = updateLink(u);
  return link && u?.latest ? `${shortVersion(u.latest)} is available` : null;
}
