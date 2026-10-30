<script lang="ts">
  // Fake mode only (#/dev/gallery): the design system's catalogue (spec §7). One section per block, headed by the
  // block's name and the rule it carries in one line (spec §7 table and §11), with the block in every state. A page
  // agent reads it before designing; a pattern no block covers is added here centrally, never built on a page.
  // The design-system blocks come first; then the shared components §7 doesn't rework yet; last the outdated ones,
  // which a redesigned page must not use (outdated.ts).
  import { onMount } from 'svelte';
  import { markReady } from '../ready';
  import { OUTDATED, OUTDATED_TOKENS } from '../outdated';
  import { PROBLEM_KINDS, type Library, type WatchedFolderRow, type DownloadsAccount, type DownloadsView, type EmptyKind, type FindLogins, type FolderCheck, type Service, type ReadStatus as ReadStatusT, type TrackRow as Row } from '../bridge/types';
  import { sampleTracks, trackRow, coverUri, makeUpgrade, dateOnly } from '../bridge/fake/data';
  import { fakeSpectrum } from '../bridge/fake/spectrum';
  import { toneUrl } from '../bridge/fake/audio';
  import { toasts } from '../stores/toasts';
  import type { PlayerState } from '../stores/player';
  import { EMPTY_RUN } from '../stores/run';
  import { goTo, makeQueue, setShuffle as shuffleQueue, type QueueItem } from '../stores/queueModel';
  import Foot from '../shell/Foot.svelte';
  import NowPlayingRow from '../shell/NowPlayingRow.svelte';
  import { ColumnFrame, ListPanelFrame, Panel } from '../frames';
  import {
    AccountPanel, AddRow, CopyCode, NumberedSteps, SecretField, StepStrip, type AccountActions, type PanelPhase, type StripStep,
    AwayTag, Badge, Banner, Button, Card, FolderField, Chip, ChipGroup, ComparePlayer, Cover, DayBar, DeltaBar, Dialog, DropZone, EmptyState, ExternalLink,
    Hint, InfoTip, KeyValue, ListRow, ListLine, ListSection, MiddleText, MiniPlayer, NavIcon, NAV_ICONS, NoteCard, ServiceMark, LOGO_KEYS, LOGO_NAMES, tip, SummaryStrip, PageHeader, PathText, ProblemCard, ProgressBar, QualityBadge, QualityBar, RiskScale, Ring, SearchField,
    Segmented, SectionLabel, SelectCard, Skeleton, SortHeader, SourceLadder, Spectrum, Spinner, SplitView, StatCard, StatusMark, Surface, Switch, TextField, Tile, Toast,
    ToggleGroup, ToggleRow, TrackHead, TrackRow, UpgradeCard, WriteButton, setOn, type DayBarInput, type SegOption, type ToggleItem,
    confirm, envelope, ImportCard, UnreadableList, WatchedFolderList,
  } from '../components';
  import Tick from '../components/Tick.svelte';
  import NeverButton from '../../pages/sync/plan/NeverButton.svelte';
  import Why from '../../pages/sync/plan/Why.svelte';
  import WhyMark from '../../pages/sync/plan/WhyMark.svelte';
  import KindIcon from '../../pages/sync/plan/KindIcon.svelte';
  import { isKindKey, KINDS, type KindKey } from '../../pages/sync/planModel';

  const NAV_NAMES = { dashboard: 'Dashboard', sync: 'Sync', todo: 'To-do', playlists: 'Playlists', limits: 'Download limits',
    library: 'Library', settings: 'Settings' } as const;
  // SummaryStrip: a collection's summary in each state (the counts add up like the mockup's Rekordbox Library)
  const strip = (o: Partial<Library['summary']> = {}): Library['summary'] => ({ tracks: 472, lossless_share: 290 / 460,
    by_quality: { lossless: 290, good_lossy: 120, weak: 41, fake: 9, missing: 0 }, upgrades_ready: 6, to_do: 41,
    not_lossless: 170, ...o });
  const STRIPS: [string, Library['summary'] | null, number][] = [
    ['fewer in To-do: files of your own in no playlist aren\'t (tooltip)', strip(), 900],
    ['all in To-do, a big library', strip({ tracks: 5318, lossless_share: 3776 / 5306, upgrades_ready: 9, to_do: 1530,
      not_lossless: 1530, by_quality: { lossless: 3776, good_lossy: 900, weak: 500, fake: 130, missing: 0 } }), 900],
    ['the longest words: big counts, some in To-do', strip({ tracks: 5318, lossless_share: 3776 / 5306, upgrades_ready: 1204,
      to_do: 1234, not_lossless: 1530, by_quality: { lossless: 3776, good_lossy: 900, weak: 500, fake: 130, missing: 0 } }), 900],
    ['none in To-do, no upgrades: no links, no ›', strip({ upgrades_ready: 0, to_do: 0 }), 900],
    ['everything lossless', strip({ lossless_share: 1, upgrades_ready: 0, to_do: 0, not_lossless: 0,
      by_quality: { lossless: 460, good_lossy: 0, weak: 0, fake: 0, missing: 0 } }), 900],
    ['nothing checked yet', strip({ lossless_share: null, upgrades_ready: 0, to_do: 0, not_lossless: 0,
      by_quality: { lossless: 0, good_lossy: 0, weak: 0, fake: 0, missing: 0 } }), 900],
    ['waiting', null, 900],
    ['586 px: the list beside the inspector at 1280', strip(), 586],
  ];
  const HDR_PARTS = ['472 tracks', '8 folders with music', '~/Music/Rekordbox Library'];
  /** Gallery only: starts a scroller at a given offset, so a stuck state shows without scrolling by hand. */
  function scrollAt(node: HTMLElement, y: number) { requestAnimationFrame(() => { node.scrollTop = y; }); }
  let inspectorOpen = $state(true);
  let gFolded = $state(['Playlists']);
  // Tip: one tip open at a time, as in the app; the strip picks which example shows its own
  const TIP_SHOW: SegOption<'rail' | 'cut' | 'crate'>[] = [{ key: 'rail', label: 'Rail icon' }, { key: 'cut', label: 'Cut name' },
    { key: 'crate', label: 'Crate, two lines' }];
  let tipShown = $state<'rail' | 'cut' | 'crate'>('rail');
  const now = new Date();
  const tracks = sampleTracks(now).map(trackRow);
  const t = (id: string) => tracks.find((x) => x.track_id === id) as Row;
  const weak = t('t2');
  const lossless = t('t1');
  const missing = t('t3');
  const fakeQ = tracks.find((x) => x.quality === 'fake')!;
  const good = tracks.find((x) => x.quality === 'good_lossy')!;
  const specCut = fakeSpectrum(16000, 11, 268);
  const specFull = fakeSpectrum(null, 5, 156);
  const env = envelope(specFull);
  const upExact = makeUpgrade(weak, 'exact', dateOnly(now));
  const upDifferent = makeUpgrade(weak, 'different', dateOnly(now));
  const toneA = toneUrl(40, 220);
  const toneB = toneUrl(40, 330);

  // Foot · Now playing row: fixed player states (the real store is untouched; the buttons still act on it)
  const qItems: QueueItem[] = tracks.filter((x) => x.path !== null).slice(0, 8)
    .map(({ track_id, title, artist, cover_url, duration_s }) => ({ track_id, title, artist, cover_url, duration_s }));
  const longItem: QueueItem = { ...qItems[0], title: 'Sonnenfinsternis (Extended Hardstyle Remix)',
    artist: 'DJ Fluxkompensator & The Bounce Brigade' };
  const np = (o: Partial<PlayerState> & { at?: number; items?: QueueItem[]; label?: string; shuffle?: boolean } = {}): PlayerState => {
    const { at = 1, items = qItems, label = 'All tracks', shuffle = false, ...rest } = o;
    const q = shuffleQueue(goTo(makeQueue(items, 0, { label, href: '#/library' }), Math.min(at, items.length - 1)), shuffle, () => .3);
    const d = items[Math.min(at, items.length - 1)].duration_s;
    return { url: 'blob:gallery', title: '', track_id: items[0].track_id, playing: true, loading: false,
      position_s: (d ?? 200) * .48, duration_s: d, error: null, queue: q, hidden: false, ended: false, ...rest };
  };
  const syncRun = { ...EMPTY_RUN, phase: 'running' as const, total: 6, index: 4, qobuz: { used: 1, allowance: 80 } };
  const FOOTS: [string, string, PlayerState, { edge?: number; sync?: boolean }][] = [
    ['Playing', 'the page\'s lower edge is the position', np(), {}],
    ['Pointer on the edge', 'it thickens, a knob at the position, the time under the pointer; click or drag', np(), { edge: .71 }],
    ['Paused', '', np({ playing: false }), {}],
    ['Loading the next track', 'the new title at once, no fill', np({ at: 2, url: null, loading: true, playing: false, position_s: 0, duration_s: null }), {}],
    ["Can't play", "doesn't skip by itself; ⏮ ⏭ go on", np({ at: 2, url: null, playing: false, error: "Can't play this file.", position_s: 0 }), {}],
    ['End of the list', '▶ plays it again from the top', np({ at: qItems.length - 1, playing: false, ended: true }), {}],
    ['A list of one', 'a search with one hit: ⤮ ⏮ ⏭ grey', np({ at: 0, items: qItems.slice(0, 1), label: 'Bouncy · “neonf”' }), {}],
    ['Shuffle on, from To-do', 'colour plus a dot', np({ label: 'To-do', shuffle: true }), {}],
    ['Long names', 'cut with …, the full name in the tooltip', np({ at: 0, items: [longItem, ...qItems], label: 'Hard_Bounce_Classics_2026' }), {}],
    ['Playing while a sync runs', 'the sync\'s short form at the right end, a link to Sync', np(), { sync: true }],
  ];
  const sp = (o: Partial<ReadStatusT>): ReadStatusT => ({ read_at: new Date(now.getTime() - 120000).toISOString(),
    minutes_ago: 2, problem: null, message: '', stale: false, reading: false, offline: false, auto_read: true,
    problem_service: null, services: [{ service: 'spotify', name: 'Spotify', connected: true }], ...o });
  const EMPTY_KINDS: EmptyKind[] = ['no_playlists', 'not_set_up', 'empty_library', 'no_preview', 'up_to_date', 'no_match',
    'all_lossless', 'all_hidden', 'nothing_here'];
  const BY_Q = { lossless: 226, good_lossy: 49, weak: 24, fake: 3, missing: 4 };

  // SourceLadder: the downloads view in the states the ladder shows (Qobuz only is the user's own setup)
  const dlAcc = (state: DownloadsView['youtube']['state']): DownloadsView['youtube'] => ({ state, browser: state === 'off' ? null : 'chrome',
    browser_name: state === 'off' ? null : 'Chrome', profile: null, profile_name: null, last_check: null, tracks: 0 });
  const dl = (q: DownloadsView['qobuz']['state'], yt: DownloadsView['youtube']['state'], sc: DownloadsView['soundcloud']['state']): DownloadsView =>
    ({ qobuz: { state: q, last_check: null, tracks: 0 }, youtube: dlAcc(yt), soundcloud: dlAcc(sc),
      library: { lossless: 226, account: 31, free: 49 } });
  const LADDERS: [string, string, DownloadsView | null][] = [
    ['nothing set up', 'nothing', dl('off', 'off', 'off')],
    ['Qobuz only', 'qobuz', dl('on', 'off', 'off')],
    ['Qobuz + YouTube Premium', 'premium', dl('on', 'on', 'off')],
    ['no Qobuz · SoundCloud, Go+ not confirmed', 'no-premium', dl('skipped', 'off', 'no_premium')],
    ['YouTube paused today', 'paused', dl('on', 'paused', 'off')],
    ['loading', 'loading', null],
  ];
  // AccountPanel: every phase from props, with a stand-in for the flow that only says what was asked
  const day = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const checkedAt = `${day(now)}T10:42:00`;
  const gAcc = (o: Partial<DownloadsAccount> = {}): DownloadsAccount => ({ state: 'off', browser: null, browser_name: null,
    profile: null, profile_name: null, last_check: null, tracks: 0, ...o });
  const gDl = (o: Partial<DownloadsView> = {}): DownloadsView => ({ qobuz: { state: 'on', tracks: 412,
    last_check: { ok: true, problem: null, kbps: null, at: checkedAt } }, youtube: gAcc(), soundcloud: gAcc(),
    library: { lossless: 412, account: 0, free: 31 }, ...o });
  const G_LOGINS: FindLogins = { browsers: [
    { id: 'chrome', name: 'Chrome', default: true, readable: true, problem: null,
      profiles: [{ id: 'Default', name: 'Person 1', signed_in: false }, { id: 'Profile 2', name: 'DJ', signed_in: true }] },
    { id: 'firefox', name: 'Firefox', default: false, readable: true, problem: null,
      profiles: [{ id: 'abc.default', name: 'default', signed_in: false }] },
    { id: 'safari', name: 'Safari', default: false, readable: false, problem: 'no_access',
      profiles: [{ id: null, name: 'Safari', signed_in: false }] }] };
  let accAsked = $state('');
  const said = (what: string) => async () => { accAsked = what; };
  const G_ACTIONS: AccountActions = {
    load: said('find_logins again'), useLogin: async (b, p) => { accAsked = `Use this login: ${b} ${p ?? ''}`; },
    signIn: async (b, p) => { accAsked = `Sign in: ${b} ${p ?? ''}`; }, cancel: said('Cancel'), checkAgain: said('Check again'),
    signOut: said('Sign out'), openPrivacySettings: said('Open System Settings'),
    pick: (c) => { accAsked = `picked ${c.label}`; }, back: () => { accAsked = 'back'; },
    qobuzLogin: async (email) => { accAsked = `Qobuz sign in as ${email || '(no e-mail)'}`; }, skipQobuz: said("I don't have Qobuz"),
    openPasswordPage: said('Set a Qobuz password'), editQobuz: () => { accAsked = 'Use another account'; },
  };
  const ytOn = gAcc({ state: 'on', browser: 'chrome', browser_name: 'Chrome', profile: 'Profile 2', profile_name: 'DJ',
    last_check: { ok: true, problem: null, kbps: 256, at: checkedAt }, tracks: 12 });
  const found: PanelPhase = { kind: 'found', browser: 'chrome', browserName: 'Chrome', profile: 'Profile 2', profileName: 'DJ' };
  const noneChrome: PanelPhase = { kind: 'none', browser: 'chrome', browserName: 'Chrome', profile: null, profileName: null,
    searched: ['Chrome', 'Firefox'] };
  const qOff = { state: 'off' as const, last_check: null, tracks: 0 };
  const ACCOUNT_PANELS: { key: string; cap: string; service: Service; d: DownloadsView | null; phase: PanelPhase;
    why?: string; steps?: boolean; busy?: boolean }[] = [
    { key: 'looking', cap: 'YouTube · looking for a login', service: 'youtube', d: gDl(), phase: { kind: 'looking' } },
    { key: 'found', cap: 'found in Chrome (DJ) → Use this login', service: 'youtube', d: gDl(), phase: found },
    { key: 'none', cap: 'no login → Sign in with the default browser', service: 'youtube', d: gDl(), phase: noneChrome },
    { key: 'waiting', cap: 'waiting for the browser · Cancel', service: 'youtube', d: gDl(), busy: true,
      phase: { kind: 'waiting', browser: 'chrome', browserName: 'Chrome' } },
    { key: 'checking', cap: 'checking one song', service: 'youtube', d: gDl(), busy: true, phase: { kind: 'checking', browserName: 'Chrome' } },
    { key: 'works', cap: 'works · nothing in the foot', service: 'youtube', d: gDl({ youtube: ytOn }), phase: { kind: 'working' } },
    { key: 'no-premium', cap: 'signed in, but no Premium', service: 'youtube', phase: { kind: 'no_premium' },
      d: gDl({ youtube: gAcc({ state: 'no_premium', browser: 'chrome', browser_name: 'Chrome',
        last_check: { ok: false, problem: 'no_premium', kbps: 160, at: checkedAt } }) }) },
    { key: 'safari', cap: 'Safari without Full Disk Access → Open System Settings', service: 'youtube', d: gDl(),
      phase: { kind: 'unreadable', browser: 'safari', browserName: 'Safari', profile: null } },
    { key: 'timed-out', cap: 'the sign-in timed out → Sign in again', service: 'youtube', d: gDl(),
      phase: { kind: 'result', tone: 'problem', message: "Didn't see a login in 10 minutes. Sign in again.", retry: noneChrome } },
    { key: 'paused', cap: 'paused today → Download limits', service: 'youtube', phase: { kind: 'working' },
      d: gDl({ youtube: { ...ytOn, state: 'paused' } }) },
    { key: 'sign-out-failed', cap: 'a failed sign-out → OK goes back', service: 'youtube', d: gDl({ youtube: ytOn }),
      phase: { kind: 'result', tone: 'problem', message: 'Wait until the current change is finished.', retry: null } },
    { key: 'disabled', cap: 'off, with the reason (a terminal run)', service: 'youtube', d: gDl(), phase: found,
      why: 'A sync is running in the terminal.' },
    { key: 'error', cap: 'looking failed → Retry', service: 'youtube', d: gDl(),
      phase: { kind: 'error', message: "Discjockey couldn't look at your browsers. Try again." } },
    { key: 'soundcloud', cap: 'SoundCloud · no login in Chrome or Firefox', service: 'soundcloud', d: gDl(), phase: noneChrome },
    { key: 'qobuz-form', cap: 'Qobuz · sign in', service: 'qobuz', d: gDl({ qobuz: qOff }), phase: { kind: 'form' } },
    { key: 'qobuz-steps', cap: 'Qobuz · Google, Apple or Facebook: the steps', service: 'qobuz', d: gDl({ qobuz: qOff }),
      phase: { kind: 'form' }, steps: true },
    { key: 'qobuz-works', cap: 'Qobuz · signed in', service: 'qobuz', d: gDl(), phase: { kind: 'working' } },
    { key: 'qobuz-rejected', cap: "Qobuz · didn't accept the login", service: 'qobuz', phase: { kind: 'result', tone: 'problem',
      message: "Qobuz didn't accept this e-mail and password.", retry: { kind: 'form' } },
      d: gDl({ qobuz: { state: 'off', tracks: 0, last_check: { ok: false, problem: 'login_failed', kbps: null, at: checkedAt } } }) },
  ];
  let accSteps = $state<Record<string, boolean>>(Object.fromEntries(ACCOUNT_PANELS.map((p) => [p.key, !!p.steps])));
  let ladderPicked = $state<string>('');
  let subOn = $state(true);
  // StepStrip: every state at once (two done, the one on screen, the next one, one that waits)
  const STRIP: StripStep[] = [
    { key: 'music', label: 'Music folder', state: 'done', done: true },
    { key: 'tools', label: 'Programs', state: 'done', done: true },
    { key: 'spotify', label: 'Spotify', state: 'current' },
    { key: 'downloads', label: 'Downloads', state: 'open' },
    { key: 'playlists', label: 'First playlist', state: 'locked' },
  ];
  let stripPicked = $state('');
  let chip = $state<'all' | 'weak' | 'fake'>('all');
  let pickedCard = $state<'q' | 'y' | 's'>('q');
  let riskValue = $state(72);
  const GALLERY_ZONES = [{ name: 'careful', from: 1, to: 40 }, { name: 'normal', from: 41, to: 60 },
    { name: 'faster', from: 61, to: 79 }, { name: 'fast', from: 80, to: 100 }, { name: 'risky', from: 101, to: 500 }];
  // ToggleGroup · Segmented
  const flip = (list: ToggleItem[], key: string, on: boolean) => setOn(list, [key], on);
  const playlists = (names: string[], counts: number[], off: number[]): ToggleItem[] =>
    names.map((label, i) => ({ key: `p${i}`, label, count: counts[i % counts.length], on: !off.includes(i) }));
  let kinds = $state<ToggleItem[]>([{ key: 'new', label: 'New', count: 95, on: true },
    { key: 'retry', label: 'Not found last time', count: 4, on: true }, { key: 'bought', label: 'Bought files', count: 3, on: false }]);
  // the 5 kinds the app defines: a fixed set, so no search (spec §11, Task 9B)
  let allKinds = $state<ToggleItem[]>(KINDS.map((k, i) => ({ key: k.key, label: k.label, count: [95, 4, 2, 1, 12][i], on: i !== 3 })));
  // 14 of the user's own playlists, one with a long name: search, scrolling rows and the end fade
  let pls = $state<ToggleItem[]>(playlists(['Ohne_Quatsch', 'Tekke_Ecke', 'Powertrance', 'Hard_Bounce', 'Bouncy', '03_06_2026',
    'Voller_Quatsch', 'Rollers', 'Peak Time', 'Kölsch Mix', 'Liquid Sunday', 'Afterhours with a very long playlist name that has to shorten',
    'Warmup', 'Closing'], [41, 9, 3, 12, 2, 8, 14, 6, 5, 3, 2, 1234, 7, 11], [2, 7]));
  let allOff = $state<ToggleItem[]>(playlists(['Ohne_Quatsch', 'Tekke_Ecke', 'Hard_Bounce', 'Bouncy'], [41, 9, 12, 2], [0, 1, 2, 3]));
  let panelPls = $state<ToggleItem[]>(playlists(['Ohne_Quatsch', 'Tekke_Ecke', 'Powertrance', 'Hard_Bounce', 'Bouncy', '03_06_2026',
    'Voller_Quatsch', 'Rollers', 'Peak Time'], [41, 9, 3, 12, 2, 8, 14, 6, 5], [2]));
  let panelFew = $state<ToggleItem[]>(playlists(['Ohne_Quatsch', 'Tekke_Ecke', 'Powertrance', 'Hard_Bounce'], [41, 9, 3, 12], [2]));
  // a folder with too many crates (Settings, B7): All waits for a search (allMax), a row is found by its parent folder too
  let crates = $state<ToggleItem[]>(Array.from({ length: 40 }, (_, i) => {
    const artist = ['Aphex', 'Burial', 'Calibre', 'Dusk'][i % 4], album = `Album ${i + 1}`;
    return { key: `c${i}`, label: album, count: 8 + (i % 5), on: i < 2, tip: `Albums › ${artist} › ${album}`, find: artist };
  }));
  let sources = $state<ToggleItem[]>([{ key: 'ytm', label: 'YouTube Music', on: true }, { key: 'sc', label: 'SoundCloud', on: false },
    { key: 'yt', label: 'YouTube', count: null, on: true }]);
  let auto = $state<ToggleItem>({ key: 'auto', label: 'Read Spotify when the hub opens', on: true });
  let howMany = $state<string>('66');
  const HOW_MANY: SegOption<string>[] = [{ key: '10', label: '10' }, { key: '25', label: '25' }, { key: '50', label: '50' },
    { key: '66', label: '66 ✦' }, { key: 'all', label: 'All' }];
  let qf = $state<string>('all');
  const QUALITY_FILTER: SegOption<string>[] = [{ key: 'all', label: 'All', count: 306 },
    { key: 'lossless', label: 'Lossless', count: 226, dot: 'lossless' }, { key: 'good', label: 'Good', count: 49, dot: 'good_lossy' },
    { key: 'weak', label: 'Weak', count: 24, dot: 'weak' }, { key: 'fake', label: 'Fake', count: 3, dot: 'fake' },
    { key: 'missing', label: 'Not found', count: 4, dot: 'missing' }];
  // a count of 0: nothing is there, so the dot stays away (the label and the 0 stay)
  const QUALITY_NONE: SegOption<string>[] = [{ key: 'all', label: 'All', count: 12 },
    { key: 'lossless', label: 'Lossless', count: 12, dot: 'lossless' }, { key: 'good', label: 'Good', count: 0, dot: 'good_lossy' },
    { key: 'weak', label: 'Weak', count: 0, dot: 'weak' }, { key: 'fake', label: 'Fake', count: 0, dot: 'fake' },
    { key: 'upgrade', label: 'Upgrade ready', count: 0, dot: 'lossless' }];
  // 8 options: 6 on the strip, the rest in More; the chosen one (Afterhours) is in More and stays visible
  let folder = $state<string>('f7');
  const FOLDERS: SegOption<string>[] = ['All', 'Ohne_Quatsch', 'Tekke_Ecke', 'Hard_Bounce', 'Bouncy', 'Rollers', 'Peak Time', 'Afterhours']
    .map((label, i) => ({ key: `f${i}`, label }));
  let narrow = $state<string>('b');
  const NARROW: SegOption<string>[] = [{ key: 'a', label: 'Everything in the library', count: 306 },
    { key: 'b', label: 'Upgrade ready', count: 12 }, { key: 'c', label: 'Not found', count: 4 }];
  // DayBar: the five dayBar cases, and one that moves with the amount (66 a day, 102 ticked)
  const DAY_CASES: [string, DayBarInput][] = [
    ['today and tomorrow', { today: 66, later: 36, limited: true, laterDays: 1 }],
    ['takes longer: "Today 10" keeps its label beside "Later 185"', { today: 10, later: 185, limited: true, laterDays: 4 }],
    ['no daily limit: one segment', { today: 120, later: 0, limited: false, laterDays: 0 }],
    ['limit reached: all later', { today: 0, later: 77, limited: true, laterDays: 2 }],
    ['nothing ticked', { today: 0, later: 0, limited: true, laterDays: 0 }],
    ['day mode: used, this sync, left (Dashboard)', { today: 15, later: 0, limited: true, laterDays: 0, day: { used: 37, allowance: 80 } }],
    ['day mode over the limit: used, this sync, tomorrow', { today: 43, later: 20, limited: true, laterDays: 1, day: { used: 37, allowance: 80 } }],
    ['day mode with nothing to sync', { today: 0, later: 0, limited: true, laterDays: 0, day: { used: 37, allowance: 80 } }],
  ];
  const dayTest = (name: string) => `g-day-${name.split(/[:"]/)[0].trim().replaceAll(' ', '-')}`;
  let amount = $state<string>('66');
  const AMOUNTS: SegOption<string>[] = [{ key: '0', label: 'Limit hit' }, { key: '10', label: '10' }, { key: '25', label: '25' },
    { key: '66', label: '66 ✦' }, { key: '102', label: 'All' }];
  // as the mockup: the amount picks how many download today, everything else ticked waits for later; "Limit hit"
  // leaves nothing for today (the today segment slides out like any other split)
  const live = $derived.by((): DayBarInput => {
    const today = Math.min(Number(amount), 66), later = 102 - today;
    return { today, later, limited: true, laterDays: Math.ceil(later / 66) };
  });
  // ProgressBar: one value, three paces, so the motions can be compared side by side
  let share = $state<string>('0.25');
  const SHARES: SegOption<string>[] = [{ key: '0.1', label: '10 %' }, { key: '0.25', label: '25 %' }, { key: '0.6', label: '60 %' },
    { key: '0.9', label: '90 %' }];
  let text = $state('');
  let bad = $state('not-a-link');
  let okv = $state('0123456789abcdef0123456789abcdef');
  let search = $state('gimme');
  let search2 = $state('');
  let dialogOpen = $state(false);
  let dialogBusy = $state(false);
  let tipDialogOpen = $state(false);
  let selected = $state('t1');
  let answer = $state<string>('');
  let folded = $state(false);
  // the sortable table demo (Surface `columns` + SortHeader) and the playable cover
  let gSort = $state<{ col: 'track' | 'length'; desc: boolean }>({ col: 'track', desc: false });
  const gFolder = (o: Partial<FolderCheck>): FolderCheck =>
    ({ path: '', exists: true, usable: true, problem: null, kind: 'empty', message: null, ...o });
  const gSortBy = (col: 'track' | 'length') => { gSort = { col, desc: gSort.col === col ? !gSort.desc : false }; };
  const gSorted = (col: 'track' | 'length') => (gSort.col === col ? (gSort.desc ? 'desc' : 'asc') : null);
  let gPlaying = $state<string | null>('c2');
  let focusMe: HTMLDivElement | undefined = $state();
  // ListRow: the Sync plan's tick list (narrow and wide), a "one of many" list, a list without a button. Narrow, the
  // why is a mark before ⊘ (WhyMark, a 26 px slot: trailing 60 px); from 680 px list width it is the why column.
  const LR_COLS = '--row-cols: 52px minmax(0, 1fr) 60px; --row-cols-wide: 52px minmax(0, 1fr) 200px 32px';
  const LR_ROWS: { id: string; artist: string; title: string; tag: string | null; kind: KindKey | null; next: boolean }[] = [
    { id: 'a', artist: 'Charlotte de Witte', title: 'Overdrive', tag: null, kind: null, next: false },
    { id: 'b', artist: 'Amelie Lens', title: 'Feel It', tag: 'not found last time', kind: 'retry', next: false },
    { id: 'c', artist: 'Ben Klock, Fadi Mohem, DVS1, Etapp Kyle, Marcel Dettmann, Norman Nodge',
      title: 'Subzero (Extended Original Mix featuring a very long remix credit that has to shorten) [Ostgut Ton]',
      tag: 'bought file', kind: 'bought', next: true },
  ];
  let lrTicked = $state(new Set(['a', 'c']));
  const lrToggle = (id: string) => { const n = new Set(lrTicked); if (n.has(id)) n.delete(id); else n.add(id); lrTicked = n; };
  let lrChosen = $state('t1');
  // rows with an ⓘ each, one under the other: every tip opens under (or above) its own ⓘ
  const TIP_ROWS = [
    ['Qobuz', '66 a day', 'Qobuz allows about 66 downloads a day. Tracks beyond that wait for the next sync.'],
    ['YouTube Music', 'no limit', 'No daily limit. Discjockey keeps the pace slow, because downloading breaks their terms.'],
    ['SoundCloud', 'no limit', 'No daily limit. Only tracks the artist allows to download come in lossless.'],
    ['YouTube', 'backup', 'Used only when nothing else has the track. The file is lossy.'],
  ];
  onMount(() => {
    markReady('gallery');
    focusMe?.querySelector('button')?.focus();
  });
  const gFolders: WatchedFolderRow[] = [
    { id: 1, path: '/Users/you/Music/Discjockey/Library', name: 'Library', kind: 'library', state: 'online', files: 412, waiting: 0, unreadable: 0, crates: [], too_many: false },
    { id: 2, path: '/Volumes/Example Drive/Music', name: 'Music', kind: 'import', state: 'importing', files: 1840, waiting: 1500, unreadable: 0, crates: [], too_many: false },
    { id: 3, path: '/Volumes/Old Drive/Music', name: 'Music', kind: 'import', state: 'offline', files: 612, waiting: 0, unreadable: 0, crates: [], too_many: false },
    { id: 4, path: '/Users/you/Music/Crates', name: 'Crates', kind: 'import', state: 'online', files: 1, waiting: 0, unreadable: 0, crates: [], too_many: false },
  ];
  // Settings: import folders with crates are rows to pick (`onpick`), the picked one washed; `cap` keeps the list to 4 rows and a peek
  const gCrate = (name: string) => ({ path: `/Users/you/Music/Rekordbox Library/${name}`, label: name, name, tip: `Rekordbox Library › ${name}`, files: 4, hidden: false, has_crates: false });
  const gPickable: WatchedFolderRow[] = [
    gFolders[0],
    { id: 5, path: '/Users/you/Music/Rekordbox Library', name: 'Rekordbox Library', kind: 'import', state: 'online', files: 30, waiting: 0, unreadable: 0, crates: [gCrate('Bounce'), gCrate('Edits')], too_many: false },
    { id: 6, path: '/Volumes/Example Drive/Albums', name: 'Albums', kind: 'import', state: 'online', files: 312, waiting: 0, unreadable: 0, crates: [gCrate('Night Tapes')], too_many: false },
    gFolders[3],
    { id: 7, path: '/Users/you/Music/Festival Sets', name: 'Festival Sets', kind: 'import', state: 'online', files: 41, waiting: 0, unreadable: 0, crates: [], too_many: false },
  ];
