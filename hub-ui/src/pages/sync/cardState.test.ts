import { describe, expect, it } from 'vitest';
import syncRaw from '$fixtures/hub_events_sync.jsonl?raw';
import stoppedRaw from '$fixtures/hub_events_stopped.jsonl?raw';
import type { HubEvent } from '$lib/bridge/events';
import { EMPTY_RUN, reduceRun, type RunState } from '$lib/stores/run';
import type { Budget, LimitCard, Result } from '$lib/bridge/types';
import { cardState, liveUsage, qobuzFallback, stepIndex, verdict, type Card } from './cardState';

const lines = (raw: string): HubEvent[] => raw.split('\n').filter((l) => l.trim()).map((l) => JSON.parse(l));
const sync = lines(syncRaw);
const stopped = lines(stoppedRaw);
const T = (line: number) => line * 1000;   // synthetic clock: fixture line n arrives at n seconds

/** The run state after each line (1-based) and the card at that moment. */
function walk(evs: HubEvent[], hook?: (line: number, s: RunState) => RunState) {
  let s = EMPTY_RUN;
  const out: { line: number; s: RunState; card: Card }[] = [];
  evs.forEach((e, i) => {
    const line = i + 1;
    s = reduceRun(s, e, T(line));
    if (hook) s = hook(line, s);
    out.push({ line, s, card: cardState(s, T(line)) });
  });
  return out;
}
const at = (w: ReturnType<typeof walk>, line: number) => w[line - 1];
const kinds = (w: ReturnType<typeof walk>) => w.map((x) => x.card.kind).filter((k, i, a) => k !== a[i - 1]);
function inOrder(seq: string[], want: string[]) {
  let j = 0;
  for (const k of seq) if (k === want[j]) j++;
  return j === want.length;
}

