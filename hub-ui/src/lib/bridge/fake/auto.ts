// Auto-upgrade in the fake backend (issue 33 stage C): Settings' and Setup's switch, rekordbox's state, the marks on a
// parked upgrade and the words To-do and the Sync page read them with. The real engine: discjockey/auto_upgrade.py,
// hub/api.py (set_auto_upgrade, rekordbox_status, _auto_upgrade_ready), hub/views.py (upgrade_detail, auto_refused_view).
// The switch lives in `s.setup.auto_upgrade` (setup_status answers it as it is); rekordbox's state in
// `s.rekordbox_state` / `s.rekordbox_running` (the dev toolbar's "rekordbox open" sets the latter).
import type { HubEvent } from '../events';
import type { AutoRefused, AutoUpgradeBlock, AutoUpgradeResult, RekordboxStatus, Result, RunSummary, SyncPreview, Upgrade } from '../types';
import { dateOnly, isoLocal, makeUpgrade, pathOf, qualityOf, result, runDetail, runId, type FakeState, type FakeTrack } from './data';

/** The switch (on unless the state says off). */
export const autoOn = (s: FakeState): boolean => s.setup.auto_upgrade !== false;

/** `rekordbox_status()`: the library's state and whether rekordbox runs. */
export const rekordboxStatus = (s: FakeState): RekordboxStatus =>
  ({ state: s.rekordbox_state ?? 'ready', running: !!s.rekordbox_running });

/** views.AUTO_REFUSED_SHORT: the short word of a refusal in To-do's row. */
export const AUTO_REFUSED_SHORT: Record<AutoRefused['reason'], string> = {
  timing: "couldn't line it up", not_analysed: 'not analysed in rekordbox', cloud: 'in Cloud Library Sync',
  space: 'not enough free space', needs_choice: "couldn't compare it",
};
export const AUTO_WAITING_DETAIL = 'Waits for rekordbox to be closed';
/** views.AUTO_BATCH_DETAIL */
export const AUTO_BATCH_DETAIL = 'Upgraded during your sync';
/** The engine's words for a refusal, recorded on the parked upgrade by the sync: design §8 (convert.REFUSED), and
 *  upgrades.COULD_NOT_COMPARE for `needs_choice` (the two files could not be compared at all). */
export const AUTO_REFUSED_WORDS: Record<AutoRefused['reason'], string> = {
  timing: "Discjockey couldn't line the new file up with your rekordbox track exactly, so nothing was changed. Analyse the track again in rekordbox and try again.",
  not_analysed: "rekordbox hasn't analysed this track yet, so Discjockey can't tell exactly where your cues sit. Nothing was changed. Analyse it in rekordbox, quit rekordbox, and try again.",
  cloud: "This track is in rekordbox's Cloud Library Sync, which Discjockey doesn't change yet. Nothing was changed.",
  space: "There isn't enough free space for the new AIFF files (640 MB needed, 120 MB free). Nothing was changed.",
  needs_choice: "Discjockey couldn't compare the two files, so nothing was changed. Try again, or choose New track.",
};

/** views.auto_waits_mark: the sync met rekordbox open for this upgrade; only while the switch is on and Same track could run. */
export const autoWaits = (s: FakeState, up: Upgrade & { cutoff_hz?: null }, sameTrackOk: boolean): boolean =>
  autoOn(s) && !!up.auto_waits && sameTrackOk;

/** views.upgrade_detail: an Upgrade ready row's short line. `same` is the row's quick `same_track` answer. */
export function autoDetail(s: FakeState, t: FakeTrack, same: string | null, plain: string): string {
  const up = t.upgrade!;
  if (autoWaits(s, up, same === null)) return AUTO_WAITING_DETAIL;
  const r = up.auto_refused;
  if (r && AUTO_REFUSED_SHORT[r.reason]) {
    const different = up.alignment?.result === 'different';
    if (same === null || (same === r.reason && !different)) {
      const short = AUTO_REFUSED_SHORT[r.reason];
      return `${short[0].toUpperCase()}${short.slice(1)} · not upgraded at your sync`;
    }
  }
  return plain;
}

/** `sync_preview().auto_upgrade`: the upgrades the sync's last phase would put in place (waiting ones included), the
 *  recorded refusals left out; null while the switch is off. */
