// Library fake scenarios (scenario names get the prefix "library:").
import type { PageFake } from '$lib/bridge/fake/bridge';
import type { FakeState } from '$lib/bridge/fake/data';

/** States whose second Hard_Bounce track (Sternenstaub) has a file the player can't play. */
const cantPlay = new WeakSet<FakeState>();
const BROKEN = 'data:audio/wav;base64,AAAA';

const fake: PageFake = {
  scenarios: {
    // set up, but no files yet (first_run would open the wizard)
    empty: (s) => { s.tracks = []; s.runs = []; },
    // a folder from playlists.txt that has no files yet
    empty_folder: (s) => { s.extraFolders.push({ folder: 'New_Folder', in_playlists_txt: true }); },
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
