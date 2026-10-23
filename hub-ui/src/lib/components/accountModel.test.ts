import { describe, expect, it } from 'vitest';
import type { DownloadsAccount, DownloadsView, FindLogins, JobSnap, LoginBrowser } from '../bridge/types';
import { WRITE_BLOCKED } from '../copy';
import {
  accountBlocked, accountPhase, browserLabel, browserMenu, checkPhase, checkedBefore, checkedWhen, chromiumHint,
  compactLine, dismissable, firstFound, foundText, gainCaption, gainLine, isWorking, mainAction, noneText, orList, panelLine,
  pickedPhase, qobuzPasswordSteps, qobuzPhase, qobuzShare, signInHint, stateLine, takeSecret, unreadableText,
  waitingText, QOBUZ_PASSWORD_URL, RISK_NOTE, type Offer,
} from './accountModel';

const NOW = new Date(2026, 9, 22, 12, 0);
const TODAY = { ok: true, problem: null, kbps: 256, at: '2026-10-22T09:00:00' };
const acc = (over: Partial<DownloadsAccount> = {}): DownloadsAccount => ({ state: 'off', browser: null,
  browser_name: null, profile: null, profile_name: null, last_check: null, tracks: 0, ...over });
const view = (over: Partial<DownloadsView> = {}): DownloadsView => ({
  qobuz: { state: 'on', last_check: { ok: true, problem: null, kbps: null, at: '2026-10-22T09:15:00' }, tracks: 412 },
  youtube: acc(), soundcloud: acc(), library: { lossless: 412, account: 0, free: 31 }, ...over });
const chrome = (profiles: LoginBrowser['profiles'], def = true): LoginBrowser => ({ id: 'chrome', name: 'Chrome',
  default: def, readable: true, problem: null, profiles });
const safari = (def = false): LoginBrowser => ({ id: 'safari', name: 'Safari', default: def, readable: false,
  problem: 'no_access', profiles: [{ id: null, name: 'Safari', signed_in: false }] });
const firefox = (signed = false): LoginBrowser => ({ id: 'firefox', name: 'Firefox', default: false, readable: true,
  problem: null, profiles: [{ id: 'abc.default', name: 'default', signed_in: signed }] });
const fl = (...browsers: LoginBrowser[]): FindLogins => ({ browsers });
const snap = (kind: string, running = true): JobSnap => ({ id: 1, kind, track_id: null, started: '', running,
  stopping: false, last: {}, results: [], finished: null, actions: [] });

describe('first offer from find_logins', () => {
  it('prefers the default browser and its first signed-in profile', () => {
    const f = fl(firefox(true), chrome([{ id: 'Default', name: 'Person 1', signed_in: false },
      { id: 'Profile 2', name: 'DJ', signed_in: true }]));
    expect(firstFound(f)).toEqual({ kind: 'found', browser: 'chrome', browserName: 'Chrome', profile: 'Profile 2',
      profileName: 'DJ' });
  });
  it('names the profile only when the browser has several', () => {
    expect(firstFound(fl(chrome([{ id: 'Default', name: 'Person 1', signed_in: false }]), firefox(true)))).toEqual(
      { kind: 'found', browser: 'firefox', browserName: 'Firefox', profile: 'abc.default', profileName: null });
  });
  it('none found offers the default browser, with the browsers it looked in', () => {
    const f = fl(safari(), chrome([{ id: 'Default', name: 'Person 1', signed_in: false }]), firefox());
    expect(firstFound(f)).toEqual({ kind: 'none', browser: 'chrome', browserName: 'Chrome', profile: null,
      profileName: null, searched: ['Chrome', 'Firefox'] });
  });
  it('never offers a browser macOS keeps closed; Safari alone says why', () => {
    expect(firstFound(fl(safari(true), firefox()))).toMatchObject({ kind: 'none', browser: 'firefox' });
    expect(firstFound(fl(safari(true)))).toEqual({ kind: 'unreadable', browser: 'safari', browserName: 'Safari', profile: null });
  });
  it('no browsers installed', () => {
    expect(firstFound(fl())).toEqual({ kind: 'none', browser: null, browserName: null, profile: null, profileName: null,
      searched: [] });
  });
});

