// Fake scenarios for the dashboard and the run history (Task 66). Picked with ?scenario=dashboard:<name>.
import type { PageFake } from '$lib/bridge/fake/bridge';
import { sampleRuns, type FakeState } from '$lib/bridge/fake/data';

const upToDate = new WeakSet<FakeState>();
const broken = new WeakSet<FakeState>();
const ZERO = { new: 0, retries: 0, redownloads: 0, bought: 0, weekly_checks: 0 };

const fake: PageFake = {
  scenarios: {
    /** Spotify read, nothing to do: "Everything is up to date." */
    up_to_date: (s) => { upToDate.add(s); s.newTracks = []; },
    /** no run has finished yet (setup done) */
    no_runs: (s) => { s.runs = []; },
    /** Spotify never read (setup done): the ready card points up to the header's Read Spotify */
    unread: (s) => { s.previewRead = false; s.spotify = { ...s.spotify, read_at: null, minutes_ago: null }; },
    /** the Spotify login expired: the banner says it, the header slot keeps the last read with Read Spotify off */
    login_expired: (s) => { s.spotify = { ...s.spotify, problem: 'login_expired',
      message: 'Your Spotify login has expired.' }; },
    /** a library grown over a year: 20 playlists (one with a long name) and 30 runs, so Folders and Last runs fill their
     *  space and scroll in place */
    grown: (s) => {
      const names = ['Ohne_Quatsch', 'Voller_Quatsch', 'Peak_Time_Warmup_Selection_2026_Final_v3', 'Schranz_Nacht',
        'Rave_Classics', 'Afterhour', 'Gabber_Light', 'Melodic_Hard', 'Closing_Set', 'Opening_Set', 'Bunker_Tekk',
        'Euro_Bounce', 'Frenchcore_Mix', 'Trance_Anthems'];
      const base = s.playlists[0];
      for (const [i, folder] of names.slice(0, Math.max(0, 20 - s.playlists.length)).entries()) {
        s.playlists.push({ ...base, folder, link: `https://open.spotify.com/playlist/Grown${i}xxxxxxxxxxxxxxx`,
          info: base.info ? { ...base.info, name: folder.replaceAll('_', ' ') } : base.info });
        // every new playlist gets copies of a few of the library's tracks, so its quality bar has something to show
        const some = s.tracks.filter((t, k) => t.in_playlists && k % 7 === i % 7).slice(0, 4 + (i * 5) % 9);
        s.tracks.push(...some.map((t, k) => ({ ...t, track_id: `${t.track_id}g${i}x${k}`, folder, playlists: [folder] })));
      }
      s.runs = sampleRuns(s.now, s.tracks, 30);
    },
    /** dashboard() and runs() answer with a problem */
    broken: (s) => { broken.add(s); },
  },
  overrides: {
    dashboard: (ctx, base) => async () => {
      if (broken.has(ctx.s)) return ctx.fail('crashed', 'Something went wrong. Try again.');
      const r = await base();
      if (!r.ok || !upToDate.has(ctx.s) || !r.ready) return r;
      return { ...r, ready: { ...r.ready, counts: ZERO, actions: 0, duration_min: 0, qobuz_needed: 0, qobuz_uses: 0 },
        tiles: { ...r.tiles, still_to_load: { count: 0, days: 0, fits_today: true } }, next_checks: 0 };
    },
    runs: (ctx, base) => async () => broken.has(ctx.s) ? ctx.fail('crashed', 'Something went wrong. Try again.') : base(),
  },
};
export const scenarios = fake.scenarios;
export const overrides = fake.overrides;
