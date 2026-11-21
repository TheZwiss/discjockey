<script lang="ts">
  // While a sync runs (design system §8 Running), on ColumnFrame: the page header, the run's progress card ("Track 4
  // of 6", its bar, time left and today's usage, said only here), the live card, the result lists (RunList), and Stop
  // safely in the foot with its hint, or in red the reason a stop failed.
  // While stopping, the title is the one "Stopping…": the time left, the hint and the busy button's words go.
  // The run's numbers sit in their own card under the title instead of the title's status line: a quantity is a
  // number plus a visual (§4), and the status line has no room for a bar.
  // The sync's last phase, Auto-upgrade (issue 33 stage C): no download is in work, so the card says the batch's
  // progress in stage B's words ("3 of 8 done" over "Upgrading · Artist - Title", the bar in the accent: the live card
  // that carried it is not there) in place of "Track x of y", and the live card gives way to it. The time left goes
  // (it counted downloads); the Qobuz count stays.
  // The same view shows a sync the Terminal runs (issue 39 E4b, `source`: liveSource.ts): its header's status line
  // says "In the Terminal", Stop safely stops that job and stays busy until the job says it is stopping, and the
  // view says the console state in its body, so the shell's banner doesn't repeat it. While a Terminal sync joined
  // late is still being read, the progress card says so and the live card and lists wait for what it is.
  import { estimateText } from '$lib/format';
  import { onMount } from 'svelte';
  import { Button, Hint, PageHeader, ProgressBar, Surface } from '$lib/components';
  import { ColumnFrame } from '$lib/frames';
  import { api } from '$lib/bridge/client';
  import { hub } from '$lib/stores/hub';
  import { sayInBody } from '$lib/stores/shell';
  import { latestOnly } from '$lib/latest';
  import { markReady } from '$lib/ready';
  import { cardState, liveUsage, qobuzFallback, upgradeProgress } from './cardState';
  import { minutesLeft, pickedOf, type Picked } from './selection';
  import { coverMap, liveMessage } from './results';
  import SyncCard from './SyncCard.svelte';
  import RunList from './RunList.svelte';
  import { JOINING, joining, selectionOf, type LiveSource } from './liveSource';

  let { source }: { source: LiveSource } = $props();
  const run = $derived(source.run);
  let now = $state(Date.now());
  let qobuzToday = $state<{ used: number; allowance: number } | null>(null);
  let stopError = $state<string | null>(null);
  let asking = $state(false);
  // a Terminal sync's Stop was asked: busy until its job says it is stopping (no mark of the window's own)
  let stopSent = $state(false);
  // The songs the sync was started with: the engine's record of what was ticked (`last_sync`) named in the plan it was
  // ticked from. It stands in for the run's own plan until that arrives (`$run.planned` wins as the list) and always
  // gives the covers: the artwork of a track's own file is in the plan's rows only, not in the run's events
  // (`coverMap`). One preview per started sync.
  let selection = $state<Picked[]>([]);
  const previews = latestOnly();
  let asked: string | null = null;
  $effect(() => {
    const last = selectionOf(source, $hub.last_sync, $hub.job?.kind === 'sync' ? $hub.job.id : null);
    if (!last || asked === last.job) return;
    asked = last.job;
    const ticket = previews.next();
    void api.sync_preview().then((r) => {
      if (previews.isLatest(ticket) && r.ok) selection = pickedOf(r, last.args.selected);
    });
  });

  onMount(() => {
    markReady('sync');
    const t = setInterval(() => { now = Date.now(); }, 250);
    void api.dashboard().then((d) => {
      if (d.ok) qobuzToday = qobuzFallback(d.tiles);
    });
    return () => clearInterval(t);
  });

  const card = $derived(cardState($run, now, qobuzToday));
  const covers = $derived(coverMap(selection, $run.planned));
  const plan = $derived($run.planned.length ? $run.planned : selection);
  const done = $derived($run.results.map((r) => r.action.track_id));
  const left = $derived(minutesLeft(plan, done));
  const known = $derived($run.total !== null);
  // a Stop in the phase keeps the batch's words (the run store keeps following it)
  const batch = $derived($run.upgrade && ($run.phase === 'upgrading' || $run.phase === 'stopping')
    ? upgradeProgress($run.upgrade) : null);
  const position = $derived(batch ? batch.position
    : $run.total === null ? null : `Track ${Math.max($run.index, 1)} of ${$run.total}`);
  // the bar counts finished actions, so it reaches the end when the last one is done, not when it starts
  const share = $derived(batch ? batch.share : $run.total ? Math.min(1, $run.results.length / $run.total) : null);
  const message = $derived(batch ? batch.message : liveMessage($run));
  // the "Getting ready" card says the last info message itself (a state is shown once, §11): the line stays for any other (a warning)
  const showMessage = $derived(message !== null && !(card.kind === 'preparing' && card.text === message));
  const stopping = $derived($run.phase === 'stopping');
  const catchingUp = $derived(joining(source, $run));
  // only a Terminal sync's view says the console state (its header); the own one leaves the banner as it was
  $effect(() => { if (source.kind === 'terminal') return sayInBody({ console: true }); });
  const stats = $derived([...(left !== null && known && !stopping && !batch ? [`${estimateText(left)} left`] : []),
    ...(known ? liveUsage(qobuzToday, $run.usage) : [])]);

  async function stop() {
    asking = true;
    stopError = null;
    const r = await source.stop();
    asking = false;
    if (r.ok) stopSent = r.waits;
    else stopError = r.message;
  }
