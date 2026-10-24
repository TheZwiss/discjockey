// Fake mode only: an in-memory Discjockey state shaped like the contract. Reads are computed from it, writes change it.
import type {
  AnySignalKind, AppUpdate, Alignment, Browser, Budget, LastCheck, LoginBrowser, ByQuality, Candidate, PlaylistInfo, PlaylistRow, PreviewAction, Quality, Result, RunDetail,
  DownloadTools, FolderCheck, SetupStatus, SignalKind, Source, SpotifyStatus, Status, TodoGroupKey, TrackRow, Upgrade, FreeDownload,
} from '../types';
import { NOT_IN_PLAYLIST, QUALITIES } from '../types';

/** the fake's newest yt-dlp on PyPI */
export const FAKE_NEWEST_YT_DLP = '2026.10.28';

export function builtInTools(): DownloadTools {
  return { 'yt-dlp': { version: '2026.10.21', source: 'built_in', waiting: null, previous: null },
    streamrip: { version: '2.1.0', source: 'built_in', waiting: null, previous: null } };
}

/** A service with a daily limit (Qobuz, YouTube Premium, SoundCloud Go+), as the Download limits page shows it. */
export type FakeService = { limit: number; extra_today: number; carry_over: number; used_today: number; days: number[];
  signals: { time: string; kind: AnySignalKind; message: string }[]; last_download: string | null;
  /** "Got it": the time up to which its warning signs were seen (settings.json warnings_seen) */
  seen?: string | null };
export type FakeAccount = FakeService & { browser: Browser; profile?: string | null; profileName?: string | null;
  lastCheck?: LastCheck | null };

export type FakeTrack = {
  track_id: string; artist: string; title: string; folder: string; duration_s: number;
  status: Status; cutoff_hz: number | null; source: Source | null; codec: string | null;
  in_playlists: boolean; hidden: boolean; added: string | null; cover: number | null;  // cover: gradient index
  isrc: string | null; playlists: string[]; upgrade: (Upgrade & { cutoff_hz?: null }) | null;
  rekordbox_check: { reason: 'wrong_song' | 'added_as_new'; since: string } | null;
  other: string | null;          // "Other" to-do item text (something is in the way)
  next_try_days: number | null;  // not found: next try in N days
  rejected_sources: string[];
  file_name?: string;            // superseded duplicates may carry a suffix; Library names never do
  kbps?: number;                 // lossy sources: the bitrate
  free_downloads?: FreeDownload[];
};
export type FakeRun = RunDetail;
export type FakePlaylist = { folder: string; link: string; enabled: boolean; info: PlaylistInfo | null };
export type FakeState = {
  scenario: string;
  /** what check_music_folder answers per path; a path not in it is `new` and usable (unless it isn't absolute) */
  folders: Record<string, Omit<FolderCheck, 'path'>>;
  /** what the folder dialog (pick_folder) returns; null: the user cancelled */
  pick: string | null;
  now: Date;
  tracks: FakeTrack[];
  newTracks: { track_id: string; artist: string; title: string; folder: string; duration_s: number }[];
  extraFolders: { folder: string; in_playlists_txt: boolean }[];
  playlists: FakePlaylist[];
  version: number;
  runs: FakeRun[];
  qobuz: FakeService;
  accounts: { youtube: FakeAccount | null; soundcloud: FakeAccount | null };
  qobuzSkipped: boolean;  // "I don't have Qobuz" in setup
  qobuzLastCheck?: LastCheck | null;
  /** find_logins per service on the fake Mac (default: Chrome without a login, Safari without Full Disk Access) */
  browsers?: Partial<Record<'youtube' | 'soundcloud', LoginBrowser[]>>;
  /** a sign-in that never sees the login (shots of the waiting state) */
  signInWaits?: boolean;
  /** a sign-in that never sees the login and gives up as after its 10 minutes (here after a few seconds) */
  signInTimesOut?: boolean;
  /** bridge methods the engine doesn't answer: they come back `crashed`, as client.ts makes a call that throws */
  unanswered?: string[];
  spotifyUser?: string | null;
  setup: SetupStatus;
  /** setup_check_tools' download_tools; update_tools / rollback_tools change it as the engine would */
  downloadTools: DownloadTools;
  /** open_licenses is refused: the licences folder is missing from this copy */
  licensesMissing?: boolean;
  spotify: SpotifyStatus;
  console_running: boolean;
  offline: boolean;
  /** app_update(): the update check's answer (scenario update_available: a newer version) */
  appUpdate: AppUpdate;
  previewRead: boolean;          // false → sync_preview empty 'no_preview'
  selected: string | null;
  dropped: { track_id: string; name: string } | null;
  errors: boolean;               // every write ends with a problem
  errorTurn: number;
  syncStarts: number;
  never: string[];               // "never download": Spotify ids the plan leaves out
};

