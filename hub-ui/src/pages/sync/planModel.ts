// The Sync page's plan before the start (docs/archive/pre-public/hub-ui-pages/sync-REDESIGN.md): kinds and tags of the rows, the scope (playlists and kinds
// in this run), the "how many" presets, the "next sync" tags and the "This run" summary. Pure, so it is tested.
import type { SegOption } from '$lib/components/segmentedModel';
import type { PreviewAction, SyncAccount, SyncPreview } from '$lib/bridge/types';
import { daysToLoad } from '$lib/days';
import type { DayBarInput } from '$lib/components/dayBarModel';
import type { ToggleItem } from '$lib/components/toggleModel';
import { estimate, foldText, plural, serviceName } from '$lib/format';
import { allActions, keyId } from './selection';

export const PREF_SCOPE = 'sync.scope';

/** Spotify is read by itself once per app session: only while the hub has not started its automatic read
 * (`spotify.auto_read`, kept in Python so a window reload doesn't read again), never while a read or a sync runs and
 * never before setup. A stopped or failed read stays as it is; the page offers "↻ Read Spotify". */
export function shouldAutoRead(p: Pick<SyncPreview, 'spotify' | 'empty'>,
  busy: { refreshRunning: boolean; syncRunning: boolean }): boolean {
  const sp = p.spotify;
  return !sp.auto_read && p.empty !== 'not_set_up' && sp.problem !== 'not_set_up' && !sp.reading
    && !busy.refreshRunning && !busy.syncRunning;
}
export const PREF_HOW_MANY = 'sync.howMany';

export type KindKey = 'new' | 'retry' | 'redownload' | 'move' | 'adopt' | 'bought' | 'weekly';
export const KINDS: { key: KindKey; label: string }[] = [
  { key: 'new', label: 'New' }, { key: 'retry', label: 'Not found last time' }, { key: 'redownload', label: 'File gone' },
  { key: 'move', label: 'Moves' }, { key: 'adopt', label: 'Moved by hand' }, { key: 'bought', label: 'Bought files' },
  { key: 'weekly', label: 'Weekly checks' },
];

/** A kind the app knows (one of KINDS): it has a label and a drawn icon (KindIcon). */
export const isKindKey = (k: string): k is KindKey => KINDS.some((x) => x.key === k);
export function kindOf(a: Pick<PreviewAction, 'kind' | 'reason'>): KindKey {
  if (a.kind === 'acquire') return a.reason === 'retry' ? 'retry' : a.reason === 'redownload' ? 'redownload' : 'new';
  if (a.kind === 'adopt_bought') return 'bought';
  if (a.kind === 'upgrade') return 'weekly';
  return a.kind === 'adopt' ? 'adopt' : 'move';
}

/** The small tag after the name; a plain new track has none. */
export function tagOf(a: PreviewAction): string | null {
  switch (kindOf(a)) {
    case 'retry': return 'not found last time';
    case 'redownload': return 'file gone';
    case 'move': return a.to_not_lossless && a.from_folder === a.folder ? 'to not_lossless'
      : `from ${a.from_folder ?? '?'}${a.to_not_lossless ? ' → not_lossless' : ''}`;
    case 'adopt': return 'file moved by hand';
    case 'bought': return 'bought file';
    case 'weekly': return 'weekly check';
    default: return null;
  }
}

/** Acquire and upgrade use Qobuz and take time; moves and adopts take none. */
export const isDownload = (a: { kind: string }) => a.kind === 'acquire' || a.kind === 'upgrade';
/** Only downloads can be "never download" (an existing file is never touched by it). */
export const canNever = (a: { kind: string }) => a.kind === 'acquire';

/** The minutes for `downloads` downloads, looked up in the engine's table (`estimate.minutes_by_downloads`, the
 * formula lives in views.run_minutes). The table ends at what fits today, so a larger count gets its last entry;
 * no table yet (no preview): 0. */
