// What LinkGuide says (sources round, notes problem 2, binding words): where a playlist's link is in each service's
// app and what such a link looks like. Pure, so the words and the order are pinned. The services stand in the user's
// order (YouTube Music, SoundCloud, Spotify, Qobuz), the same order AddRow's placeholder shows their logos in. The
// example shapes are the canonical links the readers write (`canonical_link`), cut where the playlist's own part
// starts.
import type { PlaylistService } from '../bridge/types';

/** The playlist services in the user's order: AddRow's placeholder logos and LinkGuide's rows. */
export const GUIDE_SERVICES: readonly PlaylistService[] = ['youtube_music', 'soundcloud', 'spotify', 'qobuz'];

export const GUIDE_HEAD = "Where to find a playlist's link";

export type GuideRow = {
  service: PlaylistService;
  /** where to click in the service's app, the menu steps joined by "›" */
  where: string;
  /** what the copied link looks like */
  example: string;
};

const ROWS: Record<PlaylistService, Omit<GuideRow, 'service'>> = {
  youtube_music: { where: 'Share › Copy', example: 'music.youtube.com/playlist?list=…' },
  soundcloud: { where: 'Share › Copy link', example: 'soundcloud.com/name/sets/…' },
  spotify: { where: '⋯ › Share › Copy link to playlist', example: 'open.spotify.com/playlist/…' },
  qobuz: { where: 'Share › Copy link', example: 'open.qobuz.com/playlist/…' },
};

/** LinkGuide's rows, one per service in the user's order. */
export function guideRows(): GuideRow[] {
  return GUIDE_SERVICES.map((service) => ({ service, ...ROWS[service] }));
}