// ---------- helpers ----------
export const COVER_COLOURS = ['#ff5a1f', '#7b2cff', '#2fd27a', '#1d6fff', '#e8b93a'];
export function coverUri(i: number | null): string | null {
  if (i === null) return null;
  const a = COVER_COLOURS[i % COVER_COLOURS.length];
  const b = COVER_COLOURS[(i + 1 + (i >> 2)) % COVER_COLOURS.length];
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs><linearGradient id="g" x1="0" y1="0" `
    + `x2="1" y2="1"><stop offset="0" stop-color="${a}"/><stop offset="1" stop-color="${b}"/></linearGradient></defs>`
    + `<rect width="10" height="10" fill="url(#g)"/></svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}
export const SOURCE_NAMES: Record<Source, string> = { qobuz: 'Qobuz', youtube_music: 'YT Music',
  soundcloud: 'SoundCloud', youtube: 'YouTube', manual: 'bought' };
const khz = (hz: number) => `${(hz / 1000).toFixed(1)} kHz`;
export function qualityOf(t: FakeTrack): Quality {
  if (t.status === 'missing') return 'missing';
  if (t.status === 'lossless') return 'lossless';
  if (t.status === 'fake_lossless') return 'fake';
  return t.cutoff_hz !== null && t.cutoff_hz <= 17000 ? 'weak' : 'good_lossy';
}
export function qualityLabel(t: FakeTrack): string {
  const q = qualityOf(t);
  if (q === 'lossless') return 'LOSSLESS';
  if (q === 'missing') return 'NOT FOUND';
  if (q === 'fake') return `FAKE · ${khz(t.cutoff_hz ?? 16000)}`;
  return t.cutoff_hz ? khz(t.cutoff_hz) : 'LOSSY';
}
export function pathOf(t: FakeTrack): string | null {
  if (t.status === 'missing') return null;
  const sub = t.status === 'lossless' ? '' : '/not_lossless';
  return `Library/${t.folder}${sub}/${t.artist} - ${t.title}.aiff`;
}
export function trackRow(t: FakeTrack): TrackRow {
  return {
    track_id: t.track_id, artist: t.artist, title: t.title, folder: t.folder, duration_s: t.duration_s,
    status: t.status, quality: qualityOf(t), quality_label: qualityLabel(t), cutoff_hz: t.cutoff_hz,
    source: t.source, source_name: t.source ? SOURCE_NAMES[t.source] : null, in_playlists: t.in_playlists,
    hidden: t.hidden, upgrade_ready: !!t.upgrade, path: pathOf(t), added: t.added, cover_url: coverUri(t.cover),
  };
}
export function qualityLine(t: FakeTrack): string {
  const q = qualityOf(t);
  const src = t.source ? SOURCE_NAMES[t.source] : '';
  if (q === 'missing') return 'No file yet';
  if (q === 'lossless') return t.source === 'manual' ? 'bought file · lossless' : `${src} FLAC · verified lossless`;
  if (q === 'fake') return `${src} FLAC · fake lossless, cutoff ${khz(t.cutoff_hz ?? 16000)}`;
  const kbps = t.kbps ? ` ${t.kbps} kbps` : '';
  return `${src} ${(t.codec ?? 'aac').toUpperCase()}${kbps} · cutoff ${khz(t.cutoff_hz ?? 20000)}`;
}
export function todoGroup(t: FakeTrack): TodoGroupKey | null {
  if (t.other) return 'other';
  if (t.upgrade) return 'upgrade_ready';
  const q = qualityOf(t);
  return q === 'missing' ? 'not_found' : q === 'lossless' ? null : q === 'good_lossy' ? 'good_lossy' : q;
}
export function todoDetail(t: FakeTrack, g: TodoGroupKey): string {
  if (g === 'rekordbox_check') return checkText(t.rekordbox_check!.reason);
  if (g === 'upgrade_ready') return t.upgrade!.cue_text;
  if (g === 'not_found') {
    const d = t.next_try_days;
    return d === null ? 'tried again at the next sync' : `next try in ${d} day${d === 1 ? '' : 's'}`;
  }
  if (g === 'other') return t.other ?? '';
  // as views._detail: the badge says the kHz
  const kbps = t.kbps && t.status === 'not_lossless' ? `${t.kbps} kbps` : '';
  return [t.source ? SOURCE_NAMES[t.source] : '', kbps].filter(Boolean).join(' · ');
}
/** As SOURCE_NAMES in models.py: the details panel's "from YouTube Music". */
export const SOURCE_FULL: Record<Source, string> = { qobuz: 'Qobuz', youtube_music: 'YouTube Music',
  soundcloud: 'SoundCloud', youtube: 'YouTube', manual: 'bought' };
