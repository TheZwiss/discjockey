<script lang="ts">
  // "This run" (spec §8), on `Panel`: head = what Start does today as two StatCards (count; run time), then the day
  // card: the DayBar (today against later under the daily limit), the amount Segmented (✦ marks what fits today) and
  // the line to Download limits; with more than one service their usage as a small list of its own under the card
  // (spec §11: a list nested in the card would be a container in a container); with today's limit used up a yellow
  // NoteCard, title only (the DayBar and Start already say what still runs). Fill = the Playlists ToggleGroup (takes
  // the spare height, scrolls inside, search from 7);
  // after = What to do (natural height); foot = Start sync and its console note (`start`, built by the page).
  // Labels and numbers, no sentences (spec §6): the old prose lines ("215 more after this run · ~4 more days…") are
  // now the DayBar's segments.
  import type { Snippet } from 'svelte';
  import { Button, DayBar, Hint, ListRow, NoteCard, ProgressBar, Segmented, StatCard, Surface, ToggleGroup } from '$lib/components';
  import { Panel } from '$lib/frames';
  import type { EstimateAccount } from '$lib/bridge/types';
  import {
    dayBarInput, folderItems, howManyOptions, isKindKey, kindItems, runCount, runTime, serviceRows, type Facet, type HowMany, type Preset,
    type RunTotals, type Scope,
  } from '../planModel';
  import KindIcon from './KindIcon.svelte';

  let { summary, left, limit, accounts, presets, howMany, folders, kinds, scope, moves, onhowmany, onscope, onscopeall,
    start }: {
    /** left null: no daily limit (only free sources are set up) */
    summary: RunTotals; left: number | null; limit: number; accounts: EstimateAccount[];
    presets: Preset[]; howMany: HowMany | 'custom';
    folders: Facet[]; kinds: Facet[]; scope: Scope;
    /** ticked moves (they run even when today's downloads are used up) */
    moves: number;
    onhowmany: (h: HowMany) => void; onscope: (what: 'folders' | 'kinds', key: string) => void;
    onscopeall: (what: 'folders' | 'kinds', keys: string[], on: boolean) => void;
    /** Start sync and what goes with it (console note, start problem) */
    start: Snippet;
  } = $props();

  const limitReached = $derived(left === 0 && summary.downloads > 0);
  // the count says what Start says: what runs today (spec §11), the ticked downloads that wait not counted; only
  // moves when that is all that runs ("Start sync · 1 move")
  const run = $derived(runCount(summary.tracks, summary.downloads, summary.uses, moves));
  const time = $derived(runTime(summary.minutes, run.n));
  // the ticked downloads that wait, said only when the DayBar's Later doesn't already say it (Later counts the whole
  // plan after today; it equals the ticked ones that wait when everything is picked)
  const overflow = $derived(left !== null && left > 0 && summary.waiting > 0 && summary.waiting !== summary.after);
  const services = $derived(accounts.length > 1 ? serviceRows(accounts, summary.downloads, { limitReached }) : []);
  const options = $derived(howManyOptions(presets));
  const fits = $derived(presets.some((p) => p.value === 'fits'));
  // one line under the amount: what ✦ means and the limit the later segment is counted in, the way to change it at the
  // right (a separate hint line cost 20 px in a panel that already scrolls at 1100 × 700)
  const limitsLine = $derived([fits && '✦ fits today', left !== null && `${limit} a day`].filter(Boolean).join(' · '));
  function pick(key: string) {
    const p = presets.find((x) => String(x.value) === key);
    if (p) onhowmany(p.value);
  }
</script>

{#snippet head()}
  <div class="stats" data-test="sync-summary">
    <StatCard value={run.n} label="{run.unit}{run.n === 1 ? '' : 's'} this run" valueTest="sync-run-count" />
    <StatCard value={time.value} unit={time.unit} label="run time" data-test="sync-time" />
  </div>
  <Surface kind="card" data-test="sync-day">
    <DayBar input={dayBarInput(summary, left, moves)} data-test="sync-daybar" />
    {#if overflow}
      <Hint text="{summary.waiting} ticked wait for the next sync" data-test="sync-overflow" />
    {/if}
    {#if options.length > 1}
      <Segmented {options} value={String(howMany)} onchange={pick} label="How many downloads" test="sync-howmany" />
    {/if}
    <div class="limits" data-test="sync-after">
      <span class="what">{limitsLine}</span><Button variant="link" size="sm" href="#/limits" data-test="sync-limits-link">Download limits →</Button>
    </div>
  </Surface>
  {#if services.length}
    <Surface kind="list" style="--row-cols: minmax(0, 1fr) 132px" data-test="sync-estimate">
      {#each services as s (s.service)}
        {#snippet name()}{s.name}{/snippet}
        <!-- a backup behind Qobuz gets no bar (an empty one reads as unused): "backup" in its place -->
        {#snippet use()}<span class="bar">{#if s.value === null}<span class="backup">backup</span>{:else}<ProgressBar
          value={s.value} pace="reply" label={s.text} />{/if}</span><span class="n">{s.short}</span>{/snippet}
        <ListRow {name} trailing={use} title={s.text} test="sync-estimate-{s.service}" />
      {/each}
    </Surface>
  {/if}
  {#if limitReached}
    <NoteCard tone="warn" title="Downloads start tomorrow" data-test="sync-limit-reached" />
  {/if}
{/snippet}

{#snippet fill()}
  <ToggleGroup label="Playlists" items={folderItems(folders, scope)} grow test="sync-playlists" rowTest="sync-scope-folder"
    onchange={(key) => onscope('folders', key)} onall={(on, keys) => onscopeall('folders', keys, on)} />
{/snippet}

{#snippet after()}
  <ToggleGroup label="What to do" items={kindItems(kinds, scope)} search={false} test="sync-kinds" rowTest="sync-scope-kind"
    onchange={(key) => onscope('kinds', key)} onall={(on, keys) => onscopeall('kinds', keys, on)}>
    {#snippet lead(item)}<span class="toggle-icon">{#if isKindKey(item.key)}<KindIcon kind={item.key} />{/if}</span>{/snippet}
  </ToggleGroup>
{/snippet}

<div class="run-panel" data-test="sync-panel">
  <Panel {head} fill={folders.length > 1 ? fill : undefined} after={kinds.length > 1 ? after : undefined} foot={start} />
</div>

<style>
  .run-panel { display: contents; }
  .stats { display: grid; grid-template-columns: 1fr 1fr; gap: var(--s-3); }
  /* the limit (what the later segment is measured in) at the left, the way to change it at the card's right edge */
  .limits { display: flex; align-items: baseline; justify-content: space-between; gap: var(--s-3); min-width: 0;
    font-size: var(--fs-small); color: var(--text-muted); white-space: nowrap; }
  .what { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .bar { flex: 1 1 auto; min-width: 0; }
  .backup { color: var(--text-label); font-size: var(--fs-small); }
  /* a fixed number column, so every service's bar starts and ends at the same x */
  .n { flex: none; width: var(--w-row-action); text-align: right; color: var(--text-muted); }
</style>
