// Number and date formats used everywhere (plan 64.10). "3:12", "74 %", "16.0 kHz", "Today 21:47".
import type { FileState, Quality, Service, TrackDetail } from './bridge/types';
const NONE = '—';
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const two = (n: number) => String(n).padStart(2, '0');

/** 192 → "3:12"; 3725 → "1:02:05"; null → "—". */
export function duration(s: number | null | undefined): string {
  if (s === null || s === undefined || !Number.isFinite(s) || s < 0) return NONE;
  const t = Math.round(s);
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), sec = t % 60;
  return h ? `${h}:${two(m)}:${two(sec)}` : `${m}:${two(sec)}`;
}
/** 25 → "25 min"; 92 → "1 h 32 min"; 120 → "2 h". */
export function minutesLong(min: number | null | undefined): string {
  if (min === null || min === undefined || !Number.isFinite(min)) return NONE;
  const t = Math.max(0, Math.round(min));
  if (t < 60) return `${t} min`;
  const h = Math.floor(t / 60), m = t % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}
/** Every time estimate in one format (spec §11 "one time format"): below 2 h in minutes, "~75" min; then hours to the
 * half hour, "~2.5" h; "~" marks it as an estimate, as the service rows' "~4 of 30". The compact form wins because it
 * has to fit Sync's run time card ("~1 h 15 min" was cut off at 1280), and a minute-exact "1 h 15 min" claims more
 * than an estimate knows. Value and unit apart for a StatCard; `estimateText` joins them for a line. */
export function estimate(min: number | null | undefined): { value: string; unit: string } {
  if (min === null || min === undefined || !Number.isFinite(min)) return { value: NONE, unit: '' };
  const t = Math.max(0, Math.round(min));
  if (t < 120) return { value: `~${t}`, unit: 'min' };
  return { value: `~${Math.round(t / 30) / 2}`, unit: 'h' };
}
/** 75 → "~75 min"; 200 → "~3.5 h"; null → "—". */
export function estimateText(min: number | null | undefined): string {
  const e = estimate(min);
  return e.unit ? `${e.value} ${e.unit}` : e.value;
}
/** 19_800_000 → "19.8" (MB, as Finder counts). */
export function megabytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return NONE;
  return (bytes / 1e6).toFixed(1);
}
/** 0.7412 → "74 %"; null → "—". */
export function percent(share: number | null | undefined): string {
  if (share === null || share === undefined || !Number.isFinite(share)) return NONE;
  return `${Math.round(share * 100)} %`;
}
/** 16000 → "16.0 kHz". */
/** What a quality class means, next to its badge (whose label may already say "LOSSY"). */
export function qualityWords(q: Quality, label = '', checked = true): string {
  if (!checked) return 'sound not checked yet';
  if (label === 'LOSSY' && q === 'good_lossy') return 'hard to hear';
  return { lossless: 'verified lossless', good_lossy: 'lossy, hard to hear', weak: 'lossy, audible',
    fake: 'fake lossless', missing: 'no file yet' }[q];
}

export function khz(hz: number | null | undefined): string {
  if (hz === null || hz === undefined || !Number.isFinite(hz)) return NONE;
  return `${(hz / 1000).toFixed(1)} kHz`;
}
/** Minutes since → "just now" / "2 min ago" / "3 h ago" / "yesterday" / "4 days ago". */
export function ago(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes)) return 'never';
  const m = Math.max(0, Math.floor(minutes));
  if (m < 1) return 'just now';
  if (m < 60) return `${m} min ago`;
  if (m < 24 * 60) return `${Math.floor(m / 60)} h ago`;
  if (m < 48 * 60) return 'yesterday';
  return `${Math.floor(m / (24 * 60))} days ago`;
}
function parse(iso: string): Date | null {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}
const sameDay = (a: Date, b: Date) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth()
  && a.getDate() === b.getDate();