/** As views.FREE_GROUPS: the row's FREE tag. */
export function todoFree(t: FakeTrack, g: TodoGroupKey): boolean {
  return ['not_found', 'weak', 'good_lossy', 'fake'].includes(g) && !!t.free_downloads?.length;
}
const FORMAT_NAMES: Record<string, string> = { opus: 'Opus', aac: 'AAC', mp3: 'MP3', flac: 'FLAC' };
/** As views.format_line. */
export function formatLine(t: FakeTrack): string | null {
  if (t.status === 'missing' || !t.codec) return null;
  const name = FORMAT_NAMES[t.codec] ?? t.codec.toUpperCase();
  return t.kbps && t.status === 'not_lossless' ? `${name} · ${t.kbps} kbps` : name;
}
export function checkText(reason: 'wrong_song' | 'added_as_new'): string {
  return reason === 'wrong_song'
    ? 'This track now plays the right song. In rekordbox: analyse it again and delete the old cues (they belong to the wrong song).'
    : 'This is a different edit. In rekordbox: analyse it again and set the cues again.';
}
export function byQuality(ts: FakeTrack[]): ByQuality {
  const b = Object.fromEntries(QUALITIES.map((q) => [q, 0])) as ByQuality;
  for (const t of ts) b[qualityOf(t)]++;
  return b;
}
export function budget(s: FakeState): Budget {
  const allowance = s.qobuz.limit + s.qobuz.carry_over + s.qobuz.extra_today;
  return { used: s.qobuz.used_today, allowance, limit: s.qobuz.limit, carry_over: s.qobuz.carry_over,
    extra: s.qobuz.extra_today, remaining: Math.max(0, allowance - s.qobuz.used_today) };
}
const ALIGN: Record<'exact' | 'different', Alignment> = {
  exact: { drift_ms: 0, offset_ms: 0, offset_samples: 0, result: 'exact', text: 'matches exactly' },
  different: { drift_ms: 412.5, offset_ms: 1830, offset_samples: 80703, result: 'different', text: "doesn't match" },
};
export function makeUpgrade(t: { folder: string; artist: string; title: string }, kind: 'exact' | 'different',
  found: string): Upgrade {
  return {
    file: `Upgrades ready/${t.folder}/${t.artist} - ${t.title}.aiff`, source: 'qobuz', source_name: 'Qobuz',
    source_id: `q${Math.abs(hash(t.title)) % 900000}`, found, what: 'lossless version',
    quality_line: 'Qobuz FLAC · verified lossless',
    alignment: ALIGN[kind],
    cue_text: kind === 'exact' ? 'matches exactly, cues stay' : "doesn't match: would be a new rekordbox entry",
    swap_safe: kind === 'exact', swap_possible: true, audio_url: null,
  };
}
export function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h | 0;
}
const iso = (d: Date) => {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
};
export const isoLocal = iso;
export const dateOnly = (d: Date) => iso(d).slice(0, 10);
const daysAgo = (now: Date, n: number, h = 21, m = 47) => {
  const d = new Date(now);
  d.setDate(d.getDate() - n);
  d.setHours(h, m, 0, 0);
  return d;
};
export const runId = (d: Date) => iso(d).replace('T', '_').replace(/:/g, '');

// ---------- the sample library ----------
export const FOLDERS = ['Hard_Bounce', 'Powertrance', 'Bouncy', '03_06_2026', 'Tekke_Ecke'];
const ARTISTS = ['Kalte Nacht', 'Rave Kollektiv', 'DJ Fluxkompensator', 'Neon Riot', 'Hardline Theory',
  'Bassgewitter', 'Lena Strobe', 'Mira Volt', 'Tekk Tobi', 'Pulsar 9', 'Nachtfalter', 'Kai Kickdrum', 'Sora Blitz',
  'Vortex Unit', 'Jana Jump', 'Remo Rush', 'Bounce Brigade', 'Low Ceiling', 'Echo Gruppe', 'Frau Funk'];
