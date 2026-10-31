// The playlist services' own logos (plan library stage 5 D7: "the services' original coloured logos", the user's
// wish), copied unchanged from the approved mockup's `SVC` table (docs/hub-mockups/design-system/library-layout.html):
// Spotify, YouTube, YouTube Music and SoundCloud are Simple Icons shapes (CC0, simpleicons.org); Qobuz's is the mark
// from static.qobuz.com on its black tile, with a faint edge so it doesn't vanish on the black frame. Each is 14 px
// and keeps its own colours: the colour rule's one exception (design language §2), because a logo is an image that
// names a service, not a signal. Constant markup, never user text; `ServiceMark` renders it.

import type { PlaylistService } from '../bridge/types';

/** A service whose logo `ServiceMark` can draw. */
export type LogoKey = 'spotify' | 'youtube' | 'youtubemusic' | 'soundcloud' | 'qobuz';

/** Each service's name as the app writes it ("YouTube Music", not "youtubemusic"). */
export const LOGO_NAMES: Record<LogoKey, string> = {
  spotify: 'Spotify', youtube: 'YouTube', youtubemusic: 'YouTube Music', soundcloud: 'SoundCloud', qobuz: 'Qobuz',
};

/** The logos as SVG markup, 14 × 14, `aria-hidden` (the mark's own `aria-label` names the service). */
export const SERVICE_LOGOS: Record<LogoKey, string> = {
  spotify:
    '<svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11" fill="#000"/><path fill="#1ED760" d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/></svg>',
  youtube:
    '<svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><path fill="#fff" d="M9 7.5v9l7-4.5z"/><path fill="#FF0000" d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>',
  youtubemusic:
    '<svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11.5" fill="#fff"/><path fill="#FF0000" d="M12 0C5.376 0 0 5.376 0 12s5.376 12 12 12 12-5.376 12-12S18.624 0 12 0zm0 19.104c-3.924 0-7.104-3.18-7.104-7.104S8.076 4.896 12 4.896s7.104 3.18 7.104 7.104-3.18 7.104-7.104 7.104zm0-13.332c-3.432 0-6.228 2.796-6.228 6.228S8.568 18.228 12 18.228s6.228-2.796 6.228-6.228S15.432 5.772 12 5.772zM9.684 15.54V8.46L15.816 12l-6.132 3.54z"/></svg>',
  soundcloud:
    '<svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><rect width="24" height="24" rx="5" fill="#FF5500"/><g transform="translate(3.6 3.6) scale(.7)"><path fill="#fff" d="M23.999 14.165c-.052 1.796-1.612 3.169-3.4 3.169h-8.18a.68.68 0 0 1-.675-.683V7.862a.747.747 0 0 1 .452-.724s.75-.513 2.333-.513a5.364 5.364 0 0 1 2.763.755 5.433 5.433 0 0 1 2.57 3.54c.282-.08.574-.121.868-.12.884 0 1.73.358 2.347.992s.948 1.49.922 2.373ZM10.721 8.421c.247 2.98.427 5.697 0 8.672a.264.264 0 0 1-.53 0c-.395-2.946-.22-5.718 0-8.672a.264.264 0 0 1 .53 0ZM9.072 9.448c.285 2.659.37 4.986-.006 7.655a.277.277 0 0 1-.55 0c-.331-2.63-.256-5.02 0-7.655a.277.277 0 0 1 .556 0Zm-1.663-.257c.27 2.726.39 5.171 0 7.904a.266.266 0 0 1-.532 0c-.38-2.69-.257-5.21 0-7.904a.266.266 0 0 1 .532 0Zm-1.647.77a26.108 26.108 0 0 1-.008 7.147.272.272 0 0 1-.542 0 27.955 27.955 0 0 1 0-7.147.275.275 0 0 1 .55 0Zm-1.67 1.769c.421 1.865.228 3.5-.029 5.388a.257.257 0 0 1-.514 0c-.21-1.858-.398-3.549 0-5.389a.272.272 0 0 1 .543 0Zm-1.655-.273c.388 1.897.26 3.508-.01 5.412-.026.28-.514.283-.54 0-.244-1.878-.347-3.54-.01-5.412a.283.283 0 0 1 .56 0Zm-1.668.911c.4 1.268.257 2.292-.026 3.572a.257.257 0 0 1-.514 0c-.241-1.262-.354-2.312-.023-3.572a.283.283 0 0 1 .563 0Z"/></g></svg>',
  qobuz:
    '<svg width="14" height="14" viewBox="0 0 180 180" aria-hidden="true"><rect x="4" y="4" width="172" height="172" rx="22" fill="#000" stroke="rgba(255,255,255,.3)" stroke-width="8"/><path fill="#fff" d="M154.98,107.69s-.06,0-.09,0h-20.06c6.73-8.99,22.89-30.61,22.9-30.62.73-1.01,1.17-2.25,1.17-3.59,0-3.32-2.65-6.01-5.95-6.08h0s-24.55,0-24.55,0h-.15s.14,0,.13,0c-2.34,0-4.38,1.9-4.38,4.24s1.9,4.23,4.23,4.23c.03,0,.06,0,.1,0h19.74s-22.82,30.51-22.84,30.53c-.77,1.02-1.23,2.29-1.23,3.67,0,3.37,2.73,6.09,6.09,6.09h24.88s0,0,.01,0c2.15,0,3.89-1.9,3.89-4.23s-1.74-4.23-3.89-4.23Z"/><path fill="#fff" d="M45.53,115.85c4.68,0,9.06-1.32,12.77-3.61v-11.25c-2.91,3.88-7.55,6.39-12.77,6.39-8.81,0-15.96-7.15-15.96-15.96s7.14-15.96,15.96-15.96,15.96,7.15,15.96,15.96h0v43.76s0,.03,0,.05c0,2.34,1.9,4.24,4.23,4.24s4.23-1.9,4.23-4.24c0-.02,0-.03,0-.05v-43.76c0-13.49-10.93-24.43-24.42-24.43s-24.42,10.94-24.42,24.43,10.93,24.43,24.42,24.43Z"/><path fill="#fff" d="M99.42,66.97c-4.68,0-9.06,1.32-12.77,3.61v11.25c2.91-3.88,7.55-6.39,12.77-6.39,8.81,0,15.96,7.15,15.96,15.96s-7.14,15.96-15.96,15.96-15.96-7.15-15.96-15.96h0v-43.76s0-.03,0-.05c0-2.34-1.9-4.24-4.23-4.24s-4.23,1.9-4.23,4.24c0,.02,0,.03,0,.05v43.76c0,13.49,10.93,24.43,24.42,24.43s24.42-10.94,24.42-24.43-10.93-24.43-24.42-24.43Z"/></svg>',
};

/** The logo of a playlist service from the wire: the one place that maps its names to the logos' (YouTube Music is
 *  `youtube_music` on the wire, `youtubemusic` here). Every `ServiceMark` for a playlist passes through it. */
export function logoOf(service: PlaylistService): LogoKey {
  return service === 'youtube_music' ? 'youtubemusic' : service;
}

/** The keys in the order the gallery shows them. */
export const LOGO_KEYS = Object.keys(SERVICE_LOGOS) as LogoKey[];
