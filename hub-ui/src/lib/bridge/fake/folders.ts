// Fake mode: watched folders, the import and its To-do questions (plan library stage 4, I11/I12). The words are the
// engine's (folders.py, importer.py, jobs.py, views.py), verbatim; the import advances `ImportProgress` on a timer
// and honours Stop. Paths: a folder named "Missing" is not there, one named "Locked" can't be read.
import type {
  DuplicateItem, Fail, FileSide, ImportFolderCheck, ImportFolderProblem, ImportPhase, ImportResult, JobStart,
  QuestionItem, QuestionWhy, RemovalPreview, Result, TrackRow, WatchedFolderRow, WatchedFolders,
} from '../types';
import { FAKE_MUSIC, type FakeDuplicate, type FakeFolder, type FakeQuestion, type FakeState } from './data';
import type { FakeContext, Finish } from './bridge';
import { toneUrl } from './audio';
import { cratesIn } from './library';

// ---------- the engine's words ----------
export const IMPORTING_BUSY = 'Discjockey is importing your music. Stop the import in Settings → Watched folders to do '
  + 'this now; it carries on later where it stopped.';
export const NO_FOLDER = "That folder isn't one of the watched folders.";
export const NOT_ANSWERABLE = 'Each answer needs the song or group it is about.';
const NOT_A_PLAYLIST_SONG = "That song isn't in your playlists any more, so there is nothing to answer.";
const CHANGED = 'This track changed in the meantime, so nothing was done. The page shows it as it is now.';
const NOT_ABSOLUTE = 'Choose the folder with Choose…, or type its full path (starting with / or ~).';
const PROBLEM_WORDS = (other: string): Record<ImportFolderProblem, string> => ({
  not_absolute: NOT_ABSOLUTE,
  not_a_folder: 'That is a file, not a folder.',
  system_folder: 'That folder belongs to macOS or holds your whole home folder. Choose a folder just for your music, '
    + 'such as Music/Discjockey.',
  inside_app: 'That folder is inside Discjockey itself, which is replaced on every update. Choose a folder outside it.',
  is_support_dir: 'Discjockey keeps its own settings in that folder. Choose another one for your music.',
  not_writable: "Discjockey can't write in that folder. Choose one of your own folders.",
  music: 'This is inside your music folder, which Discjockey watches already.',
  holds_music: 'This folder holds your music folder. Choose a folder inside it instead.',
  watched: `This is inside ${other}, which Discjockey watches already.`,
  already: 'Discjockey watches this folder already.',
  not_found: "That folder isn't there. If it is on a drive, connect the drive first.",
  not_readable: "macOS doesn't let Discjockey read that folder.",
});
const MERGE_HINT = (name: string) => `${name} is inside it and becomes part of it.`;
const NO_ACCESS = "macOS doesn't let Discjockey read it";
const NO_SOUND = "Discjockey can't find sound it can read in it";
const EMPTY = 'The file is empty';
const DONE = (files: number) => (files === 1 ? 'Imported 1 file.' : `Imported ${files} files.`);
const STOPPED = (left: number) => `Import stopped with ${left === 1 ? '1 file' : `${left} files`} to go. `
  + 'It carries on where it stopped.';
const QUESTION_WORDS = (why: QuestionWhy, delta: number | null): string => {
  if (why === 'artist') return 'Same title, different artist';
  if (why === 'no_artist') return 'Same title, no artist in your file';
  if (why === 'no_length' || delta === null) return "Same artist and title, the length couldn't be read";
  return `Same artist and title, ${Math.abs(delta)} s ${delta > 0 ? 'longer' : 'shorter'}`;
};
const DUPLICATE_WORDS = (why: 'same_audio' | 'same_song', n: number) =>
  (why === 'same_audio' ? `The same audio in ${n} files` : `${n} files of the same song`);

const name = (path: string) => path.split('/').filter(Boolean).at(-1) ?? path;
const importFolders = (s: FakeState) => s.imp.folders.filter((f) => f.kind === 'import');
const fail = (kind: Fail['kind'], message: string): Fail => ({ ok: false, kind, message });

