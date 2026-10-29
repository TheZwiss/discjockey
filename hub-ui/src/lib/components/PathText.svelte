<script lang="ts">
  // A file or folder path that wraps: it breaks only after a "/" (or after a drive's "›"), never inside a folder's or
  // file's name; a piece wider than the box breaks inside itself as the last resort. `lead` (an arrow) is part of the
  // first piece, so it is never left alone at the end of a line. The text is the path itself (<wbr> adds no character),
  // so selecting and copying it gives the real path. For a path that may take several lines; one line uses
  // `fitPathAction` / `MiddleText`.
  import { pathSegments } from './pathBreak';

  let { path, lead = '' }: { path: string; lead?: string } = $props();
  const parts = $derived(pathSegments(path));
</script>

<span class="pt">{#each parts as part, i (i)}<span class="seg">{i === 0 ? lead : ''}{part}</span><wbr />{/each}</span>

<style>
  .pt { user-select: text; -webkit-user-select: text; }
  .seg { display: inline-block; max-width: 100%; vertical-align: top; overflow-wrap: anywhere; }
</style>
