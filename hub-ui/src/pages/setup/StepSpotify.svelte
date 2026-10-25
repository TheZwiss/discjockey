<script lang="ts">
  // Step 2, Spotify (spec settings-setup §7.2): the free Spotify app as numbered rows (the dashboard, Create app, the
  // redirect address to copy, Web API, the Client ID), then Connect: the login in the system browser, which comes back
  // by itself. Connect is the screen's filled button until Spotify is connected or left out; then Continue is.
  // "I don't use Spotify" (plan stage 3, D1, like the Qobuz card's skip) counts the step as done; the steps and
  // Connect stay, so Spotify can still be connected here or in Settings.
  // The Client ID stays in its SecretField until Connect sends it (takeSecret); the page keeps only the live check.
  import { onDestroy } from 'svelte';
  import { api, runJob } from '$lib/bridge/client';
  import type { SetupStatus, SetupTools } from '$lib/bridge/types';
  import {
    Button, CopyCode, ExternalLink, Hint, NoteCard, NumberedSteps, SecretField, Spinner, StatusMark, Surface, WriteButton,
  } from '$lib/components';
  import { problemCopy, detailLine } from '$lib/copy';
  import { CLIENT_ID_BAD, checkClientId, stepsDone, takeSecret, type ClientIdCheck } from './setupModel';

  let { status, tools, onchanged, busy = $bindable(false) }: {
    status: SetupStatus; tools: SetupTools | null; onchanged: () => void; busy?: boolean;
  } = $props();

  type Phase = 'form' | 'saving' | 'waiting' | 'failed' | 'cancelled';
  const DASHBOARD = 'https://developer.spotify.com/dashboard';
  let phase = $state<Phase>('form');
  let idCheck = $state<ClientIdCheck>('empty');
  let idEl = $state<HTMLInputElement | HTMLTextAreaElement>();
  let otherId = $state(false);
  let failTitle = $state('');
  let failMessage = $state('');
  let fieldError = $state<string | null>(null);
  let alive = true;
  onDestroy(() => { alive = false; });

  const done = $derived(stepsDone(status).spotify);
  const connected = $derived(status.spotify_app && status.spotify_login);
  // "I don't use Spotify" (plan stage 3, D1): the step counts as done; Connect stays here and in Settings for later
  const skipped = $derived(status.spotify_skipped && !connected);
  let skipping = $state(false);
  const askId = $derived(!status.spotify_app || otherId);
  const redirect = $derived(tools?.redirect_uri ?? 'http://127.0.0.1:8888/callback');
  $effect(() => { busy = phase === 'saving' || phase === 'waiting' || skipping; });
  // the one filled button: Connect while Spotify isn't connected; once it is, Continue (Connect again stays quiet)
  const connectFilled = $derived(!done);

  async function connect() {
    fieldError = null;
    if (askId) {
      if (idCheck !== 'ok') { fieldError = idCheck === 'empty' ? 'Paste the Client ID first.' : CLIENT_ID_BAD; return; }
      phase = 'saving';
      const id = takeSecret(idEl).trim();
      idCheck = 'empty';
      const saved = await runJob(api.setup_save_client_id(id), { quiet: true, success: false });
      if (!alive) return;
      if (!saved.ok) { phase = 'form'; fieldError = saved.message; return; }
      otherId = false;
      onchanged();
    }
    phase = 'waiting';
    const r = await runJob<{ user: string }>(api.setup_spotify_login(), { quiet: true, success: false });
    onchanged();
    if (!alive) return;
    if (r.ok) { phase = 'form'; return; }
    if (r.kind === 'stopped') { phase = 'cancelled'; return; }
    failTitle = r.kind === 'login_failed' ? "The Spotify login didn't work." : problemCopy(r.kind).title;
    failMessage = r.message;
    phase = 'failed';
  }
  async function skip() {
    if (skipping) return;
    skipping = true;
    const r = await runJob(api.setup_skip_spotify(), { quiet: true, success: false });
    skipping = false;
    onchanged();
    if (!alive || r.ok) return;
    failTitle = problemCopy(r.kind).title;
    failMessage = r.message;
    phase = 'failed';
  }
  const failDetail = $derived(detailLine(failMessage, failTitle));
</script>

