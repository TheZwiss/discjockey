// Library fake scenarios (scenario names get the prefix "library:").
import type { PageFake } from '$lib/bridge/fake/bridge';
import type { FakePlaylist, FakeState, FakeTrack } from '$lib/bridge/fake/data';
import { QOBUZ_PLAYLIST_LINK, SPOTIFY_HINT, playlistRef } from '$lib/bridge/fake/data';

/** States whose next playable Hard_Bounce track after Get Naughty (THE WEEKEND; Gone Track has no file) has a file the player can't play. */
const cantPlay = new WeakSet<FakeState>();
const BROKEN = 'data:audio/wav;base64,AAAA';

/** A song of the user's own that the import found; `away`: why its file isn't there (none: it is). */
function ownAway(s: FakeState, n: number, artist: string, title: string, status: FakeTrack['status'],
  cutoff_hz: number | null, away?: FakeTrack['away']): FakeTrack {
  return { ...s.tracks[0], track_id: `local:${n}`, artist, title, folder: '', duration_s: 233, status, cutoff_hz,
    source: 'manual', codec: 'pcm', in_playlists: false, playlists: [], upgrade: null, isrc: null, cover: n,
    own: true, away };
}

/** An own file in `dir` (its folder, absolute); the files of a scenario are numbered on from the ones already there. */
function ownIn(s: FakeState, dir: string, artist: string, title: string, over: Partial<FakeTrack> = {}): FakeTrack {
  const n = s.tracks.filter((t) => t.track_id.startsWith('local:')).length + 1;
  return { ...s.tracks[0], track_id: `local:${n}`, artist, title, folder: '', duration_s: 180 + ((n * 37) % 200),
    status: 'lossless', cutoff_hz: null, source: 'manual', codec: 'pcm', in_playlists: false, playlists: [],
    upgrade: null, isrc: null, cover: n, own: true, dir, away: undefined, ...over };
}
const ARTISTS = ['Mira Nacht', 'Tom Brandt', 'Kalte Welle', 'Nova Strand', 'Eli Brandt', 'Ruth Kessel'];
const WORDS = ['Neon', 'Harbour', 'Static', 'Lantern', 'Copper', 'Velvet', 'Orbit', 'Gravel', 'Signal', 'Ember', 'Tidal',
  'Hollow', 'Marble', 'Drift', 'Pulse', 'Quarry', 'Saffron', 'Thunder', 'Willow', 'Zenith', 'Anchor', 'Basalt', 'Cinder',
  'Dusk'];
const SUFFIXES = ['Nights', 'Sessions', 'Tapes', 'Rooms', 'Hours', 'Letters', 'Maps', 'Visions', 'Echoes', 'Gardens',
  'Stories', 'Lines', 'Remains'];

/** `crates` and `crates_busy`: the sidebar at its fullest with four Favourites in the mockup's order (a playlist, two
 *  crates, and the crate inside a wrapper folder, whose label says where it is). */
function withFavourites(s: FakeState): void {
  crateFolders(s);
  const rekordbox = '/Users/you/Music/Rekordbox Library';
  const hard = s.playlists.find((p) => p.folder === 'Hard_Bounce')!;
  s.favourites = [`playlist:${playlistRef(hard.link)}`, `folder:${rekordbox}/Hardtechno`, `folder:${rekordbox}/Peak Time`,
    `folder:${rekordbox}/Old Sets/Bounce`];
}

/** The sidebar's folders at their fullest (plan library stage 5, the library-browser mockup): a watched folder with
 *  crates, one with 312 album folders (more than 25, so all hidden at first), one whose drive is away, and a Library
 *  folder no playlist uses. No Favourites yet: `crates` pins four, `first_look` none. */
