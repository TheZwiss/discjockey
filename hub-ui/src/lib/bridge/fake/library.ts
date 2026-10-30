// Fake mode: what the library's screens are made of, worked out as the engine does it (discjockey/hub/views.py:
// `crates`, `place`, `sidebar`, `library`, plan library stage 5, I4 and D8–D12). The fake keeps the same few things the
// engine keeps: files with a path, the playlists' read records (here derived from each song's `playlists`), the
// Favourites and the user's crate switches. Words and rules are the engine's; a rule that changes there changes here.
import type {
  Crate, Favourite, FolderState, Library, LibraryFilter, LibraryRow, LibrarySort, LibraryView, PlaylistService,
  Sidebar, WatchedEntry,
} from '../types';
import { NOT_IN_PLAYLIST, QUALITIES } from '../types';
import {
  SERVICE_NAME, byQuality, pathOf, playlistRef, serviceOfLink, todoGroup, trackRow, type FakeState,
  type FakeTrack,
} from './data';

export const BAD_FAVOURITES = "That list of favourites isn't one Discjockey can keep.";
export const BAD_CRATE = "That isn't a folder Discjockey can show or hide.";
export const BRIEF_WRITE_FAILED = "Discjockey couldn't save that just now. Try again in a moment.";
export const LIBRARY_VIEWS: readonly LibraryView[] = ['all', 'unlisted', 'playlist', 'folder'];
export const LIBRARY_FILTERS: readonly LibraryFilter[] = ['all', 'lossless', 'good_lossy', 'weak', 'fake', 'upgrade_ready'];
/** more crates than this under one watched folder: the folder is one row and its crates start hidden (D8) */
export const CRATE_LIMIT = 25;
const AWAY_WORDS: Record<Exclude<FolderState, 'here'>, string> = {
  offline: 'Offline: connect the drive', folder_missing: 'Folder not found' };

// ---------- paths and names ----------
const nfc = (x: string): string => x.normalize('NFC');
/** names compare as the disk does: NFC, case ignored (names.fold) */
export const fold = (x: string): string => nfc(x).toLowerCase();
const parent = (p: string): string => p.slice(0, p.lastIndexOf('/')) || '/';
const base = (p: string): string => p.slice(p.lastIndexOf('/') + 1);
const within = (p: string, root: string): boolean => p === root || p.startsWith(`${root}/`);
const depth = (p: string): number => p.split('/').filter(Boolean).length;
const plural = (n: number, one: string, many: string): string => (n === 1 ? one : many.replace('{n}', String(n)));

/** A folder's path as the watched-folder list words it (views.place): the home folder as "~", a folder on another
 *  drive as "Example Drive › Music/Old" (the drive's name first, a no-break blank before the "›"). */
export function placeWords(path: string): string {
  const home = /^\/Users\/[^/]+(\/.*)?$/.exec(path);
  if (home) return home[1] && home[1] !== '/' ? `~${home[1]}` : '~';
  const segs = path.replace(/\/+$/, '').split('/');
  if (segs.length > 2 && segs[0] === '' && segs[1] === 'Volumes' && segs[2]) {
    const rest = segs.slice(3).filter(Boolean).join('/');
    return rest ? `${segs[2]} › ${rest}` : segs[2];
  }
  return path;
}

// ---------- files, read records, who holds a song ----------
/** the tracks that have a file (what "All tracks" counts) */
export const filesOf = (s: FakeState): FakeTrack[] => s.tracks.filter((t) => t.status !== 'missing' && !!pathOf(t));
const importRoots = (s: FakeState): string[] => s.imp.folders.filter((f) => f.kind === 'import').map((f) => f.path);

/** One song of a playlist's read; `t` is the fake's song (None for a song only just read, which the sync has yet to
 *  look at: it waits). */
export type Held = { key: string; t: FakeTrack | null; artist: string; title: string; duration_s: number };
export type Read = { read_at: string; held: Held[] };
/** A playlist's read record (db.playlist_records), derived from the songs that name the playlist: null while it was
 *  never read (`s.unread`, or no song at all), and a read that found nothing (`s.emptyRead`) is a record of no song. */
