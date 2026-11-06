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
  // The layout is ShareStrip's (issue 36: Sync's KindStrip is the same block); this file gives it Library's words,
  // the quality bar and the rows' marks.
  // `summary={null}`: waiting (dashes and the bar's shimmer), the same height.
  // `songs` (a read playlist's `{listed, with_file}`, sources round D10): the caption adds "13 of 18 downloaded" and
  // the bar ends in a dashed segment for the songs with no file yet, so it spans every song of the playlist; a view
  // that is no read playlist passes none and the caption and the bar are as before.
  import type { Library } from '../bridge/types';
  import QualityBar from './QualityBar.svelte';
  import ShareStrip, { type ShareRow } from './ShareStrip.svelte';
  import { stripView } from './summaryStripModel';

  let { summary, onupgrades, ontodo, songs = null }: {
    summary: Library['summary'] | null; onupgrades: () => void; ontodo: () => void; songs?: Library['songs'];
  } = $props();
  const v = $derived(stripView(summary, songs));
  const waiting = $derived(songs ? Math.max(0, songs.listed - songs.with_file) : 0);
  const rows = $derived<ShareRow[]>([
    { key: 'upgrades', mark: good, words: 'Upgrade ready', count: v.upgrades.count, test: 'strip-upgrades',
      onclick: v.upgrades.link ? onupgrades : null },
    { key: 'todo', mark: mix, words: 'Not lossless yet', quiet: v.notLossless.todo, count: v.notLossless.count,
      test: 'strip-todo', tip: v.notLossless.tip, onclick: v.notLossless.link ? ontodo : null },
  ]);
</script>

{#snippet good()}<span class="dot good" aria-hidden="true"></span>{/snippet}
{#snippet mix()}<span class="mix" aria-hidden="true" data-test="strip-mix">{#each v.mix as p (p.quality)}<i class={p.quality}
  style:flex-grow={p.n}></i>{/each}</span>{/snippet}
{#snippet bar()}<QualityBar by_quality={summary?.by_quality ?? null} {waiting} />{/snippet}

<ShareStrip value={v.share} unit="% lossless" line={v.line} {bar} {rows} test="summary-strip" valueTest="strip-share"
  lineTest="strip-line" />

<style>
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
</style>