const TITLES = ['Neonfieber', 'Strobe Light', 'Bis zum Morgen', 'Hands Up Again', 'Hyperdrive', 'Kick it Hard',
  'Gravity', 'Mitternacht', 'Rush Hour', 'Feuerwerk', 'Sunrise Tekk', 'Durch die Halle', 'Afterhour', 'Tunnelblick',
  'Laserpark', 'Sternenstaub', 'Overdrive', 'Zeitlupe', 'Schall und Rauch', 'Kopfkino', 'Wellenreiter', 'Polarlicht',
  'Herzschlag', 'Nebelmaschine', 'Lichtgeschwindigkeit', 'Druckwelle', 'Rueckenwind', 'Sonnenfinsternis',
  'Blitzlicht', 'Endlos', 'Funkenflug', 'Taktgefuehl', 'Treppenhaus', 'Unterwasser', 'Vollgas'];
// big library: same titles as other mixes (part of the real title, never a "(2)" file suffix)
const MIXES = ['', ' (Extended Mix)', ' (Radio Edit)', ' (Club Mix)', ' (Dub Mix)', ' (VIP Mix)', ' (Hard Mix)',
  ' (Festival Mix)', ' (Bounce Mix)'];

function base(id: string, artist: string, title: string, folder: string, duration_s: number, now: Date,
  ago: number): FakeTrack {
  return { track_id: id, artist, title, folder, duration_s, status: 'lossless', cutoff_hz: null, source: 'qobuz',
    codec: 'flac', in_playlists: true, hidden: false, added: iso(daysAgo(now, ago, 22, 15)),
    cover: Math.abs(hash(id)) % 5, isrc: `DE${String(Math.abs(hash(id)) % 1e10).padStart(10, '0')}`,
    playlists: [folder], upgrade: null, rekordbox_check: null, other: null, next_try_days: null,
    rejected_sources: [] };
}
function lossy(t: FakeTrack, source: Source, cutoff: number, codec: string): FakeTrack {
  const kbps = source === 'soundcloud' ? 160 : codec === 'opus' ? 135 : 128;
  return { ...t, status: 'not_lossless', source, cutoff_hz: cutoff, codec, kbps };
}
/** An artist's free download behind a download gate (fake mode). */
export function gate(t: FakeTrack, host = 'hypeddit.com'): FreeDownload {
  const slug = `${t.artist} ${t.title}`.toLowerCase().replace(/[^a-z0-9]+/g, '');
  return { url: `https://${host}/${slug}`, host, direct: false, title: `${t.title} [FREE DL]`, uploader: t.artist };
}

/** Six named tracks (contract examples + fixture tracks) and about 35 more. */
export function sampleTracks(now: Date, extra = 35): FakeTrack[] {
  const ts: FakeTrack[] = [];
  ts.push(base('t1', 'Vatoz Locoz', 'Gimme Gimme', 'Hard_Bounce', 156, now, 3));
  ts.push({ ...lossy(base('t2', 'Armin Hermann', 'Get Naughty', 'Hard_Bounce', 268, now, 3), 'youtube', 16000, 'opus'),
    playlists: ['Hard_Bounce', 'Powertrance'],
    upgrade: makeUpgrade({ folder: 'Hard_Bounce', artist: 'Armin Hermann', title: 'Get Naughty' }, 'exact',
      dateOnly(daysAgo(now, 0))) });
  ts.push({ ...base('t3', 'Some Artist', 'Gone Track', 'Hard_Bounce', 180, now, 3), status: 'missing', source: null,
    codec: null, next_try_days: 5 });
  ts.push({ ...base('t6', 'DJ TALLBOY', 'THE WEEKEND', 'Hard_Bounce', 192, now, 9) });
  for (let i = 0; i < extra; i++) {
    const n = i + 7;
    const id = `t${n}`;
    const round = Math.floor(i / TITLES.length);
    const artist = ARTISTS[(i * 7 + Math.floor(round / MIXES.length)) % ARTISTS.length];
    const title = TITLES[i % TITLES.length] + MIXES[round % MIXES.length];
    const folder = FOLDERS[i % FOLDERS.length];
    let t = base(id, artist, title, folder, 150 + ((i * 37) % 200), now, (i * 3) % 40);
    if (i % 7 === 1) t = lossy(t, 'youtube_music', 20000, 'aac');
    else if (i % 7 === 3) t = lossy(t, i % 2 ? 'soundcloud' : 'youtube', i % 2 ? 17000 : 16000, i % 2 ? 'aac' : 'opus');
    if (t.source === 'soundcloud') t.free_downloads = [gate(t)];
    else if (i % 7 === 1 && i % 3 === 1) t.free_downloads = [gate(t, 'downloadgater.com')];
    else if (i % 11 === 5) t = { ...t, status: 'fake_lossless', cutoff_hz: 16000, source: 'qobuz', codec: 'flac' };
    else if (i % 9 === 4) t = { ...t, status: 'missing', source: null, codec: null, next_try_days: i % 3 ? 2 : 1 };
    if (i % 5 === 2) t.cover = null;
    ts.push(t);
  }
  if (extra >= 30) {
    // a second upgrade that doesn't match
    const g = ts.find((t) => qualityOf(t) === 'good_lossy')!;
    g.upgrade = makeUpgrade(g, 'different', dateOnly(daysAgo(now, 1)));
    // one hidden track
    ts.filter((t) => qualityOf(t) === 'weak')[1].hidden = true;
    // one "Other" item: a move that is blocked
    const o = ts.find((t) => t.folder === 'Bouncy' && qualityOf(t) === 'lossless')!;
    o.other = 'Not moved to Powertrance: a different file with this name is already there.';
    // one "Check in rekordbox" item
    const r = ts.find((t) => t.folder === 'Powertrance' && qualityOf(t) === 'lossless')!;
    r.rekordbox_check = { reason: 'wrong_song', since: dateOnly(daysAgo(now, 1)) };
    r.source = 'youtube_music';
    r.status = 'not_lossless'; r.cutoff_hz = 20000; r.codec = 'aac';
    // two tracks no longer in a playlist, still in their old folder (Old_Sets is no longer in playlists.txt)
    for (const t of ts.filter((x) => qualityOf(x) === 'lossless' && !x.other && !x.rekordbox_check).slice(-2)) {
      t.in_playlists = false; t.folder = 'Old_Sets'; t.playlists = [];
    }
  }
  return ts;
}

