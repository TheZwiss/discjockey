// Fake mode: Convert to AIFF, Give it its clean name, Make all lossless files AIFF and the "Won't play well on CDJs"
// group (issue 33 stage D). Ports, in this order, discjockey/cdj.py (the CDJ rule), aiff_plan.py (the plan: what each
// file becomes, the room it needs, what is left as it is) and the words of rbstep.py / views.py, computed from the fake
// library so a scenario only sets data: a track's `audio` (the facts the import stored), `cloud`, `inRekordbox`,
// `away`, `upgrade`, the state's `rekordbox_state` / `rekordbox_running` and `freeBytes`. Pure: nothing here keeps state;
// the bridge runs the jobs and keeps the batch records.
import type { AiffLeft, AiffPlan, AiffPlanItem, AiffScope, CdjWhy, TrackAiff } from '../types';
import { FAKE_MUSIC, dateOnly, hash, pathOf, type FakeAudio, type FakeState, type FakeTrack } from './data';
import { libraryOf } from './library';

export const AIFF_LINE = 'AIFF · 16-bit · 44.1 kHz';
export const NOTHING_TO_CHANGE = 'Nothing to change: these are clean AIFFs already.';
export const BAD_SCOPE = "That isn't a set of files Discjockey can make AIFF.";
export const NONE_CHANGEABLE = 'None of these can be changed right now.';
const NO_TRACK_NOTE = "This file isn't in your rekordbox collection, so there was nothing to keep there.";
const NO_FREE_NAME = 'no free file name is left for it';
/** the room a drive has unless `FakeState.freeBytes` says otherwise */
const DEFAULT_FREE = 400_000_000_000;

/** The words of a skip (batches.words for an item of Convert or Rename: rbstep.CONVERT_REFUSED, REFUSED and the own-file
 *  words), also the ones a run finds (`timing`, `not_analysed`, `changed`). */
export const SKIP_WORDS: Record<string, string> = {
  downloaded: 'Discjockey downloaded this file: it is a clean AIFF already. Nothing was changed.',
  no_name: "This song has no artist or title yet, so Discjockey can't give its file a clean name. Nothing was changed.",
  upgrade_waits: 'A better version is waiting: Same track makes it an AIFF.',
  clean_aiff: 'This file is a clean AIFF already: Give it its clean name.',
  named_already: 'A clean AIFF with its clean name already.',
  needs_convert: "This file isn't a clean AIFF yet: Convert to AIFF gives it its clean name too. Nothing was changed.",
  away: "The file's drive isn't connected, so nothing was changed.",
  file_missing: "Discjockey can't find the file where it expects it. Run a sync first, so it can find the file again. Nothing was changed.",
  rekordbox_unreadable: "Discjockey can't open this rekordbox version's library yet, so it can't point your rekordbox track at the file. Nothing was changed.",
  cloud: "This track is in rekordbox's Cloud Library Sync, which Discjockey doesn't change yet. Nothing was changed.",
  rename_blocked: `Discjockey can only give this file its new name while it can point your rekordbox track at it, and it can't right now (${NO_FREE_NAME}). Nothing was changed.`,
  timing: "Discjockey couldn't line the new file up with your rekordbox track exactly, so nothing was changed. Analyse the track again in rekordbox and try again.",
  not_analysed: "rekordbox hasn't analysed this track yet, so Discjockey can't tell exactly where your cues sit. Nothing was changed. Analyse it in rekordbox, quit rekordbox, and try again.",
  changed: 'Your rekordbox track changed while Discjockey was working on it, so nothing was changed. Try again.',
};
/** the reasons a file can't run now but may later, in the order `waiting` lists them (aiff_plan.WAITING) */
const WAITING = ['away', 'file_missing', 'no_name', 'rekordbox_unreadable', 'cloud', 'rename_blocked', 'upgrade_waits'];
/** the reasons a one-file answer has nothing to say for (aiff_plan.NO_ANSWER) */
const NO_ANSWER = ['file_missing', 'downloaded', 'upgrade_waits'];

const KIND_ORDER = ['flac', 'wav', 'alac', 'aiff_hires', 'tags', 'name', 'wavpack', 'ape', 'tta', 'mp3', 'aac', 'opus', 'vorbis'];
const KIND_LABELS: Record<string, string> = { flac: 'FLAC → AIFF', wav: 'WAV → AIFF', alac: 'ALAC → AIFF',
  aiff_hires: 'AIFF 24-bit or above 44.1 kHz → 16-bit', tags: 'New tags', name: 'Clean name only' };
