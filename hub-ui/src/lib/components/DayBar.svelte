<script lang="ts">
  // Today against later (design system §7): what this run downloads (solid accent) next to what waits for the next
  // days under the daily limit (striped). `dayBar` (dayBarModel.ts) turns the numbers into segments; each segment's
  // share is its flex-grow, so a new split slides over in --t-reply (the user caused it, so it answers fast). Every segment stays in the DOM and a missing one
  // shrinks to nothing, so a split that gains or loses a side slides too. A segment is never narrower than its label,
  // so both numbers always read (spec §11): a hidden copy of each label is measured, and a present segment's
  // flex-basis is that width plus its padding, in px (never `auto` or min-content, which can't animate), with its
  // share growing on top; a missing one's basis is 0. So the label floor slides in and out with the share instead of
  // snapping. The moves-only segment (`fit`) takes no share, so it is exactly as wide as its label. Transitions start
  // once the first measurements are in, so nothing slides when the bar appears. While a segment shrinks to nothing
  // (`gone`) its label wraps onto a hidden second line, so no half label shows mid-slide, and `title` keeps it.
  // Day mode (`input.day`, Dashboard) draws the whole daily limit: what earlier runs used today (filled, quiet) ahead
  // of this sync, and what is left after it (outline only); all four kinds slide the same way.
  // Without a daily limit the caption "No daily limit" sits under the bar as a Hint; with nothing ticked the bar is
  // an empty track. Other attributes (`data-test`) go onto the root.
  import type { HTMLAttributes } from 'svelte/elements';
  import Hint from './Hint.svelte';
  import { dayBar, type DayBarInput, type DaySeg } from './dayBarModel';

  type Props = Omit<HTMLAttributes<HTMLDivElement>, 'children'> & { input: DayBarInput };
  let { input, class: className, ...rest }: Props = $props();
  const KINDS: DaySeg['kind'][] = ['used', 'today', 'later', 'free'];
  const bar = $derived(dayBar(input));
  const segOf = $derived(Object.fromEntries(bar.segs.map((s) => [s.kind, s])) as Partial<Record<DaySeg['kind'], DaySeg>>);
  // the present segments' ends: the first takes the bar's left corners and no split before it, the last the right
  const first = $derived(bar.segs[0]?.kind);
  const last = $derived(bar.segs[bar.segs.length - 1]?.kind);
  const said = $derived(bar.segs.length ? bar.segs.map((s) => s.label).join(' · ') : 'Nothing ticked');
  let w = $state<Record<DaySeg['kind'], number>>({ used: 0, today: 0, later: 0, free: 0 });  // the labels' natural widths
  let armed = $state(false);  // transitions on: the first measurements have been drawn
  $effect(() => {
    if (armed || bar.segs.some((s) => w[s.kind] === 0)) return;
    const f = requestAnimationFrame(() => (armed = true));
    return () => cancelAnimationFrame(f);
  });
</script>

<div {...rest} class="day-bar {className ?? ''}">
  <div class="bar" class:empty={!bar.segs.length} class:still={!armed} role="img" aria-label={said}>
    {#each KINDS as kind (kind)}
      {@const s = segOf[kind]}
      <div class="seg {kind}" class:gone={!s} class:fit={s?.fit} class:first={kind === first} class:last={kind === last}
        style:flex-grow={s?.grow ?? 0} style:flex-basis={s ? `calc(${w[kind]}px + 2 * var(--s-2))` : '0px'} title={s?.label}
        data-seg={kind} aria-hidden="true">
        <span>{s?.label ?? ''}</span>
      </div>
    {/each}
  </div>
  <!-- the labels' twins, measured for the segments' label floor; a new label is measured a frame after it shows and
       the basis retargets mid-slide (a transition starts from where it is) -->
  {#each bar.segs as s (s.kind)}
    <span class="measure" class:bold={s.kind === 'today'} bind:offsetWidth={w[s.kind]} aria-hidden="true">{s.label}</span>
  {/each}
  {#if bar.caption}<Hint text={bar.caption} />{/if}
</div>

<style>
  .day-bar { position: relative; display: flex; flex-direction: column; gap: var(--s-1); min-width: 0; }
  .bar { --h: var(--h-ctl-sm); display: flex; height: var(--h); min-width: 0; border-radius: var(--r-icon); }
  .bar.empty { background: var(--bg-inset); }
  .seg {
    flex: 0 1 0; min-width: 0; height: 100%; padding-left: var(--s-2); overflow: hidden;
    /* the label is the second flex item after an empty full-height one: when it doesn't fit beside it, it wraps
       onto the clipped second line, so a narrow segment shows no half label */
    display: flex; flex-wrap: wrap; align-items: center; align-content: flex-start;
    font-size: var(--fs-small); white-space: nowrap;
    transition: flex-grow var(--t-reply) var(--ease), flex-basis var(--t-reply) var(--ease),
      padding var(--t-reply) var(--ease), margin var(--t-reply) var(--ease);
  }
  .still .seg { transition: none; }
  .seg::before { content: ''; width: 0; height: var(--h); }
  /* a split before every present segment but the first; the bar's corners on its two ends */
  .seg:not(.first) { margin-left: var(--gap-split); }
  .seg.first { border-top-left-radius: var(--r-icon); border-bottom-left-radius: var(--r-icon); }
  .seg.last { border-top-right-radius: var(--r-icon); border-bottom-right-radius: var(--r-icon); }
  .today { background: var(--accent); color: var(--text-on-accent); font-weight: var(--fw-bold); }
  .later {
    color: var(--accent-text);
    background: repeating-linear-gradient(135deg, var(--accent-stripe) 0 5px, var(--accent-wash) 5px 10px);
    box-shadow: inset 0 0 0 var(--bw) var(--accent-line);   /* a border that takes no room, so it can shrink to 0 */
  }
  /* day mode: what earlier runs used today is spent (filled, quiet); what is left is room (outline only) */
  .used { background: var(--bg-inset); color: var(--text-muted); }
  .free { color: var(--text-label); box-shadow: inset 0 0 0 var(--bw) var(--line-control); }
  /* "Today: 3 moves": as wide as its label (no share), so it reads beside a long later segment */
  .seg.fit { flex-shrink: 0; }
  .seg:not(.gone) { padding-right: var(--s-2); }
  /* the labels' twins, measured for the segments' flex-basis; same type as their segments */
  .measure { position: absolute; top: 0; left: 0; visibility: hidden; pointer-events: none; white-space: nowrap;
    font-size: var(--fs-small); }
  .measure.bold { font-weight: var(--fw-bold); }
  /* the outline stays: at 0 px width it draws nothing, and removing it would flash a stripe without one */
  .seg.gone { padding-left: 0; margin-left: 0; }
</style>