export const minutesFor = (table: number[], downloads: number): number =>
  downloads <= 0 ? 0 : (table[Math.min(downloads, table.length - 1)] ?? 0);

/** Every action in the order the sync works through them (the backend's `run` index). */
export const inRunOrder = (p: SyncPreview | null): PreviewAction[] => allActions(p);

// ---------- scope: which playlists and kinds are in this run ----------
/** Left out: folders and kinds the user unticked in the panel (remembered, so new ones come in ticked). */
export type Scope = { folders: string[]; kinds: KindKey[] };
export const FULL_SCOPE: Scope = { folders: [], kinds: [] };
export const inScope = (a: PreviewAction, s: Scope) => !s.folders.includes(a.folder) && !s.kinds.includes(kindOf(a));
export function toggleScope(s: Scope, what: 'folders' | 'kinds', v: string): Scope {
  const list = s[what] as string[];
  return { ...s, [what]: list.includes(v) ? list.filter((x) => x !== v) : [...list, v] };
}
export function readScope(v: unknown): Scope {
  const o = (v && typeof v === 'object' ? v : {}) as Partial<Scope>;
  const strings = (x: unknown) => (Array.isArray(x) ? x.filter((y): y is string => typeof y === 'string') : []);
  return { folders: strings(o.folders), kinds: strings(o.kinds).filter(isKindKey) };
}

export type Facet = { key: string; label: string; count: number };
/** Playlists (playlists.txt order) and kinds that have actions, with their counts. */
export function facets(actions: PreviewAction[], folderOrder: string[]): { folders: Facet[]; kinds: Facet[] } {
  const byFolder = new Map<string, number>();
  for (const a of actions) byFolder.set(a.folder, (byFolder.get(a.folder) ?? 0) + 1);
  const order = [...folderOrder, ...[...byFolder.keys()].filter((f) => !folderOrder.includes(f))];
  const folders = order.filter((f) => byFolder.has(f)).map((f) => ({ key: f, label: f, count: byFolder.get(f)! }));
  const kinds = KINDS.map((k) => ({ key: k.key, label: k.label, count: actions.filter((a) => kindOf(a) === k.key).length }))
    .filter((k) => k.count > 0);
  return { folders, kinds };
}

// ---------- how many downloads this run ----------
export type HowMany = number | 'fits' | 'all';
export type Preset = { value: HowMany; n: number; label: string };

/** 5, 10, 25, 50 (only below the total), "L · fits today" (when 0 < L < total), "All N". */
export function presets(total: number, left: number): Preset[] {
  if (total <= 0) return [];
  const fits = left > 0 && left < total;
  const out: Preset[] = [5, 10, 25, 50].filter((n) => n < total && !(fits && n === left))
    .map((n) => ({ value: n, n, label: String(n) }));
  if (fits) out.push({ value: 'fits', n: left, label: `${left} · fits today` });
  out.push({ value: 'all', n: total, label: `All ${total}` });
  return out.sort((a, b) => a.n - b.n);
}
export const defaultHowMany = (total: number, left: number): HowMany => (left > 0 && left < total ? 'fits' : 'all');
export function presetN(h: HowMany, total: number, left: number): number {
  return h === 'all' ? total : h === 'fits' ? Math.min(Math.max(left, 0), total) : Math.min(h, total);
}
/** The chip that a choice lights up now: a remembered 25 with only 8 downloads is "All 8". */
export function shownPreset(h: HowMany | 'custom', list: Preset[], total: number, left: number): HowMany | 'custom' {
  if (h === 'custom' || list.some((p) => p.value === h)) return h;
  const n = presetN(h, total, left);
  return list.find((p) => p.n === n)?.value ?? 'custom';
}
export function readHowMany(v: unknown): HowMany | null {
  return v === 'fits' || v === 'all' ? v : typeof v === 'number' && Number.isInteger(v) && v > 0 ? v : null;
}