export function autoPreview(s: FakeState, ready: number): SyncPreview['auto_upgrade'] {
  return autoOn(s) ? { on: true, ready } : null;
}

/** views.same_track_reason for a fake track: null when Same track can run now (the quick answer: rekordbox's cached state). */
export function sameTrackReasonOf(s: FakeState, t: FakeTrack): string | null {
  const up = t.upgrade;
  if (!up) return 'no_upgrade';
  if (!up.swap_safe) return 'needs_choice';
  if (t.away) return 'away';   // its drive isn't connected: the quick check knows that much
  return (s.rekordbox_state ?? 'ready') === 'unreadable' && up.swap_how === 'new_aiff' ? 'rekordbox_unreadable' : null;
}

/** The set of the sync's last phase, in To-do's order (auto_upgrade.plan): Upgrade all's list (hidden left out) filtered
 *  by the quick Same track answer, minus the tracks a recorded refusal still holds. The switch is not asked here. */
export const readyTracks = (s: FakeState): FakeTrack[] => s.tracks.filter((t) => t.in_playlists && !t.hidden && t.upgrade
  && sameTrackReasonOf(s, t) === null && !t.upgrade.auto_refused);

/** Makes `n` more tracks of the playlists wait with a lossless version of the same edit (a scenario's Upgrade ready
 *  rows), lossy files first; every other one is an MP3 (Same track makes it a new AIFF). A lossless track is turned into
 *  the lossy file it would have had. `skip` leaves tracks out. */
export function seedUpgrades(s: FakeState, n: number, skip: readonly string[] = []): FakeTrack[] {
  // the library's generated tracks only (t7 on): the named fixture tracks and the ones with a service page of their own stay as they are
  const pool = s.tracks.filter((t) => /^t([7-9]|\d\d+)$/.test(t.track_id) && t.in_playlists && !t.upgrade && !t.hidden
    && !t.rekordbox_check && !t.away && !t.other && !t.own && !skip.includes(t.track_id) && qualityOf(t) !== 'missing'
    && qualityOf(t) !== 'fake');
  const picked = [...pool.filter((t) => qualityOf(t) !== 'lossless'), ...pool.filter((t) => qualityOf(t) === 'lossless')].slice(0, n);
  picked.forEach((t, i) => {
    if (qualityOf(t) === 'lossless') Object.assign(t, { status: 'not_lossless', source: 'youtube_music', cutoff_hz: 20000, codec: 'aac', kbps: 128 });
    if (i % 2) Object.assign(t, { codec: 'mp3', kbps: 320 });
    t.upgrade = makeUpgrade(t, 'exact', dateOnly(s.now), i % 2 === 0);
  });
  return picked;
}
/** The sync met rekordbox open for this upgrade (`auto_waits`). */
export function markWaiting(t: FakeTrack): void { if (t.upgrade) t.upgrade.auto_waits = true; }
/** The phase refused this upgrade and recorded why (`auto_refused`, with the engine's words). */
export function markRefused(s: FakeState, t: FakeTrack, reason: AutoRefused['reason']): void {
  if (t.upgrade) t.upgrade.auto_refused = { reason, message: AUTO_REFUSED_WORDS[reason], at: isoLocal(s.now) };
}

// ---------- the sync's last phase ----------
/** auto_upgrade.WAITS: the waiting rows of the results, by the reason the track did not run. */
export const AUTO_WAITS_WORDS = {
  rekordbox_open: 'Waits for rekordbox to be closed: it is upgraded at your next sync, or press Upgrade all.',
  not_reached: 'The sync stopped before this one; it is upgraded at your next sync.',
  busy: 'Another Discjockey window or the Terminal was changing your rekordbox library; it is upgraded at your next sync.',
} as const;
export const AUTO_DONE_NOTE = 'Your track keeps its cues, playlists and history';
const CHANGED_WORDS = 'Your rekordbox track changed while Discjockey was working on it, so nothing was changed. Try again.';
/** auto_upgrade.waiting_line: what the phase says when it meets rekordbox open at the end of a sync. */
export const autoWaitingLine = (n: number): string => `${n} upgrade${n === 1 ? ' waits' : 's wait'} for rekordbox to be closed.`;
export const autoUpgradingLine = (n: number): string => `Upgrading ${n} track${n === 1 ? '' : 's'} at the end of the sync...`;
const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

