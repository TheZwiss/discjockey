<script lang="ts">
  // One download login (spec settings-setup §5): what it gives, its state, the sign-in. Presentational (plan R11): it
  // renders `phase` and calls `actions` (an AccountFlow, accountFlow.svelte.ts, or the gallery's stand-in), so every
  // phase shows without running a job. Words and decisions come from accountModel.ts.
  // Full form (Settings, `compact={false}`): a `Panel`. Its head is the gain card (a StatCard: 256 kbps against about
  // 130 with two bars; Qobuz: its tracks and their share) and the state card, named after the service with the risk
  // note behind the ⓘ at its head's end (Playlists' list head puts its ⓘ there too); the foot holds the phase's one
  // filled action (Use this login · Sign in · Open System Settings · Qobuz's Sign in), nothing while it works or
  // waits. A panel never puts a title on the background: the state card's label names the panel (decision log).
  // Compact form (Setup): one Surface card per service, its head the mark · name · state or what it gives; the main
  // action is `filled` only when Setup's step says this is the one (`filled`, plan R10), else `primary`.
  // Explanations inside a card wrap as quiet lines (they sit in a Surface, so they may be longer than a Hint); the
  // one Hint is the reason the buttons are off (`disabledWhy`), under the control it explains.
  // The Qobuz password stays in its element (SecretField) until `actions.qobuzLogin` takes it out (takeSecret).
  import type { DownloadsView, FindLogins, Service } from '../bridge/types';
  import { Panel } from '../frames';
  import Button from './Button.svelte';
  import ContextMenu, { type MenuItem } from './ContextMenu.svelte';
  import Hint from './Hint.svelte';
  import InfoTip from './InfoTip.svelte';
  import NoteCard from './NoteCard.svelte';
  import NumberedSteps from './NumberedSteps.svelte';
  import ProgressBar from './ProgressBar.svelte';
  import SecretField from './SecretField.svelte';
  import Skeleton from './Skeleton.svelte';
  import Spinner from './Spinner.svelte';
  import StatCard from './StatCard.svelte';
  import StatusMark from './StatusMark.svelte';
  import Surface from './Surface.svelte';
  import TextField from './TextField.svelte';
  import type { AccountActions } from './accountFlow.svelte';
  import {
    GAIN_KBPS, RISK_NOTE, SERVICE_TITLES, browserMenu, checkedBefore, chromiumHint, compactLine, foundText, gainCaption,
    gainLine, isWorking, mainAction, noneText, panelLine, qobuzPasswordSteps, qobuzShare, signInHint, unreadableText,
    waitingText, dismissable, type AccountService, type Offer, type PanelPhase,
  } from './accountModel';
  import { limitsHref } from './ladderModel';

  type Props = {
    service: Service; downloads: DownloadsView | null; phase: PanelPhase; actions: AccountActions;
    /** find_logins' answer, for "Use another browser ▾" */
    logins?: FindLogins | null;
    compact?: boolean;
    /** compact: this card's main action is the screen's one filled button (Setup decides, plan R10) */
    filled?: boolean;
    /** one of this panel's own jobs runs (its phase already says so) */
    busy?: boolean;
    /** why the write buttons are off (accountBlocked): a terminal run, the hub's sync, another change */
    disabledWhy?: string | null;
    /** Qobuz: the Google, Apple or Facebook steps are open */
    stepsOpen?: boolean;
    now?: Date; test?: string;
  };
  let { service, downloads, phase, actions, logins = null, compact = false, filled = false, busy = false,
    disabledWhy = null, stepsOpen = $bindable(false), now = new Date(), test = `account-${service}` }: Props = $props();

  const isQ = $derived(service === 'qobuz');
  const acc = $derived(service as AccountService);
  const name = $derived(SERVICE_TITLES[service]);
  const line = $derived(downloads ? panelLine(service, downloads, now) : null);
  const head = $derived(downloads ? compactLine(service, downloads, now) : null);
  const works = $derived(!!downloads && isWorking(service, downloads));
  const row = $derived(!isQ && downloads ? downloads[acc] : null);
  const action = $derived(mainAction(phase));
  const off = $derived(!!disabledWhy || busy);
  /** the browser profile the phase offers (a result offers its retry) */
  const offer = $derived.by((): Offer | null => {
    if (phase.kind === 'found' || phase.kind === 'none' || phase.kind === 'unreadable') return phase;
    if (phase.kind === 'result' && phase.retry && phase.retry.kind !== 'form') return phase.retry;
    return null;
  });
  // macOS's keychain prompt, before the first check of a Chromium browser (null for Safari and Firefox)
  const keychain = $derived(offer ? chromiumHint(offer.browser, checkedBefore(offer.browser, downloads)) : null);
  const defaultName = $derived(logins?.browsers.find((b) => b.default)?.name ?? null);
  const formShown = $derived(isQ && (phase.kind === 'form' || (phase.kind === 'result' && phase.retry?.kind === 'form')));
  // a failed attempt whose saved state is a problem too (Qobuz's rejected login, a lost login that didn't come back):
  // the attempt's own words are the headline, so the problem is said once
  const resultHeads = $derived(phase.kind === 'result' && line?.tone === 'problem');
  // paused or used up for today: where that is explained and can be lifted
  const limits = $derived(downloads ? limitsHref(service, isQ ? downloads.qobuz.state : downloads[acc].state) : null);
  const tone = $derived(line?.tone === 'good' || line?.tone === 'warn' || line?.tone === 'problem' ? line.tone : 'default');

  // ---- Qobuz's fields: the email is no secret; the password stays in its element ----
  let email = $state('');
  let pwEl = $state<HTMLInputElement | HTMLTextAreaElement>();
  // Qobuz's Sign in stays on with empty fields (the screen's one filled button keeps its look); the flow then
  // says "Type your e-mail and password." and sends nothing. Opening System Settings is a read: never off.
  // System Settings and another look for logins only read, so a running change doesn't block them
  const readOnly = $derived(action?.kind === 'privacy' || action?.kind === 'look-again');
  const mainOff = $derived(readOnly ? false : off);
  const mainWhy = $derived(readOnly ? undefined : disabledWhy ?? undefined);
  function doMain() {
    if (!action || mainOff) return;
    if (action.kind === 'privacy') { void actions.openPrivacySettings(); return; }
    if (action.kind === 'qobuz-sign-in') { void actions.qobuzLogin(email, pwEl); return; }
    if (action.kind === 'look-again') { void actions.load(); return; }
    if (!offer?.browser) return;
    if (action.kind === 'use') void actions.useLogin(offer.browser, offer.profile);
    else void actions.signIn(offer.browser, offer.profile);
  }

  // ---- "Use another browser ▾" ----
  const choices = $derived(browserMenu(logins));
  let menu = $state<{ x: number; y: number; keyboard: boolean } | null>(null);
  const items = $derived<MenuItem[]>(choices.map((c) => ({ key: c.key, label: c.label, note: c.note, good: c.good,
    test: `${test}-menu-${c.key}`, onpick: () => { menu = null; actions.pick(c); } })));
  function openMenu(e: MouseEvent) {
    e.stopPropagation();   // the menu closes on any window click, this one included
    if (menu) { menu = null; return; }
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    menu = { x: r.left, y: r.bottom + 4, keyboard: e.detail === 0 };   // detail 0: Enter or Space
  }
  function closeMenu() {
    const inside = !!(document.activeElement as HTMLElement | null)?.closest('[role=menu]');
    menu = null;
    if (inside) document.querySelector<HTMLElement>(`[data-test="${test}-other"]`)?.focus();
  }
  // a card's buttons: small in Settings' panel (its main action is the foot's), full height in Setup's row
  const ctl: 'md' | 'sm' = $derived(compact ? 'md' : 'sm');