// ---------- the check (W5) ----------
export function checkImportFolder(s: FakeState, path: string): ImportFolderCheck {
  const base = (p: string, over: Partial<ImportFolderCheck>): ImportFolderCheck => ({
    path: p, exists: true, usable: false, problem: null, kind: null, message: null, merges: [], merge_hints: [], ...over });
  const refuse = (p: string, problem: ImportFolderProblem, other = '', exists = true) =>
    base(p, { exists, problem, message: PROBLEM_WORDS(other)[problem] });
  if (typeof path !== 'string' || !(path.startsWith('/') || path.startsWith('~'))) return refuse(String(path), 'not_absolute', '', false);
  const full = (path === '~' || path.startsWith('~/') ? '/Users/you' + path.slice(1) : path).replace(/\/+$/, '') || '/';
  if (name(full) === 'Missing') return refuse(full, 'not_found', '', false);
  if (name(full) === 'Locked') return refuse(full, 'not_readable');
  if (full === FAKE_MUSIC || full.startsWith(FAKE_MUSIC + '/')) return refuse(full, 'music');
  if (FAKE_MUSIC.startsWith(full + '/')) return refuse(full, 'holds_music');
  const watched = importFolders(s);
  const same = watched.find((f) => f.path === full);
  if (same) return refuse(full, 'already');
  const outer = watched.find((f) => full.startsWith(f.path + '/'));
  if (outer) return refuse(full, 'watched', name(outer.path));
  const inner = watched.filter((f) => f.path.startsWith(full + '/'));
  return base(full, { usable: true, kind: 'import', merges: inner.map((f) => f.path),
    merge_hints: inner.map((f) => MERGE_HINT(name(f.path))) });
}

// ---------- the list (W2, W3) ----------
export function watchedFolders(s: FakeState): WatchedFolders {
  const phase = s.imp.phase;
  const crates = cratesIn(s);
  const rows: WatchedFolderRow[] = s.imp.folders.map((f) => ({
    id: f.id, path: f.path, name: f.kind === 'library' ? 'Library' : name(f.path), kind: f.kind,
    state: f.kind === 'library' ? (phase === 'scan' ? 'scanning' : 'online')
      : f.offline ? 'offline' : f.missing ? 'missing' : phase === 'scan' ? 'scanning' : phase !== null && f.waiting > 0 ? 'importing' : 'online',
    files: f.files, waiting: f.waiting,
    unreadable: s.imp.unreadable.filter((u) => u.folder_id === f.id).length,
    crates: crates[f.path]?.crates ?? [], too_many: crates[f.path]?.too_many ?? false,
  }));
  return { folders: rows, unreadable: s.imp.unreadable.map((u) => ({ ...u })),
    waiting: importFolders(s).filter((f) => !f.offline && !f.missing).reduce((n, f) => n + f.waiting, 0), stopped: s.imp.stopped };
}
export function folderOf(s: FakeState, id: unknown): FakeFolder | undefined {
  return typeof id === 'number' && Number.isInteger(id) ? importFolders(s).find((f) => f.id === id) : undefined;
}
export function removalPreview(s: FakeState, id: unknown): RemovalPreview | Fail {
  const f = folderOf(s, id);
  return f ? { name: name(f.path), files: f.files, redownload: f.redownload } : fail('refused', NO_FOLDER);
}
export function removeFolder(s: FakeState, f: FakeFolder): { files: number; redownload: number } {
  s.imp.folders = s.imp.folders.filter((x) => x !== f);
  s.imp.unreadable = s.imp.unreadable.filter((u) => u.folder_id !== f.id);
  return { files: f.files, redownload: f.redownload };
}

// ---------- the To-do groups (W8) ----------
const row = (id: string, artist: string, title: string, folder: string, duration_s: number, side: FileSide | null,
  inPlaylists: boolean, own = false): TrackRow => ({
  track_id: id, artist, title, folder, duration_s, status: side?.quality === 'lossless' ? 'lossless' : side ? 'not_lossless' : 'missing',
  quality: side?.quality ?? 'missing', quality_label: side?.quality_label ?? 'NOT FOUND', cutoff_hz: null, source: null,
  source_name: null, in_playlists: inPlaylists, own, hidden: false, upgrade_ready: false, path: side?.path ?? null, added: null,
  cover_url: null });
const byName = (a: TrackRow, b: TrackRow) => `${a.folder}\u0000${a.artist}\u0000${a.title}`
  .localeCompare(`${b.folder}\u0000${b.artist}\u0000${b.title}`);
export function questionItems(s: FakeState): QuestionItem[] {
  return s.imp.questions.map((q): QuestionItem => ({
    ...row(q.song_key, q.track.artist, q.track.title, q.track.folder, q.track.duration_s, null, true),
    group: 'same_song', detail: QUESTION_WORDS(q.why, q.delta_s), free: false,
    pair: { song_key: q.song_key, own_key: q.own_key, why: q.why, delta_s: q.delta_s, track: { ...q.track },
      file: { ...q.file } } })).sort(byName);
}
export function duplicateItems(s: FakeState): DuplicateItem[] {
  return s.imp.duplicates.map((g): DuplicateItem => {
    const first = g.files.find((f) => f.in_playlist) ?? g.files[0];
    return { ...row(g.group_id, first.artist, first.title, '', first.duration_s, first, first.in_playlist, !first.in_playlist),
      group: 'duplicate', detail: DUPLICATE_WORDS(g.why, g.files.length), free: false,
      pair: { group_id: g.group_id, why: g.why, files: g.files.map((f) => ({ ...f })) } };
  }).sort(byName);
}

