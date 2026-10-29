<script lang="ts">
  // A name on one line that gives way in its middle when the column is narrower than it, so its end stays readable
  // (file names: "Artist - Title (… EDIT)(1).wav" against "Artist - Title (… EDIT).wav"); whole while it fits. The full
  // text is the tooltip. For names whose end tells them apart; a plain name that may end in "…" stays a ListRow's own.
  import { fitMiddleAction } from './fitPathAction';

  let { text }: { text: string } = $props();
</script>

<span class="mid" title={text} use:fitMiddleAction={text}></span>

<style>
  .mid { display: block; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
