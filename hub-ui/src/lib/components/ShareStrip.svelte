<script lang="ts" module>
  import type { Snippet } from 'svelte';
  /** One row of the strip's right column: its mark (a snippet, or a dot in `dot`'s colour), its words, a quiet part
   *  after them, the count, and what it does: `onclick` makes it a link row with ›; `tip` explains it (a row with a
   *  tip and no link takes focus, so the tip opens from the keyboard too). `off`: switched off (half strength, the
   *  one meaning dim has in a list). */
  export type ShareRow = {
    key: string; words: string; count: string; test: string;
    mark?: Snippet; dot?: string; quiet?: string | null; onclick?: (() => void) | null; tip?: string | null;
    off?: boolean;
  };
</script>

<script lang="ts">
  // A whole at a glance, laid along the page, 72 px (plan library stage 5 A3.4; issue 36): the share as a stat
  // (StatCard's type: 30 px number, its unit, a line under it), a bar of its parts, then a column of rows that say
  // what the parts are, each with its count. Library's SummaryStrip (lossless share, the quality bar, two link rows)
  // and Sync's KindStrip (the plan's tracks, its kinds) are this block with their own words.
  // Up to two rows they stack in one 300 px column, each half the strip's height (Library). More rows stand three to
  // a column, the columns side by side (Sync's five kinds); where the strip is too narrow for them beside the bar
  // (a container query, under 680 px), the rows take a line of their own under the share and the bar, so nothing is
  // cut and nothing scrolls sideways.
  // `value` null: "—" and no unit (waiting, nothing to count); `bar` is the strip's bar (QualityBar, ShareBar).
  import Surface from './Surface.svelte';
  import { tip as tipAction } from './tip';

  let { value, unit, line, bar, rows, mark, test, valueTest, lineTest }: {
    value: string | null; unit: string; line: string; bar: Snippet; rows: ShareRow[];
    /** every row's mark drawn from the row (a row's own `mark` or `dot` comes first) */
    mark?: Snippet<[ShareRow]>;
    test: string; valueTest?: string; lineTest?: string;
  } = $props();
  const many = $derived(rows.length > 2);
  const cols = $derived(Math.ceil(rows.length / 3));
</script>