export function readOf(s: FakeState, folder: string): Read | null {
  if (s.unread.includes(folder)) return null;
  const held: Held[] = s.tracks.filter((t) => t.playlists.includes(folder))
    .map((t) => ({ key: t.track_id, t, artist: t.artist, title: t.title, duration_s: t.duration_s }));
  for (const n of s.newTracks) {
    if (n.folder === folder) held.push({ key: n.track_id, t: null, artist: n.artist, title: n.title, duration_s: n.duration_s });
  }
  if (!held.length && !s.emptyRead.includes(folder)) return null;
  return { read_at: s.read_status.read_at ?? s.now.toISOString().slice(0, 19), held };
}
/** song key -> the names of the playlists whose read holds it, in playlists.txt order */
function holders(s: FakeState): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const p of s.playlists) {
    for (const h of readOf(s, p.folder)?.held ?? []) {
      const names = out.get(h.key) ?? [];
      if (!names.includes(p.folder)) names.push(p.folder);
      out.set(h.key, names);
    }
  }
  return out;
}

// ---------- crates (views.crates) ----------
export type CrateGroup = { too_many: boolean; crate_count: number; crates: Crate[] };
/** a sort key that reads numbers as numbers and ignores case ("Set 2" before "Set 10") */
const natural = (text: string): (string | number)[] => fold(text).split(/([0-9]+)/).map((p, i) => (i % 2 ? Number(p) : p));
function compareNatural(a: (string | number)[], b: (string | number)[]): number {
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
  }
  return a.length - b.length;
}

/** The crates under each watched import folder (D8). `files`: the snapshot paths of the files that are there;
 *  `watched`: the import folders' paths; `overrides`: crate path -> shown. A crate is any folder below a watched
 *  folder that holds a file itself; wrapper folders get no row, files directly in the watched folder belong to no
 *  crate, a file under two watched folders belongs to the deeper one. Crates come in label order; `hidden` is the
 *  user's switch or, without one, the default (shown; hidden under a folder with more than CRATE_LIMIT crates). A
 *  label never depends on what is hidden. */