/** "Today 21:47" / "Yesterday 21:47" / "Mon 13 Oct". */
export function runWhen(iso: string | null | undefined, now: Date | number = new Date()): string {
  const d = iso ? parse(iso) : null;
  if (!d) return NONE;
  const n = new Date(now);
  const time = `${two(d.getHours())}:${two(d.getMinutes())}`;
  if (sameDay(d, n)) return `Today ${time}`;
  const y = new Date(n); y.setDate(y.getDate() - 1);
  if (sameDay(d, y)) return `Yesterday ${time}`;
  return `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}
/** "13 Oct 2026". */
export function dateShort(iso: string | null | undefined): string {
  const d = iso ? parse(iso.length === 10 ? `${iso}T12:00:00` : iso) : null;
  return d ? `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}` : NONE;
}
/** "21:47". */
export function clock(iso: string | null | undefined): string {
  const d = iso ? parse(iso) : null;
  return d ? `${two(d.getHours())}:${two(d.getMinutes())}` : NONE;
}
/** plural(1, 'track') → "1 track"; plural(3, 'track') → "3 tracks"; plural(2, 'match', 'matches'). */
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
/** "Artist – Title" with an en dash. */
export function artistTitle(artist: string | null | undefined, title: string | null | undefined): string {
  return [artist, title].filter((x) => x && String(x).trim()).join(' – ');
}
/** ".../reports/2026-10-16_132430.md" → "2026-10-16_132430". */
export function runIdFromReport(path: string | null | undefined): string | null {
  if (!path) return null;
  const base = path.split(/[\\/]/).pop() ?? '';
  return base.replace(/\.md$/i, '') || null;
}
export type NotePart = { text: string } | { label: string; href: string };
/** Report notes contain Markdown links ("[Beatport](https://…)"): split them into text and links. */
export function noteParts(note: string | null | undefined): NotePart[] {
  if (!note) return [];
  const out: NotePart[] = [];
  const re = /\[([^\]]+)\]\((https:\/\/[^)\s]+)\)/g;
  let at = 0;
  for (let m = re.exec(note); m; m = re.exec(note)) {
    if (m.index > at) out.push({ text: note.slice(at, m.index) });
    out.push({ label: m[1], href: m[2] });
    at = m.index + m[0].length;
  }
  if (at < note.length) out.push({ text: note.slice(at) });
  return out;
}
/** A stable number from a string (cover placeholder colours). */
export function hashOf(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return Math.abs(h | 0);
}

/** "found 16 Oct" for the upgrade box. */
export function foundText(iso: string | null | undefined): string {
  const d = dayMonth(iso);
  return d ? `found ${d}` : '';
}
/** "18 Oct" from an ISO date (its calendar date, whatever the time zone); '' when there is none. Library's Added. */
export function dayMonth(iso: string | null | undefined): string {
  const m = iso ? /^(\d{4})-(\d{2})-(\d{2})/.exec(iso) : null;
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}` : '';
}

/** The upgrade box's heading: "Upgrade ready", and for a better lossy stream what it is ("· 256 kbps version"). */
export function upgradeLabel(what: string | null | undefined): string {
  return what && what !== 'lossless version' ? `Upgrade ready · ${what}` : 'Upgrade ready';
}

/** Green dot for exact/aligned cue points, yellow for anything that doesn't match. */
export function cueTone(result: string | null | undefined): 'lossless' | 'good_lossy' {
  return result === 'exact' || result === 'aligned' ? 'lossless' : 'good_lossy';
}

/** Text for searching: Unicode-normalised, case-insensitive and accent-free, the same idea as the library search
 * (names.fold). "Kölsch" → "kolsch". */
export const foldText = (s: string) => s.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase();

/**
 * A service's name where it labels a row or column: "YouTube", not "YouTube Premium". The plan ("Premium", "Go+") is
 * account detail; Download limits and tooltips show it with the account's full name.
 */
const SERVICE_SHORT: Record<Service, string> = { qobuz: 'Qobuz', youtube: 'YouTube', soundcloud: 'SoundCloud' };
export function serviceName(service: Service, full: string): string {
  return SERVICE_SHORT[service] ?? full;
}