</script>

<!-- ─── pieces shared by both forms ─── -->

{#snippet stateRow()}
  {#if line}
    <div class="item" data-test="{test}-line" role={resultHeads ? 'alert' : undefined}>
      <StatusMark tone={line.tone} />
      <div class="two"><span class="title" data-test={resultHeads ? `${test}-result` : undefined}>{resultHeads
        && phase.kind === 'result' ? phase.message : line.title}</span>{#if line.sub}<span class="sub">{line.sub}</span>{/if}</div>
      <!-- Sign out wherever a login is saved, also one that stopped working (spec §5 item 4); not mid sign-in -->
      {#if !compact && !isQ && row?.browser && phase.kind !== 'waiting' && phase.kind !== 'checking'}
        <Button variant="link" muted size="sm" disabled={off} title={disabledWhy ?? undefined}
          onclick={() => void actions.signOut()} data-test="{test}-sign-out">Sign out</Button>
      {/if}
    </div>
  {:else}
    <Skeleton lines={2} />
  {/if}
{/snippet}

{#snippet otherBrowser()}
  {#if choices.length}
    <Button size={ctl} disabled={off} title={disabledWhy ?? undefined} onclick={openMenu} aria-haspopup="menu"
      aria-expanded={!!menu} data-test="{test}-other">Another browser ▾</Button>
  {/if}
{/snippet}

{#snippet mainButton(wide: boolean, variant: 'filled' | 'primary')}
  {#if action}
    <Button {variant} {wide} disabled={mainOff} title={mainWhy} onclick={doMain} data-test="{test}-main">{action.label}</Button>
  {/if}
{/snippet}

<!-- where the sign-in stands; each line keeps the state row's gutter (spinner or mark in it, words on the title's
     edge), so every sentence of the card starts at one edge -->
{#snippet area()}
  {#if phase.kind === 'looking'}
    <div class="item"><Spinner size={12} label="Looking" /><span class="sub">Looking for your login…</span></div>
  {:else if phase.kind === 'error'}
    <div class="item" role="alert" data-test="{test}-error"><StatusMark tone="problem" /><span class="text">{phase.message}</span></div>
  {:else if phase.kind === 'checking'}
    <div class="item"><Spinner size={12} label="Checking" /><span class="text" data-test="{test}-checking">{isQ
      ? 'Checking the login with one search…' : 'Checking one song…'}</span></div>
  {:else if phase.kind === 'waiting'}
    <div class="item"><Spinner size={12} label="Waiting" /><div class="two">
      <span class="text" data-test="{test}-waiting">{waitingText(phase.browserName)}</span>
      <span class="sub">Use the window that just opened to sign in. Discjockey keeps watching for 10 minutes.</span></div></div>
  {:else if phase.kind === 'result' && !resultHeads}
    <!-- the keychain note sits under the result's words in the same column, as it does under found/none -->
    <div class="item" data-test="{test}-result"><StatusMark tone={phase.tone} /><div class="two">
      <span class="text" role="alert">{phase.message}</span>
      {#if keychain && action}<span class="sub" data-test="{test}-keychain">{keychain}</span>{/if}
    </div></div>
  {:else if phase.kind === 'found' || phase.kind === 'none' || phase.kind === 'unreadable'}
    <div class="item"><span></span><div class="two">
      {#if phase.kind === 'found'}
        <span class="text" data-test="{test}-found">{foundText(acc, phase)}</span>
        <span class="sub">Use it, and Discjockey checks one song for the {GAIN_KBPS.with} kbps.</span>
      {:else if phase.kind === 'none'}
        {@const hint = signInHint(acc, phase, defaultName)}
        <span class="text" data-test="{test}-none">{noneText(acc, phase)}</span>
        {#if hint}<span class="sub">{hint} Discjockey notices the login by itself.</span>{/if}
      {:else}
        {@const u = unreadableText(phase.browserName)}
        <span class="text" data-test="{test}-unreadable">{u.text}</span><span class="sub">{u.hint}</span>
      {/if}
      {#if keychain && action && action.kind !== 'privacy'}<span class="sub" data-test="{test}-keychain">{keychain}</span>{/if}
    </div></div>
  {/if}
  {#if phase.kind === 'result' && resultHeads && keychain && action}
    <div class="item"><span></span><span class="sub" data-test="{test}-keychain">{keychain}</span></div>
  {/if}
{/snippet}

<!-- a result with nothing to try again: OK goes back to the account's own state -->
{#snippet okButton()}
  <div class="buttons"><Button variant="link" muted size="sm" disabled={busy} onclick={() => actions.back()}
    data-test="{test}-ok">OK</Button></div>
{/snippet}

<!-- paused or used up for today: the limits page explains it and can lift it (spec §4, plan R26) -->
{#snippet limitsLink()}
  {#if limits}
    <Button variant="link" size="sm" href={limits} data-test="{test}-limits">Download limits →</Button>
  {/if}
{/snippet}

<!-- the smaller actions of an account (spec §5 item 4) -->
{#snippet accountButtons()}
  {#if phase.kind === 'working' || phase.kind === 'no_premium'}
    <div class="buttons">
      <Button size={ctl} disabled={off} title={disabledWhy ?? undefined} onclick={() => void actions.checkAgain(row)}
        data-test="{test}-check">Check again</Button>
      {@render otherBrowser()}
      {@render limitsLink()}
    </div>
  {:else if phase.kind === 'waiting'}
    <div class="buttons"><Button size={ctl} onclick={() => void actions.cancel()} data-test="{test}-cancel">Cancel</Button></div>
  {:else if dismissable(phase)}
    {@render okButton()}
  {:else if offer}
    <div class="buttons">
      {#if compact}{@render mainButton(false, filled ? 'filled' : 'primary')}{/if}
      {@render otherBrowser()}
      {#if offer.picked}<Button size={ctl} disabled={busy} onclick={() => actions.back()} data-test="{test}-back">Cancel</Button>{/if}
    </div>
  {/if}
{/snippet}

<!-- Qobuz: email and password, or what to do with a working login -->
{#snippet qobuzBody()}
  {#if phase.kind === 'looking'}
    <Skeleton lines={2} />
  {:else if phase.kind === 'checking'}
    {@render area()}
  {:else if phase.kind === 'working'}
    {#if !compact}
      <div class="buttons">
        <Button size="sm" disabled={off} title={disabledWhy ?? undefined} onclick={() => void actions.checkAgain()}
          data-test="{test}-check">Check again</Button>
        <Button size="sm" disabled={off} title={disabledWhy ?? undefined} onclick={() => actions.editQobuz()}
          data-test="{test}-other-account">Use another account</Button>
        {@render limitsLink()}
      </div>
    {/if}
  {:else if dismissable(phase)}
    {@render area()}{@render okButton()}
  {:else if formShown}
    <div class="fields">
      <TextField bind:value={email} type="email" placeholder="E-mail" label="Qobuz e-mail" name="qobuz-email"
        disabled={busy} />
      <SecretField bind:el={pwEl} placeholder="Password" label="Qobuz password" test="{test}-password" onenter={doMain} />
    </div>
    {#if phase.kind === 'result'}{@render area()}{/if}
    {#if !compact}<p class="sub">Stored only on this Mac. Discjockey tests the login with one search.</p>{/if}
    <div class="buttons" class:links={!compact}>
      {#if compact}{@render mainButton(false, filled ? 'filled' : 'primary')}<span class="push"></span>{/if}
      <Button variant="link" size="sm" onclick={() => (stepsOpen = !stepsOpen)} aria-expanded={stepsOpen}
        data-test="{test}-google">Google, Apple or Facebook account?</Button>
      <!-- over a working login (Use another account, or a Check again that failed), the way back keeps it -->
      {#if (phase.kind === 'form' && phase.editing) || (phase.kind === 'result' && works)}
        <Button variant="link" muted size="sm" disabled={busy} onclick={() => actions.back()} data-test="{test}-back">Keep the
          current login</Button>
      {:else if downloads?.qobuz.state !== 'skipped' && !works}
        <Button variant="link" muted size="sm" disabled={off} title={disabledWhy ?? undefined}
          onclick={() => void actions.skipQobuz()} data-test="{test}-skip">I don't have Qobuz</Button>
      {/if}
    </div>
  {/if}
{/snippet}

{#snippet steps()}
  <NoteCard title="Give your Qobuz account a password once" data-test="{test}-steps">
    <p>Your Google, Apple or Facebook sign-in keeps working.</p>
    <div class="stepsgap"><NumberedSteps>
      {#each qobuzPasswordSteps() as text, i (i)}
        <li><span>{text}</span>
          {#if i === 0}<div><Button variant="primary" size="sm" onclick={() => void actions.openPasswordPage()}
            data-test="{test}-password-page">Set a Qobuz password ↗</Button></div>{/if}</li>
      {/each}
    </NumberedSteps></div>
  </NoteCard>
{/snippet}

{#snippet why()}
  {#if disabledWhy && !busy}<Hint text={disabledWhy} data-test="{test}-why" />{/if}
{/snippet}

<!-- ─── the full form: Settings' panel ─── -->

{#snippet gainCard()}
  {#if isQ}
    {@const q = downloads ? qobuzShare(downloads) : null}
    <StatCard value={q ? q.tracks : null} unit="tracks" label={q && q.total ? `lossless from Qobuz · of ${q.total}`
      : 'lossless from Qobuz · 16-bit AIFF'} data-test="{test}-gain">
      <ProgressBar value={q?.share ?? null} tone="lossless" label="Your tracks from Qobuz" />
    </StatCard>
  {:else}
    {@const g = downloads ? gainLine(acc, downloads) : null}
    <StatCard value={GAIN_KBPS.with} unit="kbps" label={gainCaption(acc)} data-test="{test}-gain">
      <div class="gain">
        <span class="gk">{acc === 'youtube' ? 'Premium' : 'Go+'}</span>
        <span class="track"><i class="fill good" style:width="100%"></i></span><b>{GAIN_KBPS.with}</b>
        <span class="gk">Free</span>
        <span class="track"><i class="fill weak" style:width="{Math.round((GAIN_KBPS.without / GAIN_KBPS.with) * 100)}%"></i></span>
        <b>{GAIN_KBPS.without}</b>
      </div>
      <p class="sub gline">For songs Qobuz doesn't have.{#if g}{' '}<span class="text">{g}</span>{/if}</p>
    </StatCard>
  {/if}
{/snippet}

{#snippet fullHead()}
  <div class="col" data-test={test}>
    {@render gainCard()}
    <Surface kind="card" label={name} {tone} data-test="{test}-state">
      {#snippet header()}<InfoTip label="About {name}'s terms" data-test="{test}-risk">{RISK_NOTE[service]}</InfoTip>{/snippet}
      {@render stateRow()}
      {#if isQ}{@render qobuzBody()}{:else}{@render area()}{@render accountButtons()}{/if}
      {#if !action}{@render why()}{/if}
    </Surface>
    {#if formShown && stepsOpen}{@render steps()}{/if}
  </div>
{/snippet}

{#snippet fullFoot()}
  {@render mainButton(true, 'filled')}
  {@render why()}
{/snippet}

{#if compact}
  <div class="col" data-test={test} data-compact>
    <Surface kind="card" {tone} data-test="{test}-state">
      <div class="chead">
        {#if head}<StatusMark tone={head.tone ?? 'none'} />{:else}<StatusMark tone="none" />{/if}
        <b class="name">{name}</b>
        <span class="csub" data-test="{test}-line">{head?.text ?? ''}</span>
        <!-- "optional" speaks to a login still to do; on a working card it would only cut the state line short -->
        {#if !isQ && !works}<span class="opt">optional</span>{/if}
        <InfoTip label="About {name}'s terms" data-test="{test}-risk">{RISK_NOTE[service]}</InfoTip>
      </div>
      {#if !works || phase.kind !== 'working'}
        {#if isQ}{@render qobuzBody()}{:else}{@render area()}{@render accountButtons()}{/if}
        {@render why()}
      {/if}
    </Surface>
    {#if formShown && stepsOpen}{@render steps()}{/if}
  </div>
{:else}
  <Panel head={fullHead} foot={action ? fullFoot : undefined} />
{/if}

{#if menu}
  <ContextMenu x={menu.x} y={menu.y} {items} focusFirst={menu.keyboard} onclose={closeMenu} test="{test}-menu" />
{/if}

<style>
  .col { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
  /* a line of the card: a 16 px gutter (the state's mark, a spinner, or nothing), the words on one edge, an
     optional action at the end (Sign out beside the login it forgets) */
  .item { display: grid; grid-template-columns: 16px minmax(0, 1fr) auto; column-gap: var(--s-2); align-items: start; }
  .item > :global(.mark) { margin-top: 1px; }
  .item > :global(.spinner) { margin: 3px 2px 0; }
  .item > :global(button) { align-self: center; }
  .two { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .title { color: var(--text-strong); font-size: var(--fs-body); font-weight: var(--fw-semi); line-height: 1.35;
    overflow-wrap: anywhere; }
  .text { color: var(--text); font-size: var(--fs-body); line-height: 1.4; overflow-wrap: anywhere; }
  p { margin: 0; }
  .sub { color: var(--text-muted); font-size: var(--fs-small); line-height: 1.45; overflow-wrap: anywhere; }
    /* what changes with the phase arrives with a short fade (spec §6: entrances ≤ 150 ms, fades only) */
  .item { transition: opacity 120ms var(--ease); }
  @starting-style { .item { opacity: 0; } }
  .buttons { display: flex; align-items: center; gap: var(--s-2); flex-wrap: wrap; min-width: 0; }
  .buttons.links { flex-direction: column; align-items: flex-start; gap: var(--s-2); }
  .push { flex: 1; }
  .fields { display: flex; flex-direction: column; gap: var(--s-2); }

  /* the gain: two bars on one scale, the account's quality (good) against the free streams' (weak) */
  .gain { display: grid; grid-template-columns: 48px minmax(0, 1fr) 28px; align-items: center; column-gap: var(--s-2);
    row-gap: var(--s-1); font-size: var(--fs-label); color: var(--text-label); margin-top: var(--s-1); }
  .gain b { font-weight: var(--fw-medium); color: var(--text); text-align: right; font-variant-numeric: tabular-nums;
    font-size: var(--fs-label); }
  .track { display: block; height: 6px; border-radius: var(--r-pill); background: var(--bg-inset); overflow: hidden; }
  .fill { display: block; height: 100%; border-radius: var(--r-pill); }
  .fill.good { background: var(--q-good-bar); }
  .fill.weak { background: var(--q-weak-bar); }
  .gline { margin-top: var(--s-2); }

  /* the password steps: a numbered column, the button under its step */
  .stepsgap { margin-top: var(--s-2); }

  /* Setup's compact head: mark · name · state or gain · optional · ⓘ, on one line */
  .chead { display: flex; align-items: center; gap: var(--s-2); min-width: 0; }
  .name { flex: none; color: var(--text-strong); font-size: var(--fs-body); font-weight: var(--fw-semi); }
  .csub { flex: 1 1 auto; min-width: 0; color: var(--text-muted); font-size: var(--fs-small); white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; }
  .opt { flex: none; color: var(--text-label); font-size: var(--fs-label); }
</style>
