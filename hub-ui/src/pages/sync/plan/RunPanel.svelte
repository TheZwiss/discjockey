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
  // The import's two notes (plan library stage 4, W9) are NoteCards (up to three lines: a Hint is one line, and these
  // sentences wrap), each where its subject is: the songs that wait for an answer (yellow: they wait for the user)
  // under the counts, which they are why smaller, with To-do → as the card's action; the first upgrade checks left
  // for later runs (info) right under the day card, which speaks of today's allowance (a card inside the day card
  // would be a container in a container, spec §11).
  import type { Snippet } from 'svelte';
  import { Button, DayBar, Hint, ListRow, NoteCard, ProgressBar, Segmented, StatCard, Surface, ToggleGroup } from '$lib/components';
  import { Panel } from '$lib/frames';
  import type { SyncAccount } from '$lib/bridge/types';
  import {
    dayBarInput, folderItems, howManyOptions, isKindKey, kindItems, runCount, runTime, serviceRows, type Facet, type HowMany, type Preset,
    type RunTotals, type Scope, WAITING_ANSWERS_HREF, deferredChecksLine, waitingAnswersLine,
  } from '../planModel';
  import KindIcon from './KindIcon.svelte';

  let { summary, left, limit, accounts, presets, howMany, folders, kinds, scope, onhowmany, onscope, onscopeall,
    start, waitingAnswers = 0, deferredChecks = 0 }: {
    /** left null: no daily limit (only free sources are set up) */
    summary: RunTotals; left: number | null; limit: number; accounts: SyncAccount[];
    presets: Preset[]; howMany: HowMany | 'custom';
    folders: Facet[]; kinds: Facet[]; scope: Scope;
    onhowmany: (h: HowMany) => void; onscope: (what: 'folders' | 'kinds', key: string) => void;
    onscopeall: (what: 'folders' | 'kinds', keys: string[], on: boolean) => void;
    /** Start sync and what goes with it (console note, start problem) */
    start: Snippet;
    /** songs held back until the user answers "Is this the same song?" (SyncPreview.waiting_answers) */
    waitingAnswers?: number;
    /** first upgrade checks of imported music left for later runs (SyncPreview.deferred_checks) */
    deferredChecks?: number;
  } = $props();
  const waitingLine = $derived(waitingAnswersLine(waitingAnswers));
  const deferredLine = $derived(deferredChecksLine(deferredChecks));

  const limitReached = $derived(left === 0 && summary.downloads > 0);
  // the count says what Start says: what runs today (spec §11), the ticked downloads that wait not counted
  const run = $derived(runCount(summary.tracks, summary.downloads, summary.uses));
  const time = $derived(runTime(summary.minutes, run));
  // the ticked downloads that wait, said only when the DayBar's Later doesn't already say it (Later counts the plan in
  // scope after today; it equals the ticked ones that wait when everything in scope is picked)
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
    <StatCard value={run} label="track{run === 1 ? '' : 's'} this run" valueTest="sync-run-count" />
    <StatCard value={time.value} unit={time.unit} label="run time" data-test="sync-time" />
  </div>
  {#if waitingLine}
    <NoteCard tone="warn" data-test="sync-waiting-answers">{waitingLine}
      <div class="act"><Button variant="link" size="sm" href={WAITING_ANSWERS_HREF} data-test="sync-waiting-link">To-do →</Button></div>
    </NoteCard>
  {/if}
  <Surface kind="card" data-test="sync-day">
    <DayBar input={dayBarInput(summary, left)} data-test="sync-daybar" />
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
  {#if deferredLine}<NoteCard data-test="sync-deferred-checks">{deferredLine}</NoteCard>{/if}
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
  /* the card's action, on its own line under the sentence */
  .act { margin-top: var(--s-1); }
  .what { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .bar { flex: 1 1 auto; min-width: 0; }
  .backup { color: var(--text-label); font-size: var(--fs-small); }
  /* a fixed number column, so every service's bar starts and ends at the same x */
  .n { flex: none; width: var(--w-row-action); text-align: right; color: var(--text-muted); }
</style>
