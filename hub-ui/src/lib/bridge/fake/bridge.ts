// Fake mode only: an object implementing every contract method from an in-memory state (plan 64.8).
import type { Bridge } from '../client';
import type { HubEvent } from '../events';
import type {
  BatchResult, Candidate, ChangePreview, Fail, JobStart, LibraryFilter, LibrarySort, PlaylistLine, ProblemKind, Res, Result,
  AccountCheck, Browser, PlaylistService, SaveFiles, FolderCheck, FolderProblem, QobuzUsage, Service, SignalKind, TodoFilter, TodoGroupKey, TodoItem, Which, SyncEstimate,
} from '../types';
import { NOT_IN_PLAYLIST } from '../types';
import { LIBRARY_METHODS } from '../contract';
import {
  FAKE_MUSIC, FAKE_NEWEST_YT_DLP, QOBUZ_UNREADABLE, SERVICE_NAME, hintOf, playlistRef, serviceOfLink, budget, byQuality, checkText, coverUri, dateOnly, folderList, hash, inFolder, isoLocal, makeState, nextStep,
  pathOf, playlistRows, previewAction, qualityLabel, qualityLine, qualityOf, result, runDetail, runId,
  sampleCandidates, spotifyOk, todoDetail, todoFree, formatLine, SOURCE_FULL, todoGroup, trackRow, type FakeAccount, type FakeState,
  type FakeTrack,
} from './data';
import { JobRecord, Replay, STREAMS, SYNC_LINES, SYNC_START_LINE, rewrite } from './replay';
import { daysToLoad } from '../../days';
import { minutesByDownloads } from './minutes';
import { fakeSpectrum } from './spectrum';
import { toneUrl } from './audio';
import { BROWSER_NAMES, defaultBrowsers } from './browsers';
import { CRASHED_MESSAGE } from '../../copy';
import { downloads } from './downloads';
import {
  NO_BATCH, NOTHING_CHOSEN, hasFile, planRename, planTidy, planUndo, renameOffers, retargets, runBatch, seedTidy,
  tidyPreview, tidyRow, tidyWaiting, trackOfId, undoPreview, validMoves, validSaveFiles, moveBatches, outOfPlace,
  type MoveRun,
} from './tidy';
import { SERVICES, NAMES, RECOMMENDED, serviceOf, limits as limitsOf, whatIf as whatIfOf, gate, syncSplit, cards } from './limits';

/** library.FOLDER_PROBLEMS verbatim: what a refused folder says */
const FOLDER_PROBLEMS: Record<FolderProblem, string> = {
  not_absolute: 'Choose the folder with Choose…, or type its full path (starting with / or ~).',
  not_a_folder: 'That is a file, not a folder.',
  system_folder: 'That folder belongs to macOS or holds your whole home folder. Choose a folder just for your '
    + 'music, such as Music/Discjockey.',
  inside_app: 'That folder is inside Discjockey itself, which is replaced on every update. Choose a folder '
    + 'outside it.',
  is_support_dir: 'Discjockey keeps its own settings in that folder. Choose another one for your music.',
  not_writable: "Discjockey can't write in that folder. Choose one of your own folders.",
};
/** the fake Mac's home folder, for `~` */
const FAKE_HOME = '/Users/you';

/** Like FallbackSource.check_account + accounts.check_message: Safari needs Full Disk Access, the rest works. */
function accountCheck(service: 'youtube' | 'soundcloud', browser: Browser): AccountCheck {
  if (browser === 'safari') {
    return { ok: false, problem: 'cookies_unreadable', kbps: null, message: "macOS didn't let Discjockey read Safari's "
      + 'login. Give Discjockey Full Disk Access (System Settings → Privacy & Security → Full Disk Access), or pick '
      + 'another browser.' };
  }
  return { ok: true, problem: null, kbps: 256, message: `✓ ${NAMES[service]} works (256 kbps).` };
}

export type FakeOptions = { speed?: number; freeze?: number | null; emit?: (e: HubEvent) => void };
export type FakeContext = {
  s: FakeState;
  speed: number;
  emit(e: HubEvent): void;
  /** starts a write job; `body` calls `finish` when done */
  startJob(kind: string, track_id: string | null, body: (finish: Finish) => void): JobStart;
  /** refusal for network reads (sync running, offline), else null */
  networkBlock(): Fail | null;
  fail(kind: ProblemKind, message: string, service?: PlaylistService): Fail;
  later<T>(ms: number, value: () => T): Promise<T>;
  /** a login check's outcome saved / recorded as the engine does it (HubApi._account_result) */
  accountResult(service: 'youtube' | 'soundcloud', browser: Browser, profile: string | null, check: AccountCheck):
    { service: 'youtube' | 'soundcloud'; browser: Browser; profile: string | null; saved: boolean; check: AccountCheck };
};
export type Finish = (ok: boolean, result?: unknown, problem?: ProblemKind | null, message?: string) => void;
type Handlers = { [K in keyof Bridge]: Bridge[K] };
export type PageFake = {
  scenarios?: Record<string, (s: FakeState) => void>;
  overrides?: Partial<{ [K in keyof Bridge]: (ctx: FakeContext, base: Bridge[K]) => Bridge[K] }>;
};

const MSG = {
  busy: 'Discjockey is busy with another change. Try again when it has finished.',
  console: 'A Discjockey run in the terminal holds the library. Changes wait until it has finished.',
  sync_running: "Not while a sync runs. Try again when it's finished.",
  offline: "Spotify did not answer. Check your internet connection.",
  quit_busy: 'Discjockey is still busy with a change. Wait until it has finished, then quit.',
};
const ERROR_TURNS: [ProblemKind, string][] = [
  ['changed', 'This track changed in the meantime. Look at it again, then try once more.'],
  ['refused', 'Not possible: the file is open in another app.'],
  ['failed', 'The download stopped half way. Nothing was changed.'],
  ['crashed', 'Something went wrong. Try again.'],
];
const DOWNLOAD_KINDS = ['sync', 'use_candidate', 'use_link'];

/** Page extensions: src/pages/<page>/fake.ts may add scenarios and override handlers. */
const pageFakes = import.meta.glob<PageFake>('/src/pages/*/fake.ts', { eager: true });
export function pageScenarios(): Record<string, (s: FakeState) => void> {
  const out: Record<string, (s: FakeState) => void> = {};
  for (const [path, mod] of Object.entries(pageFakes)) {
    const page = path.split('/').at(-2)!;
    for (const [name, fn] of Object.entries(mod.scenarios ?? {})) out[`${page}:${name}`] = fn;
  }
  return out;
}
export const SCENARIOS = ['normal', 'update_available', 'first_run', 'offline', 'console', 'syncing', 'pause', 'break', 'stopped',
  'finished', 'big', 'errors', 'no_music', 'music_missing', 'qobuz_unreadable', 'qobuz_not_connected'] as const;

/** The dashboard's estimate has no minutes or uses tables (only the Sync page ticks subsets). */
const dashboardEstimate = ({ minutes_by_downloads: _table, accounts, ...rest }: SyncEstimate) =>
  ({ ...rest, accounts: accounts.map(({ uses_by_downloads: _uses, ...a }) => a) });