describe('the panel phase', () => {
  const logins = fl(chrome([{ id: 'Default', name: 'Person 1', signed_in: true }]));
  it('a running flow wins over everything', () => {
    expect(accountPhase(acc({ state: 'on' }), logins, null, { kind: 'checking', browserName: 'Chrome' }))
      .toEqual({ kind: 'checking', browserName: 'Chrome' });
  });
  it('a saved account shows its state', () => {
    expect(accountPhase(acc({ state: 'on' }), null, null, null)).toEqual({ kind: 'working' });
    expect(accountPhase(acc({ state: 'paused' }), null, null, null)).toEqual({ kind: 'working' });
    expect(accountPhase(acc({ state: 'used_up' }), null, null, null)).toEqual({ kind: 'working' });
    expect(accountPhase(acc({ state: 'no_premium' }), null, null, null)).toEqual({ kind: 'no_premium' });
    expect(accountPhase(acc({ state: 'unreadable', browser: 'safari', browser_name: 'Safari' }), null, null, null))
      .toEqual({ kind: 'unreadable', browser: 'safari', browserName: 'Safari', profile: null });
  });
  it('looking until both answers are there, then the offer; a failed look is an error', () => {
    expect(accountPhase(null, logins, null, null)).toEqual({ kind: 'looking' });
    expect(accountPhase(acc(), null, null, null)).toEqual({ kind: 'looking' });
    expect(accountPhase(acc(), null, 'The engine is not answering.', null)).toEqual(
      { kind: 'error', message: 'The engine is not answering.' });
    expect(accountPhase(acc(), logins, null, null)).toMatchObject({ kind: 'found', browser: 'chrome' });
    // a lost login (saved browser, state off) is offered a sign-in again
    expect(accountPhase(acc({ browser: 'chrome', browser_name: 'Chrome' }), logins, null, null).kind).toBe('found');
  });
  it('Qobuz: signed in works, everything else is the form', () => {
    expect(qobuzPhase(null, null)).toEqual({ kind: 'looking' });
    expect(qobuzPhase(view().qobuz, null)).toEqual({ kind: 'working' });
    expect(qobuzPhase({ state: 'skipped', last_check: null, tracks: 0 }, null)).toEqual({ kind: 'form' });
    expect(qobuzPhase(view().qobuz, { kind: 'form', editing: true })).toEqual({ kind: 'form', editing: true });
  });
});

describe('main action', () => {
  const found: Offer = { kind: 'found', browser: 'chrome', browserName: 'Chrome', profile: null, profileName: null };
  const none: Offer = { kind: 'none', browser: 'chrome', browserName: 'Chrome', profile: null, profileName: null, searched: ['Chrome'] };
  it('one per phase that needs the user', () => {
    expect(mainAction(found)).toEqual({ kind: 'use', label: 'Use this login' });
    expect(mainAction(none)).toEqual({ kind: 'sign-in', label: 'Sign in' });
    expect(mainAction({ ...none, browser: null, browserName: null })).toEqual({ kind: 'look-again', label: 'Look again' });
    expect(mainAction({ kind: 'unreadable', browser: 'safari', browserName: 'Safari', profile: null }))
      .toEqual({ kind: 'privacy', label: 'Open System Settings' });
    expect(mainAction({ kind: 'unreadable', browser: 'chrome', browserName: 'Chrome', profile: null })?.kind).toBe('use');
    expect(mainAction({ kind: 'result', message: 'x', tone: 'problem', retry: none })?.kind).toBe('sign-in');
    // the login answered without Premium/Go+: the same login is checked again, a failed one is used again
    expect(mainAction({ kind: 'result', message: 'x', tone: 'warn', retry: found }))
      .toEqual({ kind: 'use', label: 'Check again' });
    expect(mainAction({ kind: 'result', message: 'x', tone: 'problem', retry: found }))
      .toEqual({ kind: 'use', label: 'Use this login' });
    expect(mainAction({ kind: 'result', message: 'x', tone: 'warn', retry: none })?.label).toBe('Sign in');
    expect(mainAction({ kind: 'form' })).toEqual({ kind: 'qobuz-sign-in', label: 'Sign in' });
    expect(mainAction({ kind: 'error', message: 'x' })).toEqual({ kind: 'look-again', label: 'Try again' });
  });
  it('nothing while it works, waits or checks', () => {
    for (const k of ['working', 'no_premium', 'looking'] as const) expect(mainAction({ kind: k })).toBeNull();
    expect(mainAction({ kind: 'waiting', browser: 'chrome', browserName: 'Chrome' })).toBeNull();
    expect(mainAction({ kind: 'checking', browserName: null })).toBeNull();
  });
  it('a finished check: works → the state says it; no Premium warns; Safari refused → unreadable', () => {
    expect(checkPhase({ ok: true, problem: null, kbps: 256, message: 'ok' }, found)).toBeNull();
    expect(checkPhase({ ok: false, problem: 'no_premium', kbps: 160, message: 'No Premium.' }, found)).toEqual(
      { kind: 'result', message: 'No Premium.', tone: 'warn', retry: found });
    expect(checkPhase({ ok: false, problem: 'not_logged_in', kbps: null, message: 'Not signed in.' }, found))
      .toMatchObject({ tone: 'problem' });
    expect(checkPhase({ ok: false, problem: 'cookies_unreadable', kbps: null, message: 'FDA' },
      { ...found, browser: 'safari', browserName: 'Safari' })).toEqual(
      { kind: 'unreadable', browser: 'safari', browserName: 'Safari', profile: null, picked: undefined });
  });
});

