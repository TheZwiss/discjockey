import { describe, expect, it } from 'vitest';
import type { LimitCard, ServiceUsage, Signal } from '$lib/bridge/types';
import { createFakeBridge } from '$lib/bridge/fake/bridge';
import {
  HONEST_NOTE, SIGNAL_ORDER, backlog, clearsText, compareDays, compareRun, defaultService, extraOptions, footerLabels,
  isChanged, isService, lastDownload, riskOf, serviceStatus, suggestion, todayLine, verdict, warningRows, zoneIndex,
} from './limitsModel';

const ZONES = [{ name: 'careful', from: 1, to: 40 }, { name: 'normal', from: 41, to: 60 },
  { name: 'faster', from: 61, to: 79 }, { name: 'fast', from: 80, to: 100 }, { name: 'risky', from: 101, to: 500 }];
const sig = (kind: Signal['kind'], time: string, over: Partial<Signal> = {}): Signal =>
  ({ time, kind, message: `${kind} message`, new: true, clears_in: 12, ...over });

async function usage(service: 'qobuz' | 'youtube' = 'qobuz', scenario = 'normal'): Promise<ServiceUsage> {
  const r = await createFakeBridge(scenario).limits(service);
  if (!r.ok || !r.usage) throw new Error('fake failed');
  return r.usage;
}

describe('zones and risk', () => {
  it('finds the zone and its risk tone', () => {
    expect([40, 41, 79, 100, 101, 1].map((v) => zoneIndex(v, ZONES))).toEqual([0, 1, 2, 3, 4, 0]);
    expect([40, 60, 61, 100, 101].map((v) => riskOf(v, ZONES))).toEqual(['safe', 'safe', 'notice', 'notice', 'high']);
  });
  it('has a plain verdict per level', () => {
    expect(verdict(2).title).toBe('The recommended pace');
    expect(verdict(4).title).toBe('Faster, but easier to notice');
    expect(verdict(9).title).toBe(verdict(5).title);
  });
});

describe('what a new limit does', () => {
  it('compares days and the run, green when better', () => {
    expect(compareDays(2, 3)).toEqual({ value: '2', unit: 'days', was: 'instead of 3 days', better: true });
    expect(compareDays(1, 1)).toEqual({ value: '1', unit: 'day', was: null, better: false });
    expect(compareRun(16, 11).better).toBe(false);
    expect(compareRun(16, 11).was).toMatch(/^instead of /);
  });
  it('labels Back and Save; both stay, off until something changed', () => {
    const saved = { limit: 60, extra_today: 0 };
    expect(isChanged({ limit: 60, extra: 0 }, saved)).toBe(false);
    expect(footerLabels({ limit: 60, extra: 0 }, saved)).toEqual({ back: 'Undo', save: 'Save' });
    expect(footerLabels({ limit: 90, extra: 0 }, saved)).toEqual({ back: 'Back to 60', save: 'Save 90 a day' });
    expect(footerLabels({ limit: 60, extra: 10 }, saved)).toEqual({ back: 'Undo', save: 'Save +10 for today' });
  });
  it('offers fixed extra amounts and keeps an amount set elsewhere', () => {
    expect(extraOptions(0, 200).map((o) => o.label)).toEqual(['None', '+5', '+10', '+20', '+40']);
    expect(extraOptions(15, 200).map((o) => o.key)).toEqual(['0', '5', '10', '15', '20', '40']);
    expect(extraOptions(0, 10).map((o) => o.key)).toEqual(['0', '5', '10']);
  });
});

describe('today and the backlog', () => {
  it('says where today comes from', async () => {
    const u = await usage();
    expect(todayLine(u)).toBe('60 + 20 carried over');
    expect(todayLine({ ...u, today: { ...u.today, carry_over: 0, extra: 10 } })).toBe('60 + 10 extra');
    expect(todayLine({ ...u, today: { ...u.today, carry_over: 0, extra: 0 } })).toBe('60 a day');
    expect(lastDownload(u, new Date())).toMatch(/^last download \d\d:\d\d$/);
    expect(lastDownload({ ...u, last_download: null })).toBeNull();
  });
  it('answers when the backlog is done', async () => {
    const u = await usage();
    expect(backlog({ ...u, still_to_load: { count: 15, days: 1, fits_today: true } }))
      .toEqual({ value: '15', unit: 'tracks', line: 'done today', done: true });
    expect(backlog({ ...u, still_to_load: { count: 120, days: 3, fits_today: false } }).line).toBe('about 3 days at 60 a day');
    expect(backlog({ ...u, behind: 'Qobuz' }).line).toBe('Qobuz sets the pace');
    expect(backlog({ ...u, still_to_load: { count: 0, days: 0, fits_today: true } }).done).toBe(true);
  });
});

