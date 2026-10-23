<script lang="ts">
  // The sync's part of the frame's foot (plan now-playing): while the hub's own sync runs, on every screen except
  // Sync (which shows the same in its header). A link to Sync. `short` is the form at the player bar's right end
  // (dot · "Sync 4 of 6" · a 90 px bar, the long sentence in its tooltip); otherwise the foot holds only this, the
  // long form: what the sync does now, its bar and the Qobuz count at the right end. `fixed` replaces the live run
  // (the gallery).
  import { run, type RunState } from '../stores/run';
  import { activityLine, activityProgress, activityShort, activityText } from './activity';
  import { link } from '../router';

  let { short = false, fixed }: { short?: boolean; fixed?: RunState } = $props();
  let now = $state(Date.now());
  $effect(() => { const t = setInterval(() => (now = Date.now()), 250); return () => clearInterval(t); });
  const s = $derived(fixed ?? $run);
  const a = $derived(activityText(s, now));
  const p = $derived(activityProgress(s));
</script>

<a class="sync" class:short href="#/sync" use:link data-test="activity-bar" title={short ? activityLine(a) : undefined}
  aria-label="{activityLine(a)}. Open the Sync screen">
  <span class="dot live-anim" aria-hidden="true"></span>
  {#if short}
    <span class="text num">{activityShort(s)}</span>
  {:else}
    <span class="text">{a.lead}{#if a.track}<b>{a.track}</b>{/if}{#if a.tail}{a.tail}{/if}</span>
  {/if}
  <span class="pbar" aria-hidden="true"><span style:transform="translateX({p * 100 - 100}%)"></span></span>
  {#if !short && a.pause}<span class="pause num">{a.pause}</span>{/if}
  {#if !short && a.qobuz}<span class="qobuz num">{a.qobuz}</span>{/if}
</a>

<style>
  .sync { display: flex; align-items: center; gap: var(--s-3); min-width: 0; height: 100%; color: var(--text-dim);
    text-decoration: none; white-space: nowrap; transition: color var(--t-hover) var(--ease); }
  .short { gap: var(--s-2); font-size: var(--fs-small); height: auto; }
  /* no fill on hover: a fill would break the frame's one material; the words light up instead */
  .sync:hover { text-decoration: none; color: var(--text); }
  .sync:active { opacity: var(--link-press); }
  .dot { width: 8px; height: 8px; border-radius: var(--r-pill); background: var(--accent); box-shadow: 0 0 6px var(--accent);
    animation: dj-pulse 1.6s ease-in-out infinite; flex-shrink: 0; }
  .text { overflow: hidden; text-overflow: ellipsis; min-width: 0; }
  b { color: var(--text); font-weight: var(--fw-bold); }
  .pbar { flex: 1; max-width: 300px; min-width: 80px; height: 4px; background: var(--bg-inset); border-radius: 2px; overflow: hidden; }
  .short .pbar { flex: none; width: 90px; min-width: 0; }
  /* full width, slid in from the left: a transform at the live pace (spec §6, see ProgressBar) */
  .pbar span { display: block; height: 100%; background: var(--accent); transition: transform var(--t-live) linear; }
  .qobuz { margin-left: auto; color: var(--text-label); }
</style>
