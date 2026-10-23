<script lang="ts">
  // While a sync runs (design system §8 Running), on ColumnFrame: the page header, the run's progress card ("Track 4
  // of 6", its bar, time left and today's usage, said only here), the live card, the result lists (RunList), and Stop
  // safely in the foot with its hint, or in red the reason a stop failed.
  // While stopping, the title is the one "Stopping…": the time left, the hint and the busy button's words go.
  // The run's numbers sit in their own card under the title instead of the title's status line: a quantity is a
  // number plus a visual (§4), and the status line has no room for a bar.
  import { estimateText } from '$lib/format';
  import { onMount } from 'svelte';
  import { Button, Hint, PageHeader, ProgressBar, Surface } from '$lib/components';
  import { ColumnFrame } from '$lib/frames';
  import { api } from '$lib/bridge/client';
  import { markStopping, run } from '$lib/stores/run';
  import { getPref } from '$lib/prefs';
  import { markReady } from '$lib/ready';
  import { cardState, liveUsage, qobuzFallback } from './cardState';
  import { PREF_LAST_SELECTION, minutesLeft, type Picked } from './selection';
  import { liveMessage } from './results';
  import SyncCard from './SyncCard.svelte';
  import RunList from './RunList.svelte';

  let now = $state(Date.now());
  let qobuzToday = $state<{ used: number; allowance: number } | null>(null);
  let stopError = $state<string | null>(null);
  let asking = $state(false);
  const selection = getPref<Picked[]>(PREF_LAST_SELECTION, []);

  onMount(() => {
    markReady('sync');
    const t = setInterval(() => { now = Date.now(); }, 250);
    void api.dashboard().then((d) => {
      if (d.ok) qobuzToday = qobuzFallback(d.tiles);
    });
    return () => clearInterval(t);
  });

  const card = $derived(cardState($run, now, qobuzToday));
  const plan = $derived($run.planned.length ? $run.planned : selection);
  const done = $derived($run.results.map((r) => r.action.track_id));
  const left = $derived(minutesLeft(plan, done));
  const known = $derived($run.total !== null);
  const position = $derived($run.total === null ? null : `Track ${Math.max($run.index, 1)} of ${$run.total}`);
  // the bar counts finished actions, so it reaches the end when the last one is done, not when it starts
  const share = $derived($run.total ? Math.min(1, $run.results.length / $run.total) : null);
  const message = $derived(liveMessage($run));
  const stopping = $derived($run.phase === 'stopping');
  const stats = $derived([...(left !== null && known && !stopping ? [`${estimateText(left)} left`] : []),
    ...(known ? liveUsage(qobuzToday, $run.usage) : [])]);

  async function stop() {
    asking = true;
    stopError = null;
    const r = await api.stop();
    asking = false;
    if (r.ok && r.stopped) markStopping();
    else if (!r.ok) stopError = r.message;
  }
</script>

{#snippet content()}
  <PageHeader title={stopping ? 'Stopping…' : 'Sync running'} />
  <Surface kind="card" data-test="sync-progress">
    <div class="prog">
      <span class="pos" data-test="sync-position">{#if position}{position}{:else}<span class="muted">Counting tracks…</span>{/if}</span>
      {#each stats as s (s)}<span class="stat">{s}</span>{/each}
    </div>
    <!-- muted: the live card's own bars carry the accent; the run's bar is context (§11, Task 10B fix round 1) -->
    <ProgressBar value={share} tone="muted" pace="live" label="Sync progress" />
    {#if message}<p class="message" data-test="sync-message" title={message}>{message}</p>{/if}
  </Surface>
  <SyncCard {card} />
  <RunList />
{/snippet}

{#snippet foot()}
  <div class="stop" data-test="sync-stop-footer">
    {#if stopError}
      <!-- an error, so it reads and is announced as one (apple-design §16), not as a grey hint -->
      <Hint text={stopError} tone="problem" data-test="stop-error" />
    {:else if !stopping}
      <Hint text="Stopping is safe at any time" data-test="stop-hint" />
    {/if}
    <!-- busy only for the click's round trip; once stopping, the title and the card's spinner say it and the button
         is off (a state is shown once, §11) -->
    <Button variant="secondary" busy={asking} disabled={stopping} onclick={stop}
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
