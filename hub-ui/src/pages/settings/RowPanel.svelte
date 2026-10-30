<script lang="ts">
  // Settings' panel for the rows that aren't download accounts (spec settings-setup §3.2): Spotify (connected as,
  // Connect again, Sign out, the Client ID under Advanced), Programs (ffmpeg, ffprobe, deno; the download tools'
  // versions, their update and Go back), the music folder (Change… closes the app), About (the version, the licences) and the reports. Each card says its state first; the one filled button
  // of the panel is in the foot, and only when there is something to do.
  import { untrack } from 'svelte';
  import { get } from 'svelte/store';
  import { api, runJob } from '$lib/bridge/client';
  import type { ProblemKind, SetupStatus, SetupTools, ToolsChange } from '$lib/bridge/types';
  import {
    Button, CopyCode, ExternalLink, FolderField, Hint, KeyValue, NoteCard, ProblemCard, SecretField, Skeleton, Spinner, StatusMark, Surface, WriteButton,
    confirm,
  } from '$lib/components';
  import { Panel } from '$lib/frames';
  import { SAVED_MESSAGE, chooseFolder, isFail, useFolder } from '$lib/musicFolderFlow';
  import { go } from '$lib/router';
  import { hub } from '$lib/stores/hub';
  import { updateLink } from '$lib/appUpdate';
  import { waitForJob } from '$lib/stores/jobs';
  import { CLIENT_ID_BAD, TOOL_NAMES, TOOL_PURPOSE, checkClientId, takeSecret, toolFixes } from '../setup/setupModel';
  import {
    cardJob, needsReopen, reopenNote, spotifyState, spotifyUsed, toolsCard, updateOutcome, type SettingsRow,
  } from './settingsModel';

  // `toolsError`: reading the programs failed and there are no versions to show (the cards give way to a retry)
  let { row, status, tools, toolsError = null, reports, disabledWhy = null, onchanged, onrecheck }: {
    row: Exclude<SettingsRow, 'qobuz' | 'youtube' | 'soundcloud' | 'folders'>; status: SetupStatus | null;
    tools: SetupTools | null; toolsError?: { kind: ProblemKind; message: string } | null; reports: number | null;
    disabledWhy?: string | null; onchanged: () => void; onrecheck: () => void;
  } = $props();

  // ---- Spotify ----
  let connecting = $state(false);
  let spotifyError = $state<string | null>(null);
  let idEl = $state<HTMLInputElement | HTMLTextAreaElement>();
  let idOk = $state(false);
  let idError = $state<string | null>(null);
  let savingId = $state(false);

  async function connect() {
    connecting = true;
    spotifyError = null;
    const r = await runJob(api.setup_spotify_login(), { quiet: true, success: false });
    connecting = false;
    if (!r.ok && r.kind !== 'stopped') spotifyError = r.message;
    onchanged();
  }
  async function signOut() {
    const yes = await confirm({ title: 'Sign out of Spotify?', body: 'Discjockey stops reading your playlists until you '
      + 'connect again.', confirmLabel: 'Sign out', tone: 'danger' });
    if (!yes) return;
    spotifyError = null;
    const r = await runJob(api.spotify_sign_out(), { quiet: true });
    if (!r.ok && r.kind !== 'stopped') spotifyError = r.message;
    onchanged();
  }
  async function saveId() {
    const value = takeSecret(idEl).trim();
    idOk = false;
    if (checkClientId(value) !== 'ok') { idError = CLIENT_ID_BAD; return; }
    idError = null;
    savingId = true;
    const r = await runJob(api.setup_save_client_id(value), { quiet: true, success: false });
    savingId = false;
    if (!r.ok) idError = r.message;
    onchanged();
  }

  // ---- Programs ----
  let updating = $state(false);
  let goingBack = $state(false);
  let lines = $state<string[] | null>(null);
  let updateError = $state<string | null>(null);
  // the engine's answer to the last change: true when Discjockey has to be opened again to use it ("already the
  // newest" needs no reopen). The versions' own "waiting" comes with setup_check_tools; this covers the moment before
  // it is read again, or when reading it failed.
  let restart = $state(false);
  // which change asked for the reopen, so the note can say what starts being used
  let changeKind = $state<'update_tools' | 'rollback_tools' | null>(null);
  let quitting = $state(false);
  const card = $derived(toolsCard(tools?.download_tools));
  const reopen = $derived(needsReopen(card, restart));
  const reopenText = $derived(reopenNote(card.waiting, changeKind, quitting));
  function showUpdate(o: { lines: string[] | null; error: string | null; restart: boolean },
    kind: 'update_tools' | 'rollback_tools') {
    changeKind = kind;
    lines = o.lines;
    updateError = o.error;
    restart = o.restart;
  }
  async function change(kind: 'update_tools' | 'rollback_tools', start: () => ReturnType<typeof api.update_tools>,
    busy: (on: boolean) => void) {
    busy(true);
    updateError = null;
    lines = null;
    restart = false;
    const r = await runJob<ToolsChange>(start(), { quiet: true, success: false });
    busy(false);
    showUpdate(updateOutcome(r.ok ? { ok: true, result: r.result } : { ok: false, problem: r.kind, message: r.message }),
      kind);
    onrecheck();  // the versions, "waiting" and Go back come from setup_check_tools
  }
  const update = () => change('update_tools', () => api.update_tools(), (on) => (updating = on));
  async function goBack() {
    if (!card.back) return;
    const yes = await confirm({ title: `Go back to yt-dlp ${card.back}?`, body: 'Use this when downloads got worse '
      + 'after the last update. Discjockey uses the earlier version once you open it again.', confirmLabel: 'Go back' });
    if (yes) await change('rollback_tools', () => api.rollback_tools(), (on) => (goingBack = on));
  }
  async function quit() {
    quitting = true;
    const r = await api.quit();
    if (!r.ok) { quitting = false; updateError = r.message; }
  }

  // ---- About ----
  const aboutUpdate = $derived(updateLink($hub.app_update));
  let licencesError = $state<string | null>(null);
  async function openLicences() {
    licencesError = null;
    const r = await api.open_licenses();
    if (!r.ok) licencesError = r.message;
  }
  // ---- Music folder ----
  let changing = $state(false);
  let musicNote = $state<{ tone: 'info' | 'problem'; text: string } | null>(null);
  async function changeMusic() {
    musicNote = null;
    changing = true;
    const p = await chooseFolder(status?.music.path ?? null);
    const r = p === null ? 'cancelled' : isFail(p) ? p : await useFolder(p, { bound: true });
    changing = false;
    if (r === 'saved') musicNote = { tone: 'info', text: SAVED_MESSAGE };
    else if (isFail(r)) musicNote = { tone: 'problem', text: r.message };
  }
  async function showMusic() {
    const r = await api.reveal('.');
    musicNote = r.ok ? null : { tone: 'problem', text: r.message };
  }

  let revealError = $state<string | null>(null);
  async function openReports() {
    const r = await api.reveal('.discjockey/reports');
    revealError = r.ok ? null : r.message;
  }

  const off = $derived(!!disabledWhy);

  // A panel opened while its job runs, or after it ended elsewhere, picks it up (the job lives in the hub, the
  // panel only while its row is open): Spotify's browser login with its Cancel, the update or Go back with its
  // before → after lines and the Quit step.
  $effect(() => untrack(() => {
    let gone = false;
    const job = get(hub).job;
    const login = cardJob(job, 'setup_spotify_login');
    if (login?.running) {
      connecting = true;
      void waitForJob(login.id).then((fin) => {
        if (gone) return;
        connecting = false;
        if (!fin.ok && fin.problem !== 'stopped') spotifyError = fin.message;
        onchanged();
      });
    }
    for (const kind of ['update_tools', 'rollback_tools'] as const) {
      const own = cardJob(job, kind);
      const setBusy = (on: boolean) => { if (kind === 'update_tools') updating = on; else goingBack = on; };
      if (own?.running) {
        setBusy(true);
        void waitForJob(own.id).then((fin) => {
          if (!gone) { setBusy(false); showUpdate(updateOutcome(fin), kind); onrecheck(); }
        });
      } else if (own) showUpdate(updateOutcome(own.finished), kind);
    }
    return () => { gone = true; };
  }));
  const fixes = $derived(toolFixes(tools));
