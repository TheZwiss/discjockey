// Library fake scenarios (scenario names get the prefix "library:").
import type { PageFake } from '$lib/bridge/fake/bridge';

const fake: PageFake = {
  scenarios: {
    // set up, but no files yet (first_run would open the wizard)
    empty: (s) => { s.tracks = []; s.runs = []; },
    // a folder from playlists.txt that has no files yet
    empty_folder: (s) => { s.extraFolders.push({ folder: 'New_Folder', in_playlists_txt: true }); },
  },
};
export const scenarios = fake.scenarios;
export const overrides = fake.overrides;
export default fake;