const LOSSLESS_CODECS = ['flac', 'alac', 'wavpack', 'ape', 'tta'];
const NAMES: Record<string, string> = { opus: 'Opus', aac: 'AAC', mp3: 'MP3', flac: 'FLAC', vorbis: 'Vorbis', alac: 'ALAC',
  wmav1: 'WMA', wmav2: 'WMA', wmapro: 'WMA', wmalossless: 'WMA', ac3: 'AC-3', eac3: 'E-AC-3', dts: 'DTS', wavpack: 'WavPack',
  ape: 'APE', tta: 'TTA' };
const CONTAINERS: Record<string, string> = { aiff: 'AIFF', aif: 'AIFF', wav: 'WAV', flac: 'FLAC', mp3: 'MP3', ogg: 'OGG', opus: 'Opus' };

const isLosslessCodec = (codec: string) => codec.startsWith('pcm_') || LOSSLESS_CODECS.includes(codec);
const fold = (s: string) => s.normalize('NFC').toLowerCase();
const base = (p: string) => p.split('/').pop()!;
const dirOf = (p: string) => p.includes('/') ? p.slice(0, p.lastIndexOf('/')) : '';
const extOf = (path: string) => (/\.([^./]+)$/.exec(path)?.[1] ?? '').toLowerCase();
const khz = (rate: number) => `${rate / 1000}`;
const nameOf = (t: { artist: string; title: string }) => `${t.artist} - ${t.title}`;

/** An own file: bought or found by the import (the engine's source `manual`). */
export const isOwn = (t: FakeTrack) => t.source === 'manual';

// ---------- the stored facts ----------

/** The facts the import stored about the file, or null (a download, no file). A track without `audio` has the facts its
 *  extension suggests: a WAV is 24-bit PCM at 44.1 kHz (what the details panel already says), an AIFF 16-bit with tags
 *  that aren't the download's, a FLAC 16-bit, an MP3 320 kbps. */
export function storedAudio(t: FakeTrack): FakeAudio | null {
  if (!isOwn(t) || t.status === 'missing' || !pathOf(t)) return null;
  if (t.audio) return t.audio;
  const ext = extOf(pathOf(t)!);
  if (ext === 'aiff' || ext === 'aif') return { codec: 'pcm_s16be', rate: 44100, bits: 16, kbps: null };
  if (ext === 'flac') return { codec: 'flac', rate: 44100, bits: 16, kbps: null };
  if (ext === 'mp3') return { codec: 'mp3', rate: 44100, bits: null, kbps: 320 };
  return { codec: 'pcm_s24le', rate: 44100, bits: 24, kbps: null };
}
const extOfTrack = (t: FakeTrack, a: FakeAudio) => (a.ext ?? extOf(pathOf(t)!)).toLowerCase();

/** cdj.format_name: the container for PCM (WAV, AIFF), else the codec (MP3, AAC, FLAC, Opus ...). */
function formatName(a: FakeAudio, ext: string): string {
  return a.codec.startsWith('pcm_') ? CONTAINERS[ext] ?? 'PCM' : NAMES[a.codec] ?? a.codec.toUpperCase();
}
/** aiff_plan.format_line: "FLAC · 24-bit · 96 kHz", "MP3 · 320 kbps". */
function formatLine(a: FakeAudio, ext: string): string {
  const parts = [formatName(a, ext)];
  if (a.bits) parts.push(`${a.bits}-bit`);
  if (a.rate) parts.push(`${khz(a.rate)} kHz`);
  if (!isLosslessCodec(a.codec) && a.kbps) parts.push(`${a.kbps} kbps`);
  return parts.join(' · ');
}
const isAiff1644 = (ext: string, a: FakeAudio) =>
  (ext === 'aiff' || ext === 'aif') && a.codec.startsWith('pcm_s16') && a.bits === 16 && a.rate === 44100;

// ---------- the CDJ rule (cdj.cdj_problem) ----------

/** The first rule of plan §1.4 the file breaks, else null: MP3/AAC up to 320 kbps and 48 kHz; WAV, AIFF, FLAC and ALAC
 *  16- or 24-bit at 44.1-96 kHz. A value that is missing never matches its rule. */
