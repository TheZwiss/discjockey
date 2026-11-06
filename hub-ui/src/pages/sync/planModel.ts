// The Sync page's plan before the start (docs/archive/pre-public/hub-ui-pages/sync-REDESIGN.md): kinds and tags of the rows, the scope (playlists and kinds
// in this run), the "how many" presets, the "next sync" tags and the "This run" summary. Pure, so it is tested.
import type { SegOption } from '$lib/components/segmentedModel';
import type { PlaylistRow, PlaylistService, PreviewAction, SyncAccount, SyncPreview } from '$lib/bridge/types';
import { daysToLoad } from '$lib/days';
import type { DayBarInput } from '$lib/components/dayBarModel';
import type { ToggleItem } from '$lib/components/toggleModel';
import { estimate, foldText, plural, serviceName } from '$lib/format';
import { PLAYLIST_SERVICE_NAMES } from '$lib/copy';
import { allActions, keyId } from './selection';

export const PREF_SCOPE = 'sync.scope';

/** Spotify is read by itself once per app session: only while the hub has not started its automatic read
 * (`read_status.auto_read`, kept in Python so a window reload doesn't read again), never while a read or a sync runs and
 * never before setup. A stopped or failed read stays as it is; the page offers "↻ Read Spotify". */
export function shouldAutoRead(p: Pick<SyncPreview, 'read_status' | 'empty'>,
  busy: { refreshRunning: boolean; syncRunning: boolean }): boolean {
  const sp = p.read_status;
  return !sp.auto_read && p.empty !== 'not_set_up' && sp.problem !== 'not_set_up' && !sp.reading
    && !busy.refreshRunning && !busy.syncRunning;
}

/** The body line of Sync's card for a service whose login is missing or expired: what it affects and that the rest
 *  still syncs. `rows`: playlists.txt as the Playlists view lists it (null while it isn't known: then the line says
 *  "Your Qobuz playlists" and promises nothing about the others). Names the folders of the switched-on lines of that
 *  service (three, then "and N more"); the second sentence only when other switched-on lines exist. */
export function readBlockLine(kind: 'not_set_up' | 'login_expired', service: PlaylistService,
  rows: Pick<PlaylistRow, 'folder' | 'service' | 'enabled'>[] | null): string {
  const name = PLAYLIST_SERVICE_NAMES[service];
  const until = kind === 'login_expired' ? `you connect ${name} again` : `${name} is connected`;
  const mine = (rows ?? []).filter((r) => r.enabled && r.service === service).map((r) => r.folder);
  const others = (rows ?? []).some((r) => r.enabled && r.service !== service);
  const shown = mine.slice(0, 3);
  const more = mine.length - shown.length;
  const list = more > 0 ? `${shown.join(', ')} and ${more} more`
    : shown.length > 1 ? `${shown.slice(0, -1).join(', ')} and ${shown[shown.length - 1]}` : shown[0];
  const subject = mine.length ? list : `Your ${name} playlists`;
  const verb = mine.length === 1 ? "isn't" : "aren't";
  return `${subject} ${verb} read until ${until}.${others ? ' Your other playlists sync as usual.' : ''}`;
}
export const PREF_HOW_MANY = 'sync.howMany';

export type KindKey = 'new' | 'retry' | 'redownload' | 'bought' | 'weekly';
export const KINDS: { key: KindKey; label: string }[] = [
  { key: 'new', label: 'New' }, { key: 'retry', label: 'Not found last time' }, { key: 'redownload', label: 'File gone' },
  { key: 'bought', label: 'Bought files' }, { key: 'weekly', label: 'Weekly checks' },
];

/** A kind the app knows (one of KINDS): it has a label and a drawn icon (KindIcon). */
export const isKindKey = (k: string): k is KindKey => KINDS.some((x) => x.key === k);
export function kindOf(a: Pick<PreviewAction, 'kind' | 'reason'>): KindKey {
  if (a.kind === 'acquire') return a.reason === 'retry' ? 'retry' : a.reason === 'redownload' ? 'redownload' : 'new';
  if (a.kind === 'adopt_bought') return 'bought';
  return 'weekly';   // upgrade: the sync plans no other kinds (it never moves a file, only places new downloads)
}

/** Why a row is in the plan, in words, one per kind (issue 35): the row's tooltip says it for every row, the why
 *  column for all but a plain new song (its download icon says it; a list of new songs keeps its names' width). */
export const WHY: Record<KindKey, string> = {
  new: 'not downloaded yet', retry: 'not found last time', redownload: 'file gone', bought: 'bought file',
  weekly: 'weekly check',
};
export const whyOf = (a: Pick<PreviewAction, 'kind' | 'reason'>): string => WHY[kindOf(a)];

/** The small tag after the name, in the why column; a plain new track has none (its icon is enough). */
export function tagOf(a: Pick<PreviewAction, 'kind' | 'reason'>): string | null {
  const k = kindOf(a);
  return k === 'new' ? null : WHY[k];
}