export function createFakeBridge(scenario: string, opts: FakeOptions = {}): Handlers & { _ctx: FakeContext } {
  const baseScenario = scenario.includes(':') ? 'normal' : scenario;
  const s = makeState(baseScenario);
  seedTidy(s);
  pageScenarios()[scenario]?.(s);
  const speed = opts.speed ?? 1;
  const emitRaw = opts.emit ?? (() => {});
  let nextId = 1;
  let job: JobRecord | null = null;
  let refreshJob: { id: number; timer: ReturnType<typeof setTimeout> } | null = null;
  let replay: Replay | null = null;
  let pendingFinish: Finish | null = null;   // a job that only ends by itself or with stop() (Spotify login)
  let signIn: JobRecord | null = null;         // the sign-in slot (beside the write jobs, as Jobs.start_sign_in)
  let signInStop: (() => void) | null = null;
  let savePending: MoveRun | null = null;    // a save in its short wait before the file is written (Stop ends it after the save)
  let moveRun: MoveRun | null = null;         // the move batch that is running (Stop ends it between two moves)

  const emit = (e: HubEvent) => {
    if (job?.running && e.type !== 'ConsoleBusy' && e.type !== 'FileDropped') {
      if (e.type !== 'JobStarted' && e.type !== 'JobFinished') job.record(e);
      else if ((e as { job_id: number }).job_id === job.id) job.record(e);
    }
    emitRaw(e);
  };
  const fail = (kind: ProblemKind, message: string, service?: PlaylistService): Fail =>
    ({ ok: false, kind, message, ...(service ? { service } : {}) });
  const later = <T>(ms: number, value: () => T) => new Promise<T>((r) => setTimeout(() => r(value()), ms / speed));
  const ok = <T extends object>(v: T) => ({ ok: true as const, ...v });
  const syncRunning = () => (job?.running && job.kind === 'sync') || s.console_running;
  const networkBlock = (): Fail | null => syncRunning() ? fail('sync_running', MSG.sync_running)
    : s.offline ? fail('offline', MSG.offline) : null;
  const track = (id: string) => s.tracks.find((t) => t.track_id === id);
  /** setup_account / account_sign_in saving a login with its profile and check (as HubApi._account_result) */
  function saveAccount(service: 'youtube' | 'soundcloud', browser: Browser, profile: string | null, check: AccountCheck) {
    const old = s.accounts[service];
    const lastCheck = checkRecord(check);
    const profileName = (s.browsers?.[service] ?? defaultBrowsers()).find((x) => x.id === browser)?.profiles
      .find((p) => p.id === profile)?.name ?? null;
    s.accounts[service] = old ? { ...old, browser, profile, profileName, lastCheck }
      : { limit: RECOMMENDED[service], extra_today: 0, carry_over: 0, used_today: 0, days: Array(14).fill(0),
        signals: [], last_download: null, browser, profile, profileName, lastCheck };
  }
  const checkRecord = (check: AccountCheck) =>
    ({ ok: check.ok, problem: check.problem, kbps: check.kbps, at: isoLocal(new Date()) });
  /** setup_account / account_sign_in after the check, as HubApi._account_result: saved when ok (SoundCloud also
   *  without Go+); a failed check of the saved login itself (same browser and profile) is recorded on it */
  function accountResult(service: 'youtube' | 'soundcloud', browser: Browser, profile: string | null,
    check: AccountCheck) {
    const saved = check.ok || (service === 'soundcloud' && check.problem === 'no_premium');
    const old = s.accounts[service];
    if (saved) saveAccount(service, browser, profile, check);
    else if (old && old.browser === browser && (old.profile ?? null) === profile) {
      s.accounts[service] = { ...old, lastCheck: checkRecord(check) };
    }
    return { service, browser, profile, saved, check };
  }

  /** check_music_folder: a path in s.folders answers as set; any other absolute path is a new, usable folder */
  function checkFolder(path: string): FolderCheck {
    if (typeof path !== 'string' || !(path.startsWith('/') || path.startsWith('~'))) {
      return { path, exists: false, usable: false, problem: 'not_absolute', kind: null, message: FOLDER_PROBLEMS.not_absolute };
    }
    const full = path === '~' || path.startsWith('~/') ? FAKE_HOME + path.slice(1) : path;  // as the engine: resolved
    const known = s.folders[full] ?? s.folders[path];
    if (!known) return { path: full, exists: false, usable: true, problem: null, kind: 'new', message: null };
    return { path: full, ...known, message: known.message ?? (known.problem ? FOLDER_PROBLEMS[known.problem] : null) };
  }

  function startJob(kind: string, track_id: string | null, body: (finish: Finish) => void): JobStart {
    if (s.console_running) return fail('console', MSG.console);
    if (job?.running) return fail('busy', MSG.busy);
    const id = nextId++;
    job = new JobRecord(id, kind, track_id, isoLocal(new Date()));
    const me = job;
    let finished = false;
    const finish: Finish = (good, res = null, problem = null, message = '') => {
      if (finished) return;
      finished = true;
      if (s.errors && good && !DOWNLOAD_KINDS.includes(kind) && kind !== 'scan' && !kind.startsWith('setup_')) {
        const [k, m] = ERROR_TURNS[s.errorTurn++ % ERROR_TURNS.length];
        good = false; problem = k; message = m; res = null;
      }
      emit({ type: 'JobFinished', job_id: id, kind, ok: good, problem: good ? null : (problem ?? 'failed'), message,
        result: good ? (res ?? {}) : (problem === 'stopped' ? (res ?? null) : null) } as HubEvent);
      me.running = false;
    };
    setTimeout(() => {
      emit({ type: 'JobStarted', job_id: id, kind, track_id });
      body(finish);
    }, 0);
    return { ok: true, job_id: id };
  }
  const ctx: FakeContext = { s, speed, emit, startJob, networkBlock, fail, later, accountResult };

  /** Runs move batches as the body of a write job: ends `stopped` (with the batches so far) when Stop came. */
  function moveJob(finish: Finish, work: (run: MoveRun) => Promise<{ result: BatchResult; stopped: boolean }[]>,
    wrap: (batches: BatchResult[]) => unknown): void {
    const run: MoveRun = { stopped: false };
    moveRun = run;
    work(run).then((done) => {
      moveRun = null;
      const out = wrap(done.map((d) => d.result));
      if (done.some((d) => d.stopped)) finish(false, out, 'stopped', 'Stopped. Nothing was left half-done.');
      else finish(true, out);
    }, () => { moveRun = null; finish(false, null, 'crashed', CRASHED_MESSAGE); });
  }

  // ---------- computed views ----------
  function preview() {
    type Row = ReturnType<typeof previewAction>;
    const groups: { key: string; label: string; actions: Row[] }[] = [];
    const never: Row[] = [];
    const add = (key: string, label: string, actions: Row[]) => {
      const keep = actions.filter((a) => a.kind !== 'acquire' || !s.never.includes(a.track_id));
      never.push(...actions.filter((a) => !keep.includes(a)));
      if (keep.length) groups.push({ key, label, actions: keep });
    };
    add('acquire:new', 'Download (new)', s.newTracks.map((t, i) => previewAction('acquire', 'new', t, false,
      null, i % 3 ? i % 5 : null)));
    add('acquire:retry', 'Try again', s.tracks.filter((t) => t.status === 'missing' && t.next_try_days === 1
      && t.in_playlists).map((t) => previewAction('acquire', 'retry', t, false, null, t.cover)));
    add('upgrade', 'Look for a better version (weekly check)', s.tracks.filter((t) => qualityOf(t) === 'weak'
      && !t.upgrade && !t.hidden && t.in_playlists).slice(0, 3).map((t) => previewAction('upgrade', 'weekly', t,
      true, pathOf(t), t.cover)));
    // the order the sync works through them: bought files first, then downloads, then the weekly checks; playlist order
    const rank = (k: string) => ({ adopt_bought: 0, acquire: 1, upgrade: 2 }[k] ?? 1);
    const folderAt = (f: string) => { const i = s.playlists.findIndex((p) => p.folder === f); return i < 0 ? 99 : i; };
    groups.flatMap((g) => g.actions).sort((a, b) => rank(a.kind) - rank(b.kind) || folderAt(a.folder) - folderAt(b.folder))
      .forEach((a, i) => { a.run = i; });
    const n = (k: string) => groups.find((g) => g.key === k)?.actions.length ?? 0;
    const counts = { new: n('acquire:new'), retries: n('acquire:retry'), redownloads: n('acquire:redownload'),
      bought: n('adopt_bought'), weekly_checks: n('upgrade') };
    const actions = groups.reduce((a, g) => a + g.actions.length, 0);
    const needed = counts.new + counts.retries + counts.redownloads + counts.weekly_checks;
    const g = gate(s);
    const left = g ? g.remaining : needed;
    const uses = Math.min(needed, left);
    const minutes = minutesByDownloads(uses);
    const estimate = { duration_min: minutes[uses], qobuz_limit: g?.limit ?? 0,
      qobuz_needed: needed, qobuz_left: left, qobuz_uses: uses, accounts: syncSplit(s, needed, uses),
      left: g ? g.remaining : null, limit: g?.limit ?? 0, minutes_by_downloads: minutes };
    const folders = s.playlists.filter((p) => p.enabled).map((p) => p.folder);
    const in_playlists = s.tracks.filter((t) => t.in_playlists).length + s.newTracks.length;
    return { groups, counts, actions, estimate, never, folders, in_playlists };
  }
  const stillToLoad = () => {
    const p = preview();
    const count = p.estimate.qobuz_needed;
    return { count, days: daysToLoad(count, budget(s).remaining, s.qobuz.limit),
      fits_today: count <= budget(s).remaining };
  };
  const summary = (r: (typeof s.runs)[number]) => ({ run_id: r.run_id, started: r.started, finished: r.finished,
    duration_s: r.duration_s, exit_code: r.exit_code, counts: r.counts, stopped_after: r.stopped_after });
  const assessment = (limit: number) => {
    const zones = [['careful', 40], ['normal', 60], ['faster', 79], ['fast', 100], ['risky', 500]] as const;
    const i = zones.findIndex(([, to]) => limit <= to);
    return { level: i + 1, label: zones[i][0] };
  };
  const whatIf = (limit: number, extra_today: number) => {
    const allowance = limit + s.qobuz.carry_over + extra_today;
    const remaining = Math.max(0, allowance - s.qobuz.used_today);
    const count = stillToLoad().count;
    return { limit, extra_today, assessment: assessment(limit), allowance_today: allowance, remaining_today: remaining,
      days_to_load: daysToLoad(count, remaining, limit),
      run_minutes: Math.max(1, Math.round(Math.min(count, remaining) * 0.75)) };
  };
  const opResult = (t: FakeTrack, section: string, note: string, more: Partial<Result> = {}) => ({
    track_id: t.track_id, result: result(section, t, note, { status: t.status, source: t.source,
      cutoff_hz: t.cutoff_hz, path: pathOf(t), ...more }), recovered: [] as [string, boolean][] });
  const versionHash = () => (Math.abs(hash(`v${s.version}`)).toString(16).padStart(8, '0')).repeat(8);
  const reportPath = (id: string) => `${FAKE_MUSIC}/.discjockey/reports/${id}.md`;
  const media = (t: FakeTrack, which: Which) => toneUrl(which === 'upgrade' ? Math.min(t.duration_s, 90)
    : Math.min(t.duration_s, 120), which === 'upgrade' ? 330 : 196 + (Math.abs(hash(t.track_id)) % 6) * 22);

  /** A short synthetic download for use_candidate / use_link (SourceChosen, Progress ×4, Checked, convert). */
  function syntheticDownload(t: FakeTrack, source: string, title: string, done: () => void) {
    const total = 9_400_000;
    const evs: HubEvent[] = [
      { type: 'StepChanged', track_id: t.track_id, step: 'search' },
      { type: 'SourceChosen', track_id: t.track_id, source, query_kind: 'chosen', title, duration_s: t.duration_s },
      { type: 'StepChanged', track_id: t.track_id, step: 'download' },
      ...[1, 2, 3, 4].map((k) => ({ type: 'Progress', track_id: t.track_id, step: 'download', done: (total * k) / 4,
        total, unit: 'bytes' }) as HubEvent),
      { type: 'StepChanged', track_id: t.track_id, step: 'check' },
      { type: 'Checked', track_id: t.track_id, file_duration_s: t.duration_s, track_duration_s: t.duration_s,
        codec: source === 'qobuz' ? 'flac' : 'aac', ok: true },
      { type: 'StepChanged', track_id: t.track_id, step: 'convert' },
      { type: 'Progress', track_id: t.track_id, step: 'convert', done: t.duration_s, total: t.duration_s,
        unit: 'seconds' },
      { type: 'StepChanged', track_id: t.track_id, step: 'analyse' },
    ];
    let i = 0;
    const tick = () => {
      if (i >= evs.length) return done();
      const e = evs[i++];
      emit(e);
      setTimeout(tick, (e.type === 'Progress' ? 700 : 200) / speed);
    };
    tick();
  }

  function startReplay(from: number, opts2: { events?: HubEvent[]; crashAfter?: number | null; freeze?: number | null;
    preRun?: number } = {}): JobStart {
    if (s.console_running) return fail('console', MSG.console);
    if (job?.running) return fail('busy', MSG.busy);
    const id = nextId++;
    const events = opts2.events ?? STREAMS.sync;
    job = new JobRecord(id, 'sync', null, isoLocal(new Date()));
    const rid = runId(new Date());
    const path = reportPath(rid);
    const me = job;
    if (opts2.preRun) {
      // a sync already running at load: record the first lines silently (job_status shows them), then continue
      for (let i = from - 1; i < opts2.preRun; i++) me.record(rewrite(events[i], id, path));
    }
    replay = new Replay({ events, from: opts2.preRun ? opts2.preRun + 1 : from, jobId: id, speed,
      freeze: opts2.freeze ?? opts.freeze ?? null, reportPath: path, emit, crashAfter: opts2.crashAfter ?? null,
      onDone: () => { me.running = false; me.stopping = false; replay = null; afterSync(rid, me); } });
    replay.start();
    return { ok: true, job_id: id };
  }
  /** After a replayed sync: its run is in the reports, and the plan is worked out again from the sync's own read
   *  and what the run left (like jobs.preview_after_run, issue 20), so what the run did is not offered again. */
  function afterSync(rid: string, rec: JobRecord) {
    const results = rec.results.map((e) => e.result as Result);
    const done = new Set(results.filter((r) => r.track_id && r.section !== 'queued' && r.section !== 'errors')
      .map((r) => r.track_id));
    s.spotify = { ...s.spotify, stale: false, read_at: rec.started, minutes_ago: 0 };
    s.newTracks = s.newTracks.filter((t) => t.track_id === 't5' || !done.has(t.track_id));
    const run = rec.last.RunFinished;
    if (!run) return;
    const started = new Date(rec.started);
    s.runs.unshift(runDetail(rid, started, Math.round((Date.now() - started.getTime()) / 1000), run.exit_code,
      results, run.exit_code === 130 ? results.length : null, s.tracks.filter((t) => t.upgrade).length));
    const t5 = s.newTracks.find((t) => t.track_id === 't5');
    if (t5 && results.some((r) => r.track_id === 't5' && r.section === 'new_not_lossless')) {
      s.newTracks = s.newTracks.filter((t) => t.track_id !== 't5');
      s.tracks.push({ ...t5, status: 'not_lossless', cutoff_hz: 20000, source: 'youtube_music', codec: 'aac',
        in_playlists: true, hidden: false, added: isoLocal(new Date()), cover: 2, isrc: null, playlists: [t5.folder],
        upgrade: null, rekordbox_check: null, other: null, next_try_days: null, rejected_sources: [] });
    }
  }

  // ---------- the contract ----------
  const h: Handlers = {
    async dashboard() {
      const inPl = s.tracks.filter((t) => t.in_playlists);
      const lossless = inPl.filter((t) => qualityOf(t) === 'lossless').length;
      const p = preview();
      const hour = new Date().getHours();
      return ok({
        greeting: hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening',
        spotify: { ...s.spotify },
        tiles: { lossless: { share: inPl.length ? lossless / inPl.length : null, lossless, total: inPl.length,
          by_quality: byQuality(inPl) }, qobuz_today: budget(s), still_to_load: stillToLoad(),
          account_today: cards(s).find((c) => c.set_up) ?? null },
        ready: s.previewRead ? { counts: p.counts, actions: p.actions, ...dashboardEstimate(p.estimate) } : null,
        needs_you: { upgrades: inPl.filter((t) => t.upgrade).length,
          swappable: inPl.filter((t) => t.upgrade?.swap_safe).length,
          not_found: inPl.filter((t) => qualityOf(t) === 'missing' && !t.hidden).length,
          weak: inPl.filter((t) => qualityOf(t) === 'weak' && !t.hidden).length },
        folders: s.playlists.map((pl) => {
          const ts = s.tracks.filter((t) => t.in_playlists && t.folder === pl.folder);
          return { folder: pl.folder, tracks: ts.length, by_quality: byQuality(ts),
            lossless_share: ts.length ? ts.filter((t) => qualityOf(t) === 'lossless').length / ts.length : null };
        }),
        last_runs: s.runs.slice(0, 30).map(summary), has_more_runs: s.runs.length > 30,
        next_checks: p.counts.weekly_checks,
        empty: !s.setup.complete ? 'not_set_up' : !s.playlists.length ? 'no_playlists' : null,
      });
    },
    async sidebar() {
      const files = s.tracks.filter((t) => t.status !== 'missing');
      return ok({ todo: todoView('all', false).chips.all, all_tracks: files.length,
        folders: folderList(s).map((f) => ({ ...f, tracks: files.filter((t) => t.folder === f.folder).length })),
        not_in_playlist: files.filter((t) => !t.in_playlists).length,
        limits_warning: cards(s).some((c) => c.new_warnings > 0 || c.paused) });
    },
    async sync_preview() {
      const p = preview();
      if (!s.previewRead) return ok({ spotify: { ...s.spotify }, counts: null, groups: [], estimate: null, never: [],
        folders: [], in_playlists: null, ambiguous: [], dropped: [], notes: [],
        empty: 'no_preview' as const });  // like views.sync_preview: never not_set_up
      return ok({ spotify: { ...s.spotify }, counts: p.counts, groups: p.groups, estimate: p.estimate, never: p.never,
        folders: p.folders, in_playlists: p.in_playlists, ambiguous: [], dropped: [], notes: [],
        empty: p.actions ? null : 'up_to_date' as const });
    },
    async refresh(auto = false) {
      if (auto && s.spotify.auto_read) {
        return fail('refused', 'Spotify was read by itself once this session already. Use ↻ Read Spotify to read it again.');
      }
      if (job?.running && job.kind === 'sync') return fail('busy', 'Not while a sync runs.');
      if (refreshJob) return fail('busy', 'Spotify is being read already.');
      if (!s.setup.spotify_login) return fail('not_set_up', 'Spotify is not set up yet.');
      const id = nextId++;
      s.spotify = { ...s.spotify, reading: true, auto_read: s.spotify.auto_read || auto };
      const [, msg] = STREAMS.sync;
      const folders = s.playlists.filter((p) => p.enabled).map((p) => p.folder);
      const reads = folders.map((folder, i) => setTimeout(() => {
        if (refreshJob?.id === id) emit({ type: 'ReadingPlaylist', index: i + 1, total: folders.length, folder });
      }, (100 + (i * 2300) / Math.max(1, folders.length)) / speed));
      setTimeout(() => {
        emit({ type: 'JobStarted', job_id: id, kind: 'refresh', track_id: null });
        emit(msg);
      }, 0);
      refreshJob = { id, timer: setTimeout(() => {
        reads.forEach(clearTimeout);
        refreshJob = null;
        if (s.offline) {
          s.spotify = { ...s.spotify, reading: false };
          emit({ type: 'JobFinished', job_id: id, kind: 'refresh', ok: false, problem: 'offline', message: MSG.offline,
            result: null });
          return;
        }
        s.spotify = { ...spotifyOk(0), auto_read: s.spotify.auto_read }; s.previewRead = true;
        emit({ type: 'JobFinished', job_id: id, kind: 'refresh', ok: true, problem: null, message: '',
          result: { actions: preview().actions } });
      }, 2500 / speed) };
      return ok({ job_id: id });
    },
    async stop_refresh() {
      if (!refreshJob) return ok({ stopped: false });
      clearTimeout(refreshJob.timer);
      const id = refreshJob.id;
      refreshJob = null;
      s.spotify = { ...s.spotify, reading: false };
      emit({ type: 'JobFinished', job_id: id, kind: 'refresh', ok: false, problem: 'stopped',
        message: 'Stopped. The last read stays.', result: null });
      return ok({ stopped: true });
    },
    async job_status() {
      return ok({ job: job ? job.snapshot() : null, refresh_running: !!refreshJob, console_running: s.console_running,
        spotify: { ...s.spotify }, sign_in: signIn ? signIn.snapshot() : null });
    },
    async library(folder: string | null, query: string, filter: LibraryFilter, sort: LibrarySort) {
      const known = folder === null || folder === NOT_IN_PLAYLIST || folderList(s).some((f) => f.folder === folder);
      if (!known) return fail('refused', `There is no folder "${folder}".`);
      const q = (query ?? '').trim().toLowerCase();
      const all = inFolder(s, folder);
      const found = q ? all.filter((t) => `${t.artist} ${t.title}`.toLowerCase().includes(q)) : all;
      const chips = { all: found.length, lossless: 0, good_lossy: 0, weak: 0, fake: 0, upgrade_ready: 0 };
      for (const t of found) {
        const k = qualityOf(t);
        if (k !== 'missing') chips[k]++;
        if (t.upgrade) chips.upgrade_ready++;
      }
      const rows = found.filter((t) => filter === 'all' || (filter === 'upgrade_ready' ? !!t.upgrade : qualityOf(t) === filter));
      const desc = sort.startsWith('-');
      const key = sort.replace('-', '');
      const qorder = ['lossless', 'good_lossy', 'weak', 'fake', 'missing'];
      const val = (t: FakeTrack): string | number => key === 'title' ? t.title.toLowerCase()
        : key === 'length' ? t.duration_s : key === 'source' ? (t.source ?? '') : key === 'quality'
          ? qorder.indexOf(qualityOf(t)) : key === 'added' ? (t.added ?? '')
            : key === 'folder' ? `${t.in_playlists ? 0 : 1} ${t.folder} ${t.artist} ${t.title}`.toLowerCase()
              : `${t.artist} ${t.title}`.toLowerCase();
      rows.sort((a, b) => (val(a) < val(b) ? -1 : val(a) > val(b) ? 1 : 0) * (desc ? -1 : 1));
      const lossless = all.filter((t) => qualityOf(t) === 'lossless').length;
      return ok({ title: folder === null ? 'All tracks' : folder === NOT_IN_PLAYLIST ? 'Not in a playlist' : folder,
        folder, summary: { tracks: all.length, lossless_share: all.length ? lossless / all.length : null,
          by_quality: byQuality(all), upgrades_ready: all.filter((t) => !!t.upgrade).length,
          to_do: all.filter((t) => t.in_playlists && !t.hidden && todoGroup(t)).length }, chips,
        rows: rows.map(trackRow), empty: !s.tracks.length ? 'empty_library' as const : rows.length ? null : 'no_match' as const });
    },
    async track(track_id: string) {
      const t = track(track_id);
      if (!t) return fail('refused', 'This track is not in your library any more.');
      const q = qualityOf(t);
      const plus = (n: number) => { const d = new Date(); d.setDate(d.getDate() + n); return dateOnly(d); };
      const query = `${t.artist} ${t.title}`.replace(/ /g, '+');
      return ok({ track: {
        ...trackRow(t), isrc: t.isrc, playlists: s.previewRead ? [...t.playlists] : null,
        in_playlist_count: t.playlists.length, quality_line: qualityLine(t), format_line: formatLine(t),
        source_full: !t.source || q === 'missing' ? null : SOURCE_FULL[t.source],
        source_url: t.source === 'youtube' ? 'https://www.youtube.com/watch?v=abcdefghijk'
          : t.source === 'youtube_music' ? 'https://music.youtube.com/watch?v=abcdefghijk'
            : t.source === 'soundcloud' ? 'https://soundcloud.com/artist/track'
              : t.source === 'qobuz' ? 'https://open.qobuz.com/track/112233' : null,
        track_link: t.link ?? { url: `https://open.spotify.com/track/${t.track_id}`, label: 'Open in Spotify' },
        next_qobuz_check: q === 'lossless' ? null : q === 'missing' ? (t.next_try_days === 1 ? 'next_sync'
          : plus(t.next_try_days ?? 5)) : plus(4),
        rejected_sources: [...t.rejected_sources],
        buy_links: { beatport: `https://www.beatport.com/search?q=${query}`, bandcamp: `https://bandcamp.com/search?q=${query}` },
        free_downloads: q === 'lossless' ? [] : [...(t.free_downloads ?? [])],
        bought_name: `Library/${t.folder}/${t.artist} - ${t.title}.wav`,
        audio_url: q === 'missing' ? null : media(t, 'current'),
        upgrade: t.upgrade ? { ...t.upgrade, audio_url: media(t, 'upgrade') } : null,
      } });
    },
    async todo(filter: TodoFilter, show_hidden: boolean) { return ok(todoView(filter, show_hidden)); },
    async playlists() {
      const overlaps = s.tracks.filter((t) => t.playlists.length > 1).map((t) => {
        const r = trackRow(t);
        return { track_id: t.track_id, artist: t.artist, title: t.title, cover_url: r.cover_url,
          downloaded: r.quality !== 'missing', quality: r.quality, quality_label: r.quality_label,
          never: s.never.includes(t.track_id), folders: [...t.playlists], lands_in: s.playlists.find((p) => t.playlists.includes(p.folder))?.folder ?? t.folder };
      });
      return ok({ version: versionHash(), problem: null, rows: playlistRows(s), overlaps, tidy: { waiting: tidyWaiting(s) },
        empty: s.playlists.length ? null : 'no_playlists' as const });
    },
    async limits(service: Service) {
      if (!SERVICES.includes(service)) return fail('refused', 'service must be one of qobuz, youtube, soundcloud');
      return ok(limitsOf(s, service, stillToLoad().count));
    },
    async limits_what_if(service: Service, limit: number, extra_today: number) {
      if (!serviceOf(s, service)) return fail('refused', `Set up ${NAMES[service]} first.`);
      if (!(limit >= 1 && limit <= 500)) return fail('refused', 'The daily limit is between 1 and 500.');
      return ok(whatIfOf(s, service, limit, extra_today ?? 0, stillToLoad().count));
    },
    async runs() { return ok({ runs: s.runs.map(summary) }); },
    async run(run_id: string) {
      const r = s.runs.find((x) => x.run_id === run_id);
      if (!r) return fail('refused', 'This report is not there any more.');
      // like the hub: each row shown one by one gets its cover; the playlist folders in their order
      const withCover = (x: Result) => x.track_id && x.section !== 'queued'
        ? { ...x, cover_url: coverUri(track(x.track_id)?.cover ?? null) } : x;
      const sections = Object.fromEntries(Object.entries(r.sections).map(([k, v]) => [k, v.map(withCover)]));
      return ok({ run: { ...r, sections, needs_you: r.needs_you.map(withCover), queued: r.sections.queued?.length ?? 0,
        folder_order: folderList(s).map((f) => f.folder) } });
    },
    async spectrum(track_id: string, which: Which) {
      const t = track(track_id);
      if (!t || t.status === 'missing') return fail('refused', 'This track has no file yet.');
      if (which === 'upgrade' && !t.upgrade) return fail('refused', 'There is no upgrade for this track.');
      return later(350, () => ok({ spectrum: fakeSpectrum(which === 'upgrade' ? null : t.cutoff_hz,
        Math.abs(hash(t.track_id)), t.duration_s, which) }));
    },
    async media_url(track_id: string, which: Which) {
      const t = track(track_id);
      if (!t || t.status === 'missing') return fail('refused', 'This track has no file yet.');
      return ok({ url: media(t, which) });
    },
    async setup_status() {
      const status = (a: FakeAccount | null) => a && { browser: a.browser, browser_name: BROWSER_NAMES[a.browser],
        daily_limit: a.limit, profile: a.profile ?? null, profile_name: a.profileName ?? null,
        last_check: a.lastCheck ?? null };
      return ok({ ...s.setup, music: { ...s.setup.music }, tools: { ...s.setup.tools }, qobuz_skipped: s.qobuzSkipped,
        qobuz_last_check: s.qobuzLastCheck ?? null,
        spotify_user: s.setup.spotify_login ? s.spotifyUser ?? 'DJ One' : null,
        accounts: { youtube: status(s.accounts.youtube), soundcloud: status(s.accounts.soundcloud) } });
    },
    async select(track_id: string | null) { s.selected = track_id; return ok({}); },
    async downloads_view() {
      const d = downloads(s);
      if (s.setup.music.state === 'ok') return ok({ downloads: d });
      // no music folder: the engine counts an empty library
      return ok({ downloads: { ...d, qobuz: { ...d.qobuz, tracks: 0 }, youtube: { ...d.youtube, tracks: 0 },
        soundcloud: { ...d.soundcloud, tracks: 0 }, library: { lossless: 0, account: 0, free: 0 } } });
    },
    async find_logins(service: 'youtube' | 'soundcloud') {
      if (!['youtube', 'soundcloud'].includes(service)) return fail('refused', 'service must be one of youtube, soundcloud');
      return later(250, () => ok({ browsers: (s.browsers?.[service] ?? defaultBrowsers()).map((b) => ({ ...b,
        profiles: b.profiles.map((p) => ({ ...p })) })) }));
    },
    async account_sign_in(service: 'youtube' | 'soundcloud', browser: Browser, profile: string | null = null) {
      if (!['youtube', 'soundcloud'].includes(service)) return fail('refused', 'service must be one of youtube, soundcloud');
      if (syncRunning()) return fail('sync_running', MSG.sync_running);
      if (signIn?.running) return fail('busy', 'A sign-in is already waiting for the browser.');
      const b = (s.browsers?.[service] ?? defaultBrowsers()).find((x) => x.id === browser);
      if (!b) return fail('refused', `${BROWSER_NAMES[browser]} isn't installed on this Mac.`);
      const id = nextId++;
      const me = signIn = new JobRecord(id, 'account_sign_in', null, isoLocal(new Date()));
      const send = (e: HubEvent) => { if (me.running) me.record(e); emitRaw(e); };
      const timers: ReturnType<typeof setTimeout>[] = [];
      const end = (good: boolean, result: unknown, problem: ProblemKind | null, message: string) => {
        if (!me.running) return;
        timers.forEach(clearTimeout);
        send({ type: 'JobFinished', job_id: id, kind: 'account_sign_in', ok: good, problem, message,
          result: good ? result : null } as HubEvent);
        signInStop = null;
      };
      signInStop = () => end(false, null, 'stopped', 'Stopped. Nothing was changed.');
      timers.push(setTimeout(() => {
        send({ type: 'JobStarted', job_id: id, kind: 'account_sign_in', track_id: null });
        if (b.problem === 'no_access') {
          end(false, null, 'failed', accountCheck(service, 'safari').message);
          return;
        }
        send({ type: 'SignInPhase', service, phase: 'waiting', browser, browser_name: BROWSER_NAMES[browser] });
        if (s.signInWaits) return;
        if (s.signInTimesOut) {
          timers.push(setTimeout(() => end(false, null, 'failed', "Didn't see a login in 10 minutes. Sign in again."),
            2400 / speed));
          return;
        }
        timers.push(setTimeout(() => {
          send({ type: 'SignInPhase', service, phase: 'checking', browser, browser_name: BROWSER_NAMES[browser] });
          timers.push(setTimeout(() => {
            const check = accountCheck(service, browser);
            const prof = profile ?? b.profiles[0]?.id ?? null;
            end(true, accountResult(service, browser, prof, check), null, '');
          }, 700 / speed));
        }, 1800 / speed));
      }, 0));
      return { ok: true as const, job_id: id };
    },
    async stop_sign_in() {
      if (!signInStop) return ok({ stopped: false });
      signInStop();
      return ok({ stopped: true });
    },
    async open_privacy_settings() { return ok({}); },
    async qobuz_check_login() {
      if (syncRunning()) return fail('sync_running', MSG.sync_running);
      return startJob('qobuz_check_login', null, (finish) => setTimeout(() => {
        s.qobuzLastCheck = { ok: true, problem: null, kbps: null, at: isoLocal(new Date()) };
        finish(true, {});
      }, 600 / speed));
    },
    async spotify_sign_out() {
      return startJob('spotify_sign_out', null, (finish) => setTimeout(() => {
        s.setup = nextStep({ ...s.setup, spotify_login: false });
        finish(true, {});
      }, 300 / speed));
    },

    async search_candidates(track_id: string) {
      const block = networkBlock();
      if (block) return block;
      const t = track(track_id);
      if (!t) return fail('refused', 'This track is not in your library any more.');
      return later(900, () => ok({ track_id, track_duration_s: t.duration_s, current_quality_label: qualityLabel(t),
        candidates: sampleCandidates(t), notes: ['YouTube: 1 more result is a live version, left out.'] }));
    },
    async preview(_track_id: string, candidate: Candidate) {
      const block = networkBlock();
      if (block) return block;
      if (candidate?.source === 'qobuz') return fail('refused', 'Qobuz versions have no preview.');
      if (candidate?.id?.startsWith('drm')) return later(600, () => fail('protected', "SoundCloud marks this upload as "
        + "DRM-protected, so Discjockey can't play or use it. Pick another version."));
      return later(1200, () => ok({ url: toneUrl(30, 262 + (Math.abs(hash(candidate?.key ?? '')) % 5) * 30) }));
    },
    async add_playlist(url: string) {
      const block = networkBlock();
      if (block) return block;
      const q = /open\.qobuz\.com\/playlist\/(\d+)/.exec(url ?? '');
      if (q) {
        if (s.spotify.services.some((x) => x.service === 'qobuz' && !x.connected)) {
          return fail('not_set_up', 'Connect Qobuz first.', 'qobuz');
        }
        if (s.qobuzUnreadable) return later(700, () => fail('playlist_unreadable', QOBUZ_UNREADABLE, 'qobuz'));
        const name = `Qobuz playlist ${q[1].slice(-4)}`;
        return later(700, () => ok({ playlist_id: `qobuz:${q[1]}`, service: 'qobuz' as const, service_name: 'Qobuz',
          link: `https://open.qobuz.com/playlist/${q[1]}`,
          info: { name, owner_name: 'Example Curator', yours: false, collaborative: false, readable: true,
            image_url: null, track_count: 18, hint: hintOf('qobuz') }, tracks: 18, readable: true,
          suggested_folder: name.replace(/\W+/g, '_'), hint: null }));
      }
      const m = /open\.spotify\.com\/playlist\/([A-Za-z0-9]+)/.exec(url ?? '');
      if (!m) return fail('refused', "That isn't a Spotify or Qobuz playlist link. Copy it in Spotify: Share → Copy link to playlist.");
      const id = m[1];
      const readable = !/private|follow/i.test(id);
      const name = `Name of ${id.slice(0, 4)}`;
      const link = `https://open.spotify.com/playlist/${id}`;
      return later(700, () => ok({ playlist_id: playlistRef(link) ?? id, service: serviceOfLink(link),
        service_name: SERVICE_NAME[serviceOfLink(link)], link,
        info: { name, owner_name: readable ? 'DJ One' : 'Someone else', yours: readable, collaborative: false, readable,
          image_url: null, track_count: readable ? 24 : 0, hint: hintOf('spotify') }, tracks: readable ? 24 : 0, readable,
        suggested_folder: name.replace(/\W+/g, '_'), hint: readable ? null : hintOf('spotify') }));
    },
    async tidy_preview() { return ok(tidyPreview(s)); },
    async move_batches() { return ok(moveBatches(s)); },
    async undo_preview(batch_id: number) {
      const p = undoPreview(s, batch_id);
      return p ? ok(p) : fail('refused', NO_BATCH);
    },
    async preview_playlist_change(lines: PlaylistLine[]) {
      const block = networkBlock();
      if (block) return block;
      return later(300, () => ok(changePreview(lines)));
    },

    async start_sync(selected) {
      if (!Array.isArray(selected)) return fail('refused', 'Pick at least one thing to do.');
      if (s.errors) {
        s.syncStarts++;
        if (s.syncStarts % 2 === 1) {
          return startJob('sync', null, (finish) => setTimeout(() => finish(false, null, 'login_expired',
            'Your Spotify login has expired. Log in again in setup.'), 600 / speed));
        }
        return startReplay(SYNC_START_LINE, { crashAfter: SYNC_LINES.crash });
      }
      if (!selected.length) {
        return startJob('sync', null, (finish) => setTimeout(() => finish(true, { exit_code: 0, report: '',
          actions: 0, new_since_preview: 0 }), 300 / speed));
      }
      return startReplay(SYNC_START_LINE);
    },
    async stop() {
      if (moveRun && job?.running) { job.stopping = true; moveRun.stopped = true; return ok({ stopped: true }); }
      if (savePending && job?.running) { job.stopping = true; savePending.stopped = true; return ok({ stopped: true }); }
      if (replay && job?.running) { job.stopping = true; replay.stop(); return ok({ stopped: true }); }
      if (pendingFinish && job?.running) {
        job.stopping = true;
        const f = pendingFinish; pendingFinish = null;
        f(false, null, 'stopped', 'Stopped. Nothing was changed.');
        return ok({ stopped: true });
      }
      return ok({ stopped: false });
    },
    async save_playlists(lines: PlaylistLine[], loaded_version: string, files?: SaveFiles | null) {
      const problem = linesProblem(lines);
      if (problem) return fail('refused', problem);
      const choice = validSaveFiles(files);
      if (choice === 'bad') return fail('refused', 'Choose whether to move the files or leave them where they are.');
      const wait: MoveRun = { stopped: false };
      const started = startJob('save_playlists', null, (finish) => {
        setTimeout(() => {
          if (savePending === wait) savePending = null;
          if (loaded_version !== versionHash()) {
            return finish(false, null, 'changed', 'playlists.txt was changed elsewhere. Load it again before saving.');
          }
          const { renames, moved } = retargets(s, lines);
          const before = new Map(s.tracks.map((t) => [t.track_id, pathOf(t) ?? '']));
          const old = new Map(s.playlists.map((p) => [p.link, p]));
          s.playlists = lines.map((l) => ({ folder: l.folder, link: l.link, enabled: l.enabled,
            info: old.get(l.link)?.info ?? null }));
          for (const t of s.tracks) t.playlists = t.playlists.map((f) => renames.find(([was]) => was === f)?.[1] ?? f);
          s.version++;
          // as the real setup_status, which reads playlists.txt: a saved list counts as "playlists added"
          s.setup = { ...s.setup, playlists: s.playlists.length > 0 };
          s.spotify = { ...s.spotify, stale: true };
          if (!choice) return finish(true, { version: versionHash(), batches: [] });
          // the songs get their new folder; their files stay until moved, and a file left in place is the user's own
          for (const t of s.tracks) {
            const m = moved.get(t.track_id);
            if (!m) continue;
            const sits = t.at ?? t.folder;
            t.folder = m.to;
            if (hasFile(t) && t.in_playlists) {
              if (sits !== m.to) t.at = sits; else delete t.at;
              if (choice.choice === 'leave' && !s.tidy.placed[t.track_id]) s.tidy.placed[t.track_id] = 'user';
            }
          }
          if (choice.choice === 'leave') return finish(true, { version: versionHash(), batches: [] });
          // as the real backend: a Stop before the moves start leaves the file saved and no batch run
          if (wait.stopped) return finish(false, { version: versionHash(), batches: [] }, 'stopped', 'Stopped. Nothing was left half-done.');
          moveJob(finish, async (run) => {
            const out: { result: BatchResult; stopped: boolean }[] = [];
            for (const [was, now] of choice.renames) {
              const r = await runBatch(s, emit, run, 250 / speed, 'rename', [planRename(s, was, now)], { about: { from: was, to: now } });
              out.push(r);
              if (r.stopped) return out;
            }
            const accept = new Map([...before].filter(([id]) => moved.has(id)));
            const sent = choice.moves.filter(([id]) => { const t = trackOfId(s, id); return !t || outOfPlace(t); });
            const plan = planTidy(s, sent, accept);
            if (plan.length) out.push(await runBatch(s, emit, run, 250 / speed, 'save', plan));
            return out;
          }, (batches) => ({ version: versionHash(), batches }));
        }, 500 / speed);
      });
      if (started.ok) savePending = wait;  // from now on a Stop reaches it, also before the job's first tick
      return started;
    },
    async tidy_up(moves: [number, string][]) {
      const sent = validMoves(moves);
      if (!sent) return fail('refused', 'Each file to move needs its number and where it is now.');
      if (!sent.length) return fail('refused', NOTHING_CHOSEN);
      return startJob('tidy', null, (finish) => moveJob(finish, async (run) =>
        [await runBatch(s, emit, run, 250 / speed, 'tidy', planTidy(s, sent))], (batches) => batches[0]));
    },
    async undo_moves(batch_id: number) {
      const b = Number.isInteger(batch_id) ? s.tidy.batches.find((x) => x.id === batch_id) : undefined;
      if (!b) return fail('refused', NO_BATCH);
      return startJob('undo_moves', null, (finish) => moveJob(finish, async (run) =>
        [await runBatch(s, emit, run, 250 / speed, 'undo', planUndo(s, b), { undoes: b.id })],
      (batches) => batches[0]));
    },
    async save_limits(service: Service, limit: number, extra_today: number) {
      const f = serviceOf(s, service);
      if (!f) return fail('refused', `Set up ${NAMES[service]} first.`);
      if (!(Number.isInteger(limit) && limit >= 1 && limit <= 500)) return fail('refused', 'The daily limit is between 1 and 500.');
      if (!(Number.isInteger(extra_today) && extra_today >= 0 && extra_today <= 200)) {
        return fail('refused', 'Extra downloads today are between 0 and 200.');
      }
      return startJob('save_limits', null, (finish) => setTimeout(() => {
        f.limit = limit; f.extra_today = extra_today;
        finish(true, { service, limit, extra_today });
      }, 400 / speed));
    },
    async mark_warnings_seen(service: Service) {
      const f = serviceOf(s, service);
      if (!f) return fail('refused', `Set up ${NAMES[service]} first.`);
      return startJob('mark_warnings_seen', null, (finish) => setTimeout(() => {
        const p = (n: number) => String(n).padStart(2, '0'), d = new Date(s.now);
        f.seen = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
        finish(true, { service, seen_until: f.seen });
      }, 300 / speed));
    },
    async hide(track_id: string, hidden: boolean) {
      const t = track(track_id);
      if (!t) return fail('refused', 'This track is not in your library any more.');
      return startJob(hidden ? 'hide' : 'unhide', track_id, (finish) => setTimeout(() => {
        t.hidden = hidden;
        finish(true, opResult(t, hidden ? 'hidden' : 'unhidden', hidden ? 'hidden from the to-do list' : 'back on the to-do list'));
      }, 400 / speed));
    },
    async never_download(track_id: string, never: boolean) {
      const p = preview();
      const known = [...p.groups.flatMap((g) => g.actions), ...p.never].some((a) => a.track_id === track_id);
      if (never && !known) return fail('changed', 'This track is not in the sync plan any more.');
      return startJob('never_download', track_id, (finish) => setTimeout(() => {
        s.never = never ? [...new Set([...s.never, track_id])] : s.never.filter((x) => x !== track_id);
        finish(true, { track_id, never });
      }, 300 / speed));
    },
    async rescan_library() {
      // a finished scan that found nothing new (the quiet, usual answer)
      return startJob('scan', null, (finish) => setTimeout(() => {
        finish(true, { moved: 0, new: 0, gone: 0, changed: 0, copies: 0 });
      }, 50 / speed));
    },
    async add_bought_file(track_id: string) {
      const t = track(track_id);
      if (!t) return fail('refused', 'This track is not in your library any more.');
      if (s.dropped?.track_id !== track_id) return fail('refused', 'Drop the bought file on this track first.');
      return startJob('add_bought_file', track_id, (finish) => setTimeout(() => {
        const name = s.dropped?.name ?? '';
        s.dropped = null;
        Object.assign(t, { status: 'lossless', cutoff_hz: null, source: 'manual', codec: 'wav', upgrade: null });
        finish(true, opResult(t, 'bought', `bought file ${name}`));
      }, 1500 / speed));
    },
    async use_candidate(track_id: string, candidate: Candidate) {
      const t = track(track_id);
      if (!t) return fail('refused', 'This track is not in your library any more.');
      if (!candidate || typeof candidate !== 'object' || !candidate.id) return fail('refused', 'That is not a version from the list.');
      if (candidate.current) return fail('refused', 'This is the version you have now.');
      return startJob('use_candidate', track_id, (finish) => syntheticDownload(t, String(candidate.source), candidate.title,
        () => finishReplace(t, String(candidate.source), finish)));
    },
    async use_link(track_id: string, url: string) {
      const t = track(track_id);
      if (!t) return fail('refused', 'This track is not in your library any more.');
      const source = /qobuz\.com/.test(url) ? 'qobuz' : /music\.youtube/.test(url) ? 'youtube_music'
        : /soundcloud\.com/.test(url) ? 'soundcloud' : /youtu\.?be/.test(url) ? 'youtube' : null;
      if (!source) return fail('refused', 'Paste a Qobuz, YouTube, YouTube Music or SoundCloud link.');
      return startJob('use_link', track_id, (finish) => syntheticDownload(t, source, t.title,
        () => finishReplace(t, source, finish)));
    },
    async reject_current(track_id: string) {
      const t = track(track_id);
      if (!t) return fail('refused', 'This track is not in your library any more.');
      return startJob('reject_current', track_id, (finish) => setTimeout(() => {
        if (t.source) t.rejected_sources.push(`${t.source}:${t.track_id}`);
        Object.assign(t, { status: 'missing', cutoff_hz: null, source: null, codec: null, next_try_days: null,
          rekordbox_check: { reason: 'wrong_song', since: dateOnly(new Date()) } });
        finish(true, opResult(t, 'rejected', `moved to Superseded/${t.folder}/`,
          { path: `Superseded/${t.folder}/${t.artist} - ${t.title}.aiff` }));
      }, 500 / speed));
    },
    async rekordbox_checked(track_id: string) {
      const t = track(track_id);
      if (!t) return fail('refused', 'This track is not in your library any more.');
      if (!t.rekordbox_check) return fail('refused', 'Nothing to check in rekordbox for this track.');
      return startJob('rekordbox_checked', track_id, (finish) => setTimeout(() => {
        t.rekordbox_check = null;
        finish(true, opResult(t, 'rekordbox_checked', 'checked in rekordbox'));
      }, 300 / speed));
    },
    async upgrade(track_id: string, mode: 'swap' | 'add_new' | 'discard') {
      const t = track(track_id);
      if (!t?.upgrade) return fail('refused', 'There is no upgrade for this track.');
      if (!['swap', 'add_new', 'discard'].includes(mode)) return fail('refused', 'Pick swap, add as new or discard.');
      if (mode === 'swap' && !t.upgrade.swap_safe) return fail('refused', "The two versions don't match, so a swap would break your cue points.");
      return startJob(`upgrade_${mode}`, track_id, (finish) => setTimeout(() => {
        if (mode === 'discard') {
          t.upgrade = null;
          return finish(true, opResult(t, 'discarded', 'upgrade discarded'));
        }
        Object.assign(t, { status: 'lossless', cutoff_hz: null, source: 'qobuz', codec: 'flac', upgrade: null });
        if (mode === 'add_new') t.rekordbox_check = { reason: 'added_as_new', since: dateOnly(new Date()) };
        finish(true, opResult(t, mode === 'swap' ? 'swapped' : 'added_new', mode === 'swap'
          ? 'swapped, the old file is in Superseded' : 'added as a new file, the old one is in Superseded'));
      }, 900 / speed));
    },

    async show_in_finder() { return ok({}); },
    async reveal(rel_path: string) {
      if (typeof rel_path !== 'string' || rel_path.startsWith('/') || rel_path.includes('..')) {
        return fail('refused', 'Only folders inside your music folder can be shown.');
      }
      return ok({});
    },
    async open_report(run_id: string) {
      return s.runs.some((r) => r.run_id === run_id) ? ok({}) : fail('refused', 'This report is not there any more.');
    },
    async open_licenses() {
      return s.licensesMissing ? fail('refused', 'The licences folder is missing from this copy of Discjockey.') : ok({});
    },
    async open_external(url: string) {
      return /^https:\/\//.test(url ?? '') ? ok({}) : fail('refused', 'Only https links open in the browser.');
    },
    async app_update() { return ok({ ...s.appUpdate }); },
    // the music folder (api.py pick_folder / check_music_folder / set_music_folder / retry_music_folder)
    async pick_folder(_start?: string | null) { return later(300, () => ok({ path: s.pick })); },
    async check_music_folder(path: string) { return ok(checkFolder(path)); },
    async set_music_folder(path: string) {
      const c = checkFolder(path);
      if (!c.usable) return fail('refused', c.message ?? FOLDER_PROBLEMS[c.problem ?? 'not_absolute']);
      const music = s.setup.music;
      if (music.state === 'ok' && music.path === c.path) return ok({ music: { ...music }, restart: false });
      // no library yet: no lock to share with a terminal run, as in the engine
      if (music.state === 'ok' && s.console_running) return fail('console', MSG.console);
      if (job?.running) return fail('busy', MSG.busy);
      if (music.state === 'ok') return ok({ music: { ...music }, restart: true });
      s.setup = nextStep({ ...s.setup, music: { state: 'ok', path: c.path, suggested: music.suggested } });
      return ok({ music: { ...s.setup.music }, restart: false });
    },
    async retry_music_folder() { return ok({ music: { ...s.setup.music } }); },

    async quit() { return job?.running ? fail('busy', MSG.quit_busy) : ok({}); },

    async setup_check_tools() {
      const tools = { ...s.setup.tools };
      const missing = Object.entries(tools).filter(([, v]) => !v).map(([k]) => k);
      return later(400, () => ok({ tools, missing, hints: Object.fromEntries(missing.map((m) => [m, `Install ${m} with Homebrew: brew install ${m === 'ffprobe' ? 'ffmpeg' : m}`])),
        redirect_uri: 'http://127.0.0.1:8888/callback',
        download_tools: { 'yt-dlp': { ...s.downloadTools['yt-dlp'] }, streamrip: { ...s.downloadTools.streamrip } },
        download_tools_problem: null }));
    },
    async setup_save_client_id(client_id: string) {
      if (!/^[0-9a-f]{32}$/i.test(client_id ?? '')) return fail('refused', 'A Client ID has 32 letters and digits (0–9, a–f).');
      return startJob('setup_save_client_id', null, (finish) => setTimeout(() => {
        s.setup = nextStep({ ...s.setup, spotify_app: true });
        finish(true, {});
      }, 300 / speed));
    },
    async setup_spotify_login() {
      return startJob('setup_spotify_login', null, (finish) => {
        pendingFinish = finish;
        setTimeout(() => {
          if (pendingFinish !== finish) return;
          pendingFinish = null;
          s.setup = nextStep({ ...s.setup, spotify_login: true, spotify_skipped: false });
          s.spotify = { ...spotifyOk(0), auto_read: s.spotify.auto_read };
          finish(true, { user: 'DJ One' });
        }, 4000 / speed);
      });
    },
    async setup_qobuz_login(email: string, password: string) {
      const wrong = password === 'wrong' || !email?.includes('@');
      return startJob('setup_qobuz_login', null, (finish) => setTimeout(() => {
        if (wrong) return finish(false, null, 'failed', 'Qobuz did not accept this email and password.');
        s.setup = nextStep({ ...s.setup, qobuz: true, qobuz_skipped: false }); s.qobuzSkipped = false;
        finish(true, {});
      }, 1200 / speed));
    },
    async setup_skip_qobuz() {
      return startJob('setup_skip_qobuz', null, (finish) => setTimeout(() => {
        s.qobuzSkipped = true; s.setup = nextStep({ ...s.setup, qobuz_skipped: true });
        finish(true, {});
      }, 300 / speed));
    },
    async setup_skip_spotify() {
      return startJob('setup_skip_spotify', null, (finish) => setTimeout(() => {
        s.setup = nextStep({ ...s.setup, spotify_skipped: true });
        finish(true, {});
      }, 300 / speed));
    },
    async setup_account(service: 'youtube' | 'soundcloud', browser: Browser, profile: string | null = null) {
      if (!['youtube', 'soundcloud'].includes(service)) return fail('refused', 'service must be one of youtube, soundcloud');
      if (!(browser in BROWSER_NAMES)) return fail('refused', 'browser must be one of safari, chrome, firefox, brave, edge');
      return startJob('setup_account', null, (finish) => setTimeout(() => {
        finish(true, accountResult(service, browser, profile, accountCheck(service, browser)));
      }, 600 / speed));
    },
    async setup_check_account(service: 'youtube' | 'soundcloud') {
      const a = s.accounts[service];
      if (!a) return fail('refused', `${NAMES[service]} is not set up.`);
      if (syncRunning()) return fail('sync_running', MSG.sync_running);
      if (s.console_running) return fail('console', MSG.console);
      if (job?.running) return fail('busy', MSG.busy);  // the save takes the lock, as in the engine
      const check = accountCheck(service, a.browser);
      s.accounts[service] = { ...a, lastCheck: checkRecord(check) };
      return ok({ service, check });
    },
    async setup_forget_account(service: 'youtube' | 'soundcloud') {
      return startJob('setup_forget_account', null, (finish) => setTimeout(() => {
        s.accounts[service] = null;
        finish(true, { service });
      }, 300 / speed));
    },
    async update_tools() {
      return startJob('update_tools', null, (finish) => setTimeout(() => {
        const yt = s.downloadTools['yt-dlp'];
        const next = yt.waiting ?? yt.version;
        if (next === FAKE_NEWEST_YT_DLP) {
          finish(true, { before: { 'yt-dlp': next }, after: { 'yt-dlp': next }, restart: yt.waiting !== null });
          return;
        }
        s.downloadTools = { ...s.downloadTools,
          'yt-dlp': { ...yt, waiting: FAKE_NEWEST_YT_DLP, previous: next } };
        finish(true, { before: { 'yt-dlp': next }, after: { 'yt-dlp': FAKE_NEWEST_YT_DLP }, restart: true });
      }, 3000 / speed));
    },
    async rollback_tools() {
      return startJob('rollback_tools', null, (finish) => setTimeout(() => {
        const yt = s.downloadTools['yt-dlp'];
        if (!yt.previous) { finish(false, null, 'refused', 'There is no earlier version to go back to.'); return; }
        const before = yt.waiting ?? yt.version;
        const after = yt.previous;
        // The engine keeps one folder back, so a second step exists only after two updates; the fake has one newest
        // version, so after stepping back (to the built-in) there is nothing earlier: previous null, as the engine says.
        s.downloadTools = { ...s.downloadTools,
          'yt-dlp': { ...yt, waiting: after === yt.version ? null : after, previous: null } };
        finish(true, { before: { 'yt-dlp': before }, after: { 'yt-dlp': after }, restart: after !== yt.version });
      }, 600 / speed));
    },
  };

  function finishReplace(t: FakeTrack, source: string, finish: Finish) {
    const lossless = source === 'qobuz';
    Object.assign(t, { status: lossless ? 'lossless' : 'not_lossless', cutoff_hz: lossless ? null : 20000, source,
      codec: lossless ? 'flac' : 'aac', rekordbox_check: { reason: 'wrong_song', since: dateOnly(new Date()) } });
    finish(true, opResult(t, 'replaced', 'the old file is in Superseded'));
  }

  function todoView(filter: TodoFilter, show_hidden: boolean) {
    const order: TodoGroupKey[] = ['rekordbox_check', 'upgrade_ready', 'not_found', 'weak', 'good_lossy', 'fake', 'other'];
    const LABELS: Record<TodoGroupKey, [string, string]> = {
      rekordbox_check: ['Check in rekordbox', 'the file changed; rekordbox needs a hand'],
      upgrade_ready: ['Upgrade ready', 'a better version is waiting for you'],
      not_found: ['Not found', 'nothing usable anywhere'], weak: ['Weak (≤ 17 kHz)', 'audibly lossy'],
      good_lossy: ['Good lossy (~20 kHz)', 'hard to hear'], fake: ['Fake lossless', 'the Qobuz file is really lossy'],
      other: ['Other', 'something is in the way'],
    };
    const items: Record<TodoGroupKey, TodoItem[]> = Object.fromEntries(order.map((k) => [k, []])) as never;
    const chips = Object.fromEntries(['all', ...order].map((k) => [k, 0])) as Record<TodoFilter, number>;
    const counted = new Set<string>();
    let hidden_count = 0;
    for (const t of s.tracks) {
      if (t.rekordbox_check) {
        items.rekordbox_check.push({ ...trackRow(t), group: 'rekordbox_check', detail: checkText(t.rekordbox_check.reason), free: false });
        chips.rekordbox_check++;
        if (!t.hidden) counted.add(t.track_id);
      }
      const g = t.in_playlists ? todoGroup(t) : null;
      if (!g) continue;
      if (t.hidden) hidden_count++;
      else { chips[g]++; counted.add(t.track_id); }
      if (!t.hidden || show_hidden) items[g].push({ ...trackRow(t), group: g, detail: todoDetail(t, g), free: todoFree(t, g) });
    }
    chips.all = counted.size;
    const groups = order.filter((k) => items[k].length && (filter === 'all' || filter === k))
      .map((k) => ({ key: k, label: LABELS[k][0], hint: LABELS[k][1], items: items[k] }));
    const empty = groups.length ? null : !s.tracks.length ? 'empty_library' as const : filter !== 'all'
      ? 'nothing_here' as const : hidden_count ? 'all_hidden' as const : 'all_lossless' as const;
    return { chips, hidden_count, show_hidden, groups, empty };
  }

  function linesProblem(lines: PlaylistLine[]): string | null {
    if (!Array.isArray(lines)) return 'Something is wrong with the list.';
    const names = new Set<string>();
    for (const l of lines) {
      if (!l.folder?.trim()) return 'Every playlist needs a folder name.';
      // the real rules (config._check_folder, after the name is trimmed)
      const name = l.folder.trim().normalize('NFC');
      if (name.toLowerCase() === 'not_lossless') return `"${name}" is reserved, pick another folder name.`;
      if (/[/\\:]/.test(name)) return 'Folder names cannot contain / \\ or :';
      if (name.startsWith('.')) return 'Folder names cannot start with a dot.';
      if (name.length > 100) return 'The folder name is longer than 100 characters.';
      if (names.has(name.toLowerCase())) return `Two playlists use the folder ${name}.`;
      names.add(name.toLowerCase());
    }
    return null;
  }

  function changePreview(lines: PlaylistLine[]): ChangePreview {
    const checklist = (n: number, moves: boolean) => [n ? `${n} download${n === 1 ? '' : 's'}, counted toward your Qobuz limit`
      : 'No downloads, no Qobuz quota used', 'Nothing is deleted',
    ...(moves ? ['Files move only if you choose to', 'Moves can be undone on this page'] : ['Happens at the next sync, not right away'])];
    const base = { folders: [], tidy: null, renames: [], reroutes: [], new_downloads: 0, days: 0, stopped: 0, unknown: [],
      problem: linesProblem(lines) };
    const old = s.playlists;
    const added = lines.filter((l) => !old.some((o) => o.link === l.link));
    const off = lines.filter((l) => !l.enabled && old.some((o) => o.link === l.link && o.enabled));
    const { renames, moved } = retargets(s, lines);
    const changed = s.tracks.filter((t) => moved.has(t.track_id));
    // as the backend: tracks with a file are on the tidy list, the others only land somewhere else later
    // … except a file that already sits in its new folder
    const rows = changed.filter((t) => hasFile(t) && (t.at ?? t.folder) !== moved.get(t.track_id)!.to).map((t) => tidyRow(s, t, moved.get(t.track_id)!.to, moved.get(t.track_id)!.by));
    const reroutes = changed.filter((t) => !hasFile(t)).map((t) => ({ track_id: t.track_id, artist: t.artist,
      title: t.title, cover_url: trackRow(t).cover_url, downloaded: false, quality: trackRow(t).quality,
      quality_label: trackRow(t).quality_label, never: s.never.includes(t.track_id), from: t.folder,
      to: moved.get(t.track_id)!.to }));
    const offers = renameOffers(s, renames, lines);
    const saveHeadline = rows.length === 1 ? '1 file would sit in a different folder'
      : `${rows.length} files would sit in a different folder`;
    const tidy = rows.length ? { headline: saveHeadline, rows } : null;
    if (changed.length) {
      const fs = [...new Set(changed.flatMap((t) => [moved.get(t.track_id)!.to, t.folder]))];
      const folders = s.playlists.map((p) => p.folder).filter((f) => !fs.includes(f)).map((f) => {
        const n = s.tracks.filter((t) => t.folder === f).length;
        return { folder: f, before: n, after: n };
      });
      const pairs = new Set(changed.map((t) => `${t.folder}\u0000${moved.get(t.track_id)!.to}`));
      // a rename: every song follows its playlist's new name (wherever its file sits)
      const asRename = renames.length > 0
        && changed.every((t) => renames.some(([was, now]) => was === t.folder && now === moved.get(t.track_id)!.to));
      const n = reroutes.length;
      const tracksWill = n === 1 ? '1 track will' : `${n} tracks will`;
      const first = reroutes[0];
      const kind = asRename ? 'rename' : rows.length ? 'moves' : 'reroute';
      const headline = rows.length ? saveHeadline : asRename ? `${tracksWill} go to the new folder name`
        : pairs.size === 1 ? `${tracksWill} go to ${first.to} instead of ${first.from}` : `${tracksWill} go to another folder`;
      return { ...base, kind, headline, tidy, renames: offers, reroutes, checklist: checklist(0, kind !== 'reroute'),
        folders: [...fs.map((f) => {
          const before = s.tracks.filter((t) => t.folder === f).length;
          return { folder: f, before, after: before + changed.filter((t) => moved.get(t.track_id)!.to === f).length
            - changed.filter((t) => t.folder === f).length };
        }), ...folders] };
    }
    if (added.length) {
      const n = added.length * 24;
      const days = Math.max(1, Math.ceil(n / s.qobuz.limit));
      return { ...base, kind: 'add', new_downloads: n, days, checklist: checklist(n, false), renames: offers,
        headline: `${n} new downloads, about ${days} day${days === 1 ? '' : 's'} at the current limit` };
    }
    if (off.length) {
      return { ...base, kind: 'switch_off', headline: 'Files stay, no more updates', checklist: checklist(0, false),
        renames: offers, stopped: s.tracks.filter((t) => off.some((o) => o.folder === t.folder)).length };
    }
    return { ...base, kind: 'none', headline: 'Nothing changes in your library', checklist: checklist(0, false), renames: offers };
  }

  // page overrides (src/pages/*/fake.ts)
  for (const mod of Object.values(pageFakes)) {
    for (const [name, factory] of Object.entries(mod.overrides ?? {})) {
      const k = name as keyof Bridge;
      if (factory && k in h) (h as any)[k] = (factory as any)(ctx, h[k]);
    }
  }

  // methods the engine doesn't answer (s.unanswered): the window gets what client.ts gives for a call that throws
  for (const name of s.unanswered ?? []) {
    const k = name as keyof Bridge;
    if (k in h) (h as any)[k] = async () => fail('crashed', CRASHED_MESSAGE);
  }

  // the library methods answer no_library while no music folder is bound, as the engine's bridge does
  for (const name of LIBRARY_METHODS) {
    const k = name as keyof Bridge;
    const real = (h as any)[k];
    if (typeof real !== 'function') throw new Error(`LIBRARY_METHODS names ${name}, which the fake bridge doesn't have`);
    (h as any)[k] = (...args: unknown[]) => {
      const music = s.setup.music;
      if (music.state === 'ok') return real(...args);
      return Promise.resolve(fail('no_library', music.state === 'missing'
        ? `Your music folder isn't there: ${music.path}. Connect the drive it is on, or choose another folder.`
        : 'Choose your music folder first: it is the first step of Setup.'));
    };
  }

  // scenarios that start with a job already running
  const at = (fn: () => void) => fn();   // at once, so the first job_status() already sees the job
  if (baseScenario === 'syncing') at(() => startReplay(SYNC_START_LINE, { preRun: SYNC_LINES.downloading }));
  if (baseScenario === 'pause') at(() => startReplay(SYNC_START_LINE, { preRun: SYNC_LINES.inPause, freeze: SYNC_LINES.inPause }));
  if (baseScenario === 'break') {
    at(() => {
      startReplay(SYNC_START_LINE, { preRun: SYNC_LINES.sourceBeforePause, freeze: SYNC_LINES.sourceBeforePause });
      job?.record({ type: 'Waiting', kind: 'break', label: 'Longer break to protect your Qobuz account',
        remaining: 690, total: 720, service: 'qobuz' });
    });
  }
  if (baseScenario === 'stopped') {
    at(() => {
      startReplay(SYNC_START_LINE, { events: STREAMS.stopped, preRun: 36 });
      if (job) job.stopping = true;
    });
  }
  if (baseScenario === 'finished') {
    at(() => {
      startReplay(SYNC_START_LINE, { preRun: STREAMS.sync.length });
    });
  }
  Object.defineProperty(h, '_ctx', { value: ctx, enumerable: false });
  return h as Handlers & { _ctx: FakeContext };
}
