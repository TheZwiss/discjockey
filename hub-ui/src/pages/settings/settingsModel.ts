// Settings (spec settings-setup §3): the rows, the one line each says about its state, and which row opens first.
// Pure: the page passes in what the bridge answered and the time.
// The download sources' lines live with the account panel (accountModel), so a row and its panel say the same thing.
import { aboutLine } from '$lib/appUpdate';
import type {
  AppUpdate, DownloadsView, DownloadTool, DownloadTools, JobSnap, SetupStatus, SetupTools, SpotifyStatus, WatchedFolders,
} from '$lib/bridge/types';
import { WHAT_IT_GIVES, checkedWhen, stateLine, type RowLine, type Tone } from '$lib/components/accountModel';
import { shortPath } from '$lib/musicFolder';
import { settingsLine } from '$lib/components/watchedFoldersModel';
import { SETTINGS_ROWS } from '$lib/router';

export type SettingsRow = (typeof SETTINGS_ROWS)[number];
export { SETTINGS_ROWS };
export const ROW_GROUPS: { label: string; rows: SettingsRow[] }[] = [
  { label: 'Downloads', rows: ['qobuz', 'youtube', 'soundcloud'] },
  { label: 'Spotify', rows: ['spotify'] },
  // the watched folders sit with the music folder: both say where Discjockey looks for music on this Mac
  { label: 'This Mac', rows: ['music', 'folders', 'programs', 'about', 'reports'] },
];
export const ROW_NAMES: Record<SettingsRow, string> = {
  qobuz: 'Qobuz', youtube: 'YouTube Premium', soundcloud: 'SoundCloud Go+', spotify: 'Spotify', music: 'Music folder',
  folders: 'Watched folders', programs: 'Programs',
  about: 'About Discjockey', reports: 'Reports',
};
/** Each row's lead glyph, in the sidebar's style (one 14 px box). */
export const ROW_GLYPHS: Record<SettingsRow, string> = {
  qobuz: '◆', youtube: '▶', soundcloud: '☁', spotify: '♫', music: '▤', folders: '◫', programs: '⌘', about: '©', reports: '☰',
};
export function isSettingsRow(v: string | undefined): v is SettingsRow {
  return !!v && (SETTINGS_ROWS as readonly string[]).includes(v);
}
export type AccountRow = 'qobuz' | 'youtube' | 'soundcloud';
/** The download services' rows: their panel is an AccountPanel. */
export function isAccountRow(r: SettingsRow): r is AccountRow {
  return r === 'qobuz' || r === 'youtube' || r === 'soundcloud';
}

export type { RowLine, Tone };
export { checkedWhen };
export type RowContext = {
  downloads: DownloadsView | null; status: SetupStatus | null; tools: SetupTools | null; reports: number | null;
  now: Date;
  /** reading the programs failed and there are no versions to show: the row says so instead of waiting */
  toolsFailed?: boolean;
  /** playlists.txt has a switched-on Spotify line (the read status's `services`) */
  spotifyUsed?: boolean;
  /** the update check's last answer; never a problem, so it never moves `firstAttention` */
  update?: AppUpdate | null;
  /** watched_folders(); null while it is read */
  folders?: WatchedFolders | null;
  /** the hub's write job: a running import says its live count in the Watched folders row */
  job?: JobSnap | null;
};

/** Spotify's state in Settings. "I don't use Spotify" (Setup, plan stage 3 D1) is no problem — `left_out`, Connect
 *  still offered — until playlists.txt has a Spotify line (`used`: the read status's `services` name Spotify); then
 *  it is the missing login it is. */
export type SpotifyState = 'connected' | 'left_out' | 'not_connected' | 'not_set_up';
/** playlists.txt has a switched-on Spotify line: the read status names Spotify among its services. */
export function spotifyUsed(sp: SpotifyStatus | null): boolean {
  return !!sp?.services?.some((x) => x.service === 'spotify');
}
export function spotifyState(s: SetupStatus, used: boolean): SpotifyState {
  if (s.spotify_login) return 'connected';
  if (s.spotify_skipped && !used) return 'left_out';
  return s.spotify_app ? 'not_connected' : 'not_set_up';
}

/** The state line and mark of one row; `null` text pieces are left out. */
export function rowLine(row: SettingsRow, c: RowContext): RowLine {
  switch (row) {
    case 'qobuz':
    case 'youtube':
    case 'soundcloud': {
      if (!c.downloads) return { tone: null, text: '' };
      // a login not set up says what it would give, so the list shows the gain before the panel is open (spec §1)
      const l = stateLine(row, c.downloads, c.now);
      return l.tone === 'none' && l.text === 'not set up' ? { tone: 'none', text: `not set up · ${WHAT_IT_GIVES[row]}` } : l;
    }
    case 'spotify': {
      const s = c.status;
      if (!s) return { tone: null, text: '' };
      switch (spotifyState(s, !!c.spotifyUsed)) {
        case 'connected': return { tone: 'good', text: s.spotify_user ? `connected as ${s.spotify_user}` : 'connected' };
        case 'left_out': return { tone: 'none', text: 'left out' };
        case 'not_connected': return { tone: 'problem', text: 'not connected' };
        case 'not_set_up': return { tone: 'problem', text: 'not set up' };
      }
    }
    case 'music': {
      const m = c.status?.music;
      if (!m) return { tone: null, text: '' };
      if (m.state === 'ok' && m.path) return { tone: 'good', text: shortPath(m.path) };
      return m.state === 'missing' ? { tone: 'problem', text: 'not found' } : { tone: 'none', text: 'not chosen' };
    }
    case 'folders':
      return settingsLine(c.folders ?? null, c.job ?? null);
    case 'programs': {
      if (!c.tools) return c.toolsFailed ? { tone: 'problem', text: "couldn't check" } : { tone: null, text: '' };
      return c.tools.missing.length ? { tone: 'problem', text: `${c.tools.missing.join(', ')} missing` }
        : { tone: 'good', text: 'all there' };
    }
    case 'about':
      return { tone: null, text: c.status ? [c.status.version, aboutLine(c.update ?? null)].filter(Boolean).join(' · ') : '' };
    case 'reports':
      if (c.reports === null) return { tone: null, text: '' };
      return { tone: null, text: c.reports === 0 ? 'no reports yet' : c.reports === 1 ? '1 sync report'
        : `${c.reports} sync reports` };
  }
}

