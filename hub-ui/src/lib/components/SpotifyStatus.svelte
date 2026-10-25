<script lang="ts">
  // "Playlists read 2 min ago  [↻ Read playlists]" (reads hub.spotify, the read status of every playlist service;
  // the wire and this block keep the Spotify name until stage 5 rebuilds the slot, plan stage 3 D2). While reading: a
  // spinner, "Reading · 3 of 7" and Stop. Stop ends the read at once (the backend's JobFinished comes right away);
  // then "Stopped reading." until the next read. The button is disabled during the hub's own sync.
  // Placed only by PageHeader's `spotify` slot (design system §5a; the rules checker fails it anywhere else).
  // `inBody`: the page shows the read in progress and the read's problems as cards in its body (Sync before the
  // start), so the slot says neither again: while reading it holds only "Stop reading", otherwise the last read and
  // Read playlists without the OFFLINE badge or the compact problem line. The control always stays in the slot.
  // While a service playlists.txt uses can't be read (not connected, login expired) the shell's banner says so with its
  // Connect link, so the slot doesn't repeat it: only the last read, if any, and Read playlists disabled with
  // "Connect Qobuz first." as its reason (§5a: a state said once).
  import { api, runJob } from '../bridge/client';
  import { hub, hubSyncRunning, bumpData, readBlock, readBlockIn } from '../stores/hub';
  import { PLAYLIST_SERVICE_NAMES } from '../copy';
  import { ago } from '../format';
  import Badge from './Badge.svelte';
  import Button from './Button.svelte';
  import ProblemCard from './ProblemCard.svelte';
  import Skeleton from './Skeleton.svelte';
  import Spinner from './Spinner.svelte';
  import type { SpotifyStatus } from '../bridge/types';

  // `status` only for the gallery: shows a given state instead of the live one
  let { status, inBody = false }: { status?: SpotifyStatus | null; inBody?: boolean } = $props();

  let now = $state(Date.now());
  $effect(() => { const t = setInterval(() => (now = Date.now()), 30_000); return () => clearInterval(t); });
  const sp = $derived(status !== undefined ? status : $hub.spotify);
  const reading = $derived(!!sp?.reading || (status === undefined && $hub.refresh_running));
  const progress = $derived(status === undefined ? $hub.read_progress : null);
  const minutes = $derived(sp?.read_at ? (now - Date.parse(sp.read_at)) / 60000 : sp?.minutes_ago ?? null);
  const when = $derived(sp?.read_at ? `Playlists read ${ago(minutes)}` : "Playlists haven't been read yet");
  const block = $derived(status !== undefined ? readBlockIn(status) : $readBlock);
  const problem = $derived(sp?.problem && !sp.offline && sp.problem !== 'offline' && !block ? sp.problem : null);
  const blocked = $derived(block ? `Connect ${PLAYLIST_SERVICE_NAMES[block.service]} first.`
    : $hubSyncRunning ? 'Not while a sync runs.' : undefined);
  const stopped = $derived(status === undefined && $hub.read_stopped);

  function read() { void runJob(api.refresh(), { success: false, quiet: true }); }
  async function stop() { const r = await api.stop_refresh(); if (r.ok) bumpData(); }
</script>

<span class="sp" data-test="spotify-status" data-spotify-status>
  {#if !sp}
    <span class="sk"><Skeleton height={10} width="140px" /></span>
  {:else if reading && inBody}
    <Button size="sm" variant="secondary" onclick={stop} data-test="spotify-stop">Stop reading</Button>
  {:else if reading}
    <span class="txt reading" data-test="spotify-reading"><Spinner size={10} label="Reading playlists" />
      Reading{progress ? ` · ${progress.index} of ${progress.total}` : ' playlists…'}</span>
    <Button size="sm" variant="secondary" onclick={stop} data-test="spotify-stop">Stop reading</Button>
  {:else if problem && !inBody}
    <ProblemCard kind={problem} message={sp.message} service={sp.problem_service} compact />
  {:else}
    {#if sp.offline && !inBody}<Badge tone="muted" text="OFFLINE" />{/if}
    {#if stopped}<span class="txt" data-test="spotify-stopped">Stopped reading.</span>{/if}
    {#if !block || sp.read_at}
      <span class="txt" data-test="spotify-when">{sp.stale && !sp.offline ? 'Your playlists changed since.' : when}</span>
    {/if}
    <Button size="sm" disabled={!!blocked} title={blocked}
      onclick={read} data-test="spotify-read">↻ Read playlists</Button>
  {/if}
</span>

<style>
  .sp { display: inline-flex; align-items: center; gap: var(--s-2); color: var(--text-label); font-size: var(--fs-small);
    font-weight: 400; white-space: nowrap; }
  .sk { width: 140px; display: inline-block; }
  .reading { display: inline-flex; align-items: center; gap: 6px; color: var(--accent-text); font-weight: var(--fw-semi); }
</style>
