// Fake mode: songs of the user's own in a watched folder, made by a small deterministic generator (no clock, no
// random): the same folder path and count give the same songs every time, so shots and tests never drift. The songs
// are what the import read ("Artist - Title", with tags); `listedCounts` (library.ts) counts them for the sidebar
// and Settings' rows, and the folder's page lists the same ones.
import type { FakeState, FakeTrack } from './data';

const ARTISTS = ['Mira Nacht', 'Tom Brandt', 'Kalte Welle', 'Nova Strand', 'Eli Brandt', 'Ruth Kessel', 'Jonas Falk',
  'Lena Vogt', 'Max Hollander', 'Ida Sommer', 'Paul Reuter', 'Hanna Wolter', 'Felix Arndt', 'Clara Beck', 'Oskar Lenz',
  'Mara Teich', 'Nils Auer', 'Vera Lindt', 'Anton Krause', 'Sofie Marker', 'Leo Brandl', 'Tilda Kern', 'Ben Rosen',
  'Greta Pohl', 'Kilian Haas', 'Mona Tiedt', 'Rafael Dorn', 'Yara Stein', 'Emil Fuchs', 'Nele Ahrens'];
const WORDS = ['Neon', 'Harbour', 'Static', 'Lantern', 'Copper', 'Velvet', 'Orbit', 'Gravel', 'Signal', 'Ember', 'Tidal',
  'Hollow', 'Marble', 'Drift', 'Pulse', 'Quarry', 'Saffron', 'Thunder', 'Willow', 'Zenith', 'Anchor', 'Basalt', 'Cinder',
  'Dusk', 'Mirror', 'Granite', 'Falcon', 'Lagoon', 'Nectar', 'Prism', 'Rivet', 'Summit', 'Timber', 'Umber', 'Vapour',
  'Wander', 'Crimson', 'Aurora', 'Glacier', 'Horizon'];
const NOUNS = ['Nights', 'Rooms', 'Hours', 'Letters', 'Maps', 'Echoes', 'Gardens', 'Lines', 'Tapes', 'Dreams', 'Fields',
  'Streets', 'Wires', 'Skies', 'Engines', 'Waves', 'Stories', 'Signals', 'Towers', 'Rivers', 'Shadows', 'Lights',
  'Bridges', 'Colours', 'Doors', 'Voices', 'Steps', 'Trains', 'Islands', 'Circles', 'Mirrors', 'Gates', 'Ghosts',
  'Roads', 'Winters', 'Seasons', 'Orbits', 'Machines', 'Parades', 'Pictures'];

/** The n-th song's name. Artist, word and noun repeat only after 4,800 songs, so every song of a scenario (the ids
 *  run on across its folders) has a name of its own, and so has its path. */
export function ownSongName(n: number): { artist: string; title: string } {
  const artist = ARTISTS[(n * 7) % ARTISTS.length];
  const word = WORDS[n % WORDS.length];
  const noun = NOUNS[(Math.floor(n / WORDS.length) + n) % NOUNS.length];
  // a few edits and remixes among the plain titles, as a DJ's own folder holds them
  const kind = n % 23 === 5 ? ' (Extended Mix)' : n % 31 === 11 ? ' (Club Edit)' : '';
  return { artist, title: `${word} ${noun}${kind}` };
}

export type OwnSongs = {
  /** the first id number: the songs are `own:<first>`, `own:<first + 1>`, ... (their own prefix, so the numbered
   *  `local:` songs of the Library scenarios never move) */
  first: number;
  /** how many of the last songs the import has read but not sound-checked yet (`unchecked`) */
  unchecked?: number;
  /** why the files can't be played: their drive is away, or their folder isn't found */
  away?: Exclude<FakeTrack['away'], undefined>;
};

/** `count` songs of the user's own in the folder `dir`, as the import read them: WAV files, most of them lossless and
 *  about one in nine a lossy file in a lossless container that the sound check caught (fake lossless). */
export function ownSongs(dir: string, count: number, opts: OwnSongs): FakeTrack[] {
  return Array.from({ length: count }, (_, k): FakeTrack => {
    const n = opts.first + k;
    const unchecked = k >= count - (opts.unchecked ?? 0);
    const fake = !unchecked && n % 9 === 4;
    return {
      track_id: `own:${n}`, ...ownSongName(n), folder: '', duration_s: 150 + ((n * 37) % 230),
      status: fake ? 'fake_lossless' : 'lossless', cutoff_hz: fake ? 16000 : null,
      source: 'manual', codec: 'pcm', in_playlists: false, hidden: false, added: null, cover: n, isrc: null,
      playlists: [], upgrade: null, rekordbox_check: null, other: null, next_try_days: null, rejected_sources: [],
      own: true, dir, away: opts.away, unchecked: unchecked || undefined,
    };
  });
}

/** A scenario that sets up its own watched folders (and so drops the default Music folder) calls this first: the
 *  default folder's generated songs go with it, so none is left in a folder nobody watches. */
export function dropOwnSongs(s: FakeState): void {
  s.tracks = s.tracks.filter((t) => !t.track_id.startsWith('own:'));
}
