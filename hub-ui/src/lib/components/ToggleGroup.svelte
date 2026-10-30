<script lang="ts">
  // On/off for several items (design system §4): a grouped list of ToggleRows with "N of M on" and All · None in
  // its head (muted links), and a search field from SEARCH_FROM rows (accent- and case-insensitive). All · None act on
  // the rows the search shows: `onall(on, keys)` gets their keys (every key without a search); `setOn` applies it.
  // With `grow` the group takes the height it is given up to its rows' height (Panel's `fill`), never less than 3 rows
  // (it knows whether it shows a search, so the minimum is its own), and its rows scroll; an end with more rows
  // beyond it fades (edgeFade). When it is cut, the cut lands half a row into the next row (the peek), never on a row's edge: it
  // hands the few px above that to its host (Panel's spacer above the foot, `GROW_SPARE`), measured from the space it
  // is given (its box plus what the spacer holds), so applying the spare changes nothing (spec §11, issue 10). Rows that
  // come or go above the ones on screen (a list read again while it grows: Settings' crates during an import) leave
  // those where they are (scrollAnchor).
  import { getContext } from 'svelte';
  import type { Snippet } from 'svelte';
  import Hint from './Hint.svelte';
  import SearchField from './SearchField.svelte';
  import Surface from './Surface.svelte';
  import ToggleRow from './ToggleRow.svelte';
  import { edgeFade } from './edgeFade';
  import { growFill } from './growFill';
  import { scrollAnchor } from './scrollAnchor';
  import { allDisabled, filterItems, groupSummary, GROW_SPARE, SEARCH_FROM, visibleKeys, type GrowSpareHost,
    type ToggleItem } from './toggleModel';

  let { label, items, lead, onchange, onall, test, rowTest, grow = false, disabled = false, disabledReason,
    search = true, placeholder, allMax }:
    { label: string; items: ToggleItem[]; lead?: Snippet<[ToggleItem]>; onchange: (key: string, on: boolean) => void;
      onall: (on: boolean, keys: string[]) => void; test?: string; rowTest?: string; grow?: boolean; disabled?: boolean;
      /** why the group is off: each row's tooltip, and a one-line Hint in the group's head in place of the All · None
       *  it locks (as a disabled Button's title; final review fix B: under the group it sat a gap away, as far from
       *  its group as from the next one) */
      disabledReason?: string;
      /** false: a fixed set the app defines (Sync's kinds), never the user's own list, needs no search (spec §11) */
      search?: boolean;
      /** the search's words (default "Search {label}…"), when the label alone doesn't say what is searched */
      placeholder?: string;
      /** All is off while more rows than this show: a list whose whole would flood where it switches things on
       *  (Settings' crates of a folder with too many of them) asks for a search first, None stays */
      allMax?: number } = $props();

  let query = $state('');
  const searchable = $derived(search && items.length >= SEARCH_FROM);
  // a group that shrinks below SEARCH_FROM drops its search field, and with it any leftover query (else the old
  // filter would come back unseen when the group grows to SEARCH_FROM again)
  $effect(() => { if (!searchable) query = ''; });
  const shown = $derived(searchable ? filterItems(items, query) : items);
  // the grow minimum (spec §11): up to 3 whole rows, fewer when the group has fewer (never an empty box), counted on
  // `items`, not `shown`, so a search doesn't make the box jump; with more than 3, half a row's peek of the next row under
  // the end fade says "more below" (the iOS peek), where a cut exactly on a row edge read as the whole list
  const minRows = $derived(Math.min(3, Math.max(1, items.length)));
  const minStyle = $derived(grow ? `--min-rows: ${minRows}; --peek: ${items.length > 3 ? 'calc(var(--h-row) / 2)' : '0px'}` : undefined);
  // both links are off when they would change nothing among the shown rows (also in an empty group or search)
  // (All also while more than `allMax` rows show)
  const allIdle = $derived(allDisabled(shown, allMax));
  const noneOn = $derived(shown.every((i) => !i.on));
  const setAll = (on: boolean) => onall(on, visibleKeys(items, searchable ? query : ''));
  const sub = (suffix: string) => (test ? `${test}-${suffix}` : undefined);

  // above its minimum, a cut group rounds its rows' area down to whole rows plus the peek (growFill)
  const host = getContext<GrowSpareHost | undefined>(GROW_SPARE);
  const locked = $derived(disabled && !!disabledReason);
</script>

{#snippet reason()}<Hint text={disabledReason ?? ''} data-test={sub('reason')} />{/snippet}
<Surface kind="list" {label} summary={items.length ? groupSummary(items) : undefined} data-test={test} class="toggle-group{grow ? ' toggle-grow' : ''}{searchable ? ' searchable' : ''}" style={minStyle}
  header={locked ? reason : undefined} bulk={locked ? undefined : { allOff: disabled || allIdle, noneOff: disabled || noneOn, onall: setAll, test }}>
  {#if searchable}
    <div class="find"><SearchField bind:value={query} placeholder={placeholder ?? `Search ${label.toLowerCase()}…`} test={sub('search')} /></div>
  {/if}
  <div class="scroller" use:edgeFade use:scrollAnchor use:growFill={grow ? host : undefined}>
    {#each shown as item (item.key)}
      {#snippet rowLead()}{@render lead?.(item)}{/snippet}
      <ToggleRow {item} {onchange} {disabled} title={disabled ? disabledReason : item.tip} test={rowTest} lead={lead ? rowLead : undefined} />
    {:else}
      <div class="none">{query.trim() ? `No match for “${query.trim()}”` : 'Nothing here yet'}</div>
    {/each}
  </div>
</Surface>

<style>
  /* (`toggle-grow`, not `grow`: Surface's own `class:grow` directive, off for a group, took a plain "grow" token out
     of the class, so no group ever grew; B7)
     up to its rows' height, never an empty box; never less than --min-rows whole rows (3, fewer in a smaller group)
     plus --peek (spec §11, Task 9B fix rounds 1 and 2), from the real sizes: head --h-list-row + its rule, [search
     --h-ctl + 2 × --s-2], rows × --h-row + (rows − 1) row rules, the Surface's 2 borders: 3 rows 159 px (+19 peek),
     205 px with a search (+19 peek); the peek is half a row (issue 10) */
  :global(.toggle-group.toggle-grow) { flex: 0 1 auto;
    min-height: calc(var(--h-list-row) + var(--min-rows) * var(--h-row) + (var(--min-rows) + 2) * var(--bw) + var(--peek)); }
  :global(.toggle-group.toggle-grow.searchable) {
    min-height: calc(var(--h-list-row) + var(--h-ctl) + 2 * var(--s-2) + var(--min-rows) * var(--h-row)
      + (var(--min-rows) + 2) * var(--bw) + var(--peek)); }
  .find { padding: var(--s-2) var(--s-4); }
  .find > :global(.sf) { display: flex; width: 100%; min-width: 0; }
  .scroller { flex: 1 1 auto; min-height: 0; overflow: hidden auto; display: flex; flex-direction: column; }
  .scroller > :global(* + *) { border-top: var(--bw) solid var(--line-soft); }
  .none { padding: var(--s-3) var(--s-4); color: var(--text-muted); font-size: var(--fs-small); }
</style>
