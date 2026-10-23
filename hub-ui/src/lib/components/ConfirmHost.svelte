<script lang="ts">
  import Dialog from './Dialog.svelte';
  import Button from './Button.svelte';
  import { answerConfirm, confirmRequest } from './confirm';
  let open = $state(false);
  $effect(() => { open = !!$confirmRequest; });
</script>

{#if $confirmRequest}
  {@const c = $confirmRequest}
  <Dialog bind:open title={c.title} onclose={() => answerConfirm(false)}>
    {#if c.body}<p class="body">{c.body}</p>{/if}
    {#snippet footer()}
      <Button variant="secondary" onclick={() => answerConfirm(false)}>{c.cancelLabel ?? 'Cancel'}</Button>
      <Button variant={c.tone === 'danger' ? 'danger' : 'primary'} onclick={() => answerConfirm(true)} data-autofocus>
        {c.confirmLabel ?? 'OK'}</Button>
    {/snippet}
  </Dialog>
{/if}

<style>
  .body { color: var(--text-muted); }
</style>
