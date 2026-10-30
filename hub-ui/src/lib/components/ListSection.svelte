<script lang="ts">
  // A section head inside one list Surface (design system §7, To-do): the list's rows come in groups, and each group
  // is named here, as a row-high head between them (name · count · one-line hint), the way Mail groups by date. It
  // sits among the rows as a sibling (the rows stay direct children of the list, so their rules and columns hold) and
  // sticks to the top of the list's scroller while its rows pass, so the group in view is always named; the next head
  // pushes it away. It is a heading (level 3) for screen readers. The head is the scroller's top edge while stuck, so
  // a Surface with sections doesn't fade its top end (Surface CSS). `data-list-section` marks it for that rule.
  //
  // A stuck head is solid and square (plan library stage 5 A3.6, notes N15, house rule 10): opaque in its list's own
  // colour (one solid value, `--surface-list-solid`: a gradient of its own would restart at each head), no rounded
  // corners, no soft fade, so no row shows through it or round it; while rows pass beneath it, it
  // gets a hairline on that edge (`stuckEdge` sets `data-stuck`). Not stuck it has no line of its own: in a list with
  // row rules the next row's rule is the line under it. A row scrolled into view (a selection, the keyboard, a
  // collection opened) stops whole beside a stuck head, never half under it: the rows beside sections get the head's
  // height as their scroll margin (the global rule below).
  // `stick`: `top` (default), or `both` for a short list of sections in a tall column (the browser column: "Folders"
  // waits at the foot from the first look). `on`: `list` inside a Surface list (default), `chrome` on the frame's
  // material (the browser column), whose solid colour and hairline it then takes, a step lower than the column's rows
  // (`--h-section-chrome`) and in the label grey, so the heads read as quieter than the names they group.
  //
  // `fold` (plan library stage 5 A5, notes N10): the whole head folds its section, with a chevron at its end that
  // turns (open: pointing down); the section's rows are the caller's to leave out. The head stays a heading; the
  // control inside it is a button over the whole head (`data-row-hit`, as Surface's fold; `aria-expanded`, a Tip "Hide playlists" / "Show playlists").
  // `disabled`: shown open and not foldable (a filter has opened it). `children`: the head's own controls before the
  // chevron (the browser's A–Z toggle), above the fold button so they take their own clicks.
  import type { Snippet } from 'svelte';
  import { stuckEdge } from './stuckEdge';
  import { tip } from './tip';

  type Fold = { open: boolean; toggle: () => void; disabled?: boolean };
  type Props = { label: string; summary?: string; hint?: string; test?: string; stick?: 'top' | 'both';
    on?: 'list' | 'chrome'; fold?: Fold; children?: Snippet };
  let { label, summary, hint, test, stick = 'top', on = 'list', fold, children }: Props = $props();
  const open = $derived(!fold || fold.open || !!fold.disabled);
  const foldTip = $derived(fold && !fold.disabled ? `${open ? 'Hide' : 'Show'} ${label.toLowerCase()}` : null);
</script>

<div class="section {on}" class:both={stick === 'both'} class:foldable={!!fold} data-list-section data-stick={stick}
  data-test={test} use:stuckEdge>
  {#if fold}
    <span class="hd" role="heading" aria-level="3">
      <button type="button" class="hit" aria-expanded={open} aria-label={summary ? `${label}, ${summary}` : label}
        disabled={fold.disabled} use:tip={foldTip} onclick={fold.toggle} data-row-hit
        data-test={test ? `${test}-fold` : undefined}></button>
    </span>
  {/if}
  <span class="title" role={fold ? undefined : 'heading'} aria-level={fold ? undefined : 3}
    aria-hidden={fold ? 'true' : undefined}>{label}</span>
  {#if summary}<span class="summary" aria-hidden={fold ? 'true' : undefined}>{summary}</span>{/if}
  {#if hint}<span class="hint">{hint}</span>{/if}
  {#if fold || children}<span class="fill"></span>{/if}
  {#if children}<span class="own">{@render children()}</span>{/if}
  {#if fold}
    <span class="chev" class:open aria-hidden="true"><svg viewBox="0 0 8 8"><path d="M2.6 1.2 5.6 4l-3 2.8" /></svg></span>
  {/if}
</div>

<style>
  /* the caption's 16 px inset, so the name starts where the rows' covers do */
  .section { position: sticky; top: 0; z-index: 1; display: flex; align-items: center; gap: var(--s-2);
    min-height: var(--h-section); padding: 0 var(--s-4); min-width: 0; white-space: nowrap; border-radius: 0;
    --section-line: var(--line-soft); background: var(--surface-list-solid); }
  .section.both { bottom: 0; }
  /* on the frame: the column's rows' 8 px inset, a step lower than them, the name in the label grey and its count
     beside it in the same grey (a count, not a second name) */
  .section.chrome { --section-line: var(--surface-line); background: var(--sidebar-solid);
    min-height: var(--h-section-chrome); flex: none; padding: 0 3px 0 var(--s-2); gap: 6px; }
  .section.chrome .title { color: var(--text-label); }
  .section.chrome .summary { color: var(--text-label); font-weight: normal; }
  /* the hairline on the edge rows pass: a shadow, so it takes no room and travels with the head */
  .section:global([data-stuck='top']) { box-shadow: 0 var(--bw) 0 var(--section-line); }
  .section:global([data-stuck='bottom']) { box-shadow: 0 calc(-1 * var(--bw)) 0 var(--section-line); }
  .title { flex: none; color: var(--text); font-size: var(--fs-small); font-weight: var(--fw-semi); }
  .summary { flex: none; color: var(--text-muted); font-size: var(--fs-small); font-variant-numeric: tabular-nums; }
  .hint { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-label);
    font-size: var(--fs-small); }
  .fill { flex: 1; }

  /* folding: one button over the whole head; the words and the chevron are drawn above it but let the pointer through,
     the head's own controls take their clicks */
  .hd { position: absolute; inset: 0; }
  .hit { position: absolute; inset: 0; width: 100%; padding: 0; border: 0; border-radius: 0; background: transparent;
    cursor: default; }
  .hit:focus-visible { outline-offset: -2px; }
  .foldable .title, .foldable .summary, .foldable .hint, .chev { position: relative; pointer-events: none; }
  .own { position: relative; display: flex; align-items: center; gap: 2px; }
  .chev { flex: none; width: 20px; height: 20px; display: grid; place-items: center; color: var(--text-label); }
  .chev svg { width: 8px; height: 8px; fill: none; stroke: currentColor; stroke-width: 1.3; stroke-linecap: round;
    stroke-linejoin: round; transition: transform 160ms var(--ease); }
  .chev.open svg { transform: rotate(90deg); }
  /* hover: the head's words and chevron one step brighter, together (the whole head is the control) */
  .foldable:has(.hit:not(:disabled):hover) :is(.title, .summary, .chev) { color: var(--text-muted);
    transition: color var(--t-hover) var(--ease); }
  @media (prefers-reduced-motion: reduce) { .chev svg { transition: none; } }

  /* whatever scroller holds sections: a row scrolled into view stops whole below a stuck head (and above one stuck
     at the foot) */
  :global(:has(> [data-list-section]) > *) { scroll-margin-top: var(--h-section); }
  :global(:has(> [data-list-section][data-stick='both']) > *) { scroll-margin-bottom: var(--h-section); }
  :global(:has(> [data-list-section].chrome) > *) { scroll-margin-top: var(--h-section-chrome); }
  :global(:has(> [data-list-section].chrome[data-stick='both']) > *) { scroll-margin-bottom: var(--h-section-chrome); }
</style>
