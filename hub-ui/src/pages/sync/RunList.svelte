<script lang="ts">
  // Below the live card (design system §8 Running): the filter strip (Segmented: All · Lossless · Lossy · Problems,
  // with dots and counts, once there is a result to filter), then Problems, Done and Up next as list Surfaces of
  // ListRows. A row's badge and its Fix → sit in the trailing column; every list of the view keeps the action's slot,
  // so the badges (and Up next's folders) share one right edge down the whole column (§12 edges).
  import { Badge, Button, Cover, Hint, ListRow, Segmented, Surface } from '$lib/components';
  import { run } from '$lib/stores/run';
  import { getPref } from '$lib/prefs';
  import { artistTitle } from '$lib/format';
  import { PREF_LAST_SELECTION, upNext, type Picked } from './selection';
  import { coverMap, fixHref, listFor, rowBadge, segOptions, type ListChip } from './results';

  let chip = $state<ListChip>('all');
  const selection = getPref<Picked[]>(PREF_LAST_SELECTION, []);

  const results = $derived($run.results.map((e) => e.result));
  const options = $derived(segOptions(results));
  const list = $derived(listFor(results, chip));
  const plan = $derived<{ track_id: string; artist: string; title: string; folder?: string }[]>(
    $run.planned.length ? $run.planned : selection);
  const covers = $derived(coverMap(selection, $run.planned));
  const done = $derived($run.results.map((e) => e.action.track_id));
  const next = $derived(upNext(plan, done, $run.current?.track_id ?? null));
  const moreOnly = $derived(!plan.length && $run.total !== null ? Math.max(0, $run.total - $run.index) : null);
  const COLS = '--row-cols: 28px minmax(0, 1fr) auto';
</script>

{#snippet cover(id: string | null | undefined, seed: string)}<Cover url={covers.get(id ?? '') ?? null} {seed} size={28} />{/snippet}

<div class="runlist" data-test="sync-runlist">
  {#if results.length}
    <Segmented {options} value={chip} onchange={(k) => (chip = k)} label="Show results" test="sync-chips" />
  {/if}
  {#if (results.length || chip !== 'all') && !list.problems.length && !list.done.length}
    <Hint text="Nothing here yet" data-test="sync-none" />
  {/if}

  {#if list.problems.length}
    <Surface kind="list" label="Problems" summary={String(list.problems.length)} data-test="sync-problems" style={COLS}>
      {#each list.problems as r, i (i)}
        {@const b = rowBadge(r)}
        {@const fix = fixHref(r)}
        <ListRow test="sync-result" data-section={r.section} title={artistTitle(r.artist, r.title)}>
          {#snippet lead()}{@render cover(r.track_id, r.track_id ?? r.title)}{/snippet}
          {#snippet name()}{artistTitle(r.artist, r.title)}{/snippet}
          {#snippet trailing()}
            <Badge tone={b.tone} text={b.text} />
            <span class="act">{#if fix}<Button variant="link" size="sm" href={fix} data-test="sync-fix">Fix →</Button>{/if}</span>
          {/snippet}
        </ListRow>
      {/each}
    </Surface>
  {/if}

  {#if list.done.length}
    <Surface kind="list" label="Done" summary={String(list.done.length)} data-test="sync-done" style={COLS}>
      {#each list.done as r, i (i)}
        {@const b = rowBadge(r)}
        <ListRow test="sync-result" data-section={r.section} title={artistTitle(r.artist, r.title)}>
          {#snippet lead()}{@render cover(r.track_id, r.track_id ?? r.title)}{/snippet}
          {#snippet name()}{artistTitle(r.artist, r.title)}{/snippet}
          {#snippet trailing()}<Badge tone={b.tone} text={b.text} /><span class="act"></span>{/snippet}
        </ListRow>
      {/each}
    </Surface>
  {/if}

  {#if next.length}
    <Surface kind="list" label="Up next" summary={String(next.length)} data-test="sync-up-next" style={COLS}>
      {#each next as a (a.track_id)}
        <ListRow title={artistTitle(a.artist, a.title)}>
          {#snippet lead()}{@render cover(a.track_id, a.track_id)}{/snippet}
          {#snippet name()}<span class="waits">{artistTitle(a.artist, a.title)}</span>{/snippet}
          {#snippet trailing()}{#if a.folder}<span class="folder">{a.folder}</span>{/if}<span class="act"></span>{/snippet}
        </ListRow>
      {/each}
    </Surface>
  {:else if moreOnly}
    <Surface kind="list" label="Up next" data-test="sync-up-next">
      <ListRow>{#snippet name()}<span class="waits">{moreOnly} more</span>{/snippet}</ListRow>
    </Surface>
  {/if}
</div>

<style>
  /* the frame's gap between the strip and the lists, so the column keeps one rhythm */
  .runlist { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
  /* the action's slot, in every list of the view: the badges' right edges line up whether or not a row has one.
     64 px fits Review →, the widest row action; the end screen uses the same width (§11, Task 10B fix round 1) */
  .act { display: inline-flex; justify-content: flex-end; min-width: var(--w-row-action); }
  .waits { color: var(--text-muted); }
  .folder { color: var(--text-label); max-width: 200px; overflow: hidden; text-overflow: ellipsis; }
</style>