/** A preset's ticks: every non-download action in scope plus the first n downloads in scope, in run order. */
export function presetTicks(ordered: PreviewAction[], scope: Scope, n: number): Set<string> {
  const out = new Set<string>();
  let dl = 0;
  for (const a of ordered) {
    if (!inScope(a, scope)) continue;
    if (!isDownload(a)) out.add(keyId(a.key));
    else if (dl < n) { out.add(keyId(a.key)); dl++; }
  }
  return out;
}

/** Ticked downloads in scope that come after the first `left` in run order: they wait for the next sync. */
export function nextSyncSet(ordered: PreviewAction[], ticked: Set<string>, scope: Scope, left: number): Set<string> {
  const out = new Set<string>();
  let dl = 0;
  for (const a of ordered) {
    const id = keyId(a.key);
    if (!isDownload(a) || !inScope(a, scope) || !ticked.has(id)) continue;
    if (dl >= Math.max(left, 0)) out.add(id);
    dl++;
  }
  return out;
}

// ---------- the "This run" summary ----------
export type RunTotals = {
  tracks: number;          // ticked actions in scope
  downloads: number;       // of those, downloads
  uses: number;            // Qobuz downloads this run uses (min(downloads, left))
  minutes: number;         // only the downloads that fit today take time
  waiting: number;         // ticked downloads over today's limit: they wait for the next sync
  after: number;           // downloads in scope still to come after this run (the DayBar's Later)
  days: number;            // more days for those at the daily limit (today counts while some is left: daysToLoad)
};
/** One row per service with a daily limit (spec §7, §8 several services), for the `downloads` the DJ ticked
 * (looked up in each account's `uses_by_downloads`, the engine's views.split for every count; a count over the table
 * takes its last entry). Qobuz takes min(downloads, left), exactly; behind Qobuz the accounts only catch the tracks
 * Qobuz doesn't have; without Qobuz the accounts fill up in order, as estimates. `short` is the number column ("10 of 10", "~4 of 30" for an estimate, "30 left" for a
 * backup); `value` the mini bar's share, null for a backup behind Qobuz (no bar: an empty one reads as unused);
 * `text` the full sentence (the row's tooltip, Dashboard's quota line). `limitReached`: the "limit is reached"
 * warning shows, so a used-up service says nothing more. */
export type ServiceRow = { service: string; name: string; text: string; value: number | null; short: string };
export function serviceRows(accounts: SyncAccount[], downloads: number, { limitReached = false } = {}): ServiceRow[] {
  if (!downloads) return [];
  const out: ServiceRow[] = [];
  for (const a of accounts) {
    const table = a.uses_by_downloads;
    const uses = table === null ? null : (table[Math.min(downloads, table.length - 1)] ?? 0);
    if (limitReached && a.left <= 0) continue;
    const about = a.about ? 'about ' : '';
    out.push(uses === null
      ? { service: a.service, name: serviceName(a.service, a.name), text: `${a.name}: ${a.left} left today · for tracks Qobuz doesn't have`,
          value: null, short: `${a.left} left` }
      : { service: a.service, name: serviceName(a.service, a.name), text: `${a.name}${a.service === 'qobuz' ? ' today' : ''}: uses ${about}`
          + `${uses} of ${a.left} left`, value: a.left ? uses / a.left : 1, short: `${a.about ? '~' : ''}${uses} of ${a.left}` });
  }
  return out;
}

/** The downloads in the playlists and kinds the user left on: what "All N" counts, and what Later counts from. */
export const downloadsInScope = (ordered: PreviewAction[], scope: Scope): number =>
  ordered.filter((a) => isDownload(a) && inScope(a, scope)).length;

/** `chosen` the ticked actions in scope; `scopedDownloads` the downloads in scope (`downloadsInScope`): Later counts
 * only those (issue 7, the user's ruling), so Today + Later is "All N" when everything in scope is ticked, and the
 * days follow the same number. What's switched off is the plan's "more tracks left out" note, never Later. */
