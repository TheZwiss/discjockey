<script lang="ts">
  // Setup, the short first-run guide (spec settings-setup §8, mockup design-system/settings.html "Setup"): built from
  // Settings' blocks in a ColumnFrame. The header (title, Finish later), the step strip (done ✓ · on screen ·
  // next · waiting), the step, and the foot: Back · why Continue is off · Continue. One filled button per screen:
  // the step's own main action until the step is done, then Continue.
  // Opens at #/setup/<next_step> (main.ts while a required step is open). A done setup has nothing to guide: arriving
  // at a step then opens its place in Settings (or Playlists) instead; finishing the guide keeps going to its end.
  import { untrack } from 'svelte';
  import { api } from '$lib/bridge/client';
  import type { ProblemKind, SetupStatus, SetupTools } from '$lib/bridge/types';
  import { Banner, Button, PageHeader, ProblemCard, Skeleton, StepStrip } from '$lib/components';
  import { ColumnFrame } from '$lib/frames';
  import { dataVersion, hub } from '$lib/stores/hub';
  import { go } from '$lib/router';
  import { markReady } from '$lib/ready';
  import StepDownloads from './StepDownloads.svelte';
  import StepExisting from './StepExisting.svelte';
  import StepFooter from './StepFooter.svelte';
  import StepMusic from './StepMusic.svelte';
  import StepPlaylists from './StepPlaylists.svelte';
  import StepSpotify from './StepSpotify.svelte';
  import StepTools from './StepTools.svelte';
  import {
    continueFilled, doneRedirect, firstStep, isStep, mustChooseMusic, neighbour, nextRule, stepsDone, stripSteps,
    type WizardStep,
  } from './setupModel';

  let { params }: { params: Record<string, string>; query: URLSearchParams } = $props();

  let status = $state<SetupStatus | null>(null);
  let loadError = $state<{ kind: ProblemKind; message: string } | null>(null);
  let tools = $state<SetupTools | null>(null);
  let toolsError = $state<string | null>(null);
  let checking = $state(false);
  let retry = $state(0);
  /** the step on screen waits for something it started (Spotify's browser login, a download sign-in): Back,
   *  Continue and the step strip wait too */
  let stepBusy = $state(false);
  let arrived = false;

  const asked = $derived<WizardStep | null>(isStep(params.step) ? params.step : null);
  // no music folder yet: the music step only, whatever the address says (the later steps read the library)
  const step = $derived<WizardStep | null>(status && mustChooseMusic(status) ? 'music'
    : asked ?? (status ? firstStep(status) : null));

  // only the newest answer counts
  let turn = 0;
  function loadStatus() {
    const t = ++turn;
    void api.setup_status().then((r) => {
      if (t !== turn) return;
      if (!r.ok) { loadError = { kind: r.kind, message: r.message }; markReady('setup'); return; }
      const { ok: _ok, ...s } = r;
      status = s;
      loadError = null;
      if (!arrived) {
        arrived = true;
        const to = doneRedirect(s, asked);
        if (to) { void go(to, { replace: true }); return; }
      }
      if (mustChooseMusic(s) && asked && asked !== 'music') void go('/setup/music', { replace: true });
      markReady('setup');
    });
  }
  function checkTools() {
    checking = true;
    void api.setup_check_tools().then((r) => {
      checking = false;
      if (r.ok) { const { ok: _ok, ...rest } = r; tools = rest; toolsError = null; } else toolsError = r.message;
    });
  }
  // a finished job reads the status again, and so does a job's start: an added folder counts for "Your existing
  // music" at once, not only when its import is through
  $effect(() => {
    void $dataVersion;
    void $hub.job?.id;
    void retry;
    untrack(loadStatus);
  });
  checkTools();

  const rule = $derived(status && step ? nextRule(step, status, tools) : { allowed: false, why: null });
  const back = $derived(step ? neighbour(step, -1) : null);
  /** the step after this one; none after the last, where Continue reads Finish and opens the Sync page */
  const onward = $derived(step ? neighbour(step, 1) : null);
  function goto(s: WizardStep | null) { if (s && s !== step) void go(`/setup/${s}`); }
  /** a step in the strip: not while the step on screen waits (Back is held for the same reason) */
  function pickStep(s: WizardStep) { if (!stepBusy) goto(s); }
  const finish = () => void go('/');
  /** Continue: on an optional step left undone it is the skip (Your existing music: setup_skip_import); a refused
   *  skip (another change runs) doesn't hold the user, the step stays open in the strip */
  async function onContinue() {
    if (step === 'existing' && status && !stepsDone(status).existing) {
      const r = await api.setup_skip_import();
      if (r.ok) loadStatus();
    }
    if (onward) goto(onward); else finish();
  }
</script>

{#snippet content()}
  <PageHeader title="Set up Discjockey">
    {#snippet actions()}
      <!-- nothing to go back to before a music folder is chosen -->
      {#if status && !mustChooseMusic(status)}
        <Button variant="link" muted onclick={finish} data-test="finish-later">Finish later</Button>
      {/if}
    {/snippet}
  </PageHeader>
  {#if status && step}
    <StepStrip steps={stripSteps(step, status)} onpick={pickStep} label="Setup steps" test="setup-steps" />
  {/if}
  {#if $hub.console_running}
    <Banner tone="warn" text="A Discjockey run in the terminal is busy. You can go on with setup when it has finished." />
  {/if}
  <div class="step" data-test="setup-step" data-step={step}>
    {#if loadError && !status}
      <ProblemCard kind={loadError.kind} message={loadError.message} onretry={() => retry++} />
    {:else if !status || !step}
      <div data-test="setup-loading"><Skeleton shape="card" height={160} /></div>
    {:else if step === 'music'}
      <StepMusic {status} />
    {:else if step === 'existing'}
      <StepExisting {status} />
    {:else if step === 'tools'}
      <StepTools {tools} error={toolsError} {checking} onrecheck={() => { checkTools(); loadStatus(); }} />
    {:else if step === 'spotify'}
      <StepSpotify {status} {tools} onchanged={loadStatus} bind:busy={stepBusy} />
    {:else if step === 'downloads'}
      <StepDownloads {status} bind:busy={stepBusy} />
    {:else}
      <StepPlaylists onchanged={loadStatus} />
    {/if}
  </div>
{/snippet}

{#snippet foot()}
  {#if status && step}
    <StepFooter onback={back ? () => goto(back) : null} backOff={stepBusy} why={stepBusy ? null : rule.why}
      allowed={rule.allowed && !stepBusy} filled={continueFilled(step, status, rule)} label={onward ? 'Continue' : 'Finish'}
      oncontinue={() => void onContinue()} />
  {/if}
{/snippet}

<div class="page" data-test="setup-page"><ColumnFrame {content} {foot} /></div>

<style>
  .page { height: 100vh; min-height: 0; background: var(--bg); color: var(--text); }
  .step { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
</style>
