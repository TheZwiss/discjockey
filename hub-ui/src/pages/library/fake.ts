// Library fake scenarios (scenario names get the prefix "library:").
import type { PageFake } from '$lib/bridge/fake/bridge';
import type { FakeState, FakeTrack } from '$lib/bridge/fake/data';

/** States whose second Hard_Bounce track (Sternenstaub) has a file the player can't play. */
const cantPlay = new WeakSet<FakeState>();
const BROKEN = 'data:audio/wav;base64,AAAA';

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
      const own = (n: number, artist: string, title: string, status: FakeTrack['status'], cutoff_hz: number | null,
        offline: boolean): FakeTrack => ({
        ...s.tracks[0], track_id: `local:${n}`, artist, title, folder: '', duration_s: 233, status, cutoff_hz,
        source: 'manual', codec: 'pcm', in_playlists: false, playlists: [], upgrade: null, isrc: null, cover: n,
        own: true, offline });
      s.tracks.push(own(1, 'Mira Nacht', 'Funkenregen', 'fake_lossless', 16000, true),
        own(2, 'Tom Brandt', 'Letzter Zug', 'fake_lossless', 16000, false),
        own(3, 'Mira Nacht', 'Stille Post', 'lossless', null, true));
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
