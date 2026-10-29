// Library fake scenarios (scenario names get the prefix "library:").
import type { PageFake } from '$lib/bridge/fake/bridge';
import type { FakeState, FakeTrack } from '$lib/bridge/fake/data';

/** States whose second Hard_Bounce track (Sternenstaub) has a file the player can't play. */
const cantPlay = new WeakSet<FakeState>();
const BROKEN = 'data:audio/wav;base64,AAAA';

/** A song of the user's own that the import found; `away`: why its file isn't there (none: it is). */
function ownAway(s: FakeState, n: number, artist: string, title: string, status: FakeTrack['status'],
  cutoff_hz: number | null, away?: FakeTrack['away']): FakeTrack {
  return { ...s.tracks[0], track_id: `local:${n}`, artist, title, folder: '', duration_s: 233, status, cutoff_hz,
    source: 'manual', codec: 'pcm', in_playlists: false, playlists: [], upgrade: null, isrc: null, cover: n,
    own: true, away };
}

const fake: PageFake = {
  scenarios: {
    // set up, but no files yet (first_run would open the wizard)
    empty: (s) => { s.tracks = []; s.runs = []; },
    // a folder from playlists.txt that has no files yet
    empty_folder: (s) => { s.extraFolders.push({ folder: 'New_Folder', in_playlists_txt: true }); },
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
      s.tracks.push(ownAway(s, 1, 'Mira Nacht', 'Funkenregen', 'fake_lossless', 16000, 'offline'),
        ownAway(s, 3, 'Mira Nacht', 'Stille Post', 'lossless', null, 'offline'),
        ownAway(s, 2, 'Tom Brandt', 'Letzter Zug', 'lossless', null));
      const stick = s.imp.folders.find((f) => f.kind === 'import');
      if (stick) Object.assign(stick, { path: '/Volumes/Example Stick/Music', offline: true, files: 2, redownload: 0 });
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
    // now playing: ▶ on Get Naughty, then ⏭ reaches a file that can't be played (the bar says so and waits)
    cant_play: (s) => { cantPlay.add(s); },
  },
  overrides: {
    track: (ctx, base) => async (id) => {
      const r = await base(id);
      if (!r.ok || !cantPlay.has(ctx.s) || r.track.title !== 'Sternenstaub' || !r.track.audio_url) return r;
      return { ...r, track: { ...r.track, audio_url: BROKEN } };
    },
  },
};
export const scenarios = fake.scenarios;
export const overrides = fake.overrides;
export default fake;
