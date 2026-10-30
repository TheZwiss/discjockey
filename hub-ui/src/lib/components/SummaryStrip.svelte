<script lang="ts">
  // A collection at a glance, laid along the page (plan library stage 5 A3.4, notes N5, house rule 3): Library's
  // panel left the page, and its summary card became this 72 px strip between the header and the filter segments.
  //   [63 % lossless / 290 of 460 checked tracks] [the quality bar] | ● Upgrade ready      6 ›
  //                                                                  | ● Not lossless yet · 41 in To-do   170 ›
  // The share is a stat (StatCard's type: 30 px number, its unit and label under it), the bar is the QualityBar, and
  // the two rows say where to go from here, each with its count. No legend: the filter segments right below carry the
  // same dots and counts. A row is a link only when it leads somewhere: Upgrade ready (`onupgrades`, the page shows
  // the Upgrade ready segment) while there are upgrades, Not lossless yet (`ontodo`, opens To-do) while some of them
  // are on the to-do list; at none it keeps its words and count without › (stripView, the words of I7). Fewer in
  // To-do than not lossless explains itself in a Tip under the row (the row takes focus for it when it is no link). The summary
  // ignores the search and the filter (views.library), so the strip stays the collection's while the table narrows.
  // Each row's mark says what it counts in the qualities' colours: Upgrade ready the lossless dot (its segment's dot
  // below); Not lossless yet holds good lossy, weak and fake together, so its mark is those colours side by side in
  // proportion (`stripView.mix`), the not-lossless part of the bar beside it, never one quality's dot (red alone
  // would claim "weak" for the whole group, and red is the Weak segment's dot right below).
  // `summary={null}`: waiting (dashes and the bar's shimmer), the same height.
  import type { Library } from '../bridge/types';
  import QualityBar from './QualityBar.svelte';
  import Surface from './Surface.svelte';
  import { stripView } from './summaryStripModel';
  import { tip as tipAction } from './tip';

  let { summary, onupgrades, ontodo }: {
    summary: Library['summary'] | null; onupgrades: () => void; ontodo: () => void;
  } = $props();
  const v = $derived(stripView(summary));
</script>

{#snippet chev()}<svg class="chev" viewBox="0 0 12 12" aria-hidden="true"><path d="M4.5 2.5 8 6l-3.5 3.5" /></svg>{/snippet}

{#snippet mark(tone: 'good' | 'mix')}
  {#if tone === 'good'}<span class="dot good" aria-hidden="true"></span>
  {:else}<span class="mix" aria-hidden="true" data-test="strip-mix">{#each v.mix as p (p.quality)}<i class={p.quality}
    style:flex-grow={p.n}></i>{/each}</span>{/if}
{/snippet}

{#snippet row(tone: 'good' | 'mix', link: boolean, onclick: () => void, n: string, test: string, words: string, todo: string | null, tip: string | null)}
  {#if link}
    <button type="button" class="srow link" data-row-hit data-test={test} use:tipAction={tip} {onclick}>
      {@render mark(tone)}<span class="w">{words}{#if todo}<span class="q">{` · ${todo}`}</span>{/if}</span>
      <span class="n">{n}</span>{@render chev()}
    </button>
  {:else}
    <!-- a row that explains itself takes focus, so its tip opens from the keyboard too (the tooltip pattern needs a
         focusable trigger); it stays a plain row, it does nothing when pressed -->
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <div class="srow" data-test={test} use:tipAction={tip} tabindex={tip ? 0 : undefined}>
      {@render mark(tone)}<span class="w">{words}{#if todo}<span class="q">{` · ${todo}`}</span>{/if}</span>
      <span class="n">{n}</span><span></span>
    </div>
  {/if}
{/snippet}

<Surface class="strip" padded={false} data-test="summary-strip">
  <div class="grid">
    <div class="share">
      <!-- without a share the line names it, so the unit doesn't stand beside a dash -->
      <div class="num"><span data-test="strip-share">{v.share ?? '—'}</span>{#if v.share !== null}<span class="unit">% lossless</span>{/if}</div>
      <div class="label" data-test="strip-line">{v.line}</div>
    </div>
    <div class="bar"><QualityBar by_quality={summary?.by_quality ?? null} /></div>
    <div class="rows">
      {@render row('good', v.upgrades.link, onupgrades, v.upgrades.count, 'strip-upgrades', 'Upgrade ready', null, null)}
      {@render row('mix', v.notLossless.link, ontodo, v.notLossless.count, 'strip-todo', 'Not lossless yet',
        v.notLossless.todo, v.notLossless.tip)}
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
  /* the marks share one 14 px column, centred on it, so both rows' words start at one x */
  .dot { width: 7px; height: 7px; border-radius: var(--r-pill); justify-self: center; }
  .dot.good { background: var(--q-lossless); }
  /* the bar's own colours and its 6 px height, a pill 14 px long; empty (none, or waiting) it is the bar's empty track */
  .mix { display: flex; width: 14px; height: 6px; border-radius: var(--r-pill); overflow: hidden;
    background: var(--bg-inset); }
  .mix i { display: block; flex-basis: 0; min-width: 2px; }
  .mix .good_lossy { background: var(--q-good-bar); }
  .mix .weak { background: var(--q-weak-bar); }
  .mix .fake { background: var(--q-fake-bar); }
  .chev { width: 12px; height: 12px; fill: none; stroke: var(--text-label); stroke-width: 1.4; stroke-linecap: round;
    stroke-linejoin: round; }
  .link:hover .chev { stroke: var(--text); }
</style>