describe('a result with nothing to try again', () => {
  const offer: Offer = { kind: 'found', browser: 'chrome', browserName: 'Chrome', profile: null, profileName: null };
  it('gets an OK (a failed sign-out); a result with a retry or the Qobuz form does not', () => {
    expect(dismissable({ kind: 'result', message: 'x', tone: 'problem', retry: null })).toBe(true);
    expect(dismissable({ kind: 'result', message: 'x', tone: 'problem', retry: offer })).toBe(false);
    expect(dismissable({ kind: 'result', message: 'x', tone: 'problem', retry: { kind: 'form' } })).toBe(false);
    expect(dismissable({ kind: 'working' })).toBe(false);
  });
});

describe('state line (shared with Settings rows)', () => {
  it('a working account: the row in one line, the panel as headline and sub-line', () => {
    const d = view({ youtube: acc({ state: 'on', browser: 'chrome', browser_name: 'Chrome', profile: 'Profile 2',
      profile_name: 'DJ', last_check: TODAY }) });
    expect(stateLine('youtube', d, NOW)).toEqual({ tone: 'good', text: 'via Chrome (DJ) · 256 kbps · checked today' });
    expect(panelLine('youtube', d, NOW)).toEqual({ tone: 'good', title: 'Signed in via Chrome (DJ)',
      sub: '256 kbps · checked today' });
  });
  it('no Premium, Go+ not confirmed, unreadable, lost, not set up', () => {
    const np = view({ youtube: acc({ state: 'no_premium', browser: 'chrome', browser_name: 'Chrome',
      last_check: { ok: false, problem: 'no_premium', kbps: 160, at: '2026-10-21T10:00:00' } }) });
    expect(panelLine('youtube', np, NOW)).toEqual({ tone: 'warn', title: 'Signed in, but no Premium',
      sub: 'YouTube gives this account 160 kbps · checked 21 Oct' });
    expect(stateLine('soundcloud', view({ soundcloud: acc({ state: 'no_premium' }) }), NOW)).toEqual(
      { tone: 'warn', text: 'signed in · Go+ not confirmed' });
    expect(panelLine('youtube', view({ youtube: acc({ state: 'unreadable', browser: 'safari', browser_name: 'Safari' }) }), NOW))
      .toEqual({ tone: 'problem', title: "Can't read the login in Safari", sub: null });
    expect(panelLine('youtube', view({ youtube: acc({ browser: 'chrome', browser_name: 'Chrome' }) }), NOW).title)
      .toBe('Not signed in any more in Chrome');
    expect(panelLine('soundcloud', view(), NOW)).toEqual({ tone: 'none', title: 'Not set up yet', sub: null });
    expect(panelLine('youtube', view({ youtube: acc({ state: 'paused', browser: 'chrome', browser_name: 'Chrome' }) }), NOW))
      .toEqual({ tone: 'warn', title: 'Paused today', sub: 'Signed in via Chrome' });
  });
  it('Qobuz: signed in, rejected, left out', () => {
    expect(panelLine('qobuz', view(), NOW)).toEqual({ tone: 'good', title: 'Signed in', sub: 'checked today' });
    const rejected = view({ qobuz: { state: 'off', tracks: 0, last_check: { ok: false, problem: 'login_failed',
      kbps: null, at: '2026-10-22T09:00:00' } } });
    expect(panelLine('qobuz', rejected, NOW).title).toBe("Qobuz didn't accept the login");
    expect(stateLine('qobuz', view({ qobuz: { state: 'skipped', last_check: null, tracks: 0 } }), NOW)).toEqual(
      { tone: 'none', text: 'left out' });
  });
  it('Setup\'s compact head: the state, or what the login gives', () => {
    expect(compactLine('youtube', view(), NOW)).toEqual({ tone: 'none', text: 'about 256 kbps instead of 130' });
    expect(compactLine('qobuz', view({ qobuz: { state: 'off', last_check: null, tracks: 0 } }), NOW)).toEqual(
      { tone: 'none', text: 'lossless for most songs' });
    expect(compactLine('qobuz', view(), NOW)).toEqual({ tone: 'good', text: 'signed in · checked today' });
    expect(isWorking('qobuz', view())).toBe(true);
    expect(isWorking('youtube', view())).toBe(false);
  });
  it('checked when', () => {
    expect(checkedWhen(null, NOW)).toBe('');
    expect(checkedWhen({ ok: true, problem: null, kbps: null, at: '2026-10-20T23:59:00' }, NOW)).toBe('checked 20 Oct');
  });
});

