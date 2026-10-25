// Fake scenarios of Setup, the first-run guide (fake mode only). Open them with ?scenario=setup:<name>.
import type { PageFake } from '$lib/bridge/fake/bridge';
import { nextStep, setupComplete, type FakeState } from '$lib/bridge/fake/data';
import { account, chrome, safari, signedQobuz } from '$lib/bridge/fake/logins';
import type { SetupStatus } from '$lib/bridge/types';

type Mode = 'spotify-waits' | 'spotify-fails' | 'soundcloud-no-go';
const mode = new WeakMap<FakeState, Mode>();
// states opened with a setup scenario: there setup_status().playlists follows the saved playlists (so Next works
// after Add), as the real setup_status does; other pages' scenarios keep their fixed status
const wizard = new WeakSet<FakeState>();
const FRESH = { spotify_app: false, spotify_login: false, qobuz: false, playlists: false };
const SPOTIFY_APP_SET = { spotify_login: false, qobuz: false, playlists: false };

const DJ_SETS = '/Users/you/Music/DJ Sets';
// the no_music base: nothing chosen, nothing else set up (the shell keeps the user in Setup)
function noMusic(s: FakeState) {
  setup(s, { ...FRESH, music: { state: 'not_chosen', path: null, suggested: s.setup.music.suggested } });
  s.playlists = []; s.pick = DJ_SETS;
}
function setup(s: FakeState, patch: Partial<SetupStatus>) {
  s.setup = nextStep({ ...setupComplete(), ...patch });
  wizard.add(s);
}
// the Downloads step reached with Qobuz signed in (Spotify done, no playlist yet)
function qobuzDone(s: FakeState) {
  setup(s, { playlists: false });
  signedQobuz(s);
  s.playlists = [];
}

