// Fake mode only: an object implementing every contract method from an in-memory state (plan 64.8).
import type { Bridge } from '../client';
import type { HubEvent } from '../events';
import type {
  BatchResult, Candidate, ChangePreview, Fail, JobSnap, JobStart, LibraryFilter, LibrarySort, LibraryView, PlaylistInfo, PlaylistLine, ProblemKind, Res, Result,
  AccountCheck, Browser, PlaylistService, SaveFiles, SettingKey, FolderCheck, FolderProblem, QobuzUsage, Service, SignalKind, TodoFilter, TodoGroupKey, TodoItem, Which, SyncEstimate, AiffBatchResult, AiffScope, ItemResult as AiffItemResult, UndoItem } from '../types';
import { LIBRARY_METHODS } from '../contract';
import {
  FAKE_MUSIC, FAKE_NEWEST_YT_DLP, LINK_REFUSED, QOBUZ_UNREADABLE, SOUNDCLOUD_SET_LINK, SERVICE_NAME, SOUNDCLOUD_UNREADABLE, YOUTUBE_MIX_REFUSED, hintOf, playlistRef, serviceOfLink, budget, byQuality, checkStatus, checkView, coverUri, dateOnly, folderList, hash, isoLocal, makeState, nextStep,
  pathOf, previewAction, qualityLabel, qualityLine, qualityOf, result, runDetail, runId,
  readStatus, sampleCandidates, readOk, todoDetail, todoFree, fileFormatLine, sourceFormatLine, sourceHowOf, sourceFull, todoFileState, todoGroup, trackRow, type FakeAccount, type FakeFolder, type FakeState,
  type FakeTrack,
} from './data';
import { BAD_CRATE, BAD_FAVOURITES, BRIEF_WRITE_FAILED, fakeLink, libraryOf, membersOf, mergedFavourites, playlistRows, sidebarOf, trackPlace } from './library';
import { AUTO_BATCH_DETAIL, autoDetail, autoPreview, autoBlock, backupId, markRefused, markWaiting, phaseEvents, phaseResults,
  planPhase, readyTracks, rekordboxStatus, sameTrackReasonOf, stopRows, withPhase, AUTO_REFUSED_WORDS, type PhasePlan } from './auto';
import { LIKED_FOLDER, LIKED_LINK, LIKED_LISTED, LIKED_NEEDS_LOGIN, LIKED_OFF, LIKED_SETTING, isLikedLink, likedOn,
  likedScenarios, likedStatus } from './liked';
import { JobRecord, Replay, STREAMS, SYNC_LINES, SYNC_START_LINE, lineOf, rewrite } from './replay';
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
import { NONE_CHANGEABLE, NOTHING_TO_CHANGE, SKIP_WORDS as AIFF_SKIP_WORDS, applyItem, cdjAiff, cdjMembers, fileAnswer, heldInRekordbox,
  planOf, undoneWords } from './convert';
import { SERVICES, NAMES, RECOMMENDED, serviceOf, limits as limitsOf, whatIf as whatIfOf, gate, syncSplit, cards } from './limits';
import {
  IMPORTING_BUSY, NO_FOLDER, answerSameSong, checkImportFolder, duplicateItems, folderOf, keepDuplicates, questionItems,
  removalPreview, removeFolder, runImport, seedImport, supersedeDuplicate, watchedFolders, type ImportRun,
} from './folders';

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

/** `prepare` (tests): sets data on the state after the scenario did, before the bridge reads it */
export type FakeOptions = { speed?: number; freeze?: number | null; emit?: (e: HubEvent) => void; prepare?: (s: FakeState) => void };
export type FakeContext = {
  s: FakeState;
  speed: number;
  emit(e: HubEvent): void;
  /** starts a write job; `body` calls `finish` when done */
  startJob(kind: string, track_id: string | null, body: (finish: Finish) => void, batch_kind?: JobSnap['batch_kind']): JobStart;
  /** refusal for network reads (sync running, offline), else null */
  networkBlock(): Fail | null;
  fail(kind: ProblemKind, message: string, service?: PlaylistService): Fail;
  later<T>(ms: number, value: () => T): Promise<T>;
  /** a login check's outcome saved / recorded as the engine does it (HubApi._account_result) */
  accountResult(service: 'youtube' | 'soundcloud', browser: Browser, profile: string | null, check: AccountCheck):
    { service: 'youtube' | 'soundcloud'; browser: Browser; profile: string | null; saved: boolean; check: AccountCheck };
};
export type Finish = (ok: boolean, result?: unknown, problem?: ProblemKind | null, message?: string,
  service?: PlaylistService | null) => void;
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
  const out: Record<string, (s: FakeState) => void> = { ...likedScenarios };
  for (const [path, mod] of Object.entries(pageFakes)) {
    const page = path.split('/').at(-2)!;
    for (const [name, fn] of Object.entries(mod.scenarios ?? {})) out[`${page}:${name}`] = fn;
  }
  return out;
}
export const SCENARIOS = ['normal', 'update_available', 'first_run', 'offline', 'console', 'syncing', 'pause', 'break', 'stopped',
  'finished', 'big', 'errors', 'no_music', 'music_missing', 'qobuz_unreadable', 'qobuz_not_connected',
  'soundcloud_unreadable', 'youtube_mix_refused',
  // the import of the user's own music (library stage 4)
  'folders_importing', 'folders_offline', 'folders_missing', 'folders_couldnt_read', 'folders_long_names', 'folders_library_only', 'setup_existing_empty',
  'setup_existing_added', 'todo_same_song', 'todo_duplicates', 'todo_duplicates_three', 'sync_waiting_answers'] as const;

/** The dashboard's estimate has no minutes or uses tables (only the Sync page ticks subsets). */
const dashboardEstimate = ({ minutes_by_downloads: _table, accounts, ...rest }: SyncEstimate) =>
  ({ ...rest, accounts: accounts.map(({ uses_by_downloads: _uses, ...a }) => a) });