describe('cardState with the recorded sync', () => {
  const w = walk(sync);   // the refresh job (lines 1–5) is not a download job: the run store ignores it
  const L = (line: number) => at(w, line);

  it('goes through the whole sequence in order', () => {
    expect(inOrder(kinds(w), ['preparing', 'working', 'analysed', 'working', 'downloading', 'working', 'converting',
      'analysed', 'working', 'pause', 'downloading', 'working', 'converting', 'working', 'analysed', 'finished']))
      .toBe(true);
  });
  it('prepares with the last info message before RunStarted', () => {
    expect(L(7).card).toEqual({ kind: 'preparing', text: 'Reading your Spotify playlists...' });
    expect(L(8).card).toEqual({ kind: 'preparing', text: 'Reading your Spotify playlists · 1 of 2 · Hard_Bounce' });
    expect(L(9).card).toEqual({ kind: 'preparing', text: 'Reading your Spotify playlists · 2 of 2 · Powertrance' });
    expect(L(10).card).toEqual({ kind: 'preparing', text: 'Looking up the bitrate of 1 older download...' });
    expect(L(11).card.kind).toBe('preparing');
  });
  it('shows the move without steps, then its result', () => {
    const c = L(12).card;
    expect(c.kind === 'working' && c.detail).toBe('Moving to Hard_Bounce…');
    expect(c.kind === 'working' && c.steps).toEqual([]);
    const r = L(13).card;
    expect(r.kind === 'analysed' && r.result.section).toBe('moved');
    expect(r.kind === 'analysed' && verdict(r.result)).toMatchObject({ label: 'MOVED → Hard_Bounce', hasFile: false });
  });
  it('holds the analysed card 4 s, then the search with its short pause shows', () => {
    for (const line of [14, 15, 16]) expect(L(line).card.kind).toBe('analysed');
    const c = L(17).card;
    expect(c.kind).toBe('working');
    expect(c.kind === 'working' && c.step).toBe('search');
    expect(c.kind === 'working' && c.detail).toMatch(/^Short pause before searching Qobuz · \d s$/);
  });
  it('downloads with percent and MB strings', () => {
    const d = [26, 27, 28, 29].map((l) => L(l).card);
    expect(d.map((c) => c.kind === 'downloading' && c.percent)).toEqual([25, 50, 75, 100]);
    expect(d.map((c) => c.kind === 'downloading' && c.doneMB)).toEqual(['0.3', '0.7', '1.0', '1.3']);
    expect(d.every((c) => c.kind === 'downloading' && c.totalMB === '1.3' && c.source === 'qobuz')).toBe(true);
    expect(d[0].kind === 'downloading' && d[0].secondsLeft).toBeNull();   // rate unknown on the first sample
    expect(d[1].kind === 'downloading' && d[1].secondsLeft).toBe(2);
    expect(stepIndex(d[0])).toBe(1);
  });
  it('converts with the length line', () => {
    const c = L(34).card;
    expect(c).toMatchObject({ kind: 'converting', lengthLine: 'Length matches (0:12 = Spotify 0:12)', lengthOk: true,
      done_s: 12, total_s: 12 });
    expect(L(33).card).toMatchObject({ kind: 'converting', done_s: 0 });
  });
  it('shows the lossless result', () => {
    const c = L(36).card;
    expect(c.kind === 'analysed' && verdict(c.result)).toMatchObject({ label: 'LOSSLESS', hasFile: true,
      line: 'full spectrum up to 22 kHz' });
  });
  it('pauses before Get Naughty with next up = the current action', () => {
    const c = L(97).card;
    expect(c.kind).toBe('pause');
    if (c.kind !== 'pause') return;
    expect(c.waiting).toBe('between');
    expect(c.nextUp.track.title).toBe('Get Naughty');
    expect(c.afterThat).toBe(0);
    // today's usage is said once, in the run's progress card (liveUsage), not again on the pause card (§11)
    expect('usage' in c).toBe(false);
    expect(c.source).toBe('qobuz');
    expect(c.remaining_s).toBeCloseTo(34.31, 1);
  });
  it('a pause between account downloads: the progress card counts that account', () => {
    let s = L(97).s;
    s = reduceRun(s, { type: 'AccountUsage', service: 'youtube', used: 2, allowance: 30 }, T(97));
    s = reduceRun(s, { type: 'Waiting', kind: 'between', label: 'Protection pause between YouTube Premium downloads',
      remaining: 30, total: 40, service: 'youtube' }, T(97));
    expect(cardState(s, T(97)).kind).toBe('pause');
    expect(liveUsage(null, s.usage)).toContain('YouTube Premium 2 of 30 today');
  });
  it('counts the pause down with the clock, never below 0', () => {
    const s = L(97).s;
    const a = cardState(s, T(97) + 500), b = cardState(s, T(97) + 2500), z = cardState(s, T(97) + 99_000);
    expect(a.kind === 'pause' && b.kind === 'pause').toBe(true);
    if (a.kind !== 'pause' || b.kind !== 'pause') return;
    expect(a.remaining_s - b.remaining_s).toBeCloseTo(2, 5);
    expect(z.kind === 'pause' && z.remaining_s).toBe(0);
  });
  it('the progress card falls back to the dashboard Qobuz count before any AccountUsage', () => {
    expect(liveUsage({ used: 37, allowance: 80 }, {})).toEqual(['Qobuz 37 of 80 today']);
  });
  it('downloads after the pause, compares with 6 steps, then the upgrade result and the end', () => {
    expect(L(134).card.kind).toBe('downloading');
    const c = L(144).card;
    expect(c.kind === 'working' && c.step).toBe('compare');
    expect(c.kind === 'working' && c.steps).toHaveLength(6);
    expect(stepIndex(c)).toBe(5);
    const r = L(145).card;
    expect(r.kind === 'analysed' && r.result.section).toBe('upgrade_ready');
    if (r.kind === 'analysed') expect(verdict(r.result).line).toBe('a better version waits for you');
    expect(L(147).card).toEqual({ kind: 'finished', exit_code: 1 });
  });
  it('lets new download work end the analysed card early', () => {
    const s = L(36).s;   // Gimme Gimme finished at T(36)
    const next = reduceRun(reduceRun(s, sync[36], T(36) + 100), { type: 'StepChanged',
      track_id: (sync[36] as { action: { track_id: string } }).action.track_id, step: 'download' }, T(36) + 200);
    expect(cardState(next, T(36) + 300).kind).not.toBe('analysed');
  });
  it('keeps the result up while no newer action started', () => {
    expect(cardState(L(36).s, T(36) + 60_000).kind).toBe('analysed');
  });
  it('ignores a Progress of another track', () => {
    const s = L(27).s;
    const other = reduceRun(s, { type: 'Progress', track_id: 'someone-else', step: 'download', done: 9, total: 10,
      unit: 'bytes' }, T(27) + 10);
    expect(cardState(other, T(27))).toEqual(cardState(s, T(27)));
  });
});