/**
 * `text` in the width it has (`fits` says whether a text fits): whole while it fits; else its middle gives way to "…"
 * and both ends stay, the end a little longer, since the end is what tells two long names apart
 * ("Artist - Title (… EDIT).wav" against "Artist - Title (… EDIT)(1).wav"). At least a character of each end stays, even
 * when nothing fits (the element clips the rest).
 */
export function fitMiddle(text: string, fits: (text: string) => boolean): string {
  if (fits(text) || text.length <= 2) return text;
  const cut = (n: number) => {
    const tail = Math.ceil(n / 2);
    return `${text.slice(0, n - tail).trimEnd()}…${text.slice(text.length - tail).trimStart()}`;
  };
  let lo = 2, hi = text.length - 1;   // n characters of the text stay; lo is the least there is, hi the most
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (fits(cut(mid))) lo = mid; else hi = mid - 1;
  }
  return cut(lo);
}

/** What a watched folder's state line and a file's picture say when its drive is away (library stage 4, W3). */
export const OFFLINE_WORDS = 'Offline: connect the drive';
/** A watched folder's row when the folder isn't found (moved, renamed or deleted; the row keeps its ×). */
export const FOLDER_NOT_FOUND_LINE = 'Folder not found: moved, renamed or deleted? Put it back or remove it here.';
/** What a file's picture says in the Library and To-do panels when the file isn't there, by why. */
export const FILE_STATE_WORDS: Record<Exclude<FileState, 'here'>, string> = {
  offline: OFFLINE_WORDS,
  folder_missing: 'Folder not found',
  file_missing: "This file isn't there any more.",
};
/** The track has a file, but it isn't there to play (the panels: no Show in Finder, the player off). */
export const fileAway = (t: Pick<TrackDetail, 'status' | 'file_state'>): boolean =>
  t.status !== 'missing' && t.file_state !== 'here';
/** The words for a track whose file isn't there; null when it is (or there is no file to be away). */
export const fileAwayWords = (t: Pick<TrackDetail, 'status' | 'file_state'>): string | null =>
  fileAway(t) && t.file_state !== 'here' ? FILE_STATE_WORDS[t.file_state] : null;

/** The name of a file's container as people say it ("FLAC", "WAV", "AIFF"), from its path's extension; null for none
 *  we know (a path without an extension, a lossy format). */
const FILE_FORMATS: Record<string, string> = { flac: 'FLAC', wav: 'WAV', wave: 'WAV', aif: 'AIFF', aiff: 'AIFF', aifc: 'AIFF',
  alac: 'ALAC', caf: 'CAF', wv: 'WavPack', ape: 'APE' };
export function fileFormat(path: string | null | undefined): string | null {
  const m = /\.([A-Za-z0-9]+)$/.exec(path ?? '');
  return (m && FILE_FORMATS[m[1].toLowerCase()]) || null;
}

/** The current file's cutoff as a number for its StatCard (where the highs end, over the spectrum; To-do and
 *  Library): null for a lossless file or none (nothing to show), "—" (value null) when the analysis found no edge.
 *  A fake lossless file names the format it really is ("a lossy file inside the WAV"), else says "a lossless file". */
export function cutoffStat(t: Pick<TrackDetail, 'status' | 'cutoff_hz'> & { sound_checked?: boolean; path?: string | null }): { value: string | null; label: string } | null {
  // a file whose sound isn't checked yet has no cutoff to show: "no clear edge" would be a verdict
  if (t.status === 'lossless' || t.status === 'missing' || t.sound_checked === false) return null;
  const value = t.cutoff_hz ? (t.cutoff_hz / 1000).toFixed(1) : null;
  if (t.status === 'fake_lossless') {
    const format = fileFormat(t.path);
    return { value, label: `where the highs end · a lossy file inside ${format ? `the ${format}` : 'a lossless file'}` };
  }
  return { value, label: value ? 'where the highs end · lossless reaches about 22 kHz' : 'no clear edge in the highs' };
}
