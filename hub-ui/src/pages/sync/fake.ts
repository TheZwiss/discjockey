// Fake scenarios of the Sync page (dev only, picked up by the fake backend's glob).
//   sync:long-plan   the user's real case: 195 new tracks in 2 new playlists, 10 Qobuz downloads left today,
//                    3 "never download" tracks, ambiguous + dropped + notes
//   sync:reading     Spotify is read for the first time (no plan yet), at playlist 3 of 7
//   sync:rereading   Spotify is read again, the old plan dims below the reading card
//   sync:converting  a sync already running, frozen at the StepChanged convert of "non stop" (SYNC_LINES.converting)
//   sync:up-to-date  Spotify read, nothing to do (2 "never download" tracks)
//   sync:crashed           a sync already running crashes; its crash note is filed as the run's report
//   sync:stop-refused  a sync already running (as sync:converting) whose Stop safely fails
//   sync:no-qobuz    the long plan for a colleague without Qobuz: YouTube Premium 30/day (26 used), SoundCloud Go+ 60/day
//   sync:up-to-date-console  up to date while a sync runs in the terminal: no Start, so the shell's banner says it
//   sync:up-to-date-wait  up to date, and the last run's details take a minute to come (the panel's waiting state)
//   sync:qobuz-backup the long plan with Qobuz (10 left today) plus two limited backups behind it: YouTube Premium
//                    30/day, SoundCloud Go+ 60/day (12 used); their service rows read "backup" with no bar
//   sync:limit-reached  the long plan with today's 60 Qobuz downloads used up
//   sync:downloads-wait the limit-reached plan with downloads only (no other kinds): nothing runs today,
//                       Start is off with its reason
//   sync:many        the long plan plus 12 more playlists (one with a very long name, Peak_Time_Warmup_Selection_2026_Final_v3)
//                    and actions of all 5 kinds (new, not found last time, file gone, bought, weekly)
//   sync:long-names  the long plan with three titles over 120 characters and one track by six artists
import type { PageFake } from '$lib/bridge/fake/bridge';
import type { FakeState } from '$lib/bridge/fake/data';
import { FAKE_MUSIC, SPOTIFY_HINT, previewAction, runId, samplePlaylists } from '$lib/bridge/fake/data';
import { STREAMS, SYNC_LINES, SYNC_START_LINE } from '$lib/bridge/fake/replay';
import type { SyncPreview } from '$lib/bridge/types';

const ARTISTS = ['Pegassi', 'Vatoz Locoz', 'torbentorben', 'Armin Hermann', 'DJ TALLBOY', 'Nina Kraviz', 'Kölsch',
  'Ben Klock', 'Changing Faces', 'Luude', 'Sub Focus', 'Hannah Laing'];
const WORDS = ['Night Drive', 'Pressure', 'Low Tide', 'Overdrive', 'Mirror', 'Signal', 'Afterglow', 'Static',
  'Heatwave', 'Undertow', 'Drop It Low', 'The Logical Song', 'Never Adds Up', 'Elevate'];
const NEW_FOLDERS = ['Voller_Quatsch', 'Ohne_Quatsch'];
let crashStarted = false;
let readStarted = false;

const longPlan = (s: FakeState) => {
  s.scenario = 'sync:long-plan';
  // two new playlists at the top of playlists.txt, 120 + 75 new tracks
  s.playlists = [
    ...NEW_FOLDERS.map((folder, i) => ({ folder, link: `https://open.spotify.com/playlist/Quatsch${i}xxxxxxxxxxxxxx`,
      enabled: true, info: { name: folder.replace('_', ' '), owner_name: 'DJ One', yours: true, collaborative: false,
        readable: true, image_url: null, track_count: i ? 75 : 120, hint: SPOTIFY_HINT } })),
    ...samplePlaylists(),
  ];
  s.newTracks = Array.from({ length: 195 }, (_, i) => ({ track_id: `q${i + 1}`, artist: ARTISTS[i % ARTISTS.length],
    title: `${WORDS[(i * 5) % WORDS.length]}${i >= WORDS.length ? ` ${Math.floor(i / WORDS.length) + 1}` : ''}`,
    folder: i < 120 ? NEW_FOLDERS[0] : NEW_FOLDERS[1], duration_s: 180 + i }));
  s.qobuz = { ...s.qobuz, limit: 60, carry_over: 0, extra_today: 0, used_today: 50 };   // 10 left today
  s.never = ['q7', 'q31', 'q140'];
};
// twelve more playlists for `sync:many`: long and short names, so the panel's group and the list sections scroll
const MORE_FOLDERS = ['Peak_Time_Warmup_Selection_2026_Final_v3', 'Afterhour', 'Schranz_Classics', 'Melodic_Techno',
  'Rave_Tools', 'Warmup', 'Closing_Tracks', 'Vocals', 'Hardgroove', 'Acid', 'Trance_Classics', 'Breaks'];