/** report.auto_upgrade_line: the run's one-line account of its phase; null when nothing happened. */
export function autoLine(block: Pick<AutoUpgradeBlock, 'done' | 'refused' | 'results'>): string | null {
  const m = block.results.filter((r) => r.state === 'waiting' && r.reason === 'rekordbox_open').length;
  const j = block.results.filter((r) => r.state === 'waiting' && r.reason !== 'rekordbox_open').length;
  const n = block.done, k = block.refused;
  if (!(n || m || j || k)) return null;
  if (n) {
    const out = [`Upgraded ${plural(n, 'track', 'tracks')}; your cues stayed.`];
    if (m) out.push(`${m} ${m === 1 ? 'waits' : 'wait'} for rekordbox to be closed.`);
    if (j) out.push(`${j} ${j === 1 ? 'waits' : 'wait'} for your next sync.`);
    if (k) out.push(`${k} couldn't go in; To-do says why.`);
    return out.join(' ');
  }
  const out: string[] = [];
  if (m) out.push(`${plural(m, 'upgrade waits', 'upgrades wait')} for rekordbox to be closed.`);
  if (j) out.push(`${plural(j, 'upgrade waits', 'upgrades wait')} for your next sync.`);
  if (k) out.push(`${plural(k, 'upgrade', 'upgrades')} couldn't go in; To-do says why.`);
  return out.join(' ');
}

/** What the phase will do, worked out when the sync starts: `order` the tracks the batch takes (To-do's order; empty when
 *  rekordbox is open at the start: no batch), `rows` every track's end state. Hooks: `s.rekordbox_running` (open at the
 *  start: all wait), `s.autoOpensAfter` (rekordbox opens after that many tracks of the batch: the rest wait),
 *  `s.batchSkip` (a track's full check refuses it with that reason). */
export type PhasePlan = { batch: number | null; order: string[]; rows: AutoUpgradeResult[] };
export function planPhase(s: FakeState, batchId: number): PhasePlan | null {
  if (!autoOn(s)) return null;
  const set = readyTracks(s);
  const row = (t: FakeTrack, state: AutoUpgradeResult['state'], reason: string | null, message: string | null): AutoUpgradeResult =>
    ({ track: t.track_id, name: `${t.artist} \u2013 ${t.title}`, state, reason, message, how: t.upgrade!.swap_how });
  const waits = (t: FakeTrack) => row(t, 'waiting', 'rekordbox_open', AUTO_WAITS_WORDS.rekordbox_open);
  if (!set.length) return { batch: null, order: [], rows: [] };
  if (s.rekordbox_running) return { batch: null, order: [], rows: set.map(waits) };
  const opens = s.autoOpensAfter ?? Infinity;
  const rows = set.map((t, i) => {
    if (i >= opens) return waits(t);
    const late = s.batchSkip?.[t.track_id];
    if (late) return row(t, 'refused', late, (AUTO_REFUSED_WORDS as Record<string, string>)[late] ?? CHANGED_WORDS);
    // the second done track had its title edited in rekordbox, which Same track keeps (convert.kept_note)
    return row(t, 'done', null, i === 1 ? `${AUTO_DONE_NOTE}. Kept your own title in rekordbox.` : AUTO_DONE_NOTE);
  });
  return { batch: batchId, order: set.map((t) => t.track_id), rows };
}

/** The events of the phase, to go in before the run's RunFinished: the waiting line (no batch), or the batch's
 *  "Upgrading n tracks…" and one BatchProgress per track it reaches (and the closing one when it got through them all). */