const fake: PageFake = {
  scenarios: {
    // no music folder chosen yet: the suggested new ~/Music/Discjockey
    'music-new'(s) { noMusic(s); },
    // "A folder I already have": the dialog returns a folder with other files in it (Use this folder asks first)
    'music-existing'(s) { noMusic(s); s.folders[DJ_SETS] = { exists: true, usable: true, problem: null, kind: 'other_files', message: null }; },
    // the dialog returns a Discjockey library from before (used as it is)
    'music-library'(s) {
      noMusic(s); s.folders[DJ_SETS] = { exists: true, usable: true, problem: null, kind: 'discjockey_library', message: null };
    },
    // the dialog returns Discjockey's own support folder: refused, with the engine's words
    'music-refused'(s) {
      noMusic(s);
      s.pick = '/Users/you/Library/Application Support/Discjockey';
      s.folders[s.pick] = { exists: true, usable: false, problem: 'is_support_dir', kind: null, message: null };
    },
    // the folder is bound; the rest is still to do (#/setup/music shows the step done)
    'music-done'(s) { setup(s, FRESH); s.playlists = []; },
    // no folder yet, and a Discjockey run in the terminal
    'music-console'(s) { noMusic(s); s.console_running = true; },
    // nothing set up yet (programs are there)
    new(s) { setup(s, FRESH); s.playlists = []; },
    // ffmpeg (and so ffprobe) is missing
    'tools-missing'(s) { setup(s, { ...FRESH, tools: { ffmpeg: false, ffprobe: false, deno: true } }); s.playlists = []; },
    // Spotify done, the Downloads step next (Qobuz neither signed in nor left out)
    downloads(s) { setup(s, { qobuz: false, playlists: false }); s.playlists = []; },
    // Spotify and Qobuz done, no playlists yet
    playlists(s) { setup(s, { playlists: false }); s.playlists = []; },
    // a colleague without Qobuz: "I don't have Qobuz" was chosen
    'no-qobuz'(s) {
      setup(s, { qobuz: false, qobuz_skipped: true, playlists: false });
      s.qobuzSkipped = true; s.playlists = [];
    },
    // a DJ whose playlists are all on Qobuz: "I don't use Spotify" was chosen (no app, no login)
    'no-spotify'(s) { setup(s, { ...FRESH, qobuz: true, spotify_skipped: true }); s.playlists = []; },
    // the Spotify app is set up; the browser login never comes back
    'spotify-waits'(s) { setup(s, SPOTIFY_APP_SET); s.playlists = []; mode.set(s, 'spotify-waits'); },
    // the Spotify app is set up; the browser login fails
    'spotify-fails'(s) { setup(s, SPOTIFY_APP_SET); s.playlists = []; mode.set(s, 'spotify-fails'); },
    // the Downloads step; SoundCloud's login is found in Chrome and "Use this login" saves it, but the test track
    // comes at 128 kbps (no Go+)
    'soundcloud-no-go'(s) {
      qobuzDone(s); mode.set(s, 'soundcloud-no-go');
      s.browsers = { youtube: [chrome(), safari()], soundcloud: [chrome(['Default']), safari()] };
    },
    // Qobuz signed in, nothing else: Continue is the filled button, no card is
    'downloads-qobuz-only'(s) { qobuzDone(s); },
    // Qobuz, YouTube Premium (Chrome, DJ) and SoundCloud Go+ (Chrome) all work: the whole ladder is lit
    'downloads-all'(s) {
      qobuzDone(s);
      s.accounts.youtube = account(s, 'youtube');
      s.accounts.soundcloud = account(s, 'soundcloud', { profile: null, profileName: null });
      s.browsers = { youtube: [chrome(['Profile 2']), safari()], soundcloud: [chrome(['Default']), safari()] };
    },
    // a YouTube login is in Chrome's second profile: YouTube's card offers "Use this login"
    'downloads-yt-found'(s) {
      qobuzDone(s);
      s.browsers = { youtube: [chrome(['Profile 2']), safari()], soundcloud: [chrome(), safari()] };
    },
    // no YouTube login anywhere; Sign in never sees one (open it with a click on YouTube's main action)
    'downloads-waiting'(s) { qobuzDone(s); s.browsers = { youtube: [chrome(), safari()] }; s.signInWaits = true; },
    // the same, but the sign-in gives up as after its 10 minutes
    'downloads-timeout'(s) { qobuzDone(s); s.browsers = { youtube: [chrome(), safari()] }; s.signInTimesOut = true; },
    // the same waiting sign-in, for the shot that stops it with Cancel
    'downloads-cancelled'(s) { qobuzDone(s); s.browsers = { youtube: [chrome(), safari()] }; s.signInWaits = true; },
    // no browser Discjockey can read logins from
    'downloads-no-browsers'(s) { qobuzDone(s); s.browsers = { youtube: [], soundcloud: [] }; },
    // only Safari, without Full Disk Access
    'downloads-safari'(s) {
      qobuzDone(s);
      s.browsers = { youtube: [{ ...safari(), default: true }], soundcloud: [{ ...safari(), default: true }] };
    },
    // a Discjockey run in the terminal while Setup is open, on the Downloads step with Qobuz still to do
    console(s) {
      setup(s, { qobuz: false, playlists: false }); s.playlists = []; s.console_running = true;
    },
    // the engine doesn't answer setup_status: the page shows the problem with Retry
    unreachable(s) { setup(s, FRESH); s.playlists = []; s.unanswered = ['setup_status']; },
  },
  overrides: {
    setup_status: (ctx, base) => async () => {
      if (wizard.has(ctx.s)) ctx.s.setup = nextStep({ ...ctx.s.setup, playlists: ctx.s.playlists.length > 0 });
      return base();
    },
    // like the backend: a SoundCloud login without Go+ is saved all the same (many tracks have no Go+ stream)
    setup_account: (ctx, base) => async (service, browser, profile = null) => {
      if (mode.get(ctx.s) !== 'soundcloud-no-go' || service !== 'soundcloud') return base(service, browser, profile);
      return ctx.startJob('setup_account', null, (finish) => setTimeout(() => {
        finish(true, ctx.accountResult(service, browser, profile, { ok: false, problem: 'no_premium', kbps: 128,
          message: 'Logged in, but the test track came at 128 kbps. Either the account has no Go+, or this track has '
            + 'no Go+ stream. Discjockey tries Go+ on every track and shows what it got.' }));
      }, 600 / ctx.speed));
    },
    setup_spotify_login: (ctx, base) => async () => {
      const m = mode.get(ctx.s);
      if (m === 'spotify-waits') return ctx.startJob('setup_spotify_login', null, () => {});
      if (m === 'spotify-fails') {
        return ctx.startJob('setup_spotify_login', null, (finish) => setTimeout(() => finish(false, null, 'login_failed',
          'Port 8888 is used by another app, so the Spotify login could not come back. Close that app, then try again.'),
        300 / ctx.speed));
      }
      return base();
    },
  },
};
export const scenarios = fake.scenarios;
export const overrides = fake.overrides;
export default fake;
