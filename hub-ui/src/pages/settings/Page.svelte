<script lang="ts">
  // Settings (spec settings-setup §3, mockup design-system/settings.html): the one home for every login and option.
  // The main column answers "where does my music come from?" first (the source ladder, its rungs lit by what is
  // signed in), then lists every setting in three groups, each row with the one line that says its state. The panel
  // is the selected row: an AccountPanel for the download services (what the login gives, its state, the sign-in),
  // a RowPanel for the rest. `#/settings` opens the first row that needs the user. A click on a ladder rung or chip
  // opens its row, so the ladder doubles as a map of the settings below it.
  import { untrack } from 'svelte';
  import { api } from '$lib/bridge/client';
  import type { DownloadsView, ProblemKind, SetupTools } from '$lib/bridge/types';
  import {
    AccountFlow, AccountPanel, ListRow, ListSection, PageHeader, ProblemCard, Skeleton, SourceLadder, StatusMark,
    Surface, WatchedFoldersFlow, accountBlocked,
  } from '$lib/components';
  import { ListPanelFrame } from '$lib/frames';
  import { go } from '$lib/router';
  import { bumpData, dataVersion, hub, writeBlockedReason } from '$lib/stores/hub';
  import { markReady } from '$lib/ready';
  import { sayInBody } from '$lib/stores/shell';
  import FoldersPanel from './FoldersPanel.svelte';
  import RowPanel from './RowPanel.svelte';
  import {
    ROW_GLYPHS, ROW_GROUPS, ROW_NAMES, firstAttention, isAccountRow, isSettingsRow, rowLine, spotifyUsed, type RowContext,
    type SettingsRow,
  } from './settingsModel';

  let { params }: { params: Record<string, string>; query: URLSearchParams } = $props();

  const row = $derived<SettingsRow | null>(isSettingsRow(params.row) ? params.row : null);

  let downloads = $state<DownloadsView | null>(null);
  let downloadsError = $state<{ kind: ProblemKind; message: string } | null>(null);
  let tools = $state<SetupTools | null>(null);
  let toolsError = $state<{ kind: ProblemKind; message: string } | null>(null);
  let reports = $state<number | null>(null);
  let retry = $state(0);
  let ready = false;

  // only the newest answer of each read counts
  let turn = 0;
  function load() {
    const t = ++turn;
    if (!tools) toolsError = null;  // Try again shows the skeleton until it answers
    void Promise.all([api.downloads_view(), api.setup_check_tools(), api.runs()]).then(([d, tl, r]) => {
      if (t !== turn) return;
      if (d.ok) { downloads = d.downloads; downloadsError = null; } else downloadsError = { kind: d.kind, message: d.message };
      if (tl.ok) { const { ok: _ok, ...rest } = tl; tools = rest; toolsError = null; }
      else toolsError = { kind: tl.kind, message: tl.message };
      if (r.ok) reports = r.runs.length;
      if (!ready) { ready = true; markReady('settings'); }
    });
  }
  $effect(() => {
    void $dataVersion;
    void retry;
    untrack(load);
  });

  // a finished job (a sign-in, a check, a sign-out) bumps dataVersion, which reads everything again; changes that
  // aren't jobs (Qobuz "I don't have Qobuz") poke it the same way
  const changed = () => bumpData();
  const flows = { qobuz: new AccountFlow('qobuz', changed), youtube: new AccountFlow('youtube', changed),
    soundcloud: new AccountFlow('soundcloud', changed) };
  // the shown account's flow looks for logins and follows its sign-in; leaving the row stops following
  $effect(() => {
    const r = row;
    if (!r || !isAccountRow(r)) return;
    return untrack(() => flows[r].mount());
  });

  // the watched folders: read here, so the row's line follows the import while another row is open
  const folders = new WatchedFoldersFlow();
  $effect(() => untrack(() => folders.mount()));

  const ctx = $derived<RowContext>({ downloads, status: $hub.setup, tools, reports, now: new Date(), toolsFailed: !tools && !!toolsError,
    spotifyUsed: spotifyUsed($hub.read_status),
    update: $hub.app_update, folders: folders.data, job: $hub.job });
  // #/settings: the first row that needs the user, once everything it depends on has answered
  $effect(() => {
    if (row) return;
    const c = ctx;
    const known = (c.downloads || downloadsError) && c.status && (c.tools || toolsError);
    if (known) untrack(() => void go(`/settings/${firstAttention(c)}`, { replace: true }));
  });

  // the Spotify panel says Spotify's state and offers Connect itself, so the shell's banner stays off there
  $effect(() => { if (row === 'spotify') return sayInBody({ readStatus: true }); });

  const blockedAccount = $derived(accountBlocked($hub));
  const open = (r: SettingsRow) => { if (r !== row) void go(`/settings/${r}`); };
</script>

{#snippet main()}
  <PageHeader title="Settings" />
  {#if downloadsError && !downloads}
    <ProblemCard kind={downloadsError.kind} message={downloadsError.message} onretry={() => retry++} />
  {:else}
    <SourceLadder {downloads} onpick={open} test="settings-ladder" />
  {/if}
  <Surface kind="list" style="--row-cols: 20px minmax(0, 1fr) 16px" data-test="settings-list">
    {#each ROW_GROUPS as g (g.label)}
      <ListSection label={g.label} test="settings-group-{g.label}" />
      {#each g.rows as r (r)}
        {@const line = rowLine(r, ctx)}
        <ListRow height={52} selected={r === row} onclick={() => open(r)} test="settings-row-{r}">
          {#snippet lead()}<span class="glyph">{ROW_GLYPHS[r]}</span>{/snippet}
          {#snippet name()}{ROW_NAMES[r]}{/snippet}
          {#snippet sub()}{#if line.text}{line.text}{:else}<Skeleton height={10} width="140px" />{/if}{/snippet}
          {#snippet trailing()}{#if line.tone}<StatusMark tone={line.tone} />{/if}{/snippet}
        </ListRow>
      {/each}
    {/each}
  </Surface>
{/snippet}

{#snippet side()}
  {#if row && isAccountRow(row)}
    {@const flow = flows[row]}
    {#key row}
      <AccountPanel service={row} {downloads} phase={flow.phase(downloads)} actions={flow} logins={flow.logins}
        busy={flow.busy} disabledWhy={blockedAccount} test="settings-panel-{row}" />
    {/key}
  {:else if row === 'folders'}
    <FoldersPanel flow={folders} />
  {:else if row}
    <RowPanel {row} status={$hub.setup} {tools} {toolsError} {reports} disabledWhy={$writeBlockedReason} onchanged={changed}
      onrecheck={load} />
  {/if}
{/snippet}

<div class="page" data-test="settings-page"><ListPanelFrame {main} panel={row ? side : null}
  emptyPanel="Pick a setting to see it." /></div>

<style>
  .page { height: 100%; min-height: 0; }
  /* the sidebar's glyph box: mixed glyphs in one 14 px box line up optically, dimmed like a label */
  .glyph { display: inline-block; width: 14px; text-align: center; font-size: var(--fs-small); color: var(--text-muted); }
</style>