function crateFolders(s: FakeState): void {
  const rekordbox = '/Users/you/Music/Rekordbox Library';
  const albums = '/Volumes/Example Drive/Albums';
  const vinyl = '/Volumes/Vinyl Drive/Vinyl Rips';
  const add = (dir: string, names: string[], over: Partial<FakeTrack> = {}) => names.forEach((title, i) =>
    s.tracks.push(ownIn(s, dir, ARTISTS[(s.tracks.length + i) % ARTISTS.length], title, over)));
  // Rekordbox Library: Bounce twice (one inside the wrapper folder Old Sets), Hardtechno with a crate of 2019, Edits
  add(rekordbox, ['Loose End', 'Untitled Idea']);
  add(`${rekordbox}/Bounce`, ['Bounce Wave', 'Low Rider Bounce', 'Jump Up', 'Heavy Bounce', 'Kick Bounce', 'Bounce Back']);
  add(`${rekordbox}/Old Sets/Bounce`, ['Old Bounce', 'Bounce Memory', 'Bounce 2014', 'Rave Bounce']);
  add(`${rekordbox}/Hardtechno`, ['Warehouse Fire', 'Dark Room', 'Industrial Dream', 'Rumble', 'Basement Rule']);
  add(`${rekordbox}/Hardtechno/2019`, ['Berlin 2019', 'Night Shift 2019', 'Closing 2019', 'Peak 2019'],
    { status: 'not_lossless', cutoff_hz: 16000 });
  add(`${rekordbox}/Edits`, ['Edit One', 'Edit Two', 'Edit Three']);
  add(`${rekordbox}/Peak Time`, ['Main Floor', 'Hands Up Hour', 'Last Drop', 'Big Room Break', 'Peak Moment', 'Final Call',
    'Strobe Season']);
  // Albums: one folder per album, 24 words x 13 words = 312 different names
  for (let i = 0; i < 312; i++) {
    const album = `${WORDS[i % WORDS.length]} ${SUFFIXES[Math.floor(i / WORDS.length)]}`;
    s.tracks.push(ownIn(s, `${albums}/${album}`, ARTISTS[i % ARTISTS.length], `${album} (Opening)`));
  }
  // Vinyl Rips: its drive is not connected
  add(`${vinyl}/Side A`, ['A1 Intro', 'A2 Groove', 'A3 Break'], { away: 'offline' });
  add(`${vinyl}/Side B`, ['B1 Loop', 'B2 Fade', 'B3 Outro'], { away: 'offline' });
  // a Library folder no playlist line uses, beside Old_Sets
  const lib = s.tracks.filter((t) => t.status === 'lossless' && t.in_playlists && !t.own);
  ['Hardstyle Anthem', 'Euphoric Rush', 'Reverse Bass', 'Gold Kick'].forEach((title, i) => {
    s.tracks.push({ ...lib[i], track_id: `old-hardstyle-${i}`, artist: ARTISTS[i], title, folder: 'Old_Hardstyle',
      at: undefined, in_playlists: false, playlists: [], hidden: false });
  });
  // the watched folders: ids go on after the Library's, and their file counts are what is there
  const [library] = s.imp.folders;
  library.files = s.tracks.filter((t) => !t.own && t.status !== 'missing').length;
  s.imp.folders = [library];
  const watch = (path: string, over: { offline?: boolean } = {}) => {
    const files = s.tracks.filter((t) => t.own && t.dir !== undefined && (t.dir === path || t.dir.startsWith(`${path}/`))).length;
    s.imp.folders.push({ id: s.imp.nextId++, path, kind: 'import', offline: false, files, waiting: 0, redownload: 0, ...over });
  };
  watch(rekordbox);
  watch(albums);
  watch(vinyl, { offline: true });
  s.crateShown[`${rekordbox}/Edits`] = false;
}

/** A watched import folder at `path` that counts the files of the scenario under it. */
function watchFolder(s: FakeState, path: string, over: { offline?: boolean } = {}): void {
  const files = s.tracks.filter((t) => t.own && t.dir !== undefined && (t.dir === path || t.dir.startsWith(`${path}/`))).length;
  s.imp.folders.push({ id: s.imp.nextId++, path, kind: 'import', offline: false, files, waiting: 0, redownload: 0, ...over });
}