export const PLAYLIST_IDS = ['0DiscjockeyExampleList', '3DiscjockeyExampleList', '5bQx1Bounce0yW2rZtQ9aP',
  '2Juni2026mX8kLq0Pw3vNe', '7TekkeEckeQe2xYb9LmPzR', '1HardTechnoNoAccessKv4'];
export function samplePlaylists(): FakePlaylist[] {
  const info = (name: string, n: number, yours = true, readable = true): PlaylistInfo => ({ name,
    owner_name: yours ? 'DJ One' : 'Hard Techno Radio', yours, collaborative: false, readable, image_url: null,
    track_count: n });
  const link = (id: string) => `https://open.spotify.com/playlist/${id}`;
  return [
    { folder: 'Hard_Bounce', link: link(PLAYLIST_IDS[0]), enabled: true, info: info('Hard Bounce', 12) },
    { folder: 'Powertrance', link: link(PLAYLIST_IDS[1]), enabled: true, info: info('Powertrance', 9) },
    { folder: 'Bouncy', link: link(PLAYLIST_IDS[2]), enabled: true, info: info('Bouncy', 7) },
    { folder: '03_06_2026', link: link(PLAYLIST_IDS[3]), enabled: true, info: info('03.06.2026 set', 7) },
    { folder: 'Tekke_Ecke', link: link(PLAYLIST_IDS[4]), enabled: false, info: info('Tekke Ecke', 7) },
    { folder: 'Hard_Techno', link: link(PLAYLIST_IDS[5]), enabled: true,
      info: info('Hard Techno Radio', 0, false, false) },
  ];
}

export function newTracks(n = 10) {
  const out = [
    { track_id: 't4', artist: 'Pegassi', title: 'AEIOU', folder: 'Hard_Bounce', duration_s: 201 },
    { track_id: 't5', artist: 'torbentorben', title: 'non stop', folder: 'Powertrance', duration_s: 174 },
  ];
  for (let i = 0; i < n; i++) {
    out.push({ track_id: `n${i + 1}`, artist: ARTISTS[(i * 3 + 5) % ARTISTS.length],
      title: `${TITLES[(i * 5 + 3) % TITLES.length]} (Extended Mix)`, folder: FOLDERS[i % 4], duration_s: 210 + i * 9 });
  }
  return out;
}

export function previewAction(kind: string, reason: string | null, t: { track_id: string; artist: string;
  title: string; folder: string }, to_not_lossless = false, src: string | null = null,
  cover: number | null = null): PreviewAction {
  const to_dir = `Library/${t.folder}${to_not_lossless ? '/not_lossless' : ''}`;
  return { key: [kind, t.track_id, to_dir], kind, reason, track_id: t.track_id, artist: t.artist, title: t.title,
    folder: t.folder, to_dir, to_not_lossless, src, cover_url: coverUri(cover) };
}

