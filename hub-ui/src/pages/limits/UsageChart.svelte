<script lang="ts">
  // Last 14 days: one bar per day coloured by how fast that day was (its zone's risk colour: green normal, yellow
  // faster, red risky; design language §2), today's ringed, the saved limit as a dashed line. While the user moves
  // the limit (`draft` differs) the new limit is a second, solid line in the accent: the user's change, so the past
  // days it would have allowed show at a glance. Its scale never jumps while dragging past the top: the top grows
  // with the draft, the bars shrink smoothly with it.
  import { barTooltip, dayLabel, riskOf, zoneIndex, type Zone } from './limitsModel';
  let { days, limit, draft, zones, height }: {
    days: { date: string; used: number }[]; limit: number; draft: number; zones: Zone[]; height: number;
  } = $props();

  const top = $derived(Math.max(1, limit * 1.25, draft * 1.12, ...days.map((d) => d.used)));
  const pct = (v: number) => (v / top) * 100;
  const changed = $derived(draft !== limit);
</script>

<div class="chart" data-test="usage-chart">
  <div class="plot" style:height="{height}px">
    {#each days as d, i (d.date)}
      <span class="col" title={barTooltip(d.date, d.used, zones[zoneIndex(d.used, zones)]?.name ?? '')}>
        {#if d.used > 0}<span class="bar {riskOf(d.used, zones)}" class:today={i === days.length - 1}
          style:height="{pct(d.used)}%"></span>{/if}
      </span>
    {/each}
    <span class="lim" style:bottom="{pct(limit)}%"><span>limit {limit}</span></span>
    {#if changed}<span class="lim new" style:bottom="{pct(draft)}%" data-test="new-limit-line"><span>new limit {draft}</span></span>{/if}
  </div>
  <div class="days">
    {#each days as d, i (d.date)}<span class:today={i === days.length - 1}>{dayLabel(d.date, i === days.length - 1)}</span>{/each}
  </div>
</div>

<style>
  .chart { display: flex; flex-direction: column; gap: var(--s-1); }
  .plot { position: relative; display: flex; align-items: flex-end; gap: 6px;
    border-bottom: var(--bw) solid var(--line-soft); }
  .col { flex: 1; height: 100%; display: flex; align-items: flex-end; min-width: 0; }
  .bar { width: 100%; border-radius: 3px 3px 1px 1px; opacity: .85;
    transition: height var(--t-reply) var(--ease); }
  .bar.safe { background: var(--risk-safe); }
  .bar.notice { background: var(--risk-notice); }
  .bar.high { background: var(--risk-high); }
  .bar.today { opacity: 1; box-shadow: 0 0 0 1.5px var(--bg), 0 0 0 2.5px var(--text-muted); }
  .lim { position: absolute; left: 0; right: 0; border-top: var(--bw) dashed var(--text-label); pointer-events: none; }
  .lim span { position: absolute; right: 0; bottom: 2px; padding-left: var(--s-1); font-size: var(--fs-label);
    color: var(--text-muted); }
  .lim.new { border-top: var(--bw-accent) solid var(--accent); }
  .lim.new span { left: 0; right: auto; bottom: auto; top: 2px; padding: 0 var(--s-1) 0 0; color: var(--accent-text);
    font-weight: var(--fw-semi); }
  .days { display: flex; gap: 6px; font-size: var(--fs-label); color: var(--text-label); }
  .days span { flex: 1; text-align: center; font-variant-numeric: tabular-nums; }
  .days span.today { color: var(--text-strong); }
</style>
