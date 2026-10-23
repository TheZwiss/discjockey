<script lang="ts">
  // Search → Download → Check → Convert → Analyse (+ Compare): done steps ✓, the current one accent.
  import type { Step } from '$lib/bridge/events';
  let { steps, current, fill = null }: { steps: Step[]; current: number; fill?: number | null } = $props();
  const NAME: Record<Step, string> = { search: 'Search', download: 'Download', check: 'Check', convert: 'Convert',
    analyse: 'Analyse', compare: 'Compare' };
  const state = (i: number) => (current < 0 || i < current ? 'done' : i === current ? 'now' : 'todo');
</script>

<div class="bar" data-test="step-bar">
  <div class="segs">
    {#each steps as s, i (s)}
      <span class="seg {state(i)}">{#if state(i) === 'now'}<i style:width="{Math.round((fill ?? 0) * 100)}%"></i>{/if}</span>
    {/each}
  </div>
  <div class="names">
    {#each steps as s, i (s)}
      <span class={state(i)}>{NAME[s]}{state(i) === 'done' ? ' ✓' : ''}</span>
    {/each}
  </div>
</div>

<style>
  .segs, .names { display: flex; gap: var(--s-1); }
  .segs { margin: var(--s-2) 0 var(--s-1); }
  .seg { flex: 1; height: 5px; border-radius: var(--r-pill); background: var(--bg-inset); position: relative;
    overflow: hidden; }
  .seg.done { background: var(--q-lossless); }
  .seg.now i { position: absolute; inset: 0 auto 0 0; background: var(--accent); }
  .names span { flex: 1; font-size: var(--fs-label); color: var(--text-dim); }
  .names .done { color: var(--q-lossless); }
  .names .now { color: var(--accent-text); }
</style>