export function phaseEvents(plan: PhasePlan): HubEvent[] {
  const message = (text: string): HubEvent => ({ type: 'Message', level: 'info', text });
  if (plan.batch === null) return plan.rows.length ? [message(autoWaitingLine(plan.rows.length))] : [];
  const n = plan.order.length;
  const stopsAt = plan.rows.findIndex((r) => r.reason === 'rekordbox_open');
  const reached = stopsAt < 0 ? n : stopsAt;
  const out: HubEvent[] = [message(autoUpgradingLine(n))];
  for (let i = 0; i < reached; i++) {
    out.push({ type: 'BatchProgress', batch_id: plan.batch, done: i, total: n, track_id: plan.rows[i].track, name: plan.rows[i].name });
  }
  if (reached === n) out.push({ type: 'BatchProgress', batch_id: plan.batch, done: n, total: n, track_id: null, name: null });
  return out;
}
/** The recorded stream with the phase before its (last) RunFinished; `at` is the 0-based index of the phase's first event. */
export function withPhase(base: HubEvent[], phase: HubEvent[]): { events: HubEvent[]; at: number } {
  let at = base.length;
  for (let i = base.length - 1; i >= 0; i--) if (base[i].type === 'RunFinished') { at = i; break; }
  return { events: [...base.slice(0, at), ...phase, ...base.slice(at)], at };
}

/** A Stop that reached the phase after `handled` tracks of the batch (the one in work finishes): the rest were not reached
 *  (so rekordbox opening later in the batch never happens either). */
export function stopRows(plan: PhasePlan, handled: number): AutoUpgradeResult[] {
  return plan.rows.map((r, i) => (i < handled ? r
    : { ...r, state: 'waiting', reason: 'not_reached', message: AUTO_WAITS_WORDS.not_reached }));
}

/** The run's block (the report's `.json` key `auto_upgrade`, with `line`). `backup` is the id of the copy of rekordbox's library. */
export function autoBlock(plan: PhasePlan, rows: AutoUpgradeResult[], stopped: boolean, backup: string | null): NonNullable<RunSummary['auto_upgrade']> {
  const count = (state: AutoUpgradeResult['state']) => rows.filter((r) => r.state === state).length;
  const block: AutoUpgradeBlock = { batch: plan.batch, backup: plan.batch === null ? null : backup, done: count('done'),
    waiting: count('waiting'), refused: count('refused'), failed: count('failed'), stopped, dry_run: false, results: rows };
  return { ...block, line: autoLine(block) };
}

/** The run's rows for the phase, after the batch's changes were made: `upgraded` for a done track (its new file), the
 *  rest `upgrade_waits` (waiting and refused ones). Looks the tracks up by id. */
export function phaseResults(rows: AutoUpgradeResult[], track: (id: string) => FakeTrack | undefined): Result[] {
  return rows.flatMap((r) => {
    const t = track(r.track);
    if (!t) return [];
    if (r.state === 'done') {
      return [result('upgraded', t, r.message ?? '', { status: 'lossless', source: t.source, path: pathOf(t) })];
    }
    return [result('upgrade_waits', t, r.message ?? '')];
  });
}
/** The id of rekordbox's library copy the phase made before the batch (`2026-11-09T21-04-11Z`). */
export const backupId = (d: Date): string => d.toISOString().slice(0, 19).replace(/:/g, '-') + 'Z';

/** An earlier sync of the library that upgraded three lossless tracks at its end (a run in the reports with the phase's
 *  block, "Upgraded 3 tracks; your cues stayed."), `daysBack` days ago. Those tracks are lossless now. */
export function addPastAutoRun(s: FakeState, daysBack = 2): void {
  const tracks = s.tracks.filter((t) => t.in_playlists && !t.upgrade && !t.rekordbox_check && !t.away && qualityOf(t) === 'lossless').slice(0, 3);
  const rows: AutoUpgradeResult[] = tracks.map((t, i) => ({ track: t.track_id, name: `${t.artist} \u2013 ${t.title}`, state: 'done',
    reason: null, message: AUTO_DONE_NOTE, how: i % 2 ? 'new_aiff' : 'in_place' }));
  const started = new Date(s.now);
  started.setDate(started.getDate() - daysBack);
  started.setHours(21, 32, 0, 0);
  const plan: PhasePlan = { batch: 3, order: tracks.map((t) => t.track_id), rows };
  const run = runDetail(runId(started), started, 540, 0, phaseResults(rows, (id) => tracks.find((t) => t.track_id === id)), null,
    s.tracks.filter((t) => t.upgrade).length, autoBlock(plan, rows, false, backupId(started)));
  s.runs = [...s.runs, run].sort((a, b) => (a.started < b.started ? 1 : -1));
}
