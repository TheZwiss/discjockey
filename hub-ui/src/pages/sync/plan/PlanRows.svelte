<script lang="ts">
  // The plan's rows, one list Surface per playlist folder (playlists.txt order), in the order the sync works through
  // them (spec §8). The head: the folder's name (folds the section), "N of M ticked" (plus "· W next sync" while
  // ticked rows wait for a later day), Tick all · None; it stays at the top while a long playlist scrolls by. A row
  // (ListRow): tick + cover · "Artist – Title" · why the track is in the run and "next sync" (Why) · ⊘ (NeverButton).
  // The why column exists only in a section that can fill it (a tag, or a download that may wait); a section of
  // plain new tracks gives its names the width instead of a blank 200 px. It is fixed for the page (`mayWait` doesn't
  // change with ticks), so ticking never makes the columns jump. The cost, accepted: a section where rows may wait
  // keeps the column blank until one does, so a very long name ends in "…" before it. On a narrow list (< 680 px) the column hides; tag
  // and "next sync" stay in the row's tooltip and description. When every ticked row of a section waits, the head
  // says it once and the rows drop the label (one fact, said once). A folded section stays folded while a search
  // hides and shows it again.
  import { SvelteSet } from 'svelte/reactivity';
  import { Cover, ListRow, Surface } from '$lib/components';
  import type { PreviewAction } from '$lib/bridge/types';
  import { artistTitle } from '$lib/format';
  import { canNever, kindOf, sectionSummary, tagOf, waitsWhole, whyColumn, type Section } from '../planModel';
  import { keyId } from '../selection';
  import NeverButton from './NeverButton.svelte';
  import { Tick } from '$lib/components';
  import WhyMark from './WhyMark.svelte';
  import Why from './Why.svelte';

  let { sections, ticked, nextSync, mayWait, neverBlocked, ontoggle, onfolder, onnever }: {
    sections: Section[]; ticked: Set<string>; nextSync: Set<string>;
    /** the plan holds more downloads than today's limit leaves, so a ticked download may wait for the next sync */
    mayWait: boolean;
    /** why ⊘ can't be used right now (another change runs), else null */
    neverBlocked: string | null;
    ontoggle: (a: PreviewAction) => void; onfolder: (folder: string, on: boolean) => void;
    onnever: (a: PreviewAction) => void;
  } = $props();

  // tick + 8 + cover 28 · name · why (200 px holds "from Hard_Bounce ● next sync") · ⊘
  const COLS = '--row-cols: 52px minmax(0, 1fr) 32px';
  // a narrow list (no why column) keeps the why as a mark before ⊘: the kind's icon (as in What to do) and the yellow
  // "next sync" dot, in a fixed 26 px slot so marks line up down the list (60 = mark 26 + gap 8 + ⊘ 26)
  const WIDE = '--row-cols: 52px minmax(0, 1fr) 60px; --row-cols-wide: 52px minmax(0, 1fr) 200px 32px';
  const closed = new SvelteSet<string>();
  const setOpen = (folder: string, open: boolean) => { if (open) closed.delete(folder); else closed.add(folder); };
</script>

{#each sections as s (s.folder)}
  {@const allWait = waitsWhole(s.waiting, s.downloads)}
  <Surface kind="list" label={s.folder} summary={sectionSummary(s.ticked, s.total, s.waiting)}
    summaryTest="sync-section-count" foldable bind:open={() => !closed.has(s.folder), (v) => setOpen(s.folder, v)}
    sticky style={whyColumn(s.rows, mayWait) ? WIDE : COLS} data-test="sync-section" data-folder={s.folder}
    bulk={{ all: 'Tick all', allOff: s.ticked === s.total, noneOff: s.ticked === 0, test: 'sync-section',
      onall: (on) => onfolder(s.folder, on) }}>
    {#each s.rows as a (keyId(a.key))}
      {@const id = keyId(a.key)}
      {@const on = ticked.has(id)}
      {@const tag = tagOf(a)}
      {@const waits = on && nextSync.has(id)}
      {@const next = waits && !allWait}
      {@const name = artistTitle(a.artist, a.title)}
      {#snippet lead()}<Tick {on} /><Cover url={a.cover_url} seed={a.track_id} size={28} />{/snippet}
      {#snippet line()}{name}{/snippet}
      {#snippet why()}<Why {tag} {next} />{/snippet}
      {#snippet end()}
        <WhyMark kind={tag ? kindOf(a) : null} {next} />
        {#if canNever(a)}<NeverButton {name} blocked={neverBlocked} onclick={() => onnever(a)} />{:else if tag || next}<span
          class="slot"></span>{/if}
      {/snippet}
      <ListRow {lead} name={line} optional={tag || next ? why : undefined} trailing={canNever(a) || tag || next ? end : undefined}
        off={!on} checked={on} onclick={() => ontoggle(a)} title={[name, tag, waits && 'next sync'].filter(Boolean).join(' · ')}
        test="sync-item" data-track={a.track_id} />
    {/each}
  </Surface>
{/each}

<style>
  /* keeps the mark slot (WhyMark, 26 px) on a row that has a why but no ⊘, so ⊘ columns line up */
  .slot { flex: none; width: 26px; }
</style>
