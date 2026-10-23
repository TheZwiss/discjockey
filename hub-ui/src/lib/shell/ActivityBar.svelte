<script lang="ts">
  // While the hub's own sync runs, on every screen except Sync (which shows the same in its header).
  import { run } from '../stores/run';
  import { activityText, activityProgress } from './activity';
  import { link } from '../router';

  let now = $state(Date.now());
  $effect(() => { const t = setInterval(() => (now = Date.now()), 250); return () => clearInterval(t); });
  const a = $derived(activityText($run, now));
  const p = $derived(activityProgress($run));
</script>

<a class="activity chrome" href="#/sync" use:link data-test="activity-bar" aria-label="Sync running, open the Sync screen">
  <span class="dot live-anim" aria-hidden="true"></span>
  <span class="text">{a.lead}{#if a.track}<b>{a.track}</b>{/if}{#if a.tail}{a.tail}{/if}</span>
  <span class="pbar" aria-hidden="true"><span style:transform="translateX({p * 100 - 100}%)"></span></span>
  {#if a.pause}<span class="pause num">{a.pause}</span>{/if}
  {#if a.qobuz}<span class="qobuz num">{a.qobuz}</span>{/if}
</a>

<style>
  .activity { height: var(--activity-h); flex-shrink: 0; border-top: var(--bw) solid var(--line); display: flex; align-items: center;
    gap: var(--s-3); padding: 0 var(--s-4); color: var(--text-dim); text-decoration: none; white-space: nowrap; min-width: 0; }
  .activity:hover { text-decoration: none; background: var(--bg-hover); }
  .dot { width: 8px; height: 8px; border-radius: var(--r-pill); background: var(--accent); box-shadow: 0 0 6px var(--accent);
    animation: dj-pulse 1.6s ease-in-out infinite; flex-shrink: 0; }
  .text { overflow: hidden; text-overflow: ellipsis; min-width: 0; }
  b { color: var(--text); font-weight: var(--fw-bold); }
  .pbar { flex: 1; max-width: 300px; min-width: 80px; height: 4px; background: var(--bg-inset); border-radius: 2px; overflow: hidden; }
  /* full width, slid in from the left: a transform at the live pace (spec §6, see ProgressBar) */
  .pbar span { display: block; height: 100%; background: var(--accent); transition: transform var(--t-live) linear; }
  .qobuz { margin-left: auto; color: var(--text-label); }
</style>
