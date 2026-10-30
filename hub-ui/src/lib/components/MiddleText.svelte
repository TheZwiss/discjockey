<script lang="ts">
  // A name on one line that gives way in its middle when the column is narrower than it, so its end stays readable
  // (file names: "Artist - Title (… EDIT)(1).wav" against "Artist - Title (… EDIT).wav"); whole while it fits. The full
  // text is the tooltip. For names whose end tells them apart; a plain name that may end in "…" stays a ListRow's own.
  // `sep` (a place's "›"): the text is a row of folders, so whole folders between the first and the last give way first
  // ("Rekordbox Library › … › 2019"), then characters; the separators are in the quiet grey, the folders in the text's
  // own colour (no part of a name is greyed).
  import { fitMiddleAction } from './fitPathAction';

  let { text, sep }: { text: string; sep?: string } = $props();
</script>

<span class="mid" title={text} use:fitMiddleAction={{ text, sep }}></span>

<style>
  .mid { display: block; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .mid :global(.sep) { color: var(--text-label); }
</style>
