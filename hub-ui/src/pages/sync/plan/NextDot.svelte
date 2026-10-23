<script lang="ts">
  // The yellow "next sync" dot (spec §4: yellow means waiting or limited), 6 px: one block for the why column (Why)
  // and the plan rows' narrow mark, so both draw the same dot. Other attributes (`data-test`) go onto the dot.
  import type { HTMLAttributes } from 'svelte/elements';
  let { class: className, ...rest }: Omit<HTMLAttributes<HTMLSpanElement>, 'children'> = $props();
</script>

<span {...rest} class="next-dot {className ?? ''}" aria-hidden="true"></span>

<style>
  .next-dot { flex: none; display: block; width: 6px; height: 6px; border-radius: 50%; background: var(--q-good); }
</style>
