<script lang="ts">
  // One column's head in a sortable table (design system §7; Library): the column's name as a button of its natural
  // width (the rule checker's `button` rule: a header never stretches across its column), the arrow after it on the
  // sorted column. The cell it sits in is the `columnheader` and carries `aria-sort`, so the table says how it is
  // sorted without reading the arrow. `align="end"` puts it at the column's right edge (numbers). Clicking is the
  // page's: the same column flips, another one sorts ascending (libraryModel.nextSort). It highlights while held,
  // never shrinks (rule 2: text dims when held).
  // Without `onsort` it is a column the table can't sort by (Library's Subfolder and Playlist): the same words in the
  // same place as a plain label, no button, no hover and no `aria-sort`, so a sortable head and a static one sit in
  // one row of heads without a seam.
  let { label, sorted = null, align = 'start', onsort, test }: {
    label: string;
    /** this column's direction when it is the sorted one, else null */
    sorted?: 'asc' | 'desc' | null;
    align?: 'start' | 'end';
    /** none: a column that isn't sortable (a label, not a button) */
    onsort?: () => void; test?: string;
  } = $props();
</script>

{#if onsort}
  <span class="cell" class:end={align === 'end'} role="columnheader"
    aria-sort={sorted === 'asc' ? 'ascending' : sorted === 'desc' ? 'descending' : 'none'}>
    <button type="button" class="th" class:on={!!sorted} data-test={test} onclick={onsort}>
      {label}{#if sorted}<span class="arrow" aria-hidden="true">{sorted === 'desc' ? '↓' : '↑'}</span>{/if}
    </button>
  </span>
{:else}
  <span class="cell" class:end={align === 'end'} role="columnheader"><span class="th" data-test={test}>{label}</span></span>
{/if}

<style>
  .cell { display: flex; min-width: 0; }
  .cell.end { justify-content: flex-end; }
  .th { display: inline-flex; align-items: center; gap: var(--s-1); min-width: 0; overflow: hidden; border: 0;
    background: transparent; padding: var(--s-1) 0; color: var(--text-label); font-size: var(--fs-label);
    letter-spacing: var(--ls-label); text-transform: uppercase; white-space: nowrap; cursor: default; }
  button.th { transition: color var(--t-hover) var(--ease); }
  button.th:hover, .th.on { color: var(--text-muted); }
  button.th:active { transform: none; opacity: var(--link-press); }
</style>
