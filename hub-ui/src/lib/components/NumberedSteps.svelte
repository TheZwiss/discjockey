<script lang="ts">
  // Steps to follow in order (Setup's Spotify app, Qobuz's "give your account a password"): numbered rows, the number
  // in a 20 px ring, the text beside it. Children are the rows, each an `<li>` whose parts are elements: its text in
  // one element (a `<span>`), then any control under it (a CopyCode, a field, a button), which lines up with the
  // text, never under the number. (Loose text beside a `<b>` would split into several grid items.)
  import type { Snippet } from 'svelte';
  let { children, test }: { children: Snippet; test?: string } = $props();
</script>

<ol class="steps" data-test={test}>{@render children()}</ol>

<style>
  .steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--s-3);
    counter-reset: step; }
  .steps > :global(li) { display: grid; grid-template-columns: 20px minmax(0, 1fr); column-gap: var(--s-2);
    row-gap: var(--s-2); align-items: start; color: var(--text); counter-increment: step; }
  .steps > :global(li)::before { content: counter(step); grid-row: 1; grid-column: 1; width: 20px; height: 20px;
    border-radius: var(--r-pill); border: var(--bw) solid var(--ctl-line); display: grid; place-items: center;
    font-size: var(--fs-label); font-weight: var(--fw-semi); color: var(--text-muted); font-variant-numeric: tabular-nums; }
  /* the row's text starts on the number's centre line; its controls follow in the text column */
  .steps > :global(li > *) { grid-column: 2; min-width: 0; }
  .steps > :global(li > :first-child) { padding-top: 1px; }
</style>
