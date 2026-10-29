<script lang="ts">
  // The raised container (design system §5, §7): everything on screen sits in one. `card` is padded, `list` holds
  // grouped rows (separated by hairlines, no inner padding), `table` is a bare shell for a table. Sets
  // `data-surface` for the rule checker (long text and row buttons are allowed inside). `label` is the group's
  // title (sentence case, see below), `summary` the "N of M on" count after it, `header` extra controls at the right of the head, `bulk` the
  // group's "All · None" links there (spec §11: one spelling for every list that turns many rows on or off; `all`
  // renames the first link, "Tick all"; `test` prefixes `-all` / `-none`); `summaryTest` is the summary's `data-test`. `tone` colours only the border, with the quality colours' outline. Other attributes
  // (`class`, `style` for `--row-cols`, `data-test`) go onto the root.
  // A labelled surface is a group named by its visible caption (`aria-labelledby`), not a landmark: Sync has one
  // list per playlist, and a dozen `region`s would flood VoiceOver's landmark menu and read each name twice. A role
  // or `aria-labelledby` the caller passes wins (NoteCard is a `note`).
  // The rows area of a list or table is the `list` container that ListRow's optional columns query
  // (`@container list (…)`), so a column depends on the list's own width (spec §3).
  // Head hierarchy (spec §11, Task 9): the label is a title in sentence case (13 px semibold, --text), so a section
  // named after the user's folder keeps its spelling and reads first; the summary sits right after it (12 px,
  // --text-muted) because it belongs to the name; the header actions sit alone at the right edge, where a row's own
  // actions sit. Uppercase captions stay for values (StatCard) and panel captions, not for a group's name.
  // `foldable` turns the label into the disclosure button (chevron in a 16 px box, the tick's width, so the label
  // starts where the rows' covers do in Sync); `open` is bindable, a closed surface keeps only its head. `sticky`
  // keeps the head at the top of the scrolling area while its rows scroll by (a long playlist keeps its name and
  // Tick all · None in view); the scroller may set `--sticky-top` (ListPanelFrame does, for its padding). A list
  // clips with `overflow: clip`, which doesn't make it a scroller, so its head can stick to the page's scroller.
  // `grow` (a list of unknown length: Dashboard's folders and runs) takes the height its column gives it, up to its
  // rows' height, never less than 3 rows (fewer in a smaller list) plus half a row's peek; its head stays and its
  // rows scroll inside it with faded ends (edgeFade). `rows` is how many it has, `tall` that they carry a second line
  // (52 px). In Panel's `fill` it rounds its cut to the peek like ToggleGroup `grow` (growFill); in a page frame's
  // list it marks itself `data-scrolls-itself`, so the frame keeps the list area at the window's height.
  // A grown list may name its groups with `ListSection` heads among its rows (To-do); they stick while their rows pass.
  // `columns` (a table's column head, Library: `SortHeader`s) sits ruled between the head and the rows and never
  // scrolls, so the rows' faded top end passes under it, not over it. It is a `list` container of the rows' width,
  // so a column the rows show by `@container list` shows in the head at the same width. `scroller` (bindable) is
  // the rows' scrolling element of a `grow` surface, for a table that renders only its visible rows.
  import { getContext } from 'svelte';
  import { edgeFade } from './edgeFade';
  import { growFill } from './growFill';
  import { fitHeadLabel } from './fitPathAction';
  import { GROW_SPARE, type GrowSpareHost } from './toggleModel';
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';
  import Button from './Button.svelte';

  /** "All · None" in the head: each link is off when it would change nothing; `onall(true)` is All. */
  export type Bulk = { all?: string; allOff: boolean; noneOff: boolean; onall: (on: boolean) => void; test?: string };

  type Props = Omit<HTMLAttributes<HTMLElement>, 'children'> & {
    kind?: 'card' | 'list' | 'table'; label?: string; summary?: string; hint?: string; fitLabel?: string;
    tone?: 'default' | 'good' | 'warn' | 'problem'; header?: Snippet; children: Snippet; padded?: boolean;
    foldable?: boolean; open?: boolean; sticky?: boolean; summaryTest?: string; bulk?: Bulk;
    grow?: { rows: number; tall?: boolean }; columns?: Snippet; scroller?: HTMLElement | null;
  };
  let { kind = 'card', label, summary, hint, fitLabel, tone = 'default', header, children, padded, foldable = false, open = $bindable(true),
    sticky = false, summaryTest, bulk, grow, columns, scroller = $bindable(null), class: className, ...rest }: Props = $props();
  // a card is padded, a list or table runs edge to edge unless asked otherwise
  const pad = $derived(padded ?? kind === 'card');
  const hasHead = $derived(!!(label || summary || header || bulk));
  const uid = $props.id();
  const shown = $derived(!foldable || open);
  const host = getContext<GrowSpareHost | undefined>(GROW_SPARE);
  const growStyle = $derived(grow ? `--min-rows: ${Math.min(3, Math.max(1, grow.rows))}; --grow-row: var(${grow.tall
    ? '--h-list-row-tall' : '--h-list-row'}); --peek: ${grow.rows > 3 ? 'calc(var(--grow-row) / 2)' : '0px'}` : undefined);