/** An import of a folder of many crates under way (the live check of plan library stage 5): Incoming holds 11 crates
 *  and 140 files that wait; every step of the import (each ~140–220 ms) brings one more crate, in among the others by
 *  name, up to 24 (under D8's limit, so each shows), so the lists that show the crates grow while they are open. */
function importingCrates(s: FakeState): void {
  const incoming = '/Users/you/Music/Incoming';
  const names = WORDS.map((w, i) => `${w} Selects`);
  const crate = (name: string) => ['Opening', 'Middle', 'Closing'].forEach((part) =>
    s.tracks.push(ownIn(s, `${incoming}/${name}`, ARTISTS[s.tracks.length % ARTISTS.length], `${name} (${part})`)));
  // every other name first, so the later ones land between them
  const later = names.filter((_, i) => i % 2 === 1 || i >= 22);
  names.filter((_, i) => i % 2 === 0 && i < 22).forEach(crate);
  watchFolder(s, incoming);
  const folder = s.imp.folders[s.imp.folders.length - 1];
  folder.waiting = 140;
  s.imp.onStep = (phase) => {
    if (phase !== 'tags' && phase !== 'sound') return;
    const next = later.shift();
    if (!next) return;
    crate(next);
    folder.files += 3;
  };
}

/** Hard_Bounce as a playlist view shows it at its fullest (plan library stage 5, D6 and D9): beside its songs with a
 *  file there, a song whose file was downloaded for Powertrance first (it sits in that folder: "in Powertrance"), one the
 *  user had already in a crate of an import folder ("in Rekordbox Library › Hardtechno › 2019"), one on a drive that is
 *  away, the song not found (t3) and the ones still waiting (t4 and the songs only just read), and two files in its
 *  folder that the playlist no longer holds (the `Also in this folder` section). */
function playlistFull(s: FakeState): void {
  const rekordbox = '/Users/you/Music/Rekordbox Library';
  const vinyl = '/Volumes/Vinyl Drive/Vinyl Rips';
  const held = { in_playlists: true, playlists: ['Hard_Bounce'], folder: 'Hard_Bounce' };
  s.tracks.push(ownIn(s, `${rekordbox}/Hardtechno/2019`, 'Mira Nacht', 'Berlin 2019', held));
  s.tracks.push(ownIn(s, `${vinyl}/Side A`, 'Tom Brandt', 'A2 Groove', { ...held, away: 'offline' }));
  watchFolder(s, rekordbox);
  watchFolder(s, vinyl, { offline: true });
  const elsewhere = s.tracks.find((t) => t.folder === 'Powertrance' && t.status === 'lossless' && !t.own
    && !t.playlists.includes('Hard_Bounce'));
  if (elsewhere) elsewhere.playlists = [...elsewhere.playlists, 'Hard_Bounce'];
  const donor = s.tracks.filter((t) => t.status === 'lossless' && t.in_playlists && !t.own);
  [['Nova Strand', 'Old Favourite'], ['Eli Brandt', 'Last Summer']].forEach(([artist, title], i) => {
    s.tracks.push({ ...donor[i + 2], track_id: `left-${i + 1}`, artist, title, folder: 'Hard_Bounce', at: undefined,
      in_playlists: false, playlists: [], hidden: false, upgrade: null });
  });
}