export function cratesOf(files: string[], watched: string[], overrides: Record<string, boolean>): Record<string, CrateGroup> {
  const holding = new Map<string, Set<string>>(watched.map((w) => [w, new Set<string>()]));
  const below = new Map<string, number>();
  for (const f of files) {
    const folder = parent(f);
    const inside = watched.filter((w) => folder !== w && within(folder, w));
    if (!inside.length) continue;
    const w = inside.reduce((a, b) => (depth(b) > depth(a) ? b : a));
    holding.get(w)!.add(folder);
    for (let d = folder; d !== w; d = parent(d)) below.set(d, (below.get(d) ?? 0) + 1);
  }
  const nearest = (d: string, dirs: Set<string>): string | null => {
    for (let a = parent(d); a !== d; d = a, a = parent(a)) if (dirs.has(a)) return a;
    return null;
  };
  const outer = new Map([...holding].map(([w, dirs]) => [w, new Map([...dirs].map((d) => [d, nearest(d, dirs)] as const))] as const));
  const sameName = new Map<string, number>();
  for (const found of outer.values()) {
    for (const [d, anc] of found) if (anc === null) sameName.set(fold(base(d)), (sameName.get(fold(base(d))) ?? 0) + 1);
  }
  const out: Record<string, CrateGroup> = {};
  for (const [w, found] of outer) {
    const tooMany = found.size > CRATE_LIMIT;
    const parents = new Set([...found.values()].filter((a): a is string => a !== null));
    const rows = [...found].map(([d, anc]): Crate => ({
      path: d,
      label: anc !== null ? `${base(anc)} › ${base(d)}` : (sameName.get(fold(base(d))) ?? 0) > 1 ? `${base(d)} · ${base(parent(d))}` : base(d),
      name: base(d),
      tip: [base(w) || w, ...d.slice(w.length + 1).split('/')].join(' › '),
      files: below.get(d) ?? 0,
      hidden: !(overrides[d] ?? !tooMany),
      has_crates: parents.has(d),
    }));
    rows.sort((a, b) => compareNatural(natural(a.label), natural(b.label)) || (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
    out[w] = { too_many: tooMany, crate_count: rows.length, crates: rows };
  }
  return out;
}
/** `cratesOf` for the fake's files, watched folders and crate switches */
export const cratesIn = (s: FakeState): Record<string, CrateGroup> =>
  cratesOf(filesOf(s).map((t) => pathOf(t)!), importRoots(s), s.crateShown);

// ---------- where a file sits (views.Sites) ----------
type Sites = { names: Map<string, string>; roots: Map<string, string>; crates: Map<string, [string, string]>;
  crateCounts: Map<string, number> };
function sitesOf(s: FakeState): Sites {
  const imports = importRoots(s);
  const found = cratesOf(filesOf(s).map((t) => pathOf(t)!), imports, {});
  const roots = new Map(imports.map((w) => [nfc(w), base(w) || w] as const));
  const crates = new Map<string, [string, string]>();
  const crateCounts = new Map<string, number>();
  for (const [w, f] of Object.entries(found)) {
    crateCounts.set(nfc(w), f.crate_count);
    for (const c of f.crates) crates.set(nfc(c.path), [roots.get(nfc(w))!, c.label]);
  }
  return { names: new Map(s.playlists.map((p) => [fold(p.folder), p.folder] as const)), roots, crates, crateCounts };
}
/** the Library folder a file sits in (as the disk spells it, `not_lossless/` included), null for a file elsewhere */
function libraryFolder(path: string): string | null {
  const p = nfc(path).split('/');
  return p.length > 2 && p[0] === 'Library' ? p[1] : null;
}
/** The physical folder of the file at `path` (Sites.place): a playlist's or Library folder's name, for an import file
 *  its watched folder and crate ("Rekordbox Library › Hardtechno › 2019"; a file in the watched folder itself says
 *  just its name). */
function placeOf(sites: Sites, path: string): string {
  const own = libraryFolder(path);
  if (own !== null) return sites.names.get(fold(own)) ?? own;
  const folder = parent(nfc(path));
  const crate = sites.crates.get(folder);
  if (crate) return `${crate[0]} › ${crate[1]}`;
  return sites.roots.get(folder) || base(folder) || folder;
}
/** `track()`'s `place`: where the song's file sits; null without a file */
export function trackPlace(s: FakeState, t: FakeTrack): string | null {
  const path = t.status === 'missing' ? null : pathOf(t);
  return path ? placeOf(sitesOf(s), path) : null;
}

/** the state of the folder at `path`: the innermost away import folder holding it decides */
function folderState(s: FakeState, path: string): FolderState {
  const away = s.imp.folders.filter((f) => f.kind === 'import' && (f.offline || f.missing) && within(path, nfc(f.path).replace(/\/+$/, '')));
  if (!away.length) return 'here';
  const f = away.reduce((a, b) => (depth(b.path) > depth(a.path) ? b : a));
  return f.offline ? 'offline' : 'folder_missing';
}

/** a row's `file_state`, from its watched folder as the engine reads it (never from the file itself: a file that went
 *  since the last scan still reads `here` in the list); a Library file is always `here` */
function pathState(s: FakeState, t: FakeTrack): LibraryRow['file_state'] {
  return folderState(s, nfc(pathOf(t)!));
}

// ---------- the sidebar (views.sidebar) ----------
export function sidebarOf(s: FakeState, todo: number, limits_warning: boolean): Sidebar {
  const files = filesOf(s);
  const used = new Set(s.playlists.map((p) => fold(p.folder)));
  const lib = new Map<string, { path: string; name: string; files: number }>();
  for (const t of files) {
    if (!t.folder || used.has(fold(t.folder))) continue;
    const parts = pathOf(t)!.split('/');
    const seen = lib.get(fold(t.folder));
    if (seen) seen.files++;
    else lib.set(fold(t.folder), { path: parts[0] === 'Library' ? parts.slice(0, 2).join('/') : `Library/${t.folder}`, name: t.folder, files: 1 });
  }
  const library_folders = [...lib].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([, v]) => v);
  const playlists = s.playlists.map((p) => {
    const read = readOf(s, p.folder);
    return { name: p.folder, ref: playlistRef(p.link) ?? '', service: serviceOfLink(p.link) as PlaylistService | null,
      enabled: p.enabled, songs: read ? new Set(read.held.map((h) => h.key)).size : null };
  });
  const found = cratesIn(s);
  const paths = files.map((t) => nfc(pathOf(t)!));
  const watched: WatchedEntry[] = s.imp.folders.filter((f) => f.kind === 'import')
    .sort((a, b) => (fold(base(a.path) || a.path) < fold(base(b.path) || b.path) ? -1
      : fold(base(a.path) || a.path) > fold(base(b.path) || b.path) ? 1 : a.path < b.path ? -1 : 1))
    .map((f) => ({ path: f.path, name: base(f.path) || f.path, place: placeWords(f.path),
      files: paths.filter((p) => p !== nfc(f.path) && within(p, nfc(f.path))).length,
      state: f.offline ? 'offline' : f.missing ? 'folder_missing' : 'here', ...found[f.path] }));
  const targets = new Map<string, Omit<Favourite, 'key'>>();
  for (const p of playlists) {
    targets.set(`playlist:${p.ref}`, { kind: 'playlist', name: p.name, service: p.service, enabled: p.enabled,
      count: p.songs, path: null, state: 'here' });
  }
  const folder = (path: string, name: string, count: number, state: FolderState): void => {
    targets.set(`folder:${path}`, { kind: 'folder', name, service: null, enabled: true, count, path, state });
  };
  for (const lf of library_folders) folder(lf.path, lf.name, lf.files, 'here');
  for (const w of watched) {
    folder(w.path, w.name, w.files, w.state);
    for (const c of w.crates) folder(c.path, c.label, c.files, w.state);
  }
  return { todo, all_tracks: files.length, not_in_playlist: files.filter((t) => !t.in_playlists).length, limits_warning,
    favourites: [...new Set(s.favourites)].filter((k) => targets.has(k)).map((key) => ({ key, ...targets.get(key)! })),
    playlists, watched, library_folders };
}

// ---------- library() (views.library) ----------
type Key = string | number | boolean | Key[];
function compare(a: Key, b: Key): number {
  if (Array.isArray(a) && Array.isArray(b)) {
    for (let i = 0; i < Math.min(a.length, b.length); i++) {
      const c = compare(a[i], b[i]);
      if (c) return c;
    }
    return a.length - b.length;
  }
  return a < b ? -1 : a > b ? 1 : 0;
}
const SORTS: Record<string, (r: LibraryRow) => Key> = {
  title: (r) => fold(r.title),
  artist: (r) => [fold(r.artist), fold(r.title)],
  length: (r) => r.duration_s,
  source: (r) => r.source_name ?? '',
  quality: (r) => (r.sound_checked ? QUALITIES.indexOf(r.quality) : QUALITIES.length),
  added: (r) => r.added ?? '',
  order: (r) => [r.position === null, r.position ?? 0],
  folder: (r) => [!r.in_playlists, fold(r.folder), fold(r.artist), fold(r.title)],
};
type Entry = { row: LibraryRow; t: FakeTrack | null };
/** a quality filter (and its chip) never holds a file whose sound isn't checked yet, nor a song without a file */
const matches = (e: Entry, filter: string): boolean => filter === 'all'
  || (e.t !== null && (filter === 'upgrade_ready' ? !!e.t.upgrade : !e.t.unchecked && e.row.quality === filter));

export type LibraryFail = { refused: string };
/** One view of the library, as `HubApi.library` answers it. A request the engine would refuse (a view it doesn't
 *  know, a playlist or folder view without its key, a filter it doesn't know) comes back as `{refused}`. */
export function libraryOf(s: FakeState, view: string, key: string | null, query: string, filter: string,
  sort: LibrarySort | null): Library | LibraryFail {
  if (!(LIBRARY_VIEWS as readonly string[]).includes(view)) return { refused: `view must be one of ${LIBRARY_VIEWS.join(', ')}` };
  if ((view === 'playlist' || view === 'folder') && !key) return { refused: `a ${view} view needs its key` };
  if (!(LIBRARY_FILTERS as readonly string[]).includes(filter)) return { refused: `filter must be one of ${LIBRARY_FILTERS.join(', ')}` };
  const files = filesOf(s);
  const sites = sitesOf(s);
  const held = holders(s);
  const mk = (t: FakeTrack, over: Partial<LibraryRow> = {}): Entry => ({ t, row: {
    ...trackRow(t), sound_checked: !t.unchecked, file_state: pathState(s, t), wait: null, position: null,
    place: placeOf(sites, pathOf(t)!), subfolder: null, playlists: held.get(t.track_id) ?? [], ...over } });

  let entries: Entry[] = [];
  let also: Entry[] | null = null;
  let folderKind: Library['folder_kind'] = null;
  let readAt: string | null = null;
  let enabled: boolean | null = null;
  let service: PlaylistService | null = null;
  let gone = false;
  let title = 'All tracks';
  let shownKey: string | null = null;
  let folder: string | null = null;
  let subtitle = (n: string): string[] => [n, 'every folder'];
  if (view === 'unlisted') {
    title = 'Not in a playlist'; folder = NOT_IN_PLAYLIST;
    entries = files.filter((t) => !t.in_playlists).map((t) => mk(t));
    subtitle = (n) => [n, 'in no playlist'];
  } else if (view === 'all') {
    entries = files.map((t) => mk(t));
  } else if (view === 'playlist') {
    const line = s.playlists.find((p) => fold(p.folder) === fold(key ?? ''));
    title = shownKey = folder = line ? line.folder : key ?? '';
    gone = !line;
    if (line) {
      const read = readOf(s, line.folder);
      readAt = read?.read_at ?? null; enabled = line.enabled; service = serviceOfLink(line.link);
      const label = `${SERVICE_NAME[service]} playlist`;
      subtitle = !read ? (() => [label, 'not read yet']) : (n) => [n, label, ...(line.enabled ? [] : ['switched off']), `Library › ${line.folder}`];
      const heldKeys = new Set<string>();
      let position = 0;
      for (const h of read?.held ?? []) {
        position++;
        heldKeys.add(h.key);
        if (h.t && files.includes(h.t)) {
          const own = fold(libraryFolder(pathOf(h.t)!) ?? '') === fold(line.folder);
          entries.push(mk(h.t, { position, place: own ? null : placeOf(sites, pathOf(h.t)!) }));
          continue;
        }
        // a song without a file: waiting (or, when the sync found nothing usable, Not found)
        const name: FakeTrack = h.t ?? { track_id: h.key, artist: h.artist, title: h.title, folder: '', duration_s: h.duration_s,
          status: 'missing', cutoff_hz: null, source: null, codec: null, in_playlists: true, hidden: false, added: null, cover: null,
          isrc: null, playlists: [line.folder], upgrade: null, rekordbox_check: null, other: null, next_try_days: null,
          rejected_sources: [] };
        const missing: FakeTrack = { ...name, status: 'missing', source: null, cutoff_hz: null, upgrade: null, away: undefined };
        entries.push({ t: null, row: { ...trackRow(missing), sound_checked: true, file_state: 'no_file',
          wait: h.t !== null && todoGroup(h.t) === 'not_found' ? 'not_found' : 'waiting', position, place: null,
          subfolder: null, playlists: held.get(h.key) ?? [line.folder] } });
      }
      also = files.filter((t) => !heldKeys.has(t.track_id) && fold(libraryFolder(pathOf(t)!) ?? '') === fold(line.folder))
        .map((t) => mk(t, { place: null }));
    }
  } else {
    shownKey = folder = key ?? '';
    const nkey = nfc(shownKey).replace(/\/+$/, '');
    const root = [...sites.roots.keys()].filter((r) => within(nkey, r)).sort((a, b) => depth(b) - depth(a))[0] ?? null;
    folderKind = root === nkey ? 'watched' : root !== null ? 'crate' : nkey.startsWith('Library/') ? 'library' : null;
    const inside = files.filter((t) => folderKind !== null && nfc(pathOf(t)!).startsWith(`${nkey}/`));
    title = folderKind === 'watched' ? sites.roots.get(nkey)! : sites.crates.get(nkey)?.[1] ?? base(nkey);
    const name = base(nkey);
    gone = folderKind === null || (folderKind !== 'watched' && !inside.length);
    const state = folderState(s, nkey);
    const away = state !== 'here' ? [AWAY_WORDS[state]] : [];
    for (const t of inside) {
      const path = nfc(pathOf(t)!);
      const between = path.slice(nkey.length + 1).split('/').slice(0, -1);   // the folders from the folder to the file
      const sub = folderKind === 'crate' ? between.join(' › ')
        : folderKind === 'watched' ? (between.length ? (sites.crates.get(parent(path)) ?? ['', between.join(' › ')])[1] : '') : null;
      entries.push(mk(t, { subfolder: sub }));
    }
    if (folderKind === 'watched') {
      const count = sites.crateCounts.get(nkey) ?? 0;
      subtitle = (n) => [n, ...away, ...(count ? [plural(count, '1 folder with music', '{n} folders with music')] : []), placeWords(nkey)];
    } else if (folderKind === 'crate') {
      const tip = [sites.roots.get(root!)!, ...nkey.slice(root!.length + 1).split('/')].join(' › ');
      subtitle = (n) => [n, ...away, tip];
    } else if (folderKind === 'library') {
      const listed = s.playlists.some((p) => fold(p.folder) === fold(name));
      subtitle = (n) => [n, ...(listed ? [] : ['no playlist uses it']), `Library › ${name}`];
    }
  }

  const have = entries.filter((e) => e.row.file_state !== 'no_file');
  const by = byQuality(have.map((e) => e.t!));
  const counted = Object.values(by).reduce((n, c) => n + c, 0);
  const summary = { tracks: have.length, lossless_share: counted ? Math.round((by.lossless / counted) * 10000) / 10000 : null,
    by_quality: by, upgrades_ready: have.filter((e) => e.row.upgrade_ready).length,
    not_lossless: by.good_lossy + by.weak + by.fake,
    to_do: have.filter((e) => e.t!.in_playlists && !e.t!.hidden && todoGroup(e.t!)).length };
  const q = fold(query ?? '').trim();
  const search = (list: Entry[]): Entry[] => (q ? list.filter((e) => fold(`${e.row.artist} ${e.row.title}`).includes(q)) : list);
  entries = search(entries);
  also = also && search(also);
  const chips = Object.fromEntries(LIBRARY_FILTERS.map((f) => [f,
    entries.filter((e) => e.row.file_state !== 'no_file' && matches(e, f)).length])) as Record<LibraryFilter, number>;
  const narrow = (list: Entry[]): Entry[] => list.filter((e) => matches(e, filter || 'all'));
  entries = narrow(entries);
  also = also && narrow(also);
  const wanted = (sort ?? (view === 'playlist' ? 'order' : 'artist')).replace(/^-/, '');
  const order = wanted === 'order' && view !== 'playlist' ? 'artist' : wanted;
  const byOrder = SORTS[order] ?? SORTS.artist;
  const sign = (sort ?? '').startsWith('-') ? -1 : 1;
  const sorted = (list: Entry[]): LibraryRow[] => [...list].sort((a, b) => sign * compare(byOrder(a.row), byOrder(b.row))).map((e) => e.row);
  const rows = sorted(entries);
  const alsoRows = also && sorted(also);
  const empty = gone ? 'gone' as const : rows.length || alsoRows?.length ? null
    : !files.length ? 'empty_library' as const : 'no_match' as const;
  return { title, folder, view: view as LibraryView, key: shownKey, folder_kind: folderKind,
    subtitle: gone ? [] : subtitle(plural(have.length, '1 track', '{n} tracks')), summary, chips, rows, also: alsoRows,
    read_at: readAt, enabled, service, empty };
}