<Surface kind="card" label="Spotify" summary="Discjockey only reads your playlists; it never changes them."
  tone={connected ? 'good' : 'default'} data-test="spotify-card">
  <div class="state" data-test="spotify-state">
    {#if phase === 'waiting'}
      <Spinner size={12} label="Waiting for Spotify" />
      <span data-test="spotify-waiting">Your browser opened. Log in to Spotify there; Discjockey goes on by itself.</span>
    {:else if skipped}
      <StatusMark tone="none" />
      <span data-test="spotify-skipped"><span class="strong">Left out.</span> Connect it here or in Settings when a
        playlist of yours is on Spotify.</span>
    {:else if connected}
      <StatusMark tone="good" />
      <span class="strong" data-test="spotify-connected">{status.spotify_user ? `Connected as ${status.spotify_user}` : 'Connected'}</span>
    {:else if status.spotify_app}
      <StatusMark tone="none" /><span>Your Spotify app is ready. Connect to log in.</span>
    {:else}
      <StatusMark tone="none" /><span>Not set up. It needs a free Spotify app, once (about 2 minutes).</span>
    {/if}
  </div>

  {#if askId && phase !== 'waiting'}
    <div class="steps">
      <NumberedSteps test="spotify-steps">
        <li><span>Open Spotify's developer dashboard and log in.</span>
          <div><ExternalLink href={DASHBOARD} label="Open the dashboard" /></div></li>
        <li><span>Click <b>Create app</b>. Give it any name, for example <b>Discjockey</b>.</span></li>
        <li><span>Add this <b>Redirect URI</b>:</span><div class="field"><CopyCode text={redirect} test="redirect-uri" /></div></li>
        <li><span>Tick <b>Web API</b>, accept the terms and click <b>Save</b>.</span></li>
        <li><span>Copy the app's <b>Client ID</b> and paste it here:</span>
          <div class="field">
            <SecretField bind:el={idEl} type="text" mono placeholder="Client ID" label="Spotify Client ID" test="client-id"
              tone={idCheck === 'ok' ? 'ok' : idCheck === 'bad' ? 'bad' : null}
              oninput={(v) => { idCheck = checkClientId(v); fieldError = null; }} onenter={connect} />
            {#if fieldError}<Hint tone="problem" text={fieldError} data-test="client-id-error" />
            {:else if idCheck === 'bad'}<Hint text={CLIENT_ID_BAD} />
            {:else}<Hint text="New Spotify apps need a Premium account (yours)." />{/if}
          </div></li>
      </NumberedSteps>
    </div>
  {/if}

  {#if phase === 'failed'}
    <NoteCard tone="problem" title={failTitle} data-test="spotify-failed">{#if failDetail}{failDetail}{/if}</NoteCard>
  {/if}

  <div class="actions">
    {#if phase === 'waiting'}
      <Button onclick={() => void api.stop()} data-test="spotify-cancel">Cancel</Button>
      <Hint text="Stops waiting after 5 minutes." />
    {:else}
      <WriteButton variant={connectFilled ? 'filled' : 'secondary'} busy={phase === 'saving'} disabled={skipping}
        onclick={connect} data-test="spotify-login">{phase === 'failed' ? 'Try again' : connected ? 'Connect again'
          : 'Connect'}</WriteButton>
      {#if phase === 'cancelled'}<Hint text="Cancelled." data-test="spotify-cancelled" />
      {:else if !done}<Hint text="Your browser opens to log in to Spotify, then Discjockey comes back here." />{/if}
      <span class="push"></span>
      {#if status.spotify_app && !askId}
        <Button variant="link" muted size="sm" onclick={() => (otherId = true)} data-test="other-client-id">Use another
          Client ID</Button>
      {/if}
      <!-- the Qobuz card's "I don't have Qobuz", in the same voice and place: a muted link at the actions' end -->
      {#if !connected && !status.spotify_skipped}
        <WriteButton variant="link" muted size="sm" disabled={skipping || phase === 'saving'} onclick={skip}
          data-test="spotify-skip">I don't use Spotify</WriteButton>
      {/if}
    {/if}
  </div>
</Surface>

<style>
  .state { display: flex; align-items: center; gap: var(--s-2); min-height: 20px; color: var(--text); }
  .strong { color: var(--text-strong); font-weight: var(--fw-semi); }
  .steps { margin-top: var(--s-4); }
  .steps :global(b) { color: var(--text-strong); font-weight: var(--fw-semi); }
  /* the controls in the steps share one width, so the copy line and the Client ID field end on the same edge */
  .field { display: flex; flex-direction: column; gap: var(--s-1); max-width: 420px; }
  .actions { display: flex; align-items: center; gap: var(--s-3); margin-top: var(--s-4); min-width: 0; }
  .push { flex: 1; }
</style>