describe('what it gives', () => {
  it('uses the library numbers; no line at 0', () => {
    const d = view({ qobuz: { state: 'on', last_check: null, tracks: 10 } });
    expect(gainLine('youtube', d)).toBe('31 of your tracks came from free streams at about 130 kbps.');
    expect(gainLine('soundcloud', view({ library: { lossless: 10, account: 0, free: 0 } }))).toBeNull();
    expect(gainLine('qobuz', d)).toBe('10 of your tracks came from Qobuz.');
    expect(gainLine('qobuz', view({ qobuz: { state: 'off', last_check: null, tracks: 0 } }))).toBeNull();
    expect(gainCaption('youtube')).toBe('with Premium · about 130 without');
    expect(gainCaption('soundcloud')).toBe('with Go+ · about 130 without');
  });
  it('Qobuz\'s share of the library', () => {
    expect(qobuzShare(view())).toEqual({ tracks: 412, total: 443, share: 412 / 443 });
    expect(qobuzShare(view({ library: { lossless: 0, account: 0, free: 0 } })).share).toBeNull();
  });
});

describe('Chromium hint', () => {
  it('names the browser\'s Safe Storage until it was checked once', () => {
    expect(chromiumHint('chrome', false)).toBe('macOS will ask about “Chrome Safe Storage” once. Click Always Allow.');
    expect(chromiumHint('brave', false)).toBe('macOS will ask about “Brave Safe Storage” once. Click Always Allow.');
    expect(chromiumHint('edge', false)).toContain('Microsoft Edge Safe Storage');
    expect(chromiumHint('chrome', true)).toBeNull();
    expect(chromiumHint('firefox', false)).toBeNull();
    expect(chromiumHint('safari', false)).toBeNull();
    expect(chromiumHint(null, false)).toBeNull();
  });
  it('checked before: any saved account with that browser and a check', () => {
    const d = view({ soundcloud: acc({ state: 'on', browser: 'chrome', browser_name: 'Chrome', last_check: TODAY }) });
    expect(checkedBefore('chrome', d)).toBe(true);
    expect(checkedBefore('brave', d)).toBe(false);
    expect(checkedBefore('chrome', view({ youtube: acc({ browser: 'chrome' }) }))).toBe(false);
    expect(checkedBefore('chrome', null)).toBe(false);
  });
});

