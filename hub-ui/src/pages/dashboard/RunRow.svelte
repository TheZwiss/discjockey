<script lang="ts">
  // One run in the Dashboard's Last runs (a ListRow of a list Surface): its mark (finished, some failed, stopped by
  // you), "Yesterday 21:47 · 24 min", and the counts in their quality colours under it; the whole row opens the run.
  // The list sets the columns: --row-cols: 16px minmax(0, 1fr) 16px.
  import type { RunSummary } from '$lib/bridge/types';
  import { ListRow } from '$lib/components';
  import { go, link } from '$lib/router';
  import { runLine } from './dashboardModel';

  let { run, now = Date.now() }: { run: RunSummary; now?: number } = $props();
  const l = $derived(runLine(run, now));
  const said = $derived([l.parts.map((p) => p.text).join(' · '), l.note].filter(Boolean).join(' · '));
</script>

{#snippet lead()}<svg class="mark {l.status}" viewBox="0 0 16 16">{#if l.status === 'ok'}<path d="M3.5 8.5l3 3 6-7" />{:else if l.status === 'failed'}<path
  d="M8 3.5v6M8 12.5v.01" />{:else}<path d="M5 5h6v6H5z" />{/if}</svg>{/snippet}
{#snippet name()}{l.title}{/snippet}
{#snippet sub()}{#each l.parts as p, i (i)}{#if i}<span class="sep">{' · '}</span>{/if}<span class={p.tone ?? 'plain'}>{p.text}</span>{/each}{#if l.note}<span
  class="sep">{' · '}</span>{l.note}{/if}{/snippet}
<!-- the row's button is mark + name; the chevron is the same link, out of the tab order -->
{#snippet trailing()}<a class="go" href={l.href} use:link tabindex="-1" aria-hidden="true"><svg class="chev" viewBox="0 0 16 16"><path
  d="M6 4l4 4-4 4" /></svg></a>{/snippet}
<ListRow {lead} {name} {sub} {trailing} onclick={() => void go(l.href.slice(1))} title="{l.title} · {said}" test="run-row"
  data-run={run.run_id} />

<style>
  .mark, .chev { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round;
    stroke-linejoin: round; display: block; }
  .mark.ok { color: var(--q-lossless); }
  .mark.failed { color: var(--q-weak); }
  .mark.stopped { color: var(--text-muted); }
  .go { display: flex; color: var(--text-label); }
  .go:hover { color: var(--text); }
  .sep { color: var(--text-label); }
  .ok { color: var(--q-lossless); }
  .warn { color: var(--q-good); }
  .bad { color: var(--q-weak); }
  .plain { color: var(--text-muted); }
</style>