</script>

{#snippet spotifyHead()}
  <div class="col" data-test="settings-spotify">
    {#if !status}
      <Skeleton lines={3} />
    {:else}
      {@const sp = spotifyState(status, spotifyUsed($hub.read_status))}
      {@const tone = sp === 'connected' ? 'good' : sp === 'left_out' ? 'default' : 'problem'}
      <Surface kind="card" label="Spotify" {tone}>
        <div class="state">
          <StatusMark tone={sp === 'connected' ? 'good' : sp === 'left_out' ? 'none' : 'problem'} />
          <span class="strong" data-test="spotify-state">{sp === 'connected'
            ? (status.spotify_user ? `Connected as ${status.spotify_user}` : 'Connected')
            : sp === 'left_out' ? 'Left out' : sp === 'not_connected' ? 'Not connected' : 'Not set up'}</span>
        </div>
        <p class="note">{sp === 'left_out'
          ? "You chose I don't use Spotify in Setup. Connect it when a playlist of yours is on Spotify."
          : 'Discjockey reads your playlists from Spotify; it never changes them.'}</p>
        {#if connecting}
          <div class="state"><Spinner size={12} label="Waiting" /><span class="muted">Waiting for the Spotify login in
            your browser…</span></div>
          <div><Button size="sm" onclick={() => void api.stop()} data-test="spotify-cancel">Cancel</Button></div>
        {:else if status.spotify_login}
          <div class="row">
            <WriteButton size="sm" disabled={off} title={disabledWhy ?? undefined} onclick={connect}
              data-test="spotify-connect-again">Connect again</WriteButton>
            <span class="grow"></span>
            <Button variant="link" size="sm" disabled={off} onclick={signOut} data-test="spotify-sign-out">Sign out</Button>
          </div>
        {/if}
        {#if spotifyError}<NoteCard tone="problem">{spotifyError}</NoteCard>{/if}
      </Surface>
      {#if !status.spotify_app}
        <NoteCard title="The Spotify app comes first">Setup walks you through making it (a few minutes, once).
          <div class="row top"><Button variant="primary" size="sm" onclick={() => void go('/setup/spotify')}
            data-test="spotify-open-setup">Open setup</Button></div></NoteCard>
      {:else}
        <Surface kind="card" label="Spotify app (Client ID)" foldable open={false} data-test="spotify-advanced">
          <p class="note">Only when you made a new app in Spotify's developer dashboard.</p>
          <SecretField bind:el={idEl} type="text" mono placeholder="Client ID" label="Spotify Client ID"
            test="settings-client-id" oninput={(v) => { idOk = checkClientId(v) === 'ok'; idError = null; }}
            onenter={saveId} />
          {#if idError}<NoteCard tone="problem">{idError}</NoteCard>{/if}
          <div><WriteButton size="sm" busy={savingId} disabled={!idOk || off} onclick={saveId}
            data-test="settings-save-client-id">Save the Client ID</WriteButton></div>
        </Surface>
      {/if}
    {/if}
  </div>
{/snippet}

{#snippet programsHead()}
  <div class="col" data-test="settings-programs">
    {#if !tools && toolsError}
      <ProblemCard kind={toolsError.kind} message={toolsError.message} onretry={onrecheck} />
    {:else}
    <Surface kind="card" label="On this Mac">
      {#snippet header()}<Button variant="link" size="sm" onclick={onrecheck} data-test="programs-check">Check
        again</Button>{/snippet}
      {#if !tools}
        <Skeleton lines={3} />
      {:else}
        <div class="tools">
          {#each TOOL_NAMES as name (name)}
            {@const ok = tools.tools[name]}
            <div class="tool" data-test="tool-{name}">
              <StatusMark tone={ok ? 'good' : 'problem'} />
              <span class="two"><span class="strong">{name}</span><span class="note">{TOOL_PURPOSE[name]}</span></span>
            </div>
            <!-- one line per command, as Setup shows it: ffprobe comes with ffmpeg -->
            {#if fixes[name]}
              <div class="fix"><CopyCode text={fixes[name] ?? ''} test="tool-fix-{name}" /></div>
            {/if}
          {/each}
        </div>
        {#if tools.missing.length}
          <p class="note">Paste the line into the Terminal app and press Return; then Check again.</p>
        {/if}
      {/if}
    </Surface>
    <Surface kind="card" label="Download tools">
      {#if !tools}
        <Skeleton lines={2} />
      {:else}
        {#if tools.download_tools}
          <div class="facts" data-test="tool-versions">
            {#each card.rows as r (r.name)}<KeyValue plain keyWidth={80} k={r.name} v={r.value} />{/each}
          </div>
        {:else}
          <NoteCard tone="warn" data-test="tools-unread">{tools.download_tools_problem
            ?? "Discjockey couldn't read the download tools' versions. Check again in a moment."}</NoteCard>
        {/if}
        <p class="note">yt-dlp downloads from YouTube and SoundCloud: update it when those stop working. streamrip
          downloads from Qobuz and comes with Discjockey.</p>
        <!-- while a version waits for a reopen, Go back would only cancel it: reopen first -->
        {#if card.back && !card.waiting && !updating && !goingBack}
          <div><Button variant="link" size="sm" disabled={off} title={disabledWhy ?? undefined} onclick={goBack}
            data-test="tools-back">Go back to yt-dlp {card.back}</Button></div>
        {/if}
        {#if updating || goingBack}<div class="state"><Spinner size={12} label="Working" /><span class="muted"
          data-test="updating">{updating ? 'Updating… this can take a minute' : 'Going back…'}</span></div>{/if}
        {#if lines}
          <ul class="lines" data-test="update-lines">{#each lines as l (l)}<li>{l}</li>{/each}</ul>
        {/if}
        {#if reopen}
          <NoteCard title={reopenText.title} data-test="tools-waiting">{reopenText.text}</NoteCard>
        {/if}
        {#if updateError}<NoteCard tone="problem" data-test="update-error">{updateError}</NoteCard>{/if}
      {/if}
    </Surface>
    {/if}
  </div>
{/snippet}

{#snippet aboutHead()}
  <div class="col" data-test="settings-about">
    <Surface kind="card" label="About Discjockey">
      {#if status}
        <div class="state"><span class="strong" data-test="about-version">Version {status.version}</span></div>
        {#if aboutUpdate}
          <div class="state" data-test="about-update-link"><ExternalLink href={aboutUpdate.url}>{aboutUpdate.text}</ExternalLink></div>
          <p class="note">Drag the new Discjockey onto Applications: your music, logins and settings stay.</p>
        {:else if $hub.app_update?.state === 'up_to_date'}
          <div class="state"><span class="muted" data-test="about-update">Up to date</span></div>
        {/if}
      {:else}
        <div class="state wait"><Skeleton lines={1} width="40%" /></div>
      {/if}
      <p class="note">Free software under the GPL-3.0. It includes ffmpeg, deno, yt-dlp, streamrip and other parts,
        each under its own licence.</p>
      {#if licencesError}<NoteCard tone="problem">{licencesError}</NoteCard>{/if}
    </Surface>
  </div>
{/snippet}

{#snippet musicHead()}
  <div class="col" data-test="settings-music">
    <Surface kind="card" label="Music folder" tone={status?.music.state === 'ok' ? 'good' : 'default'}>
      {#if !status}<Skeleton lines={2} />{:else}
        <FolderField path={status.music.path} onchoose={changeMusic} label="Change…" busy={changing}
          disabledWhy={changing ? null : disabledWhy} test="music-folder" />
        <p class="note">Your music, its playlist folders and the sync reports. Change… closes Discjockey to use the new
          folder; your music stays where it is.</p>
        <div><Button variant="link" size="sm" onclick={showMusic} data-test="music-reveal">Show in Finder</Button></div>
        {#if musicNote}<NoteCard tone={musicNote.tone} data-test="music-note">{musicNote.text}</NoteCard>{/if}
      {/if}
    </Surface>
  </div>
{/snippet}

{#snippet reportsHead()}
  <div class="col" data-test="settings-reports">
    <Surface kind="card" label="Reports">
      <div class="state"><span class="strong">{reports === null ? '…' : reports === 0 ? 'No reports yet'
        : reports === 1 ? '1 sync report' : `${reports} sync reports`}</span></div>
      <p class="note">Every sync writes a report: what came in, from where, and what's still missing.</p>
      <div><Button variant="link" size="sm" onclick={() => void go('/runs')} data-test="settings-all-runs">See all runs
        →</Button></div>
      {#if revealError}<NoteCard tone="problem">{revealError}</NoteCard>{/if}
    </Surface>
  </div>
{/snippet}

{#snippet spotifyFoot()}
  <WriteButton variant="filled" wide busy={connecting} disabled={off} title={disabledWhy ?? undefined} onclick={connect}
    data-test="spotify-connect">Connect Spotify</WriteButton>
{/snippet}
{#snippet programsFoot()}
  <!-- a version waiting for the next start makes Quit the panel's one filled button -->
  {#if reopen}
    <Button variant="filled" wide busy={quitting} onclick={quit} data-test="quit">Quit Discjockey</Button>
  {:else}
    <WriteButton variant="filled" wide busy={updating} disabled={off || goingBack} title={disabledWhy ?? undefined}
      onclick={update} data-test="update-tools">Update download tools</WriteButton>
  {/if}
{/snippet}
{#snippet aboutFoot()}
  <Button wide onclick={openLicences} data-test="open-licenses">Show licences</Button>
{/snippet}
{#snippet reportsFoot()}
  <Button wide onclick={openReports} data-test="open-reports">Open the reports folder</Button>
{/snippet}
{#snippet why()}{#if disabledWhy}<Hint text={disabledWhy} />{/if}{/snippet}

{#if row === 'spotify'}
  <Panel head={spotifyHead} after={why}
    foot={status && status.spotify_app && !status.spotify_login && !connecting ? spotifyFoot : undefined} />
{:else if row === 'music'}
  <!-- no foot: a bound folder is nothing to do, and Change… sits on the folder it changes -->
  <Panel head={musicHead} />
{:else if row === 'programs'}
  <Panel head={programsHead} after={why} foot={programsFoot} />
{:else if row === 'about'}
  <Panel head={aboutHead} foot={aboutFoot} />
{:else}
  <Panel head={reportsHead} foot={reportsFoot} />
{/if}

<style>
  .col { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
  .state { display: flex; align-items: center; gap: var(--s-2); min-width: 0; }
  /* the version line's height, so the card does not change height when the status arrives */
  .wait { min-height: 19px; }
  .strong { color: var(--text-strong); }
  .muted { color: var(--text-muted); }
  .row { display: flex; align-items: center; gap: var(--s-2); }
  .row.top { margin-top: var(--s-2); }
  .grow { flex: 1; }
  .tools { display: flex; flex-direction: column; }
  .tool { display: grid; grid-template-columns: 16px minmax(0, 1fr); align-items: center; gap: var(--s-2);
    min-height: var(--h-row); padding: var(--s-1) 0; }
  .two { display: flex; flex-direction: column; min-width: 0; }
  /* a card's explanation: muted, wrapping (AccountPanel's sub line); a one-line Hint would cut it in the panel */
  .note { margin: 0; color: var(--text-muted); font-size: var(--fs-small); line-height: 1.45; overflow-wrap: anywhere; }
  .fix { padding-left: calc(16px + var(--s-2)); padding-bottom: var(--s-2); }
  .facts { display: flex; flex-direction: column; }
  .lines { margin: 0; padding-left: 18px; color: var(--text-strong); font-variant-numeric: tabular-nums;
    font-size: var(--fs-small); display: flex; flex-direction: column; gap: 2px; overflow-wrap: anywhere; }
</style>
