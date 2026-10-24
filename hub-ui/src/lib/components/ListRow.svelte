<script lang="ts">
  // The row grid every list uses (design system §4, §7): lead (tick, cover, icon) · name · optional · trailing.
  // The columns belong to the list, not the row, so badges and counts line up down a whole list: the list sets
  // `--row-cols` on its `Surface kind="list"` (the cells its rows have, in order: lead? name trailing?) and, when it
  // has an optional column, `--row-cols-wide` (the same plus the optional column after the name). Sync:
  //   style="--row-cols: 52px minmax(0, 1fr) 32px; --row-cols-wide: 52px minmax(0, 1fr) 200px 32px"
  // `optional` is shown only while the list itself is at least 680 px wide (`@container list`, the rows area of a
  // non-`padded` list Surface; spec §3: a column depends on the list's own width, never the window). Rows are direct
  // children of that Surface. All rows of one list give the same cells; a row without a trailing action leaves that
  // column empty, so nothing shifts.
  // `sub` is a second, muted line under the name (folder · detail); a row with it is 52 px tall unless `height` says
  // otherwise. Both lines end in "…" on their own; `title` is the full text for the tooltip. `wrap` lets the sub-line
  // wrap instead (a destination folder or a reason the user must read whole); the row grows by its lines.
  // With `onclick`, lead + name + optional are one `<button>` (the row's hit area; `trailing` stays outside it, so ⊘
  // or "Fix →" are their own buttons and own their own disabled state). `checked` makes that button a tick box
  // (`role="checkbox"`), `selected` marks the chosen row of a "one of many" list (wash + `aria-current`) and brings it into view
  // when it becomes the chosen one (`block: 'nearest'`, instant: a row already in view does not move; a row reached by
  // its address or by the keyboard, below the fold of a short window, is shown). The
  // button's name is the name line only, so it doesn't change when the optional column appears; `sub` and
  // `optional` are its description. `off` dims name and lead, except a lead item marked `data-mark` (the tick; an unticked track: the name stays readable, the user
  // decides on it — rule 8). `disabled` keeps the row focusable but ignores clicks (like Button) and mutes name and
  // lead. Rows highlight on hover and while held, never shrink (a whole row scaling would jump). The lead is
  // decorative (`aria-hidden`): its meaning goes into `checked` or the name. Other attributes (`data-track`, …) go
  // onto the row.
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';

  type Props = Omit<HTMLAttributes<HTMLDivElement>, 'children' | 'onclick' | 'title'> & {
    lead?: Snippet; name: Snippet; sub?: Snippet; optional?: Snippet; trailing?: Snippet;
    off?: boolean; selected?: boolean; disabled?: boolean; checked?: boolean; height?: 40 | 52; wrap?: boolean;
    onclick?: (e: MouseEvent) => void; title?: string; test?: string;
  };
  let { lead, name, sub, optional, trailing, off = false, selected = false, disabled = false, checked, height, wrap = false,
    onclick, title, test, class: className, ...rest }: Props = $props();

  const uid = $props.id();
  const isTall = $derived((height ?? (sub ? 52 : 40)) === 52);
  const described = $derived([sub && `${uid}-sub`, optional && `${uid}-opt`].filter(Boolean).join(' ') || undefined);
  function click(e: MouseEvent) { if (!disabled) onclick?.(e); }
  let rowEl = $state<HTMLDivElement>();
  $effect(() => { if (selected) rowEl?.scrollIntoView?.({ block: 'nearest' }); });
</script>

