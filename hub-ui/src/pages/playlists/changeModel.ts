// Editing model of the Playlists page (plan Task 69, pure). The page keeps `loaded` (what playlists() returned)
// and `draft` (the rows as the user edits them). Nothing here talks to the backend.
import type {
  AddedPlaylist, ByQuality, ChangePreview, Fail, PlaylistInfo, PlaylistLine, PlaylistRow, PlaylistTrack, Playlists,
  Quality,
} from '$lib/bridge/types';
import { artistTitle, plural } from '$lib/format';
import { ownerText } from '$lib/components/addRowModel';

export type Loaded = { version: string; rows: PlaylistRow[] };
export type DraftRow = {
  key: string; folder: string; link: string; enabled: boolean; info: PlaylistInfo | null; tracks: number | null;
  quality: ByQuality; isNew: boolean;
};

const NO_QUALITY: ByQuality = { lossless: 0, good_lossy: 0, weak: 0, fake: 0, missing: 0 };

export function loadedFrom(p: Pick<Playlists, 'version' | 'rows'>): Loaded {
  return { version: p.version, rows: p.rows };
}

/** Draft rows from the loaded rows. Keys stay stable for the same row of the same file. */
export function draftFrom(loaded: Loaded): DraftRow[] {
  return loaded.rows.map((r) => ({ key: `r${r.index}:${r.link}`, folder: r.folder, link: r.link, enabled: r.enabled,
    info: r.info, tracks: r.tracks, quality: r.quality, isNew: false }));
}

/** The lines for preview_playlist_change / save_playlists, top (highest priority) first. */
export function lines(draft: DraftRow[]): PlaylistLine[] {
  return draft.map((r) => ({ folder: r.folder, link: r.link, enabled: r.enabled }));
}

/** True when order, folder names, on/off or links differ from the loaded file. */
export function isDirty(draft: DraftRow[], loaded: Loaded | null): boolean {
  if (!loaded) return false;
  const a = lines(draft);
  const b = loaded.rows;
  if (a.length !== b.length) return true;
  return a.some((l, i) => l.folder !== b[i].folder || l.link !== b[i].link || l.enabled !== b[i].enabled);
}

/** Back to the loaded file. */
export function undo(loaded: Loaded): DraftRow[] {
  return draftFrom(loaded);
}

/** Moves the row at `from` to index `to` (indexes of the list before the move). */
export function reorder(draft: DraftRow[], from: number, to: number): DraftRow[] {
  if (from < 0 || from >= draft.length) return draft;
  const t = Math.max(0, Math.min(draft.length - 1, to));
  if (t === from) return draft;
  const out = [...draft];
  const [row] = out.splice(from, 1);
  out.splice(t, 0, row);
  return out;
}

/** ⌥↑ / ⌥↓: one step up (-1) or down (+1). */
export function moveBy(draft: DraftRow[], key: string, delta: number): DraftRow[] {
  const i = draft.findIndex((r) => r.key === key);
  return i < 0 ? draft : reorder(draft, i, i + delta);
}

/**
 * Pointer drag: where the dragged row lands. `mids` are the vertical centres of all rows as laid out when the
 * drag started, `from` is the dragged row, `y` the dragged row's current centre.
 */
export function dropIndex(mids: number[], from: number, y: number): number {
  let to = 0;
  mids.forEach((m, i) => { if (i !== from && m < y) to++; });
  return to;
}

/** Visual shift of row `i` while row `from` is dragged to `to` (in rows: -1, 0 or +1). */
export function shiftFor(i: number, from: number, to: number): number {
  if (i === from) return 0;
  if (from < to && i > from && i <= to) return -1;
  if (from > to && i >= to && i < from) return 1;
  return 0;
}

export function rename(draft: DraftRow[], key: string, folder: string): DraftRow[] {
  return draft.map((r) => (r.key === key ? { ...r, folder: folder.trim() } : r));
}

export function toggle(draft: DraftRow[], key: string): DraftRow[] {
  return draft.map((r) => (r.key === key ? { ...r, enabled: !r.enabled } : r));
}

export function remove(draft: DraftRow[], key: string): DraftRow[] {
  return draft.filter((r) => r.key !== key);
}

