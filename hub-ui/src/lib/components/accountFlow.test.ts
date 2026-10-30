import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { _resetBridge } from '../bridge/client';
import { dispatch } from '../bridge/events';
import type { DownloadsView } from '../bridge/types';
import { _resetJobs } from '../stores/jobs';
import { AccountFlow } from './accountFlow.svelte';
import { answerConfirm } from './confirm';
import { browserMenu, dismissable, mainAction } from './accountModel';

const LOGINS = { browsers: [
  { id: 'chrome', name: 'Chrome', default: true, readable: true, problem: null,
    profiles: [{ id: 'Default', name: 'Person 1', signed_in: false }, { id: 'Profile 2', name: 'DJ', signed_in: true }] },
  { id: 'safari', name: 'Safari', default: false, readable: false, problem: 'no_access',
    profiles: [{ id: null, name: 'Safari', signed_in: false }] },
] };
const D: DownloadsView = {
  qobuz: { state: 'off', last_check: null, tracks: 0 },
  youtube: { state: 'off', browser: null, browser_name: null, profile: null, profile_name: null, last_check: null, tracks: 0 },
  soundcloud: { state: 'off', browser: null, browser_name: null, profile: null, profile_name: null, last_check: null, tracks: 0 },
  library: { lossless: 0, account: 0, free: 31 },
};

let calls: [string, unknown[]][] = [];
let nextJob = 1;
function fakeWindow(over: Record<string, (...a: any[]) => any> = {}) {
  const job = (name: string) => async (...a: unknown[]) => { calls.push([name, a]); return { ok: true, job_id: nextJob++ }; };
  const w = new EventTarget() as any;
  w.pywebview = { api: {
    find_logins: async () => ({ ok: true, ...LOGINS }),
    job_status: async () => ({ ok: true, job: null, sign_in: null, refresh_running: false, console_running: false, read_status: null }),
    setup_account: job('setup_account'), account_sign_in: job('account_sign_in'), qobuz_check_login: job('qobuz_check_login'),
    setup_qobuz_login: job('setup_qobuz_login'), setup_skip_qobuz: job('setup_skip_qobuz'),
    setup_forget_account: job('setup_forget_account'),
    stop_sign_in: async () => { calls.push(['stop_sign_in', []]); return { ok: true, stopped: true }; },
    ...over,
  } };
  (globalThis as any).window = w;
}
const finish = (job_id: number, kind: string, extra: object = {}) => dispatch({ type: 'JobFinished', job_id, kind,
  ok: true, problem: null, message: '', result: null, ...extra } as any);
const flush = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => { _resetBridge(); _resetJobs(); calls = []; nextJob = 1; vi.spyOn(console, 'warn').mockImplementation(() => {}); });
afterEach(() => { vi.restoreAllMocks(); delete (globalThis as any).window; });

