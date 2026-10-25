import { describe, expect, it } from 'vitest';
import type { PlaylistInfo } from '../bridge/types';
import { folderProblem, hasLink, ownerText, playlistKey, type PlaylistRef } from './addRowModel';

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
});

describe('owner', () => {
  it('yours, collaborative, else the owner\'s name', () => {
    expect(ownerText(info({ yours: true }))).toBe('yours');
    expect(ownerText(info({ collaborative: true }))).toBe('collaborative');
    expect(ownerText(info())).toBe('DJ One');
  });
});