// ---------- the answers ----------
const asJob = (ctx: FakeContext, kind: string, ms: number, work: (finish: Finish) => void): JobStart =>
  ctx.startJob(kind, null, (finish) => setTimeout(() => work(finish), ms / ctx.speed));

export function answerSameSong(ctx: FakeContext, song_key: unknown, own_key: unknown, same: unknown): JobStart | Fail {
  if (typeof song_key !== 'string' || typeof own_key !== 'string' || typeof same !== 'boolean') {
    return ctx.fail('refused', NOT_ANSWERABLE);
  }
  return asJob(ctx, 'answer', 350, (finish) => {
    const q = ctx.s.imp.questions.find((x) => x.song_key === song_key && x.own_key === own_key);
    if (!q) return finish(false, null, 'changed', NOT_A_PLAYLIST_SONG);
    ctx.s.imp.questions = ctx.s.imp.questions.filter((x) => x !== q);
    finish(true, {});
  });
}
const isGroup = (id: unknown): id is string => typeof id === 'string' && /^dup:\d+(-\d+)*$/.test(id);
const isPaths = (v: unknown): v is string[] => Array.isArray(v) && v.every((p) => typeof p === 'string');
/** The paths the card showed against the group's files now (any order): the engine's `changed` check. */
const sameFiles = (g: { files: { path: string }[] }, shown: string[]) =>
  g.files.length === shown.length && [...g.files.map((f) => f.path)].sort().join('\n') === [...shown].sort().join('\n');
export function keepDuplicates(ctx: FakeContext, group_id: unknown, paths: unknown): JobStart | Fail {
  if (!isGroup(group_id) || !isPaths(paths)) return ctx.fail('refused', NOT_ANSWERABLE);
  return asJob(ctx, 'answer', 350, (finish) => {
    const g = ctx.s.imp.duplicates.find((x) => x.group_id === group_id);
    if (g && !sameFiles(g, paths)) return finish(false, null, 'changed', CHANGED);
    ctx.s.imp.duplicates = ctx.s.imp.duplicates.filter((x) => x.group_id !== group_id);
    finish(true, {});
  });
}
export function supersedeDuplicate(ctx: FakeContext, group_id: unknown, file_id: unknown, paths: unknown): JobStart | Fail {
  if (!isGroup(group_id) || typeof file_id !== 'number' || !Number.isInteger(file_id) || !isPaths(paths)) {
    return ctx.fail('refused', NOT_ANSWERABLE);
  }
  return asJob(ctx, 'supersede', 450, (finish) => {
    const g = ctx.s.imp.duplicates.find((x) => x.group_id === group_id);
    const file = g?.files.find((f) => f.file_id === file_id);
    if (!g || !file || !sameFiles(g, paths)) return finish(false, null, 'changed', CHANGED);
    const home = importFolders(ctx.s).find((f) => file.path.startsWith(f.path + '/'));
    const dst = `Superseded/${home ? name(home.path) + '/' : ''}${name(file.path)}`;
    g.files = g.files.filter((f) => f !== file);
    if (g.files.length < 2) ctx.s.imp.duplicates = ctx.s.imp.duplicates.filter((x) => x !== g);
    const result: Result = { section: 'replaced', folder: '', artist: file.artist, title: file.title,
      track_id: file.song_key, note: `Moved to ${dst}.`, status: file.quality === 'lossless' ? 'lossless' : 'not_lossless',
      source: null, cutoff_hz: null, path: dst, error_kind: null };
    finish(true, { result, recovered: [] });
  });
}

// ---------- the import ----------
/** A running import: Stop sets `stopped`; `hold` keeps it at its resume point until then (screenshots). */
export type ImportRun = { stopped: boolean; hold: boolean };

/** Runs an import as the body of a write job: scan, tags, sound, link, with `ImportProgress` on a timer. `adding`
 *  is a folder just watched (its files turn up in the scan). `resume` starts mid-way (scenario folders_importing). */