describe('Use another browser', () => {
  const f = fl(firefox(true), safari(), chrome([{ id: 'Default', name: 'Person 1', signed_in: false },
    { id: 'Profile 2', name: 'Work', signed_in: true }]));
  it('every browser × profile, default first, marked, unique keys', () => {
    const m = browserMenu(f);
    expect(m.map((c) => [c.label, c.note])).toEqual([
      ['Chrome · Person 1', 'default browser'], ['Chrome · Work', 'signed in'], ['Firefox', 'signed in'],
      ['Safari', 'needs Full Disk Access']]);
    expect(new Set(m.map((c) => c.key)).size).toBe(m.length);
    expect(m.find((c) => c.label === 'Firefox')?.profileName).toBeNull();
    expect(browserMenu(null)).toEqual([]);
  });
  it('a browser without profiles still gets one line; two profiles of the same name keep apart', () => {
    const twins = chrome([{ id: 'A', name: 'Person 1', signed_in: false }, { id: 'B', name: 'Person 1', signed_in: false }]);
    const m = browserMenu(fl({ ...safari(), profiles: [] }, twins));
    expect(m.map((c) => c.label)).toEqual(['Chrome · Person 1', 'Chrome · Person 1', 'Safari']);
    expect(new Set(m.map((c) => c.key)).size).toBe(3);
  });
  it('a pick becomes the offer the main action then carries out', () => {
    const [p1, work, , saf] = browserMenu(f);
    expect(pickedPhase(work)).toEqual({ kind: 'found', browser: 'chrome', browserName: 'Chrome', profile: 'Profile 2',
      profileName: 'Work', picked: true });
    expect(pickedPhase(p1)).toEqual({ kind: 'none', browser: 'chrome', browserName: 'Chrome', profile: 'Default',
      profileName: 'Person 1', searched: ['Chrome (Person 1)'], picked: true });
    expect(pickedPhase(saf)).toEqual({ kind: 'unreadable', browser: 'safari', browserName: 'Safari', profile: null, picked: true });
  });
});

describe('sentences', () => {
  it('found, none, sign-in hint, unreadable, waiting', () => {
    expect(foundText('youtube', { kind: 'found', browser: 'chrome', browserName: 'Chrome', profile: 'P2', profileName: 'DJ' }))
      .toBe('Found your YouTube login in Chrome (DJ).');
    const none = { kind: 'none' as const, browser: 'chrome' as const, browserName: 'Chrome', profile: null, profileName: null,
      searched: ['Chrome', 'Firefox', 'Brave'] };
    expect(noneText('soundcloud', none)).toBe('No SoundCloud login in Chrome, Firefox or Brave.');
    expect(noneText('youtube', { ...none, browser: null, browserName: null, searched: [] }))
      .toBe('No browser Discjockey can read is on this Mac.');
    expect(signInHint('youtube', { ...none, browser: null, browserName: null, searched: [] }, null))
      .toBe('Install Chrome or Firefox, sign in there, then look again.');
    expect(signInHint('youtube', none, 'Chrome')).toBe('Sign in opens YouTube in Chrome, your default browser.');
    expect(signInHint('youtube', { ...none, browser: 'firefox', browserName: 'Firefox' }, 'Chrome')).toBe('Sign in opens YouTube in Firefox.');
    expect(unreadableText('Safari').hint).toMatch(/Full Disk Access/);
    expect(unreadableText('Chrome').hint).toMatch(/Always Allow/);
    expect(waitingText('Chrome')).toBe('Waiting for your sign-in in Chrome…');
    expect(orList(['A'])).toBe('A');
    expect(orList(['A', 'B'])).toBe('A or B');
    expect(browserLabel('Chrome', null)).toBe('Chrome');
  });
});

describe('why the buttons are off', () => {
  it('terminal run, hub sync, another change, another sign-in', () => {
    expect(accountBlocked({ job: null, console_running: true })).toBe(WRITE_BLOCKED.console);
    expect(accountBlocked({ job: snap('sync'), console_running: false })).toBe('Wait until the sync has finished.');
    expect(accountBlocked({ job: snap('save_playlists'), console_running: false })).toBe(WRITE_BLOCKED.busy);
    expect(accountBlocked({ job: null, console_running: false, sign_in: snap('account_sign_in') }))
      .toBe('Another sign-in is waiting for the browser.');
    expect(accountBlocked({ job: snap('sync', false), console_running: false })).toBeNull();
  });
});

describe('Qobuz and secrets', () => {
  it('three password steps, Qobuz\'s page, the risk notes', () => {
    expect(qobuzPasswordSteps()).toHaveLength(3);
    expect(qobuzPasswordSteps()[2]).toContain('e-mail and password');
    expect(QOBUZ_PASSWORD_URL).toBe('https://www.qobuz.com/signin/forget-password');
    expect(RISK_NOTE.qobuz).toMatch(/Qobuz's terms/);
    expect(RISK_NOTE.youtube).toMatch(/Google account/);
  });
  it('takeSecret empties the element', () => {
    const el = { value: 'hunter2' };
    expect(takeSecret(el)).toBe('hunter2');
    expect(el.value).toBe('');
    expect(takeSecret(null)).toBe('');
  });
});