{#snippet chev()}<svg class="chev" viewBox="0 0 12 12" aria-hidden="true"><path d="M4.5 2.5 8 6l-3.5 3.5" /></svg>{/snippet}

{#snippet lead(r: ShareRow)}
  {#if r.mark}{@render r.mark()}{:else if r.dot}<span class="dot" style:background={r.dot} aria-hidden="true"></span>{:else if mark}{@render mark(r)}{:else}<span></span>{/if}
{/snippet}

{#snippet row(r: ShareRow)}
  {#if r.onclick}
    <button type="button" class="srow link" class:off={r.off} data-row-hit data-test={r.test} use:tipAction={r.tip ?? null}
      onclick={r.onclick}>
      {@render lead(r)}<span class="w">{r.words}{#if r.quiet}<span class="q">{` · ${r.quiet}`}</span>{/if}</span>
      <span class="n">{r.count}</span>{@render chev()}
    </button>
  {:else}
    <!-- a row that explains itself takes focus, so its tip opens from the keyboard too (the tooltip pattern needs a
         focusable trigger); it stays a plain row, it does nothing when pressed -->
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <div class="srow" class:off={r.off} data-test={r.test} data-key={r.key} use:tipAction={r.tip ?? null} tabindex={r.tip ? 0 : undefined}>
      {@render lead(r)}<span class="w">{r.words}{#if r.quiet}<span class="q">{` · ${r.quiet}`}</span>{/if}</span>
      <span class="n">{r.count}</span>{#if !many}<span></span>{/if}
    </div>
  {/if}
{/snippet}

<Surface class="strip" padded={false} data-test={test}>
  <div class="cq" class:many>
    <div class="grid" style:--cols={cols}>
      <div class="share">
        <!-- without a value the line names it, so the unit doesn't stand beside a dash -->
        <div class="num"><span data-test={valueTest}>{value ?? '—'}</span>{#if value !== null}<span class="unit">{unit}</span>{/if}</div>
        <div class="label" data-test={lineTest}>{line}</div>
      </div>
      <div class="bar">{@render bar()}</div>
      <div class="rows">
        {#each rows as r (r.key)}{@render row(r)}{/each}
      </div>
    </div>
  </div>
</Surface>

<style>
  /* 72 px: two 35 px rows and their rule inside the 1 px border; the share and the bar centred on them */
  .grid { display: grid; grid-template-columns: auto minmax(80px, 1fr) minmax(0, 300px); align-items: center;
    column-gap: 18px; height: 70px; padding-left: var(--s-4); min-width: 0; }
  .share { display: flex; flex-direction: column; gap: var(--s-1); white-space: nowrap; }
  /* StatCard's type, so the share reads as the same kind of number as every other stat */
  .num { font-size: var(--fs-stat); letter-spacing: var(--ls-stat); line-height: 1; font-weight: var(--fw-bold);
    color: var(--text-strong); font-variant-numeric: tabular-nums; }
  .unit { font-size: var(--fs-body); font-weight: var(--fw-medium); color: var(--text-muted); letter-spacing: 0;
    margin-left: var(--s-1); }
  .label { font-size: var(--fs-label); color: var(--text-muted); }
  .bar { min-width: 0; }
  .rows { align-self: stretch; display: flex; flex-direction: column; min-width: 0;
    border-left: var(--bw) solid var(--line-soft); }
  .srow { flex: 1 1 0; display: grid; grid-template-columns: 14px minmax(0, 1fr) auto 12px; align-items: center;
    gap: 10px; padding: 0 14px; min-width: 0; font-size: var(--fs-small); color: var(--text); text-align: left;
    white-space: nowrap; }
  .srow + .srow { border-top: var(--bw) solid var(--line-soft); }
  /* the last row reaches into the surface's rounded corner: the hover fill follows it */
  .srow:last-child { border-bottom-right-radius: calc(var(--r-surface) - var(--bw)); }
  .srow:first-child { border-top-right-radius: calc(var(--r-surface) - var(--bw)); }
  /* a row is a list item: it highlights, it doesn't shrink (design language §5) */
  .link:hover { background: var(--ctl-hover); }
  .link:active { transform: none; background: var(--ctl-press); }
  .w { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .q { color: var(--text-muted); }
  .n { font-variant-numeric: tabular-nums; }
  .off { opacity: var(--dim-locked); }
  /* a row's dot: 7 px in its part's colour, centred in the marks' 14 px column */
  .dot { width: 7px; height: 7px; border-radius: var(--r-pill); justify-self: center; }
  .chev { width: 12px; height: 12px; fill: none; stroke: var(--text-label); stroke-width: 1.4; stroke-linecap: round;
    stroke-linejoin: round; }
  .link:hover .chev { stroke: var(--text); }

  /* more than two rows: three to a column, columns side by side, a rule between them; no › column (a row of many
     is a legend line) */
  .many { container-type: inline-size; }
  .many .grid { grid-template-columns: auto minmax(80px, 1fr) minmax(0, calc(var(--cols) * 192px)); }
  .many .rows { display: grid; grid-template-rows: repeat(3, minmax(0, 1fr)); grid-auto-flow: column;
    grid-auto-columns: minmax(0, 1fr); }
  .many .srow { grid-template-columns: 14px minmax(0, 1fr) auto; gap: var(--s-2); padding: 0 var(--s-3); border-radius: 0; }
  .many .srow + .srow { border-top: 0; }
  .many .srow:nth-child(n + 4) { border-left: var(--bw) solid var(--line-soft); }
  .many .srow:last-child { border-bottom-right-radius: calc(var(--r-surface) - var(--bw)); }
  /* too narrow for the rows beside the bar: they take a line of their own under the share and the bar */
  @container (max-width: 680px) {
    .many .grid { grid-template-columns: auto minmax(80px, 1fr); grid-template-rows: 70px 70px; height: auto;
      padding-left: 0; }
    .many .share { padding-left: var(--s-4); }
    .many .bar { padding-right: var(--s-4); }
    .many .rows { grid-column: 1 / -1; border-left: 0; border-top: var(--bw) solid var(--line-soft); }
    .many .srow:last-child { border-bottom-left-radius: 0; }
  }
</style>