export async function runImport(ctx: FakeContext, run: ImportRun, finish: Finish,
  opts: { adding?: FakeFolder; resume?: { phase: 'tags' | 'sound'; done: number } } = {}): Promise<void> {
  const { s, emit } = ctx;
  const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms / ctx.speed));
  const progress = (phase: ImportPhase, done: number, total: number) => {
    s.imp.phase = phase;
    emit({ type: 'ImportProgress', phase, done, total, unreadable: s.imp.unreadable.length });
  };
  const resumed = opts.resume;
  if (!resumed) {
    progress('scan', 0, 0);
    await sleep(700);
    if (opts.adding) { opts.adding.files += 180; opts.adding.waiting += 180; }
  }
  const targets = importFolders(s).filter((f) => !f.offline && !f.missing && f.waiting > 0);
  const initial = new Map(targets.map((f) => [f, f.waiting] as const));
  const total = targets.reduce((n, f) => n + f.waiting, 0);
  let read = 0;
  let judged = 0;
  const result = (stopped: boolean): ImportResult => ({ files: read, own_songs: read, sound_checked: judged,
    unreadable: s.imp.unreadable.length, left: total - judged, stopped, link_note: null });
  const end = (stopped: boolean) => {
    s.imp.phase = null;
    if (stopped) {
      s.imp.stopped = true;
      return finish(false, result(true), 'stopped', STOPPED(total - judged));
    }
    finish(true, result(false), null, DONE(read));
  };
  const step = Math.max(1, Math.ceil(total / 24));
  if (run.stopped) return end(true);
  for (const phase of ['tags', 'sound'] as const) {
    if (resumed?.phase === 'sound' && phase === 'tags') { read = total; continue; }
    let done = resumed?.phase === phase ? resumed.done : 0;
    if (phase === 'sound') read = total;
    else read = done;
    progress(phase, done, total);
    while (done < total) {
      if (run.hold && resumed?.phase === phase && done === resumed.done) {
        while (!run.stopped) await sleep(100);
      }
      if (run.stopped) return end(true);
      await sleep(phase === 'tags' ? 140 : 220);
      done = Math.min(total, done + step);
      if (phase === 'tags') read = done;
      else {
        judged = done;
        let spent = done;  // the folders finish in order
        for (const f of targets) { const part = Math.min(initial.get(f)!, spent); spent -= part; f.waiting = initial.get(f)! - part; }
      }
      progress(phase, done, total);
      if (run.stopped && done < total) return end(true);
    }
  }
  progress('link', 0, 0);
  await sleep(600);
  for (const f of targets) f.waiting = 0;
  end(false);
}

// ---------- the seed: watched folders and questions per scenario ----------
const DRIVE = '/Volumes/Example Drive';
const side = (file_id: number, song_key: string | null, path: string, artist: string, title: string, duration_s: number,
  quality: FileSide['quality'], label: string, inPlaylist = false): FileSide => ({ file_id, song_key, path, artist, title,
  duration_s, quality, quality_label: label, online: true, in_playlist: inPlaylist,
  // every online file plays, an import folder's too (the media server's `file/<id>` address, contract FileSide)
  audio_url: toneUrl(Math.min(duration_s || 90, 90), 196 + (file_id % 6) * 22) });
const own = (id: number, artist: string, title: string, duration_s: number, quality: FileSide['quality'] = 'lossless',
  label = 'LOSSLESS', dir = 'Music'): FileSide => side(id, `local:${id}`,
  `${DRIVE}/${dir}/${artist ? artist + ' - ' : ''}${title}.aiff`, artist, title, duration_s, quality, label);
const group = (why: FakeDuplicate['why'], files: FileSide[]): FakeDuplicate => ({
  group_id: 'dup:' + files.map((f) => f.file_id).sort((a, b) => a - b).join('-'), why, files });
const ask = (song_key: string, artist: string, title: string, folder: string, duration_s: number, why: QuestionWhy,
  delta_s: number | null, file: FileSide): FakeQuestion => ({ song_key, own_key: file.song_key!, why, delta_s,
  track: { artist, title, duration_s, folder, link: `https://open.spotify.com/track/${song_key}` }, file });