describe('cardState when stopping or failing', () => {
  it('stops after action 3 starts, then finishes with 130', () => {
    const w = walk(stopped, (line, s) => (line === 37 ? { ...s, phase: 'stopping' } : s));   // markStopping()
    expect(at(w, 36).card.kind).toBe('analysed');
    expect(at(w, 37).card).toEqual({ kind: 'stopping' });
    expect(at(w, 38).card).toEqual({ kind: 'stopping' });
    expect(at(w, 39).card).toEqual({ kind: 'finished', exit_code: 130 });
  });
  it('fails on a JobFinished with a problem', () => {
    let s = reduceRun(EMPTY_RUN, { type: 'JobStarted', job_id: 7, kind: 'sync', track_id: null }, 0);
    s = reduceRun(s, { type: 'JobFinished', job_id: 7, kind: 'sync', ok: false, problem: 'login_expired',
      message: 'Your Spotify login has expired.', result: null }, 10);
    expect(cardState(s, 20)).toEqual({ kind: 'failed', problem: 'login_expired',
      message: 'Your Spotify login has expired.' });
  });
});

describe('the live line counts', () => {
  const budget: Budget = { used: 0, allowance: 60, limit: 60, carry_over: 0, extra: 0, remaining: 60 };
  const card = (service: LimitCard['service']): LimitCard => ({ service, name: '', set_up: true, used: 0,
    allowance: 30, warnings: 0, new_warnings: 0, paused: false });
  it("takes the dashboard's Qobuz count only when Qobuz is set up", () => {
    expect(qobuzFallback({ qobuz_today: budget, account_today: card('qobuz') })).toEqual({ used: 0, allowance: 60 });
    expect(qobuzFallback({ qobuz_today: budget, account_today: card('youtube') })).toBeNull();  // I don't have Qobuz
    expect(qobuzFallback({ qobuz_today: budget, account_today: null })).toBeNull();               // free sources only
  });
  it('lists Qobuz first, then the accounts, the run\'s own counts over the dashboard\'s', () => {
    const yt = { youtube: { used: 3, allowance: 30 } };
    expect(liveUsage(null, yt)).toEqual(['YouTube Premium 3 of 30 today']);
    expect(liveUsage({ used: 0, allowance: 60 }, yt)).toEqual(['Qobuz 0 of 60 today', 'YouTube Premium 3 of 30 today']);
    expect(liveUsage({ used: 0, allowance: 60 }, { qobuz: { used: 5, allowance: 60 } })).toEqual(['Qobuz 5 of 60 today']);
  });
});

describe('verdict of an upgrade', () => {
  const up = (source: string): Result => ({ section: 'upgrade_ready', folder: 'A', artist: 'A', title: 'x',
    track_id: 't1', note: '', status: 'not_lossless', source, cutoff_hz: null, path: 'Upgrades ready/A/x.aiff',
    error_kind: null });
  it('a Qobuz upgrade is lossless, a stream from an account is lossy', () => {
    expect(verdict(up('qobuz'))).toMatchObject({ tone: 'lossless', quality: 'lossless', label: 'UPGRADE READY' });
    expect(verdict(up('youtube_music'))).toMatchObject({ tone: 'good_lossy', quality: 'good_lossy',
      label: 'UPGRADE READY', line: 'a better version waits for you' });
    expect(verdict(up('soundcloud'))).toMatchObject({ tone: 'good_lossy', quality: 'good_lossy' });
  });
});

describe('the live card of an upgrade check that found a lossless SoundCloud original', () => {
  it('shows the lossless badge: the found file says lossless, whatever the source', () => {
    const evs = sync.map((e, i) => (i === 144 && e.type === 'ActionFinished'
      ? { ...e, result: { ...e.result, source: 'soundcloud', found_status: 'lossless' } } : e)) as HubEvent[];
    const c = at(walk(evs), 145).card;
    expect(c.kind).toBe('analysed');
    if (c.kind === 'analysed') {
      expect(verdict(c.result)).toMatchObject({ tone: 'lossless', quality: 'lossless', label: 'UPGRADE READY' });
    }
  });
  it('keeps a lossy find lossy, even from Qobuz', () => {
    const r: Result = { section: 'upgrade_ready', folder: 'A', artist: 'A', title: 'x', track_id: 't1', note: '',
      status: 'not_lossless', source: 'qobuz', cutoff_hz: null, path: 'Upgrades ready/A/x.aiff', error_kind: null,
      found_status: 'not_lossless' };
    expect(verdict(r)).toMatchObject({ tone: 'good_lossy', quality: 'good_lossy' });
  });
});