let added = 0;
/** "Add to the list": appends at the bottom (lowest priority). */
export function addRow(draft: DraftRow[], a: AddedPlaylist, folder: string): DraftRow[] {
  added++;
  return [...draft, { key: `new${added}:${a.link}`, folder: folder.trim(), link: a.link, enabled: true, info: a.info,
    tracks: a.tracks, quality: { ...NO_QUALITY }, isNew: true }];
}

/** Priority numbers: switched-on rows 1…n from the top, switched-off rows "–". */
export function priorities(draft: DraftRow[]): string[] {
  let n = 0;
  return draft.map((r) => (r.enabled ? String(++n) : '–'));
}

/** The line under the folder name. tone 'bad' = red. */
export function infoLine(r: DraftRow): { text: string; tone: 'muted' | 'bad' } {
  if (!r.enabled) return { text: 'switched off · files stay', tone: 'muted' };
  if (!r.info) return { text: 'not read yet', tone: 'muted' };
  if (!r.info.readable) return { text: 'Follow ≠ own: make your own copy in Spotify.', tone: 'bad' };
  return { text: `"${r.info.name}" · ${ownerText(r.info)}`, tone: 'muted' };
}

/** The page header's status line: the tracks of the switched-on playlists ("38 tracks in your playlists"). */
export function statusLine(draft: DraftRow[]): string {
  const n = draft.reduce((a, r) => a + (r.enabled ? r.tracks ?? 0 : 0), 0);
  return `${plural(n, 'track')} in your playlists`;
}

/** The list head's summary: "5 on · 1 off". */
export function onOffText(draft: DraftRow[]): string {
  const on = draft.filter((r) => r.enabled).length;
  const off = draft.length - on;
  return off ? `${on} on · ${off} off` : `${on} on`;
}

/** "6 of 11 lossless" beside a playlist's quality bar; null when nothing is downloaded yet. */
export function losslessText(q: ByQuality): string | null {
  const n = q.lossless + q.good_lossy + q.weak + q.fake + q.missing;
  return n ? `${q.lossless} of ${n} lossless` : null;
}

// ---- Right panel "What this change does" (part B) ----

export type PreviewAnswer = ({ ok: true } & ChangePreview) | Fail;
/** What the panel knows about the preview: the last answer that counted, and whether a newer one is on its way. */
export type PreviewState = { loading: boolean; answer: PreviewAnswer | null };
export type Overlap = Playlists['overlaps'][number];
export type PanelView = 'overlaps' | 'loading' | 'moves' | 'reroute' | 'add' | 'rename' | 'switch_off' | 'unknown' | 'none'
  | 'problem' | 'sync_running' | 'failed';
export type Panel = {
  view: PanelView;
  dim: boolean;             // a newer preview is on its way: keep this one, dimmed
  saveAllowed: boolean;     // false only while the preview names a problem
  preview: ChangePreview | null;
  fail: Fail | null;        // view 'failed' (offline, ...)
  overlaps: Overlap[];
};

export const PREVIEW_AFTER_SYNC = 'The preview is available when the sync is finished.';
export const NO_PREVIEW: PreviewState = { loading: false, answer: null };

export function panelFor(dirty: boolean, preview: PreviewState, overlaps: Overlap[]): Panel {
  const base: Panel = { view: 'overlaps', dim: false, saveAllowed: true, preview: null, fail: null, overlaps };
  if (!dirty) return base;
  const a = preview.answer;
  if (!a) return { ...base, view: 'loading' };
  const dim = preview.loading;
  if (!a.ok) return { ...base, dim, view: a.kind === 'sync_running' ? 'sync_running' : 'failed', fail: a };
  const { ok: _ok, ...p } = a;
  return { ...base, dim, preview: p, view: p.problem ? 'problem' : p.kind, saveAllowed: !p.problem };
}

/** Request ids: only the answer to the newest request counts. `next()` when a request is planned, `cancel()` when
 *  no answer is wanted any more (draft clean again, sync started). */
export function previewRequests() {
  let latest = 0;
  return {
    next: (): number => ++latest,
    cancel: (): void => { latest++; },
    isLatest: (id: number): boolean => id === latest,
  };
}