</script>

{#snippet head(name: string, rule: string)}
  <header class="sh"><h2>{name}</h2><p class="rule">{rule}</p></header>
{/snippet}

{#snippet gDetailsGlyph(struck = false)}
  <!-- Library's details glyph (the macOS inspector symbol); struck: hidden by hand -->
  <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="2.5" width="13" height="11" rx="2.4" /><path d="M10 2.5v11" />
    {#if struck}<path d="M1.8 1.6l12.4 12.8" />{:else}<path d="M11.6 5.2h1.3M11.6 7.2h1.3M11.6 9.2h1.3" />{/if}</svg>
{/snippet}
{#snippet srows(n: number, prefix: string)}
  {#each Array(n) as _, i (i)}<div class="srow">{prefix} {i + 1}</div>{/each}
{/snippet}

<div class="gallery">
  <PageHeader title="Design system" sub="every block in every state, with its rule · fake mode only" />

  <!-- ─── design-system blocks (spec §7) ─── -->

  <section data-test="gallery-frames">
    {@render head('ListPanelFrame · ColumnFrame', 'Every page uses one: a list with the panel docked at the right, or one column; the content grows to 900 px (1200 px wide), then centres (§3)')}
    <span class="cap">ListPanelFrame · the panel is 360 px, 320 px below a 1240 px window</span>
    <div class="framebox">
      <ListPanelFrame>
        {#snippet main()}
          <PageHeader title="List" sub="rows grow to 900 px, then centre" />
          <Surface kind="list" label="Rows" summary="4">{@render srows(4, 'Row')}</Surface>
        {/snippet}
        {#snippet panel()}
          <Panel>
            {#snippet head()}<StatCard value={66} label="tracks this run" />{/snippet}
            {#snippet foot()}<Button variant="filled" wide>Main action</Button>{/snippet}
          </Panel>
        {/snippet}
      </ListPanelFrame>
    </div>
    <span class="cap">ListPanelFrame · no item picked: the panel's empty state</span>
    <div class="framebox short">
      <ListPanelFrame panel={null}>
        {#snippet main()}<Surface kind="list" label="Rows">{@render srows(2, 'Row')}</Surface>{/snippet}
      </ListPanelFrame>
    </div>
    <span class="cap">ListPanelFrame inspector · when wanted: the list resizes at once, the panel slides in</span>
    <div class="framebox" data-test="g-frame-inspector">
      <ListPanelFrame panelMode="inspector" open={inspectorOpen}>
        {#snippet main()}
          <PageHeader title="Rekordbox Library" sub={HDR_PARTS}>{#snippet actions()}
            <Button variant="icon" pressed={inspectorOpen} aria-label={inspectorOpen ? 'Hide details' : 'Show details'}
              tip={{ text: inspectorOpen ? 'Hide details' : 'Show details', keys: '⌘I' }}
              onclick={() => (inspectorOpen = !inspectorOpen)} data-test="g-inspector-toggle">{@render gDetailsGlyph()}</Button>{/snippet}</PageHeader>
          <Surface kind="list" label="Rows" summary="4">{@render srows(4, 'Row')}</Surface>
        {/snippet}
        {#snippet panel()}
          <Panel>
            {#snippet head()}<StatCard value={20} unit="kHz" label="cutoff · a lossy file" />{/snippet}
          </Panel>
        {/snippet}
      </ListPanelFrame>
    </div>
    <span class="cap">ColumnFrame · one 900 px column, the foot's rule spans the content</span>
    <div class="framebox tall">
      <ColumnFrame>
        {#snippet content()}
          <PageHeader title="Column" sub="Settings, the end screen" />
          <Surface label="A card">A column holds cards and lists one under the other.</Surface>
          <Surface kind="list" label="A list">{@render srows(3, 'Row')}</Surface>
        {/snippet}
        {#snippet foot()}<Button>Back</Button><Button variant="filled">Done</Button>{/snippet}
      </ColumnFrame>
    </div>
  </section>

  <section data-test="gallery-panel">
    {@render head('Panel', 'Head, fill, after, foot: fill grows to its list\'s rows and never shrinks below 3 of them (a peek under the fade); when even that doesn\'t fit, the whole body scrolls and its cut fades over a row\'s height; the foot never scrolls away (§3, §11)')}
    <div class="row top">
      {#each [[560, 'few rows: the list takes its 4 rows, the spare height sits above the foot', 'few'],
        [576, 'many rows: the list takes the spare height, scrolls inside itself and its cut lands a peek into a row, the px under it above the foot', 'fill'],
        [380, 'too short: the list keeps 3 rows and a peek, the whole body scrolls and fades above the foot', 'body']] as [h, cap, k] (k)}
        <div class="col tight">
          <span class="cap w320">{cap}</span>
          <div class="panelbox" style="height: {h}px">
            <Panel>
              {#snippet head()}<StatCard value={0} label="tracks this run" />{/snippet}
              {#snippet fill()}
                {#if k === 'few'}
                  <ToggleGroup label="Playlists" items={panelFew} grow onchange={(key, on) => (panelFew = flip(panelFew, key, on))}
                    onall={(on, keys) => (panelFew = setOn(panelFew, keys, on))} />
                {:else}
                  <ToggleGroup label="Playlists" items={panelPls} grow onchange={(key, on) => (panelPls = flip(panelPls, key, on))}
                    onall={(on, keys) => (panelPls = setOn(panelPls, keys, on))} />
                {/if}
              {/snippet}
              {#snippet after()}<NoteCard tone="warn" title="Downloads start tomorrow" />{/snippet}
              {#snippet foot()}
                <Button variant="filled" wide disabled>Start sync</Button>
                <Hint text="Nothing to run today · downloads start tomorrow" />
              {/snippet}
            </Panel>
          </div>
        </div>
      {/each}
    </div>
  </section>

  <section data-test="gallery-page-header">
    {@render head('PageHeader · the read slot', 'One per page: title · status line, the page\'s actions, the playlists\' read slot always last at the right edge (§5a)')}
    <div class="col headers">
      <PageHeader title="Good morning" readStatus readStatusState={sp({})} />
      <PageHeader title="To-do" sub="18 tracks are not lossless yet" readStatus readStatusState={sp({ reading: true })} />
      <PageHeader title="To-do" sub="18 tracks are not lossless yet" readStatus readStatusState={sp({ stale: true })} />
      <PageHeader title="To-do" sub="18 tracks are not lossless yet" readStatus
        readStatusState={sp({ offline: true, problem: 'offline', minutes_ago: 184, read_at: new Date(now.getTime() - 184 * 60000).toISOString() })} />
      <!-- a status line too long for the space beside the title wraps under it, whole, after a "·" -->
      <PageHeader title="To-do" sub="18 tracks are not lossless yet · 5 questions about your files · 3 songs need a look in rekordbox · 2 upgrades are ready" readStatus readStatusState={sp({})} />
      <PageHeader title="Good morning" readStatus readStatusState={sp({ problem: 'login_expired', message: 'Your Spotify login has expired.' })} />
      <PageHeader title="Good morning" readStatus readStatusState={sp({ read_at: null, minutes_ago: null })} />
      <!-- a used service without its login: Read playlists off, its reason names the service (the banner says it) -->
      <PageHeader title="Playlists" sub="33 tracks in your playlists" readStatus readStatusState={sp({
        services: [{ service: 'spotify', name: 'Spotify', connected: true }, { service: 'qobuz', name: 'Qobuz', connected: false }] })} />
      <PageHeader title="Good morning" readStatus readStatusState={null} />
      <PageHeader title="Sync" readStatus readStatusInBody readStatusState={sp({ reading: true })} />
      <PageHeader title="Sync" readStatus readStatusInBody
        readStatusState={sp({ offline: true, problem: 'offline', minutes_ago: 184, read_at: new Date(now.getTime() - 184 * 60000).toISOString() })} />
      <PageHeader title="Hard_Bounce" sub="45 tracks · 82 % lossless">{#snippet actions()}<SearchField bind:value={search2} placeholder="Search…" shortcut="cmd+f" />{/snippet}</PageHeader>
      <PageHeader title="Sync done" sub="Today 21:47 · 24 min">{#snippet actions()}<Button size="sm" variant="link" href="https://example.com">Full report ↗</Button>{/snippet}</PageHeader>
      <PageHeader title="Hard_Bounce_Extended_Afterhour_Selection_2026" sub="1,204 tracks · 82 % lossless · 3 not in a playlist" readStatus readStatusState={sp({})} />
      <PageHeader title="Settings" />
    </div>
    <span class="cap">subtitle as parts: whole parts drop, the last first; all of it is the tooltip</span>
    <div class="col" data-test="g-header-parts">
      {#each [[946, 'Rekordbox Library', HDR_PARTS], [586, 'Rekordbox Library', HDR_PARTS], [440, 'Rekordbox Library', HDR_PARTS],
        [300, 'Rekordbox Library', HDR_PARTS], [586, 'Afterhour_Sonntag_Warmup', ['88 tracks', 'Qobuz playlist', 'switched off', 'Library › Afterhour_Sonntag_Warmup']],
        [300, 'Afterhour_Sonntag_Warmup_Selection_2026', ['88 tracks', 'Qobuz playlist']],
        [245, 'Rekordbox Library', HDR_PARTS]] as [w, t, ps], i (i)}
        <div class="g-hdr" style="width: {w}px">
          <PageHeader title={t as string} sub={ps as string[]}>{#snippet actions()}<Button variant="icon" aria-label="Show details (⌘I)">
            <svg viewBox="0 0 16 16"><rect x="2" y="3" width="12" height="10" rx="2" /><path d="M10 3v10" /></svg></Button>{/snippet}</PageHeader>
        </div>
      {/each}
    </div>
  </section>

  <section data-test="gallery-navicon">
    {@render head('NavIcon', 'A page\'s icon: 14 px, 1.3 px stroke, one family, the same spot in both forms (rule 6)')}
    <div class="row top">
      <div class="col tight">
        <span class="cap">full sidebar · Sync selected</span>
        <div class="g-nav g-nav-full" data-test="g-navicon-full">
          {#each NAV_ICONS as n (n)}
            <span class="g-navrow" class:on={n === 'sync'}><NavIcon name={n} /><span>{NAV_NAMES[n]}</span></span>
          {/each}
        </div>
      </div>
      <div class="col tight">
        <span class="cap">rail · the same spot; To-do's count as a pill</span>
        <div class="g-nav g-nav-rail" data-test="g-navicon-rail">
          {#each NAV_ICONS as n (n)}
            <span class="g-navrow" class:on={n === 'sync'} title={NAV_NAMES[n]}><span class="g-glyph"><NavIcon name={n} />{#if n === 'todo'}<span class="g-pill">5</span>{/if}</span></span>
          {/each}
        </div>
      </div>
    </div>
  </section>

  <section data-test="gallery-servicemark">
    {@render head('ServiceMark', 'The service\'s own logo in its own colours, 14 px: the colour rule\'s one exception (D7)')}
    <div class="g-svc" data-test="g-servicemark">
      <span class="cap">service</span><span class="cap">mark</span><span class="cap">dim</span>
      <span class="cap">on the frame · a row, a switched-off row</span>
      {#each LOGO_KEYS as k (k)}
        <span>{LOGO_NAMES[k]}</span>
        <ServiceMark service={k} />
        <ServiceMark service={k} dim />
        <span class="g-nav g-svc-rows">
          <span class="g-navrow"><ServiceMark service={k} /><span>Hard_Bounce</span><span class="g-n">45</span></span>
          <span class="g-navrow g-off"><ServiceMark service={k} /><span>Peak Time</span><span class="g-n">12</span></span>
        </span>
      {/each}
    </div>
  </section>

  <section data-test="gallery-tip">
    {@render head('Tip', 'Names an icon or a cut row on hover: 500 ms, then the next at once; one at a time')}
    <div class="w480"><Segmented label="Which tip shows" options={TIP_SHOW} value={tipShown} onchange={(k) => (tipShown = k)} test="g-tip-which" /></div>
    <div class="row top g-tips">
      <div class="col tight">
        <span class="cap">rail · beside the icon, the shortcut as a cap</span>
        <div class="g-nav g-nav-rail" data-test="g-tip-rail">
          <button type="button" class="g-navrow" aria-label="Dashboard" use:tip={{ text: 'Dashboard', keys: '⌘1', side: 'right' }}><NavIcon name="dashboard" /></button>
          <button type="button" class="g-navrow" aria-label="Sync" use:tip={{ text: 'Sync · syncing, 12 of 40', keys: '⌘2', side: 'right' }}><NavIcon name="sync" /></button>
          <button type="button" class="g-navrow" aria-label="To-do" use:tip={{ text: 'To-do · 5 to look at', keys: '⌘3', side: 'right', show: tipShown === 'rail' }}><NavIcon name="todo" /></button>
          <button type="button" class="g-navrow" aria-label="Playlists" use:tip={{ text: 'Playlists', keys: '⌘4', side: 'right' }}><NavIcon name="playlists" /></button>
        </div>
      </div>
      <div class="col tight g-tip-rows">
        <span class="cap">rows · under it, at the pointer; a whole name gets none</span>
        <div class="g-nav g-tip-col" data-test="g-tip-rows">
          <span class="g-navrow" use:tip={{ text: 'Afterhour_Sonntag_Warmup_Selection_2026', cut: '.g-cut', show: tipShown === 'cut' }}><span class="g-cut">Afterhour_Sonntag_Warmup_Selection_2026</span><span class="g-n">88</span></span>
          <span class="g-navrow" use:tip={{ text: 'Hard_Bounce', cut: '.g-cut' }}><span class="g-cut">Hard_Bounce</span><span class="g-n">45</span></span>
          <span class="g-navrow" use:tip={{ text: 'Rekordbox Library › Music › Old Sets › Bounce\n61 files', show: tipShown === 'crate' }}><span class="g-cut">Bounce · Old Sets</span><span class="g-n">61</span></span>
        </div>
      </div>
    </div>
  </section>

  <section data-test="gallery-summarystrip">
    {@render head('SummaryStrip', 'A collection at a glance along the page, 72 px: share · bar · two link rows')}
    <div class="col">
      {#each STRIPS as [cap, sm, w], i (i)}
        <div class="col tight" style="width: {w}px; max-width: 100%">
          <span class="cap">{cap}</span>
          <SummaryStrip summary={sm} onupgrades={() => toasts.show({ tone: 'info', title: 'Upgrade ready segment' })}
            ontodo={() => toasts.show({ tone: 'info', title: 'Opens To-do' })} />
        </div>
      {/each}
    </div>
  </section>

  <section data-test="gallery-surface">
    {@render head('Surface', 'Everything on screen sits in one: card (padded), list (grouped rows), table (shell); a tone colours only the border (§7)')}
    <div class="grid3">
      <Surface label="Download limits"><p>A card is padded. Longer text is allowed inside a surface, so it can say what the numbers mean.</p></Surface>
      <Surface kind="list" label="Playlists" summary="4 of 5 on" bulk={{ allOff: false, noneOff: false, onall: () => {} }}>
        {@render srows(5, 'Playlist')}
      </Surface>
      <Surface kind="list">{@render srows(2, 'A list without a head · row')}</Surface>
      <!-- hint: a group's one-line hint after its count, the way ListSection prints it; fitLabel: a folder as the label, given in whole folders -->
      <Surface kind="list" label="Duplicates" summary="2" hint="the same song more than once">{@render srows(2, 'Group')}</Surface>
      <Surface label="/Volumes/Example Drive/Crates/Old" fitLabel="/Volumes/Example Drive/Crates/Old" summary="In your playlists"><p>A folder as the label</p></Surface>
      <Surface label="Up to date" tone="good"><p>5 playlists · 49 tracks</p></Surface>
      <Surface tone="warn" label="Could be better"><p>Warn tone</p></Surface>
      <Surface tone="problem" label="Needs you" summary="3"><p>Problem tone</p></Surface>
      <!-- grow: in a column of fixed height it takes the rest, rows scroll inside with a faded end and a half-row peek -->
      <div class="col grow-demo" data-test="g-surface-grow">
        <Surface label="Above it" summary="natural height"><p>Fixed</p></Surface>
        <Surface kind="list" label="Folders" summary="20 playlists" grow={{ rows: 20 }}>{@render srows(20, 'Folder')}</Surface>
      </div>
      <Surface kind="list" label="Hard_Bounce" summary="2 of 3 ticked" foldable bind:open={() => !folded, (v) => (folded = !v)}
        bulk={{ all: 'Tick all', allOff: false, noneOff: false, onall: () => {} }}>{@render srows(3, 'Track')}</Surface>
      <!-- a table with a fixed column head: SortHeaders keep their natural width, the rows scroll under the head -->
      <div class="col grow-demo span2" data-test="g-surface-columns">
        <Surface kind="table" grow={{ rows: 12 }}>
          {#snippet columns()}
            <!-- Playlist has no onsort: a static head, the same words as a label (no button, no aria-sort) -->
            <div class="gtr"><SortHeader label="Track" sorted={gSorted('track')} onsort={() => gSortBy('track')} />
              <SortHeader label="Playlist" test="g-sort-static" />
              <SortHeader label="Length" align="end" sorted={gSorted('length')} onsort={() => gSortBy('length')} /></div>
          {/snippet}
          {#each Array.from({ length: 12 }, (_, i) => i) as i (i)}
            <div class="gtr row-line"><span>Track {i + 1}</span><span>{i % 3 ? 'Hard_Bounce' : 'Peak Time'}</span><span
              class="num">{3 + (i % 3)}:{10 + i}</span></div>
          {/each}
        </Surface>
      </div>
      <div class="span2">
        <Surface kind="table" label="Table shell">
          <table class="tbl">
            <thead><tr><th>Track</th><th>Folder</th><th class="num">Quality</th></tr></thead>
            <tbody>
              {#each [lossless, weak, fakeQ] as r (r.track_id)}<tr><td>{r.artist} – {r.title}</td><td>{r.folder}</td>
                <td class="num"><QualityBadge quality={r.quality} label={r.quality_label} /></td></tr>{/each}
            </tbody>
          </table>
        </Surface>
      </div>
    </div>
  </section>

  <section data-test="gallery-button">
    {@render head('Button', 'filled: the one main action of a screen, or of a dialog inside it; primary (orange outline): a forward step that is not the main one; secondary: other actions; link: actions inside text and rows; icon: a row action; natural width, wide only in a panel foot (§4, §7, §11)')}
    <div class="spec">
      <span class="cap">filled</span>
      <div class="row"><Button variant="filled">Start sync</Button><span class="note">the screen's one main action (data-primary); wide: see Panel</span></div>
      <span class="cap">secondary</span>
      <div class="row"><Button>Secondary</Button><Button size="sm">Small</Button>
        <div bind:this={focusMe} class="inline"><Button>Focused</Button></div>
        <Button>{#snippet icon()}▶{/snippet}With icon</Button></div>
      <span class="cap">primary · danger</span>
      <div class="row"><Button variant="primary">Primary</Button><Button size="sm" variant="primary">Small primary</Button>
        <Button variant="danger">None of these</Button></div>
      <span class="cap">link</span>
      <div class="row"><Button variant="link">+ Add a playlist</Button><Button variant="link" href="#/limits">Download limits →</Button>
        <Button variant="link" href="https://example.com">Full report ↗</Button><Button variant="link" size="sm">Fix →</Button>
        <Button variant="link" href="#/todo" disabled title="Wait until the current change is finished.">Review →</Button>
        <Button variant="link" muted size="sm">Tick all</Button><Button variant="link" muted size="sm" disabled>None (muted, off)</Button></div>
      <span class="cap">icon</span>
      <div class="row"><NeverButton name="this track" onclick={() => {}} />
        <NeverButton name="this track" blocked="Wait until the current change is finished." onclick={() => {}} />
        <span class="note">a drawn 16 px SVG, red on hover when destructive · off</span></div>
      <span class="cap">icon toggle</span>
      <div class="row"><Button variant="icon" aria-label="Show details" tip={{ text: 'Show details', keys: '⌘I' }}>{@render gDetailsGlyph()}</Button>
        <Button variant="icon" pressed aria-label="Hide details" tip={{ text: 'Hide details', keys: '⌘I' }}>{@render gDetailsGlyph()}</Button>
        <Button variant="icon" switchedOff="Show details" aria-label="Show details"
          tip={{ text: "Hidden by you: selecting a track won't open them", keys: '⌘I' }}>{@render gDetailsGlyph(true)}</Button>
        <span class="note">off · on (pressed) · switched off by hand (switchedOff: words, dashed outline, glyph struck through)</span></div>
      <span class="cap">busy</span>
      <div class="row"><Button variant="primary" busy busyLabel="Swapping…">Swap</Button><Button size="sm" busy>Busy small</Button></div>
      <span class="cap">disabled</span>
      <div class="row"><Button variant="primary" disabled title="Wait until the current change is finished.">Disabled (tooltip)</Button>
        <Button disabled>Disabled</Button></div>
    </div>
  </section>

  <section data-test="gallery-toggles">
    {@render head('ToggleGroup · ToggleRow · Switch', 'Every on/off choice: "N of M on", All · None, a search from 7 rows for the user\'s own lists; never loose pills (§4, §11)')}
    <div class="grid3">
      <div class="col">
        <span class="cap">3 rows</span>
        <ToggleGroup label="What to do" items={kinds} search={false} test="g-kinds" rowTest="g-kind"
          onchange={(k, on) => (kinds = flip(kinds, k, on))} onall={(on, keys) => (kinds = setOn(kinds, keys, on))}>
          {#snippet lead(item)}<span class="toggle-icon">{#if isKindKey(item.key)}<KindIcon kind={item.key} />{/if}</span>{/snippet}
        </ToggleGroup>
        <span class="cap">no counts</span>
        <ToggleGroup label="Sources" items={sources} test="g-sources"
          onchange={(k, on) => (sources = flip(sources, k, on))} onall={(on, keys) => (sources = setOn(sources, keys, on))} />
      </div>
      <div class="col">
        <span class="cap">14 rows · search, scroll, end fade</span>
        <div class="fillbox">
          <ToggleGroup label="Playlists" items={pls} grow test="g-pls" rowTest="g-pl"
            onchange={(k, on) => (pls = flip(pls, k, on))} onall={(on, keys) => (pls = setOn(pls, keys, on))}>
            {#snippet lead(item)}<Cover url={coverUri(Number(item.key.slice(1)) % 6)} seed={item.key} size={24} />{/snippet}
          </ToggleGroup>
        </div>
        <span class="cap">7 rows the app defines · search off</span>
        <ToggleGroup label="What to do" items={allKinds} search={false} test="g-allkinds"
          onchange={(k, on) => (allKinds = flip(allKinds, k, on))} onall={(on, keys) => (allKinds = setOn(allKinds, keys, on))}>
          {#snippet lead(item)}<span class="toggle-icon">{#if isKindKey(item.key)}<KindIcon kind={item.key} />{/if}</span>{/snippet}
        </ToggleGroup>
      </div>
      <div class="col">
        <span class="cap">all off</span>
        <ToggleGroup label="Playlists" items={allOff} test="g-alloff"
          onchange={(k, on) => (allOff = flip(allOff, k, on))} onall={(on, keys) => (allOff = setOn(allOff, keys, on))} />
        <span class="cap">40 rows · All after a search (allMax 25) · found by artist</span>
        <div class="fillbox">
          <ToggleGroup label="In the sidebar" items={crates} grow allMax={25} placeholder="Search Albums…" test="g-crates"
            onchange={(k, on) => (crates = flip(crates, k, on))} onall={(on, keys) => (crates = setOn(crates, keys, on))} />
        </div>
        <span class="cap">disabled (a change is running)</span>
        <ToggleGroup label="Locked" items={kinds} disabled disabledReason="Not while a sync runs." search={false} test="g-locked" onchange={() => {}} onall={() => {}}>
          {#snippet lead(item)}<span class="toggle-icon">{#if isKindKey(item.key)}<KindIcon kind={item.key} />{/if}</span>{/snippet}
        </ToggleGroup>
        <span class="cap">empty</span>
        <ToggleGroup label="Empty" items={[]} test="g-empty" onchange={() => {}} onall={() => {}} />
        <span class="cap">a single setting with its detail (sub wraps) · locked with the reason</span>
        <Surface kind="list" data-test="g-toggle-sub">
          <ToggleRow item={{ key: 'r', label: 'Rename the folder on disk too', on: subOn }} sub="One folder move instead of 7 file moves."
            onchange={(_k, on) => (subOn = on)} />
          <ToggleRow item={{ key: 'x', label: 'Rename the folder on disk too', on: false }} disabled
            sub="A folder called Powertrance_2026 is already in your Library." onchange={() => {}} />
        </Surface>
        <span class="cap">one ToggleRow in a list</span>
        <Surface kind="list" label="A single setting">
          <ToggleRow item={auto} test="g-auto" onchange={(_k, on) => (auto = { ...auto, on })} />
        </Surface>
        <span class="cap">Switch alone (presentational)</span>
        <div class="row"><Switch on label="on" /><Switch on={false} label="off" /><Switch on disabled label="on, disabled" />
          <Switch on={false} disabled label="off, disabled" /></div>
      </div>
    </div>
  </section>

  <section data-test="gallery-segmented">
    {@render head('Segmented', 'One choice of up to 6 on one line, never wrapping; the rest in More, the chosen one always in view; replaces filter Chips (§7, §11)')}
    <div class="spec w800">
      <span class="cap">5 options</span>
      <Segmented label="How many" options={HOW_MANY} value={howMany} onchange={(k) => (howMany = k)} test="g-howmany" />
      <span class="cap">none chosen</span>
      <Segmented label="How many (hand-picked: none chosen)" options={HOW_MANY} value="custom" onchange={(k) => (howMany = k)} test="g-custom" />
      <span class="cap">counts and dots</span>
      <Segmented label="Quality" options={QUALITY_FILTER} value={qf} onchange={(k) => (qf = k)} test="g-quality" />
      <span class="cap">a count of 0 · no dot</span>
      <Segmented label="Quality (nothing weak, fake or to upgrade)" options={QUALITY_NONE} value="all" onchange={() => {}} test="g-quality-zero" />
      <span class="cap">8 options · chosen in More</span>
      <Segmented label="Folder" options={FOLDERS} value={folder} onchange={(k) => (folder = k)} test="g-folder" />
      <span class="cap">tight · 260 px strip</span>
      <div class="w260"><Segmented label="Show" options={NARROW} value={narrow} onchange={(k) => (narrow = k)} test="g-narrow" /></div>
    </div>
  </section>

  <section data-test="gallery-statcard">
    {@render head('StatCard', 'A number plus a visual for every quantity: 30 px number, unit, label, the bar under it (§4, §7)')}
    <div class="grid3 w800">
      <StatCard value={66} label="tracks" valueTest="g-stat-count" />
      <StatCard value="~75" unit="min" label="run time" />
      <StatCard value={null} label="not known yet" />
      <StatCard value={37} unit="of 80" label="Qobuz today"><ProgressBar value={37 / 80} label="Qobuz today" /></StatCard>
      <StatCard value={226} label="lossless"><ProgressBar value={226 / 306} tone="lossless" label="Lossless share" /></StatCard>
      <StatCard value="12 345 678" unit="tracks" label="a number too long for its card shortens" />
      <StatCard value="16.0" unit="kHz" wrap label="where the highs end · a lossy file inside the AIFF, shown whole on a second line" />
      <div class="span3"><StatCard value={2} label="tracks added"><QualityBar by_quality={{ lossless: 1, good_lossy: 1, weak: 0, fake: 0, missing: 0 }} legend /></StatCard></div>
    </div>
  </section>

  <section data-test="gallery-daybar">
    {@render head('DayBar', 'Today solid, later striped; day mode adds used (filled) and left (outline); 280 ms because it answers the user; a segment is never narrower than its label (§7, §11)')}
    <div class="col w360">
      {#each DAY_CASES as [name, input] (name)}
        <div class="col tight"><span class="cap">{name}</span><DayBar {input} data-test={dayTest(name)} /></div>
      {/each}
      <Surface label="This run · moves with the amount">
        <DayBar input={live} data-test="g-day-live" />
        <Segmented label="How many" options={AMOUNTS} value={amount} onchange={(k) => (amount = k)} test="g-amount" />
      </Surface>
    </div>
  </section>

  <section data-test="gallery-progress">
    {@render head('ProgressBar', 'Its pace says who moved it: value (on its own, 420 ms), reply (the user\'s click, 280 ms), live (a job, linear); without a value it sweeps (§6, §11)')}
    <div class="spec w640">
      <span class="cap">move all three</span>
      <Segmented label="Value" options={SHARES} value={share} onchange={(k) => (share = k)} test="g-share" />
      <span class="cap">pace="value"</span><ProgressBar value={Number(share)} label="value pace" />
      <span class="cap">pace="reply"</span><ProgressBar value={Number(share)} pace="reply" label="reply pace" />
      <span class="cap">pace="live"</span><ProgressBar value={Number(share)} pace="live" label="live pace" />
      <span class="cap">0 · full · muted</span>
      <div class="col tight"><ProgressBar value={0} /><ProgressBar value={1} tone="lossless" /><ProgressBar value={0.38} tone="muted" /></div>
      <span class="cap">indeterminate</span><ProgressBar value={null} />
    </div>
  </section>

  <section data-test="gallery-qualitybar">
    {@render head('QualityBar', 'The quality split as one bar in the quality colours; with its legend when it stands as a card\'s visual (§4, §11)')}
    <div class="spec w640">
      <span class="cap">legend</span><QualityBar by_quality={{ lossless: 40, good_lossy: 6, weak: 3, fake: 1, missing: 2 }} legend />
      <span class="cap">4 px</span><QualityBar by_quality={{ lossless: 8, good_lossy: 2, weak: 0, fake: 0, missing: 1 }} height={4} />
      <span class="cap">waiting</span><QualityBar by_quality={null} legend />
      <span class="cap">nothing yet</span><QualityBar by_quality={{ lossless: 0, good_lossy: 0, weak: 0, fake: 0, missing: 0 }} />
    </div>
  </section>

  <section data-test="gallery-deltabar">
    {@render head('DeltaBar', 'A signed change either side of a centre line, one scale for the whole list: gains right in the accent, losses left in grey (§4; Playlists\' move view)')}
    <div class="spec w360">
      {#each [27, -4, -3, -20, 1, 0] as v (v)}
        <span class="cap">{v > 0 ? `+${v}` : v}</span><DeltaBar value={v} max={27} />
      {/each}
    </div>
  </section>

  <section data-test="gallery-selectcard">
    {@render head('SelectCard', 'One of a few things to pick, as a card that shows its state where you click: picked (accent edge), not set up (dashed); ← / → between them (§4; Download limits\' services)')}
    <div class="g-cards w800" role="tablist" aria-label="Services">
      <SelectCard title="Qobuz" selected={pickedCard === 'q'} onclick={() => (pickedCard = 'q')}>
        <span class="cap">37 of 80 today</span><ProgressBar value={37 / 80} height={6} />
        <span class="cap g-st"><StatusMark tone="warn" />2 new warnings</span>
      </SelectCard>
      <SelectCard title="YouTube Premium" selected={pickedCard === 'y'} onclick={() => (pickedCard = 'y')}>
        <span class="cap">4 of 40 today</span><ProgressBar value={4 / 40} height={6} />
        <span class="cap g-st"><StatusMark tone="good" />All good</span>
      </SelectCard>
      <SelectCard title="SoundCloud Go+" off selected={pickedCard === 's'} onclick={() => (pickedCard = 's')}>
        <span class="cap">not set up</span>
      </SelectCard>
    </div>
  </section>

  <section data-test="gallery-riskscale">
    {@render head('RiskScale · StatusMark', 'A number on five equal risk steps, green · yellow · red (risk colours, §2), the handle 1:1 with the pointer, the saved value as a tick; a state as colour plus shape: ✓ ! ▪, the quiet ✓ for a check that passed, and the dashed none for nothing set up')}
    <div class="col w360">
      <RiskScale zones={GALLERY_ZONES} value={riskValue} saved={60} max={150} label="Daily limit" onchange={(v) => (riskValue = v)} />
      <span class="cap">{riskValue} a day</span>
      <div class="g-marks"><StatusMark tone="good" /><StatusMark tone="warn" /><StatusMark tone="problem" /><StatusMark tone="good" quiet /><StatusMark tone="none" /><StatusMark tone="back" /></div>
    </div>
  </section>

  <section data-test="gallery-sourceladder">
    {@render head('SourceLadder', 'Where the music comes from, best first: a rung lit in its quality colour when the download uses it, greyed with the chain dashed past it when not; one Hint says what the setup means (Settings, Setup)')}
    <div class="g-ladders">
      {#each LADDERS as [name, key, d] (key)}
        <div class="col tight"><span class="cap">{name}</span>
          <SourceLadder downloads={d} onpick={(row) => (ladderPicked = `${name}: ${row}`)} test="g-ladder-{key}" /></div>
      {/each}
    </div>
    <div class="col tight w372"><span class="cap">compact, Setup's 372 px column (Qobuz only)</span>
      <SourceLadder downloads={LADDERS[1][2]} compact onpick={(row) => (ladderPicked = `compact: ${row}`)} test="g-ladder-compact" /></div>
    <span class="cap" data-test="g-ladder-picked">{ladderPicked ? `picked ${ladderPicked}` : 'Qobuz and the account chips pick their row'}</span>
  </section>

  <section data-test="gallery-accountpanel">
    {@render head('AccountPanel', 'One download login, the same in Settings (a Panel: what it gives, its state, the sign-in, the one filled action in the foot) and Setup (compact cards, filled only where Setup says); presentational, driven by AccountFlow')}
    <div class="g-accounts">
      {#each ACCOUNT_PANELS as p (p.key)}
        <div class="col tight"><span class="cap w320">{p.cap}</span>
          <div class="panelbox" style="height: 600px">
            <AccountPanel service={p.service} downloads={p.d} phase={p.phase} actions={G_ACTIONS} logins={G_LOGINS}
              disabledWhy={p.why ?? null} busy={p.busy} bind:stepsOpen={accSteps[p.key]} test="g-acc-{p.key}" />
          </div>
        </div>
      {/each}
    </div>
    <span class="cap">compact, Setup's 520 px column: Qobuz carries the screen's one filled button, the others are primary</span>
    <div class="col w520" data-test="g-acc-compact">
      <AccountPanel compact filled service="qobuz" downloads={gDl({ qobuz: qOff })} phase={{ kind: 'form' }} actions={G_ACTIONS}
        test="g-acc-c-qobuz" />
      <AccountPanel compact service="youtube" downloads={gDl({ qobuz: qOff })} phase={found} actions={G_ACTIONS} logins={G_LOGINS}
        test="g-acc-c-youtube" />
      <AccountPanel compact service="soundcloud" downloads={gDl({ soundcloud: { ...ytOn } })} phase={{ kind: 'working' }}
        actions={G_ACTIONS} logins={G_LOGINS} test="g-acc-c-soundcloud" />
    </div>
    <span class="cap" data-test="g-acc-asked">{accAsked ? `asked: ${accAsked}` : 'the buttons say here what they asked the flow for'}</span>
  </section>

  <section data-test="gallery-explain">
    {@render head('Hint · InfoTip · NoteCard', 'The only three ways to put explanation on screen: one line under its control, more behind an ⓘ, a note of up to three lines (§6, §7)')}
    <div class="grid2 w800">
      <Surface label="Hint">
        <div class="col tight start"><Button size="sm">Stop safely</Button><Hint text="Finishes the track it is on, then stops." /></div>
        <div class="col tight start"><Button size="sm">Read Spotify</Button>
          <Hint text="A hint that runs longer than one line is cut with an ellipsis, and the full text shows on hover over it." /></div>
        <div class="col tight start"><Button size="sm">Stop safely</Button>
          <Hint tone="problem" text="tone problem: the error your action just caused, the backend's words" data-test="g-hint-problem" /></div>
      </Surface>
      <Surface label="InfoTip">
        <div class="row tight-row"><span>Daily limit · 66</span>
          <InfoTip label="About the daily limit" data-test="g-tip">
            <p>Qobuz allows about 66 downloads a day. Tracks beyond that wait for the next sync.</p>
            <p>Bought files and files already on disk don't count.</p>
          </InfoTip></div>
        <div class="row tight-row"><span>In a dialog</span>
          <Button size="sm" onclick={() => (tipDialogOpen = true)} data-test="g-tip-dialog-open">Open dialog</Button></div>
      </Surface>
      <Surface kind="list" label="An ⓘ on consecutive rows" style="--row-cols: minmax(0, 1fr) 112px">
        {#each TIP_ROWS as [svc, value, tip], i (svc)}
          <ListRow>
            {#snippet name()}{svc}{/snippet}
            {#snippet trailing()}<span class="tipcell">{value}<InfoTip label="About {svc}" data-test="g-stack-{i}"><p>{tip}</p></InfoTip></span>{/snippet}
          </ListRow>
        {/each}
      </Surface>
      <div class="col">
        <NoteCard data-test="g-note-info">YouTube Music, SoundCloud and YouTube have no daily limit. Downloading from them breaks their terms, so Discjockey keeps their pace slow.</NoteCard>
        <NoteCard tone="warn" title="Downloads start tomorrow">Today's Qobuz limit is reached. This run only adds bought files; the 77 ticked tracks wait for the next days.</NoteCard>
        <NoteCard tone="problem" title="The sync stopped">Qobuz refused 3 downloads in a row, so Discjockey paused to protect your account. Nothing in your library was changed.</NoteCard>
        <NoteCard tone="warn" title="Title only: no text under it" />
      </div>
    </div>
    <Dialog bind:open={tipDialogOpen} title="Download limits" width={560}>
      <Surface kind="list" style="--row-cols: minmax(0, 1fr) 112px">
        {#each TIP_ROWS as [svc, value, tip], i (svc)}
          <ListRow>
            {#snippet name()}{svc}{/snippet}
            {#snippet trailing()}<span class="tipcell">{value}<InfoTip label="About {svc}" data-test="g-dtip-{i}"><p>{tip}</p></InfoTip></span>{/snippet}
          </ListRow>
        {/each}
      </Surface>
      {#snippet footer()}<Button variant="filled" onclick={() => (tipDialogOpen = false)}>Done</Button>{/snippet}
    </Dialog>
  </section>

  <section data-test="gallery-listrow">
    {@render head('ListRow', 'The row grid every list uses: the list owns the columns, the optional one shows from 680 px list width; an off row stays readable (§7, §11)')}
    {#snippet tickList(test: string, label: string)}
      <Surface kind="list" {label} summary="{lrTicked.size} of {LR_ROWS.length} ticked" style={LR_COLS} data-test={test}>
        {#each LR_ROWS as r (r.id)}
          {@const on = lrTicked.has(r.id)}
          <ListRow off={!on} checked={on} onclick={() => lrToggle(r.id)} title="{r.artist} – {r.title}" data-track={r.id}>
            {#snippet lead()}<Tick {on} /><Cover url={null} seed={r.id} size={28} />{/snippet}
            {#snippet name()}{r.artist} – {r.title}{/snippet}
            {#snippet optional()}<Why tag={r.tag} next={r.next && on} />{/snippet}
            {#snippet trailing()}<WhyMark kind={r.kind} next={r.next && on} /><NeverButton name="{r.artist} – {r.title}" onclick={() => {}} />{/snippet}
          </ListRow>
        {/each}
      </Surface>
    {/snippet}
    <div class="col">
      <span class="cap">640 px list · the why is a mark before ⊘: kind icon, yellow "next sync" dot (Sync's WhyMark, not a block)</span>
      <div class="w640">{@render tickList('g-rows-narrow', 'Ticks · narrow')}</div>
      <span class="cap">800 px list · the why column in words</span>
      <div class="w800">{@render tickList('g-rows-wide', 'Ticks · wide')}</div>
      <div class="grid2 w800">
        <div class="col tight"><span class="cap">one of many · selected (Vatoz Locoz) · disabled (Mira Volt: name and cover muted, no hover or click while a change runs)</span>
          <Surface kind="list" label="One of many" style="--row-cols: 28px minmax(0, 1fr) 72px">
            {#each [lossless, weak, fakeQ, good] as r (r.track_id)}
              <ListRow selected={lrChosen === r.track_id} onclick={() => (lrChosen = r.track_id)} disabled={r === good}
                title="{r.artist} – {r.title}">
                {#snippet lead()}<Cover url={null} seed={r.track_id} size={28} />{/snippet}
                {#snippet name()}{r.artist} – {r.title}{/snippet}
                {#snippet trailing()}<QualityBadge quality={r.quality} label={r.quality_label} />{/snippet}
              </ListRow>
            {/each}
          </Surface></div>
        <div class="col tight"><span class="cap">no button · second line (sub) · off</span>
          <Surface kind="list" label="Could be better" style="--row-cols: minmax(0, 1fr) 56px">
            <ListRow>{#snippet name()}Lossy that could be lossless{/snippet}{#snippet sub()}Qobuz has 9 of them in 16-bit{/snippet}{#snippet trailing()}12{/snippet}</ListRow>
            <ListRow>{#snippet name()}Not found anywhere{/snippet}{#snippet sub()}Searched Qobuz, YouTube Music, SoundCloud and YouTube{/snippet}{#snippet trailing()}<Button variant="link" size="sm">Fix →</Button>{/snippet}</ListRow>
            <ListRow off>{#snippet name()}Bought files (off){/snippet}{#snippet sub()}Nothing to do{/snippet}{#snippet trailing()}0{/snippet}</ListRow>
          </Surface></div>
        <div class="col tight"><span class="cap">wrap · the sub-line wraps (a destination or a reason read whole)</span>
          <Surface kind="list" label="Can't move" style="--row-cols: 52px minmax(0, 1fr)" data-test="g-rows-wrap">
            <ListRow wrap>{#snippet lead()}<StatusMark tone="warn" /><Cover url={null} seed="w1" size={28} />{/snippet}{#snippet name()}Bounce Brigade – Rush Hour{/snippet}{#snippet sub()}A file with this name is already in 03_06_2026/not_lossless{/snippet}</ListRow>
            <ListRow wrap>{#snippet lead()}<Tick on /><Cover url={null} seed="w2" size={28} />{/snippet}{#snippet name()}Remo Rush – Kick it Hard{/snippet}{#snippet sub()}Elsewhere/not_lossless → Hard_Bounce/not_lossless{/snippet}</ListRow>
          </Surface></div>
      </div>
    </div>
  </section>

  <section data-test="gallery-problemcard">
    {@render head('ProblemCard', 'A problem-tone Surface card marked data-note; compact keeps no box; the caller\'s recovery sits in its actions (§11)')}
    <div class="grid2">
      {#each PROBLEM_KINDS as k (k)}
        <ProblemCard kind={k} message="The backend's message, shown verbatim." onretry={() => toasts.show({ tone: 'info', title: 'Retry' })}
          report={k === 'crashed' ? { run_id: '2026-10-16_141111' } : null} />
      {/each}
      <ProblemCard kind="crashed" sync message="The sync stopped unexpectedly. Everything done up to then is saved, and the next sync carries on from there." report={{ run_id: '2026-10-16_141111' }} />
      <ProblemCard kind="crashed" sync message="The sync stopped unexpectedly. No report could be written, but everything done up to then is saved.">
        {#snippet actions()}<Button size="sm" onclick={() => toasts.show({ tone: 'info', title: 'Show reports folder' })}>Show reports folder</Button>{/snippet}
      </ProblemCard>
      <Surface label="compact, inside a card"><ProblemCard kind="login_expired" message="" compact /></Surface>
      <ProblemCard kind="not_set_up" service="qobuz" message="Connect Qobuz first." />
      <Surface label="service, compact (the add row)"><ProblemCard kind="not_set_up" service="spotify"
        message="Connect Spotify first." compact /></Surface>
    </div>
  </section>

  <section data-test="gallery-emptystate">
    {@render head('EmptyState', 'A short centred message on balanced lines (§11)')}
    <div class="grid3">
      {#each EMPTY_KINDS as k (k)}<Surface><EmptyState kind={k} /></Surface>{/each}
      <Surface><EmptyState title="The plan shows here when Spotify is read." /></Surface>
    </div>
  </section>

  <section data-test="gallery-skeleton">
    {@render head('Skeleton · Spinner', 'A placeholder has its content\'s shape and height, so nothing moves when the content draws (§6, §11)')}
    <div class="spec w640">
      <span class="cap">lines</span><Skeleton lines={3} />
      <span class="cap">shape="card"</span><Skeleton shape="card" height={120} />
      <span class="cap">Spinner</span><div class="row"><Spinner /><Spinner size={18} /></div>
    </div>
  </section>

  <!-- ─── shared components §7 doesn't rework yet ─── -->

  <header class="group"><h2>Other components</h2>
    <p class="rule">Shared and in use, not reworked by the design system yet (§7 doesn't list them); phase 2 reworks each with its page.</p></header>

  <section data-test="gallery-writebutton">
    {@render head('WriteButton', 'A Button that is off, with the reason, while a change runs or the terminal holds the library')}
    <div class="row">
      <WriteButton variant="primary">Swap</WriteButton>
      <WriteButton busy busyLabel="Hiding…">Hide</WriteButton>
      <span class="note">FAKE → Console starts shows the off state.</span>
    </div>
  </section>

  <section data-test="gallery-badge">
    {@render head('Badge · QualityBadge · AwayTag · ExternalLink', 'A short state or value in the quality colours; why a file isn\'t there to play, in a row\'s quality column (the panel\'s line as its tooltip); a link that leaves the app')}
    <div class="row"><Badge tone="lossless" text="LOSSLESS" /><Badge tone="good_lossy" text="20.0 kHz" /><Badge tone="weak" text="16.0 kHz" />
      <Badge tone="fake" text="FAKE · 16.0 kHz" /><Badge tone="missing" text="NOT FOUND" /><Badge tone="accent" text="↑" />
      <Badge tone="muted" text="OFFLINE" /><Badge tone="other" text="OTHER" /></div>
    <div class="row">
      <QualityBadge quality="lossless" label="LOSSLESS" /><QualityBadge quality="good_lossy" label="20.0 kHz" />
      <QualityBadge quality="weak" label="16.0 kHz" upgrade /><QualityBadge quality="fake" label="FAKE · 16.0 kHz" />
      <QualityBadge quality="missing" label="NOT FOUND" /><QualityBadge quality="lossless" label="LOSSLESS" checked={false} />
    </div>
    <div class="row" data-test="g-away-tag"><AwayTag state="offline" /><AwayTag state="folder_missing" /><AwayTag state="file_missing" /></div>
    <span class="cap">quiet: a state with no badge yet, as words in the badge's place (a playlist song waiting for its file)</span>
    <div class="row" data-test="g-badge-quiet"><Badge tone="quiet" text="Waiting" tip="Downloads at the next sync" />
      <Badge tone="quiet" text="Switched off" /><Badge tone="missing" text="NOT FOUND" /></div>
    <span class="cap">muted with <code>more</code> (Library's Playlist column): a name as the user spelled it, "+n" for the others; in a narrow cell the name gives way, the +n never</span>
    <div class="row" data-test="g-badge-more"><Badge text="Hard_Bounce" more={2} /><Badge text="Peak Time" more={0} />
      <span class="cell140"><Badge text="Afterhour_Sonntag_Warmup_Classics" more={3} /></span></div>
    <span class="cap">MiddleText with <code>sep="›"</code> (a place: whole folders give way first, then characters; the separators quiet)</span>
    <div class="col" data-test="g-middle-sep">
      <span class="cell320"><MiddleText text="Rekordbox Library › Old Sets › Bounce › 2019" sep="›" /></span>
      <span class="cell200"><MiddleText text="Rekordbox Library › Old Sets › Bounce › 2019" sep="›" /></span>
      <span class="cell140"><MiddleText text="Rekordbox Library › Old Sets › Bounce › 2019" sep="›" /></span>
    </div>
    <div class="row"><ExternalLink href="https://www.beatport.com/search?q=Armin+Hermann+Get+Naughty" label="Beatport" />
      <ExternalLink href="https://bandcamp.com">Bandcamp</ExternalLink></div>
  </section>

  <section data-test="gallery-cover">
    {@render head('Cover', 'image · none · failed: a failed or missing cover is a placeholder drawn from the track id')}
    <div class="row">
      <Cover url={coverUri(0)} seed="t1" size={18} /><Cover url={coverUri(1)} seed="t1" size={28} /><Cover url={coverUri(2)} seed="t2" size={40} />
      <Cover url={null} seed="t3" size={64} /><Cover url="data:image/png;base64,AAAA" seed="t4" size={64} /><Cover url={coverUri(3)} seed="t5" size={120} />
    </div>
    <span class="cap">playable (Library's rows): ▶ on hover or with hint, ❚❚ while playing; a click plays or pauses</span>
    <div class="row" data-test="g-cover-play">
      <Cover url={coverUri(1)} seed="c1" size={22} onplay={() => (gPlaying = gPlaying === 'c1' ? null : 'c1')} playing={gPlaying === 'c1'} name="Track one" />
      <Cover url={null} seed="c2" size={22} onplay={() => (gPlaying = gPlaying === 'c2' ? null : 'c2')} playing={gPlaying === 'c2'} name="Track two" />
      <Cover url={coverUri(2)} seed="c3" size={22} hint onplay={() => (gPlaying = gPlaying === 'c3' ? null : 'c3')} playing={gPlaying === 'c3'} name="Track three" />
    </div>
    <span class="cap">empty: no file yet (a playlist song waiting or not found), a dashed outline in the cover's place, no ▶</span>
    <div class="row" data-test="g-cover-empty"><Cover url={null} seed="e1" size={22} empty /><Cover url={null} seed="e2" size={64} empty /></div>
  </section>

  <section data-test="gallery-listsection">
    {@render head('ListSection', 'A group\'s head among one list\'s rows (name · count · hint): it sticks while its rows pass, so one anchored list holds every group and a long one never pushes the rest off screen (§3, §7)')}
    <div class="col grow-demo w640" data-test="g-list-section">
      <Surface kind="list" label="All to-dos" style="--row-cols: 28px minmax(0, 1fr) auto" grow={{ rows: 9, tall: true }}>
        {#each [{ label: 'Not found', hint: 'nothing usable anywhere', rows: [missing, missing, missing] }, { label: 'Weak (≤ 17 kHz)', hint: 'audibly lossy', rows: [weak, weak] }, { label: 'Fake lossless', hint: 'a lossy file inside the FLAC', rows: [fakeQ] }] as g, gi (g.label)}
          <ListSection label={g.label} summary={String(g.rows.length)} hint={g.hint} />
          {#each g.rows as r, ri (ri)}
            <ListRow selected={gi === 1 && ri === 0} onclick={() => {}} title="{r.artist} – {r.title}">
              {#snippet lead()}<Cover url={null} seed={r.track_id + ri} size={28} />{/snippet}
              {#snippet name()}{r.artist} – {r.title}{/snippet}
              {#snippet sub()}{r.folder}{/snippet}
              {#snippet trailing()}<Badge tone={r.quality} text={r.quality_label} />{/snippet}
            </ListRow>
          {/each}
        {/each}
      </Surface>
    </div>
  </section>

  <section data-test="gallery-listline">
    {@render head('ListLine', 'An empty group\'s one quiet line among a list\'s rows, at a section head\'s height')}
    <div class="col w640" data-test="g-list-line">
      <Surface kind="list" label="Hard_Bounce" summary="0 songs">
        <ListLine text="This playlist is empty." />
        <ListSection label="Also in this folder" summary="2" hint="files in Hard_Bounce that aren't in this playlist" />
        {#each [weak, fakeQ] as r, ri (ri)}
          <ListRow onclick={() => {}} title="{r.artist} – {r.title}">
            {#snippet lead()}<Cover url={null} seed={r.track_id + ri} size={28} />{/snippet}
            {#snippet name()}{r.artist} – {r.title}{/snippet}
            {#snippet trailing()}<Badge tone={r.quality} text={r.quality_label} />{/snippet}
          </ListRow>
        {/each}
      </Surface>
    </div>
  </section>

  <section data-test="gallery-listsection-chrome">
    {@render head('ListSection · stuck', 'A stuck head is opaque and square, a hairline on the edge rows pass (rule 10)')}
    <div class="row top">
      <div class="col tight">
        <span class="cap">on the frame, sticking at both ends: top stuck, foot stuck</span>
        <div class="g-chrome-list" use:scrollAt={200} data-test="g-section-chrome">
          {#each [['Favourites', 4], ['Playlists', 12], ['Folders', 6]] as [name, n] (name)}
            <ListSection label={name as string} summary={String(n)} stick="both" on="chrome" />
            {#each Array(n as number) as _, i (i)}<div class="g-crow">{name} row {i + 1}</div>{/each}
          {/each}
        </div>
      </div>
      <div class="col tight">
        <span class="cap">fold: Playlists folded, stuck; Folders right below it, not stuck: no line</span>
        <div class="g-chrome-list" use:scrollAt={149} data-test="g-section-chrome-folded">
          {#each [['Favourites', 4], ['Playlists', 12], ['Folders', 10]] as [name, n] (name)}
            {@const open = !gFolded.includes(name as string)}
            <ListSection label={name as string} summary={String(n)} stick="both" on="chrome"
              fold={{ open, toggle: () => { gFolded = open ? [...gFolded, name as string] : gFolded.filter((x) => x !== name); } }} />
            {#if open}{#each Array(n as number) as _, i (i)}<div class="g-crow">{name} row {i + 1}</div>{/each}{/if}
          {/each}
        </div>
      </div>
    </div>
  </section>

  <section data-test="gallery-trackrow">
    {@render head('TrackRow · KeyValue', 'To-do and Library rows until phase 2 re-bases TrackRow on ListRow (§7)')}
    <div class="col w640">
      <Surface kind="list">
        <TrackRow track={lossless} selected={selected === 't1'} onclick={() => (selected = 't1')} />
        <TrackRow track={weak} detail="matches exactly, cues stay" selected={selected === 't2'} onclick={() => (selected = 't2')} />
        <TrackRow track={good} showFolder onclick={() => (selected = good.track_id)} selected={selected === good.track_id}>
          {#snippet trailing()}<Button size="sm">Hide</Button>{/snippet}
        </TrackRow>
        <TrackRow track={fakeQ} detail="FAKE · 16.0 kHz" />
        <TrackRow track={missing} detail="next try in 5 days" />
        <TrackRow track={{ ...lossless, track_id: 'x', in_playlists: false }} dim showFolder detail="not in a playlist" />
      </Surface>
      <Surface label="KeyValue">
        <KeyValue k="Source" v="Qobuz FLAC · verified lossless" />
        <KeyValue k="File"><PathText path="Library/Hard_Bounce/Vatoz Locoz - Gimme Gimme.aiff" /></KeyValue>
        <KeyValue k="ISRC" />
      </Surface>
      <Surface label="KeyValue plain · keyWidth">
        <KeyValue plain keyWidth={80} k="yt-dlp" v="2026.10.28 (updated)" />
        <KeyValue plain keyWidth={80} k="streamrip" v="2.1.0 (built in)" />
      </Surface>
    </div>
  </section>

  <section data-test="gallery-long-text">
    {@render head('Long text', 'Every line ends in "…" or wraps inside its block, never past it (640 px column)')}
    <div class="long" data-test="long-text">
      <PageHeader title="Hard_Bounce_Extended_Afterhour_Selection_2026" sub="1,204 tracks · 82 % lossless · 3 not in a playlist">{#snippet actions()}<Button size="sm">Read now</Button>{/snippet}</PageHeader>
      <TrackRow track={{ ...weak, artist: 'Dr. Peacock, Sefa, Partyraiser & The Very Long Featured Artist', title: 'Never Stop Raving (Extended Festival Anthem Remix 2026)' }} showFolder detail="matches exactly, cues stay" />
      <KeyValue k="File" v="Library/Hard_Bounce_Extended_Afterhour_Selection_2026/Dr. Peacock, Sefa, Partyraiser - Never Stop Raving (Extended Festival Anthem Remix 2026).aiff" />
      <Surface label="Never Stop Raving (Extended Festival Anthem Remix 2026) by Dr. Peacock and friends" summary="1,204 not found"><p>Body.</p></Surface>
      <ProblemCard kind="failed" message="Couldn't move /Users/dj/Music/Library/Hard_Bounce_Extended_Afterhour_Selection_2026/Dr. Peacock - Never Stop Raving.aiff because the disk is full." />
      <Toast toast={{ id: 9, tone: 'problem', title: 'Couldn\'t add Dr. Peacock, Sefa, Partyraiser – Never Stop Raving (Extended Festival Anthem Remix 2026)', body: 'Library/Hard_Bounce_Extended_Afterhour_Selection_2026/Never_Stop_Raving_Extended_Festival_Anthem_Remix.wav' }} onclose={() => {}} />
    </div>
  </section>

  <section data-test="gallery-fields">
    {@render head('TextField · SearchField', 'Fields check as you type and say what is wrong under them')}
    <div class="grid3">
      <TextField bind:value={text} placeholder="Paste a Qobuz, YouTube or SoundCloud link" />
      <TextField bind:value={bad} invalid hint="That isn't a link." />
      <TextField bind:value={okv} okHint="looks right" mono />
      <TextField value="secret" type="password" placeholder="Password" />
      <SearchField bind:value={search} />
      <SearchField placeholder="Search…" shortcut="cmd+f" />
      <SearchField placeholder="Filter playlists, folders" shortcut="cmd+k" />
    </div>
  </section>

  <section data-test="gallery-stepstrip">
    {@render head('StepStrip', 'Where you are in a short guide (Setup): done ✓ and the next step open their step, the one on screen in the accent, a step that waits is no button')}
    <div class="col w800">
      <StepStrip steps={STRIP} onpick={(k) => (stripPicked = k)} label="Gallery steps" test="g-strip" />
      <span class="cap">tight · 480 px: labels end in "…"</span>
      <div class="w480"><StepStrip steps={STRIP} onpick={(k) => (stripPicked = k)} label="Gallery steps, narrow" /></div>
      <span class="cap" data-test="g-strip-picked">{stripPicked ? `picked ${stripPicked}` : 'Programs, Spotify and First playlist open their step'}</span>
    </div>
  </section>

  <section data-test="gallery-numberedsteps">
    {@render head('NumberedSteps', 'Steps to follow in order: a number in a ring, the text beside it, a control under the text (Setup\'s Spotify app, Qobuz\'s password steps)')}
    <div class="col start w480">
      <NumberedSteps test="g-steps">
        <li><span>Open Spotify's developer dashboard and log in.</span></li>
        <li><span>Add this <b>Redirect URI</b>:</span><CopyCode text="http://127.0.0.1:8888/callback" /></li>
        <li><span>Copy the app's <b>Client ID</b> and paste it here:</span>
          <SecretField type="text" mono placeholder="Client ID" label="Client ID" /></li>
      </NumberedSteps>
    </div>
  </section>

  <section data-test="gallery-addrow">
    {@render head('AddRow', 'Paste a Spotify or Qobuz playlist link, check it, name its folder (Playlists\' list head, Setup\'s first playlist)')}
    <div class="col w800"><AddRow draft={[]} onadd={(a, f) => { toasts.show({ tone: 'success', title: `Would add ${a.info?.name ?? a.link} as ${f}` }); return true; }} /></div>
  </section>

  <section data-test="gallery-copycode">
    {@render head('CopyCode', 'A line to paste into the Terminal, with its Copy button; without clipboard access it selects the line and says Press ⌘C')}
    <div class="col start w480">
      <CopyCode text="brew install ffmpeg" test="g-copycode" />
      <CopyCode text="/opt/homebrew/bin/brew install deno ffmpeg --quiet --force-bottle --no-quarantine" />
    </div>
  </section>

  <section data-test="gallery-folderfield">
    {@render head('FolderField', "A folder is chosen with the Mac's dialog, never typed: where it is, Choose… beside it, and one line on what is there")}
    <div class="grid3">
      <FolderField path={null} onchoose={() => {}} filled test="g-folder-none" />
      <FolderField path="/Users/you/Music/Discjockey" check={gFolder({ exists: false, kind: 'new' })} onchoose={() => {}} test="g-folder-new" />
      <FolderField path="/Users/you/Music/DJ Sets" check={gFolder({ kind: 'empty' })} onchoose={() => {}} test="g-folder-empty" />
      <FolderField path="/Volumes/DJ SSD/Discjockey" check={gFolder({ kind: 'discjockey_library' })} onchoose={() => {}} test="g-folder-library" />
      <FolderField path="/Users/you/Music" check={gFolder({ kind: 'other_files' })} onchoose={() => {}} test="g-folder-other" />
      <FolderField path="/Users/you" check={gFolder({ usable: false, problem: 'system_folder', kind: null, message: 'That folder belongs to macOS or holds your whole home folder. Choose a folder just for your music, such as Music/Discjockey.' })} onchoose={() => {}} test="g-folder-problem" />
      <FolderField path="/Users/you/Music/Discjockey" check={gFolder({ kind: 'empty' })} onchoose={() => {}} busy test="g-folder-busy" />
      <FolderField path="/Users/you/Music/Discjockey" onchoose={() => {}} disabledWhy="A sync is running. Choose a folder when it has finished." test="g-folder-off" />
      <FolderField path="/Volumes/DJ SSD/Discjockey" test="g-folder-shown" />
      <FolderField path="/Users/you/Music/Discjockey" onchoose={() => {}} disabled label="Choose where…" test="g-folder-disabled" />
    </div>
    <div class="w240">
      <FolderField path="/Users/you/Music/Sets and edits/Discjockey" check={gFolder({ kind: 'empty' })} onchoose={() => {}} label="Change…" test="g-folder-narrow" />
    </div>
    <div class="w372">
      <FolderField path="/Users/you/Music/Sets and edits for the summer season 2026/Discjockey Library" check={gFolder({ kind: 'discjockey_library' })} onchoose={() => {}} test="g-folder-long" />
    </div>
  </section>

  <section data-test="gallery-watchedfolders">
    {@render head('WatchedFolderList · ImportCard · UnreadableList', "The folders Discjockey indexes where they are, the import that reads them, and the files it couldn't read (Settings → Watched folders, Setup)")}
    <div class="grid3">
      <div class="w372"><WatchedFolderList folders={gFolders} onremove={() => {}} test="g-wf-list" /></div>
      <div class="w372"><WatchedFolderList folders={null} test="g-wf-loading" /></div>
      <div class="w372"><WatchedFolderList folders={gPickable} picked={5} cap={4} onpick={() => {}} onremove={() => {}} test="g-wf-picked" /></div>
      <div class="w372"><ImportCard view={{ kind: 'running', line: 'Reading tags · 340 of 1,500', share: 340 / 1500, stopping: false }} onstop={() => {}} test="g-wf-running" /></div>
      <div class="w372"><ImportCard view={{ kind: 'running', line: 'Looking for music files', share: null, stopping: true }} onstop={() => {}} test="g-wf-stopping" /></div>
      <div class="w372"><ImportCard view={{ kind: 'stopped', line: 'Import stopped with 1,160 files to go. It carries on where it stopped.' }} oncontinue={() => {}} test="g-wf-stopped" /></div>
      <div class="w372"><ImportCard view={{ kind: 'done', line: 'Imported 1,240 files.' }} test="g-wf-done" /></div>
      <div class="w372"><UnreadableList folders={gFolders} files={[{ folder_id: 2, path: '/Volumes/Example Drive/Music/Old/Untitled 3.mp3', reason: "Discjockey can't find sound it can read in it" },
        { folder_id: 2, path: '/Volumes/Example Drive/Music/Old/Example Artist - A Very Long Title (GUEST ONE x GUEST TWO EDIT).wav', reason: 'The file is empty' },
        { folder_id: 2, path: '/Volumes/Example Drive/Music/Old/Example Artist - A Very Long Title (GUEST ONE x GUEST TWO EDIT)(1).wav', reason: 'The file is empty' }]} test="g-wf-unreadable" /></div>
    </div>
  </section>

  <section data-test="gallery-secretfield">
    {@render head('SecretField', 'A credential stays in its element until it is sent: the page reads it out with takeSecret; oninput gives only a boolean or a check')}
    <div class="grid3">
      <SecretField placeholder="Password" label="Password" test="g-secret" />
      <SecretField type="text" mono placeholder="Client ID" label="Client ID" tone="ok" />
      <SecretField type="text" mono placeholder="Client ID" label="Client ID, wrong" tone="bad" />
      <div class="span3"><SecretField multiline placeholder="Paste the whole line here" label="Pasted line" /></div>
    </div>
  </section>

  <section data-test="gallery-banner">
    {@render head('Banner · Toast', 'The shell\'s banners under the title bar; toasts confirm what just happened')}
    <div class="col bordered">
      <Banner tone="warn" text="A sync is running in the terminal. You can look around; changes wait until it's finished." />
      <Banner tone="info" text="Spotify isn't connected." action={{ label: 'Set up →', href: '#/setup/spotify' }} />
    </div>
    <div class="row top">
      <Toast toast={{ id: 1, tone: 'info', title: 'First finished an interrupted step:', body: 'Moved a file back' }} onclose={() => {}} />
      <Toast toast={{ id: 2, tone: 'success', title: 'Swapped. rekordbox keeps the cue points.' }} onclose={() => {}} />
      <Toast toast={{ id: 3, tone: 'problem', title: 'This track changed in the meantime.', body: 'Look at it again.', action: { label: 'Open To-do', href: '#/todo' } }} onclose={() => {}} />
    </div>
    <div class="row">
      <Button size="sm" onclick={() => toasts.show({ tone: 'info', title: 'Info toast', body: 'Hides after 5 s.' })}>Show info</Button>
      <Button size="sm" onclick={() => toasts.show({ tone: 'success', title: 'Bought file added.' })}>Show success</Button>
      <Button size="sm" onclick={() => toasts.show({ tone: 'problem', title: "That didn't work.", body: 'Stays until closed.' })}>Show problem</Button>
    </div>
  </section>

  <section data-test="gallery-dialog">
    {@render head('Dialog · confirm()', 'A modal stays centred and only fades; a confirm only for what can\'t be undone')}
    <div class="row">
      <Button onclick={() => (dialogOpen = true)} data-test="open-dialog">Open dialog</Button>
      <Button onclick={async () => (answer = (await confirm({ title: 'Swap the file?', body: 'The old file goes to Superseded.', confirmLabel: 'Swap' })) ? 'yes' : 'no')}>confirm()</Button>
      <Button variant="danger" onclick={async () => (answer = (await confirm({ title: 'Discard the upgrade?', confirmLabel: 'Discard', tone: 'danger' })) ? 'yes' : 'no')}>confirm() danger</Button>
      {#if answer}<span class="note">answer: {answer}</span>{/if}
    </div>
    <Dialog bind:open={dialogOpen} title="Wrong song?" width={760} busy={dialogBusy}>
      <TextField placeholder="Paste a link" />
      {#each Array(14) as _, i (i)}<p class="note">Line {i + 1}: the body scrolls inside the dialog.</p>{/each}
      {#snippet footer()}
        <Button onclick={() => (dialogBusy = !dialogBusy)}>{dialogBusy ? 'Not busy' : 'Busy (Esc ignored)'}</Button>
        <Button variant="filled" onclick={() => (dialogOpen = false)}>Use this one</Button>
      {/snippet}
    </Dialog>
  </section>

  <section data-test="gallery-ring">
    {@render head('Ring', 'A share or a countdown as a ring with its number inside; mark: 2 px round a glyph')}
    <div class="row">
      <span class="g-ringmark"><Ring mark size={26} value={0.3} max={1} tone="muted" /><NavIcon name="sync" /></span>
      <Ring value={37} max={80} label="37" sub="of 80" />
      <Ring value={34} max={43} countdown sub="pause" />
      <Ring value={690} max={720} countdown sub="break" size={90} />
      <Ring value={80} max={80} tone="lossless" label="80" sub="of 80" size={90} />
    </div>
  </section>

  <section data-test="gallery-spectrum">
    {@render head('Spectrum', 'A file\'s spectrum: cut, full, loading, none, failed')}
    <div class="grid2">
      <Spectrum spectrum={specCut} height={110} />
      <Spectrum spectrum={specFull} height={110} />
      <Spectrum spectrum={null} loading height={110} />
      <Spectrum spectrum={null} height={110} />
      <Spectrum spectrum={null} error="The spectrum could not be read." height={110} />
    </div>
  </section>

  <section data-test="gallery-player">
    {@render head('MiniPlayer · ComparePlayer', 'Play, scrub, and compare the current and the new file')}
    <div class="col w480">
      <MiniPlayer url={toneA} title="Vatoz Locoz – Gimme Gimme" track_id="t1" length_s={40} />
      <MiniPlayer url={toneB} title="Armin Hermann – Get Naughty" track_id="t2" envelope={env} length_s={40} />
      <MiniPlayer url={null} title="Some Artist – Gone Track" />
      <MiniPlayer url="data:audio/wav;base64,AAAA" title="Broken" length_s={10} />
      <ComparePlayer a={{ url: toneA, label: 'Current' }} b={{ url: toneB, label: 'New' }} cueText="matches exactly, cues stay" />
      <ComparePlayer a={{ url: 'data:audio/wav;base64,AAAA', label: 'Current' }} b={{ url: 'data:audio/wav;base64,AAAA', label: 'New' }} />
    </div>
  </section>

  <section data-test="gallery-foot">
    {@render head('Foot · Now playing row', 'The frame\'s foot: sidebar and a 44 px bar are one L in one material; the line along the page is the position; ⏯ sits on the window\'s centre; Hide folds it into the sidebar\'s row')}
    {#each FOOTS as [title, sub, p, o] (title)}
      <span class="cap">{sub ? `${title} · ${sub}` : title}</span>
      <div class="footbox"><div class="pg"><span class="sb"></span></div>
        <Foot {p} sync={o.sync ?? false} motion={false} edge={o.edge ?? null} run={syncRun} /></div>
    {/each}
    <span class="cap">Sync only · no queue, or the player hidden</span>
    <div class="footbox"><div class="pg"><span class="sb"></span></div>
      <Foot p={np({ queue: null })} sync motion={false} run={syncRun} /></div>
    <span class="cap">The row, while hidden · playing · paused · the pointer on ⌃ Show player</span>
    <div class="row">
      <div class="rowbox"><NowPlayingRow p={np({ hidden: true })} motion={false} /></div>
      <div class="rowbox"><NowPlayingRow p={np({ hidden: true, playing: false })} motion={false} /></div>
      <div class="rowbox"><NowPlayingRow p={np({ hidden: true })} motion={false} hovered /></div>
    </div>
    <span class="cap">In the rail · playing · paused</span>
    <div class="row">
      <div class="rowbox railbox"><NowPlayingRow p={np({ hidden: true })} motion={false} rail /></div>
      <div class="rowbox railbox"><NowPlayingRow p={np({ hidden: true, playing: false })} motion={false} rail /></div>
    </div>
  </section>

  <section data-test="gallery-trackhead">
    {@render head('TrackHead · UpgradeCard', 'A details panel\'s head (beside: 64 px cover, one line each, an action at the title\'s end; stacked: Library) and the parked better version, compared and with its cue verdict (§7)')}
    <div class="col w360">
      <Surface kind="card">
        <TrackHead track={{ ...weak, cover_url: null }} place={weak.folder}>
          {#snippet action()}<Button variant="link" muted size="sm">Hide</Button>{/snippet}
          <QualityBadge quality={weak.quality} label={weak.quality_label} />
        </TrackHead>
      </Surface>
      <Surface kind="card">
        <TrackHead track={{ ...weak, cover_url: null, title: 'THE WEEKEND (Extended Festival Mix 2026 Remaster)',
          artist: 'DJ TALLBOY & The Extended Friends' }} place="Hard_Bounce">
          {#snippet action()}<Button variant="link" muted size="sm">Hide</Button>{/snippet}
          <QualityBadge quality={weak.quality} label={weak.quality_label} />
        </TrackHead>
      </Surface>
      <Surface kind="card" data-test="g-trackhead-empty">
        <TrackHead track={{ ...weak, cover_url: null, title: 'AEIOU', artist: 'Pegassi' }} place="not downloaded yet" empty>
          <Badge tone="missing" text="NOT FOUND" />
        </TrackHead>
      </Surface>
      <UpgradeCard upgrade={upExact} currentUrl={toneA} current={specCut} next={specFull} swap>
        {#snippet actions()}<Button variant="link" size="sm">Add as new file</Button><Button variant="link" muted size="sm">Discard</Button>{/snippet}
      </UpgradeCard>
      <UpgradeCard upgrade={upDifferent} currentUrl={null} current={specCut} next={null} loading swap={false} />
    </div>
  </section>

  <section data-test="gallery-dropzone">
    {@render head('DropZone', 'Drop a bought file onto its track: idle, dragging over, busy, refused')}
    <div class="grid2">
      <DropZone trackName="Armin Hermann – Get Naughty" expectedName="Library/Hard_Bounce/Armin Hermann - Get Naughty.wav" />
      <DropZone trackName="Armin Hermann – Get Naughty" over />
      <DropZone trackName="Armin Hermann – Get Naughty" busy fileName="Armin Hermann - Get Naughty.wav" />
      <DropZone trackName="Armin Hermann – Get Naughty" error="macOS didn't let Discjockey read this file. Move it to Downloads, or allow access in System Settings → Privacy & Security → Files and Folders." />
    </div>
  </section>

  <!-- ─── outdated (outdated.ts) ─── -->

  <section data-test="gallery-outdated">
    {@render head('Outdated', 'Don\'t use in redesigned pages: outdated.ts lists them and a test fails a redesigned page that imports one; deleted when phase 2 ends (§7)')}
    <Surface tone="warn" label="Don't use in redesigned pages">
      <div class="outlist">
        <span class="cap">blocks</span><span class="mono">{OUTDATED.join(' · ')}</span>
        <span class="cap">variant</span><span class="mono">Button variant="ghost" (= secondary; use secondary or link)</span>
        <span class="cap">tokens</span><span class="mono">{OUTDATED_TOKENS.join(' · ')}</span>
      </div>
    </Surface>
    <div class="spec">
      <span class="cap">Button ghost</span><div class="row"><Button variant="ghost">Ghost</Button><Button variant="ghost" size="sm">Ghost small</Button></div>
      <span class="cap">Chip · ChipGroup</span>
      <div class="col">
        <div class="row"><Chip label="Off" count={12} /><Chip label="On" count={4} active /><Chip label="Zero" count={0} />
          <Chip label="Weak" count={7} quality="weak" /><Chip label="Lossless" quality="lossless" /></div>
        <ChipGroup value={chip} onchange={(k) => (chip = k)} options={[{ key: 'all', label: 'All', count: 23 },
          { key: 'weak', label: 'Weak', count: 7, quality: 'weak' }, { key: 'fake', label: 'Fake', count: 0, quality: 'fake' }]} />
        <ChipGroup value={chip} onchange={(k) => (chip = k)} hideZero options={[{ key: 'all', label: 'All (zero hidden)', count: 23 },
          { key: 'weak', label: 'Weak', count: 7, quality: 'weak' }, { key: 'fake', label: 'Fake', count: 0, quality: 'fake' }]} />
      </div>
      <span class="cap">Card</span>
      <div class="grid3">
        <Card label="Default" title="Hairline card">Body text.{#snippet footer()}<Button size="sm">Action</Button>{/snippet}</Card>
        <Card label="Accent" title="Ready to sync" tone="accent">{#snippet header()}<Badge tone="accent" text="12" />{/snippet}Accent outline.</Card>
        <Card label="Problem" title="Needs you" tone="problem">Red outline.</Card>
      </div>
      <span class="cap">Tile</span>
      <div class="row">
        <Tile label="Lossless" value="74 %" sub="226 of 306 tracks"><QualityBar by_quality={BY_Q} /></Tile>
        <Tile label="Qobuz today" value={37} unit="of 80" sub="60 + 20 carried over"><ProgressBar value={0.46} /></Tile>
        <Tile label="Loading" value={null} loading />
        <Tile label="Still to load" value={null} sub="none" />
      </div>
      <span class="cap">SectionLabel</span><SectionLabel text="Not found" count={3} hint="nothing usable anywhere" />
      <span class="cap">SplitView</span>
      <div class="framebox short">
        <SplitView>
          {#snippet main()}<PageHeader title="Hard_Bounce" sub="45 tracks · 82 % lossless" /><SectionLabel text="Not found" count={3} />{/snippet}
        </SplitView>
      </div>
    </div>
  </section>
</div>

<style>
  .gallery { padding: var(--s-5) var(--s-6) 120px; display: flex; flex-direction: column; gap: var(--s-8, 48px); max-width: 1100px; }
  section { display: flex; flex-direction: column; gap: var(--s-3); }
  /* a section's head: the block's name, then the rule it carries in one line (spec §7) */
  .sh, .group { display: flex; flex-direction: column; gap: var(--s-1); padding-bottom: var(--s-2); border-bottom: var(--bw) solid var(--surface-line); }
  .sh h2, .group h2 { margin: 0; font-size: 17px; font-weight: 600; color: var(--text); }
  .group h2 { font-size: var(--fs-h1); }
  .rule { margin: 0; color: var(--text-muted); font-size: var(--fs-small); }
  .cap { color: var(--text-label); font-size: var(--fs-small); }
  .note { color: var(--text-label); font-size: var(--fs-small); }
  .mono { font-family: var(--font-mono, ui-monospace, monospace); font-size: var(--fs-small); color: var(--text); }
  .row { display: flex; flex-wrap: wrap; gap: var(--s-3); align-items: center; }
  .row.top { align-items: flex-start; }
  .col { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
  .tight { gap: var(--s-1); }
  .start { align-items: flex-start; }
  .start > :global([data-hint]) { max-width: 100%; }
  .tight-row { gap: var(--s-2); }
  .inline { display: inline-flex; }
  /* a labelled grid: the state on the left, the samples on one aligned column */
  .spec { display: grid; grid-template-columns: 150px minmax(0, 1fr); gap: var(--s-3) var(--s-4); align-items: center; }
  .grid2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--s-3); align-items: start; }
  .grid3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--s-3); align-items: start; }
  .span2 { grid-column: span 2; }
  .span3 { grid-column: span 3; }
  .headers { max-width: 900px; }
  .bordered { border-top: var(--bw) solid var(--surface-line); gap: 0; }
  .long { width: 640px; max-width: 100%; display: flex; flex-direction: column; gap: var(--s-3); border: var(--bw) dashed var(--surface-line); padding: var(--s-2) 0; }
  /* miniature frames: a fixed box stands in for the window's page area */
  .framebox { height: 300px; border: var(--bw) solid var(--surface-line); border-radius: var(--r-surface); overflow: hidden; }
  .framebox.short { height: 200px; }
  .framebox.tall { height: 420px; }
  .panelbox { width: 320px; background: var(--panel-bg); border: var(--bw) solid var(--surface-line); border-radius: var(--r-surface); overflow: hidden; }
  .fillbox { height: 300px; display: flex; flex-direction: column; }
  .srow { display: flex; align-items: center; min-height: var(--h-row); padding: 0 var(--s-4); }
  .tipcell { display: inline-flex; align-items: center; gap: var(--s-2); color: var(--text-muted); }
  .toggle-icon { display: grid; place-items: center; width: 16px; color: var(--text-muted); }
  .outlist { display: grid; grid-template-columns: 80px minmax(0, 1fr); gap: var(--s-2) var(--s-3); }
  .tbl { width: 100%; border-collapse: collapse; font-size: var(--fs-small); }
  .tbl th { text-align: left; font-weight: 500; color: var(--text-label); padding: var(--s-2) var(--s-4); border-bottom: var(--bw) solid var(--surface-line); }
  .tbl td { padding: var(--s-2) var(--s-4); border-bottom: var(--bw) solid var(--surface-line); color: var(--text); }
  .tbl tr:last-child td { border-bottom: none; }
  .tbl .num { text-align: right; }
  .gtr { display: grid; grid-template-columns: minmax(0, 1fr) 120px 56px; align-items: center; gap: var(--s-3); height: var(--h-row);
    padding: 0 var(--s-4); font-size: var(--fs-body); color: var(--text); }
  .gtr.row-line + .gtr.row-line { border-top: var(--bw) solid var(--line-soft); }
  .gtr .num { justify-self: end; color: var(--text-muted); font-variant-numeric: tabular-nums; }
  .w260 { width: 260px; }
  .w320 { width: 320px; }
  .w360 { width: 360px; max-width: 100%; }
  /* table cells of a fixed width, to show how a block gives way in one (Badge more, MiddleText sep) */
  .cell140, .cell200, .cell320 { display: flex; min-width: 0; color: var(--text-muted); font-size: var(--fs-small); }
  .cell140 { width: 140px; } .cell200 { width: 200px; } .cell320 { width: 320px; max-width: 100%; }
  .w240 { width: 240px; max-width: 100%; margin-bottom: var(--s-3); }
  .w372 { width: 372px; max-width: 100%; }
  .g-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--s-3); }
  .g-st { display: inline-flex; align-items: center; gap: var(--s-1); }
  .g-marks { display: flex; gap: var(--s-2); }
  .g-ladders { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--s-4) var(--s-3); align-items: start; }
  .w520 { width: 520px; max-width: 100%; }
  .g-accounts { display: grid; grid-template-columns: repeat(3, 320px); gap: var(--s-4) var(--s-3); align-items: start; }
  .grow-demo { height: 300px; }
  .w480 { width: 480px; max-width: 100%; }
  .w640 { width: 640px; max-width: 100%; }
  .w800 { width: 800px; max-width: 100%; }
  /* the foot with a sliver of page above it: the sidebar's 168 px column and its border, the frame's material */
  .footbox { position: relative; display: flex; flex-direction: column; height: 88px; border-radius: var(--r-surface);
    overflow: hidden; background: var(--sidebar-bg); border: var(--bw) solid var(--surface-line); }
  .footbox .pg { flex: 1; display: flex; background: var(--bg); }
  .footbox .sb { width: var(--sidebar-w); border-right: var(--bw) solid var(--surface-line); }
  .rowbox { width: var(--sidebar-full-w); padding: 0 10px var(--s-2); background: var(--sidebar-bg); border-radius: var(--r-surface);
    border: var(--bw) solid var(--surface-line); }
  /* NavIcon: a sidebar column in the frame's material, its rows as the sidebar draws them */
  .g-nav { display: flex; flex-direction: column; gap: 2px; padding: var(--s-2) 10px; background: var(--sidebar-bg);
    border: var(--bw) solid var(--surface-line); border-radius: var(--r-surface); }
  .railbox { width: var(--rail-w); padding-top: var(--s-2); }
  .g-ringmark { position: relative; width: 26px; height: 26px; display: grid; place-items: center; color: var(--text-nav); }
  .g-ringmark :global(.ring) { position: absolute; inset: 0; }
  .g-nav-full { width: var(--sidebar-full-w); }
  .g-nav-rail { width: 50px; }
  .g-navrow { display: flex; align-items: center; gap: 9px; height: var(--h-ctl); padding: 0 var(--s-2); color: var(--text-nav);
    border-radius: var(--r-nav); white-space: nowrap; }
  .g-navrow.on { color: var(--text-strong); background: var(--nav-on-bg); }
  /* ServiceMark: each logo alone, dimmed, and in a row of the frame's material (a switched-off row dims as a whole) */
  .g-svc { display: grid; grid-template-columns: 120px 40px 40px 240px; gap: var(--s-2) var(--s-3); align-items: center;
    font-size: var(--fs-small); color: var(--text-muted); }
  .g-svc-rows { padding: var(--s-1) 6px; }
  .g-svc-rows .g-navrow { height: 26px; color: var(--text); }
  .g-n { margin-left: auto; color: var(--text-label); font-size: var(--fs-label); font-variant-numeric: tabular-nums; }
  .g-off { opacity: var(--dim-locked); }
  /* Tip: room on the right of the rail and under the rows for the tips shown open */
  .g-tips { gap: 220px; padding-bottom: var(--s-8); }
  .g-tip-col { width: 200px; }
  .g-cut { min-width: 0; overflow: hidden; text-overflow: ellipsis; color: var(--text); }
  button.g-navrow { padding: 0 var(--s-2); }
  .g-hdr { max-width: 100%; padding: 0 var(--s-2); border-left: var(--bw) dashed var(--surface-line); border-right: var(--bw) dashed var(--surface-line); }
  .g-chrome-list { width: 220px; height: 240px; overflow-y: auto; padding: 0 var(--s-2); background: var(--sidebar-bg);
    border: var(--bw) solid var(--surface-line); border-radius: var(--r-surface); }
  .g-crow { display: flex; align-items: center; height: var(--h-ctl); padding: 0 var(--s-2); color: var(--text-nav);
    font-size: var(--fs-body); }
  .g-glyph { position: relative; display: grid; }
  /* the rail's count pill on the glyph's corner, ringed in the frame's colour so it cuts the glyph cleanly */
  .g-pill { position: absolute; left: 11px; top: -9px; min-width: 18px; height: 14px; padding: 0 4px; border-radius: var(--r-pill);
    background: var(--rail-pill-bg); box-shadow: 0 0 0 2px var(--sidebar-solid); color: var(--text); font-size: var(--fs-label);
    font-weight: var(--fw-semi); line-height: 14px; text-align: center; font-variant-numeric: tabular-nums; }
</style>
