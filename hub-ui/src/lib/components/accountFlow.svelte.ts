// The account panel's controller (plan R11): one per service, the only part of the panel that talks to the bridge.
// The panel (AccountPanel.svelte) renders from what this holds; the page creates the flow, calls `mount()` once
// (find_logins, the SignInPhase events, a sign-in still waiting from before) and hands it to the panel as `actions`.
// After every finished job it calls `onchanged`, so the page reads downloads_view / setup_status again.
// The Qobuz password is read out of its element with takeSecret as the call goes out; it is never kept here.
import { api, runJob, type JobOutcome } from '../bridge/client';
import { onEvent, type EventOf } from '../bridge/events';
import type { AccountCheck, Browser, DownloadsAccount, DownloadsView, FindLogins, Service } from '../bridge/types';
import { waitForJob } from '../stores/jobs';
import { confirm } from './confirm';
import {
  QOBUZ_PASSWORD_URL, SERVICE_TITLES, accountPhase, checkPhase, pickedPhase, qobuzPhase, takeSecret,
  type MenuChoice, type Offer, type PanelPhase,
} from './accountModel';

/** What the panel can ask for. AccountFlow implements it; the gallery passes a stand-in. */
export interface AccountActions {
  /** find_logins again (the Retry of a failed look) */
  load(): Promise<void>;
  /** check the login in that browser profile and save it (setup_account) */
  useLogin(browser: Browser, profile: string | null): Promise<void>;
  /** open the sign-in page and wait for the login (account_sign_in) */
  signIn(browser: Browser, profile?: string | null): Promise<void>;
  /** Cancel a waiting sign-in (stop_sign_in); it ends quietly where it started */
  cancel(): Promise<void>;
  /** the saved login checked again (accounts: setup_account with its browser and profile; Qobuz: qobuz_check_login) */
  checkAgain(a?: DownloadsAccount | null): Promise<void>;
  /** forget the saved login after asking (setup_forget_account) */
  signOut(): Promise<void>;
  openPrivacySettings(): Promise<void>;
  /** a "Use another browser" pick: the panel then offers that profile */
  pick(choice: MenuChoice): void;
  /** leave a picked browser, a result (its OK) or the Qobuz form over a working login */
  back(): void;
  /** Qobuz: sign in with the email and the password in its element */
  qobuzLogin(email: string, password: { value: string } | null | undefined): Promise<void>;
  /** Qobuz: "I don't have Qobuz" */
  skipQobuz(): Promise<void>;
  /** Qobuz: Set a Qobuz password ↗ */
  openPasswordPage(): Promise<void>;
  /** Qobuz: Use another account (the form over a working login) */
  editQobuz(): void;
}

type SignInPhaseEvent = EventOf<'SignInPhase'>;
const QUIET = { quiet: true, success: false } as const;

export class AccountFlow implements AccountActions {
  readonly service: Service;
  /** find_logins' answer (accounts); null until it came */
  logins = $state<FindLogins | null>(null);
  /** find_logins failed: the panel shows a compact problem with Retry */
  loadError = $state<string | null>(null);
  /** a phase the flow is in (waiting, checking, a result, a pick); null: the account's own state shows */
  active = $state<PanelPhase | null>(null);
  /** one of this panel's jobs runs */
  busy = $state(false);
  #onchanged: () => void;
  /** where to go back to when a sign-in is cancelled */
  #before: PanelPhase | null = null;

  constructor(service: Service, onchanged: () => void) {
    this.service = service;
    this.#onchanged = onchanged;
  }

  /** The phase to render, from the page's downloads_view. */
  phase(d: DownloadsView | null): PanelPhase {
    if (this.service === 'qobuz') return qobuzPhase(d?.qobuz ?? null, this.active);
    return accountPhase(d?.[this.service] ?? null, this.logins, this.loadError, this.active);
  }