const many = (s: FakeState) => {
  longPlan(s);
  s.scenario = 'sync:many';
  s.playlists = [...s.playlists, ...MORE_FOLDERS.map((folder, i) => ({ folder,
    link: `https://open.spotify.com/playlist/More${i}xxxxxxxxxxxxxxxx`, enabled: true, info: { name: folder.replaceAll('_', ' '),
      owner_name: 'DJ One', yours: true, collaborative: false, readable: true, image_url: null, track_count: 3 + (i % 4), hint: SPOTIFY_HINT } }))];
  s.newTracks = [...s.newTracks, ...MORE_FOLDERS.flatMap((folder, i) => Array.from({ length: 1 + (i % 3) }, (_, j) => ({
    track_id: `m${i}_${j}`, artist: ARTISTS[(i + j * 7) % ARTISTS.length], title: WORDS[(i * 3 + j) % WORDS.length],
    folder, duration_s: 200 + i }))) ];
};
/** One action of every kind but "new" for `sync:many`, spread over the extra playlists. */
function otherKinds(): SyncPreview['groups'] {
  const t = (id: string, i: number) => ({ track_id: id, artist: ARTISTS[(i * 5) % ARTISTS.length],
    title: `${WORDS[(i * 7 + 2) % WORDS.length]} (Extended Mix)`, folder: MORE_FOLDERS[i % MORE_FOLDERS.length] });
  const two = (kind: string, reason: string | null, at: number) =>
    [0, 1].map((j) => previewAction(kind, reason, t(`k${at}_${j}`, at + j), false, null, at + j));
  return [
    { key: 'acquire:retry', label: 'Not found last time', actions: two('acquire', 'retry', 0) },
    { key: 'acquire:redownload', label: 'File gone', actions: two('acquire', 'redownload', 2) },
    { key: 'adopt_bought', label: 'Bought files', actions: two('adopt_bought', null, 8) },
    { key: 'upgrade', label: 'Weekly checks', actions: two('upgrade', null, 10) },
  ];
}
// `sync:long-names`: titles that end in "…" at every width, and a track credited to six artists
const LONG_TITLES = [
  'Schall und Rauch (Peak Time Warmup Extended Club Mix by the Very Long Remixer Name Collective featuring Everyone We Know) [2026 Remaster]',
  'Nebelmaschine im Morgengrauen über dem Hafen von Hamburg (Original Extended Twelve Inch Version with Extra Percussion and Live Strings)',
  'A Title So Long That No Row Could Ever Hold It Even at the Widest Window the Hub Will Ever Be Opened In (Dub Version) [Bonus Track]',
];
const longNames = (s: FakeState) => {
  longPlan(s);
  s.scenario = 'sync:long-names';
  s.newTracks = s.newTracks.map((t, i) => (i < 3 ? { ...t, title: LONG_TITLES[i] }
    : i === 3 ? { ...t, artist: 'Pegassi, Vatoz Locoz, torbentorben, Armin Hermann, DJ TALLBOY, Hannah Laing' } : t));
};
const reading = (first: boolean) => (s: FakeState) => {
  s.scenario = first ? 'sync:reading' : 'sync:rereading';
  s.spotify = { ...s.spotify, reading: true };
  if (first) s.previewRead = false;
};

function extendLongPlan(p: SyncPreview): SyncPreview {
  return { ...p,
    ambiguous: [
      { track_id: 'a1', artist: 'Pegassi', title: 'Overdrive', folder: 'Hard_Bounce',
        files: ['Library/Hard_Bounce/Pegassi - Overdrive.aiff', 'Library/Bouncy/Pegassi - Overdrive.aiff'] },
    ],
    dropped: [
      { track_id: 'd1', artist: 'Kölsch', title: 'Grey', folder: 'Bouncy' },
      { track_id: 'd2', artist: 'Nina Kraviz', title: 'Ghetto Kraviz', folder: 'Hard_Bounce' },
    ],
    notes: ['3 tracks are in two playlists; they go to the first one in playlists.txt.'] };
}

/** A fallback account with a daily limit (YouTube Premium, SoundCloud Go+). */
const account = (limit: number, used: number, browser: 'chrome' | 'firefox') => ({ limit, extra_today: 0,
  carry_over: 0, used_today: used, days: Array(14).fill(0), signals: [], last_download: null, browser });