export type OverlapCard = {
  folder: string;
  total: number | null;                     // the playlist's tracks in Spotify (null: not read)
  keeps: number | null;                     // ... of them landing in its own folder
  goTo: { to: string; count: number }[];    // where the others land, in list order
  lost: Overlap[];                          // the tracks that land elsewhere
  hint: string;                             // its section's hint: "lands in Hard_Bounce", "4 in H · 1 in P"
};
/** One card per playlist that gives tracks to a higher one, in list order: how many stay, where the rest land. */
export function overlapCards(overlaps: Overlap[], rows: { folder: string; tracks: number | null }[]): OverlapCard[] {
  const lost = new Map<string, Overlap[]>();
  for (const o of overlaps) {
    for (const f of o.folders) if (f !== o.lands_in) lost.set(f, [...(lost.get(f) ?? []), o]);
  }
  const rank = (f: string) => { const i = rows.findIndex((r) => r.folder === f); return i < 0 ? rows.length : i; };
  return [...lost.keys()].sort((a, b) => rank(a) - rank(b)).map((folder) => {
    const ts = lost.get(folder)!;
    const counts = new Map<string, number>();
    for (const t of ts) counts.set(t.lands_in, (counts.get(t.lands_in) ?? 0) + 1);
    const goTo = [...counts].sort((a, b) => rank(a[0]) - rank(b[0])).map(([to, count]) => ({ to, count }));
    const total = rows.find((r) => r.folder === folder)?.tracks ?? null;
    return { folder, total, keeps: total === null ? null : Math.max(0, total - ts.length), goTo, lost: ts,
      hint: goTo.length === 1 ? `lands in ${goTo[0].to}` : goTo.map((g) => `${g.count} in ${g.to}`).join(' · ') };
  });
}

/** The move view's folder rows: each folder whose file count changes, in the backend's order (the new list's), with
 *  its count after the change and the difference; `max` is the biggest difference, the scale of every row's bar. */
export function folderBars(fs: ChangePreview['folders']): { rows: { folder: string; after: number; delta: number }[];
  max: number } {
  const rows = fs.filter((f) => f.after !== f.before).map((f) => ({ folder: f.folder, after: f.after, delta: f.after - f.before }));
  return { rows, max: Math.max(0, ...rows.map((r) => Math.abs(r.delta))) };
}

/** What the unsaved change does to each folder (after - before, only the ones that change), for the main list. */
export function folderChanges(p: ChangePreview | null): Map<string, number> {
  return new Map((p ? folderBars(p.folders).rows : []).map((r) => [r.folder, r.delta]));
}

/** Under a playlist's name while a change is unsaved: "gets 27 more" / "gives 20 away". */
export function changeText(delta: number): string {
  return delta > 0 ? `gets ${delta} more` : `gives ${-delta} away`;
}

export type Route = { from: string; to: string; rows: FoldRow[] };
/** The tracks that change folder, grouped by route ("Hard_Bounce → Set_04"): the ones with a file (moves) and the
 *  ones that only land somewhere else later (reroutes), the biggest route first, equal ones in the backend's order. */
export function moveRoutes(p: Pick<ChangePreview, 'moves' | 'reroutes'>): Route[] {
  const routes = new Map<string, Route>();
  const add = (from: string, to: string, row: FoldRow) => {
    const k = `${from}\u0000${to}`;
    if (!routes.has(k)) routes.set(k, { from, to, rows: [] });
    routes.get(k)!.rows.push(row);
  };
  // the route head says where a track goes; its badge says what it is (a lossy file lands in that folder's not_lossless/)
  for (const m of p.moves ?? []) add(m.from, m.to, foldTrack({ ...m, downloaded: true }));
  for (const r of p.reroutes) add(r.from, r.to, foldTrack(r));
  return [...routes.values()].sort((a, b) => b.rows.length - a.rows.length);
}

export type FoldRow = { track_id: string; name: string; cover_url: string | null; note: string | null;
  badge: { quality: Quality; label: string } | null };
/** A track row of a fold: the quality badge once it has a file, else "not downloaded yet" (badge null); a track
 * the user said "never download" to says so instead. */
export function foldTrack(t: PlaylistTrack, note: string | null = null): FoldRow {
  const badge = t.downloaded && t.quality_label ? { quality: t.quality, label: t.quality_label } : null;
  return { track_id: t.track_id, name: artistTitle(t.artist, t.title), cover_url: t.cover_url,
    note: !badge && t.never ? [note, 'never download'].filter(Boolean).join(' · ') : note, badge };
}
