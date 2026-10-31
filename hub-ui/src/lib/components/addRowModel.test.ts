import { describe, expect, it } from 'vitest';
import type { PlaylistInfo } from '../bridge/types';
import { bannerSaysIt, folderProblem, hasLink, ownerText, playlistKey, type PlaylistRef } from './addRowModel';

const ROWS: PlaylistRef[] = [
  { key: 'a', folder: 'Hard_Bounce', link: 'https://open.spotify.com/playlist/3DiscjockeyExampleList' },
  { key: 'b', folder: 'Powertrance', link: 'https://open.spotify.com/playlist/5DiscjockeyExampleList' },
];
const info = (over: Partial<PlaylistInfo> = {}): PlaylistInfo => ({ name: 'Peak Time', owner_name: 'DJ One', yours: false,
  collaborative: false, readable: true, image_url: null, track_count: 12, hint: 'Make it public.', ...over });

describe('folder name', () => {
  it('accepts a new name and the row\'s own name', () => {
    expect(folderProblem('Power_Trance', ROWS, 'b')).toBeNull();
    expect(folderProblem('Powertrance', ROWS, 'b')).toBeNull();
    expect(folderProblem('Peak_Time', ROWS)).toBeNull();
  });
  it('refuses empty names, "/", dots and names another playlist uses (any case)', () => {
    expect(folderProblem('  ', ROWS, 'b')).toMatch(/needed/);
    expect(folderProblem('Hard/Bounce', ROWS, 'b')).toMatch(/"\/"/);
    expect(folderProblem('..', ROWS)).toBe('Pick another folder name.');
    expect(folderProblem('hard_bounce', ROWS, 'b')).toBe('Another playlist already uses the folder Hard_Bounce.');
    expect(folderProblem('powertrance', ROWS)).toBe('Another playlist already uses the folder Powertrance.');
  });
});

describe('links', () => {
  it('the playlist id of a link in its web and spotify: forms; else the trimmed text', () => {
    expect(playlistKey('https://open.spotify.com/playlist/3DiscjockeyExampleList?si=abc')).toBe('3DiscjockeyExampleList');
    expect(playlistKey('spotify:playlist:3DiscjockeyExampleList')).toBe('3DiscjockeyExampleList');
    expect(playlistKey('  not a link ')).toBe('not a link');
  });
  it('finds a link already in the list, also with ?si= and spotify: forms', () => {
    expect(hasLink(ROWS, 'https://open.spotify.com/playlist/3DiscjockeyExampleList?si=abc')).toBe(true);
    expect(hasLink(ROWS, 'spotify:playlist:3DiscjockeyExampleList')).toBe(true);
    expect(hasLink(ROWS, 'https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M')).toBe(false);
  });
  it("keys a Qobuz playlist by service and id, in the player's and the store's forms (sources/qobuz.py)", () => {
    expect(playlistKey('https://open.qobuz.com/playlist/900000001')).toBe('qobuz:900000001');
    expect(playlistKey('https://play.qobuz.com/playlist/900000001?x=1')).toBe('qobuz:900000001');
    expect(playlistKey('https://www.qobuz.com/gb-en/playlists/example-picks/900000001')).toBe('qobuz:900000001');
    const rows = [...ROWS, { key: 'q', folder: 'Qobuz_Picks', link: 'https://open.qobuz.com/playlist/900000001' }];
    expect(hasLink(rows, 'https://www.qobuz.com/gb-en/playlists/example-picks/900000001')).toBe(true);
    expect(hasLink(rows, 'https://open.qobuz.com/playlist/900000002')).toBe(false);
  });
  it('keys a SoundCloud set or likes list like the engine: lowercased, a private set keeping its secret token', () => {
    expect(playlistKey('https://soundcloud.com/Example-Label/sets/Example-Set?si=abc#x')).toBe('soundcloud:example-label/sets/example-set');
    expect(playlistKey('https://m.soundcloud.com/example-label/sets/example-set/')).toBe('soundcloud:example-label/sets/example-set');
    expect(playlistKey('https://soundcloud.com/Example-DJ/likes?x=1')).toBe('soundcloud:example-dj/likes');
    expect(playlistKey('https://soundcloud.com/ex/sets/my-playlist/s-AbC?si=1')).toBe('soundcloud:ex/sets/my-playlist/s-AbC');
    const rows = [{ key: 's', folder: 'Set', link: 'https://soundcloud.com/ex/sets/my-playlist/s-AbC' }];
    expect(hasLink(rows, 'https://www.soundcloud.com/EX/sets/My-Playlist/s-AbC?si=zz')).toBe(true);
    expect(hasLink(rows, 'https://soundcloud.com/ex/sets/my-playlist/s-XyZ')).toBe(false);
    expect(hasLink(rows, 'https://soundcloud.com/ex/sets/my-playlist/s-abc')).toBe(false);
  });
  it('keys a YouTube Music playlist by its list id, in every link form (sources/youtube_music.py)', () => {
    const id = 'PLexampleListId_1-x';
    expect(playlistKey(`https://music.youtube.com/playlist?list=${id}&si=abc`)).toBe(`youtube_music:${id}`);
    expect(playlistKey(`https://www.youtube.com/playlist?list=${id}`)).toBe(`youtube_music:${id}`);
    expect(playlistKey(`https://music.youtube.com/browse/VL${id}`)).toBe(`youtube_music:${id}`);
    expect(playlistKey(`https://m.youtube.com/watch?v=abc123&list=${id}`)).toBe(`youtube_music:${id}`);
    const rows = [{ key: 'y', folder: 'Mix', link: `https://music.youtube.com/playlist?list=${id}` }];
    expect(hasLink(rows, `https://www.youtube.com/watch?v=abc123&si=q&list=${id}`)).toBe(true);
    expect(hasLink(rows, `https://music.youtube.com/playlist?list=${id.toLowerCase()}`)).toBe(false);
  });
});

describe('owner', () => {
  it('yours, collaborative, else the owner\'s name', () => {
    expect(ownerText(info({ yours: true }))).toBe('yours');
    expect(ownerText(info({ collaborative: true }))).toBe('collaborative');
    expect(ownerText(info())).toBe('DJ One');
  });
});

describe('bannerSaysIt: the banner already asks for this login', () => {
  const qobuz = { kind: 'not_set_up' as const, service: 'qobuz' as const };
  it('is true for the same service while the banner shows', () => {
    expect(bannerSaysIt(qobuz, { service: 'qobuz' }, {})).toBe(true);
    expect(bannerSaysIt({ kind: 'login_expired', service: 'qobuz' }, { service: 'qobuz' }, {})).toBe(true);
  });
  it('is false for the first link a user pastes (no banner), another service, or a banner the page took over', () => {
    expect(bannerSaysIt(qobuz, null, {})).toBe(false);
    expect(bannerSaysIt(qobuz, { service: 'spotify' }, {})).toBe(false);
    expect(bannerSaysIt(qobuz, { service: 'qobuz' }, { readStatus: true })).toBe(false);
  });
  it('is false for other problems and answers without a service', () => {
    expect(bannerSaysIt({ kind: 'offline', service: 'qobuz' }, { service: 'qobuz' }, {})).toBe(false);
    expect(bannerSaysIt({ kind: 'not_set_up', service: null }, { service: 'qobuz' }, {})).toBe(false);
  });
});