// ---------- runs ----------
export function result(section: string, t: { folder: string; artist: string; title: string; track_id: string | null },
  note: string, more: Partial<Result> = {}): Result {
  return { section, folder: t.folder, artist: t.artist, title: t.title, track_id: t.track_id, note, status: null,
    source: null, cutoff_hz: null, path: null, error_kind: null, ...more };
}
const NEW_FILE_SECTIONS = ['new_lossless', 'new_not_lossless', 'fake', 'swapped', 'added_new', 'bought', 'replaced',
  'moved', 'redownloaded'];
const PROBLEM_SECTIONS = ['missing', 'errors', 'conflicts', 'ambiguous'];
export function runDetail(id: string, started: Date, duration_s: number, exit_code: number, results: Result[],
  stopped_after: number | null, upgrades_ready: number): RunDetail {
  const sections: Record<string, Result[]> = {};
  for (const r of results) (sections[r.section] ??= []).push(r);
  const newFiles = results.filter((r) => NEW_FILE_SECTIONS.includes(r.section) && r.path).map((r) => r.path!);
  const count = (...ss: string[]) => results.filter((r) => ss.includes(r.section)).length;
  return {
    run_id: id, started: iso(started), finished: iso(new Date(started.getTime() + duration_s * 1000)), duration_s,
    exit_code, counts: { lossless: count('new_lossless', 'swapped', 'redownloaded'),
      lossy: count('new_not_lossless', 'fake'), problems: count(...PROBLEM_SECTIONS), moved: count('moved') },
    stopped_after, sections, needs_you: results.filter((r) => PROBLEM_SECTIONS.includes(r.section) && r.track_id),
    for_rekordbox: { new_files: newFiles.length, folders: [...new Set(newFiles.map((p) => p.slice(0, p.lastIndexOf('/'))))].sort() },
    upgrades_ready, report_md: `reports/${id}.md`, queued: count('queued'), folder_order: [],
  };
}
export function sampleRuns(now: Date, tracks: FakeTrack[], n = 3): FakeRun[] {
  const t = (id: string) => tracks.find((x) => x.track_id === id)!;
  const runs: FakeRun[] = [];
  const s0 = daysAgo(now, 0, 21, 47);
  runs.push(runDetail(runId(s0), s0, 1440, 1, [
    result('moved', t('t6'), 'from Library/Bouncy/DJ TALLBOY - THE WEEKEND.aiff',
      { status: 'lossless', source: 'qobuz', path: 'Library/Hard_Bounce/DJ TALLBOY - THE WEEKEND.aiff' }),
    result('new_lossless', t('t1'), 'Qobuz FLAC · verified lossless',
      { status: 'lossless', source: 'qobuz', path: 'Library/Hard_Bounce/Vatoz Locoz - Gimme Gimme.aiff' }),
    result('missing', t('t3'), 'not found on Qobuz, YouTube Music, SoundCloud or YouTube · [Beatport](https://www.beatport.com/search?q=Some+Artist+Gone+Track) · [Bandcamp](https://bandcamp.com/search?q=Some+Artist+Gone+Track)',
      { error_kind: 'not_found' }),
    result('new_not_lossless', { folder: 'Powertrance', artist: 'torbentorben', title: 'non stop', track_id: 't5' },
      'YT Music AAC · cutoff 20.0 kHz', { status: 'not_lossless', source: 'youtube_music', cutoff_hz: 20000,
        path: 'Library/Powertrance/not_lossless/torbentorben - non stop.aiff' }),
    result('errors', { folder: 'Hard_Bounce', artist: 'Pegassi', title: 'AEIOU', track_id: 't4' },
      'no internet connection, tried again at the next sync', { error_kind: 'network' }),
    result('upgrade_ready', t('t2'), 'Qobuz FLAC · matches exactly, cues stay',
      { status: 'not_lossless', source: 'qobuz', found_status: 'lossless', path: 'Upgrades ready/Hard_Bounce/Armin Hermann - Get Naughty.aiff' }),
  ], null, 2));
  const s1 = daysAgo(now, 1, 22, 5);
  const many = tracks.filter((x) => qualityOf(x) === 'lossless').slice(0, 12);
  const r1: Result[] = [];
  for (let i = 0; i < 61; i++) {
    const x = many[i % many.length];
    r1.push(result('new_lossless', x, 'Qobuz FLAC · verified lossless', { status: 'lossless', source: 'qobuz',
      path: `Library/${x.folder}/${x.artist} - ${x.title}.aiff` }));
  }
  runs.push(runDetail(runId(s1), s1, 3720, 130, r1, 61, 2));
  for (let k = 2; k < n; k++) {
    const sk = daysAgo(now, k + 1, 20, 10 + (k % 40));
    const x = tracks[k % tracks.length];
    runs.push(runDetail(runId(sk), sk, 600 + k * 30, 0, [result('new_lossless', x, 'Qobuz FLAC · verified lossless',
      { status: 'lossless', source: 'qobuz', path: `Library/${x.folder}/${x.artist} - ${x.title}.aiff` })], null, 1));
  }
  return runs;
}