describe('AccountFlow', () => {
  it('looks for logins and offers the signed-in profile', async () => {
    fakeWindow();
    const f = new AccountFlow('youtube', () => {});
    await f.load();
    expect(f.phase(D)).toMatchObject({ kind: 'found', browser: 'chrome', profile: 'Profile 2', profileName: 'DJ' });
  });
  it('a failed look is an error the panel can retry', async () => {
    fakeWindow({ find_logins: async () => ({ ok: false, kind: 'crashed', message: 'Something went wrong. Try again.' }) });
    const f = new AccountFlow('youtube', () => {});
    await f.load();
    expect(f.phase(D)).toEqual({ kind: 'error', message: 'Something went wrong. Try again.' });
  });
  it('Use this login: checking, then the account state; onchanged after the job', async () => {
    fakeWindow();
    const changed = vi.fn();
    const f = new AccountFlow('youtube', changed);
    await f.load();
    const p = f.useLogin('chrome', 'Profile 2');
    expect(f.phase(D)).toEqual({ kind: 'checking', browserName: 'Chrome' });
    expect(f.busy).toBe(true);
    await flush();
    finish(1, 'setup_account', { result: { check: { ok: true, problem: null, kbps: 256, message: 'Works.' } } });
    await p;
    expect(calls[0]).toEqual(['setup_account', ['youtube', 'chrome', 'Profile 2']]);
    expect(f.active).toBeNull();
    expect(f.busy).toBe(false);
    expect(changed).toHaveBeenCalledOnce();
  });
  it('a login without Premium says so and offers it again', async () => {
    fakeWindow();
    const f = new AccountFlow('youtube', () => {});
    await f.load();
    const p = f.useLogin('chrome', 'Profile 2');
    await flush();
    finish(1, 'setup_account', { result: { check: { ok: false, problem: 'no_premium', kbps: 160, message: 'No Premium.' } } });
    await p;
    const ph = f.phase(D);
    expect(ph).toMatchObject({ kind: 'result', tone: 'warn', message: 'No Premium.' });
    expect(mainAction(ph)?.kind).toBe('use');
  });
  it('Sign in follows SignInPhase; a timeout shows its message with Sign in again', async () => {
    fakeWindow();
    const f = new AccountFlow('soundcloud', () => {});
    const off = f.mount();
    await flush();
    const p = f.signIn('chrome');
    expect(f.phase(D)).toEqual({ kind: 'waiting', browser: 'chrome', browserName: 'Chrome' });
    await flush();
    dispatch({ type: 'SignInPhase', service: 'youtube', phase: 'checking', browser: 'chrome', browser_name: 'Chrome' });
    expect(f.phase(D).kind).toBe('waiting');   // another service's event
    dispatch({ type: 'SignInPhase', service: 'soundcloud', phase: 'checking', browser: 'chrome', browser_name: 'Chrome' });
    expect(f.phase(D)).toEqual({ kind: 'checking', browserName: 'Chrome' });
    finish(1, 'account_sign_in', { ok: false, problem: 'failed', message: "Didn't see a login in 10 minutes. Sign in again." });
    await p;
    const ph = f.phase(D);
    expect(ph).toMatchObject({ kind: 'result', tone: 'problem', message: "Didn't see a login in 10 minutes. Sign in again." });
    expect(mainAction(ph)?.kind).toBe('sign-in');
    off();
  });
  it('Cancel ends quietly where the sign-in started (a picked profile stays picked)', async () => {
    fakeWindow();
    const f = new AccountFlow('youtube', () => {});
    await f.load();
    const person1 = browserMenu(f.logins)[0];
    f.pick(person1);
    const picked = f.phase(D);
    expect(picked).toMatchObject({ kind: 'none', profile: 'Default', picked: true });
    const p = f.signIn('chrome', 'Default');
    await flush();
    await f.cancel();
    finish(1, 'account_sign_in', { ok: false, problem: 'stopped', message: 'Stopped.' });
    await p;
    expect(calls.map((c) => c[0])).toEqual(['account_sign_in', 'stop_sign_in']);
    expect(f.phase(D)).toEqual(picked);
  });
  it('an immediate refusal shows its words', async () => {
    fakeWindow({ account_sign_in: async () => ({ ok: false, kind: 'sync_running', message: 'A sync is running.' }) });
    const f = new AccountFlow('youtube', () => {});
    await f.signIn('chrome');
    expect(f.active).toMatchObject({ kind: 'result', message: 'A sync is running.' });
  });
  it('picks Safari without access: Open System Settings', async () => {
    fakeWindow();
    const f = new AccountFlow('youtube', () => {});
    await f.load();
    f.pick(browserMenu(f.logins).find((c) => c.noAccess)!);
    expect(mainAction(f.phase(D))?.kind).toBe('privacy');
    f.back();
    expect(f.phase(D).kind).toBe('found');
  });
  it('Check again uses the saved browser and profile', async () => {
    fakeWindow();
    const f = new AccountFlow('youtube', () => {});
    const p = f.checkAgain({ ...D.youtube, state: 'on', browser: 'chrome', browser_name: 'Chrome', profile: 'Profile 2' });
    await flush();
    finish(1, 'setup_account', { result: { check: { ok: true, problem: null, kbps: 256, message: '' } } });
    await p;
    expect(calls[0]).toEqual(['setup_account', ['youtube', 'chrome', 'Profile 2']]);
  });
  it('picks up a sign-in still waiting from before', async () => {
    fakeWindow({ job_status: async () => ({ ok: true, job: null, refresh_running: false, console_running: false, read_status: null,
      sign_in: { id: 7, kind: 'account_sign_in', running: true, last: { SignInPhase: { type: 'SignInPhase',
        service: 'youtube', phase: 'waiting', browser: 'chrome', browser_name: 'Chrome' } } } }) });
    const changed = vi.fn();
    const f = new AccountFlow('youtube', changed);
    const off = f.mount();
    await flush(); await flush();
    expect(f.phase(D)).toEqual({ kind: 'waiting', browser: 'chrome', browserName: 'Chrome' });
    finish(7, 'account_sign_in', { result: { check: { ok: true, problem: null, kbps: 256, message: '' } } });
    await flush();
    expect(f.active).toBeNull();
    expect(changed).toHaveBeenCalledOnce();
    off();
  });
  it('Qobuz: the password leaves its element as the call goes out; no email sends nothing', async () => {
    fakeWindow();
    const f = new AccountFlow('qobuz', () => {});
    const el = { value: 'hunter2' };
    await f.qobuzLogin('  ', el);
    expect(calls).toEqual([]);
    expect(el.value).toBe('hunter2');
    expect(f.active).toMatchObject({ kind: 'result', retry: { kind: 'form' } });
    const p = f.qobuzLogin(' dj@example.com ', el);
    expect(el.value).toBe('');
    expect(f.phase(D)).toEqual({ kind: 'checking', browserName: null });
    await flush();
    finish(1, 'setup_qobuz_login', { ok: false, problem: 'failed', message: "Qobuz didn't accept the login." });
    await p;
    expect(calls[0]).toEqual(['setup_qobuz_login', ['dj@example.com', 'hunter2']]);
    expect(JSON.stringify(f.active)).not.toContain('hunter2');
    expect(mainAction(f.phase(D))?.kind).toBe('qobuz-sign-in');
  });
  it('Qobuz: Check again and Use another account', async () => {
    fakeWindow();
    const f = new AccountFlow('qobuz', () => {});
    const p = f.checkAgain();
    await flush();
    finish(1, 'qobuz_check_login');
    await p;
    expect(calls[0][0]).toBe('qobuz_check_login');
    f.editQobuz();
    expect(f.phase({ ...D, qobuz: { state: 'on', last_check: null, tracks: 3 } })).toEqual({ kind: 'form', editing: true });
  });
  it('Qobuz: a failed Check again brings the fields back under its words; over a working login it can go back', async () => {
    fakeWindow();
    const f = new AccountFlow('qobuz', () => {});
    const p = f.checkAgain();
    await flush();
    finish(1, 'qobuz_check_login', { ok: false, problem: 'failed', message: "Qobuz didn't accept the login." });
    await p;
    const rejected = f.phase({ ...D, qobuz: { state: 'off', last_check: { ok: false, problem: 'failed', kbps: null, at: '' }, tracks: 3 } });
    expect(rejected).toEqual({ kind: 'result', message: "Qobuz didn't accept the login.", tone: 'problem', retry: { kind: 'form' } });
    expect(mainAction(rejected)?.kind).toBe('qobuz-sign-in');
    expect(dismissable(rejected)).toBe(false);
    f.back();
    expect(f.phase({ ...D, qobuz: { state: 'on', last_check: null, tracks: 3 } })).toEqual({ kind: 'working' });
  });
  it('a failed sign-out is a result with OK, which goes back to the account', async () => {
    fakeWindow();
    const f = new AccountFlow('youtube', () => {});
    const p = f.signOut();
    answerConfirm(true);
    await flush();
    finish(1, 'setup_forget_account', { ok: false, problem: 'busy', message: 'Wait until the current change is finished.' });
    await p;
    const on = { ...D, youtube: { ...D.youtube, state: 'on' as const, browser: 'chrome' as const, browser_name: 'Chrome' } };
    const phase = f.phase(on);
    expect(phase).toMatchObject({ kind: 'result', retry: null });
    expect(mainAction(phase)).toBeNull();
    expect(dismissable(phase)).toBe(true);
    f.back();
    expect(f.phase(on)).toEqual({ kind: 'working' });
  });
  it('System Settings that did not open is a result with OK', async () => {
    fakeWindow({ open_privacy_settings: async () => ({ ok: false, kind: 'crashed', message: "System Settings didn't open." }) });
    const f = new AccountFlow('youtube', () => {});
    await f.openPrivacySettings();
    expect(dismissable(f.phase(D))).toBe(true);
    f.back();
    expect(f.active).toBeNull();
  });
});