/** `#/settings` opens the first row that needs the user, else Qobuz. A folder that is away (offline, not found) is no such row: its
 *  folder keeps its files and waits (plan library stage 4, §6.4), and a DJ whose drive is mostly unplugged would
 *  land on it every time. */
export function firstAttention(c: RowContext): SettingsRow {
  return SETTINGS_ROWS.find((r) => {
    if (r === 'folders') return false;
    const t = rowLine(r, c).tone;
    return t === 'problem' || t === 'warn';
  }) ?? 'qobuz';
}

function versions(v: unknown): Record<string, string> {
  if (!v || typeof v !== 'object') return {};
  return Object.fromEntries(Object.entries(v as Record<string, unknown>).map(([k, x]) => [k, x == null ? '' : String(x)]));
}

/** update_tools' {before, after} as lines: "streamrip 2.1.0 → 2.1.1", or "yt-dlp 2026.10.10 (already the newest)". */
export function updateLines(before: unknown, after: unknown): string[] {
  const b = versions(before);
  const a = versions(after);
  const names = [...new Set([...Object.keys(b), ...Object.keys(a)])];
  return names.map((n) => {
    const was = b[n] || 'not installed';
    const now = a[n] || 'not installed';
    return was === now ? `${n} ${now} (already the newest)` : `${n} ${was} → ${now}`;
  });
}

export type ToolsCard = { rows: { name: string; value: string }[]; waiting: string | null; back: string | null };

function toolValue(t: DownloadTool): string {
  return t.version ? `${t.version} (${t.source === 'updated' ? 'updated' : 'built in'})` : 'not installed';
}

/** Settings → This Mac, Download tools: "yt-dlp 2026.10.21 (updated)" / "(built in)" per tool (spec
 *  public-release §6.4); `waiting`: the yt-dlp the next start uses (Quit becomes the step); `back`: what Go back
 *  would use. */
export function toolsCard(t: DownloadTools | null | undefined): ToolsCard {
  if (!t) return { rows: [], waiting: null, back: null };
  return { rows: [{ name: 'yt-dlp', value: toolValue(t['yt-dlp']) }, { name: 'streamrip', value: toolValue(t.streamrip) }],
    waiting: t['yt-dlp'].waiting, back: t['yt-dlp'].previous };
}

/** Whether Discjockey has to be opened again for the download tools: a yt-dlp is waiting for the next start
 *  (`card.waiting`, read with setup_check_tools), or the last change said so (`restart`, the engine's answer: it covers
 *  the moment before the versions are read again, or a failed read). "Already the newest" needs no reopen. */
export function needsReopen(card: Pick<ToolsCard, 'waiting'>, restart: boolean): boolean {
  return card.waiting !== null || restart;
}

/** What the reopen note says (it is shown once `needsReopen`): the title is the step, the text names the version
 *  that starts being used. `kind` is the change that asked for it; a waiting version names itself. */
export function reopenNote(waiting: string | null, kind: 'update_tools' | 'rollback_tools' | null, quitting: boolean):
  { title: string; text: string } {
  const what = waiting ? `yt-dlp ${waiting}` : kind === 'rollback_tools' ? 'the earlier yt-dlp' : 'the new yt-dlp';
  return { title: 'Open Discjockey again',
    text: quitting ? `Open Discjockey again to start using ${what}.`
      : `Quit Discjockey and open it again to start using ${what}.` };
}

/** The hub's write job when it is this card's own (Spotify's Connect: `setup_spotify_login`; Programs' update and
 *  Go back: `update_tools`, `rollback_tools`), so a panel opened while it runs, or after it ended, picks it up: its
 *  id to wait for while it runs, else how it ended. null: no job, or another kind. */
export function cardJob(job: JobSnap | null, kind: 'setup_spotify_login' | 'update_tools' | 'rollback_tools'):
  { id: number; running: true } | { id: number; running: false; finished: JobSnap['finished'] } | null {
  if (!job || job.kind !== kind) return null;
  return job.running ? { id: job.id, running: true } : { id: job.id, running: false, finished: job.finished };
}

/** How Update download tools or Go back ended, as the card says it: the before → after lines, whether Discjockey
 *  has to be opened again to use them (`restart`, the engine's answer: "already the newest" needs no reopen), or
 *  the problem's words; a stopped job says nothing. */
export function updateOutcome(fin: { ok: boolean; problem?: string | null; message?: string; result?: unknown } | null):
  { lines: string[] | null; error: string | null; restart: boolean } {
  if (!fin) return { lines: null, error: null, restart: false };
  if (fin.ok) {
    const r = (fin.result ?? {}) as { before?: unknown; after?: unknown; restart?: unknown };
    return { lines: updateLines(r.before, r.after), error: null, restart: r.restart === true };
  }
  return { lines: null, error: fin.problem === 'stopped' ? null : fin.message || null, restart: false };
}