export function cdjProblem(a: FakeAudio, ext: string): CdjWhy | null {
  const lossy = a.codec === 'mp3' || a.codec === 'aac';
  const lossless = a.codec.startsWith('pcm_') || a.codec === 'flac' || a.codec === 'alac';
  const name = formatName(a, ext);
  if (!(lossy || lossless)) return { reason: 'format', short: `${name} · CDJs don't play it`, words: `CDJs don't play ${name} files.` };
  if (lossy && a.kbps !== null && a.kbps > 320) {
    return { reason: 'bitrate', short: `${name} ${a.kbps} kbps · CDJs stop at 320`,
      words: `${name} at ${a.kbps} kbps: CDJs play ${name} only up to 320 kbps, so it may not load or may stutter.` };
  }
  if (lossless && a.bits !== null && a.bits !== 16 && a.bits !== 24) {
    const depth = `${a.bits}-bit${a.codec.startsWith('pcm_f') ? ' float' : ''}`;
    return { reason: 'bits', short: `${name} ${depth} · CDJs play 16/24-bit`, words: `${name} ${depth}: CDJs play only 16- and 24-bit files.` };
  }
  if (a.rate !== null) {
    const limit = lossy ? 48000 : 96000;
    if (a.rate > limit) {
      return { reason: 'rate_high', short: `${name} ${khz(a.rate)} kHz · CDJs stop at ${khz(limit)} kHz`,
        words: `${name} at ${khz(a.rate)} kHz: CDJs play ${name} only up to ${khz(limit)} kHz.` };
    }
    if (lossless && a.rate < 44100) {
      return { reason: 'rate_low', short: `${name} ${khz(a.rate)} kHz · CDJs need 44.1 kHz`,
        words: `${name} at ${khz(a.rate)} kHz: CDJs play ${name} from 44.1 kHz.` };
    }
  }
  return null;
}

/** cdj.group_members: the songs of To-do's "Won't play well on CDJs" group with their problems, in library order: an own
 *  file with a path and stored facts the rule flags, no parked upgrade, hidden only with `includeHidden`. */
export function cdjMembers(s: FakeState, includeHidden = false): Map<string, CdjWhy> {
  const found = new Map<string, CdjWhy>();
  for (const t of s.tracks) {
    if (t.upgrade || (t.hidden && !includeHidden)) continue;
    const a = storedAudio(t);
    const problem = a && cdjProblem(a, extOfTrack(t, a));
    if (problem) found.set(t.track_id, problem);
  }
  return found;
}

// ---------- the plan (aiff_plan.plan) ----------

type Skip = { reason: string; message: string };
type Judged = { item: (AiffPlanItem & { lossy: boolean; oldBytes: number; held: boolean }) | null; skip: Skip | null };
const skipOf = (reason: string): Judged => ({ item: null, skip: { reason, message: SKIP_WORDS[reason] } });
/** Whether rekordbox has a track of this file to change (it has a library, and holds the file). */
export const heldInRekordbox = (s: FakeState, t: FakeTrack) => (s.rekordbox_state ?? 'ready') === 'ready' && t.inRekordbox !== false;
const oldBytesOf = (t: FakeTrack, a: FakeAudio) => Math.round(t.duration_s * (a.kbps && !isLosslessCodec(a.codec)
  ? a.kbps * 125 : ((a.rate ?? 44100) * (a.bits ?? 16) * 2) / 8 * (a.codec.startsWith('pcm_') ? 1 : 0.6)));