export const sampleQuestions = (): FakeQuestion[] => [
  ask('q1', 'Neon Riot', 'Hands Up Again', 'Hard_Bounce', 194, 'artist', null, own(101, 'Neonriot', 'Hands Up Again', 194)),
  ask('q2', 'Hardline Theory', 'Hyperdrive', 'Powertrance', 215, 'no_artist', null, own(102, '', 'Hyperdrive', 215)),
  ask('q3', 'DJ Fluxkompensator', 'Kick it Hard', 'Hard_Bounce', 188, 'length', 4,
    own(103, 'DJ Fluxkompensator', 'Kick it Hard', 192, 'weak', '16.0 kHz')),
  ask('q4', 'Rave Kollektiv', 'Strobe Light', 'Bouncy', 241, 'length', -8, own(104, 'Rave Kollektiv', 'Strobe Light', 233)),
  ask('q5', 'Kalte Nacht', 'Bis zum Morgen', 'Powertrance', 207, 'no_length', null,
    own(105, 'Kalte Nacht', 'Bis zum Morgen', 0, 'good_lossy', '20.0 kHz')),
];
const sameAudio = (n: number) => group('same_audio', [
  own(201, 'Neon Riot', 'Neonfieber', 229), own(202, 'Neon Riot', 'Neonfieber', 229, 'lossless', 'LOSSLESS', 'Music/Old'),
  ...(n > 2 ? [own(203, 'Neon Riot', 'Neonfieber', 229, 'lossless', 'LOSSLESS', 'Crates')] : [])]);
const sameSong = () => group('same_song', [
  side(210, 't7', 'Library/Hard_Bounce/Rave Kollektiv - Bis zum Morgen.aiff', 'Rave Kollektiv', 'Bis zum Morgen', 207,
    'lossless', 'LOSSLESS', true),
  own(211, 'Rave Kollektiv', 'Bis zum Morgen', 207, 'weak', '16.0 kHz')]);

/** Called once by createFakeBridge: the Library, and the scenario's import folders, questions and duplicates. */
export function seedImport(s: FakeState, scenario: string): void {
  const library: FakeFolder = { id: 1, path: `${FAKE_MUSIC}/Library`, kind: 'library', offline: false,
    files: s.tracks.filter((t) => t.status !== 'missing').length, waiting: 0, redownload: 0 };
  s.imp.folders = [library];
  const add = (over: Partial<FakeFolder> = {}): FakeFolder => {
    const f: FakeFolder = { id: s.imp.nextId++, path: `${DRIVE}/Music`, kind: 'import', offline: false, files: 1240,
      waiting: 0, redownload: 4, ...over };
    s.imp.folders.push(f);
    return f;
  };
  if (['first_run', 'no_music', 'music_missing', 'folders_library_only', 'setup_existing_empty'].includes(scenario)) return;
  if (scenario === 'setup_existing_added') { add({ files: 312, redownload: 0 }); return; }
  const music = add();
  if (scenario === 'folders_importing') {
    music.files = 1840; music.waiting = 1500;
    add({ path: `${DRIVE}/Crates`, files: 220, redownload: 0 });
  }
  if (scenario === 'folders_offline') add({ path: '/Volumes/Old Drive/Music', files: 612, offline: true, redownload: 0 });
  if (scenario === 'folders_missing') add({ path: '/Users/you/Music/Crates', files: 612, missing: true, redownload: 0 });
  if (scenario === 'folders_couldnt_read') {
    s.imp.unreadable = [
      { folder_id: music.id, path: `${music.path}/Crates/Neon Riot - Strobe Light.aiff`, reason: NO_ACCESS },
      { folder_id: music.id, path: `${music.path}/Old/Rave Kollektiv - Hyperdrive.wav`, reason: NO_SOUND },
      { folder_id: music.id, path: `${music.path}/Old/Untitled 3.mp3`, reason: NO_SOUND }];
  }
  if (scenario === 'folders_long_names') {
    // names that differ only at their end, and folders on other drives with names of every length
    const crates = add({ path: '/Volumes/New Volume/Crates Mix', files: 96, redownload: 0 });
    add({ path: '/Volumes/Backup Drive/DJ Sets/2019/Peak Hour Rarities and Other Long Folder Names', files: 3010, redownload: 0 });
    const long = 'Example Artist - A Very Long Title (GUEST ONE x GUEST TWO EDIT)';
    s.imp.unreadable = [
      { folder_id: music.id, path: `${music.path}/Crates/${long}.wav`, reason: EMPTY },
      { folder_id: music.id, path: `${music.path}/Crates/${long}(1).wav`, reason: EMPTY },
      { folder_id: crates.id, path: `${crates.path}/Untitled 3.mp3`, reason: NO_SOUND }];
  }
  if (scenario === 'todo_same_song') s.imp.questions = sampleQuestions();
  if (scenario === 'sync_waiting_answers') { s.imp.questions = sampleQuestions().slice(0, 2); s.imp.deferred = 40; }
  if (scenario === 'todo_duplicates') s.imp.duplicates = [sameAudio(2), sameSong()];
  if (scenario === 'todo_duplicates_three') s.imp.duplicates = [sameAudio(3), sameSong()];
}