// ---------- candidates (Wrong song?) ----------
export function sampleCandidates(t: FakeTrack): Candidate[] {
  const c = (source: Source, id: string, title: string, duration_s: number | null, more: Partial<Candidate>): Candidate => ({
    source, id, title, artist: t.artist, duration_s, url: source === 'qobuz' ? null : `https://example.org/${source}/${id}`,
    isrc: null, album: null, label: null, image_url: null, key: `${source}:${id}`, source_name: SOURCE_NAMES[source],
    length_diff_s: duration_s === null ? null : Math.round((duration_s - t.duration_s) * 10) / 10,
    can_preview: source !== 'qobuz', score: null, matches: true, length_ok: true, current: false, rejected: false,
    ...more,
  });
  return [
    c(t.source ?? 'youtube', 'cur1', t.title, t.duration_s + 41, { current: true, score: 62, length_ok: false,
      matches: false }),
    c('youtube_music', 'ytm2', t.title, t.duration_s + 1, { score: 96, album: 'Hard Bounce Vol. 3' }),
    c('soundcloud', 'sc3', `${t.title} (Edit)`, t.duration_s - 18, { score: 71, length_ok: false }),
    c('qobuz', '448812', t.title, t.duration_s, { score: 88, isrc: t.isrc, album: 'Hard Dance Essentials',
      label: 'Kontor' }),
    c('youtube', 'yt5', `${t.title} (Live)`, t.duration_s + 95, { score: 40, length_ok: false, matches: false,
      rejected: true }),
    // DRM-protected upload: its preview answers "protected" and the dialog takes it off the list
    c('soundcloud', 'drm6', `${t.title} (Original Mix)`, t.duration_s, { score: 90 }),
  ];
}

// ---------- the state per scenario ----------
export const FAKE_MUSIC = '/Users/you/Music/Discjockey';
export function setupComplete(): SetupStatus {
  return { music: { state: 'ok', path: FAKE_MUSIC, suggested: FAKE_MUSIC }, tools: { ffmpeg: true, ffprobe: true, deno: true }, spotify_app: true, spotify_login: true, qobuz: true,
    playlists: true, complete: true, next_step: null, version: '1.0.0', qobuz_skipped: false,
    accounts: { youtube: null, soundcloud: null } };
}
export function nextStep(s: SetupStatus): SetupStatus {
  const missingTools = !s.tools.ffmpeg || !s.tools.ffprobe || !s.tools.deno;
  const next = s.music.state !== 'ok' ? 'music' : missingTools ? 'tools' : !(s.spotify_app && s.spotify_login) ? 'spotify' : !(s.qobuz || s.qobuz_skipped) ? 'downloads'
    : !s.playlists ? 'playlists' : null;
  return { ...s, next_step: next, complete: next === null };
}
export function spotifyOk(minutes = 2, now = new Date()): SpotifyStatus {
  return { read_at: iso(new Date(now.getTime() - minutes * 60000)), minutes_ago: minutes, problem: null, message: '',
    stale: false, reading: false, offline: false, auto_read: true };  // as after the hub's read when it opens
}

