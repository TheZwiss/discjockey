<script lang="ts">
  // Setup's foot (ColumnFrame `foot`): Back · the reason Continue is off · Continue. Continue is the screen's one
  // filled button once its step is done; before that it is off, and the step's own main action (Connect, Qobuz's
  // Sign in, Check again) is the filled one. On the last step the same button reads Finish.
  import { Button, Hint } from '$lib/components';
  let { onback = null, backOff = false, why = null, allowed, oncontinue, label = 'Continue' }: {
    onback?: (() => void) | null; backOff?: boolean; why?: string | null; allowed: boolean; oncontinue: () => void;
    /** Continue, or Finish on the last step */
    label?: string;
  } = $props();
</script>

{#if onback}<Button onclick={onback} disabled={backOff} data-test="back">Back</Button>{/if}
<span class="why">{#if why}<Hint text={why} data-test="next-why" />{/if}</span>
<Button variant={allowed ? 'filled' : 'secondary'} disabled={!allowed} title={why ?? undefined} onclick={oncontinue}
  data-test="next">{label}</Button>

<style>
  /* the reason sits right beside the button it explains (one line, ends in "…" when long) */
  .why { flex: 1; min-width: 0; display: flex; justify-content: flex-end; }
</style>