export function runTotals(chosen: PreviewAction[], scopedDownloads: number, left: number, limit: number,
  minutesTable: number[]): RunTotals {
  const downloads = chosen.filter(isDownload).length;
  const uses = Math.min(downloads, Math.max(left, 0));
  const after = Math.max(0, scopedDownloads - uses);
  return { tracks: chosen.length, downloads, uses, minutes: minutesFor(minutesTable, uses), waiting: downloads - uses, after,
    days: limit > 0 ? daysToLoad(after, Math.max(left, 0) - uses, limit) : 0 };
}

// ---------- the run panel's blocks ----------
/** The DayBar's numbers: today's downloads, the downloads in scope after this run and their days, the moves. `left`
 * null means no daily limit (only free sources), so nothing waits for a later day. */
export function dayBarInput(t: RunTotals, left: number | null, moves: number): DayBarInput {
  const limited = left !== null;
  return { today: t.uses, later: limited ? t.after : 0, limited, laterDays: limited ? t.days : 0, moves };
}
/** The Playlists group's rows: a playlist is on unless the user left it out of the scope. */
export const folderItems = (folders: Facet[], scope: Scope): ToggleItem[] =>
  folders.map((f) => ({ ...f, on: !scope.folders.includes(f.key) }));
/** The What to do group's rows: a kind is on unless the user left it out of the scope. */
export const kindItems = (kinds: Facet[], scope: Scope): ToggleItem[] =>
  kinds.map((k) => ({ ...k, on: !(scope.kinds as string[]).includes(k.key) }));
/** What a run does today (spec §8, §11 "a run's count is what runs today"): the ticked actions minus the ticked
 * downloads that wait for the next sync (`downloads - uses`). When that is only the moves (today's limit used up, or
 * only moves ticked), they are counted as moves. `chosen` ticked actions, `downloads` of them downloads, `uses` the
 * downloads that fit today, `moves` the ticked moves. The count card and Start both say it. */
export function runCount(chosen: number, downloads: number, uses: number, moves: number): { n: number; unit: 'track' | 'move' } {
  const n = chosen - (downloads - uses);
  return { n, unit: moves > 0 && n === moves ? 'move' : 'track' };
}
/** "Start sync · 66 tracks"; with today's limit used up and only moves runnable: "Start sync · 3 moves"; nothing
 * that runs today: "Start sync". Arguments as `runCount`. */
export function startLabel(chosen: number, downloads: number, uses: number, moves: number): string {
  const { n, unit } = runCount(chosen, downloads, uses, moves);
  return n > 0 ? `Start sync · ${plural(n, unit)}` : 'Start sync';
}
/** Ticked, but nothing of it runs today: only downloads that wait for the next sync (today's limit used up, no moves
 * or other actions). A run would only re-read Spotify, log in to Qobuz and queue nothing, so Start is off (Task 9B
 * ruling). Nothing ticked is its own reason. Arguments as `runCount`. */
export function runsNothingToday(chosen: number, downloads: number, uses: number, moves: number): boolean {
  return chosen > 0 && runCount(chosen, downloads, uses, moves).n === 0;
}
/** The reason beside the switched-off Start. */
export const NOTHING_TODAY = 'Nothing to run today · downloads start tomorrow';

/** The time card for `n` actions that run today, in the one estimate format (`estimate`: "~75" min, "~2.5" h);
 * moves only take a minute or two; nothing runs: "0" min, so the card keeps its place. */