<div {...rest} bind:this={rowEl} class="row {className ?? ''}" class:off class:selected class:locked={disabled} class:tall={isTall}
  class:clickable={!!onclick} class:has-lead={!!lead} class:has-trailing={!!trailing} class:wrap data-test={test}>
  {#if onclick}
    <button type="button" class="main" data-row-hit role={checked === undefined ? undefined : 'checkbox'}
      aria-checked={checked} aria-current={selected || undefined} aria-disabled={disabled || undefined}
      aria-labelledby="{uid}-name" aria-describedby={described} onclick={click}>
      {@render cells()}
    </button>
  {:else}
    <div class="main">{@render cells()}</div>
  {/if}
  {#if trailing}<div class="trailing">{@render trailing()}</div>{/if}
</div>

{#snippet cells()}
  {#if lead}<span class="lead" aria-hidden="true">{@render lead()}</span>{/if}
  <span class="name" {title}>
    <span class="line" id="{uid}-name">{@render name()}</span>
    {#if sub}<span class="sub" id="{uid}-sub">{@render sub()}</span>{/if}
  </span>
  {#if optional}<span class="optional" id="{uid}-opt">{@render optional()}</span>{/if}
{/snippet}

<style>
  /* An edge track on each side: edge + gap = the 16 px inset (the Surface caption's inset, so caption, lead and
     trailing share the list's hard edges), and the row's button reaches the left edge, so the whole row is the hit
     area and its focus ring. */
  .row {
    --edge: calc(var(--s-4) - var(--s-3));
    display: grid; grid-template-columns: var(--edge) var(--row-cols, minmax(0, 1fr)) var(--edge);
    column-gap: var(--s-3); align-items: center; min-height: var(--h-list-row); min-width: 0;
    color: var(--text); font-size: var(--fs-body); transition: background var(--t-hover) var(--ease);
  }
  .tall { min-height: var(--h-list-row-tall); }
  /* the hit area spans the edge, lead, name and optional tracks and keeps the row's columns (subgrid) */
  .main { grid-column: 1 / -1; align-self: stretch; display: grid; grid-template-columns: subgrid; align-items: center;
    min-width: 0; padding: 0; text-align: left; }
  .has-trailing .main { grid-column: 1 / -3; }
  .trailing { grid-column: -3 / -2; display: flex; align-items: center; justify-content: flex-end; gap: var(--s-2);
    min-width: 0; color: var(--text-muted); font-size: var(--fs-small); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .lead { grid-column: 2; display: flex; align-items: center; gap: var(--s-2); min-width: 0; }
  .lead > :global(*) { transition: opacity var(--t-state) var(--ease); }
  .name { grid-column: 2; min-width: 0; display: flex; flex-direction: column; }
  .has-lead .name { grid-column: 3; }
  .line, .sub { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .line { transition: color var(--t-state) var(--ease); }
  .sub { color: var(--text-muted); font-size: var(--fs-small); }
  /* a wrapping sub-line keeps the row's padding rhythm: the lines sit 8 px in from the row's rules */
  .wrap .sub { white-space: normal; overflow-wrap: break-word; line-height: 1.35; }
  .wrap .name { padding: var(--s-2) 0; }
  .optional { grid-column: 3; display: none; align-items: center; gap: var(--s-2); min-width: 0; overflow: hidden;
    color: var(--text-muted); font-size: var(--fs-small); white-space: nowrap; }
  /* what doesn't fit ends in "…" instead of being cut mid-letter */
  .optional > :global(*) { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .has-lead .optional { grid-column: 4; }

  /* states: hover and held highlight the row (press arrives on pointer-down, instantly; release fades back) */
  .clickable:not(.locked):hover { background: var(--ctl-hover); }
  .clickable:not(.locked):has(> .main:active) { background: var(--ctl-press); transition: none; }
  .selected, .selected.clickable:not(.locked):hover { background: var(--nav-on-bg); }
  .main:active { transform: none; }
  /* the ring sits inside the row; its corners are concentric with the Surface's (rule 10), so the first and last
     row's ring isn't cut by the list's rounded clip */
  .main:focus-visible { outline-offset: -2px; border-radius: calc(var(--r-surface) - var(--bw)); }
  .off .line { color: var(--text-muted); }
  /* an off row dims its cover or icon, never the tick that carries its state (a dimmed empty box all but vanished,
     spec §11 "an off row stays readable"); the tick marks itself `data-mark` */
  .off .lead > :global(:not([data-mark])) { opacity: var(--dim-cover); }
  .locked .line { color: var(--text-muted); }
  .locked:not(.off) .lead > :global(*) { opacity: var(--dim-locked); }

  /* the optional column: only while the list itself is wide enough (after the base rules, so it wins) */
  @container list (min-width: 680px) {
    .row { grid-template-columns: var(--edge) var(--row-cols-wide, var(--row-cols, minmax(0, 1fr))) var(--edge); }
    .optional { display: flex; }
  }
</style>