  /** Call once when the panel shows (`$effect(() => flow.mount())`): looks for logins, follows this service's
   *  SignInPhase events and picks up a sign-in that is still waiting (after navigating away and back). */
  mount(): () => void {
    const off = onEvent((e) => { if (e.type === 'SignInPhase') this.#phaseEvent(e); });
    void this.load();
    void this.#restore();
    return off;
  }

  async load(): Promise<void> {
    if (this.service === 'qobuz') return;
    this.loadError = null;
    const r = await api.find_logins(this.service);
    if (r.ok) this.logins = { browsers: r.browsers };
    else this.loadError = r.message;
  }

  async useLogin(browser: Browser, profile: string | null): Promise<void> {
    if (this.service === 'qobuz' || this.busy) return;
    const retry = this.#offerFor(browser, profile);
    this.#start({ kind: 'checking', browserName: retry.browserName });
    const r = await runJob<{ check: AccountCheck }>(api.setup_account(this.service, browser, profile), QUIET);
    this.#settle(r, retry);
  }

  async signIn(browser: Browser, profile: string | null = null): Promise<void> {
    if (this.service === 'qobuz' || this.busy) return;
    const retry = this.#offerFor(browser, profile);
    const browserName = retry.browserName ?? browser;
    this.#start({ kind: 'waiting', browser, browserName });
    const r = await runJob<{ check: AccountCheck }>(api.account_sign_in(this.service, browser, profile), QUIET);
    this.#settle(r, retry);
  }

  async cancel(): Promise<void> {
    await api.stop_sign_in();
  }

  async checkAgain(a?: DownloadsAccount | null): Promise<void> {
    if (this.service === 'qobuz') {
      if (this.busy) return;
      this.#start({ kind: 'checking', browserName: null });
      // a failed check brings the fields back under its words: that is when the user needs to sign in again
      this.#settle(await runJob(api.qobuz_check_login(), QUIET), { kind: 'form' });
      return;
    }
    if (a?.browser) await this.useLogin(a.browser, a.profile);
  }

  async signOut(): Promise<void> {
    if (this.service === 'qobuz' || this.busy) return;
    const name = SERVICE_TITLES[this.service];
    const yes = await confirm({ title: `Sign out of ${name}?`, body: 'Discjockey forgets which browser holds the login. '
      + 'Downloads use the free streams until you sign in again; your browser stays signed in.',
      confirmLabel: 'Sign out', tone: 'danger' });
    if (!yes) return;
    this.#start(null);
    this.#settle(await runJob(api.setup_forget_account(this.service), QUIET), null);
  }

  async openPrivacySettings(): Promise<void> {
    const r = await api.open_privacy_settings();
    if (!r.ok) this.active = { kind: 'result', message: r.message, tone: 'problem', retry: null };
  }

  pick(choice: MenuChoice): void {
    if (this.busy) return;
    this.active = pickedPhase(choice);
  }

  back(): void {
    if (!this.busy) this.active = null;
  }

  async qobuzLogin(email: string, password: { value: string } | null | undefined): Promise<void> {
    if (this.service !== 'qobuz' || this.busy) return;
    const mail = email.trim();
    // without an email nothing is sent, so a typed password stays in its field
    if (!mail) { this.active = { kind: 'result', message: 'Type your e-mail and password.', tone: 'problem', retry: { kind: 'form' } }; return; }
    const pw = takeSecret(password);
    if (!pw) { this.active = { kind: 'result', message: 'Type your e-mail and password.', tone: 'problem', retry: { kind: 'form' } }; return; }
    this.#start({ kind: 'checking', browserName: null });
    this.#settle(await runJob(api.setup_qobuz_login(mail, pw), QUIET), { kind: 'form' });
  }

  async skipQobuz(): Promise<void> {
    if (this.service !== 'qobuz' || this.busy) return;
    this.#start(null);
    this.#settle(await runJob(api.setup_skip_qobuz(), QUIET), { kind: 'form' });
  }

  async openPasswordPage(): Promise<void> {
    const r = await api.open_external(QOBUZ_PASSWORD_URL);
    if (!r.ok) this.active = { kind: 'result', message: r.message, tone: 'problem', retry: { kind: 'form' } };
  }

  editQobuz(): void {
    if (!this.busy) this.active = { kind: 'form', editing: true };
  }

  // ---- inside ----

  /** The offer a browser profile stands for (what Try again repeats), named from find_logins. */
  #offerFor(browser: Browser, profile: string | null): Offer {
    const b = this.logins?.browsers.find((x) => x.id === browser);
    const p = b?.profiles.find((x) => x.id === profile);
    const profileName = b && p && b.profiles.length > 1 ? p.name : null;
    const browserName = b?.name ?? browser;
    return p?.signed_in
      ? { kind: 'found', browser, browserName, profile, profileName }
      : { kind: 'none', browser, browserName, profile, profileName, searched: [browserName] };
  }

  #start(phase: PanelPhase | null): void {
    this.#before = this.active;
    this.busy = true;
    if (phase) this.active = phase;
  }

  /** A job ended: it works → the state shows; stopped → back where it started; else its words and Try again. */
  #settle(r: JobOutcome<unknown>, retry: Offer | { kind: 'form' } | null): void {
    this.busy = false;
    if (r.ok) {
      const check = (r.result as { check?: AccountCheck } | null)?.check;
      this.active = check && retry && retry.kind !== 'form' ? checkPhase(check, retry) : null;
    } else if (r.kind === 'stopped') {
      this.active = this.#before?.kind === 'waiting' || this.#before?.kind === 'checking' ? null : this.#before;
    } else {
      this.active = { kind: 'result', message: r.message, tone: 'problem', retry };
    }
    this.#before = null;
    this.#onchanged();
  }

  #phaseEvent(e: SignInPhaseEvent): void {
    if (e.service !== this.service || !this.busy) return;
    this.active = e.phase === 'waiting' ? { kind: 'waiting', browser: e.browser, browserName: e.browser_name }
      : { kind: 'checking', browserName: e.browser_name };
  }

  /** A sign-in for this service still waiting from before (job_status().sign_in): show it and wait for its end. */
  async #restore(): Promise<void> {
    if (this.service === 'qobuz' || this.busy) return;
    const js = await api.job_status();
    const job = js.ok ? js.sign_in : null;
    const last = job?.last?.SignInPhase as SignInPhaseEvent | undefined;
    if (!job || !job.running || job.kind !== 'account_sign_in' || last?.service !== this.service || this.busy) return;
    this.#start(null);
    this.#phaseEvent(last);
    const retry: Offer = { kind: 'none', browser: last.browser, browserName: last.browser_name, profile: null,
      profileName: null, searched: [last.browser_name] };
    const fin = await waitForJob(job.id);
    const outcome: JobOutcome<unknown> = fin.ok ? { ok: true, job_id: job.id, result: fin.result }
      : { ok: false, job_id: job.id, kind: fin.problem ?? 'crashed', message: fin.message };
    this.#settle(outcome, retry);
  }
}