</script>

{#snippet head()}
  <div class="head" class:inset={pad} class:sticky class:ruled={!pad && shown} class:wraps={!!fitLabel}>
    {#if label && foldable}
      <button type="button" class="fold" data-row-hit aria-expanded={open} aria-controls={open ? `${uid}-body` : undefined} onclick={() => (open = !open)}>
        <svg class="chev" class:open viewBox="0 0 16 16" aria-hidden="true"><path d="M6 4l4 4-4 4" /></svg><span class="title" id="{uid}-label">{label}</span>
      </button>
    {:else if label && fitLabel}<span class="title path" id="{uid}-label" title={fitLabel}
      use:fitHeadLabel={fitLabel}><span></span><span></span></span>
    {:else if label}<span class="title" id="{uid}-label">{label}</span>{/if}
    {#if summary}<span class="summary" data-test={summaryTest}>{summary}</span>{/if}
    {#if hint}<span class="hint">{hint}</span>{/if}
    {#if header || bulk}
      <div class="extra">
        {@render header?.()}
        {#if bulk}
          <Button variant="link" muted size="sm" disabled={bulk.allOff} onclick={() => bulk.onall(true)}
            data-test={bulk.test && `${bulk.test}-all`}>{bulk.all ?? 'All'}</Button>
          <span class="dot" aria-hidden="true">·</span>
          <Button variant="link" muted size="sm" disabled={bulk.noneOff} onclick={() => bulk.onall(false)}
            data-test={bulk.test && `${bulk.test}-none`}>None</Button>
        {/if}
      </div>
    {/if}
  </div>
{/snippet}

<div {...rest} class="surface {kind} tone-{tone} {className ?? ''}" class:pad class:grow={!!grow}
  style={[growStyle, rest.style].filter(Boolean).join('; ') || undefined} data-scrolls-itself={grow ? '' : undefined} role={rest.role ?? (label ? 'group' : undefined)}
  aria-labelledby={rest['aria-labelledby'] ?? (label ? `${uid}-label` : undefined)} data-surface={kind}>
  {#if hasHead}{@render head()}{/if}
  {#if shown}
    {#if columns && !pad}<div class="columns">{@render columns()}</div>{/if}
    {#if pad}<div class="body" id="{uid}-body">{@render children()}</div>
    {:else if grow}<div class="rows scroll" id="{uid}-body" bind:this={scroller} use:edgeFade use:growFill={host}>{@render children()}</div>
    {:else}<div class="rows" id="{uid}-body">{@render children()}</div>{/if}
  {/if}
</div>

<style>
  .surface {
    background: var(--surface); border: var(--bw) solid var(--surface-line); border-radius: var(--r-surface);
    box-shadow: var(--surface-highlight); min-width: 0; display: flex; flex-direction: column;
  }
  .surface.list { background: var(--surface-list); overflow: clip; }
  .surface.table { overflow: hidden; }
  .pad { padding: var(--s-4); gap: var(--s-3); }
  .body { display: contents; }
  .rows { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; container: list / inline-size; }
  .list > .rows > :global(:not(:first-child)) { border-top: var(--bw) solid var(--line-soft); }
  /* up to its rows' height, never an empty box; never less than --min-rows whole rows plus --peek: head
     --h-list-row + its rule, rows × --grow-row + (rows − 1) row rules, the 2 borders (as ToggleGroup grow) */
  .grow { flex: 0 1 auto;
    min-height: calc(var(--h-list-row) + var(--min-rows) * var(--grow-row) + (var(--min-rows) + 2) * var(--bw) + var(--peek)); }
  .rows.scroll { overflow: hidden auto; }
  /* a list's rows keep their height: in this flex column a child would otherwise shrink as soon as the rows outgrow
     the scroller (a row without a min-height, a table's spacer standing in for rows it doesn't render) */
  .rows > :global(*) { flex-shrink: 0; }
  .columns { flex: none; container: list / inline-size; border-bottom: var(--bw) solid var(--line-soft); }
  /* with ListSections, the stuck head is the scroller's top edge: the rows pass under it, so that end doesn't fade
     (it would fade the head itself) */
  .rows.scroll:has(> :global([data-list-section]))[data-fade-above] { --fade-top: black; }
  /* and a row scrolled into view (arrow keys, ?track=) stops below the stuck head, not under it */
  .rows.scroll:has(> :global([data-list-section])) > :global(*) { scroll-margin-top: var(--h-section); }
  .head { display: flex; align-items: center; gap: var(--s-2); min-height: var(--h-list-row); padding: 0 var(--s-4);
    min-width: 0; }
  .head.inset { min-height: 0; padding: 0; }
  /* a head with a fitted path: when the path is not whole beside the head's links, they wrap below it, so the path takes the head's width (fitHeadLabel) */
  .head.wraps { flex-wrap: wrap; row-gap: var(--s-1); }
  /* the hairline under the head sits on the head, so it stays with it while the head is stuck */
  .head.ruled { border-bottom: var(--bw) solid var(--line-soft); }
  .head.sticky { position: sticky; top: var(--sticky-top, 0); z-index: 1; background: var(--surface-list); }
  .title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text);
    font-size: var(--fs-body); font-weight: var(--fw-semi); }
  .fold { display: inline-flex; align-items: center; gap: var(--s-2); min-width: 0; min-height: 28px; padding: 0;
    color: var(--text); text-align: left; }
  .fold:active { transform: none; opacity: var(--link-press); }   /* text dims when held, never shrinks (rule 2) */
  .chev { flex: none; width: 16px; height: 16px; fill: none; stroke: var(--text-muted); stroke-width: 1.6;
    stroke-linecap: round; stroke-linejoin: round; transition: transform var(--t-press) var(--ease); }
  .chev.open { transform: rotate(90deg); }
  .fold:hover .chev { stroke: var(--text); }
  .title.path { flex: none; max-width: 100%; }
  /* a group's one-line hint, as ListSection's (name · count · hint): the same two spans, the same colours */
  .hint { flex: 1 1 0; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    color: var(--text-label); font-size: var(--fs-small); }
  .summary { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    color: var(--text-muted); font-size: var(--fs-small); font-variant-numeric: tabular-nums; }
  .extra { flex: none; margin-left: auto; display: flex; align-items: center; gap: var(--s-2); }
  /* a Hint in the head (a locked ToggleGroup's reason) gives way with the label and summary and cuts with its
     ellipsis; links and buttons there keep their width */
  .extra:has(> :global([data-hint])) { flex-shrink: 1; min-width: 0; }
  /* the separator matches the small links it sits between */
  .dot { color: var(--text-label); font-size: var(--fs-small); }
  .tone-good { border-color: var(--q-lossless-line); }
  .tone-warn { border-color: var(--q-good-line); }
  .tone-problem { border-color: var(--q-weak-line); }
</style>