/** Acquire and upgrade use Qobuz and take time; a bought file takes none. */
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
/** Left out: playlists the user switched off in the browser column and weekly checks switched off in the panel
 *  (remembered, so new ones come in switched on). Only the two weekly checks switch as kinds (issue 36): new songs,
 *  files gone and bought files are left out row by row or per playlist with the plan's ticks. */
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
  // a kind left out before issue 36 that no longer has a switch is dropped, so nothing stays out unseen
  return { folders: strings(o.folders), kinds: strings(o.kinds).filter((k): k is KindKey => isWeeklyKind(k)) };
}

/** What a playlist or folder is called on the page: never blank, even when an action arrives without a folder name. */
export const folderLabel = (folder: string): string => folder.trim() || 'Your own music';

/** The plan's note on what the switches leave out: "4 more tracks left out" under rows, but "4 tracks left out" when
 *  every track is left out and no row is above it (issue 35: weekly checks switched off, nothing else). */
export const leftOutTitle = (hidden: number, shown: number): string =>
  `${plural(hidden, shown > 0 ? 'more track' : 'track')} left out`;
/** The note's line: where the switches that leave them out are (issue 36: playlists in the column on the left,
 *  the weekly checks in the panel on the right). */
export function leftOutBody(s: Scope): string {
  const lists = s.folders.length > 0;
  const kinds = s.kinds.length > 0;
  return lists && kinds ? 'Playlists switched off on the left and weekly checks switched off on the right.'
    : kinds ? 'Weekly checks you switched off on the right.' : 'Playlists you switched off on the left.';
}

// ---------- the kinds at a glance (issue 36: the strip on top of the plan) ----------
/** The two weekly checks, the kinds with a switch of their own (issue 36). */
export const WEEKLY_KINDS: KindKey[] = ['retry', 'weekly'];
export const isWeeklyKind = (k: string): boolean => (WEEKLY_KINDS as string[]).includes(k);
/** Each kind in the strip: its words, what it means (the row's tooltip) and its colour token. The bar's order:
 *  the downloads (the blue family), the weekly checks (the teal family), then bought files, which download nothing. */
export const KIND_SHARE: { key: KindKey; label: string; tip: string; colour: string }[] = [
  { key: 'new', label: 'New downloads', tip: 'Songs in your playlists with no file yet', colour: 'var(--kind-new)' },
  { key: 'redownload', label: 'Files gone', tip: 'Downloaded before, but the file isn’t there any more: downloaded again',
    colour: 'var(--kind-gone)' },
  { key: 'retry', label: 'Missing songs', tip: 'Not found last time: looked for again once a week', colour: 'var(--kind-retry)' },
  { key: 'weekly', label: 'Lossy files', tip: 'Files that aren’t lossless: checked once a week for a lossless copy',
    colour: 'var(--kind-weekly)' },
  { key: 'bought', label: 'Bought files', tip: 'Files you bought, put in their playlists: nothing to download',
    colour: 'var(--kind-bought)' },
];
export type KindShare = { key: KindKey; label: string; tip: string; colour: string; n: number; off: boolean };
/** The strip's numbers: the tracks in the playlists switched on, by kind. A kind is listed while the plan has it in
 *  any playlist (so the rows stay put while playlists switch); `off`: a weekly check switched off (its count stays,
 *  its part of the bar dims, its row says so). `total` counts what is switched on, kinds and playlists. */
export function kindShares(ordered: PreviewAction[], s: Scope): { total: number; playlists: number; kinds: KindShare[] } {
  const listed = ordered.filter((a) => !s.folders.includes(a.folder));
  const kinds = KIND_SHARE.filter((k) => ordered.some((a) => kindOf(a) === k.key)).map((k) => ({
    ...k, n: listed.filter((a) => kindOf(a) === k.key).length, off: s.kinds.includes(k.key) }));
  const on = listed.filter((a) => inScope(a, s));
  return { total: on.length, playlists: new Set(on.map((a) => a.folder)).size, kinds };
}
/** The strip's line under the count. */
export function stripLine(total: number, playlists: number, everyListOff: boolean): string {
  if (everyListOff) return 'every playlist switched off';
  if (!total) return 'everything switched off';
  // a plan section is a folder: a playlist's, or the folder of your own music a weekly check is about
  return `to sync in ${plural(playlists, 'folder')}`;
}

/** The panel's Weekly checks: both switches always (issue 36; issue 35's bug: a switch must never go because its
 *  kind is the only one, or has no rows today), each with its count in the playlists switched on. */
export function weeklyItems(ordered: PreviewAction[], s: Scope): ToggleItem[] {
  const listed = ordered.filter((a) => !s.folders.includes(a.folder));
  return WEEKLY_KINDS.map((key) => ({ key, label: KIND_SHARE.find((k) => k.key === key)!.label,
    count: listed.filter((a) => kindOf(a) === key).length, on: !s.kinds.includes(key) }));
}

/** Per playlist, the tracks the sync would do in it: only the kinds switched on (the old panel counted the weekly
 *  checks switched off too). The browser column's switch tooltip says it. */