export function makeState(scenario: string, now = new Date()): FakeState {
  const big = scenario === 'big';
  const tracks = sampleTracks(now, big ? 1494 : 35);
  if (big) {
    // keep about 300 to-do items: lift most lossy tracks to lossless
    let todo = 0;
    for (const t of tracks) {
      if (todoGroup(t)) todo++;
      if (todo > 300 && todoGroup(t) && !t.upgrade) { t.status = 'lossless'; t.cutoff_hz = null; t.source = 'qobuz'; t.other = null; }
    }
  }
  const playlists = samplePlaylists();
  if (big) {
    for (let i = 0; i < 8; i++) {
      playlists.push({ folder: `Set_${String(i + 1).padStart(2, '0')}`, link: `https://open.spotify.com/playlist/Set${i}xxxxxxxxxxxxxxxxx`,
        enabled: true, info: { name: `Set ${i + 1}`, owner_name: 'DJ One', yours: true, collaborative: false,
          readable: true, image_url: null, track_count: 30 + i } });
    }
  }
  const days = Array.from({ length: 14 }, (_, i) => (i === 13 ? 37 : [12, 0, 44, 60, 31, 0, 0, 58, 75, 20, 9, 0, 66][i]));
  const s: FakeState = {
    scenario, folders: {}, pick: '/Users/you/Music/DJ Sets', now, tracks, newTracks: newTracks(big ? 60 : 10),
    extraFolders: [{ folder: 'Old_Sets', in_playlists_txt: false }],
    playlists, version: 1, runs: sampleRuns(now, tracks, big ? 30 : 3),
    qobuz: { limit: 60, extra_today: 0, carry_over: 20, used_today: 37, days,
      signals: [{ time: iso(daysAgo(now, 3, 22, 12)), kind: 'search_failed', message: 'Qobuz search did not answer twice' },
        { time: iso(daysAgo(now, 6, 21, 58)), kind: 'duration_mismatch', message: 'Length 3:12 vs Spotify 4:28' }],
      last_download: iso(daysAgo(now, 0, 21, 47)) },
    setup: setupComplete(), downloadTools: builtInTools(), spotify: spotifyOk(2, now), console_running: false, offline: false, previewRead: true,
    appUpdate: { state: 'up_to_date', current: '1.0.0', latest: null, url: null },
    selected: null, dropped: null, errors: scenario === 'errors', errorTurn: 0, syncStarts: 0, never: [],
    accounts: { youtube: null, soundcloud: null }, qobuzSkipped: false,  // the user's own setup: Qobuz only
  };
  if (scenario === 'first_run' || scenario === 'no_music') {
    s.tracks = []; s.newTracks = []; s.playlists = []; s.runs = []; s.extraFolders = []; s.previewRead = false;
    s.qobuz = { ...s.qobuz, used_today: 0, carry_over: 0, days: Array(14).fill(0), signals: [], last_download: null };
    s.setup = nextStep({ ...setupComplete(), spotify_login: false, qobuz: false, playlists: false });
    s.spotify = { read_at: null, minutes_ago: null, problem: 'not_set_up', message: 'Spotify is not set up yet.',
      stale: false, reading: false, offline: false, auto_read: false };
  }
  if (scenario === 'no_music') {
    s.setup = nextStep({ ...s.setup, music: { state: 'not_chosen', path: null, suggested: FAKE_MUSIC } });
  }
  if (scenario === 'music_missing') {
    s.setup = nextStep({ ...s.setup, music: { state: 'missing', path: '/Volumes/DJ SSD/Discjockey', suggested: FAKE_MUSIC },
      playlists: false });  // no library to read playlists.txt from
  }
  if (scenario === 'offline') {
    s.offline = true;
    s.spotify = { ...spotifyOk(184, now), problem: 'offline', offline: true,
      message: 'Spotify did not answer. Check your internet connection.' };
    s.appUpdate = { state: 'unknown', current: '1.0.0', latest: null, url: null };  // no answer: the page shows nothing
  }
  if (scenario === 'console') s.console_running = true;
  if (scenario === 'update_available') {
    s.appUpdate = { state: 'available', current: '1.0.0', latest: '1.1.0',
      url: 'https://github.com/TheZwiss/discjockey/releases/tag/v1.1.0' };
  }
  return s;
}

/** Folders as the sidebar and library see them: playlists.txt order, then folders with files only. */
export function folderList(s: FakeState): { folder: string; in_playlists_txt: boolean }[] {
  const out = s.playlists.map((p) => ({ folder: p.folder, in_playlists_txt: true }));
  for (const f of s.extraFolders) if (!out.some((o) => o.folder === f.folder)) out.push(f);
  return out;
}
export function playlistRows(s: FakeState): PlaylistRow[] {
  return s.playlists.map((p, index) => {
    const ts = s.tracks.filter((t) => t.playlists.includes(p.folder));
    return { index, folder: p.folder, link: p.link, playlist_id: p.link.split('/').pop() ?? null, enabled: p.enabled,
      info: p.info, tracks: ts.length, quality: byQuality(ts) };
  });
}
export function inFolder(s: FakeState, folder: string | null): FakeTrack[] {
  const files = s.tracks.filter((t) => t.status !== 'missing');
  if (folder === null) return files;
  if (folder === NOT_IN_PLAYLIST) return files.filter((t) => !t.in_playlists);
  return files.filter((t) => t.folder === folder);
}
