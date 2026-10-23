// Fake scenarios of the Settings page (fake mode only): open them with ?scenario=settings:<name>. Setup stays complete
// in all of them (an incomplete one sends the window to Setup once per session).
import type { PageFake } from '$lib/bridge/fake/bridge';
import { account, at, check, chrome, safari, signedQobuz } from '$lib/bridge/fake/logins';
import type { FakeState } from '$lib/bridge/fake/data';

// states whose quit is refused, as while a change is still being written
const quitBusy = new WeakSet<FakeState>();
// states whose Update download tools can't reach the download server
const updateFails = new WeakSet<FakeState>();
// states whose tool versions can't be read
const toolsUnread = new WeakSet<FakeState>();
// states whose update / Go back never finishes (the busy line stays for its shot)
const toolsHeld = new WeakSet<FakeState>();
// states whose programs check (setup_check_tools) fails altogether
const checkFails = new WeakSet<FakeState>();

const fake: PageFake = {
  scenarios: {
    // the user's case: Qobuz only; YouTube's login is in Chrome's second profile (found → Use this login)
    'yt-found'(s) {
      signedQobuz(s);
      s.browsers = { youtube: [chrome(['Profile 2']), safari()], soundcloud: [chrome(), safari()] };
    },
    // no login anywhere; Sign in never sees one (the waiting state stays for its shot)
    'yt-waiting'(s) { signedQobuz(s); s.browsers = { youtube: [chrome(), safari()] }; s.signInWaits = true; },
    // everything works: Qobuz, YouTube Premium via Chrome (DJ), SoundCloud Go+ via Chrome
    all(s) {
      signedQobuz(s);
      s.accounts.youtube = account(s, 'youtube');
      s.accounts.soundcloud = account(s, 'soundcloud', { profile: null, profileName: null });
      s.browsers = { youtube: [chrome(['Profile 2']), safari()], soundcloud: [chrome(['Default']), safari()] };
    },
    // YouTube is signed in, but the account has no Premium (its last check)
    'no-premium'(s) {
      signedQobuz(s);
      s.accounts.youtube = account(s, 'youtube', { lastCheck: check(s, { ok: false, problem: 'no_premium', kbps: 160 }) });
    },
    // the saved YouTube login is gone (its last check found none)
    'signed-out'(s) {
      signedQobuz(s);
      s.accounts.youtube = account(s, 'youtube', { lastCheck: check(s, { ok: false, problem: 'not_logged_in', kbps: null }) });
      s.browsers = { youtube: [chrome(), safari()] };
    },
    // only Safari, without Full Disk Access
    safari(s) { signedQobuz(s); s.browsers = { youtube: [{ ...safari(), default: true }], soundcloud: [{ ...safari(), default: true }] }; },
    // no browser Discjockey knows
    'no-browsers'(s) { signedQobuz(s); s.browsers = { youtube: [], soundcloud: [] }; },
    // YouTube stopped itself today (three failed downloads)
    paused(s) {
      signedQobuz(s);
      s.accounts.youtube = account(s, 'youtube', { signals: [{ time: at(s, 11), kind: 'auto_stop',
        message: 'YouTube Premium paused for today after 3 failed downloads.' }] });
    },
    // Qobuz didn't accept the saved login at its last check
    'qobuz-rejected'(s) {
      s.qobuzLastCheck = { ok: false, problem: 'login_failed', kbps: null, at: at(s) };
    },
    // deno is missing
    'tools-missing'(s) { signedQobuz(s); s.setup = { ...s.setup, tools: { ...s.setup.tools, deno: false } }; },
    // Spotify is set up but not connected
    'spotify-off'(s) {
      signedQobuz(s);
      s.setup = { ...s.setup, spotify_login: false };
    },
    // the licences folder is missing from this copy: Show licences is refused
    'licences-missing'(s) { signedQobuz(s); s.licensesMissing = true; },
    // the update check had no answer (offline): About shows the version only
    'update-unknown'(s) { signedQobuz(s); s.appUpdate = { state: 'unknown', current: '1.0.0', latest: null, url: null }; },
    // setup_status is not answered, so the window has no status: the About card shows its loading state
    'status-unreachable'(s) { signedQobuz(s); s.unanswered = ['setup_status']; },
    // Change… saves the new folder, but quit is refused (still busy): the row says it is saved for the next start
    'music-quit-busy'(s) { signedQobuz(s); s.pick = '/Volumes/DJ SSD/Discjockey'; quitBusy.add(s); },
    // yt-dlp was updated and Discjockey reopened; Go back is offered
    'tools-updated'(s) {
      signedQobuz(s);
      s.downloadTools = { ...s.downloadTools,
        'yt-dlp': { version: '2026.10.28', source: 'updated', waiting: null, previous: '2026.10.21' } };
    },
    // an update finished but Discjockey wasn't opened again yet
    'tools-waiting'(s) {
      signedQobuz(s);
      s.downloadTools = { ...s.downloadTools,
        'yt-dlp': { version: '2026.10.21', source: 'built_in', waiting: '2026.10.28', previous: '2026.10.21' } };
    },
    // Update download tools can't reach the download server
    'tools-update-fails'(s) { signedQobuz(s); updateFails.add(s); },
    // the download tools' versions couldn't be read (setup_check_tools answers without them)
    'tools-unread'(s) { signedQobuz(s); toolsUnread.add(s); },
    // Update download tools is running (it never finishes here)
    'tools-updating'(s) { signedQobuz(s); toolsHeld.add(s); },
    // Go back is running (it never finishes here)
    'tools-going-back'(s) {
      signedQobuz(s);
      s.downloadTools = { ...s.downloadTools,
        'yt-dlp': { version: '2026.10.28', source: 'updated', waiting: null, previous: '2026.10.21' } };
      toolsHeld.add(s);
    },
    // the programs check fails (the cards give way to a retry)
    'tools-check-fails'(s) { signedQobuz(s); checkFails.add(s); },
    // a Discjockey run in the terminal holds the library
    console(s) { signedQobuz(s); s.console_running = true; },
  },
  overrides: {
    quit: (ctx, base) => async () => quitBusy.has(ctx.s)
      ? { ok: false, kind: 'busy', message: 'Discjockey is still busy with a change. Wait until it has finished, then quit.' }
      : base(),
    setup_check_tools: (ctx, base) => async () => {
      if (checkFails.has(ctx.s)) {
        return { ok: false as const, kind: 'failed' as const, message: "Discjockey couldn't check the programs on this Mac. Try again in a moment." };
      }
      const r = await base();
      return r.ok && toolsUnread.has(ctx.s) ? { ...r, download_tools: null,
        download_tools_problem: "Discjockey couldn't read the download tools' versions. Check again in a moment." } : r;
    },
    rollback_tools: (ctx, base) => async () => toolsHeld.has(ctx.s)
      ? ctx.startJob('rollback_tools', null, () => undefined)
      : base(),
    update_tools: (ctx, base) => async () => toolsHeld.has(ctx.s)
      ? ctx.startJob('update_tools', null, () => undefined)
      : updateFails.has(ctx.s)
      ? ctx.startJob('update_tools', null, (finish) => setTimeout(() => finish(false, null, 'failed',
        "Couldn't reach the download server. Check your internet connection and try again. Nothing was changed."),
      800 / ctx.speed))
      : base(),
  },
};
export const scenarios = fake.scenarios;
export const overrides = fake.overrides;
export default fake;