export function planCounts(ordered: PreviewAction[], s: Scope): Record<string, number> {
  const out: Record<string, number> = {};
  for (const a of ordered) if (!s.kinds.includes(kindOf(a))) out[a.folder] = (out[a.folder] ?? 0) + 1;
  return out;
}
/** A playlist's switch in the browser column, in words (its tooltip): what it holds for the sync, or why it can't
 *  switch. `n` null: the plan isn't known (reading, up to date, a run). */
export function playlistSwitchTip(name: string, o: { enabled: boolean; on: boolean; n: number | null; running: boolean }): string {
  if (!o.enabled) return `${name} · switched off on the Playlists page`;
  if (o.running) return `${name} · ${o.on ? 'in' : 'left out of'} this sync · switch it once the sync ends`;
  if (!o.on) return `${name} · left out of the sync`;
  return o.n === null ? `${name} · in the sync` : o.n === 0 ? `${name} · nothing to sync` : `${name} · ${plural(o.n, 'track')} to sync`;
}
/** The day bar's words while it is empty: why nothing downloads. */
export function dayBarEmpty(inScope: number, ticked: number): string {
  return inScope === 0 ? 'Everything switched off' : ticked === 0 ? 'Nothing ticked' : 'No downloads';
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
/** The DayBar's numbers: today's downloads, the downloads in scope after this run and their days. `left` null means
 * no daily limit (only free sources), so nothing waits for a later day. */
export function dayBarInput(t: RunTotals, left: number | null): DayBarInput {
  const limited = left !== null;
  return { today: t.uses, later: limited ? t.after : 0, limited, laterDays: limited ? t.days : 0 };
}
/** What a run does today (spec §8, §11 "a run's count is what runs today"): the ticked actions minus the ticked
 * downloads that wait for the next sync (`downloads - uses`). `chosen` ticked actions, `downloads` of them downloads,
 * `uses` the downloads that fit today. The count card and Start both say it. */
export const runCount = (chosen: number, downloads: number, uses: number): number => chosen - (downloads - uses);
/** "Start sync · 66 tracks"; nothing that runs today: "Start sync". Arguments as `runCount`. */
export function startLabel(chosen: number, downloads: number, uses: number): string {
  const n = runCount(chosen, downloads, uses);
  return n > 0 ? `Start sync · ${plural(n, 'track')}` : 'Start sync';
}
/** Ticked, but nothing of it runs today: only downloads that wait for the next sync (today's limit used up, no
 * other actions). A run would only re-read Spotify, log in to Qobuz and queue nothing, so Start is off (Task 9B
 * ruling). Nothing ticked is its own reason. Arguments as `runCount`. */
export function runsNothingToday(chosen: number, downloads: number, uses: number): boolean {
  return chosen > 0 && runCount(chosen, downloads, uses) === 0;
}
/** The reason beside the switched-off Start. */
export const NOTHING_TODAY = 'Nothing to run today · downloads start tomorrow';

/** The time card for `n` actions that run today, in the one estimate format (`estimate`: "~75" min, "~2.5" h);
 * bought files only take a minute or two; nothing runs: "0" min, so the card keeps its place. */
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
  /** ticked downloads (bought files and weekly checks never wait, so they don't count against `waiting`) */
  downloads: number };

/** A section's counts among `rows`, all its rows in scope: total, ticked, the ticked downloads that wait for the next
 *  sync (`nextSync`), and the ticked downloads (bought files and weekly checks are ticked but never wait). Sets hold keyIds. */
export function sectionCounts(rows: PreviewAction[], ticked: ReadonlySet<string>, nextSync: ReadonlySet<string>)
  : Pick<Section, 'total' | 'ticked' | 'waiting' | 'downloads'> {
  const on = rows.filter((a) => ticked.has(keyId(a.key)));
  return { total: rows.length, ticked: on.length, waiting: on.filter((a) => nextSync.has(keyId(a.key))).length,
    downloads: on.filter(isDownload).length };
}

/** Every ticked download of a section waits for the next sync: the head says it once and the rows drop it. Counts
 *  downloads only; a ticked bought file in the section must not turn the per-row label back on for every download. */
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

// ---------- the import's hints (plan library stage 4, W9) ----------
/** Songs held back until "Is this the same song?" is answered (D4): said under the run's counts (they are why the
 *  count is smaller), with the way to To-do. Null at 0. */
export function waitingAnswersLine(n: number): string | null {
  if (n <= 0) return null;
  return n === 1 ? '1 song waits for your answer on the To-do page.'
    : `${n} songs wait for your answer on the To-do page.`;
}
/** First upgrade checks of imported music the per-run cap left for later runs (D9): said in the day card, where
 *  today's allowance is. Null at 0. */
export function deferredChecksLine(n: number): string | null {
  if (n <= 0) return null;
  const allowance = "so today's Qobuz allowance isn't used up.";
  return n === 1 ? `1 first upgrade check of your imported music waits for later runs, ${allowance}`
    : `${n} first upgrade checks of your imported music wait for later runs, ${allowance}`;
}
/** The waiting answers: To-do, showing the questions only. */
export const WAITING_ANSWERS_HREF = '#/todo?filter=same_song';