export function runTime(minutes: number, n: number): { value: string; unit: string } {
  if (!n) return { value: '0', unit: 'min' };
  if (Math.round(minutes) <= 0) return { value: '1–2', unit: 'min' };
  return estimate(minutes);
}
/** All · None in a scope group: the given keys turned on (`on`, out of the excluded list) or off; a new scope. */
export function scopeSet(s: Scope, what: 'folders' | 'kinds', keys: string[], on: boolean): Scope {
  const cur = s[what] as string[];
  const next = on ? cur.filter((k) => !keys.includes(k)) : [...cur, ...keys.filter((k) => !cur.includes(k))];
  return { ...s, [what]: next };
}
/** The amount Segmented's options: one per preset, keyed by its value; the amount that fits today carries ✦. */
export const howManyOptions = (list: Preset[]): SegOption<string>[] =>
  list.map((p) => ({ key: String(p.value), label: p.value === 'fits' ? `${p.n} ✦` : p.label }));

// ---------- search ----------
export { foldText };   // lives in $lib/format; re-exported for this page's callers and tests
export function matches(a: Pick<PreviewAction, 'artist' | 'title'>, query: string): boolean {
  const q = foldText(query.trim());
  return !q || foldText(`${a.artist} ${a.title}`).includes(q) || foldText(`${a.artist} – ${a.title}`).includes(q);
}

/** A list section: the visible rows of one folder, and its ticks among all its rows in scope; `waiting` of the ticked
 *  ones wait for the next sync. */
export type Section = { folder: string; rows: PreviewAction[]; total: number; ticked: number; waiting: number;
  /** ticked downloads (moves and weekly checks never wait, so they don't count against `waiting`) */
  downloads: number };

/** A section's counts among `rows`, all its rows in scope: total, ticked, the ticked downloads that wait for the next
 *  sync (`nextSync`), and the ticked downloads (moves and weekly checks are ticked but never wait). Sets hold keyIds. */
export function sectionCounts(rows: PreviewAction[], ticked: ReadonlySet<string>, nextSync: ReadonlySet<string>)
  : Pick<Section, 'total' | 'ticked' | 'waiting' | 'downloads'> {
  const on = rows.filter((a) => ticked.has(keyId(a.key)));
  return { total: rows.length, ticked: on.length, waiting: on.filter((a) => nextSync.has(keyId(a.key))).length,
    downloads: on.filter(isDownload).length };
}

/** Every ticked download of a section waits for the next sync: the head says it once and the rows drop it. Counts
 *  downloads only; a ticked move in the section must not turn the per-row label back on for every download. */
export const waitsWhole = (waiting: number, tickedDownloads: number): boolean =>
  waiting > 0 && waiting === tickedDownloads;

/** Some ticked download may wait for the next sync while others run today (the why column may fill row by row): the
 *  plan holds more downloads than today's `left`, and some are left. With none left every download waits and the
 *  head says so (waitsWhole); without a daily limit (`left` infinite) nothing waits. */
export const mayWaitToday = (planDownloads: number, left: number): boolean => left > 0 && planDownloads > left;

/** A section head's count: "N of M ticked", plus "· W next sync" while ticked downloads wait for a later day. */
export const sectionSummary = (ticked: number, total: number, waiting: number): string =>
  `${ticked} of ${total} ticked${waiting ? ` · ${waiting} next sync` : ''}`;

/** Whether a section's rows get the why column: one has a tag, or one is a download that may wait for the next sync
 *  (`mayWait`: the plan holds more downloads than today's limit leaves). Doesn't depend on ticks, so it stays put. */
export const whyColumn = (rows: PreviewAction[], mayWait: boolean): boolean =>
  rows.some((a) => tagOf(a) !== null || (mayWait && isDownload(a)));

/** Sections per playlist folder in playlists.txt order; inside, run order. */
export function sections(rows: PreviewAction[], folderOrder: string[]): { folder: string; rows: PreviewAction[] }[] {
  const by = new Map<string, PreviewAction[]>();
  for (const a of rows) by.set(a.folder, [...(by.get(a.folder) ?? []), a]);
  const order = [...folderOrder, ...[...by.keys()].filter((f) => !folderOrder.includes(f))];
  return order.filter((f) => by.has(f)).map((folder) => ({ folder, rows: by.get(folder)! }));
}