function judge(s: FakeState, t: FakeTrack | undefined, taken: Set<string>, only: 'rename' | undefined): Judged {
  if (!t) return skipOf('file_missing');
  const path = pathOf(t);
  if (t.status === 'missing' || !path) return skipOf('file_missing');
  if (t.away) return skipOf(t.away === 'offline' ? 'away' : 'file_missing');
  if (!isOwn(t)) return skipOf('downloaded');
  if (t.upgrade) return skipOf('upgrade_waits');
  const a = storedAudio(t)!;
  if (!t.artist.trim() || !t.title.trim()) return skipOf('no_name');
  const state = s.rekordbox_state ?? 'ready';
  // what rekordbox's state says, asked after a clean AIFF's `named_already` and a Rename's `needs_convert` (the engine's order)
  const blocked = (): Judged | null => state === 'unreadable' ? skipOf('rekordbox_unreadable') : t.cloud && state === 'ready' ? skipOf('cloud') : null;
  const ext = extOfTrack(t, a);
  const dir = dirOf(path);
  const clean = `${dir}/${nameOf(t)}.aiff`;
  const id = Math.abs(hash(t.track_id)).toString(36).slice(0, 6);
  const idName = `${dir}/${nameOf(t)} [${id}].aiff`;
  const held = heldInRekordbox(s, t);
  const make = (action: 'convert' | 'rename', kind: string, newPath: string, superseded: string | null): Judged => {
    taken.add(fold(newPath));
    return { skip: null, item: { track: t.track_id, name: nameOf(t), action, kind, from: formatLine(a, ext), path, new_path: newPath,
      superseded, bytes: action === 'convert' ? Math.ceil(t.duration_s * 44100) * 4 + 4096 : 0,
      cdj: cdjWords(cdjProblem(a, ext)), lossy: !isLosslessCodec(a.codec), oldBytes: action === 'convert' ? oldBytesOf(t, a) : 0, held } };
  };
  if (isAiff1644(ext, a) && a.tagsClean === true) {
    // a clean AIFF: only its name is left
    if (fold(clean) === fold(path)) return skipOf('named_already');
    const stopped = blocked();
    if (stopped) return stopped;
    const free = !taken.has(fold(clean)) ? clean : !taken.has(fold(idName)) ? idName : null;
    if (free === null) return skipOf('rename_blocked');
    return make('rename', 'name', free, null);
  }
  if (only === 'rename') return skipOf('needs_convert');
  const stopped = blocked();
  if (stopped) return stopped;
  // the AIFF takes the clean name, or the ID name when another file holds it; an AIFF that already has the clean name
  // ends where the old file was
  const chain = fold(clean) === fold(path);
  const newPath = chain ? path : !taken.has(fold(clean)) ? clean : idName;
  const kind = a.codec.startsWith('pcm_') ? (ext !== 'aiff' && ext !== 'aif' ? 'wav' : isAiff1644(ext, a) ? 'tags' : 'aiff_hires') : a.codec;
  return make('convert', kind, newPath, `Superseded/${base(path)}`);
}
const cdjWords = (p: CdjWhy | null) => p ? { short: p.short, words: p.words } : null;

const kindRank = (k: string) => KIND_ORDER.includes(k) ? KIND_ORDER.indexOf(k) : KIND_ORDER.length;
const driveOf = (p: string) => /^\/Volumes\/[^/]+/.exec(p)?.[0] ?? FAKE_MUSIC;

/** aiff_plan.plan for a scope, or `{refused}` with the words of a scope that isn't one of the three (api._aiff_scope).
 *  `only: 'rename'`: Rename's answer alone (a file that needs a Convert is left out). The plan's items are the batch's. */
