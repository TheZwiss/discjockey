<script lang="ts">
  import { toasts } from '../stores/toasts';
  import Toast from '../components/Toast.svelte';
</script>

<div class="host" aria-live="polite">
  {#each $toasts as t (t.id)}<Toast toast={t} onclose={() => toasts.dismiss(t.id)} />{/each}
</div>

<style>
  .host { position: absolute; left: var(--s-4); bottom: var(--s-4);   /* main area, bottom left: right-panel footers stay free */
    display: flex; flex-direction: column; gap: var(--s-2);
    z-index: 20; pointer-events: none; }
  .host :global(> *) { pointer-events: auto; }
</style>