const card = (over: Partial<LimitCard>): LimitCard => ({ service: 'youtube', name: 'YouTube Premium', set_up: true,
  used: 3, allowance: 30, warnings: 0, new_warnings: 0, paused: false, ...over });

describe('cards', () => {
  it('say how each service is doing, colour plus shape', () => {
    expect(serviceStatus(card({}))).toEqual({ tone: 'good', text: 'All good' });
    expect(serviceStatus(card({ warnings: 3, new_warnings: 1 }))).toEqual({ tone: 'warn', text: '1 new warning' });
    expect(serviceStatus(card({ warnings: 3 }))).toEqual({ tone: 'good', text: 'All good · 3 seen' });
    expect(serviceStatus(card({ warnings: 4, new_warnings: 4, paused: true }))).toEqual({ tone: 'problem', text: 'Paused today' });
    expect(serviceStatus(card({ set_up: false }))).toBeNull();
  });
  it('open the first service that is set up', () => {
    expect(defaultService([card({ service: 'qobuz', set_up: false }), card({}), card({ service: 'soundcloud' })]))
      .toBe('youtube');
    expect(defaultService([card({ service: 'qobuz', set_up: false })])).toBe('qobuz');
    expect(isService('soundcloud')).toBe(true);
    expect(isService('tidal')).toBe(false);
  });
});

describe('warning signs', () => {
  it('lists what happened first, newest first, then the quiet checks', () => {
    const rows = warningRows('qobuz', [
      sig('search_failed', '2026-10-18T22:12:00', { new: false, clears_in: 11 }),
      sig('download_rejected', '2026-10-19T21:53:00', { clears_in: 13 }),
      sig('download_rejected', '2026-10-19T21:54:00', { message: 'Qobuz refused “The Weekend”', clears_in: 13 })]);
    expect(rows.map((r) => r.kind)).toEqual(['download_rejected', 'search_failed', 'login_failed', 'preview_only',
      'duration_mismatch', 'auto_stop']);
    expect(rows[0]).toMatchObject({ ok: false, title: 'Download refused', count: 2, isNew: true, clearsIn: 13 });
    expect(rows[0].ok === false && rows[0].latest).toMatch(/21:54 · Qobuz refused “The Weekend”$/);
    expect(rows[1]).toMatchObject({ isNew: false, clearsIn: 11 });
    expect(rows[2]).toEqual({ kind: 'login_failed', ok: true, title: 'Login always worked' });
    expect(SIGNAL_ORDER.soundcloud).not.toContain('bot_check');
    expect([clearsText(1), clearsText(9)]).toEqual(['clears tomorrow', 'clears in 9 days']);
  });
  it('suggests a slower limit only for new pace signs of this week above careful', async () => {
    const u = await usage();
    const at = (signals: Signal[]) => ({ ...u, signals });
    const refused = [sig('download_rejected', '2026-10-19T21:53:00'), sig('download_rejected', '2026-10-19T21:54:00'),
      sig('search_failed', '2026-10-18T22:12:00')];
    expect(suggestion(at(refused), 60)).toEqual({ text: 'Qobuz refused 2 downloads this week.', limit: 40 });
    expect(suggestion(at(refused), 40)).toBeNull();                                   // already careful
    expect(suggestion(at(refused.map((g) => ({ ...g, new: false }))), 60)).toBeNull();  // seen
    expect(suggestion(at(refused.map((g) => ({ ...g, clears_in: 5 }))), 60)).toBeNull(); // older than a week
    expect(suggestion(at([sig('login_failed', '2026-10-19T21:00:00'), sig('login_failed', '2026-10-19T21:01:00')]), 60))
      .toBeNull();                                                                   // an account problem
    expect(suggestion(at([sig('search_failed', '2026-10-18T22:12:00')]), 60)).toBeNull();  // one sign is noise
    const yt = await usage('youtube', 'limits:youtube-paused');
    expect(suggestion(yt, 30)?.limit).toBe(20);
  });
  it('has an honest note for every service', () => {
    expect(HONEST_NOTE.youtube).toMatch(/Google account/);
    expect(Object.keys(HONEST_NOTE)).toEqual(['qobuz', 'youtube', 'soundcloud']);
  });
});
