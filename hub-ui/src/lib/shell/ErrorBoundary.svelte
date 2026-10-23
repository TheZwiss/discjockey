<script lang="ts">
  import type { Snippet } from 'svelte';
  import Button from '../components/Button.svelte';
  let { children }: { children: Snippet } = $props();
  function report(err: unknown) {
    // never shown in the window; the developer console only
    if (import.meta.env.DEV) console.warn('screen failed', err);
  }
</script>

<svelte:boundary onerror={report}>
  {@render children()}
  {#snippet failed(_error, reset)}
    <div class="failed" role="alert">
      <p>Something went wrong on this screen.</p>
      <Button onclick={reset}>Reload</Button>
    </div>
  {/snippet}
</svelte:boundary>

<style>
  .failed { margin: var(--s-8) auto; display: flex; flex-direction: column; align-items: center; gap: var(--s-3); color: var(--text-muted); }
</style>