export function planOf(s: FakeState, scope: AiffScope, only?: 'rename'): { plan: AiffPlan } | { refused: string } {
  let keys: string[]; let label: string;
  const sc = scope as { kind?: unknown; tracks?: unknown; view?: unknown; key?: unknown } | null;
  if (!sc || typeof sc !== 'object' || !['tracks', 'lossless', 'cdj'].includes(sc.kind as string)) {
    return { refused: BAD_SCOPE };
  }
  if (sc.kind === 'tracks') {
    const list = sc.tracks;
    if (!Array.isArray(list) || !list.length || !list.every((i) => typeof i === 'string' && i)) return { refused: 'No tracks were chosen.' };
    keys = [...new Set(list as string[])]; label = 'Selection';
    scope = { kind: 'tracks', tracks: keys };
  } else if (sc.kind === 'cdj') {
    keys = [...cdjMembers(s).keys()]; label = "Won't play well on CDJs"; scope = { kind: 'cdj' };
  } else {
    // api._aiff_scope: a view the Library has, and a key for a playlist or a folder (none for the others)
    const view = sc.view ?? 'all';
    const named = view === 'playlist' || view === 'folder';
    if (!['all', 'unlisted', 'playlist', 'folder'].includes(view as string) || (named && !(typeof sc.key === 'string' && sc.key))) {
      return { refused: BAD_SCOPE };
    }
    scope = { kind: 'lossless', view: view as 'all', key: named ? (sc.key as string) : null };
    const found = libraryOf(s, view as string, named ? (sc.key as string) : null, '', 'all', null);
    if ('refused' in found) return { refused: found.refused };
    label = found.title;
    keys = found.rows.map((r) => r.track_id).filter((k) => {
      const t = s.tracks.find((x) => x.track_id === k);
      const a = t && storedAudio(t);
      return !!a && isLosslessCodec(a.codec);
    });
  }
  const taken = new Set(s.tracks.map((t) => pathOf(t)).filter((p): p is string => !!p).map(fold));
  const items: Judged['item'][] = []; const left: AiffLeft[] = []; const waits: Record<string, number> = {};
  for (const key of keys) {
    const t = s.tracks.find((x) => x.track_id === key);
    const { item, skip } = judge(s, t, taken, only);
    if (item) { items.push(item); continue; }
    if (WAITING.includes(skip!.reason)) waits[skip!.reason] = (waits[skip!.reason] ?? 0) + 1;
    if (sc.kind === 'tracks') left.push({ track: key, name: t ? nameOf(t) : key, reason: skip!.reason, message: skip!.message });
  }
  const done = items as NonNullable<Judged['item']>[];
  const kinds = new Map<string, { kind: string; label: string; n: number }>();
  for (const i of done) {
    const a = storedAudio(s.tracks.find((t) => t.track_id === i.track)!)!;
    const label = KIND_LABELS[i.kind] ?? `${formatName(a, extOfTrack(s.tracks.find((t) => t.track_id === i.track)!, a))} → AIFF`;
    const k = kinds.get(i.kind) ?? { kind: i.kind, label, n: 0 };
    k.n++; kinds.set(i.kind, k);
  }
  const final: Record<string, number> = {}; const peak: Record<string, number> = {};
  for (const i of done.filter((x) => x.bytes)) {
    const target = driveOf(i.new_path);
    final[target] = (final[target] ?? 0) + i.bytes;
    if (target !== FAKE_MUSIC) peak[FAKE_MUSIC] = Math.max(peak[FAKE_MUSIC] ?? 0, i.bytes);   // the render lands in .discjockey/.tmp first
  }
  const space = [...new Set([...Object.keys(final), ...Object.keys(peak)])]
    .sort((a, b) => (a === FAKE_MUSIC ? -1 : b === FAKE_MUSIC ? 1 : a.localeCompare(b)))
    .map((drive) => {
      const needed = Math.max(final[drive] ?? 0, peak[drive] ?? 0);
      const free = s.freeBytes?.[drive] ?? DEFAULT_FREE;
      return { drive, needed, free, enough: free >= needed };
    });
  const state = s.rekordbox_state ?? 'ready';
  const plan: AiffPlan = {
    scope: { ...scope, label },
    items: done.map(({ lossy: _l, oldBytes: _o, held: _h, ...i }) => i),
    skipped: left,
    waiting: WAITING.filter((r) => waits[r]).map((reason) => ({ reason, message: SKIP_WORDS[reason], n: waits[reason] })),
    kinds: [...kinds.values()].sort((a, b) => kindRank(a.kind) - kindRank(b.kind) || a.kind.localeCompare(b.kind)),
    lossy: done.filter((i) => i.lossy).length, total: done.length, space,
    superseded_bytes: done.reduce((n, i) => n + i.oldBytes, 0),
    rekordbox: { state, running: !!s.rekordbox_running, needs_closed: state === 'ready' && done.some((i) => i.held) },
  };
  return { plan };
}

/** The reasons whose answer still says what the step would do (aiff_plan.BLOCKED): rekordbox's library can't be read, a
 *  Cloud Library Sync track, no free name. */
const BLOCKED = ['rekordbox_unreadable', 'cloud', 'rename_blocked'];
const NOTHING_WOULD = { action: null, kind: null, to: null, new_name: null, bytes: 0 };

/** aiff_plan._would_do: the plan again as a what-if with rekordbox taken out (`none`), so a blocked file's action, kind,
 *  new name and room are those of a step that could run; no free name is a Rename with no name to take. */
function wouldDo(s: FakeState, t: FakeTrack, reason: string): Pick<TrackAiff, 'action' | 'kind' | 'to' | 'new_name' | 'bytes'> {
  const rename = { action: 'rename' as const, kind: 'name', to: null, new_name: null, bytes: 0 };
  if (reason === 'rename_blocked') return rename;
  const again = planOf({ ...s, rekordbox_state: 'none' }, { kind: 'tracks', tracks: [t.track_id] });
  if ('refused' in again) return NOTHING_WOULD;
  const [i] = again.plan.items;
  if (i) return { action: i.action, kind: i.kind, to: i.action === 'convert' ? AIFF_LINE : null, new_name: base(i.new_path), bytes: i.bytes };
  return again.plan.skipped[0]?.reason === 'rename_blocked' ? rename : NOTHING_WOULD;
}