</script>

{#snippet content()}
  <PageHeader title={stopping ? 'Stopping…' : 'Sync running'} sub={source.where} />
  <Surface kind="card" data-test="sync-progress">
    <div class="prog">
      <span class="pos" data-test="sync-position">{#if position}{position}{:else}<span class="muted">{catchingUp ? JOINING : 'Counting tracks…'}</span>{/if}</span>
      {#each stats as s (s)}<span class="stat">{s}</span>{/each}
    </div>
    <!-- muted: the live card's own bars carry the accent; the run's bar is context (§11, Task 10B fix round 1) -->
    <ProgressBar value={share} tone={batch ? 'accent' : 'muted'} pace="live" label={batch ? 'Upgrading' : 'Sync progress'} />
    {#if showMessage}<p class="message" data-test="sync-message" title={message}>{message}</p>{/if}
  </Surface>
  {#if !catchingUp}
    {#if card.kind !== 'upgrading'}<SyncCard {card} {covers} />{/if}
    <RunList {run} {selection} />
  {/if}
{/snippet}

{#snippet foot()}
  <div class="stop" data-test="sync-stop-footer">
    {#if stopError}
      <!-- an error, so it reads and is announced as one (apple-design §16), not as a grey hint -->
      <Hint text={stopError} tone="problem" data-test="stop-error" />
    {:else if !stopping}
      <Hint text="Stopping is safe at any time" data-test="stop-hint" />
    {/if}
    <!-- busy only for the click's round trip (a Terminal sync's: until its job says it is stopping); once stopping, the
         title and the card's spinner say it and the button is off (a state is shown once, §11) -->
    <Button variant="secondary" busy={asking || (stopSent && !stopping)} disabled={stopping} onclick={stop}
      title="The current track is finished or cleanly discarded" data-test="stop-safely">Stop safely</Button>
  </div>
{/snippet}

<div class="live" data-test="sync-live"><ColumnFrame {content} {foot} /></div>

<style>
  .live { flex: 1; min-height: 0; display: flex; flex-direction: column; }
  /* "4 of 6" leads; the time left and Qobuz usage follow as small numbers, the last one at the card's right edge */
  .prog { display: flex; align-items: baseline; gap: var(--s-4); min-width: 0; }
  .pos { flex: 1 1 auto; min-width: 0; font-size: var(--fs-title); font-weight: var(--fw-bold); color: var(--text-strong);
    font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .muted { font-size: var(--fs-body); font-weight: var(--fw-medium); color: var(--text-muted); }
  .stat { flex: none; font-size: var(--fs-small); color: var(--text-muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .message { margin: 0; font-size: var(--fs-small); color: var(--text-muted); white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; }
  /* the hint sits right beside the button it explains, both at the foot's right edge (grouping by proximity) */
  .stop { margin-left: auto; display: flex; align-items: center; gap: var(--s-3); min-width: 0; }
</style>