export function createFakeBridge(scenario: string, opts: FakeOptions = {}): Handlers & { _ctx: FakeContext } {
  const baseScenario = scenario.includes(':') ? 'normal' : scenario;
  const s = makeState(baseScenario);
  seedTidy(s);
  seedImport(s, baseScenario);
  pageScenarios()[scenario]?.(s);
  opts.prepare?.(s);
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
  let importRun: ImportRun | null = null;     // the import that is running (Stop ends it between two files)

  const emit = (e: HubEvent) => {
    if (job?.running && e.type !== 'ConsoleBusy' && e.type !== 'FileDropped') {
      if (e.type !== 'JobStarted' && e.type !== 'JobFinished') job.record(e);
      else if ((e as { job_id: number }).job_id === job.id) job.record(e);
    }
    emitRaw(e);
  };
  const fail = (kind: ProblemKind, message: string, service?: PlaylistService, setting?: SettingKey): Fail =>
    ({ ok: false, kind, message, ...(service ? { service } : {}), ...(setting ? { setting } : {}) });
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
  /** setup_account / account_sign_in after the check, as HubApi._account_result: saved when ok (also without
   *  Premium or Go+: YouTube's then only reads Liked music); a failed check of the saved login itself (same browser and profile) is recorded on it */
  function accountResult(service: 'youtube' | 'soundcloud', browser: Browser, profile: string | null,
    check: AccountCheck) {
    const saved = check.ok || check.problem === 'no_premium';
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

  function startJob(kind: string, track_id: string | null, body: (finish: Finish) => void, batch_kind: JobSnap['batch_kind'] = null): JobStart {
    if (s.console_running) return fail('console', MSG.console);
    if (job?.running) return fail('busy', job.kind === 'import' ? IMPORTING_BUSY : MSG.busy);
    const id = nextId++;
    job = new JobRecord(id, kind, track_id, isoLocal(new Date()), batch_kind);
    const me = job;
    let finished = false;
    const finish: Finish = (good, res = null, problem = null, message = '', service = null) => {
      if (finished) return;
      finished = true;
      if (s.errors && good && !DOWNLOAD_KINDS.includes(kind) && kind !== 'scan' && !kind.startsWith('setup_')) {
        const [k, m] = ERROR_TURNS[s.errorTurn++ % ERROR_TURNS.length];
        good = false; problem = k; message = m; res = null;
      }
      emit({ type: 'JobFinished', job_id: id, kind, ok: good, problem: good ? null : (problem ?? 'failed'), message,
        result: good ? (res ?? {}) : (problem === 'stopped' || problem === 'rekordbox_open' || problem === 'busy' || problem === 'refused' ? (res ?? null) : null), service } as HubEvent);
      me.running = false;
    };
    setTimeout(() => {
      emit({ type: 'JobStarted', job_id: id, kind, track_id });
      body(finish);
    }, 0);
    return { ok: true, job_id: id };
  }
  const ctx: FakeContext = { s, speed, emit, startJob, networkBlock, fail, later, accountResult };

  /** The import as a write job (kind "import"): `adding` is a folder just watched, `resume`/`hold` start it mid-way and
   *  keep it there until Stop (scenario folders_importing). */
  function beginImport(opts: { adding?: ReturnType<typeof folderOf>; resume?: { phase: 'tags' | 'sound'; done: number };
    hold?: boolean } = {}): JobStart {
    const run: ImportRun = { stopped: false, hold: !!opts.hold };
    return startJob('import', null, (finish) => {
      importRun = run;
      void runImport(ctx, run, (...args) => { importRun = null; finish(...args); }, opts);
    });
  }

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
  // the weekly check of an imported file (a song of the user's own): in no playlist, so the engine names its folder
  // after the folder the file sits in ("Techno"), the way the rest of the app does (views.action_folder)
  const OWN_CHECK = [previewAction('upgrade', 'weekly', { track_id: 'own-techno-1', artist: 'Dub Chord', title: 'Night Drive',
    folder: 'Techno' }, true, '/Volumes/Example Drive/Music/Techno/Dub Chord - Night Drive.mp3', null)];
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
      true, pathOf(t), t.cover)).concat(OWN_CHECK));
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
    duration_s: r.duration_s, exit_code: r.exit_code, counts: r.counts, stopped_after: r.stopped_after,
    auto_upgrade: r.auto_upgrade });
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
  /** The upgrade block's rekordbox answer for a track: the fake library's state decides Same track for other formats. */
  const rbOf = (t: FakeTrack) => {
    const state = s.rekordbox_state ?? 'ready';
    const blocked = state === 'unreadable' && t.upgrade!.swap_how === 'new_aiff';
    return { rekordbox: { state, running: !!s.rekordbox_running },
      ...(blocked ? { swap_possible: false, why_not: 'rekordbox_unreadable' } : {}) };
  };
  // --- Same track batches (issue 33 stage B): the fake keeps its batch records here ---
  /** The engine's words for a skip its full check finds (preview.REASON_WORDS, the ones a fake scenario uses). */
  const SKIP_WORDS: Record<string, string> = {
    timing: "Discjockey couldn't line the new file up with your rekordbox track exactly; analyse the track again in rekordbox and try again",
    not_analysed: "rekordbox hasn't analysed this track yet, so Discjockey can't tell exactly where your cues sit; analyse it in rekordbox, quit rekordbox, and try again",
    changed: 'your rekordbox track changed while Discjockey was working on it; try again',
  };
  /** `kind` / `scope` as `aiff_batches` has them (Same track: `upgrade`; Convert and Rename: `convert`); `left`: the songs
   *  of a selection the plan left out, listed as skipped in every result of the batch */
  type AiffBatch = { id: number; state: 'running' | 'stopped' | 'done'; stop_reason: AiffBatchResult['stop_reason'];
    items: AiffItemResult[]; started_by?: 'user' | 'upgrade_all' | 'auto_upgrade' | 'make_aiff' | 'cdj_all';
    kind: 'upgrade' | 'convert' | 'mixed'; scope: string; left: AiffItemResult[] };
  const aiff: AiffBatch[] = (s.batches ?? []).map((b, i) => ({ id: i + 1, state: b.state, stop_reason: b.state === 'stopped' ? 'stop' as const : null,
    started_by: b.started_by ?? 'user', kind: b.kind, scope: b.scope, left: [],
    items: b.items.map((it) => ({ track: it.track, action: it.action, state: it.state, reason: null, message: null, path: null, rekordbox: null })) }));
  /** the newest stopped batch with items left, as `views.stopped_batch`: only a scope starting with `scope`, only these kinds */
  const stoppedBatch = (scope?: string, kinds?: AiffBatch['kind'][]) => {
    const b = [...aiff].reverse().find((x) => x.state === 'stopped' && x.items.some((i) => i.state === 'planned')
      && (!scope || x.scope.startsWith(scope)) && (!kinds || kinds.includes(x.kind)));
    return b ? { batch_id: b.id, left: b.items.filter((i) => i.state === 'planned').length } : null;
  };
  let batchStop: { stopped: boolean } | null = null;
  const listOf = (ids: unknown): string[] | null => Array.isArray(ids) && ids.length && ids.every((i) => typeof i === 'string' && i)
    ? [...new Set(ids as string[])] : null;
  const itemOf = (t: FakeTrack, action: string, message: string): AiffItemResult => ({ track: t.track_id, action, state: 'done',
    reason: null, message, path: pathOf(t) ?? null, rekordbox: null });
  const batchBody = (id: number | null, state: AiffBatchResult['state'], stop_reason: AiffBatchResult['stop_reason'],
    items: AiffItemResult[], left: AiffItemResult[] = []): AiffBatchResult => {
    const results = [...items, ...left];
    return { batch: id, state, stop_reason, total: results.length, done: results.filter((r) => r.state === 'done').length,
      skipped: results.filter((r) => r.state === 'skipped').length, failed: results.filter((r) => r.state === 'failed').length,
      results, backup: id ? '20261108T120000Z' : null, recovered: [] };
  };
  /** What a replace does to a fake track: the swap/add_new/Same track outcome, with its check and undo record. */
  function apply(t: FakeTrack, mode: 'swap' | 'add_new' | 'same_track', batch: number | null) {
    const measured = t.upgrade!.alignment;
    const old = pathOf(t)!;
    const inPlace = t.upgrade!.swap_how === 'in_place';
    const oldPath = `Superseded/${t.folder}/${mode === 'add_new' ? old.split('/').pop() : inPlace
      ? old.split('/').pop()!.replace(/\.[^.]+$/, ' (lossy)$&') : old.split('/').pop()}`;
    const before = { status: t.status, cutoff_hz: t.cutoff_hz, source: t.source, codec: t.codec, upgrade: t.upgrade,
      rekordbox_check: t.rekordbox_check ? { ...t.rekordbox_check, undo: undefined } : null };
    Object.assign(t, { status: 'lossless', cutoff_hz: null, source: 'qobuz', codec: 'flac', upgrade: null });
    if (mode === 'add_new') {
      t.rekordbox_check = { reason: 'added_as_new', since: dateOnly(new Date()), match: measured.result,
        offset_ms: measured.offset_ms ?? 0, aligned: measured.result === 'exact' || measured.result === 'shifted',
        undo: before, old_path: oldPath };
    } else {
      t.rekordbox_check = { reason: inPlace ? 'swapped' : 'repointed', since: dateOnly(new Date()), match: measured.result,
        offset_ms: measured.offset_ms ?? 0, ...(inPlace ? { moved: false } : { aligned: true }), reload_tag: false,
        rekordbox: s.rekordbox_state === 'none' ? null : { entries: 1, kept: [] }, ...(batch ? { batch } : {}),
        undo: before, old_path: oldPath };
    }
  }
  /** One AIFF batch as a write job. Same track (`upgrade_batch`) is the default; with `plan` it is a Convert / Rename /
   *  Make all batch (`aiff_batch`, stage D): `plan.actions` the items, `plan.scope` the batch's scope, `plan.left` the songs
   *  a selection leaves out, `plan.quick` a batch of one song (rekordbox open before anything ran closes it, no Resume). */
  type AiffRun = { actions: [string, string][]; scope: string; left: AiffItemResult[]; quick: boolean; track_id: string | null };
  function runAiff(started_by: 'user' | 'upgrade_all' | 'make_aiff' | 'cdj_all', ids: string[], resuming: AiffBatch | null = null,
    plan?: AiffRun): JobStart {
    const actions = plan?.actions ?? ids.map((id): [string, string] => [id, 'same_track']);
    const b: AiffBatch = resuming ?? { id: (aiff.at(-1)?.id ?? 0) + 1, state: 'running', stop_reason: null, started_by,
      kind: actions.every(([, a]) => a === 'same_track') ? 'upgrade' : actions.some(([, a]) => a === 'same_track') ? 'mixed' : 'convert',
      scope: plan?.scope ?? (started_by === 'upgrade_all' ? 'todo:upgrade' : 'todo:selection'), left: plan?.left ?? [],
      items: actions.map(([track, action]) => ({ track, action, state: 'planned', reason: null, message: null, path: null,
        rekordbox: null })) };
    if (!resuming) aiff.push(b);
    b.state = 'running'; b.stop_reason = null;
    const quick = plan ? plan.quick : started_by === 'user' && ids.length === 1 && !resuming; // the real upgrade_all never carries a track_id
    const jobKind = resuming ? 'batch_resume' : plan ? 'aiff_batch' : 'upgrade_batch';
    return startJob(jobKind, plan ? plan.track_id : quick ? ids[0] : null, (finish) => {
      const stop = batchStop = { stopped: false };
      const total = b.items.length + b.left.length;
      const left = () => b.items.filter((i) => i.state === 'planned');
      const body = (state: AiffBatch['state'], reason: AiffBatch['stop_reason']) => batchBody(b.id, state, reason, b.items, b.left);
      const end = (state: AiffBatch['state'], reason: AiffBatch['stop_reason'], problem: 'stopped' | 'rekordbox_open' | null,
        message = '') => { b.state = state; b.stop_reason = reason; batchStop = null;
        finish(!problem, body(state, reason), problem, message); };
      const next = () => {
        const item = left()[0];
        if (!item) {
          emit({ type: 'BatchProgress', batch_id: b.id, done: total, total, track_id: null, name: null } as HubEvent);
          if (b.items.every((i) => i.state === 'skipped')) { b.state = 'done'; batchStop = null;
            // one track: the item's own words (as the engine's Refused), else the general sentence
            const only = total === 1 ? b.items[0] : null;
            return finish(false, body('done', null), 'refused',
              (only && (only.message ?? (only.reason ? SKIP_WORDS[only.reason] ?? AIFF_SKIP_WORDS[only.reason] : null)))
              || (b.kind === 'upgrade' ? 'None of these can be upgraded right now.' : NONE_CHANGEABLE)); }
          return end('done', null, null);
        }
        const done = b.items.length - left().length;
        if (stop.stopped) return end('stopped', 'stop', 'stopped', `Stopped after ${done} of ${total}.`);
        const t = track(item.track);
        const converting = item.action !== 'same_track';
        // Same track writes rekordbox only for a new AIFF; Convert and Rename wherever rekordbox holds the file (at the start:
        // any item's file stops the batch, after that the item in work)
        const needsWrite = converting ? !!t && heldInRekordbox(s, t) : !!t?.upgrade && t.upgrade.swap_how === 'new_aiff';
        const blocked = converting ? (done === 0 ? left().some((i) => { const x = track(i.track); return !!x && heldInRekordbox(s, x); }) : needsWrite)
          : needsWrite || done > 0 || !quick;
        if (s.rekordbox_running && blocked) {
          if (quick && done === 0) { item.state = 'skipped'; item.reason = 'rekordbox_open'; }
          return end(quick && done === 0 ? 'done' : 'stopped', quick && done === 0 ? null : 'rekordbox_open', 'rekordbox_open',
            'rekordbox is open. Quit rekordbox, then try again. Discjockey changes your rekordbox tracks only while rekordbox is closed.');
        }
        emit({ type: 'BatchProgress', batch_id: b.id, done, total, track_id: item.track, name: t ? `${t.artist} - ${t.title}` : item.track } as HubEvent);
        setTimeout(() => {
          const late = s.batchSkip?.[item.track];
          if (converting) {
            // the item's answer now: a song that changed under the batch is skipped with the new reason (never switched)
            const r = planOf(s, { kind: 'tracks', tracks: [item.track] }, item.action === 'rename' ? 'rename' : undefined);
            const now = 'plan' in r ? r.plan : null;
            const planned = now?.items[0];
            if (late) Object.assign(item, { state: 'skipped', reason: late, message: AIFF_SKIP_WORDS[late] ?? null });
            else if (!t || !planned) {
              const why = now?.skipped[0];
              Object.assign(item, { state: 'skipped', reason: why?.reason ?? 'file_missing', message: why?.message ?? AIFF_SKIP_WORDS.file_missing });
            } else {
              const did = applyItem(s, t, planned, b.id);
              Object.assign(item, { action: planned.action, state: 'done', message: did.message, path: did.path, rekordbox: did.rekordbox });
            }
          } else if (!t?.upgrade) Object.assign(item, { state: 'skipped', reason: 'no_upgrade' });
          else if (!t.upgrade.swap_safe) Object.assign(item, { state: 'skipped', reason: 'needs_choice' });
          else if (late) Object.assign(item, { state: 'skipped', reason: late, message: SKIP_WORDS[late] ?? null });
          else {
            apply(t, 'same_track', b.id);
            Object.assign(item, { state: 'done', message: 'Upgraded, your cues stayed.', path: pathOf(t) ?? null,
              rekordbox: t.rekordbox_check?.rekordbox ? { entries: ['1'], kept: [] } : null });
          }
          next();
        }, (s.batchStep ?? 700) / speed);
      };
      setTimeout(next, 200 / speed);
    }, resuming ? b.kind : plan ? 'convert' : 'upgrade');   // as the engine's snapshot: a resumed batch keeps its own kind
  }
  /** `convert`, `rename` and `make_aiff` after the plan: a batch of its items, or a refusal that still carries the songs
   *  it left out (a job that ends `refused` with `batch` null). `only` "rename": Rename's answer alone. */
  function aiffJob(scope: AiffScope, only: 'rename' | undefined, started_by: 'user' | 'make_aiff' | 'cdj_all', batchScope: string,
    nothing: string | null): JobStart {
    const r = planOf(s, scope, only);
    if ('refused' in r) return fail('refused', r.refused);
    const plan = r.plan;
    const selected = scope.kind === 'tracks';
    const alone = selected && scope.tracks.length === 1;
    const track_id = alone ? scope.tracks[0] : null;
    const left: AiffItemResult[] = plan.skipped.map((l) => ({ track: l.track, action: 'convert', state: 'skipped', reason: l.reason,
      message: l.message, path: null, rekordbox: null }));
    if (!plan.items.length) {
      const words = nothing ?? (left.length === 1 ? left[0].message! : NONE_CHANGEABLE);
      return startJob('aiff_batch', track_id, (finish) => setTimeout(() => finish(false, batchBody(null, 'done', null, [], left),
        'refused', words), 200 / speed), 'convert');
    }
    return runAiff(started_by, [], null, { actions: plan.items.map((i) => [i.track, i.action]), scope: batchScope, left,
      quick: alone, track_id });
  }
  function runUndo(kind: string, ids: string[], batch: AiffBatch | null): JobStart {
    return startJob(kind, kind === 'undo_upgrade' && ids.length === 1 ? ids[0] : null, (finish) => setTimeout(() => {
      const results: UndoItem[] = [];
      const needs = ids.some((id) => track(id)?.rekordbox_check?.reason === 'repointed' && track(id)?.rekordbox_check?.rekordbox);
      const body = () => ({ batch: batch?.id ?? null, total: ids.length, undone: results.filter((r) => r.state === 'undone').length,
        refused: results.filter((r) => r.state === 'refused').length, failed: 0, results, recovered: [] as [string, boolean][] });
      if (s.rekordbox_running && needs) {
        for (const id of ids) results.push({ track: id, state: 'waiting', reason: 'rekordbox_open', message: 'Not undone yet. Nothing was changed.' });
        return finish(false, body(), 'rekordbox_open', 'Quit rekordbox to undo: Discjockey points your rekordbox track back at your old file only while rekordbox is closed.');
      }
      const undone: (string | undefined)[] = [];   // the checks' reasons of the tracks put back (views.undone_words)
      for (const id of ids) {
        const t = track(id);
        const before = t?.rekordbox_check?.undo;
        const refuse = s.undoRefuse?.[id];
        if (refuse) { results.push({ track: id, state: 'refused', reason: 'changed', message: refuse }); continue; }
        if (!t || !before || t.upgrade) {
          results.push({ track: id, state: 'refused', reason: null, message: 'There is no upgrade to undo for this track.' });
          continue;
        }
        const was = t.rekordbox_check?.reason;
        Object.assign(t, before);
        undone.push(was);
        results.push({ track: id, state: 'undone', reason: null, message: 'the old file is back; the new version waits again' });
        const item = aiff.flatMap((x) => x.items).filter((i) => i.track === id && i.state === 'done').at(-1);
        if (item) item.state = 'undone';
      }
      if (ids.length && !results.some((r) => r.state === 'undone')) {
        return finish(false, body(), 'refused', ids.length === 1 ? results[0].message : 'None of these could be undone.');
      }
      finish(true, { ...body(), words: undoneWords(undone) });
    }, 600 / speed));
  }
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

  /** The recorded sync with Auto-upgrade's last phase before its end (nothing extra when the switch is off). */
  function autoSync(): { events?: HubEvent[]; phase?: PhasePlan; phaseFrom?: number } {
    const phase = planPhase(s, (aiff.at(-1)?.id ?? 0) + 1);
    if (!phase) return {};
    const { events, at } = withPhase(STREAMS.sync, phaseEvents(phase));
    return { events, phase, phaseFrom: at };
  }
  function startReplay(from: number, opts2: { events?: HubEvent[]; crashAfter?: number | null; freeze?: number | null;
    preRun?: number; phase?: PhasePlan | null; phaseFrom?: number | null } = {}): JobStart {
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
    const rp: Replay = new Replay({ events, from: opts2.preRun ? opts2.preRun + 1 : from, jobId: id, speed,
      freeze: opts2.freeze ?? opts.freeze ?? null, reportPath: path, emit, crashAfter: opts2.crashAfter ?? null,
      phaseFrom: opts2.phaseFrom ?? null,
      onDone: () => { me.running = false; me.stopping = false; replay = null; afterSync(rid, me, opts2.phase ?? null, rp.phaseReached); } });
    replay = rp;
    rp.start();
    return { ok: true, job_id: id };
  }
  /** After a replayed sync: its run is in the reports, and the plan is worked out again from the sync's own read
   *  and what the run left (like jobs.preview_after_run, issue 20), so what the run did is not offered again. */
  function afterSync(rid: string, rec: JobRecord, plan: PhasePlan | null = null, phaseReached = false) {
    const results = rec.results.map((e) => e.result as Result);
    const done = new Set(results.filter((r) => r.track_id && r.section !== 'queued' && r.section !== 'errors')
      .map((r) => r.track_id));
    s.read_status = { ...s.read_status, stale: false, read_at: rec.started, minutes_ago: 0 };
    s.newTracks = s.newTracks.filter((t) => t.track_id === 't5' || !done.has(t.track_id));
    const run = rec.last.RunFinished;
    if (!run) return;
    const started = new Date(rec.started);
    const stopped = run.exit_code === 130 ? results.length : null;   // before the phase's rows join the results
    const phase = endPhase(rec, plan, phaseReached, started);
    if (phase) {
      // the sync's own check parked these a moment ago (`upgrade_ready`); the phase's row replaces it (auto_upgrade._file)
      const filed = new Set(phase.results.map((r) => r.track_id));
      results.splice(0, results.length, ...results.filter((r) => !(r.section === 'upgrade_ready' && filed.has(r.track_id))), ...phase.results);
    }
    s.runs.unshift(runDetail(rid, started, Math.round((Date.now() - started.getTime()) / 1000), run.exit_code,
      results, stopped, s.tracks.filter((t) => t.upgrade).length, phase?.block ?? null));
    const t5 = s.newTracks.find((t) => t.track_id === 't5');
    if (t5 && results.some((r) => r.track_id === 't5' && r.section === 'new_not_lossless')) {
      s.newTracks = s.newTracks.filter((t) => t.track_id !== 't5');
      s.tracks.push({ ...t5, status: 'not_lossless', cutoff_hz: 20000, source: 'youtube_music', codec: 'aac',
        in_playlists: true, hidden: false, added: isoLocal(new Date()), cover: 2, isrc: null, playlists: [t5.folder],
        upgrade: null, rekordbox_check: null, other: null, next_try_days: null, rejected_sources: [] });
    }
  }

  /** The sync's last phase, done when the sync ends (the fake works its outcome out at the start, `planPhase`): the upgrades
   *  go in as one batch (`apply`, the batch record "started by the sync"), the tracks that waited or were refused get their
   *  marks, and the rows join the run's results and block. A Stop in the phase ends the batch: the rest were not reached.
   *  Null: the switch was off, or the run never got to the phase (Stop or a crash came first). */
  function endPhase(rec: JobRecord, plan: PhasePlan | null, reached: boolean, started: Date) {
    if (!plan || !reached) return null;
    const stopped = rec.last.RunFinished?.exit_code === 130;
    const progress = rec.last.BatchProgress as Extract<HubEvent, { type: 'BatchProgress' }> | undefined;
    // the track in work when Stop came finishes; the batch had not begun without a first BatchProgress
    const handled = Math.min(plan.order.length, progress ? progress.done + (progress.track_id ? 1 : 0) : 0);
    const rows = stopped && plan.batch !== null ? stopRows(plan, handled) : plan.rows;
    const byId = new Map(rows.map((r) => [r.track, r]));
    if (plan.batch !== null) {
      const items: AiffBatch['items'] = plan.order.map((id) => {
        const r = byId.get(id)!;
        return { track: id, action: 'same_track', state: r.state === 'done' ? 'done' : 'skipped', reason: r.state === 'done' ? null : r.reason,
          message: r.message, path: null, rekordbox: null };
      });
      const atRekordbox = rows.some((r) => r.reason === 'rekordbox_open');
      // batches.end_auto closes the batch `done` whatever cut it short, with no stop reason: To-do never offers Resume
      aiff.push({ id: plan.batch, state: 'done', stop_reason: null, started_by: 'auto_upgrade', kind: 'upgrade', scope: 'sync', left: [], items });
      if (atRekordbox) s.rekordbox_running = true;   // it was opened mid-phase and is still open
    }
    for (const r of rows) {
      const t = track(r.track);
      if (!t?.upgrade) continue;
      if (r.state === 'done') {
        apply(t, 'same_track', plan.batch);
        const item = aiff.find((b) => b.id === plan.batch)?.items.find((i) => i.track === r.track);
        if (item) item.path = pathOf(t) ?? null;
        continue;
      }
      t.upgrade.auto_refused = null; t.upgrade.auto_waits = false;   // tried now: what was recorded before is out of date
      if (r.state === 'refused' && r.reason && r.reason in AUTO_REFUSED_WORDS) markRefused(s, t, r.reason as keyof typeof AUTO_REFUSED_WORDS);
      if (r.state === 'waiting' && r.reason === 'rekordbox_open') markWaiting(t);
    }
    // the way a batch leaves its tracks: no Resume is offered for it (nothing stays planned)
    return { results: phaseResults(rows, track), block: autoBlock(plan, rows, stopped && plan.batch !== null, plan.batch === null ? null : backupId(started)) };
  }

  // ---------- the contract ----------
  // add_playlist's answer for a pasted link; what it finds is kept (`found`), as the engine keeps each read's info
  // (hub/api.py `_infos`), so a playlist saved right after it lists with its name, owner and tracks, not "not read yet"
  const found = new Map<string, PlaylistInfo>();
  async function findPlaylist(url: string) {
    const block = networkBlock();
    if (block) return block;
    const q = /open\.qobuz\.com\/playlist\/(\d+)/.exec(url ?? '');
    if (q) {
      if (s.qobuzNotConnected) {
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
    // a short link or "you/likes" is expanded first (the real engine: sources.expand); here to the sample set / likes
    const pasted = (url ?? '').trim().replace(/^https?:\/\/on\.soundcloud\.com\/\w+\/?$/i, SOUNDCLOUD_SET_LINK)
      .replace(/^(https?:\/\/(?:www\.)?soundcloud\.com\/)you\/likes\/?$/i, '$1example-dj/likes');
    const sc = /^https?:\/\/(?:www\.)?soundcloud\.com\/([\w-]+(?:\/(?:sets\/[\w-]+(?:\/s-\w+)?|likes))?)\/?$/i.exec(pasted);
    if (sc) {
      if (s.soundcloudUnreadable) return later(700, () => fail('playlist_unreadable', SOUNDCLOUD_UNREADABLE, 'soundcloud'));
      const link = `https://soundcloud.com/${sc[1].toLowerCase()}`;
      const likes = /\/likes$/.test(link);
      const name = likes ? "Example DJ's likes" : 'Example Set';
      return later(700, () => ok({ playlist_id: playlistRef(link)!, service: 'soundcloud' as const,
        service_name: 'SoundCloud', link,
        info: { name, owner_name: likes ? '' : 'Example Label', yours: false, collaborative: false,
          readable: true, image_url: null, track_count: likes ? null : 12, hint: hintOf('soundcloud') },
        tracks: 12, readable: true, suggested_folder: name.replace(/\W+/g, '_'), hint: null }));
    }
    const yt = /^https?:\/\/(?:music\.|www\.|m\.)?youtube\.com\/(?:playlist|watch)\?(?:[^#]*&)?list=([\w-]+)/i.exec((url ?? '').trim());
    if (yt && isLikedLink(url ?? '')) {
      // Liked music signs in, so it is a choice in Settings (the engine decides before any request)
      if (!likedOn(s)) return fail('setting_off', LIKED_OFF, 'youtube_music', LIKED_SETTING);
      return later(700, () => ok({ playlist_id: 'youtube_music:LM', service: 'youtube_music' as const,
        service_name: 'YouTube Music', link: LIKED_LINK,
        info: { name: 'Liked music', owner_name: 'You', yours: true, collaborative: false, readable: true,
          image_url: null, track_count: 312, hint: hintOf('youtube_music') },
        tracks: 312, readable: true, suggested_folder: LIKED_FOLDER, hint: null }));
    }
    if (yt) {
      if (s.youtubeMixRefused || /^RD(?!CLAK5uy_)/.test(yt[1])) {
        return fail('playlist_unreadable', YOUTUBE_MIX_REFUSED, 'youtube_music');
      }
      const link = `https://music.youtube.com/playlist?list=${yt[1]}`;
      return later(700, () => ok({ playlist_id: `youtube_music:${yt[1]}`, service: 'youtube_music' as const,
        service_name: 'YouTube Music', link,
        info: { name: 'Example Warm-up', owner_name: 'Example Channel', yours: false, collaborative: false,
          readable: true, image_url: null, track_count: 20, hint: hintOf('youtube_music') },
        tracks: 20, readable: true, suggested_folder: 'Example_Warm_up', hint: null }));
    }
    const m = /open\.spotify\.com\/playlist\/([A-Za-z0-9]+)/.exec(url ?? '');
    if (!m) return fail('refused', LINK_REFUSED);
    const id = m[1];
    const readable = !/private|follow/i.test(id);
    const name = `Name of ${id.slice(0, 4)}`;
    const link = `https://open.spotify.com/playlist/${id}`;
    return later(700, () => ok({ playlist_id: playlistRef(link) ?? id, service: serviceOfLink(link),
      service_name: SERVICE_NAME[serviceOfLink(link)], link,
      info: { name, owner_name: readable ? 'DJ One' : 'Someone else', yours: readable, collaborative: false, readable,
        image_url: null, track_count: readable ? 24 : 0, hint: hintOf('spotify') }, tracks: readable ? 24 : 0, readable,
      suggested_folder: name.replace(/\W+/g, '_'), hint: readable ? null : hintOf('spotify') }));
  }

  const h: Handlers = {
    async dashboard() {
      const inPl = s.tracks.filter((t) => t.in_playlists);
      const lossless = inPl.filter((t) => qualityOf(t) === 'lossless').length;
      const p = preview();
      const hour = new Date().getHours();
      return ok({
        greeting: hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening',
        read_status: readStatus(s),
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
      return ok(sidebarOf(s, todoView('all', false).chips.all, cards(s).some((c) => c.new_warnings > 0 || c.paused)));
    },
    async sync_preview() {
      const p = preview();
      if (!s.previewRead) return ok({ read_status: readStatus(s), counts: null, groups: [], estimate: null, never: [],
        folders: [], in_playlists: null, ambiguous: [], dropped: [], notes: [], waiting_answers: 0, deferred_checks: 0,
        empty: 'no_preview' as const, collections: {}, auto_upgrade: null });  // like views.sync_preview: never not_set_up
      // each row's collections, as views._members gives them (issue 37)
      const m = membersOf(s, sidebarOf(s, 0, false));
      for (const a of [...p.groups.flatMap((g) => g.actions), ...p.never]) a.in = m.of(a);
      return ok({ read_status: readStatus(s), counts: p.counts, groups: p.groups, estimate: p.estimate, never: p.never,
        collections: m.names,
        folders: p.folders, in_playlists: p.in_playlists, ambiguous: [], dropped: [], notes: [],
        waiting_answers: s.imp.questions.length, deferred_checks: s.imp.deferred,
        auto_upgrade: autoPreview(s, autoReady()),
        empty: p.actions ? null : 'up_to_date' as const });
    },
    async refresh(auto = false) {
      if (auto && s.read_status.auto_read) {
        return fail('refused', 'Spotify was read by itself once this session already. Use ↻ Read Spotify to read it again.');
      }
      if (job?.running && job.kind === 'sync') return fail('busy', 'Not while a sync runs.');
      if (refreshJob) return fail('busy', 'Spotify is being read already.');
      // only a service playlists.txt uses must be logged in (plan stage 3, D1)
      const off = readStatus(s).services.find((x) => !x.connected);
      if (off) return fail('not_set_up', `Connect ${off.name} first.`, off.service);
      const id = nextId++;
      s.read_status = { ...s.read_status, reading: true, auto_read: s.read_status.auto_read || auto };
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
          s.read_status = { ...s.read_status, reading: false };
          emit({ type: 'JobFinished', job_id: id, kind: 'refresh', ok: false, problem: 'offline', message: MSG.offline,
            result: null, service: null });
          return;
        }
        s.read_status = { ...readOk(0), auto_read: s.read_status.auto_read }; s.previewRead = true;
        emit({ type: 'JobFinished', job_id: id, kind: 'refresh', ok: true, problem: null, message: '',
          result: { actions: preview().actions }, service: null });
      }, 2500 / speed) };
      return ok({ job_id: id });
    },
    async stop_refresh() {
      if (!refreshJob) return ok({ stopped: false });
      clearTimeout(refreshJob.timer);
      const id = refreshJob.id;
      refreshJob = null;
      s.read_status = { ...s.read_status, reading: false };
      emit({ type: 'JobFinished', job_id: id, kind: 'refresh', ok: false, problem: 'stopped',
        message: 'Stopped. The last read stays.', result: null, service: null });
      return ok({ stopped: true });
    },
    async job_status() {
      return ok({ job: job ? job.snapshot() : null, refresh_running: !!refreshJob, console_running: s.console_running,
        read_status: readStatus(s), sign_in: signIn ? signIn.snapshot() : null });
    },
    async library(view: LibraryView, key: string | null, query: string, filter: LibraryFilter, sort: LibrarySort | null) {
      const r = libraryOf(s, view, key, query, filter, sort);
      return 'refused' in r ? fail('refused', r.refused) : ok({ ...r, aiff_stopped: stoppedBatch('library:') });
    },
    async track(track_id: string) {
      const t = track(track_id);
      if (!t) return fail('refused', 'This track is not in your library any more.');
      const q = qualityOf(t);
      const plus = (n: number) => { const d = new Date(); d.setDate(d.getDate() + n); return dateOnly(d); };
      const query = `${t.artist} ${t.title}`.replace(/ /g, '+');
      const link = fakeLink(t);
      // the engine drops the source's link when it is the song's own page (a YouTube Music playlist's own upload)
      const sourceUrl = t.source === 'youtube' ? 'https://www.youtube.com/watch?v=abcdefghijk'
        : t.source === 'youtube_music' ? (t.how === 'upload' ? link.url : 'https://music.youtube.com/watch?v=abcdefghijk')
          : t.source === 'soundcloud' ? null   // as the engine: a SoundCloud id is a number, no page link
            : t.source === 'qobuz' ? 'https://open.qobuz.com/track/112233' : null;
      return ok({ track: {
        ...trackRow(t), sound_checked: !t.unchecked, file_state: t.away ?? 'here', place: trackPlace(s, t), isrc: t.isrc,
        playlists: s.previewRead ? [...t.playlists] : null,
        in_playlist_count: t.playlists.length, quality_line: qualityLine(t), format_line: fileFormatLine(t),
        source_format_line: sourceFormatLine(t), source_how: sourceHowOf(t),
        source_full: q === 'missing' ? null : sourceFull(t),
        source_url: sourceUrl === link.url ? null : sourceUrl,
        track_link: link,
        next_qobuz_check: q === 'lossless' ? null : q === 'missing' ? (t.next_try_days === 1 ? 'next_sync'
          : plus(t.next_try_days ?? 5)) : plus(4),
        rejected_sources: [...t.rejected_sources],
        buy_links: { beatport: `https://www.beatport.com/search?q=${query}`, bandcamp: `https://bandcamp.com/search?q=${query}` },
        free_downloads: q === 'lossless' ? [] : [...(t.free_downloads ?? [])],
        bought_name: `Library/${t.folder}/${t.artist} - ${t.title}.wav`,
        audio_url: q === 'missing' || t.away ? null : media(t, 'current'),
        upgrade: t.upgrade ? { ...t.upgrade, audio_url: media(t, 'upgrade'), ...rbOf(t) } : null,
        aiff: fileAnswer(s, t),
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
      if (t.away) return fail('refused', "This file isn't there.");
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
      const imports = s.imp.folders.filter((f) => f.kind === 'import').length;
      return ok({ ...s.setup, music: { ...s.setup.music }, tools: { ...s.setup.tools }, qobuz_skipped: s.qobuzSkipped,
        existing: imports > 0 || s.imp.skipped, import_folders: imports, import_skipped: s.imp.skipped,
        qobuz_last_check: s.qobuzLastCheck ?? null,
        spotify_user: s.setup.spotify_login ? s.spotifyUser ?? 'DJ One' : null,
        accounts: { youtube: status(s.accounts.youtube), soundcloud: status(s.accounts.soundcloud) },
        youtube_music: likedStatus(s) });
    },
    async select(track_id: string | null) { s.selected = track_id; return ok({}); },
    async rekordbox_status() { return ok(rekordboxStatus(s)); },
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
          result: good ? result : null, service: null } as HubEvent);
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
      const r = await findPlaylist(url);
      if (r.ok) found.set(r.link, r.info);
      return r;
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
      if (s.syncNeedsQobuz) {
        // a Qobuz line, no Qobuz login: the sync is refused at its start and says which service (JobFinished.service)
        return startJob('sync', null, (finish) => setTimeout(() => finish(false, null, 'not_set_up',
          'Connect Qobuz first.', 'qobuz'), 600 / speed));
      }
      if (!selected.length) {
        return startJob('sync', null, (finish) => setTimeout(() => finish(true, { exit_code: 0, report: '',
          actions: 0, new_since_preview: 0 }), 300 / speed));
      }
      return startReplay(SYNC_START_LINE, autoSync());
    },
    async stop() {
      if (importRun && job?.running) { job.stopping = true; importRun.stopped = true; return ok({ stopped: true }); }
      if (batchStop && job?.running) { job.stopping = true; batchStop.stopped = true; return ok({ stopped: true }); }
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
            info: old.get(l.link)?.info ?? found.get(l.link) ?? null }));
          for (const t of s.tracks) t.playlists = t.playlists.map((f) => renames.find(([was]) => was === f)?.[1] ?? f);
          s.version++;
          // as the real setup_status, which reads playlists.txt: a saved list counts as "playlists added"
          s.setup = { ...s.setup, playlists: s.playlists.length > 0 };
          s.read_status = { ...s.read_status, stale: true };
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
    async watched_folders() { return ok(watchedFolders(s)); },
    async check_import_folder(path: string) { return ok(checkImportFolder(s, path)); },
    async removal_preview(folder_id: number) {
      const r = removalPreview(s, folder_id);
      return 'ok' in r ? r : ok(r);
    },
    async add_watched_folder(path: string) {
      const c = checkImportFolder(s, path);
      if (!c.usable) return fail('refused', c.message ?? '');
      const folder: FakeFolder = { id: s.imp.nextId++, path: c.path, kind: 'import', offline: false, imported: 0, waiting: 0,
        redownload: 0 };
      s.imp.folders.push(folder);
      const started = beginImport({ adding: folder });
      if (!started.ok) {
        s.imp.folders = s.imp.folders.filter((f) => f !== folder);
        return started;
      }
      s.imp.stopped = false;
      // the watched folders inside it become part of it, with their files
      for (const inner of s.imp.folders.filter((f) => f.kind === 'import' && c.merges.includes(f.path))) {
        folder.imported += inner.imported; folder.waiting += inner.waiting; folder.redownload += inner.redownload;
        s.imp.unreadable = s.imp.unreadable.map((u) => (u.folder_id === inner.id ? { ...u, folder_id: folder.id } : u));
        s.imp.folders = s.imp.folders.filter((f) => f !== inner);
      }
      return started;
    },
    async start_import() {
      const started = beginImport();
      if (started.ok) s.imp.stopped = false;
      return started;
    },
    async remove_watched_folder(folder_id: number) {
      const f = folderOf(s, folder_id);
      if (!f) return fail('refused', NO_FOLDER);
      return startJob('folders', null, (finish) => setTimeout(() => finish(true, removeFolder(s, f)), 400 / speed));
    },
    async answer_same_song(song_key: string, own_key: string, same: boolean) {
      return answerSameSong(ctx, song_key, own_key, same);
    },
    async keep_duplicates(group_id: string, paths: string[]) { return keepDuplicates(ctx, group_id, paths); },
    async supersede_duplicate(group_id: string, file_id: number, paths: string[]) {
      return supersedeDuplicate(ctx, group_id, file_id, paths);
    },
    async setup_skip_import() {
      if (s.console_running) return fail('console', MSG.console);
      if (job?.running) return fail('busy', job.kind === 'import' ? IMPORTING_BUSY : MSG.busy);
      s.imp.skipped = true;
      return ok({});
    },
    // brief saves (D15): no job and no engine lock; they answer at once, or `busy` when library.db is held (a hook)
    async set_favourites(keys: string[]) {
      if (!Array.isArray(keys) || !keys.every((k) => typeof k === 'string' && /^(playlist|folder):/.test(k))) {
        return fail('refused', BAD_FAVOURITES);
      }
      if (s.briefBusy) return fail('busy', BRIEF_WRITE_FAILED);
      const resolving = new Set(sidebarOf({ ...s, favourites: [...s.favourites, ...keys] }, 0, false).favourites.map((f) => f.key));
      s.favourites = mergedFavourites(s.favourites, keys, resolving);
      return ok({ favourites: [...s.favourites] });
    },
    async set_crates_shown(paths: string[], shown: boolean | null) {
      if (!Array.isArray(paths) || !paths.length || !paths.every((p) => typeof p === 'string' && p)
        || !(shown === null || typeof shown === 'boolean')) return fail('refused', BAD_CRATE);
      if (s.briefBusy) return fail('busy', BRIEF_WRITE_FAILED);
      const wanted = [...new Set(paths)];
      for (const p of wanted) { if (shown === null) delete s.crateShown[p]; else s.crateShown[p] = shown; }
      return ok({ paths: wanted, shown });
    },
    async set_crate_shown(path: string, shown: boolean | null) {
      if (typeof path !== 'string' || !path || !(shown === null || typeof shown === 'boolean')) return fail('refused', BAD_CRATE);
      if (s.briefBusy) return fail('busy', BRIEF_WRITE_FAILED);
      if (shown === null) delete s.crateShown[path]; else s.crateShown[path] = shown;
      return ok({ path, shown });
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
    async rekordbox_checked(track_ids: string[]) {
      const ids = listOf(track_ids);
      if (!ids) return fail('refused', 'No tracks were chosen.');
      const have = ids.filter((id) => track(id)?.rekordbox_check);
      // like the engine: nothing to check is a job that ends `changed`, not a refusal at the call
      if (!have.length) return startJob('rekordbox_checked', ids.length === 1 ? ids[0] : null, (finish) => setTimeout(() =>
        finish(false, null, 'changed', 'There is nothing to check for these tracks any more.'), 300 / speed));
      return startJob('rekordbox_checked', ids.length === 1 ? ids[0] : null, (finish) => setTimeout(() => {
        const results = have.map((id) => { const t = track(id)!; t.rekordbox_check = null;
          return opResult(t, 'rekordbox_checked', 'checked in rekordbox').result; });
        for (const b of aiff) if (b.state === 'stopped' && !b.items.some((i) => i.state === 'planned')) b.state = 'done';
        finish(true, { results, checked: have, not_checked: ids.filter((id) => !have.includes(id)), recovered: [] });
      }, 300 / speed));
    },
    async upgrade(track_ids: string[], mode: 'swap' | 'add_new' | 'discard') {
      const ids = listOf(track_ids);
      if (!ids) return fail('refused', 'No tracks were chosen.');
      if (!['swap', 'add_new', 'discard'].includes(mode)) return fail('refused', 'Pick swap, add as new or discard.');
      if (mode === 'swap') return runAiff('user', ids);
      return startJob(`upgrade_${mode}`, ids.length === 1 ? ids[0] : null, (finish) => {
        const results: AiffItemResult[] = [];
        const stop = batchStop = { stopped: false };
        let n = 0;
        const next = () => {
          if (stop.stopped && n < ids.length) {
            // Stop between tracks: the rest is planned, as the engine's _each_work ends it
            batchStop = null;
            for (const id of ids.slice(n)) results.push({ track: id, action: mode, state: 'planned', reason: null, message: null,
              path: null, rekordbox: null });
            return finish(false, batchBody(null, 'stopped', 'stop', results), 'stopped', `Stopped after ${n} of ${ids.length}.`);
          }
          if (n >= ids.length) {
            batchStop = null;
            emit({ type: 'BatchProgress', batch_id: 0, done: ids.length, total: ids.length, track_id: null, name: null } as HubEvent);
            return finish(true, batchBody(null, 'done', null, results));
          }
          const t = track(ids[n++]);
          if (!t?.upgrade) results.push({ track: ids[n - 1], action: mode, state: 'skipped', reason: 'no_upgrade', message: null,
            path: null, rekordbox: null });
          else {
            emit({ type: 'BatchProgress', batch_id: 0, done: n - 1, total: ids.length, track_id: t.track_id, name: `${t.artist} - ${t.title}` } as HubEvent);
            if (mode === 'discard') { t.upgrade = null; results.push(itemOf(t, mode, 'upgrade discarded')); }
            else { apply(t, 'add_new', null); results.push(itemOf(t, mode, 'added as a new file, the old one is in Superseded')); }
          }
          setTimeout(next, 500 / speed);
        };
        setTimeout(next, 300 / speed);
      }, 'upgrade');
    },
    async upgrade_all() {
      const ids = s.tracks.filter((t) => t.in_playlists && !t.hidden && t.upgrade && sameTrackReason(t) === null).map((t) => t.track_id);
      if (!ids.length) return fail('refused', 'None of these can be upgraded right now.');
      return runAiff('upgrade_all', ids);
    },
    async aiff_plan(scope: AiffScope) {
      const r = planOf(s, scope);
      return 'refused' in r ? fail('refused', r.refused) : ok({ plan: r.plan });
    },
    async convert(track_ids: string[], origin: 'library' | 'todo' = 'library') {
      const ids = listOf(track_ids);
      if (!ids) return fail('refused', 'No tracks were chosen.');
      if (origin !== 'library' && origin !== 'todo') return fail('refused', 'origin must be one of library, todo');
      return aiffJob({ kind: 'tracks', tracks: ids }, undefined, 'user', `${origin}:selection`, null);
    },
    async rename(track_ids: string[]) {
      const ids = listOf(track_ids);
      if (!ids) return fail('refused', 'No tracks were chosen.');
      return aiffJob({ kind: 'tracks', tracks: ids }, 'rename', 'user', 'library:selection', null);
    },
    async make_aiff(scope: Extract<AiffScope, { kind: 'lossless' | 'cdj' }>) {
      if (!scope || (scope.kind !== 'lossless' && scope.kind !== 'cdj')) return fail('refused', 'scope kind must be one of lossless, cdj');
      if (scope.kind === 'cdj') return aiffJob(scope, undefined, 'cdj_all', 'todo:cdj', NOTHING_TO_CHANGE);
      const where = [scope.view, scope.key].filter(Boolean).join(':');
      return aiffJob(scope, undefined, 'make_aiff', `library:${where}`, NOTHING_TO_CHANGE);
    },
    async batch_resume(batch_id: number) {
      const b = aiff.find((x) => x.id === batch_id);
      if (!b) return fail('refused', 'Discjockey has no record of this batch.');
      if (b.state !== 'stopped') return fail('refused', 'This batch is not stopped, so there is nothing to resume.');
      return runAiff('user', [], b);
    },
    async batch_undo(batch_id: number) {
      const b = aiff.find((x) => x.id === batch_id);
      if (!b) return fail('refused', 'Discjockey has no record of this batch.');
      return runUndo('batch_undo', b.items.filter((i) => i.state === 'done').map((i) => i.track).reverse(), b);
    },

    async undo_upgrade(track_ids: string[]) {
      const ids = listOf(track_ids);
      if (!ids) return fail('refused', 'No tracks were chosen.');
      return runUndo('undo_upgrade', ids, null);
    },

    async show_in_finder() { return ok({}); },
    // api.reveal: a place inside the music folder, or an absolute path at or inside a watched import folder
    async reveal(rel_path: string) {
      const inWatched = (p: string) => s.imp.folders.some((f) => p === f.path || p.startsWith(`${f.path}/`));
      if (typeof rel_path !== 'string' || rel_path.split('/').includes('..') || (rel_path.startsWith('/') && !inWatched(rel_path))) {
        return fail('refused', 'Discjockey only opens places inside your music folder or a folder it watches.');
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
          s.read_status = { ...readOk(0), auto_read: s.read_status.auto_read };
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
    async set_read_liked_music(on: boolean) {
      if (typeof on !== 'boolean') return fail('refused', 'on must be true or false.');
      return startJob('set_read_liked_music', null, (finish) => setTimeout(() => {
        if (on && !s.accounts.youtube) return finish(false, null, 'not_set_up', LIKED_NEEDS_LOGIN);
        s.likedMusic = on;  // turning it off never touches playlists.txt
        finish(true, {});
      }, 300 / speed));
    },
    async set_auto_upgrade(on: boolean) {
      if (typeof on !== 'boolean') return fail('refused', 'on must be true or false.');
      return startJob('set_auto_upgrade', null, (finish) => setTimeout(() => {
        s.setup = { ...s.setup, auto_upgrade: on };   // turning it off touches nothing that waits
        finish(true, {});
      }, 300 / speed));
    },
    async add_liked_music() {
      return startJob('add_liked_music', null, (finish) => setTimeout(() => {
        if (!likedOn(s)) return finish(false, null, 'setting_off', LIKED_OFF);
        if (s.playlists.some((p) => isLikedLink(p.link))) return finish(false, null, 'exists', LIKED_LISTED);
        let folder = LIKED_FOLDER;
        for (let n = 2; s.playlists.some((p) => p.folder.toLowerCase() === folder.toLowerCase()); n++) folder = `${LIKED_FOLDER}_${n}`;
        s.playlists = [...s.playlists, { folder, link: LIKED_LINK, enabled: true,
          info: { name: 'Liked music', owner_name: 'You', yours: true, collaborative: false, readable: true,
            image_url: null, track_count: 312, hint: hintOf('youtube_music') } }];
        s.version++;
        s.setup = { ...s.setup, playlists: true };
        s.read_status = { ...s.read_status, stale: true };
        finish(true, { folder });
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
        if (service === 'youtube') s.likedMusic = false;  // nothing to read it with; signing in again doesn't resume
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

  /** views.same_track_reason for a fake track: null when Same track can run now. */
  function sameTrackReason(t: FakeTrack): string | null { return sameTrackReasonOf(s, t); }
  /** the CDJ group's `all` (Convert all can do n now, k wait: the `cdj` plan's total and waiting) and its stopped batch */
  function cdjAll() {
    const r = planOf(s, { kind: 'cdj' });
    const plan = 'plan' in r ? r.plan : null;
    return { all: { n: plan?.total ?? 0, k: plan?.waiting.reduce((n, w) => n + w.n, 0) ?? 0 }, stopped: stoppedBatch('todo:') };
  }
  function upgradeAll(rows: TodoItem[]) {
    const mine = rows.filter((r) => !r.hidden);
    const stopped = stoppedBatch(undefined, ['upgrade']);
    return { all: { n: mine.filter((r) => r.same_track === null).length, m: mine.filter((r) => r.same_track === 'needs_choice').length,
      k: mine.filter((r) => r.same_track && r.same_track !== 'needs_choice').length },
      stopped };
  }

  /** The upgrades the sync's last phase would put in place now (views/api `_auto_upgrade_ready`): Upgrade all's set,
   *  minus the ones a recorded refusal still holds. */
  function autoReady(): number { return readyTracks(s).length; }

  function todoView(filter: TodoFilter, show_hidden: boolean) {
    const order: TodoGroupKey[] = ['rekordbox_check', 'same_song', 'duplicate', 'upgrade_ready', 'cdj', 'not_found', 'weak',
      'good_lossy', 'fake', 'other'];
    const LABELS: Record<TodoGroupKey, [string, string]> = {
      rekordbox_check: ['Check in rekordbox', 'the file changed; rekordbox needs a hand'],
      same_song: ['Is this the same song?', 'a file of yours might be a playlist song'],
      duplicate: ['Duplicates', 'the same song more than once'],
      upgrade_ready: ['Upgrade ready', 'a better version is waiting for you'],
      cdj: ["Won't play well on CDJs", 'CDJs refuse or stutter on these files'],
      not_found: ['Not found', 'nothing usable anywhere'], weak: ['Weak (≤ 17 kHz)', 'audibly lossy'],
      good_lossy: ['Good lossy (~20 kHz)', 'hard to hear'], fake: ['Fake lossless', 'the Qobuz file is really lossy'],
      other: ['Other', 'something is in the way'],
    };
    const items: Record<TodoGroupKey, TodoItem[]> = Object.fromEntries(order.map((k) => [k, []])) as never;
    const chips = Object.fromEntries(['all', ...order].map((k) => [k, 0])) as Record<TodoFilter, number>;
    const counted = new Set<string>();
    let hidden_count = 0;
    const open = new Map<number, FakeTrack[]>();
    for (const t of s.tracks) if (t.rekordbox_check?.batch) open.set(t.rekordbox_check.batch, [...(open.get(t.rekordbox_check.batch) ?? []), t]);
    const checkItem = (t: FakeTrack, size = 1): TodoItem => ({ ...trackRow(t), group: 'rekordbox_check',
      detail: checkStatus(t.rekordbox_check), check: checkView(t.rekordbox_check!, size), free: false,
      file_state: todoFileState(t), can_undo: !!t.rekordbox_check!.undo && !t.upgrade });
    for (const t of s.tracks) {
      if (t.rekordbox_check) {
        const id = t.rekordbox_check.batch;
        const group = id ? open.get(id)! : [];
        if (id && group.length > 1) {
          if (group[0] === t) {
            const key = `batch:${id}`;
            const tracks = group.map((x) => checkItem(x, group.length));
            const started = tracks.map((x) => x.check!.since).filter(Boolean).sort()[0] ?? null;
            const record = aiff.find((b) => b.id === id);
            const started_by = s.batchStartedBy?.[id] ?? record?.started_by ?? 'user';
            // the batch's own kind; a scenario that only sets checks has no record: its checks' reasons say it
            const kind = record?.kind ?? (tracks.some((x) => ['converted', 'renamed'].includes(x.check!.reason)) ? 'convert' : 'upgrade');
            // views._batch_how: "Made AIFF" for a Convert batch, "Clean name" when every check is a clean name
            const how = started_by === 'auto_upgrade' ? AUTO_BATCH_DETAIL : kind === 'upgrade' ? 'Same track'
              : tracks.every((x) => x.check!.reason === 'renamed') ? 'Clean name' : 'Made AIFF';
            items.rekordbox_check.unshift({ ...tracks[0], track_id: key, key, detail: `${started ?? ''} · ${how}`,
              batch: { id, size: group.length, started, started_by, kind, tracks } });
            chips.rekordbox_check++;
            counted.add(key);
          }
        } else {
          items.rekordbox_check.push(checkItem(t, group.length || 1));
          chips.rekordbox_check++;
          if (!t.hidden) counted.add(t.track_id);
        }
      }
      const g = t.in_playlists ? todoGroup(t) : null;
      if (!g) continue;
      if (t.hidden) hidden_count++;
      else { chips[g]++; counted.add(t.track_id); }
      if (!t.hidden || show_hidden) items[g].push({ ...trackRow(t), group: g, detail: todoDetail(t, g, g === 'upgrade_ready' ? (plain) => autoDetail(s, t, sameTrackReason(t), plain) : undefined), free: todoFree(t, g),
        file_state: todoFileState(t), ...(g === 'upgrade_ready' ? { same_track: sameTrackReason(t) } : {}) });
    }
    // stage D: the files CDJs play badly (a song listed there only, hidden as any item)
    const members = cdjMembers(s, true);
    const why = cdjAiff(s, [...members.keys()]);
    for (const t of s.tracks) {
      const problem = members.get(t.track_id);
      if (!problem) continue;
      if (t.hidden) hidden_count++;
      else { chips.cdj++; counted.add(t.track_id); }
      if (!t.hidden || show_hidden) items.cdj.push({ ...trackRow(t), group: 'cdj', detail: problem.short, free: false,
        file_state: todoFileState(t), cdj: problem, aiff: why.get(t.track_id) ?? null });
    }
    for (const q of questionItems(s)) { items.same_song.push(q); chips.same_song++; counted.add(q.track_id); }
    for (const d of duplicateItems(s)) { items.duplicate.push(d); chips.duplicate++; counted.add(d.track_id); }
    chips.all = counted.size;
    const groups = order.filter((k) => items[k].length && (filter === 'all' || filter === k))
      .map((k) => ({ key: k, label: LABELS[k][0], hint: LABELS[k][1], items: items[k],
        ...(k === 'upgrade_ready' ? upgradeAll(items[k]) : {}), ...(k === 'cdj' ? cdjAll() : {}) }));
    const empty = groups.length ? null : !s.tracks.length ? 'empty_library' as const : filter !== 'all'
      ? 'nothing_here' as const : hidden_count ? 'all_hidden' as const : 'all_lossless' as const;
    const check_tracks = s.tracks.filter((t) => t.rekordbox_check).length;
    return { chips, check_tracks, hidden_count, show_hidden, groups, empty };
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
      // as the engine: a folder's count is made of the playlists that are on, so a switched-off one counts 0 (its
      // files do not go anywhere); a song another playlist that is on holds is not stopped
      const stopped = s.tracks.filter((t) => off.some((o) => o.folder === t.folder)
        && !t.playlists.some((f) => f !== t.folder && lines.some((l) => l.enabled && l.folder === f))).length;
      return { ...base, kind: 'switch_off', headline: 'Left out of the sync, its files stay', checklist: checklist(0, false),
        renames: offers, stopped, folders: off.map((o) => ({ folder: o.folder,
          before: s.tracks.filter((t) => t.folder === o.folder).length, after: 0 })) };
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
  if (scenario === 'sync:auto-running') {
    // the sync is in its last phase, frozen with 3 of the batch's tracks done (the 4th is in work)
    at(() => {
      const a = autoSync();
      const line = lineOf(a.events!, (e) => e.type === 'BatchProgress', 3);
      startReplay(SYNC_START_LINE, { ...a, preRun: line, freeze: line });
    });
  }
  if (baseScenario === 'folders_importing') {
    // an import already running, held half way through reading the tags until Stop
    at(() => {
      const total = s.imp.folders.reduce((n, f) => n + (f.kind === 'import' ? f.waiting : 0), 0);
      beginImport({ resume: { phase: 'tags', done: 340 }, hold: true });
      s.imp.phase = 'tags';
      job?.record({ type: 'ImportProgress', phase: 'tags', done: 340, total, unreadable: 0 });
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