/** aiff_plan.file_answer: what Convert and Rename can do for one track's details; null when there is nothing to say (no
 *  file, a download, a better version waiting). `why_not` set means the action is blocked: for `BLOCKED` the action,
 *  `kind`, `to`, `new_name` and `bytes` are still the step's own; any other reason has no action. */
export function fileAnswer(s: FakeState, t: FakeTrack): TrackAiff | null {
  const r = planOf(s, { kind: 'tracks', tracks: [t.track_id] });
  if ('refused' in r) return null;
  const path = pathOf(t);
  const [i] = r.plan.items;
  if (i) {
    return { action: i.action, why_not: null, kind: i.kind, from: i.from, to: i.action === 'convert' ? AIFF_LINE : null,
      name_now: base(i.path), new_name: base(i.new_path), bytes: i.bytes, lossy: !isLosslessCodec(storedAudio(t)!.codec), cdj: i.cdj };
  }
  const reason = r.plan.skipped[0].reason;
  if (NO_ANSWER.includes(reason) || !path) return null;
  const a = storedAudio(t)!;
  const ext = extOfTrack(t, a);
  return { ...(BLOCKED.includes(reason) ? wouldDo(s, t, reason) : NOTHING_WOULD), why_not: reason, from: formatLine(a, ext),
    name_now: base(path), lossy: !isLosslessCodec(a.codec), cdj: cdjWords(cdjProblem(a, ext)) };
}

/** To-do's `aiff` of each CDJ item: the reason Convert can't run now (an eligibility key), null when it can. */
export function cdjAiff(s: FakeState, keys: string[]): Map<string, string | null> {
  const out = new Map<string, string | null>();
  if (!keys.length) return out;
  const r = planOf(s, { kind: 'tracks', tracks: keys });
  if ('refused' in r) return out;
  for (const i of r.plan.items) out.set(i.track, null);
  for (const l of r.plan.skipped) out.set(l.track, l.reason);
  return out;
}

// ---------- what a run does to a fake track ----------

/** The file is an AIFF now (Convert) or has its clean name (Rename): its path, facts and the check it leaves, with the
 *  undo record `runUndo` restores from. Returns the item's words, path and rekordbox part. */
export function applyItem(s: FakeState, t: FakeTrack, item: AiffPlanItem, batch: number) {
  const before = { file: t.file, audio: t.audio, rekordbox_check: t.rekordbox_check ? { ...t.rekordbox_check, undo: undefined } : null };
  const rb = heldInRekordbox(s, t) ? { entries: 1, kept: [] as string[] } : null;
  const since = dateOnly(new Date());
  const old = storedAudio(t)!;
  t.file = item.new_path;
  if (item.action === 'convert') {
    t.audio = { codec: 'pcm_s16be', rate: 44100, bits: 16, kbps: null, ext: 'aiff', tagsClean: true };
    t.rekordbox_check = { reason: 'converted', since, rekordbox: rb, batch, undo: before as never, old_path: item.superseded ?? undefined };
  } else {
    t.audio = { ...old, ext: extOf(item.new_path) };
    t.rekordbox_check = { reason: 'renamed', since, rekordbox: rb, batch, undo: before as never, oldName: base(item.path) };
  }
  const message = item.action === 'convert'
    ? `new file ${item.new_path}, lined up with rekordbox; the old one moved to ${item.superseded}${rb ? '' : `. ${NO_TRACK_NOTE}`}`
    : `now named ${base(item.new_path)}${rb ? '' : `. ${NO_TRACK_NOTE}`}`;
  return { message, path: item.new_path, rekordbox: rb ? { entries: ['1'], kept: [] as string[] } : null };
}

/** views.undone_words: what an undo says when it worked; `reasons` the checks' reasons the undone tracks had. */
export function undoneWords(reasons: (string | null | undefined)[]): string {
  if (reasons.length === 1) {
    return reasons[0] === 'converted' ? 'Conversion undone. Your old file is back.'
      : reasons[0] === 'renamed' ? 'Clean name undone. Your old name is back.' : 'Upgrade undone. Your old file is back.';
  }
  const names = reasons.filter((r) => r === 'renamed').length;
  return names === 0 ? 'Undone. Your old files are back.' : names === reasons.length ? 'Undone. Your old names are back.'
    : 'Undone. Your old files and names are back.';
}
