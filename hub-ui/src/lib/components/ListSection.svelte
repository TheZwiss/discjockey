<script lang="ts">
  // A section head inside one list Surface (design system §7, To-do): the list's rows come in groups, and each group
  // is named here, as a row-high head between them (name · count · one-line hint), the way Mail groups by date. It
  // sits among the rows as a sibling (the rows stay direct children of the list, so their rules and columns hold) and
  // sticks to the top of the list's scroller while its rows pass, so the group in view is always named; the next head
  // pushes it away. It is a heading (level 3) for screen readers. The head is the scroller's top edge while stuck, so
  // a Surface with sections doesn't fade its top end (Surface CSS). `data-list-section` marks it for that rule.
  //
  // A stuck head is solid and square (plan library stage 5 A3.6, notes N15, house rule 10): opaque in its list's own
  // colour, no rounded corners, no soft fade, so no row shows through it or round it; while rows pass beneath it, it
  // gets a hairline on that edge (`stuckEdge` sets `data-stuck`). Not stuck it has no line of its own: in a list with
  // row rules the next row's rule is the line under it. A row scrolled into view (a selection, the keyboard, a
  // collection opened) stops whole beside a stuck head, never half under it: the rows beside sections get the head's
  // height as their scroll margin (the global rule below).
  // `stick`: `top` (default), or `both` for a short list of sections in a tall column (the browser column: "Folders"
  // waits at the foot from the first look). `on`: `list` inside a Surface list (default), `chrome` on the frame's
  // material (the browser column), whose solid colour and hairline it then takes.
  import { stuckEdge } from './stuckEdge';

  type Props = { label: string; summary?: string; hint?: string; test?: string; stick?: 'top' | 'both';
    on?: 'list' | 'chrome' };
  let { label, summary, hint, test, stick = 'top', on = 'list' }: Props = $props();
</script>

<div class="section {on}" class:both={stick === 'both'} data-list-section data-stick={stick} data-test={test}
  use:stuckEdge>
  <span class="title" role="heading" aria-level="3">{label}</span>
  {#if summary}<span class="summary">{summary}</span>{/if}
  {#if hint}<span class="hint">{hint}</span>{/if}
</div>

<style>
  /* the caption's 16 px inset, so the name starts where the rows' covers do */
  .section { position: sticky; top: 0; z-index: 1; display: flex; align-items: center; gap: var(--s-2);
    min-height: var(--h-section); padding: 0 var(--s-4); min-width: 0; white-space: nowrap; border-radius: 0;
    --section-line: var(--line-soft); background: var(--surface); }
  .section.both { bottom: 0; }
  .section.chrome { --section-line: var(--surface-line); background: var(--sidebar-solid); }
  /* the hairline on the edge rows pass: a shadow, so it takes no room and travels with the head */
  .section:global([data-stuck='top']) { box-shadow: 0 var(--bw) 0 var(--section-line); }
  .section:global([data-stuck='bottom']) { box-shadow: 0 calc(-1 * var(--bw)) 0 var(--section-line); }
  .title { flex: none; color: var(--text); font-size: var(--fs-small); font-weight: var(--fw-semi); }
  .summary { flex: none; color: var(--text-muted); font-size: var(--fs-small); font-variant-numeric: tabular-nums; }
  .hint { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-label);
    font-size: var(--fs-small); }
  /* whatever scroller holds sections: a row scrolled into view stops whole below a stuck head (and above one stuck
     at the foot) */
  :global(:has(> [data-list-section]) > *) { scroll-margin-top: var(--h-section); }
  :global(:has(> [data-list-section][data-stick='both']) > *) { scroll-margin-bottom: var(--h-section); }
</style>