export const scenarios: PageFake['scenarios'] = {
  /** Spotify's login is missing but no read has failed yet (problem null): Sync's card says it from the shared store */
  'no-login': (s) => { s.setup = { ...s.setup, spotify_login: false }; },
  'long-plan': longPlan,
  'no-qobuz'(s) {
    longPlan(s);
    s.qobuzSkipped = true;
    s.accounts.youtube = account(30, 26, 'chrome');
    s.accounts.soundcloud = account(60, 0, 'firefox');
  },
  'qobuz-backup'(s) {
    longPlan(s);
    s.accounts.youtube = account(30, 0, 'chrome');
    s.accounts.soundcloud = account(60, 12, 'firefox');
  },
  'limit-reached'(s) {
    longPlan(s);
    s.qobuz = { ...s.qobuz, used_today: 60 };
  },
  'downloads-wait'(s) {
    longPlan(s);
    s.qobuz = { ...s.qobuz, used_today: 60 };
    s.scenario = 'sync:downloads-wait';
  },
  many,
  'long-names': longNames,
  reading: reading(true),
  rereading: reading(false),
  converting: (s) => { s.scenario = 'sync:converting'; },
  'up-to-date': (s) => { s.scenario = 'sync:up-to-date'; },
  'up-to-date-console': (s) => { s.scenario = 'sync:up-to-date'; s.console_running = true; },
  'up-to-date-wait': (s) => { s.scenario = 'sync:up-to-date-wait'; },
  'crashed': (s) => { s.scenario = 'sync:crashed'; },
  'stop-refused': (s) => { s.scenario = 'sync:stop-refused'; },
};

export const overrides: PageFake['overrides'] = {
  // the real run(run_id) is a pywebview round trip plus a report parse; this one takes a minute
  // Stop safely fails (the foot's red alert line); every other scenario stops as the base does
  stop: (ctx, base) => async () => ctx.s.scenario === 'sync:stop-refused'
    ? { ok: false as const, kind: 'refused' as const, message: "The sync didn't answer. It is still running; try again in a moment." }
    : base(),
  run: (ctx, base) => async (run_id) => {
    if (ctx.s.scenario === 'sync:up-to-date-wait') await new Promise((r) => setTimeout(r, 60_000));
    return base(run_id);
  },
  sync_preview: (ctx, base) => async () => {
    const r = await base();
    if (!r.ok) return r;
    if (ctx.s.scenario === 'sync:long-plan' || ctx.s.scenario === 'sync:long-names') return { ...r, ...extendLongPlan(r) };
    if (ctx.s.scenario === 'sync:downloads-wait') {
      const p = extendLongPlan(r);
      return { ...r, ...p, groups: p.groups.filter((g) => g.key.startsWith('acquire')),
        counts: p.counts && { ...p.counts, bought: 0, weekly_checks: 0 } };
    }
    if (ctx.s.scenario === 'sync:many') return { ...r, ...extendLongPlan(r), groups: [...r.groups, ...otherKinds()] };
    if (ctx.s.scenario === 'sync:up-to-date' || ctx.s.scenario === 'sync:up-to-date-wait') {
      const never = [ctx.s.newTracks[2], ctx.s.newTracks[5]].filter(Boolean)
        .map((t, i) => previewAction('acquire', 'new', t, false, null, i + 1));
      return { ...r, groups: [], counts: { new: 0, retries: 0, redownloads: 0, bought: 0, weekly_checks: 0 }, never, empty: 'up_to_date' as const };
    }
    return r;
  },
  job_status: (ctx, base) => {
    // a sync that already runs when the window opens, frozen in the conversion of "non stop"
    if (ctx.s.scenario === 'sync:converting' || ctx.s.scenario === 'sync:stop-refused') {
      ctx.startJob('sync', null, () => {
        for (const e of STREAMS.sync.slice(SYNC_START_LINE, SYNC_LINES.converting)) ctx.emit(e);
      });
    }
    if (ctx.s.scenario === 'sync:crashed' && !crashStarted) {
      crashStarted = true;
      ctx.startJob('sync', null, (finish) => {
        for (const e of STREAMS.sync.slice(SYNC_START_LINE, SYNC_LINES.crash)) ctx.emit(e);
        // as jobs.sync_work: the run is filed with its crash note (RunFinished exit 1), then the crashed JobFinished
        // carries that report like a finished sync
        const report = `${FAKE_MUSIC}/.discjockey/reports/${runId(new Date())}.md`;
        setTimeout(() => {
          ctx.emit({ type: 'RunFinished', exit_code: 1, report_path: report });
          finish(false, { exit_code: 1, report, actions: 9, new_since_preview: 0 }, 'crashed',
            "The sync stopped unexpectedly. Everything done up to then is saved, and the next sync carries on from there.");
        }, 800 / ctx.speed);
      });
    }
    // Spotify is being read when the window opens, frozen at playlist 3 of 7
    if (ctx.s.scenario === 'sync:reading' || ctx.s.scenario === 'sync:rereading') {
      return async () => {
        const r = await base();
        if (!readStarted) {
          readStarted = true;
          setTimeout(() => {
            ctx.emit({ type: 'JobStarted', job_id: 900, kind: 'refresh', track_id: null });
            ctx.emit({ type: 'ReadingPlaylist', index: 3, total: 7, folder: 'Bouncy' });
          }, 50);
        }
        return r.ok ? { ...r, refresh_running: true } : r;
      };
    }
    return base;
  },
};
