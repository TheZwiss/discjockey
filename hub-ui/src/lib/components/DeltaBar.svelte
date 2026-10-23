<script lang="ts">
  // A signed change as a bar either side of a centre line (design system §4: a number plus a visual), so the rows of
  // one list compare at a glance: a gain grows right in the accent (what the user's change brings), a loss grows left
  // in quiet grey. Every row of a list passes the same `max` (the biggest change), so 27 and 3 differ by length; a
  // change of zero draws only the centre line. The number belongs to the caller (beside the bar); the bar is
  // decorative. Fixed width (`--w-row-action`), so the bars of a list line up. Playlists' move view.
  let { value, max }: { value: number; max: number } = $props();
  // at least a sliver, so a change of 1 among 300 still shows its side
  const pct = $derived(value === 0 || max <= 0 ? 0 : Math.max(6, Math.min(100, (Math.abs(value) / max) * 100)));
</script>

<span class="delta" aria-hidden="true">
  {#if pct}<span class="fill" class:gain={value > 0} class:loss={value < 0} style:width="{pct / 2}%"></span>{/if}
</span>

<style>
  .delta { position: relative; display: block; flex: none; width: var(--w-row-action); height: 8px; }
  .delta::before { content: ''; position: absolute; left: 50%; top: -3px; bottom: -3px; width: var(--bw);
    background: var(--line-control); }
  .fill { position: absolute; top: 0; bottom: 0; border-radius: 2px;
    transition: width var(--t-reply) var(--ease); }
  .gain { left: calc(50% + var(--bw)); background: var(--accent); }
  .loss { right: calc(50% + var(--bw)); background: var(--text-label); }
</style>
