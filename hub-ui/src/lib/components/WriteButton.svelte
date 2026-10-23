<script lang="ts">
  // A Button for anything that changes files: disabled with the reason while a change runs or the terminal
  // holds the library.
  import type { ComponentProps } from 'svelte';
  import Button from './Button.svelte';
  import { writeBlockedReason, writeBusy } from '../stores/hub';

  let { disabled = false, title, busy = false, ...rest }: ComponentProps<typeof Button> = $props();
  // its own busy job keeps the spinner; other jobs only disable it
  const blocked = $derived($writeBusy && !busy);
</script>

<Button {...rest} {busy} disabled={disabled || blocked} title={blocked ? ($writeBlockedReason ?? title) : title} />