const fake: PageFake = {
  scenarios: {
    // set up, but no files yet (first_run would open the wizard)
    empty: (s) => { s.tracks = []; s.runs = []; },
    // an import stopped after its first pass: two WAVs read but not sound-checked (a "Not checked" badge, no
    // quality colour, left out of the counts) beside one the sound check has judged
    unchecked: (s) => {
      const own = (n: number, artist: string, title: string, duration_s: number, unchecked: boolean): FakeTrack => ({
        ...s.tracks[0], track_id: `local:${n}`, artist, title, folder: '', duration_s, status: 'lossless',
        cutoff_hz: null, source: 'manual', codec: 'pcm', in_playlists: false, playlists: [], upgrade: null,
        isrc: null, cover: n, own: true, unchecked });
      s.tracks.push(own(1, 'Mira Nacht', 'Funkenregen', 241, true), own(2, 'Mira Nacht', 'Stille Post', 198, true),
        own(3, 'Tom Brandt', 'Letzter Zug', 305, false));
    },
    // an import folder whose drive was ejected: its files stay in the library, the panel says the drive is offline
    // (two fake lossless WAVs, one on the drive that is away, one on a drive that is there; a lossless one away)
    offline: (s) => {
      s.tracks.push(ownAway(s, 1, 'Mira Nacht', 'Funkenregen', 'fake_lossless', 16000, 'offline'),
        ownAway(s, 2, 'Tom Brandt', 'Letzter Zug', 'fake_lossless', 16000),
        ownAway(s, 3, 'Mira Nacht', 'Stille Post', 'lossless', null, 'offline'));
    },
    // the USB stick an import folder is on was ejected while the window is open (library stage 4 fix K): two of its
    // files read Offline in the list, beside a file of the user's own on the Mac (there), the playlist songs and the
    // two that left every playlist (dimmed, no tag). `window.__fake.drive(true)` plugs it back in (DrivesChanged).
    ejected: (s) => {
      // the list reads a row's state from the folder its path sits in (library.ts folderState), so the two offline files
      // sit under the stick's own path, not the fake's default one
      const STICK = '/Volumes/Example Stick/Music';
      s.tracks.push({ ...ownAway(s, 1, 'Mira Nacht', 'Funkenregen', 'fake_lossless', 16000, 'offline'), dir: STICK },
        { ...ownAway(s, 3, 'Mira Nacht', 'Stille Post', 'lossless', null, 'offline'), dir: STICK },
        ownAway(s, 2, 'Tom Brandt', 'Letzter Zug', 'lossless', null));
      const stick = s.imp.folders.find((f) => f.kind === 'import');
      if (stick) Object.assign(stick, { path: STICK, offline: true, files: 2, redownload: 0 });
      s.imp.folders.push({ id: s.imp.nextId++, path: '/Users/you/Music/Old Sets', kind: 'import', offline: false,
        files: 1, waiting: 0, redownload: 0 });
    },
    // an import folder that was moved, renamed or deleted (its drive is there): "Folder not found" in the panel
    folder_missing: (s) => {
      s.tracks.push(ownAway(s, 1, 'Mira Nacht', 'Funkenregen', 'fake_lossless', 16000, 'folder_missing'),
        ownAway(s, 2, 'Tom Brandt', 'Letzter Zug', 'fake_lossless', 16000));
    },
    // one file deleted inside a folder that is there, before the next scan: "This file isn't there any more."
    file_missing: (s) => {
      s.tracks.push(ownAway(s, 1, 'Mira Nacht', 'Funkenregen', 'fake_lossless', 16000, 'file_missing'),
        ownAway(s, 2, 'Tom Brandt', 'Letzter Zug', 'fake_lossless', 16000));
    },
    // the Not in a playlist view with both kinds of row: two files of the user's own (never dimmed, nothing is
    // wrong with them) beside the downloaded songs that left every playlist (dimmed)
    not_in_playlist: (s) => {
      s.tracks.push(ownAway(s, 1, 'Mira Nacht', 'Funkenregen', 'lossless', null),
        ownAway(s, 2, 'Tom Brandt', 'Letzter Zug', 'lossless', null));
    },
    // the longest words the panel's head line carries: a Qobuz file that is really lossy (the badge is the widest,
    // "FAKE · 16.0 kHz", beside "fake lossless"); the Source row below says where the file came from
    fake_qobuz: (s) => {
      const t = s.tracks.find((x) => x.track_id === 't6');
      if (t) Object.assign(t, { status: 'fake_lossless', cutoff_hz: 16000, source: 'qobuz', codec: 'flac' });
    },
    // the longest words every line of the panel carries (open t6): a song in four playlists, a long title and artist
    // (so a long file name, whose end tells it apart), a fake lossless file (the longest badge and the cutoff's whole
    // sentence)
    long_panel: (s) => {
      const t = s.tracks.find((x) => x.track_id === 't6');
      if (t) Object.assign(t, { artist: 'DJ TALLBOY & Friends', title: 'THE WEEKEND (Extended Festival Mix)',
        status: 'fake_lossless', cutoff_hz: 16000, source: 'qobuz', codec: 'flac',
        playlists: ['Hard_Bounce', 'Powertrance', 'Bouncy', '03_06_2026'] });
    },
    // the browser column's load (plan library stage 5): 35 playlist lines, two switched off, one with a very long
    // folder name, a mix of Spotify and Qobuz lines (the wire knows only those two services until stage 6), most
    // with a few files of their own, a few never read; and two Library folders no line uses (Old_Sets from the base state, Crate_Dumps)
    browser: (s) => {
      const names = ['Warehouse_Nights', 'Peak_Hour', 'Afterhours', 'Closing_Set', 'Rave_Classics', 'Big_Room_Hard',
        'Kick_Studies', 'Acid_Trax', 'Hardstyle_Gold', 'Schranz_Selects', 'Festival_Edits', 'Basement_Cuts',
        'Warm_Up', 'Tekk_Tools', 'Gabber_Basics', 'Industrial_Hard', 'Late_Trains', 'Sunday_Set', 'Open_Air_2024',
        'Clubnight_Berlin', 'Rotterdam_Run', 'Bouncy_Edits', 'Detour_Techno', 'Pitch_Black',
        'Hardtechno_Warehouse_Afterhours_Closing_Sets_2019_To_2024_Extended_Edition', 'Vinyl_Only', 'Radio_Rips',
        'New_Finds'];
      const base = s.tracks.filter((t) => t.in_playlists && t.status !== 'missing' && !t.own);
      const added: FakePlaylist[] = names.map((folder, i) => {
        const qobuz = i % 4 === 3;
        const id = `Browser${String(i).padStart(2, '0')}xxxxxxxxxxxxxxxx`;
        return { folder, enabled: i !== 11, link: qobuz ? `${QOBUZ_PLAYLIST_LINK.slice(0, -2)}${String(i).padStart(2, '0')}`
          : `https://open.spotify.com/playlist/${id}`,
          info: { name: folder.replace(/_/g, ' '), owner_name: 'DJ One', yours: true, collaborative: false, readable: true,
            image_url: null, track_count: (i * 3) % 7, hint: SPOTIFY_HINT } };
      });
      added.forEach((p, i) => {
        const n = i % 6 === 5 ? 0 : (i * 5) % 6;   // every sixth playlist has no file yet (never read)
        for (let k = 0; k < n; k++) {
          const from = base[(i * 7 + k) % base.length];
          s.tracks.push({ ...from, track_id: `browser-${i}-${k}`, folder: p.folder, playlists: [p.folder] });
        }
      });
      s.playlists.push(...added);
      for (let k = 0; k < 3; k++) {   // the second Library folder no line uses (Old_Sets is the first)
        const from = base[(3 + k) % base.length];
        s.tracks.push({ ...from, track_id: `browser-lib-${k}`, folder: 'Crate_Dumps', in_playlists: false, playlists: [] });
      }
    },
    // a playlist of long names, as DJ downloads come (mix names in brackets, several artists): every Hard_Bounce track
    // gets a long title and artist, so the table shows what it keeps of a name at 1100 × 700 (plan library stage 5
    // A6: names readable on a laptop)
    long_titles: (s) => {
      const mixes = ['(Extended Festival Mix)', '(Original Mix)', '(Hardtechno Remix)', '(Warehouse Edit)', '(Club Mix)'];
      s.tracks.filter((t) => t.folder === 'Hard_Bounce').forEach((t, i) => {
        Object.assign(t, { title: `${t.title} ${mixes[i % mixes.length]}`,
          artist: i % 2 ? `${t.artist} & Frau Funk` : t.artist });
      });
    },
    // a playlist view at its fullest (see playlistFull)
    playlist: (s) => { playlistFull(s); },
    // the same playlist switched off: its files stay, nothing new downloads
    playlist_off: (s) => {
      playlistFull(s);
      const p = s.playlists.find((x) => x.folder === 'Hard_Bounce');
      if (p) p.enabled = false;
    },
    // a playlist read and found empty, whose folder holds nothing
    empty_playlist: (s) => {
      const hard = s.playlists.find((p) => p.folder === 'Hard_Bounce')!;
      s.playlists.push({ ...hard, folder: 'Fresh_Finds', link: 'https://open.spotify.com/playlist/FreshFindsxxxxxxxxxxxx',
        info: hard.info ? { ...hard.info, name: 'Fresh Finds', track_count: 0 } : null });
      s.emptyRead.push('Fresh_Finds');
    },
    // the crates' folders, some of Hardtechno's files held by playlists (the folder views' Playlist column: a badge, "+n")
    crates_held: (s) => {
      withFavourites(s);
      const hold: Record<string, string[]> = { Rumble: ['Hard_Techno', 'Hard_Bounce', 'Powertrance'],
        'Warehouse Fire': ['Powertrance'], 'Berlin 2019': ['Hard_Techno'], 'Peak 2019': ['Hard_Techno', 'Bouncy'] };
      for (const t of s.tracks) {
        if (t.own && t.dir?.includes('/Hardtechno') && hold[t.title]) {
          t.playlists = hold[t.title];
          t.in_playlists = true;
        }
      }
    },
    // a crate of the user's own untagged files: titles come from the file names and no row has an artist, so the table
    // leaves the Artist column out (libraryModel.artistColumnFor)
    untagged: (s) => {
      crateFolders(s);
      ['Chrome Intro', 'Chrome Loop 1', 'Chrome Loop 2', 'Chrome Drums', 'Chrome Bass Take', 'Chrome Vocal Cut', 'Chrome Fx Hit',
        'Chrome Final'].forEach((title) => s.tracks.push(ownIn(s, '/Users/you/Music/Rekordbox Library/Chrome', '', title)));
    },
    // every file is in a playlist: Not in a playlist has nothing to show
    all_listed: (s) => { s.tracks = s.tracks.filter((t) => t.in_playlists); },
    // a watched import folder with no music in it yet, beside the sidebar's other folders
    empty_watched: (s) => {
      crateFolders(s);
      s.imp.folders.push({ id: s.imp.nextId++, path: '/Users/you/Music/New Crates', kind: 'import', offline: false, files: 0,
        waiting: 0, redownload: 0 });
    },
    // the sidebar's folders at their fullest (see crateFolders) and four Favourites in the mockup's order: a playlist, two
    // crates and the crate inside a wrapper folder, whose label says where it is
    crates: (s) => { withFavourites(s); },
    // the same sidebar while the library file is held by a running job: saving a Favourite or a crate switch answers
    // busy (the brief-write failure B5 shows)
    crates_busy: (s) => { withFavourites(s); s.briefBusy = true; },
    // the first look at the same sidebar: folders and crates there, nothing pinned yet
    first_look: (s) => { crateFolders(s); },
    // the same while an import of Incoming runs (started by the page or a script): its crates arrive one by one
    crates_importing: (s) => { crateFolders(s); importingCrates(s); },
    // no playlist was read yet: no read record, so no playlist knows its songs (the files are in their folders)
    never_read: (s) => { s.unread = s.playlists.map((p) => p.folder); },
    // now playing: ▶ on Get Naughty, then ⏭ reaches a file that can't be played (the bar says so and waits)
    cant_play: (s) => { cantPlay.add(s); },
  },
  overrides: {
    track: (ctx, base) => async (id) => {
      const r = await base(id);
      if (!r.ok || !cantPlay.has(ctx.s) || r.track.title !== 'THE WEEKEND' || !r.track.audio_url) return r;
      return { ...r, track: { ...r.track, audio_url: BROKEN } };
    },
  },
};
export const scenarios = fake.scenarios;
export const overrides = fake.overrides;
export default fake;
