// YouTube Music's Liked music in the fake backend (sources round, E2): Settings' choice, the listed line, and the
// scenarios the Settings and Playlists pages show it with. The real engine: discjockey/sources/youtube_music.py,
// hub/api.py (set_read_liked_music, add_liked_music, add_playlist, setup_status). Scenarios (open with
// ?scenario=<name>):
//   settings:liked-off          a YouTube login is set up; the choice is off; no Liked music line
//   settings:liked-on           the same with the choice on, no Liked music line yet ("Add Liked music to Playlists")
//   settings:liked-no-login     no YouTube login: the choice can't be turned on
//   settings:liked-free-off     a YouTube login without Premium (kept for Liked music only); the choice is off
//   settings:liked-free-on      the same with the choice on
//   playlists:liked-listed-off  a Liked music line is listed while the choice is off
import { isoLocal, type FakeState } from './data';
import { account } from './logins';
import type { SettingKey, SetupStatus } from '../types';

export const LIKED_LINK = 'https://music.youtube.com/playlist?list=LM';
export const LIKED_FOLDER = 'Liked_music';
/** The engine's words (youtube_music.SETTING_OFF, hub/api.py) */
export const LIKED_OFF = 'Reading your Liked music is off. Turn it on in Settings.';
export const LIKED_NEEDS_LOGIN = 'Sign in to YouTube first: Discjockey reads your Liked music through that login.';
export const LIKED_LISTED = 'Liked music is in your playlists already.';
export const LIKED_SETTING: SettingKey = 'read_liked_music';

export const isLikedLink = (link: string) => /^https?:\/\/(?:music\.|www\.|m\.)?youtube\.com\/(?:playlist|watch)\?(?:[^#]*&)?list=LM(?:&|$)/i.test(link.trim());

/** The choice as it counts: on, and a YouTube login to read it with (the engine's `Settings.reads_liked_music`) */
export const likedOn = (s: FakeState): boolean => !!s.likedMusic && !!s.accounts.youtube;

export function likedStatus(s: FakeState): SetupStatus['youtube_music'] {
  return { liked_music: likedOn(s), can_turn_on: !!s.accounts.youtube, listed: s.playlists.some((p) => isLikedLink(p.link)) };
}

/** What a listed Liked music line needs while the choice is off (a PlaylistRow's `needs_setting`) */
export const needsSetting = (s: FakeState, link: string): SettingKey | null =>
  isLikedLink(link) && !likedOn(s) ? LIKED_SETTING : null;

/** A YouTube login whose last check found no Premium: kept to read Liked music, never used for a download */
const freeAccount = (s: FakeState) => account(s, 'youtube',
  { lastCheck: { ok: false, problem: 'no_premium', kbps: 129, at: isoLocal(new Date()) } });

export const likedScenarios: Record<string, (s: FakeState) => void> = {
  'settings:liked-off': (s) => { s.accounts.youtube = account(s, 'youtube'); s.likedMusic = false; },
  'settings:liked-on': (s) => { s.accounts.youtube = account(s, 'youtube'); s.likedMusic = true; },
  'settings:liked-free-off': (s) => { s.accounts.youtube = freeAccount(s); s.likedMusic = false; },
  'settings:liked-free-on': (s) => { s.accounts.youtube = freeAccount(s); s.likedMusic = true; },
  'settings:liked-no-login': (s) => { s.accounts.youtube = null; s.likedMusic = false; },
  'playlists:liked-listed-off': (s) => {
    s.accounts.youtube = account(s, 'youtube');
    s.likedMusic = false;
    s.playlists = [...s.playlists, { folder: LIKED_FOLDER, link: LIKED_LINK, enabled: true,
      info: { name: 'Liked music', owner_name: 'You', yours: true, collaborative: false, readable: true, image_url: null,
        track_count: null, hint: 'Set it to public or unlisted in YouTube Music.' } }];
  },
};
